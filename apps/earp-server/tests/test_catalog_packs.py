"""Pack lifecycle contract: draft editing, hash publication, then immutability."""

from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.catalog.database_resolver import DatabaseCatalogResolver
from earp_server.catalog.domain import envelope_hash, manifest_content_hash, pack_content_hash
from earp_server.catalog.manifests import CatalogManifestService
from earp_server.catalog.packs import CatalogPackError, CatalogPackService
from earp_server.catalog.registry import CatalogRefRegistry
from earp_server.causal_model_management.catalog import CatalogValidationContext, UnavailableCatalogResolver
from earp_server.causal_model_management.schemas import CatalogRef
from earp_server.causal_model_management.service import ActorContext, CausalModelService
from earp_server.infra.db import tenant_session

from .test_catalog_registry import AuthoritativeAdapter, _source


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def test_published_pack_is_hashed_and_immutable(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-pack-{uuid.uuid4().hex[:10]}"
    source = _source()
    registered = await CatalogRefRegistry(app_engine).register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="register-1",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    service = CatalogPackService(app_engine)
    await service.create_draft(
        tenant_id=tenant_id,
        pack_id="platform-core",
        version="1.0.0",
        layer="platform",
        name="Platform core",
        owner_role="platform-admin",
    )
    await service.add_registered_entry(
        tenant_id=tenant_id,
        pack_id="platform-core",
        pack_version="1.0.0",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    digest = await service.publish(
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="publish-1",
        pack_id="platform-core",
        version="1.0.0",
    )

    assert digest == pack_content_hash(
        "platform-core",
        "platform",
        "1.0.0",
        [
            {
                "kind": source.kind,
                "stable_id": source.stable_id,
                "version": source.version,
                "content_hash": registered["content_hash"],
            }
        ],
    )
    with pytest.raises(CatalogPackError, match="only draft"):
        await service.add_registered_entry(
            tenant_id=tenant_id,
            pack_id="platform-core",
            pack_version="1.0.0",
            kind=source.kind,
            stable_id=source.stable_id,
            version=source.version,
        )
    with pytest.raises(CatalogPackError, match="immutable"):
        await service.publish(
            tenant_id=tenant_id,
            actor_id="user-1",
            correlation_id="publish-2",
            pack_id="platform-core",
            version="1.0.0",
        )


async def test_pack_draft_defaults_to_v1_and_replays_idempotently(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-pack-{uuid.uuid4().hex[:10]}"
    source = _source()
    await CatalogRefRegistry(app_engine).register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="register-default-version",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    service = CatalogPackService(app_engine)
    first = await service.create_draft(
        tenant_id=tenant_id,
        actor_id="user-1",
        pack_id="mock-platform",
        layer="platform",
        name="Mock platform",
        owner_role="platform-admin",
        idempotency_key="pack-draft-1",
    )
    replay = await service.create_draft(
        tenant_id=tenant_id,
        actor_id="user-1",
        pack_id="mock-platform",
        layer="platform",
        name="Mock platform",
        owner_role="platform-admin",
        idempotency_key="pack-draft-1",
    )
    assert first["version"] == replay["version"] == "1.0.0"
    entry = await service.add_registered_entry(
        tenant_id=tenant_id,
        actor_id="user-1",
        pack_id="mock-platform",
        pack_version="1.0.0",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
        idempotency_key="pack-entry-1",
    )
    entry_replay = await service.add_registered_entry(
        tenant_id=tenant_id,
        actor_id="user-1",
        pack_id="mock-platform",
        pack_version="1.0.0",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
        idempotency_key="pack-entry-1",
    )
    assert entry == entry_replay
    with pytest.raises(CatalogPackError, match="reused"):
        await service.create_draft(
            tenant_id=tenant_id,
            actor_id="user-1",
            pack_id="mock-platform",
            layer="platform",
            name="Changed request",
            owner_role="platform-admin",
            idempotency_key="pack-draft-1",
        )


async def test_manifest_publication_binds_signoff_pointer_and_outbox(
    app_engine: AsyncEngine,
) -> None:
    tenant_id = f"catalog-manifest-{uuid.uuid4().hex[:10]}"
    profile_id = "profile-1"
    source = _source()
    registered = await CatalogRefRegistry(app_engine).register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="register-1",
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
                "(:tenant,:profile,:catalog_profile,'catalog-profile/v2','industry','enterprise',"
                "'production','[]','backup','active')"
            ),
            {
                "tenant": tenant_id,
                "profile": profile_id,
                "catalog_profile": f"catalog-{profile_id}",
            },
        )
    pack_service = CatalogPackService(app_engine)
    await pack_service.create_draft(
        tenant_id=tenant_id,
        pack_id="platform-core",
        version="1.0.0",
        layer="platform",
        name="Platform core",
        owner_role="platform-admin",
    )
    await pack_service.add_registered_entry(
        tenant_id=tenant_id,
        pack_id="platform-core",
        pack_version="1.0.0",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    pack_hash = await pack_service.publish(
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="publish-pack-1",
        pack_id="platform-core",
        version="1.0.0",
    )
    manifest = {
        "manifest_schema_version": "catalog-manifest/v1",
        "manifest_id": "profile-1-manifest",
        "manifest_revision": 1,
        "scope": {
            "industry_scope": "industry",
            "enterprise_scope": "enterprise",
            "tenant_id": tenant_id,
            "data_domains": ["production"],
            "global_enabled": False,
        },
        "pack_lock": [
            {
                "pack_id": "platform-core",
                "layer": "platform",
                "version": "1.0.0",
                "content_hash": pack_hash,
            }
        ],
        "entries": [
            {
                "kind": source.kind,
                "stable_id": source.stable_id,
                "version": source.version,
                "content_hash": registered["content_hash"],
                "status": "active",
                "data_domain_id": "production",
                "semantic_schema_version": "catalog-unit/v1",
            }
        ],
        "owners": [{"role_key": "platform_architect", "name": "test", "team": "test"}],
        "resolver_adapter": {
            "identity": "earp.catalog.resolver.api/v1",
            "contract_version": "catalog-resolver/v1.0",
        },
    }
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    attestation = {
        "manifest_hash": manifest["manifest_hash"],
        "signoff_tag": "test-signoff",
        "change_order": "test-change",
        "signed_at": "2026-09-02T00:00:00+08:00",
        "effective_from": "2026-09-02T00:00:00+08:00",
        "effective_until": None,
        "signers": [{"role_key": "platform_architect", "name": "test"}],
    }
    attestation["envelope_hash"] = envelope_hash(attestation)
    digest = await CatalogManifestService(app_engine).publish_and_activate(
        tenant_id=tenant_id,
        profile_id=profile_id,
        actor_id="user-1",
        correlation_id="manifest-1",
        idempotency_key="manifest-request-1",
        manifest=manifest,
        attestation=attestation,
    )
    assert digest == manifest["manifest_hash"]
    resolved = await DatabaseCatalogResolver(app_engine).resolve(
        tenant_id,
        CatalogRef(kind=source.kind, stable_id=source.stable_id, version=source.version),
        source.kind,
        context=CatalogValidationContext(tenant_id, "production", {"profile_id": profile_id}),
    )
    assert resolved.content_hash == source.content_hash
    async with tenant_session(app_engine, tenant_id) as session:
        counts = await session.execute(
            text(
                "SELECT (SELECT count(*) FROM catalog_signoffs), "
                "(SELECT count(*) FROM catalog_outbox), "
                "(SELECT manifest_revision FROM catalog_active_manifests WHERE profile_id=:profile)"
            ),
            {"profile": profile_id},
        )
        assert counts.one() == (1, 2, 1)

    second = deepcopy(manifest)
    second["manifest_id"] = "profile-1-manifest"
    second["manifest_revision"] = 2
    second["manifest_hash"] = manifest_content_hash(second)
    second_attestation = {
        **attestation,
        "manifest_hash": second["manifest_hash"],
        "signoff_tag": "test-signoff-2",
        "change_order": "test-change-2",
    }
    second_attestation["envelope_hash"] = envelope_hash(second_attestation)
    await CatalogManifestService(app_engine).publish_and_activate(
        tenant_id=tenant_id,
        profile_id=profile_id,
        actor_id="user-1",
        correlation_id="manifest-2",
        idempotency_key="manifest-request-2",
        manifest=second,
        attestation=second_attestation,
        expected_active_revision=1,
    )
    rollback = deepcopy(manifest)
    rollback["manifest_revision"] = 3
    rollback["manifest_hash"] = manifest_content_hash(rollback)
    rollback_attestation = {
        **attestation,
        "manifest_hash": rollback["manifest_hash"],
        "signoff_tag": "test-rollback",
        "change_order": "test-rollback-change",
    }
    rollback_attestation["envelope_hash"] = envelope_hash(rollback_attestation)
    await CatalogManifestService(app_engine).rollback(
        tenant_id=tenant_id,
        profile_id=profile_id,
        target_revision=1,
        new_manifest_id="profile-1-manifest",
        new_revision=3,
        actor_id="user-1",
        correlation_id="manifest-rollback",
        idempotency_key="manifest-request-3",
        attestation=rollback_attestation,
    )
    assert (
        await CatalogManifestService(app_engine).revoke_active(
            tenant_id=tenant_id,
            profile_id=profile_id,
            actor_id="user-1",
            correlation_id="manifest-revoke",
            idempotency_key="manifest-revoke-1",
            reason="Controlled rollback drill completed.",
        )
    )["status"] == "revoked"
    async with tenant_session(app_engine, tenant_id) as session:
        historical = await session.execute(
            text("SELECT status FROM catalog_manifests WHERE tenant_id=:tenant AND manifest_revision=1"),
            {"tenant": tenant_id},
        )
        assert historical.scalar_one() == "active"


async def test_manifest_builder_reads_profile_and_published_pack_pins(app_engine: AsyncEngine) -> None:
    tenant_id = f"catalog-manifest-builder-{uuid.uuid4().hex[:10]}"
    source = _source()
    await CatalogRefRegistry(app_engine).register(
        AuthoritativeAdapter(source),
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="builder-register",
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
                "(:tenant,'profile-builder','coal.sdrh.builder.production','catalog-profile/v2',"
                "'coal_mining','SDRH','production',:roles,'audit_compliance_owner','active')"
            ),
            {
                "tenant": tenant_id,
                "roles": '[{"role_key":"product_owner","name":"test","team":"test","contact":null}]',
            },
        )
    packs = CatalogPackService(app_engine)
    await packs.create_draft(
        tenant_id=tenant_id,
        pack_id="platform-base",
        layer="platform",
        name="Platform base",
        owner_role="platform-admin",
    )
    await packs.add_registered_entry(
        tenant_id=tenant_id,
        pack_id="platform-base",
        pack_version="1.0.0",
        kind=source.kind,
        stable_id=source.stable_id,
        version=source.version,
    )
    pack_hash = await packs.publish(
        tenant_id=tenant_id,
        actor_id="user-1",
        correlation_id="builder-pack",
        pack_id="platform-base",
        version="1.0.0",
    )
    manifest = await CatalogManifestService(app_engine).build_from_packs(
        tenant_id=tenant_id,
        profile_id="profile-builder",
        manifest_id="coal.sdrh.builder.production",
        manifest_revision=1,
        packs=[{"pack_id": "platform-base", "version": "1.0.0"}],
    )
    assert manifest["manifest_hash"] == manifest_content_hash(manifest)
    assert manifest["pack_lock"] == [
        {"pack_id": "platform-base", "layer": "platform", "version": "1.0.0", "content_hash": pack_hash}
    ]
    assert manifest["entries"][0]["content_hash"] == source.content_hash
    assert manifest["owners"][0]["role_key"] == "product_owner"


async def test_pack_publish_request_reuses_shared_approval_and_sod(
    app_engine: AsyncEngine,
) -> None:
    tenant_id = f"catalog-pack-approval-{uuid.uuid4().hex[:10]}"
    async with tenant_session(app_engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id,tenant_id,name,permissions,data_scope,data_domain_access,is_admin) "
                "VALUES ('pack-requester',:tenant,'Pack requester',"
                "ARRAY['ecmc.catalog.read','ecmc.catalog.request'],'all','[]',false),"
                "('pack-owner',:tenant,'Pack owner',"
                "ARRAY['ecmc.catalog.read','ecmc.catalog.approve'],'all','[]',false)"
            ),
            {"tenant": tenant_id},
        )
    pack_service = CatalogPackService(app_engine)
    await pack_service.create_draft(
        tenant_id=tenant_id,
        pack_id="mock-industry",
        layer="industry",
        name="Mock industry",
        owner_role="pack-owner",
    )
    request = await pack_service.create_publish_request(
        tenant_id=tenant_id,
        actor_id="requester-1",
        correlation_id="pack-publish-request-1",
        pack_id="mock-industry",
        version="1.0.0",
        rationale="Request publication after reviewing registered reference pins.",
        idempotency_key="pack-publish-request-1",
    )
    service = CausalModelService(app_engine, UnavailableCatalogResolver())
    requester = ActorContext(tenant_id, "requester-1", "pack-requester", "submit-1")
    approver = ActorContext(tenant_id, "approver-1", "pack-owner", "approve-1")
    submitted = await service.submit_request(requester, str(request["request_id"]), "submit-pack-1")
    assert submitted["body"]["status"] == "submitted"
    approved = await service.approve_request(approver, str(request["request_id"]), "approve-pack-1")
    assert approved["body"]["status"] == "approved_pending_fulfillment"
    attempt_id = str(approved["body"]["fulfillment_attempt_id"])
    fulfilled = await service.fulfill_pack_publish(
        approver,
        str(request["request_id"]),
        attempt_id,
        "fulfill-pack-1",
    )
    fulfilled_replay = await service.fulfill_pack_publish(
        approver,
        str(request["request_id"]),
        attempt_id,
        "fulfill-pack-1",
    )
    assert fulfilled["body"] == fulfilled_replay["body"]
    assert fulfilled["body"]["status"] == "fulfilled"
    assert fulfilled["body"]["content_hash"]
    async with tenant_session(app_engine, tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM catalog_packs WHERE tenant_id=:tenant AND pack_id='mock-industry'"),
                {"tenant": tenant_id},
            )
        ).scalar_one()
        assert status == "published"
        approval = (
            (
                await session.execute(
                    text("SELECT decision,approver_id FROM catalog_approvals WHERE tenant_id=:tenant"),
                    {"tenant": tenant_id},
                )
            )
            .mappings()
            .one()
        )
        assert approval["decision"] == "approved"
        assert approval["approver_id"] == "approver-1"
