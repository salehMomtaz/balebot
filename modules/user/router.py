# modules/user/router.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import config
from modules.user.keyboards import get_guide_menu_keyboard, get_help_submenu_keyboard

user_router = Router()

# Helper to detect plain web links so downloader_router can handle them
def is_link(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")

# We strictly isolate this router from matching the System Creator
@user_router.message(F.text, F.chat.type == "private", lambda message: message.from_user.id != config.SYSTEM_CREATOR_ID)
async def user_start_text_handler(message: Message):
    text = message.text.strip()

    # Let link downloads propagate downstream to downloader_router
    if is_link(text):
        return

    await message.reply(
        text="👋 *Hello! Welcome to your Private Downloader Bot.*\n\n"
             "To get started, browse my features or use the complete help guide using the button below:",
        reply_markup=get_guide_menu_keyboard()
    )

@user_router.callback_query(F.data == "user_help_guide")
async def user_help_guide_handler(callback_query: CallbackQuery):
    keyboard = get_help_submenu_keyboard()
    await callback_query.message.edit_text(
        text="📘 *Complete Bot Help Guide*\nSelect a category from the buttons below to view complete commands, instructions, and examples:",
        reply_markup=keyboard
    )
    await callback_query.answer()

@user_router.callback_query(F.data == "user_close_menu")
async def user_close_menu_handler(callback_query: CallbackQuery):
    await callback_query.message.delete()
    await callback_query.answer("Guide closed.")

@user_router.callback_query(F.data.startswith("user_help_select:"))
async def user_help_select_handler(callback_query: CallbackQuery):
    category = callback_query.data.split(":")[1]
    back_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Back to Guides", callback_data="user_help_guide")]])
    
    if category == "github":
        text = (
            "🐙 *GitHub Helper Guide*\n\n"
            "1. Send any repository link to open its Control Panel:\n"
            "   `https://github.com/owner/repo`\n\n"
            "2. Search repositories by stars:\n"
            "   `/search django`\n"
            "3. List last updated repos of a user:\n"
            "   `/user torvalds`\n"
            "4. Check weekly trending repos:\n"
            "   `/trend`\n"
            "5. Process Issue, Pull Request, or Discussion links:\n"
            "   `https://github.com/owner/repo/issues/123`\n"
            "6. Download Gist files directly:\n"
            "   `https://gist.github.com/owner/abcdef123...`"
        )
    elif category == "translate":
        text = (
            "🈯 *Google Translate Guide*\n\n"
            "Translate any text asynchronously on-the-fly.\n"
            "Format: `/tr src:dst text` (e.g. `/tr fa:en hello`)\n\n"
            "Use `auto` to let Google detect the source language:\n"
            "• `/tr auto:en سلام`"
        )
    elif category == "youtube":
        text = (
            "🎬 *YouTube Helper Guide*\n\n"
            "1. Search top video results:\n"
            "   `/yt python tutorial` (outputs titles, creators, duration, and direct links)\n"
            "2. Query specific channel uploads:\n"
            "   `/ytrecent @freecodecamp 5` (gets last 5 uploaded videos)\n"
            "3. Search inside a channel:\n"
            "   `/ytch @freecodecamp django` (searches django inside freecodecamp uploads)\n"
            "4. Extract raw, cleaned text transcripts:\n"
            "   `/transcript https://youtube.com/watch?v=...` (downloads subtitles, strips VTT garbage, and delivers as a lightweight .txt file)"
        )
    elif category == "direct":
        text = (
            "🌐 *Direct Link Downloader & Web Extractor*\n\n"
            "1. Upload direct file URLs:\n"
            "   `https://example.com/file.zip` (The bot downloads and splits into 48MB parts if it exceeds limit)\n"
            "2. Custom naming: Append a pipeline with custom filename:\n"
            "   `https://example.com/file.zip | my_cool_file.zip`\n"
            "3. Extract webpage markdown text:\n"
            "   `/web https://en.wikipedia.org/wiki/Python` (utilizes urltomarkdown.com to retrieve cleaned article plain text or delivers as file)"
        )
    else:
        text = "Help category details are currently under construction."
        
    await callback_query.message.edit_text(text=text, reply_markup=back_markup)
    await callback_query.answer()