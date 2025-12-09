# app.py
import os
import json
import logging
import time
from typing import Dict, Any

from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config from environment ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")  # e.g., "-1001234567890"
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g., "https://yourapp.onrender.com/"

if not BOT_TOKEN or not DB_CHANNEL_ID or not WEBHOOK_URL:
    raise SystemExit("Set BOT_TOKEN, DB_CHANNEL_ID, and WEBHOOK_URL in env variables.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# --- Registration state ---
REG_STEP: Dict[int, str] = {}  # user_id -> step
TEMP_BUFFER: Dict[int, Dict[str, Any]] = {}  # temporary user data

# --- Fake profiles for non-VIP users ---
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

# --- DB utilities ---
def load_db_from_channel() -> Dict[str, Any]:
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        if pinned and pinned.text:
            return json.loads(pinned.text)
        return {"users": {}, "meta": {}}
    except Exception as e:
        logger.warning("Failed to load DB: %s", e)
        return {"users": {}, "meta": {}}

def save_db_to_channel(db: Dict[str, Any]) -> bool:
    try:
        text = json.dumps(db, ensure_ascii=False, indent=2)
        if len(text) > 3800:
            logger.error("DB too large for pinned message")
            return False
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
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

def get_user_record(tgid: int) -> Dict[str, Any] | None:
    db = load_db_from_channel()
    return db.get("users", {}).get(str(tgid))

def save_user_record(tgid: int, record: Dict[str, Any]) -> bool:
    db = load_db_from_channel()
    db.setdefault("users", {})[str(tgid)] = record
    return save_db_to_channel(db)

# --- Admin /init_db ---
@bot.message_handler(commands=["init_db"])
def cmd_init_db(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Admin only.")
        return
    db = {"users": {}, "meta": {"created_by": message.from_user.id, "created_at": int(time.time())}}
    if save_db_to_channel(db):
        bot.reply_to(message, "DB initialized and pinned in channel.")
    else:
        bot.reply_to(message, "Failed to initialize DB. Check bot permissions.")

# --- Registration flow ---
@bot.message_handler(commands=["start"])
def cmd_start(message):
    tgid = message.from_user.id
    rec = get_user_record(tgid)
    if rec and rec.get("registered"):
        bot.send_message(message.chat.id, f"Welcome back, <b>{rec.get('name') or message.from_user.first_name}</b>!\nUse /profiles to browse.", parse_mode="HTML")
        return
    TEMP_BUFFER[tgid] = {}
    REG_STEP[tgid] = "photo"
    bot.send_message(message.chat.id, "Step 1: Upload your profile photo (mandatory).")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    tgid = message.from_user.id
    if REG_STEP.get(tgid) != "photo":
        bot.reply_to(message, "Not expecting photo now.")
        return
    TEMP_BUFFER[tgid]["photo_file_id"] = message.photo[-1].file_id
    REG_STEP[tgid] = "name"
    bot.send_message(message.chat.id, "✔ Photo saved. Step 2: Enter your full name.")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    tgid = message.from_user.id
    text = message.text.strip()
    if text.startswith("/"):
        return
    step = REG_STEP.get(tgid)
    if not step:
        bot.send_message(message.chat.id, "Use /start to register.")
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
        bot.send_message(message.chat.id, "Step 4: Enter your gender (male/female).")
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
            bot.send_message(message.chat.id, "Choose male/female/both.")
            return
        TEMP_BUFFER[tgid]["interest"] = text.lower()
        REG_STEP[tgid] = "city"
        bot.send_message(message.chat.id, "Step 6: Enter your city.")
        return
    if step == "city":
        TEMP_BUFFER[tgid]["city"] = text
        REG_STEP[tgid] = "bio"
        bot.send_message(message.chat.id, "Step 7: Short bio about yourself (one line).")
        return
    if step == "bio":
        TEMP_BUFFER[tgid]["bio"] = text
        # finalize
        rec = {
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
            "likes": [],
            "liked_by": [],
            "matches": [],
            "current_fake_index": 0,
            "current_real_index": 0,
            "coins": 20,
            "created_at": int(time.time())
        }
        if save_user_record(tgid, rec):
            bot.send_message(message.chat.id, "🎉 Registration complete! Use /profiles to browse.")
        else:
            bot.send_message(message.chat.id, "Failed to save profile — contact admin.")
        TEMP_BUFFER.pop(tgid, None)
        REG_STEP.pop(tgid, None)
        return

# --- Profiles browsing ---
@bot.message_handler(commands=["profiles"])
def cmd_profiles(message):
    tgid = message.from_user.id
    rec = get_user_record(tgid)
    if not rec or not rec.get("registered"):
        bot.reply_to(message, "Register first with /start.")
        return

    if not rec.get("vip"):
        # show fake
        interest = rec.get("interest","both")
        pool = FAKE_PROFILES_MALE+FAKE_PROFILES_FEMALE if interest=="both" else FAKE_PROFILES_MALE if interest=="male" else FAKE_PROFILES_FEMALE
        idx = rec.get("current_fake_index",0)%len(pool)
        profile = pool[idx]
        rec["current_fake_index"] = (idx+1)%len(pool)
        save_user_record(tgid, rec)

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("❤️ Like (Preview)", callback_data="fake_like"),
            InlineKeyboardButton("➡ Next", callback_data="fake_next")
        )
        markup.row(InlineKeyboardButton("🌟 Buy VIP", callback_data="buyvip"))
        bot.send_photo(message.chat.id, profile["photo"],
                       caption=f"{profile['name']}, {profile['age']}\n{profile['city']}\n\n{profile['bio']}",
                       reply_markup=markup)
        return

    # VIP: real users
    db = load_db_from_channel()
    users = db.get("users",{})
    candidates = []
    for uid, u in users.items():
        if int(uid)==tgid: continue
        if not u.get("registered"): continue
        pref = rec.get("interest")
        if pref=="both" or u.get("gender")==pref:
            candidates.append((int(uid), u))
    if not candidates:
        bot.reply_to(message, "No real profiles available.")
        return

    idx = rec.get("current_real_index",0)%len(candidates)
    target_id, target = candidates[idx]
    rec["current_real_index"] = (idx+1)%len(candidates)
    save_user_record(tgid, rec)

    caption = f"{target.get('name')}, {target.get('age')}\n{target.get('city')}\n\n{target.get('bio')}"
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("❤️ Like", callback_data=f"like_{target_id}"),
        InlineKeyboardButton("❌ Skip", callback_data=f"skip_{target_id}")
    )
    if target.get("photo_file_id"):
        try:
            bot.send_photo(message.chat.id, target.get("photo_file_id"), caption=caption, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(message.chat.id, caption, reply_markup=markup)

# --- Callbacks for like/skip/fake ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    data = call.data or ""
    uid = call.from_user.id
    if data=="fake_like":
        bot.answer_callback_query(call.id,"Preview: upgrade to VIP for real likes")
        bot.edit_message_caption(chat_id=call.message.chat.id,message_id=call.message.message_id,
                                 caption=(call.message.caption or "")+"\n\n❤️ They liked you! (preview)")
        return
    if data=="fake_next":
        bot.answer_callback_query(call.id,"Next preview...")
        bot.send_message(uid,"/profiles")
        return
    if data=="buyvip":
        bot.answer_callback_query(call.id,"Tap /buy for info")
        bot.send_message(uid,"/buy")
        return
    if data.startswith("like_"):
        target = int(data.split("_",1)[1])
        me = get_user_record(uid)
        tgt = get_user_record(target)
        if not me or not me.get("vip"):
            bot.answer_callback_query(call.id,"VIP required. /buy")
            return
        if not tgt:
            bot.answer_callback_query(call.id,"Target not found.")
            return
        if str(target) not in me["likes"]: me["likes"].append(str(target))
        if str(uid) not in tgt["liked_by"]: tgt["liked_by"].append(str(uid))
        # match check
        if str(uid) in tgt["likes"]:
            if str(target) not in me["matches"]: me["matches"].append(str(target))
            if str(uid) not in tgt["matches"]: tgt["matches"].append(str(uid))
            save_user_record(uid, me)
            save_user_record(target, tgt)
            bot.answer_callback_query(call.id,"🎉 MATCH!")
            try: bot.send_message(target,f"🎉 New match with {me.get('name')}!")
            except: pass
            bot.edit_message_caption(chat_id=call.message.chat.id,message_id=call.message.message_id,
                                     caption=(call.message.caption or "")+"\n\n🎉 MATCH!")
            return
        save_user_record(uid, me)
        save_user_record(target, tgt)
        bot.answer_callback_query(call.id,"Liked.")
        bot.edit_message_caption(chat_id=call.message.chat.id,message_id=call.message.message_id,
                                 caption=(call.message.caption or "")+"\n\n✅ You liked this profile.")
        return
    if data.startswith("skip_"):
        bot.answer_callback_query(call.id,"Skipped")
        bot.send_message(uid,"/profiles")
        return

# --- VIP info ---
@bot.message_handler(commands=["buy"])
def cmd_buy(message):
    bot.reply_to(message,"💎 VIP unlocks real profiles, unlimited likes. Contact admin to upgrade.")

# --- /likes_you ---
@bot.message_handler(commands=["likes_you"])
def cmd_likes_you(message):
    tgid = message.from_user.id
    rec = get_user_record(tgid)
    if not rec or not rec.get("registered"): return bot.reply_to(message,"Register first")
    if not rec.get("vip"): return bot.reply_to(message,"VIP only. Preview: Priya/Aman")
    liked_by = rec.get("liked_by",[])
    if not liked_by: return bot.reply_to(message,"No one liked you yet")
    db = load_db_from_channel()
    names = [db.get("users",{}).get(str(uid),{}).get("name",uid) for uid in liked_by]
    bot.reply_to(message,"People who liked you:\n"+ "\n".join(names))

# --- /matches ---
@bot.message_handler(commands=["matches"])
def cmd_matches(message):
    tgid = message.from_user.id
    rec = get_user_record(tgid)
    if not rec or not rec.get("registered"): return bot.reply_to(message,"Register first")
    if not rec.get("vip"): return bot.reply_to(message,"VIP only. Preview: Anjali")
    matches = rec.get("matches",[])
    if not matches: return bot.reply_to(message,"No matches yet")
    db = load_db_from_channel()
    names = [db.get("users",{}).get(str(uid),{}).get("name",uid) for uid in matches]
    bot.reply_to(message,"Your matches:\n"+ "\n".join(names))

# --- Flask webhook ---
@app.route("/", methods=["POST"])
def webhook():
    update = request.get_json()
    if update:
        bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "OK",200

@app.route("/", methods=["GET"])
def index():
    return "Bot running",200

if __name__=="__main__":
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
