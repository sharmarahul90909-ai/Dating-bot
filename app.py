import os
import json
import time
import logging
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment variables ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")  # e.g. -1001234567890
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-app.onrender.com

if not BOT_TOKEN or not DB_CHANNEL_ID or not WEBHOOK_URL:
    logger.error("BOT_TOKEN, DB_CHANNEL_ID, and WEBHOOK_URL must be set.")
    raise SystemExit("Missing required environment variables.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# --- In-memory registration steps ---
REG_STEP = {}
TEMP_BUFFER = {}

# --- Fake profiles for non-VIP users ---
FAKE_PROFILES_MALE = [
    {"name": "Rahul", "age": 24, "city": "Delhi", "bio": "Coffee & coding.", "photo": "https://picsum.photos/400?random=11"},
    {"name": "Aman",  "age": 26, "city": "Mumbai", "bio": "Traveler.", "photo": "https://picsum.photos/400?random=12"},
]
FAKE_PROFILES_FEMALE = [
    {"name": "Priya", "age": 22, "city": "Delhi", "bio": "Bookworm.", "photo": "https://picsum.photos/400?random=21"},
    {"name": "Anjali","age": 24, "city": "Pune",  "bio": "Artist.", "photo": "https://picsum.photos/400?random=22"},
]

# --- DB functions ---
def load_db():
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        if pinned and pinned.text:
            return json.loads(pinned.text)
        return {"users": {}, "meta": {}}
    except Exception as e:
        logger.warning("Failed to load DB: %s", e)
        return {"users": {}, "meta": {}}

def save_db(db):
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        text = json.dumps(db, ensure_ascii=False, indent=2)
        if len(text) > 3800:
            logger.error("DB too big to save in pinned message.")
            return False
        if pinned:
            bot.edit_message_text(chat_id=DB_CHANNEL_ID, message_id=pinned.message_id, text=text)
        else:
            msg = bot.send_message(DB_CHANNEL_ID, text)
            time.sleep(0.5)
            bot.pin_chat_message(DB_CHANNEL_ID, msg.message_id, disable_notification=True)
        return True
    except Exception as e:
        logger.exception("Failed to save DB: %s", e)
        return False

def get_user(uid):
    db = load_db()
    return db.get("users", {}).get(str(uid))

def save_user(uid, record):
    db = load_db()
    if "users" not in db:
        db["users"] = {}
    db["users"][str(uid)] = record
    return save_db(db)

def safe_init_db(admin_id):
    """Create DB if not exists, but do not wipe existing users."""
    db = load_db()
    if "meta" not in db:
        db["meta"] = {}
    db["meta"].update({"created_by": admin_id, "created_at": int(time.time())})
    return save_db(db)

# --- /init_db ---
@bot.message_handler(commands=["init_db"])
def cmd_init_db(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    ok = safe_init_db(message.from_user.id)
    if ok:
        bot.reply_to(message, "DB initialized (existing data preserved).")
    else:
        bot.reply_to(message, "Failed to init DB. Check permissions.")

# --- /start ---
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    rec = get_user(uid)
    if rec and rec.get("registered"):
        bot.send_message(message.chat.id, f"Welcome back, <b>{rec.get('name')}</b>!\nUse /menu to see options.", parse_mode="HTML")
        return
    TEMP_BUFFER[uid] = {}
    REG_STEP[uid] = "photo"
    bot.send_message(message.chat.id, "Step 1: Send your profile photo.")

# --- Photo handler ---
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    uid = message.from_user.id
    step = REG_STEP.get(uid)
    if step != "photo":
        bot.reply_to(message, "Not expecting photo now.")
        return
    file_id = message.photo[-1].file_id
    TEMP_BUFFER[uid]["photo_file_id"] = file_id
    REG_STEP[uid] = "name"
    bot.send_message(message.chat.id, "✔ Photo saved. Step 2: Enter your full name.")

# --- Text handler for registration & commands ---
@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    uid = message.from_user.id
    text = message.text.strip()
    # admin commands and /menu handled elsewhere
    if text.startswith("/"):
        if text == "/menu":
            send_menu(uid)
        return
    step = REG_STEP.get(uid)
    if not step:
        bot.send_message(uid, "Use /menu to see options.")
        return

    buf = TEMP_BUFFER.get(uid, {})
    if step == "name":
        buf["name"] = text
        REG_STEP[uid] = "age"
        bot.send_message(uid, "Step 3: Enter your age (18+).")
        return
    if step == "age":
        if not text.isdigit() or int(text) < 18:
            bot.send_message(uid, "Enter valid age (18+).")
            return
        buf["age"] = int(text)
        REG_STEP[uid] = "gender"
        bot.send_message(uid, "Step 4: Enter your gender (male/female).")
        return
    if step == "gender":
        if text.lower() not in ("male","female"):
            bot.send_message(uid, "Type male or female.")
            return
        buf["gender"] = text.lower()
        REG_STEP[uid] = "interest"
        bot.send_message(uid, "Step 5: Who do you want to see? (male/female/both)")
        return
    if step == "interest":
        if text.lower() not in ("male","female","both"):
            bot.send_message(uid, "Choose male, female or both.")
            return
        buf["interest"] = text.lower()
        REG_STEP[uid] = "city"
        bot.send_message(uid, "Step 6: Enter your city.")
        return
    if step == "city":
        buf["city"] = text
        REG_STEP[uid] = "bio"
        bot.send_message(uid, "Step 7: Send a short bio about yourself.")
        return
    if step == "bio":
        buf["bio"] = text
        rec = {
            "telegram_id": uid,
            "photo_file_id": buf.get("photo_file_id"),
            "name": buf.get("name"),
            "age": buf.get("age"),
            "gender": buf.get("gender"),
            "interest": buf.get("interest"),
            "city": buf.get("city"),
            "bio": buf.get("bio"),
            "registered": True,
            "vip": False,
            "likes": [],
            "liked_by": [],
            "matches": [],
            "current_fake_index": 0,
            "current_real_index": 0,
            "coins": 20,
            "created_at": int(time.time())
        }
        ok = save_user(uid, rec)
        REG_STEP.pop(uid, None)
        TEMP_BUFFER.pop(uid, None)
        if ok:
            bot.send_message(uid, "🎉 Registration complete! Use /menu to browse options.")
        else:
            bot.send_message(uid, "Failed to save profile — contact admin.")

# --- /menu UI buttons ---
def send_menu(uid):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("/profile", callback_data="profile"),
        InlineKeyboardButton("/profiles", callback_data="profiles")
    )
    markup.row(
        InlineKeyboardButton("/likes_you", callback_data="likes_you"),
        InlineKeyboardButton("/matches", callback_data="matches")
    )
    markup.row(
        InlineKeyboardButton("/buy", callback_data="buy"),
        InlineKeyboardButton("/paysupport", callback_data="paysupport")
    )
    markup.row(
        InlineKeyboardButton("/help", callback_data="help")
    )
    bot.send_message(uid, "💠 Main Menu", reply_markup=markup)

# --- Webhook route ---
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "", 200

# --- Set webhook on startup ---
def set_webhook():
    bot.remove_webhook()
    full_url = f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}"
    bot.set_webhook(url=full_url)
    logger.info("Webhook set: %s", full_url)

# --- Start Flask app ---
if __name__ == "__main__":
    set_webhook()
    print("Run with gunicorn on Render")
    
