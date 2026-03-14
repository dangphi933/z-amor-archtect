"""
app/senders/telegram_sender.py
================================
Telegram sender — extract từ telegram_engine.py monolith.
Giữ nguyên DEFCON 1/2/3 message formats.
"""

import os
import asyncio
import logging
import httpx

logger = logging.getLogger("zarmor.notification.telegram")

BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID   = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "") or os.getenv("ADMIN_TELEGRAM_CHAT_ID", "")
RADAR_CHAT_ID   = os.getenv("RADAR_ALERT_CHAT_ID", ADMIN_CHAT_ID)


class TelegramSender:
    def __init__(self):
        self.bot_token    = BOT_TOKEN
        self.admin_chat   = ADMIN_CHAT_ID
        self.radar_chat   = RADAR_CHAT_ID

    def _is_configured(self) -> bool:
        if not self.bot_token or "THAY_TOKEN" in self.bot_token:
            logger.warning("[TELEGRAM] Bot token not configured")
            return False
        return True

    def send_admin(self, text: str, silent: bool = False) -> bool:
        """Gửi tới admin chat."""
        if not self.admin_chat:
            return True  # No admin chat configured — not an error
        return self._send_sync(self.admin_chat, text, silent)

    def send_user(self, chat_id: str, text: str, silent: bool = False) -> bool:
        """Gửi tới user chat."""
        return self._send_sync(chat_id, text, silent)

    def _send_sync(self, chat_id: str, text: str, silent: bool) -> bool:
        """Synchronous send — notification service runs in sync context."""
        if not self._is_configured():
            return True  # Configured-away — not retry-worthy
        try:
            return asyncio.run(self._send_async(chat_id, text, silent))
        except RuntimeError:
            # Already in event loop
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._send_async(chat_id, text, silent))
            finally:
                loop.close()

    async def _send_async(self, chat_id: str, text: str, silent: bool) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id":                  chat_id,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
            "disable_notification":     silent,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.debug(f"[TELEGRAM] Sent to {chat_id}: {text[:50]}...")
                    return True
                logger.warning(f"[TELEGRAM] HTTP {resp.status_code}: {resp.text[:100]}")
                # 429 = rate limit → retry
                # 400 = bad request → don't retry
                return resp.status_code == 429
        except httpx.TimeoutException:
            logger.warning(f"[TELEGRAM] Timeout sending to {chat_id}")
            return False  # Retry
        except Exception as e:
            logger.error(f"[TELEGRAM] Error: {e}")
            return False
