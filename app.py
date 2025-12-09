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
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")  # like "-1001234567890"
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://yourapp.onrender.com

if not BOT_TOKEN or not DB_CHANNEL_ID or not WEBHOOK_URL:
    logger.error("Missing BOT_TOKEN, DB_CHANNEL_ID, or WEBHOOK_URL")
    raise SystemExit("Set required environment variables!")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# --- In-memory registration ---
REG_STEP = {}  # user_id -> step
TEMP_BUFFER = {}  # user_id -> temp data

# --- Fake profiles ---
FAKE_MALE = [
    {"name":"Rahul","age":24,"city":"Delhi","bio":"Coffee & coding.","photo":"https://picsum.photos/400?random=11"},
    {"name":"Aman","age":26,"city":"Mumbai","bio":"Traveler.","photo":"https://picsum.photos/400?random=12"}
]
FAKE_FEMALE = [
    {"name":"Priya","age":22,"city":"Delhi","bio":"Bookworm.","photo":"https://picsum.photos/400?random=21"},
    {"name":"Anjali","age":24,"city":"Pune","bio":"Artist.","photo":"https://picsum.photos/400?random=22"}
]

# --- DB helpers ---
def load_db():
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        if pinned and pinned.text:
            return json.loads(pinned.text)
        return {"users": {}, "meta": {}}
    except Exception as e:
        logger.warning("DB load failed: %s", e)
        return {"users": {}, "meta": {}}

def save_db(db):
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        text = json.dumps(db, ensure_ascii=False, indent=2)
        if len(text) > 3800:
            logger.error("DB too large")
            return False
        if pinned:
            bot.edit_message_text(chat_id=DB_CHANNEL_ID, message_id=pinned.message_id, text=text)
        else:
            msg = bot.send_message(DB_CHANNEL_ID, text)
            time.sleep(0.5)
            bot.pin_chat_message(DB_CHANNEL_ID, msg.message_id, disable_notification=True)
        return True
    except Exception as e:
        logger.exception("DB save failed: %s", e)
        return False

def get_user(uid):
    db = load_db()
    return db.get("users", {}).get(str(uid))

def save_user(uid, record):
    db = load_db()
    db.setdefault("users", {})[str(uid)] = record
    return save_db(db)

# --- Webhook endpoint ---
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "", 200

# --- Admin /init_db ---
@bot.message_handler(commands=["init_db"])
def init_db(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    db = {"users": {}, "meta": {"created_by": message.from_user.id, "created_at": int(time.time())}}
    ok = save_db(db)
    if ok:
        bot.reply_to(message, "DB initialized ✅")
    else:
        bot.reply_to(message, "Failed to init DB ❌")

# --- Start / Registration ---
@bot.message_handler(commands=["start"])
def start(message):
    uid = message.from_user.id
    rec = get_user(uid)
    if rec and rec.get("registered"):
        bot.send_message(uid, f"Welcome back <b>{rec.get('name')}</b>!\nUse the menu below ⬇️", parse_mode="HTML", reply_markup=main_menu())
        return
    TEMP_BUFFER[uid] = {}
    REG_STEP[uid] = "photo"
    bot.send_message(uid, "Step 1: Send your profile photo 📸")

@bot.message_handler(content_types=["photo"])
def photo_handler(msg):
    uid = msg.from_user.id
    if REG_STEP.get(uid) != "photo":
        bot.send_message(uid, "Not expecting photo now.")
        return
    TEMP_BUFFER[uid]["photo_file_id"] = msg.photo[-1].file_id
    REG_STEP[uid] = "name"
    bot.send_message(uid, "Step 2: Send your full name ✏️")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def text_handler(msg):
    uid = msg.from_user.id
    step = REG_STEP.get(uid)
    text = msg.text.strip()

    if text.startswith("/"):
        # ignore, commands handled separately
        return

    if step == "name":
        TEMP_BUFFER[uid]["name"] = text
        REG_STEP[uid] = "age"
        bot.send_message(uid, "Step 3: Enter your age")
        return

    if step == "age":
        if not text.isdigit() or int(text)<18:
            bot.send_message(uid, "Enter a valid age (18+).")
            return
        TEMP_BUFFER[uid]["age"] = int(text)
        REG_STEP[uid] = "gender"
        bot.send_message(uid, "Step 4: Enter gender (male/female)")
        return

    if step == "gender":
        if text.lower() not in ("male","female"):
            bot.send_message(uid, "Type 'male' or 'female'.")
            return
        TEMP_BUFFER[uid]["gender"] = text.lower()
        REG_STEP[uid] = "interest"
        bot.send_message(uid, "Step 5: Who do you want to see? (male/female/both)")
        return

    if step == "interest":
        if text.lower() not in ("male","female","both"):
            bot.send_message(uid, "Type 'male','female' or 'both'.")
            return
        TEMP_BUFFER[uid]["interest"] = text.lower()
        REG_STEP[uid] = "city"
        bot.send_message(uid, "Step 6: Enter your city")
        return

    if step == "city":
        TEMP_BUFFER[uid]["city"] = text
        REG_STEP[uid] = "bio"
        bot.send_message(uid, "Step 7: Short bio")
        return

    if step == "bio":
        TEMP_BUFFER[uid]["bio"] = text
        rec = {
            "telegram_id": uid,
            "photo_file_id": TEMP_BUFFER[uid]["photo_file_id"],
            "name": TEMP_BUFFER[uid]["name"],
            "age": TEMP_BUFFER[uid]["age"],
            "gender": TEMP_BUFFER[uid]["gender"],
            "interest": TEMP_BUFFER[uid]["interest"],
            "city": TEMP_BUFFER[uid]["city"],
            "bio": TEMP_BUFFER[uid]["bio"],
            "registered": True,
            "vip": False,
            "likes": [], "liked_by": [], "matches": [],
            "current_fake_index": 0,
            "current_real_index": 0,
            "coins": 20,
            "created_at": int(time.time())
        }
        if save_user(uid, rec):
            bot.send_message(uid, "Registration complete ✅", reply_markup=main_menu())
        else:
            bot.send_message(uid, "Failed to save profile ❌")
        REG_STEP.pop(uid)
        TEMP_BUFFER.pop(uid)

# --- UI Menu Buttons ---
def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👤 Profile", callback_data="profile"),
        InlineKeyboardButton("💎 Buy VIP", callback_data="buyvip"),
        InlineKeyboardButton("❤️ Browse Profiles", callback_data="profiles"),
        InlineKeyboardButton("ℹ️ Help", callback_data="help")
    )
    return markup

@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    uid = call.from_user.id
    data = call.data
    if data=="profile":
        rec = get_user(uid)
        if not rec:
            bot.send_message(uid, "No profile found.")
            return
        text = f"Name: {rec.get('name')}\nAge: {rec.get('age')}\nCity: {rec.get('city')}\nBio: {rec.get('bio')}\nVIP: {rec.get('vip')}"
        bot.send_photo(uid, rec.get("photo_file_id"), caption=text)
    elif data=="buyvip":
        bot.send_message(uid,"VIP info:\nManual payment to admin. Contact /help")
    elif data=="help":
        admins = ", ".join([f"<a href='tg://user?id={aid}'>{aid}</a>" for aid in ADMIN_IDS])
        bot.send_message(uid,f"Admins: {admins}\nUse the buttons to navigate.", parse_mode="HTML")
    elif data=="profiles":
        bot.send_message(uid,"Profiles browsing coming soon ⏳")

# --- Set webhook ---
if __name__=="__main__":
    full_url = f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=full_url)
    logger.info(f"Webhook set to {full_url}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
