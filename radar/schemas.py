"""radar/schemas.py — Pydantic models for Radar Scan API"""
from pydantic import BaseModel, field_validator
from typing import Optional, List
from enum import Enum


class AssetEnum(str, Enum):
    GOLD   = "GOLD"
    EURUSD = "EURUSD"
    BTC    = "BTC"
    NASDAQ = "NASDAQ"


class TimeframeEnum(str, Enum):
    M5  = "M5"
    M15 = "M15"
    H1  = "H1"


class RadarScanRequest(BaseModel):
    asset:       AssetEnum
    timeframe:   TimeframeEnum
    email:       Optional[str] = None
    send_report: bool = False

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if v and "@" not in v:
            raise ValueError("Invalid email format")
        return v.lower().strip() if v else None


class BreakdownOut(BaseModel):
    trend_strength:     float
    volatility_quality: float
    session_bias:       float
    market_structure:   float
    # Phase 1.5: live data fields — None khi fallback
    data_source:  Optional[str]  = None   # "live" | "cache" | "fallback"
    adx_live:     Optional[float] = None
    rsi_live:     Optional[float] = None
    atr_pct_live: Optional[float] = None


class RadarScanResponse(BaseModel):
    scan_id:       str
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
    breakdown:     BreakdownOut
    risk_notes:    List[str]
    strategy_hint: str
    risk_level:    str
    session:       str
    cta_url:       str
    share_url:     str
    report_queued: bool
    timestamp_utc: str
    ttl_sec:       int
    # ── EA-actionable fields (Sprint C-1) ──────────────────────────────────────
    # Tất cả fields dưới đây được tính bởi engine._ea_params() — single source of truth.
    # state_cap values: SCALE | OPTIMAL | REDUCED | MINIMAL | BLOCKED
    #   SCALE    → score 85+, gate=ALLOW_SCALE, position_pct=125
    #   OPTIMAL  → score 70-84, gate=ALLOW, position_pct=60-100
    #   REDUCED  → score 50-69, gate=CAUTION, position_pct=30-60
    #   MINIMAL  → score 30-49, gate=WARN, position_pct=20-30
    #   BLOCKED  → score<30, gate=BLOCK, allow_trade=False, position_pct=0
    allow_trade:   bool  = True
    position_pct:  int   = 100   # % of normal size (0-125)
    sl_multiplier: float = 1.0   # ATR multiplier for SL distance
    state_cap:     str   = "OPTIMAL"
    ml_boost:      Optional[float] = None  # Sprint D: ML confidence boost (+0.10/+0.15)