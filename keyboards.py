# keyboards.py
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def main_menu_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("/menu"),
        KeyboardButton("/profile"),
        KeyboardButton("/profiles"),
        KeyboardButton("/buy"),
    )
    return kb

def inline_main_menu():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("👤 Profile", callback_data="menu_profile"),
        InlineKeyboardButton("👀 Browse", callback_data="menu_browse")
    )
    markup.row(
        InlineKeyboardButton("💎 VIP", callback_data="menu_vip"),
        InlineKeyboardButton("🛠️ Admin", callback_data="menu_admin")
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
    