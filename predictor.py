"""
predictor.py — Moteur de prédiction complet
Scores exacts + Paris sûrs (75% / 80% / 85%)
"""
import math
from itertools import product


# ══════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════

def odd_to_prob(odd: float) -> float:
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
#  CLASSE PRINCIPALE
# ══════════════════════════════════════════════════════════

class ScorePredictor:
    def __init__(self, data: dict):
        self.d     = data
        self.team1 = data["team1"]
        self.team2 = data["team2"]
        self.league= data.get("league", "")
        self.h2h   = data.get("h2h", [])

    # ── Probabilités Over depuis les cotes ──────────────────
    def _over_probs(self, keys_map):
        result = {}
        for key, threshold in keys_map:
            if key in self.d:
                po, _ = normalize2(odd_to_prob(self.d[key][0]), odd_to_prob(self.d[key][1]))
                result[threshold] = po
        return result

    # ── Calcul des lambdas ──────────────────────────────────
    def _compute_lambdas(self, scope="full"):
        d = self.d
        if scope == "full":
            total_keys  = [("total_05",0.5),("total_15",1.5),("total_25",2.5),("total_35",3.5),("total_45",4.5)]
            team1_keys  = [("total1_05",0.5),("total1_15",1.5),("total1_25",2.5)]
            team2_keys  = [("total2_05",0.5),("total2_15",1.5),("total2_25",2.5)]
            x2_key, btts_key = "1x2_full", "btts_full"
            mt_div = 1.0
        else:
            total_keys  = [("mt_total_05",0.5),("mt_total_15",1.5),("mt_total_25",2.5),("mt_total_35",3.5)]
            team1_keys  = [("mt_total1_05",0.5),("mt_total1_15",1.5)]
            team2_keys  = [("mt_total2_05",0.5),("mt_total2_15",1.5)]
            x2_key, btts_key = "1x2_mt", "btts_mt"
            mt_div = 2.0

        lam_total  = estimate_lambda(self._over_probs(total_keys))
        lam1_team  = lambda_from_team_totals(d, team1_keys)
        lam2_team  = lambda_from_team_totals(d, team2_keys)
        lam1_h2h, lam2_h2h = h2h_lambdas(self.h2h)
        lam1_h2h /= mt_div
        lam2_h2h /= mt_div

        # Ratio offensif depuis 1X2
        lam1_ratio, lam2_ratio = 0.55, 0.45
        if x2_key in d:
            x = d[x2_key]
            p1, px, p2 = normalize3(odd_to_prob(x["w1"]), odd_to_prob(x["x"]), odd_to_prob(x["w2"]))
            s1 = p1 + 0.5*px; s2 = p2 + 0.5*px
            t  = s1 + s2
            lam1_ratio, lam2_ratio = s1/t, s2/t

        if lam1_team and lam2_team:
            lam1 = 0.40*lam1_team + 0.30*lam1_h2h + 0.30*(lam_total*lam1_ratio)
            lam2 = 0.40*lam2_team + 0.30*lam2_h2h + 0.30*(lam_total*lam2_ratio)
        else:
            lam1 = 0.50*(lam_total*lam1_ratio) + 0.50*lam1_h2h
            lam2 = 0.50*(lam_total*lam2_ratio) + 0.50*lam2_h2h

        if btts_key in d:
            p_btts, _ = normalize2(odd_to_prob(d[btts_key]["yes"]), odd_to_prob(d[btts_key]["no"]))
            if p_btts > 0.65:
                lam1 = max(lam1, 0.6)
                lam2 = max(lam2, 0.6)

        return round(max(lam1, 0.05), 3), round(max(lam2, 0.05), 3)

    # ── Matrice des scores ──────────────────────────────────
    def _score_matrix(self, lam1, lam2, max_g=8):
        mat = {(g1,g2): poisson_pmf(g1,lam1)*poisson_pmf(g2,lam2)
               for g1,g2 in product(range(max_g+1), repeat=2)}
        total = sum(mat.values())
        if total: mat = {k: v/total for k,v in mat.items()}
        return dict(sorted(mat.items(), key=lambda x: x[1], reverse=True))

    # ── Paris sûrs ──────────────────────────────────────────
    def _safe_bets(self, mat, lam1, lam2, scope="full") -> list:
        """
        Retourne une liste de (label, probabilité, cote_implicite, niveau)
        pour tous les paris dépassant 75%.
        """
        d = self.d
        bets = []

        def add(label, prob, cote=None):
            bets.append({"label": label, "prob": prob, "cote": cote})

        # ── 1. Over / Under total ──────────────────────────
        thresholds_full = [
            (0.5,"total_05"), (1.5,"total_15"), (2.5,"total_25"),
            (3.5,"total_35"), (4.5,"total_45")
        ]
        thresholds_mt = [
            (0.5,"mt_total_05"),(1.5,"mt_total_15"),
            (2.5,"mt_total_25"),(3.5,"mt_total_35")
        ]
        thresholds = thresholds_full if scope=="full" else thresholds_mt

        for t, key in thresholds:
            p_over  = sum(p for (g1,g2),p in mat.items() if g1+g2 > t)
            p_under = 1 - p_over
            cote_o  = d[key][0] if key in d else None
            cote_u  = d[key][1] if key in d else None
            lbl_sfx = "" if scope=="full" else " MT"
            add(f"Over {t}{lbl_sfx}",  p_over,  cote_o)
            add(f"Under {t}{lbl_sfx}", p_under, cote_u)

        # ── 2. Total1 (buts équipe 1) ──────────────────────
        t1_keys_full = [
            (0.5,"total1_05"),(1.5,"total1_15"),(2.5,"total1_25")
        ]
        t1_keys_mt = [
            (0.5,"mt_total1_05"),(1.5,"mt_total1_15")
        ]
        t1_keys = t1_keys_full if scope=="full" else t1_keys_mt

        for t, key in t1_keys:
            p_over  = sum(p for (g1,_),p in mat.items() if g1 > t)
            p_under = 1 - p_over
            cote_o  = d[key][0] if key in d else None
            cote_u  = d[key][1] if key in d else None
            sfx = "" if scope=="full" else " MT"
            add(f"{self.team1} Over {t}{sfx}",  p_over,  cote_o)
            add(f"{self.team1} Under {t}{sfx}", p_under, cote_u)

        # ── 3. Total2 (buts équipe 2) ──────────────────────
        t2_keys_full = [
            (0.5,"total2_05"),(1.5,"total2_15"),(2.5,"total2_25")
        ]
        t2_keys_mt = [
            (0.5,"mt_total2_05"),(1.5,"mt_total2_15")
        ]
        t2_keys = t2_keys_full if scope=="full" else t2_keys_mt

        for t, key in t2_keys:
            p_over  = sum(p for (_,g2),p in mat.items() if g2 > t)
            p_under = 1 - p_over
            cote_o  = d[key][0] if key in d else None
            cote_u  = d[key][1] if key in d else None
            sfx = "" if scope=="full" else " MT"
            add(f"{self.team2} Over {t}{sfx}",  p_over,  cote_o)
            add(f"{self.team2} Under {t}{sfx}", p_under, cote_u)

        # ── 4. BTTS ────────────────────────────────────────
        btts_key  = "btts_full"  if scope=="full" else "btts_mt"
        btts2_key = "btts2_full" if scope=="full" else "btts2_mt"
        sfx = "" if scope=="full" else " MT"

        p_btts_yes = sum(p for (g1,g2),p in mat.items() if g1>0 and g2>0)
        p_btts_no  = 1 - p_btts_yes
        cote_by = d[btts_key]["yes"] if btts_key in d else None
        cote_bn = d[btts_key]["no"]  if btts_key in d else None
        add(f"BTTS Oui{sfx}", p_btts_yes, cote_by)
        add(f"BTTS Non{sfx}", p_btts_no,  cote_bn)

        # Chaque équipe marque 2+
        p_btts2_yes = sum(p for (g1,g2),p in mat.items() if g1>=2 and g2>=2)
        p_btts2_no  = 1 - p_btts2_yes
        cote_b2y = d[btts2_key]["yes"] if btts2_key in d else None
        cote_b2n = d[btts2_key]["no"]  if btts2_key in d else None
        add(f"Chaque équipe 2+{sfx} Oui", p_btts2_yes, cote_b2y)
        add(f"Chaque équipe 2+{sfx} Non", p_btts2_no,  cote_b2n)

        # ── 5. 1X2 ────────────────────────────────────────
        x2_key = "1x2_full" if scope=="full" else "1x2_mt"
        if x2_key in d:
            x   = d[x2_key]
            p1  = sum(p for (g1,g2),p in mat.items() if g1>g2)
            px  = sum(p for (g1,g2),p in mat.items() if g1==g2)
            p2  = sum(p for (g1,g2),p in mat.items() if g2>g1)
            add(f"Victoire {self.team1}{sfx}", p1, x["w1"])
            add(f"Match Nul{sfx}",             px, x["x"])
            add(f"Victoire {self.team2}{sfx}", p2, x["w2"])

        # ── 6. Score exact (top 10 si ≥ 75%) ─────────────
        for (g1,g2), prob in list(mat.items())[:15]:
            add(f"Score exact {g1}-{g2}{sfx}", prob, None)

        # ── Filtrage par seuils ────────────────────────────
        levels = {}
        for b in bets:
            p = b["prob"]
            if p >= 0.75:
                lvl = "🔴 85%" if p >= 0.85 else ("🟠 80%" if p >= 0.80 else "🟡 75%")
                levels.setdefault(lvl, []).append(b)

        return levels

    # ── Formatage H2H ───────────────────────────────────────
    def _format_h2h(self):
        lines = ["📋 *5 Derniers H2H (plus récent en 1er)*", ""]
        for i,(s1,s2) in enumerate(self.h2h, 1):
            lines.append(f"{i}. {self.team1} *{s1}-{s2}* {self.team2}")
        return "\n".join(lines)

    # ── Formatage favori ────────────────────────────────────
    def _favori(self, scope="full"):
        key = "1x2_full" if scope=="full" else "1x2_mt"
        if key not in self.d: return ""
        x = self.d[key]
        p1,px,p2 = normalize3(odd_to_prob(x["w1"]),odd_to_prob(x["x"]),odd_to_prob(x["w2"]))
        best = max([(p1,f"🏠 {self.team1}",x["w1"]),(px,"🤝 Match Nul",x["x"]),(p2,f"✈️ {self.team2}",x["w2"])], key=lambda t:t[0])
        return f"⭐ *Favori :* {best[1]}  `{best[2]}`  _(prob. {best[0]*100:.0f}%)_"

    # ── Formatage top 5 scores ──────────────────────────────
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

    # ── Formatage paris sûrs ────────────────────────────────
    def _format_safe_bets(self, levels_full, levels_mt):
        sep = "━━━━━━━━━━━━━━━━━━━━━"
        lines = [sep, "🔒 *PARIS SÛRS RECOMMANDÉS*", sep, ""]

        order = ["🔴 85%", "🟠 80%", "🟡 75%"]
        medals = {"🔴 85%": "🔴", "🟠 80%": "🟠", "🟡 75%": "🟡"}
        labels = {"🔴 85%": "Très sûr (≥85%)", "🟠 80%": "Sûr (≥80%)", "🟡 75%": "Probable (≥75%)"}

        # Fusion MT + full dans chaque niveau
        all_levels = {}
        for lvl in order:
            bets_all = []
            if lvl in levels_full: bets_all += [(b,"🏁") for b in levels_full[lvl]]
            if lvl in levels_mt:   bets_all += [(b,"🕐") for b in levels_mt[lvl]]
            if bets_all:
                all_levels[lvl] = bets_all

        if not all_levels:
            lines.append("⚠️ _Aucun pari ne dépasse 75% de confiance pour ce match._")
            return "\n".join(lines)

        for lvl in order:
            if lvl not in all_levels: continue
            med = medals[lvl]
            lbl = labels[lvl]
            lines.append(f"{med} *{lbl}*")
            lines.append("")
            seen = set()
            for b, scope_icon in all_levels[lvl]:
                key = b["label"]
                if key in seen: continue
                seen.add(key)
                cote_str = f"  _(cote `{b['cote']}`)_" if b["cote"] else ""
                lines.append(f"  {scope_icon} {b['label']} → *{b['prob']*100:.1f}%*{cote_str}")
            lines.append("")

        lines.append("_🏁 = Temps réglementaire  |  🕐 = Mi-temps_")
        return "\n".join(lines)

    # ── Point d'entrée ──────────────────────────────────────
    def predict(self) -> str:
        lam1_mt,   lam2_mt   = self._compute_lambdas(scope="mt")
        lam1_full, lam2_full = self._compute_lambdas(scope="full")
        mat_mt   = self._score_matrix(lam1_mt,   lam2_mt)
        mat_full = self._score_matrix(lam1_full, lam2_full)

        levels_full = self._safe_bets(mat_full, lam1_full, lam2_full, scope="full")
        levels_mt   = self._safe_bets(mat_mt,   lam1_mt,   lam2_mt,   scope="mt")

        fav_full = self._favori(scope="full")
        fav_mt   = self._favori(scope="mt")
        sep = "━━━━━━━━━━━━━━━━━━━━━"

        return (
            f"⚽ *ANALYSE : {self.team1} vs {self.team2}*\n"
            f"🏆 {self.league}\n"
            f"{sep}\n\n"
            f"{self._format_h2h()}\n\n"
            f"{sep}\n\n"
            f"{fav_mt}\n\n"
            f"{self._format_scores(mat_mt,  '🕐 PRÉDICTION 1ÈRE MI-TEMPS', lam1_mt,   lam2_mt)}\n\n"
            f"{sep}\n\n"
            f"{fav_full}\n\n"
            f"{self._format_scores(mat_full,'🏁 PRÉDICTION SCORE FINAL',   lam1_full, lam2_full)}\n\n"
            f"{self._format_safe_bets(levels_full, levels_mt)}\n\n"
            f"{sep}\n"
            f"⚠️ _Prédictions basées sur le modèle de Poisson.\nAucune garantie de résultat._"
        )
