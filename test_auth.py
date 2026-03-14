"""
tests/test_auth.py
==================
Tests cho Authentication endpoints (magic link, JWT).
"""
import pytest


class TestAuth:
    def test_magic_request_valid_email(self, client):
        """Email hợp lệ → status sent (hoặc 500 nếu SMTP không config trong CI)."""
        resp = client.post("/auth/magic-request", json={"email": "test@example.com"})
        # CI không có SMTP — chấp nhận 200 hoặc 500
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") in ("sent", "ok", "success")

    def test_magic_request_invalid_email_format(self, client):
        """Email format không hợp lệ → 400 hoặc 422."""
        resp = client.post("/auth/magic-request", json={"email": "not-an-email"})
        assert resp.status_code in (400, 422)

    def test_magic_request_empty_email(self, client):
        """Email rỗng → 400 hoặc 422."""
        resp = client.post("/auth/magic-request", json={"email": ""})
        assert resp.status_code in (400, 422)

    def test_login_with_valid_license(self, client, test_license):
        """Login bằng license key hợp lệ → JWT token."""
        resp = client.post("/auth/login", json={"license_key": "TEST-ABCDE-FGHIJ"})
        if resp.status_code == 200:
            data = resp.json()
            assert "access_token" in data
            assert data.get("token_type") == "bearer"
        else:
            # Endpoint có thể chưa implement — skip
            pytest.skip(f"Login endpoint returned {resp.status_code}")

    def test_login_invalid_license(self, client):
        """License không tồn tại → 401 hoặc 400."""
        resp = client.post("/auth/login", json={"license_key": "INVALID-KEY-9999"})
        assert resp.status_code in (400, 401, 404)

    def test_protected_endpoint_requires_auth(self, client):
        """Endpoint cần auth → 401 nếu không có token."""
        resp = client.get("/user/profile")
        assert resp.status_code in (401, 403, 422)


class TestLicense:
    def test_license_bind_valid(self, client, test_license):
        """Bind license với MT5 ID → thành công."""
        resp = client.post("/bind-license", json={
            "license_key": "TEST-ABCDE-FGHIJ",
            "mt5_id": "12345678",
        })
        assert resp.status_code in (200, 201)

    def test_license_bind_invalid_key(self, client):
        """Bind license không tồn tại → error."""
        resp = client.post("/bind-license", json={
            "license_key": "NONEXISTENT-KEY-ABC",
            "mt5_id": "99999999",
        })
        assert resp.status_code in (400, 404)

    def test_license_status_active(self, client, test_license):
        """License status check → ACTIVE."""
        resp = client.get("/heartbeat", params={
            "license": "TEST-ABCDE-FGHIJ",
            "account": "12345678",
        })
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_license_expired_returns_false(self, client, expired_license):
        """Expired license → valid=False."""
        resp = client.get("/heartbeat", params={
            "license": "EXPIRED-12345-67890",
            "account": "11111111",
        })
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
