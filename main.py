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

# ---------------- bot handlers ----------------
@bot.message_handler(commands=["init_db"])
def cmd_init_db(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    ok = safe_init_db(message.from_user.id)
    if ok:
        bot.reply_to(message, "DB initialized (existing data preserved).")
    else:
        bot.reply_to(message, "Failed to initialize DB — check bot permissions on channel.")

@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    uid = message.from_user.id

    # --- START TEMPORARY TEST BLOCK ---
    # THIS BYPASSES THE DB CHECK. If this works, the problem is 100% the DB channel access.
    bot.send_message(uid, "TEMPORARY TEST SUCCESS! DB Check bypassed.", parse_mode="HTML")
    return
    # --- END TEMPORARY TEST BLOCK ---

    # The original code follows:
    # rec = get_user_record(uid)
    # if rec and rec.get("registered"):
    # ...

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    uid = message.from_user.id
    step = REG_STEP.get(uid)
    if step != "photo":
        rec = get_user_record(uid)
        if rec and rec.get("registered"):
            rec["photo_file_id"] = message.photo[-1].file_id
            save_user_record(uid, rec)
            bot.reply_to(message, "Profile photo updated.")
        else:
            bot.reply_to(message, "Not expecting photo now. Use /start to register.")
        return
    TEMP_BUFFER[uid]["photo_file_id"] = message.photo[-1].file_id
    REG_STEP[uid] = "name"
    bot.send_message(message.chat.id, "✔ Photo saved. Step 2: Send your full name (text).")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    uid = message.from_user.id
    text = message.text.strip()
    # ignore pure commands here
    if text.startswith("/"):
        return
    step = REG_STEP.get(uid)
    if not step:
        bot.send_message(uid, "Use the menu or /start to register.", reply_markup=main_menu_keyboard())
        return

    if step == "name":
        TEMP_BUFFER[uid]["name"] = text
        REG_STEP[uid] = "age"
        bot.send_message(uid, "Step 3: Enter your age (18+).")
        return
    if step == "age":
        if not text.isdigit() or int(text) < 18:
            bot.send_message(uid, "Enter a valid age (18+).")
            return
        TEMP_BUFFER[uid]["age"] = int(text)
        REG_STEP[uid] = "gender"
        bot.send_message(uid, "Step 4: Enter your gender (male/female).")
        return
    if step == "gender":
        if text.lower() not in ("male", "female"):
            bot.send_message(uid, "Type 'male' or 'female'.")
            return
        TEMP_BUFFER[uid]["gender"] = text.lower()
        REG_STEP[uid] = "interest"
        bot.send_message(uid, "Step 5: Who do you want to see? (male/female/both)")
        return
    if step == "interest":
        if text.lower() not in ("male", "female", "both"):
            bot.send_message(uid, "Choose 'male', 'female' or 'both'.")
            return
        TEMP_BUFFER[uid]["interest"] = text.lower()
        REG_STEP[uid] = "city"
        bot.send_message(uid, "Step 6: Enter your city.")
        return
    if step == "city":
        TEMP_BUFFER[uid]["city"] = text
        REG_STEP[uid] = "bio"
        bot.send_message(uid, "Step 7: Send a short bio about yourself (one line).")
        return
    if step == "bio":
        TEMP_BUFFER[uid]["bio"] = text
        # finalize profile
        user_record = {
            "telegram_id": uid,
            "photo_file_id": TEMP_BUFFER[uid].get("photo_file_id"),
            "name": TEMP_BUFFER[uid].get("name"),
            "age": TEMP_BUFFER[uid].get("age"),
            "gender": TEMP_BUFFER[uid].get("gender"),
            "interest": TEMP_BUFFER[uid].get("interest"),
            "city": TEMP_BUFFER[uid].get("city"),
            "bio": TEMP_BUFFER[uid].get("bio"),
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
        ok = save_user_record(uid, user_record)
        REG_STEP.pop(uid, None)
        TEMP_BUFFER.pop(uid, None)
        if ok:
            bot.send_message(uid, "🎉 Registration complete! Use /menu to browse.", reply_markup=main_menu_keyboard())
        else:
            bot.send_message(uid, "Failed to save profile — contact admin.")
        return

# ---------------- menu / browsing / callbacks ----------------
@bot.message_handler(commands=["menu"])
def cmd_menu(message):
    uid = message.from_user.id
    rec = get_user_record(uid)
    if not rec or not rec.get("registered"):
        bot.send_message(uid, "Register first with /start.")
        return
    bot.send_message(uid, "Main Menu", reply_markup=inline_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.from_user.id
    data = call.data or ""

    # Menu actions
    if data == "menu_profile":
        rec = get_user_record(uid)
        if not rec:
            bot.send_message(uid, "No profile found. Use /start to register.")
            return
        caption = (f"Name: {rec.get('name')}\nAge: {rec.get('age')}\nGender: {rec.get('gender')}\n"
                   f"Interest: {rec.get('interest')}\nCity: {rec.get('city')}\nBio: {rec.get('bio')}\nVIP: {rec.get('vip')}\nCoins: {rec.get('coins')}")
        try:
            bot.send_photo(uid, rec.get("photo_file_id"), caption=caption)
        except Exception:
            bot.send_message(uid, caption)
        return

    if data == "menu_vip":
        bot.send_message(uid, "VIP unlocks real profiles and match features. Contact admin to upgrade.")
        return

    if data == "menu_browse":
        rec = get_user_record(uid)
        if not rec:
            bot.send_message(uid, "Register first with /start.")
            return
        if rec.get("vip"):
            # show real users according to interest
            db = load_db()
            users = db.get("users", {})
            candidates = []
            for uid_s, u in users.items():
                if int(uid_s) == uid:
                    continue
                if not u.get("registered"):
                    continue
                pref = rec.get("interest", "both")
                if pref == "both" or u.get("gender") == pref:
                    candidates.append((int(uid_s), u))
            if not candidates:
                bot.send_message(uid, "No real profiles available at the moment.")
                return
            idx = rec.get("current_real_index", 0) % len(candidates)
            target_id, target = candidates[idx]
            rec["current_real_index"] = (idx + 1) % len(candidates)
            save_user_record(uid, rec)
            caption = f"{target.get('name')}, {target.get('age')}\n{target.get('city')}\n\n{target.get('bio')}"
            if target.get("photo_file_id"):
                try:
                    bot.send_photo(uid, target.get("photo_file_id"), caption=caption, reply_markup=profile_buttons(target_id, True))
                    return
                except Exception:
                    pass
            bot.send_message(uid, caption, reply_markup=profile_buttons(target_id, True))
        else:
            # fake profiles for free users
            pref = rec.get("interest", "both")
            pool = FAKE_PROFILES_MALE + FAKE_PROFILES_FEMALE if pref == "both" else (FAKE_PROFILES_MALE if pref == "male" else FAKE_PROFILES_FEMALE)
            if not pool:
                bot.send_message(uid, "No preview profiles available.")
                return
            idx = rec.get("current_fake_index", 0) % len(pool)
            profile = pool[idx]
            rec["current_fake_index"] = (idx + 1) % len(pool)
            save_user_record(uid, rec)
            try:
                bot.send_photo(uid, profile["photo"], caption=f"{profile['name']}, {profile['age']}\n{profile['city']}\n\n{profile['bio']}", reply_markup=profile_buttons(0, False))
            except Exception:
                bot.send_message(uid, f"{profile['name']}, {profile['age']}\n{profile['city']}\n\n{profile['bio']}")
        return

    # like / skip for real profiles
    if data.startswith("like_"):
        try:
            target = int(data.split("_", 1)[1])
        except Exception:
            bot.answer_callback_query(call.id, "Invalid target.")
            return
        me = get_user_record(uid)
        tgt = get_user_record(target)
        if not me or not me.get("vip"):
            bot.answer_callback_query(call.id, "VIP required to like real profiles. Use /menu -> VIP.")
            return
        if not tgt:
            bot.answer_callback_query(call.id, "Target not found.")
            return
        if str(target) not in me.get("likes", []):
            me["likes"].append(str(target))
        if str(uid) not in tgt.get("liked_by", []):
            tgt["liked_by"].append(str(uid))
        # check match
        if str(uid) in tgt.get("likes", []):
            # mutual match
            if str(target) not in me.get("matches", []):
                me["matches"].append(str(target))
            if str(uid) not in tgt.get("matches", []):
                tgt["matches"].append(str(uid))
            save_user_record(uid, me)
            save_user_record(target, tgt)
            bot.answer_callback_query(call.id, "🎉 It's a MATCH!")
            try:
                bot.send_message(target, f"🎉 You matched with {me.get('name')}!")
            except Exception:
                pass
            try:
                bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=(call.message.caption or "") + "\n\n🎉 It's a MATCH!")
            except Exception:
                pass
            return
        save_user_record(uid, me)
        save_user_record(target, tgt)
        bot.answer_callback_query(call.id, "Liked.")
        try:
            bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=(call.message.caption or "") + "\n\n✅ You liked this profile.")
        except Exception:
            pass
        return

    if data.startswith("skip_"):
        bot.answer_callback_query(call.id, "Skipped.")
        bot.send_message(uid, "/menu")
        return

    # fake preview actions
    if data == "fake_like":
        bot.answer_callback_query(call.id, "Preview: someone 'liked' you (fake). Upgrade to VIP for real likes.")
        try:
            bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=(call.message.caption or "") + "\n\n❤️ They liked you! (preview)")
        except Exception:
            pass
        return
    if data == "fake_next":
        bot.answer_callback_query(call.id, "Next preview...")
        bot.send_message(uid, "/menu")
        return

    # admin menu
    if data == "menu_admin":
        if uid not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "Admin only.")
            return
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Broadcast", callback_data="admin_broadcast"))
        markup.row(InlineKeyboardButton("Grant VIP (by id)", callback_data="admin_grant_vip"))
        bot.send_message(uid, "Admin panel:", reply_markup=markup)
        return

    if data == "admin_grant_vip":
        bot.send_message(uid, "Send: /grant_vip <tgid>")
        return
    if data == "admin_broadcast":
        bot.send_message(uid, "Send: /broadcast <message>")
        return

# ---------------- admin commands ----------------
@bot.message_handler(commands=["grant_vip"])
def cmd_grant_vip(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: /grant_vip <tgid>")
        return
    tgid = int(parts[1])
    rec = get_user_record(tgid)
    if not rec:
        bot.reply_to(message, "User not found.")
        return
    rec["vip"] = True
    save_user_record(tgid, rec)
    bot.reply_to(message, f"Granted VIP to {tgid}")

@bot.message_handler(commands=["revoke_vip"])
def cmd_revoke_vip(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: /revoke_vip <tgid>")
        return
    tgid = int(parts[1])
    rec = get_user_record(tgid)
    if not rec:
        bot.reply_to(message, "User not found.")
        return
    rec["vip"] = False
    save_user_record(tgid, rec)
    bot.reply_to(message, f"Revoked VIP for {tgid}")

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        bot.reply_to(message, "Usage: /broadcast <message>")
        return
    db = load_db()
    users = db.get("users", {})
    sent = 0
    for uid_s in users.keys():
        try:
            bot.send_message(int(uid_s), f"[Broadcast]\n\n{text}")
            sent += 1
        except Exception:
            continue
    bot.reply_to(message, f"Broadcast sent to {sent} users.")

@bot.message_handler(commands=["delete_user"])
def cmd_delete_user(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: /delete_user <tgid>")
        return
    tgid = int(parts[1])
    ok = delete_user_record(tgid)
    bot.reply_to(message, "Deleted." if ok else "User not found.")

@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    uid = message.from_user.id
    rec = get_user_record(uid)
    if not rec:
        bot.reply_to(message, "No profile found. Use /start to register.")
        return
    caption = (f"Name: {rec.get('name')}\nAge: {rec.get('age')}\nCity: {rec.get('city')}\n"
               f"Bio: {rec.get('bio')}\nVIP: {rec.get('vip')}")
    try:
        bot.send_photo(uid, rec.get("photo_file_id"), caption=caption)
    except Exception:
        bot.send_message(uid, caption)

@bot.message_handler(commands=["profiles"])
def cmd_profiles(message):
    bot.send_message(message.chat.id, "Use /menu -> Browse for a better experience.")

@bot.message_handler(commands=["buy"])
def cmd_buy(message):
    bot.reply_to(message, "VIP & coins: manual upgrade handled by admins. Contact /help for admin contacts.")

@bot.message_handler(commands=["help"])
def cmd_help(message):
    admin_links = ", ".join([f"<a href='tg://user?id={aid}'>{aid}</a>" for aid in ADMIN_IDS]) if ADMIN_IDS else "No admins set"
    bot.send_message(message.chat.id, f"Admins: {admin_links}\nCommands: /start /menu /profile /profiles /buy /help", parse_mode="HTML")

# ---------------- webhook + health endpoints ----------------
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
