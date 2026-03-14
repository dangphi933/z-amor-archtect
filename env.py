"""
migrations/env.py
=================
Alembic environment config cho Z-Armor Cloud Engine.

- Load DATABASE_URL từ .env (KHÔNG hardcode credentials)
- Auto-convert asyncpg → psycopg2 nếu cần
- compare_type=True để detect column type changes
- compare_server_default=True để detect DEFAULT changes
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# ─── Load .env ────────────────────────────────────────────────────────────────
load_dotenv()

# ─── Import tất cả models để Alembic detect schema ───────────────────────────
# QUAN TRỌNG: phải import Base và tất cả models TRƯỚC khi dùng Base.metadata
# Nếu thêm model mới, import ở đây để autogenerate hoạt động
try:
    from database import Base  # noqa: F401
    import database  # noqa: F401 — trigger tất cả mapped_column definitions

    # Import thêm các module có models riêng nếu có
    # from radar.models import RadarScan  # noqa: F401
    # from ml.models import LabeledScan   # noqa: F401
except ImportError as e:
    print(f"[ALEMBIC] Warning: Could not import models: {e}")
    print("[ALEMBIC] Continuing without model metadata (offline mode only)")
    Base = None

# ─── Alembic config ───────────────────────────────────────────────────────────
config = context.config

# Build sync DATABASE_URL từ env
_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://zarmor:password@localhost:5432/zarmor_db"
)

# Alembic cần psycopg2 driver (sync) — convert nếu có asyncpg hoặc plain postgres
SYNC_URL = (
    _raw_url
    .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    .replace("postgresql://", "postgresql+psycopg2://")
    .split("?")[0]  # xóa query params (sslmode, etc.) để tránh conflict
)

config.set_main_option("sqlalchemy.url", SYNC_URL)

# Setup file logging nếu có config file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata để autogenerate diffs
# None nếu không import được models (offline mode)
target_metadata = Base.metadata if Base is not None else None


def run_migrations_offline() -> None:
    """
    Offline mode: generate SQL script mà không cần kết nối DB.
    Dùng để review SQL trước khi chạy trên production.

    Chạy: alembic upgrade head --sql > migration.sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        # include_schemas=True,  # bật nếu dùng multiple schemas
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Online mode: kết nối trực tiếp và chạy migrations.
    Dùng trong CI/CD và deploy.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool cho CI — không giữ connections
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,               # detect column type changes
            compare_server_default=True,     # detect DEFAULT value changes
            # render_as_batch=True,          # bật nếu dùng SQLite (test env)
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
