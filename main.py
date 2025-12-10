"""
Advanced Telegram Dating Bot (single-file Render-ready)

Features:
- Flask + webhook (works with gunicorn on Render)
- Telegram channel pinned-message as JSON DB
- Registration with photo, name, age, gender, interest, city, bio
- VIP vs Free (fake profiles for free users)
- Browse, Like, Skip, Matches, Likes-you
- Admin panel: /init_db (safe), /grant_vip, /revoke_vip, /broadcast, /delete_user
- Reply keyboard + Inline keyboards
- Safe DB save (checks message size)
- Health endpoints for Render
"""

import os
import time
import json
import logging
from typing import Dict, Any

from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ---------------- logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dating-bot")

# ---------------- env / config ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")  # e.g. -1001234567890
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x) for x in ADMIN_IDS_ENV.split(",") if x.strip().isdigit()]
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-app.onrender.com

if not BOT_TOKEN or not DB_CHANNEL_ID or not WEBHOOK_URL:
    logger.error("Missing one of required env vars: BOT_TOKEN, DB_CHANNEL_ID, WEBHOOK_URL")
    raise SystemExit("Set BOT_TOKEN, DB_CHANNEL_ID, WEBHOOK_URL as env vars before running.")

# ---------------- bot + flask ----------------
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ---------------- in-memory registration state ----------------
REG_STEP: Dict[int, str] = {}
TEMP_BUFFER: Dict[int, Dict[str, Any]] = {}

# ---------------- fake profiles ----------------
FAKE_PROFILES_MALE = [
    {"name": "Rahul", "age": 24, "city": "Delhi", "bio": "Coffee & coding.", "photo": "https://picsum.photos/400?random=11"},
    {"name": "Aman", "age": 26, "city": "Mumbai", "bio": "Traveler.", "photo": "https://picsum.photos/400?random=12"},
]
FAKE_PROFILES_FEMALE = [
    {"name": "Priya", "age": 22, "city": "Delhi", "bio": "Bookworm.", "photo": "https://picsum.photos/400?random=21"},
    {"name": "Anjali", "age": 24, "city": "Pune", "bio": "Artist.", "photo": "https://picsum.photos/400?random=22"},
]

# ---------------- DB helpers (channel pinned message) ----------------
DB_CHAR_LIMIT = 3800  # safe margin under Telegram message limit

def _get_pinned_message():
    """Return pinned_message object or None"""
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        return getattr(chat, "pinned_message", None)
    except Exception as e:
        logger.exception("Failed to get pinned message: %s", e)
        return None

def load_db() -> Dict[str, Any]:
    """
    Load DB JSON from pinned message. If not found or invalid, returns default structure.
    """
    try:
        pinned = _get_pinned_message()
        if pinned and getattr(pinned, "text", None):
            try:
                return json.loads(pinned.text)
            except Exception as e:
                logger.warning("Pinned message JSON parse error: %s", e)
                return {"users": {}, "meta": {}}
        return {"users": {}, "meta": {}}
    except Exception as e:
        logger.exception("load_db error: %s", e)
        return {"users": {}, "meta": {}}

def save_db(db: Dict[str, Any]) -> bool:
    """
    Write DB JSON into pinned message (create+pin if not exists).
    Returns True on success.
    """
    try:
        text = json.dumps(db, ensure_ascii=False, indent=2)
        if len(text) > DB_CHAR_LIMIT:
            logger.error("DB JSON too large (%d > %d).", len(text), DB_CHAR_LIMIT)
            return False
        pinned = _get_pinned_message()
        if pinned:
            bot.edit_message_text(chat_id=DB_CHANNEL_ID, message_id=pinned.message_id, text=text)
            return True
        else:
            m = bot.send_message(DB_CHANNEL_ID, text)
            time.sleep(0.5)
            bot.pin_chat_message(DB_CHANNEL_ID, m.message_id, disable_notification=True)
            return True
    except Exception as e:
        logger.exception("save_db error: %s", e)
        return False

def safe_init_db(created_by) -> bool:
    """
    Initialize DB if it doesn't exist yet. Does not wipe existing data.
    """
    db = load_db()
    if db.get("users"):
        # already exists; update meta only
        db.setdefault("meta", {})["last_init_by"] = created_by
        db["meta"]["last_init_at"] = int(time.time())
        return save_db(db)
    db = {"users": {}, "meta": {"created_by": created_by, "created_at": int(time.time())}}
    return save_db(db)

def get_user_record(tgid: int):
    db = load_db()
    return db.get("users", {}).get(str(tgid))

def save_user_record(tgid: int, record: Dict[str, Any]) -> bool:
    db = load_db()
    db.setdefault("users", {})[str(tgid)] = record
    return save_db(db)

def delete_user_record(tgid: int) -> bool:
    db = load_db()
    users = db.get("users", {})
    if str(tgid) in users:
        del users[str(tgid)]
        db["users"] = users
        return save_db(db)
    return False

# ---------------- keyboards ----------------
def main_menu_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("/menu"),
        KeyboardButton("/profile"),
        KeyboardButton("/profiles"),
        KeyboardButton("/buy"),
        KeyboardButton("/help"),
    )
    return kb

def inline_main_menu():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("👤 Profile", callback_data="menu_profile"),
        InlineKeyboardButton("👀 Browse", callback_data="menu_browse"),
    )
    markup.row(
        InlineKeyboardButton("💎 VIP", callback_data="menu_vip"),
        InlineKeyboardButton("🛠 Admin", callback_data="menu_admin"),    return markup

def profile_buttons(target_id: int, vip: bool):
    markup = InlineKeyboardMarkup()
    if vip:
        markup.row(
            InlineKeyboardButton("❤️ Like", callback_data=f"like_{target_id}"),
            InlineKeyboardButton("❌ Skip", callback_data=f"skip_{target_id}")
        )
    else:
        markup.row(
            InlineKeyboardButton("❤️ Like (Preview)", callback_data="fake_like"),
            InlineKeyboardButton("➡ Next", callback_data="fake_next")
        )
        markup.row(InlineKeyboardButton("🌟 Buy VIP", callback_data="buy_vip"))
    return markup

# ---------------- bot handlers ----------------
# --- UNIFIED DIAGNOSTIC HANDLER ---
@bot.message_handler(commands=["start", "menu", "init_db"])
def cmd_unified_test(message):
    uid = message.chat.id
    try:
        bot.send_message(uid, 
                         "✅ **SYSTEM CHECK SUCCESS!** The core is working.",
                         parse_mode="HTML")
        return
    except Exception as e:
        logger.exception("CRITICAL: Failed to send simple diagnostic message.")
        return

# ---------------- webhook + health endpoits ----------------
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        if not json_str:
            return "", 400
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "", 200
    except Exception as e:
        logger.exception("Error processing update: %s", e)
        return "", 500

@app.route("/", methods=["GET"])
def index():
    return "Dating-bot is running", 200

@app.route("/healthz", methods=["GET"])
def healthz():
    return "OK", 200

# ---------------- set webhook (executed on import) ----------------
def set_webhook():
    try:
        full = f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}"
        logger.info("Removing existing webhook (if any)...")
        try:
            bot.remove_webhook()
        except Exception:
            pass
        time.sleep(0.7)
        logger.info("Setting webhook to %s", full)
        bot.set_webhook(url=full)
        logger.info("Webhook set successfully.")
    except Exception as e:
        logger.exception("Failed to set webhook: %s", e)

# Set webhook now (gunicorn workers may call this on import)
set_webhook()

# ---------------- run (development) ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("Starting Flask dev server on port %d", port)
    app.run(host="0.0.0.0", port=port)
