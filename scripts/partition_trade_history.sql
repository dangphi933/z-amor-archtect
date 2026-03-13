-- partition_trade_history.sql — Z-ARMOR CLOUD
-- =============================================
-- 4.3 / R-12: Partition bảng trade_history theo tháng
-- Chạy khi tổng rows vượt 100,000
--
-- CÁCH CHẠY:
--   psql -U zarmor -d zarmor_db -f partition_trade_history.sql
--
-- KIỂM TRA TRƯỚC KHI CHẠY:
--   SELECT COUNT(*) FROM trade_history;
--   -- Chỉ chạy khi > 100,000 rows

-- ── BƯỚC 0: Kiểm tra row count ──────────────────────────────────
DO $$
DECLARE v_count bigint;
BEGIN
    SELECT COUNT(*) INTO v_count FROM trade_history;
    IF v_count < 100000 THEN
        RAISE NOTICE 'trade_history chỉ có % rows — chưa cần partition. Dừng.', v_count;
    ELSE
        RAISE NOTICE 'trade_history có % rows — tiến hành partition.', v_count;
    END IF;
END $$;

-- ── BƯỚC 1: Rename bảng cũ ──────────────────────────────────────
ALTER TABLE trade_history RENAME TO trade_history_legacy;

-- ── BƯỚC 2: Tạo bảng partitioned mới ───────────────────────────
CREATE TABLE trade_history (
    id           SERIAL,
    account_id   VARCHAR(50)  NOT NULL,
    session_id   VARCHAR(50),
    ticket       VARCHAR(50),
    symbol       VARCHAR(20),
    trade_type   VARCHAR(10),
    volume       FLOAT,
    open_price   FLOAT,
    close_price  FLOAT,
    pnl          FLOAT,
    rr_ratio     FLOAT,
    risk_amount  FLOAT,
    actual_rr    FLOAT,
    opened_at    TIMESTAMPTZ,
    closed_at    TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- ── BƯỚC 3: Tạo partitions theo tháng (2 năm gần nhất) ──────────
DO $$
DECLARE
    start_date DATE := DATE_TRUNC('month', NOW() - INTERVAL '12 months');
    end_date   DATE := DATE_TRUNC('month', NOW() + INTERVAL '3 months');
    cur_month  DATE;
    next_month DATE;
    part_name  TEXT;
BEGIN
    cur_month := start_date;
    WHILE cur_month < end_date LOOP
        next_month := cur_month + INTERVAL '1 month';
        part_name  := 'trade_history_' || TO_CHAR(cur_month, 'YYYY_MM');

        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF trade_history
             FOR VALUES FROM (%L) TO (%L)',
            part_name, cur_month, next_month
        );
        RAISE NOTICE 'Created partition %', part_name;
        cur_month := next_month;
    END LOOP;
END $$;

-- ── BƯỚC 4: Index trên mỗi partition ────────────────────────────
-- PostgreSQL tự động propagate index từ parent sang child partitions
CREATE INDEX ix_trade_account_created ON trade_history (account_id, created_at);
CREATE INDEX ix_trade_account_closed  ON trade_history (account_id, closed_at);

-- ── BƯỚC 5: Migrate data từ bảng cũ sang partitioned ────────────
-- Chạy trong batch để tránh lock toàn bảng
DO $$
DECLARE
    batch_size INT := 10000;
    offset_val INT := 0;
    rows_moved INT;
BEGIN
    LOOP
        INSERT INTO trade_history
        SELECT * FROM trade_history_legacy
        ORDER BY id
        LIMIT batch_size OFFSET offset_val
        ON CONFLICT DO NOTHING;

        GET DIAGNOSTICS rows_moved = ROW_COUNT;
        RAISE NOTICE 'Migrated batch: % rows (offset=%)', rows_moved, offset_val;
        EXIT WHEN rows_moved < batch_size;
        offset_val := offset_val + batch_size;
        PERFORM pg_sleep(0.1);  -- nhả CPU giữa các batch
    END LOOP;
    RAISE NOTICE 'Migration hoàn tất.';
END $$;

-- ── BƯỚC 6: Xác nhận ────────────────────────────────────────────
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE tablename LIKE 'trade_history%'
ORDER BY tablename;

-- ── BƯỚC 7: Sau khi xác nhận migration đúng → xóa bảng cũ ──────
-- CHỈ chạy sau khi đã verify row count khớp:
--   SELECT COUNT(*) FROM trade_history;         -- phải = trade_history_legacy
--   SELECT COUNT(*) FROM trade_history_legacy;
--
-- Sau đó:
--   DROP TABLE trade_history_legacy;

-- ── AUTO-CREATE PARTITION CHO THÁNG MỚI ─────────────────────────
-- Thêm vào crontab để tự động tạo partition đầu mỗi tháng:
--   0 0 1 * * psql -U zarmor -d zarmor_db -c "
--     CREATE TABLE IF NOT EXISTS trade_history_$(date +\%Y_\%m)
--     PARTITION OF trade_history
--     FOR VALUES FROM ('$(date +\%Y-\%m-01)') TO ('$(date -d 'next month' +\%Y-\%m-01)');"
