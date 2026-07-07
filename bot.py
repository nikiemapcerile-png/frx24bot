import logging
import asyncio
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from predictor import ScorePredictor
from scraper import get_fifa_matches, get_match_full_data
from collector import start_collector

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSE_MODE, CHOOSE_LEAGUE, CHOOSE_MATCH, ENTER_TEAMS, ENTER_MT_ODDS, ENTER_FULL_ODDS = range(6)
LEAGUES = ["🇮🇹 FC 25. Italy Championship (Serie A)", "🏆 FC 26. Champions League"]

# ── Format formulaire ──────────────────────────────────────────────────────────
def box(option):
    o = f" {option}".ljust(16)
    return f"┌────────────────┬──────────┐\n│{o}│          │\n└────────────────┴──────────┘"

def make_form_mt(t1, t2):
    items = [
        f"1 ({t1[:8]})", "X (Nul)", f"2 ({t2[:8]})",
        "BTTS Oui", "BTTS Non", "2+ Eq. Oui", "2+ Eq. Non",
        "Tot MT 0.5 Ov", "Tot MT 0.5 Un", "Tot MT 1.5 Ov", "Tot MT 1.5 Un",
        "Tot MT 2.5 Ov", "Tot MT 2.5 Un", "Tot MT 3.5 Ov", "Tot MT 3.5 Un",
        f"{t1[:6]} 0.5 Ov", f"{t1[:6]} 0.5 Un",
        f"{t1[:6]} 1.5 Ov", f"{t1[:6]} 1.5 Un",
        f"{t2[:6]} 0.5 Ov", f"{t2[:6]} 0.5 Un",
        f"{t2[:6]} 1.5 Ov", f"{t2[:6]} 1.5 Un",
    ]
    return "🕐 *1ÈRE MI-TEMPS*\n\n" + "\n".join(box(i) for i in items)

def make_form_full(t1, t2):
    items = [
        f"1 ({t1[:8]})", "X (Nul)", f"2 ({t2[:8]})",
        "BTTS Oui", "BTTS Non", "2+ Eq. Oui", "2+ Eq. Non",
        "Total 0.5 Ov", "Total 0.5 Un", "Total 1.5 Ov", "Total 1.5 Un",
        "Total 2.5 Ov", "Total 2.5 Un", "Total 3.5 Ov", "Total 3.5 Un",
        "Total 4.5 Ov", "Total 4.5 Un",
        f"{t1[:6]} 0.5 Ov", f"{t1[:6]} 0.5 Un",
        f"{t1[:6]} 1.5 Ov", f"{t1[:6]} 1.5 Un",
        f"{t1[:6]} 2.5 Ov", f"{t1[:6]} 2.5 Un",
        f"{t2[:6]} 0.5 Ov", f"{t2[:6]} 0.5 Un",
        f"{t2[:6]} 1.5 Ov", f"{t2[:6]} 1.5 Un",
        f"{t2[:6]} 2.5 Ov", f"{t2[:6]} 2.5 Un",
    ]
    return "🏁 *MATCH COMPLET*\n\n" + "\n".join(box(i) for i in items)

def parse_form(text):
    values = []
    for line in text.splitlines():
        if "│" in line and "─" not in line:
            parts = line.split("│")
            if len(parts) >= 3:
                values.append(parts[2].strip())
    return values

def parse_one(t):
    if not t: return None
    try: return float(t.replace(",","."))
    except: return None

def build_data(values, scope, d):
    def p(i): return parse_one(values[i]) if i < len(values) else None
    if scope == "mt":
        if p(0) and p(1) and p(2): d["1x2_mt"]={"w1":p(0),"x":p(1),"w2":p(2)}
        if p(3) and p(4): d["btts_mt"]={"yes":p(3),"no":p(4)}
        if p(5) and p(6): d["btts2_mt"]={"yes":p(5),"no":p(6)}
        pairs=[("mt_total_05",7),("mt_total_15",9),("mt_total_25",11),("mt_total_35",13),
               ("mt_total1_05",15),("mt_total1_15",17),("mt_total2_05",19),("mt_total2_15",21)]
        for key,i in pairs:
            o,u=p(i),p(i+1)
            if o and u: d[key]=(o,u)
    else:
        if p(0) and p(1) and p(2): d["1x2_full"]={"w1":p(0),"x":p(1),"w2":p(2)}
        if p(3) and p(4): d["btts_full"]={"yes":p(3),"no":p(4)}
        if p(5) and p(6): d["btts2_full"]={"yes":p(5),"no":p(6)}
        pairs=[("total_05",7),("total_15",9),("total_25",11),("total_35",13),("total_45",15),
               ("total1_05",17),("total1_15",19),("total1_25",21),
               ("total2_05",23),("total2_15",25),("total2_25",27)]
        for key,i in pairs:
            o,u=p(i),p(i+1)
            if o and u: d[key]=(o,u)

# ── Handlers ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb=[["🤖 Auto — 1xBet Live"],["✏️ Saisie manuelle"]]
    await update.message.reply_text(
        "╔══════════════════════════╗\n"
        "║  ⚽ *FRX24 BOT*           ║\n"
        "║  Prédiction Score Exact  ║\n"
        "╚══════════════════════════╝\n\n"
        "Comment veux-tu entrer les données ?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return CHOOSE_MODE

async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = update.message.text.strip()
    if "auto" in mode.lower():
        context.user_data["mode"] = "auto"
        msg = await update.message.reply_text(
            "🔄 *Connexion à 1xBet...*\nRécupération des matchs FIFA en cours...",
            parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
        )
        matches = get_fifa_matches()
        if not matches:
            await msg.edit_text("❌ Aucun match FIFA disponible sur 1xBet.\nTapez /start pour réessayer.")
            return ConversationHandler.END
        context.user_data["matches"] = matches
        kb=[]
        for i,m in enumerate(matches[:20]):
            kb.append([InlineKeyboardButton(
                f"⚽ {m['team1']} vs {m['team2']}",
                callback_data=str(i)
            )])
        await msg.edit_text(
            f"✅ *{len(matches)} match(s) FIFA disponible(s)*\n\nChoisissez le match :",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return CHOOSE_MATCH
    else:
        context.user_data["mode"] = "manual"
        kb=[[lg] for lg in LEAGUES]
        await update.message.reply_text(
            "Choisissez le championnat :",
            reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
        )
        return CHOOSE_LEAGUE

async def choose_match_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data)
    matches = context.user_data.get("matches",[])
    if idx >= len(matches):
        await query.edit_message_text("❌ Match invalide."); return ConversationHandler.END
    m = matches[idx]
    await query.edit_message_text(
        f"⏳ *Récupération des cotes...*\n{m['team1']} vs {m['team2']}",
        parse_mode="Markdown"
    )
    data = get_match_full_data(m["id"])
    if not data:
        await query.message.reply_text("❌ Impossible de récupérer les cotes. Tapez /start.")
        return ConversationHandler.END
    league = m["league"].lower()
    data["league"] = "🇮🇹 FC 25. Italy Championship (Serie A)" if any(x in league for x in ["italy","serie","fc 25"]) else "🏆 FC 26. Champions League"
    await query.message.reply_text("⚙️ *Analyse en cours...*", parse_mode="Markdown")
    pred = ScorePredictor(data)
    await query.message.reply_text(pred.predict_mt(), parse_mode="Markdown")
    await asyncio.sleep(1)
    await query.message.reply_text(pred.predict_full(), parse_mode="Markdown")
    await query.message.reply_text("🔄 Tapez /start pour un nouveau match.")
    return ConversationHandler.END

async def choose_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    league = update.message.text.strip()
    if league not in LEAGUES:
        await update.message.reply_text("❌ Choix invalide. Tapez /start."); return CHOOSE_LEAGUE
    context.user_data["league"] = league
    await update.message.reply_text(
        f"✅ *{league}*\n\nEntrez le match :\nEx: `Milano vs Juventus`",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove(),
    )
    return ENTER_TEAMS

async def enter_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    sep = None
    for s in [" vs "," VS "," Vs "]:
        if s in text: sep=s; break
    if not sep:
        await update.message.reply_text("❌ Ex: `Milano vs Juventus`", parse_mode="Markdown")
        return ENTER_TEAMS
    parts = [p.strip() for p in text.split(sep,1)]
    if len(parts)!=2 or not all(parts):
        await update.message.reply_text("❌ Format invalide.", parse_mode="Markdown")
        return ENTER_TEAMS
    context.user_data.update({"team1":parts[0],"team2":parts[1],"h2h":[],"stats_team1":None,"stats_team2":None})
    form = make_form_mt(parts[0],parts[1])
    await update.message.reply_text(
        f"🔍 *{parts[0]} vs {parts[1]}*\n\n"
        "Copiez, remplissez les cotes dans la colonne droite, renvoyez :\n\n"
        f"```\n{form}\n```",
        parse_mode="Markdown"
    )
    return ENTER_MT_ODDS

async def enter_mt_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    values = parse_form(update.message.text)
    d = context.user_data
    if len(values) < 5:
        await update.message.reply_text("❌ Formulaire non reconnu. Recopiez et remplissez.", parse_mode="Markdown")
        return ENTER_MT_ODDS
    build_data(values, "mt", d)
    form = make_form_full(d["team1"], d["team2"])
    await update.message.reply_text(
        f"✅ MT enregistré !\n\nMaintenant le match complet :\n\n```\n{form}\n```",
        parse_mode="Markdown"
    )
    return ENTER_FULL_ODDS

async def enter_full_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    values = parse_form(update.message.text)
    d = context.user_data
    if len(values) < 5:
        await update.message.reply_text("❌ Formulaire non reconnu. Recopiez et remplissez.", parse_mode="Markdown")
        return ENTER_FULL_ODDS
    build_data(values, "full", d)
    await update.message.reply_text("⚙️ *Analyse en cours...*", parse_mode="Markdown")
    pred = ScorePredictor(d)
    await update.message.reply_text(pred.predict_mt(), parse_mode="Markdown")
    await asyncio.sleep(1)
    await update.message.reply_text(pred.predict_full(), parse_mode="Markdown")
    await update.message.reply_text("🔄 Tapez /start pour un nouveau match.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Annulé. Tapez /start.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def post_init(app):
    asyncio.create_task(start_collector())

def main():
    import os
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","VOTRE_TOKEN_ICI")
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start",start)],
        states={
            CHOOSE_MODE:    [MessageHandler(filters.TEXT&~filters.COMMAND,choose_mode)],
            CHOOSE_LEAGUE:  [MessageHandler(filters.TEXT&~filters.COMMAND,choose_league)],
            CHOOSE_MATCH:   [CallbackQueryHandler(choose_match_callback)],
            ENTER_TEAMS:    [MessageHandler(filters.TEXT&~filters.COMMAND,enter_teams)],
            ENTER_MT_ODDS:  [MessageHandler(filters.TEXT&~filters.COMMAND,enter_mt_odds)],
            ENTER_FULL_ODDS:[MessageHandler(filters.TEXT&~filters.COMMAND,enter_full_odds)],
        },
        fallbacks=[CommandHandler("cancel",cancel)],
    )
    app.add_handler(conv)
    logger.info("Bot démarré ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
