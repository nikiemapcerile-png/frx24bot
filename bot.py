import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from predictor import ScorePredictor

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSE_LEAGUE, ENTER_TEAMS, ENTER_MT_ODDS, ENTER_FULL_ODDS = range(4)
LEAGUES = ["🇮🇹 FC 25. Italy Championship (Serie A)", "🏆 FC 26. Champions League"]

def box(option, cote=""):
    o = f" {option}".ljust(14)
    c = f" {cote}".ljust(10)
    top = "┌──────────────┬──────────┐"
    mid = f"│{o}│{c}│"
    bot = "└──────────────┴──────────┘"
    return f"{top}\n{mid}\n{bot}"

def make_form_mt(t1, t2):
    lines = [
        "🕐 *1ÈRE MI-TEMPS*\n",
        box(f"1 ({t1})"),
        box("X (Nul)"),
        box(f"2 ({t2})"),
        box("BTTS Oui"),
        box("BTTS Non"),
        box("2+ Equipes Oui"),
        box("2+ Equipes Non"),
        box("Total 0.5 Over"),
        box("Total 0.5 Under"),
        box("Total 1.5 Over"),
        box("Total 1.5 Under"),
        box("Total 2.5 Over"),
        box("Total 2.5 Under"),
        box("Total 3.5 Over"),
        box("Total 3.5 Under"),
        box(f"{t1} 0.5 Over"),
        box(f"{t1} 0.5 Under"),
        box(f"{t1} 1.5 Over"),
        box(f"{t1} 1.5 Under"),
        box(f"{t2} 0.5 Over"),
        box(f"{t2} 0.5 Under"),
        box(f"{t2} 1.5 Over"),
        box(f"{t2} 1.5 Under"),
    ]
    return "\n".join(lines)

def make_form_full(t1, t2):
    lines = [
        "🏁 *MATCH COMPLET*\n",
        box(f"1 ({t1})"),
        box("X (Nul)"),
        box(f"2 ({t2})"),
        box("BTTS Oui"),
        box("BTTS Non"),
        box("2+ Equipes Oui"),
        box("2+ Equipes Non"),
        box("Total 0.5 Over"),
        box("Total 0.5 Under"),
        box("Total 1.5 Over"),
        box("Total 1.5 Under"),
        box("Total 2.5 Over"),
        box("Total 2.5 Under"),
        box("Total 3.5 Over"),
        box("Total 3.5 Under"),
        box("Total 4.5 Over"),
        box("Total 4.5 Under"),
        box(f"{t1} 0.5 Over"),
        box(f"{t1} 0.5 Under"),
        box(f"{t1} 1.5 Over"),
        box(f"{t1} 1.5 Under"),
        box(f"{t1} 2.5 Over"),
        box(f"{t1} 2.5 Under"),
        box(f"{t2} 0.5 Over"),
        box(f"{t2} 0.5 Under"),
        box(f"{t2} 1.5 Over"),
        box(f"{t2} 1.5 Under"),
        box(f"{t2} 2.5 Over"),
        box(f"{t2} 2.5 Under"),
    ]
    return "\n".join(lines)

def parse_form(text, n_options):
    """Extrait les cotes depuis le formulaire rempli."""
    lines = text.splitlines()
    values = []
    for line in lines:
        if "│" in line and "─" not in line and "Option" not in line and "Côte" not in line:
            parts = line.split("│")
            if len(parts) >= 3:
                cote = parts[2].strip()
                values.append(cote if cote else "")
    return values

def parse_two(text):
    if not text: return None
    parts = text.strip().split()
    if len(parts) == 2:
        try: return float(parts[0].replace(",",".")), float(parts[1].replace(",","."))
        except: pass
    return None

def parse_one(text):
    if not text: return None
    try: return float(text.strip().replace(",","."))
    except: return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[lg] for lg in LEAGUES]
    await update.message.reply_text(
        "⚽ *Bot de Prédiction de Score Exact*\n\nChoisissez le championnat :",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return CHOOSE_LEAGUE

async def choose_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    league = update.message.text.strip()
    if league not in LEAGUES:
        await update.message.reply_text("❌ Choix invalide. Tapez /start.")
        return CHOOSE_LEAGUE
    context.user_data["league"] = league
    await update.message.reply_text(
        f"✅ *{league}*\n\nEntrez le match :\nEx: `Milano vs Juventus`",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove(),
    )
    return ENTER_TEAMS

async def enter_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    sep = None
    for s in [" vs ", " VS ", " Vs "]:
        if s in text:
            sep = s; break
    if not sep:
        await update.message.reply_text("❌ Format invalide. Ex: `Milano vs Juventus`", parse_mode="Markdown")
        return ENTER_TEAMS
    parts = [p.strip() for p in text.split(sep, 1)]
    if len(parts) != 2 or not all(parts):
        await update.message.reply_text("❌ Format invalide.", parse_mode="Markdown")
        return ENTER_TEAMS
    context.user_data["team1"] = parts[0]
    context.user_data["team2"] = parts[1]
    t1, t2 = parts[0], parts[1]

    form = make_form_mt(t1, t2)
    await update.message.reply_text(
        f"🔍 *{t1} vs {t2}*\n\n"
        f"Copiez le formulaire, remplissez les côtes dans la colonne droite et renvoyez :\n\n"
        f"```\n{form}\n```",
        parse_mode="Markdown"
    )
    return ENTER_MT_ODDS

async def enter_mt_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    values = parse_form(text, 23)
    d = context.user_data
    t1, t2 = d["team1"], d["team2"]

    if len(values) < 8:
        await update.message.reply_text("❌ Formulaire non reconnu. Recopiez et remplissez le formulaire.", parse_mode="Markdown")
        return ENTER_MT_ODDS

    # 1X2 MT (3 valeurs sur 3 lignes)
    v1 = parse_one(values[0])
    vx = parse_one(values[1])
    v2 = parse_one(values[2])
    if v1 and vx and v2:
        d["1x2_mt"] = {"w1": v1, "x": vx, "w2": v2}
    # BTTS MT
    yes = parse_one(values[3])
    no  = parse_one(values[4])
    if yes and no: d["btts_mt"] = {"yes": yes, "no": no}
    # BTTS2 MT
    yes2 = parse_one(values[5])
    no2  = parse_one(values[6])
    if yes2 and no2: d["btts2_mt"] = {"yes": yes2, "no": no2}
    # Totaux MT
    keys = ["mt_total_05","mt_total_05u","mt_total_15","mt_total_15u",
            "mt_total_25","mt_total_25u","mt_total_35","mt_total_35u"]
    for i, key in enumerate(keys):
        if 7+i < len(values):
            v = parse_one(values[7+i])
            if v: d[key] = v
    # Total1 MT
    if 15 < len(values): 
        v = parse_one(values[15])
        if v: d["mt_total1_05_o"] = v
    if 16 < len(values):
        v = parse_one(values[16])
        if v: d["mt_total1_05_u"] = v
    if 17 < len(values):
        v = parse_one(values[17])
        if v: d["mt_total1_15_o"] = v
    if 18 < len(values):
        v = parse_one(values[18])
        if v: d["mt_total1_15_u"] = v
    # Total2 MT
    if 19 < len(values):
        v = parse_one(values[19])
        if v: d["mt_total2_05_o"] = v
    if 20 < len(values):
        v = parse_one(values[20])
        if v: d["mt_total2_05_u"] = v
    if 21 < len(values):
        v = parse_one(values[21])
        if v: d["mt_total2_15_o"] = v
    if 22 < len(values):
        v = parse_one(values[22])
        if v: d["mt_total2_15_u"] = v

    # Conversion en tuples Over/Under
    if "mt_total_05" in d and "mt_total_05u" in d:
        d["mt_total_05"] = (d["mt_total_05"], d.pop("mt_total_05u"))
    if "mt_total_15" in d and "mt_total_15u" in d:
        d["mt_total_15"] = (d["mt_total_15"], d.pop("mt_total_15u"))
    if "mt_total_25" in d and "mt_total_25u" in d:
        d["mt_total_25"] = (d["mt_total_25"], d.pop("mt_total_25u"))
    if "mt_total_35" in d and "mt_total_35u" in d:
        d["mt_total_35"] = (d["mt_total_35"], d.pop("mt_total_35u"))
    if "mt_total1_05_o" in d and "mt_total1_05_u" in d:
        d["mt_total1_05"] = (d.pop("mt_total1_05_o"), d.pop("mt_total1_05_u"))
    if "mt_total1_15_o" in d and "mt_total1_15_u" in d:
        d["mt_total1_15"] = (d.pop("mt_total1_15_o"), d.pop("mt_total1_15_u"))
    if "mt_total2_05_o" in d and "mt_total2_05_u" in d:
        d["mt_total2_05"] = (d.pop("mt_total2_05_o"), d.pop("mt_total2_05_u"))
    if "mt_total2_15_o" in d and "mt_total2_15_u" in d:
        d["mt_total2_15"] = (d.pop("mt_total2_15_o"), d.pop("mt_total2_15_u"))

    form = make_form_full(t1, t2)
    await update.message.reply_text(
        f"✅ MT enregistré !\n\n"
        f"Maintenant le match complet :\n\n"
        f"```\n{form}\n```",
        parse_mode="Markdown"
    )
    return ENTER_FULL_ODDS

async def enter_full_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    values = parse_form(text, 29)
    d = context.user_data

    if len(values) < 8:
        await update.message.reply_text("❌ Formulaire non reconnu. Recopiez et remplissez.", parse_mode="Markdown")
        return ENTER_FULL_ODDS

    # 1X2
    v1 = parse_one(values[0])
    vx = parse_one(values[1])
    v2 = parse_one(values[2])
    if v1 and vx and v2: d["1x2_full"] = {"w1": v1, "x": vx, "w2": v2}
    # BTTS
    yes = parse_one(values[3])
    no  = parse_one(values[4])
    if yes and no: d["btts_full"] = {"yes": yes, "no": no}
    # BTTS2
    yes2 = parse_one(values[5])
    no2  = parse_one(values[6])
    if yes2 and no2: d["btts2_full"] = {"yes": yes2, "no": no2}
    # Totaux
    idx = 7
    for key_o, key_u in [
        ("total_05","total_05u"),("total_15","total_15u"),
        ("total_25","total_25u"),("total_35","total_35u"),
        ("total_45","total_45u")
    ]:
        if idx < len(values):
            v = parse_one(values[idx]); 
            if v: d[key_o] = v
        if idx+1 < len(values):
            v = parse_one(values[idx+1])
            if v: d[key_u] = v
        idx += 2
    # Total1
    for key_o, key_u in [("t1_05o","t1_05u"),("t1_15o","t1_15u"),("t1_25o","t1_25u")]:
        if idx < len(values):
            v = parse_one(values[idx])
            if v: d[key_o] = v
        if idx+1 < len(values):
            v = parse_one(values[idx+1])
            if v: d[key_u] = v
        idx += 2
    # Total2
    for key_o, key_u in [("t2_05o","t2_05u"),("t2_15o","t2_15u"),("t2_25o","t2_25u")]:
        if idx < len(values):
            v = parse_one(values[idx])
            if v: d[key_o] = v
        if idx+1 < len(values):
            v = parse_one(values[idx+1])
            if v: d[key_u] = v
        idx += 2

    # Conversion tuples
    for o,u,k in [("total_05","total_05u","total_05"),("total_15","total_15u","total_15"),
                  ("total_25","total_25u","total_25"),("total_35","total_35u","total_35"),
                  ("total_45","total_45u","total_45")]:
        if o in d and u in d: d[k] = (d.pop(o), d.pop(u))
    for o,u,k in [("t1_05o","t1_05u","total1_05"),("t1_15o","t1_15u","total1_15"),("t1_25o","t1_25u","total1_25")]:
        if o in d and u in d: d[k] = (d.pop(o), d.pop(u))
    for o,u,k in [("t2_05o","t2_05u","total2_05"),("t2_15o","t2_15u","total2_15"),("t2_25o","t2_25u","total2_25")]:
        if o in d and u in d: d[k] = (d.pop(o), d.pop(u))

    d["h2h"] = []
    await update.message.reply_text("⚙️ *Calcul en cours...*", parse_mode="Markdown")
    predictor = ScorePredictor(d)
    result = predictor.predict()
    await update.message.reply_text(result, parse_mode="Markdown")
    await update.message.reply_text("🔄 Tapez /start pour un nouveau match.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Annulé. Tapez /start.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    import os
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "VOTRE_TOKEN_ICI")
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_LEAGUE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_league)],
            ENTER_TEAMS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_teams)],
            ENTER_MT_ODDS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt_odds)],
            ENTER_FULL_ODDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_full_odds)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    logger.info("Bot démarré ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
