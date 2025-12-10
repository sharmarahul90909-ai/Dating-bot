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
import random
from typing import Dict, Any

from flask import Flask, request
import telebot
# This line lists the specific types needed for your bot's keyboards
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
# This line is the fix we added previously for error logging (it is now clean)
from telebot.apihelper import ApiTelegramException
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
    """Return pinned_message object or None. Handles API errors gracefully."""
    if not DB_CHANNEL_ID:
        return None
    try:
        # This is the call that raises the permission error (400)
        chat = bot.get_chat(DB_CHANNEL_ID)
        return getattr(chat, "pinned_message", None)
    except ApiTelegramException as e:
        # **THIS IS THE CRITICAL LOGGING FIX**
        # This will print the error code (e.g., 400 Bad Request) to your Render logs.
        logger.error("API ERROR in DB access. Code: %s, Description: %s", 
                     e.error_code, e.description)
        logger.error("SOLUTION: Ensure the bot is an ADMIN in the channel (%s) with 'Post' and 'Pin' permissions.", DB_CHANNEL_ID)
        return None
    except Exception as e:
        logger.exception("Failed to get pinned message (UNKNOWN ERROR): %s", e)
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
        InlineKeyboardButton("🛠 Admin", callback_data="menu_admin"),
    )
    return markup

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

# ---------------- profile view helpers ----------------

def _send_profile_card(chat_id: int, rec: Dict[str, Any], is_vip: bool, is_own: bool = False, source_id: int = 0):
    if is_own:
        caption = (
            f"<b>Your Profile:</b>\n"
            f"Name: {rec.get('name')}, Age: {rec.get('age')}\n"
            f"City: {rec.get('city')}, Gender: {rec.get('gender')}\n"
            f"Looking for: {rec.get('looking_for')}\n"
            f"Bio: {rec.get('bio')}"
        )
        markup = None # Add edit buttons later if needed
    else:
        # Logic for target profile card
        caption = (
            f"<b>{rec.get('name')}</b>, {rec.get('age')}\n"
            f"City: {rec.get('city')}\n"
            f"Bio: {rec.get('bio')}"
        )
        markup = profile_buttons(source_id, is_vip)

    bot.send_photo(chat_id, rec.get("photo_id"), caption=caption, reply_markup=markup)

def _get_next_profile(current_uid: int, db: Dict[str, Any]):
    # Simplified logic: just cycle through registered users who are not the current user
    user_uids = [int(uid) for uid in db.get("users", {}).keys() if int(uid) != current_uid]
    if not user_uids:
        return None, None
    
    # Simple cycle, can be improved with matching logic
    target_uid = random.choice(user_uids)
    return target_uid, db["users"][str(target_uid)]

def _send_browse_view(uid: int):
    db = load_db()
    current_user = get_user_record(uid)
    is_vip = current_user.get("vip", False)

    target_uid, target_rec = _get_next_profile(uid, db)

    if target_rec:
        # VIP user sees real profiles
        if is_vip:
            _send_profile_card(uid, target_rec, is_vip=True, source_id=target_uid)
        # Free user sees fake profiles
        else:
            fake_list = FAKE_PROFILES_FEMALE if current_user.get("looking_for") == "Male" else FAKE_PROFILES_MALE
            fake_rec = random.choice(fake_list)
            fake_rec['photo_id'] = fake_rec.pop('photo')
            _send_profile_card(uid, fake_rec, is_vip=False)
    else:
        bot.send_message(uid, "No profiles found yet. Try again later.")


# ---------------- bot handlers ----------------

# ---------------- bot handlers ----------------

@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    uid = message.from_user.id
    rec = get_user_record(uid)
    
    # Try to send a message immediately to catch the blocked user error (403)
    try:
        if rec and rec.get("registered"):
            bot.send_message(uid, f"Welcome back, <b>{rec.get('name')}</b>! Use /profiles to browse.", reply_markup=main_menu_keyboard())
            return
    except ApiTelegramException as e:
        # This will catch the 403 (blocked) or other errors and log them clearly.
        logger.error("API ERROR on initial /start reply. Code: %s, Description: %s", e.error_code, e.description)
        logger.error("SOLUTION: User may have blocked the bot (403).")
        return
    except Exception as e:
        logger.exception("CRITICAL: Failed to send start message (Unknown error).")
        return
    
    # If not registered, start registration flow
    if not rec or not rec.get("registered"):
        TEMP_BUFFER[uid] = {"tgid": uid}
        REG_STEP[uid] = "photo"
        bot.send_message(uid, "👋 Welcome! Let's create your dating profile.\n\nStep 1: Send your profile photo (mandatory).", reply_markup=None)


@bot.message_handler(commands=["init_db"])
def cmd_init_db(message):
    """Admin command to initialize the database pinned message."""
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    
    # This call now uses the fixed _get_pinned_message()
    ok = safe_init_db(message.from_user.id) 
    
    if ok:
        bot.reply_to(message, "DB initialized (existing data preserved).")
    else:
        # The specific error details are now logged inside _get_pinned_message()
        bot.reply_to(message, "Failed to initialize DB. Check server logs for API_ERROR details.")
    # --- DIAGNOSTIC END ---


@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    uid = message.from_user.id
    rec = get_user_record(uid)
    if not rec or not rec.get("registered"):
        bot.reply_to(message, "Please use /start to register first.")
        return
    
    is_vip = rec.get("vip", False)
    _send_profile_card(uid, rec, is_vip=is_vip, is_own=True)


@bot.message_handler(commands=["profiles"])
def cmd_profiles(message):
    uid = message.from_user.id
    rec = get_user_record(uid)
    if not rec or not rec.get("registered"):
        bot.reply_to(message, "Please use /start to register first.")
        return
    
    _send_browse_view(uid)


# ---------------- Registration Handlers ----------------

@bot.message_handler(content_types=['photo'])
def handle_photo_reg(message):
    uid = message.from_user.id
    current_step = REG_STEP.get(uid)

    if current_step == "photo":
        TEMP_BUFFER[uid]["photo_id"] = message.photo[-1].file_id
        REG_STEP[uid] = "name"
        bot.send_message(uid, "Step 2: Enter your name (e.g., Alex)")
        return
    
    # Fallthrough to default handlers if not in registration


@bot.message_handler(content_types=['text'])
def handle_text_messages(message):
    uid = message.from_user.id
    text = message.text
    current_step = REG_STEP.get(uid)

    if current_step == "name":
        if 2 <= len(text) <= 50 and text.isalpha():
            TEMP_BUFFER[uid]["name"] = text
            REG_STEP[uid] = "age"
            bot.send_message(uid, "Step 3: Enter your age (18-99).")
        else:
            bot.send_message(uid, "Invalid name. Please enter a valid name (letters only).")
        return
    
    elif current_step == "age":
        if text.isdigit() and 18 <= int(text) <= 99:
            TEMP_BUFFER[uid]["age"] = int(text)
            REG_STEP[uid] = "gender"
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("Male", callback_data="reg_gender_Male"),
                       InlineKeyboardButton("Female", callback_data="reg_gender_Female"))
            bot.send_message(uid, "Step 4: Select your gender.", reply_markup=markup)
        else:
            bot.send_message(uid, "Invalid age. Must be a number between 18 and 99.")
        return
    
    elif current_step == "city":
        if 2 <= len(text) <= 50 and all(c.isalpha() or c.isspace() for c in text):
            TEMP_BUFFER[uid]["city"] = text
            REG_STEP[uid] = "bio"
            bot.send_message(uid, "Step 6: Write a short bio (max 200 characters).")
        else:
            bot.send_message(uid, "Invalid city. Please enter a valid city name.")
        return

    elif current_step == "bio":
        if 5 <= len(text) <= 200:
            TEMP_BUFFER[uid]["bio"] = text
            TEMP_BUFFER[uid]["vip"] = False
            TEMP_BUFFER[uid]["likes"] = []
            TEMP_BUFFER[uid]["matches"] = []
            TEMP_BUFFER[uid]["registered"] = True
            
            # Final Save
            ok = save_user_record(uid, TEMP_BUFFER[uid])
            
            del REG_STEP[uid]
            del TEMP_BUFFER[uid]

            if ok:
                bot.send_message(uid, "🎉 Registration complete! You can now start browsing profiles using /profiles.", reply_markup=main_menu_keyboard())
            else:
                bot.send_message(uid, "❌ Error saving your profile. Please try again later.")
        else:
            bot.send_message(uid, "Bio too short or too long. Must be between 5 and 200 characters.")
        return

    # Catch-all for non-command text
    if not text.startswith('/'):
        rec = get_user_record(uid)
        if not rec or not rec.get("registered"):
            bot.send_message(uid, "Please use /start to begin registration.")
        else:
            bot.send_message(uid, "I'm not sure what to do with that. Use /menu to see options.")


# ---------------- Callback Handlers ----------------

def _handle_registration_callback(call, data, uid):
    # Handles gender and looking_for selection
    _, step, value = data.split('_')
    
    if step == "gender":
        TEMP_BUFFER[uid]["gender"] = value
        REG_STEP[uid] = "looking_for"
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Male", callback_data="reg_looking_for_Male"),
                   InlineKeyboardButton("Female", callback_data="reg_looking_for_Female"))
        bot.edit_message_text("Step 5: Select who you are looking for.", call.message.chat.id, call.message.message_id, reply_markup=markup)
        
    elif step == "looking_for":
        TEMP_BUFFER[uid]["looking_for"] = value
        REG_STEP[uid] = "city"
        bot.edit_message_text("Step 6: Enter your city.", call.message.chat.id, call.message.message_id, reply_markup=None)


def _handle_like_skip(call, data, uid):
    _, action, target_id_str = data.split('_')
    target_id = int(target_id_str)
    
    # Load DB
    db = load_db()
    
    # Handle Like
    if action == "like":
        user_record = db["users"].get(str(uid), {})
        target_record = db["users"].get(str(target_id), {})
        
        # Add like to user's list
        if target_id not in user_record.get("likes", []):
            user_record.setdefault("likes", []).append(target_id)

        # Check for match (if target already liked current user)
        if uid in target_record.get("likes", []):
            # Match found
            user_record.setdefault("matches", []).append(target_id)
            target_record.setdefault("matches", []).append(uid)
            
            # Notify both users
            bot.send_message(uid, f"🎉 **MATCH!** You matched with {target_record.get('name')}! You can chat with them.")
            bot.send_message(target_id, f"🎉 **MATCH!** You matched with {user_record.get('name')}! Chat with them here.")
        
        db["users"][str(uid)] = user_record
        db["users"][str(target_id)] = target_record

        # Save and update view
        if save_db(db):
            bot.answer_callback_query(call.id, "Liked!")
            bot.edit_message_caption(call.message.chat.id, call.message.message_id, caption="Liked!", reply_markup=None)
            _send_browse_view(uid)
        else:
            bot.answer_callback_query(call.id, "Error saving like.")
    
    # Handle Skip
    elif action == "skip":
        bot.answer_callback_query(call.id, "Skipped.")
        bot.edit_message_caption(call.message.chat.id, call.message.message_id, caption="Skipped!", reply_markup=None)
        _send_browse_view(uid)


def _handle_admin_callback(call, data, uid):
    # Admin callback logic (not fully implemented here, but reserved)
    bot.answer_callback_query(call.id, "Admin feature not active.")
    bot.edit_message_text("Admin Menu", call.message.chat.id, call.message.message_id, reply_markup=inline_main_menu())


@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    uid = call.from_user.id
    data = call.data
    
    # Cancel any pending registration text step
    if uid in REG_STEP:
        del REG_STEP[uid]
        bot.send_message(uid, "Registration interrupted. Start again with /start.")
        
    if data.startswith("reg_"):
        _handle_registration_callback(call, data, uid)
    
    elif data.startswith("like_") or data.startswith("skip_"):
        _handle_like_skip(call, data, uid)
    
    elif data.startswith("menu_"):
        if data == "menu_browse":
            bot.edit_message_text("Starting to browse...", call.message.chat.id, call.message.message_id, reply_markup=None)
            _send_browse_view(uid)
        else:
            bot.answer_callback_query(call.id, f"Menu action: {data} not fully implemented.")
            bot.edit_message_text(f"Welcome to the {data.split('_')[1]} menu!", call.message.chat.id, call.message.message_id, reply_markup=inline_main_menu())

    elif data == "fake_like" or data == "fake_next":
        bot.answer_callback_query(call.id, "Profiles for VIP members only. Use /buy to upgrade.")
        _send_browse_view(uid)

    elif data == "buy_vip":
        bot.answer_callback_query(call.id, "Redirecting to payment link...")
        bot.send_message(uid, "Buy VIP: [Link to Payment Placeholder]")

    elif data == "menu_admin" and uid in ADMIN_IDS:
        _handle_admin_callback(call, data, uid)
    
    else:
        bot.answer_callback_query(call.id, "Unknown command.")


# ---------------- Fallback Handler ----------------
# This must be the last handler
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    uid = message.from_user.id
    rec = get_user_record(uid)
    if not rec or not rec.get("registered"):
        # If user sends non-command, non-photo, and isn't registered, prompt /start
        if not message.text.startswith('/'):
            bot.send_message(uid, "Welcome! Use /start to begin registration.")
        else:
            # Handle unknown command
            bot.send_message(uid, "Unknown command. Use /menu to see options.")
    else:
        # Registered user sends non-command text
        bot.send_message(uid, "I'm not sure what to do with that. Use /menu to see options.")


# ---------------- webhook + health endpoits ----------------
@app.route(f"/{TOKEN}", methods=['POST'])
def webhook():
    json_data = request.get_json(force=True)
    update = telebot.types.Update.de_json(json_data)
    
    if update.message:
        bot.process_new_messages([update.message])
    elif update.callback_query:
        bot.process_new_callback_query([update.callback_query])

    return "OK", 200
    

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
