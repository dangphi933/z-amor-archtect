-- ═══════════════════════════════════════════════════════════════
-- migration_sprint_a.sql — Z-ARMOR CLOUD
-- Sprint A: Email Identity Foundation
-- Chạy: psql -U zarmor -d zarmor_db -f migration_sprint_a.sql
-- Idempotent: an toàn để chạy nhiều lần
-- ═══════════════════════════════════════════════════════════════

-- ── 1. Bảng za_users ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS za_users (
    id         VARCHAR(64)  PRIMARY KEY,           -- sha256(email)[:36]
    email      VARCHAR(200) UNIQUE NOT NULL,
    tier       VARCHAR(32)  NOT NULL DEFAULT 'TRIAL',
    ref_code   VARCHAR(32),
    status     VARCHAR(20)  NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_za_users_email
    ON za_users(email);

-- ── 2. Bảng za_sessions ─────────────────────────────────────────
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

CREATE INDEX IF NOT EXISTS idx_za_sess_jti
    ON za_sessions(jti);
CREATE INDEX IF NOT EXISTS idx_za_sess_user
    ON za_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_za_sess_refresh
    ON za_sessions(refresh_token);

-- ── 3. Backfill za_users từ licenses hiện có ────────────────────
-- Tạo account cho tất cả buyer_email đã có trong hệ thống
-- sha256 được tính bằng md5 thay thế (PostgreSQL không có sha256 native trong basic install)
-- user_id = left(md5(email), 36) — đủ unique cho scale hiện tại

INSERT INTO za_users (id, email, tier, status, created_at, last_seen)
SELECT
    left(md5(buyer_email), 36)                    AS id,
    buyer_email                                   AS email,
    COALESCE(
        MAX(CASE
            WHEN tier = 'FLEET'   THEN 'FLEET'
            WHEN tier = 'ARSENAL' THEN 'ARSENAL'
            WHEN tier = 'ARMOR'   THEN 'ARMOR'
            WHEN tier = 'STARTER' THEN 'STARTER'
            ELSE 'TRIAL'
        END),
        'TRIAL'
    )                                             AS tier,
    'active'                                      AS status,
    MIN(created_at)                               AS created_at,
    NOW()                                         AS last_seen
FROM licenses
WHERE buyer_email IS NOT NULL
  AND buyer_email <> ''
  AND buyer_email <> 'no-email@zarmor.com'
GROUP BY buyer_email
ON CONFLICT (email) DO UPDATE
    SET last_seen = NOW();

-- Fallback nếu bảng tên là license_keys thay vì licenses
INSERT INTO za_users (id, email, tier, status, created_at, last_seen)
SELECT
    left(md5(buyer_email), 36)                    AS id,
    buyer_email                                   AS email,
    COALESCE(MAX(tier), 'TRIAL')                  AS tier,
    'active'                                      AS status,
    MIN(created_at)                               AS created_at,
    NOW()                                         AS last_seen
FROM license_keys
WHERE buyer_email IS NOT NULL
  AND buyer_email <> ''
  AND buyer_email <> 'no-email@zarmor.com'
GROUP BY buyer_email
ON CONFLICT (email) DO UPDATE
    SET last_seen = NOW();

-- ── 4. Index hỗ trợ fleet isolation query ───────────────────────
-- (buyer_email index trên licenses — nếu chưa có)
DO $$
BEGIN
    BEGIN
        CREATE INDEX idx_licenses_buyer_email ON licenses(buyer_email);
    EXCEPTION WHEN duplicate_table OR duplicate_object THEN
        NULL; -- đã có, bỏ qua
    END;
    BEGIN
        CREATE INDEX idx_license_keys_buyer_email ON license_keys(buyer_email);
    EXCEPTION WHEN duplicate_table OR duplicate_object THEN
        NULL;
    END;
END $$;

-- ── 5. Verify ────────────────────────────────────────────────────
DO $$
DECLARE
    user_count  INT;
    sess_count  INT;
BEGIN
    SELECT COUNT(*) INTO user_count FROM za_users;
    SELECT COUNT(*) INTO sess_count FROM za_sessions;
    RAISE NOTICE '✅ Sprint A migration complete: % users, % sessions',
        user_count, sess_count;
END $$;
