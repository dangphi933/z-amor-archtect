"""
sync_keys.py — Tự động sync license keys từ PostgreSQL → SQLite
Chạy background mỗi 60 giây để đảm bảo EA luôn nhận được key mới.
Đặt file này tại: Z-ARMOR-CLOUD/sync_keys.py
"""

import time
import logging
import sqlite3
import os
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  SYNC  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("sync_keys")

# ── Config ────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB  = os.path.join(BASE_DIR, "Z-Armor.db")
SYNC_INTERVAL = 60  # giây

def get_pg_conn():
    """Kết nối PostgreSQL từ .env của zarmor-backend."""
    from dotenv import load_dotenv
    env_path = os.path.join(BASE_DIR, "zarmor-backend", ".env")
    load_dotenv(env_path)

    import psycopg2
    db_url = os.getenv("DATABASE_URL", "")
    # Strip driver prefix
    db_url = db_url.replace("postgresql+psycopg2://", "postgresql://")
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(db_url)

def get_sqlite_conn():
    return sqlite3.connect(SQLITE_DB)

def get_sqlite_schema(sqlite_conn):
    """Lấy tên bảng và cột license trong SQLite."""
    cur = sqlite_conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cur.fetchall()]
        if "license_key" in cols:
            return t, cols
    return None, []

def sync_once():
    """Sync một lần: PostgreSQL → SQLite."""
    try:
        pg  = get_pg_conn()
        sql = get_sqlite_conn()
    except Exception as e:
        log.error(f"Loi ket noi DB: {e}")
        return

    try:
        table, sqlite_cols = get_sqlite_schema(sql)
        if not table:
            log.error("Khong tim thay bang license trong SQLite!")
            return

        # Lay tat ca keys tu PostgreSQL
        pg_cur = pg.cursor()
        pg_cur.execute("""
            SELECT license_key, status, tier, buyer_name, buyer_email,
                   is_trial, activated_at, expires_at, created_at, bound_mt5_id
            FROM license_keys
            WHERE status IN ('ACTIVE', 'UNUSED', 'PENDING')
        """)
        pg_keys = pg_cur.fetchall()

        if not pg_keys:
            log.info("Khong co key nao can sync.")
            return

        # Sync tung key vao SQLite
        sql_cur = sql.cursor()
        synced = 0
        for row in pg_keys:
            key, status, tier, name, email, is_trial, activated_at, expires_at, created_at, mt5_id = row

            # Kiem tra da ton tai chua
            sql_cur.execute(f"SELECT license_key FROM {table} WHERE license_key=?", (key,))
            exists = sql_cur.fetchone()

            if exists:
                # Update status neu thay doi
                sql_cur.execute(
                    f"UPDATE {table} SET status=?, expires_at=? WHERE license_key=?",
                    (status, expires_at.isoformat() if expires_at else None, key)
                )
            else:
                # Insert moi
                try:
                    sql_cur.execute(f"""
                        INSERT INTO {table}
                            (license_key, status, tier, buyer_name, buyer_email,
                             is_trial, activated_at, expires_at, created_at, bound_mt5_id)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                    """, (
                        key, status, tier or "STARTER_TRIAL",
                        name or "", email or "",
                        1 if is_trial else 0,
                        activated_at.isoformat() if activated_at else None,
                        expires_at.isoformat() if expires_at else None,
                        created_at.isoformat() if created_at else datetime.utcnow().isoformat(),
                        mt5_id or ""
                    ))
                    synced += 1
                    log.info(f"SYNCED: {key[:20]}... ({tier})")
                except Exception as e:
                    log.warning(f"Insert error {key[:15]}: {e}")

        sql.commit()
        if synced > 0:
            log.info(f"Sync xong: {synced} key moi duoc them vao SQLite.")
        else:
            log.debug(f"Tat ca {len(pg_keys)} keys da co trong SQLite.")

    except Exception as e:
        log.error(f"Loi trong qua trinh sync: {e}")
        import traceback; traceback.print_exc()
    finally:
        pg.close()
        sql.close()

def main():
    log.info("=" * 50)
    log.info("Z-ARMOR KEY SYNC SERVICE STARTED")
    log.info(f"SQLite: {SQLITE_DB}")
    log.info(f"Interval: {SYNC_INTERVAL}s")
    log.info("=" * 50)

    if not os.path.exists(SQLITE_DB):
        log.error(f"Khong tim thay SQLite DB: {SQLITE_DB}")
        log.error("Kiem tra lai duong dan!")
        return

    while True:
        try:
            sync_once()
        except KeyboardInterrupt:
            log.info("Dung sync service.")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")
        time.sleep(SYNC_INTERVAL)

if __name__ == "__main__":
    main()
