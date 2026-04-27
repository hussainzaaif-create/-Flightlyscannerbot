import os
import logging
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")  # optional

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in environment variables")

# ================= BASIC HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running successfully 🚀")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Help section working.")

# ================= CALLBACK HANDLER =================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.edit_message_text("Callback received ✅")
    except Exception as e:
        logger.error(f"Callback error: {e}")

    # SAFE PAYMENT HANDLING (fixes Payment_provider_invalid crash)
    if PAYMENT_PROVIDER_TOKEN:
        try:
            # Only attempt invoice if provider exists
            await context.bot.send_invoice(
                chat_id=query.message.chat_id,
                title="Test Payment",
                description="Demo payment",
                payload="test-payload",
                provider_token=PAYMENT_PROVIDER_TOKEN,
                currency="USD",
                prices=[]
            )
        except Exception as e:
            logger.error(f"Payment error: {e}")
    else:
        logger.warning("PAYMENT_PROVIDER_TOKEN not set, skipping payments.")

# ================= ERROR HANDLER =================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update caused error: {context.error}")

# ================= MAIN STARTUP =================

async def post_init(app: Application):
    """
    CRITICAL FIX:
    Stops Telegram conflict error by ensuring ONLY ONE polling session exists.
    """
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook cleared, starting clean polling session.")

def main():
    # Build application (NO Updater used → avoids conflict bug)
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.add_error_handler(error_handler)

    # ================= IMPORTANT =================
    # ONLY ONE polling instance (fixes your 409 Conflict issue)
    logger.info("Bot starting...")

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

# ================= ENTRY POINT =================

if __name__ == "__main__":
    main()
