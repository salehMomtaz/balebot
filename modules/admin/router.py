# modules/admin/router.py
import os
import shutil
import logging
import io
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, ForceReply
import yt_dlp
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
from operators.downloader import get_cookies_for_url
import utils.shared as shared

admin_router = Router()
logger = logging.getLogger(__name__)

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

    # Clean up old prompt message to keep chat spotless
    if prompt_id:
        try:
            await bot.delete_message(chat_id=user_id, message_id=prompt_id)
        except Exception:
            pass

    # Delete the user's incoming message containing the raw text input (User ID or cookies)
    try:
        await bot.delete_message(chat_id=user_id, message_id=message.message_id)
    except Exception:
        pass

    # A. Handle Cookie Replacement State
    if state.startswith("waiting_for_replace_"):
        USER_STATES.pop(user_id, None)
        # Text messages are not accepted; we require a document file because Bale
        # fragments long text into multiple messages, corrupting Netscape cookie jars.
        await bot.send_message(
            chat_id=user_id,
            text="❌ *Please send the cookie jar as a `.txt` document file, not as text.*",
            reply_markup=back_markup
        )
        return
    if state == "waiting_for_setlimit":
        USER_STATES.pop(user_id, None)
        parts = input_text.split()
        if len(parts) != 2:
            await message.reply("Invalid format. Use: <key> <value_mb>")
            return

        key, raw_value = parts[0], parts[1]
        valid_keys = {"bale_hard_limit_mb", "split_target_mb", "binary_chunk_mb", "max_cache_age_hours"}
        if key not in valid_keys:
            await message.reply(f"Unknown key. Allowed: {', '.join(sorted(valid_keys))}")
            return

        try:
            value = int(raw_value)
            if value <= 0:
                raise ValueError
        except ValueError:
            await message.reply("Value must be a positive integer.")
            return

        shared.set_setting_mb(key, value)
        await message.reply(f"Updated {key} = {value}")
        logger.info(f"Admin {user_id} set runtime {key}={value}")
        return

    # B. Handle User ID Input States (Add, Remove, Unban)
    if not is_valid_telegram_id(input_text):
        USER_STATES.pop(user_id, None)
        await bot.send_message(
            chat_id=user_id,
            text="❌ *Error:* Invalid User ID. Please input digits only (between 5 and 11 numbers).",
            reply_markup=back_markup
        )
        return
        
    target_id = int(input_text)
    USER_STATES.pop(user_id, None)
    
    if state == "waiting_for_add_user":
        if add_user(target_id):
            await bot.send_message(chat_id=user_id, text=f"✅ User `{target_id}` authorized successfully.", reply_markup=back_markup)
            await log_event(f"👥 *User Whitelisted:* Creator whitelisted User ID `{target_id}`.")
        else:
            await bot.send_message(chat_id=user_id, text=f"ℹ️ User `{target_id}` was already authorized.", reply_markup=back_markup)
            
    elif state == "waiting_for_remove_user":
        db = load_database()
        if target_id not in db["authorized"]:
            await bot.send_message(chat_id=user_id, text=f"❌ *Error:* User ID `{target_id}` is not currently authorized.", reply_markup=back_markup)
            return
        if remove_user(target_id):
            await bot.send_message(chat_id=user_id, text=f"✅ User `{target_id}` has been removed.", reply_markup=back_markup)
            await log_event(f"👥 *User Revoked:* Creator removed User ID `{target_id}`.")
            
    elif state == "waiting_for_unban":
        db = load_database()
        if target_id not in db["blacklisted"]:
            await bot.send_message(chat_id=user_id, text=f"❌ *Error:* User ID `{target_id}` is not found in the blacklist.", reply_markup=back_markup)
            return
        if unblacklist_user(target_id):
            await bot.send_message(chat_id=user_id, text=f"✅ User `{target_id}` has been unbanned.", reply_markup=back_markup)
            await log_event(f"🔓 *User Unbanned:* Creator unbanned User ID `{target_id}`.")

# =========================================================================
# 2b. Cookie Jar Replacement via Document File
# =========================================================================
@admin_router.message(
    F.document,
    F.chat.type == "private",
    lambda message: message.from_user.id == config.SYSTEM_CREATOR_ID,
    lambda message: USER_STATES.get(message.from_user.id, "").startswith("waiting_for_replace_")
)
async def admin_cookie_replace_document_handler(message: Message, bot: Bot):
    from main import log_event
    user_id = message.from_user.id
    state = USER_STATES.pop(user_id, None)
    cookie_key = state.split("waiting_for_replace_")[1]
    file_path = COOKIE_MAP.get(cookie_key)

    prompt_id = ACTIVE_PROMPTS.pop(user_id, None)
    if prompt_id:
        try:
            await bot.delete_message(chat_id=user_id, message_id=prompt_id)
        except Exception:
            pass

    try:
        await bot.delete_message(chat_id=user_id, message_id=message.message_id)
    except Exception:
        pass

    if not file_path:
        await bot.send_message(chat_id=user_id, text="❌ *Error:* Invalid cookie profile selected.", reply_markup=back_markup)
        return

    doc = message.document
    file_name = (doc.file_name or "").lower()
    mime = (doc.mime_type or "").lower()
    if not (file_name.endswith(".txt") or mime.startswith("text/")):
        await bot.send_message(
            chat_id=user_id,
            text="❌ *Invalid file type.* Please send a `.txt` cookie jar file.",
            reply_markup=back_markup
        )
        return

    try:
        buffer = io.BytesIO()
        await bot.download(file=message.document.file_id, destination=buffer)
        buffer.seek(0)
        content = buffer.read().decode("utf-8", errors="replace")
    except Exception as e:
        await bot.send_message(chat_id=user_id, text=f"❌ *Failed to download file:* {e}", reply_markup=back_markup)
        return

    # Normalize Netscape header if missing
    stripped = content.strip()
    if not stripped.startswith("# Netscape"):
        content = f"# Netscape HTTP Cookie File\n{content}"

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        await bot.send_message(chat_id=user_id, text=f"✅ `{cookie_key}.txt` successfully replaced from document!", reply_markup=back_markup)
        await log_event(f"🍪 *Admin Action:* Cookie profile `{cookie_key}.txt` was replaced via document.")
    except Exception as e:
        await bot.send_message(chat_id=user_id, text=f"❌ *Failed to write cookie file:* {e}", reply_markup=back_markup)

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
    ACTIVE_PROMPTS[user_id] = callback_query.message.message_id
    
    await callback_query.message.edit_text(
        text="➕ *Add User*\nPlease enter the numeric User ID to authorize below, or press the button to cancel:",
        reply_markup=back_markup
    )
    await callback_query.answer()

@admin_router.callback_query(F.data == "admin_remove")
async def callback_admin_remove(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    USER_STATES[user_id] = "waiting_for_remove_user"
    ACTIVE_PROMPTS[user_id] = callback_query.message.message_id
    
    await callback_query.message.edit_text(
        text="➖ *Remove User*\nPlease enter the numeric User ID to revoke below, or press the button to cancel:",
        reply_markup=back_markup
    )
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
        ACTIVE_PROMPTS[user_id] = callback_query.message.message_id
        lines = [f"• `{uid}`" for uid in black_list]
        text = (
            "🚫 *Blacklisted Users List*\n\n" + "\n".join(lines) + 
            "\n\nTo unban a user from the blacklist, enter their numeric User ID below, or press the button to cancel:"
        )
        await callback_query.message.edit_text(text=text, reply_markup=back_markup)
    await callback_query.answer()

@admin_router.callback_query(F.data == "admin_toggle_doc")
async def callback_admin_toggle_doc(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    state = toggle_document_mode(user_id)
    status_str = "Enabled ✅" if state else "Disabled ❌"
    await callback_query.answer(f"Doc Mode {status_str}", show_alert=True)
    await callback_query.message.edit_reply_markup(reply_markup=get_admin_console_keyboard(user_id))

@admin_router.callback_query(F.data == "admin_setlimit")
async def callback_admin_setlimit(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id != config.SYSTEM_CREATOR_ID:
        await callback_query.answer("Unauthorized", show_alert=True)
        return

    USER_STATES[user_id] = "waiting_for_setlimit"
    current = (
        f"bale_hard_limit_mb = {shared.RUNTIME_SETTINGS['bale_hard_limit_mb']}\n"
        f"split_target_mb    = {shared.RUNTIME_SETTINGS['split_target_mb']}\n"
        f"binary_chunk_mb    = {shared.RUNTIME_SETTINGS['binary_chunk_mb']}"
    )
    await callback_query.message.edit_text(
        "Send: <key> <value_mb>\n\n"
        f"Current values:\n{current}\n\n"
        "Example: split_target_mb 1900",
        reply_markup=back_markup,
    )
    await callback_query.answer()
    
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
            from operators.uploader import upload_file_direct_to_bale
            await upload_file_direct_to_bale(
                method="sendDocument",
                chat_id=user_id,
                file_path=file_path,
                caption=f"🍪 *Cookie Jar:* `{cookie_key}.txt`"
            )
        else:
            await callback_query.answer("⚠️ File is empty or does not exist yet.", show_alert=True)

    elif action == "test":
        await callback_query.answer("Testing jar...")
        await _test_cookie_jar(user_id, cookie_key, file_path, bot)

    elif action == "replace":
        USER_STATES[user_id] = f"waiting_for_replace_{cookie_key}"
        ACTIVE_PROMPTS[user_id] = callback_query.message.message_id
        await callback_query.message.edit_text(
            text=(
                f"📝 *Replace Cookies for `{cookie_key}.txt`*\n\n"
                "Bale splits long text into multiple messages, which corrupts cookie jars.\n"
                "Please send the cookie jar as a *document file* (`.txt`). "
                "The filename does not matter — only the contents are used."
            ),
            reply_markup=back_markup
        )
        await callback_query.answer()

    elif action == "restore":
        await callback_query.answer("Restoring from backup...")
        backup_path = getattr(config, "YT_COOKIES_BACKUP", "ytcookies.backup")
        if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
            await callback_query.message.edit_text(
                text=f"⚠️ No backup found for `{cookie_key}.txt`.",
                reply_markup=get_cookie_action_keyboard(cookie_key)
            )
            return
        try:
            shutil.copy(backup_path, file_path)
            await callback_query.message.edit_text(
                text=f"✅ Restored `{cookie_key}.txt` from `{backup_path}`.",
                reply_markup=get_cookie_action_keyboard(cookie_key)
            )
            await log_event(f"🍪 *Admin Action:* `{cookie_key}.txt` restored from backup.")
        except Exception as e:
            await callback_query.message.edit_text(
                text=f"❌ Failed to restore backup: {e}",
                reply_markup=get_cookie_action_keyboard(cookie_key)
            )

    elif action == "savebackup":
        await callback_query.answer("Saving backup...")
        backup_path = getattr(config, "YT_COOKIES_BACKUP", "ytcookies.backup")
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            await callback_query.message.edit_text(
                text=f"⚠️ `{cookie_key}.txt` is empty. Nothing to backup.",
                reply_markup=get_cookie_action_keyboard(cookie_key)
            )
            return
        try:
            # Make backup writable if it was locked, then restore read-only after.
            if os.path.exists(backup_path):
                os.chmod(backup_path, 0o644)
            shutil.copy(file_path, backup_path)
            os.chmod(backup_path, 0o444)
            await callback_query.message.edit_text(
                text=f"✅ Locked `{cookie_key}.txt` as `{backup_path}` (read-only).",
                reply_markup=get_cookie_action_keyboard(cookie_key)
            )
            await log_event(f"🍪 *Admin Action:* `{cookie_key}.txt` saved as protected backup.")
        except Exception as e:
            await callback_query.message.edit_text(
                text=f"❌ Failed to save backup: {e}",
                reply_markup=get_cookie_action_keyboard(cookie_key)
            )

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


async def _test_cookie_jar(user_id: int, cookie_key: str, file_path: str, bot: Bot):
    """Run a lightweight yt-dlp extraction on a known public video and report format availability."""
    from main import log_event

    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        await bot.send_message(
            chat_id=user_id,
            text=f"⚠️ `{cookie_key}.txt` is empty or missing. Nothing to test.",
            reply_markup=back_markup,
        )
        return

    # Pick a short, age-unrestricted public video that should always have real formats.
    test_url = "https://www.youtube.com/watch?v=jSi2LDkyKmI"
    cookie_snapshot = get_cookies_for_url(test_url)
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "all",
        "cookiefile": cookie_snapshot,
        "proxy": getattr(config, "YTDLP_PROXY", None),
    }
    user_agent = getattr(config, "YTDLP_USER_AGENT", "")
    if user_agent:
        ydl_opts["user_agent"] = user_agent

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(test_url, download=False)
    except Exception as exc:
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"❌ *Cookie Test Failed for `{cookie_key}.txt`*\n\n"
                f"yt-dlp could not extract anything using this jar.\n"
                f"Error: `{exc}`\n\n"
                f"Please upload a fresh cookie jar from a browser where YouTube plays normally."
            ),
            reply_markup=back_markup,
        )
        return

    formats = info.get("formats", [])
    real_formats = [
        f for f in formats
        if f.get("format_note") != "storyboard" and f.get("ext") != "mhtml"
    ]

    if real_formats:
        samples = []
        seen = set()
        for f in real_formats:
            note = f.get("format_note") or "?"
            ext = f.get("ext") or "?"
            key = (note, ext)
            if key not in seen:
                seen.add(key)
                samples.append(f"• `{note}` ({ext})")
            if len(samples) >= 6:
                break
        summary = "\n".join(samples)
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ *Cookie Test Passed for `{cookie_key}.txt`*\n\n"
                f"YouTube returned {len(real_formats)} downloadable formats.\n"
                f"Sample formats:\n{summary}\n\n"
                f"The jar is working — try your link again."
            ),
            reply_markup=back_markup,
        )
        await log_event(f"🧪 *Admin Action:* Cookie jar `{cookie_key}.txt` passed live test ({len(real_formats)} formats).")
    else:
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"⚠️ *Cookie Test Warning for `{cookie_key}.txt`*\n\n"
                f"YouTube accepted the cookies, but only returned storyboard/preview formats.\n\n"
                f"This means the jar is *bot-flagged, expired, or from an account that cannot watch videos*.\n"
                f"Please upload a fresh `ytcookies.txt` from a browser where you can actually play YouTube videos."
            ),
            reply_markup=back_markup,
        )
        await log_event(f"⚠️ *Admin Action:* Cookie jar `{cookie_key}.txt` failed live test (storyboard-only).")
