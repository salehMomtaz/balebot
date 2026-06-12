# modules/admin.py
import os
import shutil
from aiogram import Router, F, Bot, BaseMiddleware
from aiogram.types import (
    CallbackQuery, 
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    TelegramObject,
    ForceReply
)
import config
from utils.gate import (
    load_database, 
    add_user, 
    remove_user, 
    unblacklist_user, 
    is_document_mode, 
    toggle_document_mode,
    is_blacklisted,
    blacklist_user,
    is_authorized
)
from utils.id_validator import is_valid_telegram_id

# Instantiate the independent modular router
admin_router = Router()

# Map callback string shortcuts to physical filenames
COOKIE_MAP = {
    "ytcookies": config.YT_COOKIES,
    "igcookies": config.IG_COOKIES,
    "ttcookies": config.TT_COOKIES,
    "xcookies": config.X_COOKIES,
    "cookies": config.COOKIES_FILE
}

# In-memory dictionary to track administrative states per user
USER_STATES = {}

# In-memory registry to track and delete active prompts on cancel or success
ACTIVE_PROMPTS = {}

# Global reusable "Back to Console" inline button
back_markup = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="◀️ Back to Console", callback_data="admin_main")]
])

# =========================================================================
# 0. Global Interceptor Middleware (Strict Security Shield)
# =========================================================================
class SecurityGateMiddleware(BaseMiddleware):
    """
    aiogram v3 Security Gate Middleware:
    Pre-intercepts all incoming updates, blocks banned users, Whitelists
    authorized users, and automatically blacklists intruders.
    """
    async def __call__(self, handler, event: TelegramObject, data: dict):
        from main import log_event
        
        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)
            
        if is_blacklisted(user_id):
            return # Block and ignore completely
            
        if not is_authorized(user_id):
            blacklist_user(user_id)
            await log_event(f"⚠️ *Intruder Blocked:* User `{user_id}` has been banned.")
            return # Block propagation
            
        return await handler(event, data)

# =========================================================================
# Helpers
# =========================================================================
async def purge_active_prompt(user_id: int, bot: Bot):
    """Helper to safely delete any active prompt bubble from the chat stream."""
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
    
    # Failsafe escape: If you type /start or console triggers, clear active state and let main router handle it
    if input_text.lower() in ["/start", "🛠 console", "hey", "console", "hi!"]:
        USER_STATES.pop(user_id, None)
        await purge_active_prompt(user_id, bot)
        return  # Bypasses and continues processing downstream to main handler
        
    prompt_id = ACTIVE_PROMPTS.pop(user_id, None)

    # A. Handle Cookie Replacement State
    if state.startswith("waiting_for_replace_"):
        USER_STATES.pop(user_id, None)
        
        # Delete the bot's old prompt message
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
            await log_event(f"🍪 *Admin Action:* Cookie profile `{cookie_key}.txt` was replaced via chat interface.")
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
    USER_STATES.pop(user_id, None)  # Reset state
    
    # Delete the bot's old prompt message
    if prompt_id:
        try:
            await bot.delete_message(chat_id=user_id, message_id=prompt_id)
        except Exception:
            pass
    
    if state == "waiting_for_add_user":
        if add_user(target_id):
            await message.reply(
                text=f"✅ User `{target_id}` has been authorized successfully.",
                reply_markup=back_markup
            )
            await log_event(f"👥 *User Whitelisted:* Creator whitelisted User ID `{target_id}`.")
        else:
            await message.reply(
                text=f"ℹ️ User `{target_id}` was already authorized.",
                reply_markup=back_markup
            )
            
    elif state == "waiting_for_remove_user":
        db = load_database()
        if target_id not in db["authorized"]:
            await message.reply(
                text=f"❌ *Error:* User ID `{target_id}` is not currently authorized.",
                reply_markup=back_markup
            )
            return
            
        if remove_user(target_id):
            await message.reply(
                text=f"✅ User `{target_id}` has been removed.",
                reply_markup=back_markup
            )
            await log_event(f"👥 *User Revoked:* Creator removed User ID `{target_id}`.")
            
    elif state == "waiting_for_unban":
        db = load_database()
        if target_id not in db["blacklisted"]:
            await message.reply(
                text=f"❌ *Error:* User ID `{target_id}` is not found in the blacklist.",
                reply_markup=back_markup
            )
            return
            
        if unblacklist_user(target_id):
            await message.reply(
                text=f"✅ User `{target_id}` has been unbanned.",
                reply_markup=back_markup
            )
            await log_event(f"🔓 *User Unbanned:* Creator unbanned and unblacklisted User ID `{target_id}`.")

# =========================================================================
# 2. Standard Private Text Router (Handles /start and console text triggers)
# =========================================================================
@admin_router.message(
    F.text, 
    F.chat.type == "private",
    lambda message: not message.text.strip().split("|")[0].strip().startswith("http")
)
async def admin_start_text_handler(message: Message):
    text = message.text.strip()
    user_id = message.from_user.id
        
    if user_id == config.SYSTEM_CREATOR_ID:
        doc_status = "✅" if is_document_mode(user_id) else "❌"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 List Users", callback_data="admin_list"), InlineKeyboardButton(text="➕ Add User", callback_data="admin_add")],
            [InlineKeyboardButton(text="➖ Remove User", callback_data="admin_remove"), InlineKeyboardButton(text="🚫 Blacklist Logs", callback_data="admin_blacklist")],
            [InlineKeyboardButton(text=f"📄 Doc Mode: {doc_status}", callback_data="admin_toggle_doc"), InlineKeyboardButton(text="🍪 Cookie Jars", callback_data="admin_cookies_menu")],
            [InlineKeyboardButton(text="💥 Abort Transfer", callback_data="admin_abort_queue"), InlineKeyboardButton(text="❌ Close Console", callback_data="admin_close")]
        ])
        await message.reply(
            text="🛠 *Admin System Console*\nChoose an administrative action below:",
            reply_markup=keyboard
        )
    else:
        await message.reply(
            text="👋 *Hello! Welcome to your Private Downloader Bot.*\n\n"
                 "To get started:\n"
                 "• Send me any YouTube, Instagram, TikTok, or X/Twitter link to download it.\n"
                 "• Send me any direct file URL to upload it directly to Bale.\n"
                 "• Forward me any document/file to generate an instant direct stream link."
        )

# =========================================================================
# 3. Callback Query Handler (Handles inline buttons)
# =========================================================================
@admin_router.callback_query(F.data.startswith("admin_"))
async def admin_callback_handler(callback_query: CallbackQuery, bot: Bot):
    from main import log_event, queue
    
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if user_id != config.SYSTEM_CREATOR_ID:
        await callback_query.answer("Access Denied.", show_alert=True)
        return
        
    if data == "admin_close":
        USER_STATES.pop(user_id, None)
        await purge_active_prompt(user_id, bot)
        await callback_query.message.delete()
        await callback_query.answer("Console closed.")
        
    elif data == "admin_abort_queue":
        queue_len = len(queue._pending)
        queue._pending.clear()
        queue._active = False
        
        if os.path.exists("cache"):
            try:
                shutil.rmtree("cache")
                os.makedirs("cache", exist_ok=True)
            except Exception:
                pass
                
        await callback_query.answer("💥 System Reset: All queue jobs aborted and cache purged!", show_alert=True)
        await log_event(f"💥 *Admin Action:* Queue reset executed. {queue_len} pending jobs aborted.")
        
    elif data == "admin_toggle_doc":
        state = toggle_document_mode(user_id)
        status_str = "✅" if state else "❌"
        await callback_query.answer(f"📄 Document Mode toggled to {status_str}.", show_alert=True)
        await log_event(f"⚙️ *Admin Action:* Document Mode toggled to {status_str}.")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 List Users", callback_data="admin_list"), InlineKeyboardButton(text="➕ Add User", callback_data="admin_add")],
            [InlineKeyboardButton(text="➖ Remove User", callback_data="admin_remove"), InlineKeyboardButton(text="🚫 Blacklist Logs", callback_data="admin_blacklist")],
            [InlineKeyboardButton(text=f"📄 Doc Mode: {status_str}", callback_data="admin_toggle_doc"), InlineKeyboardButton(text="🍪 Cookie Jars", callback_data="admin_cookies_menu")],
            [InlineKeyboardButton(text="💥 Abort Transfer", callback_data="admin_abort_queue"), InlineKeyboardButton(text="❌ Close Console", callback_data="admin_close")]
        ])
        try:
            await callback_query.message.edit_text(
                text="🛠 *Admin System Console*\nChoose an administrative action below:",
                reply_markup=keyboard
            )
        except Exception:
            pass
        
    elif data == "admin_list":
        db = load_database()
        users = db["authorized"]
        text = "📋 *Authorized Users List:*\n" + "\n".join([f"• `{uid}`" for uid in users]) if users else "No additional users authorized."
        await callback_query.message.edit_text(text=text, reply_markup=back_markup)
        await callback_query.answer()
        
    elif data == "admin_blacklist":
        db = load_database()
        blacklisted = db["blacklisted"]
        text = "🚫 *Banned Intruders List:*\n" + "\n".join([f"• `{uid}`" for uid in blacklisted]) if blacklisted else "Blacklist registry is empty."
        
        keyboard_rows = []
        if blacklisted:
            keyboard_rows.append([InlineKeyboardButton(text="🔓 Unban User", callback_data="admin_unban")])
        keyboard_rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="admin_main")])
        
        await callback_query.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows))
        await callback_query.answer()
        
    elif data == "admin_unban":
        USER_STATES[user_id] = "waiting_for_unban"
        ACTIVE_PROMPTS[user_id] = callback_query.message.message_id
        await callback_query.message.edit_text(
            text="🔓 *Unban User*\nPlease type the numerical ID of the blocked user you want to unban directly in your text box and press send:",
            reply_markup=back_markup
        )
        await callback_query.answer()
        
    elif data == "admin_main":
        USER_STATES.pop(user_id, None)  # Reset state on return
        ACTIVE_PROMPTS.pop(user_id, None)
        
        doc_status = "✅" if is_document_mode(user_id) else "❌"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 List Users", callback_data="admin_list"), InlineKeyboardButton(text="➕ Add User", callback_data="admin_add")],
            [InlineKeyboardButton(text="➖ Remove User", callback_data="admin_remove"), InlineKeyboardButton(text="🚫 Blacklist Logs", callback_data="admin_blacklist")],
            [InlineKeyboardButton(text=f"📄 Doc Mode: {doc_status}", callback_data="admin_toggle_doc"), InlineKeyboardButton(text="🍪 Cookie Jars", callback_data="admin_cookies_menu")],
            [InlineKeyboardButton(text="💥 Abort Transfer", callback_data="admin_abort_queue"), InlineKeyboardButton(text="❌ Close Console", callback_data="admin_close")]
        ])
        await callback_query.message.edit_text(
            text="🛠 *Admin System Console*\nChoose an administrative action below:",
            reply_markup=keyboard
        )
        await callback_query.answer()
        
    elif data == "admin_add":
        USER_STATES[user_id] = "waiting_for_add_user"
        ACTIVE_PROMPTS[user_id] = callback_query.message.message_id
        await callback_query.message.edit_text(
            text="➕ *Add Authorized User*\nPlease type the numerical ID of the user you want to authorize directly in your text box and press send:",
            reply_markup=back_markup
        )
        await callback_query.answer()
        
    elif data == "admin_remove":
        USER_STATES[user_id] = "waiting_for_remove_user"
        ACTIVE_PROMPTS[user_id] = callback_query.message.message_id
        await callback_query.message.edit_text(
            text="➖ *Remove Authorized User*\nPlease type the numerical ID of the user you want to remove directly in your text box and press send:",
            reply_markup=back_markup
        )
        await callback_query.answer()

    # =========================================================================
    # Cookies Sub-Menus Configuration (With Safe try/except popup containment)
    # =========================================================================
    elif data == "admin_cookies_menu":
        USER_STATES.pop(user_id, None)
        ACTIVE_PROMPTS.pop(user_id, None)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="YouTube", callback_data="admin_cookie_select:ytcookies"), InlineKeyboardButton(text="Instagram", callback_data="admin_cookie_select:igcookies")],
            [InlineKeyboardButton(text="TikTok", callback_data="admin_cookie_select:ttcookies"), InlineKeyboardButton(text="X/Twitter", callback_data="admin_cookie_select:xcookies")],
            [InlineKeyboardButton(text="Global (cookies.txt)", callback_data="admin_cookie_select:cookies")],
            [InlineKeyboardButton(text="◀️ Return to Console", callback_data="admin_main")]
        ])
        await callback_query.message.edit_text(
            text="🍪 *Cookie Jars Manager*\nSelect a cookie profile to view or edit:",
            reply_markup=keyboard
        )
        await callback_query.answer()
            
    elif data.startswith("admin_cookie_select:"):
        cookie_key = data.split(":")[1]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Download", callback_data=f"admin_cookie_action:{cookie_key}:download")],
            [InlineKeyboardButton(text="✏️ Replace", callback_data=f"admin_cookie_action:{cookie_key}:replace")],
            [InlineKeyboardButton(text="◀️ Back", callback_data="admin_cookies_menu")]
        ])
        await callback_query.message.edit_text(
            text=f"🍪 *Cookie Profile: `{cookie_key}.txt`*\nSelect an administration action:",
            reply_markup=keyboard
        )
        await callback_query.answer()
            
    elif data.startswith("admin_cookie_action:"):
        _, cookie_key, action = data.split(":")
        file_path = COOKIE_MAP.get(cookie_key)
        
        if action == "download":
            if os.path.exists(file_path):
                try:
                    from aiogram.types import FSInputFile
                    await bot.send_document(
                        chat_id=user_id,
                        document=FSInputFile(file_path),
                        caption=f"🍪 Here is your active `{cookie_key}.txt` file."
                    )
                    await callback_query.answer("✅ Cookie file delivered!")
                except Exception as ce:
                    await callback_query.answer(f"❌ API Error: {str(ce)}", show_alert=True)
            else:
                await callback_query.answer("⚠️ File is empty or does not exist on VPS yet.", show_alert=True)
                
        elif action == "replace":
            USER_STATES[user_id] = f"waiting_for_replace_{cookie_key}"
            ACTIVE_PROMPTS[user_id] = callback_query.message.message_id
            await callback_query.message.edit_text(
                text=f"✏️ *Replace {cookie_key}.txt*\nPlease paste your fresh Netscape formatted cookies into your standard text box and press send:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Cancel & Return", callback_data=f"admin_cookie_select:{cookie_key}")]])
            )
            await callback_query.answer()