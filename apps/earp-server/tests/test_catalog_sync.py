"""Pull synchronization contract: verify-before-write, cursor and run evidence."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.catalog.hashing import content_hash
from earp_server.catalog.source import SourceObject
from earp_server.catalog.sync import pull_once
from earp_server.infra.db import tenant_session


class PullAdapter:
    source_system = "test-ontology"

    def __init__(self, objects: list[SourceObject], cursor: str = "cursor-2") -> None:
        self.objects = objects
        self.cursor = cursor

    async def fetch_exact(self, kind: str, stable_id: str, version: str) -> SourceObject:
        return self.objects[0]

    async def list_since(self, cursor: str | None) -> tuple[list[SourceObject], str | None]:
        assert cursor in {None, "cursor-2"}
        return self.objects, self.cursor

    def source_identity(self, source: SourceObject) -> str:
        return f"ontology/{source.stable_id}/{source.version}"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def _source(*, bad_hash: bool = False) -> SourceObject:
    stable_id = f"coal.mine-{uuid.uuid4().hex[:10]}"
    payload = {
        "kind": "entity_type",
        "stable_id": stable_id,
        "version": "1.0.0",
        "entity_type_id": stable_id,
        "name": "Mine",
        "kind_type": "object",
        "data_domain_id": "production",
        "semantic_schema_version": "catalog-entity/v1",
    }
    return SourceObject(
        kind="entity_type",
        stable_id=stable_id,
        version="1.0.0",
        canonical_input=payload,
        content_hash="0" * 64 if bad_hash else content_hash(payload, schema_version="catalog-entity/v1"),
        schema_version="catalog-entity/v1",
        status="active",
        data_domain_id="production",
    )


async def test_pull_verifies_refs_and_advances_cursor_atomically(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-sync-{uuid.uuid4().hex[:10]}"
    source = _source()
    adapter = PullAdapter([source])
    result = await pull_once(app_engine, tenant_id, adapter)
    assert result.status == "succeeded"
    assert result.seen_count == result.updated_count == 1

    repeated = await pull_once(app_engine, tenant_id, adapter)
    assert repeated.status == "succeeded"
    async with tenant_session(app_engine, tenant_id) as session:
        cursor = await session.execute(
            text("SELECT cursor FROM catalog_sync_cursors WHERE source_system=:source"),
            {"source": adapter.source_system},
        )
        assert cursor.scalar_one() == "cursor-2"
        runs = await session.execute(
            text("SELECT count(*) FROM catalog_sync_runs WHERE source_system=:source AND status='succeeded'"),
            {"source": adapter.source_system},
        )
        assert runs.scalar_one() == 2


async def test_pull_rejects_bad_hash_without_creating_a_ref(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-sync-{uuid.uuid4().hex[:10]}"
    adapter = PullAdapter([_source(bad_hash=True)])
    result = await pull_once(app_engine, tenant_id, adapter)
    assert result.status == "failed"
    async with tenant_session(app_engine, tenant_id) as session:
        refs = await session.execute(text("SELECT count(*) FROM catalog_refs"))
        assert refs.scalar_one() == 0
        runs = await session.execute(
            text("SELECT status,error_code FROM catalog_sync_runs WHERE source_system=:source"),
            {"source": adapter.source_system},
        )
        assert runs.one() == ("failed", "HASH_OR_SCHEMA_REJECTED")


async def test_pull_commit_conflict_records_failed_run_without_partial_writes(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-sync-conflict-{uuid.uuid4().hex[:10]}"
    original = _source()
    assert (await pull_once(app_engine, tenant_id, PullAdapter([original]))).status == "succeeded"
    changed_payload = {**original.canonical_input, "name": "Changed by source"}
    changed = replace(
        original,
        canonical_input=changed_payload,
        content_hash=content_hash(changed_payload, schema_version=original.schema_version),
    )
    result = await pull_once(app_engine, tenant_id, PullAdapter([changed]))
    assert result.status == "failed"
    async with tenant_session(app_engine, tenant_id) as session:
        refs = await session.execute(
            text("SELECT count(*),max(content_hash) FROM catalog_refs WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
        assert refs.one() == (1, original.content_hash)
        runs = await session.execute(
            text(
                "SELECT status,error_code FROM catalog_sync_runs "
                "WHERE tenant_id=:tenant ORDER BY started_at DESC LIMIT 1"
            ),
            {"tenant": tenant_id},
        )
        assert runs.one() == ("failed", "HASH_OR_SCHEMA_REJECTED")
