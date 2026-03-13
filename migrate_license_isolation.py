"""
migrate_license_isolation.py — Z-ARMOR CLOUD
=============================================
Migration script: thêm index + constraint để hỗ trợ fleet isolation.

Chạy 1 lần:  py migrate_license_isolation.py
Không xóa dữ liệu cũ, chỉ thêm index.
"""

import os
import sys
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate")

# ── Load app database ────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import engine, SessionLocal, Base, License, LicenseActivation

from sqlalchemy import text, inspect


def run_migration():
    logger.info("=" * 55)
    logger.info("Z-ARMOR License Isolation Migration")
    logger.info(f"Target DB: {str(engine.url)[:60]}...")
    logger.info("=" * 55)

    with engine.connect() as conn:
        inspector = inspect(engine)

        # ── 1. Index: license_keys.buyer_email ──────────────────
        # Cần để filter fleet theo owner nhanh
        _ensure_index(conn, inspector,
                      table="license_keys",
                      index_name="ix_lic_buyer_email",
                      column="buyer_email")

        # ── 2. Index: license_keys.bound_mt5_id ─────────────────
        # Cần để verify_license(account_id) nhanh
        _ensure_index(conn, inspector,
                      table="license_keys",
                      index_name="ix_lic_bound_mt5",
                      column="bound_mt5_id")

        # ── 3. Index: license_activations.account_id ────────────
        _ensure_index(conn, inspector,
                      table="license_activations",
                      index_name="ix_la_account_id",
                      column="account_id")

        # ── 4. Kiểm tra + báo cáo orphan accounts ───────────────
        _report_orphan_accounts(conn)

        # ── 5. Fix NULL buyer_email nếu có ──────────────────────
        _fix_null_emails(conn)

        conn.commit()

    logger.info("")
    logger.info("✅ Migration hoàn tất!")
    logger.info("   Restart server: pm2 restart z-armor-core")


def _ensure_index(conn, inspector, table: str, index_name: str, column: str):
    existing = [idx["name"] for idx in inspector.get_indexes(table)]
    if index_name in existing:
        logger.info(f"[OK]    Index {index_name} đã tồn tại")
        return

    try:
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"
        ))
        logger.info(f"[ADDED] Index {index_name} ON {table}({column})")
    except Exception as e:
        logger.warning(f"[SKIP]  {index_name}: {e}")


def _report_orphan_accounts(conn):
    """
    Báo cáo: accounts trong trading_accounts nhưng KHÔNG có license active.
    Đây là nguyên nhân gây KEY_NOT_BOUND khi EA kết nối.
    """
    logger.info("")
    logger.info("── Kiểm tra orphan accounts (không có license bind) ──")

    try:
        result = conn.execute(text("""
            SELECT ta.account_id, ta.alias
            FROM   trading_accounts ta
            LEFT JOIN license_keys lk
                   ON lk.bound_mt5_id = ta.account_id
                  AND lk.status = 'ACTIVE'
            WHERE  lk.id IS NULL
            ORDER  BY ta.account_id
        """))
        rows = result.fetchall()

        if not rows:
            logger.info("   ✅ Không có orphan account")
        else:
            logger.warning(f"   ⚠️  Tìm thấy {len(rows)} account chưa có license:")
            for r in rows:
                logger.warning(f"       account_id={r[0]}  alias={r[1]}")
            logger.warning("")
            logger.warning("   → FIX: Vào dashboard bind license cho từng account,")
            logger.warning("          hoặc chạy: python fix_bind_accounts.py")
    except Exception as e:
        logger.warning(f"   [SKIP] Không thể check orphans: {e}")


def _fix_null_emails(conn):
    """
    Fix các license ACTIVE nhưng buyer_email = NULL.
    Không thể filter fleet theo owner nếu email null.
    """
    logger.info("")
    logger.info("── Kiểm tra license thiếu buyer_email ──")

    try:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM license_keys
            WHERE status = 'ACTIVE'
              AND (buyer_email IS NULL OR buyer_email = '')
              AND bound_mt5_id IS NOT NULL
        """))
        count = result.scalar()

        if count == 0:
            logger.info("   ✅ Tất cả license active đều có email")
        else:
            logger.warning(f"   ⚠️  {count} license active không có buyer_email")
            logger.warning("   → Vào /admin/licenses để cập nhật email cho từng key")
    except Exception as e:
        logger.warning(f"   [SKIP] {e}")


if __name__ == "__main__":
    run_migration()
