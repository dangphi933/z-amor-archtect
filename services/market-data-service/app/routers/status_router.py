"""
services/market-data-service/app/routers/status_router.py
"""
from fastapi import APIRouter
from shared.libs.cache.candle_cache import cache_status_all
from shared.libs.universe.symbol_universe import universe_status

router = APIRouter(tags=["Market Data"])


@router.get("/status")
def market_data_status():
    return {
        "candle_cache": cache_status_all(),
        "symbol_universe": universe_status(),
    }


@router.get("/universe")
def symbol_universe():
    return universe_status()
