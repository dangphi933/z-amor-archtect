"""
app/routers/billing_router.py
===============================
Billing portal — extract từ api/billing_router.py monolith.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..core.database import SessionLocal, License
from shared.libs.security.jwt_utils import require_jwt
from shared.libs.messaging.redis_streams import publish_notification

router = APIRouter(tags=["billing"])

TIER_PRICES = {"TRIAL": 0, "ARMOR": 29, "ARSENAL": 79, "FLEET": 199}
TIER_FEATURES = {
    "TRIAL":   {"scans": 50,    "accounts": 1,  "alerts": "Telegram only"},
    "ARMOR":   {"scans": 500,   "accounts": 3,  "alerts": "Telegram + Email"},
    "ARSENAL": {"scans": 2000,  "accounts": 10, "alerts": "All channels"},
    "FLEET":   {"scans": 99999, "accounts": -1, "alerts": "All + Priority"},
}


class UpgradeReq(BaseModel):
    license_key: str
    target_tier: str
    payment_method: Optional[str] = "manual"

class CancelReq(BaseModel):
    license_key: str
    reason: Optional[str] = ""


def _ensure_invoice_table():
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
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_za_inv_email ON za_invoices(owner_email)"))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


@router.get("/portal")
async def billing_portal(payload: dict = require_jwt):
    """Overview: tier, usage, renewal info."""
    _ensure_invoice_table()
    email = payload.get("sub", "")
    db = SessionLocal()
    try:
        licenses = db.query(License).filter(License.buyer_email == email).all()
        if not licenses:
            return {"email": email, "licenses": [], "message": "Chưa có license."}

        result = []
        for lic in licenses:
            tier = lic.tier or "TRIAL"
            features = TIER_FEATURES.get(tier, {})
            price = TIER_PRICES.get(tier, 0)
            days_left = None
            if lic.expires_at:
                delta = lic.expires_at - datetime.now(timezone.utc)
                days_left = max(0, delta.days)

            result.append({
                "license_key":  lic.license_key,
                "tier":         tier,
                "status":       lic.status,
                "price_usd":    price,
                "features":     features,
                "expires_at":   lic.expires_at.isoformat() if lic.expires_at else None,
                "days_left":    days_left,
                "bound_mt5_id": lic.bound_mt5_id,
                "upgrade_options": [
                    {"tier": t, "price": p, "features": TIER_FEATURES[t]}
                    for t, p in TIER_PRICES.items()
                    if p > price
                ],
            })
        return {"email": email, "licenses": result}
    finally:
        db.close()


@router.get("/invoices")
async def billing_invoices(payload: dict = require_jwt):
    """Invoice history."""
    _ensure_invoice_table()
    email = payload.get("sub", "")
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT * FROM za_invoices WHERE owner_email = :email ORDER BY created_at DESC LIMIT 50"
        ), {"email": email}).fetchall()
        return {"email": email, "invoices": [dict(r._mapping) for r in rows]}
    finally:
        db.close()


@router.post("/upgrade")
async def billing_upgrade(req: UpgradeReq, payload: dict = require_jwt):
    """Request upgrade — tạo invoice PENDING, admin confirm thủ công."""
    email = payload.get("sub", "")
    target_tier = req.target_tier.upper()
    if target_tier not in TIER_PRICES:
        raise HTTPException(400, f"Tier không hợp lệ: {target_tier}")

    _ensure_invoice_table()
    invoice_id = str(uuid.uuid4())
    inv_number = f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{invoice_id[:6].upper()}"
    amount = TIER_PRICES[target_tier]

    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO za_invoices
              (id, invoice_number, owner_email, license_key, amount_usd, status, tier, description,
               period_start, period_end)
            VALUES (:id, :inv, :email, :lk, :amt, 'PENDING', :tier, :desc, :start, :end)
        """), {
            "id": invoice_id, "inv": inv_number, "email": email,
            "lk": req.license_key, "amt": amount, "tier": target_tier,
            "desc": f"Upgrade to {target_tier}",
            "start": datetime.now(timezone.utc),
            "end":   datetime.now(timezone.utc) + timedelta(days=30),
        })
        db.commit()
    finally:
        db.close()

    # Notify admin
    publish_notification("EMAIL_NOTIFY", {
        "to_email": email,
        "subject":  f"[Z-ARMOR] Upgrade request nhận được — {target_tier}",
        "html_body": f"<p>Invoice <b>{inv_number}</b> đã được tạo. Admin sẽ xác nhận trong 24h.</p>",
    }, source="user-service")

    return {
        "status":         "ok",
        "invoice_number": inv_number,
        "amount_usd":     amount,
        "target_tier":    target_tier,
        "message":        "Upgrade request đã nhận. Admin sẽ xác nhận trong 24h.",
    }


@router.post("/cancel")
async def billing_cancel(req: CancelReq, payload: dict = require_jwt):
    """Cancel subscription — set trạng thái CANCEL_PENDING."""
    email = payload.get("sub", "")
    db = SessionLocal()
    try:
        lic = db.query(License).filter(
            License.license_key == req.license_key,
            License.buyer_email == email,
        ).first()
        if not lic:
            raise HTTPException(404, "License không tìm thấy.")
        lic.notes = f"CANCEL_REQUESTED: {req.reason}"
        db.commit()
    finally:
        db.close()

    publish_notification("DEFCON3_SILENT", {
        "account_id": email,
        "message":    f"⚠️ Cancel request: {email} — {req.license_key[:8]}*** Reason: {req.reason}",
    }, source="user-service")

    return {"status": "ok", "message": "Cancel request đã nhận. Team sẽ liên hệ trong 48h."}
