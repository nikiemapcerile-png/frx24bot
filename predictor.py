"""
predictor.py — Moteur de prédiction complet avec stats DB
"""
import math
from itertools import product

LEAGUE_PROFILES = {
    "serie_a": {
        "lam_min": 0.3, "lam_max": 3.5, "lam_total_ref": 2.5,
        "btts_base": 0.45, "zero_zero": 0.06,
        "mt_lam_ratio": 0.30, "mt_zero_boost": 1.8,
    },
    "champions": {
        "lam_min": 0.5, "lam_max": 5.0, "lam_total_ref": 3.5,
        "btts_base": 0.55, "zero_zero": 0.03,
        "mt_lam_ratio": 0.40, "mt_zero_boost": 1.2,
    }
}

def get_profile(league):
    if any(x in league.lower() for x in ["serie","italy","fc 25"]):
        return LEAGUE_PROFILES["serie_a"], "serie_a"
    return LEAGUE_PROFILES["champions"], "champions"

def odd_to_prob(o): return 1.0/o if o and o > 1.0 else 0.0
def normalize2(a,b): t=a+b; return (a/t,b/t) if t else (0.5,0.5)
def normalize3(a,b,c): t=a+b+c; return (a/t,b/t,c/t) if t else (1/3,1/3,1/3)
def poisson_pmf(k,lam):
    if lam<=0: return 1.0 if k==0 else 0.0
    return math.exp(-lam)*(lam**k)/math.factorial(k)
def poisson_cdf(k,lam): return sum(poisson_pmf(i,lam) for i in range(k+1))

def estimate_lambda(over_probs):
    if not over_probs: return 1.5
    best_lam, best_err = 1.5, float("inf")
    for x in range(1,121):
        lam = x/10.0
        err = sum((1-poisson_cdf(int(t),lam)-p)**2 for t,p in over_probs.items())
        if err < best_err: best_err,best_lam = err,lam
    return best_lam

def lambda_team(d, keys):
    op = {}
    for key,t in keys:
        if key in d and isinstance(d[key],tuple) and len(d[key])==2:
            po,_ = normalize2(odd_to_prob(d[key][0]), odd_to_prob(d[key][1]))
            op[t] = po
    return estimate_lambda(op) if op else None

def h2h_lambdas(h2h):
    w=[5,4,3,2,1]; sw=sum(w[:len(h2h)])
    if not sw: return 1.5,1.5
    return (sum(w*s1 for (s1,_),w in zip(h2h,w))/sw,
            sum(w*s2 for (_,s2),w in zip(h2h,w))/sw)

class ScorePredictor:
    def __init__(self, data):
        self.d=data; self.t1=data["team1"]; self.t2=data["team2"]
        self.league=data.get("league",""); self.h2h=data.get("h2h",[])
        self.profile,self.pkey=get_profile(self.league)
        self.stats1=data.get("stats_team1"); self.stats2=data.get("stats_team2")
        self.h2h_detail=data.get("h2h_detail",[])

    def _over_probs(self, keys_map):
        r={}
        for key,t in keys_map:
            if key in self.d and isinstance(self.d[key],tuple):
                po,_=normalize2(odd_to_prob(self.d[key][0]),odd_to_prob(self.d[key][1]))
                r[t]=po
        return r

    def _compute_lambdas(self, scope="full"):
        d=self.d; p=self.profile
        if scope=="full":
            tk=[("total_05",.5),("total_15",1.5),("total_25",2.5),("total_35",3.5),("total_45",4.5)]
            t1k=[("total1_05",.5),("total1_15",1.5),("total1_25",2.5)]
            t2k=[("total2_05",.5),("total2_15",1.5),("total2_25",2.5)]
            xk,bk="1x2_full","btts_full"; md=1.0
        else:
            tk=[("mt_total_05",.5),("mt_total_15",1.5),("mt_total_25",2.5),("mt_total_35",3.5)]
            t1k=[("mt_total1_05",.5),("mt_total1_15",1.5)]
            t2k=[("mt_total2_05",.5),("mt_total2_15",1.5)]
            xk,bk="1x2_mt","btts_mt"; md=1.0/p["mt_lam_ratio"]

        lam_t = estimate_lambda(self._over_probs(tk)) or p["lam_total_ref"]
        lam1_odds = lambda_team(d,t1k)
        lam2_odds = lambda_team(d,t2k)

        # H2H
        lam1_h2h, lam2_h2h = h2h_lambdas(self.h2h)
        if scope=="mt":
            lam1_h2h *= p["mt_lam_ratio"]
            lam2_h2h *= p["mt_lam_ratio"]

        # Stats DB
        lam1_db = lam2_db = None
        if self.stats1 and self.stats1["matches"] >= 3:
            lam1_db = self.stats1["avg_scored_ht"] if scope=="mt" else (self.stats1["avg_scored_ht"]+self.stats1["avg_scored_2h"])
        if self.stats2 and self.stats2["matches"] >= 3:
            lam2_db = self.stats2["avg_scored_ht"] if scope=="mt" else (self.stats2["avg_scored_ht"]+self.stats2["avg_scored_2h"])

        # Ratio 1X2
        r1,r2=0.55,0.45
        if xk in d:
            x=d[xk]
            p1,px,p2=normalize3(odd_to_prob(x.get("w1",2)),odd_to_prob(x.get("x",3)),odd_to_prob(x.get("w2",2)))
            s1,s2=p1+.5*px,p2+.5*px; t=s1+s2
            r1,r2=s1/t,s2/t

        # Fusion intelligente
        sources1=[]; weights1=[]
        sources2=[]; weights2=[]
        if lam1_odds:  sources1.append(lam1_odds);             weights1.append(0.35)
        if lam1_db:    sources1.append(lam1_db);               weights1.append(0.30)
        sources1.append(lam1_h2h);                             weights1.append(0.20)
        sources1.append(lam_t*r1);                             weights1.append(0.15)
        if lam2_odds:  sources2.append(lam2_odds);             weights2.append(0.35)
        if lam2_db:    sources2.append(lam2_db);               weights2.append(0.30)
        sources2.append(lam2_h2h);                             weights2.append(0.20)
        sources2.append(lam_t*r2);                             weights2.append(0.15)

        sw1=sum(weights1); sw2=sum(weights2)
        lam1=sum(s*w for s,w in zip(sources1,weights1))/sw1
        lam2=sum(s*w for s,w in zip(sources2,weights2))/sw2

        # Ajustement BTTS
        if bk in d:
            p_btts,_=normalize2(odd_to_prob(d[bk].get("yes",2)),odd_to_prob(d[bk].get("no",1.5)))
            if p_btts>0.65: lam1=max(lam1,0.6); lam2=max(lam2,0.6)

        lam1=max(p["lam_min"],min(p["lam_max"],lam1))
        lam2=max(p["lam_min"],min(p["lam_max"],lam2))
        return round(lam1,3),round(lam2,3)

    def _matrix(self, lam1, lam2, scope="full", max_g=8):
        mat={(g1,g2):poisson_pmf(g1,lam1)*poisson_pmf(g2,lam2)
             for g1,g2 in product(range(max_g+1),repeat=2)}
        # Boost/réduction 0-0 selon profil
        if (0,0) in mat:
            boost=self.profile["mt_zero_boost"] if scope=="mt" else (0.5 if self.profile["zero_zero"]<0.04 else 1.0)
            mat[(0,0)]*=boost
        total=sum(mat.values())
        if total: mat={k:v/total for k,v in mat.items()}
        return dict(sorted(mat.items(),key=lambda x:x[1],reverse=True))

    def _safe_bets(self, mat, scope="full"):
        d=self.d; bets=[]; sfx="" if scope=="full" else " MT"
        def add(label,prob,cote=None): bets.append({"label":label,"prob":prob,"cote":cote})

        # Over/Under total
        th_full=[(.5,"total_05"),(1.5,"total_15"),(2.5,"total_25"),(3.5,"total_35"),(4.5,"total_45")]
        th_mt=[(.5,"mt_total_05"),(1.5,"mt_total_15"),(2.5,"mt_total_25"),(3.5,"mt_total_35")]
        for t,key in (th_full if scope=="full" else th_mt):
            po=sum(p for (g1,g2),p in mat.items() if g1+g2>t)
            co=d[key][0] if key in d and isinstance(d[key],tuple) else None
            cu=d[key][1] if key in d and isinstance(d[key],tuple) else None
            add(f"Over {t}{sfx}",po,co); add(f"Under {t}{sfx}",1-po,cu)

        # Total1
        tk1_f=[(.5,"total1_05"),(1.5,"total1_15"),(2.5,"total1_25")]
        tk1_m=[(.5,"mt_total1_05"),(1.5,"mt_total1_15")]
        for t,key in (tk1_f if scope=="full" else tk1_m):
            po=sum(p for (g1,_),p in mat.items() if g1>t)
            co=d[key][0] if key in d and isinstance(d[key],tuple) else None
            cu=d[key][1] if key in d and isinstance(d[key],tuple) else None
            add(f"{self.t1} Over {t}{sfx}",po,co); add(f"{self.t1} Under {t}{sfx}",1-po,cu)

        # Total2
        tk2_f=[(.5,"total2_05"),(1.5,"total2_15"),(2.5,"total2_25")]
        tk2_m=[(.5,"mt_total2_05"),(1.5,"mt_total2_15")]
        for t,key in (tk2_f if scope=="full" else tk2_m):
            po=sum(p for (_,g2),p in mat.items() if g2>t)
            co=d[key][0] if key in d and isinstance(d[key],tuple) else None
            cu=d[key][1] if key in d and isinstance(d[key],tuple) else None
            add(f"{self.t2} Over {t}{sfx}",po,co); add(f"{self.t2} Under {t}{sfx}",1-po,cu)

        # BTTS
        bk="btts_full" if scope=="full" else "btts_mt"
        b2k="btts2_full" if scope=="full" else "btts2_mt"
        pb=sum(p for (g1,g2),p in mat.items() if g1>0 and g2>0)
        add(f"BTTS Oui{sfx}",pb,d[bk]["yes"] if bk in d else None)
        add(f"BTTS Non{sfx}",1-pb,d[bk]["no"] if bk in d else None)
        pb2=sum(p for (g1,g2),p in mat.items() if g1>=2 and g2>=2)
        add(f"2+ Eq. Oui{sfx}",pb2,d[b2k]["yes"] if b2k in d else None)
        add(f"2+ Eq. Non{sfx}",1-pb2,d[b2k]["no"] if b2k in d else None)

        # 1X2
        xk="1x2_full" if scope=="full" else "1x2_mt"
        if xk in d:
            x=d[xk]
            p1=sum(p for (g1,g2),p in mat.items() if g1>g2)
            px=sum(p for (g1,g2),p in mat.items() if g1==g2)
            p2=sum(p for (g1,g2),p in mat.items() if g2>g1)
            add(f"Victoire {self.t1}{sfx}",p1,x.get("w1"))
            add(f"Match Nul{sfx}",px,x.get("x"))
            add(f"Victoire {self.t2}{sfx}",p2,x.get("w2"))

        # Score exact
        for (g1,g2),prob in list(mat.items())[:10]:
            add(f"Score {g1}-{g2}{sfx}",prob,None)

        levels={}
        for b in bets:
            p=b["prob"]
            if p>=0.75:
                lvl="🔴 85%" if p>=0.85 else ("🟠 80%" if p>=0.80 else "🟡 75%")
                levels.setdefault(lvl,[]).append(b)
        return levels

    def _format_scores(self, mat, title, lam1, lam2):
        top5=list(mat.items())[:5]
        lines=[f"{title}",""]
        medals=["🥇","🥈","🥉","4️⃣","5️⃣"]
        for i,((g1,g2),p) in enumerate(top5):
            bar="█"*int(p*35)
            lines.append(f"{medals[i]} *{g1}-{g2}*  {p*100:.1f}%  {bar}")
        lines+=["",
            f"📊 λ {self.t1}: `{lam1}` | λ {self.t2}: `{lam2}`",
            f"⚽ Over 2.5 : `{sum(p for (g1,g2),p in mat.items() if g1+g2>2.5)*100:.1f}%`",
            f"🤝 BTTS : `{sum(p for (g1,g2),p in mat.items() if g1>0 and g2>0)*100:.1f}%`",
            f"🏠 {self.t1} : `{sum(p for (g1,g2),p in mat.items() if g1>g2)*100:.1f}%`",
            f"🤝 Nul : `{sum(p for (g1,g2),p in mat.items() if g1==g2)*100:.1f}%`",
            f"✈️ {self.t2} : `{sum(p for (g1,g2),p in mat.items() if g2>g1)*100:.1f}%`",
        ]
        return "\n".join(lines)

    def _format_safe_bets(self, lf, lm):
        sep="━━━━━━━━━━━━━━━━━━━━━"
        lines=[sep,"🔒 *PARIS SÛRS*",sep,""]
        order=["🔴 85%","🟠 80%","🟡 75%"]
        labels={"🔴 85%":"Très sûr ≥85%","🟠 80%":"Sûr ≥80%","🟡 75%":"Probable ≥75%"}
        all_l={}
        for lvl in order:
            b=[(b,"🏁") for b in lf.get(lvl,[])]+[(b,"🕐") for b in lm.get(lvl,[])]
            if b: all_l[lvl]=b
        if not all_l:
            lines.append("⚠️ _Aucun pari ≥75% détecté._"); return "\n".join(lines)
        for lvl in order:
            if lvl not in all_l: continue
            lines.append(f"{lvl} — *{labels[lvl]}*\n")
            seen=set()
            for b,icon in all_l[lvl]:
                if b["label"] in seen: continue
                seen.add(b["label"])
                c=f"  `{b['cote']}`" if b["cote"] else ""
                lines.append(f"  {icon} {b['label']} → *{b['prob']*100:.1f}%*{c}")
            lines.append("")
        lines.append("_🏁 Temps réglementaire  |  🕐 Mi-temps_")
        return "\n".join(lines)

    def _format_h2h(self):
        if not self.h2h: return "📋 _Pas encore de H2H enregistré. Le bot collecte les matchs automatiquement._"
        lines=["📋 *5 Derniers H2H*",""]
        for i,(s1,s2) in enumerate(self.h2h,1):
            w = "🏠" if s1>s2 else ("✈️" if s2>s1 else "🤝")
            lines.append(f"{i}. {self.t1} *{s1}-{s2}* {self.t2} {w}")
        return "\n".join(lines)

    def _format_stats(self):
        lines=[]
        for team,stats in [(self.t1,self.stats1),(self.t2,self.stats2)]:
            if not stats or stats["matches"]<3:
                lines.append(f"📈 _{team} : données insuffisantes (< 3 matchs)_")
                continue
            n=stats["matches"]
            lines.append(
                f"📈 *{team}* ({n} matchs)\n"
                f"  W{stats['wins']} D{stats['draws']} L{stats['losses']}\n"
                f"  ⏱ Moy. buts MT1 marqués : `{stats['avg_scored_ht']}` | encaissés : `{stats['avg_conceded_ht']}`\n"
                f"  ⏱ Moy. buts MT2 marqués : `{stats['avg_scored_2h']}` | encaissés : `{stats['avg_conceded_2h']}`\n"
                f"  🎯 Total/match : `{round(stats['avg_goals_ht']+stats['avg_goals_2h'],2)}`"
            )
        return "\n\n".join(lines)

    def _favori(self, scope="full"):
        key="1x2_full" if scope=="full" else "1x2_mt"
        if key not in self.d: return ""
        x=self.d[key]
        p1,px,p2=normalize3(odd_to_prob(x.get("w1",2)),odd_to_prob(x.get("x",3)),odd_to_prob(x.get("w2",2)))
        best=max([(p1,f"🏠 {self.t1}",x.get("w1")),(px,"🤝 Nul",x.get("x")),(p2,f"✈️ {self.t2}",x.get("w2"))],key=lambda t:t[0])
        return f"⭐ *Favori :* {best[1]}  `{best[2]}`  _{best[0]*100:.0f}%_"

    def predict_mt(self):
        """Message 1 : Analyse 1ère mi-temps."""
        lam1,lam2=self._compute_lambdas("mt")
        mat=self._matrix(lam1,lam2,"mt")
        lm=self._safe_bets(mat,"mt")
        badge="🇮🇹 _Serie A FC25_" if self.pkey=="serie_a" else "🏆 _Champions League FC26_"
        sep="━━━━━━━━━━━━━━━━━━━━━"
        return (
            f"╔═══════════════════════╗\n"
            f"║  ⚽ {self.t1} vs {self.t2}\n"
            f"╚═══════════════════════╝\n"
            f"{badge}\n\n"
            f"{self._format_h2h()}\n\n"
            f"{sep}\n"
            f"{self._format_stats()}\n"
            f"{sep}\n\n"
            f"{self._favori('mt')}\n\n"
            f"{self._format_scores(mat,'🕐 *PRÉDICTION 1ÈRE MI-TEMPS*',lam1,lam2)}\n\n"
            f"{self._format_safe_bets({},lm)}\n\n"
            f"{sep}\n"
            f"⚠️ _Modèle Poisson adapté FIFA Virtuel_"
        )

    def predict_full(self):
        """Message 2 : Analyse 2ème mi-temps + score final."""
        lam1_mt,lam2_mt=self._compute_lambdas("mt")
        lam1,lam2=self._compute_lambdas("full")
        mat_mt=self._matrix(lam1_mt,lam2_mt,"mt")
        mat=self._matrix(lam1,lam2,"full")
        lf=self._safe_bets(mat,"full")
        lm=self._safe_bets(mat_mt,"mt")
        sep="━━━━━━━━━━━━━━━━━━━━━"

        # Prédiction 2ème MT (différence entre full et MT)
        lam1_2h=max(0.05,round(lam1-lam1_mt,3))
        lam2_2h=max(0.05,round(lam2-lam2_mt,3))
        mat_2h=self._matrix(lam1_2h,lam2_2h,"full")

        return (
            f"╔═══════════════════════╗\n"
            f"║  🏁 ANALYSE FINALE\n"
            f"║  {self.t1} vs {self.t2}\n"
            f"╚═══════════════════════╝\n\n"
            f"{self._favori('full')}\n\n"
            f"{sep}\n\n"
            f"{self._format_scores(mat_2h,'⚡ *PRÉDICTION 2ÈME MI-TEMPS*',lam1_2h,lam2_2h)}\n\n"
            f"{sep}\n\n"
            f"{self._format_scores(mat,'🏆 *PRÉDICTION SCORE FINAL*',lam1,lam2)}\n\n"
            f"{self._format_safe_bets(lf,{})}\n\n"
            f"{sep}\n"
            f"⚠️ _Prédictions basées sur Poisson + historique DB.\nAucune garantie de résultat._"
        )

    def predict(self):
        """Compatibilité : retourne les deux analyses en un seul texte."""
        return self.predict_mt() + "\n\n" + self.predict_full()
