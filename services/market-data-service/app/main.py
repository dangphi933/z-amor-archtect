"""
services/market-data-service/app/main.py
==========================================
Market Data Service — Port 8006.

Responsibilities:
  1. Schedule candle collection at each bar close (M5/M15/H1)
  2. Run candle_collector for all active symbols
  3. Candle cache write → triggers stream:candle-events → Radar Workers

This service is the ONLY component that calls external market data APIs.
All other services read from Redis candle cache.

Endpoints (read-only status):
  GET /health
  GET /market-data/status    — cache status + last collection times
  GET /market-data/universe  — active symbol universe
  POST /market-data/collect  — manual trigger (admin/debug only)
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .collectors.candle_collector import collect_all
from .routers.status_router import router as status_router

logger = logging.getLogger("zarmor.market_data")

# ── Collection schedule ────────────────────────────────────────────
# Tracks last run time per timeframe
_last_run: dict = {}
_running = False

TIMEFRAME_INTERVALS = {
    "M5":  5  * 60,
    "M15": 15 * 60,
    "H1":  60 * 60,
}


async def _collection_loop():
    """
    Background scheduler: triggers collection when a candle closes.
    Checks every 30 seconds if a new candle has closed for any TF.
    """
    global _last_run, _running
    _running = True
    logger.info("[MARKET-DATA] Collection scheduler started")

    while _running:
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()

        for tf, interval in TIMEFRAME_INTERVALS.items():
            # Align to candle close boundaries (e.g. M5 at :00, :05, :10 ...)
            last = _last_run.get(tf, 0)
            # Check if a new candle has closed since last run
            current_candle_close = (now_ts // interval) * interval
            if current_candle_close > last:
                _last_run[tf] = current_candle_close
                logger.info(f"[MARKET-DATA] Candle close detected: {tf} at {now.strftime('%H:%M:%S')}")
                asyncio.create_task(_run_collection(tf))

        await asyncio.sleep(30)   # check every 30s — fine grain enough


async def _run_collection(timeframe: str):
    """Run collection for all active symbols for a given timeframe."""
    try:
        results = await collect_all(timeframe)
        ok = sum(1 for r in results.values() if r.get("ok"))
        logger.info(f"[MARKET-DATA] {timeframe} collection done: {ok}/{len(results)} symbols OK")
    except Exception as e:
        logger.error(f"[MARKET-DATA] Collection error for {timeframe}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Immediate warm-up on startup: collect H1 for all active symbols
    logger.info("[MARKET-DATA] Service starting — warming up H1 cache...")
    asyncio.create_task(_run_collection("H1"))

    # Start background scheduler
    task = asyncio.create_task(_collection_loop())

    yield

    global _running
    _running = False
    task.cancel()
    logger.info("[MARKET-DATA] Service shutting down")


app = FastAPI(
    title="Z-Armor Market Data Service",
    version="1.0.0",
    description="Candle data collection, normalization, Redis caching. The only service calling external APIs.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").strip("[]\"").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(status_router, prefix="/market-data")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "market-data-service",
        "scheduler_running": _running,
        "last_runs": {
            tf: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            for tf, ts in _last_run.items()
        },
    }
