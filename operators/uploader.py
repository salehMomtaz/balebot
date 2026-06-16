# operators/uploader.py
import os
import re
import asyncio
import aiohttp
from aiogram import Bot
from utils.gate import is_document_mode
import config
from utils import shared

def sanitize_filename_for_bale(filename: str) -> str:
    """
    Sanitizes and truncates a filename to prevent HTTP headers or multipart form errors on Bale.
    Replaces colons, quotes, and unsafe characters with underscores, and limits length.
    """
    base, ext = os.path.splitext(filename)
    # Replace unsafe characters and spaces with underscores
    clean_base = re.sub(r'[\\/:*?"<>|\[\]()\'\s]+', '_', base)
    # Ensure it's not excessively long (e.g. max 40 chars for base)
    if len(clean_base) > 40:
        clean_base = clean_base[:40].strip("_")
    # Clean up multiple underscores
    clean_base = re.sub(r'_+', '_', clean_base).strip("_")
    if not clean_base:
        clean_base = "file"
    return f"{clean_base}{ext}"

def clean_caption_text(text: str, max_len: int = 150) -> str:
    """
    Cleans and truncates a media title to guarantee safe, error-free caption delivery on Bale.
    Removes Markdown syntax characters to prevent parser loop/crash rejections.
    """
    if not text:
        return "Media File"
    # Remove characters that trigger Markdown formatting or link parsing
    cleaned = text.replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "").replace("(", "").replace(")", "")
    # Trim multiple spaces
    cleaned = " ".join(cleaned.split())
    # Limit length
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].strip() + "..."
    return cleaned

async def upload_file_direct_to_bale(method: str, chat_id: int, file_path: str, caption: str = "", extra_params: dict = None) -> dict:
    """
    Directly uploads a file to Bale's API using standard multipart/form-data POST.
    Bypasses framework-specific serialization limitations completely to guarantee successful delivery.
    """
    url = f"https://tapi.bale.ai/bot{config.BALE_TOKEN}/{method}"
    
    # Map the multipart form field name to the target Bale API method
    field_name = "document"
    if method == "sendVideo":
        field_name = "video"
    elif method == "sendAudio":
        field_name = "audio"
        
    safe_filename = sanitize_filename_for_bale(os.path.basename(file_path))
    
    async with aiohttp.ClientSession() as session:
        with open(file_path, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            if caption:
                form.add_field("caption", caption)
                
            if extra_params:
                for k, v in extra_params.items():
                    if v is not None:
                        form.add_field(k, str(v))
                        
            form.add_field(field_name, f, filename=safe_filename)
            
            async with session.post(url, data=form, timeout=1800) as response:
                res_json = await response.json()
                if not res_json.get("ok"):
                    raise RuntimeError(f"Bale API Error: {res_json.get('description', 'Unknown')}")
                return res_json

async def send_single_media(bot: Bot, chat_id: int, file_path: str, action: str, title: str, uploader: str, duration: int, thumb_path: str, progress_fn, force_document=False):
    """Sends a single media file to Bale using direct standard multipart uploads."""
    safe_title = clean_caption_text(title)
    
    if force_document or action == 'd':
        return await upload_file_direct_to_bale(
            method="sendDocument",
            chat_id=chat_id,
            file_path=file_path,
            caption=f"📁 **Part:** `{os.path.basename(file_path)}`"
        )
        
    if action == 'a':
        return await upload_file_direct_to_bale(
            method="sendAudio",
            chat_id=chat_id,
            file_path=file_path,
            caption=f"🎵 **{safe_title}**\nUploaded via Downloader Bot",
            extra_params={
                "title": safe_title,
                "performer": clean_caption_text(uploader, 50),
                "duration": int(duration)
            }
        )
    else:  # action == 'v'
        from operators.downloader import probe_video_dimensions
        width, height, parsed_duration = probe_video_dimensions(file_path)
        final_duration = parsed_duration if parsed_duration > 0 else int(duration)
        return await upload_file_direct_to_bale(
            method="sendVideo",
            chat_id=chat_id,
            file_path=file_path,
            caption=f"🎥 **{safe_title}**\nUploaded via Downloader Bot",
            extra_params={
                "width": width,
                "height": height,
                "duration": final_duration,
                "supports_streaming": "true"
            }
        )

async def process_split_and_upload(bot: Bot, chat_id: int, file_path: str, action: str, title: str, uploader: str, duration: int, thumb_path: str, progress_msg):
    """
    On-Demand Sequential Uploader for Bale:
    Generates chunks one-by-one, uploads them, and immediately purges them from disk.
    Caps VPS disk overhead to exactly ONE chunk size. Uses 39 MB boundaries to bypass Bale's 50 MB limit comfortably.
    """
    from operators.downloader import split_file_generator, split_video_by_size_generator
    from main import progress_bar_handler
    import utils.shared as shared

    file_size = os.path.getsize(file_path)

    # Dynamic limits from runtime settings (admin-adjustable, no restart)

    rs = shared.RUNTIME_SETTINGS
    is_video = action == 'v'

    if is_video:
        target_bytes = rs["split_target_mb"] * 1024 * 1024
        hard_bytes = rs["split_hard_mb"] * 1024 * 1024
        max_chunk_size = target_bytes
    else:
        max_chunk_size = rs["binary_chunk_mb"] * 1024 * 1024

    force_document = is_document_mode(chat_id) or action == 'd'

    is_split = file_size > max_chunk_size
    parts_list = []
    
    try:
        part_num = 1
        loop = asyncio.get_event_loop()
        
        if is_video:
            generator = split_video_by_size_generator(file_path, target_bytes, hard_bytes)
        else:
            generator = split_file_generator(file_path, max_chunk_size)

        
        while True:
            def get_next_part():
                try:
                    return next(generator)
                except StopIteration:
                    return None
            
            part_path = await loop.run_in_executor(None, get_next_part)
            if not part_path:
                break
                
            parts_list.append(part_path)
            
            async def upload_progress(cur, tot):
                part_label = f"part {part_num}" if is_split else "file"
                await progress_bar_handler(cur, tot, progress_msg, f"Uploading {part_label} to Bale...")
                
            await progress_msg.edit_text(text=f"📤 Uploading part {part_num}...")
            
            await send_single_media(
                bot=bot,
                chat_id=chat_id,
                file_path=part_path,
                action=action,
                title=title if not is_split else f"{title} (Part {part_num})",
                uploader=uploader,
                duration=duration,
                thumb_path=thumb_path if not is_split else None,
                progress_fn=upload_progress,
                force_document=force_document or is_split
            )
            
            if part_path != file_path:
                if os.path.exists(part_path):
                    os.remove(part_path)
                    
            part_num += 1
            
        if os.path.exists(file_path):
            os.remove(file_path)
            
        await progress_msg.delete()
        
    except Exception as e:
        for p in parts_list:
            if p != file_path and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        raise e