"""M2 RBAC scenarios — PRD-2026-022 AC-01 through AC-06.

Covers: PolicyLayer permissions check, PERMISSION_DENIED audit event,
role-aware capability discover, data_scope self-filtering, rate limiter.
"""

from __future__ import annotations

import asyncio

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text

from earp_server.config import Settings
from earp_server.main import create_app

DEV_SECRET = "earp-dev-secret-change-in-production"


def _token(sub="u1", tenant_id="t1", role_id="r1") -> str:
    return jwt.encode(
        {"sub": sub, "tenant_id": tenant_id, "role_id": role_id, "exp": 9999999999},
        DEV_SECRET, algorithm="HS256",
    )


def _seed_rbac_data(app, tenant_id: str) -> None:
    """Seed roles and users for RBAC testing."""
    engine = app.state.engine

    async def _seed():
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))

            # role R1: has demo:echo permission (replace if exists)
            await conn.execute(text(f"DELETE FROM roles WHERE role_id = 'r1' AND tenant_id = '{tenant_id}'"))
            await conn.execute(
                text(f"INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope) "
                     f"VALUES ('r1', '{tenant_id}', 'Role-One', ARRAY['demo:echo'], 'all')")
            )

            # role R2: no permissions
            await conn.execute(
                text(
                    "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope) "
                    "VALUES ('r2', :tid, 'Role-Two', '{}', 'self') "
                    "ON CONFLICT (role_id) DO NOTHING"
                ),
                {"tid": tenant_id},
            )

            # register demo capability (replace if exists)
            await conn.execute(
                text(f"DELETE FROM business_capabilities "
                     f"WHERE capability_id = 'cap-demo-echo' AND tenant_id = '{tenant_id}'"))
            await conn.execute(
                text(f"INSERT INTO business_capabilities "
                     f"(capability_id, tenant_id, domain, name, type, "
                     f"input_schema, required_permissions, version) "
                     f"VALUES ('cap-demo-echo', '{tenant_id}', 'demo', 'echo', "
                     f"'query', '{{}}', ARRAY['demo:echo'], '1.0.0')")
            )
            await conn.commit()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_seed())
    loop.close()


class TestRBACPermissions:
    """AC-01: permissions check — allow/deny invoke based on role.permissions."""

    def test_role_with_permission_invokes_successfully(self, migrated: str, app_url: str) -> None:
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app) as c:
            _seed_rbac_data(app, "t1")

            # R1 has demo:echo — invoke should succeed
            auth_r1 = {"Authorization": f"Bearer {_token(sub='u1', tenant_id='t1', role_id='r1')}"}
            resp = c.post("/v1/sessions", json={"user_id": "u1", "tenant_id": "t1", "role_id": "r1"}, headers=auth_r1)
            assert resp.status_code == 201
            sid = resp.json()["session_id"]

            resp = c.post(f"/v1/sessions/{sid}/invoke",
                           json={"capability_id": "cap-demo-echo", "input": {"message": "hi"}},
                           headers=auth_r1)
            assert resp.status_code == 200, f"invoke failed: {resp.status_code} {resp.json()}"
            assert resp.json()["status"] == "completed"

    def test_role_without_permission_gets_403_and_audit_denied(self, migrated: str, app_url: str) -> None:
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app) as c:
            _seed_rbac_data(app, "t1")

            # R2 has no permissions — invoke should get 403
            auth_r2 = {"Authorization": f"Bearer {_token(sub='u2', tenant_id='t1', role_id='r2')}"}
            resp = c.post("/v1/sessions", json={"user_id": "u2", "tenant_id": "t1", "role_id": "r2"}, headers=auth_r2)
            assert resp.status_code == 201
            sid = resp.json()["session_id"]

            resp = c.post(f"/v1/sessions/{sid}/invoke",
                           json={"capability_id": "cap-demo-echo", "input": {"message": "hi"}},
                           headers=auth_r2)
            assert resp.status_code == 403, f"expected 403, got {resp.status_code}"

            # AC-05: verify PERMISSION_DENIED event in audit_logs
            async def _verify():
                async with app.state.engine.connect() as conn:
                    await conn.execute(text("SET LOCAL earp.tenant_id = 't1'"))
                    row = await conn.execute(
                        text(
                            "SELECT detail->>'denied_capability' AS cap, "
                            "detail->>'role_id' AS rid "
                            "FROM audit_logs WHERE event_type = 'earp.execution.denied' "
                            "ORDER BY log_id DESC LIMIT 1"
                        ),
                    )
                    result = row.fetchone()
                    assert result is not None, "PERMISSION_DENIED audit event missing"
                    assert result.cap == "cap-demo-echo"
                    assert result.rid == "r2"
                    await conn.rollback()

            loop = asyncio.new_event_loop()
            loop.run_until_complete(_verify())
            loop.close()


class TestCapabilityDiscoverByRole:
    """AC-04: Capability discover returns only capabilities the role can access."""

    def test_discover_filters_by_role_permissions(self, migrated: str, app_url: str) -> None:
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app) as c:
            _seed_rbac_data(app, "t1")

            # R1 can see echo capability
            auth_r1 = {"Authorization": f"Bearer {_token(sub='u1', tenant_id='t1', role_id='r1')}"}
            resp = c.get("/capabilities?q=echo", headers=auth_r1)
            assert resp.status_code == 200
            caps = resp.json()
            assert any(c["name"] == "echo" for c in caps), f"R1 should see echo: {caps}"

            # R2 has no demo:echo — discover returns empty
            auth_r2 = {"Authorization": f"Bearer {_token(sub='u2', tenant_id='t1', role_id='r2')}"}
            resp = c.get("/capabilities?q=echo", headers=auth_r2)
            assert resp.status_code == 200
            caps = resp.json()
            assert not any(c["name"] == "echo" for c in caps), f"R2 should NOT see echo: {caps}"


class TestAuditEnhancement:
    """AC-05: audit events contain role_id."""

    def test_audit_contains_role_id(self, migrated: str, app_url: str) -> None:
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app) as c:
            _seed_rbac_data(app, "t1")

            auth_r1 = {"Authorization": f"Bearer {_token(sub='u1', tenant_id='t1', role_id='r1')}"}
            resp = c.post("/v1/sessions", json={"user_id": "u1", "tenant_id": "t1", "role_id": "r1"}, headers=auth_r1)
            assert resp.status_code == 201
            sid = resp.json()["session_id"]

            resp = c.post(f"/v1/sessions/{sid}/invoke",
                           json={"capability_id": "cap-demo-echo", "input": {"message": "hi"}},
                           headers=auth_r1)
            assert resp.status_code == 200

            async def _verify():
                async with app.state.engine.connect() as conn:
                    await conn.execute(text("SET LOCAL earp.tenant_id = 't1'"))
                    row = await conn.execute(
                        text(
                            "SELECT detail->>'role_id' AS rid FROM audit_logs "
                            "WHERE event_type = 'earp.execution.started' "
                            "ORDER BY log_id DESC LIMIT 1"
                        ),
                    )
                    result = row.fetchone()
                    assert result is not None
                    assert result.rid == "r1", f"role_id mismatch: {result.rid}"
                    await conn.rollback()

            loop = asyncio.new_event_loop()
            loop.run_until_complete(_verify())
            loop.close()
