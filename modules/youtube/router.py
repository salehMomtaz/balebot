# modules/youtube/router.py
import os
import uuid
import glob
import shutil
import asyncio
import urllib.parse
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
import config
from utils.shared import queue
from main import progress_bar_handler, log_event
from modules.youtube.scraper import clean_vtt_subtitles, search_ytdlp_flat
from operators.downloader import get_cookies_for_url
import yt_dlp

youtube_router = Router()

@youtube_router.message(Command("yt"))
async def youtube_search_handler(message: Message):
    args = message.text[3:].strip()
    if not args:
        await message.reply("⚠️ *Usage:* `/yt <query>` or `/yt <limit> <query>`")
        return
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
    args = message.text[9:].strip()
    if not args:
        await message.reply("⚠️ *Usage:* `/ytrecent <@channel_handle> [count]`")
        return
    parts = args.split()
    channel = parts[0].strip()
    limit = 5
    if len(parts) > 1 and parts[1].isdigit():
        limit = min(int(parts[1]), 15)
    status_msg = await message.reply(f"🔍 Fetching recent uploads for `{channel}`...")
    try:
        clean_channel = channel if channel.startswith("@") else f"@{channel}"
        url = f"https://www.youtube.com/{clean_channel}/videos"
        loop = asyncio.get_event_loop()
        def extract():
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'skip_download': True,
                'proxy': getattr(config, 'YTDLP_PROXY', None),
            }
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
            results.append(f"{idx}. *{title}*\n   🔗 [Watch Video](https://youtu.be/{video_id})")
        await status_msg.edit_text(f"🎬 *Recent Uploads: {clean_channel}*\n\n" + "\n\n".join(results))
    except Exception as e:
        await status_msg.edit_text(f"❌ *Failed to fetch uploads:* {e}")

@youtube_router.message(Command("ytch"))
async def youtube_channel_search_handler(message: Message):
    args = message.text[5:].strip()
    if not args:
        await message.reply("⚠️ *Usage:* `/ytch <@channel_handle> <query>`")
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
        search_query = f"{clean_channel} {query}"
        entries = await search_ytdlp_flat(search_query, 5)
        if not entries:
            await status_msg.edit_text("ℹ️ No matching videos found inside this channel.")
            return
        results = []
        for idx, entry in enumerate(entries, 1):
            title = entry.get('title', 'Unknown Title')
            video_id = entry.get('id')
            results.append(f"{idx}. *{title}*\n   🔗 [Watch Video](https://youtu.be/{video_id})")
        await status_msg.edit_text(f"🎬 *Results inside {clean_channel} matching `{query}`:*\n\n" + "\n\n".join(results))
    except Exception as e:
        await status_msg.edit_text(f"❌ *Search inside channel failed:* {e}")

@youtube_router.message(Command("transcript"))
async def youtube_transcript_handler(message: Message, bot: Bot):
    url = message.text[11:].strip()
    if not url:
        await message.reply("⚠️ *Usage:* `/transcript <youtube_video_url>`")
        return
    status_msg = await message.reply("📥 Received. Enqueueing transcript job...")
    user_id = message.from_user.id
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
                'writeautomaticsub': True,
                'writesubtitles': True,
                'subtitleslangs': ['en', 'fa', 'auto'],
                'outtmpl': f"{task_dir}/subtitle",
                'cookiefile': get_cookies_for_url(url),
                'proxy': getattr(config, 'YTDLP_PROXY', None),
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)
        try:
            info = await loop.run_in_executor(None, extract_subs)
            title = info.get('title', 'Unknown Title')
            vtt_pattern = os.path.join(task_dir, "subtitle*.*.vtt")
            found_vtts = glob.glob(vtt_pattern)
            if not found_vtts:
                raise FileNotFoundError("No subtitle streams could be extracted for this video.")
            vtt_path = found_vtts[0]
            await status_msg.edit_text("🧹 Processing and cleaning transcript formatting...")
            clean_text = await loop.run_in_executor(None, clean_vtt_subtitles, vtt_path)
            sanitized_title = "".join([c if c.isalnum() or c in " ._-" else "_" for c in title])
            out_txt_path = f"{task_dir}/{sanitized_title}_Transcript.txt"
            with open(out_txt_path, "w", encoding="utf-8") as f:
                f.write(f"📖 YouTube Video Transcript\n")
                f.write(f"📝 Title: {title}\n")
                f.write(f"🔗 URL: {url}\n")
                f.write(f"="*40 + "\n\n")
                f.write(clean_text)
            await status_msg.edit_text("📤 Delivering transcript document...")
            
            from operators.uploader import upload_file_direct_to_bale
            await upload_file_direct_to_bale(
                method="sendDocument",
                chat_id=user_id,
                file_path=out_txt_path,
                caption=f"📖 *Transcript delivered:* `{title}`"
            )
            await status_msg.delete()
            await log_event(f"📖 **Transcript Generator:** Successfully delivered transcript for `{title}`.")
        except Exception as e:
            await status_msg.edit_text(f"❌ *Transcript Extraction failed:*\n`{str(e)}`")
            await log_event(f"❌ **Transcript Generator Error:** Failed on `{url}`. Details: `{str(e)}`")
        finally:
            if os.path.exists(task_dir):
                try:
                    shutil.rmtree(task_dir)
                except Exception:
                    pass
    await queue.add_task(user_id, status_msg, transcript_job)