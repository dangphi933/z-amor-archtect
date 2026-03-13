-- =============================================================================
-- Z-ARMOR V8.3 — FULL STORAGE MIGRATION
-- Chạy 1 lần trên PostgreSQL instance tại 47.129.243.206
-- Safe to re-run: tất cả đều dùng IF NOT EXISTS / ON CONFLICT DO NOTHING
-- =============================================================================
-- Order: Extensions → Core tables → ML tables → Indexes → Constraints → Cleanup
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid() cho scan_id


-- ===========================================================================
-- SECTION A: RADAR SCANS — thêm columns còn thiếu + EA fields
-- ===========================================================================

-- Bảng radar_scans được CREATE bởi router.py nhưng schema không đầy đủ
-- ALTER an toàn — chỉ thêm nếu chưa có
ALTER TABLE radar_scans
    ADD COLUMN IF NOT EXISTS created_at     TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS result_viewed  BOOLEAN     DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS cta_clicked    BOOLEAN     DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS converted      BOOLEAN     DEFAULT FALSE,
    -- Phase 4B: EA integration fields (engine.py compute nhưng chưa persist)
    ADD COLUMN IF NOT EXISTS allow_trade    BOOLEAN,
    ADD COLUMN IF NOT EXISTS position_pct   INTEGER,
    ADD COLUMN IF NOT EXISTS sl_multiplier  NUMERIC(4,2),
    ADD COLUMN IF NOT EXISTS state_cap      TEXT,
    -- ML join support
    ADD COLUMN IF NOT EXISTS risk_level     TEXT,
    ADD COLUMN IF NOT EXISTS data_source    TEXT DEFAULT 'fallback';

-- Indexes cho radar_scans — critical cho history query + ML labeler JOIN
CREATE INDEX IF NOT EXISTS idx_radar_scans_email
    ON radar_scans(email)
    WHERE email IS NOT NULL AND email <> '';

CREATE INDEX IF NOT EXISTS idx_radar_scans_asset_tf
    ON radar_scans(asset, timeframe);

CREATE INDEX IF NOT EXISTS idx_radar_scans_created_at
    ON radar_scans(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_radar_scans_score
    ON radar_scans(score);

-- Index cho ML labeler JOIN: tìm scan trong ±2h của trade
CREATE INDEX IF NOT EXISTS idx_radar_scans_asset_created
    ON radar_scans(asset, created_at);


-- ===========================================================================
-- SECTION B: MACHINE BINDINGS — thay thế _machine_registry in-memory
-- ===========================================================================
-- Hiện tại: main.py dùng dict thuần, mất sau restart
-- Fix: LicenseActivation đã có trong database.py → chỉ cần đảm bảo index

-- Bảng machine_bindings (nếu chưa dùng LicenseActivation)
CREATE TABLE IF NOT EXISTS machine_bindings (
    id          SERIAL PRIMARY KEY,
    license_key TEXT        NOT NULL,
    account_id  TEXT        NOT NULL,
    magic       TEXT        DEFAULT '',
    broker      TEXT        DEFAULT '',
    first_seen  TIMESTAMPTZ DEFAULT NOW(),
    last_seen   TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_machine_binding UNIQUE (license_key, account_id)
);

CREATE INDEX IF NOT EXISTS idx_machine_bindings_license
    ON machine_bindings(license_key);

CREATE INDEX IF NOT EXISTS idx_machine_bindings_account
    ON machine_bindings(account_id);

-- Đảm bảo LicenseActivation (nếu đã tồn tại) có đủ index
CREATE INDEX IF NOT EXISTS idx_license_activation_key
    ON license_activations(license_key)
    WHERE EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'license_activations'
    );


-- ===========================================================================
-- SECTION C: EA SESSIONS — index + cleanup policy
-- ===========================================================================

-- Index cho session_token lookup (mỗi heartbeat POST /ea/heartbeat)
CREATE INDEX IF NOT EXISTS idx_ea_sessions_token
    ON ea_sessions(session_token)
    WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_ea_sessions_account_status
    ON ea_sessions(account_id, status);

CREATE INDEX IF NOT EXISTS idx_ea_sessions_last_seen
    ON ea_sessions(last_seen DESC);

-- Cleanup: xóa sessions cũ > 7 ngày (sẽ được chạy lại bởi cron)
DELETE FROM ea_sessions
WHERE status IN ('EXPIRED', 'REVOKED')
  AND last_seen < NOW() - INTERVAL '7 days';


-- ===========================================================================
-- SECTION D: TRADE HISTORY — index cho ML labeler JOIN
-- ===========================================================================

CREATE INDEX IF NOT EXISTS idx_trade_history_account
    ON trade_history(account_id);

CREATE INDEX IF NOT EXISTS idx_trade_history_symbol_opened
    ON trade_history(symbol, opened_at);

CREATE INDEX IF NOT EXISTS idx_trade_history_opened_at
    ON trade_history(opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_history_pnl
    ON trade_history(pnl)
    WHERE pnl IS NOT NULL;


-- ===========================================================================
-- SECTION E: ML PIPELINE — labeled_scans + model_registry
-- ===========================================================================

-- E1: labeled_scans — output của ml/labeler.py (JOIN radar_scans + trade_history)
CREATE TABLE IF NOT EXISTS labeled_scans (
    id              SERIAL PRIMARY KEY,
    scan_id         TEXT        NOT NULL,
    trade_id        INTEGER,                    -- FK → trade_history.id
    asset           TEXT        NOT NULL,
    timeframe       TEXT        NOT NULL,
    -- Features (copy từ radar_scans tại thời điểm label)
    score           INTEGER,
    regime          TEXT,
    trend_strength  NUMERIC(5,1),
    vol_quality     NUMERIC(5,1),
    session_bias    NUMERIC(5,1),
    mkt_structure   NUMERIC(5,1),
    adx_live        NUMERIC(5,1),
    rsi_live        NUMERIC(5,1),
    atr_pct_live    NUMERIC(7,4),
    utc_hour        INTEGER,
    utc_dow         INTEGER,
    -- Label (output của labeler)
    label           TEXT        NOT NULL,       -- PROFITABLE_TREND | FALSE_SIGNAL | RANGE_BOUND
    label_confidence NUMERIC(5,4),             -- 0.0-1.0
    trade_pnl       NUMERIC(12,2),
    trade_rr        NUMERIC(5,2),
    -- Metadata
    labeled_at      TIMESTAMPTZ DEFAULT NOW(),
    label_method    TEXT        DEFAULT 'auto', -- auto | manual
    CONSTRAINT uq_labeled_scan UNIQUE (scan_id, trade_id)
);

CREATE INDEX IF NOT EXISTS idx_labeled_scans_asset_tf
    ON labeled_scans(asset, timeframe);

CREATE INDEX IF NOT EXISTS idx_labeled_scans_label
    ON labeled_scans(label);

CREATE INDEX IF NOT EXISTS idx_labeled_scans_labeled_at
    ON labeled_scans(labeled_at DESC);

-- E2: model_registry — version control cho ML model
CREATE TABLE IF NOT EXISTS model_registry (
    id              SERIAL PRIMARY KEY,
    version         TEXT        NOT NULL UNIQUE,   -- e.g. "v20260309_001"
    trained_at      TIMESTAMPTZ DEFAULT NOW(),
    -- Performance metrics
    cv_accuracy     NUMERIC(6,4),                  -- cross-validation accuracy
    cv_f1           NUMERIC(6,4),
    sample_count    INTEGER,
    -- Deployment
    is_active       BOOLEAN     DEFAULT FALSE,
    model_path      TEXT,                          -- đường dẫn file .pkl trên server
    model_size_kb   INTEGER,
    -- Context
    assets_trained  TEXT[],                        -- GOLD, EURUSD, BTC, NASDAQ
    notes           TEXT,
    activated_at    TIMESTAMPTZ,
    deactivated_at  TIMESTAMPTZ
);

-- Đảm bảo chỉ 1 model active tại 1 thời điểm
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_registry_active
    ON model_registry(is_active)
    WHERE is_active = TRUE;

-- E3: ml_training_runs — log từng lần retrain
CREATE TABLE IF NOT EXISTS ml_training_runs (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT        DEFAULT 'running', -- running | success | failed
    sample_count    INTEGER,
    cv_accuracy     NUMERIC(6,4),
    prev_accuracy   NUMERIC(6,4),
    accuracy_delta  NUMERIC(6,4),                  -- > 0.02 → auto-activate
    model_version   TEXT,
    error_message   TEXT
);


-- ===========================================================================
-- SECTION F: PERFORMANCE SNAPSHOTS
-- ===========================================================================

CREATE TABLE IF NOT EXISTS performance_snapshots (
    id              SERIAL PRIMARY KEY,
    account_id      TEXT        NOT NULL,
    snapshot_at     TIMESTAMPTZ DEFAULT NOW(),
    period          TEXT        DEFAULT '30d',      -- 7d | 30d | 90d | all
    -- Core metrics
    total_trades    INTEGER     DEFAULT 0,
    win_rate        NUMERIC(5,2),
    avg_rr          NUMERIC(5,2),
    total_pnl       NUMERIC(12,2),
    -- Risk-adjusted metrics
    sharpe_ratio    NUMERIC(6,3),
    sortino_ratio   NUMERIC(6,3),
    calmar_ratio    NUMERIC(6,3),
    max_drawdown    NUMERIC(5,2),
    -- Context
    regime_breakdown JSONB,                         -- {TRENDING: 40%, RANGE: 30%, ...}
    asset_breakdown  JSONB                          -- {GOLD: 50%, EURUSD: 30%, ...}
);

CREATE INDEX IF NOT EXISTS idx_perf_snapshots_account
    ON performance_snapshots(account_id, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS idx_perf_snapshots_at
    ON performance_snapshots(snapshot_at DESC);


-- ===========================================================================
-- SECTION G: CRM — alert_subscribers fix (UNIQUE + thêm columns)
-- ===========================================================================

-- Thêm columns còn thiếu cho alert scheduler (Luồng C)
ALTER TABLE radar_alert_subs
    ADD COLUMN IF NOT EXISTS threshold     INTEGER     DEFAULT 70,
    ADD COLUMN IF NOT EXISTS last_score    INTEGER,
    ADD COLUMN IF NOT EXISTS last_alert_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS alert_count   INTEGER     DEFAULT 0;

-- Dedup constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_alert_sub_dedup'
    ) THEN
        ALTER TABLE radar_alert_subs
            ADD CONSTRAINT uq_alert_sub_dedup
            UNIQUE (email, asset, timeframe, channel);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_alert_subs_active
    ON radar_alert_subs(active, asset, timeframe)
    WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_alert_subs_email
    ON radar_alert_subs(email);

-- radar_leads: thêm index + columns
ALTER TABLE radar_leads
    ADD COLUMN IF NOT EXISTS scan_count    INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_scan_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS converted_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ref_code      TEXT;

CREATE INDEX IF NOT EXISTS idx_radar_leads_email
    ON radar_leads(email);

CREATE INDEX IF NOT EXISTS idx_radar_leads_created
    ON radar_leads(created_at DESC);

-- radar_share_events: thêm ref tracking
ALTER TABLE radar_share_events
    ADD COLUMN IF NOT EXISTS ref_code      TEXT,
    ADD COLUMN IF NOT EXISTS ip_hash       TEXT,
    ADD COLUMN IF NOT EXISTS converted     BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_share_events_asset
    ON radar_share_events(asset, created_at DESC);


-- ===========================================================================
-- SECTION H: OHLCV CACHE — persistent fallback (khi ohlcv_service in-memory miss)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS ohlcv_cache (
    id          SERIAL PRIMARY KEY,
    asset       TEXT        NOT NULL,
    timeframe   TEXT        NOT NULL,
    -- Indicators
    adx         NUMERIC(6,2),
    rsi         NUMERIC(6,2),
    atr_pct     NUMERIC(8,5),
    ema_slope   NUMERIC(8,5),
    -- Metadata
    source      TEXT        DEFAULT 'twelvedata',
    fetched_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ,
    CONSTRAINT uq_ohlcv_cache UNIQUE (asset, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_cache_asset_tf
    ON ohlcv_cache(asset, timeframe);

CREATE INDEX IF NOT EXISTS idx_ohlcv_cache_expires
    ON ohlcv_cache(expires_at);

-- Upsert function cho ohlcv_service
CREATE OR REPLACE FUNCTION upsert_ohlcv_cache(
    p_asset TEXT, p_tf TEXT,
    p_adx NUMERIC, p_rsi NUMERIC, p_atr_pct NUMERIC, p_ema_slope NUMERIC,
    p_source TEXT, p_ttl_seconds INTEGER
) RETURNS VOID AS $$
BEGIN
    INSERT INTO ohlcv_cache (asset, timeframe, adx, rsi, atr_pct, ema_slope, source, fetched_at, expires_at)
    VALUES (p_asset, p_tf, p_adx, p_rsi, p_atr_pct, p_ema_slope, p_source, NOW(), NOW() + (p_ttl_seconds || ' seconds')::INTERVAL)
    ON CONFLICT (asset, timeframe) DO UPDATE SET
        adx        = EXCLUDED.adx,
        rsi        = EXCLUDED.rsi,
        atr_pct    = EXCLUDED.atr_pct,
        ema_slope  = EXCLUDED.ema_slope,
        source     = EXCLUDED.source,
        fetched_at = NOW(),
        expires_at = NOW() + (p_ttl_seconds || ' seconds')::INTERVAL;
END;
$$ LANGUAGE plpgsql;


-- ===========================================================================
-- SECTION I: AUDIT LOG
-- ===========================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    event_at    TIMESTAMPTZ DEFAULT NOW(),
    event_type  TEXT        NOT NULL,   -- LICENSE_CREATED | MACHINE_BOUND | RADAR_SCAN | etc.
    account_id  TEXT,
    license_key TEXT,
    ip          TEXT,
    payload     JSONB,
    severity    TEXT        DEFAULT 'INFO'  -- INFO | WARN | CRITICAL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_event_at
    ON audit_log(event_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_account
    ON audit_log(account_id, event_at DESC)
    WHERE account_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_log_type
    ON audit_log(event_type, event_at DESC);

-- Auto-partition cleanup: xóa audit log > 90 ngày (keep storage nhỏ)
CREATE OR REPLACE FUNCTION cleanup_old_audit_logs() RETURNS void AS $$
BEGIN
    DELETE FROM audit_log WHERE event_at < NOW() - INTERVAL '90 days';
END;
$$ LANGUAGE plpgsql;


-- ===========================================================================
-- SECTION J: BACKUP CRON SETUP (pg_cron extension nếu available)
-- ===========================================================================

-- Nếu pg_cron được cài đặt trên instance, uncomment để enable:
-- CREATE EXTENSION IF NOT EXISTS pg_cron;
--
-- -- Daily pg_dump backup lúc 2:00 AM UTC
-- SELECT cron.schedule('daily-backup', '0 2 * * *',
--     $$SELECT pg_notify('backup_trigger', 'daily')$$);
--
-- -- Weekly cleanup ea_sessions + audit_log
-- SELECT cron.schedule('weekly-cleanup', '0 3 * * 0', $$
--     DELETE FROM ea_sessions WHERE status IN ('EXPIRED','REVOKED') AND last_seen < NOW() - INTERVAL '7 days';
--     PERFORM cleanup_old_audit_logs();
-- $$);


COMMIT;

-- =============================================================================
-- POST-MIGRATION VERIFICATION
-- =============================================================================
DO $$
DECLARE
    tbl TEXT;
    cnt INTEGER;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'labeled_scans', 'model_registry', 'ml_training_runs',
        'performance_snapshots', 'machine_bindings',
        'ohlcv_cache', 'audit_log'
    ]
    LOOP
        SELECT COUNT(*) INTO cnt FROM information_schema.tables
        WHERE table_name = tbl AND table_schema = 'public';
        IF cnt > 0 THEN
            RAISE NOTICE 'OK: table % exists', tbl;
        ELSE
            RAISE WARNING 'MISSING: table % not created', tbl;
        END IF;
    END LOOP;
END $$;
