"""End-to-end walking skeleton test — full M0→M7 chain validation.

Chain: create_session → plan(intent) → invoke → audit_logs → checkpoints → blobs → executions.
Uses testcontainers PostgreSQL + FastAPI TestClient.
"""

from __future__ import annotations

import asyncio
import time

import jwt
from fastapi.testclient import TestClient

from earp_server.config import Settings
from earp_server.main import create_app

DEV_SECRET = "earp-dev-secret-change-in-production"
TENANT = "tenant-demo"  # register_demo in lifespan registers under this tenant


def _token(sub="u1", tenant_id=TENANT, role_id="r1") -> str:
    return jwt.encode(
        {"sub": sub, "tenant_id": tenant_id, "role_id": role_id, "exp": 9999999999},
        DEV_SECRET, algorithm="HS256",
    )


def test_full_e2e_walking_skeleton(migrated: str, app_url: str) -> None:
    """M0→M7 full chain: session → plan → invoke → audit → checkpoint → blobs → execution."""
    app = create_app(Settings(database_url=app_url, app_env="test"))
    auth = {"Authorization": f"Bearer {_token()}"}

    with TestClient(app) as c:
        # e2e bypass: PolicyLayer allows capabilities with empty required_permissions.
        # No DB seed needed — demo capability from lifespan has required_permissions but
        # we verify the chain via HTTP endpoints (session→plan→invoke→status checks).
        # Role-based permission verifications are covered by M2 RBAC scenario tests.

        # 1. Create session (M1)
        resp = c.post(
            "/v1/sessions",
            json={"user_id": "u1", "tenant_id": TENANT, "role_id": "r1"},
            headers=auth,
        )
        assert resp.status_code == 201, f"create session: {resp.json()}"
        sid = resp.json()["session_id"]

        # 2. Plan: intent → steps (M3)
        resp = c.post("/plan", json={"intent": "echo"}, headers=auth)
        assert resp.status_code == 200, f"plan: {resp.json()}"
        steps = resp.json()["steps"]
        assert len(steps) == 1
        cap_id = steps[0]["capability_id"]
        assert cap_id == "cap-demo-echo"

        # 3. Invoke (M1+M2+M5)
        resp = c.post(
            f"/v1/sessions/{sid}/invoke",
            json={"capability_id": cap_id, "input": {"message": "hello e2e"}},
            headers=auth,
        )
        assert resp.status_code == 200, f"invoke: {resp.json()}"
        data = resp.json()
        eid = data["execution_id"]
        ckpt_id = data["checkpoint_id"]
        assert data["status"] == "completed"
        assert ckpt_id is not None

        # 4. Verify DB: audit (M1+M2 — role_id in audit)
        time.sleep(0.2)  # let EventBus fire-and-forget write

        from sqlalchemy import text

        async def _verify():
            async with app.state.engine.connect() as conn:
                await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))

                # Audit: EXECUTION_COMPLETED
                audit = await conn.execute(
                    text(
                        "SELECT event_type, role_id, detail FROM audit_logs "
                        "WHERE execution_id = :eid "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"eid": eid},
                )
                row = audit.fetchone()
                assert row is not None, "audit_logs: no EXECUTION_COMPLETED"
                assert row.event_type == "earp.execution.completed"
                assert row.role_id == "r1"

                # Checkpoints (M1+M5)
                ckpt = await conn.execute(
                    text("SELECT checkpoint_id, checkpoint, metadata FROM checkpoints WHERE checkpoint_id = :cid"),
                    {"cid": ckpt_id},
                )
                assert ckpt.fetchone() is not None, "checkpoints: missing"

                # Blobs (M1)
                blob = await conn.execute(
                    text("SELECT count(*) FROM checkpoint_blobs WHERE checkpoint_id = :cid"),
                    {"cid": ckpt_id},
                )
                assert blob.scalar_one() > 0, "checkpoint_blobs: empty"

                # Execution (M1+M5)
                exec_row = await conn.execute(
                    text("SELECT status, result FROM executions WHERE execution_id = :eid"),
                    {"eid": eid},
                )
                r = exec_row.fetchone()
                assert r.status == "completed"

                # Capability (M4 pgvector)
                cap = await conn.execute(
                    text(
                        "SELECT capability_id, embedding "
                        "FROM business_capabilities WHERE capability_id = 'cap-demo-echo'"
                    ),
                )
                assert cap.fetchone() is not None, "capability: demo echo not registered"

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_verify())
        loop.close()
