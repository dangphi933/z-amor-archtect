"""
app/intelligence/engine.py
============================
Radar Intelligence Stack — 5 layers.

Layer 1: Feature Engine      — ADX, ATR%, Volatility Ratio, EMA Slope, Range Compression
Layer 2: Composite Score     — weighted 0-100 score
Layer 3: Regime Transition   — STABLE/TREND_EXHAUSTION/VOLATILITY_SHOCK/RANGE_EXPANSION
Layer 4: Market State Machine— RANGE/BREAKOUT_SETUP/TREND/TREND_EXHAUSTION/VOLATILITY_SHOCK (stateful)
Layer 5: Portfolio Regime    — RISK_ON/RISK_MIXED/RISK_OFF/VOLATILITY_SHOCK

Extract + extend từ Z-ARMOR-CLOUD/radar/engine.py.
Business logic layers 1-2 KHÔNG thay đổi.
Layers 3-5 là THÊM MỚI trong V2.0.
"""

import hashlib
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Dict

logger = logging.getLogger("zarmor.radar.engine")

# ── Asset profiles (giữ nguyên từ monolith) ────────────────────────────────────
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
    ("GOLD",   "LONDON/NY OVERLAP"): 95, ("GOLD",   "LONDON SESSION"):    85,
    ("GOLD",   "NY SESSION"):        78, ("GOLD",   "ASIAN SESSION"):     52,
    ("GOLD",   "DEAD ZONE"):         28, ("EURUSD", "LONDON SESSION"):    92,
    ("EURUSD", "LONDON/NY OVERLAP"): 88, ("EURUSD", "NY SESSION"):        70,
    ("EURUSD", "ASIAN SESSION"):     42, ("EURUSD", "DEAD ZONE"):         25,
    ("BTC",    "NY SESSION"):        85, ("BTC",    "LATE NY"):           60,
    ("BTC",    "LONDON SESSION"):    72, ("BTC",    "ASIAN SESSION"):     68,
    ("NASDAQ", "US MARKET OPEN"):    95, ("NASDAQ", "PRE-OPEN"):          45,
    ("NASDAQ", "PRE-MARKET"):        18, ("NASDAQ", "AFTER-HOURS"):       20,
}

SCORE_LABELS = [
    (85, 101, "STRONG",  "Strong Opportunity",  "#00ff9d", "🟢", "ALLOW_SCALE"),
    (70,  85, "GOOD",    "Good Conditions",      "#00e5ff", "🔵", "ALLOW"),
    (50,  70, "CAUTION", "Trade with Caution",   "#ffaa00", "🟡", "CAUTION"),
    (30,  50, "RISKY",   "Risky Conditions",     "#ff7700", "🟠", "WARN"),
    (0,   30, "AVOID",   "Avoid Trading",        "#ff4444", "🔴", "BLOCK"),
]

TTL_BY_TF = {"M5": 300, "M15": 600, "H1": 1800}

# ── Layer 3: Transition types ──────────────────────────────────────────────────
TRANSITION_TYPES = {
    "STABLE":            "Market regime stable — no significant change detected",
    "TREND_EXHAUSTION":  "Trend momentum fading — potential reversal ahead",
    "VOLATILITY_SHOCK":  "Sudden volatility spike — widen stops or step aside",
    "RANGE_EXPANSION":   "Range breaking out — breakout trade opportunity forming",
}

# ── Layer 4: Market State Machine states ───────────────────────────────────────
MARKET_STATES = ["RANGE", "BREAKOUT_SETUP", "TREND", "TREND_EXHAUSTION", "VOLATILITY_SHOCK"]

# State transition rules: (from_state, condition) → to_state
STATE_TRANSITIONS = {
    ("RANGE",            "score >= 70 and adx > 25"):  "BREAKOUT_SETUP",
    ("RANGE",            "atr_pct > 1.5"):             "VOLATILITY_SHOCK",
    ("BREAKOUT_SETUP",   "score >= 80 and adx > 30"):  "TREND",
    ("BREAKOUT_SETUP",   "score < 50"):                "RANGE",
    ("TREND",            "score < 60 or adx < 20"):    "TREND_EXHAUSTION",
    ("TREND",            "atr_pct > 2.0"):             "VOLATILITY_SHOCK",
    ("TREND_EXHAUSTION", "score >= 70"):               "TREND",
    ("TREND_EXHAUSTION", "score < 40"):                "RANGE",
    ("VOLATILITY_SHOCK", "atr_pct < 1.0"):             "RANGE",
}

# R-01: State Machine backed by Redis (no TTL — permanent state per symbol)
# Key: radar_state:{symbol}   Value: JSON {state, bars_in_state, prev_state}
# Falls back to in-memory dict if Redis unavailable.
_state_mem_fallback: dict = {}   # only used when Redis down

# ── Layer 5: Portfolio Regime ──────────────────────────────────────────────────
PORTFOLIO_REGIMES = {
    "RISK_ON":         {"min_avg_score": 70, "max_shock_pct": 0.1},
    "RISK_MIXED":      {"min_avg_score": 50, "max_shock_pct": 0.3},
    "RISK_OFF":        {"min_avg_score": 0,  "max_shock_pct": 0.5},
    "VOLATILITY_SHOCK":{"min_avg_score": 0,  "max_shock_pct": 0.99},
}

# ── R-01: Redis-backed state helpers ──────────────────────────────────────────

def _state_key(symbol: str) -> str:
    return f"radar_state:{symbol}"

def _state_get(symbol: str) -> dict:
    """Get state from Redis. Fallback to in-memory if Redis unavailable."""
    try:
        from shared.libs.cache.redis_store import cache_get
        data = cache_get(_state_key(symbol))
        if data:
            return data
    except Exception:
        pass
    return _state_mem_fallback.get(symbol, {"state": "RANGE", "bars_in_state": 0, "prev_state": None})

def _state_set(symbol: str, state: str, bars: int, prev_state: Optional[str]):
    """Persist state to Redis (no TTL — permanent). Also update in-memory fallback."""
    entry = {"state": state, "bars_in_state": bars, "prev_state": prev_state}
    _state_mem_fallback[symbol] = entry
    try:
        from shared.libs.cache.redis_store import cache_set
        cache_set(_state_key(symbol), entry, ttl=0)   # ttl=0 → no expiry
    except Exception as e:
        logger.debug(f"[RADAR] State Redis write failed for {symbol}: {e}")

@dataclass
class FeatureVector:
    """Layer 1 output."""
    adx:              float
    atr_pct:          float
    volatility_ratio: float
    ema_slope:        float
    range_compression:float
    rsi:              float = 50.0   # R-03: RSI for structure score
    data_source:      str = "static"


@dataclass
class RadarResult:
    """Full radar result — output contract của radar_map."""
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
    feature_vector:    dict = field(default_factory=dict)   # Layer 1
    transition_score:  float = 0.0                          # Layer 3
    transition_type:   str = "STABLE"                       # Layer 3
    market_state:      str = "RANGE"                        # Layer 4
    bars_in_state:     int = 0                              # Layer 4
    ea_allow_trade:    bool  = True
    ea_position_pct:   int   = 60
    ea_sl_multiplier:  float = 1.5
    ea_state_cap:      str   = "CAUTION"


@dataclass
class RadarMap:
    """Portfolio-level output — Layer 5 output contract."""
    scan_id:          str
    portfolio_regime: str          # RISK_ON/RISK_MIXED/RISK_OFF/VOLATILITY_SHOCK
    avg_score:        float
    symbol_count:     int
    timestamp_utc:    str
    results:          Dict[str, RadarResult] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════
# LAYER 1: FEATURE ENGINE
# ══════════════════════════════════════════════════════════════════

def _adx_score(adx: float, adx_strong: float) -> float:
    if adx < 15:  return 20.0
    if adx < 20:  return 20 + (adx - 15) / 5 * 20
    if adx < adx_strong: return 40 + (adx - 20) / max(adx_strong - 20, 1) * 40
    return min(100.0, 80 + (adx - adx_strong) / 10 * 20)


def _atr_quality(atr_pct: float, typical: float) -> float:
    ratio = atr_pct / max(typical, 1e-6)
    if 0.7 <= ratio <= 1.5: return 70 + (ratio - 0.7) / 0.8 * 20
    if ratio < 0.7:         return max(20.0, 60 * ratio / 0.7)
    return max(20.0, 90 - (ratio - 1.5) * 30)


def compute_features(asset: str, live_indicators: dict) -> FeatureVector:
    """Layer 1: compute feature vector từ live OHLCV indicators."""
    profile = ASSET_PROFILES.get(asset, ASSET_PROFILES["GOLD"])

    adx      = live_indicators.get("adx", 0.0)
    atr_pct  = live_indicators.get("atr_pct", profile["typical_atr"])
    rsi      = live_indicators.get("rsi", 50.0)          # R-03: capture RSI
    ema_fast = live_indicators.get("ema_fast", 0.0)
    ema_slow = live_indicators.get("ema_slow", 0.0)

    ema_slope = (ema_fast - ema_slow) / max(ema_slow, 1e-6) * 100 if ema_slow > 0 else 0.0
    ema_slope = max(-5.0, min(5.0, ema_slope))

    vol_ratio = atr_pct / max(profile["typical_atr"], 1e-6)
    range_compression = max(0.0, 1.0 - vol_ratio) if vol_ratio < 1.0 else 0.0
    data_source = "live" if live_indicators.get("source") == "live" else "static"

    return FeatureVector(
        adx=adx, atr_pct=atr_pct, volatility_ratio=vol_ratio,
        ema_slope=ema_slope, range_compression=range_compression,
        rsi=rsi, data_source=data_source,       # R-03: pass rsi through
    )


# ── R-03: RSI structure score (mirrors monolith _rsi_struct) ──────────────────
def _rsi_struct(rsi: float) -> float:
    """RSI → market structure clarity 0-100. Optimal zone: 40–65."""
    if 40 <= rsi <= 65:  return 85.0
    if 30 <= rsi < 40 or 65 < rsi <= 75: return 65.0
    if 20 <= rsi < 30 or 75 < rsi <= 85: return 40.0
    return 20.0


# ── R-06: Deterministic jitter ±2 (matches monolith is_live branch) ──────────
def _jitter_score(asset: str, tf: str, score: int) -> int:
    """
    R-06: Minimal deterministic jitter ±2 to prevent score freezing in flat markets.
    Uses hash of (asset, tf, UTC-hour, date) — same call within same hour = same jitter.
    """
    import hashlib
    now = datetime.now(timezone.utc)
    h = int(hashlib.md5(f"{asset}{tf}{now.strftime('%Y%m%d')}{now.hour:02d}".encode()).hexdigest()[:4], 16)
    jitter = (h % 5) - 2   # range: -2 .. +2
    return max(0, min(100, score + jitter))


# ── R-04: Linear gradient _ea_params (matches monolith logic exactly) ─────────
def _ea_params(score: int, gate: str, regime: str) -> dict:
    """
    R-04: Restore monolith linear gradient for position_pct.
    Monolith: ALLOW → 60→100 linear, CAUTION → 30→60 linear, WARN → 20→30 linear.
    ZCloud previously used fixed steps (60, 30) — now restored to smooth scaling.
    sl_multiplier follows regime: STRONG_TREND/TRENDING→1.5, VOLATILE/UNCERTAIN→2.0, others→1.0.
    """
    _sl = {
        "STRONG_TREND": 1.5, "TRENDING": 1.5,
        "VOLATILE": 2.0,     "UNCERTAIN": 2.0,
    }
    sl = _sl.get(regime, 1.0)

    if gate == "BLOCK":
        return {"allow_trade": False, "position_pct": 0, "sl_multiplier": max(sl, 2.0), "state_cap": "BLOCKED"}
    if score >= 85:
        return {"allow_trade": True,  "position_pct": 125, "sl_multiplier": sl, "state_cap": "SCALE"}
    if score >= 70:
        pos = 60 + int((score - 70) / 15 * 40)    # 60→100 over 70–85
        return {"allow_trade": True,  "position_pct": pos, "sl_multiplier": sl, "state_cap": "OPTIMAL"}
    if score >= 50:
        pos = 30 + int((score - 50) / 20 * 30)    # 30→60 over 50–70
        return {"allow_trade": True,  "position_pct": pos, "sl_multiplier": sl, "state_cap": "REDUCED"}
    # gate == WARN, score 30–49
    pos = 20 + int((score - 30) / 20 * 10)        # 20→30 over 30–50
    return {"allow_trade": True, "position_pct": pos, "sl_multiplier": sl, "state_cap": "MINIMAL"}


# ══════════════════════════════════════════════════════════════════
# LAYER 2: COMPOSITE SCORE ENGINE  (R-03: +RSI, R-06: +jitter)
# ══════════════════════════════════════════════════════════════════

def compute_score(asset: str, timeframe: str, features: FeatureVector) -> tuple[int, dict, str, str]:
    """
    Layer 2: weighted composite score 0-100.
    R-03: weights rebalanced to include RSI structure (10%).
    R-06: deterministic ±2 jitter added to prevent score freezing.
    Updated weights: ADX:28%, EMA:23%, VR:19%, ATR:13%, Session:7%, RSI:10%
    """
    profile  = ASSET_PROFILES.get(asset, ASSET_PROFILES["GOLD"])
    tf_mult  = TF_MULT.get(timeframe, 1.0)

    adx_s   = _adx_score(features.adx, profile["adx_strong"])
    atr_s   = _atr_quality(features.atr_pct, profile["typical_atr"])
    slope_s = min(100.0, 50 + features.ema_slope * 15)
    vr_s    = _atr_quality(features.volatility_ratio, 1.0)
    rsi_s   = _rsi_struct(getattr(features, "rsi", 50.0))   # R-03

    # Session component
    now_h = datetime.now(timezone.utc).hour
    session_name, session_s = "UNKNOWN", 50
    for h_start, h_end, _, _, s_name in SESSION_WINDOWS.get(asset, []):
        if h_start <= now_h < h_end:
            session_name = s_name
            session_s = SESSION_BIAS.get((asset, s_name), 50)
            break

    # R-03: RSI added at 10%, session reduced 10%→7%, others slightly trimmed
    raw_score = (
        adx_s    * 0.28 +
        atr_s    * 0.13 +
        vr_s     * 0.19 +
        slope_s  * 0.23 +
        rsi_s    * 0.10 +
        session_s* 0.07
    ) * tf_mult

    score = max(0, min(100, int(raw_score)))
    score = _jitter_score(asset, timeframe, score)   # R-06: ±2 jitter

    # Label
    label, label_text, color, emoji, gate = "CAUTION", "Trade with Caution", "#ffaa00", "🟡", "CAUTION"
    for lo, hi, lbl, lt, col, emj, gt in SCORE_LABELS:
        if lo <= score < hi:
            label, label_text, color, emoji, gate = lbl, lt, col, emj, gt
            break

    # Regime
    if score >= 80 and features.adx > 30:                  regime = "STRONG_TREND"
    elif score >= 70 and features.adx > 25:                regime = "TRENDING"
    elif score >= 50 and features.volatility_ratio > 1.5:  regime = "VOLATILE"
    elif score < 35 and features.range_compression > 0.4:  regime = "BREAKOUT_WATCH"
    elif score >= 40 and features.volatility_ratio < 0.8:  regime = "MEAN_REVERSION"
    else:                                                   regime = "NEUTRAL"

    # Confidence
    data_bonus = 10 if features.data_source == "live" else 0
    raw_conf = min(99, 60 + data_bonus + score // 5)
    confidence = f"{raw_conf}%"

    breakdown = {
        "adx_score":    round(adx_s,   1),
        "atr_score":    round(atr_s,   1),
        "slope_score":  round(slope_s, 1),
        "vr_score":     round(vr_s,    1),
        "rsi_score":    round(rsi_s,   1),    # R-03
        "session_score": session_s,
        "adx_live":     round(features.adx,      1),
        "atr_pct_live": round(features.atr_pct,  3),
        "rsi_live":     round(getattr(features, "rsi", 50.0), 1),  # R-03
        "ema_slope":    round(features.ema_slope, 3),
        "data_source":  features.data_source,
        "session":      session_name,
        "tf_mult":      tf_mult,
    }

    return score, breakdown, regime, confidence, session_name


# ══════════════════════════════════════════════════════════════════
# LAYER 3: REGIME TRANSITION DETECTOR
# ══════════════════════════════════════════════════════════════════

def detect_transition(
    current_score: int,
    prev_score: int,
    features: FeatureVector,
    prev_features: Optional[FeatureVector] = None,
) -> tuple[str, float]:
    """
    Layer 3: detect regime transition type + score.
    Returns (transition_type, transition_score 0-100)
    """
    score_delta = abs(current_score - prev_score) if prev_score else 0

    # Volatility shock — sudden spike
    if features.atr_pct > 2.0 or features.volatility_ratio > 2.5:
        return "VOLATILITY_SHOCK", min(100.0, features.volatility_ratio * 30)

    # Trend exhaustion — score falling while ADX high (momentum fading)
    if prev_score and current_score < prev_score - 15 and features.adx > 25:
        return "TREND_EXHAUSTION", min(100.0, score_delta * 2)

    # Range expansion — compression breaking out
    if (prev_features and prev_features.range_compression > 0.3
            and features.range_compression < 0.1 and current_score > 65):
        return "RANGE_EXPANSION", min(100.0, 50 + score_delta)

    # Stable
    return "STABLE", max(0.0, 100 - score_delta * 3)


# ══════════════════════════════════════════════════════════════════
# LAYER 4: MARKET STATE MACHINE  (R-01: Redis-backed, multi-replica safe)
# ══════════════════════════════════════════════════════════════════

def get_market_state(symbol: str) -> dict:
    """Get current market state from Redis (falls back to in-memory)."""
    return _state_get(symbol)


def update_market_state(symbol: str, score: int, features: FeatureVector) -> tuple[str, int, str]:
    """
    Layer 4: state machine transition logic.
    R-01: reads/writes via Redis — safe with multi-replica deployment.
    Returns (new_state, bars_in_state, prev_state)
    """
    current       = _state_get(symbol)
    current_state = current["state"]
    bars          = current["bars_in_state"]
    adx           = features.adx
    atr_pct       = features.atr_pct

    new_state = current_state

    if current_state == "RANGE":
        if score >= 70 and adx > 25:  new_state = "BREAKOUT_SETUP"
        elif atr_pct > 1.5:           new_state = "VOLATILITY_SHOCK"

    elif current_state == "BREAKOUT_SETUP":
        if score >= 80 and adx > 30:  new_state = "TREND"
        elif score < 50:              new_state = "RANGE"

    elif current_state == "TREND":
        if score < 60 or adx < 20:    new_state = "TREND_EXHAUSTION"
        elif atr_pct > 2.0:           new_state = "VOLATILITY_SHOCK"

    elif current_state == "TREND_EXHAUSTION":
        if score >= 70:               new_state = "TREND"
        elif score < 40:              new_state = "RANGE"

    elif current_state == "VOLATILITY_SHOCK":
        if atr_pct < 1.0:             new_state = "RANGE"

    if new_state == current_state:
        bars += 1
    else:
        bars = 0
        logger.info(f"[RADAR] State: {symbol} {current_state} → {new_state}")

    prev = current_state if new_state != current_state else current.get("prev_state")
    _state_set(symbol, new_state, bars, prev)   # → Redis + mem fallback

    return new_state, bars, current_state


def seed_state_cache(symbol: str, state: str, bars: int, prev_state: Optional[str]):
    """Seed from DB on startup — writes to Redis so all replicas get it."""
    _state_set(symbol, state, bars, prev_state)


# ══════════════════════════════════════════════════════════════════
# LAYER 5: PORTFOLIO REGIME DETECTOR
# ══════════════════════════════════════════════════════════════════

def compute_portfolio_regime(results: Dict[str, RadarResult]) -> str:
    """
    Layer 5: aggregate individual symbol regimes → portfolio regime.
    RISK_ON:         avg_score >= 70, ≤10% in VOLATILITY_SHOCK
    RISK_MIXED:      avg_score >= 50, ≤30% in VOLATILITY_SHOCK
    RISK_OFF:        avg_score < 50
    VOLATILITY_SHOCK: >50% symbols in VOLATILITY_SHOCK state
    """
    if not results:
        return "RISK_OFF"

    scores = [r.score for r in results.values()]
    shock_count = sum(1 for r in results.values() if r.market_state == "VOLATILITY_SHOCK")
    avg_score   = sum(scores) / len(scores)
    shock_pct   = shock_count / len(results)

    if shock_pct > 0.5:        return "VOLATILITY_SHOCK"
    if avg_score >= 70 and shock_pct <= 0.10: return "RISK_ON"
    if avg_score >= 50 and shock_pct <= 0.30: return "RISK_MIXED"
    return "RISK_OFF"


# ══════════════════════════════════════════════════════════════════
# MAIN COMPUTE FUNCTIONS
# ══════════════════════════════════════════════════════════════════

async def compute(asset: str, timeframe: str, prev_result: Optional[RadarResult] = None) -> RadarResult:
    """Compute full radar result cho 1 symbol — runs all 5 layers."""
    # Layer 1: Features
    try:
        from .ohlcv_service import get_live_indicators
        live_indicators = await get_live_indicators(asset, timeframe)
    except Exception as e:
        logger.debug(f"[RADAR] OHLCV fetch failed for {asset}/{timeframe}: {e}")
        live_indicators = {}

    features = compute_features(asset, live_indicators)

    # Layer 2: Score
    score, breakdown, regime, confidence, session = compute_score(asset, timeframe, features)

    # Layer 3: Transition — R-07: load prev_score from Redis if not passed in
    symbol_key = f"{asset}:{timeframe}"
    if prev_result:
        prev_score = prev_result.score
    else:
        try:
            from shared.libs.cache.redis_store import cache_get
            prev_score = cache_get(f"radar_prev_score:{symbol_key}") or None
        except Exception:
            prev_score = None

    transition_type, transition_score = detect_transition(score, prev_score, features)

    # R-07: persist current score as prev for next scan
    try:
        from shared.libs.cache.redis_store import cache_set
        cache_set(f"radar_prev_score:{symbol_key}", score, ttl=7200)  # 2h TTL
    except Exception:
        pass

    # Layer 4: State Machine (R-01: Redis-backed)
    market_state, bars_in_state, _ = update_market_state(symbol_key, score, features)

    # Gate — re-derive from score (gate already in breakdown label loop above)
    gate = "CAUTION"
    for lo, hi, _, _, _, _, gt in SCORE_LABELS:
        if lo <= score < hi:
            gate = gt; break

    # R-04: Use _ea_params() for linear gradient position sizing
    ea = _ea_params(score, gate, regime)

    # R-05: ML Regime Override — mirrors monolith Phase 3 logic
    # Calls ml-service via HTTP if available. Graceful fallback to rule-based.
    ml_meta = None
    try:
        import os, httpx
        ml_url = os.getenv("ML_SERVICE_URL", "http://ml-service:8005")
        async with httpx.AsyncClient(timeout=1.5) as client:
            ml_resp = await client.post(f"{ml_url}/ml/predict", json={
                "asset":          asset,
                "timeframe":      timeframe,
                "adx":            features.adx,
                "atr_pct":        features.atr_pct,
                "rsi":            getattr(features, "rsi", 50.0),
                "ema_slope":      features.ema_slope,
                "volatility_ratio": features.volatility_ratio,
                "score":          score,
                "utc_hour":       datetime.now(timezone.utc).hour,
                "utc_dow":        datetime.now(timezone.utc).weekday(),
            })
            if ml_resp.status_code == 200:
                ml_data = ml_resp.json()
                ml_conf = ml_data.get("confidence", "LOW")
                if ml_conf in ("HIGH", "MEDIUM"):
                    ml_regime_raw = ml_data.get("regime", "")
                    # Map ML 3-class → engine 7-regime (same as monolith _map_ml_regime)
                    if ml_regime_raw == "PROFITABLE_TREND":
                        ml_regime = "STRONG_TREND" if score >= 80 else "TRENDING"
                    elif ml_regime_raw == "FALSE_SIGNAL":
                        ml_regime = "VOLATILE" if score < 40 else "MEAN_REVERSION"
                    else:  # RANGE_BOUND
                        ml_regime = "BREAKOUT_WATCH" if score >= 55 else "NEUTRAL"

                    regime = ml_regime
                    # Boost confidence when ML and rule-based agree
                    if ml_regime == regime:
                        confidence = "HIGH" if ml_conf == "HIGH" else confidence
                    ml_meta = {
                        "ml_regime":     ml_regime_raw,
                        "ml_confidence": ml_conf,
                        "ml_proba":      ml_data.get("probabilities", {}),
                        "model_version": ml_data.get("model_version", "unknown"),
                        "source":        "ml",
                    }
                    logger.debug(f"[RADAR] ML override {asset}/{timeframe}: {regime} conf={ml_conf}")
    except Exception as _ml_err:
        logger.debug(f"[RADAR] ML predict skipped for {asset}/{timeframe}: {_ml_err}")

    if ml_meta:
        breakdown["ml"] = ml_meta

    risk_notes = []
    if features.volatility_ratio > 1.8: risk_notes.append("High volatility — widen stops")
    if features.adx < 15:               risk_notes.append("Weak trend — avoid breakout entries")
    if market_state == "VOLATILITY_SHOCK": risk_notes.append("Volatility shock — reduce size")
    if transition_type != "STABLE":     risk_notes.append(f"Regime transition: {transition_type}")

    strategy_hints = {
        "STRONG_TREND":   "Strong trend. Scale in on pullbacks.",
        "TRENDING":       "Trend-following favored. Wait for pullback.",
        "NEUTRAL":        "Mixed signals. Reduce size.",
        "MEAN_REVERSION": "Range conditions. Fade extremes.",
        "VOLATILE":       "High vol. Widen stops or stand aside.",
        "BREAKOUT_WATCH": "Compression detected. Watch for breakout.",
        "UNCERTAIN":      "Conflicting signals. Wait for clarity.",
    }

    return RadarResult(
        asset=asset, timeframe=timeframe,
        score=score, regime=regime,
        label=next((lbl for lo, hi, lbl, _, _, _, _ in SCORE_LABELS if lo <= score < hi), "CAUTION"),
        label_text=next((lt for lo, hi, _, lt, _, _, _ in SCORE_LABELS if lo <= score < hi), "Caution"),
        color=next((col for lo, hi, _, _, col, _, _ in SCORE_LABELS if lo <= score < hi), "#ffaa00"),
        emoji=next((emj for lo, hi, _, _, _, emj, _ in SCORE_LABELS if lo <= score < hi), "🟡"),
        gate=gate, confidence=confidence,
        breakdown=breakdown, risk_notes=risk_notes,
        strategy_hint=strategy_hints.get(regime, "Monitor conditions."),
        risk_level="HIGH" if score < 40 else "MEDIUM" if score < 70 else "LOW",
        session=session,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        ttl_sec=TTL_BY_TF.get(timeframe, 1800),
        feature_vector={
            "adx": features.adx, "atr_pct": features.atr_pct,
            "rsi": getattr(features, "rsi", 50.0),            # R-03
            "volatility_ratio": features.volatility_ratio,
            "ema_slope": features.ema_slope,
            "range_compression": features.range_compression,
            "data_source": features.data_source,
        },
        transition_score=transition_score,
        transition_type=transition_type,
        market_state=market_state,
        bars_in_state=bars_in_state,
        ea_allow_trade=ea["allow_trade"],        # R-04: linear gradient
        ea_position_pct=ea["position_pct"],
        ea_sl_multiplier=ea["sl_multiplier"],
        ea_state_cap=ea["state_cap"],
    )


async def compute_all(timeframe: str = "H1") -> RadarMap:
    """Compute tất cả assets → build radar_map với portfolio regime (Layer 5)."""
    import uuid
    results = {}
    for asset in ASSET_PROFILES:
        try:
            result = await compute(asset, timeframe)
            results[f"{asset}:{timeframe}"] = result
        except Exception as e:
            logger.error(f"[RADAR] compute_all error for {asset}: {e}")

    portfolio_regime = compute_portfolio_regime(results)
    avg_score = sum(r.score for r in results.values()) / len(results) if results else 0

    return RadarMap(
        scan_id=f"MAP-{uuid.uuid4().hex[:8].upper()}",
        portfolio_regime=portfolio_regime,
        avg_score=round(avg_score, 1),
        symbol_count=len(results),
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        results=results,
    )
