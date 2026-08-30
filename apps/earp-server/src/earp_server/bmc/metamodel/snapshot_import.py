"""Case A's hash-locked causal snapshot fixture import boundary.

This is deliberately a fixture consumer, not a model editor.  It validates the
raw-byte package manifest and semantic hashes before opening a tenant transaction,
then imports only the ontology prerequisites and causal source-model projection
needed by later Prepare work.  ``published_fixture`` remains a test-release
marker: the persisted causal model version stays ``testing``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.infra.db import tenant_session


class FixtureImportError(ValueError):
    """The fixture is malformed, inconsistent, or conflicts with imported state."""


FIXTURE_FILES = frozenset(
    {
        "algorithm_fixture.json",
        "capability_fixture.json",
        "causal_model_snapshot.json",
        "evidence_observations.json",
        "expected_plan.json",
        "expected_reasoning.json",
        "intent_goal_fixture.json",
        "ontology_fixture.json",
        "scenario.yaml",
    }
)
_BINDING_LANGUAGE = "case-a-abox-binding/v1"
_CAUSAL_EDGE_RELATION_REF = "causal_effect"


@dataclass(frozen=True)
class SnapshotImportResult:
    tenant_id: str
    model_id: str
    model_version_id: str
    snapshot_id: str
    snapshot_hash: str
    algorithm_version_id: str
    algorithm_config_hash: str
    validation_run_id: str
    ontology_entity_ids: tuple[str, ...]
    fixture_release_only: bool = True


@dataclass(frozen=True)
class _Fixture:
    scenario: dict[str, Any]
    model_document: dict[str, Any]
    ontology: dict[str, Any]
    algorithm_document: dict[str, Any]
    package_hash: str

    @property
    def snapshot(self) -> dict[str, Any]:
        return self.model_document["snapshot"]

    @property
    def algorithm(self) -> dict[str, Any]:
        return self.algorithm_document["algorithm"]


def canonical_json_hash(value: object) -> str:
    """The PRD's semantic-object SHA-256 representation."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FixtureImportError(f"cannot parse {path.name}") from error
    if not isinstance(value, dict):
        raise FixtureImportError(f"{path.name} must contain a JSON object")
    return value


def _load_fixture(fixture_dir: Path, tenant_id: str | None) -> _Fixture:
    manifest = _load_json(fixture_dir / "fixture_hashes.json")
    files = manifest.get("files")
    if manifest.get("schema_version") != "case-a-fixture-hashes/v1" or not isinstance(files, dict):
        raise FixtureImportError("unsupported fixture hash manifest")
    if frozenset(files) != FIXTURE_FILES:
        raise FixtureImportError("fixture hash manifest file set does not match the Case A contract")
    actual_hashes: dict[str, str] = {}
    for name, expected_hash in files.items():
        path = fixture_dir / name
        try:
            actual_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise FixtureImportError(f"fixture file missing: {name}") from error
        if not isinstance(expected_hash, str) or actual_hashes[name] != expected_hash:
            raise FixtureImportError(f"raw-byte hash mismatch for {name}")
    package_payload = "".join(f"{name}:{actual_hashes[name]}\n" for name in sorted(actual_hashes))
    package_hash = hashlib.sha256(package_payload.encode("utf-8")).hexdigest()
    if package_hash != manifest.get("package_hash"):
        raise FixtureImportError("fixture package hash mismatch")

    scenario_path = fixture_dir / "scenario.yaml"
    try:
        scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise FixtureImportError("cannot parse scenario.yaml") from error
    if not isinstance(scenario, dict):
        raise FixtureImportError("scenario.yaml must contain a mapping")
    fixture_tenant = scenario.get("request", {}).get("tenant_id")
    if not isinstance(fixture_tenant, str) or not fixture_tenant:
        raise FixtureImportError("scenario tenant_id is required")
    if tenant_id is not None and tenant_id != fixture_tenant:
        raise FixtureImportError("explicit tenant_id conflicts with the fixture tenant")

    model_document = _load_json(fixture_dir / "causal_model_snapshot.json")
    algorithm_document = _load_json(fixture_dir / "algorithm_fixture.json")
    ontology = _load_json(fixture_dir / "ontology_fixture.json")
    if ontology.get("tenant_id") != fixture_tenant:
        raise FixtureImportError("ontology fixture tenant_id conflicts with scenario")
    snapshot = model_document.get("snapshot")
    algorithm = algorithm_document.get("algorithm")
    if not isinstance(snapshot, dict) or not isinstance(algorithm, dict):
        raise FixtureImportError("causal snapshot and algorithm payloads are required")
    if canonical_json_hash(snapshot) != model_document.get("model_content_hash"):
        raise FixtureImportError("causal model semantic hash mismatch")
    if canonical_json_hash(algorithm) != algorithm_document.get("algorithm_config_hash"):
        raise FixtureImportError("algorithm configuration semantic hash mismatch")
    return _Fixture(scenario, model_document, ontology, algorithm_document, package_hash)


def _as_string_set(value: object, field: str) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise FixtureImportError(f"{field} must be a non-empty string list")
    return set(value)


def _validate_snapshot_graph(fixture: _Fixture) -> None:
    snapshot = fixture.snapshot
    if snapshot.get("status") != "published_fixture":
        raise FixtureImportError("only the hash-locked published_fixture import path is supported")
    if snapshot.get("graph_type") != "dag":
        raise FixtureImportError("Case A snapshot graph_type must be dag")
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    requirements = snapshot.get("evidence_requirements")
    rules = snapshot.get("rules")
    if (
        not isinstance(nodes, list)
        or not isinstance(edges, list)
        or not isinstance(requirements, list)
        or not isinstance(rules, list)
    ):
        raise FixtureImportError("snapshot graph arrays are required")
    node_keys = [node.get("node_key") for node in nodes if isinstance(node, dict)]
    if len(node_keys) != len(nodes) or not all(isinstance(key, str) and key for key in node_keys):
        raise FixtureImportError("each causal node needs node_key")
    if len(set(node_keys)) != len(node_keys):
        raise FixtureImportError("duplicate causal node_key")
    known_nodes = {key for key in node_keys if isinstance(key, str)}
    entry_points = _as_string_set(snapshot.get("entry_points"), "entry_points")
    if not entry_points <= known_nodes:
        raise FixtureImportError("entry_points reference unknown causal nodes")
    if "diagnose" not in _as_string_set(snapshot.get("supported_objectives"), "supported_objectives"):
        raise FixtureImportError("Case A snapshot must support diagnose")

    edge_keys: set[str] = set()
    children = {key: [] for key in known_nodes}
    for edge in edges:
        if not isinstance(edge, dict):
            raise FixtureImportError("causal edge must be an object")
        edge_key = edge.get("edge_key")
        source, target = edge.get("source_node_key"), edge.get("target_node_key")
        if not isinstance(edge_key, str) or not edge_key or edge_key in edge_keys:
            raise FixtureImportError("causal edge_key must be unique")
        if source not in known_nodes or target not in known_nodes or source == target:
            raise FixtureImportError("causal edge has a dangling or self reference")
        if edge.get("effect") not in {"+", "-"}:
            raise FixtureImportError("causal edge effect must be + or -")
        if not all(
            isinstance(edge.get(field), (int, float)) and 0 <= edge[field] <= 1 for field in ("strength", "confidence")
        ):
            raise FixtureImportError("causal edge strength/confidence must be within [0, 1]")
        edge_keys.add(edge_key)
        children[source].append(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_key: str) -> None:
        if node_key in visiting:
            raise FixtureImportError("causal graph contains a directed cycle")
        if node_key in visited:
            return
        visiting.add(node_key)
        for child in children[node_key]:
            visit(child)
        visiting.remove(node_key)
        visited.add(node_key)

    for node_key in sorted(known_nodes):
        visit(node_key)

    requirement_ids: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise FixtureImportError("evidence requirement must be an object")
        requirement_id, requirement_key, node_key = (
            requirement.get("requirement_id"),
            requirement.get("requirement_key"),
            requirement.get("node_key"),
        )
        if not all(isinstance(value, str) and value for value in (requirement_id, requirement_key, node_key)):
            raise FixtureImportError("evidence requirement identity is incomplete")
        # The all() guard cannot narrow tuple elements; cast after validation.
        requirement_id = cast(str, requirement_id)
        requirement_key = cast(str, requirement_key)
        node_key = cast(str, node_key)
        if requirement_id in requirement_ids or node_key not in known_nodes:
            raise FixtureImportError("evidence requirement has duplicate identity or dangling node")
        if requirement.get("requirement_level") not in {"required", "optional"}:
            raise FixtureImportError("evidence requirement level must be required or optional")
        if (
            not isinstance(requirement.get("capability_contract_ref"), str)
            or not requirement["capability_contract_ref"]
        ):
            raise FixtureImportError("evidence requirement capability contract is required")
        binding = requirement.get("instance_binding")
        if not isinstance(binding, dict) or binding.get("binding_language") != _BINDING_LANGUAGE:
            raise FixtureImportError("evidence requirement has an unsupported instance binding language")
        if not isinstance(binding.get("expression"), dict):
            raise FixtureImportError("evidence requirement instance binding expression is required")
        requirement_ids.add(requirement_id)
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("node_key") not in known_nodes:
            raise FixtureImportError("causal rule references an unknown node")


def _split_type_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _validate_ontology_contract(fixture: _Fixture) -> dict[str, str]:
    ontology = fixture.ontology
    contract = ontology.get("import_contract")
    if not isinstance(contract, dict) or contract.get("contract_version") != "case-a-ontology-import/v1":
        raise FixtureImportError("unsupported ontology import contract")
    expected_order = ["data_domains", "tbox.entity_types", "tbox.relation_types", "entities", "facts"]
    if contract.get("import_order") != expected_order:
        raise FixtureImportError("ontology import order must be data domain → TBox → ABox")
    tbox = contract.get("tbox")
    if not isinstance(tbox, dict):
        raise FixtureImportError("ontology TBox is required")
    entity_types = tbox.get("entity_types")
    relation_types = tbox.get("relation_types")
    entities = ontology.get("entities")
    facts = ontology.get("facts")
    if (
        not isinstance(contract.get("data_domains"), list)
        or not isinstance(entity_types, list)
        or not isinstance(relation_types, list)
        or not isinstance(entities, list)
        or not isinstance(facts, list)
    ):
        raise FixtureImportError("ontology contract arrays are required")
    entity_type_ids = {entry.get("entity_type_id") for entry in entity_types if isinstance(entry, dict)}
    if len(entity_type_ids) != len(entity_types) or not all(
        isinstance(value, str) and value for value in entity_type_ids
    ):
        raise FixtureImportError("ontology entity types must have unique ids")
    domains = {entry.get("data_domain_id") for entry in contract["data_domains"] if isinstance(entry, dict)}
    if not domains or not all(isinstance(value, str) and value for value in domains):
        raise FixtureImportError("ontology data domains must have unique ids")
    for entity_type in entity_types:
        if entity_type.get("data_domain_id") not in domains:
            raise FixtureImportError("ontology entity type refers to an unavailable data domain")
    relation_by_id = {entry.get("relation_type_id"): entry for entry in relation_types if isinstance(entry, dict)}
    if len(relation_by_id) != len(relation_types) or not all(
        isinstance(value, str) and value for value in relation_by_id
    ):
        raise FixtureImportError("ontology relation types must have unique ids")
    for relation in relation_types:
        if not _as_string_set(relation.get("source_type"), "relation source_type") <= entity_type_ids:
            raise FixtureImportError("ontology relation has an unknown source type")
        if not _as_string_set(relation.get("target_type"), "relation target_type") <= entity_type_ids:
            raise FixtureImportError("ontology relation has an unknown target type")
    entity_by_id = {entry.get("entity_id"): entry for entry in entities if isinstance(entry, dict)}
    if len(entity_by_id) != len(entities) or not all(isinstance(value, str) and value for value in entity_by_id):
        raise FixtureImportError("ontology ABox entities must have unique ids")
    for entity in entities:
        if entity.get("entity_type") not in entity_type_ids or entity.get("data_domain_id") not in domains:
            raise FixtureImportError("ontology ABox entity misses a TBox type or data domain")
    fact_keys: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict):
            raise FixtureImportError("ontology fact must be an object")
        fact_key, subject, relation_id, obj = (
            fact.get("fact_key"),
            fact.get("subject_entity_id"),
            fact.get("relation_type_id"),
            fact.get("object_entity_id"),
        )
        if not isinstance(fact_key, str) or not fact_key or fact_key in fact_keys:
            raise FixtureImportError("ontology fact keys must be unique")
        relation = relation_by_id.get(relation_id)
        if subject not in entity_by_id or obj not in entity_by_id or relation is None:
            raise FixtureImportError("ontology fact has a dangling reference")
        if entity_by_id[subject]["entity_type"] not in set(relation["source_type"]):
            raise FixtureImportError("ontology fact source violates relation TBox")
        if entity_by_id[obj]["entity_type"] not in set(relation["target_type"]):
            raise FixtureImportError("ontology fact target violates relation TBox")
        confidence = fact.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise FixtureImportError("ontology fact confidence must be within [0, 1]")
        fact_keys.add(fact_key)
    return {str(entity_id): str(entity["entity_type"]) for entity_id, entity in entity_by_id.items()}


def _resolve_fixture_bindings(fixture: _Fixture, entity_types: dict[str, str]) -> dict[str, str]:
    snapshot = fixture.snapshot
    context_entity_id = fixture.scenario.get("context", {}).get("entity_id")
    if context_entity_id not in entity_types:
        raise FixtureImportError("scenario context entity is absent from ontology ABox")
    facts = fixture.ontology["facts"]
    relation_types = fixture.ontology["import_contract"]["tbox"]["relation_types"]
    relation_by_id = {relation["relation_type_id"]: relation for relation in relation_types}
    resolved: dict[str, str] = {}
    for requirement in snapshot["evidence_requirements"]:
        expression = requirement["instance_binding"]["expression"]
        operation = expression.get("op")
        if operation == "context_entity":
            target = context_entity_id
            if entity_types[target] != expression.get("expected_entity_type_id"):
                raise FixtureImportError("context_entity binding has incompatible entity type")
        elif operation == "outbound_relation":
            if expression.get("from") != "context.entity_id":
                raise FixtureImportError("Case A only supports context.entity_id outbound bindings")
            relation_id = expression.get("relation_type_id")
            relation = relation_by_id.get(relation_id)
            if relation is None or entity_types[context_entity_id] not in relation["source_type"]:
                raise FixtureImportError("outbound binding relation is unavailable for context entity")
            candidates = [
                fact["object_entity_id"]
                for fact in facts
                if fact["subject_entity_id"] == context_entity_id and fact["relation_type_id"] == relation_id
            ]
            expected_type = expression.get("target_entity_type_id")
            candidates = [candidate for candidate in candidates if entity_types[candidate] == expected_type]
            if expression.get("cardinality") != "exactly_one" or len(candidates) != 1:
                raise FixtureImportError("outbound binding must resolve exactly one compatible ABox entity")
            target = candidates[0]
        else:
            raise FixtureImportError("unsupported Case A ABox binding operation")
        resolved[requirement["requirement_id"]] = target

    expectations = fixture.ontology.get("prepare_binding_expectations", {}).get("bindings")
    if not isinstance(expectations, list):
        raise FixtureImportError("ontology Prepare binding expectations are required")
    expected = {
        entry.get("requirement_id"): entry.get("target_entity_id") for entry in expectations if isinstance(entry, dict)
    }
    if resolved != expected:
        raise FixtureImportError("snapshot ABox bindings do not match ontology binding expectations")
    return resolved


async def _row(session: AsyncSession, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
    result = await session.execute(text(query), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def _ensure_data_domain(session: AsyncSession, tenant_id: str, payload: dict[str, Any]) -> None:
    domain_id = payload["data_domain_id"]
    existing = await _row(
        session,
        "SELECT name, description, data_classification, status FROM data_domains "
        "WHERE tenant_id = :tenant_id AND data_domain_id = :domain_id",
        {"tenant_id": tenant_id, "domain_id": domain_id},
    )
    expected = {
        "name": payload["name"],
        "description": payload.get("description"),
        "data_classification": payload["data_classification"],
        "status": payload["status"],
    }
    if existing is not None:
        if existing != expected:
            raise FixtureImportError(f"ontology data domain conflicts with existing state: {domain_id}")
        return
    await session.execute(
        text(
            "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, data_classification, status) "
            "VALUES (:data_domain_id, :tenant_id, :name, :description, :data_classification, :status)"
        ),
        {**payload, "tenant_id": tenant_id},
    )


async def _ensure_entity_type(session: AsyncSession, tenant_id: str, payload: dict[str, Any]) -> None:
    entity_type_id = payload["entity_type_id"]
    existing = await _row(
        session,
        "SELECT name, kind, description, data_domain_id, status FROM entity_types "
        "WHERE tenant_id = :tenant_id AND entity_type_id = :entity_type_id",
        {"tenant_id": tenant_id, "entity_type_id": entity_type_id},
    )
    expected = {
        "name": payload["name"],
        "kind": payload["kind"],
        "description": payload.get("description"),
        "data_domain_id": payload["data_domain_id"],
        "status": "active",
    }
    if existing is not None:
        if existing != expected:
            raise FixtureImportError(f"ontology entity type conflicts with existing state: {entity_type_id}")
        return
    await session.execute(
        text(
            "INSERT INTO entity_types (entity_type_id, tenant_id, name, kind, description, data_domain_id) "
            "VALUES (:entity_type_id, :tenant_id, :name, :kind, :description, :data_domain_id)"
        ),
        {**payload, "tenant_id": tenant_id},
    )


async def _ensure_relation_type(session: AsyncSession, tenant_id: str, payload: dict[str, Any]) -> None:
    relation_type_id = payload["relation_type_id"]
    source_type = ",".join(payload["source_type"])
    target_type = ",".join(payload["target_type"])
    existing = await _row(
        session,
        "SELECT name, source_type, target_type, cardinality, status FROM relation_types "
        "WHERE tenant_id = :tenant_id AND relation_type_id = :relation_type_id",
        {"tenant_id": tenant_id, "relation_type_id": relation_type_id},
    )
    expected = {
        "name": payload["name"],
        "source_type": source_type,
        "target_type": target_type,
        "cardinality": payload["cardinality"],
        "status": "active",
    }
    if existing is not None:
        if existing != expected:
            raise FixtureImportError(f"ontology relation type conflicts with existing state: {relation_type_id}")
        return
    await session.execute(
        text(
            "INSERT INTO relation_types (relation_type_id, tenant_id, name, source_type, target_type, cardinality) "
            "VALUES (:relation_type_id, :tenant_id, :name, :source_type, :target_type, :cardinality)"
        ),
        {**payload, "tenant_id": tenant_id, "source_type": source_type, "target_type": target_type},
    )


async def _ensure_entity(session: AsyncSession, tenant_id: str, payload: dict[str, Any]) -> None:
    entity_id = payload["entity_id"]
    existing = await _row(
        session,
        "SELECT entity_type_id, name, business_code, data_domain_id, status FROM entities "
        "WHERE tenant_id = :tenant_id AND entity_id = :entity_id",
        {"tenant_id": tenant_id, "entity_id": entity_id},
    )
    expected = {
        "entity_type_id": payload["entity_type"],
        "name": payload["name"],
        "business_code": payload["business_code"],
        "data_domain_id": payload["data_domain_id"],
        "status": "active",
    }
    if existing is not None:
        if existing != expected:
            raise FixtureImportError(f"ontology entity conflicts with existing state: {entity_id}")
        return
    await session.execute(
        text(
            "INSERT INTO entities (entity_id, tenant_id, entity_type_id, name, business_code, "
            "source_mode, source_ref, data_domain_id) "
            "VALUES (:entity_id, :tenant_id, :entity_type, :name, :business_code, 'virtual', :source_ref, "
            ":data_domain_id)"
        ),
        {**payload, "tenant_id": tenant_id, "source_ref": "case-a-fixture"},
    )


async def _ensure_fact(session: AsyncSession, tenant_id: str, payload: dict[str, Any]) -> None:
    fact_id = f"case-a-{payload['fact_key']}"
    existing = await _row(
        session,
        "SELECT source_entity_id, relation_type_id, target_entity_id, confidence, status FROM facts "
        "WHERE tenant_id = :tenant_id AND fact_id = :fact_id",
        {"tenant_id": tenant_id, "fact_id": fact_id},
    )
    expected = {
        "source_entity_id": payload["subject_entity_id"],
        "relation_type_id": payload["relation_type_id"],
        "target_entity_id": payload["object_entity_id"],
        "confidence": payload["confidence"],
        "status": "active",
    }
    if existing is not None:
        if existing != expected:
            raise FixtureImportError(f"ontology fact conflicts with existing state: {payload['fact_key']}")
        return
    await session.execute(
        text(
            "INSERT INTO facts (fact_id, tenant_id, source_entity_id, relation_type_id, target_entity_id, "
            "confidence, source_ref) VALUES (:fact_id, :tenant_id, :subject_entity_id, :relation_type_id, "
            ":object_entity_id, :confidence, 'case-a-fixture')"
        ),
        {**payload, "tenant_id": tenant_id, "fact_id": fact_id},
    )


async def _import_ontology(session: AsyncSession, tenant_id: str, fixture: _Fixture) -> None:
    contract = fixture.ontology["import_contract"]
    for domain in contract["data_domains"]:
        await _ensure_data_domain(session, tenant_id, domain)
    for entity_type in contract["tbox"]["entity_types"]:
        await _ensure_entity_type(session, tenant_id, entity_type)
    for relation_type in contract["tbox"]["relation_types"]:
        await _ensure_relation_type(session, tenant_id, relation_type)
    for entity in fixture.ontology["entities"]:
        await _ensure_entity(session, tenant_id, entity)
    for fact in fixture.ontology["facts"]:
        await _ensure_fact(session, tenant_id, fact)


def _model_version_id(snapshot: dict[str, Any]) -> str:
    value = f"{snapshot['model_id']}:{snapshot['model_version']}"
    if len(value) > 64:
        raise FixtureImportError("causal model/version identity exceeds persistence limit")
    return value


def _projection_row_id(snapshot_id: str, kind: str, stable_key: str) -> str:
    """A readable, bounded surrogate identity for T04's VARCHAR(64) projections."""
    digest = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]
    value = f"{snapshot_id}:{kind}:{digest}"
    if len(value) > 64:
        raise FixtureImportError("snapshot projection identity exceeds persistence limit")
    return value


def _data_domain_id(fixture: _Fixture) -> str:
    application_types = set(fixture.snapshot["applicability"].get("entity_types", []))
    candidates = {
        entry["data_domain_id"]
        for entry in fixture.ontology["import_contract"]["tbox"]["entity_types"]
        if entry["entity_type_id"] in application_types
    }
    if len(candidates) != 1:
        raise FixtureImportError("causal applicability must resolve to exactly one ontology data domain")
    return candidates.pop()


def _node_entity_types(
    fixture: _Fixture, resolved_bindings: dict[str, str], entity_types: dict[str, str]
) -> dict[str, str]:
    node_types = {node["node_key"]: fixture.scenario["context"]["entity_type"] for node in fixture.snapshot["nodes"]}
    for requirement in fixture.snapshot["evidence_requirements"]:
        node_types[requirement["node_key"]] = entity_types[resolved_bindings[requirement["requirement_id"]]]
    return node_types


async def _import_causal_snapshot(
    session: AsyncSession,
    tenant_id: str,
    fixture: _Fixture,
    entity_types: dict[str, str],
    resolved_bindings: dict[str, str],
) -> tuple[str, str]:
    snapshot = fixture.snapshot
    model_version_id = _model_version_id(snapshot)
    snapshot_hash = fixture.model_document["model_content_hash"]
    data_domain_id = _data_domain_id(fixture)
    await session.execute(
        text(
            "INSERT INTO causal_models (tenant_id, model_id, data_domain_id, name, description) "
            "VALUES (:tenant_id, :model_id, :data_domain_id, :name, :description) "
            "ON CONFLICT (tenant_id, model_id) DO NOTHING"
        ),
        {
            "tenant_id": tenant_id,
            "model_id": snapshot["model_id"],
            "data_domain_id": data_domain_id,
            "name": snapshot["model_id"],
            "description": "Case A hash-locked fixture source model",
        },
    )
    model = await _row(
        session,
        "SELECT data_domain_id, name FROM causal_models WHERE tenant_id = :tenant_id AND model_id = :model_id",
        {"tenant_id": tenant_id, "model_id": snapshot["model_id"]},
    )
    if model != {"data_domain_id": data_domain_id, "name": snapshot["model_id"]}:
        raise FixtureImportError("causal model conflicts with existing state")
    await session.execute(
        text(
            "INSERT INTO causal_model_versions (tenant_id, model_version_id, model_id, version, status, "
            "dependency_resolution, applicability) "
            "VALUES (:tenant_id, :model_version_id, :model_id, :version, 'testing', '{}'::jsonb, :applicability) "
            "ON CONFLICT (tenant_id, model_version_id) DO NOTHING"
        ),
        {
            "tenant_id": tenant_id,
            "model_version_id": model_version_id,
            "model_id": snapshot["model_id"],
            "version": snapshot["model_version"],
            "applicability": json.dumps(snapshot["applicability"]),
        },
    )
    version = await _row(
        session,
        "SELECT model_id, version, status, applicability FROM causal_model_versions "
        "WHERE tenant_id = :tenant_id AND model_version_id = :model_version_id",
        {"tenant_id": tenant_id, "model_version_id": model_version_id},
    )
    if (
        version is None
        or version["model_id"] != snapshot["model_id"]
        or version["version"] != snapshot["model_version"]
        or version["status"] != "testing"
        or version["applicability"] != snapshot["applicability"]
    ):
        raise FixtureImportError("causal model version conflicts with existing state")

    node_types = _node_entity_types(fixture, resolved_bindings, entity_types)
    for sequence, node in enumerate(snapshot["nodes"], start=1):
        await session.execute(
            text(
                "INSERT INTO causal_nodes (tenant_id, node_row_id, model_version_id, node_key, node_seq, "
                "entity_type_ref, entry_point, entry_direction, entry_description) "
                "VALUES (:tenant_id, :node_row_id, :model_version_id, :node_key, :node_seq, :entity_type_ref, "
                ":entry_point, :entry_direction, :entry_description) "
                "ON CONFLICT (tenant_id, model_version_id, node_key) DO NOTHING"
            ),
            {
                "tenant_id": tenant_id,
                "node_row_id": _projection_row_id(snapshot["model_snapshot_id"], "node", node["node_key"]),
                "model_version_id": model_version_id,
                "node_key": node["node_key"],
                "node_seq": sequence,
                "entity_type_ref": node_types[node["node_key"]],
                "entry_point": node["node_key"] in snapshot["entry_points"],
                "entry_direction": fixture.scenario["context"]["direction"]
                if node["node_key"] in snapshot["entry_points"]
                else None,
                "entry_description": node.get("label"),
            },
        )
    for edge in snapshot["edges"]:
        await session.execute(
            text(
                "INSERT INTO causal_edges (tenant_id, edge_row_id, edge_key, model_version_id, source_node_key, "
                "target_node_key, relation_type_ref, effect, strength, confidence) "
                "VALUES (:tenant_id, :edge_row_id, :edge_key, :model_version_id, :source_node_key, "
                ":target_node_key, :relation_type_ref, :effect, :strength, :confidence) "
                "ON CONFLICT (tenant_id, model_version_id, edge_key) DO NOTHING"
            ),
            {
                "tenant_id": tenant_id,
                "edge_row_id": _projection_row_id(snapshot["model_snapshot_id"], "edge", edge["edge_key"]),
                "model_version_id": model_version_id,
                "relation_type_ref": _CAUSAL_EDGE_RELATION_REF,
                **edge,
            },
        )
    for rule in snapshot["rules"]:
        await session.execute(
            text(
                "INSERT INTO causal_rules (tenant_id, rule_row_id, rule_key, model_version_id, node_key, rule_type, "
                "rule_spec) VALUES (:tenant_id, :rule_row_id, :rule_key, :model_version_id, :node_key, "
                "'direction_rule', :rule_spec) ON CONFLICT (tenant_id, model_version_id, rule_key) DO NOTHING"
            ),
            {
                "tenant_id": tenant_id,
                "rule_row_id": _projection_row_id(snapshot["model_snapshot_id"], "rule", rule["rule_key"]),
                "model_version_id": model_version_id,
                "rule_spec": json.dumps(rule),
                **rule,
            },
        )
    for requirement in snapshot["evidence_requirements"]:
        metric_binding = {key: requirement[key] for key in ("unit", "aggregation")}
        base = {
            "tenant_id": tenant_id,
            "model_version_id": model_version_id,
            "node_key": requirement["node_key"],
            "requirement_key": requirement["requirement_key"],
        }
        await session.execute(
            text(
                "INSERT INTO causal_data_bindings (tenant_id, binding_row_id, model_version_id, node_key, "
                "requirement_key, requirement_level, metric_binding, instance_binding_expr, output_mapping) "
                "VALUES (:tenant_id, :binding_row_id, :model_version_id, :node_key, :requirement_key, "
                ":requirement_level, :metric_binding, :instance_binding_expr, :output_mapping) "
                "ON CONFLICT (tenant_id, model_version_id, node_key, requirement_key) DO NOTHING"
            ),
            {
                **base,
                "binding_row_id": _projection_row_id(
                    snapshot["model_snapshot_id"], "requirement", requirement["requirement_id"]
                ),
                "requirement_level": requirement["requirement_level"],
                "metric_binding": json.dumps(metric_binding),
                "instance_binding_expr": json.dumps(requirement["instance_binding"]),
                "output_mapping": json.dumps(
                    {"fixture_target_entity_id": resolved_bindings[requirement["requirement_id"]]}
                ),
            },
        )
        await session.execute(
            text(
                "INSERT INTO causal_capability_bindings (tenant_id, cap_binding_row_id, model_version_id, node_key, "
                "requirement_key, capability_role, capability_contract_ref) "
                "VALUES (:tenant_id, :cap_binding_row_id, :model_version_id, :node_key, :requirement_key, "
                "'primary', :capability_contract_ref) "
                "ON CONFLICT (tenant_id, model_version_id, node_key, requirement_key, capability_role) DO NOTHING"
            ),
            {
                **base,
                "cap_binding_row_id": _projection_row_id(
                    snapshot["model_snapshot_id"], "capability", requirement["requirement_id"]
                ),
                "capability_contract_ref": requirement["capability_contract_ref"],
            },
        )
    await session.execute(
        text(
            "INSERT INTO causal_model_snapshots (tenant_id, snapshot_id, model_version_id, content_hash, nodes_json, "
            "edges_json, rules_json, requirements_json, applicability_snapshot, schema_version) "
            "VALUES (:tenant_id, :snapshot_id, :model_version_id, :content_hash, :nodes_json, :edges_json, "
            ":rules_json, :requirements_json, :applicability_snapshot, :schema_version) "
            "ON CONFLICT (tenant_id, snapshot_id) DO NOTHING"
        ),
        {
            "tenant_id": tenant_id,
            "snapshot_id": snapshot["model_snapshot_id"],
            "model_version_id": model_version_id,
            "content_hash": snapshot_hash,
            "nodes_json": json.dumps(snapshot["nodes"]),
            "edges_json": json.dumps(snapshot["edges"]),
            "rules_json": json.dumps(snapshot["rules"]),
            "requirements_json": json.dumps(snapshot["evidence_requirements"]),
            "applicability_snapshot": json.dumps(snapshot["applicability"]),
            "schema_version": fixture.model_document["schema_version"],
        },
    )
    stored_snapshot = await _row(
        session,
        "SELECT model_version_id, content_hash FROM causal_model_snapshots "
        "WHERE tenant_id = :tenant_id AND snapshot_id = :snapshot_id",
        {"tenant_id": tenant_id, "snapshot_id": snapshot["model_snapshot_id"]},
    )
    if stored_snapshot != {"model_version_id": model_version_id, "content_hash": snapshot_hash}:
        raise FixtureImportError("immutable snapshot identity conflicts with existing state")
    # The pointer makes this validated frozen source selectable for test compilation,
    # but model status intentionally remains testing (not a production publication).
    await session.execute(
        text(
            "UPDATE causal_model_versions SET published_snapshot_id = :snapshot_id "
            "WHERE tenant_id = :tenant_id AND model_version_id = :model_version_id "
            "AND (published_snapshot_id IS NULL OR published_snapshot_id = :snapshot_id)"
        ),
        {"tenant_id": tenant_id, "model_version_id": model_version_id, "snapshot_id": snapshot["model_snapshot_id"]},
    )
    pointer = await _row(
        session,
        "SELECT published_snapshot_id, status FROM causal_model_versions "
        "WHERE tenant_id = :tenant_id AND model_version_id = :model_version_id",
        {"tenant_id": tenant_id, "model_version_id": model_version_id},
    )
    if pointer != {"published_snapshot_id": snapshot["model_snapshot_id"], "status": "testing"}:
        raise FixtureImportError("model version already points to a different immutable snapshot")
    run_id = f"validation-{snapshot['model_snapshot_id']}"
    await session.execute(
        text(
            "INSERT INTO causal_snapshot_validation_runs (tenant_id, run_id, snapshot_id, result, detail, finished_at) "
            "VALUES (:tenant_id, :run_id, :snapshot_id, 'passed', :detail, now()) "
            "ON CONFLICT (tenant_id, run_id) DO NOTHING"
        ),
        {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "snapshot_id": snapshot["model_snapshot_id"],
            "detail": json.dumps(
                {
                    "validation_contract": "case-a-snapshot-import/v1",
                    "fixture_package_hash": fixture.package_hash,
                    "fixture_release_only": True,
                    "resolved_bindings": resolved_bindings,
                }
            ),
        },
    )
    validation = await _row(
        session,
        "SELECT result FROM causal_snapshot_validation_runs WHERE tenant_id = :tenant_id AND run_id = :run_id",
        {"tenant_id": tenant_id, "run_id": run_id},
    )
    if validation != {"result": "passed"}:
        raise FixtureImportError("snapshot validation record conflicts with existing state")
    return model_version_id, run_id


async def _register_unbuilt_algorithm(registry_engine: AsyncEngine, fixture: _Fixture) -> None:
    """Write global registry metadata with a privileged platform connection.

    Registry tables are intentionally read-only to ``earp_app``.  The tenant
    source-model/ABox import is still done under ``tenant_session``; callers must
    pass the platform registry engine used for controlled fixture bootstrap.
    """
    algorithm = fixture.algorithm
    artifact = algorithm.get("implementation_artifact")
    if not isinstance(artifact, dict) or artifact.get("status") != "not_built" or artifact.get("sha256") is not None:
        raise FixtureImportError("T05 only accepts an explicitly unbuilt algorithm fixture")
    async with registry_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO reasoning_algorithms (algorithm_id, name) VALUES (:algorithm_id, :name) "
                "ON CONFLICT (algorithm_id) DO NOTHING"
            ),
            {"algorithm_id": algorithm["algorithm_id"], "name": algorithm["algorithm_id"]},
        )
        await connection.execute(
            text(
                "INSERT INTO reasoning_algorithm_versions (algorithm_version_id, algorithm_id, version, "
                "contract_version, profile_version, profile_json, params_schema, handler, implementation_hash, "
                "algorithm_config_hash, algorithm_config_json, status) "
                "VALUES (:algorithm_version_id, :algorithm_id, :version, 'case-a-fixture', "
                ":profile_version, :profile_json, :params_schema, :handler, NULL, "
                ":algorithm_config_hash, :algorithm_config_json, 'beta') "
                "ON CONFLICT (algorithm_version_id) DO NOTHING"
            ),
            {
                "algorithm_version_id": algorithm["algorithm_version_id"],
                "algorithm_id": algorithm["algorithm_id"],
                "version": algorithm["algorithm_version"],
                "profile_version": algorithm["profile_version"],
                "profile_json": json.dumps(algorithm["profile"]),
                "params_schema": json.dumps(
                    {"params": algorithm["params"], "score_contract": algorithm["score_contract"]}
                ),
                "handler": algorithm["implementation_ref"],
                "algorithm_config_hash": fixture.algorithm_document["algorithm_config_hash"],
                "algorithm_config_json": json.dumps(algorithm),
            },
        )
        result = await connection.execute(
            text(
                "SELECT algorithm_id, version, implementation_hash, algorithm_config_hash, "
                "algorithm_config_json, status "
                "FROM reasoning_algorithm_versions WHERE algorithm_version_id = :algorithm_version_id"
            ),
            {"algorithm_version_id": algorithm["algorithm_version_id"]},
        )
        stored = dict(result.mappings().one())
    if (
        stored["algorithm_id"] != algorithm["algorithm_id"]
        or stored["version"] != algorithm["algorithm_version"]
        or stored["implementation_hash"] is not None
        or stored["algorithm_config_hash"] != fixture.algorithm_document["algorithm_config_hash"]
        or stored["algorithm_config_json"] != algorithm
        or stored["status"] != "beta"
    ):
        raise FixtureImportError("algorithm fixture conflicts with global registry state")


async def import_case_a_snapshot_fixture(
    engine: AsyncEngine,
    registry_engine: AsyncEngine,
    fixture_dir: Path,
    *,
    tenant_id: str | None = None,
) -> SnapshotImportResult:
    """Verify and import one Case A fixture package.

    ``registry_engine`` is deliberately distinct because platform-global algorithm
    registry writes are not granted to the tenant application role.  No route is
    provided: this is controlled test-fixture bootstrap, not production approval.
    """
    fixture = _load_fixture(fixture_dir, tenant_id)
    _validate_snapshot_graph(fixture)
    entity_types = _validate_ontology_contract(fixture)
    resolved_bindings = _resolve_fixture_bindings(fixture, entity_types)
    resolved_tenant = fixture.scenario["request"]["tenant_id"]
    async with tenant_session(engine, resolved_tenant) as session:
        await _import_ontology(session, resolved_tenant, fixture)
        model_version_id, validation_run_id = await _import_causal_snapshot(
            session, resolved_tenant, fixture, entity_types, resolved_bindings
        )
    # The tenant import is deliberately completed before the global registry
    # write.  A tenant conflict can therefore never leave a newly-created
    # algorithm registry row behind; a registry failure remains safely
    # retryable because the immutable snapshot import is idempotent.
    await _register_unbuilt_algorithm(registry_engine, fixture)
    return SnapshotImportResult(
        tenant_id=resolved_tenant,
        model_id=fixture.snapshot["model_id"],
        model_version_id=model_version_id,
        snapshot_id=fixture.snapshot["model_snapshot_id"],
        snapshot_hash=fixture.model_document["model_content_hash"],
        algorithm_version_id=fixture.algorithm["algorithm_version_id"],
        algorithm_config_hash=fixture.algorithm_document["algorithm_config_hash"],
        validation_run_id=validation_run_id,
        ontology_entity_ids=tuple(sorted(entity_types)),
    )
