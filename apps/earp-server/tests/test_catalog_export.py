"""Pack export contract: authoritative source content and owner/admin gate."""

from __future__ import annotations

import json
import uuid
from io import BytesIO
from zipfile import ZipFile

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.catalog.export import CatalogPackExportError, CatalogPackExportService
from earp_server.catalog.packs import CatalogPackService
from earp_server.catalog.registry import CatalogRefRegistry
from earp_server.catalog.testing import MockCatalogSourceAdapter

from .test_catalog_registry import _source


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def test_pack_export_fetches_authoritative_content_and_checks_owner(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-export-{uuid.uuid4().hex[:10]}"
    source = _source()
    adapter = MockCatalogSourceAdapter("mock-source", [source])
    await CatalogRefRegistry(app_engine).register(
        adapter,
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="export-register-1",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    pack_service = CatalogPackService(app_engine)
    await pack_service.create_draft(
        tenant_id=tenant_id,
        pack_id="mock-pack",
        layer="industry",
        name="Mock pack",
        owner_role="pack-owner",
    )
    await pack_service.add_registered_entry(
        tenant_id=tenant_id,
        pack_id="mock-pack",
        pack_version="1.0.0",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    await pack_service.publish(
        tenant_id=tenant_id,
        actor_id="pack-owner",
        correlation_id="export-publish-1",
        pack_id="mock-pack",
        version="1.0.0",
    )
    archive = await CatalogPackExportService(app_engine).export(
        tenant_id=tenant_id,
        actor_role="pack-owner",
        is_platform_admin=False,
        pack_id="mock-pack",
        version="1.0.0",
        adapters={"mock-source": adapter},
    )
    with ZipFile(BytesIO(archive)) as zipped:
        assert set(zipped.namelist()) == {
            "pack.json",
            f"entries/{source.kind}/{source.stable_id}@{source.version}.json",
        }
        metadata = json.loads(zipped.read("pack.json"))
        entry = json.loads(zipped.read(zipped.namelist()[1]))
    assert metadata["content_hash"]
    assert entry["canonical_input"] == source.canonical_input
    with pytest.raises(CatalogPackExportError, match="only the Pack owner"):
        await CatalogPackExportService(app_engine).export(
            tenant_id=tenant_id,
            actor_role="other-role",
            is_platform_admin=False,
            pack_id="mock-pack",
            version="1.0.0",
            adapters={"mock-source": adapter},
        )
    with pytest.raises(CatalogPackExportError, match="adapter is not ready"):
        await CatalogPackExportService(app_engine).export(
            tenant_id=tenant_id,
            actor_role="pack-owner",
            is_platform_admin=False,
            pack_id="mock-pack",
            version="1.0.0",
            adapters={},
        )
