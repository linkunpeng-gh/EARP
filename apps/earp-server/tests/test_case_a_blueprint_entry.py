"""T07 contract tests for the isolated Case A Blueprint planning entry."""

from __future__ import annotations

import asyncio
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.compiler import compile_case_a_causal_blueprint, seed_case_a_step_types
from earp_server.bmc.metamodel import import_case_a_snapshot_fixture
from earp_server.config import Settings
from earp_server.gateway.auth import DEV_SECRET
from earp_server.infra.db import tenant_session
from earp_server.main import create_app
from earp_server.planner.blueprint_discovery import BlueprintDiscoveryError, discover_compiled_causal_blueprint
from earp_server.planner.blueprint_entry import BlueprintEntryError, BlueprintPlanningEntry, PlanningEntryRequest
from earp_server.planner.task_planner import SimpleTaskPlanner

FIXTURE_DIR = Path(__file__).parent / "scenarios" / "mine_3_production_drop"
TENANT = "tenant-mine-demo"
ROLE = "r-case-a-planner"
CASE_A_TEXT = "为什么 3 号矿昨天产量下降？"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
def registry_engine(migrated: str, migration_url: str) -> AsyncEngine:
    return create_async_engine(migration_url, pool_pre_ping=True)


async def _ready(app_engine: AsyncEngine, registry_engine: AsyncEngine) -> None:
    await import_case_a_snapshot_fixture(app_engine, registry_engine, FIXTURE_DIR)
    await seed_case_a_step_types(registry_engine)
    await compile_case_a_causal_blueprint(app_engine, TENANT, "cms-mine-3-production-drop-v1")
    async with tenant_session(app_engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope) "
                "VALUES (:role_id, :tenant_id, 'Case A planner', '{}', 'all') "
                "ON CONFLICT (role_id) DO NOTHING"
            ),
            {"role_id": ROLE, "tenant_id": TENANT},
        )


async def test_entry_resolves_one_goal_and_pinned_blueprint(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    await _ready(app_engine, registry_engine)
    result = await BlueprintPlanningEntry(app_engine, FIXTURE_DIR).resolve(
        PlanningEntryRequest(text=CASE_A_TEXT, tenant_id=TENANT, role_id=ROLE)
    )
    payload = result.as_dict()

    assert payload["intent_fixture"] == {
        "fixture_hash": "bd2b059dfac685957a151a3254893089581b8acbd6eccbb12c0d79281a5cbcae",
        "prompt_version": "case-a-deterministic-stub/v1",
        "structured_output_schema_version": "intent-goal-output/v1",
    }
    assert payload["parsed_intent"] == {
        "entry_point": "production_output",
        "direction": "down",
        "domain": "production",
        "business_objective": "diagnose",
    }
    assert payload["blueprint"]["source_snapshot_id"] == "cms-mine-3-production-drop-v1"
    assert payload["blueprint"]["source_content_hash"] == (
        "3f7418d45f8c9ba92fd4a9a701f76127825383018cbcd3a02a7ea1c349f8aa16"
    )
    assert len(payload["goals"]) == 1
    goal = payload["goals"][0]
    assert goal["objective"] == "diagnose"
    assert goal["bindings"] == {
        "entity_id": "mine-3",
        "entity_type": "mine",
        "time_window": {"start": "2026-08-28T00:00:00+08:00", "end": "2026-08-29T00:00:00+08:00"},
    }
    assert payload["prepare"] == {"status": "not_prepared", "prepare_id": None}
    # T07 only resolves a goal; it must not pre-expand dynamic evidence tasks.
    assert "tasks" not in payload and "evidence" not in payload


async def test_entry_fails_closed_for_mismatch_missing_role_and_uncompiled_intent(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    await _ready(app_engine, registry_engine)
    entry = BlueprintPlanningEntry(app_engine, FIXTURE_DIR)
    with pytest.raises(BlueprintEntryError, match="does not match"):
        await entry.resolve(PlanningEntryRequest(text="另一个问题", tenant_id=TENANT, role_id=ROLE))
    with pytest.raises(BlueprintEntryError, match="role"):
        await entry.resolve(PlanningEntryRequest(text=CASE_A_TEXT, tenant_id=TENANT, role_id="missing-role"))

    # A different supported-looking intent must not use Case A as a fallback.
    with pytest.raises(BlueprintDiscoveryError, match="exactly one current compiled"):
        await discover_compiled_causal_blueprint(
            app_engine,
            TENANT,
            entry_point="production_output",
            direction="down",
            domain="maintenance",
            business_objective="diagnose",
        )


def _token() -> str:
    return jwt.encode(
        {"sub": "case-a-user", "tenant_id": TENANT, "role_id": ROLE, "exp": 9999999999},
        DEV_SECRET,
        algorithm="HS256",
    )


def test_entry_http_route_is_isolated_from_legacy_plan(migrated: str, app_url: str, migration_url: str) -> None:
    """The explicit entry works over HTTP without changing the legacy `/plan` route."""

    async def setup() -> None:
        app_engine = create_async_engine(app_url, pool_pre_ping=True)
        registry_engine = create_async_engine(migration_url, pool_pre_ping=True)
        try:
            await _ready(app_engine, registry_engine)
        finally:
            await app_engine.dispose()
            await registry_engine.dispose()

    asyncio.run(setup())
    app = create_app(Settings(database_url=app_url, app_env="test"))
    auth = {"Authorization": f"Bearer {_token()}"}
    with TestClient(app) as client:
        response = client.post("/v1/ecmc/planning/entry", json={"text": CASE_A_TEXT}, headers=auth)
        assert response.status_code == 200, response.json()
        assert response.json()["goals"][0]["bindings"]["entity_id"] == "mine-3"
        assert response.json()["prepare"]["status"] == "not_prepared"

        # Avoid the optional real LLM connector in this regression assertion.
        app.state.planner = SimpleTaskPlanner()
        legacy = client.post("/plan", json={"intent": "echo"}, headers=auth)
        assert legacy.status_code == 200, legacy.json()
        assert legacy.json() == {
            "intent": "echo",
            "steps": [{"capability_id": "cap-demo-echo", "adapter_type": "demo.echo", "input": {"message": "hello"}}],
        }
