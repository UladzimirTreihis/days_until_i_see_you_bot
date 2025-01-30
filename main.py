# main.py

import os
import logging
import asyncio
from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

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
import aiofiles

# Load environment variables from .env
load_dotenv()

# Set timezone 
EUROPE_TZ = ZoneInfo("Europe/Berlin")

# Define the path to data.json in the mounted volume
DATA_FILE = "/data/data.json"

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
if isinstance(CHANNEL_ID, str) and CHANNEL_ID.startswith("-100"):
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

# Helper functions for writing JSON data

async def write_data(data):
    """Writes data to the JSON file asynchronously."""
    async with aiofiles.open(DATA_FILE, mode='w') as f:
        await f.write(json.dumps(data, indent=4))

# Helper functions for reading JSON data
async def read_data():
    """Reads data from the JSON file asynchronously."""
    try:
        async with aiofiles.open(DATA_FILE, mode='r') as f:
            content = await f.read()
            data = json.loads(content)
            # Ensure all required keys are present
            if 'intervals' not in data:
                data['intervals'] = []
            if 'last_event_date' not in data:
                data['last_event_date'] = None
            if 'target_date' not in data:
                data['target_date'] = None
            return data
    except FileNotFoundError:
        # If the file doesn't exist, return default structure
        logger.info(f"{DATA_FILE} not found. Creating a new one.")
        data = {"intervals": [], "last_event_date": None, "target_date": None}
        await write_data(data)
        return data
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        # Optionally, reset the data
        data = {"intervals": [], "last_event_date": None, "target_date": None}
        await write_data(data)
        return data

# Define command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text(
        "Hello! Send me a date (dd-mm-yyyy) to start the countdown or 'None' to reset."
    )
    logger.info(f"User {update.message.from_user.id} initiated /start command.")

async def set_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles setting the countdown date, restricted to channel admins."""
    user_id = update.message.from_user.id
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
    except Exception as e:
        await update.message.reply_text("Failed to verify your admin status.")
        logger.error(f"Error fetching chat member: {e}")
        return

    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("You are not authorized to set the date.")
        logger.info(f"Unauthorized user {user_id} attempted to set date.")
        return

    text = update.message.text.strip()
    logger.info(f"User {user_id} submitted date input: {text}")

    data = await read_data()
    logger.info(f"Current data: {data}")

    if text.lower() == "none":
        data['target_date'] = None
        data['last_event_date'] = None
        await write_data(data)
        await update.message.reply_text("Countdown reset. Future posts will show the statistical message.")
        logger.info(f"Countdown reset by user {user_id}.")
    else:
        try:
            new_target_date = datetime.strptime(text, "%d-%m-%Y").date()
            current_date = datetime.now(tz=EUROPE_TZ).date()
            if new_target_date < current_date:
                await update.message.reply_text("The date must be in the future.")
                logger.warning(f"User {user_id} tried to set a past date: {new_target_date}")
                return

            data['target_date'] = new_target_date.strftime("%Y-%m-%d")
            data['last_event_date'] = None  # Reset to prevent immediate interval counting
            await write_data(data)
            await update.message.reply_text(f"Countdown set to {new_target_date.strftime('%d-%m-%Y')}.")
            logger.info(f"Countdown set to {new_target_date} by user {user_id}.")
        except ValueError:
            await update.message.reply_text("Invalid format! Please use dd-mm-yyyy or 'none'.")
            logger.warning(f"User {user_id} submitted invalid date format: {text}")

async def print_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to print data.json contents."""
    user_id = update.message.from_user.id
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
    except Exception as e:
        await update.message.reply_text("Failed to verify your admin status.")
        logger.error(f"Error fetching chat member: {e}")
        return

    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("You are not authorized to perform this action.")
        logger.info(f"Unauthorized user {user_id} attempted to print data.")
        return

    data = await read_data()
    data_str = json.dumps(data, indent=4)

    # Telegram has a message character limit (~4096). Handle larger data accordingly.
    if len(data_str) > 4000:
        await update.message.reply_text("data.json is too large to display.")
    else:
        # Send as a code block for better readability
        await update.message.reply_text(f"```\n{data_str}\n```", parse_mode="MarkdownV2")

async def set_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to set data.json with provided JSON."""
    user_id = update.message.from_user.id
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
    except Exception as e:
        await update.message.reply_text("Failed to verify your admin status.")
        logger.error(f"Error fetching chat member: {e}")
        return

    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("You are not authorized to perform this action.")
        logger.info(f"Unauthorized user {user_id} attempted to set data.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /set_data <json>")
        return

    # Join all arguments to form the JSON string
    json_str = ' '.join(context.args)
    try:
        data = json.loads(json_str)
        # Validate required keys
        required_keys = {"intervals", "last_event_date", "target_date"}
        if not required_keys.issubset(data.keys()):
            await update.message.reply_text(f"JSON must contain the following keys: {', '.join(required_keys)}.")
            return
        # Validate types
        if not isinstance(data['intervals'], list):
            await update.message.reply_text("'intervals' must be a list.")
            return
        if data['last_event_date'] is not None:
            try:
                datetime.strptime(data['last_event_date'], "%Y-%m-%d")
            except ValueError:
                await update.message.reply_text("'last_event_date' must be in 'YYYY-MM-DD' format or null.")
                return
        if data['target_date'] is not None:
            try:
                datetime.strptime(data['target_date'], "%Y-%m-%d")
            except ValueError:
                await update.message.reply_text("'target_date' must be in 'YYYY-MM-DD' format or null.")
                return
        # Overwrite data.json
        await write_data(data)
        await update.message.reply_text("data.json has been updated successfully.")
        logger.info(f"data.json updated by user {user_id}.")
    except json.JSONDecodeError as e:
        await update.message.reply_text("Invalid JSON format.")
        logger.error(f"User {user_id} provided invalid JSON: {e}")


# Register handlers with appropriate filters
application.add_handler(
    CommandHandler("start", start, filters=filters.ChatType.PRIVATE)
)
application.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        set_date
    )
)

# Register the /print_data command
application.add_handler(
    CommandHandler("print_data", print_data_command, filters=filters.ChatType.PRIVATE)
)

# Register the /set_data command
application.add_handler(
    CommandHandler("set_data", set_data_command, filters=filters.ChatType.PRIVATE)
)

# Define an error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log the error and send a message to notify the developer."""
    logger.error(f"Exception while handling an update: {context.error}")

# Register the error handler
application.add_error_handler(error_handler)

async def send_daily_message():
    """Background task to send daily countdown messages at midnight European time."""
    while True:
        try:
            now = datetime.now(tz=EUROPE_TZ)
            # Calculate time until next midnight in European time
            next_run = datetime(year=now.year, month=now.month, day=now.day, tzinfo=EUROPE_TZ) + timedelta(days=1)
            sleep_duration = (next_run - now).total_seconds()
            logger.info(f"Sleeping for {sleep_duration} seconds until next run (European midnight).")
            await asyncio.sleep(sleep_duration)

            today = datetime.now(tz=EUROPE_TZ).date()

            data = await read_data()
            target_date_str = data.get("target_date")
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date() if target_date_str else None

            if target_date and target_date == today:
                # Handle event occurrence
                if data['last_event_date']:
                    last_event = datetime.strptime(data['last_event_date'], "%Y-%m-%d").date()
                    if last_event == today:
                        # Consecutive 0s; do not count
                        logger.info("Event occurred again today without resetting target_date.")
                    else:
                        interval = (today - last_event).days
                        data['intervals'].append(interval)
                        logger.info(f"Event occurred. Interval since last event: {interval} days.")
                        data['last_event_date'] = today.strftime("%Y-%m-%d")
                        await write_data(data)
                else:
                    # First event occurrence
                    data['last_event_date'] = today.strftime("%Y-%m-%d")
                    await write_data(data)
                    logger.info("First event occurrence recorded.")

                # Reset target_date
                data['target_date'] = None
                await write_data(data)

            elif not target_date:
                # Generate statistical message based on past intervals
                intervals = data.get("intervals", [])

                if intervals:
                    n_days = sum(intervals) / len(intervals)  # Mean interval
                    lambda_param = 1 / n_days if n_days != 0 else 0

                    # Exponential Distribution: Expected time until next event
                    expected_time = n_days

                    # Poisson Distribution: Probability calculations
                    from math import exp

                    def poisson_prob_at_least_one(lam, days):
                        return 1 - exp(-lam * days)

                    # Calculating probabilities
                    days_prob = poisson_prob_at_least_one(lambda_param, 1) * 100  # Tomorrow
                    week_prob = poisson_prob_at_least_one(lambda_param, 7) * 100  # Within a week
                    month_prob = poisson_prob_at_least_one(lambda_param, 30) * 100  # Within a month
                    year_prob = poisson_prob_at_least_one(lambda_param, 365) * 100  # Within a year

                    # Construct the message
                    message = (
                        f"Based on previous data, expected time until next event: {int(expected_time)} days "
                        f"according to Exponential distribution.\n"
                        f"According to Poisson distribution, the event has {days_prob:.2f}% chance to happen tomorrow, "
                        f"{week_prob:.2f}% chance to happen within a week, "
                        f"{month_prob:.2f}% chance to happen within a month, "
                        f"{year_prob:.2f}% chance to happen within a year."
                    )
                else:
                    # No data available
                    message = (
                        "No historical data available to predict the next event. "
                        "Please set a target date to start the countdown."
                    )
                    logger.info("No intervals data available for statistical message.")

                # Send the message to the channel
                try:
                    await application.bot.send_message(chat_id=CHANNEL_ID, text=message)
                    logger.info("Sent statistical message to channel.")
                except Exception as e:
                    logger.error(f"Failed to send statistical message: {e}")

            else:
                # Send countdown as usual
                days_left = (target_date - today).days
                message = str(max(0, days_left))  # Ensure non-negative
                logger.info(f"Posting countdown to channel: {message}")

                try:
                    await application.bot.send_message(chat_id=CHANNEL_ID, text=message)
                    logger.info("Sent countdown message to channel.")
                except Exception as e:
                    logger.error(f"Failed to send countdown message: {e}")

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
