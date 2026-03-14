"""
app/routers/radar_router.py  (v3 — read-only API)
===================================================
ARCHITECTURE CHANGE v3:
  POST /radar/scan  → REMOVED
  Radar is now triggered by candle-close events via stream:candle-events.
  Workers compute and write to Redis. API only reads.

Read-only endpoints:
  GET /radar/latest           — latest radar_map for engine-service heartbeat
  GET /radar/symbol/{symbol}  — single symbol result
  GET /radar/portfolio        — portfolio_regime aggregate
  GET /radar/feed             — all symbols current scores (dashboard)
  GET /radar/history          — scan history from DB
  GET /radar/universe         — active symbol universe status
  GET /radar/cache-status     — candle cache + worker health
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from ..core.database import SessionLocal
from shared.libs.cache.candle_cache import cache_status_all
from shared.libs.cache.redis_store import cache_get
from shared.libs.universe.symbol_universe import universe_status, active_scan_jobs

logger = logging.getLogger("zarmor.radar.router")
router = APIRouter(tags=["Radar"])

RADAR_MAP_KEY   = "radar_map:{symbol}:{tf}"
PORTFOLIO_KEY   = "radar_portfolio_regime"


def _read_radar_map(symbol: str, tf: str) -> Optional[dict]:
    """Read radar_map entry from Redis. None if not computed yet."""
    key = RADAR_MAP_KEY.format(symbol=symbol.upper(), tf=tf.upper())
    return cache_get(key)


def _symbol_map(mt5_symbol: str) -> str:
    """Map MT5 symbol names to internal names."""
    mapping = {
        "XAUUSD": "GOLD", "XAUUSDM": "GOLD", "XAU/USD": "GOLD",
        "EURUSDM": "EURUSD", "EUR/USD": "EURUSD",
        "BTCUSD": "BTC",  "BTCUSDM": "BTC",
        "NAS100": "NASDAQ", "NAS100M": "NASDAQ",
    }
    return mapping.get(mt5_symbol.upper(), mt5_symbol.upper())


# ══════════════════════════════════════════════════════════════════
# GET /radar/latest  — primary read endpoint for engine-service
# ══════════════════════════════════════════════════════════════════

@router.get("/latest")
async def radar_latest(
    symbols: Optional[str] = Query(None, description="Comma-separated MT5 symbols"),
    tf:      str            = Query("H1"),
):
    """
    Latest radar_map — read from Redis (computed by workers).
    engine-service calls this in heartbeat handler.
    Returns empty dict for symbols not yet computed (worker still warming up).
    """
    tf = tf.upper()
    if symbols:
        requested = [_symbol_map(s.strip()) for s in symbols.split(",")]
    else:
        requested = [job[0] for job in active_scan_jobs() if job[1] == tf]

    result = {}
    for sym in requested:
        entry = _read_radar_map(sym, tf)
        if entry:
            result[f"{sym}:{tf}"] = entry

    portfolio = cache_get(PORTFOLIO_KEY) or {}

    return {
        "radar_map":        result,
        "portfolio_regime": portfolio.get("portfolio_regime", "RISK_MIXED"),
        "avg_score":        portfolio.get("avg_score", 50),
        "symbol_count":     len(result),
        "timestamp_utc":    datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════
# GET /radar/symbol/{symbol}
# ══════════════════════════════════════════════════════════════════

@router.get("/symbol/{symbol}")
async def radar_symbol(symbol: str, tf: str = Query("H1")):
    """Single symbol result. Used by dashboard and debug."""
    internal = _symbol_map(symbol)
    entry = _read_radar_map(internal, tf.upper())
    if not entry:
        raise HTTPException(404, f"No radar data for {symbol}/{tf}. Worker may still be computing.")
    return entry


# ══════════════════════════════════════════════════════════════════
# GET /radar/portfolio
# ══════════════════════════════════════════════════════════════════

@router.get("/portfolio")
async def radar_portfolio():
    """Portfolio-level regime aggregate (Layer 5 output)."""
    portfolio = cache_get(PORTFOLIO_KEY)
    if not portfolio:
        return {
            "portfolio_regime": "RISK_MIXED",
            "avg_score": 50,
            "symbol_count": 0,
            "note": "Workers starting up — no data yet",
        }
    return portfolio


# ══════════════════════════════════════════════════════════════════
# GET /radar/feed  — dashboard widget
# ══════════════════════════════════════════════════════════════════

@router.get("/feed")
async def radar_feed(tf: str = Query("H1")):
    """All active symbols current scores. Refresh every 30s for dashboard."""
    tf   = tf.upper()
    jobs = active_scan_jobs()
    feed = []
    for sym, job_tf in jobs:
        if job_tf != tf:
            continue
        entry = _read_radar_map(sym, tf)
        if entry:
            feed.append({
                "symbol":       sym,
                "tf":           tf,
                "score":        entry.get("score"),
                "regime":       entry.get("regime"),
                "gate":         entry.get("gate"),
                "market_state": entry.get("market_state"),
                "computed_at":  entry.get("computed_at"),
            })

    return {
        "feed":          feed,
        "count":         len(feed),
        "timeframe":     tf,
        "portfolio":     (cache_get(PORTFOLIO_KEY) or {}).get("portfolio_regime", "UNKNOWN"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════
# GET /radar/history
# ══════════════════════════════════════════════════════════════════

@router.get("/history")
async def radar_history(
    symbol: Optional[str] = Query(None),
    tf:     str           = Query("H1"),
    limit:  int           = Query(50, le=500),
):
    """Historical scan results from DB. Used for chart and analytics."""
    db = SessionLocal()
    try:
        query = """
            SELECT scan_id, asset, timeframe, score, regime, label,
                   market_state, transition_type, session, scanned_at
            FROM radar_scans
            WHERE 1=1
        """
        params: dict = {"limit": limit}
        if symbol:
            query += " AND asset = :asset"
            params["asset"] = _symbol_map(symbol)
        if tf:
            query += " AND timeframe = :tf"
            params["tf"] = tf.upper()
        query += " ORDER BY scanned_at DESC LIMIT :limit"

        rows = db.execute(text(query), params).fetchall()
        return {
            "history": [dict(r._mapping) for r in rows],
            "count":   len(rows),
        }
    except Exception as e:
        logger.error(f"[RADAR] History query failed: {e}")
        return {"history": [], "count": 0}
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════
# GET /radar/universe
# ══════════════════════════════════════════════════════════════════

@router.get("/universe")
async def radar_universe():
    """Active symbol universe status."""
    return universe_status()


# ══════════════════════════════════════════════════════════════════
# GET /radar/cache-status
# ══════════════════════════════════════════════════════════════════

@router.get("/cache-status")
async def radar_cache_status():
    """Candle cache health + radar_map freshness."""
    return {
        "candle_cache":  cache_status_all(),
        "portfolio":     cache_get(PORTFOLIO_KEY),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
