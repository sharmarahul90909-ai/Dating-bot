# app.py
import os
import logging
import time

from flask import Flask, request
import telebot

from db import load_db, save_db, safe_init_db
from handlers import register_handlers
from utils import ensure_env

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dating-bot")

# Ensure required env vars early
BOT_TOKEN, DB_CHANNEL_ID, WEBHOOK_URL = ensure_env()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# Set webhook on import/start (works for gunicorn; each worker may attempt it but that's ok)
def set_webhook_once():
    try:
        full = f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}"
        logger.info("Setting webhook to %s", full)
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=full)
        logger.info("Webhook set.")
    except Exception as e:
        logger.exception("Failed to set webhook: %s", e)

set_webhook_once()

# Register handlers from handlers.py
register_handlers(bot)

# Webhook endpoint for Telegram to post updates
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    payload = request.get_data().decode("utf-8")
    if not payload:
        return "", 400
    update = telebot.types.Update.de_json(payload)
    bot.process_new_updates([update])
    return "", 200

# Health check
@app.route("/", methods=["GET"])
def index():
    return "Dating-bot running", 200

# Optional: admin endpoint to re-init DB (protected by ADMIN_IDS check in bot command)
@app.route("/reinit_db", methods=["POST"])
def reinit_db():
    # Keep simple — call safe_init_db; admin actions via telegram recommended
    ok = safe_init_db("webhook")
    return ("ok" if ok else "fail"), (200 if ok else 500)

# When running directly (for local debugging)
if __name__ == "__main__":
    logger.info("Starting Flask (development) - use gunicorn in production")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
