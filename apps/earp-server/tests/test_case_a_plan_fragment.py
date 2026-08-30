"""T09 contract tests for Case A Capability Resolution and PlanFragment projection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.compiler import compile_case_a_causal_blueprint, seed_case_a_step_types
from earp_server.bmc.metamodel import import_case_a_snapshot_fixture
from earp_server.bmc.reasoning import prepare_case_a_reasoning
from earp_server.capability.resolution import FixtureCapabilityResolver
from earp_server.infra.db import tenant_session
from earp_server.planner.plan_fragment import (
    KnowledgeQueryPlanFragmentHandler,
    PlanFragmentError,
    build_case_a_plan_fragment,
    validate_case_a_plan_fragment,
)

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


def _prepared_requirements() -> list[dict[str, object]]:
    snapshot = json.loads((FIXTURE_DIR / "causal_model_snapshot.json").read_text(encoding="utf-8"))["snapshot"]
    target_by_source_id = {
        "er-production-actual-and-baseline": ("mine-3", "mine"),
        "er-critical-equipment-availability": ("critical-equipment-group-mine-3", "equipment_group"),
        "er-haulage-cycle-observation": ("haulage-system-mine-3", "haulage_system"),
        "er-haulage-queue-observation": ("haulage-system-mine-3", "haulage_system"),
        "er-ore-quality-observation": ("mine-3", "mine"),
    }
    return [
        {
            "requirement_id": f"prepared-{requirement['requirement_id']}",
            "source_requirement_id": requirement["requirement_id"],
            "requirement_key": requirement["requirement_key"],
            "node_key": requirement["node_key"],
            "requirement_level": requirement["requirement_level"],
            "capability_contract_ref": requirement["capability_contract_ref"],
            "unit": requirement["unit"],
            "aggregation": requirement["aggregation"],
            "target_entity_id": target_by_source_id[requirement["requirement_id"]][0],
            "target_entity_type": target_by_source_id[requirement["requirement_id"]][1],
            "time_window": TIME_WINDOW,
        }
        for requirement in snapshot["evidence_requirements"]
    ]


def _fragment(*, unavailable_provider_keys: set[str] | None = None):
    return build_case_a_plan_fragment(
        prepare_id="prepare-case-a-contract",
        blueprint_version_id="blueprint-version-case-a",
        knowledge_query_step_id="step-knowledge-query",
        output_step_id="step-output",
        output_contract_ref="output-cause-ranking",
        requirements=_prepared_requirements(),
        resolver=FixtureCapabilityResolver(FIXTURE_DIR, unavailable_provider_keys=unavailable_provider_keys),
    )


def test_fragment_has_five_acquisitions_then_evaluate_then_output_and_preserves_prepare_targets() -> None:
    fragment = _fragment()
    assert [task.kind for task in fragment.tasks] == [
        "evidence_acquisition",
        "evidence_acquisition",
        "evidence_acquisition",
        "evidence_acquisition",
        "evidence_acquisition",
        "reasoning_evaluate",
        "output",
    ]
    acquisitions = fragment.tasks[:5]
    evaluate, output = fragment.tasks[5:]
    assert all(task.step.capability_call["adapter_type"] == "reasoning.acquire" for task in acquisitions)
    assert all(task.step.capability_call["input"]["prepare_id"] == fragment.prepare_id for task in acquisitions)
    assert {task.step.capability_call["input"]["target"]["entity_id"] for task in acquisitions} == {
        "mine-3",
        "critical-equipment-group-mine-3",
        "haulage-system-mine-3",
    }
    assert evaluate.depends_on == tuple(task.task_key for task in acquisitions)
    assert evaluate.step.capability_call["adapter_type"] == "reasoning.evaluate"
    assert evaluate.step.capability_call["input"]["planned_requirement_ids"] == [
        task.step.capability_call["input"]["requirement_id"] for task in acquisitions
    ]
    assert output.depends_on == (evaluate.task_key,)
    # Seven tasks are valid because the graph's longest path is acquisition ->
    # evaluate -> output (depth 3), not the legacy linear item count.
    validate_case_a_plan_fragment(fragment)
    with pytest.raises(PlanFragmentError, match="graph depth 3 exceeds max 2"):
        validate_case_a_plan_fragment(fragment, max_graph_depth=2)


def test_required_provider_unavailable_fails_closed_and_optional_remains_a_terminal_task() -> None:
    with pytest.raises(PlanFragmentError, match="required evidence requirement"):
        _fragment(unavailable_provider_keys={"mock-production-metrics-v1"})

    fragment = _fragment(unavailable_provider_keys={"mock-quality-metrics-v1"})
    optional = next(
        task
        for task in fragment.tasks
        if task.kind == "evidence_acquisition"
        and task.step.capability_call["input"]["requirement_key"] == "ore_quality_observation"
    )
    assert optional.step.capability_call["input"]["provider_key"] is None
    assert optional.step.capability_call["input"]["provider_resolution_status"] == "unbound_optional"
    assert optional.task_key in fragment.tasks[-2].depends_on


async def _prepared_context(app_engine: AsyncEngine, registry_engine: AsyncEngine) -> str:
    await import_case_a_snapshot_fixture(app_engine, registry_engine, FIXTURE_DIR)
    await seed_case_a_step_types(registry_engine)
    compiled = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID)
    assert compiled.blueprint_version_id is not None
    async with tenant_session(app_engine, TENANT) as session:
        skeleton_id = (
            await session.execute(
                text(
                    "SELECT goal_skeleton_id FROM blueprint_goal_skeletons "
                    "WHERE tenant_id = :tenant_id AND blueprint_version_id = :version_id AND objective = 'diagnose'"
                ),
                {"tenant_id": TENANT, "version_id": compiled.blueprint_version_id},
            )
        ).scalar_one()
    prepared = await prepare_case_a_reasoning(
        app_engine,
        TENANT,
        compiled.blueprint_version_id,
        {"entity_id": "mine-3", "time_window": TIME_WINDOW},
        goal_skeleton_id=skeleton_id,
    )
    return prepared.prepare_id


async def test_handler_projects_only_the_persisted_prepared_context(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    prepare_id = await _prepared_context(app_engine, registry_engine)
    fragment = await KnowledgeQueryPlanFragmentHandler(app_engine, FIXTURE_DIR).project(TENANT, prepare_id)
    assert fragment.prepare_id == prepare_id
    assert len(fragment.tasks) == 7
    assert fragment.tasks[-2].depends_on == tuple(task.task_key for task in fragment.tasks[:5])
    assert fragment.tasks[-1].depends_on == (fragment.tasks[-2].task_key,)
    assert all(
        task.step.capability_call["input"]["blueprint"]["step_id"] for task in fragment.tasks if task.kind != "output"
    )
    with pytest.raises(PlanFragmentError, match="prepared ReasoningContext"):
        await KnowledgeQueryPlanFragmentHandler(app_engine, FIXTURE_DIR).project(TENANT, "missing-prepare")
