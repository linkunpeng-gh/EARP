"""Transactional N01A domain service.

The service is the authority; FastAPI is only a transport adapter.  Every
method uses one tenant transaction so revision CAS, audit and outbox changes
commit or roll back together.
"""

# Native SQL is used consistently with the existing EARP services.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.catalog.domain import CatalogCompositionError, pack_content_hash
from earp_server.catalog.governance import assert_approval_separation
from earp_server.infra.db import tenant_session

from .canonicalization import (
    CANONICALIZER_VERSION,
    CAUSAL_SNAPSHOT_SCHEMA,
    canonical_hash,
    canonical_json,
)
from .catalog import CatalogResolutionError, CatalogResolver, CatalogValidationContext, ResolvedCatalogRef
from .errors import N01AError, conflict, forbidden, not_found, validation_failed
from .schemas import (
    CatalogRef,
    CreateCatalogChangeRequest,
    CreateModelRequest,
    PatchCatalogChangeRequest,
    PutEdgeRequest,
    PutEvidenceRequirementRequest,
    PutNodeRequest,
    PutRuleRequest,
)


@dataclass(frozen=True)
class ActorContext:
    tenant_id: str
    actor_id: str
    role_id: str
    correlation_id: str


@dataclass(frozen=True)
class _RoleScope:
    exists: bool
    is_admin: bool
    permissions: frozenset[str]
    domains: frozenset[str]


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _request_hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def parse_if_match(value: str | None) -> int:
    if value is None or len(value) < 4 or not value.startswith('"v') or not value.endswith('"'):
        raise N01AError("MISSING_IF_MATCH", 'If-Match must use the form "v<revision>".', 422)
    try:
        revision = int(value[2:-1])
    except ValueError as error:
        raise N01AError("MISSING_IF_MATCH", 'If-Match must use the form "v<revision>".', 422) from error
    if revision < 1:
        raise N01AError("MISSING_IF_MATCH", "If-Match must use a positive revision.", 422)
    return revision


def etag(revision: int) -> str:
    return f'"v{revision}"'


class _CausalModelServiceBase:
    def __init__(self, engine: AsyncEngine, catalog: CatalogResolver) -> None:
        self.engine = engine
        self.catalog = catalog

    async def _role_scope(self, session: AsyncSession, actor: ActorContext) -> _RoleScope:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT is_admin, permissions, data_domain_access FROM roles "
                        "WHERE tenant_id=:tenant AND role_id=:role"
                    ),
                    {"tenant": actor.tenant_id, "role": actor.role_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return _RoleScope(False, False, frozenset(), frozenset())
        domains = frozenset(
            str(item["data_domain_id"])
            for item in (row["data_domain_access"] or [])
            if isinstance(item, dict) and item.get("data_domain_id")
        )
        return _RoleScope(True, bool(row["is_admin"]), frozenset(row["permissions"] or []), domains)

    @staticmethod
    def _require_permission(scope: _RoleScope, permission: str) -> None:
        if not scope.exists or (not scope.is_admin and permission not in scope.permissions):
            raise forbidden()

    @staticmethod
    def _require_domain(scope: _RoleScope, data_domain_id: str, *, invisible: bool = False) -> None:
        if not scope.exists or (not scope.is_admin and data_domain_id not in scope.domains):
            if invisible:
                raise not_found("CAUSAL_MODEL_NOT_FOUND", "Causal model was not found.")
            raise forbidden("DOMAIN_ACCESS_DENIED", "The data domain is outside the role scope.")

    async def _model(
        self, session: AsyncSession, actor: ActorContext, model_id: str, *, for_update: bool = False
    ) -> dict[str, Any]:
        suffix = " FOR UPDATE" if for_update else ""
        row = (
            (
                await session.execute(
                    text(
                        "SELECT tenant_id,model_id,data_domain_id,name,description,diagnostic_target_signature,"
                        "active_model_version_id,active_snapshot_id,revision,created_at,updated_at "
                        "FROM causal_models WHERE tenant_id=:tenant AND model_id=:model" + suffix
                    ),
                    {"tenant": actor.tenant_id, "model": model_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise not_found("CAUSAL_MODEL_NOT_FOUND", "Causal model was not found.")
        result = dict(row)
        scope = await self._role_scope(session, actor)
        self._require_domain(scope, result["data_domain_id"], invisible=True)
        return result

    async def _version(
        self,
        session: AsyncSession,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        *,
        for_update: bool = False,
    ) -> dict[str, Any]:
        await self._model(session, actor, model_id, for_update=for_update)
        suffix = " FOR UPDATE" if for_update else ""
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM causal_model_versions WHERE tenant_id=:tenant AND model_id=:model "
                        "AND model_version_id=:version" + suffix
                    ),
                    {"tenant": actor.tenant_id, "model": model_id, "version": version_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None or row["status"] in {"testing", "deprecated"}:
            raise not_found("MODEL_VERSION_NOT_FOUND", "Causal model version was not found.")
        return dict(row)

    @staticmethod
    def _revision(version: dict[str, Any], expected_revision: int) -> None:
        if version["revision"] != expected_revision:
            raise conflict(
                "VERSION_CONFLICT",
                "The version revision is stale.",
                current_revision=version["revision"],
            )

    @staticmethod
    async def _replay(
        session: AsyncSession,
        actor: ActorContext,
        operation: str,
        idempotency_key: str,
        request: Any,
    ) -> dict[str, Any] | None:
        if not idempotency_key.strip():
            raise N01AError("REQUEST_SCHEMA_INVALID", "Idempotency-Key is required.", 422)
        request_hash = _request_hash(request)
        row = (
            (
                await session.execute(
                    text(
                        "SELECT request_hash,response_status,response_body FROM idempotency_records "
                        "WHERE tenant_id=:tenant AND actor_id=:actor AND operation=:operation AND idempotency_key=:key"
                    ),
                    {
                        "tenant": actor.tenant_id,
                        "actor": actor.actor_id,
                        "operation": operation,
                        "key": idempotency_key,
                    },
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise conflict("IDEMPOTENCY_KEY_REUSE", "Idempotency-Key was reused with a different request.")
        return {"status_code": row["response_status"], "body": row["response_body"], "replayed": True}

    @staticmethod
    async def _remember(
        session: AsyncSession,
        actor: ActorContext,
        operation: str,
        idempotency_key: str,
        request: Any,
        status_code: int,
        body: dict[str, Any],
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO idempotency_records "
                "(tenant_id,actor_id,operation,idempotency_key,request_hash,response_status,response_body) "
                "VALUES (:tenant,:actor,:operation,:key,:hash,:status,:body)"
            ),
            {
                "tenant": actor.tenant_id,
                "actor": actor.actor_id,
                "operation": operation,
                "key": idempotency_key,
                "hash": _request_hash(request),
                "status": status_code,
                "body": _json(body),
            },
        )

    @staticmethod
    async def _audit(
        session: AsyncSession,
        actor: ActorContext,
        event_type: str,
        entity_type: str,
        entity_id: str,
        detail: dict[str, Any],
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO audit_logs (tenant_id,event_type,entity_type,entity_id,user_id,detail) "
                "VALUES (:tenant,:event,:entity_type,:entity_id,:actor,:detail)"
            ),
            {
                "tenant": actor.tenant_id,
                "event": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "actor": actor.actor_id,
                "detail": _json({**detail, "role_id": actor.role_id, "correlation_id": actor.correlation_id}),
            },
        )

    @staticmethod
    async def _outbox(
        session: AsyncSession,
        actor: ActorContext,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
        destination: str,
    ) -> str:
        event_id = _id("evt")
        await session.execute(
            text(
                "INSERT INTO outbox_events "
                "(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload,correlation_id,idempotency_key) "
                "VALUES (:tenant,:event_id,:event_type,:aggregate_type,:aggregate_id,:payload,:correlation,:key)"
            ),
            {
                "tenant": actor.tenant_id,
                "event_id": event_id,
                "event_type": event_type,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "payload": _json(payload),
                "correlation": actor.correlation_id,
                "key": idempotency_key,
            },
        )
        await session.execute(
            text(
                "INSERT INTO outbox_deliveries (tenant_id,delivery_id,event_id,destination) "
                "VALUES (:tenant,:delivery,:event,:destination)"
            ),
            {
                "tenant": actor.tenant_id,
                "delivery": _id("delivery"),
                "event": event_id,
                "destination": destination,
            },
        )
        return event_id

    async def create_model(
        self, actor: ActorContext, request: CreateModelRequest, idempotency_key: str
    ) -> dict[str, Any]:
        operation = "causal-model.create"
        payload = request.model_dump(mode="json")
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.write_draft")
            domain = await self.catalog.resolve(
                actor.tenant_id,
                request.data_domain_ref,
                "data_domain",
                context=CatalogValidationContext(
                    actor.tenant_id,
                    request.data_domain_ref.stable_id,
                    {"resource_type": "model", "field": "data_domain_ref"},
                ),
            )
            self._require_domain(scope, domain.data_domain_id)
            for ref, kind, field in (
                (request.diagnostic_target.target_entity_type_ref, "entity_type", "target_entity_type_ref"),
                (request.diagnostic_target.time_window_schema_ref, "time_window_schema", "time_window_schema_ref"),
            ):
                await self.catalog.resolve(
                    actor.tenant_id,
                    ref,
                    kind,
                    context=CatalogValidationContext(
                        actor.tenant_id, domain.data_domain_id, {"resource_type": "model", "field": field}
                    ),
                )
            target = request.diagnostic_target.model_dump(mode="json")
            signature = _request_hash(target)
            model_id, version_id = _id("cm"), _id("cmv")
            await session.execute(
                text(
                    "INSERT INTO causal_models "
                    "(tenant_id,model_id,data_domain_id,name,description,diagnostic_target_signature) "
                    "VALUES (:tenant,:model,:domain,:name,:description,:signature)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "model": model_id,
                    "domain": domain.data_domain_id,
                    "name": request.name,
                    "description": request.description,
                    "signature": signature,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO causal_model_versions "
                    "(tenant_id,model_version_id,model_id,version,status,diagnostic_target,"
                    "diagnostic_target_signature,revision,created_by,updated_by) "
                    "VALUES (:tenant,:version_id,:model,'1','draft',:target,:signature,1,:actor,:actor)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "version_id": version_id,
                    "model": model_id,
                    "target": _json(target),
                    "signature": signature,
                    "actor": actor.actor_id,
                },
            )
            body = {
                "model_id": model_id,
                "name": request.name,
                "data_domain_ref": request.data_domain_ref.model_dump(mode="json"),
                "diagnostic_target": target,
                "active_pointer": {"model_version_id": None, "snapshot_id": None},
                "initial_version": {"model_version_id": version_id, "version": "1", "status": "draft", "revision": 1},
            }
            await self._audit(session, actor, "ecmc.causal_model.created", "causal_model", model_id, body)
            await self._remember(session, actor, operation, idempotency_key, payload, 201, body)
            return {"status_code": 201, "body": body, "replayed": False}

    async def list_models(self, actor: ActorContext) -> list[dict[str, Any]]:
        async with tenant_session(self.engine, actor.tenant_id) as session:
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.read")
            rows = (
                await session.execute(
                    text(
                        "SELECT model_id,data_domain_id,name,description,active_model_version_id,active_snapshot_id,revision "
                        "FROM causal_models WHERE diagnostic_target_signature IS NOT NULL ORDER BY created_at DESC"
                    )
                )
            ).mappings()
            return [
                {
                    **dict(row),
                    "active_pointer": {
                        "model_version_id": row["active_model_version_id"],
                        "snapshot_id": row["active_snapshot_id"],
                    },
                }
                for row in rows
                if scope.is_admin or row["data_domain_id"] in scope.domains
            ]

    async def get_model(self, actor: ActorContext, model_id: str) -> dict[str, Any]:
        async with tenant_session(self.engine, actor.tenant_id) as session:
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.read")
            model = await self._model(session, actor, model_id)
            versions = (
                await session.execute(
                    text(
                        "SELECT model_version_id,version,status,revision,published_snapshot_id,created_at,updated_at "
                        "FROM causal_model_versions WHERE model_id=:model AND status NOT IN ('testing','deprecated') "
                        "ORDER BY created_at DESC"
                    ),
                    {"model": model_id},
                )
            ).mappings()
            model["active_pointer"] = {
                "model_version_id": model.pop("active_model_version_id"),
                "snapshot_id": model.pop("active_snapshot_id"),
            }
            model["versions"] = [dict(row) for row in versions]
            return model

    async def create_version(
        self,
        actor: ActorContext,
        model_id: str,
        clone_from_version_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.version.create:{model_id}"
        payload = {"clone_from_version_id": clone_from_version_id}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.write_draft")
            model = await self._model(session, actor, model_id, for_update=True)
            source = None
            if clone_from_version_id:
                source = await self._version(session, actor, model_id, clone_from_version_id)
            next_number = int(
                (
                    await session.execute(
                        text(
                            "SELECT COALESCE(max(CASE WHEN version ~ '^[0-9]+$' THEN version::int END),0)+1 "
                            "FROM causal_model_versions WHERE model_id=:model"
                        ),
                        {"model": model_id},
                    )
                ).scalar_one()
            )
            version_id = _id("cmv")
            target = source["diagnostic_target"] if source else None
            if target is None:
                first = (
                    await session.execute(
                        text(
                            "SELECT diagnostic_target FROM causal_model_versions WHERE model_id=:model "
                            "AND diagnostic_target IS NOT NULL ORDER BY created_at LIMIT 1"
                        ),
                        {"model": model_id},
                    )
                ).scalar_one()
                target = first
            await session.execute(
                text(
                    "INSERT INTO causal_model_versions "
                    "(tenant_id,model_version_id,model_id,version,status,diagnostic_target,diagnostic_target_signature,"
                    "revision,created_by,updated_by,derived_from_model_version_id,applicability) "
                    "VALUES (:tenant,:version_id,:model,:version,'draft',:target,:signature,1,:actor,:actor,:source,:applicability)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "version_id": version_id,
                    "model": model_id,
                    "version": str(next_number),
                    "target": _json(target),
                    "signature": model["diagnostic_target_signature"],
                    "actor": actor.actor_id,
                    "source": clone_from_version_id,
                    "applicability": _json(source["applicability"] if source else {}),
                },
            )
            if clone_from_version_id is not None:
                await self._clone_children(session, actor.tenant_id, clone_from_version_id, version_id)
            body = {"model_version_id": version_id, "version": str(next_number), "status": "draft", "revision": 1}
            await self._audit(session, actor, "ecmc.causal_version.created", "causal_model_version", version_id, body)
            await self._remember(session, actor, operation, idempotency_key, payload, 201, body)
            return {"status_code": 201, "body": body, "replayed": False}

    @staticmethod
    async def _clone_children(session: AsyncSession, tenant_id: str, source: str, target: str) -> None:
        # Stable business keys are retained; database row ids are regenerated.
        await session.execute(
            text(
                "INSERT INTO causal_nodes "
                "(tenant_id,node_row_id,model_version_id,node_key,node_seq,entity_type_ref,entry_point,entry_direction,"
                "entry_description,aggregation_mode,aggregation_operator,aggregation_predicate,aggregation_weight_ref,"
                "observation_window,entity_type_catalog_ref,observability,business_name,notes) "
                "SELECT tenant_id,concat('node-',md5(random()::text||node_row_id)),:target,node_key,node_seq,entity_type_ref,"
                "entry_point,entry_direction,entry_description,aggregation_mode,aggregation_operator,aggregation_predicate,"
                "aggregation_weight_ref,observation_window,entity_type_catalog_ref,observability,business_name,notes "
                "FROM causal_nodes WHERE tenant_id=:tenant AND model_version_id=:source"
            ),
            {"tenant": tenant_id, "source": source, "target": target},
        )
        for table, pk, columns in (
            (
                "causal_edges",
                "edge_row_id",
                "edge_key,source_node_key,target_node_key,relation_type_ref,effect,strength,lag,confidence,relation_type_catalog_ref",
            ),
            ("causal_rules", "rule_row_id", "rule_key,node_key,rule_type,rule_spec,rule_schema_ref,rationale"),
            (
                "causal_data_bindings",
                "binding_row_id",
                "node_key,requirement_key,requirement_level,metric_binding,instance_binding_expr,instance_key_field,"
                "instance_observation,output_mapping,metric_ref,unit_ref,aggregation_ref,time_window_ref,binding_template_ref,"
                "binding_params,business_description",
            ),
            (
                "causal_capability_bindings",
                "cap_binding_row_id",
                "node_key,requirement_key,capability_role,read_only_required,capability_contract_ref,"
                "capability_contract_catalog_ref",
            ),
        ):
            await session.execute(
                text(
                    f"INSERT INTO {table} (tenant_id,{pk},model_version_id,{columns}) "
                    f"SELECT tenant_id,concat('clone-',md5(random()::text||{pk})),:target,{columns} "
                    f"FROM {table} WHERE tenant_id=:tenant AND model_version_id=:source"
                ),
                {"tenant": tenant_id, "source": source, "target": target},
            )

    async def _draft_for_write(
        self,
        session: AsyncSession,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        scope = await self._role_scope(session, actor)
        self._require_permission(scope, "ecmc.causal_model.write_draft")
        version = await self._version(session, actor, model_id, version_id, for_update=True)
        self._revision(version, expected_revision)
        if version["status"] != "draft":
            raise conflict("INVALID_STATE_TRANSITION", "Only draft versions can be edited.")
        return version

    async def _finish_draft_write(
        self,
        session: AsyncSession,
        actor: ActorContext,
        version_id: str,
        event: str,
        detail: dict[str, Any],
    ) -> int:
        revision = int(
            (
                await session.execute(
                    text(
                        "UPDATE causal_model_versions SET revision=revision+1,updated_by=:actor,updated_at=now() "
                        "WHERE model_version_id=:version RETURNING revision"
                    ),
                    {"actor": actor.actor_id, "version": version_id},
                )
            ).scalar_one()
        )
        await self._audit(session, actor, event, "causal_model_version", version_id, {**detail, "revision": revision})
        return revision

    async def put_node(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        node_key: str,
        request: PutNodeRequest,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-node.put:{version_id}:{node_key}"
        payload = request.model_dump(mode="json")
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            await self._draft_for_write(session, actor, model_id, version_id, expected_revision)
            model = await self._model(session, actor, model_id)
            await self.catalog.resolve(
                actor.tenant_id,
                request.entity_type_ref,
                "entity_type",
                context=CatalogValidationContext(
                    actor.tenant_id,
                    model["data_domain_id"],
                    {"resource_type": "node", "node_key": node_key, "field": "entity_type_ref"},
                ),
            )
            seq = int(
                (
                    await session.execute(
                        text("SELECT COALESCE(max(node_seq),0)+1 FROM causal_nodes WHERE model_version_id=:version"),
                        {"version": version_id},
                    )
                ).scalar_one()
            )
            await session.execute(
                text(
                    "INSERT INTO causal_nodes "
                    "(tenant_id,node_row_id,model_version_id,node_key,node_seq,entity_type_ref,entity_type_catalog_ref,"
                    "observability,entry_point,business_name,notes) "
                    "VALUES (:tenant,:row,:version,:key,:seq,:entity,:catalog_ref,:observability,:entry,:name,:notes) "
                    "ON CONFLICT (tenant_id,model_version_id,node_key) DO UPDATE SET "
                    "entity_type_ref=excluded.entity_type_ref,entity_type_catalog_ref=excluded.entity_type_catalog_ref,"
                    "observability=excluded.observability,entry_point=excluded.entry_point,business_name=excluded.business_name,"
                    "notes=excluded.notes"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("node"),
                    "version": version_id,
                    "key": node_key,
                    "seq": seq,
                    "entity": request.entity_type_ref.stable_id,
                    "catalog_ref": _json(request.entity_type_ref.model_dump(mode="json")),
                    "observability": request.observability,
                    "entry": request.entry_point,
                    "name": request.business_name,
                    "notes": request.notes,
                },
            )
            revision = await self._finish_draft_write(
                session, actor, version_id, "ecmc.causal_node.saved", {"node_key": node_key}
            )
            body = {"model_version_id": version_id, "node_key": node_key, "revision": revision}
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def put_edge(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        edge_key: str,
        request: PutEdgeRequest,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-edge.put:{version_id}:{edge_key}"
        payload = request.model_dump(mode="json")
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            await self._draft_for_write(session, actor, model_id, version_id, expected_revision)
            model = await self._model(session, actor, model_id)
            for node_key in (request.from_node_key, request.to_node_key):
                exists = await session.execute(
                    text("SELECT 1 FROM causal_nodes WHERE model_version_id=:version AND node_key=:node"),
                    {"version": version_id, "node": node_key},
                )
                if exists.first() is None:
                    raise N01AError("REQUEST_SCHEMA_INVALID", f"Unknown edge endpoint: {node_key}", 422)
            await self.catalog.resolve(
                actor.tenant_id,
                request.relation_type_ref,
                "relation_type",
                context=CatalogValidationContext(
                    actor.tenant_id,
                    model["data_domain_id"],
                    {"resource_type": "edge", "edge_key": edge_key, "field": "relation_type_ref"},
                ),
            )
            await session.execute(
                text(
                    "INSERT INTO causal_edges "
                    "(tenant_id,edge_row_id,edge_key,model_version_id,source_node_key,target_node_key,relation_type_ref,"
                    "relation_type_catalog_ref,effect,strength,confidence,lag) "
                    "VALUES (:tenant,:row,:key,:version,:source,:target,:relation,:catalog_ref,:effect,:strength,:confidence,:lag) "
                    "ON CONFLICT (tenant_id,model_version_id,edge_key) DO UPDATE SET "
                    "source_node_key=excluded.source_node_key,target_node_key=excluded.target_node_key,"
                    "relation_type_ref=excluded.relation_type_ref,relation_type_catalog_ref=excluded.relation_type_catalog_ref,"
                    "effect=excluded.effect,strength=excluded.strength,confidence=excluded.confidence,lag=excluded.lag"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("edge"),
                    "key": edge_key,
                    "version": version_id,
                    "source": request.from_node_key,
                    "target": request.to_node_key,
                    "relation": request.relation_type_ref.stable_id,
                    "catalog_ref": _json(request.relation_type_ref.model_dump(mode="json")),
                    "effect": request.effect,
                    "strength": request.strength,
                    "confidence": request.confidence,
                    "lag": request.lag,
                },
            )
            revision = await self._finish_draft_write(
                session, actor, version_id, "ecmc.causal_edge.saved", {"edge_key": edge_key}
            )
            body = {"model_version_id": version_id, "edge_key": edge_key, "revision": revision}
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def put_rule(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        rule_key: str,
        request: PutRuleRequest,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-rule.put:{version_id}:{rule_key}"
        payload = request.model_dump(mode="json")
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            await self._draft_for_write(session, actor, model_id, version_id, expected_revision)
            model = await self._model(session, actor, model_id)
            resolved = await self.catalog.resolve(
                actor.tenant_id,
                request.rule_schema_ref,
                "rule_schema",
                context=CatalogValidationContext(
                    actor.tenant_id,
                    model["data_domain_id"],
                    {"resource_type": "rule", "rule_key": rule_key, "field": "rule_schema_ref"},
                ),
            )
            rule_type = str(resolved.compatibility_metadata.get("rule_kind", "predicate"))
            if rule_type not in {"predicate", "threshold", "direction_rule"}:
                raise CatalogResolutionError(
                    "CATALOG_REF_SCHEMA_INCOMPATIBLE", request.rule_schema_ref, "Unsupported rule schema kind."
                )
            await session.execute(
                text(
                    "INSERT INTO causal_rules "
                    "(tenant_id,rule_row_id,rule_key,model_version_id,node_key,rule_type,rule_spec,rule_schema_ref,rationale) "
                    "VALUES (:tenant,:row,:key,:version,NULL,:type,:spec,:schema_ref,:rationale) "
                    "ON CONFLICT (tenant_id,model_version_id,rule_key) DO UPDATE SET "
                    "rule_type=excluded.rule_type,rule_spec=excluded.rule_spec,rule_schema_ref=excluded.rule_schema_ref,"
                    "rationale=excluded.rationale"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("rule"),
                    "key": rule_key,
                    "version": version_id,
                    "type": rule_type,
                    "spec": _json(request.rule_spec),
                    "schema_ref": _json(request.rule_schema_ref.model_dump(mode="json")),
                    "rationale": request.rationale,
                },
            )
            revision = await self._finish_draft_write(
                session, actor, version_id, "ecmc.causal_rule.saved", {"rule_key": rule_key}
            )
            body = {"model_version_id": version_id, "rule_key": rule_key, "revision": revision}
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def put_evidence(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        node_key: str,
        requirement_key: str,
        request: PutEvidenceRequirementRequest,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-evidence.put:{version_id}:{node_key}:{requirement_key}"
        payload = request.model_dump(mode="json")
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            await self._draft_for_write(session, actor, model_id, version_id, expected_revision)
            model = await self._model(session, actor, model_id)
            node = (
                (
                    await session.execute(
                        text(
                            "SELECT entity_type_catalog_ref FROM causal_nodes WHERE model_version_id=:version AND node_key=:node"
                        ),
                        {"version": version_id, "node": node_key},
                    )
                )
                .mappings()
                .first()
            )
            if node is None:
                raise N01AError("REQUEST_SCHEMA_INVALID", "Evidence node does not exist.", 422)
            context = CatalogValidationContext(
                actor.tenant_id,
                model["data_domain_id"],
                {"resource_type": "evidence", "node_key": node_key, "requirement_key": requirement_key},
                source_entity_type_ref=CatalogRef.model_validate(node["entity_type_catalog_ref"]),
            )
            refs = [
                (request.metric_ref, "metric"),
                (request.unit_ref, "unit"),
                (request.aggregation_ref, "aggregation"),
                (request.time_window_ref, "time_window_schema"),
                (request.binding_template_ref, "binding_template"),
                (request.primary_contract_ref, "capability_contract"),
                *((ref, "capability_contract") for ref in request.supporting_contract_refs),
            ]
            validated = await self.catalog.validate(actor.tenant_id, refs, context)
            if validated.errors:
                raise validated.errors[0]
            await session.execute(
                text(
                    "INSERT INTO causal_data_bindings "
                    "(tenant_id,binding_row_id,model_version_id,node_key,requirement_key,requirement_level,"
                    "metric_binding,instance_binding_expr,metric_ref,unit_ref,aggregation_ref,time_window_ref,"
                    "binding_template_ref,binding_params,business_description) "
                    "VALUES (:tenant,:row,:version,:node,:requirement,:level,:metric_binding,:binding_expr,:metric,:unit,"
                    ":aggregation,:time_window,:template,:params,:description) "
                    "ON CONFLICT (tenant_id,model_version_id,node_key,requirement_key) DO UPDATE SET "
                    "requirement_level=excluded.requirement_level,metric_binding=excluded.metric_binding,"
                    "instance_binding_expr=excluded.instance_binding_expr,metric_ref=excluded.metric_ref,unit_ref=excluded.unit_ref,"
                    "aggregation_ref=excluded.aggregation_ref,time_window_ref=excluded.time_window_ref,"
                    "binding_template_ref=excluded.binding_template_ref,binding_params=excluded.binding_params,"
                    "business_description=excluded.business_description"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("binding"),
                    "version": version_id,
                    "node": node_key,
                    "requirement": requirement_key,
                    "level": "required" if request.required else "optional",
                    "metric_binding": _json(request.metric_ref.model_dump(mode="json")),
                    "binding_expr": _json(request.binding_params),
                    "metric": _json(request.metric_ref.model_dump(mode="json")),
                    "unit": _json(request.unit_ref.model_dump(mode="json")),
                    "aggregation": _json(request.aggregation_ref.model_dump(mode="json")),
                    "time_window": _json(request.time_window_ref.model_dump(mode="json")),
                    "template": _json(request.binding_template_ref.model_dump(mode="json")),
                    "params": _json(request.binding_params),
                    "description": request.business_description,
                },
            )
            await session.execute(
                text(
                    "DELETE FROM causal_capability_bindings WHERE model_version_id=:version "
                    "AND node_key=:node AND requirement_key=:requirement"
                ),
                {"version": version_id, "node": node_key, "requirement": requirement_key},
            )
            contracts = [
                ("primary", request.primary_contract_ref),
                *[("supporting", r) for r in request.supporting_contract_refs],
            ]
            for role, ref in contracts:
                await session.execute(
                    text(
                        "INSERT INTO causal_capability_bindings "
                        "(tenant_id,cap_binding_row_id,model_version_id,node_key,requirement_key,capability_role,"
                        "read_only_required,capability_contract_ref,capability_contract_catalog_ref) "
                        "VALUES (:tenant,:row,:version,:node,:requirement,:role,true,:stable_id,:catalog_ref)"
                    ),
                    {
                        "tenant": actor.tenant_id,
                        "row": _id("cap-binding"),
                        "version": version_id,
                        "node": node_key,
                        "requirement": requirement_key,
                        "role": role,
                        "stable_id": ref.stable_id,
                        "catalog_ref": _json(ref.model_dump(mode="json")),
                    },
                )
            revision = await self._finish_draft_write(
                session,
                actor,
                version_id,
                "ecmc.causal_evidence.saved",
                {"node_key": node_key, "requirement_key": requirement_key},
            )
            body = {
                "model_version_id": version_id,
                "node_key": node_key,
                "requirement_key": requirement_key,
                "revision": revision,
            }
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def delete_draft_resource(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        resource_type: str,
        resource_key: str,
        expected_revision: int,
        idempotency_key: str,
        *,
        node_key: str | None = None,
    ) -> dict[str, Any]:
        operation = f"causal-{resource_type}.delete:{version_id}:{node_key or ''}:{resource_key}"
        payload = {"resource_type": resource_type, "resource_key": resource_key, "node_key": node_key}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            await self._draft_for_write(session, actor, model_id, version_id, expected_revision)
            params = {"version": version_id, "key": resource_key, "node": node_key}
            if resource_type == "node":
                dependent = int(
                    (
                        await session.execute(
                            text(
                                "SELECT (SELECT count(*) FROM causal_edges WHERE model_version_id=:version "
                                "AND (source_node_key=:key OR target_node_key=:key)) + "
                                "(SELECT count(*) FROM causal_rules WHERE model_version_id=:version AND node_key=:key) + "
                                "(SELECT count(*) FROM causal_data_bindings WHERE model_version_id=:version AND node_key=:key)"
                            ),
                            params,
                        )
                    ).scalar_one()
                )
                if dependent:
                    raise conflict("RESOURCE_HAS_DEPENDENTS", "The node still has dependent graph resources.")
                result = await session.execute(
                    text("DELETE FROM causal_nodes WHERE model_version_id=:version AND node_key=:key"), params
                )
            elif resource_type == "edge":
                result = await session.execute(
                    text("DELETE FROM causal_edges WHERE model_version_id=:version AND edge_key=:key"), params
                )
            elif resource_type == "rule":
                result = await session.execute(
                    text("DELETE FROM causal_rules WHERE model_version_id=:version AND rule_key=:key"), params
                )
            elif resource_type == "evidence":
                if node_key is None:
                    raise N01AError("REQUEST_SCHEMA_INVALID", "node_key is required for evidence deletion.", 422)
                await session.execute(
                    text(
                        "DELETE FROM causal_capability_bindings WHERE model_version_id=:version "
                        "AND node_key=:node AND requirement_key=:key"
                    ),
                    params,
                )
                result = await session.execute(
                    text(
                        "DELETE FROM causal_data_bindings WHERE model_version_id=:version "
                        "AND node_key=:node AND requirement_key=:key"
                    ),
                    params,
                )
            else:
                raise N01AError("REQUEST_SCHEMA_INVALID", "Unknown draft resource type.", 422)
            if getattr(result, "rowcount", 0) == 0:
                raise not_found("MODEL_VERSION_NOT_FOUND", "Draft resource was not found.")
            revision = await self._finish_draft_write(
                session,
                actor,
                version_id,
                f"ecmc.causal_{resource_type}.deleted",
                {"resource_key": resource_key, "node_key": node_key},
            )
            body = {"model_version_id": version_id, "revision": revision}
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def get_version(self, actor: ActorContext, model_id: str, version_id: str) -> dict[str, Any]:
        async with tenant_session(self.engine, actor.tenant_id) as session:
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.read")
            version = await self._version(session, actor, model_id, version_id)
            content = await self._load_content(session, version_id)
            return {**version, **content}

    @staticmethod
    async def _load_content(session: AsyncSession, version_id: str) -> dict[str, Any]:
        nodes = [
            dict(row)
            for row in (
                await session.execute(
                    text(
                        "SELECT node_key,entity_type_catalog_ref AS entity_type_ref,observability,entry_point,"
                        "business_name,notes FROM causal_nodes WHERE model_version_id=:version ORDER BY node_key"
                    ),
                    {"version": version_id},
                )
            ).mappings()
        ]
        edges = [
            {
                **dict(row),
                "from_node_key": row["source_node_key"],
                "to_node_key": row["target_node_key"],
            }
            for row in (
                await session.execute(
                    text(
                        "SELECT edge_key,source_node_key,target_node_key,relation_type_catalog_ref AS relation_type_ref,"
                        "effect,strength,confidence,lag FROM causal_edges WHERE model_version_id=:version ORDER BY edge_key"
                    ),
                    {"version": version_id},
                )
            ).mappings()
        ]
        for edge in edges:
            edge.pop("source_node_key", None)
            edge.pop("target_node_key", None)
        rules = [
            dict(row)
            for row in (
                await session.execute(
                    text(
                        "SELECT rule_key,rule_schema_ref,rule_spec,rationale FROM causal_rules "
                        "WHERE model_version_id=:version ORDER BY rule_key"
                    ),
                    {"version": version_id},
                )
            ).mappings()
        ]
        requirements: list[dict[str, Any]] = []
        bindings = (
            await session.execute(
                text(
                    "SELECT node_key,requirement_key,requirement_level,metric_ref,unit_ref,aggregation_ref,time_window_ref,"
                    "binding_template_ref,binding_params,business_description FROM causal_data_bindings "
                    "WHERE model_version_id=:version ORDER BY node_key,requirement_key"
                ),
                {"version": version_id},
            )
        ).mappings()
        for binding in bindings:
            contracts = [
                dict(row)
                for row in (
                    await session.execute(
                        text(
                            "SELECT capability_role,capability_contract_catalog_ref FROM causal_capability_bindings "
                            "WHERE model_version_id=:version AND node_key=:node AND requirement_key=:requirement "
                            "ORDER BY capability_role,capability_contract_ref"
                        ),
                        {
                            "version": version_id,
                            "node": binding["node_key"],
                            "requirement": binding["requirement_key"],
                        },
                    )
                ).mappings()
            ]
            primary = [
                item["capability_contract_catalog_ref"] for item in contracts if item["capability_role"] == "primary"
            ]
            supporting = [
                item["capability_contract_catalog_ref"] for item in contracts if item["capability_role"] == "supporting"
            ]
            requirements.append(
                {
                    "node_key": binding["node_key"],
                    "requirement_key": binding["requirement_key"],
                    "metric_ref": binding["metric_ref"],
                    "unit_ref": binding["unit_ref"],
                    "aggregation_ref": binding["aggregation_ref"],
                    "time_window_ref": binding["time_window_ref"],
                    "binding_template_ref": binding["binding_template_ref"],
                    "binding_params": binding["binding_params"],
                    "required": binding["requirement_level"] == "required",
                    "primary_contract_ref": primary[0] if len(primary) == 1 else None,
                    "supporting_contract_refs": supporting,
                    "business_description": binding["business_description"],
                }
            )
        return {"nodes": nodes, "edges": edges, "rules": rules, "evidence_requirements": requirements}

    async def _analyze(
        self,
        session: AsyncSession,
        actor: ActorContext,
        model: dict[str, Any],
        version: dict[str, Any],
        mode: str,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        content = await self._load_content(session, version["model_version_id"])
        issues: list[dict[str, Any]] = []
        target = version["diagnostic_target"]
        nodes = content["nodes"]
        edges = content["edges"]
        requirements = content["evidence_requirements"]
        node_map = {node["node_key"]: node for node in nodes}
        entries = [node for node in nodes if node["entry_point"]]
        if len(entries) != 1:
            issues.append(
                self._issue(
                    "CAUSAL_ENTRY_POINT_COUNT",
                    "error",
                    {"resource_type": "version", "field": "nodes"},
                    "Exactly one entry point is required.",
                )
            )
        elif entries[0]["node_key"] != target["entry_point"]:
            issues.append(
                self._issue(
                    "CAUSAL_TARGET_MISMATCH",
                    "error",
                    {"resource_type": "node", "node_key": entries[0]["node_key"], "field": "entry_point"},
                    "Entry point does not match the diagnostic target.",
                )
            )
        elif entries[0]["observability"] != "observable":
            issues.append(
                self._issue(
                    "CAUSAL_ENTRY_NOT_OBSERVABLE",
                    "error",
                    {"resource_type": "node", "node_key": entries[0]["node_key"], "field": "observability"},
                    "The entry point must be observable.",
                )
            )

        adjacency = {key: [] for key in node_map}
        for edge in edges:
            source, destination = edge["from_node_key"], edge["to_node_key"]
            if source == destination:
                issues.append(
                    self._issue(
                        "CAUSAL_SELF_LOOP",
                        "error",
                        {"resource_type": "edge", "edge_key": edge["edge_key"]},
                        "Self loops are not allowed.",
                    )
                )
            if source not in node_map or destination not in node_map:
                issues.append(
                    self._issue(
                        "CAUSAL_DANGLING_EDGE",
                        "error",
                        {"resource_type": "edge", "edge_key": edge["edge_key"]},
                        "Edge endpoint is missing.",
                    )
                )
            elif source != destination:
                adjacency[source].append(destination)
            if Decimal(edge["confidence"]) < Decimal("0.2"):
                issues.append(
                    self._issue(
                        "CAUSAL_LOW_CONFIDENCE",
                        "warning",
                        {"resource_type": "edge", "edge_key": edge["edge_key"], "field": "confidence"},
                        "Edge confidence is low.",
                    )
                )
        if self._has_cycle(adjacency):
            issues.append(
                self._issue(
                    "CAUSAL_DAG_CYCLE",
                    "error",
                    {"resource_type": "version", "field": "edges"},
                    "The Phase 1 authoring profile requires a DAG.",
                )
            )
        if len(entries) == 1:
            entry_key = entries[0]["node_key"]
            for key in node_map:
                if key != entry_key and not self._reachable(adjacency, key, entry_key):
                    issues.append(
                        self._issue(
                            "CAUSAL_NODE_CANNOT_REACH_ENTRY",
                            "error",
                            {"resource_type": "node", "node_key": key},
                            "Node cannot reach the diagnostic entry point.",
                        )
                    )

        requirement_nodes = {item["node_key"] for item in requirements if item["required"]}
        for node in nodes:
            if node["observability"] == "observable" and node["node_key"] not in requirement_nodes:
                issues.append(
                    self._issue(
                        "CAUSAL_REQUIRED_EVIDENCE_MISSING",
                        "error",
                        {"resource_type": "node", "node_key": node["node_key"]},
                        "Observable nodes require evidence under sign_propagation_v1.",
                    )
                )
        for requirement in requirements:
            if requirement["primary_contract_ref"] is None:
                issues.append(
                    self._issue(
                        "CAUSAL_PRIMARY_CONTRACT_MISSING",
                        "error",
                        {
                            "resource_type": "evidence",
                            "node_key": requirement["node_key"],
                            "requirement_key": requirement["requirement_key"],
                            "field": "primary_contract_ref",
                        },
                        "Exactly one primary capability contract is required.",
                    )
                )

        resolutions: dict[tuple[str, str, str], ResolvedCatalogRef] = {}
        refs: list[tuple[dict[str, Any] | None, str, dict[str, Any]]] = [
            (
                target["target_entity_type_ref"],
                "entity_type",
                {"resource_type": "version", "field": "diagnostic_target.target_entity_type_ref"},
            ),
            (
                target["time_window_schema_ref"],
                "time_window_schema",
                {"resource_type": "version", "field": "diagnostic_target.time_window_schema_ref"},
            ),
        ]
        for node in nodes:
            refs.append(
                (
                    node["entity_type_ref"],
                    "entity_type",
                    {"resource_type": "node", "node_key": node["node_key"], "field": "entity_type_ref"},
                )
            )
        for edge in edges:
            refs.append(
                (
                    edge["relation_type_ref"],
                    "relation_type",
                    {"resource_type": "edge", "edge_key": edge["edge_key"], "field": "relation_type_ref"},
                )
            )
        for rule in content["rules"]:
            refs.append(
                (
                    rule["rule_schema_ref"],
                    "rule_schema",
                    {"resource_type": "rule", "rule_key": rule["rule_key"], "field": "rule_schema_ref"},
                )
            )
        for requirement in requirements:
            location = {
                "resource_type": "evidence",
                "node_key": requirement["node_key"],
                "requirement_key": requirement["requirement_key"],
            }
            refs.extend(
                [
                    (requirement["metric_ref"], "metric", {**location, "field": "metric_ref"}),
                    (requirement["unit_ref"], "unit", {**location, "field": "unit_ref"}),
                    (requirement["aggregation_ref"], "aggregation", {**location, "field": "aggregation_ref"}),
                    (requirement["time_window_ref"], "time_window_schema", {**location, "field": "time_window_ref"}),
                    (
                        requirement["binding_template_ref"],
                        "binding_template",
                        {**location, "field": "binding_template_ref"},
                    ),
                    (
                        requirement["primary_contract_ref"],
                        "capability_contract",
                        {**location, "field": "primary_contract_ref"},
                    ),
                    *[
                        (ref, "capability_contract", {**location, "field": "supporting_contract_refs"})
                        for ref in requirement["supporting_contract_refs"]
                    ],
                ]
            )
        for raw_ref, kind, location in refs:
            if raw_ref is None:
                continue
            try:
                ref = CatalogRef.model_validate(raw_ref)
                resolved = await self.catalog.resolve(
                    actor.tenant_id,
                    ref,
                    kind,
                    context=CatalogValidationContext(actor.tenant_id, model["data_domain_id"], location),
                )
                resolutions[(resolved.kind, resolved.stable_id, resolved.version)] = resolved
            except CatalogResolutionError as error:
                issues.append(
                    {
                        **self._issue(error.code, "error", location, error.message),
                        "catalog_ref": error.ref.model_dump(mode="json"),
                    }
                )
            except ValueError:
                issues.append(
                    self._issue(
                        "CATALOG_REF_SCHEMA_INCOMPATIBLE", "error", location, "CatalogRef payload is malformed."
                    )
                )

        run_id = _id("cvr")
        draft_input = {"diagnostic_target": target, **content, "applicability": version["applicability"]}
        input_hash = _request_hash(draft_input)
        result = "failed" if any(item["severity"] == "error" for item in issues) else "passed"
        validation = {
            "validation_run_id": run_id,
            "model_version_id": version["model_version_id"],
            "draft_revision": version["revision"],
            "input_hash": input_hash,
            "result": result,
            "issues": issues,
        }
        await session.execute(
            text(
                "INSERT INTO causal_model_validation_runs "
                "(tenant_id,validation_run_id,model_id,model_version_id,draft_revision,input_hash,validator_version,mode,result,issues) "
                "VALUES (:tenant,:run,:model,:version,:revision,:hash,'n01a/v1',:mode,:result,:issues)"
            ),
            {
                "tenant": actor.tenant_id,
                "run": run_id,
                "model": model["model_id"],
                "version": version["model_version_id"],
                "revision": version["revision"],
                "hash": input_hash,
                "mode": mode,
                "result": result,
                "issues": _json(issues),
            },
        )
        snapshot_payload = None
        if result == "passed":
            snapshot_payload = {
                "snapshot_schema_version": CAUSAL_SNAPSHOT_SCHEMA,
                "model_identity": {"model_id": model["model_id"], "model_version": version["version"]},
                "diagnostic_target": target,
                "algorithm_profile": {"stable_id": "sign_propagation_v1", "version": "v1"},
                "nodes": [
                    {key: value for key, value in node.items() if key not in {"business_name", "notes"}}
                    for node in nodes
                ],
                "edges": edges,
                "rules": [
                    {key: value for key, value in rule.items() if key != "rationale"} for rule in content["rules"]
                ],
                "evidence_requirements": [
                    {key: value for key, value in requirement.items() if key != "business_description"}
                    for requirement in requirements
                ],
                "applicability": version["applicability"],
                "catalog_resolutions": [entry.pin() for entry in resolutions.values()],
                "semantic_schema_versions": {
                    f"{entry.kind}:{entry.stable_id}:{entry.version}": entry.semantic_schema_version
                    for entry in resolutions.values()
                },
            }
        return validation, snapshot_payload

    @staticmethod
    def _issue(code: str, severity: str, location: dict[str, Any], message: str) -> dict[str, Any]:
        return {"code": code, "severity": severity, "location": location, "message": message}

    @staticmethod
    def _has_cycle(adjacency: dict[str, list[str]]) -> bool:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(child) for child in adjacency[node]):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in adjacency)

    @staticmethod
    def _reachable(adjacency: dict[str, list[str]], source: str, target: str) -> bool:
        pending, seen = [source], set()
        while pending:
            node = pending.pop()
            if node == target:
                return True
            if node not in seen:
                seen.add(node)
                pending.extend(adjacency[node])
        return False

    async def validate(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        mode: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.validate:{version_id}"
        payload = {"mode": mode}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.write_draft")
            model = await self._model(session, actor, model_id)
            version = await self._version(session, actor, model_id, version_id)
            if version["status"] != "draft":
                raise conflict(
                    "INVALID_STATE_TRANSITION", "Only draft versions can be validated from the authoring API."
                )
            result, _ = await self._analyze(session, actor, model, version, mode)
            await self._audit(
                session,
                actor,
                "ecmc.causal_model.validated",
                "causal_model_version",
                version_id,
                {"validation_run_id": result["validation_run_id"], "result": result["result"]},
            )
            await self._remember(session, actor, operation, idempotency_key, payload, 200, result)
            return {"status_code": 200, "body": result, "replayed": False}

    async def submit_review(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.submit-review:{version_id}"
        payload = {"expected_revision": expected_revision}
        blocked: dict[str, Any] | None = None
        response: dict[str, Any] | None = None
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            version = await self._draft_for_write(session, actor, model_id, version_id, expected_revision)
            model = await self._model(session, actor, model_id)
            validation, _ = await self._analyze(session, actor, model, version, "full")
            if validation["result"] == "failed":
                blocked = validation
                error_body = {"code": "MODEL_VALIDATION_FAILED", "details": {"validation_result": validation}}
                await self._remember(session, actor, operation, idempotency_key, payload, 422, error_body)
            else:
                revision = expected_revision + 1
                await session.execute(
                    text(
                        "UPDATE causal_model_versions SET status='in_review',revision=:revision,submitted_at=now(),"
                        "submitted_by=:actor,updated_by=:actor,updated_at=now() WHERE model_version_id=:version"
                    ),
                    {"revision": revision, "actor": actor.actor_id, "version": version_id},
                )
                await CausalModelService._review(session, actor, model_id, version_id, "submit", "submitted", None)
                response = {"model_version_id": version_id, "status": "in_review", "revision": revision}
                await self._audit(
                    session, actor, "ecmc.causal_model.submitted", "causal_model_version", version_id, response
                )
                await self._remember(session, actor, operation, idempotency_key, payload, 200, response)
        if blocked is not None:
            raise validation_failed(blocked)
        assert response is not None
        return {"status_code": 200, "body": response, "replayed": False}


class CausalModelService(_CausalModelServiceBase):
    async def create_request(
        self, actor: ActorContext, request: CreateCatalogChangeRequest, idempotency_key: str
    ) -> dict[str, Any]:
        operation = "catalog-change-request.create"
        payload = request.model_dump(mode="json")
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.catalog.request")
            domain = await self.catalog.resolve(
                actor.tenant_id,
                request.target_data_domain_ref,
                "data_domain",
                context=CatalogValidationContext(
                    actor.tenant_id,
                    request.target_data_domain_ref.stable_id,
                    {"resource_type": "catalog_change_request", "field": "target_data_domain_ref"},
                ),
            )
            self._require_domain(scope, domain.data_domain_id)
            request_id = _id("ccr")
            await session.execute(
                text(
                    "INSERT INTO catalog_change_requests "
                    "(tenant_id,request_id,request_type,target_data_domain_ref,rationale,proposed_definition,status,requester_id) "
                    "VALUES (:tenant,:request,:type,:domain,:rationale,:definition,'draft',:actor)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "request": request_id,
                    "type": request.request_type,
                    "domain": _json(request.target_data_domain_ref.model_dump(mode="json")),
                    "rationale": request.rationale,
                    "definition": _json(request.proposed_definition.model_dump(mode="json")),
                    "actor": actor.actor_id,
                },
            )
            body = {"request_id": request_id, "status": "draft", "revision": 1, **payload}
            await self._audit(
                session, actor, "ecmc.catalog_request.created", "catalog_change_request", request_id, body
            )
            await self._remember(session, actor, operation, idempotency_key, payload, 201, body)
            return {"status_code": 201, "body": body, "replayed": False}

    async def list_requests(self, actor: ActorContext) -> list[dict[str, Any]]:
        async with tenant_session(self.engine, actor.tenant_id) as session:
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.catalog.read")
            rows = (
                await session.execute(
                    text(
                        "SELECT r.*, (SELECT a.attempt_id FROM catalog_fulfillment_attempts a "
                        "WHERE a.tenant_id=r.tenant_id AND a.request_id=r.request_id "
                        "ORDER BY a.attempt_no DESC LIMIT 1) AS fulfillment_attempt_id "
                        "FROM catalog_change_requests r ORDER BY r.created_at DESC"
                    )
                )
            ).mappings()
            visible: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                if scope.is_admin or (item["target_data_domain_ref"] or {}).get("stable_id") in scope.domains:
                    visible.append(item)
                    continue
                if item["request_type"] == "pack_publish":
                    pack = (
                        await session.execute(
                            text(
                                "SELECT owner_role FROM catalog_packs "
                                "WHERE tenant_id=:tenant AND pack_id || '@' || version=:resource"
                            ),
                            {"tenant": actor.tenant_id, "resource": item["resource_id"]},
                        )
                    ).scalar_one_or_none()
                    if item["requester_id"] == actor.actor_id or actor.role_id == pack:
                        visible.append(item)
            return visible

    async def _request(
        self, session: AsyncSession, actor: ActorContext, request_id: str, *, for_update: bool = False
    ) -> tuple[dict[str, Any], _RoleScope]:
        scope = await self._role_scope(session, actor)
        self._require_permission(scope, "ecmc.catalog.read")
        suffix = " FOR UPDATE" if for_update else ""
        row = (
            (
                await session.execute(
                    text("SELECT * FROM catalog_change_requests WHERE request_id=:request" + suffix),
                    {"request": request_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise not_found("CATALOG_CHANGE_REQUEST_NOT_FOUND", "Catalog change request was not found.")
        result = dict(row)
        if result["request_type"] == "pack_publish" and not scope.is_admin:
            owner_role = (
                await session.execute(
                    text(
                        "SELECT owner_role FROM catalog_packs "
                        "WHERE tenant_id=:tenant AND pack_id || '@' || version=:resource"
                    ),
                    {"tenant": actor.tenant_id, "resource": result["resource_id"]},
                )
            ).scalar_one_or_none()
            if result["requester_id"] != actor.actor_id and actor.role_id != owner_role:
                raise not_found("CATALOG_CHANGE_REQUEST_NOT_FOUND", "Catalog change request was not found.")
            return result, scope
        domain = (result["target_data_domain_ref"] or {}).get("stable_id")
        if not scope.is_admin and domain not in scope.domains:
            raise not_found("CATALOG_CHANGE_REQUEST_NOT_FOUND", "Catalog change request was not found.")
        return result, scope

    async def get_request(self, actor: ActorContext, request_id: str) -> dict[str, Any]:
        async with tenant_session(self.engine, actor.tenant_id) as session:
            request, _ = await self._request(session, actor, request_id)
            attempts = [
                dict(row)
                for row in (
                    await session.execute(
                        text(
                            "SELECT attempt_id,attempt_no,status,resolved_ref,sanitized_error,created_at,finished_at "
                            "FROM catalog_fulfillment_attempts WHERE request_id=:request ORDER BY attempt_no"
                        ),
                        {"request": request_id},
                    )
                ).mappings()
            ]
            return {**request, "fulfillment_attempts": attempts}

    async def submit_request(self, actor: ActorContext, request_id: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request_transition(
            actor,
            request_id,
            "submit",
            idempotency_key,
            allowed={"draft"},
            result="submitted",
            permission="ecmc.catalog.request",
            owner_only=True,
        )

    async def approve_request(self, actor: ActorContext, request_id: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request_transition(
            actor,
            request_id,
            "approve",
            idempotency_key,
            allowed={"submitted"},
            result="approved_pending_fulfillment",
            permission="ecmc.catalog.approve",
            create_attempt=True,
        )

    async def reject_request(
        self, actor: ActorContext, request_id: str, reason: str, idempotency_key: str
    ) -> dict[str, Any]:
        return await self._request_transition(
            actor,
            request_id,
            "reject",
            idempotency_key,
            allowed={"submitted"},
            result="rejected",
            permission="ecmc.catalog.approve",
            reason=reason,
        )

    async def cancel_request(self, actor: ActorContext, request_id: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request_transition(
            actor,
            request_id,
            "cancel",
            idempotency_key,
            allowed={"draft", "submitted"},
            result="cancelled",
            permission="ecmc.catalog.request",
            owner_only=True,
        )

    async def retry_fulfillment(self, actor: ActorContext, request_id: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request_transition(
            actor,
            request_id,
            "retry-fulfillment",
            idempotency_key,
            allowed={"fulfillment_failed"},
            result="approved_pending_fulfillment",
            permission="ecmc.catalog.approve",
            create_attempt=True,
        )

    async def _request_transition(
        self,
        actor: ActorContext,
        request_id: str,
        command: str,
        idempotency_key: str,
        *,
        allowed: set[str],
        result: str,
        permission: str,
        owner_only: bool = False,
        reason: str | None = None,
        create_attempt: bool = False,
    ) -> dict[str, Any]:
        operation = f"catalog-change-request.{command}:{request_id}"
        payload = {"reason": reason}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            request, scope = await self._request(session, actor, request_id, for_update=True)
            self._require_permission(scope, permission)
            if command == "approve":
                assert_approval_separation(requester_id=request["requester_id"], approver_id=actor.actor_id)
            if owner_only and request["requester_id"] != actor.actor_id:
                raise forbidden()
            if request["status"] not in allowed:
                raise conflict("INVALID_STATE_TRANSITION", f"Cannot {command} from {request['status']}.")
            revision = request["revision"] + 1
            await session.execute(
                text(
                    "UPDATE catalog_change_requests SET status=:status,revision=:revision,updated_at=now(),"
                    "decision_reason=:reason,decided_by=:decided_by WHERE request_id=:request"
                ),
                {
                    "status": result,
                    "revision": revision,
                    "reason": reason,
                    "decided_by": actor.actor_id if command in {"approve", "reject", "retry-fulfillment"} else None,
                    "request": request_id,
                },
            )
            if command in {"approve", "reject"}:
                await session.execute(
                    text(
                        "INSERT INTO catalog_approvals "
                        "(tenant_id,approval_id,request_id,approver_id,decision,reason) VALUES "
                        "(:tenant,:approval,:request,:approver,:decision,:reason)"
                    ),
                    {
                        "tenant": actor.tenant_id,
                        "approval": _id("approval"),
                        "request": request_id,
                        "approver": actor.actor_id,
                        "decision": "approved" if command == "approve" else "rejected",
                        "reason": reason,
                    },
                )
            attempt_id = None
            if create_attempt:
                attempt_no = int(
                    (
                        await session.execute(
                            text(
                                "SELECT COALESCE(max(attempt_no),0)+1 FROM catalog_fulfillment_attempts "
                                "WHERE request_id=:request"
                            ),
                            {"request": request_id},
                        )
                    ).scalar_one()
                )
                attempt_id = _id("fulfillment")
                await session.execute(
                    text(
                        "INSERT INTO catalog_fulfillment_attempts "
                        "(tenant_id,attempt_id,request_id,attempt_no,status,requested_by) "
                        "VALUES (:tenant,:attempt,:request,:number,'pending',:actor)"
                    ),
                    {
                        "tenant": actor.tenant_id,
                        "attempt": attempt_id,
                        "request": request_id,
                        "number": attempt_no,
                        "actor": actor.actor_id,
                    },
                )
                await self._outbox(
                    session,
                    actor,
                    "ecmc.catalog_request.fulfillment_requested",
                    "catalog_change_request",
                    request_id,
                    {"request_id": request_id, "attempt_id": attempt_id, "request_type": request["request_type"]},
                    idempotency_key,
                    f"catalog-owner:{request['request_type']}",
                )
            body = {
                "request_id": request_id,
                "status": result,
                "revision": revision,
                "fulfillment_attempt_id": attempt_id,
            }
            await self._audit(
                session,
                actor,
                f"ecmc.catalog_request.{command}",
                "catalog_change_request",
                request_id,
                body,
            )
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def complete_fulfillment(
        self,
        actor: ActorContext,
        request_id: str,
        attempt_id: str,
        *,
        resolved_ref: CatalogRef | None,
        sanitized_error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Internal owner callback; deliberately not exposed as public HTTP."""
        async with tenant_session(self.engine, actor.tenant_id) as session:
            request, scope = await self._request(session, actor, request_id, for_update=True)
            self._require_permission(scope, "ecmc.catalog.approve")
            if request["status"] != "approved_pending_fulfillment":
                raise conflict("INVALID_STATE_TRANSITION", "Request is not awaiting fulfillment.")
            attempt = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM catalog_fulfillment_attempts WHERE request_id=:request "
                            "AND attempt_id=:attempt FOR UPDATE"
                        ),
                        {"request": request_id, "attempt": attempt_id},
                    )
                )
                .mappings()
                .first()
            )
            if attempt is None or attempt["status"] != "pending":
                raise conflict("INVALID_STATE_TRANSITION", "Fulfillment attempt is not pending.")
            if resolved_ref is not None:
                domain = request["target_data_domain_ref"]["stable_id"]
                resolved = await self.catalog.resolve(
                    actor.tenant_id,
                    resolved_ref,
                    request["request_type"],
                    context=CatalogValidationContext(
                        actor.tenant_id, domain, {"resource_type": "catalog_change_request", "request_id": request_id}
                    ),
                )
                await session.execute(
                    text(
                        "UPDATE catalog_fulfillment_attempts SET status='success',resolved_ref=:ref,finished_at=now() "
                        "WHERE attempt_id=:attempt"
                    ),
                    {"ref": _json(resolved.catalog_ref().model_dump(mode="json")), "attempt": attempt_id},
                )
                await session.execute(
                    text(
                        "UPDATE catalog_change_requests SET status='fulfilled',resolved_ref=:ref,fulfillment_error=NULL,"
                        "revision=revision+1,updated_at=now() WHERE request_id=:request"
                    ),
                    {"ref": _json(resolved.catalog_ref().model_dump(mode="json")), "request": request_id},
                )
                status = "fulfilled"
            else:
                error = sanitized_error or {"code": "CATALOG_FULFILLMENT_FAILED"}
                await session.execute(
                    text(
                        "UPDATE catalog_fulfillment_attempts SET status='failed',sanitized_error=:error,finished_at=now() "
                        "WHERE attempt_id=:attempt"
                    ),
                    {"error": _json(error), "attempt": attempt_id},
                )
                await session.execute(
                    text(
                        "UPDATE catalog_change_requests SET status='fulfillment_failed',fulfillment_error=:error,"
                        "revision=revision+1,updated_at=now() WHERE request_id=:request"
                    ),
                    {"error": _json(error), "request": request_id},
                )
                status = "fulfillment_failed"
            await self._audit(
                session,
                actor,
                "ecmc.catalog_request.fulfillment_completed",
                "catalog_change_request",
                request_id,
                {"attempt_id": attempt_id, "status": status},
            )
            return {"request_id": request_id, "attempt_id": attempt_id, "status": status}

    async def fulfill_pack_publish(
        self,
        actor: ActorContext,
        request_id: str,
        attempt_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Fulfill an approved Pack request without accepting client content or hash."""
        operation = f"catalog-pack.publish.fulfill:{request_id}"
        payload = {"request_id": request_id, "attempt_id": attempt_id}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            request, scope = await self._request(session, actor, request_id, for_update=True)
            self._require_permission(scope, "ecmc.catalog.approve")
            if request["request_type"] != "pack_publish":
                raise conflict("REQUEST_TYPE_MISMATCH", "Request is not a Pack publication request.")
            if request["status"] != "approved_pending_fulfillment":
                raise conflict("INVALID_STATE_TRANSITION", "Pack request is not awaiting fulfillment.")
            attempt = (
                (
                    await session.execute(
                        text(
                            "SELECT status FROM catalog_fulfillment_attempts "
                            "WHERE tenant_id=:tenant AND request_id=:request AND attempt_id=:attempt FOR UPDATE"
                        ),
                        {"tenant": actor.tenant_id, "request": request_id, "attempt": attempt_id},
                    )
                )
                .mappings()
                .first()
            )
            if attempt is None or attempt["status"] != "pending":
                raise conflict("INVALID_STATE_TRANSITION", "Pack fulfillment attempt is not pending.")
            pack = (
                (
                    await session.execute(
                        text(
                            "SELECT p.pack_id,p.version,p.layer,p.status FROM catalog_packs p "
                            "WHERE p.tenant_id=:tenant AND p.pack_id || '@' || p.version=:resource FOR UPDATE"
                        ),
                        {"tenant": actor.tenant_id, "resource": request["resource_id"]},
                    )
                )
                .mappings()
                .first()
            )
            if pack is None:
                raise not_found("CATALOG_PACK_NOT_FOUND", "Pack was not found.")
            if pack["status"] != "draft":
                raise conflict("INVALID_STATE_TRANSITION", "Only a draft Pack can be fulfilled.")
            entries = (
                await session.execute(
                    text(
                        "SELECT kind,stable_id,version,content_hash FROM catalog_pack_entries "
                        "WHERE tenant_id=:tenant AND pack_id=:pack_id AND pack_version=:version"
                    ),
                    {"tenant": actor.tenant_id, "pack_id": pack["pack_id"], "version": pack["version"]},
                )
            ).mappings()
            try:
                digest = pack_content_hash(
                    pack["pack_id"], pack["layer"], pack["version"], [dict(item) for item in entries]
                )
            except CatalogCompositionError as error:
                raise conflict("PACK_HASH_INVALID", str(error)) from error
            updated = await session.execute(
                text(
                    "UPDATE catalog_packs SET content_hash=:hash,status='published',published_at=now() "
                    "WHERE tenant_id=:tenant AND pack_id=:pack_id AND version=:version AND status='draft'"
                ),
                {
                    "tenant": actor.tenant_id,
                    "pack_id": pack["pack_id"],
                    "version": pack["version"],
                    "hash": digest,
                },
            )
            if getattr(updated, "rowcount", 0) != 1:
                raise conflict("PACK_PUBLICATION_CONFLICT", "Pack publication conflicted; retry from current state.")
            resolved = {
                "resource_type": "catalog_pack",
                "pack_id": pack["pack_id"],
                "version": pack["version"],
                "content_hash": digest,
            }
            await session.execute(
                text(
                    "UPDATE catalog_fulfillment_attempts SET status='success',resolved_ref=:resolved,finished_at=now() "
                    "WHERE tenant_id=:tenant AND request_id=:request AND attempt_id=:attempt"
                ),
                {
                    "tenant": actor.tenant_id,
                    "request": request_id,
                    "attempt": attempt_id,
                    "resolved": _json(resolved),
                },
            )
            await session.execute(
                text(
                    "UPDATE catalog_change_requests SET status='fulfilled',resolved_ref=:resolved,"
                    "fulfillment_error=NULL,revision=revision+1,updated_at=now() "
                    "WHERE tenant_id=:tenant AND request_id=:request"
                ),
                {"tenant": actor.tenant_id, "request": request_id, "resolved": _json(resolved)},
            )
            await session.execute(
                text(
                    "INSERT INTO catalog_audit_logs "
                    "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,after_hash,status,"
                    "correlation_id,detail) VALUES "
                    "(:tenant,:audit,:actor,'catalog_pack',:resource,'publish',:hash,'succeeded',:correlation,"
                    "CAST(:detail AS jsonb))"
                ),
                {
                    "tenant": actor.tenant_id,
                    "audit": _id("caud"),
                    "actor": actor.actor_id,
                    "resource": request["resource_id"],
                    "hash": digest,
                    "correlation": actor.correlation_id,
                    "detail": _json({"request_id": request_id, "attempt_id": attempt_id}),
                },
            )
            body = {
                "request_id": request_id,
                "attempt_id": attempt_id,
                "status": "fulfilled",
                **resolved,
            }
            await self._audit(
                session, actor, "ecmc.catalog_pack.published", "catalog_pack", request["resource_id"], body
            )
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    @staticmethod
    async def _review(
        session: AsyncSession,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        action: str,
        decision: str,
        reason: str | None,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO causal_model_reviews "
                "(tenant_id,review_id,model_id,model_version_id,action,decision,reason,actor_id,role_id,policy_snapshot) "
                "VALUES (:tenant,:review,:model,:version,:action,:decision,:reason,:actor,:role,:policy)"
            ),
            {
                "tenant": actor.tenant_id,
                "review": _id("review"),
                "model": model_id,
                "version": version_id,
                "action": action,
                "decision": decision,
                "reason": reason,
                "actor": actor.actor_id,
                "role": actor.role_id,
                "policy": _json({"separation_of_duties": True}),
            },
        )

    async def reject_review(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.reject:{version_id}"
        payload = {"reason": reason, "expected_revision": expected_revision}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.review")
            version = await self._version(session, actor, model_id, version_id, for_update=True)
            self._revision(version, expected_revision)
            if version["status"] != "in_review":
                raise conflict("INVALID_STATE_TRANSITION", "Only an in-review version can be rejected.")
            revision = expected_revision + 1
            await session.execute(
                text(
                    "UPDATE causal_model_versions SET status='draft',revision=:revision,reviewed_at=now(),"
                    "reviewed_by=:actor,updated_by=:actor,updated_at=now() WHERE model_version_id=:version"
                ),
                {"revision": revision, "actor": actor.actor_id, "version": version_id},
            )
            await self._review(session, actor, model_id, version_id, "reject", "rejected", reason)
            body = {"model_version_id": version_id, "status": "draft", "revision": revision}
            await self._audit(session, actor, "ecmc.causal_model.rejected", "causal_model_version", version_id, body)
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def publish(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.publish:{version_id}"
        payload = {"expected_revision": expected_revision}
        blocked: dict[str, Any] | None = None
        response: dict[str, Any] | None = None
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.review")
            model = await self._model(session, actor, model_id, for_update=True)
            version = await self._version(session, actor, model_id, version_id, for_update=True)
            self._revision(version, expected_revision)
            if version["status"] != "in_review":
                raise conflict("INVALID_STATE_TRANSITION", "Only an in-review version can be published.")
            if not scope.is_admin and version["submitted_by"] == actor.actor_id:
                raise forbidden("PERMISSION_DENIED", "Submitter and reviewer must be separated by policy.")
            validation, snapshot_payload = await self._analyze(session, actor, model, version, "final")
            if validation["result"] == "failed" or snapshot_payload is None:
                blocked = validation
                error_body = {"code": "MODEL_VALIDATION_FAILED", "details": {"validation_result": validation}}
                await self._remember(session, actor, operation, idempotency_key, payload, 422, error_body)
            else:
                content_hash = canonical_hash(snapshot_payload, CAUSAL_SNAPSHOT_SCHEMA)
                snapshot_id = _id("cms")
                await session.execute(
                    text(
                        "INSERT INTO causal_model_snapshots "
                        "(tenant_id,snapshot_id,model_version_id,content_hash,nodes_json,edges_json,rules_json,requirements_json,"
                        "applicability_snapshot,schema_version,canonical_payload,canonicalizer_version,diagnostic_target,"
                        "catalog_resolutions,semantic_schema_versions) "
                        "VALUES (:tenant,:snapshot,:version,:hash,:nodes,:edges,:rules,:requirements,:applicability,"
                        ":schema,:payload,:canonicalizer,:target,:resolutions,:semantic_versions)"
                    ),
                    {
                        "tenant": actor.tenant_id,
                        "snapshot": snapshot_id,
                        "version": version_id,
                        "hash": content_hash,
                        "nodes": _json(snapshot_payload["nodes"]),
                        "edges": _json(snapshot_payload["edges"]),
                        "rules": _json(snapshot_payload["rules"]),
                        "requirements": _json(snapshot_payload["evidence_requirements"]),
                        "applicability": _json(snapshot_payload["applicability"]),
                        "schema": CAUSAL_SNAPSHOT_SCHEMA,
                        "payload": canonical_json(snapshot_payload, CAUSAL_SNAPSHOT_SCHEMA),
                        "canonicalizer": CANONICALIZER_VERSION,
                        "target": _json(snapshot_payload["diagnostic_target"]),
                        "resolutions": _json(snapshot_payload["catalog_resolutions"]),
                        "semantic_versions": _json(snapshot_payload["semantic_schema_versions"]),
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO causal_snapshot_validation_runs "
                        "(tenant_id,run_id,snapshot_id,result,detail,finished_at) "
                        "VALUES (:tenant,:run,:snapshot,'passed',:detail,now())"
                    ),
                    {
                        "tenant": actor.tenant_id,
                        "run": _id("svr"),
                        "snapshot": snapshot_id,
                        "detail": _json({"validator_version": "n01a/v1", "content_hash": content_hash}),
                    },
                )
                revision = expected_revision + 1
                await session.execute(
                    text(
                        "UPDATE causal_model_versions SET status='published',published_snapshot_id=:snapshot,"
                        "published_at=now(),reviewed_at=now(),reviewed_by=:actor,updated_by=:actor,updated_at=now(),"
                        "revision=:revision WHERE model_version_id=:version"
                    ),
                    {"snapshot": snapshot_id, "actor": actor.actor_id, "revision": revision, "version": version_id},
                )
                await self._review(session, actor, model_id, version_id, "publish", "approved", None)
                event_payload = {
                    "tenant_id": actor.tenant_id,
                    "model_id": model_id,
                    "model_version_id": version_id,
                    "snapshot_id": snapshot_id,
                    "content_hash": content_hash,
                    "schema_version": CAUSAL_SNAPSHOT_SCHEMA,
                    "correlation_id": actor.correlation_id,
                }
                await self._outbox(
                    session,
                    actor,
                    "ecmc.causal_model.published",
                    "causal_model_version",
                    version_id,
                    event_payload,
                    idempotency_key,
                    "causal-compiler",
                )
                response = {
                    **event_payload,
                    "status": "published",
                    "revision": revision,
                    "activation_status": "inactive",
                }
                await self._audit(
                    session, actor, "ecmc.causal_model.published", "causal_model_version", version_id, response
                )
                await self._remember(session, actor, operation, idempotency_key, payload, 200, response)
        if blocked is not None:
            raise validation_failed(blocked)
        assert response is not None
        return {"status_code": 200, "body": response, "replayed": False}

    async def patch_version(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        applicability: dict[str, Any] | None,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.version.patch:{version_id}"
        payload = {"applicability": applicability}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            await self._draft_for_write(session, actor, model_id, version_id, expected_revision)
            await session.execute(
                text("UPDATE causal_model_versions SET applicability=:value WHERE model_version_id=:version"),
                {"value": _json(applicability or {}), "version": version_id},
            )
            revision = await self._finish_draft_write(
                session, actor, version_id, "ecmc.causal_version.saved", {"field": "applicability"}
            )
            body = {"model_version_id": version_id, "revision": revision, "applicability": applicability or {}}
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def governance(self, actor: ActorContext, model_id: str, version_id: str) -> dict[str, Any]:
        async with tenant_session(self.engine, actor.tenant_id) as session:
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.audit.read")
            model = await self._model(session, actor, model_id)
            version = await self._version(session, actor, model_id, version_id)
            compile_record = (
                (
                    await session.execute(
                        text(
                            "SELECT compile_id,status,retry_of_compile_id,artifact_schema_version,compiled_artifact_hash "
                            "FROM blueprint_compile_records WHERE model_version_id=:version AND n01a_attempt=true "
                            "ORDER BY started_at DESC LIMIT 1"
                        ),
                        {"version": version_id},
                    )
                )
                .mappings()
                .first()
            )
            delivery_status = None
            if compile_record is not None:
                delivery_status = (
                    await session.execute(
                        text(
                            "SELECT delivery.status FROM outbox_deliveries delivery JOIN outbox_events event "
                            "ON event.tenant_id=delivery.tenant_id AND event.event_id=delivery.event_id "
                            "WHERE event.aggregate_id=:compile ORDER BY delivery.created_at DESC LIMIT 1"
                        ),
                        {"compile": compile_record["compile_id"]},
                    )
                ).scalar_one_or_none()
            active = model["active_model_version_id"] == version_id
            if active:
                readiness = "active"
            elif compile_record is None:
                readiness = "not_activated"
            elif compile_record["status"] == "running":
                readiness = "compiling"
            elif compile_record["status"] == "failed":
                readiness = "compile_failed"
            elif compile_record["status"] == "success":
                readiness = "ready_to_activate"
            else:
                readiness = "compile_delivery_pending"
            return {
                "model_id": model_id,
                "model_version_id": version_id,
                "governance_status": version["status"],
                "compile_record": (
                    {
                        "compile_record_id": compile_record["compile_id"],
                        "status": compile_record["status"],
                        "retry_of_compile_id": compile_record["retry_of_compile_id"],
                        "artifact_schema_version": compile_record["artifact_schema_version"],
                        "compiled_artifact_hash": compile_record["compiled_artifact_hash"],
                    }
                    if compile_record
                    else None
                ),
                "delivery_status": delivery_status,
                "activation_status": "active" if active else "inactive",
                "runtime_readiness": readiness,
                "active_pointer": {
                    "model_version_id": model["active_model_version_id"],
                    "snapshot_id": model["active_snapshot_id"],
                },
            }

    async def artifact(self, actor: ActorContext, model_id: str, version_id: str, compile_id: str) -> dict[str, Any]:
        async with tenant_session(self.engine, actor.tenant_id) as session:
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.audit.read")
            await self._version(session, actor, model_id, version_id)
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT compiled_artifact_json,compiled_artifact_hash,artifact_schema_version,status "
                            "FROM blueprint_compile_records WHERE compile_id=:compile AND model_version_id=:version "
                            "AND n01a_attempt=true"
                        ),
                        {"compile": compile_id, "version": version_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise not_found("MODEL_VERSION_NOT_FOUND", "Compile Artifact was not found.")
            if row["status"] != "success":
                raise conflict("INVALID_STATE_TRANSITION", "Only a success Attempt has a Candidate Artifact.")
            return {
                "compile_record_id": compile_id,
                "artifact_schema_version": row["artifact_schema_version"],
                "compiled_artifact_hash": row["compiled_artifact_hash"],
                "compiled_artifact": row["compiled_artifact_json"],
            }

    async def patch_request(
        self,
        actor: ActorContext,
        request_id: str,
        patch: PatchCatalogChangeRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"catalog-change-request.patch:{request_id}"
        payload = patch.model_dump(mode="json", exclude_none=True)
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            request, scope = await self._request(session, actor, request_id, for_update=True)
            self._require_permission(scope, "ecmc.catalog.request")
            if request["requester_id"] != actor.actor_id or request["status"] != "draft":
                raise conflict("INVALID_STATE_TRANSITION", "Only the requester can edit their draft request.")
            definition = patch.proposed_definition.model_dump(mode="json") if patch.proposed_definition else None
            if definition is not None and definition["kind"] != request["request_type"]:
                raise N01AError("REQUEST_SCHEMA_INVALID", "Definition kind cannot change.", 422)
            revision = request["revision"] + 1
            await session.execute(
                text(
                    "UPDATE catalog_change_requests SET rationale=COALESCE(:rationale,rationale),"
                    "proposed_definition=COALESCE(:definition,proposed_definition),revision=:revision,updated_at=now() "
                    "WHERE request_id=:request"
                ),
                {
                    "rationale": patch.rationale,
                    "definition": _json(definition) if definition is not None else None,
                    "revision": revision,
                    "request": request_id,
                },
            )
            body = {"request_id": request_id, "status": "draft", "revision": revision}
            await self._audit(session, actor, "ecmc.catalog_request.saved", "catalog_change_request", request_id, body)
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}


# Both names intentionally resolve to the same bounded-context service.  The
# alias keeps call sites explicit without duplicating transaction helpers.
CatalogChangeRequestService = CausalModelService
