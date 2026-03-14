"""
tests/conftest.py
=================
Shared fixtures cho toàn bộ test suite Z-Armor.

Nguyên tắc:
- Mỗi test chạy trong transaction riêng → rollback sau khi xong → test isolation
- KHÔNG bao giờ dùng production DATABASE_URL
- client fixture dùng TestClient (sync) — đủ cho majority of tests
"""
import os
import pytest
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# ─── Test DB URL (luôn từ env, không hardcode) ────────────────────────────────
TEST_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://test:test@localhost:5432/zarmor_test"
)


@pytest.fixture(scope="session")
def db_engine():
    """Engine dùng chung trong 1 test session."""
    engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db(db_engine):
    """
    DB session với transaction rollback sau mỗi test.
    Đảm bảo test isolation — mỗi test thấy DB sạch.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    TestingSession = sessionmaker(bind=connection, autocommit=False, autoflush=False)
    session = TestingSession()

    yield session

    session.close()
    transaction.rollback()  # ← cleanup tự động
    connection.close()


@pytest.fixture(scope="session")
def client():
    """
    FastAPI TestClient — dùng cho integration tests.
    scope=session để tránh khởi động app nhiều lần.
    """
    try:
        from main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    except ImportError as e:
        pytest.skip(f"Cannot import main app: {e}")


@pytest.fixture
def test_license(db):
    """
    Tạo license test hợp lệ trong DB.
    Tự động cleanup sau test (transaction rollback).
    """
    try:
        from database import License
    except ImportError:
        pytest.skip("database.License not available")

    lic = License(
        license_key="TEST-ABCDE-FGHIJ",
        tier="ARMOR",
        status="ACTIVE",
        buyer_email="test@zarmor.com",
        buyer_name="Test User",
        bound_mt5_id="12345678",
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        max_machines=3,
        strategy_id="S1",
    )
    db.add(lic)
    db.commit()
    return lic


@pytest.fixture
def expired_license(db):
    """License đã hết hạn."""
    try:
        from database import License
    except ImportError:
        pytest.skip("database.License not available")

    lic = License(
        license_key="EXPIRED-12345-67890",
        tier="ARMOR",
        status="ACTIVE",
        buyer_email="expired@zarmor.com",
        bound_mt5_id="11111111",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(lic)
    db.commit()
    return lic


@pytest.fixture
def inactive_license(db):
    """License bị suspend."""
    try:
        from database import License
    except ImportError:
        pytest.skip("database.License not available")

    lic = License(
        license_key="SUSPENDED-ABCDE-12345",
        tier="ARMOR",
        status="SUSPENDED",
        buyer_email="suspended@zarmor.com",
        bound_mt5_id="22222222",
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
    )
    db.add(lic)
    db.commit()
    return lic
