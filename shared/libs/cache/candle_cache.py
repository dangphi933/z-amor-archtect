"""
shared/libs/cache/candle_cache.py
====================================
Redis Candle Cache — market data isolation layer.

Radar workers NEVER call external APIs directly.
They always read from this cache.

Market Data Collector writes here.
Radar workers read from here.

Redis key schema:
  candle:{SYMBOL}:{TF}          →  JSON indicators dict
  candle_raw:{SYMBOL}:{TF}      →  JSON list of raw OHLCV bars
  candle_ts:{SYMBOL}:{TF}       →  last update timestamp

TTL by timeframe:
  M5  → 6 minutes   (1.2× bar duration, allows late arrival)
  M15 → 18 minutes
  H1  → 75 minutes
"""

import json
import time
import logging
from typing import Optional

logger = logging.getLogger("zarmor.candle_cache")

TTL_BY_TF = {
    "M1":  90,
    "M5":  360,
    "M15": 1080,
    "M30": 2160,
    "H1":  4500,
    "H4":  18000,
    "D1":  90000,
}

KEY_PREFIX  = "candle"
RAW_PREFIX  = "candle_raw"
TS_PREFIX   = "candle_ts"
EVENT_STREAM = "stream:candle-events"   # published after each candle write


def _redis():
    try:
        from shared.libs.cache.redis_store import _get_redis
        return _get_redis()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
# WRITE (Market Data Collector calls these)
# ══════════════════════════════════════════════════════════════════

def write_indicators(symbol: str, tf: str, indicators: dict) -> bool:
    """
    Write computed indicators to Redis.
    Called by Market Data Collector after computing ADX/ATR/RSI/EMA from raw OHLCV.
    Also publishes candle-close event to stream:candle-events.
    """
    r = _redis()
    if not r:
        return False
    ttl = TTL_BY_TF.get(tf, 1800)
    key = f"{KEY_PREFIX}:{symbol}:{tf}"
    ts_key = f"{TS_PREFIX}:{symbol}:{tf}"
    try:
        r.setex(key, ttl, json.dumps(indicators))
        r.setex(ts_key, ttl + 60, str(time.time()))

        # Publish candle-close event → triggers Radar Workers
        r.xadd(EVENT_STREAM, {
            "symbol":    symbol,
            "tf":        tf,
            "timestamp": str(time.time()),
            "score_hint": str(indicators.get("rsi", 50)),  # quick pre-filter
        }, maxlen=10000, approximate=True)

        logger.debug(f"[CANDLE_CACHE] Written {symbol}:{tf}")
        return True
    except Exception as e:
        logger.error(f"[CANDLE_CACHE] Write failed {symbol}:{tf}: {e}")
        return False


def write_raw_ohlcv(symbol: str, tf: str, bars: list) -> bool:
    """Write raw OHLCV bars (for timeseries storage backup)."""
    r = _redis()
    if not r:
        return False
    ttl = TTL_BY_TF.get(tf, 1800) * 10   # keep raw longer
    key = f"{RAW_PREFIX}:{symbol}:{tf}"
    try:
        r.setex(key, ttl, json.dumps(bars))
        return True
    except Exception as e:
        logger.error(f"[CANDLE_CACHE] Raw write failed {symbol}:{tf}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# READ (Radar Workers call these — never external API)
# ══════════════════════════════════════════════════════════════════

def read_indicators(symbol: str, tf: str) -> Optional[dict]:
    """
    Read indicators from Redis candle cache.
    Returns None if cache miss (radar falls back to static profile).
    Radar workers ONLY call this — never external APIs.
    """
    r = _redis()
    if not r:
        return None
    key = f"{KEY_PREFIX}:{symbol}:{tf}"
    try:
        raw = r.get(key)
        if raw:
            data = json.loads(raw)
            data["source"] = "candle_cache"
            return data
    except Exception as e:
        logger.debug(f"[CANDLE_CACHE] Read failed {symbol}:{tf}: {e}")
    return None


def read_raw_ohlcv(symbol: str, tf: str) -> Optional[list]:
    """Read raw OHLCV bars from cache."""
    r = _redis()
    if not r:
        return None
    key = f"{RAW_PREFIX}:{symbol}:{tf}"
    try:
        raw = r.get(key)
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.debug(f"[CANDLE_CACHE] Raw read failed {symbol}:{tf}: {e}")
    return None


def last_update_ts(symbol: str, tf: str) -> Optional[float]:
    """Return timestamp of last candle write. None if never written."""
    r = _redis()
    if not r:
        return None
    key = f"{TS_PREFIX}:{symbol}:{tf}"
    try:
        val = r.get(key)
        return float(val) if val else None
    except Exception:
        return None


def is_fresh(symbol: str, tf: str) -> bool:
    """True if candle data is fresh (not expired)."""
    r = _redis()
    if not r:
        return False
    key = f"{KEY_PREFIX}:{symbol}:{tf}"
    try:
        return bool(r.exists(key))
    except Exception:
        return False


def cache_status_all() -> dict:
    """Return freshness status for all cached symbols. Used by /health endpoint."""
    r = _redis()
    if not r:
        return {"redis": "unavailable"}
    try:
        keys = list(r.scan_iter(f"{KEY_PREFIX}:*"))
        entries = []
        for k in keys:
            parts = k.split(":")
            if len(parts) == 3:
                _, sym, tf = parts
                ttl = r.ttl(k)
                entries.append({"symbol": sym, "tf": tf, "ttl_remaining": ttl})
        return {"cached_entries": len(entries), "entries": entries}
    except Exception as e:
        return {"error": str(e)}
