"""
webhook_retry.py — Z-ARMOR CLOUD
===================================
4.3 / R-15 FIX: Webhook retry queue cho Lark + Email

Khi Lark API hoặc Gmail SMTP fail → ghi vào bảng webhook_retry_queue
thay vì mất dữ liệu CRM. Background job retry theo exponential backoff.

Không cần Celery/Redis broker — dùng PostgreSQL làm queue (đủ cho scale hiện tại).
Upgrade lên Celery khi cần throughput cao hơn.

Tích hợp vào main.py:
    from webhook_retry import enqueue, start_retry_worker

    # Trong lifespan:
    retry_task = asyncio.create_task(start_retry_worker())

    # Thay lark_service call trực tiếp:
    await enqueue(db, "LARK_ORDER", {"order_id": ..., "buyer_email": ...})
    await enqueue(db, "EMAIL_LICENSE", {"receiver_email": ..., "license_key": ...})
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from database import SessionLocal, WebhookRetryQueue

logger = logging.getLogger("zarmor.retry")

# Exponential backoff delays (giây): thử lần 1 sau 30s, lần 2 sau 2m, ...
_BACKOFF = [30, 120, 600, 1800, 7200]   # 30s → 2m → 10m → 30m → 2h


# ══════════════════════════════════════════════════════════════════
# ENQUEUE — thay thế lark_service call trực tiếp
# ══════════════════════════════════════════════════════════════════
def enqueue_sync(db: Session, event_type: str, payload: dict, max_attempts: int = 5):
    """
    Ghi job vào queue. Gọi từ sync code (route handlers).

    Ví dụ:
        enqueue_sync(db, "LARK_ORDER", {"order_id": "ORD-123", "email": "..."})
        enqueue_sync(db, "EMAIL_LICENSE", {"receiver_email": "...", "license_key": "..."})
        enqueue_sync(db, "TELEGRAM_ALERT", {"chat_id": "...", "text": "..."})
    """
    now       = datetime.now(timezone.utc)
    next_try  = now + timedelta(seconds=_BACKOFF[0])

    job = WebhookRetryQueue(
        event_type    = event_type,
        payload_json  = json.dumps(payload, default=str),
        status        = "PENDING",
        attempts      = 0,
        max_attempts  = max_attempts,
        next_retry_at = next_try,
    )
    db.add(job)
    db.commit()
    logger.info(f"[RETRY-QUEUE] Enqueued {event_type} | id={job.id}")
    return job.id


async def enqueue(db: Session, event_type: str, payload: dict, max_attempts: int = 5) -> int:
    """Async wrapper của enqueue_sync."""
    return enqueue_sync(db, event_type, payload, max_attempts)


# ══════════════════════════════════════════════════════════════════
# HANDLERS — ánh xạ event_type → hàm xử lý
# ══════════════════════════════════════════════════════════════════
async def _handle_lark_order(payload: dict) -> bool:
    """Ghi order mới vào Lark Base."""
    try:
        # Import lazy để tránh circular
        from lark_service import push_order_to_lark
        record_id = await push_order_to_lark(
            buyer_name  = payload.get("buyer_name", ""),
            buyer_email = payload.get("buyer_email", ""),
            tier        = payload.get("tier", "STARTER"),
            amount      = float(payload.get("amount", 0)),
            method      = payload.get("method", "TRIAL_FREE"),
            key         = payload.get("license_key", ""),
            key_id      = int(payload.get("key_id", 0)),
            status      = payload.get("status", "PENDING"),
        )
        return record_id is not None
    except Exception as e:
        logger.warning(f"[RETRY] LARK_ORDER fail: {e}")
        return False


async def _handle_lark_update(payload: dict) -> bool:
    """Cập nhật record Lark Base (status, license key...)."""
    try:
        from lark_service import update_order_status_in_lark
        record_id = payload.get("record_id")
        if not record_id:
            logger.info("[RETRY] LARK_UPDATE skip - no record_id")
            return True
        from lark_service import update_order_status_in_lark
        await update_order_status_in_lark(
            record_id = record_id,
            status    = payload.get("status", "SUCCESS"),
        )
        return True
    except Exception as e:
        logger.warning(f"[RETRY] LARK_UPDATE fail: {e}")
        return False


async def _handle_email_license(payload: dict) -> bool:
    """Gửi email kèm license key cho customer."""
    try:
        from email_service import send_license_email_to_customer
        send_license_email_to_customer(
            payload["receiver_email"], payload["buyer_name"],
            payload["tier"],          payload["license_key"],
        )
        return True
    except Exception as e:
        logger.warning(f"[RETRY] EMAIL_LICENSE fail: {e}")
        return False


async def _handle_telegram_alert(payload: dict) -> bool:
    """Gửi Telegram notification."""
    try:
        from telegram_notify import tg_send
        text = payload.get("text", str(payload))
        await tg_send(text)
        return True
    except Exception as e:
        logger.warning(f"[RETRY] TELEGRAM_ALERT fail: {e}")
        return False


_HANDLERS = {
    "LARK_ORDER":      _handle_lark_order,
    "LARK_UPDATE":     _handle_lark_update,
    "EMAIL_LICENSE":   _handle_email_license,
    "TELEGRAM_ALERT":  _handle_telegram_alert,
}


# ══════════════════════════════════════════════════════════════════
# WORKER — chạy trong background task
# ══════════════════════════════════════════════════════════════════
async def _process_one(db: Session, job: WebhookRetryQueue):
    """Xử lý 1 job. Cập nhật status và next_retry_at."""
    now     = datetime.now(timezone.utc)
    handler = _HANDLERS.get(job.event_type)

    if not handler:
        job.status     = "DEAD"
        job.last_error = f"Không có handler cho {job.event_type}"
        db.commit()
        return

    job.status   = "PROCESSING"
    job.attempts += 1
    db.commit()

    try:
        payload = json.loads(job.payload_json)
        success = await handler(payload)
    except Exception as e:
        success    = False
        job.last_error = str(e)

    if success:
        job.status      = "SUCCESS"
        job.resolved_at = now
        logger.info(f"[RETRY-WORKER] ✅ {job.event_type} id={job.id} OK after {job.attempts} attempts")
    else:
        if job.attempts >= job.max_attempts:
            job.status = "DEAD"
            logger.error(f"[RETRY-WORKER] 💀 {job.event_type} id={job.id} DEAD after {job.attempts} attempts")
        else:
            delay          = _BACKOFF[min(job.attempts, len(_BACKOFF) - 1)]
            job.status     = "PENDING"
            job.next_retry_at = now + timedelta(seconds=delay)
            logger.warning(f"[RETRY-WORKER] ⏳ {job.event_type} id={job.id} retry #{job.attempts} in {delay}s")

    db.commit()


async def start_retry_worker(interval: int = 15):
    """
    Background worker — poll queue mỗi 15 giây.
    Thêm vào lifespan:

        retry_task = asyncio.create_task(start_retry_worker())
        yield
        retry_task.cancel()
    """
    logger.info("[RETRY-WORKER] 🚀 Started (interval=15s)")
    while True:
        try:
            db  = SessionLocal()
            now = datetime.now(timezone.utc)

            # Lấy tối đa 10 job pending đến hạn retry
            jobs = db.query(WebhookRetryQueue).filter(
                WebhookRetryQueue.status        == "PENDING",
                WebhookRetryQueue.next_retry_at <= now,
            ).order_by(WebhookRetryQueue.next_retry_at).limit(10).all()

            for job in jobs:
                try:
                    await _process_one(db, job)
                except Exception as e:
                    logger.error(f"[RETRY-WORKER] process_one error job={job.id}: {e}")

            # Cleanup: xóa SUCCESS + DEAD records cũ hơn 7 ngày
            cutoff = now - timedelta(days=7)
            db.query(WebhookRetryQueue).filter(
                WebhookRetryQueue.status.in_(["SUCCESS", "DEAD"]),
                WebhookRetryQueue.created_at < cutoff,
            ).delete(synchronize_session=False)
            db.commit()

        except Exception as e:
            logger.error(f"[RETRY-WORKER] loop error: {e}")
        finally:
            try: db.close()
            except: pass

        await asyncio.sleep(interval)


# ══════════════════════════════════════════════════════════════════
# ADMIN endpoint helper — xem queue status
# ══════════════════════════════════════════════════════════════════
def get_queue_stats(db: Session) -> dict:
    from sqlalchemy import func as sqlfunc
    rows = db.query(
        WebhookRetryQueue.status,
        sqlfunc.count(WebhookRetryQueue.id).label("count")
    ).group_by(WebhookRetryQueue.status).all()
    return {r.status: r.count for r in rows}
