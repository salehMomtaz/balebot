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
# 1. Admin Command Handler (Allows Creator to Open the Console Menu)
# =========================================================================
@admin_router.message(
    F.text,
    F.chat.type == "private",
    lambda message: message.from_user.id == config.SYSTEM_CREATOR_ID,
    lambda message: message.text.strip().lower() in ["/start", "/admin", "🛠 console", "console"]
)
async def admin_console_cmd_handler(message: Message):
    user_id = message.from_user.id
    USER_STATES.pop(user_id, None)
    await purge_active_prompt(user_id, message.bot)
    
    await message.reply(
        text="🛠 *Admin Console*\nSelect an action below to manage authorized users, blacklist logs, cookie jars, or system settings:",
        reply_markup=get_admin_console_keyboard(user_id)
    )

# =========================================================================
# 2. State Machine Handler (Processes text inputs ONLY if user is in an active state)
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

# =========================================================================
# 3. Callback Query Handlers (Processes Main Console Menu Buttons)
# =========================================================================

@admin_router.callback_query(F.data == "admin_main")
async def callback_admin_main(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    USER_STATES.pop(user_id, None)
    await callback_query.message.edit_text(
        text="🛠 *Admin Console*\nSelect an action below to manage authorized users, blacklist logs, cookie jars, or system settings:",
        reply_markup=get_admin_console_keyboard(user_id)
    )
    await callback_query.answer()

@admin_router.callback_query(F.data == "admin_list")
async def callback_admin_list(callback_query: CallbackQuery):
    db = load_database()
    auth_list = db.get("authorized", [])
    if not auth_list:
        text = "👥 *Authorized Users*\n\nNo users are currently authorized."
    else:
        lines = [f"• `{uid}`" for uid in auth_list]
        text = "👥 *Authorized Users List*\n\n" + "\n".join(lines)
    await callback_query.message.edit_text(text=text, reply_markup=back_markup)
    await callback_query.answer()

@admin_router.callback_query(F.data == "admin_add")
async def callback_admin_add(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    USER_STATES[user_id] = "waiting_for_add_user"
    
    prompt_msg = await callback_query.message.reply(
        text="➕ *Add User*\nPlease enter the numeric User ID to authorize (or send /start to cancel):",
        reply_markup=ForceReply(selective=True)
    )
    ACTIVE_PROMPTS[user_id] = prompt_msg.message_id
    await callback_query.answer()

@admin_router.callback_query(F.data == "admin_remove")
async def callback_admin_remove(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    USER_STATES[user_id] = "waiting_for_remove_user"
    
    prompt_msg = await callback_query.message.reply(
        text="➖ *Remove User*\nPlease enter the numeric User ID to revoke (or send /start to cancel):",
        reply_markup=ForceReply(selective=True)
    )
    ACTIVE_PROMPTS[user_id] = prompt_msg.message_id
    await callback_query.answer()

@admin_router.callback_query(F.data == "admin_blacklist")
async def callback_admin_blacklist(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    db = load_database()
    black_list = db.get("blacklisted", [])
    if not black_list:
        text = "🚫 *Blacklisted Users*\n\nNo users are currently blacklisted."
        await callback_query.message.edit_text(text=text, reply_markup=back_markup)
    else:
        USER_STATES[user_id] = "waiting_for_unban"
        lines = [f"• `{uid}`" for uid in black_list]
        text = (
            "🚫 *Blacklisted Users List*\n\n" + "\n".join(lines) + 
            "\n\nTo unban a user from the blacklist, enter their numeric User ID below (or send /start to cancel):"
        )
        prompt_msg = await callback_query.message.reply(text=text, reply_markup=ForceReply(selective=True))
        ACTIVE_PROMPTS[user_id] = prompt_msg.message_id
    await callback_query.answer()

@admin_router.callback_query(F.data == "admin_toggle_doc")
async def callback_admin_toggle_doc(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    state = toggle_document_mode(user_id)
    status_str = "Enabled ✅" if state else "Disabled ❌"
    await callback_query.answer(f"Doc Mode {status_str}", show_alert=True)
    await callback_query.message.edit_reply_markup(reply_markup=get_admin_console_keyboard(user_id))

@admin_router.callback_query(F.data == "admin_cookies_menu")
async def callback_admin_cookies_menu(callback_query: CallbackQuery):
    await callback_query.message.edit_text(
        text="🍪 *Cookie Profile Jars*\nSelect a site-specific jar to view actions, download, or replace authentication values:",
        reply_markup=get_cookies_menu_keyboard()
    )
    await callback_query.answer()

@admin_router.callback_query(F.data.startswith("admin_cookie_select:"))
async def callback_admin_cookie_select(callback_query: CallbackQuery):
    cookie_key = callback_query.data.split(":")[1]
    await callback_query.message.edit_text(
        text=f"🍪 *Cookie Profile: {cookie_key}.txt*\nSelect an action to perform on this jar:",
        reply_markup=get_cookie_action_keyboard(cookie_key)
    )
    await callback_query.answer()

@admin_router.callback_query(F.data.startswith("admin_cookie_action:"))
async def callback_admin_cookie_action(callback_query: CallbackQuery, bot: Bot):
    parts = callback_query.data.split(":")
    cookie_key = parts[1]
    action = parts[2]
    user_id = callback_query.from_user.id
    
    file_path = COOKIE_MAP.get(cookie_key)
    if not file_path:
        await callback_query.answer("❌ Invalid cookie profile.", show_alert=True)
        return
        
    if action == "download":
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            await callback_query.answer("Delivering file...")
            from utils.uploader import upload_file_direct_to_bale
            await upload_file_direct_to_bale(
                method="sendDocument",
                chat_id=user_id,
                file_path=file_path,
                caption=f"🍪 *Cookie Jar:* `{cookie_key}.txt`"
            )
        else:
            await callback_query.answer("⚠️ File is empty or does not exist yet.", show_alert=True)
            
    elif action == "replace":
        USER_STATES[user_id] = f"waiting_for_replace_{cookie_key}"
        prompt_msg = await callback_query.message.reply(
            text=f"📝 *Replace Cookies for {cookie_key}.txt*\n"
                 f"Please paste the cookie contents (Netscape format) below (or send /start to cancel):",
            reply_markup=ForceReply(selective=True)
        )
        ACTIVE_PROMPTS[user_id] = prompt_msg.message_id
        await callback_query.answer()

@admin_router.callback_query(F.data == "admin_abort_queue")
async def callback_admin_abort_queue(callback_query: CallbackQuery):
    from utils.shared import queue
    async with queue._lock:
        queue._pending.clear()
        queue._active = False
    await callback_query.message.edit_text(
        text="💥 *Active Transfer Queue Aborted*\nAll pending files and downloads in the queue have been successfully cleared.",
        reply_markup=back_markup
    )
    await callback_query.answer("Queue cleared.", show_alert=True)

@admin_router.callback_query(F.data == "admin_close")
async def callback_admin_close(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    USER_STATES.pop(user_id, None)
    await callback_query.message.delete()
    await callback_query.answer("Console closed.")