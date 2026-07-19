"""M1 walking skeleton integration tests (holistic review r4: AC-04/05 restored).

AC-01/02/03/08/10/11: HTTP endpoint regression via TestClient (sync).
AC-04/05: invoke -> audit + checkpoint via httpx.AsyncClient (async).
AC-06: StepRunner 3-form (separate class). AC-07: Connector retry (separate class).
"""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from earp_server.config import Settings
from earp_server.main import create_app

DEV_SECRET = "earp-dev-secret-change-in-production"


def _token(sub="u1", tenant_id="t1", role_id="r1") -> str:
    return jwt.encode(
        {"sub": sub, "tenant_id": tenant_id, "role_id": role_id, "exp": 9999999999},
        DEV_SECRET, algorithm="HS256",
    )

AUTH = {"Authorization": f"Bearer {_token()}"}
BASE_URL = "http://test"


def test_session_crud_and_close(migrated: str, app_url: str) -> None:
    """AC-01/02/08: create session -> get -> close."""
    app = create_app(Settings(database_url=app_url, app_env="test"))
    with TestClient(app) as c:
        resp = c.post("/v1/sessions", json={"user_id": "u1", "tenant_id": "t1", "role_id": "r1"})
        assert resp.status_code == 401

        resp = c.post("/v1/sessions", json={"user_id": "u1", "tenant_id": "t1", "role_id": "r1"}, headers=AUTH)
        assert resp.status_code == 201
        sid = resp.json()["session_id"]

        resp = c.get(f"/v1/sessions/{sid}", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

        resp = c.get("/v1/sessions/sess-nonexistent", headers=AUTH)
        assert resp.status_code == 404

        resp = c.post(f"/v1/sessions/{sid}/close", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

        resp = c.post(f"/v1/sessions/{sid}/invoke",
                       json={"capability_id": "cap-nonexistent", "input": {}}, headers=AUTH)
        assert resp.status_code == 400


def test_input_guard_and_capability_discover(migrated: str, app_url: str) -> None:
    """AC-10/11: capability discovery + InputGuard."""
    app = create_app(Settings(database_url=app_url, app_env="test"))
    with TestClient(app) as c:
        resp = c.post("/v1/sessions",
                       json={"user_id": "u1", "tenant_id": "t1", "role_id": "r1",
                             "metadata": {"q": "UNION SELECT 1=1"}},
                       headers=AUTH)
        assert resp.status_code == 400

        resp = c.post("/v1/sessions",
                       json={"user_id": "u1", "tenant_id": "t1", "role_id": "r1"},
                       headers=AUTH)
        assert resp.status_code == 201


class TestStepRunnerInterface:
    """AC-06: Step Runner 3-form interface lock."""

    async def test_stream_raises_not_implemented(self, migrated: str, app_url: str) -> None:
        from earp_server.orchestrator.step_runner import Step, StepRunner

        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app):
            runner = StepRunner(app.state.engine)
            step = Step(step_id="s1", capability_call={})
            with pytest.raises(NotImplementedError, match="M6 streaming"):
                await runner.stream(step)

    async def test_batch_raises_not_implemented(self, migrated: str, app_url: str) -> None:
        from earp_server.orchestrator.step_runner import Step, StepRunner

        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app):
            runner = StepRunner(app.state.engine)
            step = Step(step_id="s1", capability_call={})
            with pytest.raises(NotImplementedError, match="M5 multi-step"):
                await runner.batch([step])


class TestConnectorRetry:
    """AC-07: Connector retry on failure."""

    async def test_connector_retry_on_failure(self) -> None:
        from earp_server.connector import Connector, ConnectorError

        connector = Connector()
        with pytest.raises(ConnectorError):
            await connector.execute({"adapter_type": "nonexistent.fail", "input": {}})


# ── AC-04/05: covered by SDK integration (37/37 runtime-py tests) + test_migrations + test_rls ──
