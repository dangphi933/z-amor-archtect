"""
radar/ohlcv_service.py — Phase 1 Live OHLCV Feed
=================================================
Cung cấp ATR, ADX, RSI, EMA slope thật từ TwelveData free tier.
Fallback hoàn toàn về static profiles nếu API không có/lỗi.

Setup:
  pip install requests
  Thêm vào .env:  TWELVEDATA_KEY=your_key_here
  Lấy key free:   https://twelvedata.com/register  (800 req/ngày free)

source field:
  "live"     → từ API thật, vừa fetch
  "cache"    → từ in-memory cache (còn hạn)
  "fallback" → API không có key / lỗi / timeout → dùng static profile
"""

import os
import time
import logging
import json
from typing import Optional

logger = logging.getLogger("zarmor.ohlcv")

API_KEY      = os.environ.get("TWELVEDATA_KEY", "")
BASE_URL     = "https://api.twelvedata.com"
REQUEST_TIMEOUT = 5  # giây

# Symbol map: Z-Armor name → TwelveData symbol
ASSET_SYMBOL = {
    "GOLD":   "XAU/USD",
    "EURUSD": "EUR/USD",
    "BTC":    "BTC/USD",
    "NASDAQ": "QQQ",        # NASDAQ proxy ETF — free tier support
}

# TwelveData interval strings
TF_INTERVAL = {
    "M5":  "5min",
    "M15": "15min",
    "H1":  "1h",
}

# Cache TTL (giây) theo timeframe
CACHE_TTL = {"M5": 300, "M15": 600, "H1": 1800}

# Static fallback — dùng khi không có API key hoặc lỗi
FALLBACK = {
    "GOLD":   {"atr_pct": 0.55, "adx": 26, "rsi": 52, "ema_slope": 0.01},
    "EURUSD": {"atr_pct": 0.30, "adx": 20, "rsi": 50, "ema_slope": 0.00},
    "BTC":    {"atr_pct": 2.10, "adx": 32, "rsi": 54, "ema_slope": 0.04},
    "NASDAQ": {"atr_pct": 0.80, "adx": 24, "rsi": 51, "ema_slope": 0.01},
}

# In-memory cache: "ASSET:TF" → {"data": {...}, "expires": float}
_cache: dict = {}

# ── Global rate limiter: TwelveData free = 8 credits/phút ────────────────────
_api_call_timestamps: list = []  # timestamps of recent API calls
MAX_CALLS_PER_MINUTE = 6         # giữ ở 6 để có buffer (limit là 8)

def _can_call_api() -> bool:
    """Kiểm tra có được phép gọi API không (rate limit guard)."""
    now = time.time()
    cutoff = now - 60.0
    # Xóa timestamps cũ hơn 1 phút
    _api_call_timestamps[:] = [t for t in _api_call_timestamps if t > cutoff]
    return len(_api_call_timestamps) < MAX_CALLS_PER_MINUTE

def _record_api_call():
    """Ghi lại 1 API call."""
    _api_call_timestamps.append(time.time())


# ─── Cache helpers ────────────────────────────────────────────────────────────

def _get_cached(asset: str, tf: str) -> Optional[dict]:
    entry = _cache.get(f"{asset}:{tf}")
    if entry and time.time() < entry["expires"]:
        return {**entry["data"], "source": "cache"}
    return None


def _set_cache(asset: str, tf: str, data: dict):
    ttl = CACHE_TTL.get(tf, 600)
    _cache[f"{asset}:{tf}"] = {"data": data, "expires": time.time() + ttl}


# ─── Indicator calculation from raw candles ───────────────────────────────────

def _calc(candles: list) -> dict:
    """
    Tính ATR(14), ADX(14), RSI(14), EMA slope từ raw OHLCV.
    candles[0] = newest → đảo ngược để oldest-first.
    """
    c = list(reversed(candles))
    n = len(c)
    if n < 15:
        return {}

    highs  = [float(x["high"])  for x in c]
    lows   = [float(x["low"])   for x in c]
    closes = [float(x["close"]) for x in c]

    # ATR(14)
    tr = []
    for i in range(1, n):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]),
        ))
    atr14    = sum(tr[-14:]) / 14
    atr_pct  = (atr14 / closes[-1]) * 100

    # RSI(14)
    gains  = [max(0,  closes[i] - closes[i-1]) for i in range(1, n)]
    losses = [max(0, -closes[i] + closes[i-1]) for i in range(1, n)]
    ag = sum(gains[-14:])  / 14
    al = sum(losses[-14:]) / 14
    rsi = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)

    # EMA(50) slope — % change over last 5 candles vs EMA
    k = 2 / 51
    ema = closes[0]
    for p in closes[1:]:
        ema = p * k + ema * (1 - k)
    ref        = closes[-5] if n >= 5 else closes[0]
    ema_slope  = (closes[-1] - ref) / max(ref, 1e-9) * 100

    # ADX(14) — average directional index (trend strength)
    pdm = [max(0, highs[i] - highs[i-1])   if (highs[i]-highs[i-1]) > (lows[i-1]-lows[i]) else 0 for i in range(1, n)]
    ndm = [max(0, lows[i-1] - lows[i])     if (lows[i-1]-lows[i]) > (highs[i]-highs[i-1]) else 0 for i in range(1, n)]
    atr_sum = sum(tr[-14:])
    if atr_sum > 0:
        pdi = sum(pdm[-14:]) / atr_sum * 100
        ndi = sum(ndm[-14:]) / atr_sum * 100
        denom = pdi + ndi
        adx = abs(pdi - ndi) / denom * 100 if denom > 0 else 0
    else:
        adx = 0

    return {
        "atr_pct":   round(atr_pct,  4),
        "adx":       round(adx,      1),
        "rsi":       round(rsi,      1),
        "ema_slope": round(ema_slope, 4),
        "close":     round(closes[-1], 5),
    }


# ─── API fetch ────────────────────────────────────────────────────────────────

def _fetch(asset: str, tf: str) -> Optional[dict]:
    if not API_KEY:
        return None

    symbol   = ASSET_SYMBOL.get(asset)
    interval = TF_INTERVAL.get(tf)
    if not symbol or not interval:
        return None

    # Rate limit guard — tránh vượt TwelveData free tier (8 credits/phút)
    if not _can_call_api():
        logger.warning(f"[OHLCV] Rate limit — skipping API call for {asset}/{tf}, using cache/fallback")
        return None

    try:
        import requests
        r = requests.get(
            f"{BASE_URL}/time_series",
            params={"symbol": symbol, "interval": interval,
                    "outputsize": 60, "apikey": API_KEY, "format": "JSON"},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            logger.warning(f"[OHLCV] HTTP {r.status_code} {asset}/{tf}")
            return None
        body = r.json()
        if body.get("status") == "error" or "values" not in body:
            logger.warning(f"[OHLCV] API err: {body.get('message','')}")
            return None
        data = _calc(body["values"])
        if not data:
            return None
        _record_api_call()  # chỉ đếm khi thành công
        data["source"] = "live"
        logger.info(f"[OHLCV] {asset}/{tf} ATR={data['atr_pct']:.3f}% ADX={data['adx']} RSI={data['rsi']}")
        return data
    except Exception as e:
        logger.warning(f"[OHLCV] fetch error {asset}/{tf}: {e}")
        return None


# ─── Public API ───────────────────────────────────────────────────────────────

def get_live_indicators(asset: str, tf: str) -> dict:
    """
    Trả về dict: atr_pct, adx, rsi, ema_slope, source.
    Không bao giờ raise exception.
    """
    # 1. Cache
    cached = _get_cached(asset, tf)
    if cached:
        return cached

    # 2. Live API
    live = _fetch(asset, tf)
    if live:
        _set_cache(asset, tf, live)
        return live

    # 3. Fallback
    fb = dict(FALLBACK.get(asset, FALLBACK["GOLD"]))
    fb["source"] = "fallback"
    return fb


def cache_status() -> dict:
    """Admin — xem trạng thái cache."""
    now = time.time()
    return {
        k: {"ttl_left": max(0, int(v["expires"] - now)), **v["data"]}
        for k, v in _cache.items()
    }