"""
api/growth_router.py — Sprint 5
Growth Loop: Referral engine + Remarketing automation
  GET  /growth/referral-link   — share link + stats
  POST /growth/track-referral  — track visitor từ ref link
  GET  /growth/k-factor        — admin K-factor analytics
"""
import os, uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from auth import require_auth
from database import SessionLocal

router = APIRouter(tags=["growth"])


@router.get("/referral-link")
async def get_referral_link(ctx: dict = Depends(require_auth)):
    from sqlalchemy import text
    ref_code = ctx.get("ref_code","")
    if not ref_code:
        # Generate one if missing
        from api.identity_router import _ensure_identity_tables
        import secrets
        db = SessionLocal()
        try:
            ref_code = secrets.token_hex(4).upper()
            db.execute(text("UPDATE za_users SET ref_code=:rc WHERE id=:uid AND ref_code IS NULL"),
                       {"rc":ref_code,"uid":ctx.get("sub")})
            db.commit()
        except Exception: db.rollback()
        finally: db.close()

    base_url = os.getenv("NEW_BACKEND_URL","http://47.129.1.31:8000")
    return {
        "ref_code":   ref_code,
        "share_link": f"{base_url}/scan?ref={ref_code}",
        "share_text": f"Tôi vừa scan thị trường với Z-ARMOR Radar — tool AI regime detection miễn phí. Thử ngay: {base_url}/scan?ref={ref_code}",
    }


class TrackRefReq(BaseModel):
    ref_code: str
    asset:    Optional[str] = None

@router.post("/track-referral")
async def track_referral(req: TrackRefReq, request: Request, bg: BackgroundTasks):
    ip = request.client.host if request.client else "unknown"
    bg.add_task(_track_ref_bg, req.ref_code, req.asset or "", ip)
    return {"tracked": True}


def _track_ref_bg(ref_code, asset, ip):
    try:
        import redis as _redis
        r = _redis.from_url(os.getenv("REDIS_URL","redis://127.0.0.1:6379/0"))
        key = f"ref_track:{ip}:{ref_code}"
        if r.exists(key): return
        r.setex(key, 86400, "1")
    except Exception: pass
    from sqlalchemy import text
    db = SessionLocal()
    try:
        row = db.execute(text("SELECT id FROM za_users WHERE ref_code=:rc"),{"rc":ref_code}).fetchone()
        db.execute(text("""
            INSERT INTO referral_events (id,ref_code,referrer_user_id,asset,ip)
            VALUES (:id,:rc,:rid,:asset,:ip)
        """),{"id":str(uuid.uuid4()),"rc":ref_code,"rid":row[0] if row else None,"asset":asset,"ip":ip})
        db.commit()
    except Exception: db.rollback()
    finally: db.close()


@router.get("/k-factor")
async def get_k_factor(ctx: dict = Depends(require_auth)):
    """Admin: K-factor analytics toàn hệ thống."""
    if ctx.get("scope") not in ("cockpit", "admin"):
        from fastapi import HTTPException
        raise HTTPException(403, "Forbidden")
    from sqlalchemy import text
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT
              COUNT(*) as total_events,
              COUNT(*) FILTER (WHERE converted=TRUE) as total_conversions,
              COUNT(DISTINCT ref_code) as active_referrers
            FROM referral_events
            WHERE created_at >= NOW() - INTERVAL '30 days'
        """)).fetchone()
        total_scans = db.execute(text("""
            SELECT COUNT(*) FROM radar_scans
            WHERE created_at >= NOW() - INTERVAL '30 days'
        """)).fetchone()[0]
        events = row[0] or 0
        convs  = row[1] or 0
        k = round(convs / max(1, events), 3)
        return {
            "period": "last_30_days",
            "total_referral_events": events,
            "total_conversions": convs,
            "active_referrers": row[2] or 0,
            "k_factor": k,
            "total_scans": total_scans,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()