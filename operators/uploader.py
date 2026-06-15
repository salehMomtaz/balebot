# operators/uploader.py
import os
import asyncio
import aiohttp
from aiogram import Bot
from utils.gate import is_document_mode
import config

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
                        
            form.add_field(field_name, f, filename=os.path.basename(file_path))
            
            async with session.post(url, data=form, timeout=1800) as response:
                res_json = await response.json()
                if not res_json.get("ok"):
                    raise RuntimeError(f"Bale API Error: {res_json.get('description', 'Unknown')}")
                return res_json

async def send_single_media(bot: Bot, chat_id: int, file_path: str, action: str, title: str, uploader: str, duration: int, thumb_path: str, progress_fn, force_document=False):
    """Sends a single media file to Bale using direct standard multipart uploads."""
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
            caption=f"🎵 **{title}**\nUploaded via Downloader Bot",
            extra_params={
                "title": title,
                "performer": uploader,
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
            caption=f"🎥 **{title}**\nUploaded via Downloader Bot",
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
    Caps VPS disk overhead to exactly ONE chunk size. Uses 48 MB boundaries to bypass Bale's 50 MB limit.
    """
    from operators.downloader import split_file_generator
    from main import progress_bar_handler
    
    file_size = os.path.getsize(file_path)
    
    # Strict 39 MB split limit for Bale to comfortably avoid 413 Payload Too Large errors
    max_chunk_size = 39 * 1024 * 1024
    force_document = is_document_mode(chat_id) or action == 'd'
    
    is_split = file_size > max_chunk_size
    parts_list = []
    
    try:
        part_num = 1
        loop = asyncio.get_event_loop()
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
