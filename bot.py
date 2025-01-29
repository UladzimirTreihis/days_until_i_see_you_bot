import asyncio
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

# Global variable to store the target date
target_date = None  # Format: datetime object

# Logging setup
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /start - Welcome message"""
    await update.message.reply_text("Hello! Send me a date (dd-mm-yyyy) to start the countdown or 'None' to reset.")

async def set_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles input for countdown date"""
    global target_date

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

def main():
    """Main bot loop"""
    global application
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, set_date))

    # Start the background task
    asyncio.create_task(send_daily_message())

    logging.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
