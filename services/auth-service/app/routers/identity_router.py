"""
app/routers/identity_router.py
================================
User identity + license bind — extract từ api/identity_router.py monolith.

Endpoints:
  POST /auth/bind-license    — bind license key vào MT5 account
  GET  /auth/my-licenses     — danh sách licenses của user
  GET  /auth/account-status  — check account/license status
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from ..core.database import SessionLocal, License, LicenseActivation, atomic_bind_license, AuditLog
from shared.libs.security.jwt_utils import require_jwt

router = APIRouter(tags=["identity"])


class BindLicensePayload(BaseModel):
    license_key: str
    mt5_login:   str
    magic:       Optional[str] = None


# ══════════════════════════════════════════════════════════════════
# POST /auth/bind-license
# ══════════════════════════════════════════════════════════════════

@router.post("/bind-license")
async def bind_license(req: BindLicensePayload, request: Request):
    """
    Bind license_key vào mt5_login (account_id).
    Atomic — không cần SELECT FOR UPDATE.
    Idempotent — gọi lại nếu đã bind rồi vẫn trả success.
    """
    ip = request.client.host if request.client else ""
    db = SessionLocal()
    try:
        result = atomic_bind_license(db, req.license_key, req.mt5_login)
    finally:
        db.close()

    if result["status"] == "error":
        raise HTTPException(400, result.get("message", result["reason"]))

    # Ghi activation record
    db2 = SessionLocal()
    try:
        existing = db2.query(LicenseActivation).filter(
            LicenseActivation.license_key == req.license_key,
            LicenseActivation.account_id  == req.mt5_login,
        ).first()
        if not existing:
            db2.add(LicenseActivation(
                license_key=req.license_key,
                account_id=req.mt5_login,
                magic=req.magic,
            ))
            db2.commit()
    except Exception:
        db2.rollback()
    finally:
        db2.close()

    return {"status": "ok", "reason": result["reason"], "account_id": req.mt5_login}


# ══════════════════════════════════════════════════════════════════
# GET /auth/my-licenses
# ══════════════════════════════════════════════════════════════════

@router.get("/my-licenses")
async def my_licenses(payload: dict = require_jwt):
    """Danh sách licenses của user đang đăng nhập."""
    email = payload.get("sub", "")
    if not email:
        raise HTTPException(401, "Không xác định được email từ token.")

    db = SessionLocal()
    try:
        licenses = db.query(License).filter(License.buyer_email == email).all()
        return {
            "email": email,
            "licenses": [
                {
                    "license_key":  lic.license_key,
                    "tier":         lic.tier,
                    "status":       lic.status,
                    "bound_mt5_id": lic.bound_mt5_id,
                    "is_trial":     lic.is_trial,
                    "activated_at": lic.activated_at.isoformat() if lic.activated_at else None,
                    "expires_at":   lic.expires_at.isoformat()   if lic.expires_at   else None,
                    "strategy_id":  lic.strategy_id,
                }
                for lic in licenses
            ],
        }
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════
# GET /auth/account-status
# ══════════════════════════════════════════════════════════════════

@router.get("/account-status")
async def account_status(license_key: str):
    """Check trạng thái license — dùng bởi EA trước handshake."""
    db = SessionLocal()
    try:
        lic = db.query(License).filter(License.license_key == license_key).first()
        if not lic:
            raise HTTPException(404, "License không tồn tại.")
        return {
            "license_key":  lic.license_key,
            "status":       lic.status,
            "tier":         lic.tier,
            "bound_mt5_id": lic.bound_mt5_id,
            "expires_at":   lic.expires_at.isoformat() if lic.expires_at else None,
            "is_expired":   lic.expires_at is not None and
                            lic.expires_at.timestamp() < __import__("time").time(),
        }
    finally:
        db.close()
