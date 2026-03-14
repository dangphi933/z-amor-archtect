"""
services/market-data-service/app/collectors/candle_collector.py
=================================================================
Market Data Collector — the ONLY component allowed to call TwelveData.

Responsibility:
  1. Fetch raw OHLCV from TwelveData (or Polygon/AlphaVantage fallback)
  2. Compute indicators: ADX, ATR, RSI, EMA slope
  3. Normalize symbol formats
  4. Write to Redis candle cache (candle:{SYMBOL}:{TF})
  5. Cache publishes candle-close event → triggers Radar Workers

Radar Workers never call this module or any external API.
They only read from Redis candle cache.

Collection schedule (driven by candle close times):
  M5  → every 5 minutes
  M15 → every 15 minutes
  H1  → every 60 minutes

Each collection run covers all active symbols for that timeframe.
"""

import os
import time
import asyncio
import logging
import httpx
from typing import Optional

from shared.libs.universe.symbol_universe import active_symbols, get_twelvedata_symbol
from shared.libs.cache.candle_cache import write_indicators, write_raw_ohlcv

logger = logging.getLogger("zarmor.market_data.collector")

API_KEY     = os.getenv("TWELVEDATA_API_KEY", "")
BASE_URL    = "https://api.twelvedata.com"
REQUEST_TTL = 8.0  # seconds per HTTP request
RATE_DELAY  = 0.8  # seconds between TwelveData requests (rate limit)

# Provider fallback order
PROVIDERS = ["twelvedata"]   # future: ["twelvedata", "polygon", "alphavantage"]


# ══════════════════════════════════════════════════════════════════
# MAIN COLLECTION ENTRY POINT
# ══════════════════════════════════════════════════════════════════

async def collect_all(timeframe: str) -> dict:
    """
    Fetch indicators for ALL active symbols at a given timeframe.
    Called by the scheduler at each candle close.

    Returns: {symbol: {"ok": bool, "source": str}, ...}
    """
    symbols = active_symbols()
    results = {}
    logger.info(f"[COLLECTOR] Starting collection: {len(symbols)} symbols × {timeframe}")

    for sym_config in symbols:
        symbol = sym_config["symbol"]
        if timeframe not in sym_config.get("tf", ["H1"]):
            continue  # this symbol doesn't use this timeframe
        try:
            result = await collect_symbol(symbol, timeframe)
            results[symbol] = result
            await asyncio.sleep(RATE_DELAY)  # respect API rate limits
        except Exception as e:
            logger.error(f"[COLLECTOR] Failed {symbol}/{timeframe}: {e}")
            results[symbol] = {"ok": False, "error": str(e)}

    ok_count = sum(1 for r in results.values() if r.get("ok"))
    logger.info(f"[COLLECTOR] Collection complete: {ok_count}/{len(results)} OK")
    return results


async def collect_symbol(symbol: str, timeframe: str) -> dict:
    """
    Fetch + compute indicators for one symbol.
    Writes to candle cache.
    """
    if not API_KEY:
        # Dev mode: write synthetic indicators so workers still get data
        _write_synthetic(symbol, timeframe)
        return {"ok": True, "source": "synthetic"}

    td_symbol = get_twelvedata_symbol(symbol)
    indicators = await _fetch_from_twelvedata(td_symbol, timeframe)

    if not indicators:
        logger.warning(f"[COLLECTOR] No data from provider for {symbol}/{timeframe}")
        return {"ok": False, "source": "none"}

    # Write to Redis — this also publishes stream:candle-events
    ok = write_indicators(symbol, timeframe, indicators)
    if ok:
        logger.debug(f"[COLLECTOR] {symbol}/{timeframe} cached: adx={indicators.get('adx',0):.1f} rsi={indicators.get('rsi',50):.1f}")
        return {"ok": True, "source": "twelvedata", "adx": indicators.get("adx")}

    return {"ok": False, "source": "write_failed"}


# ══════════════════════════════════════════════════════════════════
# TWELVEDATA FETCHER
# ══════════════════════════════════════════════════════════════════

async def _fetch_from_twelvedata(td_symbol: str, timeframe: str) -> Optional[dict]:
    """
    Fetch ADX, ATR, RSI, EMA8, EMA21 from TwelveData.
    Returns normalized indicators dict or None on failure.
    """
    tf_map  = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h", "D1": "1day"}
    interval = tf_map.get(timeframe, "1h")
    indicators = {}

    async with httpx.AsyncClient(timeout=REQUEST_TTL) as client:
        # ── ADX ──────────────────────────────────────────────────
        try:
            r = await client.get(f"{BASE_URL}/adx", params={
                "symbol": td_symbol, "interval": interval,
                "time_period": 14, "outputsize": 2, "apikey": API_KEY,
            })
            if r.status_code == 200 and r.json().get("values"):
                vals = r.json()["values"]
                indicators["adx"] = float(vals[0].get("adx", 0))
                # compute ADX slope from prev bar
                if len(vals) > 1:
                    indicators["adx_prev"] = float(vals[1].get("adx", 0))
        except Exception as e:
            logger.debug(f"[COLLECTOR] ADX failed {td_symbol}: {e}")
        await asyncio.sleep(0.2)

        # ── ATR ──────────────────────────────────────────────────
        try:
            r = await client.get(f"{BASE_URL}/atr", params={
                "symbol": td_symbol, "interval": interval,
                "time_period": 14, "outputsize": 1, "apikey": API_KEY,
            })
            if r.status_code == 200 and r.json().get("values"):
                atr_abs = float(r.json()["values"][0].get("atr", 0))
                # Fetch price for ATR% calculation
                price_r = await client.get(f"{BASE_URL}/price", params={
                    "symbol": td_symbol, "apikey": API_KEY,
                })
                if price_r.status_code == 200:
                    price = float(price_r.json().get("price", 100))
                    indicators["atr_abs"] = atr_abs
                    indicators["atr_pct"] = (atr_abs / price) * 100 if price > 0 else atr_abs
                else:
                    indicators["atr_pct"] = atr_abs / 100   # rough fallback
        except Exception as e:
            logger.debug(f"[COLLECTOR] ATR failed {td_symbol}: {e}")
        await asyncio.sleep(0.2)

        # ── RSI ──────────────────────────────────────────────────
        try:
            r = await client.get(f"{BASE_URL}/rsi", params={
                "symbol": td_symbol, "interval": interval,
                "time_period": 14, "outputsize": 1, "apikey": API_KEY,
            })
            if r.status_code == 200 and r.json().get("values"):
                indicators["rsi"] = float(r.json()["values"][0].get("rsi", 50))
        except Exception as e:
            logger.debug(f"[COLLECTOR] RSI failed {td_symbol}: {e}")
        await asyncio.sleep(0.2)

        # ── EMA 8 + EMA 21 (for slope) ───────────────────────────
        for period, key in [(8, "ema_fast"), (21, "ema_slow")]:
            try:
                r = await client.get(f"{BASE_URL}/ema", params={
                    "symbol": td_symbol, "interval": interval,
                    "time_period": period, "outputsize": 1, "apikey": API_KEY,
                })
                if r.status_code == 200 and r.json().get("values"):
                    indicators[key] = float(r.json()["values"][0].get("ema", 0))
            except Exception as e:
                logger.debug(f"[COLLECTOR] EMA{period} failed {td_symbol}: {e}")
            await asyncio.sleep(0.15)

    return indicators if len(indicators) >= 2 else None


# ══════════════════════════════════════════════════════════════════
# SYNTHETIC DATA (dev/test when no API key)
# ══════════════════════════════════════════════════════════════════

def _write_synthetic(symbol: str, tf: str):
    """Write plausible synthetic indicators for dev/test mode."""
    import random
    indicators = {
        "adx":      20 + random.uniform(-5, 15),
        "atr_pct":  0.4 + random.uniform(-0.1, 0.3),
        "rsi":      40 + random.uniform(-15, 30),
        "ema_fast": 1800 + random.uniform(-50, 50),
        "ema_slow": 1795 + random.uniform(-40, 40),
        "source":   "synthetic",
    }
    write_indicators(symbol, tf, indicators)
