# modules/admin/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.gate import is_document_mode

back_markup = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="◀️ Back to Console", callback_data="admin_main")]
])

def get_admin_console_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Builds the main Admin Console keyboard with live Doc Mode toggles."""
    doc_status = "✅" if is_document_mode(user_id) else "❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 List Users", callback_data="admin_list"), InlineKeyboardButton(text="➕ Add User", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Remove User", callback_data="admin_remove"), InlineKeyboardButton(text="🚫 Blacklist Logs", callback_data="admin_blacklist")],
        [InlineKeyboardButton(text=f"📄 Doc Mode: {doc_status}", callback_data="admin_toggle_doc"), InlineKeyboardButton(text="🍪 Cookie Jars", callback_data="admin_cookies_menu")],
        [InlineKeyboardButton(text="💥 Abort Transfer", callback_data="admin_abort_queue"), InlineKeyboardButton(text="⚙️ Set Size Limits", callback_data="admin_setlimit")],
        [InlineKeyboardButton(text="❌ Close Console", callback_data="admin_close")]
    ])

def get_cookies_menu_keyboard() -> InlineKeyboardMarkup:
    """Builds the cookie profile selector menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="YouTube", callback_data="admin_cookie_select:ytcookies"), InlineKeyboardButton(text="Instagram", callback_data="admin_cookie_select:igcookies")],
        [InlineKeyboardButton(text="TikTok", callback_data="admin_cookie_select:ttcookies"), InlineKeyboardButton(text="X/Twitter", callback_data="admin_cookie_select:xcookies")],
        [InlineKeyboardButton(text="Global (cookies.txt)", callback_data="admin_cookie_select:cookies")],
        [InlineKeyboardButton(text="◀️ Return to Console", callback_data="admin_main")]
    ])

def get_cookie_action_keyboard(cookie_key: str) -> InlineKeyboardMarkup:
    """Builds action options for selected cookie jars."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Test Jar", callback_data=f"admin_cookie_action:{cookie_key}:test")],
        [InlineKeyboardButton(text="📤 Download", callback_data=f"admin_cookie_action:{cookie_key}:download")],
        [InlineKeyboardButton(text="✏️ Replace", callback_data=f"admin_cookie_action:{cookie_key}:replace")],
        [InlineKeyboardButton(text="◀️ Back", callback_data="admin_cookies_menu")]
    ])