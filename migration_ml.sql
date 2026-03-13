-- migration_ml.sql — Phase 3 ML Tables
-- Chạy sau migration_performance.sql
-- psql -U zarmor -d zarmor_db -f migration_ml.sql
-- ============================================================

-- 1. Labeled training dataset
CREATE TABLE IF NOT EXISTS labeled_scans (
    id               SERIAL PRIMARY KEY,
    scan_id          VARCHAR(20) UNIQUE NOT NULL,

    -- Input features (mirrors radar_scans breakdown)
    asset            VARCHAR(20) NOT NULL,
    timeframe        VARCHAR(5)  NOT NULL,
    utc_hour         SMALLINT,
    utc_dow          SMALLINT,

    -- Engine sub-scores
    trend_strength     FLOAT,
    volatility_quality FLOAT,
    session_bias       FLOAT,
    market_structure   FLOAT,

    -- Live OHLCV features (NULL khi fallback)
    adx_live         FLOAT,
    rsi_live         FLOAT,
    atr_pct_live     FLOAT,

    -- Composite
    score            INT,
    regime           VARCHAR(30),
    confidence       VARCHAR(10),

    -- Target label
    label            VARCHAR(30) NOT NULL,   -- PROFITABLE_TREND | FALSE_SIGNAL | RANGE_BOUND
    label_confidence FLOAT       NOT NULL,   -- 0.0–1.0
    trade_count      INT         DEFAULT 0,

    labeled_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_ls_asset_tf    ON labeled_scans (asset, timeframe);
CREATE INDEX IF NOT EXISTS ix_ls_label       ON labeled_scans (label, label_confidence DESC);
CREATE INDEX IF NOT EXISTS ix_ls_labeled_at  ON labeled_scans (labeled_at DESC);

-- 2. Model registry
CREATE TABLE IF NOT EXISTS model_registry (
    id                  SERIAL PRIMARY KEY,
    version             VARCHAR(30) UNIQUE NOT NULL,   -- e.g. "20260309_1030"
    model_path          TEXT        NOT NULL,           -- full path to .pkl file
    cv_accuracy         FLOAT,
    cv_std              FLOAT,
    n_samples           INT,
    label_counts        JSONB,
    feature_importance  JSONB,
    is_active           BOOLEAN     DEFAULT FALSE,
    trained_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_mr_active      ON model_registry (is_active, trained_at DESC);

-- 3. Feedback log (đã tạo trong scheduler.py Phase 2, đảm bảo tồn tại)
CREATE TABLE IF NOT EXISTS feedback_log (
    id               SERIAL PRIMARY KEY,
    account_id       VARCHAR(50) NOT NULL,
    period_days      INT         NOT NULL,
    sharpe           FLOAT,
    sortino          FLOAT,
    calmar           FLOAT,
    max_drawdown     FLOAT,
    win_rate         FLOAT,
    profit_factor    FLOAT,
    total_trades     INT,
    total_pnl        FLOAT,
    symbol_breakdown JSONB,
    logged_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_feedback_account ON feedback_log (account_id, logged_at DESC);

-- Verify
SELECT 'labeled_scans OK'    AS status;
SELECT 'model_registry OK'   AS status;
SELECT 'feedback_log OK'     AS status;
