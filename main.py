# main.py

import os
import logging
import asyncio
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Retrieve environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
PRODUCTION = os.getenv("PRODUCTION", "false").lower() == "true"

# Define the webhook URL based on production status
if PRODUCTION:
    WEBHOOK_URL = "https://daysuntiliseeyoubot-production.up.railway.app/webhook"
else:
    # For local testing, use ngrok or a similar service to expose your localhost
    WEBHOOK_URL = "https://your-ngrok-url.ngrok.io/webhook"

# Verify essential environment variables
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in the environment.")
if not CHANNEL_ID:
    raise ValueError("TELEGRAM_CHANNEL_ID is not set in the environment.")

# Convert CHANNEL_ID to integer if it's a numeric string
if CHANNEL_ID.startswith("-100"):
    CHANNEL_ID = int(CHANNEL_ID)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,  # Set to DEBUG for more detailed logs
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()

# Initialize the Telegram Application
application = Application.builder().token(TOKEN).build()

# Global variable to store the target date
target_date = None  # Will store the countdown target


# Define command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text(
        "Hello! Send me a date (dd-mm-yyyy) to start the countdown or 'None' to reset."
    )


async def set_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles setting the countdown date, restricted to channel admins."""
    global target_date

    # Check if the user is an admin
    user_id = update.message.from_user.id
    chat_member = await context.bot.get_chat_member(CHANNEL_ID, user_id)

    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("You are not authorized to set the date.")
        logger.info(f"Unauthorized user {user_id} attempted to set date.")
        return

    text = update.message.text.strip()
    logger.info(f"User {user_id} submitted date input: {text}")

    if text.lower() == "none":
        target_date = None
        await update.message.reply_text("Countdown reset. Future posts will show ∞.")
        logger.info(f"Countdown reset by user {user_id}.")
    else:
        try:
            target_date = datetime.strptime(text, "%d-%m-%Y")
            await update.message.reply_text(
                f"Countdown set to {target_date.strftime('%d-%m-%Y')}."
            )
            logger.info(f"Countdown set to {target_date} by user {user_id}.")
        except ValueError:
            await update.message.reply_text("Invalid format! Please use dd-mm-yyyy.")
            logger.warning(f"User {user_id} submitted invalid date format: {text}")


# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, set_date))


async def send_daily_message():
    """Background task to send daily countdown messages at midnight."""
    global target_date
    while True:
        try:
            now = datetime.now()
            # Calculate time until next midnight
            next_run = datetime(year=now.year, month=now.month, day=now.day) + timedelta(days=1)
            sleep_duration = (next_run - now).total_seconds()
            logger.info(f"Sleeping for {sleep_duration} seconds until next run.")
            await asyncio.sleep(sleep_duration)

            if target_date:
                days_left = (target_date - datetime.now().date()).days
                message = str(max(0, days_left))  # Ensure non-negative output
            else:
                message = "∞"  # No date set

            logger.info(f"Posting to channel: {message}")
            try:
                await application.bot.send_message(chat_id=CHANNEL_ID, text=message)
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
        except Exception as e:
            logger.error(f"Error in send_daily_message: {e}")
            await asyncio.sleep(60)  # Wait 1 minute before retrying to prevent tight loop


async def set_webhook():
    """Sets the webhook if it's not already set."""
    webhook_info = await application.bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        logger.info(f"Setting webhook to: {WEBHOOK_URL}")
        await application.bot.set_webhook(WEBHOOK_URL)
    else:
        logger.info("Webhook is already set. Skipping...")


@app.on_event("startup")
async def on_startup():
    """Runs on application startup."""
    logger.info("Starting up: Initializing and starting Telegram application.")
    await application.initialize()
    await application.start()
    await set_webhook()
    asyncio.create_task(send_daily_message())
    logger.info("Telegram application started and webhook set.")


@app.on_event("shutdown")
async def on_shutdown():
    """Runs on application shutdown."""
    logger.info("Shutting down bot...")
    await application.stop()
    await application.shutdown()
    await application.cleanup()


@app.post("/webhook")
async def webhook_handler(request: Request):
    """Handles incoming webhook updates from Telegram."""
    try:
        update = Update.de_json(await request.json(), application.bot)
        logger.info(f"Received update: {update.to_dict()}")
        await application.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.get("/")
def read_root():
    """Health check endpoint."""
    return {"message": "Bot is running!"}
