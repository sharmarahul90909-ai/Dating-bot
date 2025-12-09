# db.py
import json
import logging
import time

from typing import Dict, Any
from telebot import TeleBot

import os
from utils import BOT_TOKEN, DB_CHANNEL_ID, get_bot_instance

logger = logging.getLogger("dating-bot.db")

# Note: get_bot_instance returns TeleBot instance created in app -- import there to avoid circular import.
# But handlers import db; to avoid circularity, pass bot where network calls are used or import lazily.

def load_db() -> Dict[str, Any]:
    """
    Load JSON from channel pinned message. If none or parse error, returns base structure.
    """
    bot = get_bot_instance()
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        if pinned and pinned.text:
            try:
                return json.loads(pinned.text)
            except Exception as e:
                logger.warning("Pinned JSON parse error: %s", e)
                return {"users": {}, "meta": {}}
        else:
            return {"users": {}, "meta": {}}
    except Exception as e:
        logger.exception("Failed to load DB from channel: %s", e)
        return {"users": {}, "meta": {}}

def save_db(db: Dict[str, Any]) -> bool:
    """
    Serialize and edit pinned message. Returns True on success.
    """
    bot = get_bot_instance()
    try:
        text = json.dumps(db, ensure_ascii=False, indent=2)
        if len(text) > 3800:
            logger.error("DB too large to store in pinned message (%d chars).", len(text))
            return False
        chat = bot.get_chat(DB_CHANNEL_ID)
        pinned = getattr(chat, "pinned_message", None)
        if pinned:
            bot.edit_message_text(chat_id=DB_CHANNEL_ID, message_id=pinned.message_id, text=text)
            return True
        else:
            msg = bot.send_message(DB_CHANNEL_ID, text)
            time.sleep(0.5)
            bot.pin_chat_message(DB_CHANNEL_ID, msg.message_id, disable_notification=True)
            return True
    except Exception as e:
        logger.exception("Failed to save DB to channel: %s", e)
        return False

def safe_init_db(created_by) -> bool:
    """
    Initialize DB if absent. Does not wipe users if already present.
    """
    db = load_db()
    if "users" in db and db["users"]:
        # already present; only update meta
        db.setdefault("meta", {})["last_init_by"] = created_by
        db["meta"]["last_init_at"] = int(time.time())
        return save_db(db)
    db = {"users": {}, "meta": {"created_by": created_by, "created_at": int(time.time())}}
    return save_db(db)

# Convenience wrappers:
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
    