"""T06 contract tests for deterministic Case A Causal Blueprint compilation."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.compiler import (
    CausalCompileError,
    compile_case_a_causal_blueprint,
    seed_case_a_step_types,
)
from earp_server.bmc.metamodel import import_case_a_snapshot_fixture
from earp_server.infra.db import tenant_session

FIXTURE_DIR = Path(__file__).parent / "scenarios" / "mine_3_production_drop"
TENANT = "tenant-mine-demo"
SNAPSHOT_ID = "cms-mine-3-production-drop-v1"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
def registry_engine(migrated: str, migration_url: str) -> AsyncEngine:
    return create_async_engine(migration_url, pool_pre_ping=True)


async def _ready(app_engine: AsyncEngine, registry_engine: AsyncEngine) -> None:
    await import_case_a_snapshot_fixture(app_engine, registry_engine, FIXTURE_DIR)
    await seed_case_a_step_types(registry_engine)


async def test_dry_run_records_canonical_draft_without_blueprint_children(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    await _ready(app_engine, registry_engine)
    async with tenant_session(app_engine, TENANT) as session:
        before = int((await session.execute(text("SELECT count(*) FROM planning_blueprints"))).scalar_one())
    result = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID, dry_run=True)
    assert result.status == "success"
    assert result.dry_run is True
    assert result.blueprint_version_id is None
    assert result.canonical_blueprint_hash is not None

    async with tenant_session(app_engine, TENANT) as session:
        record = (
            (
                await session.execute(
                    text(
                        "SELECT status, validation_result FROM blueprint_compile_records WHERE compile_id = :compile_id"
                    ),
                    {"compile_id": result.compile_id},
                )
            )
            .mappings()
            .one()
        )
        assert record["status"] == "success"
        assert record["validation_result"]["dry_run"] is True
        assert record["validation_result"]["canonical_blueprint_hash"] == result.canonical_blueprint_hash
        assert int((await session.execute(text("SELECT count(*) FROM planning_blueprints"))).scalar_one()) == before


async def test_compiler_pins_source_and_handlers_without_dynamic_evidence_expansion(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    await _ready(app_engine, registry_engine)
    first = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID)
    replay = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID)
    assert replay == first
    assert first.blueprint_version_id is not None

    async with tenant_session(app_engine, TENANT) as session:
        version = (
            (
                await session.execute(
                    text(
                        "SELECT status, compile_record_id, compiler_version, source_fingerprint "
                        "FROM planning_blueprint_versions WHERE blueprint_version_id = :version_id"
                    ),
                    {"version_id": first.blueprint_version_id},
                )
            )
            .mappings()
            .one()
        )
        assert version["status"] == "compiled"
        assert version["compile_record_id"] == first.compile_id
        assert version["source_fingerprint"] == first.canonical_blueprint_hash
        source = (
            (
                await session.execute(
                    text(
                        "SELECT model_type, model_id, model_version, source_snapshot_id, source_content_hash "
                        "FROM blueprint_source_models WHERE blueprint_version_id = :version_id"
                    ),
                    {"version_id": first.blueprint_version_id},
                )
            )
            .mappings()
            .one()
        )
        assert dict(source) == {
            "model_type": "causal",
            "model_id": "causal-production-drop-mine",
            "model_version": "1.0.1-fixture",
            "source_snapshot_id": SNAPSHOT_ID,
            "source_content_hash": "3f7418d45f8c9ba92fd4a9a701f76127825383018cbcd3a02a7ea1c349f8aa16",
        }
        steps = (
            (
                await session.execute(
                    text(
                        "SELECT step_seq, step_type, step_type_version_id, params FROM blueprint_steps "
                        "WHERE blueprint_version_id = :version_id ORDER BY step_seq"
                    ),
                    {"version_id": first.blueprint_version_id},
                )
            )
            .mappings()
            .all()
        )
        assert [row["step_type"] for row in steps] == ["knowledge_query", "output"]
        assert [row["step_type_version_id"] for row in steps] == ["stv-knowledge-query-v1", "stv-output-v1"]
        assert all("capability" not in row["params"] for row in steps)
        assert (
            int(
                (
                    await session.execute(
                        text("SELECT count(*) FROM blueprint_step_deps WHERE blueprint_version_id = :version_id"),
                        {"version_id": first.blueprint_version_id},
                    )
                ).scalar_one()
            )
            == 1
        )
        goal = (
            (
                await session.execute(
                    text(
                        "SELECT objective, required_bindings, output_contract_ref FROM blueprint_goal_skeletons "
                        "WHERE blueprint_version_id = :version_id"
                    ),
                    {"version_id": first.blueprint_version_id},
                )
            )
            .mappings()
            .one()
        )
        assert goal["objective"] == "diagnose"
        assert goal["required_bindings"] == ["entity_id", "time_window"]
        assert goal["output_contract_ref"] is not None


async def test_compile_failure_is_auditable_and_creates_no_blueprint_version(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    await _ready(app_engine, registry_engine)
    before: int
    async with tenant_session(app_engine, TENANT) as session:
        before = int((await session.execute(text("SELECT count(*) FROM planning_blueprint_versions"))).scalar_one())
    with pytest.raises(CausalCompileError, match="not found"):
        await compile_case_a_causal_blueprint(app_engine, TENANT, "missing-snapshot")
    async with tenant_session(app_engine, TENANT) as session:
        failed = (
            (
                await session.execute(
                    text(
                        "SELECT status, error_log FROM blueprint_compile_records "
                        "WHERE input_snapshot ->> 'snapshot_id' = 'missing-snapshot'"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert failed["status"] == "failed"
        assert "not found" in failed["error_log"][0]["message"]
        assert (
            int((await session.execute(text("SELECT count(*) FROM planning_blueprint_versions"))).scalar_one())
            == before
        )


async def test_new_compile_supersedes_old_current_version_exactly_once(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    await _ready(app_engine, registry_engine)
    baseline = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID)
    replacement = await compile_case_a_causal_blueprint(
        app_engine, TENANT, SNAPSHOT_ID, compiler_config={"fixture_variant": "v2"}
    )
    assert replacement.blueprint_version_id != baseline.blueprint_version_id
    async with tenant_session(app_engine, TENANT) as session:
        statuses = (
            (
                await session.execute(
                    text(
                        "SELECT status FROM planning_blueprint_versions "
                        "WHERE blueprint_id = :blueprint_id ORDER BY version"
                    ),
                    {"blueprint_id": baseline.blueprint_id},
                )
            )
            .scalars()
            .all()
        )
        assert statuses.count("compiled") == 1
        assert statuses.count("superseded") >= 1


async def test_replaying_a_prior_compile_restores_its_version_as_current(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    await _ready(app_engine, registry_engine)
    baseline = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID)
    await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID, compiler_config={"fixture_variant": "v3"})

    replay = await compile_case_a_causal_blueprint(app_engine, TENANT, SNAPSHOT_ID)
    assert replay == baseline
    async with tenant_session(app_engine, TENANT) as session:
        current = (
            await session.execute(
                text(
                    "SELECT blueprint_version_id FROM planning_blueprint_versions "
                    "WHERE tenant_id = :tenant_id AND blueprint_id = :blueprint_id AND status = 'compiled'"
                ),
                {"tenant_id": TENANT, "blueprint_id": baseline.blueprint_id},
            )
        ).scalar_one()
    assert current == baseline.blueprint_version_id
