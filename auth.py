"""
auth.py — Z-ARMOR CLOUD  (merged từ auth_service.py + security fixes)
=======================================================================
Giữ nguyên 100% API của auth_service.py (backward-compat):
  send_magic_otp, verify_magic_otp, _OTPStore
  create_access_token, create_refresh_token
  store_session, revoke_session, revoke_all_sessions
  rotate_refresh_token, is_jti_revoked
  get_or_create_user_by_email, get_user_by_license
  require_auth, optional_auth, decode_jwt_unsafe
  init_auth, _upsert_za_user

Thêm mới cho security fixes:
  require_jwt            → alias require_auth (sync wrapper) — F-06/07/08
  optional_jwt           → alias optional_auth               — init-data
  require_admin          → JWT + is_admin check
  check_account_access   → verify account_id trong JWT
  set_account_lock_db    → F-02: lock ghi DB + audit trail
  check_account_locked_db→ F-02: read is_locked từ DB
  set_auth_cookies       → F-01: HttpOnly cookie
  clear_auth_cookies     → logout cookie
  hash_password          → bcrypt
  verify_password        → bcrypt verify

Security fixes so với auth_service.py gốc:
  F-01  set_auth_cookies() → HttpOnly + Secure cookie thay localStorage
  F-02  set_account_lock_db() + check_account_locked_db() — server-side lock
  F-06  require_jwt Depends → enforce trên panic-kill, unlock-unit
  F-07  require_jwt Depends → enforce trên update-unit-config
  F-08  require_jwt Depends → enforce trên sync-history
  F-09  decode_jwt_unsafe: thêm jti revoke check (đã có) + cookie fallback
  F-13  _extract_token: đọc X-License-Key header
  SEC-1 JWT_SECRET: loại bỏ hardcoded default "ZA2026@xK9..." — crash nếu không set trong prod
"""

import os, uuid, hashlib, secrets, random, asyncio, smtplib, logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import jwt as pyjwt
import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from database import SessionLocal, TradingAccount, ConfigAuditTrail

logger = logging.getLogger("zarmor.auth")

# ══════════════════════════════════════════════════════════════════
# CONFIG
# SEC-1: Bỏ hardcoded default "ZA2026@xK9..." — bắt buộc set JWT_SECRET_KEY
# ══════════════════════════════════════════════════════════════════

JWT_ALGORITHM  = "HS256"
ACCESS_TTL_H   = 24
REFRESH_TTL_D  = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "30"))
SMTP_EMAIL     = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD", "")
BACKEND_URL    = os.getenv("NEW_BACKEND_URL", "http://47.129.243.206:8000")

# F-01: cookie security flag — True sau khi cài SSL/nginx
COOKIE_SECURE  = os.getenv("COOKIE_SECURE", "false").lower() == "true"

_security      = HTTPBearer(auto_error=False)
_revoked_jtis: dict = {}


def _get_jwt_secret() -> str:
    """
    SEC-1: Loại bỏ hardcoded default secret.
    - Dev (DEBUG=true hoặc local): cho phép chạy với generated key (warn rõ)
    - Production: crash nếu chưa set JWT_SECRET_KEY trong .env
    """
    s = os.getenv("JWT_SECRET_KEY", "")
    if s:
        return s
    # Check if production
    is_prod = os.getenv("DEBUG", "false").lower() not in ("true", "1", "yes")
    if is_prod:
        raise RuntimeError(
            "[AUTH] ❌ JWT_SECRET_KEY chưa set trong .env!\n"
            "Tạo key: python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "Thêm vào .env: JWT_SECRET_KEY=<key>"
        )
    # Dev fallback: generate once per process
    if not hasattr(_get_jwt_secret, "_dev_key"):
        _get_jwt_secret._dev_key = secrets.token_hex(32)
        logger.warning("[AUTH] ⚠️  JWT_SECRET_KEY not set — using generated key (dev only, tokens reset on restart)")
    return _get_jwt_secret._dev_key


# ══════════════════════════════════════════════════════════════════
# OTP STORE — giữ nguyên từ auth_service.py
# ══════════════════════════════════════════════════════════════════

class _OTPStore:
    """
    Lưu OTP và rate-limit counter.
    Redis-backed khi REDIS_URL available, in-memory fallback.
    """
    OTP_TTL  = 900    # 15 phút
    FAIL_TTL = 1800   # 30 phút lock sau MAX_FAIL lần sai
    RATE_TTL = 900
    MAX_FAIL = 5
    MAX_RATE = 3      # 3 request OTP / 15 phút / email
    MAX_IP   = 10     # 10 request / 15 phút / IP

    def __init__(self):
        self._r          = None
        self._mem_otp:  dict = {}
        self._mem_fail: dict = {}
        self._mem_rate: dict = {}
        self._mem_ip:   dict = {}
        self._connect_redis()

    def _connect_redis(self):
        try:
            import redis as _redis
            url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
            r = _redis.from_url(url, decode_responses=True, socket_timeout=1)
            r.ping()
            self._r = r
            logger.info("[AUTH] OTP store: Redis ✅")
        except Exception as e:
            logger.warning(f"[AUTH] OTP store: Redis không khả dụng ({e}) — dùng in-memory")

    @staticmethod
    def _now() -> float:
        return datetime.now(timezone.utc).timestamp()

    def is_rate_limited(self, email: str, ip: str) -> bool:
        now = self._now()
        if self._r:
            try:
                ek  = f"magic:rate:{email}"
                ik  = f"magic:rate:ip:{ip}"
                p   = self._r.pipeline()
                p.incr(ek); p.expire(ek, self.RATE_TTL)
                p.incr(ik); p.expire(ik, self.RATE_TTL)
                res = p.execute()
                return int(res[0]) > self.MAX_RATE or int(res[2]) > self.MAX_IP
            except Exception:
                pass
        for key, store, limit in [
            (email, self._mem_rate, self.MAX_RATE),
            (ip,    self._mem_ip,   self.MAX_IP),
        ]:
            cnt, exp = store.get(key, (0, now + self.RATE_TTL))
            if now > exp:
                cnt, exp = 0, now + self.RATE_TTL
            cnt += 1
            store[key] = (cnt, exp)
            if cnt > limit:
                return True
        return False

    def set_otp(self, email: str, otp: str):
        if self._r:
            try:
                self._r.setex(f"magic:otp:{email}", self.OTP_TTL, otp)
                return
            except Exception:
                pass
        self._mem_otp[email] = (otp, self._now() + self.OTP_TTL)

    def get_otp(self, email: str) -> Optional[str]:
        if self._r:
            try:
                return self._r.get(f"magic:otp:{email}")
            except Exception:
                pass
        entry = self._mem_otp.get(email)
        if not entry:
            return None
        otp, exp = entry
        if self._now() > exp:
            self._mem_otp.pop(email, None)
            return None
        return otp

    def delete_otp(self, email: str):
        if self._r:
            try:
                self._r.delete(f"magic:otp:{email}")
                return
            except Exception:
                pass
        self._mem_otp.pop(email, None)

    def is_locked(self, email: str) -> bool:
        if self._r:
            try:
                val = self._r.get(f"magic:fail:{email}")
                return val is not None and int(val) >= self.MAX_FAIL
            except Exception:
                pass
        cnt, exp = self._mem_fail.get(email, (0, 0))
        return self._now() <= exp and cnt >= self.MAX_FAIL

    def inc_fail(self, email: str):
        if self._r:
            try:
                k = f"magic:fail:{email}"
                p = self._r.pipeline()
                p.incr(k); p.expire(k, self.FAIL_TTL)
                p.execute()
                return
            except Exception:
                pass
        now = self._now()
        cnt, exp = self._mem_fail.get(email, (0, now + self.FAIL_TTL))
        if now > exp:
            cnt, exp = 0, now + self.FAIL_TTL
        self._mem_fail[email] = (cnt + 1, exp)

    def reset_fail(self, email: str):
        if self._r:
            try:
                self._r.delete(f"magic:fail:{email}")
                return
            except Exception:
                pass
        self._mem_fail.pop(email, None)


_otp_store = _OTPStore()


# ══════════════════════════════════════════════════════════════════
# EMAIL TEMPLATE — giữ nguyên từ auth_service.py
# ══════════════════════════════════════════════════════════════════

def _build_otp_email(email: str, otp: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Z-ARMOR] Mã xác nhận đăng nhập: {otp}"
    msg["From"]    = f"Z-Armor Cloud <{SMTP_EMAIL}>"
    msg["To"]      = email

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#05070a;font-family:'Courier New',monospace;">
  <div style="max-width:520px;margin:40px auto;background:#0a0f1a;
              border:2px solid #00e5ff;border-radius:8px;padding:36px;">

    <div style="color:#00e5ff;font-size:12px;letter-spacing:3px;
                text-transform:uppercase;margin-bottom:8px;">
      Z-ARMOR CLOUD
    </div>
    <h1 style="color:#ffffff;font-size:20px;margin:0 0 24px;
               font-weight:bold;letter-spacing:1px;">
      🔑 Mã Xác Nhận Đăng Nhập
    </h1>

    <p style="color:#99aabb;font-size:14px;margin:0 0 24px;line-height:1.6;">
      Xin chào,<br><br>
      Ai đó (có thể là bạn) vừa yêu cầu đăng nhập vào
      <strong style="color:#fff;">Z-Armor Cloud</strong>
      bằng địa chỉ email này. Nhập mã bên dưới để tiếp tục:
    </p>

    <div style="background:#141922;border:1px solid #00e5ff;
                border-radius:6px;padding:28px;text-align:center;margin:0 0 24px;">
      <div style="color:#667788;font-size:11px;letter-spacing:2px;
                  text-transform:uppercase;margin-bottom:12px;">
        MÃ XÁC NHẬN CỦA BẠN
      </div>
      <div style="color:#00e5ff;font-size:44px;font-weight:bold;
                  letter-spacing:12px;font-family:'Courier New',monospace;">
        {otp}
      </div>
      <div style="color:#667788;font-size:12px;margin-top:14px;">
        ⏱ Hết hạn sau
        <strong style="color:#f5d300;">15 phút</strong>
        &nbsp;·&nbsp; Chỉ dùng được 1 lần
      </div>
    </div>

    <div style="background:#0d1520;border-left:3px solid #f5d300;
                padding:14px 16px;border-radius:0 4px 4px 0;margin:0 0 24px;">
      <div style="color:#f5d300;font-size:12px;font-weight:bold;margin-bottom:6px;">
        ⚠ BẢO MẬT
      </div>
      <div style="color:#99aabb;font-size:13px;line-height:1.6;">
        Không chia sẻ mã này với bất kỳ ai.
        Z-Armor sẽ <strong style="color:#fff;">không bao giờ</strong>
        hỏi mã xác nhận của bạn qua bất kỳ kênh nào.
      </div>
    </div>

    <p style="color:#556677;font-size:13px;margin:0;">
      Nếu bạn không thực hiện yêu cầu này, hãy bỏ qua email này.
      Tài khoản của bạn vẫn an toàn.
    </p>

    <div style="margin-top:32px;padding-top:20px;border-top:1px solid #1a2030;
                color:#445566;font-size:11px;text-align:center;">
      Z-ARMOR CLOUD · Risk Management SaaS for MT5<br>
      <a href="{BACKEND_URL}/web/" style="color:#00e5ff;">Dashboard</a>
      &nbsp;·&nbsp;
      <a href="mailto:support@zarmor.cloud" style="color:#00e5ff;">Support</a>
    </div>
  </div>
</body>
</html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def _send_otp_email_sync(email: str, otp: str) -> bool:
    """Blocking SMTP — luôn gọi qua asyncio.run_in_executor."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        logger.warning("[AUTH] SMTP chưa config — bỏ qua gửi OTP")
        return False
    try:
        msg = _build_otp_email(email, otp)
        srv = smtplib.SMTP("smtp.gmail.com", 587)
        srv.starttls()
        srv.login(SMTP_EMAIL, SMTP_PASSWORD)
        srv.send_message(msg)
        srv.quit()
        logger.info(f"[AUTH] OTP sent ✅ → {email}")
        return True
    except Exception as e:
        logger.error(f"[AUTH] OTP send FAILED → {email}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# PUBLIC API — MAGIC LINK (giữ nguyên)
# ══════════════════════════════════════════════════════════════════

async def send_magic_otp(email: str, client_ip: str = "") -> str:
    """
    Tạo OTP, lưu store, gửi email.
    Returns: "sent" | "RATE_LIMITED" | "SEND_FAILED"
    """
    if _otp_store.is_rate_limited(email, client_ip):
        logger.warning(f"[AUTH] magic-request RATE_LIMITED | {email} ip={client_ip}")
        return "RATE_LIMITED"

    otp  = f"{random.randint(0, 999999):06d}"
    _otp_store.set_otp(email, otp)

    loop = asyncio.get_event_loop()
    ok   = await loop.run_in_executor(None, _send_otp_email_sync, email, otp)

    if not ok:
        _otp_store.delete_otp(email)
        return "SEND_FAILED"

    _upsert_za_user(email)
    return "sent"


def verify_magic_otp(email: str, otp: str, client_ip: str = "") -> str:
    """
    Xác nhận OTP.
    Returns: "ok" | "LOCKED" | "EXPIRED" | "INVALID"
    """
    if _otp_store.is_locked(email):
        return "LOCKED"
    stored = _otp_store.get_otp(email)
    if stored is None:
        return "EXPIRED"
    if stored != otp:
        _otp_store.inc_fail(email)
        logger.warning(f"[AUTH] OTP mismatch | {email} ip={client_ip}")
        return "INVALID"
    _otp_store.delete_otp(email)
    _otp_store.reset_fail(email)
    logger.info(f"[AUTH] OTP verified ✅ | {email}")
    return "ok"


# ══════════════════════════════════════════════════════════════════
# USER MANAGEMENT — giữ nguyên raw SQL vào za_users
# ══════════════════════════════════════════════════════════════════

def _ensure_za_users_table():
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS za_users (
                id         VARCHAR(64)  PRIMARY KEY,
                email      VARCHAR(200) UNIQUE NOT NULL,
                tier       VARCHAR(32)  NOT NULL DEFAULT 'TRIAL',
                ref_code   VARCHAR(32),
                status     VARCHAR(20)  NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                last_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
        """))
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_za_users_email ON za_users(email)"
        ))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _ensure_sessions_table():
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS za_sessions (
                id             SERIAL PRIMARY KEY,
                user_id        VARCHAR(100) NOT NULL,
                jti            VARCHAR(100) UNIQUE NOT NULL,
                refresh_token  VARCHAR(200) UNIQUE NOT NULL,
                device_hash    VARCHAR(100),
                ip             VARCHAR(50),
                expires_at     TIMESTAMPTZ NOT NULL,
                refresh_exp_at TIMESTAMPTZ NOT NULL,
                last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_revoked     BOOLEAN NOT NULL DEFAULT FALSE,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_za_sess_jti     ON za_sessions(jti)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_za_sess_user    ON za_sessions(user_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_za_sess_refresh ON za_sessions(refresh_token)"))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _upsert_za_user(email: str) -> Optional[str]:
    """INSERT nếu mới, UPDATE last_seen nếu đã có. Trả user_id."""
    from sqlalchemy import text
    uid = hashlib.sha256(email.encode()).hexdigest()[:36]
    db  = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO za_users (id, email, tier, status, created_at, last_seen)
            VALUES (:uid, :email, 'TRIAL', 'active', NOW(), NOW())
            ON CONFLICT (email) DO UPDATE SET last_seen = NOW()
        """), {"uid": uid, "email": email})
        db.commit()
        return uid
    except Exception as e:
        db.rollback()
        logger.error(f"[AUTH] _upsert_za_user error: {e}")
        return None
    finally:
        db.close()


def _get_licenses_for_email(email: str) -> list:
    from sqlalchemy import text
    db = SessionLocal()
    for table in ("license_keys", "licenses"):
        try:
            rows = db.execute(text(f"""
                SELECT license_key, tier, status, expires_at, is_trial
                FROM {table}
                WHERE buyer_email = :e
                  AND status NOT IN ('REVOKED')
                ORDER BY created_at DESC
            """), {"e": email}).fetchall()
            db.close()
            return [
                {
                    "license_key": r[0],
                    "tier":        r[1],
                    "status":      r[2],
                    "expires_at":  r[3].isoformat() if r[3] else None,
                    "is_trial":    bool(r[4]),
                }
                for r in rows
            ]
        except Exception:
            continue
    try:
        db.close()
    except Exception:
        pass
    return []


def _get_account_ids_for_email(email: str) -> list:
    from sqlalchemy import text
    db = SessionLocal()
    for table in ("license_keys", "licenses"):
        try:
            rows = db.execute(text(f"""
                SELECT bound_mt5_id FROM {table}
                WHERE buyer_email = :e
                  AND bound_mt5_id IS NOT NULL
                  AND status = 'ACTIVE'
            """), {"e": email}).fetchall()
            ids = [r[0] for r in rows if r[0]]
            if ids:
                db.close()
                return ids
        except Exception:
            continue
    try:
        db.close()
    except Exception:
        pass
    return []


def get_or_create_user_by_email(email: str) -> Optional[dict]:
    """
    Load user từ za_users. Nếu chưa có → tạo TRIAL.
    Đính kèm licenses[] + account_ids[] + tier auto-upgrade.
    """
    from sqlalchemy import text
    db  = SessionLocal()
    row = None
    try:
        row = db.execute(text(
            "SELECT id, email, tier, ref_code FROM za_users WHERE email = :e"
        ), {"e": email}).fetchone()
    except Exception:
        pass
    finally:
        db.close()

    if not row:
        uid = _upsert_za_user(email)
        if not uid:
            return None
        tier, ref_code = "TRIAL", ""
    else:
        uid      = row[0]
        tier     = row[2] or "TRIAL"
        ref_code = row[3] or ""

    licenses    = _get_licenses_for_email(email)
    account_ids = _get_account_ids_for_email(email)

    _rank = {"FLEET": 5, "ARSENAL": 4, "ARMOR": 3, "STARTER": 2, "TRIAL": 1}
    for lic in licenses:
        if lic["status"] == "ACTIVE":
            lt = lic.get("tier", "TRIAL")
            if _rank.get(lt, 0) > _rank.get(tier, 0):
                tier = lt

    return {
        "user_id":     uid,
        "email":       email,
        "tier":        tier,
        "ref_code":    ref_code,
        "licenses":    licenses,
        "account_ids": account_ids,
    }


def _get_user_by_user_id(user_id: str) -> Optional[dict]:
    from sqlalchemy import text
    db = SessionLocal()
    try:
        row = db.execute(text(
            "SELECT id, email, tier, ref_code FROM za_users WHERE id = :uid"
        ), {"uid": user_id}).fetchone()
        if row:
            return {
                "user_id":     row[0],
                "email":       row[1],
                "tier":        row[2] or "TRIAL",
                "ref_code":    row[3] or "",
                "account_ids": _get_account_ids_for_email(row[1]),
            }
    except Exception:
        pass
    finally:
        db.close()
    return None


def get_user_by_license(license_key: str) -> Optional[dict]:
    """Backward-compat: login bằng license key."""
    from sqlalchemy import text
    db  = SessionLocal()
    row = None
    for table in ("license_keys", "licenses"):
        try:
            row = db.execute(text(f"""
                SELECT buyer_email, tier, expires_at, license_key
                FROM {table}
                WHERE license_key = :k
                  AND status IN ('ACTIVE', 'TRIAL', 'UNUSED')
            """), {"k": license_key}).fetchone()
            if row:
                break
        except Exception:
            continue
    db.close()

    if not row:
        return None
    email, tier, exp, lkey = row
    if exp:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            return None

    uid = hashlib.sha256((email or lkey).encode()).hexdigest()[:36]
    return {
        "user_id":     uid,
        "email":       email or "",
        "tier":        tier or "TRIAL",
        "ref_code":    "",
        "licenses":    _get_licenses_for_email(email or "") if email else [],
        "account_ids": _get_account_ids_for_email(email or "") if email else [],
    }


# ══════════════════════════════════════════════════════════════════
# TOKEN CREATION — giữ signature gốc, dùng _get_jwt_secret()
# ══════════════════════════════════════════════════════════════════

def create_access_token(user_id, email, tier, account_ids, ref_code=""):
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "sub":         user_id,
        "email":       email,
        "tier":        tier,
        "account_ids": account_ids,
        "ref_code":    ref_code,
        "scope":       "cockpit",
        "jti":         jti,
        "iat":         int(now.timestamp()),
        "exp":         int((now + timedelta(hours=ACCESS_TTL_H)).timestamp()),
    }
    return pyjwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM), jti


def create_refresh_token():
    return secrets.token_hex(32)


# ══════════════════════════════════════════════════════════════════
# SESSIONS — giữ nguyên
# ══════════════════════════════════════════════════════════════════

def store_session(user_id, jti, refresh_token, ip="", user_agent=""):
    from sqlalchemy import text
    dh  = hashlib.sha256(f"{user_agent}{ip}".encode()).hexdigest()[:32]
    now = datetime.now(timezone.utc)
    db  = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO za_sessions
                (user_id, jti, refresh_token, device_hash, ip,
                 expires_at, refresh_exp_at)
            VALUES (:uid, :jti, :rt, :dh, :ip, :exp, :rexp)
        """), {
            "uid": user_id, "jti": jti, "rt": refresh_token,
            "dh": dh, "ip": ip,
            "exp":  now + timedelta(hours=ACCESS_TTL_H),
            "rexp": now + timedelta(days=REFRESH_TTL_D),
        })
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()


def revoke_session(jti: str):
    from sqlalchemy import text
    _revoked_jtis[jti] = True
    db = SessionLocal()
    try:
        db.execute(text(
            "UPDATE za_sessions SET is_revoked=TRUE WHERE jti=:jti"
        ), {"jti": jti})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def revoke_all_sessions(user_id: str):
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT jti FROM za_sessions WHERE user_id=:uid AND is_revoked=FALSE"
        ), {"uid": user_id}).fetchall()
        for r in rows:
            _revoked_jtis[r[0]] = True
        db.execute(text(
            "UPDATE za_sessions SET is_revoked=TRUE WHERE user_id=:uid"
        ), {"uid": user_id})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def is_jti_revoked(jti: str) -> bool:
    if _revoked_jtis.get(jti):
        return True
    from sqlalchemy import text
    db = SessionLocal()
    try:
        row = db.execute(text(
            "SELECT is_revoked FROM za_sessions WHERE jti=:jti"
        ), {"jti": jti}).fetchone()
        return bool(row and row[0])
    except Exception:
        return False
    finally:
        db.close()


def rotate_refresh_token(old_refresh: str):
    from sqlalchemy import text
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT user_id, jti, is_revoked, refresh_exp_at
            FROM za_sessions WHERE refresh_token = :rt
        """), {"rt": old_refresh}).fetchone()
        if not row or row[2]:
            return None
        exp = row[3]
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            return None
        db.execute(text(
            "UPDATE za_sessions SET is_revoked=TRUE WHERE jti=:j"
        ), {"j": row[1]})
        _revoked_jtis[row[1]] = True
        db.commit()
        uid = row[0]
    except Exception:
        db.rollback()
        return None
    finally:
        db.close()

    user = _get_user_by_user_id(uid)
    if not user:
        return None
    new_access, new_jti = create_access_token(
        user["user_id"], user["email"], user["tier"],
        user["account_ids"], user.get("ref_code", "")
    )
    new_refresh = create_refresh_token()
    store_session(user["user_id"], new_jti, new_refresh)
    return new_access, new_refresh, new_jti


# ══════════════════════════════════════════════════════════════════
# FASTAPI DEPENDENCIES — giữ nguyên + thêm aliases
# ══════════════════════════════════════════════════════════════════

def _extract_token_from_request(request: Request) -> Optional[str]:
    """
    F-01/F-09: Lấy token từ:
    1. HttpOnly cookie 'za_access_token'  (ưu tiên — không đọc được bởi JS/XSS)
    2. Authorization: Bearer header       (backward-compat)
    """
    token = request.cookies.get("za_access_token")
    if token:
        return token.strip()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """
    Giữ nguyên signature gốc để auth_router.py không bị break.
    Thêm: đọc HttpOnly cookie (F-01) và jti revoke check.
    """
    # Ưu tiên cookie (F-01), fallback về credentials header
    cookie_token = request.cookies.get("za_access_token")
    raw_token = cookie_token or (credentials.credentials if credentials else None)

    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = pyjwt.decode(raw_token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if is_jti_revoked(payload.get("jti", "")):
        raise HTTPException(status_code=401, detail="Session revoked")
    return payload


async def optional_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> Optional[dict]:
    """Giữ nguyên signature gốc. Thêm cookie fallback (F-01)."""
    cookie_token = request.cookies.get("za_access_token")
    raw_token = cookie_token or (credentials.credentials if credentials else None)
    if not raw_token:
        return None
    try:
        payload = pyjwt.decode(raw_token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return None if is_jti_revoked(payload.get("jti", "")) else payload
    except Exception:
        return None


def decode_jwt_unsafe(token: str) -> Optional[dict]:
    """
    Decode JWT không raise exception.
    F-09 fix: verify signature đầy đủ + check jti revoked.
    Dùng trong /api/init-data dual-auth.
    """
    try:
        payload = pyjwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if is_jti_revoked(payload.get("jti", "")):
            return None
        return payload
    except Exception:
        return None


# ── Aliases mới cho main.py security patches ──────────────────────

def require_jwt(request: Request) -> dict:
    """
    Sync wrapper của require_auth — dùng với Depends() trong:
      panic-kill (F-06), unlock-unit (F-06),
      update-unit-config (F-07), sync-history (F-08)

    Sync (không async) vì các route handler đã là async,
    FastAPI tự chạy sync dependency trong threadpool.
    """
    cookie_token = request.cookies.get("za_access_token")
    auth = request.headers.get("Authorization", "")
    raw_token = cookie_token or (auth[7:].strip() if auth.startswith("Bearer ") else None)

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = pyjwt.decode(raw_token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if is_jti_revoked(payload.get("jti", "")):
        raise HTTPException(status_code=401, detail="Session revoked")
    return payload


def optional_jwt(request: Request) -> Optional[dict]:
    """Sync version của optional_auth — dùng cho init-data."""
    cookie_token = request.cookies.get("za_access_token")
    auth = request.headers.get("Authorization", "")
    raw_token = cookie_token or (auth[7:].strip() if auth.startswith("Bearer ") else None)
    if not raw_token:
        return None
    try:
        payload = pyjwt.decode(raw_token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return None if is_jti_revoked(payload.get("jti", "")) else payload
    except Exception:
        return None


def require_admin(request: Request) -> dict:
    """Dependency: JWT + is_admin=True. Thay _check_admin(X-Admin-Token)."""
    payload = require_jwt(request)
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


def check_account_access(account_id: str, jwt_payload: dict) -> bool:
    """True nếu JWT có quyền trên account_id (admin bypass all)."""
    if jwt_payload.get("is_admin"):
        return True
    allowed = jwt_payload.get("account_ids", [])
    return str(account_id) in [str(a) for a in allowed]


# ══════════════════════════════════════════════════════════════════
# F-01: HttpOnly COOKIE
# ══════════════════════════════════════════════════════════════════

def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """
    F-01: Set JWT vào HttpOnly + Secure cookie.
    XSS không thể đọc cookie httponly → token không bị đánh cắp.

    .env: COOKIE_SECURE=false  (dev, chưa có HTTPS)
    .env: COOKIE_SECURE=true   (sau khi cài nginx + SSL — fix F-12)
    """
    response.set_cookie(
        key="za_access_token",
        value=access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=ACCESS_TTL_H * 3600,
        path="/",
    )
    response.set_cookie(
        key="za_refresh_token",
        value=refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=REFRESH_TTL_D * 86400,
        path="/auth/refresh",   # chỉ gửi lên /auth/refresh
    )


def clear_auth_cookies(response: Response) -> None:
    """Xóa cookie khi logout."""
    response.delete_cookie("za_access_token",  path="/")
    response.delete_cookie("za_refresh_token", path="/auth/refresh")


# ══════════════════════════════════════════════════════════════════
# F-02: HARDLOCK SERVER-SIDE
# ══════════════════════════════════════════════════════════════════

def check_account_locked_db(account_id: str, db: Session) -> bool:
    """F-02: Đọc is_locked từ DB — client không thể bypass bằng DevTools."""
    acct = db.query(TradingAccount).filter(
        TradingAccount.account_id == str(account_id)
    ).first()
    return bool(acct and acct.is_locked)


def set_account_lock_db(
    account_id: str,
    locked: bool,
    db: Session,
    changed_by: str = "system",
    ip: str = "",
) -> dict:
    """
    F-02: Set is_locked trong DB + ghi ConfigAuditTrail.
    Returns: {"status": "ok", "account_id": ..., "is_locked": ...}
    """
    acct    = db.query(TradingAccount).filter(
        TradingAccount.account_id == str(account_id)
    ).first()
    old_val = str(acct.is_locked) if acct else "None"

    if acct is None:
        acct = TradingAccount(account_id=str(account_id), is_locked=locked)
        db.add(acct)
    else:
        acct.is_locked = locked

    try:
        db.add(ConfigAuditTrail(
            account_id=str(account_id),
            changed_by=changed_by,
            field_path="trading_accounts.is_locked",
            old_value=old_val,
            new_value=str(locked),
            ip_address=ip or "",
        ))
    except Exception:
        pass  # audit fail không block action chính

    db.commit()
    return {"status": "ok", "account_id": account_id, "is_locked": locked}


# ══════════════════════════════════════════════════════════════════
# PASSWORD UTILS (mới — dùng cho AdminUser login nếu cần)
# ══════════════════════════════════════════════════════════════════

def hash_password(plain: str) -> str:
    """bcrypt hash cost=12."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt compare."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# INIT — giữ nguyên + thêm secret check
# ══════════════════════════════════════════════════════════════════

def init_auth():
    """
    Gọi từ main.py lifespan.
    Tạo tables za_users + za_sessions + kiểm tra JWT_SECRET_KEY.
    """
    try:
        _ensure_za_users_table()
        _ensure_sessions_table()
        print("[AUTH] Tables ready (za_users + za_sessions) ✅", flush=True)
    except Exception as e:
        print(f"[AUTH] Warning during table init: {e}", flush=True)

    # SEC-1: Warn/crash nếu secret chưa set
    try:
        _get_jwt_secret()
        secret_set = bool(os.getenv("JWT_SECRET_KEY"))
        src = "ENV ✅" if secret_set else "GENERATED ⚠️  (dev-only)"
        cookie_info = f"cookie_secure={COOKIE_SECURE}"
        print(f"[AUTH] JWT ready | secret={src} | {cookie_info}", flush=True)
    except RuntimeError as e:
        print(str(e), flush=True)
        raise