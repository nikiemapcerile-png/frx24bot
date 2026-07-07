"""
collector.py — Collecteur automatique de matchs FIFA Virtuel
Tourne en arrière-plan et enregistre chaque match terminé dans la DB
"""
import asyncio
import logging
import requests
from database import save_match

logger = logging.getLogger(__name__)

BASE_URL   = "https://1xbet.com"
PARTNER_ID = 36
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Android 13; Mobile) AppleWebKit/537.36",
    "Accept": "application/json",
}
FIFA_KEYWORDS = ["italy","serie","champions","fc 25","fc 26","fifa","esport","virtual"]
_seen_finished = set()

def _get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug(f"collector: {e}")
        return None

def _fetch_live():
    url = (f"{BASE_URL}/service-api/LiveFeed/Get1x2_VZip"
           f"?sports=40&count=100&lng=fr&gr=666&mode=4"
           f"&country=0&partner={PARTNER_ID}&getEmpty=true"
           f"&virtualSports=true&noFilterBlockEvent=true")
    data = _get(url)
    if not data or "Value" not in data:
        return []
    result = []
    for m in data["Value"]:
        league = m.get("L","")
        if not any(k in league.lower() for k in FIFA_KEYWORDS):
            continue
        sc = m.get("SC", {}) or {}
        fs = sc.get("FS","0:0") or "0:0"
        s1 = sc.get("S1","0:0") or "0:0"
        parts_fs = fs.split(":")
        parts_s1 = s1.split(":")
        result.append({
            "id":       str(m["I"]),
            "league":   league,
            "team1":    m.get("O1",""),
            "team2":    m.get("O2",""),
            "score1":   int(parts_fs[0]) if parts_fs[0].isdigit() else 0,
            "score2":   int(parts_fs[1]) if len(parts_fs)>1 and parts_fs[1].isdigit() else 0,
            "score1_ht":int(parts_s1[0]) if parts_s1[0].isdigit() else 0,
            "score2_ht":int(parts_s1[1]) if len(parts_s1)>1 and parts_s1[1].isdigit() else 0,
            "status":   sc.get("I", 0),
        })
    return result

def _collect_once():
    saved = 0
    for m in _fetch_live():
        try:
            finished = int(m["status"]) in [4,5,6]
            mid = m["id"]
            if finished and mid not in _seen_finished:
                save_match(mid, m["league"], m["team1"], m["team2"],
                           m["score1"], m["score2"],
                           m["score1_ht"], m["score2_ht"], finished=True)
                _seen_finished.add(mid)
                saved += 1
                logger.info(f"✅ {m['team1']} {m['score1']}-{m['score2']} {m['team2']}")
            elif not finished:
                save_match(mid, m["league"], m["team1"], m["team2"],
                           m["score1"], m["score2"], finished=False)
        except Exception as e:
            logger.debug(f"skip {m.get('id')}: {e}")
    return saved

async def start_collector():
    logger.info("🔄 Collecteur démarré — vérification toutes les 60s")
    while True:
        try:
            saved = _collect_once()
            if saved:
                logger.info(f"📦 {saved} match(s) enregistré(s)")
        except Exception as e:
            logger.error(f"Collecteur: {e}")
        await asyncio.sleep(60)
