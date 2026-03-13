"""
api/billing_router.py — Z-ARMOR CLOUD
Sprint 3: Billing Portal (Self-serve)
  GET  /billing/portal     — overview: tier, usage, renewal
  GET  /billing/invoices   — lịch sử invoices
  POST /billing/upgrade    — request upgrade tier
  POST /billing/cancel     — cancel flow
"""
import os, uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from auth_service import require_auth
from database import SessionLocal

router = APIRouter(tags=["billing"])

TIER_PRICES = {
    "TRIAL":   0,
    "ARMOR":   29,
    "ARSENAL": 79,
    "FLEET":   199,
}

TIER_FEATURES = {
    "TRIAL":   {"scans": 50,    "accounts": 1,  "alerts": "Telegram only"},
    "ARMOR":   {"scans": 500,   "accounts": 3,  "alerts": "Telegram + Email"},
    "ARSENAL": {"scans": 2000,  "accounts": 10, "alerts": "All channels"},
    "FLEET":   {"scans": 99999, "accounts": -1, "alerts": "All + Priority"},
}


def _ensure_billing_tables():
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS za_invoices (
                id             VARCHAR(36) PRIMARY KEY,
                invoice_number VARCHAR(30) UNIQUE NOT NULL,
                owner_email    VARCHAR(200) NOT NULL,
                license_key    VARCHAR(60),
                amount_usd     FLOAT DEFAULT 0,
                status         VARCHAR(20) DEFAULT 'PENDING',
                tier           VARCHAR(20),
                description    TEXT,
                period_start   TIMESTAMPTZ,
                period_end     TIMESTAMPTZ,
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )"""))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_za_inv_email ON za_invoices(owner_email)"))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[BILLING] Table init warning: {e}", flush=True)
    finally:
        db.close()


@router.get("/portal")
async def billing_portal(ctx: dict = Depends(require_auth)):
    """Full billing overview."""
    from sqlalchemy import text
    from datetime import date
    email = ctx.get("email","")
    tier  = ctx.get("tier","TRIAL")
    db = SessionLocal()
    try:
        lic = db.execute(text("""
            SELECT license_key,tier,expires_at,status,is_trial,created_at
            FROM license_keys WHERE buyer_email=:e
            ORDER BY created_at DESC LIMIT 1
        """),{"e":email}).fetchone()

        # Scan usage today
        today = date.today().isoformat()
        scan_row = db.execute(text("""
            SELECT COUNT(*) FROM radar_scans
            WHERE user_id=:uid AND DATE(created_at)=:today
        """),{"uid":ctx.get("sub",""),"today":today}).fetchone()
        scans_today = scan_row[0] if scan_row else 0

        quota = TIER_FEATURES.get(tier, TIER_FEATURES["TRIAL"])
        next_tier = {"TRIAL":"ARMOR","ARMOR":"ARSENAL","ARSENAL":"FLEET"}.get(tier)

        expires_at = None
        days_remaining = None
        if lic and lic[2]:
            exp = lic[2].replace(tzinfo=timezone.utc) if lic[2].tzinfo is None else lic[2]
            expires_at = exp.isoformat()
            days_remaining = max(0, (exp - datetime.now(timezone.utc)).days)

        return {
            "email": email,
            "tier":  tier,
            "tier_features": quota,
            "scan_usage": {"used": scans_today, "limit": quota["scans"]},
            "license": {
                "key":      lic[0] if lic else None,
                "status":   lic[3] if lic else "NONE",
                "is_trial": lic[4] if lic else True,
                "expires_at": expires_at,
                "days_remaining": days_remaining,
            },
            "upgrade": {
                "available": next_tier is not None,
                "next_tier": next_tier,
                "next_price": TIER_PRICES.get(next_tier, 0),
            }
        }
    finally:
        db.close()


@router.get("/invoices")
async def billing_invoices(ctx: dict = Depends(require_auth)):
    from sqlalchemy import text
    email = ctx.get("email","")
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT invoice_number,amount_usd,status,tier,description,period_start,period_end,created_at
            FROM za_invoices WHERE owner_email=:e ORDER BY created_at DESC LIMIT 50
        """),{"e":email}).fetchall()
        return {"invoices": [{
            "invoice_number": r[0], "amount_usd": r[1], "status": r[2],
            "tier": r[3], "description": r[4],
            "period_start": r[5].isoformat() if r[5] else None,
            "period_end":   r[6].isoformat() if r[6] else None,
            "created_at":   r[7].isoformat() if r[7] else None,
        } for r in rows]}
    finally:
        db.close()


class UpgradeReq(BaseModel):
    target_tier: str
    notes: Optional[str] = None

@router.post("/upgrade")
async def billing_upgrade(req: UpgradeReq, ctx: dict = Depends(require_auth)):
    """Request upgrade — ghi Lark + gửi email hướng dẫn thanh toán."""
    email = ctx.get("email","")
    tier  = ctx.get("tier","TRIAL")
    target = req.target_tier.upper()
    if target not in TIER_PRICES:
        raise HTTPException(status_code=400, detail="Tier không hợp lệ")
    if TIER_PRICES.get(target,0) <= TIER_PRICES.get(tier,0):
        raise HTTPException(status_code=400, detail="Chỉ có thể upgrade lên tier cao hơn")

    # Ghi invoice PENDING
    from sqlalchemy import text
    db = SessionLocal()
    try:
        inv_num = f"ZARMOR-{datetime.now().strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"
        db.execute(text("""
            INSERT INTO za_invoices (id,invoice_number,owner_email,amount_usd,status,tier,description)
            VALUES (:id,:num,:email,:amt,'PENDING',:tier,:desc)
        """),{
            "id":   str(uuid.uuid4()),
            "num":  inv_num,
            "email":email,
            "amt":  TIER_PRICES[target],
            "tier": target,
            "desc": f"Upgrade {tier} → {target}",
        })
        db.commit()
    finally:
        db.close()

    # Telegram notify admin
    try:
        import httpx, asyncio
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN","")
        chat_id   = os.getenv("TELEGRAM_CHAT_ID","")
        if bot_token and chat_id:
            msg = f"💎 UPGRADE REQUEST\n{email}: {tier} → {target}\nInvoice: {inv_num}\nAmount: ${TIER_PRICES[target]}/tháng"
            asyncio.create_task(httpx.AsyncClient().post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id":chat_id,"text":msg}
            ))
    except Exception: pass

    return {
        "success": True,
        "invoice_number": inv_num,
        "target_tier": target,
        "amount_usd": TIER_PRICES[target],
        "message": f"Upgrade request ghi nhận. Invoice {inv_num}. Admin sẽ liên hệ qua email trong vòng 2h.",
    }


class CancelReq(BaseModel):
    reason: Optional[str] = None
    confirm: bool = False

@router.post("/cancel")
async def billing_cancel(req: CancelReq, ctx: dict = Depends(require_auth)):
    """Cancel subscription flow."""
    email = ctx.get("email","")
    tier  = ctx.get("tier","TRIAL")
    if tier == "TRIAL":
        return {"success": False, "message": "Tài khoản trial không cần cancel."}
    if not req.confirm:
        return {
            "confirm_required": True,
            "message": "Gửi confirm=true để xác nhận cancel.",
            "offer": "Thay vì cancel, bạn có thể Pause 30 ngày — gửi notes='pause' để dùng tùy chọn này.",
        }
    # Record cancel
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE license_keys SET notes=CONCAT(COALESCE(notes,''), :note), updated_at=NOW()
            WHERE buyer_email=:e AND status='ACTIVE'
        """),{"note":f"\n[CANCEL {datetime.now().date()}] {req.reason or ''}","e":email})
        db.commit()
    finally:
        db.close()

    # Notify admin
    try:
        import httpx, asyncio
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN","")
        chat_id   = os.getenv("TELEGRAM_CHAT_ID","")
        if bot_token and chat_id:
            asyncio.create_task(httpx.AsyncClient().post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id":chat_id,"text":f"❌ CANCEL: {email} ({tier})\nReason: {req.reason or 'N/A'}"}
            ))
    except Exception: pass

    return {"success": True, "message": "Đã ghi nhận cancel. License sẽ hết hạn vào ngày expiry hiện tại."}


def init_billing():
    try:
        _ensure_billing_tables()
        print("[BILLING] Tables ready", flush=True)
    except Exception as e:
        print(f"[BILLING] Warning: {e}", flush=True)
