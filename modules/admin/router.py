# modules/admin/router.py
import os
import shutil
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, ForceReply
import config
from utils.gate import (
    load_database, 
    add_user, 
    remove_user, 
    unblacklist_user, 
    is_document_mode, 
    toggle_document_mode
)
from utils.id_validator import is_valid_telegram_id
from modules.admin.keyboards import get_admin_console_keyboard, get_cookies_menu_keyboard, get_cookie_action_keyboard, back_markup
from modules.admin.cookies import COOKIE_MAP

admin_router = Router()

USER_STATES = {}
ACTIVE_PROMPTS = {}

async def purge_active_prompt(user_id: int, bot: Bot):
    """Safely delete any active prompt message from the stream on cancel or success."""
    prompt_id = ACTIVE_PROMPTS.pop(user_id, None)
    if prompt_id:
        try:
            await bot.delete_message(chat_id=user_id, message_id=prompt_id)
        except Exception:
            pass

# =========================================================================
# 1. State Machine Handler (Processes text inputs ONLY if user is in an active state)
# =========================================================================
@admin_router.message(F.text, F.chat.type == "private", lambda message: message.from_user.id in USER_STATES)
async def admin_state_message_handler(message: Message, bot: Bot):
    from main import log_event
    user_id = message.from_user.id
    state = USER_STATES.get(user_id)
    input_text = message.text.strip()
    
    # Escape handler: if admin types standard command instead of ID, clear state and propagate
    if input_text.lower() in ["/start", "🛠 console", "hey", "console", "hi!"]:
        USER_STATES.pop(user_id, None)
        await purge_active_prompt(user_id, bot)
        return  # Bypasses and continues processing downstream to user router

    prompt_id = ACTIVE_PROMPTS.pop(user_id, None)

    # A. Handle Cookie Replacement State
    if state.startswith("waiting_for_replace_"):
        USER_STATES.pop(user_id, None)
        if prompt_id:
            try:
                await bot.delete_message(chat_id=user_id, message_id=prompt_id)
            except Exception:
                pass
        
        cookie_key = state.split("waiting_for_replace_")[1]
        file_path = COOKIE_MAP.get(cookie_key)
        if not file_path:
            await message.reply(text="❌ *Error:* Invalid cookie profile selected.", reply_markup=back_markup)
            return
            
        # Prepend Netscape headers automatically if missing
        final_content = input_text
        if not input_text.startswith("# Netscape"):
            final_content = f"# Netscape HTTP Cookie File\n{input_text}"
            
        try:
            with open(file_path, "w") as f:
                f.write(final_content)
            await message.reply(text=f"✅ `{cookie_key}.txt` successfully replaced!", reply_markup=back_markup)
            await log_event(f"🍪 *Admin Action:* Cookie profile `{cookie_key}.txt` was replaced.")
        except Exception as e:
            await message.reply(text=f"❌ *Failed to write cookie file:* {e}", reply_markup=back_markup)
        return

    # B. Handle User ID Input States (Add, Remove, Unban)
    if not is_valid_telegram_id(input_text):
        USER_STATES.pop(user_id, None)
        if prompt_id:
            try:
                await bot.delete_message(chat_id=user_id, message_id=prompt_id)
            except Exception:
                pass
        await message.reply(
            text="❌ *Error:* Invalid User ID. Please input digits only (between 5 and 11 numbers).",
            reply_markup=back_markup
        )
        return
        
    target_id = int(input_text)
    USER_STATES.pop(user_id, None)
    if prompt_id:
        try:
            await bot.delete_message(chat_id=user_id, message_id=prompt_id)
        except Exception:
            pass
    
    if state == "waiting_for_add_user":
        if add_user(target_id):
            await message.reply(text=f"✅ User `{target_id}` authorized successfully.", reply_markup=back_markup)
            await log_event(f"👥 *User Whitelisted:* Creator whitelisted User ID `{target_id}`.")
        else:
            await message.reply(text=f"ℹ️ User `{target_id}` was already authorized.", reply_markup=back_markup)
            
    elif state == "waiting_for_remove_user":
        db = load_database()
        if target_id not in db["authorized"]:
            await message.reply(text=f"❌ *Error:* User ID `{target_id}` is not currently authorized.", reply_markup=back_markup)
            return
        if remove_user(target_id):
            await message.reply(text=f"✅ User `{target_id}` has been removed.", reply_markup=back_markup)
            await log_event(f"👥 *User Revoked:* Creator removed User ID `{target_id}`.")
            
    elif state == "waiting_for_unban":
        db = load_database()
        if target_id not in db["blacklisted"]:
            await message.reply(text=f"❌ *Error:* User ID `{target_id}` is not found in the blacklist.", reply_markup=back_markup)
            return
        if unblacklist_user(target_id):
            await message.reply(text=f"✅ User `{target_id}` has been unbanned.", reply_markup=back_markup)
            await log_event(f"🔓 *User Unbanned:* Creator unbanned User ID `{target_id}`.")