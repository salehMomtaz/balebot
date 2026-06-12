# utils/logger.py
import logging
import time
import threading
import requests

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
                    requests.post(self.api_url, json=payload, timeout=5)
                except Exception:
                    pass

            # Dispatch HTTP post in background thread so it never blocks the main loop
            threading.Thread(target=execute_post, daemon=True).start()
            
        except Exception:
            pass