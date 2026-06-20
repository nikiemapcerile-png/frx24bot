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

def make_formulaire_mt(t1, t2):
    return (
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🕐 *COTES 1ÈRE MI-TEMPS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Remplissez chaque ligne. Laissez vide si non disponible.\n"
        "Format Over/Under : `1.90 1.85`\n"
        "Format 1X2 : `2.10 3.20 3.50`\n\n"
        f"1X2 MT : \n"
        f"BTTS MT (Oui/Non) : \n"
        f"Chaque équipe 2+ MT (Oui/Non) : \n"
        f"Total MT 0.5 (Over/Under) : \n"
        f"Total MT 1.5 (Over/Under) : \n"
        f"Total MT 2.5 (Over/Under) : \n"
        f"Total MT 3.5 (Over/Under) : \n"
        f"{t1} MT 0.5 (Over/Under) : \n"
        f"{t1} MT 1.5 (Over/Under) : \n"
        f"{t2} MT 0.5 (Over/Under) : \n"
        f"{t2} MT 1.5 (Over/Under) : "
    )

def make_formulaire_full(t1, t2):
    return (
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🏁 *COTES MATCH COMPLET*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Remplissez chaque ligne. Laissez vide si non disponible.\n\n"
        f"1X2 : \n"
        f"BTTS (Oui/Non) : \n"
        f"Chaque équipe 2+ (Oui/Non) : \n"
        f"Total 0.5 (Over/Under) : \n"
        f"Total 1.5 (Over/Under) : \n"
        f"Total 2.5 (Over/Under) : \n"
        f"Total 3.5 (Over/Under) : \n"
        f"Total 4.5 (Over/Under) : \n"
        f"{t1} 0.5 (Over/Under) : \n"
        f"{t1} 1.5 (Over/Under) : \n"
        f"{t1} 2.5 (Over/Under) : \n"
        f"{t2} 0.5 (Over/Under) : \n"
        f"{t2} 1.5 (Over/Under) : \n"
        f"{t2} 2.5 (Over/Under) : "
    )

def parse_two(text):
    parts = text.strip().split()
    if len(parts) == 2:
        try:
            return float(parts[0].replace(",",".")), float(parts[1].replace(",","."))
        except: pass
    return None

def parse_three(text):
    parts = text.strip().split()
    if len(parts) == 3:
        try:
            return float(parts[0].replace(",",".")), float(parts[1].replace(",",".")), float(parts[2].replace(",","."))
        except: pass
    return None

def extract_values(lines):
    """Extrait les valeurs après le ':' de chaque ligne."""
    values = []
    for line in lines:
        if ":" in line:
            val = line.split(":", 1)[1].strip()
            values.append(val)
        else:
            values.append(line.strip())
    return values

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

    await update.message.reply_text(
        f"🔍 *{parts[0]} vs {parts[1]}*\n\n"
        f"{make_formulaire_mt(parts[0], parts[1])}\n\n"
        "👆 Copiez ce formulaire, remplissez les cotes après les `:` et renvoyez-le.",
        parse_mode="Markdown"
    )
    return ENTER_MT_ODDS

async def enter_mt_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    lines = [l for l in text.splitlines() if l.strip()]
    values = extract_values(lines)

    if len(values) < 11:
        await update.message.reply_text(
            f"❌ Il faut *11 lignes* pour la MT. Recopiez le formulaire complet.",
            parse_mode="Markdown"
        )
        return ENTER_MT_ODDS

    d = context.user_data
    # 1X2 MT
    v = parse_three(values[0])
    if v: d["1x2_mt"] = {"w1": v[0], "x": v[1], "w2": v[2]}
    # BTTS MT
    v = parse_two(values[1])
    if v: d["btts_mt"] = {"yes": v[0], "no": v[1]}
    # BTTS2 MT
    v = parse_two(values[2])
    if v: d["btts2_mt"] = {"yes": v[0], "no": v[1]}
    # Totaux MT
    keys_mt = ["mt_total_05","mt_total_15","mt_total_25","mt_total_35",
               "mt_total1_05","mt_total1_15","mt_total2_05","mt_total2_15"]
    for i, key in enumerate(keys_mt):
        v = parse_two(values[3+i])
        if v: d[key] = v

    t1, t2 = d["team1"], d["team2"]
    await update.message.reply_text(
        f"✅ Cotes MT enregistrées !\n\n"
        f"{make_formulaire_full(t1, t2)}\n\n"
        "👆 Copiez ce formulaire, remplissez les cotes après les `:` et renvoyez-le.",
        parse_mode="Markdown"
    )
    return ENTER_FULL_ODDS

async def enter_full_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    lines = [l for l in text.splitlines() if l.strip()]
    values = extract_values(lines)

    if len(values) < 14:
        await update.message.reply_text(
            f"❌ Il faut *14 lignes* pour le match complet. Recopiez le formulaire.",
            parse_mode="Markdown"
        )
        return ENTER_FULL_ODDS

    d = context.user_data
    # 1X2 full
    v = parse_three(values[0])
    if v: d["1x2_full"] = {"w1": v[0], "x": v[1], "w2": v[2]}
    # BTTS full
    v = parse_two(values[1])
    if v: d["btts_full"] = {"yes": v[0], "no": v[1]}
    # BTTS2 full
    v = parse_two(values[2])
    if v: d["btts2_full"] = {"yes": v[0], "no": v[1]}
    # Totaux full
    keys_full = ["total_05","total_15","total_25","total_35","total_45",
                 "total1_05","total1_15","total1_25",
                 "total2_05","total2_15","total2_25"]
    for i, key in enumerate(keys_full):
        v = parse_two(values[3+i])
        if v: d[key] = v

    d["h2h"] = []

    await update.message.reply_text("⚙️ *Calcul en cours...*", parse_mode="Markdown")
    predictor = ScorePredictor(d)
    result = predictor.predict()
    await update.message.reply_text(result, parse_mode="Markdown")
    await update.message.reply_text(
        "🔄 Tapez /start pour analyser un nouveau match.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Analyse annulée. Tapez /start.", reply_markup=ReplyKeyboardRemove())
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
