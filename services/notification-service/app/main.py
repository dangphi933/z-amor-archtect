"""
notification-service/app/main.py
===================================
Service: Notification Consumer — không có HTTP port.
Consume Redis stream:notifications → dispatch qua Telegram / Email / Lark.

Extract từ monolith:
  - telegram_engine.py    → TelegramSender
  - email_service.py      → EmailSender
  - lark_service.py       → LarkSender
  - webhook_retry.py      → retry logic → DLQ

Event types consumed:
  DEFCON1_ALERT    → Telegram + Lark (urgent)
  DEFCON2_WARNING  → Telegram
  DEFCON3_SILENT   → Telegram (silent)
  TRADE_OPENED     → Telegram (per user config)
  TRADE_CLOSED     → Telegram (per user config)
  EMAIL_NOTIFY     → Email
  LARK_NOTIFY      → Lark webhook
  RADAR_ALERT      → Telegram (regime flip)

Chạy trong infinite loop — không cần uvicorn.
"""

import os
import sys
import time
import signal
import logging
import threading

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("zarmor.notification")

from .consumers.stream_consumer import run_consumer

_shutdown = threading.Event()


def _handle_signal(sig, frame):
    logger.info(f"[NOTIFICATION] Received signal {sig} — shutting down")
    _shutdown.set()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    logger.info("[NOTIFICATION-SERVICE] Starting stream consumer...")
    run_consumer(_shutdown)
    logger.info("[NOTIFICATION-SERVICE] Stopped.")
