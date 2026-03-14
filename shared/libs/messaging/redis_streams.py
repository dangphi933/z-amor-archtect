"""
shared/libs/messaging/redis_streams.py
=======================================
Redis Streams helpers cho inter-service communication.

Pattern:
  - engine-service PUBLISH event vào stream:notifications
  - notification-service CONSUME và dispatch (Telegram, Email, Lark)
  - radar-service PUBLISH vào stream:radar-updates
  - scheduler-service CONSUME radar-updates để trigger cache refresh

Stream names (constants):
  STREAM_NOTIFICATIONS  = "stream:notifications"
  STREAM_RADAR_UPDATES  = "stream:radar-updates"
  STREAM_NOTIFY_DLQ     = "stream:notifications-dlq"

Message format:
  Mỗi message là dict với:
    event_type: str    — "TELEGRAM_ALERT" | "EMAIL_NOTIFY" | "LARK_NOTIFY" | ...
    payload:    dict   — data tùy event_type
    source:     str    — tên service gửi
    ts:         float  — unix timestamp
"""

import os
import json
import time
import logging
from typing import Optional, Callable, Any

logger = logging.getLogger("zarmor.messaging")

STREAM_NOTIFICATIONS = os.getenv("REDIS_STREAM_NOTIFY",  "stream:notifications")
STREAM_RADAR_UPDATES = os.getenv("REDIS_STREAM_RADAR",   "stream:radar-updates")
STREAM_NOTIFY_DLQ    = os.getenv("DLQ_STREAM",           "stream:notifications-dlq")

_redis_client = None


def get_redis():
    """Lazy-init Redis client. Trả None nếu REDIS_URL không set."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        logger.warning("[REDIS] REDIS_URL not set — messaging disabled")
        return None
    try:
        import redis
        password = os.getenv("REDIS_PASSWORD", "")
        _redis_client = redis.from_url(
            redis_url,
            password=password or None,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        _redis_client.ping()
        logger.info("[REDIS] Connected to Redis")
        return _redis_client
    except Exception as e:
        logger.error(f"[REDIS] Connection failed: {e}")
        return None


def publish(stream: str, event_type: str, payload: dict, source: str = "unknown") -> Optional[str]:
    """
    Publish message vào Redis Stream.
    Returns message ID nếu thành công, None nếu fail.
    Fail silently — không crash caller nếu Redis down.
    """
    r = get_redis()
    if not r:
        return None
    try:
        message = {
            "event_type": event_type,
            "payload":    json.dumps(payload),
            "source":     source,
            "ts":         str(time.time()),
        }
        msg_id = r.xadd(stream, message, maxlen=10000, approximate=True)
        logger.debug(f"[STREAM] Published {event_type} → {stream} [{msg_id}]")
        return msg_id
    except Exception as e:
        logger.error(f"[STREAM] Publish failed to {stream}: {e}")
        return None


def publish_notification(event_type: str, payload: dict, source: str = "unknown") -> Optional[str]:
    """Shortcut: publish vào STREAM_NOTIFICATIONS."""
    return publish(STREAM_NOTIFICATIONS, event_type, payload, source)


def publish_radar_update(payload: dict, source: str = "radar-service") -> Optional[str]:
    """Shortcut: publish vào STREAM_RADAR_UPDATES."""
    return publish(STREAM_RADAR_UPDATES, "RADAR_SCAN_COMPLETE", payload, source)


def create_consumer_group(stream: str, group: str, start_id: str = "$"):
    """
    Tạo consumer group nếu chưa tồn tại.
    Gọi khi service khởi động.
    start_id="0": đọc từ đầu; "$": chỉ đọc messages mới
    """
    r = get_redis()
    if not r:
        return
    try:
        r.xgroup_create(stream, group, id=start_id, mkstream=True)
        logger.info(f"[STREAM] Created consumer group '{group}' on '{stream}'")
    except Exception as e:
        if "BUSYGROUP" in str(e):
            pass  # Group đã tồn tại — OK
        else:
            logger.warning(f"[STREAM] xgroup_create warning: {e}")


def consume_messages(
    stream: str,
    group: str,
    consumer: str,
    handler: Callable[[str, dict], bool],
    batch_size: int = 10,
    block_ms: int = 2000,
    max_retry: int = 3,
):
    """
    Consume messages từ Redis Stream với consumer group.
    handler(event_type, payload) → True nếu xử lý OK, False nếu cần retry.
    Tự động ACK khi handler trả True.
    Tự động move sang DLQ khi vượt max_retry.

    Blocking call — chạy trong infinite loop bên ngoài:
        while True:
            consume_messages(...)
    """
    r = get_redis()
    if not r:
        time.sleep(2)
        return

    try:
        # Đọc pending messages trước (crash recovery)
        pending = r.xreadgroup(
            groupname=group, consumername=consumer,
            streams={stream: "0"},
            count=batch_size,
        )
        if pending and pending[0][1]:
            _process_batch(r, stream, group, pending[0][1], handler, max_retry)

        # Đọc messages mới
        new_msgs = r.xreadgroup(
            groupname=group, consumername=consumer,
            streams={stream: ">"},
            count=batch_size,
            block=block_ms,
        )
        if new_msgs and new_msgs[0][1]:
            _process_batch(r, stream, group, new_msgs[0][1], handler, max_retry)

    except Exception as e:
        logger.error(f"[STREAM] consume error on {stream}: {e}")
        time.sleep(1)


def _process_batch(r, stream: str, group: str, messages: list, handler: Callable, max_retry: int):
    """Process một batch messages, ACK hoặc move sang DLQ."""
    for msg_id, fields in messages:
        event_type = fields.get("event_type", "UNKNOWN")
        try:
            payload = json.loads(fields.get("payload", "{}"))
        except json.JSONDecodeError:
            payload = {}

        # Kiểm tra retry count
        retry_count = int(fields.get("_retry_count", "0"))

        try:
            ok = handler(event_type, payload)
            if ok:
                r.xack(stream, group, msg_id)
                logger.debug(f"[STREAM] ACK {msg_id} ({event_type})")
            else:
                raise RuntimeError("handler returned False")
        except Exception as e:
            retry_count += 1
            logger.warning(f"[STREAM] Handler failed {msg_id} (retry {retry_count}/{max_retry}): {e}")
            if retry_count >= max_retry:
                # Move to DLQ
                _move_to_dlq(r, stream, group, msg_id, event_type, payload, str(e))
            else:
                # Re-queue với updated retry count
                fields["_retry_count"] = str(retry_count)
                r.xadd(stream, fields, maxlen=10000, approximate=True)
                r.xack(stream, group, msg_id)


def _move_to_dlq(r, stream: str, group: str, msg_id: str, event_type: str, payload: dict, error: str):
    """Move failed message sang DLQ stream."""
    try:
        r.xadd(STREAM_NOTIFY_DLQ, {
            "original_stream": stream,
            "original_msg_id": msg_id,
            "event_type":      event_type,
            "payload":         json.dumps(payload),
            "error":           error,
            "failed_at":       str(time.time()),
        }, maxlen=1000)
        r.xack(stream, group, msg_id)
        logger.error(f"[STREAM] Moved {msg_id} to DLQ: {error}")
    except Exception as e:
        logger.error(f"[STREAM] DLQ move failed: {e}")
