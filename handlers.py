# handlers.py
import time
import logging
from typing import Dict, Any
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from db import load_db, save_db, get_user_record, save_user_record, delete_user_record, safe_init_db
from keyboards import main_menu_keyboard, inline_main_menu, profile_buttons
from utils import set_bot_instance, get_bot_instance
import os

logger = logging.getLogger("dating-bot.handlers")

# Admin IDs from env
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# Fake sample profiles (used for non-VIP)
FAKE_MALE = [
    {"name":"Rahul","age":24,"city":"Delhi","bio":"Coffee & coding.","photo":"https://picsum.photos/400?random=11"},
    {"name":"Aman","age":26,"city":"Mumbai","bio":"Traveler.","photo":"https://picsum.photos/400?random=12"}
]
FAKE_FEMALE = [
    {"name":"Priya","age":22,"city":"Delhi","bio":"Bookworm.","photo":"https://picsum.photos/400?random=21"},
    {"name":"Anjali","age":24,"city":"Pune","bio":"Artist.","photo":"https://picsum.photos/400?random=22"}
]

# Registration state (in-memory)
REG_STEP: Dict[int, str] = {}
TEMP_BUFFER: Dict[int, Dict[str, Any]] = {}

def register_handlers(bot: TeleBot):
    # Provide bot instance to utils/db
    set_bot_instance(bot)

    # Handlers below use decorator style; we apply them dynamically here for clarity
    @bot.message_handler(commands=["init_db"])
    def cmd_init_db(message):
        if message.from_user.id not in ADMIN_IDS:
            bot.reply_to(message, "Admin only.")
            return
        ok = safe_init_db(message.from_user.id)
        bot.reply_to(message, "DB initialized (preserved) ✅" if ok else "DB init failed ❌")

    @bot.message_handler(commands=["start"])
    def cmd_start(message):
        uid = message.from_user.id
        rec = get_user_record(uid)
        if rec and rec.get("registered"):
            bot.send_message(uid, f"Welcome back, <b>{rec.get('name')}</b>!", parse_mode="HTML", reply_markup=main_menu_keyboard())
            return
        TEMP_BUFFER[uid] = {}
        REG_STEP[uid] = "photo"
        bot.send_message(uid, "Welcome! Step 1: Please upload a profile photo (mandatory).", reply_markup=main_menu_keyboard())

    @bot.message_handler(content_types=["photo"])
    def handle_photo(message):
        uid = message.from_user.id
        step = REG_STEP.get(uid)
        if step != "photo":
            # allow updating photo for registered users
            rec = get_user_record(uid)
            if rec and rec.get("registered"):
                rec["photo_file_id"] = message.photo[-1].file_id
                save_user_record(uid, rec)
                bot.reply_to(message, "Profile photo updated.")
            else:
                bot.reply_to(message, "Unexpected photo. Use /start to register.")
            return
        TEMP_BUFFER[uid]["photo_file_id"] = message.photo[-1].file_id
        REG_STEP[uid] = "name"
        bot.send_message(uid, "Photo saved. Step 2: Send your full name.")

    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def handle_text(message):
        uid = message.from_user.id
        text = message.text.strip()
        # ignore commands here
        if text.startswith("/"):
            return
        step = REG_STEP.get(uid)
        if not step:
            # casual text -> suggest menu
            bot.send_message(uid, "Use the menu or /start to register.", reply_markup=main_menu_keyboard())
            return

        # registration state machine
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
            bot.send_message(uid, "Step 4: Gender (male/female).")
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
                bot.send_message(uid, "Type 'male','female' or 'both'.")
                return
            TEMP_BUFFER[uid]["interest"] = text.lower()
            REG_STEP[uid] = "city"
            bot.send_message(uid, "Step 6: Enter your city")
            return
        if step == "city":
            TEMP_BUFFER[uid]["city"] = text
            REG_STEP[uid] = "bio"
            bot.send_message(uid, "Step 7: Send a short bio (one line).")
            return
        if step == "bio":
            TEMP_BUFFER[uid]["bio"] = text
            # finalize
            rec = {
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
            ok = save_user_record(uid, rec)
            REG_STEP.pop(uid, None)
            TEMP_BUFFER.pop(uid, None)
            if ok:
                bot.send_message(uid, "Registration complete! Use /menu to browse.", reply_markup=main_menu_keyboard())
            else:
                bot.send_message(uid, "Failed to save profile — contact admin.")
            return

    # Menu and action commands
    @bot.message_handler(commands=["menu"])
    def cmd_menu(message):
        uid = message.from_user.id
        rec = get_user_record(uid)
        if not rec or not rec.get("registered"):
            bot.send_message(uid, "Register first with /start.")
            return
        bot.send_message(uid, "Main Menu", reply_markup=inline_main_menu())

    @bot.callback_query_handler(func=lambda c: True)
    def callback_query(call):
        uid = call.from_user.id
        data = call.data or ""
        # menu actions
        if data == "menu_profile":
            rec = get_user_record(uid)
            if not rec:
                bot.send_message(uid, "No profile found. /start to register.")
                return
            text = f"Name: {rec.get('name')}\nAge: {rec.get('age')}\nGender: {rec.get('gender')}\nCity: {rec.get('city')}\nBio: {rec.get('bio')}\nVIP: {rec.get('vip')}\nCoins: {rec.get('coins')}"
            try:
                bot.send_photo(uid, rec.get("photo_file_id"), caption=text)
            except Exception:
                bot.send_message(uid, text)
            return

        if data == "menu_browse":
            # start browsing (VIP sees real profiles, free sees fake)
            rec = get_user_record(uid)
            if not rec:
                bot.send_message(uid, "Register first with /start.")
                return
            if rec.get("vip"):
                # show next real profile
                db = load_db()
                users = db.get("users", {})
                candidates = []
                for uid_s, u in users.items():
                    # skip self
                    if int(uid_s) == uid:
                        continue
                    if not u.get("registered"):
                        continue
                    pref = rec.get("interest", "both")
                    if pref == "both" or u.get("gender") == pref:
                        candidates.append((int(uid_s), u))
                if not candidates:
                    bot.send_message(uid, "No real profiles available yet.")
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
                # show fake
                pref = rec.get("interest", "both")
                pool = FAKE_MALE + FAKE_FEMALE if pref == "both" else (FAKE_MALE if pref == "male" else FAKE_FEMALE)
                idx = rec.get("current_fake_index", 0) % len(pool)
                profile = pool[idx]
                rec["current_fake_index"] = (idx + 1) % len(pool)
                save_user_record(uid, rec)
                bot.send_photo(uid, profile["photo"], caption=f"{profile['name']}, {profile['age']}\n{profile['city']}\n\n{profile['bio']}", reply_markup=profile_buttons(0, False))
            return

        # like/skip handling
        if data.startswith("like_"):
            target = int(data.split("_", 1)[1])
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
            # check for match
            if str(uid) in tgt.get("likes", []):
                # mutual
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
            # trigger browse again
            bot.send_message(uid, "/menu")
            return

        # fake preview actions
        if data == "fake_like":
            bot.answer_callback_query(call.id, "Preview: someone liked you (fake). Upgrade to VIP for real matches.")
            try:
                bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=(call.message.caption or "") + "\n\n❤️ They liked you! (preview)")
            except Exception:
                pass
            return
        if data == "fake_next":
            bot.answer_callback_query(call.id, "Next preview...")
            bot.send_message(uid, "/menu")
            return

        # admin menu placeholder
        if data == "menu_admin":
            if uid not in ADMIN_IDS:
                bot.answer_callback_query(call.id, "Admin only.")
                return
            # admin quick actions
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

    # Admin commands
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
        for uid, u in users.items():
            try:
                bot.send_message(int(uid), f"[Broadcast]\n\n{text}")
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

    @bot.message_handler(commands=["help"])
    def cmd_help(message):
        bot.send_message(message.chat.id, "Commands:\n/start\n/menu\n/profile\n/profiles\n/buy\n/help\nAdmins: /grant_vip /revoke_vip /broadcast /delete_user")

    # simple profile command
    @bot.message_handler(commands=["profile"])
    def cmd_profile(message):
        uid = message.from_user.id
        rec = get_user_record(uid)
        if not rec:
            bot.reply_to(message, "No profile found. /start to register.")
            return
        caption = f"Name: {rec.get('name')}\nAge: {rec.get('age')}\nCity: {rec.get('city')}\nBio: {rec.get('bio')}\nVIP: {rec.get('vip')}"
        try:
            bot.send_photo(uid, rec.get("photo_file_id"), caption=caption)
        except Exception:
            bot.send_message(uid, caption)

    @bot.message_handler(commands=["profiles"])
    def cmd_profiles(message):
        uid = message.from_user.id
        bot.send_message(uid, "Use /menu -> Browse (recommended).")

    # end register_handlers
    