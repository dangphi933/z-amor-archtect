"""
app/routers/compliance_router.py
==================================
GDPR + Audit Trail — extract từ api/compliance_router.py monolith.
"""

import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from ..core.database import SessionLocal, AuditLog, License, ZAUser
from shared.libs.security.jwt_utils import require_jwt

router = APIRouter(tags=["compliance"])


class ConsentReq(BaseModel):
    consent_type: str
    granted: bool
    version: Optional[str] = "1.0"


@router.get("/audit-log")
async def audit_log(
    limit: int = 50,
    payload: dict = require_jwt,
):
    """GDPR Article 15 — lịch sử audit của user."""
    email = payload.get("sub", "")
    db = SessionLocal()
    try:
        logs = (
            db.query(AuditLog)
            .filter(AuditLog.email == email)
            .order_by(AuditLog.created_at.desc())
            .limit(min(limit, 200))
            .all()
        )
        return {
            "email": email,
            "count": len(logs),
            "logs": [
                {
                    "action":     log.action,
                    "severity":   log.severity,
                    "message":    log.message,
                    "created_at": log.created_at.isoformat(),
                    "ip_address": log.ip_address,
                }
                for log in logs
            ],
        }
    finally:
        db.close()


@router.get("/data-export")
async def data_export(payload: dict = require_jwt):
    """GDPR Article 20 — export toàn bộ data của user."""
    email = payload.get("sub", "")
    db = SessionLocal()
    try:
        user = db.query(ZAUser).filter(ZAUser.email == email).first()
        licenses = db.query(License).filter(License.buyer_email == email).all()
        logs = db.query(AuditLog).filter(AuditLog.email == email).limit(1000).all()

        return {
            "export_generated_at": datetime.now(timezone.utc).isoformat(),
            "email": email,
            "profile": {
                "name":       user.name if user else None,
                "created_at": user.created_at.isoformat() if user else None,
            } if user else None,
            "licenses": [
                {
                    "license_key":  lic.license_key,
                    "tier":         lic.tier,
                    "status":       lic.status,
                    "bound_mt5_id": lic.bound_mt5_id,
                    "created_at":   lic.created_at.isoformat(),
                    "expires_at":   lic.expires_at.isoformat() if lic.expires_at else None,
                }
                for lic in licenses
            ],
            "audit_logs": [
                {
                    "action":     log.action,
                    "created_at": log.created_at.isoformat(),
                    "ip_address": log.ip_address,
                }
                for log in logs
            ],
        }
    finally:
        db.close()


@router.delete("/account")
async def delete_account(payload: dict = require_jwt):
    """GDPR Article 17 — Right to Erasure (soft delete)."""
    email = payload.get("sub", "")
    db = SessionLocal()
    try:
        # Anonymize user record
        user = db.query(ZAUser).filter(ZAUser.email == email).first()
        if user:
            user.name      = "[DELETED]"
            user.is_active = False

        # Ghi audit
        db.add(AuditLog(
            account_id=email,
            action="DATA_DELETE",
            severity="INFO",
            email=email,
            message="GDPR Article 17 erasure request processed",
        ))
        db.commit()
    finally:
        db.close()

    return {"status": "ok", "message": "Tài khoản đã được xóa. Dữ liệu sẽ được xóa hoàn toàn trong 30 ngày."}


@router.post("/consent")
async def record_consent(req: ConsentReq, request: Request, payload: dict = require_jwt):
    """Ghi nhận consent (GDPR Article 7)."""
    email = payload.get("sub", "")
    ip = request.client.host if request.client else ""
    db = SessionLocal()
    try:
        db.add(AuditLog(
            account_id=email,
            action="CONSENT_GIVEN" if req.granted else "CONSENT_WITHDRAWN",
            severity="INFO",
            email=email,
            detail=json.dumps({"consent_type": req.consent_type, "version": req.version}),
            ip_address=ip,
        ))
        db.commit()
    finally:
        db.close()
    return {"status": "ok", "consent_type": req.consent_type, "granted": req.granted}
