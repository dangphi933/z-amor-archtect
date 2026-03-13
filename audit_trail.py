"""
audit_trail.py — Z-ARMOR CLOUD
================================
4.3: Audit trail đầy đủ cho config thay đổi.
Mọi thay đổi risk_params, neural_profile, telegram_config của trader
đều được ghi: ai thay đổi, field nào, giá trị cũ → mới, lúc nào, IP nào.

Tích hợp vào main.py /api/update-unit-config:
    from audit_trail import record_config_change
    record_config_change(db, account_id, changed_by, old_data, new_data, ip)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from database import ConfigAuditTrail

logger = logging.getLogger("zarmor.audit")

# ══════════════════════════════════════════════════════════════════
# DEEP DIFF — so sánh old vs new config dict
# ══════════════════════════════════════════════════════════════════
def _deep_diff(old: dict, new: dict, prefix: str = "") -> list[dict]:
    """
    Trả về list các field đã thay đổi.
    Ví dụ: [{"path": "risk_params.max_dd", "old": "10.0", "new": "15.0"}]
    """
    changes = []
    all_keys = set(list(old.keys()) + list(new.keys()))

    for key in all_keys:
        path    = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        old_val = old.get(key)
        new_val = new.get(key)

        if old_val == new_val:
            continue

        # Nếu cả hai đều là dict → đệ quy
        if isinstance(old_val, dict) and isinstance(new_val, dict):
            changes.extend(_deep_diff(old_val, new_val, path))
        else:
            changes.append({
                "path": path,
                "old":  json.dumps(old_val,  ensure_ascii=False, default=str) if old_val is not None else None,
                "new":  json.dumps(new_val,  ensure_ascii=False, default=str) if new_val is not None else None,
            })

    return changes


# ══════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════
def record_config_change(
    db:          Session,
    account_id:  str,
    changed_by:  str,            # email của người thay đổi (từ JWT user.email)
    old_config:  dict,
    new_config:  dict,
    ip_address:  Optional[str] = None,
) -> int:
    """
    So sánh old_config và new_config, ghi từng field thay đổi vào config_audit_trail.
    Trả về số record đã ghi.

    Ví dụ gọi trong /api/update-unit-config:
        existing = get_all_units().get(account_id, {})
        update_unit_from_payload(account_id, data)
        updated  = get_all_units().get(account_id, {})
        record_config_change(db, account_id, user.email, existing, updated, client_ip)
    """
    diffs = _deep_diff(old_config, new_config)
    if not diffs:
        return 0

    now = datetime.now(timezone.utc)
    for diff in diffs:
        trail = ConfigAuditTrail(
            account_id = account_id,
            changed_by = changed_by,
            field_path = diff["path"],
            old_value  = diff["old"],
            new_value  = diff["new"],
            ip_address = ip_address,
            created_at = now,
        )
        db.add(trail)

    try:
        db.commit()
        logger.info(f"[AUDIT] {len(diffs)} changes | account={account_id} by={changed_by}")
    except Exception as e:
        db.rollback()
        logger.error(f"[AUDIT] commit fail: {e}")
        return 0

    return len(diffs)


def get_audit_history(
    db:         Session,
    account_id: str,
    limit:      int = 100,
    field_path: Optional[str] = None,
) -> list[dict]:
    """
    Lấy lịch sử thay đổi config của account.
    FE dùng để hiển thị timeline audit.
    """
    q = db.query(ConfigAuditTrail).filter(
        ConfigAuditTrail.account_id == account_id
    )
    if field_path:
        q = q.filter(ConfigAuditTrail.field_path.like(f"{field_path}%"))

    rows = q.order_by(ConfigAuditTrail.created_at.desc()).limit(limit).all()

    return [{
        "id":         r.id,
        "field":      r.field_path,
        "old_value":  r.old_value,
        "new_value":  r.new_value,
        "changed_by": r.changed_by,
        "ip":         r.ip_address,
        "at":         r.created_at.isoformat(),
    } for r in rows]
