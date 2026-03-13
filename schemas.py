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
