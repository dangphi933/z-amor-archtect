"""
tests/test_ea_heartbeat.py
===========================
Tests cho EA Heartbeat endpoint — endpoint quan trọng nhất,
live EA clients gọi mỗi 30s.

Tất cả tests đều backward-compatible — không thay đổi behavior.
"""
import pytest


class TestEAHeartbeat:
    """Tests cho GET /heartbeat"""

    def test_heartbeat_valid_license(self, client, test_license):
        """License hợp lệ + đúng account → valid=True."""
        resp = client.get("/heartbeat", params={
            "license": "TEST-ABCDE-FGHIJ",
            "account": "12345678",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data.get("lock") is False

    def test_heartbeat_invalid_license(self, client):
        """License không tồn tại → valid=False, reason=INVALID_KEY."""
        resp = client.get("/heartbeat", params={
            "license": "INVALID-KEY-DOES-NOT-EXIST-12345",
            "account": "99999999",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data.get("reason") == "INVALID_KEY"

    def test_heartbeat_mt5_mismatch(self, client, test_license):
        """Account ID khác bound_mt5_id → lock=True, reason=MT5_ID_MISMATCH."""
        resp = client.get("/heartbeat", params={
            "license": "TEST-ABCDE-FGHIJ",
            "account": "99999999",  # khác bound_mt5_id=12345678
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("reason") == "MT5_ID_MISMATCH"

    def test_heartbeat_expired_license(self, client, expired_license):
        """License hết hạn → valid=False, reason=LICENSE_EXPIRED."""
        resp = client.get("/heartbeat", params={
            "license": "EXPIRED-12345-67890",
            "account": "11111111",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data.get("reason") == "LICENSE_EXPIRED"

    def test_heartbeat_suspended_license(self, client, inactive_license):
        """License bị suspend → valid=False."""
        resp = client.get("/heartbeat", params={
            "license": "SUSPENDED-ABCDE-12345",
            "account": "22222222",
        })
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_heartbeat_response_structure(self, client, test_license):
        """Heartbeat response phải có các fields cần thiết cho EA."""
        resp = client.get("/heartbeat", params={
            "license": "TEST-ABCDE-FGHIJ",
            "account": "12345678",
        })
        assert resp.status_code == 200
        data = resp.json()
        # Fields mà EA expects
        assert "valid" in data
        assert "lock" in data

    def test_heartbeat_rate_limit_caching(self, client, test_license):
        """2 heartbeats liên tiếp trong window → thứ 2 trả OK_CACHED."""
        params = {"license": "TEST-ABCDE-FGHIJ", "account": "12345678"}
        r1 = client.get("/heartbeat", params=params)
        r2 = client.get("/heartbeat", params=params)
        assert r1.status_code == 200
        assert r2.status_code == 200
        # Thứ 2 phải là cached response
        assert r2.json().get("reason") == "OK_CACHED"

    def test_heartbeat_missing_params_returns_error(self, client):
        """Thiếu license param → error response (không crash 500)."""
        resp = client.get("/heartbeat", params={"account": "12345678"})
        # Phải trả error, không phải 500 Internal Server Error
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            assert resp.json()["valid"] is False
