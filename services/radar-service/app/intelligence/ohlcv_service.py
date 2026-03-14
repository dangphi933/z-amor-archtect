"""
app/intelligence/ohlcv_service.py  (v3 — Redis-only read)
===========================================================
ARCHITECTURE CHANGE v3:
  This module NO LONGER calls TwelveData or any external API.
  It is a thin adapter that reads from the Redis candle cache.

  Market Data Service writes to Redis.
  Radar engine reads through this module.

  If cache miss: return {} with source="cache_miss"
  Radar engine falls back to static asset profiles in that case.
"""

import logging
from typing import Optional
from shared.libs.cache.candle_cache import read_indicators, cache_status_all

logger = logging.getLogger("zarmor.radar.ohlcv")


async def get_live_indicators(asset: str, timeframe: str) -> dict:
    """
    Read indicators from Redis candle cache.
    Returns dict with: adx, atr_pct, rsi, ema_fast, ema_slow, source
    source = "candle_cache" if fresh, "cache_miss" if not available
    """
    data = read_indicators(asset, timeframe)
    if data:
        return data
    # Cache miss — radar will use static asset profiles as fallback
    logger.debug(f"[OHLCV] Cache miss for {asset}/{timeframe} — falling back to static profile")
    return {"source": "cache_miss"}


async def warm_cache():
    """No-op in v3. Market Data Service handles cache warming."""
    logger.info("[OHLCV] Cache warming is handled by market-data-service — no action needed here")


def cache_status() -> dict:
    """Proxy to candle cache status."""
    return cache_status_all()
