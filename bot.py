import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from predictor import ScorePredictor

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── États ─────────────────────────────────────────────────────────────────────
(
    CHOOSE_LEAGUE, ENTER_TEAMS, ENTER_H2H,
    # Temps réglementaire
    ENTER_1X2_FULL,
    ENTER_BTTS_FULL, ENTER_BTTS2_FULL,
    ENTER_TOTAL_05, ENTER_TOTAL_15, ENTER_TOTAL_25, ENTER_TOTAL_35, ENTER_TOTAL_45,
    ENTER_TOTAL1_05, ENTER_TOTAL1_15, ENTER_TOTAL1_25,
    ENTER_TOTAL2_05, ENTER_TOTAL2_15, ENTER_TOTAL2_25,
    # 1ère mi-temps
    ENTER_1X2_MT,
    ENTER_BTTS_MT, ENTER_BTTS2_MT,
    ENTER_MT_05, ENTER_MT_15, ENTER_MT_25, ENTER_MT_35,
    ENTER_MT1_05, ENTER_MT1_15,
    ENTER_MT2_05, ENTER_MT2_15,
) = range(28)

LEAGUES = ["🎮 FIFA Virtuel E-Sport FC26", "🇮🇹 Championnat d'Italie (Serie A)"]

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_two(text):
    parts = text.strip().split()
    if len(parts) == 2:
        try:
            return float(parts[0].replace(",",".")), float(parts[1].replace(",","."))
        except ValueError:
            pass
    return None

def parse_three(text):
    parts = text.strip().split()
    if len(parts) == 3:
        try:
            return float(parts[0].replace(",",".")), float(parts[1].replace(",",".")), float(parts[2].replace(",","."))
        except ValueError:
            pass
    return None

ERR2 = "❌ Format invalide. Entrez *Over* puis *Under* séparés par un espace.\nEx: `1.90 1.85`"
ERR3 = "❌ Format invalide. Entrez *1* puis *X* puis *2* séparés par un espace.\nEx: `2.10 3.20 3.50`"

async def ask(update, msg):
    await update.message.reply_text(msg, parse_mode="Markdown")

# ── /start ────────────────────────────────────────────────────────────────────
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
        f"✅ *{league}*\n\nEntrez le match à analyser :\nEx: `Bologna vs Genoa`",
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
        await update.message.reply_text("❌ Format invalide. Ex: `Bologna vs Genoa`", parse_mode="Markdown")
        return ENTER_TEAMS
    parts = [p.strip() for p in text.split(sep, 1)]
    if len(parts) != 2 or not all(parts):
        await update.message.reply_text("❌ Format invalide. Ex: `Bologna vs Genoa`", parse_mode="Markdown")
        return ENTER_TEAMS
    context.user_data["team1"] = parts[0]
    context.user_data["team2"] = parts[1]
    context.user_data["h2h"] = []
    await update.message.reply_text(
        f"🔍 *{parts[0]} vs {parts[1]}*\n\n"
        "Entrez les *5 derniers face-à-face* (un par ligne ou tout ensemble).\n"
        "Format : `Score1-Score2` — *le plus récent en premier*\n\n"
        "Ex:\n`2-1\n0-0\n3-2\n1-1\n2-0`",
        parse_mode="Markdown",
    )
    return ENTER_H2H

async def enter_h2h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import re
    text = update.message.text.strip()
    lines = [l.strip() for l in text.replace(",","\n").splitlines() if l.strip()]
    for line in lines:
        m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", line)
        if m:
            context.user_data["h2h"].append((int(m.group(1)), int(m.group(2))))
    if len(context.user_data["h2h"]) < 5:
        rem = 5 - len(context.user_data["h2h"])
        await update.message.reply_text(
            f"✅ {len(context.user_data['h2h'])}/5 H2H enregistrés. Encore {rem} résultat(s) :",
            parse_mode="Markdown")
        return ENTER_H2H
    context.user_data["h2h"] = context.user_data["h2h"][:5]
    t1, t2 = context.user_data["team1"], context.user_data["team2"]
    await update.message.reply_text(
        "✅ H2H enregistrés !\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🏁 *TEMPS RÉGLEMENTAIRE*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*① Cote 1X2*\n"
        f"Entrez : Victoire *{t1}* | *Nul* | Victoire *{t2}*\n"
        f"Ex: `2.10 3.20 3.50`",
        parse_mode="Markdown")
    return ENTER_1X2_FULL

# ══════════════════════════════════════════════════════════
#  TEMPS RÉGLEMENTAIRE
# ══════════════════════════════════════════════════════════

async def enter_1x2_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_three(update.message.text)
    if not v:
        await ask(update, ERR3); return ENTER_1X2_FULL
    context.user_data["1x2_full"] = {"w1": v[0], "x": v[1], "w2": v[2]}
    await ask(update,
        "*② Les deux équipes vont marquer (BTTS)*\n"
        "Entrez : *Oui* | *Non*\nEx: `1.65 2.10`")
    return ENTER_BTTS_FULL

async def enter_btts_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_BTTS_FULL
    context.user_data["btts_full"] = {"yes": v[0], "no": v[1]}
    await ask(update,
        "*③ Chaque équipe marque 2 buts ou plus*\n"
        "Entrez : *Oui* | *Non*\nEx: `3.98 1.20`")
    return ENTER_BTTS2_FULL

async def enter_btts2_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_BTTS2_FULL
    context.user_data["btts2_full"] = {"yes": v[0], "no": v[1]}
    await ask(update,
        "*④ TOTAL — Nombre de buts*\n\n"
        "*Total 0.5* (Over | Under)\nEx: `1.12 6.00`")
    return ENTER_TOTAL_05

async def enter_total_05(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL_05
    context.user_data["total_05"] = v
    await ask(update, "*Total 1.5* (Over | Under)\nEx: `1.35 3.10`")
    return ENTER_TOTAL_15

async def enter_total_15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL_15
    context.user_data["total_15"] = v
    await ask(update, "*Total 2.5* (Over | Under)\nEx: `1.88 1.88`")
    return ENTER_TOTAL_25

async def enter_total_25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL_25
    context.user_data["total_25"] = v
    await ask(update, "*Total 3.5* (Over | Under)\nEx: `2.90 1.42`")
    return ENTER_TOTAL_35

async def enter_total_35(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL_35
    context.user_data["total_35"] = v
    await ask(update, "*Total 4.5* (Over | Under)\nEx: `4.80 1.18`")
    return ENTER_TOTAL_45

async def enter_total_45(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL_45
    context.user_data["total_45"] = v
    t1 = context.user_data["team1"]
    await ask(update,
        f"*⑤ TOTAL 1 — Buts de {t1}*\n\n"
        f"*Total1 0.5* (Over | Under)\nEx: `1.55 2.40`")
    return ENTER_TOTAL1_05

async def enter_total1_05(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL1_05
    context.user_data["total1_05"] = v
    await ask(update, "*Total1 1.5* (Over | Under)\nEx: `2.20 1.65`")
    return ENTER_TOTAL1_15

async def enter_total1_15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL1_15
    context.user_data["total1_15"] = v
    await ask(update, "*Total1 2.5* (Over | Under)\nEx: `4.50 1.22`")
    return ENTER_TOTAL1_25

async def enter_total1_25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL1_25
    context.user_data["total1_25"] = v
    t2 = context.user_data["team2"]
    await ask(update,
        f"*⑥ TOTAL 2 — Buts de {t2}*\n\n"
        f"*Total2 0.5* (Over | Under)\nEx: `1.70 2.10`")
    return ENTER_TOTAL2_05

async def enter_total2_05(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL2_05
    context.user_data["total2_05"] = v
    await ask(update, "*Total2 1.5* (Over | Under)\nEx: `2.60 1.48`")
    return ENTER_TOTAL2_15

async def enter_total2_15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL2_15
    context.user_data["total2_15"] = v
    await ask(update, "*Total2 2.5* (Over | Under)\nEx: `5.50 1.15`")
    return ENTER_TOTAL2_25

async def enter_total2_25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_TOTAL2_25
    context.user_data["total2_25"] = v
    t1, t2 = context.user_data["team1"], context.user_data["team2"]
    await update.message.reply_text(
        "✅ Cotes temps réglementaire enregistrées !\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🕐 *1ÈRE MI-TEMPS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*① Cote 1X2 Mi-Temps*\n"
        f"Entrez : Victoire *{t1}* | *Nul* | Victoire *{t2}*\n"
        f"Ex: `2.80 2.50 3.80`",
        parse_mode="Markdown")
    return ENTER_1X2_MT

# ══════════════════════════════════════════════════════════
#  1ÈRE MI-TEMPS
# ══════════════════════════════════════════════════════════

async def enter_1x2_mt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_three(update.message.text)
    if not v:
        await ask(update, ERR3); return ENTER_1X2_MT
    context.user_data["1x2_mt"] = {"w1": v[0], "x": v[1], "w2": v[2]}
    await ask(update,
        "*② BTTS Mi-Temps*\n"
        "Les deux équipes vont marquer à la MT :\n"
        "Entrez : *Oui* | *Non*\nEx: `2.90 1.38`")
    return ENTER_BTTS_MT

async def enter_btts_mt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_BTTS_MT
    context.user_data["btts_mt"] = {"yes": v[0], "no": v[1]}
    await ask(update,
        "*③ Chaque équipe marque 2 buts ou plus (MT)*\n"
        "Entrez : *Oui* | *Non*\nEx: `9.50 1.05`")
    return ENTER_BTTS2_MT

async def enter_btts2_mt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_BTTS2_MT
    context.user_data["btts2_mt"] = {"yes": v[0], "no": v[1]}
    await ask(update,
        "*④ TOTAL MT — Nombre de buts*\n\n"
        "*Total MT 0.5* (Over | Under)\nEx: `1.28 3.60`")
    return ENTER_MT_05

async def enter_mt_05(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_MT_05
    context.user_data["mt_total_05"] = v
    await ask(update, "*Total MT 1.5* (Over | Under)\nEx: `2.10 1.72`")
    return ENTER_MT_15

async def enter_mt_15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_MT_15
    context.user_data["mt_total_15"] = v
    await ask(update, "*Total MT 2.5* (Over | Under)\nEx: `4.00 1.24`")
    return ENTER_MT_25

async def enter_mt_25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_MT_25
    context.user_data["mt_total_25"] = v
    await ask(update, "*Total MT 3.5* (Over | Under)\nEx: `9.00 1.08`")
    return ENTER_MT_35

async def enter_mt_35(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_MT_35
    context.user_data["mt_total_35"] = v
    t1 = context.user_data["team1"]
    await ask(update,
        f"*⑤ TOTAL 1 MT — Buts de {t1}*\n\n"
        f"*Total1 MT 0.5* (Over | Under)\nEx: `1.80 1.95`")
    return ENTER_MT1_05

async def enter_mt1_05(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_MT1_05
    context.user_data["mt_total1_05"] = v
    await ask(update, "*Total1 MT 1.5* (Over | Under)\nEx: `3.50 1.30`")
    return ENTER_MT1_15

async def enter_mt1_15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_MT1_15
    context.user_data["mt_total1_15"] = v
    t2 = context.user_data["team2"]
    await ask(update,
        f"*⑥ TOTAL 2 MT — Buts de {t2}*\n\n"
        f"*Total2 MT 0.5* (Over | Under)\nEx: `2.00 1.80`")
    return ENTER_MT2_05

async def enter_mt2_05(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_MT2_05
    context.user_data["mt_total2_05"] = v
    await ask(update, "*Total2 MT 1.5* (Over | Under)\nEx: `4.20 1.22`")
    return ENTER_MT2_15

async def enter_mt2_15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = parse_two(update.message.text)
    if not v:
        await ask(update, ERR2); return ENTER_MT2_15
    context.user_data["mt_total2_15"] = v

    await update.message.reply_text("⚙️ *Calcul en cours...*", parse_mode="Markdown")
    predictor = ScorePredictor(context.user_data)
    result = predictor.predict()
    await update.message.reply_text(result, parse_mode="Markdown")
    await update.message.reply_text(
        "🔄 Tapez /start pour analyser un nouveau match.",
        reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Analyse annulée. Tapez /start.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    import os
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "VOTRE_TOKEN_ICI")
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_LEAGUE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_league)],
            ENTER_TEAMS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_teams)],
            ENTER_H2H:        [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_h2h)],
            # Temps réglementaire
            ENTER_1X2_FULL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_1x2_full)],
            ENTER_BTTS_FULL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_btts_full)],
            ENTER_BTTS2_FULL: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_btts2_full)],
            ENTER_TOTAL_05:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total_05)],
            ENTER_TOTAL_15:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total_15)],
            ENTER_TOTAL_25:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total_25)],
            ENTER_TOTAL_35:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total_35)],
            ENTER_TOTAL_45:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total_45)],
            ENTER_TOTAL1_05:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total1_05)],
            ENTER_TOTAL1_15:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total1_15)],
            ENTER_TOTAL1_25:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total1_25)],
            ENTER_TOTAL2_05:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total2_05)],
            ENTER_TOTAL2_15:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total2_15)],
            ENTER_TOTAL2_25:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total2_25)],
            # 1ère mi-temps
            ENTER_1X2_MT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_1x2_mt)],
            ENTER_BTTS_MT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_btts_mt)],
            ENTER_BTTS2_MT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_btts2_mt)],
            ENTER_MT_05:      [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt_05)],
            ENTER_MT_15:      [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt_15)],
            ENTER_MT_25:      [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt_25)],
            ENTER_MT_35:      [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt_35)],
            ENTER_MT1_05:     [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt1_05)],
            ENTER_MT1_15:     [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt1_15)],
            ENTER_MT2_05:     [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt2_05)],
            ENTER_MT2_15:     [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_mt2_15)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    logger.info("Bot démarré ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
