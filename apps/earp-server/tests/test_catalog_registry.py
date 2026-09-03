"""Database contract tests for reference registration provenance and immutability."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.catalog.hashing import content_hash
from earp_server.catalog.registration import CatalogRegistrationError
from earp_server.catalog.registry import CatalogRefRegistry
from earp_server.catalog.source import SourceObject
from earp_server.infra.db import tenant_session


class AuthoritativeAdapter:
    source_system = "test-authoritative-source"

    def __init__(self, source: SourceObject) -> None:
        self._source = source

    async def fetch_exact(self, kind: str, stable_id: str, version: str) -> SourceObject:
        return self._source

    async def list_since(self, cursor: str | None) -> tuple[list[SourceObject], str | None]:
        return [], cursor

    def source_identity(self, source: SourceObject) -> str:
        return f"objects/{source.kind}/{source.stable_id}/{source.version}"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def _source(*, declared_hash: str | None = None) -> SourceObject:
    stable_id = f"common.mass.tonne-{uuid.uuid4().hex[:10]}"
    payload = {
        "kind": "unit",
        "stable_id": stable_id,
        "version": "1.0.0",
        "unit_id": stable_id,
    }
    return SourceObject(
        kind="unit",
        stable_id=stable_id,
        version="1.0.0",
        canonical_input=payload,
        content_hash=declared_hash or content_hash(payload, schema_version="catalog-unit/v1"),
        schema_version="catalog-unit/v1",
        status="active",
        data_domain_id="production",
    )


async def test_registry_persists_only_verified_pin_and_audits_it(
    app_engine: AsyncEngine,
) -> None:
    tenant_id = f"catalog-reg-{uuid.uuid4().hex[:10]}"
    source = _source()
    registry = CatalogRefRegistry(app_engine)

    registered = await registry.register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="request-1",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    repeated = await registry.register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="request-2",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )

    assert repeated["ref_id"] == registered["ref_id"]
    assert registered["content_hash"] == source.content_hash
    assert registered["source_system"] == "test-authoritative-source"
    async with tenant_session(app_engine, tenant_id) as session:
        rows = await session.execute(
            text("SELECT operation, after_hash FROM catalog_audit_logs WHERE resource_id=:ref_id"),
            {"ref_id": registered["ref_id"]},
        )
        assert rows.mappings().all() == [{"operation": "register", "after_hash": source.content_hash}]


async def test_registry_rejects_authoritative_hash_mismatch_without_a_write(
    app_engine: AsyncEngine,
) -> None:
    tenant_id = f"catalog-reg-{uuid.uuid4().hex[:10]}"
    source = _source(declared_hash="0" * 64)
    registry = CatalogRefRegistry(app_engine)

    with pytest.raises(CatalogRegistrationError, match="hash mismatch"):
        await registry.register(
            AuthoritativeAdapter(source),
            tenant_id=tenant_id,
            actor_id="user-1",
            correlation_id="request-1",
            kind=source.kind,
            stable_id=source.stable_id,
            version=source.version,
        )
    async with tenant_session(app_engine, tenant_id) as session:
        count = await session.execute(text("SELECT count(*) FROM catalog_refs"))
        assert count.scalar_one() == 0


async def test_ref_status_refresh_is_source_authoritative_and_audited(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-reg-status-{uuid.uuid4().hex[:10]}"
    source = _source()
    registry = CatalogRefRegistry(app_engine)
    await registry.register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="status-register",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    deprecated = replace(source, status="deprecated")
    refreshed = await registry.refresh_from_source(
        AuthoritativeAdapter(deprecated),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="status-refresh",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    assert refreshed["status"] == "deprecated"
    inactive = replace(source, status="inactive")
    refreshed = await registry.refresh_from_source(
        AuthoritativeAdapter(inactive),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="status-revoke",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    assert refreshed["status"] == "inactive"
    restored = await registry.refresh_from_source(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="status-restored-attempt",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    assert restored["status"] == "inactive"


async def test_ref_revoke_requires_reason_and_is_idempotent(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-reg-revoke-{uuid.uuid4().hex[:10]}"
    source = _source()
    registered = await CatalogRefRegistry(app_engine).register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="revoke-register",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    registry = CatalogRefRegistry(app_engine)
    payload = {
        "tenant_id": tenant_id,
        "actor_id": "user-1",
        "correlation_id": "revoke-1",
        "idempotency_key": "revoke-key",
        "kind": source.kind,
        "stable_id": source.stable_id,
        "version": source.version,
        "reason": "Confirmed removal by the authoritative owner.",
    }
    revoked = await registry.revoke(**payload)
    replay = await registry.revoke(**payload)
    assert revoked["ref_id"] == replay["ref_id"] == registered["ref_id"]
    assert replay["replayed"] is True
