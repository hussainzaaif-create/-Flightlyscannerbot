import os
import sqlite3
import time
import threading
import logging
from datetime import datetime, time as dtime

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
    raise ValueError("BOT_TOKEN missing")

if not SERP_API_KEY:
    raise ValueError("SERP_API_KEY missing")

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
        destination TEXT,
        last_price REAL
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

def get_live_price(origin, destination):
    url = "https://serpapi.com/search.json"

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "currency": "USD",
        "hl": "en",
        "api_key": SERP_API_KEY
    }

    try:
        r = requests.get(url, params=params, timeout=15)

        if r.status_code != 200:
            logging.error(f"Bad response {r.status_code}: {r.text}")
            return None

        data = r.json()

        flights = data.get("best_flights", []) + data.get("other_flights", [])
        prices = [f.get("price") for f in flights if f.get("price")]

        return min(prices) if prices else None

    except Exception as e:
        logging.error(f"Live price error: {e}")
        return None

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
        "✈️ Welcome to Flightly!\nTrack real flight price drops.",
        reply_markup=main_menu()
    )

# ================= CALLBACKS =================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    data = q.data

    if data == "menu":
        context.user_data.clear()
        await q.edit_message_text("Main Menu", reply_markup=main_menu())

    elif data == "add_route":
        context.user_data["adding_route"] = True
        await q.edit_message_text("Send route like:\nMLE DXB")

    # ✅ FIXED: Removed hardcoded MLE-DXB and replaced with user routes
    elif data == "deals":
        if not is_premium(user_id):
            await q.edit_message_text("🔒 Premium required", reply_markup=upgrade_menu())
            return

        with db_lock:
            cur.execute("SELECT origin, destination FROM routes WHERE user_id=?", (user_id,))
            routes = cur.fetchall()

        if not routes:
            await q.edit_message_text("No routes yet. Add one first ✈️")
            return

        messages = []

        for origin, destination in routes:
            price = get_live_price(origin, destination)

            if price:
                messages.append(f"{origin} → {destination} 💰 ${price}")
            else:
                messages.append(f"{origin} → {destination} ❌ no data")

        await q.edit_message_text(
            "🌍 Your Routes:\n\n" + "\n".join(messages)
        )

    elif data == "upgrade":
        await q.edit_message_text("Upgrade Flightly", reply_markup=upgrade_menu())

    elif data == "buy_monthly":
        await context.bot.send_invoice(
            chat_id=user_id,
            title="Flightly Monthly",
            description="Premium access",
            payload="monthly",
            provider_token="YOUR_PROVIDER_TOKEN_HERE",
            currency="USD",
            prices=[LabeledPrice("Monthly", MONTHLY_STARS)]
        )

    elif data == "buy_yearly":
        await context.bot.send_invoice(
            chat_id=user_id,
            title="Flightly Yearly",
            description="Premium access",
            payload="yearly",
            provider_token="YOUR_PROVIDER_TOKEN_HERE",
            currency="USD",
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

# ================= MESSAGE HANDLER =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if context.user_data.get("adding_route"):
        try:
            origin, destination = update.message.text.upper().split()

            with db_lock:
                cur.execute(
                    "INSERT INTO routes (user_id, origin, destination, last_price) VALUES (?, ?, ?, ?)",
                    (user_id, origin, destination, None)
                )
                conn.commit()

            context.user_data["adding_route"] = False

            await update.message.reply_text(
                f"✅ Tracking {origin} → {destination}",
                reply_markup=main_menu()
            )

        except:
            await update.message.reply_text("Invalid format. Use: MLE DXB")

# ================= DAILY JOB =================

async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Running price tracker...")

    with db_lock:
        cur.execute("SELECT id, user_id, origin, destination, last_price FROM routes")
        routes = cur.fetchall()

    for route_id, user_id, origin, destination, last_price in routes:
        new_price = get_live_price(origin, destination)

        if not new_price:
            continue

        if last_price is None:
            with db_lock:
                cur.execute(
                    "UPDATE routes SET last_price=? WHERE id=?",
                    (new_price, route_id)
                )
                conn.commit()
            continue

        if new_price < last_price:
            drop = last_price - new_price

            msg = (
                f"🚨 Price Drop!\n\n"
                f"{origin} → {destination}\n"
                f"💰 ${new_price} (was ${last_price})\n"
                f"🔻 Saved ${drop}"
            )

            try:
                await context.bot.send_message(user_id, msg)
            except Exception as e:
                logging.error(f"Send failed {user_id}: {e}")

        with db_lock:
            cur.execute(
                "UPDATE routes SET last_price=? WHERE id=?",
                (new_price, route_id)
            )
            conn.commit()

# ================= MAIN =================

def main():
    logging.info("Starting Flightly...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    if app.job_queue:
        app.job_queue.run_daily(daily_job, time=dtime(hour=9, minute=0))
        logging.info("Daily job scheduled")

    logging.info("Bot running...")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
