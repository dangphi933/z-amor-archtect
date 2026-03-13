"""
database.py — Z-ARMOR CLOUD
==============================
V1.1 (Giai đoạn 2):
  [R-05] atomic_bind_license() — PostgreSQL UPDATE WHERE bound_mt5_id IS NULL
  [R-12] Composite indexes: trade_history(account_id, created_at), audit_logs(account_id, created_at)
  [R-02] AdminUser model — bcrypt password, bỏ static token
  [4.3]  WebhookRetryQueue — Lark/Email không mất dữ liệu khi fail
  [4.3]  ConfigAuditTrail — ghi ai thay đổi gì lúc nào

V1.2 (Multi-Strategy):
  [S1]   License.strategy_id — lưu chiến lược trader đang chọn (S1/S2/S3)
         Column đã được tạo qua migration_strategy.sql
"""
import os
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    create_engine, String, Integer, Float, DateTime,
    Boolean, Text, func, UniqueConstraint, Index,
    update as sa_update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
_RAW_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://zarmor:Zarmor%402025@127.0.0.1:5432/zarmor_db"
)
SYNC_URL = (
    _RAW_URL
    .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    .replace("postgresql://",         "postgresql+psycopg2://")
    .split("?")[0]
)
engine       = create_engine(SYNC_URL, pool_size=10, max_overflow=20, pool_pre_ping=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
class Base(DeclarativeBase):
    pass
# ══════════════════════════════════════════════════════════════════
# LICENSE
# ══════════════════════════════════════════════════════════════════
class License(Base):
    __tablename__ = "license_keys"
    __table_args__ = (
        Index("ix_lic_bound_mt5", "bound_mt5_id"),   # R-12: tăng tốc verify_license
        Index("ix_lic_status",    "status"),          # R-12: expire job batch
        {"extend_existing": True},
    )
    id:             Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    license_key:    Mapped[str]           = mapped_column(String(60), unique=True, index=True, nullable=False)
    tier:           Mapped[Optional[str]] = mapped_column(String(50),  nullable=True)
    status:         Mapped[str]           = mapped_column(String(20),  default="UNUSED")
    buyer_name:     Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    buyer_email:    Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    bound_mt5_id:   Mapped[Optional[str]] = mapped_column(String(50),  nullable=True)
    is_trial:       Mapped[bool]          = mapped_column(Boolean,     default=False)
    amount_usd:     Mapped[Optional[float]]= mapped_column(Float,      nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(20),  nullable=True)
    max_machines:   Mapped[int]           = mapped_column(Integer,     default=1)
    activated_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    lark_record_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email_sent:     Mapped[bool]          = mapped_column(Boolean,     default=False)
    ip_address:     Mapped[Optional[str]] = mapped_column(String(50),  nullable=True)
    notes:          Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    created_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # [S1] Multi-Strategy — trader chọn preset trong dashboard, EA nhận qua heartbeat
    # Giá trị: "S1" (Gold_Trend_H1) | "S2" (FX_Range_H1) | "S3" (Scalp_Session_M15)
    # Column đã tạo qua migration_strategy.sql (ADD COLUMN IF NOT EXISTS)
    strategy_id:    Mapped[Optional[str]] = mapped_column(String(10),  nullable=True, default="S1")
class LicenseActivation(Base):
    __tablename__ = "license_activations"
    __table_args__ = (
        UniqueConstraint("license_key", "account_id", name="uq_lic_account"),
        Index("ix_la_account_id", "account_id"),
        {"extend_existing": True},
    )
    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    license_key: Mapped[str]           = mapped_column(String(60), index=True, nullable=False)
    account_id:  Mapped[str]           = mapped_column(String(50), nullable=False)
    magic:       Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    first_seen:  Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
# ══════════════════════════════════════════════════════════════════
# R-05: ATOMIC BIND — tránh race condition
# UPDATE WHERE bound_mt5_id IS NULL → chỉ 1 transaction thắng
# ══════════════════════════════════════════════════════════════════
def atomic_bind_license(db, license_key: str, account_id: str) -> dict:
    """
    Bind license key vào account_id trong 1 atomic UPDATE.
    Không cần SELECT FOR UPDATE hay application-level lock.
    Kịch bản:
      - Trader A và Trader B cùng gửi bind đồng thời
      - PostgreSQL chỉ cho 1 UPDATE thành công (rowcount=1)
      - Bên thua nhận rowcount=0 → trả error ngay
    Returns:
        {"status": "success", "reason": "BOUND_OK"}
        {"status": "success", "reason": "ALREADY_BOUND"}   ← idempotent
        {"status": "error",   "reason": "KEY_USED_BY_OTHER"}
        {"status": "error",   "reason": "KEY_NOT_FOUND"}
        {"status": "error",   "reason": "KEY_INACTIVE"}
    """
    now = datetime.now(timezone.utc)
    result = db.execute(
        sa_update(License)
        .where(
            License.license_key  == license_key,
            License.bound_mt5_id == None,              # noqa: E711  IS NULL
            License.status.in_(["UNUSED", "ACTIVE"]),
        )
        .values(bound_mt5_id=account_id, status="ACTIVE", activated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if result.rowcount == 1:
        return {"status": "success", "reason": "BOUND_OK", "account": account_id}
    # Phân tích lý do rowcount=0
    lic = db.query(License).filter(License.license_key == license_key).first()
    if not lic:
        return {"status": "error", "reason": "KEY_NOT_FOUND",
                "message": "Mã bản quyền không tồn tại."}
    if lic.bound_mt5_id == account_id:
        return {"status": "success", "reason": "ALREADY_BOUND", "account": account_id}
    if lic.bound_mt5_id:
        return {"status": "error", "reason": "KEY_USED_BY_OTHER",
                "message": f"Key đã được bind cho MT5 ID {lic.bound_mt5_id}. Liên hệ admin để reset."}
    if lic.status not in ("UNUSED", "ACTIVE"):
        return {"status": "error", "reason": "KEY_INACTIVE",
                "message": f"Key đang ở trạng thái {lic.status}."}
    return {"status": "error", "reason": "BIND_FAILED", "message": "Không thể bind. Thử lại."}
# ══════════════════════════════════════════════════════════════════
# TRADE / SESSION DATA
# ══════════════════════════════════════════════════════════════════
class TradeHistory(Base):
    __tablename__ = "trade_history"
    __table_args__ = (
        Index("ix_trade_account_created", "account_id", "created_at"),  # R-12
        Index("ix_trade_account_closed",  "account_id", "closed_at"),   # R-12
        {"extend_existing": True},
    )
    id:           Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:   Mapped[str]             = mapped_column(String(50), index=True, nullable=False)
    session_id:   Mapped[Optional[str]]   = mapped_column(String(50), nullable=True)
    ticket:       Mapped[Optional[str]]   = mapped_column(String(50), nullable=True)
    symbol:       Mapped[Optional[str]]   = mapped_column(String(20), nullable=True)
    trade_type:   Mapped[Optional[str]]   = mapped_column(String(10), nullable=True)
    volume:       Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_price:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_price:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl:          Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rr_ratio:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_amount:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_rr:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opened_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:   Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now())
class SessionHistory(Base):
    __tablename__ = "session_history"
    __table_args__ = (
        Index("ix_session_account_date", "account_id", "date"),
        {"extend_existing": True},
    )
    id:              Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:      Mapped[str]             = mapped_column(String(50), index=True, nullable=False)
    session_id:      Mapped[Optional[str]]   = mapped_column(String(50), unique=True, nullable=True)
    date:            Mapped[Optional[str]]   = mapped_column(String(20), nullable=True)
    opening_balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    closing_balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl:             Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_dd:          Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trade_count:     Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)
    win_count:       Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)
    loss_count:      Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)
    summary:         Mapped[Optional[str]]   = mapped_column(Text, nullable=True)
    created_at:      Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_account_created", "account_id", "created_at"),  # R-12
        {"extend_existing": True},
    )
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    action:     Mapped[str]           = mapped_column(String(100), nullable=False)
    severity:   Mapped[str]           = mapped_column(String(10),  default="INFO")
    message:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_id:     Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    email:      Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    detail:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
# ══════════════════════════════════════════════════════════════════
# EA UNIT CONFIG TABLES (giữ nguyên để tương thích dashboard)
# ══════════════════════════════════════════════════════════════════
class TradingAccount(Base):
    __tablename__ = "trading_accounts"
    __table_args__ = {"extend_existing": True}
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str]           = mapped_column(String(50), unique=True, index=True, nullable=False)
    alias:      Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_locked:  Mapped[bool]          = mapped_column(Boolean, default=False)
    arm:        Mapped[bool]          = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
class SystemState(Base):
    __tablename__ = "system_states"
    __table_args__ = {"extend_existing": True}
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str]           = mapped_column(String(50), unique=True, index=True, nullable=False)
    state_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
class RiskHardLimit(Base):
    __tablename__ = "risk_hard_limits"
    __table_args__ = {"extend_existing": True}
    id:                Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:        Mapped[str]   = mapped_column(String(50), unique=True, index=True, nullable=False)
    daily_limit_money: Mapped[float] = mapped_column(Float, default=150.0)
    max_dd:            Mapped[float] = mapped_column(Float, default=10.0)
    dd_type:           Mapped[str]   = mapped_column(String(20), default="STATIC")
    consistency:       Mapped[float] = mapped_column(Float, default=97.0)
    updated_at:        Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
class RiskTactical(Base):
    __tablename__ = "risk_tacticals"
    __table_args__ = {"extend_existing": True}
    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:  Mapped[str]           = mapped_column(String(50), unique=True, index=True, nullable=False)
    params_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at:  Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
class NeuralProfile(Base):
    __tablename__ = "neural_profiles"
    __table_args__ = {"extend_existing": True}
    id:                  Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:          Mapped[str]   = mapped_column(String(50), unique=True, index=True, nullable=False)
    trader_archetype:    Mapped[str]   = mapped_column(String(50), default="SNIPER")
    historical_win_rate: Mapped[float] = mapped_column(Float, default=40.0)
    historical_rr:       Mapped[float] = mapped_column(Float, default=1.5)
    optimization_bias:   Mapped[str]   = mapped_column(String(50), default="HALF_KELLY")
    updated_at:          Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
class TelegramConfig(Base):
    __tablename__ = "telegram_configs"
    __table_args__ = {"extend_existing": True}
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str]           = mapped_column(String(50), unique=True, index=True, nullable=False)
    chat_id:    Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active:  Mapped[bool]          = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
class EaSession(Base):
    __tablename__ = "ea_sessions"
    __table_args__ = {"extend_existing": True}
    id:          Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:  Mapped[str]             = mapped_column(String(50), index=True, nullable=False)
    session_id:  Mapped[str]             = mapped_column(String(50), unique=True, nullable=False)
    magic:       Mapped[Optional[str]]   = mapped_column(String(50), nullable=True)
    license_key: Mapped[Optional[str]]   = mapped_column(String(60), nullable=True)
    equity:      Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    balance:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status:      Mapped[str]             = mapped_column(String(20), default="ACTIVE")
    started_at:  Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_ping:   Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    ended_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_json:   Mapped[Optional[str]]   = mapped_column(Text, nullable=True)
# ══════════════════════════════════════════════════════════════════
# R-02: ADMIN USER — bcrypt password, không dùng static token
# ══════════════════════════════════════════════════════════════════
class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = {"extend_existing": True}
    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    email:         Mapped[str]           = mapped_column(String(200), unique=True, index=True, nullable=False)
    password_hash: Mapped[str]           = mapped_column(String(200), nullable=False)  # bcrypt
    is_active:     Mapped[bool]          = mapped_column(Boolean, default=True)
    last_login:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
# ══════════════════════════════════════════════════════════════════
# 4.3: WEBHOOK RETRY QUEUE
# ══════════════════════════════════════════════════════════════════
class WebhookRetryQueue(Base):
    __tablename__ = "webhook_retry_queue"
    __table_args__ = (
        Index("ix_retry_status_next", "status", "next_retry_at"),
        {"extend_existing": True},
    )
    id:            Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type:    Mapped[str]             = mapped_column(String(50), nullable=False)
    payload_json:  Mapped[str]             = mapped_column(Text, nullable=False)
    status:        Mapped[str]             = mapped_column(String(20), default="PENDING")
    attempts:      Mapped[int]             = mapped_column(Integer, default=0)
    max_attempts:  Mapped[int]             = mapped_column(Integer, default=5)
    last_error:    Mapped[Optional[str]]   = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:    Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
# ══════════════════════════════════════════════════════════════════
# 4.3: CONFIG AUDIT TRAIL — ai thay đổi gì lúc nào
# ══════════════════════════════════════════════════════════════════
class ConfigAuditTrail(Base):
    __tablename__ = "config_audit_trail"
    __table_args__ = (
        Index("ix_cat_account_created", "account_id", "created_at"),
        {"extend_existing": True},
    )
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str]           = mapped_column(String(50), index=True, nullable=False)
    changed_by: Mapped[str]           = mapped_column(String(200), nullable=False)  # email
    field_path: Mapped[str]           = mapped_column(String(200), nullable=False)  # vd: risk_params.max_dd
    old_value:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())