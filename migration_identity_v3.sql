-- ================================================================
-- MIGRATION: Z-ARMOR IDENTITY PLATFORM v3.0
-- Sprint 1-6: Auth + Identity + Billing + Radar + Growth + GDPR
-- Run: psql -U zarmor -d zarmor_db -f migration_identity_v3.sql
-- Idempotent: safe to run nhiều lần
-- Date: 2026-03-10
-- ================================================================

BEGIN;

-- ================================================================
-- SPRINT 1: Sessions table (JWT revocation + refresh tokens)
-- ================================================================

CREATE TABLE IF NOT EXISTS za_sessions (
    id             SERIAL PRIMARY KEY,
    user_id        VARCHAR(100) NOT NULL,
    jti            VARCHAR(100) UNIQUE NOT NULL,
    refresh_token  VARCHAR(200) UNIQUE NOT NULL,
    device_hash    VARCHAR(100),
    ip             VARCHAR(50),
    expires_at     TIMESTAMPTZ NOT NULL,
    refresh_exp_at TIMESTAMPTZ NOT NULL,
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_revoked     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_za_sess_jti     ON za_sessions(jti);
CREATE INDEX IF NOT EXISTS idx_za_sess_user    ON za_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_za_sess_refresh ON za_sessions(refresh_token);

-- ================================================================
-- SPRINT 2: Users + Auth Providers + Security
-- ================================================================

CREATE TABLE IF NOT EXISTS za_users (
    id            VARCHAR(36) PRIMARY KEY,
    email         VARCHAR(200) UNIQUE NOT NULL,
    username      VARCHAR(100),
    password_hash VARCHAR(200),
    ref_code      VARCHAR(20) UNIQUE,
    referred_by   VARCHAR(20),
    tier          VARCHAR(20) DEFAULT 'TRIAL',
    status        VARCHAR(20) DEFAULT 'active',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_za_users_email    ON za_users(email);
CREATE INDEX IF NOT EXISTS idx_za_users_ref_code ON za_users(ref_code);
CREATE INDEX IF NOT EXISTS idx_za_users_status   ON za_users(status);

CREATE TABLE IF NOT EXISTS za_auth_providers (
    id           VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id      VARCHAR(36) NOT NULL REFERENCES za_users(id) ON DELETE CASCADE,
    provider     VARCHAR(20) NOT NULL,   -- 'license_key', 'email', 'telegram', 'google'
    provider_uid VARCHAR(200) NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(provider, provider_uid)
);
CREATE INDEX IF NOT EXISTS idx_za_ap_user     ON za_auth_providers(user_id);
CREATE INDEX IF NOT EXISTS idx_za_ap_provider ON za_auth_providers(provider, provider_uid);

CREATE TABLE IF NOT EXISTS za_user_security (
    user_id                VARCHAR(36) PRIMARY KEY REFERENCES za_users(id),
    failed_login_attempts  INTEGER DEFAULT 0,
    last_login_ip          VARCHAR(50),
    device_hash            VARCHAR(100),
    two_fa_enabled         BOOLEAN DEFAULT FALSE,
    two_fa_secret          VARCHAR(100)
);

-- ================================================================
-- SPRINT 2: Backfill za_users từ license_keys hiện có
-- ================================================================

INSERT INTO za_users (id, email, tier, status, ref_code, created_at)
SELECT
    SUBSTRING(MD5(buyer_email), 1, 36)           AS id,
    buyer_email                                  AS email,
    COALESCE(tier, 'TRIAL')                      AS tier,
    CASE WHEN status = 'ACTIVE' THEN 'active'
         WHEN status = 'TRIAL'  THEN 'active'
         ELSE 'inactive' END                     AS status,
    UPPER(SUBSTRING(MD5(buyer_email), 1, 8))     AS ref_code,
    MIN(created_at)                              AS created_at
FROM license_keys
WHERE buyer_email IS NOT NULL
  AND buyer_email != ''
GROUP BY buyer_email, tier, status
ON CONFLICT (email) DO NOTHING;

-- Backfill auth_providers: link license_key → za_users
INSERT INTO za_auth_providers (id, user_id, provider, provider_uid)
SELECT
    gen_random_uuid()::text                     AS id,
    SUBSTRING(MD5(lk.buyer_email), 1, 36)       AS user_id,
    'license_key'                               AS provider,
    lk.license_key                              AS provider_uid
FROM license_keys lk
WHERE lk.buyer_email IS NOT NULL
ON CONFLICT (provider, provider_uid) DO NOTHING;

-- Backfill security rows
INSERT INTO za_user_security (user_id)
SELECT id FROM za_users
ON CONFLICT (user_id) DO NOTHING;

-- ================================================================
-- SPRINT 3: Invoices / Billing
-- ================================================================

CREATE TABLE IF NOT EXISTS za_invoices (
    id             VARCHAR(36) PRIMARY KEY,
    invoice_number VARCHAR(30) UNIQUE NOT NULL,
    owner_email    VARCHAR(200) NOT NULL,
    license_key    VARCHAR(60),
    amount_usd     FLOAT DEFAULT 0,
    status         VARCHAR(20) DEFAULT 'PENDING',  -- PENDING, PAID, CANCELLED
    tier           VARCHAR(20),
    description    TEXT,
    period_start   TIMESTAMPTZ,
    period_end     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_za_inv_email  ON za_invoices(owner_email);
CREATE INDEX IF NOT EXISTS idx_za_inv_status ON za_invoices(status);

-- ================================================================
-- SPRINT 4: Radar với user_id attribution
-- ================================================================

-- Thêm user_id vào radar_scans nếu chưa có
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='radar_scans' AND column_name='user_id'
  ) THEN
    ALTER TABLE radar_scans ADD COLUMN user_id VARCHAR(100);
    CREATE INDEX idx_radar_scans_user ON radar_scans(user_id);
  END IF;
END $$;

-- Alert subscriptions (thay thế alert_subscribers cũ nếu cần)
CREATE TABLE IF NOT EXISTS alert_subscriptions (
    user_id    VARCHAR(100) NOT NULL,
    asset      VARCHAR(50)  NOT NULL,
    timeframe  VARCHAR(20)  NOT NULL,
    threshold  FLOAT        DEFAULT 70,
    channel    VARCHAR(20)  DEFAULT 'telegram',  -- telegram, email, both
    active     BOOLEAN      DEFAULT TRUE,
    created_at TIMESTAMPTZ  DEFAULT NOW(),
    PRIMARY KEY (user_id, asset, timeframe)
);
CREATE INDEX IF NOT EXISTS idx_alert_sub_asset ON alert_subscriptions(asset, timeframe, active);

-- ================================================================
-- SPRINT 5: Referral events (Growth Loop)
-- ================================================================

CREATE TABLE IF NOT EXISTS referral_events (
    id               VARCHAR(36) PRIMARY KEY,
    ref_code         VARCHAR(20) NOT NULL,
    referrer_user_id VARCHAR(100),
    asset            VARCHAR(50),
    ip               VARCHAR(50),
    converted        BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ref_events_code      ON referral_events(ref_code);
CREATE INDEX IF NOT EXISTS idx_ref_events_referrer  ON referral_events(referrer_user_id);
CREATE INDEX IF NOT EXISTS idx_ref_events_converted ON referral_events(converted);

-- ================================================================
-- SPRINT 6: Audit indexes + Compliance
-- ================================================================

CREATE INDEX IF NOT EXISTS idx_audit_user_date   ON audit_logs(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action_date ON audit_logs(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_email       ON audit_logs(email);

-- ================================================================
-- VERIFY
-- ================================================================

DO $$
DECLARE
    v_users       INT;
    v_sessions    INT;
    v_providers   INT;
    v_invoices    INT;
    v_alert_subs  INT;
    v_ref_events  INT;
BEGIN
    SELECT COUNT(*) INTO v_users     FROM za_users;
    SELECT COUNT(*) INTO v_sessions  FROM za_sessions;
    SELECT COUNT(*) INTO v_providers FROM za_auth_providers;
    SELECT COUNT(*) INTO v_invoices  FROM za_invoices;
    SELECT COUNT(*) INTO v_alert_subs FROM alert_subscriptions;
    SELECT COUNT(*) INTO v_ref_events FROM referral_events;

    RAISE NOTICE '================================================';
    RAISE NOTICE 'MIGRATION IDENTITY v3.0 — COMPLETED';
    RAISE NOTICE 'za_users:           % rows (backfilled from license_keys)', v_users;
    RAISE NOTICE 'za_sessions:        % rows', v_sessions;
    RAISE NOTICE 'za_auth_providers:  % rows (backfilled)', v_providers;
    RAISE NOTICE 'za_invoices:        % rows', v_invoices;
    RAISE NOTICE 'alert_subscriptions:% rows', v_alert_subs;
    RAISE NOTICE 'referral_events:    % rows', v_ref_events;
    RAISE NOTICE '================================================';
END $$;

COMMIT;
