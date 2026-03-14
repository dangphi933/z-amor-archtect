"""
app/services/auth_service.py  (v2 — Redis-backed)
===================================================
BUG FIX: Thay tất cả in-memory dicts bằng Redis store.
Safe với uvicorn --workers N (multi-worker).

Changes vs v1:
  - _OTPStore dict  → redis_store.otp_*()
  - _sessions dict  → redis_store.refresh_token_*()
  - _revoked_jtis   → redis_store.is_jti_revoked()
  - _otp_rate dict  → redis_store.otp_rate_check()
"""

import os
import uuid
import random
import asyncio
import smtplib
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import jwt as pyjwt
import bcrypt

from ..core.database import SessionLocal, ZAUser, License, AuditLog
from shared.libs.cache.redis_store import (
    otp_rate_check, otp_store, otp_verify,
    refresh_token_store, refresh_token_get,
    refresh_token_revoke, refresh_token_revoke_all,
    is_jti_revoked,
)

logger = logging.getLogger("zarmor.auth")

JWT_ALGORITHM  = "HS256"
ACCESS_TTL_MIN = int(os.getenv("JWT_ACCESS_TTL_MINUTES", "1440"))
REFRESH_TTL_D  = int(os.getenv("JWT_REFRESH_TTL_DAYS", "30"))
SMTP_EMAIL     = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD", "")
BACKEND_URL    = os.getenv("BACKEND_URL", "http://localhost:8001")
COOKIE_SECURE  = os.getenv("COOKIE_SECURE", "false").lower() == "true"


def _get_jwt_secret() -> str:
    s = os.getenv("JWT_SECRET_KEY", "")
    if s:
        return s
    if os.getenv("DEBUG", "false").lower() == "true":
        logger.warning("[JWT] JWT_SECRET_KEY not set — dev fallback. NEVER in production.")
        return "dev-insecure-secret-change-me"
    raise RuntimeError("JWT_SECRET_KEY not set.")


# ══════════════════════════════════════════════════════════════════
# OTP  (Redis-backed)
# ══════════════════════════════════════════════════════════════════

async def send_magic_otp(email: str, ip: str = "") -> str:
    """Returns: 'ok' | 'RATE_LIMITED' | 'SEND_FAILED'"""
    if not otp_rate_check(email):
        return "RATE_LIMITED"

    otp = str(random.randint(100000, 999999))
    otp_store(email, otp)
    _write_audit(email, "OTP_REQUESTED", ip=ip)

    if not SMTP_EMAIL or not SMTP_PASSWORD:
        logger.warning(f"[AUTH] SMTP not configured — OTP {email}: {otp} (dev)")
        return "ok"
    try:
        await asyncio.get_event_loop().run_in_executor(None, _smtp_send_otp, email, otp)
        return "ok"
    except Exception as e:
        logger.error(f"[AUTH] OTP email failed {email}: {e}")
        return "SEND_FAILED"


def verify_magic_otp(email: str, code: str) -> str:
    """Returns: 'ok' | 'INVALID' | 'EXPIRED' | 'MAX_ATTEMPTS'"""
    return otp_verify(email, code)


def _smtp_send_otp(to_email: str, otp: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Z-ARMOR] Mã xác nhận: {otp}"
    msg["From"]    = f"Z-ARMOR CLOUD <{SMTP_EMAIL}>"
    msg["To"]      = to_email
    html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;">
      <div style="background:#1B3A5C;padding:20px;text-align:center;">
        <h2 style="color:#fff;margin:0;">Z-ARMOR CLOUD</h2>
      </div>
      <div style="padding:30px;background:#f9f9f9;">
        <p>Mã xác nhận đăng nhập:</p>
        <div style="font-size:42px;font-weight:bold;letter-spacing:8px;
                    text-align:center;color:#2E75B6;padding:20px;">{otp}</div>
        <p style="color:#888;font-size:13px;">Hết hạn sau 15 phút.</p>
      </div></div>"""
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
        s.ehlo(); s.starttls(); s.ehlo()
        s.login(SMTP_EMAIL, SMTP_PASSWORD)
        s.sendmail(SMTP_EMAIL, to_email, msg.as_string())


# ══════════════════════════════════════════════════════════════════
# JWT  (Redis-backed session)
# ══════════════════════════════════════════════════════════════════

def create_access_token(email: str, account_ids: list, extra: dict = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":         email,
        "account_ids": account_ids,
        "jti":         str(uuid.uuid4()),
        "iat":         now,
        "exp":         now + timedelta(minutes=ACCESS_TTL_MIN),
        "type":        "access",
        **(extra or {}),
    }
    return pyjwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(email: str) -> tuple[str, str]:
    """Returns (token, jti)."""
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        "sub":  email, "jti": jti,
        "iat":  now,
        "exp":  now + timedelta(days=REFRESH_TTL_D),
        "type": "refresh",
    }
    return pyjwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM), jti


def store_session(email: str, jti: str, ip: str = ""):
    refresh_token_store(jti, email, ip)


def revoke_session(jti: str):
    refresh_token_revoke(jti)


def revoke_all_sessions(email: str):
    refresh_token_revoke_all(email)


def rotate_refresh_token(old_token: str) -> dict:
    try:
        payload = pyjwt.decode(old_token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise ValueError("Refresh token đã hết hạn. Đăng nhập lại.")
    except pyjwt.InvalidTokenError:
        raise ValueError("Refresh token không hợp lệ.")

    if payload.get("type") != "refresh":
        raise ValueError("Token type không hợp lệ.")
    jti = payload["jti"]
    if is_jti_revoked(jti):
        raise ValueError("Token đã bị revoke.")
    if not refresh_token_get(jti):
        raise ValueError("Session không tồn tại. Đăng nhập lại.")

    email = payload["sub"]
    revoke_session(jti)

    account_ids = _get_account_ids_for_email(email)
    access  = create_access_token(email, account_ids)
    new_ref, new_jti = create_refresh_token(email)
    store_session(email, new_jti)
    return {"access_token": access, "refresh_token": new_ref}


# ══════════════════════════════════════════════════════════════════
# USER HELPERS
# ══════════════════════════════════════════════════════════════════

def get_or_create_user(email: str) -> dict:
    db = SessionLocal()
    try:
        user = db.query(ZAUser).filter(ZAUser.email == email).first()
        if user:
            return {"email": email, "name": user.name, "is_new": False}
        user = ZAUser(email=email, name=email.split("@")[0])
        db.add(user); db.commit()
        return {"email": email, "name": user.name, "is_new": True}
    finally:
        db.close()


def get_user_by_license(license_key: str) -> Optional[dict]:
    db = SessionLocal()
    try:
        lic = db.query(License).filter(License.license_key == license_key).first()
        if not lic or lic.status not in ("ACTIVE", "UNUSED"):
            return None
        return {"email": lic.buyer_email or "", "license_key": lic.license_key,
                "tier": lic.tier, "account_id": lic.bound_mt5_id}
    finally:
        db.close()


def _get_account_ids_for_email(email: str) -> list:
    db = SessionLocal()
    try:
        lics = db.query(License).filter(
            License.buyer_email == email,
            License.bound_mt5_id.isnot(None),
        ).all()
        return [l.bound_mt5_id for l in lics]
    finally:
        db.close()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _write_audit(email: str, action: str, ip: str = "", detail: str = ""):
    db = SessionLocal()
    try:
        db.add(AuditLog(account_id=email, action=action, severity="INFO",
                        email=email, ip_address=ip, detail=detail))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
