"""N01A governed publish -> Candidate Artifact -> explicit activation lifecycle."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.bmc.compiler.causal_compiler import seed_case_a_step_types
from earp_server.causal_model_management.activation import ActivationCoordinator
from earp_server.causal_model_management.catalog import FakeCatalogResolver, ResolvedCatalogRef
from earp_server.causal_model_management.compiler import CandidateCompileService
from earp_server.causal_model_management.errors import N01AError
from earp_server.causal_model_management.schemas import (
    ActivateRequest,
    CreateModelRequest,
    PutEdgeRequest,
    PutEvidenceRequirementRequest,
    PutNodeRequest,
)
from earp_server.causal_model_management.service import ActorContext, CausalModelService
from earp_server.infra.db import tenant_session

TENANT = "tenant-n01a-lifecycle"
ADMIN_ROLE = "role-n01a-admin"
WRITER_ROLE = "role-n01a-writer"
OTHER_ROLE = "role-n01a-other-domain"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
def registry_engine(migrated: str, migration_url: str) -> AsyncEngine:
    return create_async_engine(migration_url, pool_pre_ping=True)


def ref(kind: str, stable_id: str) -> dict[str, str]:
    return {"kind": kind, "stable_id": stable_id, "version": "v1"}


def resolver() -> FakeCatalogResolver:
    entries: list[ResolvedCatalogRef] = []
    for kind, stable_id in (
        ("data_domain", "production"),
        ("entity_type", "entity.mine"),
        ("entity_type", "entity.system"),
        ("time_window_schema", "daily"),
        ("relation_type", "relation.affects"),
        ("metric", "metric.output"),
        ("metric", "metric.cause"),
        ("unit", "unit.count"),
        ("aggregation", "aggregation.mean"),
        ("binding_template", "binding.target"),
        ("capability_contract", "contract.read"),
    ):
        entries.append(
            ResolvedCatalogRef(
                kind=kind,
                stable_id=stable_id,
                version="v1",
                content_hash=(stable_id.encode().hex() + "0" * 64)[:64],
                status="active",
                data_domain_id="production",
                semantic_schema_version=f"{kind}/v1",
            )
        )
    return FakeCatalogResolver(entries)


async def seed_security(engine: AsyncEngine) -> None:
    async with tenant_session(engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id,tenant_id,name,permissions,data_scope,data_domain_access,is_admin) VALUES "
                "(:admin,:tenant,'N01A admin','{}','all','[]',true),"
                "(:writer,:tenant,'N01A writer',ARRAY['ecmc.causal_model.read','ecmc.causal_model.write_draft'],"
                "'all','[{\"data_domain_id\":\"production\"}]',false),"
                "(:other,:tenant,'N01A other',ARRAY['ecmc.causal_model.read'],'all',"
                "'[{\"data_domain_id\":\"finance\"}]',false) ON CONFLICT (role_id) DO NOTHING"
            ),
            {"tenant": TENANT, "admin": ADMIN_ROLE, "writer": WRITER_ROLE, "other": OTHER_ROLE},
        )


def actor(role: str, user: str = "user-n01a") -> ActorContext:
    return ActorContext(TENANT, user, role, f"corr-{user}")


def evidence(metric: str) -> PutEvidenceRequirementRequest:
    return PutEvidenceRequirementRequest(
        metric_ref=ref("metric", metric),
        unit_ref=ref("unit", "unit.count"),
        aggregation_ref=ref("aggregation", "aggregation.mean"),
        time_window_ref=ref("time_window_schema", "daily"),
        binding_template_ref=ref("binding_template", "binding.target"),
        binding_params={"target": "diagnostic_entity"},
        required=True,
        primary_contract_ref=ref("capability_contract", "contract.read"),
        supporting_contract_refs=[],
    )


async def build_published_model(
    engine: AsyncEngine, catalog: FakeCatalogResolver
) -> tuple[str, str, str, int]:
    service = CausalModelService(engine, catalog)
    admin = actor(ADMIN_ROLE)
    created = await service.create_model(
        admin,
        CreateModelRequest(
            name="N01A lifecycle model",
            data_domain_ref=ref("data_domain", "production"),
            diagnostic_target={
                "objective": "diagnose",
                "entry_point": "output",
                "direction": "down",
                "domain": "production",
                "target_entity_type_ref": ref("entity_type", "entity.mine"),
                "time_window_schema_ref": ref("time_window_schema", "daily"),
            },
        ),
        "create-model",
    )
    model_id = created["body"]["model_id"]
    version_id = created["body"]["initial_version"]["model_version_id"]
    revision = 1
    for key, entity, entry in (
        ("output", "entity.mine", True),
        ("cause", "entity.system", False),
    ):
        saved = await service.put_node(
            admin,
            model_id,
            version_id,
            key,
            PutNodeRequest(
                entity_type_ref=ref("entity_type", entity),
                observability="observable",
                entry_point=entry,
            ),
            revision,
            f"node-{key}",
        )
        revision = saved["body"]["revision"]
    edge = await service.put_edge(
        admin,
        model_id,
        version_id,
        "cause-output",
        PutEdgeRequest(
            from_node_key="cause",
            to_node_key="output",
            relation_type_ref=ref("relation_type", "relation.affects"),
            effect="-",
            strength="0.80",
            confidence="0.90",
            lag="PT0S",
        ),
        revision,
        "edge-cause-output",
    )
    revision = edge["body"]["revision"]
    for node_key, metric in (("cause", "metric.cause"), ("output", "metric.output")):
        saved = await service.put_evidence(
            admin,
            model_id,
            version_id,
            node_key,
            "primary-observation",
            evidence(metric),
            revision,
            f"evidence-{node_key}",
        )
        revision = saved["body"]["revision"]
    validated = await service.validate(admin, model_id, version_id, "full", "validate")
    assert validated["body"]["result"] == "passed"
    submitted = await service.submit_review(admin, model_id, version_id, revision, "submit")
    revision = submitted["body"]["revision"]
    published = await service.publish(admin, model_id, version_id, revision, "publish")
    return model_id, version_id, published["body"]["snapshot_id"], published["body"]["revision"]


async def test_full_lifecycle_candidate_is_inactive_until_explicit_activation_and_archive(
    app_engine: AsyncEngine, registry_engine: AsyncEngine
) -> None:
    await seed_security(app_engine)
    await seed_case_a_step_types(registry_engine)
    catalog = resolver()
    model_id, version_id, snapshot_id, revision = await build_published_model(app_engine, catalog)
    admin = actor(ADMIN_ROLE)
    compiler = CandidateCompileService(app_engine, catalog)
    requested = await compiler.request_compile(admin, model_id, version_id, None, "compile")
    compile_id = requested["body"]["compile_record"]["compile_record_id"]
    async with tenant_session(app_engine, TENANT) as session:
        assert int((await session.execute(text("SELECT count(*) FROM planning_blueprint_versions"))).scalar_one()) == 0
        pointer = (
            await session.execute(
                text("SELECT active_model_version_id,active_snapshot_id FROM causal_models WHERE model_id=:model"),
                {"model": model_id},
            )
        ).one()
        assert tuple(pointer) == (None, None)
    completed = await compiler.complete_attempt(admin, compile_id)
    assert completed["status"] == "success"
    async with tenant_session(app_engine, TENANT) as session:
        assert int((await session.execute(text("SELECT count(*) FROM planning_blueprint_versions"))).scalar_one()) == 0

    coordinator = ActivationCoordinator(app_engine, catalog)
    activated = await coordinator.activate(
        admin,
        model_id,
        ActivateRequest(
            model_version_id=version_id,
            compile_record_id=compile_id,
            expected_active_model_version_id=None,
            expected_active_snapshot_id=None,
        ),
        revision,
        "activate",
    )
    assert activated["body"]["active_pointer"] == {
        "model_version_id": version_id,
        "snapshot_id": snapshot_id,
    }
    assert activated["body"]["compiled_artifact_hash"] == completed["compiled_artifact_hash"]

    # A stale active-pointer CAS creates no Blueprint, audit or outbox business writes.
    async with tenant_session(app_engine, TENANT) as session:
        before = {
            "blueprints": int(
                (await session.execute(text("SELECT count(*) FROM planning_blueprint_versions"))).scalar_one()
            ),
            "audits": int(
                (
                    await session.execute(
                        text("SELECT count(*) FROM audit_logs WHERE event_type='ecmc.causal_model.activated'")
                    )
                ).scalar_one()
            ),
            "outbox": int(
                (
                    await session.execute(
                        text("SELECT count(*) FROM outbox_events WHERE event_type='ecmc.causal_model.activated'")
                    )
                ).scalar_one()
            ),
        }
    with pytest.raises(N01AError) as stale:
        await coordinator.activate(
            admin,
            model_id,
            ActivateRequest(
                model_version_id=version_id,
                compile_record_id=compile_id,
                expected_active_model_version_id=None,
                expected_active_snapshot_id=None,
            ),
            activated["body"]["revision"],
            "activate-stale-cas",
        )
    assert stale.value.code == "ACTIVE_VERSION_CHANGED"
    async with tenant_session(app_engine, TENANT) as session:
        after = {
            "blueprints": int(
                (await session.execute(text("SELECT count(*) FROM planning_blueprint_versions"))).scalar_one()
            ),
            "audits": int(
                (
                    await session.execute(
                        text("SELECT count(*) FROM audit_logs WHERE event_type='ecmc.causal_model.activated'")
                    )
                ).scalar_one()
            ),
            "outbox": int(
                (
                    await session.execute(
                        text("SELECT count(*) FROM outbox_events WHERE event_type='ecmc.causal_model.activated'")
                    )
                ).scalar_one()
            ),
        }
    assert after == before

    archived = await coordinator.archive(
        admin, model_id, version_id, activated["body"]["revision"], "archive-active"
    )
    assert archived["body"]["active_pointer"] == {"model_version_id": None, "snapshot_id": None}
    async with tenant_session(app_engine, TENANT) as session:
        assert (
            await session.execute(
                text("SELECT status FROM planning_blueprint_versions WHERE blueprint_version_id=:version"),
                {"version": activated["body"]["blueprint_version_id"]},
            )
        ).scalar_one() == "withdrawn"


async def test_permission_domain_visibility_and_idempotency(app_engine: AsyncEngine) -> None:
    await seed_security(app_engine)
    service = CausalModelService(app_engine, resolver())
    admin = actor(ADMIN_ROLE, "admin-idempotency")
    request = CreateModelRequest(
        name="Idempotent model",
        data_domain_ref=ref("data_domain", "production"),
        diagnostic_target={
            "objective": "diagnose",
            "entry_point": "output",
            "direction": "down",
            "domain": "production",
            "target_entity_type_ref": ref("entity_type", "entity.mine"),
            "time_window_schema_ref": ref("time_window_schema", "daily"),
        },
    )
    first = await service.create_model(admin, request, "same-key")
    replay = await service.create_model(admin, request, "same-key")
    assert replay["replayed"] is True and replay["body"] == first["body"]
    changed = request.model_copy(update={"name": "Different request"})
    with pytest.raises(N01AError) as reused:
        await service.create_model(admin, changed, "same-key")
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSE"
    with pytest.raises(N01AError) as hidden:
        await service.get_model(actor(OTHER_ROLE, "other"), first["body"]["model_id"])
    assert hidden.value.status_code == 404
