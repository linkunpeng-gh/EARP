"""T08 contract tests: provider-free, pinned Case A ReasoningContext Prepare."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.compiler import compile_case_a_causal_blueprint, seed_case_a_step_types
from earp_server.bmc.metamodel import import_case_a_snapshot_fixture
from earp_server.bmc.reasoning import (
    ReasoningPrepareError,
    cancel_reasoning_context,
    get_reasoning_context,
    prepare_case_a_reasoning,
)
from earp_server.infra.db import tenant_session

FIXTURE_DIR = Path(__file__).parent / "scenarios" / "mine_3_production_drop"
TENANT = "tenant-mine-demo"
SNAPSHOT_ID = "cms-mine-3-production-drop-v1"
TIME_WINDOW = {"start": "2026-08-28T00:00:00+08:00", "end": "2026-08-29T00:00:00+08:00"}


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
def registry_engine(migrated: str, migration_url: str) -> AsyncEngine:
    return create_async_engine(migration_url, pool_pre_ping=True)


async def _blueprint(app_engine: AsyncEngine, registry_engine: AsyncEngine) -> tuple[str, str]:
    await import_case_a_snapshot_fixture(app_engine, registry_engine, FIXTURE_DIR)
    await seed_case_a_step_types(registry_engine)
    compiled = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID)
    assert compiled.blueprint_version_id is not None
    async with tenant_session(app_engine, TENANT) as session:
        skeleton_id = (
            await session.execute(
                text(
                    "SELECT goal_skeleton_id FROM blueprint_goal_skeletons "
                    "WHERE blueprint_version_id = :version_id AND objective = 'diagnose'"
                ),
                {"version_id": compiled.blueprint_version_id},
            )
        ).scalar_one()
    return compiled.blueprint_version_id, skeleton_id


async def test_prepare_pins_blueprint_and_resolves_the_expected_abox_targets(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    blueprint_version_id, skeleton_id = await _blueprint(app_engine, registry_engine)
    result = await prepare_case_a_reasoning(
        app_engine,
        TENANT,
        blueprint_version_id,
        {"entity_id": "mine-3", "time_window": TIME_WINDOW},
        goal_skeleton_id=skeleton_id,
        reasoning_mode="explainable",
        authz_scope={"scope_version": "test/v1", "allowed_entity_ids": ["mine-3"]},
    )
    assert result.status == "prepared"
    assert result.snapshot_id == SNAPSHOT_ID
    assert result.algorithm_version_id == "sign-propagation-v1-fixture"
    assert len(result.requirements) == 5
    by_key = {item["requirement_key"]: item for item in result.requirements}
    assert by_key["production_actual_and_baseline"]["target_entity_id"] == "mine-3"
    assert by_key["ore_quality_observation"]["target_entity_id"] == "mine-3"
    assert by_key["critical_equipment_availability"]["target_entity_id"] == "critical-equipment-group-mine-3"
    assert by_key["haulage_cycle_observation"]["target_entity_id"] == "haulage-system-mine-3"
    assert by_key["haulage_queue_observation"]["target_entity_id"] == "haulage-system-mine-3"
    assert len({item["requirement_id"] for item in result.requirements}) == 5

    replay = await prepare_case_a_reasoning(
        app_engine,
        TENANT,
        blueprint_version_id,
        {"entity_id": "mine-3", "time_window": TIME_WINDOW},
        goal_skeleton_id=skeleton_id,
        reasoning_mode="explainable",
        authz_scope={"allowed_entity_ids": ["mine-3"], "scope_version": "test/v1"},
    )
    assert replay == result
    context = await get_reasoning_context(app_engine, TENANT, result.prepare_id)
    assert context["context_hash"] == result.context_hash
    assert context["snapshot_hash"] == result.snapshot_hash
    assert context["instance_snapshot"]["schema_version"] == "case-a-instantiated-abox/v1"
    assert len(context["evidence_requirements"]) == 5


async def test_prepare_fails_closed_for_unknown_goal_scope_and_cross_tenant_access(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    blueprint_version_id, skeleton_id = await _blueprint(app_engine, registry_engine)
    with pytest.raises(ReasoningPrepareError, match="unknown"):
        await prepare_case_a_reasoning(
            app_engine,
            TENANT,
            blueprint_version_id,
            {"entity_id": "not-mine-3", "time_window": TIME_WINDOW},
            goal_skeleton_id=skeleton_id,
        )
    with pytest.raises(ReasoningPrepareError, match="scope excludes"):
        await prepare_case_a_reasoning(
            app_engine,
            TENANT,
            blueprint_version_id,
            {"entity_id": "mine-3", "time_window": TIME_WINDOW},
            goal_skeleton_id=skeleton_id,
            authz_scope={"allowed_entity_ids": ["other-entity"]},
        )
    with pytest.raises(ReasoningPrepareError, match="not found for this tenant"):
        await prepare_case_a_reasoning(
            app_engine,
            "other-tenant",
            blueprint_version_id,
            {"entity_id": "mine-3", "time_window": TIME_WINDOW},
            goal_skeleton_id=skeleton_id,
        )


async def test_prepare_context_can_be_cancelled_without_provider_access(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    blueprint_version_id, skeleton_id = await _blueprint(app_engine, registry_engine)
    result = await prepare_case_a_reasoning(
        app_engine,
        TENANT,
        blueprint_version_id,
        {
            "entity_id": "mine-3",
            "time_window": {"start": "2026-08-29T00:00:00+08:00", "end": "2026-08-30T00:00:00+08:00"},
        },
        goal_skeleton_id=skeleton_id,
    )
    await cancel_reasoning_context(app_engine, TENANT, result.prepare_id)
    assert (await get_reasoning_context(app_engine, TENANT, result.prepare_id))["status"] == "cancelled"
    with pytest.raises(ReasoningPrepareError, match="cancelled"):
        await prepare_case_a_reasoning(
            app_engine,
            TENANT,
            blueprint_version_id,
            {
                "entity_id": "mine-3",
                "time_window": {"start": "2026-08-29T00:00:00+08:00", "end": "2026-08-30T00:00:00+08:00"},
            },
            goal_skeleton_id=skeleton_id,
        )
