-- ================================================================
-- hotfix_radar_columns.sql — Z-ARMOR CLOUD
-- Thêm các cột mới vào bảng radar_scans (idempotent)
-- Chạy: psql -U zarmor -d zarmor_db -f hotfix_radar_columns.sql
-- ================================================================

-- Thêm từng cột, bọc trong DO block để không lỗi nếu đã tồn tại

DO $$ BEGIN
    ALTER TABLE radar_scans ADD COLUMN data_source    VARCHAR(20)  DEFAULT 'live';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE radar_scans ADD COLUMN allow_trade    BOOLEAN      DEFAULT TRUE;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE radar_scans ADD COLUMN position_pct   SMALLINT     DEFAULT 100;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE radar_scans ADD COLUMN sl_multiplier  FLOAT        DEFAULT 1.0;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE radar_scans ADD COLUMN state_cap      VARCHAR(30)  DEFAULT 'OPTIMAL';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- user_email (có thể thiếu ở một số server)
DO $$ BEGIN
    ALTER TABLE radar_scans ADD COLUMN user_email     VARCHAR(200);
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- user_id (Sprint A)
DO $$ BEGIN
    ALTER TABLE radar_scans ADD COLUMN user_id        VARCHAR(100);
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Index cho user_id nếu chưa có
CREATE INDEX IF NOT EXISTS idx_radar_scans_user    ON radar_scans(user_id);
CREATE INDEX IF NOT EXISTS idx_radar_scans_email2  ON radar_scans(user_email);

-- Verify
SELECT
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'radar_scans'
ORDER BY ordinal_position;
