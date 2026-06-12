# modules/direct_dl.py
import os
import uuid
import urllib.parse
from html.parser import HTMLParser
import aiohttp
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
import config
from main import log_event

# Initialize the modular direct downloader router
direct_dl_router = Router()

class WebpageTextExtractor(HTMLParser):
    """
    Custom HTML Parser:
    Strips away tracking scripts, styles, navigations, and footers natively.
    Reclaims pure readable body text from any webpage without external packages.
    """
    def __init__(self):
        super().__init__()
        self.text_accumulator = []
        self.is_ignored_tag = False
        self.ignored_tags = {"script", "style", "nav", "footer", "header", "noscript", "aside"}

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored_tags:
            self.is_ignored_tag = True

    def handle_endtag(self, tag):
        if tag in self.ignored_tags:
            self.is_ignored_tag = False

    def handle_data(self, data):
        if not self.is_ignored_tag:
            clean_data = data.strip()
            if clean_data:
                self.text_accumulator.append(clean_data)

    def get_clean_text(self) -> str:
        return "\n\n".join(self.text_accumulator)

async def extract_webpage_text(url: str) -> str:
    """Fetch webpage HTML asynchronously and parse its readable text."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"Web server returned HTTP Error: {response.status}")
            
            html_content = await response.text()
            
            # Parse HTML natively
            parser = WebpageTextExtractor()
            parser.feed(html_content)
            return parser.get_clean_text()

@direct_dl_router.message(Command("web"))
async def webpage_extractor_handler(message: Message, bot: Bot):
    """
    Handler for /web command: /web <url>
    Extracts webpage text, formatting it as a standard message or sending as a .txt file.
    """
    url = message.text[5:].strip()
    if not url:
        await message.reply("⚠️ *Usage:* `/web <url>` (e.g. `/web https://en.wikipedia.org/wiki/Python`)")
        return
        
    status_msg = await message.reply("🔍 Fetching webpage and extracting text...")
    user_id = message.from_user.id
    
    try:
        # Perform async webpage text extraction
        extracted_text = await extract_webpage_text(url)
        
        if not extracted_text.strip():
            await status_msg.edit_text("ℹ️ No readable text content could be extracted from this webpage.")
            return
            
        # Extract webpage title or domain to name the output
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc.replace("www.", "")
        
        # Safe boundary check: if text is too long, deliver as an attachment
        if len(extracted_text) > 3500:
            os.makedirs("cache", exist_ok=True)
            cache_id = str(uuid.uuid4())[:8]
            temp_path = f"cache/{cache_id}_{domain}_Article.txt"
            
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(f"🌐 Webpage Text Extraction\n")
                f.write(f"🔗 Source: {url}\n")
                f.write(f"="*40 + "\n\n")
                f.write(extracted_text)
                
            await bot.send_document(
                chat_id=user_id,
                document=FSInputFile(temp_path),
                caption=f"📄 *Article delivered:* `{domain}`"
            )
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            await status_msg.delete()
            await log_event(f"📄 **Webpage Extractor:** Successfully delivered text file for `{url}`.")
        else:
            await status_msg.edit_text(
                text=f"🌐 *Webpage Text:* `{domain}`\n\n"
                     f"```\n{extracted_text}\n```"
            )
            await log_event(f"📄 **Webpage Extractor:** Successfully displayed text for `{url}`.")
            
    except Exception as e:
        await status_msg.edit_text(text=f"❌ *Failed to extract text:*\n`{str(e)}`")
        await log_event(f"❌ **Webpage Extractor Error:** Failed on `{url}`. Details: `{str(e)}`")