# utils.py
import os
import logging
from typing import Tuple
from telebot import TeleBot

logger = logging.getLogger("dating-bot.utils")

# Read env; raise helpful messages
def ensure_env() -> Tuple[str, str, str]:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if not BOT_TOKEN:
        raise SystemExit("Missing BOT_TOKEN env var")
    if not DB_CHANNEL_ID:
        raise SystemExit("Missing DB_CHANNEL_ID env var (e.g. -1001234567890)")
    if not WEBHOOK_URL:
        raise SystemExit("Missing WEBHOOK_URL env var (e.g. https://your-app.onrender.com)")
    return BOT_TOKEN, DB_CHANNEL_ID, WEBHOOK_URL

# Export constants for other modules
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# We'll keep a singleton TeleBot here to be used by db.py (so db.py doesn't import app.py)
# To avoid circular imports, handlers will use the TeleBot instance passed to register_handlers()
_bot_instance = None

def set_bot_instance(bot: TeleBot):
    global _bot_instance
    _bot_instance = bot

def get_bot_instance() -> TeleBot:
    if not _bot_instance:
        raise RuntimeError("Bot instance not set. Call set_bot_instance(bot) in app before using db functions.")
    return _bot_instance
    