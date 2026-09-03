"""Tenant-scoped read models for Catalog page integration."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.catalog.profiles import CatalogProfileError, CatalogProfileService
from earp_server.catalog.queries import catalog_metrics, list_profiles, list_refs
from earp_server.catalog.registry import CatalogRefRegistry
from earp_server.catalog.routes import RegisterRefRequest, _require_catalog_read, register_ref
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
