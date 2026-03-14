"""baseline_v83_full_schema

Revision ID: 001_baseline
Revises: None
Create Date: 2026-03-13

Context: Gom toàn bộ schema hiện tại (từ storage_v83_full.sql) vào 1 migration baseline.
         Dùng để document schema. Trên production đã có schema này → chỉ chạy: alembic stamp head
         Trên fresh DB → alembic upgrade head sẽ tạo toàn bộ schema từ đầu.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── license_keys ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS license_keys (
            id              SERIAL PRIMARY KEY,
            license_key     TEXT UNIQUE NOT NULL,
            tier            VARCHAR(20) NOT NULL DEFAULT 'ARMOR',
            status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
            buyer_email     TEXT,
            buyer_name      TEXT,
            bound_mt5_id    TEXT,
            bound_at        TIMESTAMPTZ,
            expires_at      TIMESTAMPTZ,
            max_machines    INTEGER DEFAULT 1,
            strategy_id     TEXT DEFAULT 'S1',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes           TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_license_key ON license_keys (license_key)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_license_email ON license_keys (buyer_email)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_license_mt5 ON license_keys (bound_mt5_id)")

    # ─── trade_history (non-partitioned baseline) ─────────────────────────────
    # Partition được áp dụng trong migration 009
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id          BIGSERIAL PRIMARY KEY,
            account_id  TEXT NOT NULL,
            ticket      BIGINT NOT NULL,
            symbol      TEXT,
            direction   VARCHAR(10),
            lots        FLOAT,
            open_price  FLOAT,
            close_price FLOAT,
            profit      FLOAT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at   TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_th_account ON trade_history (account_id, created_at DESC)")

    # ─── sessions ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id              BIGSERIAL PRIMARY KEY,
            account_id      TEXT NOT NULL,
            session_type    TEXT,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at        TIMESTAMPTZ,
            total_pnl       FLOAT DEFAULT 0,
            trade_count     INTEGER DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions (account_id)")

    # ─── audit_log ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          BIGSERIAL PRIMARY KEY,
            account_id  TEXT,
            action      TEXT,
            detail      TEXT,
            ip_addr     TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ─── webhook_events ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            id          BIGSERIAL PRIMARY KEY,
            event_type  TEXT NOT NULL,
            payload     JSONB,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ─── ohlcv_cache ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv_cache (
            id          BIGSERIAL PRIMARY KEY,
            symbol      VARCHAR(20) NOT NULL,
            timeframe   VARCHAR(5)  NOT NULL,
            ts          TIMESTAMPTZ NOT NULL,
            open        FLOAT, high FLOAT, low FLOAT, close FLOAT, volume FLOAT,
            UNIQUE (symbol, timeframe, ts)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_sym_tf ON ohlcv_cache (symbol, timeframe, ts DESC)")

    # ─── radar_scans ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS radar_scans (
            id                  SERIAL PRIMARY KEY,
            scan_id             UUID NOT NULL,
            symbol              VARCHAR(20),
            timeframe           VARCHAR(5),
            score               INTEGER,
            regime              VARCHAR(30),
            transition_score    INTEGER,
            transition_type     VARCHAR(30),
            market_state        VARCHAR(30),
            adx                 FLOAT,
            atr                 FLOAT,
            volatility_ratio    FLOAT,
            ema_slope           FLOAT,
            range_compression   FLOAT,
            portfolio_regime    VARCHAR(30),
            scanned_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_radar_scan_id ON radar_scans (scan_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_radar_symbol_ts ON radar_scans (symbol, scanned_at DESC)")

    # ─── email_captures ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS email_captures (
            id          SERIAL PRIMARY KEY,
            email       TEXT UNIQUE NOT NULL,
            source      TEXT,
            captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    # Baseline downgrade — xóa toàn bộ schema (chỉ dùng trên fresh/test DB)
    for table in [
        "email_captures", "radar_scans", "ohlcv_cache",
        "webhook_events", "audit_log", "sessions",
        "trade_history", "license_keys",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
