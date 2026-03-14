"""
shared/libs/universe/symbol_universe.py
=========================================
Symbol Universe Governance — controls which symbols Radar workers scan.

3 tiers:
  Tier 1 — Core (always active):    GOLD, EURUSD, BTC, NASDAQ
  Tier 2 — Secondary (conditional): GBPUSD, USDJPY, ETH, SP500, OIL
  Tier 3 — Experimental (disabled): user-requested symbols

Radar workers read active_symbols() before each scan cycle.
Market Data Collector also reads this to know what to fetch.

State stored in Redis: universe:active  →  JSON list of symbol configs
Falls back to TIER_1 defaults if Redis unavailable.
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger("zarmor.universe")

# ── Static tier definitions ────────────────────────────────────────
TIER_1 = [
    {"symbol": "GOLD",   "tf": ["M5","M15","H1"], "tier": 1, "twelvedata": "XAU/USD",  "typical_atr": 0.55},
    {"symbol": "EURUSD", "tf": ["M5","M15","H1"], "tier": 1, "twelvedata": "EUR/USD",  "typical_atr": 0.30},
    {"symbol": "BTC",    "tf": ["M15","H1"],       "tier": 1, "twelvedata": "BTC/USD",  "typical_atr": 2.10},
    {"symbol": "NASDAQ", "tf": ["M15","H1"],       "tier": 1, "twelvedata": "QQQ",      "typical_atr": 0.80},
]

TIER_2 = [
    {"symbol": "GBPUSD", "tf": ["H1"],       "tier": 2, "twelvedata": "GBP/USD", "typical_atr": 0.38},
    {"symbol": "USDJPY", "tf": ["H1"],       "tier": 2, "twelvedata": "USD/JPY", "typical_atr": 0.45},
    {"symbol": "ETH",    "tf": ["H1"],       "tier": 2, "twelvedata": "ETH/USD", "typical_atr": 3.20},
    {"symbol": "SP500",  "tf": ["H1"],       "tier": 2, "twelvedata": "SPY",     "typical_atr": 0.70},
    {"symbol": "OIL",    "tf": ["H1"],       "tier": 2, "twelvedata": "CL1!",    "typical_atr": 1.20},
]

TIER_3: list = []  # Disabled by default

MAX_ACTIVE_SYMBOLS = int(os.getenv("MAX_ACTIVE_SYMBOLS", "20"))
REDIS_KEY_ACTIVE   = "universe:active"
REDIS_KEY_OVERRIDE = "universe:override"   # admin can force enable/disable


def _get_redis():
    try:
        from shared.libs.cache.redis_store import cache_get, cache_set
        return cache_get, cache_set
    except Exception:
        return None, None


def active_symbols() -> list[dict]:
    """
    Return list of active symbol configs for this scan cycle.
    Reads from Redis override first, falls back to Tier 1 + enabled Tier 2.
    Each entry: {symbol, tf, tier, twelvedata, typical_atr}
    """
    cache_get, _ = _get_redis()
    if cache_get:
        try:
            override = cache_get(REDIS_KEY_OVERRIDE)
            if override and isinstance(override, list):
                return override[:MAX_ACTIVE_SYMBOLS]
            cached = cache_get(REDIS_KEY_ACTIVE)
            if cached and isinstance(cached, list):
                return cached[:MAX_ACTIVE_SYMBOLS]
        except Exception as e:
            logger.debug(f"[UNIVERSE] Redis read failed: {e}")

    # Default: Tier 1 always active
    return TIER_1[:MAX_ACTIVE_SYMBOLS]


def active_scan_jobs() -> list[tuple[str, str]]:
    """
    Flatten active symbols × timeframes into (symbol, tf) scan jobs.
    Used by workers to know what to compute.
    Example: [("GOLD","M5"), ("GOLD","M15"), ("GOLD","H1"), ("EURUSD","M5"), ...]
    """
    jobs = []
    for s in active_symbols():
        for tf in s.get("tf", ["H1"]):
            jobs.append((s["symbol"], tf))
    return jobs


def enable_tier2():
    """Enable Tier 2 symbols (called by admin or dynamic activation logic)."""
    _, cache_set = _get_redis()
    active = (TIER_1 + TIER_2)[:MAX_ACTIVE_SYMBOLS]
    if cache_set:
        try:
            cache_set(REDIS_KEY_ACTIVE, active, ttl=0)
            logger.info(f"[UNIVERSE] Tier 2 enabled: {len(active)} symbols active")
        except Exception as e:
            logger.error(f"[UNIVERSE] enable_tier2 failed: {e}")


def disable_symbol(symbol: str):
    """Dynamically disable a symbol (e.g. due to compute overload)."""
    _, cache_set = _get_redis()
    current = active_symbols()
    updated = [s for s in current if s["symbol"] != symbol]
    if cache_set:
        try:
            cache_set(REDIS_KEY_ACTIVE, updated, ttl=0)
            logger.info(f"[UNIVERSE] Symbol {symbol} disabled. Active: {len(updated)}")
        except Exception as e:
            logger.error(f"[UNIVERSE] disable_symbol failed: {e}")


def get_twelvedata_symbol(symbol: str) -> Optional[str]:
    """Map internal symbol name → TwelveData API symbol."""
    all_symbols = TIER_1 + TIER_2 + TIER_3
    for s in all_symbols:
        if s["symbol"] == symbol:
            return s.get("twelvedata", symbol)
    return symbol


def get_typical_atr(symbol: str) -> float:
    """Get typical ATR for a symbol (used by radar engine for normalization)."""
    all_symbols = TIER_1 + TIER_2 + TIER_3
    for s in all_symbols:
        if s["symbol"] == symbol:
            return s.get("typical_atr", 1.0)
    return 1.0


def universe_status() -> dict:
    """Return current universe status for monitoring."""
    active = active_symbols()
    jobs   = active_scan_jobs()
    return {
        "active_symbols":   len(active),
        "total_scan_jobs":  len(jobs),
        "max_allowed":      MAX_ACTIVE_SYMBOLS,
        "tiers_enabled":    sorted(set(s["tier"] for s in active)),
        "symbols":          [s["symbol"] for s in active],
        "scan_jobs_sample": jobs[:10],
    }
