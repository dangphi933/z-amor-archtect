"""
app/routers/user_router.py
============================
User profile endpoints — extract từ api/identity_router.py monolith.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from ..core.database import SessionLocal, License, ZAUser, AuditLog
from shared.libs.security.jwt_utils import require_jwt

router = APIRouter(tags=["user"])


@router.get("/profile")
async def get_profile(payload: dict = require_jwt):
    """User profile + tất cả licenses."""
    email = payload.get("sub", "")
    if not email:
        raise HTTPException(401, "Không xác định được user.")

    db = SessionLocal()
    try:
        user = db.query(ZAUser).filter(ZAUser.email == email).first()
        licenses = db.query(License).filter(License.buyer_email == email).all()

        active_licenses = [
            {
                "license_key":  lic.license_key,
                "tier":         lic.tier,
                "status":       lic.status,
                "bound_mt5_id": lic.bound_mt5_id,
                "expires_at":   lic.expires_at.isoformat() if lic.expires_at else None,
                "is_trial":     lic.is_trial,
                "strategy_id":  lic.strategy_id or "S1",
                "is_expired":   (
                    lic.expires_at is not None and
                    lic.expires_at < datetime.now(timezone.utc)
                ),
            }
            for lic in licenses
        ]

        return {
            "email":         email,
            "name":          user.name if user else email.split("@")[0],
            "created_at":    user.created_at.isoformat() if user else None,
            "licenses":      active_licenses,
            "total_licenses":len(active_licenses),
            "account_ids":   payload.get("account_ids", []),
        }
    finally:
        db.close()
