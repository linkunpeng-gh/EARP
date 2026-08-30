"""Pinned, provider-free Case A reasoning Prepare service.

Prepare is the boundary between a compiled Blueprint's static method skeleton and
the dynamic evidence plan.  It resolves only the immutable source snapshot and
the tenant ABox.  In particular, it intentionally has no dependency on the
Capability Registry, connectors, credentials, or runtime provider readiness.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.bmc.metamodel import canonical_json_hash
from earp_server.infra.db import tenant_session

_BINDING_LANGUAGE = "case-a-abox-binding/v1"
_MODE_TO_ALGORITHM_VERSION = {
    "causal_diagnosis": "sign-propagation-v1-fixture",
    # The frozen Case A request uses explainable as its user-facing mode.
    "explainable": "sign-propagation-v1-fixture",
}


class ReasoningPrepareError(ValueError):
    """A Blueprint, source pin, goal binding, or ABox cannot be prepared safely."""


@dataclass(frozen=True)
class PrepareResult:
    tenant_id: str
    prepare_id: str
    blueprint_version_id: str
    snapshot_id: str
    snapshot_hash: str
    algorithm_version_id: str
    context_hash: str
    status: str
    requirements: tuple[dict[str, Any], ...]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[: 64 - len(prefix) - 1]}"


async def _one(session: AsyncSession, statement: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
    result = await session.execute(text(statement), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


def _normalize_time_window(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ReasoningPrepareError("goal binding time_window is required")
    start, end = value.get("start"), value.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ReasoningPrepareError("time_window requires ISO-8601 start and end")
    try:
        start_at, end_at = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError as error:
        raise ReasoningPrepareError("time_window requires ISO-8601 start and end") from error
    if start_at.tzinfo is None or end_at.tzinfo is None or start_at >= end_at:
        raise ReasoningPrepareError("time_window must be an ordered, timezone-aware interval")
    normalized = {"start": start_at.isoformat(), "end": end_at.isoformat()}
    if isinstance(value.get("business_date"), str):
        normalized["business_date"] = value["business_date"]
    if isinstance(value.get("boundary_rule"), str):
        normalized["boundary_rule"] = value["boundary_rule"]
    return normalized


def _normalize_authz_scope(value: object, entity_id: str) -> dict[str, Any]:
    """Make the permission input explicit without inventing an auth service.

    Case A has no independent authorization aggregate.  A caller may omit the
    scope, which means the bound entity only; a supplied scope must be a concrete
    list and must contain the target.  This fails closed rather than allowing an
    empty/ambiguous scope to silently broaden a Prepare.
    """
    if value is None:
        return {"scope_version": "case-a-implicit-target/v1", "allowed_entity_ids": [entity_id]}
    if not isinstance(value, Mapping):
        raise ReasoningPrepareError("authorization scope must be an object")
    entity_ids = value.get("allowed_entity_ids")
    if (
        not isinstance(entity_ids, list)
        or not entity_ids
        or not all(isinstance(item, str) and item for item in entity_ids)
    ):
        raise ReasoningPrepareError("authorization scope requires non-empty allowed_entity_ids")
    if entity_id not in entity_ids:
        raise ReasoningPrepareError("authorization scope excludes the goal entity")
    normalized = dict(value)
    normalized["allowed_entity_ids"] = sorted(set(entity_ids))
    return normalized


async def _load_blueprint_source(
    session: AsyncSession, tenant_id: str, blueprint_version_id: str, goal_skeleton_id: str | None
) -> dict[str, Any]:
    source = await _one(
        session,
        "SELECT version.blueprint_version_id, source.source_ref_id, source.model_id, source.model_version, "
        "source.source_snapshot_id, source.source_content_hash, snapshot.model_version_id, snapshot.content_hash, "
        "snapshot.nodes_json, snapshot.requirements_json, snapshot.applicability_snapshot, "
        "model_version.applicability AS model_applicability "
        "FROM planning_blueprint_versions AS version "
        "JOIN blueprint_source_models AS source ON source.tenant_id = version.tenant_id "
        " AND source.blueprint_version_id = version.blueprint_version_id "
        "JOIN causal_model_snapshots AS snapshot ON snapshot.tenant_id = source.tenant_id "
        " AND snapshot.snapshot_id = source.source_snapshot_id "
        "JOIN causal_model_versions AS model_version ON model_version.tenant_id = snapshot.tenant_id "
        " AND model_version.model_version_id = snapshot.model_version_id "
        "WHERE version.tenant_id = :tenant_id AND version.blueprint_version_id = :blueprint_version_id "
        " AND version.status = 'compiled' AND source.model_type = 'causal' AND source.model_role = 'primary_model'",
        {"tenant_id": tenant_id, "blueprint_version_id": blueprint_version_id},
    )
    if source is None:
        raise ReasoningPrepareError("compiled Blueprint Version with a causal source was not found for this tenant")
    if source["source_content_hash"] != source["content_hash"]:
        raise ReasoningPrepareError("Blueprint source pin does not match immutable Snapshot hash")
    validation = await _one(
        session,
        "SELECT run_id FROM causal_snapshot_validation_runs WHERE tenant_id = :tenant_id "
        "AND snapshot_id = :snapshot_id AND result = 'passed' ORDER BY finished_at DESC NULLS LAST LIMIT 1",
        {"tenant_id": tenant_id, "snapshot_id": source["source_snapshot_id"]},
    )
    if validation is None:
        raise ReasoningPrepareError("Blueprint source Snapshot has no passed validation run")
    goal_query = (
        "SELECT objective, required_bindings FROM blueprint_goal_skeletons WHERE tenant_id = :tenant_id "
        "AND blueprint_version_id = :blueprint_version_id AND objective = 'diagnose'"
    )
    goal_params: dict[str, Any] = {"tenant_id": tenant_id, "blueprint_version_id": blueprint_version_id}
    if goal_skeleton_id is not None:
        goal_query += " AND goal_skeleton_id = :goal_skeleton_id"
        goal_params["goal_skeleton_id"] = goal_skeleton_id
    goal = await _one(session, goal_query, goal_params)
    if goal is None or not {"entity_id", "time_window"} <= set(goal["required_bindings"]):
        raise ReasoningPrepareError("Blueprint goal skeleton is incompatible with Case A Prepare")
    return source


async def _load_algorithm(session: AsyncSession, reasoning_mode: str, graph_type: object) -> dict[str, Any]:
    version_id = _MODE_TO_ALGORITHM_VERSION.get(reasoning_mode)
    if version_id is None:
        raise ReasoningPrepareError("unsupported Case A reasoning_mode")
    algorithm = await _one(
        session,
        "SELECT algorithm_version_id, algorithm_id, profile_version, profile_json, algorithm_config_hash, "
        "algorithm_config_json, status FROM reasoning_algorithm_versions "
        "WHERE algorithm_version_id = :algorithm_version_id AND status IN ('active', 'beta')",
        {"algorithm_version_id": version_id},
    )
    if algorithm is None or algorithm["algorithm_id"] != "sign_propagation":
        raise ReasoningPrepareError("required Case A reasoning algorithm version is unavailable")
    if algorithm["profile_json"].get("graph_type") != graph_type:
        raise ReasoningPrepareError("Snapshot and algorithm profile graph types are incompatible")
    if not algorithm["algorithm_config_hash"] or not isinstance(algorithm["algorithm_config_json"], dict):
        raise ReasoningPrepareError("algorithm configuration identity is incomplete")
    return algorithm


async def _entity(session: AsyncSession, tenant_id: str, entity_id: str) -> dict[str, Any]:
    entity = await _one(
        session,
        "SELECT entity_id, entity_type_id, name, business_code, data_domain_id FROM entities "
        "WHERE tenant_id = :tenant_id AND entity_id = :entity_id AND status = 'active'",
        {"tenant_id": tenant_id, "entity_id": entity_id},
    )
    if entity is None:
        raise ReasoningPrepareError("goal entity is unknown, inactive, or outside this tenant")
    return entity


def _is_applicable(source: Mapping[str, Any], entity: Mapping[str, Any]) -> bool:
    applicability = source["applicability_snapshot"]
    model_applicability = source["model_applicability"]
    allowed_types = applicability.get("entity_types") if isinstance(applicability, dict) else None
    if not isinstance(allowed_types, list) or entity["entity_type_id"] not in allowed_types:
        return False
    if isinstance(model_applicability, dict):
        model_types = model_applicability.get("entity_types")
        if isinstance(model_types, list) and entity["entity_type_id"] not in model_types:
            return False
    return True


async def _resolve_requirement_target(
    session: AsyncSession, tenant_id: str, context_entity: Mapping[str, Any], requirement: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    binding = requirement.get("instance_binding")
    if not isinstance(binding, Mapping) or binding.get("binding_language") != _BINDING_LANGUAGE:
        raise ReasoningPrepareError("requirement has an unsupported ABox binding language")
    expression = binding.get("expression")
    if not isinstance(expression, Mapping):
        raise ReasoningPrepareError("requirement ABox binding expression is missing")
    if expression.get("cardinality") != "exactly_one":
        raise ReasoningPrepareError("Case A requirement binding must resolve exactly one target")
    operation = expression.get("op")
    if operation == "context_entity":
        if context_entity["entity_type_id"] != expression.get("expected_entity_type_id"):
            raise ReasoningPrepareError("context entity type is incompatible with requirement binding")
        return dict(context_entity), []
    if operation != "outbound_relation" or expression.get("from") != "context.entity_id":
        raise ReasoningPrepareError("unsupported Case A ABox binding operation")
    relation_type_id = expression.get("relation_type_id")
    target_type = expression.get("target_entity_type_id")
    if not isinstance(relation_type_id, str) or not isinstance(target_type, str):
        raise ReasoningPrepareError("outbound relation binding is incomplete")
    result = await session.execute(
        text(
            "SELECT target.entity_id, target.entity_type_id, target.name, target.business_code, target.data_domain_id, "
            "fact.fact_id, fact.relation_type_id, fact.confidence "
            "FROM facts AS fact JOIN entities AS target ON target.tenant_id = fact.tenant_id "
            " AND target.entity_id = fact.target_entity_id "
            "JOIN relation_types AS relation ON relation.tenant_id = fact.tenant_id "
            " AND relation.relation_type_id = fact.relation_type_id "
            "WHERE fact.tenant_id = :tenant_id AND fact.source_entity_id = :source_entity_id "
            " AND fact.relation_type_id = :relation_type_id AND fact.status = 'active' AND target.status = 'active' "
            " AND target.entity_type_id = :target_type "
            " AND position(:source_type in relation.source_type) > 0 "
            " AND position(:target_type in relation.target_type) > 0"
        ),
        {
            "tenant_id": tenant_id,
            "source_entity_id": context_entity["entity_id"],
            "relation_type_id": relation_type_id,
            "target_type": target_type,
            "source_type": context_entity["entity_type_id"],
        },
    )
    rows = [dict(row) for row in result.mappings()]
    # Duplicated facts to the same target are still ambiguous evidence graph input.
    if len(rows) != 1:
        raise ReasoningPrepareError("outbound requirement binding resolved zero or multiple ABox targets")
    row = rows[0]
    fact = {key: row.pop(key) for key in ("fact_id", "relation_type_id", "confidence")}
    fact["source_entity_id"] = context_entity["entity_id"]
    fact["target_entity_id"] = row["entity_id"]
    return row, [fact]


def _requirement_sort_key(item: object) -> str:
    """Stable sort key for pinned evidence requirements; missing key sorts first."""
    if not isinstance(item, Mapping):
        return ""
    key = item.get("requirement_key")
    return key if isinstance(key, str) else ""


async def prepare_case_a_reasoning(
    engine: AsyncEngine,
    tenant_id: str,
    blueprint_version_id: str,
    goal_bindings: Mapping[str, Any],
    *,
    goal_skeleton_id: str | None = None,
    reasoning_mode: str = "causal_diagnosis",
    authz_scope: Mapping[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> PrepareResult:
    """Resolve a Blueprint-pinned Case A context without contacting any provider.

    ``goal_bindings`` must carry ``entity_id`` and a timezone-aware
    ``time_window``.  The result's `requirements` are logical requirements for
    T09; provider selection is deliberately absent.
    """
    entity_id = goal_bindings.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id:
        raise ReasoningPrepareError("goal binding entity_id is required")
    time_window = _normalize_time_window(goal_bindings.get("time_window"))
    scope = _normalize_authz_scope(authz_scope, entity_id)
    now = datetime.now(UTC)
    expiry = expires_at or now + timedelta(hours=1)
    if expiry.tzinfo is None or expiry <= now:
        raise ReasoningPrepareError("Prepare expiry must be in the future and timezone-aware")

    async with tenant_session(engine, tenant_id) as session:
        source = await _load_blueprint_source(session, tenant_id, blueprint_version_id, goal_skeleton_id)
        context_entity = await _entity(session, tenant_id, entity_id)
        if not _is_applicable(source, context_entity):
            raise ReasoningPrepareError("goal entity is outside the pinned Snapshot applicability")
        algorithm = await _load_algorithm(
            session, reasoning_mode, source["applicability_snapshot"].get("graph_type", "dag")
        )

        identity = {
            "tenant_id": tenant_id,
            "blueprint_version_id": blueprint_version_id,
            "goal_skeleton_id": goal_skeleton_id,
            "source_snapshot_id": source["source_snapshot_id"],
            "source_snapshot_hash": source["source_content_hash"],
            "entity_id": entity_id,
            "time_window": time_window,
            "reasoning_mode": reasoning_mode,
            "algorithm_version_id": algorithm["algorithm_version_id"],
            "algorithm_config_hash": algorithm["algorithm_config_hash"],
            "authz_scope_hash": canonical_json_hash(scope),
        }
        prepare_id = _stable_id("prepare", identity)
        existing = await _one(
            session,
            "SELECT status, context_hash, evidence_requirements FROM reasoning_contexts "
            "WHERE tenant_id = :tenant_id AND prepare_id = :prepare_id",
            {"tenant_id": tenant_id, "prepare_id": prepare_id},
        )
        if existing is not None:
            if existing["status"] != "prepared":
                raise ReasoningPrepareError(f"existing Prepare is {existing['status']} and cannot be reused")
            return PrepareResult(
                tenant_id,
                prepare_id,
                blueprint_version_id,
                source["source_snapshot_id"],
                source["source_content_hash"],
                algorithm["algorithm_version_id"],
                existing["context_hash"],
                existing["status"],
                tuple(existing["evidence_requirements"]),
            )

        requirements: list[dict[str, Any]] = []
        entities: dict[str, dict[str, Any]] = {entity_id: dict(context_entity)}
        facts: list[dict[str, Any]] = []
        source_requirements = source["requirements_json"]
        if not isinstance(source_requirements, list) or not source_requirements:
            raise ReasoningPrepareError("pinned Snapshot has no evidence requirements")
        for requirement in sorted(source_requirements, key=_requirement_sort_key):
            if not isinstance(requirement, Mapping):
                raise ReasoningPrepareError("pinned Snapshot requirement is malformed")
            stable_key = requirement.get("requirement_key")
            source_requirement_id = requirement.get("requirement_id")
            if not isinstance(stable_key, str) or not isinstance(source_requirement_id, str):
                raise ReasoningPrepareError("pinned Snapshot requirement identity is incomplete")
            target, target_facts = await _resolve_requirement_target(session, tenant_id, context_entity, requirement)
            entities[target["entity_id"]] = target
            facts.extend(target_facts)
            requirements.append(
                {
                    "requirement_id": _stable_id(
                        "req", {"prepare_id": prepare_id, "source_requirement_id": source_requirement_id}
                    ),
                    "source_requirement_id": source_requirement_id,
                    "requirement_key": stable_key,
                    "node_key": requirement.get("node_key"),
                    "requirement_level": requirement.get("requirement_level"),
                    "capability_contract_ref": requirement.get("capability_contract_ref"),
                    "unit": requirement.get("unit"),
                    "aggregation": requirement.get("aggregation"),
                    "target_entity_id": target["entity_id"],
                    "target_entity_type": target["entity_type_id"],
                    "time_window": time_window,
                }
            )
        if len({item["requirement_id"] for item in requirements}) != len(requirements):
            raise ReasoningPrepareError("generated requirement identities are not unique")

        instance_snapshot = {
            "schema_version": "case-a-instantiated-abox/v1",
            "context_entity": context_entity,
            "entities": [entities[key] for key in sorted(entities)],
            "facts": sorted(facts, key=lambda item: item["fact_id"]),
        }
        scope_meta = {
            "blueprint_version_id": blueprint_version_id,
            "blueprint_source_ref_id": source["source_ref_id"],
            "source_snapshot_id": source["source_snapshot_id"],
            "source_snapshot_hash": source["source_content_hash"],
            "authz_scope": scope,
        }
        context_payload = {
            **identity,
            "target": context_entity,
            "instance_snapshot": instance_snapshot,
            "requirements": requirements,
            "scope_meta": scope_meta,
            "algorithm_profile_version": algorithm["profile_version"],
            "algorithm_params": algorithm["algorithm_config_json"].get("params", {}),
        }
        context_hash = canonical_json_hash(context_payload)
        await session.execute(
            text(
                "INSERT INTO reasoning_contexts (tenant_id, prepare_id, model_version_id, snapshot_id, "
                "snapshot_hash, target_json, time_window_json, instance_snapshot, evidence_requirements, "
                "scope_meta, authz_scope_hash, algorithm_version_id, algorithm_profile_version, "
                "algorithm_params_json, algorithm_config_hash, context_hash, expires_at) "
                "VALUES (:tenant_id, :prepare_id, :model_version_id, :snapshot_id, :snapshot_hash, "
                ":target_json, :time_window_json, :instance_snapshot, :evidence_requirements, "
                ":scope_meta, :authz_scope_hash, :algorithm_version_id, :algorithm_profile_version, "
                ":algorithm_params_json, :algorithm_config_hash, :context_hash, "
                ":expires_at)"
            ),
            {
                "tenant_id": tenant_id,
                "prepare_id": prepare_id,
                "model_version_id": source["model_version_id"],
                "snapshot_id": source["source_snapshot_id"],
                "snapshot_hash": source["source_content_hash"],
                "target_json": _json(context_entity),
                "time_window_json": _json(time_window),
                "instance_snapshot": _json(instance_snapshot),
                "evidence_requirements": _json(requirements),
                "scope_meta": _json(scope_meta),
                "authz_scope_hash": identity["authz_scope_hash"],
                "algorithm_version_id": algorithm["algorithm_version_id"],
                "algorithm_profile_version": algorithm["profile_version"],
                "algorithm_params_json": _json(algorithm["algorithm_config_json"].get("params", {})),
                "algorithm_config_hash": algorithm["algorithm_config_hash"],
                "context_hash": context_hash,
                "expires_at": expiry,
            },
        )
        return PrepareResult(
            tenant_id,
            prepare_id,
            blueprint_version_id,
            source["source_snapshot_id"],
            source["source_content_hash"],
            algorithm["algorithm_version_id"],
            context_hash,
            "prepared",
            tuple(requirements),
        )


async def get_reasoning_context(engine: AsyncEngine, tenant_id: str, prepare_id: str) -> dict[str, Any]:
    """Read a durable Context and advance prepared contexts past their expiry."""
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "UPDATE reasoning_contexts SET status = 'expired' WHERE tenant_id = :tenant_id "
                "AND prepare_id = :prepare_id AND status = 'prepared' AND expires_at <= now()"
            ),
            {"tenant_id": tenant_id, "prepare_id": prepare_id},
        )
        context = await _one(
            session,
            "SELECT * FROM reasoning_contexts WHERE tenant_id = :tenant_id AND prepare_id = :prepare_id",
            {"tenant_id": tenant_id, "prepare_id": prepare_id},
        )
        if context is None:
            raise ReasoningPrepareError("ReasoningContext was not found for this tenant")
        return context


async def cancel_reasoning_context(engine: AsyncEngine, tenant_id: str, prepare_id: str) -> None:
    """Cancel an unused prepared Context; consumed/expired contexts stay immutable."""
    async with tenant_session(engine, tenant_id) as session:
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                text(
                    "UPDATE reasoning_contexts SET status = 'cancelled' WHERE tenant_id = :tenant_id "
                    "AND prepare_id = :prepare_id AND status = 'prepared'"
                ),
                {"tenant_id": tenant_id, "prepare_id": prepare_id},
            ),
        )
        if result.rowcount != 1:
            raise ReasoningPrepareError("only an existing prepared ReasoningContext can be cancelled")
