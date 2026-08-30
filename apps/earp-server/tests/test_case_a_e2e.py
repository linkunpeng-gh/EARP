"""T13 PostgreSQL end-to-end acceptance for the deterministic Case A slice.

This is deliberately one integration flow, rather than a collection of unit
test helpers: every scenario uses the migrated PostgreSQL database and calls
the real fixture import, compiler, planning entry, Prepare, PlanFragment,
runtime, Evaluate, trace archive and audit-only replay boundaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.compiler import compile_case_a_causal_blueprint, seed_case_a_step_types
from earp_server.bmc.metamodel import import_case_a_snapshot_fixture
from earp_server.bmc.reasoning import (
    archive_case_a_reasoning,
    evaluate_case_a_reasoning,
    prepare_case_a_reasoning,
    replay_case_a_reasoning_trace,
)
from earp_server.bmc.reasoning.runtime import FixtureReasoningRuntimeAdapter, ReasoningInfrastructureError
from earp_server.infra.db import tenant_session
from earp_server.planner.blueprint_entry import BlueprintPlanningEntry, PlanningEntryRequest
from earp_server.planner.plan_fragment import KnowledgeQueryPlanFragmentHandler, PlanFragment

FIXTURE_DIR = Path(__file__).parent / "scenarios" / "mine_3_production_drop"
TENANT = "tenant-mine-demo"
ROLE = "r-case-a-e2e-planner"
CASE_A_TEXT = "为什么 3 号矿昨天产量下降？"
SNAPSHOT_ID = "cms-mine-3-production-drop-v1"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
def registry_engine(migrated: str, migration_url: str) -> AsyncEngine:
    return create_async_engine(migration_url, pool_pre_ping=True)


async def _bootstrap(app_engine: AsyncEngine, registry_engine: AsyncEngine) -> None:
    await import_case_a_snapshot_fixture(app_engine, registry_engine, FIXTURE_DIR)
    await seed_case_a_step_types(registry_engine)
    compiled = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID)
    assert compiled.blueprint_version_id is not None
    async with tenant_session(app_engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope) "
                "VALUES (:role_id, :tenant_id, 'Case A E2E planner', '{}', 'all') "
                "ON CONFLICT (role_id) DO NOTHING"
            ),
            {"role_id": ROLE, "tenant_id": TENANT},
        )


async def _start_case(
    app_engine: AsyncEngine, registry_engine: AsyncEngine, execution_tag: str
) -> tuple[dict[str, Any], Any, PlanFragment]:
    """Run the complete planning side with a distinct consumable Context."""
    await _bootstrap(app_engine, registry_engine)
    entry = await BlueprintPlanningEntry(app_engine, FIXTURE_DIR).resolve(
        PlanningEntryRequest(text=CASE_A_TEXT, tenant_id=TENANT, role_id=ROLE)
    )
    entry_payload = entry.as_dict()
    goal = entry_payload["goals"][0]
    prepared = await prepare_case_a_reasoning(
        app_engine,
        TENANT,
        entry_payload["blueprint"]["blueprint_version_id"],
        goal["bindings"],
        goal_skeleton_id=goal["goal_skeleton_id"],
        reasoning_mode="explainable",
        # A trace consumes its Context.  This explicit run identity gives each
        # acceptance scenario an independently pinned Context without changing
        # entity scope or any causal/business input.
        authz_scope={"scope_version": "case-a-e2e/v1", "allowed_entity_ids": ["mine-3"], "run": execution_tag},
    )
    fragment = await KnowledgeQueryPlanFragmentHandler(app_engine, FIXTURE_DIR).project(TENANT, prepared.prepare_id)
    return entry_payload, prepared, fragment


async def _execute_acquisitions(
    fragment: PlanFragment,
    adapter: FixtureReasoningRuntimeAdapter,
) -> list[dict[str, Any]]:
    """Execute acquisition Tasks in the Phase-1 order and retain terminal records."""
    records: list[dict[str, Any]] = []
    for task in fragment.tasks:
        if task.kind != "evidence_acquisition":
            continue
        payload = task.step.capability_call["input"]
        try:
            records.append(await adapter.acquire(payload))
        except ReasoningInfrastructureError as error:
            # This is the same StepRunner-facing terminal representation used
            # by the runtime contract: an infrastructure error is not a
            # business Observation, and therefore blocks Evaluate.
            records.append(
                {
                    "requirement_id": payload["requirement_id"],
                    "requirement_level": payload["requirement_level"],
                    "task_status": "failed",
                    "terminal_state": "infrastructure_failed",
                    "error": str(error),
                }
            )
    return records


async def _evaluate_and_archive(
    app_engine: AsyncEngine,
    entry: dict[str, Any],
    prepared: Any,
    fragment: PlanFragment,
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], Any, Any]:
    evaluate_task = next(task for task in fragment.tasks if task.kind == "reasoning_evaluate")
    runtime_gate = await FixtureReasoningRuntimeAdapter(FIXTURE_DIR).evaluate(
        evaluate_task.step.capability_call["input"], records
    )
    evaluation = await evaluate_case_a_reasoning(app_engine, TENANT, prepared.prepare_id, records)
    archive = await archive_case_a_reasoning(
        app_engine,
        TENANT,
        evaluation,
        records,
        lineage={
            "request": {"text": CASE_A_TEXT, "intent_fixture_hash": entry["intent_fixture"]["fixture_hash"]},
            "sub_goal": {"goal_instance_key": entry["goals"][0]["goal_instance_key"]},
            "blueprint": entry["blueprint"],
            "plan": fragment.as_dict(),
        },
    )
    replay = await replay_case_a_reasoning_trace(app_engine, TENANT, archive.trace_id)
    return runtime_gate, evaluation, replay


@pytest.mark.asyncio
async def test_case_a_happy_path_is_auditable_from_fixture_to_complete_ranking(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    entry, prepared, fragment = await _start_case(app_engine, registry_engine, "happy")
    assert entry["blueprint"]["source_snapshot_id"] == SNAPSHOT_ID
    assert len(fragment.tasks) == 7
    assert fragment.tasks[-2].depends_on == tuple(task.task_key for task in fragment.tasks[:5])
    assert fragment.tasks[-1].depends_on == (fragment.tasks[-2].task_key,)

    records = await _execute_acquisitions(fragment, FixtureReasoningRuntimeAdapter(FIXTURE_DIR))
    assert len(records) == 5
    assert all(record["task_status"] == "completed" for record in records)
    runtime_gate, evaluation, replay = await _evaluate_and_archive(app_engine, entry, prepared, fragment, records)

    assert runtime_gate["status"] == "READY"
    assert evaluation.status == "COMPLETE"
    assert evaluation.complete is True
    assert evaluation.ranking[0]["node_key"] == "haulage_cycle_time"
    assert evaluation.ranking[0]["evidence_chain"] == [
        "haulage_cycle_time",
        "effective_production_capacity",
        "production_output",
    ]
    assert replay.hashes_verified is True
    assert replay.as_dict()["replay_mode"] == "audit_only"
    assert replay.as_dict()["executable_replay"] is False
    assert replay.lineage["plan"]["prepare_id"] == prepared.prepare_id


@pytest.mark.asyncio
async def test_case_a_required_data_unavailable_is_completed_business_terminal_then_failed_reasoning(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    entry, prepared, fragment = await _start_case(app_engine, registry_engine, "required-data-unavailable")
    records = await _execute_acquisitions(
        fragment,
        FixtureReasoningRuntimeAdapter(FIXTURE_DIR, unavailable_provider_keys={"mock-production-metrics-v1"}),
    )
    required = next(
        record
        for record in records
        if record.get("observation", {}).get("requirement", {}).get("source_requirement_id")
        == "er-production-actual-and-baseline"
    )
    assert required["task_status"] == "completed"
    assert required["terminal_state"] == "business"
    assert required["observation"]["status"] == "DATA_UNAVAILABLE"

    runtime_gate, evaluation, replay = await _evaluate_and_archive(app_engine, entry, prepared, fragment, records)
    assert runtime_gate["status"] == "READY"
    assert evaluation.status == "FAILED"
    assert evaluation.http_status == 422
    assert evaluation.missing_required
    assert replay.hashes_verified is True
    assert replay.result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_case_a_infrastructure_failure_blocks_evaluate_and_is_audit_replayable(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    entry, prepared, fragment = await _start_case(app_engine, registry_engine, "infrastructure-failure")
    records = await _execute_acquisitions(
        fragment,
        FixtureReasoningRuntimeAdapter(FIXTURE_DIR, infrastructure_failure_provider_keys={"mock-equipment-health-v1"}),
    )
    failed = next(record for record in records if record["task_status"] == "failed")
    assert failed["terminal_state"] == "infrastructure_failed"
    assert "observation" not in failed

    runtime_gate, evaluation, replay = await _evaluate_and_archive(app_engine, entry, prepared, fragment, records)
    assert runtime_gate["status"] == "BLOCKED"
    assert evaluation.status == "BLOCKED"
    assert evaluation.http_status == 409
    assert evaluation.infrastructure_failures
    assert replay.hashes_verified is True
    # Database Trace status uses the existing failed bucket; the historical
    # result preserves the original BLOCKED semantic.
    assert replay.status == "failed"
    assert replay.result["status"] == "BLOCKED"
