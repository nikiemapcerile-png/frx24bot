"""
predictor.py — Moteur de prédiction adapté aux réalités FIFA Virtuel
- Serie A (FC25) : ~2.5 buts/match, 0-0 possible, MT souvent 0-0
- Champions League FC26 : ~3.5 buts/match, gros scores fréquents
"""
import math
from itertools import product


# ══════════════════════════════════════════════════════════
#  PROFILS PAR CHAMPIONNAT
# ══════════════════════════════════════════════════════════

LEAGUE_PROFILES = {
    "serie_a": {
        "lam_min":       0.3,    # lambda minimum par équipe
        "lam_max":       3.5,    # lambda maximum par équipe
        "lam_total_ref": 2.5,    # buts attendus par match si pas de cotes
        "btts_base":     0.45,   # probabilité BTTS de base
        "zero_zero":     0.06,   # probabilité 0-0 de base (existe en Serie A)
        "mt_lam_ratio":  0.30,   # ratio buts 1ère MT vs match complet (MT souvent 0-0)
        "mt_zero_boost": 1.8,    # multiplicateur proba 0-0 MT (très fréquent)
        "high_score":    False,  # gros scores rares
    },
    "champions": {
        "lam_min":       0.5,
        "lam_max":       5.0,
        "lam_total_ref": 3.5,
        "btts_base":     0.55,
        "zero_zero":     0.03,   # 0-0 rare en Champions FC26
        "mt_lam_ratio":  0.40,   # plus de buts en 1ère MT
        "mt_zero_boost": 1.2,    # 0-0 MT moins boosté
        "high_score":    True,   # gros scores fréquents
    }
}

def get_profile(league: str) -> dict:
    if "serie" in league.lower() or "italy" in league.lower() or "fc 25" in league.lower():
        return LEAGUE_PROFILES["serie_a"], "serie_a"
    else:
        return LEAGUE_PROFILES["champions"], "champions"


# ══════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════

def odd_to_prob(odd):
    return 1.0 / odd if odd > 1.0 else 0.0

def normalize2(a, b):
    t = a + b
    return (a/t, b/t) if t else (0.5, 0.5)

def normalize3(a, b, c):
    t = a + b + c
    return (a/t, b/t, c/t) if t else (1/3, 1/3, 1/3)

def poisson_pmf(k, lam):
    if lam <= 0: return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)

def poisson_cdf(k_max, lam):
    return sum(poisson_pmf(i, lam) for i in range(k_max + 1))

def estimate_lambda(over_probs: dict) -> float:
    if not over_probs: return 1.5
    thresholds = sorted(over_probs.keys())
    best_lam, best_err = 1.5, float("inf")
    for lam_x10 in range(1, 121):
        lam = lam_x10 / 10.0
        err = sum((1 - poisson_cdf(int(t), lam) - over_probs[t])**2 for t in thresholds)
        if err < best_err:
            best_err, best_lam = err, lam
    return best_lam

def lambda_from_team_totals(d, keys):
    over_probs = {}
    for key, threshold in keys:
        if key in d:
            po, _ = normalize2(odd_to_prob(d[key][0]), odd_to_prob(d[key][1]))
            over_probs[threshold] = po
    return estimate_lambda(over_probs) if over_probs else None

def h2h_lambdas(h2h):
    weights = [5, 4, 3, 2, 1]
    sw = sum(weights[:len(h2h)])
    if sw == 0: return 1.5, 1.5
    l1 = sum(w*s1 for (s1,_),w in zip(h2h, weights)) / sw
    l2 = sum(w*s2 for (_,s2),w in zip(h2h, weights)) / sw
    return l1, l2


# ══════════════════════════════════════════════════════════
#  MATRICE DE SCORES ADAPTÉE
# ══════════════════════════════════════════════════════════

def score_matrix_adapted(lam1, lam2, profile, scope="full", max_g=8):
    """
    Génère la matrice de probabilités adaptée au profil du championnat.
    Ajuste la probabilité 0-0 selon le profil.
    """
    mat = {}
    for g1, g2 in product(range(max_g+1), repeat=2):
        p = poisson_pmf(g1, lam1) * poisson_pmf(g2, lam2)
        mat[(g1, g2)] = p

    # Ajustement 0-0 selon profil
    if scope == "mt":
        boost = profile["mt_zero_boost"]
    else:
        # En match complet : légère réduction si profil champions (0-0 rare)
        boost = 0.5 if profile.get("zero_zero", 0.05) < 0.04 else 1.0

    if (0,0) in mat:
        mat[(0,0)] = mat[(0,0)] * boost

    # Normalisation
    total = sum(mat.values())
    if total: mat = {k: v/total for k,v in mat.items()}
    return dict(sorted(mat.items(), key=lambda x: x[1], reverse=True))


# ══════════════════════════════════════════════════════════
#  CLASSE PRINCIPALE
# ══════════════════════════════════════════════════════════

class ScorePredictor:
    def __init__(self, data: dict):
        self.d      = data
        self.team1  = data["team1"]
        self.team2  = data["team2"]
        self.league = data.get("league", "")
        self.h2h    = data.get("h2h", [])
        self.profile, self.profile_key = get_profile(self.league)

    def _over_probs(self, keys_map):
        result = {}
        for key, threshold in keys_map:
            if key in self.d:
                po, _ = normalize2(odd_to_prob(self.d[key][0]), odd_to_prob(self.d[key][1]))
                result[threshold] = po
        return result

    def _compute_lambdas(self, scope="full"):
        d = self.d
        profile = self.profile

        if scope == "full":
            total_keys = [("total_05",0.5),("total_15",1.5),("total_25",2.5),
                          ("total_35",3.5),("total_45",4.5)]
            team1_keys = [("total1_05",0.5),("total1_15",1.5),("total1_25",2.5)]
            team2_keys = [("total2_05",0.5),("total2_15",1.5),("total2_25",2.5)]
            x2_key, btts_key = "1x2_full", "btts_full"
            mt_div = 1.0
        else:
            total_keys = [("mt_total_05",0.5),("mt_total_15",1.5),
                          ("mt_total_25",2.5),("mt_total_35",3.5)]
            team1_keys = [("mt_total1_05",0.5),("mt_total1_15",1.5)]
            team2_keys = [("mt_total2_05",0.5),("mt_total2_15",1.5)]
            x2_key, btts_key = "1x2_mt", "btts_mt"
            mt_div = 1.0 / profile["mt_lam_ratio"]  # ratio MT spécifique au profil

        # 1. Lambda global depuis cotes
        lam_total = estimate_lambda(self._over_probs(total_keys))

        # Si pas de cotes fiables, utiliser le référentiel du championnat
        if lam_total < 0.5:
            lam_total = profile["lam_total_ref"] if scope == "full" else \
                        profile["lam_total_ref"] * profile["mt_lam_ratio"]

        # 2. Lambda par équipe
        lam1_team = lambda_from_team_totals(d, team1_keys)
        lam2_team = lambda_from_team_totals(d, team2_keys)

        # 3. Lambda H2H
        lam1_h2h, lam2_h2h = h2h_lambdas(self.h2h)
        if scope == "mt":
            lam1_h2h *= profile["mt_lam_ratio"]
            lam2_h2h *= profile["mt_lam_ratio"]

        # 4. Ratio offensif depuis 1X2
        lam1_ratio, lam2_ratio = 0.55, 0.45
        if x2_key in d:
            x = d[x2_key]
            p1, px, p2 = normalize3(
                odd_to_prob(x["w1"]), odd_to_prob(x["x"]), odd_to_prob(x["w2"])
            )
            s1 = p1 + 0.5*px; s2 = p2 + 0.5*px
            t = s1 + s2
            lam1_ratio, lam2_ratio = s1/t, s2/t

        # 5. Fusion
        if lam1_team and lam2_team:
            lam1 = 0.40*lam1_team + 0.30*lam1_h2h + 0.30*(lam_total*lam1_ratio)
            lam2 = 0.40*lam2_team + 0.30*lam2_h2h + 0.30*(lam_total*lam2_ratio)
        else:
            lam1 = 0.50*(lam_total*lam1_ratio) + 0.50*lam1_h2h
            lam2 = 0.50*(lam_total*lam2_ratio) + 0.50*lam2_h2h

        # 6. Ajustement BTTS
        if btts_key in d:
            p_btts, _ = normalize2(
                odd_to_prob(d[btts_key]["yes"]), odd_to_prob(d[btts_key]["no"])
            )
            if p_btts > 0.65:
                lam1 = max(lam1, profile["lam_min"] + 0.3)
                lam2 = max(lam2, profile["lam_min"] + 0.3)

        # 7. Contraintes profil
        lam1 = max(profile["lam_min"], min(profile["lam_max"], lam1))
        lam2 = max(profile["lam_min"], min(profile["lam_max"], lam2))

        return round(lam1, 3), round(lam2, 3)

    def _safe_bets(self, mat, lam1, lam2, scope="full"):
        d = self.d
        bets = []

        def add(label, prob, cote=None):
            bets.append({"label": label, "prob": prob, "cote": cote})

        sfx = "" if scope == "full" else " MT"

        # Over/Under total
        thresholds = [
            (0.5,"total_05"),(1.5,"total_15"),(2.5,"total_25"),
            (3.5,"total_35"),(4.5,"total_45")
        ] if scope == "full" else [
            (0.5,"mt_total_05"),(1.5,"mt_total_15"),
            (2.5,"mt_total_25"),(3.5,"mt_total_35")
        ]
        for t, key in thresholds:
            p_over  = sum(p for (g1,g2),p in mat.items() if g1+g2 > t)
            p_under = 1 - p_over
            co = d[key][0] if key in d else None
            cu = d[key][1] if key in d else None
            add(f"Over {t}{sfx}",  p_over,  co)
            add(f"Under {t}{sfx}", p_under, cu)

        # Total1
        t1_keys = [(0.5,"total1_05"),(1.5,"total1_15"),(2.5,"total1_25")] if scope=="full" \
                  else [(0.5,"mt_total1_05"),(1.5,"mt_total1_15")]
        for t, key in t1_keys:
            
            p_over  = sum(p for (g1,_),p in mat.items() if g1 > t)
            p_under = 1 - p_over
            co = d[key][0] if key in d else None
            cu = d[key][1] if key in d else None
            add(f"{self.team1} Over {t}{sfx}",  p_over,  co)
            add(f"{self.team1} Under {t}{sfx}", p_under, cu)

        # Total2
        t2_keys = [(0.5,"total2_05"),(1.5,"total2_15"),(2.5,"total2_25")] if scope=="full" \
                  else [(0.5,"mt_total2_05"),(1.5,"mt_total2_15")]
        for t, key in t2_keys:
            
            p_over  = sum(p for (_,g2),p in mat.items() if g2 > t)
            p_under = 1 - p_over
            co = d[key][0] if key in d else None
            cu = d[key][1] if key in d else None
            add(f"{self.team2} Over {t}{sfx}",  p_over,  co)
            add(f"{self.team2} Under {t}{sfx}", p_under, cu)

        # BTTS
        btts_key  = "btts_full"  if scope=="full" else "btts_mt"
        btts2_key = "btts2_full" if scope=="full" else "btts2_mt"
        p_yes = sum(p for (g1,g2),p in mat.items() if g1>0 and g2>0)
        p_no  = 1 - p_yes
        add(f"BTTS Oui{sfx}", p_yes, d[btts_key]["yes"] if btts_key in d else None)
        add(f"BTTS Non{sfx}", p_no,  d[btts_key]["no"]  if btts_key in d else None)
        p2_yes = sum(p for (g1,g2),p in mat.items() if g1>=2 and g2>=2)
        add(f"Chaque équipe 2+{sfx} Oui", p2_yes, d[btts2_key]["yes"] if btts2_key in d else None)
        add(f"Chaque équipe 2+{sfx} Non", 1-p2_yes, d[btts2_key]["no"] if btts2_key in d else None)

        # 1X2
        x2_key = "1x2_full" if scope=="full" else "1x2_mt"
        if x2_key in d:
            x  = d[x2_key]
            p1 = sum(p for (g1,g2),p in mat.items() if g1>g2)
            px = sum(p for (g1,g2),p in mat.items() if g1==g2)
            p2 = sum(p for (g1,g2),p in mat.items() if g2>g1)
            add(f"Victoire {self.team1}{sfx}", p1, x["w1"])
            add(f"Match Nul{sfx}",             px, x["x"])
            add(f"Victoire {self.team2}{sfx}", p2, x["w2"])

        # Score exact
        for (g1,g2), prob in list(mat.items())[:15]:
            add(f"Score exact {g1}-{g2}{sfx}", prob, None)

        # Filtrage par seuils
        levels = {}
        for b in bets:
            p = b["prob"]
            if p >= 0.75:
                lvl = "🔴 85%" if p >= 0.85 else ("🟠 80%" if p >= 0.80 else "🟡 75%")
                levels.setdefault(lvl, []).append(b)
        return levels

    def _favori(self, scope="full"):
        key = "1x2_full" if scope=="full" else "1x2_mt"
        if key not in self.d: return ""
        x = self.d[key]
        p1,px,p2 = normalize3(odd_to_prob(x["w1"]),odd_to_prob(x["x"]),odd_to_prob(x["w2"]))
        best = max([(p1,f"🏠 {self.team1}",x["w1"]),(px,"🤝 Match Nul",x["x"]),(p2,f"✈️ {self.team2}",x["w2"])],key=lambda t:t[0])
        return f"⭐ *Favori :* {best[1]}  `{best[2]}`  _(prob. {best[0]*100:.0f}%)_"

    @staticmethod
    def _rank(i): return ["🥇","🥈","🥉","4️⃣","5️⃣"][i]

    def _format_scores(self, matrix, title, lam1, lam2):
        top5 = list(matrix.items())[:5]
        lines = [f"*{title}*", ""]
        for i,((g1,g2),prob) in enumerate(top5):
            bar = "█" * int(prob*40)
            lines.append(f"{self._rank(i)} *{g1}-{g2}*  {prob*100:.1f}%  {bar}")
        lines += ["",
            f"📈 λ {self.team1}: `{lam1}` | λ {self.team2}: `{lam2}`",
            f"⚽ Over 2.5 : `{sum(p for (g1,g2),p in matrix.items() if g1+g2>2.5)*100:.1f}%`",
            f"🤝 BTTS    : `{sum(p for (g1,g2),p in matrix.items() if g1>0 and g2>0)*100:.1f}%`",
            f"🏠 {self.team1} : `{sum(p for (g1,g2),p in matrix.items() if g1>g2)*100:.1f}%`",
            f"🤝 Nul      : `{sum(p for (g1,g2),p in matrix.items() if g1==g2)*100:.1f}%`",
            f"✈️ {self.team2} : `{sum(p for (g1,g2),p in matrix.items() if g2>g1)*100:.1f}%`",
        ]
        return "\n".join(lines)

    def _format_h2h(self):
        lines = ["📋 *5 Derniers H2H (plus récent en 1er)*", ""]
        for i,(s1,s2) in enumerate(self.h2h, 1):
            lines.append(f"{i}. {self.team1} *{s1}-{s2}* {self.team2}")
        return "\n".join(lines)

    def _format_safe_bets(self, levels_full, levels_mt):
        sep = "━━━━━━━━━━━━━━━━━━━━━"
        lines = [sep, "🔒 *PARIS SÛRS RECOMMANDÉS*", sep, ""]
        order  = ["🔴 85%", "🟠 80%", "🟡 75%"]
        medals = {"🔴 85%":"🔴","🟠 80%":"🟠","🟡 75%":"🟡"}
        labels = {"🔴 85%":"Très sûr (≥85%)","🟠 80%":"Sûr (≥80%)","🟡 75%":"Probable (≥75%)"}

        all_levels = {}
        for lvl in order:
            bets_all = []
            if lvl in levels_full: bets_all += [(b,"🏁") for b in levels_full[lvl]]
            if lvl in levels_mt:   bets_all += [(b,"🕐") for b in levels_mt[lvl]]
            if bets_all: all_levels[lvl] = bets_all

        if not all_levels:
            lines.append("⚠️ _Aucun pari ne dépasse 75% pour ce match._")
            return "\n".join(lines)

        for lvl in order:
            if lvl not in all_levels: continue
            lines.append(f"{medals[lvl]} *{labels[lvl]}*\n")
            seen = set()
            for b, icon in all_levels[lvl]:
                if b["label"] in seen: continue
                seen.add(b["label"])
                cote_str = f"  _(cote `{b['cote']}`)_" if b["cote"] else ""
                lines.append(f"  {icon} {b['label']} → *{b['prob']*100:.1f}%*{cote_str}")
            lines.append("")

        lines.append("_🏁 = Temps réglementaire  |  🕐 = Mi-temps_")
        return "\n".join(lines)

    def predict(self) -> str:
        lam1_mt,   lam2_mt   = self._compute_lambdas(scope="mt")
        lam1_full, lam2_full = self._compute_lambdas(scope="full")

        mat_mt   = score_matrix_adapted(lam1_mt,   lam2_mt,   self.profile, scope="mt")
        mat_full = score_matrix_adapted(lam1_full, lam2_full, self.profile, scope="full")

        levels_full = self._safe_bets(mat_full, lam1_full, lam2_full, scope="full")
        levels_mt   = self._safe_bets(mat_mt,   lam1_mt,   lam2_mt,   scope="mt")

        fav_full = self._favori(scope="full")
        fav_mt   = self._favori(scope="mt")

        # Badge championnat
        if self.profile_key == "serie_a":
            badge = "🇮🇹 _Profil : Serie A Virtuel FC25 — buts modérés, MT souvent 0-0_"
        else:
            badge = "🏆 _Profil : Champions League FC26 — scores élevés, gros écarts fréquents_"

        sep = "━━━━━━━━━━━━━━━━━━━━━"
        return (
            f"⚽ *ANALYSE : {self.team1} vs {self.team2}*\n"
            f"🏆 {self.league}\n"
            f"{badge}\n"
            f"{sep}\n\n"
            f"{fav_mt}\n\n"
            f"{self._format_scores(mat_mt,  '🕐 PRÉDICTION 1ÈRE MI-TEMPS', lam1_mt,   lam2_mt)}\n\n"
            f"{sep}\n\n"
            f"{fav_full}\n\n"
            f"{self._format_scores(mat_full,'🏁 PRÉDICTION SCORE FINAL',   lam1_full, lam2_full)}\n\n"
            f"{self._format_safe_bets(levels_full, levels_mt)}\n\n"
            f"{sep}\n"
            f"⚠️ _Prédictions basées sur Poisson adapté aux réalités FIFA Virtuel.\nAucune garantie de résultat._"
        )
