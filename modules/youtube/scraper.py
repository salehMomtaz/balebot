# modules/youtube/scraper.py
import os
import re
import asyncio
import yt_dlp

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
        if (not line_strip or 
            line_strip.startswith("WEBVTT") or 
            line_strip.startswith("Kind:") or 
            line_strip.startswith("Language:") or 
            "-->" in line_strip or 
            line_strip.isdigit()):
            continue
        line_clean = re.sub(r"<[^>]+>", "", line_strip)
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
            'extract_flat': True,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
    info = await loop.run_in_executor(None, extract)
    return info.get('entries', [])