"""
tests/test_health.py
====================
Tests cho /health endpoint (C.5).
Đây là test quan trọng nhất — CI/CD smoke test phụ thuộc endpoint này.
"""
import pytest


class TestHealthEndpoint:
    def test_health_returns_200_or_503(self, client):
        """/health phải trả về 200 hoặc 503 — không bao giờ crash."""
        resp = client.get("/health")
        assert resp.status_code in (200, 503), f"Unexpected status: {resp.status_code}"

    def test_health_api_alias_works(self, client):
        """/api/health backward-compat alias phải hoạt động."""
        resp = client.get("/api/health")
        assert resp.status_code in (200, 503)

    def test_health_returns_json(self, client):
        """/health phải trả về JSON hợp lệ."""
        resp = client.get("/health")
        data = resp.json()
        assert isinstance(data, dict)

    def test_health_has_required_fields(self, client):
        """/health phải có: status, checks, version, timestamp."""
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data, "Missing 'status' field"
        assert "checks" in data, "Missing 'checks' field"
        assert "version" in data, "Missing 'version' field"
        assert "timestamp" in data, "Missing 'timestamp' field"

    def test_health_status_is_valid_value(self, client):
        """/health status phải là 'healthy' hoặc 'degraded'."""
        resp = client.get("/health")
        assert resp.json()["status"] in ("healthy", "degraded")

    def test_health_checks_has_database_key(self, client):
        """/health checks phải có 'database' key."""
        resp = client.get("/health")
        checks = resp.json().get("checks", {})
        assert "database" in checks, "Missing database check"

    def test_health_version_matches(self, client):
        """/health version phải match expected version."""
        resp = client.get("/health")
        assert resp.json().get("version") == "8.3.1"

    def test_health_latency_ms_present(self, client):
        """/health phải report latency_ms."""
        resp = client.get("/health")
        data = resp.json()
        assert "latency_ms" in data
        assert isinstance(data["latency_ms"], (int, float))
        assert data["latency_ms"] >= 0
