"""
radar-service/app/main.py  (v3 — event-driven worker architecture)
====================================================================
ARCHITECTURE CHANGE v3:
  - Removed: POST /radar/scan (was synchronous, API-triggered)
  - Removed: direct TwelveData calls in this service
  - Added:   Radar Worker threads consuming stream:candle-events
  - Added:   Read-only API endpoints only

On startup:
  1. Seed State Machine from DB to Redis
  2. Start N radar worker threads (configurable via RADAR_WORKERS env)

Workers run in background:
  - Consume stream:candle-events from Market Data Service
  - Run 5-layer pipeline per candle-close event
  - Write radar_map to Redis
  - Publish stream:radar-updates

API endpoints are read-only — they serve pre-computed results from Redis.
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from .routers.radar_router import router as radar_router
from .core.database import engine, Base

N_WORKERS = int(os.getenv("RADAR_WORKERS", "2"))
_worker_shutdowns = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_shutdowns
    Base.metadata.create_all(bind=engine)

    # Seed Redis State Machine from DB (so workers get last known state)
    try:
        from .intelligence.engine import seed_state_cache
        from .core.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            rows = db.execute(text(
                "SELECT symbol, market_state, bars_in_state, prev_state FROM radar_market_state"
            )).fetchall()
            for row in rows:
                seed_state_cache(row.symbol, row.market_state, row.bars_in_state, row.prev_state)
            print(f"[RADAR-SERVICE] Seeded {len(rows)} state machine entries from DB", flush=True)
        except Exception as e:
            print(f"[RADAR-SERVICE] State machine seed warning: {e}", flush=True)
        finally:
            db.close()
    except Exception as e:
        print(f"[RADAR-SERVICE] Startup DB warning: {e}", flush=True)

    # Start radar worker threads
    try:
        from .workers.radar_worker import start_worker_threads
        _worker_shutdowns = start_worker_threads(n_workers=N_WORKERS)
        print(f"[RADAR-SERVICE] {N_WORKERS} radar worker(s) started", flush=True)
    except Exception as e:
        print(f"[RADAR-SERVICE] Worker start warning: {e}", flush=True)

    print(f"[RADAR-SERVICE] Ready. API: read-only. Workers: {N_WORKERS}", flush=True)
    yield

    # Graceful shutdown
    for s in _worker_shutdowns:
        s.set()
    print("[RADAR-SERVICE] Shutting down", flush=True)


app = FastAPI(
    title="Z-Armor Radar Service",
    version="3.0.0",
    description=(
        "Radar Intelligence Stack — event-driven, worker-based. "
        "Triggered by candle-close events. API is read-only."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").strip("[]\"").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(radar_router, prefix="/radar")


@app.get("/health")
def health():
    from shared.libs.universe.symbol_universe import universe_status
    from shared.libs.cache.redis_store import cache_get
    portfolio = cache_get("radar_portfolio_regime") or {}
    return {
        "status":   "ok",
        "service":  "radar-service",
        "workers":  N_WORKERS,
        "universe": universe_status().get("active_symbols", 0),
        "portfolio_regime": portfolio.get("portfolio_regime", "unknown"),
    }
