# modules/user/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_guide_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns the main, clean 'Complete Bot Guide' inline button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📘 Complete Bot Guide", callback_data="user_help_guide")]
    ])

def get_help_submenu_keyboard() -> InlineKeyboardMarkup:
    """Returns the organized submenu selectors for different bot guides."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐙 GitHub & Tools", callback_data="user_help_select:github")],
        [InlineKeyboardButton(text="🎬 YouTube & Transcripts", callback_data="user_help_select:youtube")],
        [InlineKeyboardButton(text="🈯 Google Translate", callback_data="user_help_select:translate")],
        [InlineKeyboardButton(text="🌐 Direct Link & Web", callback_data="user_help_select:direct")],
        [InlineKeyboardButton(text="❌ Close Guide", callback_data="user_close_menu")]
    ])