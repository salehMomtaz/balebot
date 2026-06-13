# modules/admin/middleware.py
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from utils.gate import is_blacklisted, is_authorized, blacklist_user
import config

class SecurityGateMiddleware(BaseMiddleware):
    """
    aiogram v3 Security Gate Middleware:
    Pre-intercepts all incoming updates, blocks banned users, and
    automatically blacklists and bans intruders silently.
    """
    async def __call__(self, handler, event: TelegramObject, data: dict):
        from main import log_event
        
        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)
            
        if is_blacklisted(user_id):
            return  # Block and ignore completely
            
        if not is_authorized(user_id):
            blacklist_user(user_id)
            await log_event(f"⚠️ *Intruder Blocked:* User `{user_id}` has been banned.")
            return  # Terminate propagation
            
        return await handler(event, data)