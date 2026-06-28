# main.py
import os
import time
import asyncio
import shutil
import logging
from dotenv import load_dotenv
load_dotenv()

from aiogram import Bot, Dispatcher, F
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
import config
from utils.shared import queue, DOWNLOAD_CACHE, LAST_UPDATE_TIME

# =========================================================================
# Application Global Shared Instances (Pure aiogram v3 API Server Redirect)
# =========================================================================

BALE_API_SERVER = TelegramAPIServer.from_base("https://tapi.bale.ai")

# Optional proxy for the Bale/aiogram connection itself. Usually not needed because
# api.bale.ai is not blocked, but it is exposed for completeness.
def _build_bale_session():
    proxy = getattr(config, "AIOHTTP_PROXY", None)
    if proxy:
        try:
            return AiohttpSession(api=BALE_API_SERVER, proxy=proxy)
        except RuntimeError as exc:
            if "aiohttp-socks" in str(exc).lower():
                print(f"[Proxy] aiohttp-socks not installed; Bale connection will bypass proxy.")
                return AiohttpSession(api=BALE_API_SERVER)
            raise
    return AiohttpSession(api=BALE_API_SERVER)

bale_session = _build_bale_session()

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
            
            # CRITICAL FIX: Explicitly lower root logger's filtering threshold so INFO logs are not discarded
            root_logger.setLevel(logging.INFO)
            
            channel_formatter = logging.Formatter('%(message)s')
            handler = BaleChannelHandler(config.BALE_TOKEN, config.LOG_CHANNEL_ID)
            handler.setFormatter(channel_formatter)
            handler.setLevel(logging.INFO)  # Capture standard INFO, WARNING, and ERROR logs

            # Also mirror the same logs to a local file for real-time debugging.
            # The local file keeps timestamps/levels because we read it directly.
            from utils.logger import ensure_local_log_handler
            local_handler = ensure_local_log_handler()
            local_handler.setFormatter(
                logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)s | %(message)s')
            )
            local_handler.setLevel(logging.INFO)

            root_logger.addHandler(handler)
            root_logger.addHandler(local_handler)
            logging.info("[Logger] Standalone Bale Logging Service linked to Root Logger.")
            logging.info(f"[Logger] Local log mirror active at: {os.path.abspath('logs/bot.log')}")
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
    """
    Ensure cookie files exist with a Netscape header.
    If a jar already has content, prepend the header when it is missing.
    Never overwrite existing cookies.

    The YouTube working jar is made read-only after init so that yt-dlp cannot
    corrupt it with write-back. Every yt-dlp invocation receives a snapshot copy
    from operators/downloader.get_cookies_for_url() instead.
    """
    header = "# Netscape HTTP Cookie File\n"
    cookie_files = [config.YT_COOKIES, config.IG_COOKIES, config.TT_COOKIES, config.X_COOKIES, config.COOKIES_FILE]
    for file_path in cookie_files:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(header)
                print(f"[Cookies] Initialized empty cookie jar: {file_path}")
            except Exception as e:
                print(f"[Cookies] Warning: Could not initialize cookie jar {file_path}: {e}")
            continue

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if not content.strip().startswith("# Netscape"):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(header + content)
                print(f"[Cookies] Added missing Netscape header to: {file_path}")
        except Exception as e:
            print(f"[Cookies] Warning: Could not check cookie jar {file_path}: {e}")

    # If YouTube working jar is missing but a protected backup exists, restore it.
    backup_path = getattr(config, "YT_COOKIES_BACKUP", "ytcookies.backup")
    if (not os.path.exists(config.YT_COOKIES) or os.path.getsize(config.YT_COOKIES) == 0) and os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
        try:
            # Make target writable in case a previous crash left it read-only.
            if os.path.exists(config.YT_COOKIES):
                os.chmod(config.YT_COOKIES, 0o644)
            shutil.copy(backup_path, config.YT_COOKIES)
            print(f"[Cookies] Restored {config.YT_COOKIES} from protected backup.")
        except Exception as e:
            print(f"[Cookies] Warning: Could not restore YouTube cookie backup: {e}")

    # Lock the live jar so yt-dlp can never rewrite it. Admin replace/savebackup
    # temporarily make it writable when they need to update it.
    try:
        # If the file is currently writable (e.g. after a manual edit), force it back.
        if os.path.exists(config.YT_COOKIES) and os.access(config.YT_COOKIES, os.W_OK):
            os.chmod(config.YT_COOKIES, 0o644)
        os.chmod(config.YT_COOKIES, 0o444)
        print(f"[Cookies] Locked {config.YT_COOKIES} read-only to prevent yt-dlp corruption.")
    except Exception as e:
        print(f"[Cookies] Warning: Could not lock {config.YT_COOKIES}: {e}")

async def auto_clean_cache_directory():
    """Periodically sweeps the cache directory to purge orphaned files older than the configured age."""
    from utils.shared import RUNTIME_SETTINGS
    while True:
        print("[Cleaner] Running periodic cache sweep...")
        cache_dir = "cache"
        if os.path.exists(cache_dir):
            now = time.time()
            max_age_hours = RUNTIME_SETTINGS.get("max_cache_age_hours", 2)
            threshold = now - (max_age_hours * 3600)
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

    # 3. Disk-space sanity check: refuse to run if the filesystem is critically full
    try:
        import shutil
        usage = shutil.disk_usage(os.getcwd())
        free_gb = usage.free / (1024 ** 3)
        used_pct = (usage.used / usage.total) * 100
        logging.info(f"[System] Disk usage: {used_pct:.1f}% used, {free_gb:.2f} GB free.")
        if used_pct > 95:
            logging.error("[System] Disk is critically full. Refusing to start to protect SSH/system access.")
            return
    except Exception as e:
        logging.warning(f"[System] Could not check disk usage: {e}")

    # 4. Import and register modular routing and security middlewares
    from modules.admin.router import admin_router
    from modules.admin.middleware import SecurityGateMiddleware
    from modules.user.router import user_router
    from modules.translate.router import translate_router
    from modules.github.router import github_router
    from modules.youtube.router import youtube_router
    from modules.downloader.router import downloader_router
    from modules.direct_dl.router import direct_dl_router
    
    # Register our customized security middleware on both messages and callback query streams
    dp.message.middleware(SecurityGateMiddleware())
    dp.callback_query.middleware(SecurityGateMiddleware())
    
    # Include all modular routers
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(translate_router)
    dp.include_router(github_router)
    dp.include_router(youtube_router)
    dp.include_router(downloader_router)
    dp.include_router(direct_dl_router)

    # 5. Start the PO-token provider if enabled.  Never let a provider failure
    # crash the bot; we always fall back to cookies / no-auth for YouTube.
    pot_manager = None
    if config.YTDLP_POT_ENABLED:
        from utils.pot_provider import PotProviderManager
        import utils.shared as shared
        try:
            pot_manager = PotProviderManager()
            await pot_manager.start()
            shared.pot_manager_instance = pot_manager
            logging.info(f"[POT] Provider started on 127.0.0.1:{config.YTDLP_POT_PORT}")
        except Exception as e:
            logging.error(f"[POT] Failed to start provider: {e}. YouTube downloads will fall back to cookies only.")
            shared.pot_manager_instance = None
            pot_manager = None

    logging.info("Bale Bot Online.")
    
    # Resolve Log Channel Peer on startup to avoid exceptions
    if config.LOG_CHANNEL_ID != 0:
        try:
            await bot.get_chat(config.LOG_CHANNEL_ID)
            print("Log Channel resolved successfully.")
        except Exception as e:
            print(f"Warning: Could not resolve Log Channel ID: {e}")
            
    from utils.updater import auto_update_ytdlp

    # CRITICAL RELIABILITY FIX: Clear webhook and drop any backlog updates sent when the bot was down!
    try:
        print("[Polling] Removing webhook and dropping pending backlog...")
        await bot.delete_webhook(drop_pending_updates=True)
        print("[Polling] Backlog successfully dropped.")
    except Exception as e:
        print(f"[Polling] Warning: Failed to drop pending updates: {e}")

    # Run standard long polling and background tasks concurrently
    tasks = [
        dp.start_polling(bot),
        auto_update_ytdlp(),
        auto_clean_cache_directory()
    ]
    if pot_manager:
        tasks.append(pot_manager.health_check_loop())

    try:
        await asyncio.gather(*tasks)
    finally:
        if pot_manager:
            await pot_manager.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main_engine())
    except KeyboardInterrupt:
        print("Stopping bot gracefully...")