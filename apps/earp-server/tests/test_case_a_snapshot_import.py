"""T05: hash-locked Case A fixture import, validation, and test-only publication."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.metamodel import FixtureImportError, import_case_a_snapshot_fixture
from earp_server.infra.db import tenant_session

FIXTURE_DIR = Path(__file__).parent / "scenarios" / "mine_3_production_drop"
TENANT = "tenant-mine-demo"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
def registry_engine(migrated: str, migration_url: str) -> AsyncEngine:
    """The global registry is intentionally not writable by the tenant app role."""
    return create_async_engine(migration_url, pool_pre_ping=True)


def _refresh_manifest(fixture_dir: Path) -> None:
    manifest_path = fixture_dir / "fixture_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in manifest["files"]:
        manifest["files"][name] = hashlib.sha256((fixture_dir / name).read_bytes()).hexdigest()
    package = "".join(f"{name}:{manifest['files'][name]}\n" for name in sorted(manifest["files"]))
    manifest["package_hash"] = hashlib.sha256(package.encode("utf-8")).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def test_imports_validated_snapshot_and_test_only_publication(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    result = await import_case_a_snapshot_fixture(app_engine, registry_engine, FIXTURE_DIR)
    assert result.tenant_id == TENANT
    assert result.snapshot_id == "cms-mine-3-production-drop-v1"
    assert result.fixture_release_only is True

    async with tenant_session(app_engine, TENANT) as session:
        model = (
            (
                await session.execute(
                    text(
                        "SELECT status, published_snapshot_id FROM causal_model_versions "
                        "WHERE model_version_id = :version_id"
                    ),
                    {"version_id": result.model_version_id},
                )
            )
            .mappings()
            .one()
        )
        assert dict(model) == {"status": "testing", "published_snapshot_id": result.snapshot_id}

        counts = {
            table: int((await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())
            for table in ("data_domains", "entity_types", "relation_types", "entities", "facts")
        }
        assert counts == {"data_domains": 2, "entity_types": 3, "relation_types": 2, "entities": 3, "facts": 2}
        snapshot = (
            (
                await session.execute(
                    text(
                        "SELECT content_hash, requirements_json FROM causal_model_snapshots "
                        "WHERE snapshot_id = :snapshot_id"
                    ),
                    {"snapshot_id": result.snapshot_id},
                )
            )
            .mappings()
            .one()
        )
        assert snapshot["content_hash"] == result.snapshot_hash
        assert len(snapshot["requirements_json"]) == 5
        validation = (
            (
                await session.execute(
                    text("SELECT result, detail FROM causal_snapshot_validation_runs WHERE run_id = :run_id"),
                    {"run_id": result.validation_run_id},
                )
            )
            .mappings()
            .one()
        )
        assert validation["result"] == "passed"
        assert validation["detail"]["fixture_release_only"] is True
        assert validation["detail"]["resolved_bindings"]["er-haulage-cycle-observation"] == "haulage-system-mine-3"

    async with registry_engine.connect() as session:
        algorithm = (
            (
                await session.execute(
                    text(
                        "SELECT implementation_hash, algorithm_config_hash, algorithm_config_json, status "
                        "FROM reasoning_algorithm_versions WHERE algorithm_version_id = :version_id"
                    ),
                    {"version_id": result.algorithm_version_id},
                )
            )
            .mappings()
            .one()
        )
    assert algorithm["implementation_hash"] is None
    assert algorithm["algorithm_config_hash"] == result.algorithm_config_hash
    assert algorithm["algorithm_config_json"]["implementation_artifact"]["status"] == "not_built"
    assert algorithm["status"] == "beta"


async def test_reimport_is_idempotent_and_rls_hides_fixture_from_other_tenant(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    first = await import_case_a_snapshot_fixture(app_engine, registry_engine, FIXTURE_DIR)
    second = await import_case_a_snapshot_fixture(app_engine, registry_engine, FIXTURE_DIR)
    assert first == second
    async with tenant_session(app_engine, TENANT) as session:
        assert int((await session.execute(text("SELECT count(*) FROM causal_model_snapshots"))).scalar_one()) == 1
    async with tenant_session(app_engine, "t05-other-tenant") as session:
        assert int((await session.execute(text("SELECT count(*) FROM causal_model_snapshots"))).scalar_one()) == 0
        assert int((await session.execute(text("SELECT count(*) FROM entities"))).scalar_one()) == 0


async def test_rejects_raw_hash_mismatch_without_rehashing(
    app_engine: AsyncEngine, registry_engine: AsyncEngine, tmp_path: Path
) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, fixture)
    model_path = fixture / "causal_model_snapshot.json"
    model_path.write_text(model_path.read_text(encoding="utf-8").replace("生产产量", "篡改产量", 1), encoding="utf-8")
    with pytest.raises(FixtureImportError, match="raw-byte hash mismatch"):
        await import_case_a_snapshot_fixture(app_engine, registry_engine, fixture)


async def test_rejects_dangling_graph_and_unready_ontology_before_writes(
    app_engine: AsyncEngine, registry_engine: AsyncEngine, tmp_path: Path
) -> None:
    graph_fixture = tmp_path / "bad-graph"
    shutil.copytree(FIXTURE_DIR, graph_fixture)
    model_path = graph_fixture / "causal_model_snapshot.json"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    model["snapshot"]["edges"][0]["target_node_key"] = "missing-node"
    # Re-signing the package proves semantic validation, rather than manifest
    # validation, rejects an incompatible graph.  Authors—not T05—own this step.
    model["model_content_hash"] = hashlib.sha256(
        json.dumps(model["snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _refresh_manifest(graph_fixture)
    with pytest.raises(FixtureImportError, match="dangling"):
        await import_case_a_snapshot_fixture(app_engine, registry_engine, graph_fixture)

    ontology_fixture = tmp_path / "bad-ontology"
    shutil.copytree(FIXTURE_DIR, ontology_fixture)
    ontology_path = ontology_fixture / "ontology_fixture.json"
    ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
    ontology["facts"][0]["object_entity_id"] = "missing-abox-entity"
    ontology_path.write_text(json.dumps(ontology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _refresh_manifest(ontology_fixture)
    with pytest.raises(FixtureImportError, match="dangling"):
        await import_case_a_snapshot_fixture(app_engine, registry_engine, ontology_fixture)
