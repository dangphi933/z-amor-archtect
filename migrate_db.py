# -*- coding: utf-8 -*-
"""
Z-Armor DB Migration Script
Chay: py migrate_db.py
Khong xoa bang cu, chi them cot/bang con thieu.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Z-Armor.db")

def column_exists(cur, table, column):
    cur.execute("PRAGMA table_info(%s)" % table)
    return any(row[1] == column for row in cur.fetchall())

def table_exists(cur, table):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

print("=== Z-Armor DB Migration V8.2 ===")
print("DB: %s" % DB_PATH)
print("")

# 1. Them cot moi vao risk_hard_limits
HARD_LIMIT_COLS = [
    ("max_daily_dd_pct", "REAL DEFAULT 5.0"),
    ("dd_mode",          "TEXT DEFAULT 'STATIC'"),
]
for col, col_def in HARD_LIMIT_COLS:
    if table_exists(cur, "risk_hard_limits"):
        if column_exists(cur, "risk_hard_limits", col):
            print("[OK]    risk_hard_limits.%s" % col)
        else:
            cur.execute("ALTER TABLE risk_hard_limits ADD COLUMN %s %s" % (col, col_def))
            print("[ADDED] risk_hard_limits.%s" % col)
    else:
        print("[SKIP]  Bang risk_hard_limits chua ton tai")

# 2. Tao bang risk_tactical
if not table_exists(cur, "risk_tactical"):
    cur.execute("""
        CREATE TABLE risk_tactical (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id        TEXT UNIQUE,
            daily_limit_money REAL DEFAULT 150.0,
            rollover_hour     INTEGER DEFAULT 0,
            broker_timezone   INTEGER DEFAULT 2,
            target_profit     REAL DEFAULT 0.0,
            target_timeframe  TEXT DEFAULT 'MONTH',
            profit_lock_pct   REAL DEFAULT 40.0
        )
    """)
    print("[ADDED] Bang risk_tactical")
else:
    print("[OK]    Bang risk_tactical")

# 3. Tao bang trade_history
if not table_exists(cur, "trade_history"):
    cur.execute("""
        CREATE TABLE trade_history (
            id              TEXT PRIMARY KEY,
            account_id      TEXT NOT NULL,
            session_id      TEXT,
            timestamp       INTEGER NOT NULL,
            closed_at       INTEGER,
            symbol          TEXT DEFAULT '',
            direction       TEXT DEFAULT 'BUY',
            result          TEXT DEFAULT 'PENDING',
            risk_amount     REAL DEFAULT 0.0,
            actual_rr       REAL DEFAULT 0.0,
            planned_rr      REAL DEFAULT 0.0,
            profit          REAL DEFAULT 0.0,
            hour_of_day     INTEGER DEFAULT 0,
            day_of_week     INTEGER DEFAULT 0,
            deviation_score REAL DEFAULT 0.0
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_trade_account_time ON trade_history (account_id, timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_trade_account_session ON trade_history (account_id, session_id)")
    print("[ADDED] Bang trade_history")
else:
    print("[OK]    Bang trade_history")

# 4. Tao bang session_history
if not table_exists(cur, "session_history"):
    cur.execute("""
        CREATE TABLE session_history (
            session_id          TEXT PRIMARY KEY,
            account_id          TEXT NOT NULL,
            date                TEXT NOT NULL,
            opened_at           INTEGER,
            closed_at           INTEGER,
            opening_balance     REAL DEFAULT 0.0,
            closing_balance     REAL DEFAULT 0.0,
            pnl                 REAL DEFAULT 0.0,
            actual_wr           REAL DEFAULT 0.0,
            actual_rr_avg       REAL DEFAULT 0.0,
            actual_max_dd_hit   REAL DEFAULT 0.0,
            trades_count        INTEGER DEFAULT 0,
            wins                INTEGER DEFAULT 0,
            losses              INTEGER DEFAULT 0,
            compliance_score    INTEGER DEFAULT 100,
            violations          TEXT DEFAULT '[]',
            contract_json       TEXT DEFAULT '{}',
            status              TEXT DEFAULT 'COMPLETED'
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_session_account_date ON session_history (account_id, date)")
    print("[ADDED] Bang session_history")
else:
    print("[OK]    Bang session_history")

# 5. Tao bang audit_logs
if not table_exists(cur, "audit_logs"):
    cur.execute("""
        CREATE TABLE audit_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id  TEXT NOT NULL,
            timestamp   INTEGER NOT NULL,
            date_str    TEXT NOT NULL,
            action      TEXT NOT NULL,
            message     TEXT DEFAULT '',
            severity    TEXT DEFAULT 'INFO',
            extra_json  TEXT DEFAULT '{}'
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_audit_account_time ON audit_logs (account_id, timestamp)")
    print("[ADDED] Bang audit_logs")
else:
    print("[OK]    Bang audit_logs")

# 6. Tao bang ea_sessions (MOI - V8.2)
if not table_exists(cur, "ea_sessions"):
    cur.execute("""
        CREATE TABLE ea_sessions (
            id                TEXT PRIMARY KEY,
            account_id        TEXT NOT NULL,
            license_key       TEXT NOT NULL,
            broker_server     TEXT DEFAULT '',
            device_hash       TEXT DEFAULT '',
            mt5_build         TEXT DEFAULT '',
            session_token     TEXT UNIQUE,
            token_expires_at  INTEGER,
            challenge         TEXT,
            challenge_expires INTEGER,
            status            TEXT DEFAULT 'ACTIVE',
            handshake_at      INTEGER,
            last_seen         INTEGER,
            heartbeat_count   INTEGER DEFAULT 0,
            suspicious_count  INTEGER DEFAULT 0,
            last_ip           TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_ea_session_account ON ea_sessions (account_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_ea_session_token   ON ea_sessions (session_token)")
    print("[ADDED] Bang ea_sessions (V8.2 - Handshake/Heartbeat Security)")
else:
    print("[OK]    Bang ea_sessions")

conn.commit()
conn.close()

print("")
print("=== Migration hoan tat! ===")
print("Chay: pm2 restart z-armor-core")
