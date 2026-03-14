"""partition_trade_history

Revision ID: 009_partition_trade
Revises: 008_radar_hotfix
Create Date: 2026-03-13

Context: Từ scripts/partition_trade_history.sql
         Convert trade_history → partitioned table RANGE (created_at)
         Tạo partitions cho 2025-01 đến 2026-06 + auto-create mechanism

WARNING: Migration này rename bảng cũ → copy data → drop old.
         Chạy trong off-peak hours. Estimate 5-30 phút tùy data size.
         Kiểm tra sau: \d+ trade_history trong psql phải hiện "Partitioned table"
"""
from typing import Sequence, Union
from alembic import op

revision: str = "009_partition_trade"
down_revision: Union[str, None] = "008_radar_hotfix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_partition(year: int, month: int) -> str:
    """Tạo SQL CREATE TABLE partition cho 1 tháng."""
    from_date = f"{year}-{month:02d}-01"
    if month == 12:
        to_date = f"{year + 1}-01-01"
    else:
        to_date = f"{year}-{month + 1:02d}-01"
    name = f"trade_history_{year}_{month:02d}"
    return f"""
        CREATE TABLE IF NOT EXISTS {name}
        PARTITION OF trade_history
        FOR VALUES FROM ('{from_date}') TO ('{to_date}')
    """


def upgrade() -> None:
    # Bước 1: Backup bảng cũ
    op.execute("ALTER TABLE IF EXISTS trade_history RENAME TO trade_history_old")

    # Bước 2: Tạo bảng partitioned mới
    op.execute("""
        CREATE TABLE trade_history (
            id          BIGSERIAL,
            account_id  TEXT NOT NULL,
            ticket      BIGINT NOT NULL,
            symbol      TEXT,
            direction   VARCHAR(10),
            lots        FLOAT,
            open_price  FLOAT,
            close_price FLOAT,
            profit      FLOAT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at   TIMESTAMPTZ,
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)

    # Bước 3: Tạo partitions 2025-01 đến 2026-06
    partitions = []
    for year, month in [
        (2025, 1), (2025, 2), (2025, 3), (2025, 4),
        (2025, 5), (2025, 6), (2025, 7), (2025, 8),
        (2025, 9), (2025, 10), (2025, 11), (2025, 12),
        (2026, 1), (2026, 2), (2026, 3), (2026, 4),
        (2026, 5), (2026, 6),
    ]:
        op.execute(_create_partition(year, month))
        partitions.append(f"trade_history_{year}_{month:02d}")

    # Default partition cho data ngoài range
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade_history_default
        PARTITION OF trade_history DEFAULT
    """)

    # Bước 4: Copy data từ bảng cũ (nếu tồn tại)
    op.execute("""
        INSERT INTO trade_history
        SELECT * FROM trade_history_old
        WHERE trade_history_old.created_at IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    # Bước 5: Indexes trên bảng partitioned
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_th_account_created
        ON trade_history (account_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_th_symbol
        ON trade_history (symbol, created_at DESC)
    """)

    # Bước 6: Drop bảng cũ sau khi verify data
    op.execute("DROP TABLE IF EXISTS trade_history_old")


def downgrade() -> None:
    """
    Rollback: convert partitioned → regular table.
    WARNING: Tốn thời gian, không nên chạy trên production.
    """
    # Tạo bảng thường
    op.execute("""
        CREATE TABLE trade_history_unpartitioned AS
        SELECT * FROM trade_history
    """)

    # Xóa partitioned table (cascade xóa tất cả partitions)
    op.execute("DROP TABLE trade_history CASCADE")

    # Đổi tên về trade_history
    op.execute("ALTER TABLE trade_history_unpartitioned RENAME TO trade_history")

    # Recreate primary key
    op.execute("ALTER TABLE trade_history ADD PRIMARY KEY (id)")

    # Recreate index
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_th_account
        ON trade_history (account_id, created_at DESC)
    """)
