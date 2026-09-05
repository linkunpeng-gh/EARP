"""Tenant-scoped read models for Catalog page integration."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.catalog.hashing import content_hash
from earp_server.catalog.profiles import CatalogProfileError, CatalogProfileService
from earp_server.catalog.queries import catalog_metrics, list_profiles, list_refs
from earp_server.catalog.registry import CatalogRefRegistry
from earp_server.catalog.routes import (
    RefreshRefRequest,
    RegisterRefRequest,
    _require_catalog_read,
    refresh_ref,
    register_ref,
)
from earp_server.catalog.source import SourceObject
from earp_server.catalog.testing import MockCatalogSourceAdapter
from earp_server.infra.db import tenant_session

from .test_catalog_registry import AuthoritativeAdapter, _source


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def test_catalog_page_queries_are_tenant_scoped(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-query-{uuid.uuid4().hex[:10]}"
    source = _source()
    await CatalogRefRegistry(app_engine).register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="query-test",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    async with tenant_session(app_engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO catalog_profiles "
                "(tenant_id,profile_id,catalog_profile_id,profile_schema_version,industry_scope,"
                "enterprise_scope,data_domain_id,roles,backup_approver,status) VALUES "
                "(:tenant,'profile-1','profile-1','catalog-profile/v2','industry','enterprise',"
                "'production','[]','backup','active')"
            ),
            {"tenant": tenant_id},
        )
    refs = await list_refs(app_engine, tenant_id, kind="unit", query=source.stable_id)
    profiles = await list_profiles(app_engine, tenant_id)
    assert len(refs) == 1
    assert refs[0]["stable_id"] == source.stable_id
    assert profiles[0]["data_domain_id"] == "production"
    assert await list_refs(app_engine, "another-tenant", query=source.stable_id) == []
    metrics = await catalog_metrics(app_engine, tenant_id)
    assert metrics["refs_by_status"]["active"] == 1
    assert metrics["hash_drift_count"] == 0


async def test_catalog_routes_reject_role_without_read_permission(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-query-{uuid.uuid4().hex[:10]}"
    role_id = f"role-{uuid.uuid4().hex[:10]}"
    async with tenant_session(app_engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id,tenant_id,name,permissions,data_scope,is_admin) "
                "VALUES (:role,:tenant,'No catalog read','{}','all',false)"
            ),
            {"role": role_id, "tenant": tenant_id},
        )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(engine=app_engine)),
        state=SimpleNamespace(tenant_id=tenant_id, role_id=role_id),
    )
    with pytest.raises(HTTPException) as denied:
        await _require_catalog_read(request)
    assert denied.value.status_code == 403


async def test_profile_create_is_value_only_and_idempotent(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-profile-create-{uuid.uuid4().hex[:10]}"
    service = CatalogProfileService(app_engine)
    payload = {
        "tenant_id": tenant_id,
        "actor_id": "profile-owner",
        "correlation_id": "profile-create",
        "idempotency_key": "profile-create-1",
        "profile_id": "profile-create",
        "catalog_profile_id": "scope.example.tenant.domain",
        "industry_scope": "industry",
        "enterprise_scope": "enterprise",
        "data_domain_id": "production",
        "roles": [{"role_key": "product_owner", "name": "configured", "team": "configured", "contact": None}],
        "backup_approver": "product_owner",
    }
    first = await service.create(**payload)
    replay = await service.create(**payload)
    assert replay["replayed"] is True
    assert replay["profile_id"] == first["profile_id"]
    with pytest.raises(CatalogProfileError, match="different request"):
        await service.create(**{**payload, "enterprise_scope": "changed"})


async def test_register_route_uses_injected_mock_and_never_accepts_client_hash(
    app_engine: AsyncEngine,
) -> None:
    tenant_id = f"catalog-query-{uuid.uuid4().hex[:10]}"
    role_id = f"role-{uuid.uuid4().hex[:10]}"
    source = _source()
    async with tenant_session(app_engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id,tenant_id,name,permissions,data_scope,is_admin) "
                "VALUES (:role,:tenant,'Catalog requester',:permissions,'all',false)"
            ),
            {"role": role_id, "tenant": tenant_id, "permissions": ["ecmc.catalog.request"]},
        )
    app = SimpleNamespace(
        state=SimpleNamespace(
            engine=app_engine,
            catalog_source_adapters={"mock-unit": MockCatalogSourceAdapter("mock-unit", [source])},
        )
    )
    request = SimpleNamespace(
        app=app,
        state=SimpleNamespace(
            tenant_id=tenant_id,
            role_id=role_id,
            user_id="requester-1",
            n01a_correlation_id="register-route-1",
        ),
    )
    result = await register_ref(
        RegisterRefRequest(
            source_system="mock-unit",
            kind=source.kind,
            stable_id=source.stable_id,
            version=source.version,
        ),
        request,
    )
    assert result["content_hash"] == source.content_hash
    assert "canonical_input" not in result


class _SwitchingSourceAdapter:
    """Source double that returns a different verifiable object on each exact-ref call."""

    source_system = "mock-switching"

    def __init__(self, answers: list[SourceObject]) -> None:
        self._answers = list(answers)

    async def fetch_exact(self, kind: str, stable_id: str, version: str) -> SourceObject:
        if not self._answers:
            raise LookupError("mock source object not found")
        return self._answers.pop(0)

    async def list_since(self, cursor: str | None) -> tuple[list[SourceObject], str | None]:
        return [], cursor

    def source_identity(self, source: SourceObject) -> str:
        return f"objects/{source.kind}/{source.stable_id}/{source.version}"


async def _catalog_requester_request(app_engine: AsyncEngine, tenant_id: str) -> SimpleNamespace:
    role_id = f"role-{uuid.uuid4().hex[:10]}"
    async with tenant_session(app_engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id,tenant_id,name,permissions,data_scope,is_admin) "
                "VALUES (:role,:tenant,'Catalog requester',:permissions,'all',false)"
            ),
            {"role": role_id, "tenant": tenant_id, "permissions": ["ecmc.catalog.request"]},
        )
    return SimpleNamespace(
        state=SimpleNamespace(
            tenant_id=tenant_id,
            role_id=role_id,
            user_id="requester-1",
            n01a_correlation_id="register-route-1",
        )
    )


async def test_register_route_conflicts_409_when_pinned_ref_drifts(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-query-drift-{uuid.uuid4().hex[:10]}"
    source = _source()
    drifted_payload = {
        "kind": "unit",
        "stable_id": source.stable_id,
        "version": source.version,
        "unit_id": source.stable_id,
        "declared_drift": True,
    }
    drifted = SourceObject(
        kind="unit",
        stable_id=source.stable_id,
        version=source.version,
        canonical_input=drifted_payload,
        content_hash=content_hash(drifted_payload, schema_version="catalog-unit/v1"),
        schema_version="catalog-unit/v1",
        status="active",
        data_domain_id="production",
    )
    adapter = _SwitchingSourceAdapter([source, drifted])
    app = SimpleNamespace(
        state=SimpleNamespace(
            engine=app_engine,
            catalog_source_adapters={"mock-switching": adapter},
        )
    )
    request = await _catalog_requester_request(app_engine, tenant_id)
    request.app = app
    body = RegisterRefRequest(
        source_system="mock-switching",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    result = await register_ref(body, request)
    assert result["content_hash"] == source.content_hash
    with pytest.raises(HTTPException) as conflict:
        await register_ref(body, request)
    assert conflict.value.status_code == 409
    assert "different content hash" in conflict.value.detail


async def test_refresh_route_missing_source_object_returns_404(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-query-refresh-{uuid.uuid4().hex[:10]}"
    app = SimpleNamespace(
        state=SimpleNamespace(
            engine=app_engine,
            catalog_source_adapters={"mock-unit": MockCatalogSourceAdapter("mock-unit", [])},
        )
    )
    request = await _catalog_requester_request(app_engine, tenant_id)
    request.app = app
    with pytest.raises(HTTPException) as missing:
        await refresh_ref(
            RefreshRefRequest(
                source_system="mock-unit",
                kind="unit",
                stable_id="does-not-exist",
                version="1.0.0",
            ),
            request,
        )
    assert missing.value.status_code == 404
