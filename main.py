# main.py
import os
import time
import asyncio
import shutil
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
import config
from utils.shared import queue, DOWNLOAD_CACHE, LAST_UPDATE_TIME

# =========================================================================
# Application Global Shared Instances
# =========================================================================

# Redirect aiogram's standard API server base URL to tapi.bale.ai
BALE_API_SERVER = TelegramAPIServer.from_base("https://tapi.bale.ai")
bale_session = AiohttpSession(api=BALE_API_SERVER)

bot = Bot(token=config.BALE_TOKEN, session=bale_session)
dp = Dispatcher()

# =========================================================================
# Global Shared Helpers & Standalone Logging Registry
# =========================================================================

def setup_system_logger():
    """Binds our custom BaleChannelHandler directly to Python's root logger."""
    if config.LOG_CHANNEL_ID != 0:
        try:
            from utils.logger import BaleChannelHandler
            root_logger = logging.getLogger()
            
            # Explicitly lower root logger's filtering threshold so INFO logs are not discarded
            root_logger.setLevel(logging.INFO)
            
            # Format logs briefly, our custom handler will add emojis, timestamps, and module tags
            formatter = logging.Formatter('%(message)s')
            handler = BaleChannelHandler(config.BALE_TOKEN, config.LOG_CHANNEL_ID)
            handler.setFormatter(formatter)
            handler.setLevel(logging.INFO)  # Capture standard INFO, WARNING, and ERROR logs
            
            root_logger.addHandler(handler)
            print("[Logger] Standalone Bale Logging Service linked to Root Logger.")
        except Exception as e:
            print(f"Warning: Failed to initialize standalone Bale logger: {e}")

async def log_event(text: str):
    """Log an event locally. The standalone root logger handles automatic Bale routing."""
    logging.info(text)

async def progress_bar_handler(current, total, message, status_title: str):
    """Draws a visual progress bar and updates text every 5 seconds to avoid rate limiting."""
    now = time.time()
    msg_id = message.message_id
    if msg_id in LAST_UPDATE_TIME and now - LAST_UPDATE_TIME[msg_id] < 5:
        return
    LAST_UPDATE_TIME[msg_id] = now
    
    percentage = (current * 100 / total) if total > 0 else 0
    filled = int(percentage // 10)
    bar_str = "■" * filled + "□" * (10 - filled)
    
    current_mb = round(current / (1024 * 1024), 1)
    total_mb = round(total / (1024 * 1024), 1)
    
    text = (
        f"⏳ *{status_title}*\n"
        f"`[{bar_str}]` {percentage:.1f}%\n"
        f"📦 `{current_mb} MB / {total_mb} MB`"
    )
    try:
        await message.edit_text(text)
    except Exception:
        pass

def initialize_cookie_jars():
    """Initializes empty cookie files with the Netscape header to prevent warnings."""
    cookie_files = [config.YT_COOKIES, config.IG_COOKIES, config.TT_COOKIES, config.X_COOKIES, config.COOKIES_FILE]
    for file_path in cookie_files:
        needs_init = False
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            needs_init = True
        else:
            try:
                with open(file_path, "r") as f:
                    first_line = f.readline()
                if not first_line.startswith("# Netscape"):
                    needs_init = True
            except Exception:
                needs_init = True
                
        if needs_init:
            try:
                with open(file_path, "w") as f:
                    f.write("# Netscape HTTP Cookie File\n")
                print(f"[Cookies] Cookie jar initialized with Netscape header: {file_path}")
            except Exception as e:
                print(f"[Cookies] Warning: Could not initialize cookie jar {file_path}: {e}")

async def auto_clean_cache_directory():
    """Periodically sweeps the cache directory every hour to purge orphaned files older than 2 hours."""
    while True:
        print("[Cleaner] Running periodic cache sweep...")
        cache_dir = "cache"
        if os.path.exists(cache_dir):
            now = time.time()
            threshold = now - 7200  # 2 hours = 7200 seconds
            try:
                for entry in os.scandir(cache_dir):
                    mtime = entry.stat().st_mtime
                    if mtime < threshold:
                        if entry.is_dir():
                            shutil.rmtree(entry.path)
                            print(f"[Cleaner] Purged orphaned directory: {entry.path}")
                        else:
                            os.remove(entry.path)
                            print(f"[Cleaner] Purged orphaned file: {entry.path}")
            except Exception as e:
                print(f"[Cleaner] Exception occurred during cache sweep: {e}")
                
        await asyncio.sleep(3600)  # Wait 1 hour

# =========================================================================
# Event Loop Bootstrap & Startup Configuration
# =========================================================================

async def main_engine():
    print("Initializing balebot services...")
    
    # 1. Start the global system logger to pipe all container logs to your channel
    setup_system_logger()
    
    # 2. Initialize and format cookie files
    initialize_cookie_jars()
    
    # 3. Import and register modular routing and security middlewares
    from modules.admin import admin_router, SecurityGateMiddleware
    from modules.translate import translate_router
    from modules.github import github_router
    
    # Register our customized security middleware on both messages and callback query streams
    dp.message.middleware(SecurityGateMiddleware())
    dp.callback_query.middleware(SecurityGateMiddleware())
    
    # Include admin and setting routers
    dp.include_router(admin_router)
    dp.include_router(translate_router)
    dp.include_router(github_router)
    
    print("Bale Bot Online and Listening.")
    
    from utils.updater import auto_update_ytdlp
    
    # Run standard long polling and background tasks concurrently
    await asyncio.gather(
        dp.start_polling(bot),
        auto_update_ytdlp(),
        auto_clean_cache_directory()
    )

if __name__ == "__main__":
    import sys
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main_engine())
    except KeyboardInterrupt:
        print("Stopping bot gracefully...")