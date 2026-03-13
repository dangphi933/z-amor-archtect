-- ================================================================
-- Z-ARMOR CLOUD — Radar Scan Migration
-- Run in psql: \c zarmor_db  then paste this file
-- ================================================================

CREATE TABLE IF NOT EXISTS radar_scans (
    id            SERIAL PRIMARY KEY,
    scan_id       VARCHAR(20)  UNIQUE NOT NULL,

    -- Input
    asset         VARCHAR(20)  NOT NULL,
    timeframe     VARCHAR(5)   NOT NULL,
    session       VARCHAR(30),
    utc_hour      SMALLINT,
    utc_dow       SMALLINT,       -- 0=Mon … 6=Sun

    -- Output
    score         FLOAT        NOT NULL,
    regime        VARCHAR(30)  NOT NULL,
    label         VARCHAR(20),
    confidence    VARCHAR(10),
    risk_level    VARCHAR(10),
    breakdown     JSONB,
    risk_notes    JSONB,
    strategy_hint TEXT,

    -- User
    email         VARCHAR(200),

    -- Engagement (growth loop tracking)
    report_sent   BOOLEAN DEFAULT FALSE,
    result_viewed BOOLEAN DEFAULT FALSE,
    cta_clicked   BOOLEAN DEFAULT FALSE,
    converted     BOOLEAN DEFAULT FALSE,

    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_radar_asset_tf_ts  ON radar_scans (asset, timeframe, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_radar_email_ts     ON radar_scans (email, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_radar_score_regime ON radar_scans (score, regime);
CREATE INDEX IF NOT EXISTS ix_radar_converted    ON radar_scans (converted, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_radar_session      ON radar_scans (session, created_at DESC);

ALTER TABLE radar_scans OWNER TO zarmor;

-- Verify
SELECT 'radar_scans created OK' as status, COUNT(*) as rows FROM radar_scans;
