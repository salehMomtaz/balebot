# modules/downloader_handler.py
import os
import uuid
import shutil
import asyncio
import urllib.parse
import aiohttp
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import config
from utils.shared import queue, DOWNLOAD_CACHE
from main import progress_bar_handler, log_event
from utils.gate import is_authorized
from utils.downloader import extract_formats, download_media
from utils.uploader import process_split_and_upload

# Initialize the independent modular downloader router
downloader_router = Router()

def is_link(text: str) -> bool:
    """Helper to detect if incoming text is a web link."""
    return text.startswith("http://") or text.startswith("https://")

def is_social_media_link(url: str) -> bool:
    """Check if the target link belongs to supported media crawlers."""
    url_lower = url.lower()
    social_domains = ["youtube.com", "youtu.be", "instagram.com", "tiktok.com", "twitter.com", "x.com"]
    return any(domain in url_lower for domain in social_domains)

# =========================================================================
# Group 1 Handlers: Link Downloader (Mutual-exclusive filters in aiogram v3)
# =========================================================================
@downloader_router.message(
    F.text,
    F.chat.type == "private",
    lambda message: is_link(message.text.strip().split("|")[0].strip())
)
async def text_link_handler(message: Message):
    text = message.text.strip()
    user_id = message.from_user.id
    
    parts = text.split("|", 1)
    url = parts[0].strip()
    custom_filename = parts[1].strip() if len(parts) > 1 else None
    
    if not is_authorized(user_id):
        return

    if is_social_media_link(url):
        status_msg = await message.reply(text="📥 Received. Analyzing link formats...")
        
        async def download_job():
            await status_msg.edit_text(text="🔍 Fetching format attributes...")
            try:
                data = extract_formats(url)
                
                cache_id = str(uuid.uuid4())[:8]
                DOWNLOAD_CACHE[cache_id] = {
                    "url": url,
                    "title": data["title"],
                    "videos": data["videos"],
                    "audios": data["audios"],
                    "thumbnail_url": data["thumbnail"],
                    "custom_filename": custom_filename
                }
                
                videos = data["videos"]
                audios = data["audios"]
                max_rows = max(len(videos), len(audios))
                
                keyboard_rows = []
                for i in range(max_rows):
                    row = []
                    if i < len(videos):
                        v = videos[i]
                        row.append(InlineKeyboardButton(
                            text=f"🎥 {v['quality']} ({v['size_str']})",
                            callback_data=f"dl:{cache_id}:v:{v['format_id']}"
                        ))
                    else:
                        row.append(InlineKeyboardButton(text="—", callback_data="none"))
                    
                    if i < len(audios):
                        a = audios[i]
                        row.append(InlineKeyboardButton(
                            text=f"🎵 {a['quality']} ({a['size_str']})",
                            callback_data=f"dl:{cache_id}:a:{a['format_id']}"
                        ))
                    else:
                        row.append(InlineKeyboardButton(text="—", callback_data="none"))
                    keyboard_rows.append(row)
                    
                keyboard_rows.append([InlineKeyboardButton(text="❌ Cancel", callback_data=f"dl:{cache_id}:cancel")])
                
                await log_event(f"ℹ️ *Link analyzed:* `{data['title']}` for User `{user_id}`.")
                await status_msg.delete()
                await message.reply(
                    text=f"📥 *Format Selection*\n\n📝 *Title:* {data['title']}\n"
                         f"⏱ *Duration:* {int(data['duration'] // 60)}m {int(data['duration'] % 60)}s\n\n"
                         f"Select an option below:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
                )
            except Exception as e:
                await status_msg.edit_text(text=f"❌ Extraction failed.\nError: `{str(e)}`")
                await log_event(f"❌ *Extraction Error:* Failed to parse `{url}`. Details: `{str(e)}`")

        await queue.add_task(user_id, status_msg, download_job)
    else:
        # Generic direct URL uploader
        status_msg = await message.reply(text="📥 Received URL. Queueing job...")
        
        async def direct_upload_job():
            await status_msg.edit_text(text="⚡ Starting direct URL download...")
            cache_id = str(uuid.uuid4())[:8]
            task_dir = f"cache/{cache_id}"
            try:
                async def dl_progress(cur, tot):
                    await progress_bar_handler(cur, tot, status_msg, "Downloading direct file to server...")
                    
                file_path = await download_direct_file(url, cache_id, dl_progress)
                
                dir_name = os.path.dirname(file_path)
                clean_name = custom_filename if custom_filename else os.path.basename(file_path)
                clean_file_path = os.path.join(dir_name, clean_name)
                if clean_file_path != file_path:
                    os.rename(file_path, clean_file_path)
                
                await status_msg.edit_text(text="📤 Uploading direct file to Bale...")
                
                await process_split_and_upload(
                    bot=message.bot,
                    chat_id=message.chat.id,
                    file_path=clean_file_path,
                    action='d',
                    title=clean_name,
                    uploader="Direct Link",
                    duration=0,
                    thumb_path=None,
                    progress_msg=status_msg
                )
                await log_event(f"✅ *Direct Upload:* Finished for User `{user_id}` from source `{url}`.")
            except Exception as e:
                await status_msg.edit_text(text=f"❌ Failed to process direct file URL.\nError: `{str(e)}`")
                await log_event(f"❌ *Direct Upload Error:* Failed on `{url}`. Details: `{str(e)}`")
            finally:
                if os.path.exists(task_dir):
                    try:
                        shutil.rmtree(task_dir)
                        print(f"[Cleanup] Cleared direct download directory: {task_dir}")
                    except Exception as ce:
                        print(f"[Cleanup] Error: {ce}")

        await queue.add_task(user_id, status_msg, direct_upload_job)

# Callback Query Handler
@downloader_router.callback_query(F.data.startswith("dl:"))
async def dl_callback_handler(callback_query: CallbackQuery, bot: Bot):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    parts = data.split(":")
    if len(parts) < 3:
        return
        
    cache_id = parts[1]
    action = parts[2]
    
    if action == "cancel":
        DOWNLOAD_CACHE.pop(cache_id, None)
        await callback_query.message.delete()
        await callback_query.answer("Cancelled.")
        return
        
    format_id = parts[3]
    cache_data = DOWNLOAD_CACHE.get(cache_id)
    if not cache_data:
        await callback_query.answer("⚠️ Session expired or not found.", show_alert=True)
        return
        
    target_list = cache_data["videos"] if action == 'v' else cache_data["audios"]
    target_fmt = next((f for f in target_list if f["format_id"] == format_id), None)
    
    if target_fmt and target_fmt["bytes"] > (50 * 1024 * 1024):
        # Enforce Bale's strict 50MB upload limits for format selections
        await callback_query.answer("❌ This format exceeds Bale's 50MB upload limits. Please select another quality.", show_alert=True)
        return
        
    await callback_query.message.edit_text(text="⏳ Request enqueued in Active Job Queue...")
    await callback_query.answer("Transfer enqueued...")
    
    task_dir = f"cache/{cache_id}"
    
    async def queued_transfer_job():
        await callback_query.message.edit_text(text="⚡️ Downloading file from server to VPS...")
        loop = asyncio.get_event_loop()
        try:
            from utils.downloader import download_media
            
            async def download_progress(curr, tot):
                await progress_bar_handler(curr, tot, callback_query.message, "Downloading from server to VPS...")
                
            def thread_progress(curr, tot):
                asyncio.run_coroutine_threadsafe(download_progress(curr, tot), loop)
            
            result = await loop.run_in_executor(
                None, download_media, cache_data["url"], format_id, action, cache_id, thread_progress
            )
            
            file_path = result['file_path']
            thumb_path = result['thumb_path']
            title = result['title']
            uploader = result['uploader']
            
            dir_name = os.path.dirname(file_path)
            ext = os.path.splitext(file_path)[1]
            
            custom_name = cache_data.get("custom_filename")
            if custom_name:
                clean_name = custom_name if custom_name.endswith(ext) else f"{custom_name}{ext}"
            else:
                clean_name = os.path.basename(file_path)
                
            clean_file_path = os.path.join(dir_name, clean_name)
            if clean_file_path != file_path:
                os.rename(file_path, clean_file_path)
            
            await process_split_and_upload(
                bot=bot,
                chat_id=callback_query.message.chat.id,
                file_path=clean_file_path,
                action=action,
                title=clean_name,
                uploader=uploader,
                duration=result['duration'],
                thumb_path=thumb_path,
                progress_msg=callback_query.message
            )
            
            DOWNLOAD_CACHE.pop(cache_id, None)
            await log_event(f"✅ *Job Successful:* `{clean_name}` was successfully processed and sent.")
            
        except Exception as e:
            await callback_query.message.edit_text(text=f"❌ Download/Upload failure.\nError: `{str(e)}`")
            await log_event(f"❌ *Job Failure:* Extraction/Upload crashed on `{cache_data['url']}`. Details: `{str(e)}`")
        finally:
            if os.path.exists(task_dir):
                try:
                    shutil.rmtree(task_dir)
                    print(f"[Cleanup] Cleaned active task directory: {task_dir}")
                except Exception as ce:
                    print(f"[Cleanup] Error: {ce}")

    await queue.add_task(user_id, callback_query.message, queued_transfer_job)

async def download_direct_file(url: str, cache_id: str, progress_fn) -> str:
    """Download direct file URL stream to secure subfolder."""
    task_dir = f"cache/{cache_id}"
    os.makedirs(task_dir, exist_ok=True)
    
    parsed_url = urllib.parse.urlparse(url)
    file_name = os.path.basename(parsed_url.path) or f"download_{cache_id}"
    file_name = urllib.parse.unquote(file_name)
    out_path = f"{task_dir}/{file_name}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=1800) as response:
            if response.status != 200:
                raise RuntimeError(f"Server returned error {response.status}")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(out_path, "wb") as f:
                async for chunk in response.content.iter_chunked(512 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_fn:
                        await progress_fn(downloaded, total_size)
                        
    return out_path