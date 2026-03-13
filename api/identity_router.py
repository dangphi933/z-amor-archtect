"""
api/identity_router.py — Z-ARMOR CLOUD
Sprint 2: User Identity Platform
  POST /user/register      — tạo tài khoản mới
  GET  /user/profile       — profile + tier + quota
  POST /user/change-password
  GET  /user/referral-stats
"""
import os, uuid, hashlib, secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from auth_service import require_auth
from database import SessionLocal

router = APIRouter(tags=["identity"])

class RegisterReq(BaseModel):
    email: str
    password: str
    license_key: Optional[str] = None
    ref_code: Optional[str] = None

class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str


def _ensure_identity_tables():
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS za_users (
                id            VARCHAR(36) PRIMARY KEY,
                email         VARCHAR(200) UNIQUE NOT NULL,
                username      VARCHAR(100),
                password_hash VARCHAR(200),
                ref_code      VARCHAR(20) UNIQUE,
                referred_by   VARCHAR(20),
                tier          VARCHAR(20) DEFAULT 'TRIAL',
                status        VARCHAR(20) DEFAULT 'active',
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                updated_at    TIMESTAMPTZ DEFAULT NOW()
            )"""))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_za_users_email    ON za_users(email)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_za_users_ref_code ON za_users(ref_code)"))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS za_auth_providers (
                id           VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                user_id      VARCHAR(36) NOT NULL REFERENCES za_users(id) ON DELETE CASCADE,
                provider     VARCHAR(20) NOT NULL,
                provider_uid VARCHAR(200) NOT NULL,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(provider, provider_uid)
            )"""))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_za_ap_user ON za_auth_providers(user_id)"))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS za_user_security (
                user_id                VARCHAR(36) PRIMARY KEY REFERENCES za_users(id),
                failed_login_attempts  INTEGER DEFAULT 0,
                last_login_ip          VARCHAR(50),
                device_hash            VARCHAR(100),
                two_fa_enabled         BOOLEAN DEFAULT FALSE,
                two_fa_secret          VARCHAR(100)
            )"""))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[IDENTITY] Table init warning: {e}", flush=True)
    finally:
        db.close()


@router.post("/register")
async def user_register(req: RegisterReq, request: Request):
    """Tạo tài khoản mới. Nếu có license_key, link luôn."""
    from sqlalchemy import text
    try:
        import bcrypt
    except ImportError:
        raise HTTPException(status_code=500, detail="bcrypt not installed")

    email = req.email.strip().lower()
    db = SessionLocal()
    try:
        existing = db.execute(text("SELECT id FROM za_users WHERE email=:e"), {"e":email}).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Email đã được đăng ký")

        uid = str(uuid.uuid4())
        ref_code = secrets.token_hex(4).upper()  # 8 char hex
        pw_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt(rounds=12)).decode()
        referred_by = req.ref_code if req.ref_code else None

        # Determine tier from license_key if provided
        tier = "TRIAL"
        if req.license_key:
            lrow = db.execute(text(
                "SELECT tier FROM license_keys WHERE license_key=:k AND status IN ('ACTIVE','TRIAL')"
            ),{"k":req.license_key}).fetchone()
            if lrow and lrow[0]: tier = lrow[0]

        db.execute(text("""
            INSERT INTO za_users (id,email,password_hash,ref_code,referred_by,tier)
            VALUES (:id,:email,:pw,:ref,:rby,:tier)
        """),{"id":uid,"email":email,"pw":pw_hash,"ref":ref_code,"rby":referred_by,"tier":tier})

        # Link license_key provider
        if req.license_key:
            db.execute(text("""
                INSERT INTO za_auth_providers (id,user_id,provider,provider_uid)
                VALUES (:id,:uid,'license_key',:lk) ON CONFLICT DO NOTHING
            """),{"id":str(uuid.uuid4()),"uid":uid,"lk":req.license_key})

        # Link email provider
        db.execute(text("""
            INSERT INTO za_auth_providers (id,user_id,provider,provider_uid)
            VALUES (:id,:uid,'email',:email) ON CONFLICT DO NOTHING
        """),{"id":str(uuid.uuid4()),"uid":uid,"email":email})

        # Security row
        db.execute(text("""
            INSERT INTO za_user_security (user_id,last_login_ip) VALUES (:uid,:ip)
            ON CONFLICT DO NOTHING
        """),{"uid":uid,"ip":request.client.host if request.client else ""})

        # Track referral if referred_by present
        if referred_by:
            db.execute(text("""
                UPDATE referral_events SET converted=TRUE
                WHERE ref_code=:rc AND converted=FALSE
                ORDER BY created_at DESC LIMIT 1
            """),{"rc":referred_by})

        db.commit()
        return {"success": True, "user_id": uid, "email": email,
                "tier": tier, "ref_code": ref_code}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/profile")
async def user_profile(ctx: dict = Depends(require_auth)):
    """User profile + scan quota usage."""
    from sqlalchemy import text
    from datetime import date
    db = SessionLocal()
    try:
        user_id = ctx.get("sub")
        email   = ctx.get("email")
        tier    = ctx.get("tier","TRIAL")
        # Quota used today
        today_str = date.today().isoformat()
        scan_count = 0
        try:
            row = db.execute(text("""
                SELECT COUNT(*) FROM radar_scans
                WHERE user_id=:uid AND DATE(created_at)=:today
            """),{"uid":user_id,"today":today_str}).fetchone()
            scan_count = row[0] if row else 0
        except Exception: pass

        quota_map = {"TRIAL":50,"ARMOR":500,"ARSENAL":2000,"FLEET":999999}
        quota_limit = quota_map.get(tier, 20)

        # Active license info
        lic_row = db.execute(text("""
            SELECT license_key,tier,expires_at,status FROM license_keys
            WHERE buyer_email=:e ORDER BY created_at DESC LIMIT 1
        """),{"e":email}).fetchone()

        return {
            "user_id":    user_id,
            "email":      email,
            "tier":       tier,
            "ref_code":   ctx.get("ref_code",""),
            "account_ids":ctx.get("account_ids",[]),
            "quota": {
                "used":  scan_count,
                "limit": quota_limit,
                "remaining": max(0, quota_limit - scan_count),
            },
            "license": {
                "key":        lic_row[0] if lic_row else None,
                "tier":       lic_row[1] if lic_row else tier,
                "expires_at": lic_row[2].isoformat() if lic_row and lic_row[2] else None,
                "status":     lic_row[3] if lic_row else "UNKNOWN",
            } if lic_row else None,
        }
    finally:
        db.close()


@router.post("/change-password")
async def change_password(req: ChangePasswordReq, ctx: dict = Depends(require_auth)):
    try:
        import bcrypt
    except ImportError:
        raise HTTPException(status_code=500, detail="bcrypt not installed")
    from sqlalchemy import text
    db = SessionLocal()
    try:
        user_id = ctx.get("sub")
        row = db.execute(text("SELECT password_hash FROM za_users WHERE id=:uid"),{"uid":user_id}).fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=400, detail="Tài khoản không hỗ trợ đổi mật khẩu")
        if not bcrypt.checkpw(req.old_password.encode(), row[0].encode()):
            raise HTTPException(status_code=401, detail="Mật khẩu cũ không đúng")
        new_hash = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt(rounds=12)).decode()
        db.execute(text("UPDATE za_users SET password_hash=:pw WHERE id=:uid"),{"pw":new_hash,"uid":user_id})
        db.commit()
        return {"success": True}
    finally:
        db.close()


@router.get("/referral-stats")
async def referral_stats(ctx: dict = Depends(require_auth)):
    from sqlalchemy import text
    ref_code = ctx.get("ref_code","")
    if not ref_code:
        return {"ref_code": None, "clicks": 0, "conversions": 0, "k_factor": 0}
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT COUNT(*) FILTER (WHERE converted=FALSE) as clicks,
                   COUNT(*) FILTER (WHERE converted=TRUE)  as conversions
            FROM referral_events WHERE ref_code=:rc
        """),{"rc":ref_code}).fetchone()
        clicks = row[0] if row else 0
        convs  = row[1] if row else 0
        k = round(convs / max(1, clicks), 3)
        return {"ref_code":ref_code,"clicks":clicks,"conversions":convs,"k_factor":k}
    except Exception:
        return {"ref_code":ref_code,"clicks":0,"conversions":0,"k_factor":0}
    finally:
        db.close()


def init_identity():
    try:
        _ensure_identity_tables()
        print("[IDENTITY] Tables ready", flush=True)
    except Exception as e:
        print(f"[IDENTITY] Warning: {e}", flush=True)
