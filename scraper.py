"""
scraper.py — Récupération automatique des cotes depuis 1xBet
"""
import requests
import logging
from database import save_match, get_h2h, get_team_stats, compute_team_stats

logger = logging.getLogger(__name__)
BASE_URL   = "https://1xbet.com"
PARTNER_ID = 36
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Android 13; Mobile) AppleWebKit/537.36",
    "Accept": "application/json",
}
FIFA_KEYWORDS = ["italy","serie","champions","fc 25","fc 26","fifa","esport","virtual"]

def _get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"API: {e}")
        return None

def get_fifa_matches():
    url = (f"{BASE_URL}/service-api/LiveFeed/Get1x2_VZip"
           f"?sports=40&count=100&lng=fr&gr=666&mode=4"
           f"&country=0&partner={PARTNER_ID}&getEmpty=true"
           f"&virtualSports=true&noFilterBlockEvent=true")
    data = _get(url)
    if not data or "Value" not in data:
        return []
    matches = []
    for m in data["Value"]:
        league = m.get("L","")
        if not any(k in league.lower() for k in FIFA_KEYWORDS):
            continue
        matches.append({
            "id":     str(m["I"]),
            "league": league,
            "team1":  m.get("O1","Équipe 1"),
            "team2":  m.get("O2","Équipe 2"),
            "status": m.get("SC",{}).get("I",0) if m.get("SC") else 0,
        })
    return matches

def get_match_full_data(match_id):
    url = (f"{BASE_URL}/service-api/LiveFeed/GetGameZip"
           f"?id={match_id}&lng=fr&cfview=0&isSubGames=true"
           f"&GroupEvents=true&allEventsGroupSubGames=true"
           f"&countevents=250&partner={PARTNER_ID}")
    data = _get(url)
    if not data or "Value" not in data:
        return None
    game   = data["Value"]
    team1  = game.get("O1","Équipe 1")
    team2  = game.get("O2","Équipe 2")
    league = game.get("L","")

    save_match(str(match_id), league, team1, team2)

    odds = {"team1":team1,"team2":team2,"league":league,"h2h":[]}

    for group in game.get("GE",[]):
        for event_group in group.get("E",[]):
            for event in event_group:
                _parse_event(event, odds, team1, team2)

    _finalize_odds(odds)

    h2h_rows = get_h2h(team1, team2, limit=5)
    odds["h2h"] = []
    odds["h2h_detail"] = []
    for r in h2h_rows:
        if r["team1"] == team1:
            odds["h2h"].append((r["score1"], r["score2"]))
        else:
            odds["h2h"].append((r["score2"], r["score1"]))
        odds["h2h_detail"].append(r)

    rows1 = get_team_stats(team1, league, limit=20)
    rows2 = get_team_stats(team2, league, limit=20)
    odds["stats_team1"] = compute_team_stats(team1, rows1)
    odds["stats_team2"] = compute_team_stats(team2, rows2)

    return odds

def _parse_event(event, odds, team1, team2):
    name = event.get("N","").lower()
    coef = float(event.get("C",0) or 0)
    if coef <= 1.0:
        return

    t1 = team1.lower()[:6]
    t2 = team2.lower()[:6]
    is_ht = any(x in name for x in ["mi-temps","1ère mt","1st half","halftime","ht ","mt "])

    # 1X2
    for kw,field in [("victoire 1","w1"),("win 1","w1"),("équipe 1","w1"),
                     ("match nul","x"),("draw","x"),("nul","x"),
                     ("victoire 2","w2"),("win 2","w2"),("équipe 2","w2")]:
        if kw in name:
            scope = "1x2_mt" if is_ht else "1x2_full"
            odds.setdefault(scope,{})[field] = coef

    # BTTS
    if any(x in name for x in ["les deux équipes","both teams","btts"]):
        scope = "btts_mt" if is_ht else "btts_full"
        if any(x in name for x in ["oui","yes"]): odds.setdefault(scope,{})["yes"] = coef
        elif any(x in name for x in ["non","no"]): odds.setdefault(scope,{})["no"] = coef

    # BTTS 2+
    if any(x in name for x in ["chaque équipe marque 2","each team 2","2 ou plus"]):
        scope = "btts2_mt" if is_ht else "btts2_full"
        if any(x in name for x in ["oui","yes"]): odds.setdefault(scope,{})["yes"] = coef
        elif any(x in name for x in ["non","no"]): odds.setdefault(scope,{})["no"] = coef

    # Totaux
    for val, kf, km in [
        (0.5,"total_05","mt_total_05"),(1.5,"total_15","mt_total_15"),
        (2.5,"total_25","mt_total_25"),(3.5,"total_35","mt_total_35"),
        (4.5,"total_45",None),
    ]:
        marker = str(val)
        if marker in name and t1 not in name and t2 not in name:
            key = (km if is_ht and km else kf)
            if key:
                if any(x in name for x in ["over","plus","tb"]):
                    v = odds.setdefault(key,[None,None]); v[0] = coef
                elif any(x in name for x in ["under","moins","tm"]):
                    v = odds.setdefault(key,[None,None]); v[1] = coef

    # Total1 / Total2
    for val, k1f, k1m, k2f, k2m in [
        (0.5,"total1_05","mt_total1_05","total2_05","mt_total2_05"),
        (1.5,"total1_15","mt_total1_15","total2_15","mt_total2_15"),
        (2.5,"total1_25",None,"total2_25",None),
    ]:
        marker = str(val)
        if marker in name:
            if t1 in name:
                key = (k1m if is_ht and k1m else k1f)
                if any(x in name for x in ["over","plus","tb"]):
                    v = odds.setdefault(key,[None,None]); v[0] = coef
                elif any(x in name for x in ["under","moins","tm"]):
                    v = odds.setdefault(key,[None,None]); v[1] = coef
            elif t2 in name:
                key = (k2m if is_ht and k2m else k2f)
                if any(x in name for x in ["over","plus","tb"]):
                    v = odds.setdefault(key,[None,None]); v[0] = coef
                elif any(x in name for x in ["under","moins","tm"]):
                    v = odds.setdefault(key,[None,None]); v[1] = coef

def _finalize_odds(odds):
    keys = [
        "total_05","total_15","total_25","total_35","total_45",
        "mt_total_05","mt_total_15","mt_total_25","mt_total_35",
        "total1_05","total1_15","total1_25",
        "total2_05","total2_15","total2_25",
        "mt_total1_05","mt_total1_15","mt_total2_05","mt_total2_15",
    ]
    for k in keys:
        if k in odds and isinstance(odds[k], list):
            if odds[k][0] and odds[k][1]:
                odds[k] = tuple(odds[k])
            else:
                del odds[k]
