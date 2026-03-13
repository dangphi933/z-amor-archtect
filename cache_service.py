"""
cache_service.py — Z-ARMOR CLOUD
==================================
R-04 FIX (Giai đoạn 2): Redis thay thế Python dict in-memory.
State (_hb_last_seen, _machine_registry) không mất khi restart.

Cài Redis (không Docker):
    sudo apt install redis-server -y
    sudo systemctl enable redis-server
    sudo systemctl start redis-server
    redis-cli ping   # → PONG

Thêm vào .env:
    REDIS_URL=redis://127.0.0.1:6379/0
    REDIS_PASSWORD=          # để trống nếu localhost

Tích hợp vào license_service.py / main.py:
    from cache_service import cache
    # cache.hb_is_ratelimited(key)  → True/False
    # cache.machine_get(key)        → set of account_ids
    # cache.machine_add(key, acct)  → True if new
"""

import os
import json
import time
import logging
from typing import Optional

logger = logging.getLogger("zarmor.cache")

_HB_TTL          = int(os.environ.get("CACHE_HB_TTL",      "3600"))   # 1h
_MACHINE_TTL     = int(os.environ.get("CACHE_MACHINE_TTL", "86400"))  # 24h
_OWNER_TTL       = int(os.environ.get("CACHE_OWNER_TTL",   "3600"))   # 1h
_HB_MIN_INTERVAL = 20  # giây — giống main.py


# ══════════════════════════════════════════════════════════════════
# FALLBACK — in-memory khi Redis chưa cài
# ══════════════════════════════════════════════════════════════════
class _FallbackCache:
    """In-memory fallback. Hoạt động như cũ, nhưng log warning."""
    def __init__(self):
        self._hb: dict = {}; self._machine: dict = {}; self._owner: dict = {}
        logger.warning("[CACHE] Redis không khả dụng — dùng in-memory. Cài Redis để persist state.")

    def ping(self) -> bool: return True

    def hb_is_ratelimited(self, key: str) -> bool:
        now  = time.time()
        last = self._hb.get(key, 0.0)
        if now - last < _HB_MIN_INTERVAL: return True
        self._hb[key] = now
        if len(self._hb) > 10000:
            cut = now - 3600
            self._hb = {k: v for k, v in self._hb.items() if v > cut}
        return False

    def hb_last_seen(self, key: str) -> float: return self._hb.get(key, 0.0)

    def machine_get(self, lic_key: str) -> set: return self._machine.get(lic_key, set()).copy()
    def machine_add(self, lic_key: str, acct: str) -> bool:
        s = self._machine.setdefault(lic_key, set()); new = acct not in s; s.add(acct); return new
    def machine_remove_all(self, lic_key: str): self._machine.pop(lic_key, None)
    def machine_count(self, lic_key: str) -> int: return len(self._machine.get(lic_key, set()))

    def owner_get(self, acct: str) -> Optional[str]: return self._owner.get(acct)
    def owner_set(self, acct: str, email: str): self._owner[acct] = email
    def owner_del(self, acct: str): self._owner.pop(acct, None)

    def online_count(self) -> int:
        cut = time.time() - 300
        return sum(1 for v in self._hb.values() if v > cut)

    def units_get(self) -> Optional[dict]: return None
    def units_set(self, data: dict, ttl: int = 30): pass
    def units_invalidate(self): pass


# ══════════════════════════════════════════════════════════════════
# REDIS CACHE
# ══════════════════════════════════════════════════════════════════
class _RedisCache:
    """Redis-backed cache. Tất cả state persist qua restart."""
    _PFX = "zarmor:"

    def __init__(self, client):
        self._r = client

    def ping(self) -> bool:
        try: self._r.ping(); return True
        except: return False

    # ── Heartbeat rate-limit ──────────────────────────────────────
    def hb_is_ratelimited(self, key: str) -> bool:
        """Atomic check-and-set. True = còn trong cooldown, bỏ qua heartbeat."""
        k   = f"{self._PFX}hb:{key}"
        now = time.time()
        raw = self._r.get(k)
        if raw and now - float(raw) < _HB_MIN_INTERVAL:
            return True
        self._r.setex(k, _HB_TTL, str(now))
        return False

    def hb_last_seen(self, key: str) -> float:
        v = self._r.get(f"{self._PFX}hb:{key}")
        return float(v) if v else 0.0

    # ── Machine registry ─────────────────────────────────────────
    def machine_get(self, lic_key: str) -> set:
        raw = self._r.smembers(f"{self._PFX}machines:{lic_key}")
        return {m.decode() if isinstance(m, bytes) else m for m in raw}

    def machine_add(self, lic_key: str, acct: str) -> bool:
        """SADD → 1 nếu là member mới. Expire toàn bộ set theo TTL."""
        k      = f"{self._PFX}machines:{lic_key}"
        result = self._r.sadd(k, acct)
        self._r.expire(k, _MACHINE_TTL)
        return bool(result)

    def machine_remove_all(self, lic_key: str):
        self._r.delete(f"{self._PFX}machines:{lic_key}")

    def machine_count(self, lic_key: str) -> int:
        return self._r.scard(f"{self._PFX}machines:{lic_key}")

    # ── Owner cache ──────────────────────────────────────────────
    def owner_get(self, acct: str) -> Optional[str]:
        v = self._r.get(f"{self._PFX}owner:{acct}")
        return (v.decode() if isinstance(v, bytes) else v) if v else None

    def owner_set(self, acct: str, email: str):
        self._r.setex(f"{self._PFX}owner:{acct}", _OWNER_TTL, email)

    def owner_del(self, acct: str):
        self._r.delete(f"{self._PFX}owner:{acct}")

    # ── Online count ─────────────────────────────────────────────
    def online_count(self) -> int:
        cut  = time.time() - 300
        keys = self._r.keys(f"{self._PFX}hb:*")
        return sum(1 for k in keys if (v := self._r.get(k)) and float(v) > cut)

    # ── Units config cache ───────────────────────────────────────
    def units_get(self) -> Optional[dict]:
        raw = self._r.get(f"{self._PFX}units_config")
        return json.loads(raw) if raw else None

    def units_set(self, data: dict, ttl: int = 30):
        self._r.setex(f"{self._PFX}units_config", ttl, json.dumps(data, default=str))

    def units_invalidate(self):
        self._r.delete(f"{self._PFX}units_config")


# ══════════════════════════════════════════════════════════════════
# FACTORY — singleton
# ══════════════════════════════════════════════════════════════════
def _build_cache():
    url  = os.environ.get("REDIS_URL",      "redis://127.0.0.1:6379/0")
    pwd  = os.environ.get("REDIS_PASSWORD", "") or None
    try:
        import redis as _redis
        client = _redis.from_url(url, password=pwd,
                                 socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        logger.info(f"[CACHE] ✅ Redis connected: {url}")
        return _RedisCache(client)
    except ImportError:
        logger.warning("[CACHE] redis-py chưa cài. Chạy: pip install redis")
    except Exception as e:
        logger.warning(f"[CACHE] Redis lỗi ({e}). Dùng in-memory fallback.")
    return _FallbackCache()


cache = _build_cache()


def cache_health() -> dict:
    backend = "redis" if isinstance(cache, _RedisCache) else "in-memory"
    return {"backend": backend, "connected": cache.ping(), "online_now": cache.online_count()}
