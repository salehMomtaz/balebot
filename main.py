# main.py
import os
import time
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
import config

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
            
            # Lower root logger threshold so INFO logs are processed
            root_logger.setLevel(logging.INFO)
            
            formatter = logging.Formatter('%(message)s')
            handler = BaleChannelHandler(config.BALE_TOKEN, config.LOG_CHANNEL_ID)
            handler.setFormatter(formatter)
            handler.setLevel(logging.INFO)
            
            root_logger.addHandler(handler)
            print("[Logger] Standalone Bale Logging Service linked to Root Logger.")
        except Exception as e:
            print(f"Warning: Failed to initialize standalone Bale logger: {e}")

async def log_event(text: str):
    """Log an event locally. The standalone root logger handles automatic Bale routing."""
    logging.info(text)

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

# =========================================================================
# Event Loop Bootstrap & Startup Configuration
# =========================================================================

async def main_engine():
    print("Initializing balebot services...")
    
    # 1. Start the global system logger to pipe all container logs to your channel
    setup_system_logger()
    
    # 2. Initialize and format cookie files
    initialize_cookie_jars()
    
    # 3. Import and register modular handler systems (We will define these next)
    # from modules.admin import register_admin_handlers
    # ...
    
    print("Bale Bot Online and Listening.")
    
    from utils.updater import auto_update_ytdlp
    from main import auto_clean_cache_directory # Placeholder: we'll define auto_clean or import it
    
    # Run standard long polling and background tasks concurrently
    # Note: No FastAPI or port exposures are needed!
    await asyncio.gather(
        dp.start_polling(bot),
        auto_update_ytdlp()
    )

if __name__ == "__main__":
    import sys
    try:
        asyncio.run(main_engine())
    except KeyboardInterrupt:
        print("Stopping bot gracefully...")