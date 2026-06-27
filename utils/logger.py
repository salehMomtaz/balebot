# utils/logger.py
import logging
import os
import time
import threading
import requests


def ensure_local_log_handler(log_dir: str = "logs", log_file: str = "bot.log") -> logging.Handler:
    """
    Create and return a rotating file handler that mirrors every log to a local file.
    This lets the assistant read the same logs that are sent to the Bale channel,
    without affecting the existing channel logging behavior.
    """
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_path = os.path.join(log_dir, log_file)
        handler = logging.handlers.RotatingFileHandler(
            filename=file_path,
            maxBytes=5 * 1024 * 1024,   # 5 MB per file
            backupCount=3,              # keep bot.log, bot.log.1, bot.log.2, bot.log.3
            encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
        handler.setLevel(logging.INFO)
        return handler
    except Exception:
        # If file logging fails for any reason, return a do-nothing handler so the bot still runs.
        return logging.NullHandler()


class BaleChannelHandler(logging.Handler):
    """
    Custom Python Logging Handler for Bale:
    Intercepts the system's root logger outputs and pipes them securely 
    to your private Bale log channel in real-time.
    Runs asynchronously inside non-blocking daemon threads.
    """
    def __init__(self, bot_token: str, channel_id: int):
        super().__init__()
        self.bot_token = bot_token
        self.channel_id = channel_id
        # Points securely to Bale's tapi gateway
        self.api_url = f"https://tapi.bale.ai/bot{bot_token}/sendMessage"

    def emit(self, record):
        try:
            log_entry = self.format(record)
            
            # Format timestamp and level tags
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record.created))
            level = record.levelname
            module = record.module
            
            # Emojis for logger severity
            emoji = "📝"
            if level == "WARNING":
                emoji = "⚠️"
            elif level in ["ERROR", "CRITICAL"]:
                emoji = "🚨"
                
            # Escape backticks to prevent Markdown parsing exceptions in Bale
            clean_entry = log_entry.replace("`", "'")
            
            # Truncate to prevent payload size errors on long traceback logs
            if len(clean_entry) > 3500:
                clean_entry = clean_entry[:3500] + "\n... [TRUNCATED] ..."
            
            # Format using Bale's standard Markdown specifications
            text_payload = (
                f"{emoji} *[{level}]* `[{timestamp}]` _({module})_\n\n"
                f"```\n{clean_entry}\n```"
            )
            
            payload = {
                "chat_id": self.channel_id,
                "text": text_payload
            }
            
            def execute_post():
                try:
                    import config
                    proxies = {"http": config.REQUESTS_PROXY, "https": config.REQUESTS_PROXY} if getattr(config, "REQUESTS_PROXY", None) else None
                    requests.post(self.api_url, json=payload, timeout=5, proxies=proxies)
                except Exception:
                    pass

            # Dispatch HTTP post in background thread so it never blocks the main loop
            threading.Thread(target=execute_post, daemon=True).start()
            
        except Exception:
            pass