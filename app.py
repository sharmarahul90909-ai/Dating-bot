import os
import json
import time
from typing import Dict, Any
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ---------------- Configuration ---------------- #
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # must end with /BOT_TOKEN

if not BOT_TOKEN or not DB_CHANNEL_ID or not WEBHOOK_URL:
    raise SystemExit("Set BOT_TOKEN, DB_CHANNEL_ID, and WEBHOOK_URL in environment variables.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ---------------- Registration ---------------- #
REG_STEP = {}
TEMP_BUFFER: Dict[int, Dict[str, Any]] = {}

# ---------------- Fake Profiles ---------------- #
FAKE_PROFILES_MALE = [
    {"name": "Rahul", "age": 24, "city": "Delhi", "bio": "Coffee & coding.", "photo": "https://picsum.photos/400?random=11"},
    {"name": "Aman",  "age": 26, "city": "Mumbai", "bio": "Traveler.", "photo": "https://picsum.photos/400?random=12"},
    {"name": "Vishal","age": 23, "city": "Kolkata","bio": "Food lover.", "photo": "https://picsum.photos/400?random=13"},
]
FAKE_PROFILES_FEMALE = [
    {"name": "Priya", "age": 22, "city": "Delhi", "bio": "Bookworm.", "photo": "https://picsum.photos/400?random=21"},
    {"name": "Anjali","age": 24, "city": "Pune",  "bio": "Artist.", "photo": "https://picsum.photos/400?random=22"},
    {"name": "Sana",  "age": 23, "city": "Bengaluru","bio":"Coffee lover.","photo":"https://picsum.photos/400?random=23"},
]

# ---------------- Utilities ---------------- #
def load_db_from_channel() -> Dict[str, Any]:
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        if pinned and pinned.text:
            return json.loads(pinned.text)
        else:
            return {"users": {}, "meta": {}}
    except Exception:
        return {"users": {}, "meta": {}}

def save_db_to_channel(db: Dict[str, Any]) -> bool:
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        text = json.dumps(db, ensure_ascii=False, indent=2)
        if len(text) > 3800:  # message limit
            return False
        if pinned:
            bot.edit_message_text(chat_id=DB_CHANNEL_ID, message_id=pinned.message_id, text=text)
        else:
            msg = bot.send_message(DB_CHANNEL_ID, text)
            bot.pin_chat_message(DB_CHANNEL_ID, msg.message_id, disable_notification=True)
        return True
    except Exception:
        return False

def get_user_record(tgid: int) -> Dict[str, Any] | None:
    db = load_db_from_channel()
    return db.get("users", {}).get(str(tgid))

def save_user_record(tgid: int, record: Dict[str, Any]) -> bool:
    db = load_db_from_channel()
    if "users" not in db:
        db["users"] = {}
    db["users"][str(tgid)] = record
    return save_db_to_channel(db)

# ---------------- Keyboards ---------------- #
def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("/start"), KeyboardButton("/profile"),
        KeyboardButton("/profiles"), KeyboardButton("/likes_you"),
        KeyboardButton("/matches"), KeyboardButton("/buy"),
        KeyboardButton("/paysupport"), KeyboardButton("/help")
    )
    return markup

def profile_inline_buttons(target_id: int, vip: bool):
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
        markup.row(InlineKeyboardButton("🌟 Buy VIP", callback_data="buyvip"))
    return markup

# ---------------- Commands ---------------- #
@bot.message_handler(commands=["init_db"])
def cmd_init_db(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    db = load_db_from_channel()
    if db.get("users"):
        bot.reply_to(message, "DB already exists. Initialization skipped to prevent data loss.")
        return
    db = {"users": {}, "meta": {"created_by": message.from_user.id, "created_at": int(time.time())}}
    if save_db_to_channel(db):
        bot.reply_to(message, "✅ DB initialized and pinned.")
    else:
        bot.reply_to(message, "❌ Failed to initialize DB.")

@bot.message_handler(commands=["start"])
def cmd_start(message):
    tgid = message.from_user.id
    rec = get_user_record(tgid)
    if rec and rec.get("registered"):
        bot.send_message(
            message.chat.id,
            f"Welcome back, <b>{rec.get('name') or message.from_user.first_name}</b>!",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )
        return
    TEMP_BUFFER[tgid] = {}
    REG_STEP[tgid] = "photo"
    bot.send_message(message.chat.id, "Step 1: Upload profile photo.", reply_markup=main_menu_keyboard())

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    tgid = message.from_user.id
    step = REG_STEP.get(tgid)
    if step != "photo":
        rec = get_user_record(tgid)
        if rec and rec.get("registered"):
            rec["photo_file_id"] = message.photo[-1].file_id
            save_user_record(tgid, rec)
            bot.reply_to(message, "Profile photo updated.")
        else:
            bot.reply_to(message, "Not expecting photo now. Use /start to register.")
        return
    TEMP_BUFFER[tgid]["photo_file_id"] = message.photo[-1].file_id
    REG_STEP[tgid] = "name"
    bot.send_message(message.chat.id, "Step 2: Send your full name.")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    tgid = message.from_user.id
    text = message.text.strip()
    step = REG_STEP.get(tgid)
    if text.startswith("/"):
        return
    if not step:
        bot.send_message(message.chat.id, "Use buttons or /start to register.", reply_markup=main_menu_keyboard())
        return

    if step == "name":
        TEMP_BUFFER[tgid]["name"] = text
        REG_STEP[tgid] = "age"
        bot.send_message(message.chat.id, "Step 3: Enter your age (18+).")
        return
    if step == "age":
        if not text.isdigit() or int(text) < 18:
            bot.send_message(message.chat.id, "Enter a valid age (18+).")
            return
        TEMP_BUFFER[tgid]["age"] = int(text)
        REG_STEP[tgid] = "gender"
        bot.send_message(message.chat.id, "Step 4: Enter gender (male/female).")
        return
    if step == "gender":
        if text.lower() not in ("male","female"):
            bot.send_message(message.chat.id, "Type 'male' or 'female'.")
            return
        TEMP_BUFFER[tgid]["gender"] = text.lower()
        REG_STEP[tgid] = "interest"
        bot.send_message(message.chat.id, "Step 5: Who do you want to see? (male/female/both)")
        return
    if step == "interest":
        if text.lower() not in ("male","female","both"):
            bot.send_message(message.chat.id, "Choose 'male', 'female', or 'both'.")
            return
        TEMP_BUFFER[tgid]["interest"] = text.lower()
        REG_STEP[tgid] = "city"
        bot.send_message(message.chat.id, "Step 6: Enter your city.")
        return
    if step == "city":
        TEMP_BUFFER[tgid]["city"] = text
        REG_STEP[tgid] = "bio"
        bot.send_message(message.chat.id, "Step 7: Send a short bio (one line).")
        return
    if step == "bio":
        TEMP_BUFFER[tgid]["bio"] = text
        user_record = {
            "telegram_id": tgid,
            "photo_file_id": TEMP_BUFFER[tgid].get("photo_file_id"),
            "name": TEMP_BUFFER[tgid].get("name"),
            "age": TEMP_BUFFER[tgid].get("age"),
            "gender": TEMP_BUFFER[tgid].get("gender"),
            "interest": TEMP_BUFFER[tgid].get("interest"),
            "city": TEMP_BUFFER[tgid].get("city"),
            "bio": TEMP_BUFFER[tgid].get("bio"),
            "registered": True,
            "vip": False,
            "likes": [], "liked_by": [], "matches": [],
            "current_fake_index":0, "current_real_index":0,
            "coins":20, "created_at":int(time.time())
        }
        ok = save_user_record(tgid, user_record)
        REG_STEP.pop(tgid, None)
        TEMP_BUFFER.pop(tgid, None)
        if ok:
            bot.send_message(message.chat.id, "🎉 Registration complete!", reply_markup=main_menu_keyboard())
        else:
            bot.send_message(message.chat.id, "Failed to save profile. Contact admin.")

# ---------------- More commands (profile, buy, help, profiles) ---------------- #
# ... You can add similar handlers like cmd_profile, cmd_buy, cmd_help
# using reply_markup=main_menu_keyboard() for buttons
# and inline buttons for /profiles VIP/fake logic.

# ---------------- Webhook ---------------- #
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

bot.remove_webhook()
bot.set_webhook(url=WEBHOOK_URL + BOT_TOKEN)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
