"""app/senders/lark_sender.py — Lark Bot webhook sender."""

import os
import logging
import httpx

logger = logging.getLogger("zarmor.notification.lark")

LARK_WEBHOOK = os.getenv("LARK_BOT_WEBHOOK", "")


class LarkSender:
    def send(self, text: str) -> bool:
        if not LARK_WEBHOOK:
            return True
        try:
            import asyncio
            return asyncio.run(self._send_async(text))
        except Exception as e:
            logger.error(f"[LARK] Send error: {e}")
            return False

    async def _send_async(self, text: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(LARK_WEBHOOK, json={"msg_type": "text", "content": {"text": text}})
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"[LARK] HTTP error: {e}")
            return False
