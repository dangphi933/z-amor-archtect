"""
shared/libs/cache/redis_store.py
==================================
Redis-backed store thay thế tất cả in-memory dicts.
Safe với multi-worker (uvicorn --workers N) vì state nằm trên Redis.

Covers:
  OTPStore        — otp:{email}              TTL 900s
  RateLimit       — rate:{scope}:{key}       TTL sliding window
  SessionStore    — session:{jti}            TTL per-token
  EASessionStore  — ea_session:{token}       TTL 70s sliding
  JTIRevoke       — revoked_jti:{jti}        TTL = refresh TTL
  LicenseCache    — license_cache:{key}      TTL 30s

Fallback: nếu Redis không available, dùng in-memory dict với warning.
Không crash service khi Redis down — degraded mode.
"""

import os
import json
import time
import logging
from typing import Optional, Any

logger = logging.getLogger("zarmor.cache")

_redis = None
_warned_no_redis = False


def _get_redis():
    global _redis, _warned_no_redis
    if _redis is not None:
        try:
            _redis.ping()
            return _redis
        except Exception:
            _redis = None

    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        if not _warned_no_redis:
            logger.warning("[CACHE] REDIS_URL not set — using in-memory fallback (NOT safe for multi-worker)")
            _warned_no_redis = True
        return None

    try:
        import redis as redis_lib
        _redis = redis_lib.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            retry_on_timeout=True,
        )
        _redis.ping()
        logger.info("[CACHE] Redis connected")
        return _redis
    except Exception as e:
        logger.error(f"[CACHE] Redis connect failed: {e} — falling back to in-memory")
        return None


# ── In-memory fallback (single-worker dev only) ───────────────────
_mem: dict = {}


def _mem_get(key: str) -> Optional[str]:
    entry = _mem.get(key)
    if not entry:
        return None
    if entry.get("expires_at") and time.time() > entry["expires_at"]:
        del _mem[key]
        return None
    return entry["value"]


def _mem_set(key: str, value: str, ttl: int = 0):
    _mem[key] = {
        "value": value,
        "expires_at": (time.time() + ttl) if ttl else None,
    }


def _mem_del(key: str):
    _mem.pop(key, None)


def _mem_exists(key: str) -> bool:
    return _mem_get(key) is not None


# ══════════════════════════════════════════════════════════════════
# GENERIC HELPERS
# ══════════════════════════════════════════════════════════════════

def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    """Set key với TTL (giây). value được JSON-serialize."""
    r = _get_redis()
    data = json.dumps(value) if not isinstance(value, str) else value
    if r:
        try:
            r.setex(key, ttl, data)
            return True
        except Exception as e:
            logger.error(f"[CACHE] set {key}: {e}")
            return False
    _mem_set(key, data, ttl)
    return True


def cache_get(key: str) -> Optional[Any]:
    """Get key. Returns parsed JSON hoặc str."""
    r = _get_redis()
    if r:
        try:
            val = r.get(key)
            if val is None:
                return None
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return val
        except Exception as e:
            logger.error(f"[CACHE] get {key}: {e}")
            return None
    val = _mem_get(key)
    if val is None:
        return None
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        return val


def cache_delete(key: str):
    r = _get_redis()
    if r:
        try:
            r.delete(key)
        except Exception as e:
            logger.error(f"[CACHE] delete {key}: {e}")
        return
    _mem_del(key)


def cache_exists(key: str) -> bool:
    r = _get_redis()
    if r:
        try:
            return bool(r.exists(key))
        except Exception:
            return False
    return _mem_exists(key)


def cache_incr(key: str, ttl: int = 900) -> int:
    """Increment counter. Set TTL khi tạo lần đầu."""
    r = _get_redis()
    if r:
        try:
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl)
            results = pipe.execute()
            return results[0]
        except Exception as e:
            logger.error(f"[CACHE] incr {key}: {e}")
            return 0
    # in-memory fallback
    entry = _mem.get(key)
    if not entry or (entry.get("expires_at") and time.time() > entry["expires_at"]):
        _mem_set(key, "1", ttl)
        return 1
    val = int(entry["value"]) + 1
    entry["value"] = str(val)
    return val


def hset_multi(key: str, mapping: dict, ttl: int = 0):
    """Set multiple hash fields."""
    r = _get_redis()
    if r:
        try:
            r.hset(key, mapping=mapping)
            if ttl:
                r.expire(key, ttl)
        except Exception as e:
            logger.error(f"[CACHE] hset {key}: {e}")
        return
    # Store as JSON in mem fallback
    existing = cache_get(key) or {}
    existing.update(mapping)
    cache_set(key, existing, ttl or 86400)


def hget_all(key: str) -> dict:
    """Get all hash fields."""
    r = _get_redis()
    if r:
        try:
            return r.hgetall(key) or {}
        except Exception as e:
            logger.error(f"[CACHE] hgetall {key}: {e}")
            return {}
    val = cache_get(key)
    return val if isinstance(val, dict) else {}


# ══════════════════════════════════════════════════════════════════
# OTP STORE
# ══════════════════════════════════════════════════════════════════

OTP_TTL        = 900   # 15 phút
OTP_MAX_TRIES  = 3
OTP_RATE_LIMIT = 3     # max 3 OTP requests per 15 phút


def otp_rate_check(email: str) -> bool:
    """True = under limit, False = exceeded. Dùng Redis counter."""
    key = f"otp_rate:{email}"
    count = cache_incr(key, ttl=OTP_TTL)
    return count <= OTP_RATE_LIMIT


def otp_store(email: str, otp: str):
    hset_multi(f"otp:{email}", {"otp": otp, "attempts": "0"}, ttl=OTP_TTL)


def otp_verify(email: str, code: str) -> str:
    """Returns: 'ok' | 'INVALID' | 'EXPIRED' | 'MAX_ATTEMPTS'"""
    key = f"otp:{email}"
    data = hget_all(key)
    if not data:
        return "EXPIRED"

    attempts = int(data.get("attempts", "0"))
    if attempts >= OTP_MAX_TRIES:
        cache_delete(key)
        return "MAX_ATTEMPTS"

    r = _get_redis()
    if r:
        try:
            r.hincrby(key, "attempts", 1)
        except Exception:
            pass
    else:
        val = cache_get(key) or {}
        val["attempts"] = str(attempts + 1)
        cache_set(key, val, OTP_TTL)

    if data.get("otp", "") != code.strip():
        return "INVALID"

    cache_delete(key)
    return "ok"


# ══════════════════════════════════════════════════════════════════
# REFRESH TOKEN STORE
# ══════════════════════════════════════════════════════════════════

REFRESH_TTL = int(os.getenv("JWT_REFRESH_TTL_DAYS", "30")) * 86400


def refresh_token_store(jti: str, email: str, ip: str = ""):
    hset_multi(f"refresh:{jti}", {
        "email": email,
        "ip":    ip,
        "ts":    str(int(time.time())),
    }, ttl=REFRESH_TTL)


def refresh_token_get(jti: str) -> Optional[dict]:
    data = hget_all(f"refresh:{jti}")
    return data if data else None


def refresh_token_revoke(jti: str):
    cache_delete(f"refresh:{jti}")
    # Mark revoked agar double-spend detection
    cache_set(f"revoked_jti:{jti}", "1", ttl=REFRESH_TTL)


def refresh_token_revoke_all(email: str):
    """Revoke tất cả refresh tokens của 1 email."""
    r = _get_redis()
    if r:
        try:
            keys = list(r.scan_iter("refresh:*"))
            for k in keys:
                try:
                    data = r.hgetall(k)
                    if data.get("email") == email:
                        jti = k.replace("refresh:", "")
                        refresh_token_revoke(jti)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[CACHE] revoke_all {email}: {e}")
        return
    # mem fallback
    to_del = [k for k, v in _mem.items()
              if k.startswith("refresh:") and isinstance(v.get("value"), str)]
    for k in to_del:
        _mem_del(k)


def is_jti_revoked(jti: str) -> bool:
    return cache_exists(f"revoked_jti:{jti}")


# ══════════════════════════════════════════════════════════════════
# EA SESSION STORE
# ══════════════════════════════════════════════════════════════════

EA_SESSION_TTL = 70   # seconds — sliding window reset mỗi heartbeat


def ea_session_set(token: str, data: dict, ttl: int = EA_SESSION_TTL):
    """Lưu EA session. data = dict với account_id, tier, etc."""
    cache_set(f"ea_session:{token}", data, ttl)


def ea_session_get(token: str) -> Optional[dict]:
    return cache_get(f"ea_session:{token}")


def ea_session_refresh_ttl(token: str):
    """Sliding window: reset TTL về 70s mỗi heartbeat."""
    r = _get_redis()
    if r:
        try:
            r.expire(f"ea_session:{token}", EA_SESSION_TTL)
            return
        except Exception:
            pass
    # mem fallback: re-read và re-write
    data = ea_session_get(token)
    if data:
        ea_session_set(token, data, EA_SESSION_TTL)


def ea_session_delete(token: str):
    cache_delete(f"ea_session:{token}")


def ea_sessions_for_account(account_id: str) -> list:
    """Tìm tất cả session tokens của 1 account (cho revoke)."""
    r = _get_redis()
    tokens = []
    if r:
        try:
            for key in r.scan_iter("ea_session:*"):
                try:
                    data = cache_get(key)
                    if isinstance(data, dict) and data.get("account_id") == account_id:
                        tokens.append(key.replace("ea_session:", ""))
                except Exception:
                    pass
        except Exception:
            pass
    return tokens


# ══════════════════════════════════════════════════════════════════
# RATE LIMITER (sliding window, multi-worker safe)
# ══════════════════════════════════════════════════════════════════

def rate_check(scope: str, key: str, limit: int, window: int = 60) -> bool:
    """
    Sliding window rate limiter dùng Redis sorted set.
    Returns True nếu còn trong limit.
    Falls back to in-memory counter nếu Redis down.
    """
    r = _get_redis()
    now = time.time()
    rkey = f"rate:{scope}:{key}"

    if r:
        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(rkey, "-inf", now - window)
            pipe.zadd(rkey, {str(now): now})
            pipe.zcard(rkey)
            pipe.expire(rkey, window + 5)
            results = pipe.execute()
            count = results[2]
            return count <= limit
        except Exception as e:
            logger.error(f"[RATE] Redis error: {e}")
            # Fall through to mem fallback

    # in-memory fallback
    counter_key = f"rate:{scope}:{key}"
    timestamps = []
    entry = _mem.get(counter_key)
    if entry:
        try:
            timestamps = json.loads(entry["value"])
        except Exception:
            timestamps = []
    timestamps = [t for t in timestamps if now - t < window]
    timestamps.append(now)
    _mem_set(counter_key, json.dumps(timestamps), window + 5)
    return len(timestamps) <= limit


# ══════════════════════════════════════════════════════════════════
# LICENSE CACHE (engine-service, 30s TTL)
# ══════════════════════════════════════════════════════════════════

LICENSE_CACHE_TTL = 30  # seconds


def license_cache_set(license_key: str, data: dict):
    cache_set(f"license_cache:{license_key}", data, ttl=LICENSE_CACHE_TTL)


def license_cache_get(license_key: str) -> Optional[dict]:
    return cache_get(f"license_cache:{license_key}")


def license_cache_invalidate(license_key: str):
    cache_delete(f"license_cache:{license_key}")


# ══════════════════════════════════════════════════════════════════
# RISK CONFIG CACHE (engine-service, 300s TTL)
# ══════════════════════════════════════════════════════════════════

RISK_CONFIG_TTL = 300  # 5 phút


def risk_config_set(account_id: str, config: dict):
    cache_set(f"risk_config:{account_id}", config, ttl=RISK_CONFIG_TTL)


def risk_config_get(account_id: str) -> Optional[dict]:
    return cache_get(f"risk_config:{account_id}")


def risk_config_invalidate(account_id: str):
    cache_delete(f"risk_config:{account_id}")
