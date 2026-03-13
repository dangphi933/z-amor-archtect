-- migration_performance.sql
-- Phase 2: Performance Attribution Tables
-- Chạy 1 lần: psql -U zarmor -d zarmor_db -f migration_performance.sql
-- ============================================================

-- Bảng chứa performance snapshots đã tính
CREATE TABLE IF NOT EXISTS performance_snapshots (
    id              SERIAL PRIMARY KEY,
    account_id      VARCHAR(50)  NOT NULL,
    period_days     INT          NOT NULL DEFAULT 30,

    -- Core risk-adjusted metrics
    sharpe          FLOAT,       -- > 1.5 = good, > 2.0 = excellent
    sortino         FLOAT,       -- > 2.0 = good (punishes downside harder)
    calmar          FLOAT,       -- > 1.0 = acceptable, > 3.0 = excellent
    max_drawdown    FLOAT,       -- % từ peak, thấp hơn là tốt hơn
    annual_return   FLOAT,       -- Annualized return %

    -- Trade quality
    win_rate        FLOAT,       -- % trades profitable
    avg_rr          FLOAT,       -- Average R:R ratio
    profit_factor   FLOAT,       -- Gross win / Gross loss
    expectancy      FLOAT,       -- Dollar expectancy per trade

    -- Volume
    total_trades    INT,
    total_pnl       FLOAT,

    -- JSON data
    symbol_breakdown JSONB,      -- Per-symbol stats
    daily_returns    JSONB,      -- Array of daily return %
    grades           JSONB,      -- A-F grades per metric

    computed_at      TIMESTAMPTZ DEFAULT NOW(),

    -- Unique per account + period (upsert target)
    CONSTRAINT uq_perf_snapshot UNIQUE (account_id, period_days)
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_perf_account ON performance_snapshots (account_id);
CREATE INDEX IF NOT EXISTS ix_perf_computed ON performance_snapshots (computed_at DESC);

-- View tiện dụng cho dashboard query
CREATE OR REPLACE VIEW v_performance_summary AS
SELECT
    account_id,
    period_days,
    COALESCE(sharpe, 0)        AS sharpe,
    COALESCE(sortino, 0)       AS sortino,
    COALESCE(calmar, 0)        AS calmar,
    COALESCE(max_drawdown, 0)  AS max_drawdown,
    COALESCE(win_rate, 0)      AS win_rate,
    COALESCE(avg_rr, 0)        AS avg_rr,
    COALESCE(profit_factor, 0) AS profit_factor,
    COALESCE(total_trades, 0)  AS total_trades,
    COALESCE(total_pnl, 0)     AS total_pnl,
    grades,
    computed_at,
    -- Convenience flag: data lâu hơn 6h = stale
    CASE WHEN computed_at < NOW() - INTERVAL '6 hours' THEN TRUE ELSE FALSE END AS is_stale
FROM performance_snapshots;

-- Verify
SELECT 'performance_snapshots created OK' AS status;
SELECT 'v_performance_summary view created OK' AS status;
