import asyncio
import nest_asyncio
import logging
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Load token from .env file
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")  # Your channel ID
if CHANNEL_ID and CHANNEL_ID.startswith("-100"):
    CHANNEL_ID = int(CHANNEL_ID)
PRODUCTION = os.getenv("PRODUCTION", "false").lower() == "true"
WEBHOOK_URL = "https://daysuntiliseeyoubot-production.up.railway.app/webhook"  # Replace with your actual URL


# Global variable to store the target date
target_date = None  # Format: datetime object

# Logging setup
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /start - Welcome message"""
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
        print(f"Setting webhook to: {WEBHOOK_URL}")
        await application.bot.set_webhook(WEBHOOK_URL)
    else:
        print("Webhook is already set. Skipping...")


def main():
    global application
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    async def run():
        """Starts the bot with webhook mode"""
        await set_webhook()
        await application.run_webhook(listen="0.0.0.0", port=3000, url_path="/webhook")
        asyncio.create_task(send_daily_message())  # Background task

    print(f"Running in {'PRODUCTION' if PRODUCTION else 'DEVELOPMENT'} mode")

    try:
        asyncio.run(run())  # This works correctly in Railway
    except RuntimeError:
        print("RuntimeError: Event loop already running. Using create_task instead.")
        loop = asyncio.get_event_loop()
        loop.create_task(run())



if __name__ == "__main__":
    main()
