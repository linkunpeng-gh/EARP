"""Pure validation for Case A's deterministic fixture package.

The tests intentionally exercise no database, provider, compiler, or reasoning service.  They
protect the hand-off contract consumed by later G1--G5 work, including the existing ontology
TBox/ABox import prerequisites and the boundary between Prepare's semantic target resolution and
Capability Resolution's provider selection.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

FIXTURE_DIR = Path(__file__).parent / "scenarios" / "mine_3_production_drop"
HASHED_FILES = (
    "algorithm_fixture.json",
    "capability_fixture.json",
    "causal_model_snapshot.json",
    "evidence_observations.json",
    "expected_plan.json",
    "expected_reasoning.json",
    "intent_goal_fixture.json",
    "ontology_fixture.json",
    "scenario.yaml",
)


def _load_json(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _load_yaml(name: str) -> dict[str, Any]:
    value = yaml.safe_load((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(name: str) -> str:
    return hashlib.sha256((FIXTURE_DIR / name).read_bytes()).hexdigest()


def _package_hash(file_hashes: dict[str, str]) -> str:
    payload = "".join(f"{name}:{file_hashes[name]}\n" for name in sorted(file_hashes))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unique(values: Iterable[str]) -> None:
    items = list(values)
    assert all(items)
    assert len(items) == len(set(items))


def _has_directed_path(edges: list[dict[str, Any]], path: list[str]) -> bool:
    return all(
        any(edge["source_node_key"] == source and edge["target_node_key"] == target for edge in edges)
        for source, target in zip(path, path[1:], strict=False)
    )


def _assert_acyclic(nodes: set[str], edges: list[dict[str, Any]], source_key: str, target_key: str) -> None:
    children = {node: [] for node in nodes}
    for edge in edges:
        children[edge[source_key]].append(edge[target_key])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        assert node not in visiting, f"cycle at {node}"
        if node in visited:
            return
        visiting.add(node)
        for child in children[node]:
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in nodes:
        visit(node)


def test_fixture_manifest_is_complete_and_reproducible() -> None:
    manifest = _load_json("fixture_hashes.json")
    assert manifest["hash_algorithm"] == "sha256"
    assert manifest["hash_scope"] == "raw_utf8_file_bytes"
    assert set(manifest["files"]) == set(HASHED_FILES)
    assert manifest["excluded_from_package_hash"] == ["fixture_hashes.json", "README.md"]

    actual = {name: _file_hash(name) for name in HASHED_FILES}
    assert manifest["files"] == actual
    assert manifest["package_hash"] == _package_hash(actual)


def test_fixture_schema_cross_file_references_and_ontology_import_prerequisites() -> None:
    scenario = _load_yaml("scenario.yaml")
    intent = _load_json("intent_goal_fixture.json")
    model = _load_json("causal_model_snapshot.json")
    ontology = _load_json("ontology_fixture.json")
    capabilities = _load_json("capability_fixture.json")
    algorithm = _load_json("algorithm_fixture.json")
    observations = _load_json("evidence_observations.json")
    expected_plan = _load_json("expected_plan.json")
    expected_reasoning = _load_json("expected_reasoning.json")

    assert scenario["schema_version"] == "case-a-scenario/v1"
    assert scenario["fixture_status"] == "provisional_pending_domain_confirmation"
    assert scenario["authority"]["confirmation_required_before_production_use"] is True
    assert scenario["context"]["entity_id"] == "mine-3"
    assert scenario["context"]["business_objective"] == "diagnose"
    release = scenario["fixture_release"]
    assert release["release_scope"] == "deterministic_test_input_only"
    assert release["executable_evaluate_status"] == "blocked_until_t11_artifact_release"
    assert "not a domain approval" in release["published_fixture_boundary"]
    assert "must never generate" in release["hash_update_rule"]
    time_context = scenario["context"].get("time_window") or scenario["context"]["production_day"]
    assert time_context
    assert set(scenario["fixture_files"].values()) <= {path.name for path in FIXTURE_DIR.iterdir() if path.is_file()}

    assert intent["fixture_hash"] == _canonical_hash(
        {key: value for key, value in intent.items() if key != "fixture_hash"}
    )
    primary = intent["output"]["parsed_intent"]["primary_intent"]
    assert primary == {
        "entry_point": "production_output",
        "direction": "down",
        "domain": "production",
        "business_objective": "diagnose",
    }
    sub_goals = intent["output"]["sub_goals"]
    assert len(sub_goals) == 1
    assert sub_goals[0]["dependencies"] == []
    assert intent["input"]["tenant_id"] == scenario["request"]["tenant_id"] == ontology["tenant_id"]
    assert intent["output"]["resolved_context"]["entity_id"] == scenario["context"]["entity_id"]
    assert intent["output"]["resolved_context"]["time_window"] == {
        "start": scenario["context"]["production_day"]["start"],
        "end": scenario["context"]["production_day"]["end"],
    }

    snapshot = model["snapshot"]
    assert snapshot["status"] == "published_fixture"
    assert snapshot["model_id"] == "causal-production-drop-mine"
    assert snapshot["model_version"] == "1.0.1-fixture"
    assert snapshot["model_snapshot_id"] == "cms-mine-3-production-drop-v1"
    assert model["model_content_hash"] == _canonical_hash(snapshot)
    assert snapshot["graph_type"] == "dag"
    node_keys = {node["node_key"] for node in snapshot["nodes"]}
    _unique(node["node_key"] for node in snapshot["nodes"])
    _unique(edge["edge_key"] for edge in snapshot["edges"])
    assert snapshot["entry_points"] == ["production_output"]
    assert all(
        edge["source_node_key"] in node_keys and edge["target_node_key"] in node_keys for edge in snapshot["edges"]
    )
    assert all(0 < edge["strength"] <= 1 and 0 < edge["confidence"] <= 1 for edge in snapshot["edges"])
    _assert_acyclic(node_keys, snapshot["edges"], "source_node_key", "target_node_key")
    requirements = snapshot["evidence_requirements"]
    requirement_ids = {requirement["requirement_id"] for requirement in requirements}
    _unique(requirement["requirement_id"] for requirement in requirements)
    _unique(requirement["requirement_key"] for requirement in requirements)
    assert {requirement["requirement_level"] for requirement in requirements} == {"required", "optional"}
    assert all(requirement["node_key"] in node_keys for requirement in requirements)

    # The fixture encodes an existing-service-compatible TBox/ABox setup, not an invented importer.
    import_contract = ontology["import_contract"]
    assert ontology["schema_version"] == "case-a-ontology-fixture/v2"
    assert import_contract["target"] == "existing_ontology_tbox_and_abox_services"
    assert import_contract["import_order"] == [
        "data_domains",
        "tbox.entity_types",
        "tbox.relation_types",
        "entities",
        "facts",
    ]
    assert "no metric TBox table" in import_contract["metric_catalog_boundary"]
    data_domains = import_contract["data_domains"]
    domain_ids = {domain["data_domain_id"] for domain in data_domains}
    _unique(domain["data_domain_id"] for domain in data_domains)
    assert all(domain["status"] == "active" and domain["data_classification"] for domain in data_domains)
    tbox = import_contract["tbox"]
    entity_types = {entity_type["entity_type_id"]: entity_type for entity_type in tbox["entity_types"]}
    _unique(entity_types)
    assert all(
        entity_type["kind"] == "object" and entity_type["data_domain_id"] in domain_ids
        for entity_type in entity_types.values()
    )
    relation_types = {relation["relation_type_id"]: relation for relation in tbox["relation_types"]}
    _unique(relation_types)
    assert all(
        relation["source_type"] and relation["target_type"] and relation["cardinality"]
        for relation in relation_types.values()
    )
    assert all(
        set(relation["source_type"]) <= set(entity_types) and set(relation["target_type"]) <= set(entity_types)
        for relation in relation_types.values()
    )
    entities = {entity["entity_id"]: entity for entity in ontology["entities"]}
    _unique(entities)
    _unique(entity["business_code"] for entity in entities.values())
    assert scenario["context"]["entity_id"] in entities
    assert all(
        entity["entity_type"] in entity_types
        and entity["data_domain_id"] == entity_types[entity["entity_type"]]["data_domain_id"]
        for entity in entities.values()
    )
    facts = ontology["facts"]
    _unique(fact["fact_key"] for fact in facts)
    assert all(0 <= fact["confidence"] <= 1 for fact in facts)
    for fact in facts:
        assert fact["subject_entity_id"] in entities and fact["object_entity_id"] in entities
        relation = relation_types[fact["relation_type_id"]]
        assert entities[fact["subject_entity_id"]]["entity_type"] in relation["source_type"]
        assert entities[fact["object_entity_id"]]["entity_type"] in relation["target_type"]

    metrics = {metric["metric_key"]: metric for metric in ontology["metrics"]}
    _unique(metrics)
    assert all(
        metric["entity_type"] in entity_types and metric["unit"] and metric["aggregation"]
        for metric in metrics.values()
    )
    assert {requirement["node_key"] for requirement in requirements} <= set(metrics)
    for requirement in requirements:
        metric = metrics[requirement["node_key"]]
        assert requirement["unit"] == metric["unit"]
        assert requirement["aggregation"] == metric["aggregation"]

    # Instance target semantics belong to Prepare. Provider bindings deliberately contain no target.
    expected_bindings = ontology["prepare_binding_expectations"]
    assert expected_bindings["binding_language"] == "case-a-abox-binding/v1"
    assert "must not infer or replace the target entity" in expected_bindings["resolution_rule"]
    binding_by_requirement = {binding["requirement_id"]: binding for binding in expected_bindings["bindings"]}
    _unique(binding_by_requirement)
    assert set(binding_by_requirement) == requirement_ids
    context_entity_id = scenario["context"]["entity_id"]
    resolved_targets: dict[str, str] = {}
    for requirement in requirements:
        binding = requirement["instance_binding"]
        assert binding["binding_language"] == expected_bindings["binding_language"]
        assert (
            binding["resolution_priority"]
            == binding_by_requirement[requirement["requirement_id"]]["resolution_priority"]
        )
        expression = binding["expression"]
        if expression["op"] == "context_entity":
            targets = [context_entity_id]
            assert entities[context_entity_id]["entity_type"] == expression["expected_entity_type_id"]
        else:
            assert expression["op"] == "outbound_relation"
            assert expression["from"] == "context.entity_id"
            targets = [
                fact["object_entity_id"]
                for fact in facts
                if fact["subject_entity_id"] == context_entity_id
                and fact["relation_type_id"] == expression["relation_type_id"]
                and entities[fact["object_entity_id"]]["entity_type"] == expression["target_entity_type_id"]
            ]
        assert expression["cardinality"] == "exactly_one"
        assert len(targets) == 1
        resolved_targets[requirement["requirement_id"]] = targets[0]
        assert binding_by_requirement[requirement["requirement_id"]]["target_entity_id"] == targets[0]

    # The Snapshot is the semantic source of truth for target resolution.  Keep the
    # expected ABox targets in the ontology fixture as an explicit cross-file contract,
    # and reject any drift in requirement ids, target ids, or binding language.
    assert resolved_targets == {
        "er-production-actual-and-baseline": "mine-3",
        "er-critical-equipment-availability": "critical-equipment-group-mine-3",
        "er-haulage-cycle-observation": "haulage-system-mine-3",
        "er-haulage-queue-observation": "haulage-system-mine-3",
        "er-ore-quality-observation": "mine-3",
    }
    assert all(
        requirement["instance_binding"]["binding_language"] == "case-a-abox-binding/v1" for requirement in requirements
    )

    assert algorithm["algorithm_config_hash"] == _canonical_hash(algorithm["algorithm"])
    artifact = algorithm["algorithm"]["implementation_artifact"]
    identity = algorithm["algorithm"]
    assert identity["algorithm_id"] == "sign_propagation"
    assert identity["algorithm_version_id"] == "sign-propagation-v1-fixture"
    assert identity["algorithm_version"] == "1.0.1-fixture"
    # A config/identity hash is not an executable implementation hash.
    assert algorithm["algorithm_config_hash"] != ""
    assert "implementation_hash" not in identity
    assert artifact["status"] == "not_built"
    assert artifact["sha256"] is None and artifact["hash_scope"] is None
    assert artifact["required_before_executable_evaluate"] is True
    assert "T11" in artifact["release_rule"] and "T05" in artifact["release_rule"]
    assert algorithm["algorithm"]["profile"]["max_depth"] == 3
    assert algorithm["algorithm"]["score_contract"]["tie_breaker"] == [
        "score_desc",
        "shorter_path_first",
        "node_key_asc",
    ]

    providers = {provider["provider_key"]: provider for provider in capabilities["mock_providers"]}
    contracts = {contract["contract_ref"]: contract for contract in capabilities["contracts"]}
    _unique(providers)
    _unique(contracts)
    assert all(requirement["capability_contract_ref"] in contracts for requirement in requirements)
    provider_bindings = {binding["requirement_id"]: binding for binding in capabilities["provider_bindings"]}
    _unique(provider_bindings)
    assert set(provider_bindings) == requirement_ids
    assert all("target_entity_id" not in binding for binding in capabilities["provider_bindings"])
    assert all("instance_binding" not in binding for binding in capabilities["provider_bindings"])
    for requirement in requirements:
        provider = providers[provider_bindings[requirement["requirement_id"]]["provider_key"]]
        target = entities[binding_by_requirement[requirement["requirement_id"]]["target_entity_id"]]
        assert provider["contract_ref"] == requirement["capability_contract_ref"]
        assert target["entity_type"] in provider["applicable_entity_types"]
        assert contracts[provider["contract_ref"]]["input_scope"] == target["entity_type"]

    values = observations["observations"]
    observation_by_requirement = {observation["requirement_id"]: observation for observation in values}
    _unique(observation["observation_id"] for observation in values)
    _unique(observation_by_requirement)
    assert observations["prepare_id"] == "prepare-mine-3-production-drop-fixture"
    assert set(observation_by_requirement) == requirement_ids
    for requirement in requirements:
        observation = observation_by_requirement[requirement["requirement_id"]]
        target_id = binding_by_requirement[requirement["requirement_id"]]["target_entity_id"]
        provider_key = provider_bindings[requirement["requirement_id"]]["provider_key"]
        assert observation["requirement_key"] == requirement["requirement_key"]
        assert observation["node_key"] == requirement["node_key"]
        assert observation["entity_id"] == target_id
        assert observation["unit"] == requirement["unit"]
        assert observation["quality"]["status"] == "valid"
        assert observation["provenance"]["provider_key"] == provider_key
        assert observation["time_window"] == {
            "start": scenario["context"]["production_day"]["start"],
            "end": scenario["context"]["production_day"]["end"],
        }
        assert isinstance(observation["value"], (int, float)) and isinstance(
            observation["baseline_value"], (int, float)
        )

    tasks = expected_plan["tasks"]
    task_by_key = {task["task_key"]: task for task in tasks}
    _unique(task_by_key)
    acquisition_tasks = [task for task in tasks if task["kind"] == "evidence_acquisition"]
    evaluate_tasks = [task for task in tasks if task["kind"] == "reasoning_evaluate"]
    output_tasks = [task for task in tasks if task["kind"] == "output"]
    assert {task["requirement_id"] for task in acquisition_tasks} == requirement_ids
    assert len(acquisition_tasks) == len(requirements)
    assert len(evaluate_tasks) == len(output_tasks) == 1
    assert all(set(task["depends_on"]) <= set(task_by_key) for task in tasks)
    # Task dependencies point backwards; turn them into parent -> child edges for DAG validation.
    dependency_edges = [
        {"source_node_key": dependency, "target_node_key": task["task_key"]}
        for task in tasks
        for dependency in task["depends_on"]
    ]
    _assert_acyclic(set(task_by_key), dependency_edges, "source_node_key", "target_node_key")
    for task in acquisition_tasks:
        requirement_id = task["requirement_id"]
        assert task["provider_key"] == provider_bindings[requirement_id]["provider_key"]
        assert task["target_entity_id"] == binding_by_requirement[requirement_id]["target_entity_id"]
        assert task["depends_on"] == []
    assert set(evaluate_tasks[0]["depends_on"]) == {task["task_key"] for task in acquisition_tasks}
    assert evaluate_tasks[0]["prepare_id_ref"] == observations["prepare_id"]
    assert output_tasks[0]["depends_on"] == [evaluate_tasks[0]["task_key"]]

    assert expected_reasoning["expected_status"] == "COMPLETE"
    assert expected_reasoning["complete"] is True
    assert expected_reasoning["missing_requirements"] == []
    ranking = expected_reasoning["ranking"]
    requirement_by_id = {requirement["requirement_id"]: requirement for requirement in requirements}
    assert [rank["rank"] for rank in ranking] == list(range(1, len(ranking) + 1))
    assert ranking[0]["node_key"] == "haulage_cycle_time"
    scores = [rank["expected_path_score"] for rank in ranking]
    assert scores == sorted(scores, reverse=True)
    for rank in ranking:
        assert rank["node_key"] in node_keys
        assert all(node in node_keys for node in rank["evidence_chain"])
        assert _has_directed_path(snapshot["edges"], rank["evidence_chain"])
        assert set(rank["evidence_requirement_ids"]) <= requirement_ids
        assert all(
            requirement_by_id[requirement_id]["node_key"] in rank["evidence_chain"]
            for requirement_id in rank["evidence_requirement_ids"]
        )
    assert ranking[0]["expected_path_score"] > ranking[1]["expected_path_score"]


def test_fixture_has_no_unresolved_placeholders() -> None:
    for name in HASHED_FILES:
        content = (FIXTURE_DIR / name).read_text(encoding="utf-8")
        assert "PENDING_GENERATION" not in content, name
        assert "TBD" not in content, name
