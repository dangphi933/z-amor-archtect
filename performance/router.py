"""
performance/router.py — Phase 2 Performance Attribution API
============================================================

Endpoints:
  GET  /performance/{account_id}           — Full attribution (tính mới)
  GET  /performance/{account_id}/snapshot  — Snapshot nhanh từ DB cache
  GET  /performance/{account_id}/chart     — Daily returns cho biểu đồ
  POST /performance/batch-compute          — Trigger tính cho nhiều accounts
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from database import get_db
from .service import compute_performance, get_latest_snapshot

logger = logging.getLogger("zarmor.performance")
router = APIRouter(tags=["Performance"])


# ── GET /performance/{account_id} ─────────────────────────────────────────────
@router.get("/{account_id}")
async def get_performance(
    account_id: str,
    period:     int  = Query(30, ge=7, le=365, description="Số ngày nhìn lại"),
    refresh:    bool = Query(False, description="True = tính lại, False = dùng cache"),
):
    """
    Full performance attribution cho account.
    Mặc định dùng snapshot từ DB nếu < 6h tuổi.
    refresh=true → tính lại ngay.
    """
    if not refresh:
        snap = get_latest_snapshot(account_id, period)
        if snap:
            computed_at = snap.get("computed_at")
            if computed_at:
                age_hours = (datetime.now(timezone.utc) - computed_at).total_seconds() / 3600
                if age_hours < 6:
                    snap["_from_cache"] = True
                    snap["_cache_age_hours"] = round(age_hours, 1)
                    return snap

    result = compute_performance(account_id, period)
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


# ── GET /performance/{account_id}/snapshot ────────────────────────────────────
@router.get("/{account_id}/snapshot")
async def get_snapshot(
    account_id: str,
    period:     int = Query(30, ge=7, le=365),
):
    """Trả về snapshot cũ nhất từ DB — nhanh, không tính lại."""
    snap = get_latest_snapshot(account_id, period)
    if not snap:
        raise HTTPException(404, "No snapshot found. Call GET /{account_id}?refresh=true first.")
    return snap


# ── GET /performance/{account_id}/chart ───────────────────────────────────────
@router.get("/{account_id}/chart")
async def get_chart_data(
    account_id: str,
    period:     int = Query(30, ge=7, le=365),
):
    """
    Daily returns + cumulative equity curve cho frontend chart.
    Format sẵn cho Chart.js / Recharts.
    """
    snap = get_latest_snapshot(account_id, period)
    if not snap:
        raise HTTPException(404, "No snapshot found.")

    import json
    daily = snap.get("daily_returns")
    if isinstance(daily, str):
        daily = json.loads(daily)
    daily = daily or []

    # Build cumulative curve
    cumulative = []
    cum = 0.0
    for i, r in enumerate(daily):
        cum += r
        cumulative.append({"day": i + 1, "return_pct": round(r, 3), "cumulative_pct": round(cum, 3)})

    return {
        "account_id": account_id,
        "period":     period,
        "points":     len(cumulative),
        "series":     cumulative,
        "total_return_pct": round(cum, 2),
    }


# ── POST /performance/batch-compute ───────────────────────────────────────────
@router.post("/batch-compute")
async def batch_compute(
    account_ids: list[str],
    period:      int = Query(30, ge=7, le=365),
):
    """
    Trigger tính performance cho nhiều accounts.
    Dùng trong nightly cron / manual refresh.
    """
    if len(account_ids) > 50:
        raise HTTPException(400, "Max 50 accounts per batch.")

    results = {}
    for acc in account_ids:
        try:
            r = compute_performance(acc, period)
            results[acc] = {
                "status":  "ok" if "error" not in r else "error",
                "sharpe":  r.get("sharpe"),
                "calmar":  r.get("calmar"),
                "max_dd":  r.get("max_drawdown"),
                "win_rate": r.get("win_rate"),
            }
        except Exception as e:
            results[acc] = {"status": "error", "detail": str(e)}

    ok    = sum(1 for v in results.values() if v["status"] == "ok")
    error = len(results) - ok
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "total": len(account_ids), "ok": ok, "errors": error,
        "results": results,
    }
