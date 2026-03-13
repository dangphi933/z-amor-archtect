"""
api/radar_crm_router.py
=======================
Z-ARMOR Radar CRM — Growth Loop Endpoints

Endpoints:
  POST /api/email-capture      ← RadarAlertSystem.captureEmail()   [scan.html gate]
  POST /api/subscribe-alert    ← RadarAlertSystem.subscribe()      [alert panel]
  POST /api/track-share        ← RadarShareSystem.trackShare()     [share buttons]
  POST /api/radar-apply        ← Apply radar config to EA account  [apply modal]
  GET  /api/crm/leads          ← Admin: danh sách leads            [admin only]
  GET  /api/crm/alerts         ← Admin: danh sách subscriptions    [admin only]
  GET  /api/crm/stats          ← Admin: growth loop metrics        [admin only]

Mount trong main.py:
  from api.radar_crm_router import router as radar_crm_router
  app.include_router(radar_crm_router)
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db

logger = logging.getLogger("zarmor.radar_crm")
router = APIRouter(prefix="/api", tags=["Radar CRM"])

# ── Config từ .env (dùng chung với main.py) ───────────────────────────────────
BASE_URL         = os.environ.get("NEW_BACKEND_URL",   "http://47.129.243.206:8000")
LARK_APP_ID      = os.environ.get("LARK_APP_ID",       "cli_a92af9524c789e1a")
LARK_APP_SECRET  = os.environ.get("LARK_APP_SECRET",   "")
LARK_BASE_TOKEN  = os.environ.get("LARK_BASE_TOKEN",   "lpl2bYwliawcO8s5ddOj1s58pcf")
LARK_CRM_TABLE  = os.environ.get("LARK_CRM_TABLE_ID",  "")   # Set trong .env để push leads lên Lark
LARK_BOT_WEBHOOK = os.environ.get("LARK_BOT_WEBHOOK",  "")
ADMIN_TOKEN      = os.environ.get("LICENSE_ADMIN_TOKEN","")
TG_BOT_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN","")
TG_ALERT_CHAT    = os.environ.get("RADAR_ALERT_CHAT_ID","")   # Chat ID nhận alert nội bộ


# ══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ══════════════════════════════════════════════════════════════════════════════

class EmailCapturePayload(BaseModel):
    email:              str
    asset_interest:     Optional[str] = ""
    timeframe_interest: Optional[str] = "H1"
    source:             Optional[str] = "radar_scan_gate"
    captured_at:        Optional[str] = None

class SubscribeAlertPayload(BaseModel):
    email:        str
    asset:        str
    timeframe:    Optional[str] = "H1"
    channel:      Optional[str] = "email"       # "email" | "telegram"
    subscribed_at: Optional[str] = None

class TrackSharePayload(BaseModel):
    asset:     str
    channel:   str                               # "twitter" | "telegram" | "copy"
    timestamp: Optional[str] = None

class RadarApplyPayload(BaseModel):
    asset:     str
    timeframe: str
    score:     int
    regime:    Optional[str] = ""
    email:     Optional[str] = ""
    timestamp: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _log(tag: str, data: dict):
    print(f"[{tag}] {json.dumps(data, ensure_ascii=False)}", flush=True)

def _check_admin(request: Request):
    token = request.headers.get("X-Admin-Token", "")
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── DB helpers — tạo table nếu chưa có ──────────────────────────────────────
def _ensure_tables(db: Session):
    """Tự tạo 3 table CRM nếu chưa tồn tại (PostgreSQL + SQLite compatible)."""
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS radar_leads (
                id          SERIAL PRIMARY KEY,
                email       TEXT NOT NULL,
                asset       TEXT,
                timeframe   TEXT,
                source      TEXT DEFAULT 'radar_scan_gate',
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS radar_alert_subs (
                id           SERIAL PRIMARY KEY,
                email        TEXT NOT NULL,
                asset        TEXT NOT NULL,
                timeframe    TEXT DEFAULT 'H1',
                channel      TEXT DEFAULT 'email',
                active       BOOLEAN DEFAULT TRUE,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS radar_share_events (
                id         SERIAL PRIMARY KEY,
                asset      TEXT,
                channel    TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        logger.warning(f"[CRM] ensure_tables warning: {e}")
        db.rollback()


# ── Lark CRM push (background task) ─────────────────────────────────────────
async def _push_lead_to_lark(email: str, asset: str, timeframe: str, source: str):
    """Push lead mới lên Lark Bitable CRM table."""
    if not LARK_CRM_TABLE or not LARK_APP_SECRET:
        return
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # Lấy tenant token
            r = await client.post(
                "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}
            )
            token = r.json().get("tenant_access_token")
            if not token:
                return

            # Ghi record
            url = (
                f"https://open.larksuite.com/open-apis/bitable/v1"
                f"/apps/{LARK_BASE_TOKEN}/tables/{LARK_CRM_TABLE}/records"
            )
            await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"fields": {
                    "Email":     email,
                    "Asset":     asset,
                    "Timeframe": timeframe,
                    "Source":    source,
                    "Time":      _now_utc(),
                }}
            )
            logger.info(f"[CRM] Lark lead pushed: {email} {asset}")
    except Exception as e:
        logger.warning(f"[CRM] Lark push failed: {e}")


# ── Telegram nội bộ notify ───────────────────────────────────────────────────
async def _notify_internal(message: str):
    """Gửi thông báo lead mới lên Telegram nội bộ (RADAR_ALERT_CHAT_ID)."""
    if not TG_BOT_TOKEN or not TG_ALERT_CHAT:
        return
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": TG_ALERT_CHAT, "text": message, "parse_mode": "HTML"}
            )
    except Exception as e:
        logger.warning(f"[CRM] TG notify failed: {e}")


# ── Lark Bot webhook log ─────────────────────────────────────────────────────
async def _lark_bot_log(message: str):
    if not LARK_BOT_WEBHOOK:
        return
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            await client.post(
                LARK_BOT_WEBHOOK,
                headers={"Content-Type": "application/json"},
                json={"msg_type": "text", "content": {"text": f"[RADAR CRM]\n{message}"}}
            )
    except Exception as e:
        logger.warning(f"[CRM] Lark bot log failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

# ── POST /api/email-capture ───────────────────────────────────────────────────
@router.post("/email-capture")
async def email_capture(
    payload: EmailCapturePayload,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Được gọi bởi RadarAlertSystem.captureEmail() ngay khi user bấm Scan.
    Build trader CRM — lưu email + asset interest.
    """
    captured_at = payload.captured_at or _now_utc()
    data = {
        "email":     payload.email,
        "asset":     payload.asset_interest or "",
        "timeframe": payload.timeframe_interest or "H1",
        "source":    payload.source or "radar_scan_gate",
    }
    _log("EMAIL_CAPTURE", {**data, "captured_at": captured_at})

    # ── Lưu DB ──
    _ensure_tables(db)
    try:
        # Upsert: nếu email + asset đã tồn tại trong 24h thì không ghi thêm
        existing = db.execute(text("""
            SELECT id FROM radar_leads
            WHERE email = :email AND asset = :asset
              AND created_at > NOW() - INTERVAL '24 hours'
            LIMIT 1
        """), {"email": data["email"], "asset": data["asset"]}).fetchone()

        if not existing:
            db.execute(text("""
                INSERT INTO radar_leads (email, asset, timeframe, source)
                VALUES (:email, :asset, :timeframe, :source)
            """), data)
            db.commit()

            # ── Background tasks (không block response) ──
            bg.add_task(
                _push_lead_to_lark,
                data["email"], data["asset"], data["timeframe"], data["source"]
            )
            bg.add_task(
                _notify_internal,
                f"🎯 <b>NEW LEAD</b>\n"
                f"📧 {data['email']}\n"
                f"💰 Asset: {data['asset']} {data['timeframe']}\n"
                f"📌 Source: {data['source']}"
            )
    except Exception as e:
        logger.warning(f"[EMAIL_CAPTURE] DB error: {e}")
        db.rollback()

    return {"ok": True, "message": "Captured"}


# ── POST /api/subscribe-alert ─────────────────────────────────────────────────
@router.post("/subscribe-alert")
async def subscribe_alert(
    payload: SubscribeAlertPayload,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Được gọi bởi RadarAlertSystem.subscribe() từ alert panel.
    Lưu subscription — sau này kết nối Telegram alert bot.

    Payload: { email, asset, timeframe, channel }
    """
    subscribed_at = payload.subscribed_at or _now_utc()
    data = {
        "email":     payload.email,
        "asset":     payload.asset.upper(),
        "timeframe": (payload.timeframe or "H1").upper(),
        "channel":   payload.channel or "email",
    }
    _log("SUBSCRIBE_ALERT", {**data, "subscribed_at": subscribed_at})

    # ── Lưu DB ──
    _ensure_tables(db)
    try:
        # Tránh duplicate: 1 email + asset + channel chỉ sub 1 lần
        existing = db.execute(text("""
            SELECT id FROM radar_alert_subs
            WHERE email = :email AND asset = :asset AND channel = :channel AND active = TRUE
            LIMIT 1
        """), {"email": data["email"], "asset": data["asset"], "channel": data["channel"]}).fetchone()

        if not existing:
            db.execute(text("""
                INSERT INTO radar_alert_subs (email, asset, timeframe, channel)
                VALUES (:email, :asset, :timeframe, :channel)
            """), data)
            db.commit()
            is_new = True
        else:
            is_new = False

        if is_new:
            bg.add_task(
                _notify_internal,
                f"🔔 <b>NEW ALERT SUB</b>\n"
                f"📧 {data['email']}\n"
                f"💰 {data['asset']} {data['timeframe']}\n"
                f"📡 Channel: {data['channel']}"
            )
            bg.add_task(
                _lark_bot_log,
                f"ALERT SUB | {data['email']} | {data['asset']} {data['timeframe']} | {data['channel']}"
            )

    except Exception as e:
        logger.warning(f"[SUBSCRIBE_ALERT] DB error: {e}")
        db.rollback()

    return {"ok": True, "message": "Đăng ký thành công!"}


# ── POST /api/track-share ─────────────────────────────────────────────────────
@router.post("/track-share")
async def track_share(
    payload: TrackSharePayload,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Được gọi bởi RadarShareSystem.trackShare() sau mỗi lần share.
    Đo viral coefficient: bao nhiêu user share → bao nhiêu lead mới.
    """
    data = {
        "asset":   payload.asset.upper(),
        "channel": payload.channel,
    }
    _log("TRACK_SHARE", {**data, "timestamp": payload.timestamp or _now_utc()})

    _ensure_tables(db)
    try:
        db.execute(text("""
            INSERT INTO radar_share_events (asset, channel)
            VALUES (:asset, :channel)
        """), data)
        db.commit()
    except Exception as e:
        logger.warning(f"[TRACK_SHARE] DB error: {e}")
        db.rollback()

    return {"ok": True}


# ── POST /api/radar-apply ─────────────────────────────────────────────────────
@router.post("/radar-apply")
async def radar_apply(
    payload: RadarApplyPayload,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Được gọi khi user bấm 'ÁP DỤNG VÀO TÀI KHOẢN' trong apply modal.
    Ghi log + notify nội bộ. Thực tế sync sang EA qua heartbeat.
    """
    data = {
        "asset":     payload.asset.upper(),
        "timeframe": payload.timeframe.upper(),
        "score":     payload.score,
        "regime":    (payload.regime or "").replace("_", " "),
        "email":     payload.email or "",
        "timestamp": payload.timestamp or _now_utc(),
    }
    _log("RADAR_APPLY", data)

    # Notify nội bộ
    score = payload.score
    pos_size = "100%" if score >= 70 else "60%" if score >= 50 else "30%"
    bg.add_task(
        _notify_internal,
        f"⚡ <b>EA APPLY REQUEST</b>\n"
        f"📧 {data['email'] or 'anonymous'}\n"
        f"💰 {data['asset']} {data['timeframe']} — Score {score}/100\n"
        f"📊 Regime: {data['regime']}\n"
        f"📏 Position size: {pos_size}"
    )

    return {"ok": True, "message": "Đã ghi nhận — EA sẽ đồng bộ trong heartbeat tiếp theo."}


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS  (Header: X-Admin-Token required)
# ══════════════════════════════════════════════════════════════════════════════

# ── GET /api/crm/leads ────────────────────────────────────────────────────────
@router.get("/crm/leads")
async def crm_leads(
    request: Request,
    limit: int = 100,
    asset: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Admin: danh sách leads từ email gate."""
    _check_admin(request)
    _ensure_tables(db)
    try:
        query = "SELECT * FROM radar_leads"
        params: dict = {"limit": limit}
        if asset:
            query += " WHERE asset = :asset"
            params["asset"] = asset.upper()
        query += " ORDER BY created_at DESC LIMIT :limit"
        rows = db.execute(text(query), params).fetchall()
        return {
            "count": len(rows),
            "leads": [dict(r._mapping) for r in rows],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ── GET /api/crm/alerts ───────────────────────────────────────────────────────
@router.get("/crm/alerts")
async def crm_alerts(
    request: Request,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Admin: danh sách alert subscriptions."""
    _check_admin(request)
    _ensure_tables(db)
    try:
        rows = db.execute(text("""
            SELECT * FROM radar_alert_subs
            WHERE active = TRUE
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
        return {
            "count": len(rows),
            "subscriptions": [dict(r._mapping) for r in rows],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ── GET /api/crm/stats ────────────────────────────────────────────────────────
@router.get("/crm/stats")
async def crm_stats(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Admin: Growth Loop metrics.
    Dùng để đo viral coefficient và conversion funnel.
    """
    _check_admin(request)
    _ensure_tables(db)
    try:
        total_leads    = db.execute(text("SELECT COUNT(*) FROM radar_leads")).scalar() or 0
        leads_24h      = db.execute(text(
            "SELECT COUNT(*) FROM radar_leads WHERE created_at > NOW() - INTERVAL '24 hours'"
        )).scalar() or 0
        total_subs     = db.execute(text(
            "SELECT COUNT(*) FROM radar_alert_subs WHERE active = TRUE"
        )).scalar() or 0
        total_shares   = db.execute(text("SELECT COUNT(*) FROM radar_share_events")).scalar() or 0
        shares_24h     = db.execute(text(
            "SELECT COUNT(*) FROM radar_share_events WHERE created_at > NOW() - INTERVAL '24 hours'"
        )).scalar() or 0

        # Shares per channel
        channel_rows = db.execute(text("""
            SELECT channel, COUNT(*) as cnt
            FROM radar_share_events
            GROUP BY channel ORDER BY cnt DESC
        """)).fetchall()

        # Top assets by lead count
        asset_rows = db.execute(text("""
            SELECT asset, COUNT(*) as cnt
            FROM radar_leads
            GROUP BY asset ORDER BY cnt DESC LIMIT 5
        """)).fetchall()

        # Viral coefficient: shares / leads (ratio > 1 = virality)
        viral_coeff = round(total_shares / total_leads, 2) if total_leads > 0 else 0.0

        return {
            "growth_loop": {
                "total_leads":     total_leads,
                "leads_24h":       leads_24h,
                "total_subs":      total_subs,
                "total_shares":    total_shares,
                "shares_24h":      shares_24h,
                "viral_coefficient": viral_coeff,
            },
            "shares_by_channel": {r[0]: r[1] for r in channel_rows},
            "top_assets":        {r[0]: r[1] for r in asset_rows},
            "note": "viral_coefficient = shares / leads — target > 1.5 for organic growth",
        }
    except Exception as e:
        raise HTTPException(500, str(e))