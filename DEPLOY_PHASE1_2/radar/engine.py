"""
radar/engine.py — Phase 1.5 (Live OHLCV Blend)
================================================
Nâng cấp từ static profiles → blend với live ATR/ADX/RSI.

THAY ĐỔI SO VỚI VERSION CŨ:
  - Component 1 (Trend): static + ADX + EMA slope blend
  - Component 2 (Vol):   static + ATR quality blend
  - Component 3 (Session): KHÔNG đổi (constant theo giờ)
  - Component 4 (Structure): static + RSI blend
  - breakdown có thêm: data_source, adx_live, rsi_live, atr_pct_live
  - Jitter giảm ±2 khi có live data (thay ±5)

KHÔNG ĐỔI:
  - RadarResult dataclass interface
  - compute() / compute_all() signature
  - router.py và schemas.py không cần sửa gì
"""

import hashlib
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional

from .ohlcv_service import get_live_indicators

logger = logging.getLogger("zarmor.radar")

# ── Asset profiles ─────────────────────────────────────────────────────────────
ASSET_PROFILES = {
    "GOLD":   {"trend": 65, "vol": 55, "struct": 72, "typical_atr": 0.55, "adx_strong": 30},
    "EURUSD": {"trend": 50, "vol": 45, "struct": 78, "typical_atr": 0.30, "adx_strong": 25},
    "BTC":    {"trend": 70, "vol": 78, "struct": 58, "typical_atr": 2.10, "adx_strong": 35},
    "NASDAQ": {"trend": 60, "vol": 58, "struct": 68, "typical_atr": 0.80, "adx_strong": 28},
}

TF_MULT = {"M5": 0.82, "M15": 0.91, "H1": 1.00}

SESSION_WINDOWS = {
    "GOLD": [
        (0,  2,  0.72, 0.65, "DEAD ZONE"),
        (2,  7,  0.80, 0.70, "ASIAN SESSION"),
        (7,  12, 1.05, 1.00, "LONDON SESSION"),
        (12, 17, 1.22, 1.18, "LONDON/NY OVERLAP"),
        (17, 22, 0.95, 1.05, "NY SESSION"),
        (22, 24, 0.72, 0.68, "DEAD ZONE"),
    ],
    "EURUSD": [
        (0,  7,  0.75, 0.70, "ASIAN SESSION"),
        (7,  16, 1.22, 1.12, "LONDON SESSION"),
        (16, 22, 0.90, 0.88, "NY SESSION"),
        (22, 24, 0.72, 0.68, "DEAD ZONE"),
    ],
    "BTC": [
        (0,  6,  0.85, 0.90, "ASIAN SESSION"),
        (6,  14, 0.95, 1.00, "LONDON SESSION"),
        (14, 22, 1.18, 1.12, "NY SESSION"),
        (22, 24, 1.02, 1.05, "LATE NY"),
    ],
    "NASDAQ": [
        (0,  13, 0.48, 0.48, "PRE-MARKET"),
        (13, 14, 0.75, 0.80, "PRE-OPEN"),
        (14, 21, 1.28, 1.22, "US MARKET OPEN"),
        (21, 24, 0.62, 0.65, "AFTER-HOURS"),
    ],
}

SESSION_BIAS = {
    ("GOLD",   "LONDON/NY OVERLAP"): 95,
    ("GOLD",   "LONDON SESSION"):    85,
    ("GOLD",   "NY SESSION"):        78,
    ("GOLD",   "ASIAN SESSION"):     52,
    ("GOLD",   "DEAD ZONE"):         28,
    ("EURUSD", "LONDON SESSION"):    92,
    ("EURUSD", "LONDON/NY OVERLAP"): 88,
    ("EURUSD", "NY SESSION"):        70,
    ("EURUSD", "ASIAN SESSION"):     42,
    ("EURUSD", "DEAD ZONE"):         25,
    ("BTC",    "NY SESSION"):        85,
    ("BTC",    "LATE NY"):           60,
    ("BTC",    "LONDON SESSION"):    72,
    ("BTC",    "ASIAN SESSION"):     68,
    ("NASDAQ", "US MARKET OPEN"):    95,
    ("NASDAQ", "PRE-OPEN"):          45,
    ("NASDAQ", "PRE-MARKET"):        18,
    ("NASDAQ", "AFTER-HOURS"):       20,
}

SCORE_LABELS = [
    (85, 101, "STRONG",  "Strong Opportunity", "#00ff9d", "🟢", "ALLOW_SCALE"),
    (70,  85, "GOOD",    "Good Conditions",    "#00e5ff", "🔵", "ALLOW"),
    (50,  70, "CAUTION", "Trade with Caution", "#ffaa00", "🟡", "CAUTION"),
    (30,  50, "RISKY",   "Risky Conditions",   "#ff7700", "🟠", "WARN"),
    (0,   30, "AVOID",   "Avoid Trading",      "#ff4444", "🔴", "BLOCK"),
]

STRATEGY_HINTS = {
    "STRONG_TREND":   "Strong trend momentum confirmed. Scale in on pullbacks, let winners run.",
    "TRENDING":       "Trend-following setups favored. Wait for pullback to key structure before entry.",
    "NEUTRAL":        "Mixed signals. Confirm with higher timeframe. Reduce position size.",
    "MEAN_REVERSION": "Range conditions. Fade extremes with tight stops. Avoid breakout entries.",
    "VOLATILE":       "High volatility detected. Widen stops significantly or stand aside.",
    "BREAKOUT_WATCH": "Compression detected. Watch for breakout — do not trade the range.",
    "UNCERTAIN":      "Conflicting signals. Wait for clarity before committing capital.",
}

TTL_BY_TF = {"M5": 300, "M15": 600, "H1": 1800}


@dataclass
class RadarResult:
    asset:         str
    timeframe:     str
    score:         int
    regime:        str
    label:         str
    label_text:    str
    color:         str
    emoji:         str
    gate:          str
    confidence:    str
    breakdown:     dict
    risk_notes:    List[str]
    strategy_hint: str
    risk_level:    str
    session:       str
    timestamp_utc: str
    ttl_sec:       int


# ── Live data → score converters ──────────────────────────────────────────────

def _adx_score(adx: float, adx_strong: float) -> float:
    """ADX (0-100) → trend score (0-100)."""
    if adx < 15:  return 20.0
    if adx < 20:  return 20 + (adx - 15) / 5 * 20
    if adx < adx_strong: return 40 + (adx - 20) / max(adx_strong - 20, 1) * 40
    return min(100.0, 80 + (adx - adx_strong) / 10 * 20)


def _atr_quality(atr_pct: float, typical: float) -> float:
    """ATR% so với typical → volatility quality (0-100). Optimal zone = 0.7×–1.5× typical."""
    ratio = atr_pct / max(typical, 1e-6)
    if 0.7 <= ratio <= 1.5: return 70 + (ratio - 0.7) / 0.8 * 20
    if ratio < 0.7:          return max(20.0, ratio / 0.7 * 70)
    return max(10.0, 90 - (ratio - 1.5) * 20)


def _rsi_struct(rsi: float) -> float:
    """RSI → market structure clarity. Optimal 40-65 (clean trend territory)."""
    if 40 <= rsi <= 65:  return 85.0
    if 30 <= rsi < 40 or 65 < rsi <= 75: return 65.0
    if 20 <= rsi < 30 or 75 < rsi <= 85: return 40.0
    return 20.0


def _ema_bonus(ema_slope: float) -> float:
    """EMA slope → trend bonus (direction agnostic)."""
    s = abs(ema_slope)
    if s > 0.3: return 10.0
    if s > 0.1: return 5.0
    return 0.0


# ── Private helpers ───────────────────────────────────────────────────────────

def _session(asset: str, hour: int):
    for row in SESSION_WINDOWS.get(asset, SESSION_WINDOWS["GOLD"]):
        start, end, tm, vm, label = row
        if start <= (hour % 24) < end:
            return tm, vm, label
    last = SESSION_WINDOWS.get(asset, SESSION_WINDOWS["GOLD"])[-1]
    return last[2], last[3], last[4]


def _jitter(asset: str, tf: str, hour: int, date: str, is_live: bool) -> int:
    """Deterministic ±5 (static) or ±2 (live)."""
    h = int(hashlib.md5(f"{asset}{tf}{date}{hour:02d}".encode()).hexdigest()[:4], 16)
    raw = (h % 11) - 5
    return raw // 2 if is_live else raw


def _classify(score: int):
    for lo, hi, lbl, txt, col, em, gate in SCORE_LABELS:
        if lo <= score < hi:
            return lbl, txt, col, em, gate
    return "AVOID", "Avoid Trading", "#ff4444", "🔴", "BLOCK"


def _regime(score: int, trend: float, vol: float, struct: float) -> str:
    if score >= 85 and trend >= 82:      return "STRONG_TREND"
    if score >= 70 and trend >= 72:      return "TRENDING"
    if score < 30:                        return "VOLATILE" if vol < 40 else "MEAN_REVERSION"
    if struct >= 78 and 48 <= score < 70: return "BREAKOUT_WATCH"
    if abs(trend - vol) > 30:            return "UNCERTAIN"
    return "NEUTRAL"


def _confidence(tf: str, tm: float, src: str) -> str:
    live = src in ("live", "cache")
    if tf == "M5" and not live:    return "LOW"
    if tm >= 1.10 and tf == "H1":  return "HIGH"
    if live and tf in ("M15","H1"):return "MEDIUM"
    if tm >= 0.85:                  return "MEDIUM"
    return "LOW"


def _notes(score: int, trend: float, vol: float, session: str,
           asset: str, tf: str, regime: str, live: dict) -> List[str]:
    notes = []
    src = live.get("source", "fallback")
    is_live = src in ("live", "cache")

    # Session
    if any(k in session for k in ("OVERLAP", "OPEN", "MARKET")):
        notes.append(f"✅ {session} — peak liquidity window active")
    elif any(k in session for k in ("DEAD", "PRE-MARKET", "AFTER")):
        notes.append(f"⚠ {session} — low liquidity, wider spreads expected")

    if is_live:
        adx       = live.get("adx", 0)
        rsi       = live.get("rsi", 50)
        atr_pct   = live.get("atr_pct", 0)
        ema_slope = live.get("ema_slope", 0)

        if adx >= 30:
            notes.append(f"✅ ADX {adx:.0f} — strong directional momentum confirmed")
        elif adx <= 18:
            notes.append(f"↔ ADX {adx:.0f} — weak trend, range conditions likely")

        if rsi > 70:
            notes.append(f"⚠ RSI {rsi:.0f} — overbought, pullback risk elevated")
        elif rsi < 30:
            notes.append(f"⚠ RSI {rsi:.0f} — oversold, bounce possible")
        else:
            notes.append(f"✅ RSI {rsi:.0f} — neutral zone, trend entries valid")

        if abs(ema_slope) > 0.15:
            d = "bullish" if ema_slope > 0 else "bearish"
            notes.append(f"✅ EMA slope {d} ({ema_slope:+.2f}%) — directional bias clear")

        if atr_pct > 0:
            lvl = "elevated" if atr_pct > live.get("_typical", 1.0) * 1.5 else "normal"
            notes.append(f"ℹ ATR {atr_pct:.3f}% — volatility {lvl}")
    else:
        if trend >= 78:
            notes.append("✅ Trend persistence high — pullbacks are entry opportunities")
        elif trend <= 42:
            notes.append("↔ Weak trend — mean reversion more effective than breakouts")
        if vol >= 72:
            notes.append("⚠ Volatility elevated — widen stops, reduce size")
        elif vol <= 35:
            notes.append("⚠ Volatility compressed — possible squeeze building")
        else:
            notes.append("✅ Volatility in optimal range for trend entries")

    if regime == "BREAKOUT_WATCH":
        notes.append("👁 Market compressing — watch for breakout, do not trade the range")
    if regime == "UNCERTAIN":
        notes.append("⚡ Conflicting signals — wait for alignment before entering")
    if tf == "M5":
        notes.append("ℹ M5 has higher noise — confirm on H1 before entry")
    if asset == "NASDAQ" and "PRE-MARKET" in session:
        notes.append("⚠ NASDAQ pre-market — avoid entries until US open (14:30 UTC)")

    return notes[:4]


def _risk_level(score: int, vol: float, adx: float) -> str:
    if score >= 70 and vol <= 70 and adx >= 20: return "LOW"
    if score >= 50 or vol <= 65:                 return "MEDIUM"
    return "HIGH"


# ── Main ──────────────────────────────────────────────────────────────────────

def compute(asset: str, timeframe: str) -> RadarResult:
    """
    Pure function (với side-effect duy nhất là HTTP cache).
    router.py gọi hàm này — interface không đổi so với Phase 1.
    """
    if asset not in ASSET_PROFILES:
        raise ValueError(f"Unsupported asset: {asset}")
    if timeframe not in TF_MULT:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    now      = datetime.now(timezone.utc)
    h        = now.hour
    date_str = now.strftime("%Y%m%d")
    tf_mult  = TF_MULT[timeframe]
    p        = ASSET_PROFILES[asset]

    tm, vm, sess_label = _session(asset, h)

    # ── Live OHLCV ────────────────────────────────────────────────────────────
    live    = get_live_indicators(asset, timeframe)
    src     = live.get("source", "fallback")
    is_live = src in ("live", "cache")
    adx     = float(live.get("adx",       0))
    rsi     = float(live.get("rsi",       50))
    atr_pct = float(live.get("atr_pct",   p["typical_atr"]))
    slope   = float(live.get("ema_slope", 0))
    live["_typical"] = p["typical_atr"]   # inject for notes

    # ── Component 1: Trend Strength (35%) ────────────────────────────────────
    stat_trend = min(100.0, p["trend"] * tm * tf_mult)
    if is_live and adx > 0:
        live_trend = min(100.0, _adx_score(adx, p["adx_strong"]) * tm * tf_mult + _ema_bonus(slope))
        trend = 0.45 * stat_trend + 0.55 * live_trend
    else:
        trend = stat_trend

    # ── Component 2: Volatility Quality (25%) ────────────────────────────────
    raw = p["vol"] * vm
    if 45 <= raw <= 72:   stat_vol = min(100.0, raw * 1.15)
    elif raw < 35:         stat_vol = raw / 35 * 60
    else:                  stat_vol = max(0.0, min(100.0, 100 - (raw - 72) * 1.5))

    if is_live and atr_pct > 0:
        vol = 0.40 * stat_vol + 0.60 * _atr_quality(atr_pct, p["typical_atr"])
    else:
        vol = stat_vol

    # ── Component 3: Session Bias (20%) ──────────────────────────────────────
    bias = SESSION_BIAS.get((asset, sess_label), 50)

    # ── Component 4: Market Structure (20%) ──────────────────────────────────
    stat_struct = min(100.0, max(0.0,
        {"H1": 85, "M15": 70, "M5": 45}[timeframe]
        + {"GOLD": 10, "EURUSD": 15, "BTC": -5, "NASDAQ": 5}[asset]
    ))
    if is_live and rsi > 0:
        struct = 0.60 * stat_struct + 0.40 * _rsi_struct(rsi)
    else:
        struct = stat_struct

    # ── Score ─────────────────────────────────────────────────────────────────
    raw_score = 0.35*trend + 0.25*vol + 0.20*bias + 0.20*struct
    j         = _jitter(asset, timeframe, h, date_str, is_live)
    score     = int(max(0, min(100, round(raw_score + j))))

    # ── Classify ──────────────────────────────────────────────────────────────
    reg           = _regime(score, trend, vol, struct)
    lbl, txt, col, em, gate = _classify(score)
    conf          = _confidence(timeframe, tm, src)
    notes         = _notes(score, trend, vol, sess_label, asset, timeframe, reg, live)
    hint          = STRATEGY_HINTS.get(reg, STRATEGY_HINTS["NEUTRAL"])
    risk          = _risk_level(score, vol, adx)

    logger.debug(f"[ENGINE] {asset}/{timeframe} score={score} src={src} "
                 f"trend={trend:.1f} vol={vol:.1f} bias={bias} struct={struct:.1f}")

    return RadarResult(
        asset         = asset,
        timeframe     = timeframe,
        score         = score,
        regime        = reg,
        label         = lbl,
        label_text    = txt,
        color         = col,
        emoji         = em,
        gate          = gate,
        confidence    = conf,
        breakdown     = {
            "trend_strength":     round(trend,   1),
            "volatility_quality": round(vol,     1),
            "session_bias":       round(bias,    1),
            "market_structure":   round(struct,  1),
            # Live data fields — None khi fallback
            "data_source":        src,
            "adx_live":           round(adx,     1) if is_live else None,
            "rsi_live":           round(rsi,     1) if is_live else None,
            "atr_pct_live":       round(atr_pct, 4) if is_live else None,
        },
        risk_notes    = notes,
        strategy_hint = hint,
        risk_level    = risk,
        session       = sess_label,
        timestamp_utc = now.isoformat(),
        ttl_sec       = TTL_BY_TF.get(timeframe, 600),
    )


def compute_all() -> dict:
    """All 12 asset×TF combinations — dùng cho /radar/feed và daily digest."""
    out = {}
    for asset in ASSET_PROFILES:
        out[asset] = {}
        for tf in TF_MULT:
            try:
                r = compute(asset, tf)
                out[asset][tf] = {
                    "score":       r.score,
                    "regime":      r.regime,
                    "label":       r.label,
                    "emoji":       r.emoji,
                    "color":       r.color,
                    "session":     r.session,
                    "strategy":    r.strategy_hint,
                    "data_source": r.breakdown.get("data_source", "fallback"),
                }
            except Exception as e:
                logger.error(f"compute_all {asset}/{tf}: {e}")
    return out
