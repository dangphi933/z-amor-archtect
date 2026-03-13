"""
api/compliance_router.py â€” Sprint 6
GDPR + Audit Trail + Compliance
  GET  /compliance/audit-log      â€” lá»‹ch sá»­ audit cá»§a user
  GET  /compliance/data-export    â€” GDPR Article 20: export toÃ n bá»™ data
  DELETE /compliance/account      â€” GDPR Article 17: right to erasure
  POST /compliance/consent        â€” ghi nháº­n consent
"""
import os, uuid, json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from auth_service import require_auth, revoke_all_sessions
from database import SessionLocal

router = APIRouter(tags=["compliance"])

AUDIT_ACTIONS = [
    "LOGIN","LOGOUT","SCAN","ALERT_SUB","ALERT_UNSUB",
    "UPGRADE_REQUEST","CANCEL_SUB","CHANGE_PASSWORD",
    "DATA_EXPORT","DATA_DELETE","CONSENT_GIVEN","ADMIN_ACCESS",
]


def log_audit(user_id: str, action: str, email: str = "", metadata: dict = None, ip: str = ""):
    """Ghi audit log â€” fire and forget safe."""
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO audit_logs (account_id, action, severity, message, email, detail, ip_address)
            VALUES (:uid, :action, 'INFO', :msg, :email, :detail, :ip)
        """),{
            "uid":    user_id,
            "action": action,
            "msg":    action,
            "email":  email,
            "detail": json.dumps(metadata or {}),
            "ip":     ip,
        })
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _ensure_compliance_indexes():
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_user_date ON audit_logs(account_id, created_at DESC)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_action_date ON audit_logs(action, created_at DESC)"))
        db.commit()
    except Exception: db.rollback()
    finally: db.close()


@router.get("/audit-log")
async def get_audit_log(limit: int = 100, ctx: dict = Depends(require_auth)):
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT action, severity, message, email, detail, ip_address, created_at
            FROM audit_logs WHERE account_id=:uid
            ORDER BY created_at DESC LIMIT :limit
        """),{"uid":ctx.get("sub",""),"limit":min(limit,500)}).fetchall()
        return {"logs":[{
            "action":r[0],"severity":r[1],"message":r[2],
            "email":r[3],"metadata":r[4],"ip":r[5],
            "created_at":r[6].isoformat() if r[6] else None
        } for r in rows]}
    finally:
        db.close()


@router.get("/data-export")
async def data_export(ctx: dict = Depends(require_auth), bg: BackgroundTasks = None):
    """GDPR Article 20 â€” export toÃ n bá»™ data cá»§a user."""
    from sqlalchemy import text
    user_id = ctx.get("sub")
    email   = ctx.get("email","")
    db = SessionLocal()
    try:
        # Licenses
        lics = db.execute(text("""
            SELECT license_key,tier,status,is_trial,expires_at,created_at
            FROM license_keys WHERE buyer_email=:e
        """),{"e":email}).fetchall()
        # Trade history
        trades = db.execute(text("""
            SELECT ticket,symbol,trade_type,pnl,opened_at,closed_at FROM trade_history
            WHERE account_id IN (
                SELECT account_id FROM license_activations la
                JOIN license_keys lk ON la.license_key=lk.license_key
                WHERE lk.buyer_email=:e
            ) LIMIT 1000
        """),{"e":email}).fetchall()
        # Radar scans
        scans = db.execute(text("""
            SELECT asset,timeframe,score,regime,created_at FROM radar_scans
            WHERE user_id=:uid ORDER BY created_at DESC LIMIT 500
        """),{"uid":user_id}).fetchall()
        # Alert subscriptions
        alerts = db.execute(text("""
            SELECT asset,timeframe,threshold,channel,active FROM alert_subscriptions
            WHERE user_id=:uid
        """),{"uid":user_id}).fetchall()
        # Audit logs
        audits = db.execute(text("""
            SELECT action,created_at FROM audit_logs
            WHERE account_id=:uid ORDER BY created_at DESC LIMIT 200
        """),{"uid":user_id}).fetchall()

        export = {
            "export_date":   datetime.now(timezone.utc).isoformat(),
            "user_id":       user_id,
            "email":         email,
            "licenses":      [{"key":r[0],"tier":r[1],"status":r[2],"trial":r[3],
                               "expires":r[4].isoformat() if r[4] else None} for r in lics],
            "trades":        [{"ticket":r[0],"symbol":r[1],"type":r[2],"pnl":r[3],
                               "opened":r[4].isoformat() if r[4] else None,
                               "closed":r[5].isoformat() if r[5] else None} for r in trades],
            "radar_scans":   [{"asset":r[0],"tf":r[1],"score":r[2],"regime":r[3],
                               "at":r[4].isoformat() if r[4] else None} for r in scans],
            "alert_subs":    [{"asset":r[0],"tf":r[1],"threshold":r[2],"channel":r[3],"active":r[4]} for r in alerts],
            "audit_log":     [{"action":r[0],"at":r[1].isoformat() if r[1] else None} for r in audits],
        }
        log_audit(user_id, "DATA_EXPORT", email)
        return export
    finally:
        db.close()


class DeleteAccountReq(BaseModel):
    confirm_email: str
    reason: Optional[str] = None

@router.delete("/account")
async def delete_account(req: DeleteAccountReq, ctx: dict = Depends(require_auth)):
    """GDPR Article 17 â€” right to erasure. Anonymize PII, giá»¯ aggregate data."""
    user_id = ctx.get("sub")
    email   = ctx.get("email","")
    if req.confirm_email.strip().lower() != email.lower():
        raise HTTPException(status_code=400, detail="confirm_email khÃ´ng khá»›p")

    from sqlalchemy import text
    db = SessionLocal()
    try:
        anon_email = f"deleted_{user_id[:8]}@anon.zarmor"
        # Anonymize za_users
        db.execute(text("""
            UPDATE za_users SET email=:anon, username='[deleted]',
            password_hash=NULL, status='deleted', updated_at=NOW()
            WHERE id=:uid
        """),{"anon":anon_email,"uid":user_id})
        # Anonymize za_auth_providers
        db.execute(text("DELETE FROM za_auth_providers WHERE user_id=:uid"),{"uid":user_id})
        # Anonymize license email
        db.execute(text("""
            UPDATE license_keys SET buyer_email=:anon, buyer_name='[deleted]'
            WHERE buyer_email=:email
        """),{"anon":anon_email,"email":email})
        # Anonymize audit logs PII
        db.execute(text("""
            UPDATE audit_logs SET email=:anon WHERE account_id=:uid
        """),{"anon":anon_email,"uid":user_id})
        # Revoke all sessions
        revoke_all_sessions(user_id)
        db.commit()
        log_audit(user_id, "DATA_DELETE", anon_email, {"reason":req.reason})
        return {"success":True,"message":"TÃ i khoáº£n Ä‘Ã£ Ä‘Æ°á»£c xÃ³a vÃ  dá»¯ liá»‡u PII Ä‘Ã£ Ä‘Æ°á»£c anonymize."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


class ConsentReq(BaseModel):
    consent_type: str  # "terms", "radar_disclaimer", "marketing"
    accepted: bool

@router.post("/consent")
async def record_consent(req: ConsentReq, request: Request, ctx: dict = Depends(require_auth)):
    user_id = ctx.get("sub")
    email   = ctx.get("email","")
    ip = request.client.host if request.client else ""
    log_audit(user_id, "CONSENT_GIVEN", email,
              {"type": req.consent_type, "accepted": req.accepted}, ip)
    return {"success": True, "consent_type": req.consent_type, "accepted": req.accepted}


def init_compliance():
    try:
        _ensure_compliance_indexes()
        print("[COMPLIANCE] Indexes ready", flush=True)
    except Exception as e:
        print(f"[COMPLIANCE] Warning: {e}", flush=True)
