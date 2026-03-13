"""
radar/ohlcv_persistent_cache.py
================================
DB-backed persistent cache cho OHLCV indicators.
Solve vấn đề: khi server restart, in-memory cache bị xóa → burst TwelveData
API calls ngay lập tức → hit rate limit (800 req/day free tier).

Integration: thêm 2 dòng vào ohlcv_service.py:
    from .ohlcv_persistent_cache import db_get_cached, db_set_cached
    # Dùng db_get_cached() trước khi gọi TwelveData API
    # Dùng db_set_cached() sau khi nhận response thành công

Luồng priority:
    1. In-memory cache (fastest, ~0ms)
    2. DB cache (fallback sau restart, ~5ms)
    3. TwelveData API (source of truth, ~200-500ms)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("zarmor.radar.ohlcv_cache")

# TTL map khớp với engine.py TTL_BY_TF
_TTL_BY_TF = {"M5": 300, "M15": 600, "H1": 1800}


def db_get_cached(db, asset: str, tf: str) -> Optional[dict]:
    """
    Đọc OHLCV indicators từ DB cache.
    Trả về dict {adx, rsi, atr_pct, ema_slope, source} nếu còn valid,
    None nếu expired hoặc không có.
    """
    try:
        row = db.execute("""
            SELECT adx, rsi, atr_pct, ema_slope, source, fetched_at, expires_at
            FROM ohlcv_cache
            WHERE asset = :asset AND timeframe = :tf
        """, {"asset": asset, "tf": tf}).fetchone()

        if not row:
            return None

        # Kiểm tra TTL
        if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
            logger.debug(f"[OHLCV_CACHE] DB cache expired: {asset}/{tf}")
            return None

        logger.debug(f"[OHLCV_CACHE] DB cache hit: {asset}/{tf}")
        return {
            "adx":       float(row["adx"] or 0),
            "rsi":       float(row["rsi"] or 50),
            "atr_pct":   float(row["atr_pct"] or 0),
            "ema_slope": float(row["ema_slope"] or 0),
            "source":    "cache",  # luôn report là "cache" khi từ DB
            "fetched_at": row["fetched_at"].isoformat() if row["fetched_at"] else None,
        }
    except Exception as e:
        logger.warning(f"[OHLCV_CACHE] DB read error ({asset}/{tf}): {e}")
        return None


def db_set_cached(db, asset: str, tf: str, indicators: dict) -> bool:
    """
    Lưu OHLCV indicators vào DB cache sau khi nhận được từ TwelveData.
    TTL tự động theo timeframe.
    """
    try:
        ttl = _TTL_BY_TF.get(tf, 600)
        db.execute("""
            SELECT upsert_ohlcv_cache(
                :asset, :tf,
                :adx, :rsi, :atr_pct, :ema_slope,
                :source, :ttl
            )
        """, {
            "asset":     asset,
            "tf":        tf,
            "adx":       indicators.get("adx"),
            "rsi":       indicators.get("rsi"),
            "atr_pct":   indicators.get("atr_pct"),
            "ema_slope": indicators.get("ema_slope"),
            "source":    indicators.get("source", "twelvedata"),
            "ttl":       ttl,
        })
        db.commit()
        logger.debug(f"[OHLCV_CACHE] DB write OK: {asset}/{tf} TTL={ttl}s")
        return True
    except Exception as e:
        logger.warning(f"[OHLCV_CACHE] DB write error ({asset}/{tf}): {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return False


def db_invalidate(db, asset: str, tf: str) -> bool:
    """Force invalidate cache entry — dùng khi cần refresh ngay lập tức."""
    try:
        db.execute("""
            UPDATE ohlcv_cache
            SET expires_at = NOW() - INTERVAL '1 second'
            WHERE asset = :asset AND timeframe = :tf
        """, {"asset": asset, "tf": tf})
        db.commit()
        return True
    except Exception as e:
        logger.warning(f"[OHLCV_CACHE] Invalidate error: {e}")
        return False


def db_warm_cache(db) -> dict:
    """
    Warm-up: đọc toàn bộ cache còn valid từ DB vào dict.
    Gọi 1 lần khi server startup để pre-populate in-memory cache.
    Trả về {asset/tf: indicators_dict}
    """
    result = {}
    try:
        rows = db.execute("""
            SELECT asset, timeframe, adx, rsi, atr_pct, ema_slope, source
            FROM ohlcv_cache
            WHERE expires_at > NOW()
        """).fetchall()

        for row in rows:
            key = f"{row['asset']}/{row['timeframe']}"
            result[key] = {
                "adx":       float(row["adx"] or 0),
                "rsi":       float(row["rsi"] or 50),
                "atr_pct":   float(row["atr_pct"] or 0),
                "ema_slope": float(row["ema_slope"] or 0),
                "source":    "cache",
            }

        logger.info(f"[OHLCV_CACHE] Warm-up: {len(result)} entries loaded from DB")
    except Exception as e:
        logger.warning(f"[OHLCV_CACHE] Warm-up error: {e}")

    return result
