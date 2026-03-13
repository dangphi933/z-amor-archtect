"""
monitoring.py — Z-ARMOR CLOUD
================================
4.3 / R-11: Prometheus metrics endpoint.
Theo dõi: request latency, heartbeat count, DB connections, license stats.

Cài đặt:
    pip install prometheus-client

Tích hợp vào main.py:
    from monitoring import setup_metrics, metrics_middleware
    setup_metrics(app)   # mount /metrics endpoint

Prometheus scrape config (prometheus.yml):
    scrape_configs:
      - job_name: 'zarmor'
        static_configs:
          - targets: ['47.129.243.206:8000']
        metrics_path: '/metrics'
        scrape_interval: 30s

Grafana: Import dashboard ID 1860 (Node Exporter Full) hoặc tạo custom.
"""

import time
import logging
from functools import wraps

logger = logging.getLogger("zarmor.monitoring")

try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Summary,
        generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry,
        multiprocess, REGISTRY,
    )
    _PROM_OK = True
except ImportError:
    _PROM_OK = False
    logger.warning("[MONITORING] prometheus-client chưa cài. Chạy: pip install prometheus-client")


# ══════════════════════════════════════════════════════════════════
# METRICS DEFINITIONS
# ══════════════════════════════════════════════════════════════════
if _PROM_OK:
    # Request metrics
    REQUEST_COUNT = Counter(
        "zarmor_http_requests_total",
        "Tổng số HTTP requests",
        ["method", "endpoint", "status_code"]
    )
    REQUEST_LATENCY = Histogram(
        "zarmor_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "endpoint"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    )

    # Heartbeat metrics
    HEARTBEAT_COUNT = Counter(
        "zarmor_heartbeat_total",
        "Tổng số heartbeat từ EA",
        ["result"]  # OK, CACHED, INVALID, EXPIRED, BOUND_ERROR
    )
    HEARTBEAT_LATENCY = Histogram(
        "zarmor_heartbeat_duration_seconds",
        "Heartbeat xử lý latency",
        buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5]
    )

    # License metrics
    LICENSE_ACTIVE = Gauge(
        "zarmor_licenses_active_total",
        "Số license ACTIVE hiện tại"
    )
    LICENSE_EXPIRED = Gauge(
        "zarmor_licenses_expired_total",
        "Số license EXPIRED"
    )
    LICENSE_ONLINE = Gauge(
        "zarmor_traders_online",
        "Số trader đang online (heartbeat trong 5 phút)"
    )

    # DB metrics
    DB_POOL_SIZE = Gauge(
        "zarmor_db_pool_size",
        "DB connection pool size"
    )
    DB_POOL_CHECKED_OUT = Gauge(
        "zarmor_db_pool_checked_out",
        "DB connections đang được dùng"
    )

    # Retry queue metrics
    RETRY_QUEUE_PENDING = Gauge(
        "zarmor_retry_queue_pending",
        "Số webhook jobs đang chờ retry"
    )
    RETRY_QUEUE_DEAD = Gauge(
        "zarmor_retry_queue_dead",
        "Số webhook jobs đã chết (max attempts)"
    )


# ══════════════════════════════════════════════════════════════════
# MIDDLEWARE — tự động track mọi HTTP request
# ══════════════════════════════════════════════════════════════════
def setup_metrics(app):
    """
    Mount /metrics endpoint + add request tracking middleware.

    Gọi sau khi khởi tạo app:
        from monitoring import setup_metrics
        setup_metrics(app)
    """
    if not _PROM_OK:
        logger.warning("[MONITORING] Skip — prometheus-client không khả dụng")
        return

    from fastapi import Request
    from fastapi.responses import Response
    from starlette.middleware.base import BaseHTTPMiddleware

    class _MetricsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            start = time.time()
            # Normalize path để tránh cardinality explosion
            # vd: /api/trade-history/413408816 → /api/trade-history/{account_id}
            path = _normalize_path(request.url.path)

            try:
                response = await call_next(request)
                status   = response.status_code
            except Exception as e:
                status = 500
                raise e
            finally:
                elapsed = time.time() - start
                REQUEST_COUNT.labels(
                    method=request.method, endpoint=path, status_code=str(status)
                ).inc()
                REQUEST_LATENCY.labels(
                    method=request.method, endpoint=path
                ).observe(elapsed)

            return response

    app.add_middleware(_MetricsMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        """Prometheus scrape endpoint."""
        # Cập nhật gauge metrics trước khi trả về
        _refresh_gauges()
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    logger.info("[MONITORING] ✅ /metrics endpoint mounted")


def _normalize_path(path: str) -> str:
    """Chuẩn hóa URL path để tránh tạo quá nhiều label combinations."""
    import re
    # /api/trade-history/413408816 → /api/trade-history/{account_id}
    path = re.sub(r"/api/(trade-history|session-history|sync-history|init-data|ai-analysis)/[^/]+",
                  r"/api/\1/{account_id}", path)
    # /admin/licenses/ZARMOR-XXX/... → /admin/licenses/{key}/...
    path = re.sub(r"/admin/licenses/[^/]+/", "/admin/licenses/{key}/", path)
    # /heartbeat → /heartbeat (giữ nguyên)
    return path


def _refresh_gauges():
    """Cập nhật Gauge metrics từ DB + cache."""
    if not _PROM_OK:
        return
    try:
        from database import SessionLocal, License
        db = SessionLocal()
        try:
            active  = db.query(License).filter(License.status == "ACTIVE").count()
            expired = db.query(License).filter(License.status == "EXPIRED").count()
            LICENSE_ACTIVE.set(active)
            LICENSE_EXPIRED.set(expired)

            # Retry queue stats
            from database import WebhookRetryQueue
            pending = db.query(WebhookRetryQueue).filter(WebhookRetryQueue.status == "PENDING").count()
            dead    = db.query(WebhookRetryQueue).filter(WebhookRetryQueue.status == "DEAD").count()
            RETRY_QUEUE_PENDING.set(pending)
            RETRY_QUEUE_DEAD.set(dead)
        finally:
            db.close()

        # Cache online count
        from cache_service import cache
        LICENSE_ONLINE.set(cache.online_count())

    except Exception as e:
        logger.warning(f"[MONITORING] gauge refresh fail: {e}")


# ══════════════════════════════════════════════════════════════════
# HEARTBEAT TRACKING HELPER
# ══════════════════════════════════════════════════════════════════
def track_heartbeat(result: str, duration: float):
    """
    Gọi từ _ea_heartbeat_handler để track metrics.
    result: "OK" | "CACHED" | "INVALID_KEY" | "EXPIRED" | "NOT_BOUND" | ...
    """
    if not _PROM_OK:
        return
    HEARTBEAT_COUNT.labels(result=result).inc()
    HEARTBEAT_LATENCY.observe(duration)
