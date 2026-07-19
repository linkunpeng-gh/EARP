"""AC-01: /health and /ready reflect service and DB state (no auth)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from earp_server.config import Settings
from earp_server.main import create_app


def test_health_ok_and_ready_ok(migrated: str, app_url: str) -> None:
    app = create_app(Settings(database_url=app_url, app_env="test"))
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {"db": "ok"}


def test_ready_503_when_db_unreachable() -> None:
    bogus = "postgresql+psycopg://nobody:wrong@127.0.0.1:1/earp"
    app = create_app(Settings(database_url=bogus, app_env="test"))
    with TestClient(app) as client:
        ready = client.get("/ready")
        assert ready.status_code == 503
        assert ready.json() == {"db": "fail"}


def test_sessions_placeholder_returns_501(migrated: str, app_url: str) -> None:
    """M1: real API — requires JWT auth. Test with a valid dev token."""
    import jwt

    token = jwt.encode(
        {"sub": "u1", "tenant_id": "t1", "role_id": "r1", "exp": 9999999999},
        "earp-dev-secret-change-in-production",
        algorithm="HS256",
    )
    app = create_app(Settings(database_url=app_url, app_env="test"))
    with TestClient(app) as client:
        resp = client.post(
            "/v1/sessions",
            json={"user_id": "u1", "tenant_id": "t1", "role_id": "r1"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
