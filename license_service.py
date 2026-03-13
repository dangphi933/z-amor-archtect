"""
license_service.py — Z-ARMOR CLOUD
=====================================
V2.0 (Giai đoạn 2+3 hoàn chỉnh):
  - Dùng cache_service.cache thay dict in-memory (R-04)
  - bind_license gọi atomic_bind_license từ database.py (R-05)
  - admin_reset_binding xóa cache Redis (R-04)
  - admin_get_license_stats lấy online_now từ Redis (R-04)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from database import License, LicenseActivation, atomic_bind_license
from cache_service import cache   # R-04: Redis-backed

logger = logging.getLogger("zarmor.license")

HB_MIN_INTERVAL = 20  # giây — đồng bộ với cache_service


# ══════════════════════════════════════════════════════════════════
# SECTION 1 — HEARTBEAT WITH AUTO-BIND
# ══════════════════════════════════════════════════════════════════

def process_heartbeat(
    db:      Session,
    key:     str,
    account: str,
    magic:   str   = "",
    equity:  float = 0.0,
    balance: float = 0.0,
) -> dict:
    """
    Xử lý heartbeat từ EA.

    Flow:
      1. Rate-limit check → Redis (persist qua restart)
      2. Lookup license key trong DB
      3. Kiểm tra status / expiry
      4. AUTO-BIND nếu key chưa bind và account hợp lệ
      5. Kiểm tra MT5 ID mismatch
      6. Kiểm tra machine limit → Redis
      7. OK → trả về valid=True
    """
    if not key:
        return _resp(False, False, "NO_LICENSE_KEY")

    # ── R-04: Rate limit qua Redis ───────────────────────────────
    if cache.hb_is_ratelimited(key):
        return _resp(True, False, "OK_CACHED")

    # ── Lookup DB ────────────────────────────────────────────────
    lic = db.query(License).filter(License.license_key == key).first()

    if not lic:
        logger.warning(f"[HB] INVALID_KEY | account={account} key={key[:12]}")
        return _resp(False, False, "INVALID_KEY")

    # ── Status / expiry ──────────────────────────────────────────
    if lic.status == "REVOKED":
        return _resp(False, True, "LICENSE_REVOKED")

    if lic.status == "EXPIRED" or _is_expired(lic):
        if lic.status != "EXPIRED":
            lic.status = "EXPIRED"
            db.commit()
        return _resp(False, True, "LICENSE_EXPIRED")

    if lic.status not in ("ACTIVE", "UNUSED"):
        return _resp(False, True, "LICENSE_INACTIVE")

    # ── AUTO-BIND: key chưa bind → bind ngay, không trả NOT_BOUND ──
    if not lic.bound_mt5_id:
        if account:
            lic.bound_mt5_id = account
            lic.status       = "ACTIVE"
            db.commit()
            cache.owner_set(account, lic.buyer_email or "")  # R-04
            logger.info(f"[HB] AUTO_BOUND | key={key[:12]} account={account}")
        else:
            return _resp(False, False, "KEY_NOT_BOUND",
                         "Vào dashboard bind MT5 ID trước khi chạy EA.")

    # ── MT5 ID mismatch ──────────────────────────────────────────
    elif account and account != lic.bound_mt5_id:
        logger.warning(f"[HB] MT5_MISMATCH | key={key[:12]} bound={lic.bound_mt5_id} got={account}")
        return _resp(False, True, "MT5_ID_MISMATCH",
                     f"Key này đã bind vào MT5 ID {lic.bound_mt5_id}. Liên hệ admin.")

    # ── Machine limit → Redis set ─────────────────────────────────
    max_m = getattr(lic, "max_machines", 1) or 1
    known = cache.machine_get(key)  # R-04: Redis

    if account and account not in known:
        count = cache.machine_count(key)
        if count >= max_m:
            logger.warning(f"[HB] MACHINE_LIMIT | key={key[:12]} account={account} limit={max_m}")
            return _resp(False, True, "MACHINE_LIMIT_REACHED",
                         f"Tối đa {max_m} máy. Liên hệ admin để reset.")
        _register_machine(db, key, account, magic)

    logger.info(f"[HB] OK | key={key[:12]} account={account} equity={equity:.2f}")
    return {
        "valid":      True,
        "lock":       False,
        "emergency":  False,
        "reason":     "OK",
        "status":     lic.status,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else "lifetime",
        "bound_to":   lic.bound_mt5_id,
    }


# ══════════════════════════════════════════════════════════════════
# SECTION 2 — BIND LICENSE (từ dashboard)
# ══════════════════════════════════════════════════════════════════

def bind_license(db: Session, key: str, account_id: str) -> dict:
    """
    R-05: Gọi atomic_bind_license → không còn race condition.
    Cập nhật owner cache Redis sau khi bind thành công.
    """
    if not key or not account_id:
        return {"status": "error", "message": "Thiếu license_key hoặc account_id"}

    result = atomic_bind_license(db, key, account_id)

    if result["status"] == "success":
        # Warm owner cache
        lic = db.query(License).filter(License.license_key == key).first()
        if lic and lic.buyer_email:
            cache.owner_set(account_id, lic.buyer_email)  # R-04
        logger.info(f"[BIND] OK | key={key[:12]} account={account_id} reason={result['reason']}")
    else:
        logger.warning(f"[BIND] FAIL | key={key[:12]} account={account_id} reason={result.get('reason')}")

    return result


def verify_license(db: Session, account_id: str) -> dict:
    """Kiểm tra license cho account. Dùng cho /api/verify-license."""
    lic = db.query(License).filter(
        License.bound_mt5_id == account_id,
        License.status       == "ACTIVE",
    ).first()

    if not lic:
        return {"is_valid": False, "reason": "NO_ACTIVE_LICENSE"}

    if _is_expired(lic):
        lic.status = "EXPIRED"
        db.commit()
        return {"is_valid": False, "reason": "LICENSE_EXPIRED"}

    return {
        "is_valid":   True,
        "reason":     "OK",
        "tier":       lic.tier,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else "lifetime",
    }


# ══════════════════════════════════════════════════════════════════
# SECTION 3 — FLEET ISOLATION
# ══════════════════════════════════════════════════════════════════

def get_accounts_for_owner(db: Session, buyer_email: str) -> list[str]:
    if not buyer_email:
        return []
    rows = db.query(License.bound_mt5_id).filter(
        License.buyer_email  == buyer_email,
        License.status       == "ACTIVE",
        License.bound_mt5_id.isnot(None),
    ).all()
    return [r.bound_mt5_id for r in rows]


def get_owner_for_account(db: Session, account_id: str) -> Optional[str]:
    """R-04: Đọc từ Redis cache trước, fallback về DB."""
    cached = cache.owner_get(account_id)  # R-04
    if cached is not None:
        return cached or None

    lic = db.query(License).filter(
        License.bound_mt5_id == account_id,
        License.status       == "ACTIVE",
    ).first()

    if lic:
        cache.owner_set(account_id, lic.buyer_email or "")  # R-04
        return lic.buyer_email
    return None


def filter_units_for_owner(all_units: dict, db: Session, buyer_email: str) -> dict:
    if not buyer_email:
        return {}
    allowed = set(get_accounts_for_owner(db, buyer_email))
    return {
        acc_id: cfg
        for acc_id, cfg in all_units.items()
        if str(acc_id) in allowed
    }


# ══════════════════════════════════════════════════════════════════
# SECTION 4 — ADMIN HELPERS
# ══════════════════════════════════════════════════════════════════

def admin_reset_binding(db: Session, key: str) -> dict:
    """Reset binding + xóa cache Redis."""
    lic = db.query(License).filter(License.license_key == key).first()
    if not lic:
        return {"status": "error", "message": "Key không tồn tại"}

    old_account    = lic.bound_mt5_id
    lic.bound_mt5_id = None
    lic.status       = "UNUSED"

    db.query(LicenseActivation).filter(
        LicenseActivation.license_key == key
    ).delete()
    db.commit()

    # R-04: Xóa Redis cache
    cache.machine_remove_all(key)
    if old_account:
        cache.owner_del(old_account)

    logger.info(f"[ADMIN] RESET_BINDING | key={key[:12]} was_bound={old_account}")
    return {
        "status":     "ok",
        "message":    "Đã reset binding. Key có thể bind lại.",
        "was_bound":  old_account,
    }


def admin_get_license_stats(db: Session) -> dict:
    """R-04: online_now lấy từ Redis (chính xác qua restart)."""
    total   = db.query(License).count()
    active  = db.query(License).filter(License.status == "ACTIVE").count()
    unused  = db.query(License).filter(License.status == "UNUSED").count()
    revoked = db.query(License).filter(License.status == "REVOKED").count()
    expired = db.query(License).filter(License.status == "EXPIRED").count()

    return {
        "total":      total,
        "active":     active,
        "unused":     unused,
        "revoked":    revoked,
        "expired":    expired,
        "online_now": cache.online_count(),  # R-04: Redis
    }


# ══════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════

def _resp(valid: bool, lock: bool, reason: str, message: str = "") -> dict:
    r = {"valid": valid, "lock": lock, "emergency": False, "reason": reason}
    if message:
        r["message"] = message
    return r


def _is_expired(lic: License) -> bool:
    return bool(lic.expires_at and lic.expires_at < datetime.now(timezone.utc))


def _get_machines(db: Session, key: str) -> set:
    """R-04: Redis cache + DB fallback."""
    known = cache.machine_get(key)
    if known:
        return known
    rows  = db.query(LicenseActivation).filter(LicenseActivation.license_key == key).all()
    accts = {r.account_id for r in rows}
    for a in accts:
        cache.machine_add(key, a)
    return accts


def _register_machine(db: Session, key: str, account_id: str, magic: str = "") -> None:
    """Ghi machine vào DB + Redis."""
    try:
        existing = db.query(LicenseActivation).filter(
            LicenseActivation.license_key == key,
            LicenseActivation.account_id  == account_id,
        ).first()
        if existing:
            existing.last_seen = datetime.now(timezone.utc)
        else:
            db.add(LicenseActivation(license_key=key, account_id=account_id, magic=magic))
        db.commit()
        cache.machine_add(key, account_id)  # R-04
    except Exception as e:
        db.rollback()
        logger.error(f"[MACHINE_REG] Error: {e}")


# ── R-03 Fleet Isolation Helpers ─────────────────────────────────────────────

def get_owner_for_license(db, license_key: str):
    """Trả về buyer_email của license key. None nếu key không tồn tại/không hợp lệ."""
    from database import License
    lic = db.query(License).filter(
        License.license_key == license_key,
        License.status != "REVOKED"
    ).first()
    if not lic:
        return None
    return getattr(lic, "buyer_email", None)


def get_accounts_for_owner(db, owner_email: str):
    """
    Trả về set account_ids mà owner_email có quyền xem.
    Dựa vào license_activations — mỗi activation có account_id.
    """
    if not owner_email:
        return None  # None = không filter (admin mode)
    try:
        from database import License, LicenseActivation
        # Lấy tất cả license của owner
        licenses = db.query(License).filter(
            License.buyer_email == owner_email,
            License.status != "REVOKED"
        ).all()
        if not licenses:
            return set()
        keys = {lic.license_key for lic in licenses}
        # Lấy tất cả account_ids đã activate với các keys này
        activations = db.query(LicenseActivation).filter(
            LicenseActivation.license_key.in_(keys)
        ).all()
        account_ids = {a.account_id for a in activations if a.account_id}
        # Cũng thêm bound_mt5_id nếu có
        for lic in licenses:
            if getattr(lic, "bound_mt5_id", None):
                account_ids.add(lic.bound_mt5_id)
        return account_ids
    except Exception as e:
        import logging
        logging.getLogger("zarmor.license").warning(f"get_accounts_for_owner error: {e}")
        return None  # None = không filter khi có lỗi
