# utils/uploader.py
import os
import asyncio
from aiogram import Bot
from aiogram.types import FSInputFile
from utils.gate import is_document_mode

async def send_single_media(bot: Bot, chat_id: int, file_path: str, action: str, title: str, uploader: str, duration: int, thumb_path: str, progress_fn, force_document=False):
    """Sends a single media file to Bale using aiogram v3 FSInputFile, passing thumbs to document uploads too."""
    from utils.downloader import probe_video_dimensions
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    doc_file = FSInputFile(file_path)
    thumb_file = FSInputFile(thumb_path) if (thumb_path and os.path.exists(thumb_path)) else None
    
    if force_document:
        return await bot.send_document(
            chat_id=chat_id,
            document=doc_file,
            caption=f"📁 **Part:** `{os.path.basename(file_path)}`",
            thumbnail=thumb_file,  # Bale supports document thumbnail previews!
        )
        
    if action == 'a':
        return await bot.send_audio(
            chat_id=chat_id,
            audio=doc_file,
            title=title,
            performer=uploader,
            duration=int(duration),
            thumbnail=thumb_file
        )
    else:  # action == 'v'
        width, height, parsed_duration = probe_video_dimensions(file_path)
        final_duration = parsed_duration if parsed_duration > 0 else int(duration)
        return await bot.send_video(
            chat_id=chat_id,
            video=doc_file,
            width=width,
            height=height,
            duration=final_duration,
            thumbnail=thumb_file,
            supports_streaming=True
        )

async def process_split_and_upload(bot: Bot, chat_id: int, file_path: str, action: str, title: str, uploader: str, duration: int, thumb_path: str, progress_msg):
    """
    On-Demand Sequential Uploader for Bale:
    Generates chunks one-by-one, uploads them, and immediately purges them from disk.
    Caps VPS disk overhead to exactly ONE chunk size. Uses 48 MB boundaries to bypass Bale's 50 MB limit.
    """
    from utils.downloader import split_file_generator
    from main import progress_bar_handler
    
    file_size = os.path.getsize(file_path)
    
    # Strict 48 MB split limit for Bale (48 MB = 48 * 1024 * 1024 bytes)
    max_chunk_size = 48 * 1024 * 1024
    force_document = is_document_mode(chat_id)
    
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