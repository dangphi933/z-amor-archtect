"""
MIGRATE_TO_PG.py — Fixed version
"""
import os, sys, sqlite3
from datetime import datetime
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE, "Z-Armor.db")

load_dotenv(os.path.join(BASE, ".env"))
RAW_URL = os.getenv("DATABASE_URL", "")
if not RAW_URL:
    print("[!!] Khong tim thay DATABASE_URL trong .env")
    sys.exit(1)

SYNC_URL = (
    RAW_URL
    .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    .replace("postgresql://", "postgresql+psycopg2://")
    .split("?")[0]
)
print(f"[OK] PostgreSQL: {SYNC_URL[:60]}...")

from sqlalchemy import create_engine, text, String, Integer, Float, DateTime, Boolean, Text, func, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

engine = create_engine(SYNC_URL, pool_pre_ping=True, echo=False)

class Base(DeclarativeBase):
    pass

class License(Base):
    __tablename__ = "license_keys"
    __table_args__ = {"extend_existing": True}
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    license_key:   Mapped[str]      = mapped_column(String(60), unique=True, index=True, nullable=False)
    tier:          Mapped[str]      = mapped_column(String(50), nullable=True)
    status:        Mapped[str]      = mapped_column(String(20), default="UNUSED")
    buyer_name:    Mapped[str]      = mapped_column(String(200), nullable=True)
    buyer_email:   Mapped[str]      = mapped_column(String(200), nullable=True)
    bound_mt5_id:  Mapped[str]      = mapped_column(String(50), nullable=True)
    is_trial:      Mapped[bool]     = mapped_column(Boolean, default=False)
    amount_usd:    Mapped[float]    = mapped_column(Float, nullable=True)
    payment_method:Mapped[str]      = mapped_column(String(20), nullable=True)
    max_machines:  Mapped[int]      = mapped_column(Integer, default=1)
    activated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    lark_record_id:Mapped[str]      = mapped_column(String(100), nullable=True)
    email_sent:    Mapped[bool]     = mapped_column(Boolean, default=False)
    ip_address:    Mapped[str]      = mapped_column(String(50), nullable=True)
    notes:         Mapped[str]      = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class LicenseActivation(Base):
    __tablename__ = "license_activations"
    __table_args__ = (UniqueConstraint("license_key", "account_id", name="uq_lic_account"), {"extend_existing": True})
    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    license_key: Mapped[str]      = mapped_column(String(60), index=True, nullable=False)
    account_id:  Mapped[str]      = mapped_column(String(50), nullable=False)
    magic:       Mapped[str]      = mapped_column(String(50), nullable=True)
    first_seen:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen:   Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class TradeHistory(Base):
    __tablename__ = "trade_history"
    __table_args__ = {"extend_existing": True}
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:   Mapped[str]      = mapped_column(String(50), index=True, nullable=False)
    session_id:   Mapped[str]      = mapped_column(String(50), nullable=True)
    ticket:       Mapped[str]      = mapped_column(String(50), nullable=True)
    symbol:       Mapped[str]      = mapped_column(String(20), nullable=True)
    trade_type:   Mapped[str]      = mapped_column(String(10), nullable=True)
    volume:       Mapped[float]    = mapped_column(Float, nullable=True)
    open_price:   Mapped[float]    = mapped_column(Float, nullable=True)
    close_price:  Mapped[float]    = mapped_column(Float, nullable=True)
    pnl:          Mapped[float]    = mapped_column(Float, nullable=True)
    rr_ratio:     Mapped[float]    = mapped_column(Float, nullable=True)
    risk_amount:  Mapped[float]    = mapped_column(Float, nullable=True)
    actual_rr:    Mapped[float]    = mapped_column(Float, nullable=True)
    opened_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SessionHistory(Base):
    __tablename__ = "session_history"
    __table_args__ = {"extend_existing": True}
    id:              Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:      Mapped[str]      = mapped_column(String(50), index=True, nullable=False)
    session_id:      Mapped[str]      = mapped_column(String(50), unique=True, nullable=True)
    date:            Mapped[str]      = mapped_column(String(20), nullable=True)
    opening_balance: Mapped[float]    = mapped_column(Float, nullable=True)
    closing_balance: Mapped[float]    = mapped_column(Float, nullable=True)
    pnl:             Mapped[float]    = mapped_column(Float, nullable=True)
    max_dd:          Mapped[float]    = mapped_column(Float, nullable=True)
    trade_count:     Mapped[int]      = mapped_column(Integer, nullable=True)
    win_count:       Mapped[int]      = mapped_column(Integer, nullable=True)
    loss_count:      Mapped[int]      = mapped_column(Integer, nullable=True)
    summary:         Mapped[str]      = mapped_column(Text, nullable=True)
    created_at:      Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = {"extend_existing": True}
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str]      = mapped_column(String(50), nullable=True, index=True)
    action:     Mapped[str]      = mapped_column(String(100), nullable=False)
    severity:   Mapped[str]      = mapped_column(String(10), default="INFO")
    message:    Mapped[str]      = mapped_column(Text, nullable=True)
    extra:      Mapped[str]      = mapped_column(Text, nullable=True)
    key_id:     Mapped[int]      = mapped_column(Integer, nullable=True)
    email:      Mapped[str]      = mapped_column(String(200), nullable=True)
    detail:     Mapped[str]      = mapped_column(Text, nullable=True)
    ip_address: Mapped[str]      = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# ── Step 1: Tao bang ─────────────────────────────────────────────
print("\n[1/4] Tao cac bang trong PostgreSQL...")
try:
    Base.metadata.create_all(bind=engine)
    print("[OK] Tat ca bang da duoc tao.")
except Exception as e:
    print(f"[!!] Loi: {e}")
    sys.exit(1)

# ── Step 2: Them cot neu thieu ───────────────────────────────────
print("\n[2/4] Them cot con thieu...")
with engine.connect() as conn:
    for sql in [
        "ALTER TABLE license_keys ADD COLUMN IF NOT EXISTS max_machines INTEGER DEFAULT 1",
        "ALTER TABLE license_keys ADD COLUMN IF NOT EXISTS bound_mt5_id VARCHAR(50)",
        "ALTER TABLE license_keys ADD COLUMN IF NOT EXISTS buyer_name VARCHAR(200)",
        "ALTER TABLE license_keys ADD COLUMN IF NOT EXISTS tier VARCHAR(50)",
        "ALTER TABLE license_keys ADD COLUMN IF NOT EXISTS amount_usd FLOAT",
        "ALTER TABLE license_keys ADD COLUMN IF NOT EXISTS notes TEXT",
    ]:
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception as e:
            if "already exists" not in str(e):
                print(f"  Warning: {e}")
print("[OK] Cot san sang.")

# ── Step 3: Migrate tu SQLite ────────────────────────────────────
print("\n[3/4] Migrate data tu SQLite...")
backup = os.path.join(BASE, "Z-Armor.db.backup_20260306")
src = backup if os.path.exists(backup) else SQLITE_PATH

if not os.path.exists(src):
    print(f"  Khong tim thay SQLite ({src}) — bo qua.")
else:
    print(f"  Dung source: {src}")
    sq = sqlite3.connect(src)
    sq.row_factory = sqlite3.Row
    cur = sq.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"  SQLite tables: {tables}")

    license_table = None
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1].lower() for r in cur.fetchall()]
        if "license_key" in cols:
            license_table = t
            break

    if license_table:
        cur.execute(f"SELECT * FROM {license_table}")
        rows = cur.fetchall()
        import psycopg2
        pg_url = SYNC_URL.replace("postgresql+psycopg2://", "")
        pg = psycopg2.connect(f"postgresql://{pg_url.split('postgresql+psycopg2://')[-1]}" if "postgresql+psycopg2://" in SYNC_URL else SYNC_URL.replace("postgresql+psycopg2://","postgresql://"))
        pg_cur = pg.cursor()
        migrated = skipped = 0
        for row in rows:
            d = dict(row)
            key = d.get("license_key")
            if not key:
                continue
            try:
                pg_cur.execute("""
                    INSERT INTO license_keys
                        (license_key, tier, status, buyer_name, buyer_email,
                         bound_mt5_id, is_trial, max_machines,
                         activated_at, expires_at, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (license_key) DO UPDATE SET
                        status       = EXCLUDED.status,
                        bound_mt5_id = COALESCE(EXCLUDED.bound_mt5_id, license_keys.bound_mt5_id),
                        expires_at   = COALESCE(EXCLUDED.expires_at,   license_keys.expires_at),
                        max_machines = EXCLUDED.max_machines
                """, (
                    key,
                    d.get("tier", "standard"),
                    d.get("status", "UNUSED"),
                    d.get("buyer_name") or d.get("owner_name", ""),
                    d.get("buyer_email") or d.get("owner_email", ""),
                    d.get("bound_mt5_id", ""),
                    bool(d.get("is_trial", 0)),
                    int(d.get("max_machines", 1) or 1),
                    d.get("activated_at"),
                    d.get("expires_at"),
                    d.get("created_at") or datetime.utcnow().isoformat(),
                ))
                migrated += 1
            except Exception as e:
                print(f"  Skip {key[:15]}: {e}")
                skipped += 1
        pg.commit()
        pg.close()
        sq.close()
        print(f"[OK] Migrated {migrated} keys, skipped {skipped}.")
    else:
        print("  Khong tim thay bang license trong SQLite.")

# ── Step 4: Verify ───────────────────────────────────────────────
print("\n[4/4] Kiem tra:")
with engine.connect() as conn:
    for t in ["license_keys","license_activations","trade_history","session_history","audit_logs"]:
        try:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  [OK] {t}: {n} rows")
        except Exception as e:
            print(f"  [!!] {t}: {e}")

print("\n" + "="*50)
print("MIGRATE HOAN TAT - Chay START_SERVERS.bat!")
print("="*50)
