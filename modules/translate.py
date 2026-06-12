# modules/translate.py
import aiohttp
import urllib.parse
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

# Initialize the modular translate router
translate_router = Router()

async def google_translate_async(text: str, src_lang: str, dst_lang: str) -> str:
    """
    Direct asynchronous HTTP call to Google's translation API.
    Bypasses third-party wrapper libraries entirely using your core aiohttp client.
    """
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": src_lang,
        "tl": dst_lang,
        "dt": "t",
        "q": text
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"Google Translation API returned HTTP Error: {response.status}")
            
            result = await response.json()
            # Google returns a deeply nested list structure: [[[translation, source, ...], ...]]
            try:
                translations = [item[0] for item in result[0] if item[0]]
                return "".join(translations)
            except (IndexError, TypeError):
                raise ValueError("Failed to parse Google Translation API payload.")

@translate_router.message(Command("tr"))
async def translate_command_handler(message: Message):
    """
    Handler for the /tr translation command.
    Accepts:
      - /tr src:dst text
      - Multi-line blocks starting with /tr src:dst
    """
    text_content = message.text.strip()
    
    # Strip command prefix /tr
    command_args = text_content[3:].strip()
    
    # Help guide if no arguments are provided
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
        # Parse language block and text (e.g. "fa:en text to translate")
        parts = command_args.split(None, 1)
        lang_pair = parts[0].strip()
        
        if ":" not in lang_pair:
            await message.reply("⚠️ *Error:* Language pair must use the format `src:dst` (e.g., `fa:en`).")
            return
            
        src_lang, dst_lang = lang_pair.split(":", 1)
        src_lang = src_lang.strip().lower()
        dst_lang = dst_lang.strip().lower()
        
        # Check if the user put a space after /tr src:dst but wrote no text
        if len(parts) < 2:
            await message.reply("⚠️ *Error:* Please write the text you want to translate after the language codes.")
            return
            
        target_text = parts[1].strip()
        
        # Execute async request
        translated_text = await google_translate_async(target_text, src_lang, dst_lang)
        
        # Format the output beautifully
        await message.reply(
            text=f"🈯 *Translation ({src_lang} ➡️ {dst_lang})*\n\n"
                 f"```\n{translated_text}\n```"
        )
        
    except Exception as e:
        await message.reply(f"❌ *Translation Failed:*\n`{str(e)}`")