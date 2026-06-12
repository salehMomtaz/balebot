# modules/youtube.py
import os
import re
import uuid
import glob
import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
import yt_dlp
import config
from utils.shared import queue
from main import progress_bar_handler, log_event

# Initialize the modular YouTube router
youtube_router = Router()

def clean_vtt_subtitles(vtt_path: str) -> str:
    """Strips WebVTT formatting, timestamps, and sequential duplicates to return clean plain text."""
    if not os.path.exists(vtt_path):
        return "No subtitles found."
        
    with open(vtt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    clean_lines = []
    seen = set()
    
    for line in lines:
        line_strip = line.strip()
        # Skip VTT metadata and timestamp blocks
        if (not line_strip or 
            line_strip.startswith("WEBVTT") or 
            line_strip.startswith("Kind:") or 
            line_strip.startswith("Language:") or 
            "-->" in line_strip or 
            line_strip.isdigit()):
            continue
            
        # Strip HTML-style tags (like <c> or <font>)
        line_clean = re.sub(r"<[^>]+>", "", line_strip)
        
        # Prevent spamming identical duplicated lines (standard in auto-generated captions)
        if line_clean not in seen:
            clean_lines.append(line_clean)
            seen.add(line_clean)
            
    return "\n".join(clean_lines)

async def search_ytdlp_flat(query: str, max_results: int) -> list:
    """Performs flat-playlist extraction using yt-dlp to retrieve search results asynchronously."""
    loop = asyncio.get_event_loop()
    
    def extract():
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,  # Fast: only parses metadata, does not download pages
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            
    info = await loop.run_in_executor(None, extract)
    return info.get('entries', [])

# =========================================================================
# Commands Implementation
# =========================================================================

@youtube_router.message(Command("yt"))
async def youtube_search_handler(message: Message):
    """
    Search YouTube videos.
    Supports formats:
      - /yt python tutorial (default 5 results)
      - /yt 10 python tutorial (limit to 10 results)
    """
    args = message.text[3:].strip()
    if not args:
        await message.reply("⚠️ *Usage:* `/yt <query>` or `/yt <limit_number> <query>` (e.g. `/yt 5 django`)")
        return
        
    # Check if first argument is a result limit (between 1 and 15)
    parts = args.split(None, 1)
    limit = 5
    query = args
    
    if parts[0].isdigit():
        num = int(parts[0])
        if 1 <= num <= 15:
            limit = num
            query = parts[1].strip() if len(parts) > 1 else ""
            
    if not query:
        await message.reply("⚠️ *Error:* Please provide a search query.")
        return
        
    status_msg = await message.reply("🔍 Searching YouTube...")
    try:
        entries = await search_ytdlp_flat(query, limit)
        if not entries:
            await status_msg.edit_text("ℹ️ No videos found matching your query.")
            return
            
        results = []
        for idx, entry in enumerate(entries, 1):
            title = entry.get('title', 'Unknown Title')
            video_id = entry.get('id')
            uploader = entry.get('uploader', 'Unknown Channel')
            duration_raw = entry.get('duration')
            
            # Format duration nicely
            duration = f"{int(duration_raw // 60)}m {int(duration_raw % 60)}s" if duration_raw else "??"
            
            results.append(
                f"{idx}. *{title}*\n"
                f"   👤 Creator: `{uploader}` | ⏱ Duration: `{duration}`\n"
                f"   🔗 [Watch Video](https://youtu.be/{video_id})"
            )
            
        await status_msg.edit_text("🎬 *YouTube Top Results:*\n\n" + "\n\n".join(results))
    except Exception as e:
        await status_msg.edit_text(f"❌ *Search Failed:* {e}")

@youtube_router.message(Command("ytrecent"))
async def youtube_recent_handler(message: Message):
    """Lists the last X videos of a channel: /ytrecent @freecodecamp 10"""
    args = message.text[9:].strip()
    if not args:
        await message.reply("⚠️ *Usage:* `/ytrecent <@channel_handle> [count]` (e.g. `/ytrecent @freecodecamp 5`)")
        return
        
    parts = args.split()
    channel = parts[0].strip()
    limit = 5
    if len(parts) > 1 and parts[1].isdigit():
        limit = min(int(parts[1]), 15)
        
    status_msg = await message.reply(f"🔍 Fetching recent uploads for `{channel}`...")
    try:
        # standardizing @ prefix
        clean_channel = channel if channel.startswith("@") else f"@{channel}"
        url = f"https://www.youtube.com/{clean_channel}/videos"
        
        loop = asyncio.get_event_loop()
        def extract():
            ydl_opts = {'quiet': True, 'extract_flat': True, 'skip_download': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
                
        info = await loop.run_in_executor(None, extract)
        entries = info.get('entries', [])[:limit]
        
        if not entries:
            await status_msg.edit_text("ℹ️ No recent uploads found for this channel.")
            return
            
        results = []
        for idx, entry in enumerate(entries, 1):
            title = entry.get('title', 'Unknown Title')
            video_id = entry.get('id')
            results.append(
                f"{idx}. *{title}*\n"
                f"   🔗 [Watch Video](https://youtu.be/{video_id})"
            )
        await status_msg.edit_text(f"🎬 *Recent Uploads: {clean_channel}*\n\n" + "\n\n".join(results))
    except Exception as e:
        await status_msg.edit_text(f"❌ *Failed to fetch uploads:* {e}")

@youtube_router.message(Command("ytch"))
async def youtube_channel_search_handler(message: Message):
    """Searches videos inside a specific channel: /ytch @freecodecamp django"""
    args = message.text[5:].strip()
    if not args:
        await message.reply("⚠️ *Usage:* `/ytch <@channel_handle> <query>` (e.g. `/ytch @freecodecamp django`)")
        return
        
    parts = args.split(None, 1)
    channel = parts[0].strip()
    query = parts[1].strip() if len(parts) > 1 else ""
    
    if not query:
        await message.reply("⚠️ *Error:* Please specify a search keyword.")
        return
        
    status_msg = await message.reply(f"🔍 Searching `{query}` inside channel `{channel}`...")
    try:
        clean_channel = channel if channel.startswith("@") else f"@{channel}"
        # Combine creator name + query for optimized search accuracy
        search_query = f"{clean_channel} {query}"
        
        entries = await search_ytdlp_flat(search_query, 5)
        if not entries:
            await status_msg.edit_text("ℹ️ No matching videos found inside this channel.")
            return
            
        results = []
        for idx, entry in enumerate(entries, 1):
            title = entry.get('title', 'Unknown Title')
            video_id = entry.get('id')
            results.append(
                f"{idx}. *{title}*\n"
                f"   🔗 [Watch Video](https://youtu.be/{video_id})"
            )
        await status_msg.edit_text(f"🎬 *Results inside {clean_channel} matching `{query}`:*\n\n" + "\n\n".join(results))
    except Exception as e:
        await status_msg.edit_text(f"❌ *Search inside channel failed:* {e}")

@youtube_router.message(Command("transcript"))
async def youtube_transcript_handler(message: Message, bot: Bot):
    """Downloads auto-generated or manual subtitles, cleans them, and sends them as a raw .txt file."""
    url = message.text[11:].strip()
    if not url:
        await message.reply("⚠️ *Usage:* `/transcript <youtube_video_url>`")
        return
        
    status_msg = await message.reply("📥 Received. Enqueueing transcript job...")
    user_id = message.from_user.id
    
    # Define independent queue job
    async def transcript_job():
        await status_msg.edit_text("⚡ Requesting subtitle extraction from YouTube...")
        cache_id = str(uuid.uuid4())[:8]
        task_dir = f"cache/{cache_id}"
        os.makedirs(task_dir, exist_ok=True)
        
        loop = asyncio.get_event_loop()
        
        def extract_subs():
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'writeautomaticsub': True,  # Download auto-generated subtitles
                'writesubtitles': True,       # Download manual subtitles
                'subtitleslangs': ['en', 'fa', 'auto'], # Prefer English, Persian, or standard fallback
                'outtmpl': f"{task_dir}/subtitle",
                'cookiefile': config.YT_COOKIES if os.path.exists(config.YT_COOKIES) else None
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)
                
        try:
            info = await loop.run_in_executor(None, extract_subs)
            title = info.get('title', 'Unknown Title')
            
            # Subtitle files are saved with extensions like .en.vtt, .fa.vtt, or .en.vtt.part
            # Locate any saved VTT files inside the task folder
            vtt_pattern = os.path.join(task_dir, "subtitle*.*.vtt")
            found_vtts = glob.glob(vtt_pattern)
            
            if not found_vtts:
                raise FileNotFoundError("No subtitle streams could be extracted for this video.")
                
            vtt_path = found_vtts[0]
            
            await status_msg.edit_text("🧹 Processing and cleaning transcript formatting...")
            
            # Clean VTT annotations thread-safely
            clean_text = await loop.run_in_executor(None, clean_vtt_subtitles, vtt_path)
            
            # Write final plain text to local cache
            sanitized_title = "".join([c if c.isalnum() or c in " ._-" else "_" for c in title])
            out_txt_path = f"{task_dir}/{sanitized_title}_Transcript.txt"
            with open(out_txt_path, "w", encoding="utf-8") as f:
                f.write(f"📖 YouTube Video Transcript\n")
                f.write(f"📝 Title: {title}\n")
                f.write(f"🔗 URL: {url}\n")
                f.write(f"="*40 + "\n\n")
                f.write(clean_text)
                
            await status_msg.edit_text("📤 Delivering transcript document...")
            
            # Send the clean transcript as a raw text file
            await bot.send_document(
                chat_id=user_id,
                document=FSInputFile(out_txt_path),
                caption=f"📖 *Transcript delivered:* `{title}`"
            )
            
            await status_msg.delete()
            await log_event(f"📖 **Transcript Generator:** Successfully delivered transcript for `{title}`.")
            
        except Exception as e:
            await status_msg.edit_text(f"❌ *Transcript Extraction failed:*\n`{str(e)}`")
            await log_event(f"❌ **Transcript Generator Error:** Failed on `{url}`. Details: `{str(e)}`")
        finally:
            # Reclaim VPS cache space immediately
            if os.path.exists(task_dir):
                try:
                    shutil.rmtree(task_dir)
                except Exception:
                    pass

    await queue.add_task(user_id, status_msg, transcript_job)