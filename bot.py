import os
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
if CHANNEL_ID and CHANNEL_ID.startswith("-100"):
    CHANNEL_ID = int(CHANNEL_ID)
PRODUCTION = os.getenv("PRODUCTION", "false").lower() == "true"
PORT = int(os.getenv("PORT", 8080))

WEBHOOK_URL = "https://daysuntiliseeyoubot-production.up.railway.app/webhook"  # Change this

# Logging setup
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Flask app
app = Flask(__name__)

# Telegram application
application = Application.builder().token(TOKEN).build()

# Global variable for target date
target_date = None  # Will store the countdown target

@app.route("/", methods=["GET"])
def index():
    return "Bot is running!", 200

@app.route("/webhook", methods=["POST"])
async def webhook():
    """Handles incoming Telegram updates"""
    update = Update.de_json(request.get_json(), application.bot)
    await application.process_update(update)
    return "OK", 200

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command"""
    await update.message.reply_text("Hello! Send me a date (dd-mm-yyyy) to start the countdown or 'None' to reset.")

async def set_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restricts input to only the channel admin"""
    global target_date

    # Check if the sender is an admin
    user_id = update.message.from_user.id
    chat_member = await context.bot.get_chat_member(CHANNEL_ID, user_id)

    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("You are not authorized to set the date.")
        return

    text = update.message.text.strip()
    if text.lower() == "none":
        target_date = None
        await update.message.reply_text("Countdown reset. Future posts will show ∞.")
    else:
        try:
            target_date = datetime.strptime(text, "%d-%m-%Y")
            await update.message.reply_text(f"Countdown set to {target_date.strftime('%d-%m-%Y')}.")
        except ValueError:
            await update.message.reply_text("Invalid format! Please use dd-mm-yyyy.")

async def send_daily_message():
    """Sends the daily countdown message at 00:00"""
    global target_date
    while True:
        now = datetime.now()
        next_run = datetime(now.year, now.month, now.day) + timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())  # Sleep until midnight
        
        if target_date:
            days_left = (target_date - datetime.now().date()).days
            message = str(max(0, days_left))  # Ensure non-negative output
        else:
            message = "∞"  # No date set
        
        logging.info(f"Posting to channel: {message}")
        try:
            await application.bot.send_message(chat_id=CHANNEL_ID, text=message)
        except Exception as e:
            logging.error(f"Failed to send message: {e}")

async def set_webhook():
    """Sets the webhook only if it is not already set"""
    webhook_info = await application.bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        logging.info(f"Setting webhook to: {WEBHOOK_URL}")
        await application.bot.set_webhook(WEBHOOK_URL)
    else:
        logging.info("Webhook is already set. Skipping...")

def start_background_task():
    """Runs the send_daily_message task in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_daily_message())

def main():
    """Starts the bot"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, set_date))

    # Set webhook before running Flask
    asyncio.run(set_webhook())

    # Start background task for daily messages
    threading.Thread(target=start_background_task, daemon=True).start()

    # Run Flask
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
