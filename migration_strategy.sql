-- ================================================================
-- MIGRATION: strategy_selection
-- Table thực tế: license_keys (không phải licenses)
-- License key column: license_key
-- Idempotent — safe to run nhiều lần
-- Run: psql -U zarmor -d zarmor_db -f migration_strategy.sql
-- ================================================================

BEGIN;

-- ── 1. Thêm strategy_id vào license_keys ─────────────────────────────────────
ALTER TABLE license_keys
    ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10) DEFAULT 'S1';

-- ── 2. Log mỗi lần trader đổi chiến lược ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS strategy_selection_log (
    id              SERIAL PRIMARY KEY,
    license_key     VARCHAR(60)  NOT NULL,
    buyer_email     VARCHAR(200),
    old_strategy_id VARCHAR(10),
    new_strategy_id VARCHAR(10)  NOT NULL,
    changed_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    source          VARCHAR(30)  DEFAULT 'dashboard'
);

CREATE INDEX IF NOT EXISTS idx_ssl_license ON strategy_selection_log(license_key);
CREATE INDEX IF NOT EXISTS idx_ssl_changed ON strategy_selection_log(changed_at DESC);

COMMIT;
