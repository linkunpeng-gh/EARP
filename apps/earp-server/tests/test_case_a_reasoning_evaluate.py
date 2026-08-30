"""T11 contract tests: deterministic Case A sign propagation from pinned inputs."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.compiler import compile_case_a_causal_blueprint, seed_case_a_step_types
from earp_server.bmc.metamodel import import_case_a_snapshot_fixture
from earp_server.bmc.reasoning import evaluate_case_a_reasoning, prepare_case_a_reasoning
from earp_server.bmc.reasoning.runtime import ACQUIRE_CONTRACT, FixtureReasoningRuntimeAdapter
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


async def _prepared(app_engine: AsyncEngine, registry_engine: AsyncEngine) -> tuple[str, list[dict]]:
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
    return prepared.prepare_id, list(prepared.requirements)


async def _acquisitions(requirements: list[dict], *, unavailable: set[str] | None = None) -> list[dict]:
    adapter = FixtureReasoningRuntimeAdapter(FIXTURE_DIR, unavailable_provider_keys=unavailable or set())
    provider_by_contract = {
        "production_metric_query": "mock-production-metrics-v1",
        "equipment_health_query": "mock-equipment-health-v1",
        "haulage_operation_query": "mock-haulage-operations-v1",
        "quality_metric_query": "mock-quality-metrics-v1",
    }
    results = []
    for requirement in requirements:
        provider_key = provider_by_contract[requirement["capability_contract_ref"]]
        results.append(
            await adapter.acquire(
                {
                    "contract": ACQUIRE_CONTRACT,
                    "prepare_id": requirement["requirement_id"].split("-")[1],
                    "task_id": f"acquire-{requirement['node_key']}",
                    "requirement_id": requirement["requirement_id"],
                    "source_requirement_id": requirement["source_requirement_id"],
                    "requirement_key": requirement["requirement_key"],
                    "node_key": requirement["node_key"],
                    "requirement_level": requirement["requirement_level"],
                    "provider_key": provider_key,
                    "provider_resolution_status": "bound",
                    "target": {
                        "entity_id": requirement["target_entity_id"],
                        "entity_type": requirement["target_entity_type"],
                    },
                    "time_window": requirement["time_window"],
                    "measurement": {"unit": requirement["unit"], "aggregation": requirement["aggregation"]},
                }
            )
        )
    return results


async def test_pinned_fixture_evaluate_returns_the_two_golden_candidates(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    prepare_id, requirements = await _prepared(app_engine, registry_engine)
    result = await evaluate_case_a_reasoning(app_engine, TENANT, prepare_id, await _acquisitions(requirements))

    assert result.status == "COMPLETE"
    assert result.complete is True
    assert result.model_snapshot_id == SNAPSHOT_ID
    assert result.algorithm_config_hash == "367bbd12231cf347ba0988ec2111396c55ff5d3b31cc358df5d8e05bdfd644e2"
    assert result.algorithm_artifact["status"] == "not_built"
    assert [(item["node_key"], item["path_score"]) for item in result.ranking[:2]] == [
        ("haulage_cycle_time", 0.796005),
        ("haulage_queue_time", 0.70756),
    ]
    assert result.ranking[0]["evidence_chain"] == [
        "haulage_cycle_time",
        "effective_production_capacity",
        "production_output",
    ]
    assert result.ranking[0]["evidence_requirement_ids"] == [
        "er-haulage-cycle-observation",
        "er-production-actual-and-baseline",
    ]
    assert result.evaluation_input_hash and result.result_hash


async def test_required_optional_and_infrastructure_terminal_semantics(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    prepare_id, requirements = await _prepared(app_engine, registry_engine)
    required = next(
        item for item in requirements if item["source_requirement_id"] == "er-production-actual-and-baseline"
    )
    required_result = await evaluate_case_a_reasoning(
        app_engine,
        TENANT,
        prepare_id,
        await _acquisitions(requirements, unavailable={"mock-production-metrics-v1"}),
    )
    assert required_result.status == "FAILED"
    assert required_result.http_status == 422
    assert required["requirement_id"] in required_result.missing_required

    prepare_id, requirements = await _prepared(app_engine, registry_engine)
    optional = next(item for item in requirements if item["requirement_level"] == "optional")
    partial = await evaluate_case_a_reasoning(
        app_engine,
        TENANT,
        prepare_id,
        await _acquisitions(requirements, unavailable={"mock-haulage-operations-v1"}),
    )
    # Haulage provider backs one required and one optional requirement, so this
    # fixture variation proves required always wins over optional partiality.
    assert partial.status == "FAILED"

    prepare_id, requirements = await _prepared(app_engine, registry_engine)
    results = await _acquisitions(requirements)
    results[0] = {
        "requirement_id": requirements[0]["requirement_id"],
        "requirement_level": requirements[0]["requirement_level"],
        "task_status": "failed",
        "terminal_state": "infrastructure_failed",
        "error": "connector timeout",
    }
    blocked = await evaluate_case_a_reasoning(app_engine, TENANT, prepare_id, results)
    assert blocked.status == "BLOCKED"
    assert blocked.http_status == 409
    assert blocked.infrastructure_failures[0]["error"] == "connector timeout"
    assert optional["requirement_id"] not in blocked.missing_optional


async def test_optional_data_unavailable_is_partial_and_snapshot_hash_is_pinned(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    prepare_id, requirements = await _prepared(app_engine, registry_engine)
    optional = next(item for item in requirements if item["source_requirement_id"] == "er-ore-quality-observation")
    results = await _acquisitions(requirements)
    index = next(
        index for index, item in enumerate(requirements) if item["requirement_id"] == optional["requirement_id"]
    )
    results[index]["observation"]["status"] = "DATA_UNAVAILABLE"
    partial = await evaluate_case_a_reasoning(app_engine, TENANT, prepare_id, results)
    assert partial.status == "PARTIAL"
    assert partial.complete is False
    assert partial.missing_optional == (optional["requirement_id"],)
    # The fixture is immutable at the database boundary.  Evaluating the same
    # archived observations in a different transport order retains the exact
    # pinned Snapshot/config identity and canonical input/result hashes.
    complete_records = await _acquisitions(requirements)
    first = await evaluate_case_a_reasoning(app_engine, TENANT, prepare_id, complete_records)
    second = await evaluate_case_a_reasoning(app_engine, TENANT, prepare_id, list(reversed(complete_records)))
    assert first.model_content_hash == second.model_content_hash
    assert first.algorithm_config_hash == second.algorithm_config_hash
    assert first.result_hash == second.result_hash
