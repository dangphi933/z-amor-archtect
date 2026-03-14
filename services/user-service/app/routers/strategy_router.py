"""
app/routers/strategy_router.py
================================
Strategy selection — extract từ api/strategy_router.py monolith.
Trader chọn preset S1/S2/S3 → EA nhận qua heartbeat.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..core.database import SessionLocal, License
from shared.libs.security.jwt_utils import require_jwt

router = APIRouter(tags=["strategy"])

# ── Strategy presets (extract từ strategy_presets.py monolith) ───
STRATEGY_PRESETS = [
    {
        "strategy_id":      "S1",
        "profile_name":     "Gold_Trend_H1",
        "description":      "Trend-following trên XAUUSD H1. Phù hợp London/NY session.",
        "color":            "#FFD700",
        "symbols_hint":     "XAUUSDm, XAUUSD",
        "entry_type":       "BREAKOUT",
        "min_score_entry":  70,
        "rr_ratio":         2.0,
        "risk_mode":        "HALF_KELLY",
        "session_filter":   ["LONDON", "NY", "LONDON_NY_OVERLAP"],
        "trailing_sl":      True,
    },
    {
        "strategy_id":      "S2",
        "profile_name":     "FX_Range_H1",
        "description":      "Mean-reversion trên EURUSD/GBPUSD H1. Fade extreme moves.",
        "color":            "#2E75B6",
        "symbols_hint":     "EURUSDm, GBPUSDm",
        "entry_type":       "FADE",
        "min_score_entry":  50,
        "rr_ratio":         1.5,
        "risk_mode":        "FIXED_PCT",
        "session_filter":   ["LONDON", "LONDON_NY_OVERLAP"],
        "trailing_sl":      False,
    },
    {
        "strategy_id":      "S3",
        "profile_name":     "Scalp_Session_M15",
        "description":      "Scalping M15 trong session overlap. High frequency, tight SL.",
        "color":            "#17A89C",
        "symbols_hint":     "XAUUSDm, EURUSDm, NAS100m",
        "entry_type":       "MOMENTUM",
        "min_score_entry":  60,
        "rr_ratio":         1.2,
        "risk_mode":        "MICRO",
        "session_filter":   ["LONDON_NY_OVERLAP"],
        "trailing_sl":      True,
    },
]

_PRESET_MAP = {p["strategy_id"]: p for p in STRATEGY_PRESETS}


class SelectStrategyReq(BaseModel):
    license_key: str
    strategy_id: str


@router.get("/presets")
def list_presets():
    """Danh sách tất cả strategy presets."""
    return {"presets": STRATEGY_PRESETS}


@router.get("/active")
def get_active_strategy(license_key: str):
    """Strategy đang active của license."""
    db = SessionLocal()
    try:
        lic = db.query(License).filter(License.license_key == license_key).first()
        if not lic:
            raise HTTPException(404, "License không tìm thấy.")
        strategy_id = lic.strategy_id or "S1"
        preset = _PRESET_MAP.get(strategy_id, _PRESET_MAP["S1"])
        return {"license_key": license_key, "strategy_id": strategy_id, "preset": preset}
    finally:
        db.close()


@router.post("/select")
def select_strategy(req: SelectStrategyReq, payload: dict = require_jwt):
    """Trader chọn strategy — ghi vào license.strategy_id."""
    if req.strategy_id not in _PRESET_MAP:
        raise HTTPException(400, f"Strategy ID không hợp lệ: {req.strategy_id}. Dùng: S1, S2, S3")

    email = payload.get("sub", "")
    db = SessionLocal()
    try:
        lic = db.query(License).filter(
            License.license_key == req.license_key,
            License.buyer_email == email,
        ).first()
        if not lic:
            raise HTTPException(404, "License không tìm thấy hoặc không thuộc account này.")

        lic.strategy_id = req.strategy_id
        db.commit()

        preset = _PRESET_MAP[req.strategy_id]
        return {
            "ok":           True,
            "strategy_id":  req.strategy_id,
            "profile_name": preset["profile_name"],
            "message":      f"Strategy {preset['profile_name']} đã được chọn. EA sẽ nhận khi heartbeat tiếp theo.",
        }
    finally:
        db.close()
