"""T12 contract tests: immutable Case A trace, idempotency, and audit replay."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.reasoning import (
    EvaluationResult,
    ReasoningTraceError,
    archive_case_a_reasoning,
    evaluate_case_a_reasoning,
    replay_case_a_reasoning_trace,
)
from earp_server.infra.db import tenant_session
from tests.test_case_a_reasoning_evaluate import _acquisitions, _prepared

TENANT = "tenant-mine-demo"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
def registry_engine(migrated: str, migration_url: str) -> AsyncEngine:
    return create_async_engine(migration_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
async def case_data(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> tuple[str, list[dict], list[dict], EvaluationResult]:
    prepare_id, requirements = await _prepared(app_engine, registry_engine)
    records = await _acquisitions(requirements)
    evaluation = await evaluate_case_a_reasoning(app_engine, TENANT, prepare_id, records)
    return prepare_id, requirements, records, evaluation


@pytest.mark.asyncio
async def test_trace_archive_is_idempotent_and_replay_is_audit_only(
    app_engine: AsyncEngine, case_data: tuple[str, list[dict], list[dict], EvaluationResult]
) -> None:
    prepare_id, requirements, records, evaluation = case_data

    first = await archive_case_a_reasoning(
        app_engine,
        TENANT,
        evaluation,
        records,
        lineage={"request": {"request_id": "case-a-request-1"}, "plan": {"plan_key": "case-a-plan-v1"}},
    )
    second = await archive_case_a_reasoning(app_engine, TENANT, evaluation, records)
    assert first.reused is False
    assert second.reused is True
    assert second.trace_id == first.trace_id

    async with tenant_session(app_engine, TENANT) as session:
        count = await session.execute(
            text("SELECT count(*) FROM reasoning_traces WHERE tenant_id = :tenant AND prepare_id = :prepare_id"),
            {"tenant": TENANT, "prepare_id": prepare_id},
        )
        context = await session.execute(
            text("SELECT status FROM reasoning_contexts WHERE tenant_id = :tenant AND prepare_id = :prepare_id"),
            {"tenant": TENANT, "prepare_id": prepare_id},
        )
        audit = await session.execute(
            text(
                "SELECT detail FROM audit_logs WHERE tenant_id = :tenant "
                "AND event_type = 'earp.reasoning.trace.archived' AND entity_id = :trace_id"
            ),
            {"tenant": TENANT, "trace_id": first.trace_id},
        )
        assert count.scalar_one() == 1
        assert context.scalar_one() == "consumed"
        assert audit.first() is not None

    replay = await replay_case_a_reasoning_trace(app_engine, TENANT, first.trace_id)
    payload = replay.as_dict()
    assert replay.hashes_verified is True
    assert payload["replay_mode"] == "audit_only"
    assert payload["executable_replay"] is False
    assert payload["pinned_inputs"]["causal_snapshot"]["snapshot_id"] == evaluation.model_snapshot_id
    assert payload["lineage"]["request"]["request_id"] == "case-a-request-1"
    assert len(replay.observations) == len(requirements)
    assert replay.result["result_hash"] == evaluation.result_hash


@pytest.mark.asyncio
async def test_trace_rejects_different_input_for_consumed_prepare(
    app_engine: AsyncEngine, case_data: tuple[str, list[dict], list[dict], EvaluationResult]
) -> None:
    prepare_id, _, records, evaluation = case_data
    await archive_case_a_reasoning(app_engine, TENANT, evaluation, records)

    changed = replace(evaluation, evaluation_input_hash="f" * 64)
    with pytest.raises(ReasoningTraceError, match="different evaluation input"):
        await archive_case_a_reasoning(app_engine, TENANT, changed, records)


@pytest.mark.asyncio
async def test_trace_replay_detects_tampered_archived_result(
    app_engine: AsyncEngine, case_data: tuple[str, list[dict], list[dict], EvaluationResult]
) -> None:
    prepare_id, _, records, evaluation = case_data
    archived = await archive_case_a_reasoning(app_engine, TENANT, evaluation, records)
    async with tenant_session(app_engine, TENANT) as session:
        await session.execute(
            text(
                "UPDATE reasoning_traces SET result_snapshot = jsonb_set(result_snapshot, '{status}', '"
                '"PARTIAL"\'::jsonb) WHERE tenant_id = :tenant AND trace_id = :trace_id'
            ),
            {"tenant": TENANT, "trace_id": archived.trace_id},
        )
    with pytest.raises(ReasoningTraceError, match="result hash mismatch"):
        await replay_case_a_reasoning_trace(app_engine, TENANT, archived.trace_id)
