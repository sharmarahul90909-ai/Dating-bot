import os
import json
import logging
import time
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not DB_CHANNEL_ID or not WEBHOOK_URL:
    raise SystemExit("BOT_TOKEN, DB_CHANNEL_ID, and WEBHOOK_URL must be set!")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# --- In-memory registration ---
REG_STEP = {}
TEMP_BUFFER = {}

# --- Fake profiles ---
FAKE_PROFILES_MALE = [
    {"name": "Rahul", "age": 24, "city": "Delhi", "bio": "Coffee & coding.", "photo": "https://picsum.photos/400?random=11"},
    {"name": "Aman",  "age": 26, "city": "Mumbai", "bio": "Traveler.", "photo": "https://picsum.photos/400?random=12"},
]
FAKE_PROFILES_FEMALE = [
    {"name": "Priya", "age": 22, "city": "Delhi", "bio": "Bookworm.", "photo": "https://picsum.photos/400?random=21"},
    {"name": "Anjali","age": 24, "city": "Pune",  "bio": "Artist.", "photo": "https://picsum.photos/400?random=22"},
]

# --- DB helpers ---
def load_db():
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        if pinned and pinned.text:
            return json.loads(pinned.text)
        return {"users": {}, "meta": {}}
    except:
        return {"users": {}, "meta": {}}

def save_db(db):
    text = json.dumps(db, ensure_ascii=False, indent=2)
    if len(text) > 3800:
        logger.error("DB too big")
        return False
    chat = bot.get_chat(DB_CHANNEL_ID)
    pinned = getattr(chat, "pinned_message", None)
    if pinned:
        bot.edit_message_text(chat_id=DB_CHANNEL_ID, message_id=pinned.message_id, text=text)
    else:
        msg = bot.send_message(DB_CHANNEL_ID, text)
        time.sleep(0.5)
        bot.pin_chat_message(DB_CHANNEL_ID, msg.message_id)
    return True

def get_user(uid):
    db = load_db()
    return db.get("users", {}).get(str(uid))

def save_user(uid, record):
    db = load_db()
    db.setdefault("users", {})[str(uid)] = record
    return save_db(db)

# --- /start ---
@bot.message_handler(commands=["start"])
def start(message):
    uid = message.from_user.id
    rec = get_user(uid)
    if rec and rec.get("registered"):
        bot.send_message(message.chat.id, f"Welcome back, {rec.get('name')}! Use /menu to see options.")
        return
    TEMP_BUFFER[uid] = {}
    REG_STEP[uid] = "photo"
    bot.send_message(message.chat.id, "Step 1: Send your profile photo.")

# --- Photo handler ---
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    uid = message.from_user.id
    if REG_STEP.get(uid) != "photo":
        return
    TEMP_BUFFER[uid]["photo"] = message.photo[-1].file_id
    REG_STEP[uid] = "name"
    bot.send_message(message.chat.id, "Step 2: Send your full name.")

# --- Text handler ---
@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    uid = message.from_user.id
    step = REG_STEP.get(uid)
    if not step:
        return
    text = message.text.strip()
    if step == "name":
        TEMP_BUFFER[uid]["name"] = text
        REG_STEP[uid] = "age"
        bot.send_message(message.chat.id, "Step 3: Enter age (18+).")
    elif step == "age":
        if not text.isdigit() or int(text) < 18:
            bot.send_message(message.chat.id, "Enter valid age 18+")
            return
        TEMP_BUFFER[uid]["age"] = int(text)
        REG_STEP[uid] = "gender"
        bot.send_message(message.chat.id, "Step 4: Gender (male/female).")
    elif step == "gender":
        if text.lower() not in ("male", "female"):
            bot.send_message(message.chat.id, "Type 'male' or 'female'")
            return
        TEMP_BUFFER[uid]["gender"] = text.lower()
        REG_STEP[uid] = "interest"
        bot.send_message(message.chat.id, "Step 5: Interested in (male/female/both).")
    elif step == "interest":
        if text.lower() not in ("male", "female", "both"):
            bot.send_message(message.chat.id, "Choose male/female/both")
            return
        TEMP_BUFFER[uid]["interest"] = text.lower()
        REG_STEP[uid] = "city"
        bot.send_message(message.chat.id, "Step 6: Enter city.")
    elif step == "city":
        TEMP_BUFFER[uid]["city"] = text
        REG_STEP[uid] = "bio"
        bot.send_message(message.chat.id, "Step 7: Enter a short bio.")
    elif step == "bio":
        TEMP_BUFFER[uid]["bio"] = text
        user_record = {
            "telegram_id": uid,
            **TEMP_BUFFER[uid],
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
        if save_user(uid, user_record):
            bot.send_message(message.chat.id, "Registration complete! Use /menu")
        else:
            bot.send_message(message.chat.id, "Failed to save profile. Contact admin.")
        TEMP_BUFFER.pop(uid)
        REG_STEP.pop(uid)

# --- /menu with buttons ---
@bot.message_handler(commands=["menu"])
def menu(message):
    uid = message.from_user.id
    rec = get_user(uid)
    if not rec:
        bot.send_message(message.chat.id, "Use /start to register first.")
        return
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📂 Profile", callback_data="profile"),
        InlineKeyboardButton("💎 Buy VIP", callback_data="buy")
    )
    markup.row(
        InlineKeyboardButton("👀 Browse Profiles", callback_data="profiles"),
        InlineKeyboardButton("❤️ Likes You", callback_data="likes_you")
    )
    markup.row(
        InlineKeyboardButton("🎯 Matches", callback_data="matches"),
        InlineKeyboardButton("ℹ Help", callback_data="help")
    )
    bot.send_message(message.chat.id, "Menu:", reply_markup=markup)

# --- Callback handler ---
@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    uid = call.from_user.id
    data = call.data
    rec = get_user(uid)
    if data == "profile":
        text = f"Name: {rec.get('name')}\nAge: {rec.get('age')}\nGender: {rec.get('gender')}\nCity: {rec.get('city')}\nBio: {rec.get('bio')}\nVIP: {rec.get('vip')}\nCoins: {rec.get('coins')}"
        bot.send_photo(call.message.chat.id, rec.get("photo"), caption=text)
    elif data == "buy":
        bot.send_message(uid, "VIP unlocks real profiles. Contact admin for payment.")
    elif data == "help":
        bot.send_message(uid, "Commands: /start, /menu. Use buttons to navigate.")
    elif data == "likes_you":
        bot.send_message(uid, "Likes are VIP-only. Upgrade to see.")
    elif data == "matches":
        bot.send_message(uid, "Matches are VIP-only. Upgrade to see.")
    elif data == "profiles":
        bot.send_message(uid, "Profile browsing coming soon.")

# --- Flask route for webhook ---
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "", 200

# --- Health check ---
@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200

# --- Main: set webhook & run ---
if __name__ == "__main__":
    full_url = f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=full_url)
    logger.info(f"Webhook set: {full_url}")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
