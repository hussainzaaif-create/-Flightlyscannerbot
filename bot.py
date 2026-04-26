import os
import sqlite3
import time
import threading
import logging
from datetime import datetime, timedelta

import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    filters,
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
SERP_API_KEY = os.getenv("SERP_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID") or 0)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing in environment variables")

if not SERP_API_KEY:
    raise ValueError("SERP_API_KEY missing in environment variables")

MONTHLY_STARS = 300
YEARLY_STARS = 2100

# ================= LOGGING =================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ================= DB =================

conn = sqlite3.connect("flightly.db", check_same_thread=False)
cur = conn.cursor()
db_lock = threading.Lock()

with db_lock:
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        subscription_expiry INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        origin TEXT,
        destination TEXT
    )
    """)
    conn.commit()

# ================= HELPERS =================

def now():
    return int(time.time())

def get_user(user_id):
    with db_lock:
        cur.execute("SELECT id, subscription_expiry FROM users WHERE id=?", (user_id,))
        row = cur.fetchone()

        if not row:
            cur.execute(
                "INSERT INTO users (id, subscription_expiry) VALUES (?, ?)",
                (user_id, 0)
            )
            conn.commit()
            return (user_id, 0)

        return row

def update_user(user_id, expiry):
    with db_lock:
        cur.execute(
            "UPDATE users SET subscription_expiry=? WHERE id=?",
            (expiry, user_id)
        )
        conn.commit()

def is_premium(user_id):
    _, expiry = get_user(user_id)
    return expiry > now()

# ================= FLIGHT DATA =================

def get_cheapest_flight(origin, destination):
    cheapest_price = None
    cheapest_date = None

    for i in range(1, 8):
        date = (datetime.utcnow() + timedelta(days=i)).strftime("%Y-%m-%d")

        url = "https://serpapi.com/search.json"

        params = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": date,
            "currency": "USD",
            "hl": "en",
            "api_key": SERP_API_KEY
        }

        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()

            best = data.get("best_flights", [])
            other = data.get("other_flights", [])
            flights = best + other

            if not flights:
                continue

            for f in flights:
                price = f.get("price")
                if price is None:
                    continue

                if cheapest_price is None or price < cheapest_price:
                    cheapest_price = price
                    cheapest_date = date

        except Exception as e:
            logging.error(f"Flight fetch error: {e}")

    return cheapest_price, cheapest_date

# ================= UI =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Route", callback_data="add_route")],
        [InlineKeyboardButton("🌍 Deals", callback_data="deals")],
        [InlineKeyboardButton("💎 Upgrade", callback_data="upgrade")]
    ])

def upgrade_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Monthly", callback_data="buy_monthly")],
        [InlineKeyboardButton("⭐ Yearly", callback_data="buy_yearly")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✈️ Welcome to Flightly!\nTrack real cheap flights daily.",
        reply_markup=main_menu()
    )

# ================= CALLBACKS =================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    data = q.data

    if data == "menu":
        await q.edit_message_text("Main Menu", reply_markup=main_menu())

    elif data == "add_route":
        await q.edit_message_text("Feature coming soon ✈️")

    elif data == "deals":
        if not is_premium(user_id):
            await q.edit_message_text("🔒 Premium required", reply_markup=upgrade_menu())
            return

        price, date = get_cheapest_flight("MLE", "DXB")

        if price:
            msg = f"🔥 Cheapest Flight\n\nMLE → DXB\n💰 ${price}\n📅 {date}"
        else:
            msg = "⚠️ Could not fetch deals right now"

        await q.edit_message_text(msg)

    elif data == "upgrade":
        await q.edit_message_text("Upgrade Flightly", reply_markup=upgrade_menu())

    elif data == "buy_monthly":
        await context.bot.send_invoice(
            chat_id=user_id,
            title="Flightly Monthly",
            description="Premium access",
            payload="monthly",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("Monthly", MONTHLY_STARS)]
        )

    elif data == "buy_yearly":
        await context.bot.send_invoice(
            chat_id=user_id,
            title="Flightly Yearly",
            description="Premium access",
            payload="yearly",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("Yearly", YEARLY_STARS)]
        )

# ================= PAYMENTS =================

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    payload = update.message.successful_payment.invoice_payload

    extension = 30 * 86400 if payload == "monthly" else 365 * 86400

    _, expiry = get_user(user_id)
    base = max(expiry, now())

    update_user(user_id, base + extension)

    await update.message.reply_text("✅ Premium Activated!", reply_markup=main_menu())

# ================= BROADCAST =================

broadcast_mode = {}

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    broadcast_mode[ADMIN_ID] = True
    await update.message.reply_text("Send broadcast message now")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if broadcast_mode.get(ADMIN_ID) and user_id == ADMIN_ID:
        text = update.message.text or ""

        with db_lock:
            cur.execute("SELECT id FROM users")
            users = cur.fetchall()

        sent = 0

        for u in users:
            try:
                await context.bot.send_message(u[0], text)
                sent += 1
            except Exception as e:
                logging.error(f"Broadcast failed {u[0]}: {e}")

        broadcast_mode[ADMIN_ID] = False
        await update.message.reply_text(f"Sent to {sent} users")

# ================= DAILY JOB =================

async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    with db_lock:
        cur.execute("SELECT id FROM users")
        users = cur.fetchall()

    price, date = get_cheapest_flight("MLE", "DXB")

    if price:
        message = f"✈️ Flightly Daily Deal\n\nMLE → DXB\n💰 ${price}\n📅 {date}"
    else:
        message = "⚠️ Could not fetch flight deals today"

    for u in users:
        try:
            await context.bot.send_message(u[0], message)
        except Exception as e:
            logging.error(f"Daily send failed {u[0]}: {e}")

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    if app.job_queue:
        app.job_queue.run_daily(
            daily_job,
            time=datetime.strptime("09:00", "%H:%M").time()
        )

    print("Flightly running...")
    app.run_polling()

if __name__ == "__main__":
    main()
