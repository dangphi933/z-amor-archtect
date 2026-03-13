"""
radar/engine.py
===============
RegimeFit Lite Engine — Phase 1
No OHLCV feed required. Uses static asset profiles + session bias.

Formula (from RADAR_SCAN_ARCHITECTURE_V2):
  RadarScore = 0.35 × TrendStrength
             + 0.25 × VolatilityQuality
             + 0.20 × SessionBias
             + 0.20 × MarketStructure
             + HourlyVariance(±5)

Pure functions only — no I/O, no side effects.
Swap engine.py for RFS Full (Phase 2) without touching router.py.
"""

import hashlib
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List

logger = logging.getLogger("zarmor.radar")

# ── Asset Baseline Profiles ────────────────────────────────────────────────────
# Tune these per backtesting data in Phase 2
ASSET_PROFILES = {
    "GOLD": {
        "trend":   65,   # Strong catalyst-driven moves on USD news
        "vol":     55,   # Mid volatility — optimal range most sessions
        "mom":     60,
        "struct":  72,   # Deep market, clean structure
    },
    "EURUSD": {
        "trend":   50,   # FX ranges more than GOLD in low-vol
        "vol":     45,   # Tighter spread, lower vol
        "mom":     55,
        "struct":  78,   # Highest liquidity → cleanest structure
    },
    "BTC": {
        "trend":   70,   # Crypto trends strongly when momentum is on
        "vol":     78,   # High vol by nature
        "mom":     65,
        "struct":  58,   # 24/7, weekend gaps, messier structure
    },
    "NASDAQ": {
        "trend":   60,   # Index trends well in US hours
        "vol":     58,
        "mom":     58,
        "struct":  68,
    },
}

# ── Timeframe Reliability Multipliers ─────────────────────────────────────────
TF_MULT = {
    "M5":  0.82,   # High noise, low reliability
    "M15": 0.91,   # Balanced
    "H1":  1.00,   # Baseline — most reliable of the 3
}

# ── Session Win Rate Bias ──────────────────────────────────────────────────────
# Format: (start_utc, end_utc, trend_mult, vol_mult, liq_mult, label)
SESSION_WINDOWS = {
    "GOLD": [
        (0,  2,  0.72, 0.65, 0.70, "DEAD ZONE"),
        (2,  7,  0.80, 0.70, 0.75, "ASIAN SESSION"),
        (7,  12, 1.05, 1.00, 1.00, "LONDON SESSION"),
        (12, 17, 1.22, 1.18, 1.22, "LONDON/NY OVERLAP"),   # PEAK
        (17, 22, 0.95, 1.05, 0.95, "NY SESSION"),
        (22, 24, 0.72, 0.68, 0.72, "DEAD ZONE"),
    ],
    "EURUSD": [
        (0,  7,  0.75, 0.70, 0.78, "ASIAN SESSION"),
        (7,  16, 1.22, 1.12, 1.22, "LONDON SESSION"),       # PEAK
        (16, 22, 0.90, 0.88, 0.90, "NY SESSION"),
        (22, 24, 0.72, 0.68, 0.72, "DEAD ZONE"),
    ],
    "BTC": [
        (0,  6,  0.85, 0.90, 0.80, "ASIAN SESSION"),
        (6,  14, 0.95, 1.00, 0.90, "LONDON SESSION"),
        (14, 22, 1.18, 1.12, 1.12, "NY SESSION"),           # PEAK
        (22, 24, 1.02, 1.05, 0.95, "LATE NY"),
    ],
    "NASDAQ": [
        (0,  13, 0.48, 0.48, 0.48, "PRE-MARKET"),
        (13, 14, 0.75, 0.80, 0.75, "PRE-OPEN"),
        (14, 21, 1.28, 1.22, 1.28, "US MARKET OPEN"),       # PEAK
        (21, 24, 0.62, 0.65, 0.62, "AFTER-HOURS"),
    ],
}

# ── Session Bias Score (from historical win rates) ─────────────────────────────
SESSION_BIAS_SCORE = {
    ("GOLD",   "LONDON/NY OVERLAP"): 95,
    ("GOLD",   "LONDON SESSION"):    85,
    ("GOLD",   "NY SESSION"):        78,
    ("GOLD",   "ASIAN SESSION"):     52,
    ("GOLD",   "DEAD ZONE"):         28,
    ("GOLD",   "LATE NY"):           35,
    ("EURUSD", "LONDON SESSION"):    92,
    ("EURUSD", "LONDON/NY OVERLAP"): 88,
    ("EURUSD", "NY SESSION"):        70,
    ("EURUSD", "ASIAN SESSION"):     42,
    ("EURUSD", "DEAD ZONE"):         25,
    ("BTC",    "NY SESSION"):        85,
    ("BTC",    "LONDON/NY OVERLAP"): 80,
    ("BTC",    "LONDON SESSION"):    72,
    ("BTC",    "ASIAN SESSION"):     68,   # BTC less session-dependent
    ("BTC",    "LATE NY"):           60,
    ("NASDAQ", "US MARKET OPEN"):    95,
    ("NASDAQ", "PRE-OPEN"):          45,
    ("NASDAQ", "PRE-MARKET"):        18,
    ("NASDAQ", "AFTER-HOURS"):       20,
}

# ── Score Label Table ──────────────────────────────────────────────────────────
SCORE_LABELS = [
    (85, 101, "STRONG",  "Strong Opportunity",  "#00ff9d", "🟢", "ALLOW_SCALE"),
    (70,  85, "GOOD",    "Good Conditions",     "#00e5ff", "🔵", "ALLOW"),
    (50,  70, "CAUTION", "Trade with Caution",  "#ffaa00", "🟡", "CAUTION"),
    (30,  50, "RISKY",   "Risky Conditions",    "#ff7700", "🟠", "WARN"),
    (0,   30, "AVOID",   "Avoid Trading",       "#ff4444", "🔴", "BLOCK"),
]

# ── Regime Labels ──────────────────────────────────────────────────────────────
STRATEGY_HINTS = {
    "STRONG_TREND":   "Strong trend momentum confirmed. Scale in on pullbacks, let winners run.",
    "TRENDING":       "Trend-following setups favored. Wait for pullback to key structure before entry.",
    "NEUTRAL":        "Mixed signals. Confirm with higher timeframe. Reduce position size.",
    "MEAN_REVERSION": "Range conditions. Fade extremes with tight stops. Avoid breakout entries.",
    "VOLATILE":       "High volatility detected. Widen stops significantly or stand aside.",
    "BREAKOUT_WATCH": "Compression detected. Watch for breakout — do not trade the range.",
    "UNCERTAIN":      "Conflicting signals. Wait for clarity before committing capital.",
}


@dataclass
class RadarResult:
    asset:          str
    timeframe:      str
    score:          int           # 0-100, integer (not 72.3 — see architecture doc §5.6)
    regime:         str
    label:          str
    label_text:     str
    color:          str
    emoji:          str
    gate:           str
    confidence:     str           # HIGH | MEDIUM | LOW
    breakdown: dict               # 4 sub-scores
    risk_notes:     List[str]
    strategy_hint:  str
    risk_level:     str           # LOW | MEDIUM | HIGH
    session:        str
    timestamp_utc:  str
    ttl_sec:        int


def _get_session(asset: str, hour_utc: int) -> tuple:
    """Returns (trend_mult, vol_mult, liq_mult, session_label)"""
    windows = SESSION_WINDOWS.get(asset, SESSION_WINDOWS["GOLD"])
    h = hour_utc % 24
    for (start, end, tm, vm, lm, label) in windows:
        if start <= h < end:
            return tm, vm, lm, label
    # fallback last window
    return windows[-1][2], windows[-1][3], windows[-1][4], windows[-1][5]


def _hourly_variance(asset: str, tf: str, hour_utc: int, date_str: str) -> int:
    """
    Deterministic ±5 jitter per (asset, tf, date, hour).
    Same input → same output within 1 hour.
    Makes score feel dynamic without being random.
    """
    key = f"{asset}{tf}{date_str}{hour_utc:02d}"
    h = int(hashlib.md5(key.encode()).hexdigest()[:4], 16)
    return (h % 11) - 5   # -5 to +5


def _classify_score(score: int) -> tuple:
    for (lo, hi, label, text, color, emoji, gate) in SCORE_LABELS:
        if lo <= score < hi:
            return label, text, color, emoji, gate
    return "AVOID", "Avoid Trading", "#ff4444", "🔴", "BLOCK"


def _classify_regime(score: int, trend: float, vol: float, struct: float) -> str:
    if score >= 85 and trend >= 82:
        return "STRONG_TREND"
    if score >= 70 and trend >= 72:
        return "TRENDING"
    if score < 30:
        return "VOLATILE" if vol < 40 else "MEAN_REVERSION"
    if struct >= 78 and 48 <= score < 70:
        return "BREAKOUT_WATCH"
    if 40 <= score < 70:
        return "NEUTRAL"
    # Detect contradiction: high trend but low vol or vice versa
    if abs(trend - vol) > 30:
        return "UNCERTAIN"
    return "NEUTRAL"


def _compute_confidence(tf: str, session_label: str, tm: float) -> str:
    if tf == "M5":
        return "LOW"
    if tm >= 1.10 and tf == "H1":
        return "HIGH"
    if tm >= 0.85:
        return "MEDIUM"
    return "LOW"


def _build_risk_notes(score: int, trend: float, vol: float, session: str,
                      asset: str, tf: str, regime: str) -> List[str]:
    notes = []

    # Session quality
    if "OVERLAP" in session or "PEAK" in session:
        notes.append(f"✅ {session} — peak liquidity window active")
    elif "DEAD" in session or "PRE-MARKET" in session or "AFTER" in session:
        notes.append(f"⚠ {session} — low liquidity, expect wider spreads")

    # Trend notes
    if trend >= 78:
        notes.append("✅ Trend persistence high — pullbacks are buying/selling opportunities")
    elif trend <= 42:
        notes.append("↔ Weak trend — mean reversion setups more effective than breakouts")

    # Volatility notes
    if vol >= 72:
        notes.append("⚠ Volatility elevated — widen stops, reduce position size")
    elif vol <= 35:
        notes.append("⚠ Volatility compressed — market may be squeezing before breakout")
    else:
        notes.append("✅ Volatility in optimal range for trend entries")

    # Asset-specific
    if asset == "BTC" and vol >= 70:
        notes.append("⚠ BTC high volatility — require minimum 1:2 risk/reward")
    if asset == "NASDAQ" and "PRE-MARKET" in session:
        notes.append("⚠ NASDAQ pre-market — avoid entries until US open (14:30 UTC)")
    if tf == "M5":
        notes.append("ℹ M5 generates noise — confirm direction on H1 before entry")

    # Regime-specific
    if regime == "BREAKOUT_WATCH":
        notes.append("👁 Market compressing — watch for breakout, do not trade the range")
    if regime == "UNCERTAIN":
        notes.append("⚡ Conflicting signals detected — wait for alignment")

    if not notes:
        notes.append("ℹ Standard market conditions — apply normal risk management")

    return notes[:4]   # Cap at 4 notes for clean UX


def _risk_level(score: int, vol: float) -> str:
    if score >= 70 and vol <= 70:
        return "LOW"
    if score >= 50 or vol <= 65:
        return "MEDIUM"
    return "HIGH"


def compute(asset: str, timeframe: str) -> RadarResult:
    """
    Main entry point. Pure function — no I/O.

    Args:
        asset:     "GOLD" | "EURUSD" | "BTC" | "NASDAQ"
        timeframe: "M5" | "M15" | "H1"

    Returns:
        RadarResult dataclass with all fields populated.

    Raises:
        ValueError if asset or timeframe is unsupported.
    """
    if asset not in ASSET_PROFILES:
        raise ValueError(f"Unsupported asset: {asset}. Supported: {list(ASSET_PROFILES)}")
    if timeframe not in TF_MULT:
        raise ValueError(f"Unsupported timeframe: {timeframe}. Supported: {list(TF_MULT)}")

    now      = datetime.now(timezone.utc)
    h_utc    = now.hour
    date_str = now.strftime("%Y%m%d")
    tf_mult  = TF_MULT[timeframe]
    profile  = ASSET_PROFILES[asset]

    # Session context
    tm, vm, lm, session_label = _get_session(asset, h_utc)

    # ── Sub-scores ─────────────────────────────────────────────────────────────
    # Component 1: Trend Strength (35%)
    trend = min(100.0, profile["trend"] * tm * tf_mult)

    # Component 2: Volatility Quality (25%)
    # "Quality" not "Level" — optimal zone centered around baseline
    raw_vol = profile["vol"] * vm
    if 45 <= raw_vol <= 72:
        vol = min(100.0, raw_vol * 1.15)    # bonus for optimal zone
    elif raw_vol < 35:
        vol = raw_vol / 35 * 60             # too quiet
    else:
        vol = max(0, min(100, 100 - (raw_vol - 72) * 1.5))  # too noisy

    # Component 3: Session Bias (20%)
    session_bias = SESSION_BIAS_SCORE.get((asset, session_label), 50)

    # Component 4: Market Structure (20%)
    struct_tf = {"H1": 85, "M15": 70, "M5": 45}[timeframe]
    struct_asset = {"GOLD": 10, "EURUSD": 15, "BTC": -5, "NASDAQ": 5}[asset]
    struct = min(100.0, max(0.0, struct_tf + struct_asset))

    # ── Weighted Formula ────────────────────────────────────────────────────────
    raw_score = (
        0.35 * trend
      + 0.25 * vol
      + 0.20 * session_bias
      + 0.20 * struct
    )

    # Jitter ±5 — deterministic within 1 hour
    jitter   = _hourly_variance(asset, timeframe, h_utc, date_str)
    score    = int(max(0, min(100, round(raw_score + jitter))))

    # ── Classification ──────────────────────────────────────────────────────────
    regime       = _classify_regime(score, trend, vol, struct)
    label, label_text, color, emoji, gate = _classify_score(score)
    confidence   = _compute_confidence(timeframe, session_label, tm)
    risk_notes   = _build_risk_notes(score, trend, vol, session_label, asset, timeframe, regime)
    strategy     = STRATEGY_HINTS.get(regime, STRATEGY_HINTS["NEUTRAL"])
    risk_lvl     = _risk_level(score, vol)

    return RadarResult(
        asset         = asset,
        timeframe     = timeframe,
        score         = score,
        regime        = regime,
        label         = label,
        label_text    = label_text,
        color         = color,
        emoji         = emoji,
        gate          = gate,
        confidence    = confidence,
        breakdown     = {
            "trend_strength":    round(trend,        1),
            "volatility_quality": round(vol,         1),
            "session_bias":      round(session_bias, 1),
            "market_structure":  round(struct,       1),
        },
        risk_notes    = risk_notes,
        strategy_hint = strategy,
        risk_level    = risk_lvl,
        session       = session_label,
        timestamp_utc = now.isoformat(),
        ttl_sec       = 600,
    )


def compute_all() -> dict:
    """
    Compute score cho tất cả 12 combinations (4 assets × 3 TF).
    Dùng cho /radar/feed endpoint và daily digest email.
    """
    results = {}
    for asset in ASSET_PROFILES:
        results[asset] = {}
        for tf in TF_MULT:
            try:
                r = compute(asset, tf)
                results[asset][tf] = {
                    "score":    r.score,
                    "regime":   r.regime,
                    "label":    r.label,
                    "emoji":    r.emoji,
                    "color":    r.color,
                    "session":  r.session,
                    "strategy": r.strategy_hint,
                }
            except Exception as e:
                logger.error(f"compute_all error {asset}/{tf}: {e}")
    return results
