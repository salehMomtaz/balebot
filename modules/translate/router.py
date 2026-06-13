# modules/translate/router.py
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from modules.translate.api import google_translate_async

translate_router = Router()

@translate_router.message(Command("tr"))
async def translate_command_handler(message: Message):
    text_content = message.text.strip()
    command_args = text_content[3:].strip()
    
    if not command_args:
        await message.reply(
            text="🈯 *Google Translate Guide*\n\n"
                 "Use the command using this syntax:\n"
                 "`/tr src:dst text`\n\n"
                 "*Examples:*\n"
                 "• `/tr fa:en hello`\n"
                 "• `/tr auto:en hello` (Auto-detects source)\n\n"
                 "*Multi-line format:*\n"
                 "`/tr fa:en`\n"
                 "`your text here`"
        )
        return

    try:
        parts = command_args.split(None, 1)
        lang_pair = parts[0].strip()
        if ":" not in lang_pair:
            await message.reply("⚠️ *Error:* Language pair must use the format `src:dst` (e.g., `fa:en`).")
            return
            
        src_lang, dst_lang = lang_pair.split(":", 1)
        src_lang = src_lang.strip().lower()
        dst_lang = dst_lang.strip().lower()
        
        if len(parts) < 2:
            await message.reply("⚠️ *Error:* Please write the text you want to translate after the language codes.")
            return
            
        target_text = parts[1].strip()
        translated_text = await google_translate_async(target_text, src_lang, dst_lang)
        await message.reply(
            text=f"🈯 *Translation ({src_lang} ➡️ {dst_lang})*\n\n"
                 f"```\n{translated_text}\n```"
        )
    except Exception as e:
        await message.reply(f"❌ *Translation Failed:*\n`{str(e)}`")