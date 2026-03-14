"""
app/consumers/event_persister.py
==================================
Consumer: đọc stream:trade-events → ghi TradeHistory vào PostgreSQL.
Chạy như asyncio background task trong engine-service pod.

Tách ghi DB ra khỏi request handler:
  EA gửi trade-event → handler publish stream → return 200 ngay
  event_persister nhận → ghi DB → ACK

Benefits:
  - EA heartbeat latency không bị ảnh hưởng bởi DB write
  - Retry tự động nếu DB tạm down
  - Audit trail đầy đủ
"""

import os
import time
import json
import logging
import threading
from datetime import datetime, timezone

from shared.libs.messaging.redis_streams import (
    create_consumer_group, consume_messages,
)
from shared.libs.database.models import SessionLocal, TradeHistory

logger = logging.getLogger("zarmor.engine.persister")

STREAM         = "stream:trade-events"
CONSUMER_GROUP = "event-persister"
CONSUMER_NAME  = f"engine-worker-{os.getpid()}"
MAX_RETRY      = 5


def _handle_trade_event(event_type: str, payload: dict) -> bool:
    """
    Ghi trade event vào DB.
    Returns True (ACK) nếu thành công hoặc duplicate.
    Returns False (retry) nếu DB error tạm thời.
    """
    account_id = payload.get("account_id", "")
    ticket     = payload.get("ticket", "")

    if not account_id or not ticket:
        logger.warning(f"[PERSISTER] Invalid payload: {payload}")
        return True  # ACK — bad data không cần retry

    db = SessionLocal()
    try:
        if event_type == "TRADE_OPENED":
            # Idempotent: bỏ qua nếu đã có
            existing = db.query(TradeHistory).filter(
                TradeHistory.account_id == account_id,
                TradeHistory.ticket     == ticket,
            ).first()
            if existing:
                return True  # Duplicate — ACK

            db.add(TradeHistory(
                account_id=account_id,
                ticket=ticket,
                symbol=payload.get("symbol", ""),
                trade_type=payload.get("trade_type", ""),
                volume=float(payload.get("volume", 0)),
                open_price=float(payload.get("open_price", 0)),
                opened_at=datetime.fromisoformat(payload["opened_at"])
                          if payload.get("opened_at")
                          else datetime.now(timezone.utc),
            ))
            db.commit()
            logger.debug(f"[PERSISTER] OPEN persisted: {account_id} #{ticket}")
            return True

        elif event_type == "TRADE_CLOSED":
            trade = db.query(TradeHistory).filter(
                TradeHistory.account_id == account_id,
                TradeHistory.ticket     == ticket,
            ).first()
            if not trade:
                logger.warning(f"[PERSISTER] CLOSE for unknown ticket {ticket} — creating record")
                db.add(TradeHistory(
                    account_id=account_id,
                    ticket=ticket,
                    symbol=payload.get("symbol", ""),
                    close_price=float(payload.get("close_price", 0)),
                    pnl=float(payload.get("pnl", 0)),
                    rr_ratio=float(payload.get("rr_ratio", 0)),
                    closed_at=datetime.now(timezone.utc),
                ))
            else:
                trade.close_price = float(payload.get("close_price", 0))
                trade.pnl         = float(payload.get("pnl", 0))
                trade.rr_ratio    = float(payload.get("rr_ratio", 0))
                trade.closed_at   = datetime.fromisoformat(payload["closed_at"]) \
                                    if payload.get("closed_at") \
                                    else datetime.now(timezone.utc)
            db.commit()
            logger.debug(f"[PERSISTER] CLOSE persisted: {account_id} #{ticket} PnL={payload.get('pnl')}")
            return True

        else:
            logger.info(f"[PERSISTER] Unknown event_type {event_type} — ACK")
            return True

    except Exception as e:
        db.rollback()
        logger.error(f"[PERSISTER] DB error for {event_type} #{ticket}: {e}")
        return False  # Will retry
    finally:
        db.close()


def run_persister(shutdown_event: threading.Event):
    """Run consumer loop in background thread."""
    logger.info(f"[PERSISTER] Starting: group={CONSUMER_GROUP}, consumer={CONSUMER_NAME}")
    create_consumer_group(STREAM, CONSUMER_GROUP, start_id="0")

    while not shutdown_event.is_set():
        try:
            consume_messages(
                stream=STREAM,
                group=CONSUMER_GROUP,
                consumer=CONSUMER_NAME,
                handler=_handle_trade_event,
                batch_size=50,
                block_ms=1000,
                max_retry=MAX_RETRY,
            )
        except Exception as e:
            logger.error(f"[PERSISTER] Loop error: {e}")
            time.sleep(2)

    logger.info("[PERSISTER] Stopped.")


def start_persister_thread() -> threading.Event:
    """Start persister as daemon thread. Returns shutdown_event."""
    shutdown = threading.Event()
    t = threading.Thread(target=run_persister, args=(shutdown,), daemon=True, name="event-persister")
    t.start()
    logger.info("[PERSISTER] Background thread started")
    return shutdown
