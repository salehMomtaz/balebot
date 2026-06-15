# modules/direct_dl/router.py
import os
import uuid
import shutil
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
import config
from main import log_event
from modules.direct_dl.api import fetch_markdown_text

direct_dl_router = Router()

@direct_dl_router.message(Command("web"))
async def webpage_extractor_handler(message: Message, bot: Bot):
    url = message.text[5:].strip()
    if not url:
        await message.reply("⚠️ *Usage:* `/web <url>`")
        return
    status_msg = await message.reply("🔍 Fetching webpage and converting to Markdown...")
    user_id = message.from_user.id
    try:
        title, markdown_text = await fetch_markdown_text(url)
        if not markdown_text.strip():
            await status_msg.edit_text("ℹ️ No readable markdown content could be extracted from this webpage.")
            return
            
        sanitized_title = "".join([c if c.isalnum() or c in " ._-" else "_" for c in title])
        
        # Safe boundary check: if text exceeds 3,500 characters, upload as document
        if len(markdown_text) > 3500:
            os.makedirs("cache", exist_ok=True)
            cache_id = str(uuid.uuid4())[:8]
            temp_path = f"cache/{cache_id}_{sanitized_title}.txt"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(f"🌐 Webpage Markdown Extraction\n")
                f.write(f"🔗 Source: {url}\n")
                f.write(f"="*40 + "\n\n")
                f.write(markdown_text)
                
            from operators.uploader import upload_file_direct_to_bale
            await upload_file_direct_to_bale(
                method="sendDocument",
                chat_id=user_id,
                file_path=temp_path,
                caption=f"📄 *Article delivered:* `{title}`"
            )
            if os.path.exists(temp_path):
                os.remove(temp_path)
            await status_msg.delete()
            await log_event(f"📄 **Webpage Extractor:** Delivered markdown file for `{title}`.")
        else:
            await status_msg.edit_text(
                text=f"🌐 *Webpage Text:* `{title}`\n\n"
                     f"```\n{markdown_text}\n```"
            )
            await log_event(f"📄 **Webpage Extractor:** Displayed text for `{title}`.")
    except Exception as e:
        await status_msg.edit_text(text=f"❌ *Failed to extract text:*\n`{str(e)}`")
        await log_event(f"❌ **Webpage Extractor Error:** Failed on `{url}`. Details: `{str(e)}`")