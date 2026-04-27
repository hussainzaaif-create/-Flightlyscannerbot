import os
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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
    raise RuntimeError("BOT_TOKEN missing in environment variables")

# ================= UI HELPERS =================
def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✈️ Search Flights", callback_data="flights"),
            InlineKeyboardButton("💰 Live Prices", callback_data="prices"),
        ],
        [
            InlineKeyboardButton("ℹ️ How to Use", callback_data="help"),
        ],
    ])


def back_to_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="menu")]
    ])

# ================= START COMMAND =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✈️ *Welcome to Flightly*\n\n"
        "Your smart flight assistant.\n\n"
        "👉 What you can do:\n"
        "• Search flights between destinations\n"
        "• View live price updates\n"
        "• Get daily travel insights\n\n"
        "👇 Choose an option below to continue:",
        reply_markup=main_menu(),
        parse_mode="Markdown",
    )

# ================= HELP =================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *How Flightly Works*\n\n"
        "1. Tap *Search Flights* to begin\n"
        "2. Enter your route (e.g. MLE → DXB)\n"
        "3. View available options and pricing\n\n"
        "💡 Tips:\n"
        "• Prices update dynamically (when enabled)\n"
        "• Use Back button anytime to return\n\n"
        "👇 Start below:",
        reply_markup=main_menu(),
        parse_mode="Markdown",
    )

# ================= CALLBACK HANDLER =================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    try:
        # ========== MAIN MENU ==========
        if data == "menu":
            await query.edit_message_text(
                "✈️ *Flightly Main Menu*\n\n"
                "Select what you'd like to do:",
                reply_markup=main_menu(),
                parse_mode="Markdown",
            )

        # ========== FLIGHTS ==========
        elif data == "flights":
            await query.edit_message_text(
                "✈️ *Flight Search*\n\n"
                "To find flights:\n"
                "• Enter your route in this format:\n"
                "  `MLE → DXB`\n\n"
                "• You can later filter by date, price, or airline\n\n"
                "👇 Next step: send your route (feature coming next step).",
                reply_markup=back_to_menu(),
                parse_mode="Markdown",
            )

        # ========== PRICES ==========
        elif data == "prices":
            await query.edit_message_text(
                "💰 *Live Flight Prices*\n\n"
                "Fetching latest fare data...\n\n"
                "⚠️ Note:\n"
                "Live pricing integration must be connected to a flight API.\n"
                "Once enabled, you’ll see real-time fare updates here.",
                reply_markup=back_to_menu(),
                parse_mode="Markdown",
            )

            # SAFE PAYMENT BLOCK (unchanged logic)
            if PAYMENT_PROVIDER_TOKEN:
                try:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="💳 Payment system placeholder (provider token detected but not configured)."
                    )
                except Exception as e:
                    logger.error(f"Payment error: {e}")

        # ========== HELP ==========
        elif data == "help":
            await query.edit_message_text(
                "ℹ️ *How to Use Flightly*\n\n"
                "This bot helps you track and compare flight prices.\n\n"
                "Steps:\n"
                "1. Go to Search Flights\n"
                "2. Enter route (e.g. MLE → DXB)\n"
                "3. Get available options\n\n"
                "Future features:\n"
                "• Price alerts\n"
                "• Daily deal notifications\n"
                "• Cheapest date finder\n\n"
                "👇 Return anytime:",
                reply_markup=back_to_menu(),
                parse_mode="Markdown",
            )

        else:
            await query.edit_message_text(
                "⚠️ Unknown option selected.\n\n"
                "Please return to the main menu.",
                reply_markup=main_menu(),
            )

    except Exception as e:
        logger.error(f"Callback error: {e}")

# ================= ERROR HANDLER =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update error: {context.error}")

# ================= POST INIT =================
async def post_init(app: Application):
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook cleared — safe polling started.")

# ================= MAIN =================
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    logger.info("Flightly bot starting...")

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

# ================= ENTRY =================
if __name__ == "__main__":
    main()
