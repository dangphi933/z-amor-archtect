"""
alembic/env.py — Z-ARMOR CLOUD
================================
4.3: Cấu hình Alembic đọc DATABASE_URL từ .env
     và import tất cả models từ database.py để autogenerate migration.

Copy file này vào alembic/env.py sau khi chạy alembic_setup.sh
"""

import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Thêm project root vào sys.path để import database.py
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# Import Base và tất cả models để autogenerate phát hiện thay đổi
from database import (
    Base,
    License, LicenseActivation,
    TradeHistory, SessionHistory, AuditLog,
    TradingAccount, SystemState, RiskHardLimit, RiskTactical,
    NeuralProfile, TelegramConfig, EaSession,
    AdminUser,           # R-02 (Giai đoạn 2)
    WebhookRetryQueue,   # 4.3
    ConfigAuditTrail,    # 4.3
)

# Alembic Config object
config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL từ .env — override alembic.ini
_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://zarmor:Zarmor%402025@127.0.0.1:5432/zarmor_db"
)
SYNC_URL = (
    _raw_url
    .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    .replace("postgresql://",         "postgresql+psycopg2://")
    .split("?")[0]
)
config.set_main_option("sqlalchemy.url", SYNC_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Tạo SQL script mà không cần kết nối DB thực."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
        compare_type=True,        # phát hiện thay đổi column type
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Chạy migration trực tiếp lên DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
