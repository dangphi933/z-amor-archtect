"""
app/consumers/stream_consumer.py
==================================
Redis stream consumer — đọc stream:notifications và dispatch.
"""

import os
import time
import logging
import threading
from typing import Optional

from shared.libs.messaging.redis_streams import (
    STREAM_NOTIFICATIONS, create_consumer_group, consume_messages,
)
from ..senders.telegram_sender import TelegramSender
from ..senders.email_sender import EmailSender
from ..senders.lark_sender import LarkSender

logger = logging.getLogger("zarmor.notification.consumer")

CONSUMER_GROUP = "notification-service"
CONSUMER_NAME  = f"worker-{os.getpid()}"
MAX_RETRY      = int(os.getenv("MAX_RETRY", "3"))

_telegram = TelegramSender()
_email    = EmailSender()
_lark     = LarkSender()


def _dispatch(event_type: str, payload: dict) -> bool:
    """
    Route event → đúng sender.
    Returns True nếu dispatch thành công hoặc không cần retry.
    """
    try:
        account_id = payload.get("account_id", "")
        message    = payload.get("message", "")

        # ── Telegram events ──────────────────────────────────────
        if event_type == "DEFCON1_ALERT":
            return _telegram.send_admin(
                f"🚨 <b>DEFCON 1 — CRITICAL</b>\n"
                f"Account: <code>{account_id}</code>\n"
                f"{message}\n"
                f"Kill reason: {payload.get('kill_reason', '')}",
                silent=False,
            )

        elif event_type == "DEFCON2_WARNING":
            return _telegram.send_admin(
                f"⚠️ <b>DEFCON 2 — WARNING</b>\n"
                f"Account: <code>{account_id}</code>\n{message}",
                silent=False,
            )

        elif event_type == "DEFCON3_SILENT":
            return _telegram.send_admin(
                f"ℹ️ {message}",
                silent=True,
            )

        elif event_type == "TRADE_OPENED":
            chat_id = _get_user_chat_id(account_id)
            if chat_id:
                return _telegram.send_user(
                    chat_id,
                    f"📈 <b>Trade OPENED</b>\n"
                    f"Account: <code>{account_id}</code>\n"
                    f"Ticket: {payload.get('ticket')}\n"
                    f"Symbol: {payload.get('symbol')} {payload.get('trade_type')}\n"
                    f"Vol: {payload.get('volume')} @ {payload.get('price')}",
                )
            return True  # No chat_id → không cần retry

        elif event_type == "TRADE_CLOSED":
            chat_id = _get_user_chat_id(account_id)
            pnl = payload.get("pnl", 0)
            emoji = "✅" if pnl >= 0 else "❌"
            if chat_id:
                return _telegram.send_user(
                    chat_id,
                    f"{emoji} <b>Trade CLOSED</b>\n"
                    f"Account: <code>{account_id}</code>\n"
                    f"Ticket: {payload.get('ticket')}\n"
                    f"PnL: <b>${pnl:.2f}</b> | RR: {payload.get('rr_ratio', 0):.2f}",
                )
            return True

        elif event_type == "RADAR_ALERT":
            return _telegram.send_admin(
                f"🎯 <b>RADAR REGIME FLIP</b>\n"
                f"Symbol: {payload.get('symbol')}\n"
                f"Regime: {payload.get('old_regime')} → {payload.get('new_regime')}\n"
                f"Score: {payload.get('score')}",
                silent=False,
            )

        # ── Email events ─────────────────────────────────────────
        elif event_type == "EMAIL_NOTIFY":
            return _email.send(
                to_email=payload.get("to_email", ""),
                subject=payload.get("subject", "Z-ARMOR Notification"),
                html_body=payload.get("html_body", ""),
            )

        elif event_type == "LICENSE_DELIVERED":
            return _email.send_license(
                to_email=payload.get("buyer_email", ""),
                buyer_name=payload.get("buyer_name", ""),
                tier=payload.get("tier", ""),
                license_key=payload.get("license_key", ""),
            )

        # ── Lark events ──────────────────────────────────────────
        elif event_type == "LARK_NOTIFY":
            return _lark.send(payload.get("text", str(payload)))

        # ── Unknown ──────────────────────────────────────────────
        else:
            logger.warning(f"[NOTIFICATION] Unknown event_type: {event_type}")
            return True  # Don't retry unknown events

    except Exception as e:
        logger.error(f"[NOTIFICATION] Dispatch error for {event_type}: {e}")
        return False


def _get_user_chat_id(account_id: str) -> Optional[str]:
    """Lookup Telegram chat_id từ DB."""
    try:
        from shared.libs.database.models import SessionLocal, TelegramConfig
        db = SessionLocal()
        try:
            tg = db.query(TelegramConfig).filter(
                TelegramConfig.account_id == account_id,
                TelegramConfig.is_active == True,
            ).first()
            return tg.chat_id if tg else None
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[NOTIFICATION] DB lookup failed: {e}")
        return None


def run_consumer(shutdown_event: threading.Event):
    """Main consumer loop — chạy đến khi shutdown_event set."""
    logger.info(f"[NOTIFICATION] Consumer starting: group={CONSUMER_GROUP}, name={CONSUMER_NAME}")

    # Tạo consumer group (idempotent)
    create_consumer_group(STREAM_NOTIFICATIONS, CONSUMER_GROUP, start_id="0")

    while not shutdown_event.is_set():
        try:
            consume_messages(
                stream=STREAM_NOTIFICATIONS,
                group=CONSUMER_GROUP,
                consumer=CONSUMER_NAME,
                handler=_dispatch,
                batch_size=20,
                block_ms=2000,
                max_retry=MAX_RETRY,
            )
        except Exception as e:
            logger.error(f"[NOTIFICATION] Consumer loop error: {e}")
            time.sleep(2)

    logger.info("[NOTIFICATION] Consumer stopped cleanly.")
