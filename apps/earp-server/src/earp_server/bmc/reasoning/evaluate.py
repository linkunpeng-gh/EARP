"""Deterministic, pinned-input Case A causal evaluation.

Evaluate deliberately reads only two durable inputs: the ``ReasoningContext``
created by Prepare and the immutable Causal Snapshot it pins.  Provider,
Ontology and editable causal-model tables are not consulted.  The algorithm
registry row is used only to verify the Context's already-pinned configuration
identity; the fixture configuration is *not* an executable-artifact claim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.bmc.metamodel import canonical_json_hash
from earp_server.infra.db import tenant_session


class ReasoningEvaluateError(ValueError):
    """A pinned Case A Context cannot be evaluated safely."""


@dataclass(frozen=True)
class EvaluationResult:
    prepare_id: str
    status: str
    complete: bool
    http_status: int
    ranking: tuple[dict[str, Any], ...]
    missing_required: tuple[str, ...]
    missing_optional: tuple[str, ...]
    infrastructure_failures: tuple[dict[str, Any], ...]
    evaluation_input_hash: str
    result_hash: str
    context_hash: str
    model_snapshot_id: str
    model_content_hash: str
    algorithm_version_id: str
    algorithm_config_hash: str
    algorithm_profile_version: str
    algorithm_params: dict[str, Any]
    algorithm_artifact: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["ranking"] = list(self.ranking)
        value["missing_required"] = list(self.missing_required)
        value["missing_optional"] = list(self.missing_optional)
        value["infrastructure_failures"] = list(self.infrastructure_failures)
        # This is the full Phase-1 payload T12 will archive.  It intentionally
        # makes the absent artifact boundary explicit.
        value["trace_input"] = {
            "prepare_id": self.prepare_id,
            "evaluation_input_hash": self.evaluation_input_hash,
            "context_hash": self.context_hash,
            "model_snapshot_id": self.model_snapshot_id,
            "model_content_hash": self.model_content_hash,
            "algorithm_version_id": self.algorithm_version_id,
            "algorithm_config_hash": self.algorithm_config_hash,
        }
        return value


async def _one(session: AsyncSession, statement: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
    result = await session.execute(text(statement), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReasoningEvaluateError(f"{name} must be an object")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReasoningEvaluateError(f"{name} must be numeric")
    return float(value)


def _direction(rule: Mapping[str, Any], observation: Mapping[str, Any]) -> str:
    """Apply the frozen Case A rule, never a provider-supplied direction."""
    value = _number(observation.get("value"), "observation.value")
    operator = rule.get("operator")
    threshold = _number(rule.get("threshold"), "rule.threshold")
    baseline_raw = observation.get("baseline_value")
    if operator == "absolute_gte":
        return "unchanged" if abs(value) >= threshold else "unknown"
    if baseline_raw is None:
        raise ReasoningEvaluateError("relative causal rule requires observation.baseline_value")
    baseline = _number(baseline_raw, "observation.baseline_value")
    if baseline == 0:
        raise ReasoningEvaluateError("relative causal rule cannot use a zero baseline")
    relative_change = (value - baseline) / abs(baseline)
    if operator == "relative_change_lte":
        return "down" if relative_change <= threshold else "unchanged"
    if operator == "relative_change_gte":
        return "up" if relative_change >= threshold else "unchanged"
    if operator == "absolute_relative_change_lt":
        if abs(relative_change) < threshold:
            return "unchanged"
        return "up" if relative_change > 0 else "down"
    raise ReasoningEvaluateError(f"unsupported frozen causal rule operator: {operator}")


def _propagate(direction: str, effect: str) -> str:
    if direction not in {"up", "down"}:
        return direction
    if effect == "+":
        return direction
    if effect == "-":
        return "down" if direction == "up" else "up"
    raise ReasoningEvaluateError(f"unsupported causal edge effect: {effect}")


def _as_observation(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    observation = record.get("observation")
    return observation if isinstance(observation, Mapping) else None


def _requirement_id(record: Mapping[str, Any]) -> str | None:
    observation = _as_observation(record)
    candidate = observation.get("requirement_id") if observation is not None else record.get("requirement_id")
    return candidate if isinstance(candidate, str) and candidate else None


def _is_infrastructure_failure(record: Mapping[str, Any]) -> bool:
    status = str(record.get("task_status") or record.get("status") or "").lower()
    return status in {"failed", "retrying"} or record.get("terminal_state") == "infrastructure_failed"


def _edge_paths(
    edges: Iterable[Mapping[str, Any]],
    *,
    source: str,
    target: str,
    max_depth: int,
) -> list[list[Mapping[str, Any]]]:
    outgoing: dict[str, list[Mapping[str, Any]]] = {}
    for edge in edges:
        source_key = edge.get("source_node_key")
        if not isinstance(source_key, str):
            raise ReasoningEvaluateError("pinned Snapshot has an invalid edge source")
        outgoing.setdefault(source_key, []).append(edge)
    for values in outgoing.values():
        values.sort(key=lambda item: str(item.get("edge_key", "")))

    paths: list[list[Mapping[str, Any]]] = []

    def visit(node: str, path: list[Mapping[str, Any]], visited: set[str]) -> None:
        if len(path) > max_depth:
            return
        if node == target:
            paths.append(path)
            return
        for edge in outgoing.get(node, []):
            next_node = edge.get("target_node_key")
            if not isinstance(next_node, str) or next_node in visited:
                continue
            visit(next_node, [*path, edge], {*visited, next_node})

    visit(source, [], {source})
    return paths


def _evaluate_graph(
    snapshot: Mapping[str, Any],
    context_requirements: Iterable[Mapping[str, Any]],
    observations: Mapping[str, Mapping[str, Any]],
    algorithm: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    rules = snapshot.get("rules")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(rules, list):
        raise ReasoningEvaluateError("pinned Snapshot causal graph is incomplete")
    node_by_key: dict[str, Mapping[str, Any]] = {}
    for item in nodes:
        if not isinstance(item, Mapping):
            continue
        node_key = item.get("node_key")
        if not isinstance(node_key, str) or not node_key:
            raise ReasoningEvaluateError("pinned Snapshot contains an invalid node")
        node_by_key[node_key] = item
    rule_by_node = {item.get("node_key"): item for item in rules if isinstance(item, Mapping)}
    requirement_by_node: dict[str, Mapping[str, Any]] = {}
    for requirement in context_requirements:
        node_key = requirement.get("node_key")
        requirement_id = requirement.get("requirement_id")
        if not isinstance(node_key, str) or not isinstance(requirement_id, str):
            raise ReasoningEvaluateError("pinned Context has an invalid requirement")
        if requirement_id in observations:
            requirement_by_node[node_key] = requirement

    observed_directions: dict[str, str] = {}
    for node_key, requirement in requirement_by_node.items():
        observation = observations[requirement["requirement_id"]]
        rule = rule_by_node.get(node_key)
        if not isinstance(rule, Mapping):
            raise ReasoningEvaluateError(f"pinned Snapshot has no causal rule for observed node {node_key}")
        observed_directions[node_key] = _direction(rule, observation)

    effects = [key for key, item in node_by_key.items() if item.get("role") == "effect"]
    goal_nodes = [key for key in effects if key in observed_directions and observed_directions[key] in {"up", "down"}]
    if len(goal_nodes) != 1:
        raise ReasoningEvaluateError("Case A requires exactly one observed anomalous effect node")
    goal = goal_nodes[0]
    goal_direction = observed_directions[goal]
    profile = _require_mapping(algorithm.get("profile"), "algorithm.profile")
    max_depth = int(profile.get("max_depth", 0))
    if max_depth < 1:
        raise ReasoningEvaluateError("pinned algorithm profile max_depth must be positive")

    ranked: list[dict[str, Any]] = []
    edge_objects = [edge for edge in edges if isinstance(edge, Mapping)]
    for node_key, node in node_by_key.items():
        if node.get("role") != "cause" or observed_directions.get(node_key) not in {"up", "down"}:
            continue
        requirement = requirement_by_node.get(node_key)
        if requirement is None:
            continue
        candidates: list[dict[str, Any]] = []
        for path in _edge_paths(edge_objects, source=node_key, target=goal, max_depth=max_depth):
            if not path:
                continue
            propagated = observed_directions[node_key]
            score = 1.0
            confidence = 1.0
            chain = [node_key]
            for edge in path:
                propagated = _propagate(propagated, str(edge.get("effect")))
                score *= _number(edge.get("strength"), "edge.strength") * _number(
                    edge.get("confidence"), "edge.confidence"
                )
                confidence *= _number(edge.get("confidence"), "edge.confidence")
                target_key = edge.get("target_node_key")
                if not isinstance(target_key, str):
                    raise ReasoningEvaluateError("pinned Snapshot has invalid edge target")
                chain.append(target_key)
            # Direction conflict is a veto, not weak supporting evidence.
            if propagated != goal_direction:
                continue
            goal_requirement = requirement_by_node.get(goal)
            evidence_source_ids = [str(requirement.get("source_requirement_id"))]
            if goal_requirement is not None:
                evidence_source_ids.append(str(goal_requirement.get("source_requirement_id")))
            candidates.append(
                {
                    "node_key": node_key,
                    "path_score": round(score, 12),
                    "confidence": round(confidence, 12),
                    "evidence_chain": chain,
                    "evidence_requirement_ids": evidence_source_ids,
                    "observed_direction": observed_directions[node_key],
                    "goal_direction": goal_direction,
                }
            )
        if candidates:
            # max_path_score then the frozen tie-breaker.
            ranked.append(
                sorted(
                    candidates,
                    key=lambda item: (-item["path_score"], len(item["evidence_chain"]), item["node_key"]),
                )[0]
            )
    ranked.sort(key=lambda item: (-item["path_score"], len(item["evidence_chain"]), item["node_key"]))
    return tuple({**item, "rank": index} for index, item in enumerate(ranked, start=1))


async def evaluate_case_a_reasoning(
    engine: AsyncEngine,
    tenant_id: str,
    prepare_id: str,
    acquisition_results: Iterable[Mapping[str, Any]],
) -> EvaluationResult:
    """Evaluate archived acquisition outputs against the pinned Case A inputs.

    This service owns semantic completeness.  It does not call a Provider or
    re-run ABox binding; callers must pass every planned acquisition terminal
    result from the already-projected plan.
    """
    records = [dict(item) for item in acquisition_results]
    if not records:
        raise ReasoningEvaluateError("Evaluate requires acquisition terminal results")
    async with tenant_session(engine, tenant_id) as session:
        context = await _one(
            session,
            "SELECT * FROM reasoning_contexts WHERE tenant_id = :tenant_id AND prepare_id = :prepare_id",
            {"tenant_id": tenant_id, "prepare_id": prepare_id},
        )
        if context is None:
            raise ReasoningEvaluateError("ReasoningContext was not found for this tenant")
        if context["status"] != "prepared":
            raise ReasoningEvaluateError(f"ReasoningContext is {context['status']} and cannot be evaluated")

        requirements = context["evidence_requirements"]
        if not isinstance(requirements, list) or not requirements:
            raise ReasoningEvaluateError("pinned Context has no evidence requirements")
        requirement_by_id = {item.get("requirement_id"): item for item in requirements if isinstance(item, Mapping)}
        if len(requirement_by_id) != len(requirements) or not all(isinstance(key, str) for key in requirement_by_id):
            raise ReasoningEvaluateError("pinned Context evidence requirement identities are invalid")
        by_requirement: dict[str, Mapping[str, Any]] = {}
        for record in records:
            requirement_id = _requirement_id(record)
            if requirement_id is None or requirement_id not in requirement_by_id:
                raise ReasoningEvaluateError("acquisition result does not belong to this pinned Context")
            if requirement_id in by_requirement:
                raise ReasoningEvaluateError("duplicate acquisition result for a pinned requirement")
            by_requirement[requirement_id] = record
        missing_terminal = sorted(
            key for key in requirement_by_id if key not in by_requirement and isinstance(key, str)
        )
        if missing_terminal:
            raise ReasoningEvaluateError(f"Evaluate started before all acquisition terminal states: {missing_terminal}")

        snapshot = await _one(
            session,
            "SELECT content_hash, nodes_json, edges_json, rules_json FROM causal_model_snapshots "
            "WHERE tenant_id = :tenant_id AND model_version_id = :model_version_id AND snapshot_id = :snapshot_id",
            {
                "tenant_id": tenant_id,
                "model_version_id": context["model_version_id"],
                "snapshot_id": context["snapshot_id"],
            },
        )
        if snapshot is None or snapshot["content_hash"] != context["snapshot_hash"]:
            raise ReasoningEvaluateError("pinned Causal Snapshot is unavailable or hash-mismatched")
        algorithm = await _one(
            session,
            "SELECT algorithm_id, profile_version, profile_json, algorithm_config_hash, algorithm_config_json, "
            "implementation_hash FROM reasoning_algorithm_versions WHERE algorithm_version_id = :algorithm_version_id",
            {"algorithm_version_id": context["algorithm_version_id"]},
        )
        if (
            algorithm is None
            or algorithm["algorithm_id"] != "sign_propagation"
            or algorithm["profile_version"] != context["algorithm_profile_version"]
            or algorithm["algorithm_config_hash"] != context["algorithm_config_hash"]
            or not isinstance(algorithm["algorithm_config_json"], Mapping)
        ):
            raise ReasoningEvaluateError("pinned sign_propagation algorithm identity is unavailable or hash-mismatched")
        algorithm_config = dict(algorithm["algorithm_config_json"])
        if algorithm_config.get("params") != context["algorithm_params_json"]:
            raise ReasoningEvaluateError("pinned algorithm parameters do not match the ReasoningContext")

        infra = tuple(
            {"requirement_id": requirement_id, "error": record.get("error") or "infrastructure failure"}
            for requirement_id, record in sorted(by_requirement.items())
            if _is_infrastructure_failure(record)
        )
        unavailable: dict[str, Mapping[str, Any]] = {}
        for requirement_id, record in by_requirement.items():
            # A failed connector/auth/runtime task is already classified above
            # as an infrastructure terminal state.  It intentionally has no
            # EvidenceObservation, and must yield BLOCKED rather than being
            # rejected as a malformed business-terminal result.
            if _is_infrastructure_failure(record):
                continue
            observation = _as_observation(record)
            if observation is None:
                raise ReasoningEvaluateError("business terminal result lacks an EvidenceObservation")
            if observation.get("status") == "DATA_UNAVAILABLE":
                unavailable[requirement_id] = observation
        missing_required = tuple(
            sorted(key for key in unavailable if requirement_by_id[key].get("requirement_level") == "required")
        )
        missing_optional = tuple(
            sorted(key for key in unavailable if requirement_by_id[key].get("requirement_level") == "optional")
        )
        observations: dict[str, Mapping[str, Any]] = {}
        for requirement_id, record in by_requirement.items():
            if requirement_id in unavailable:
                continue
            observation = _as_observation(record)
            if observation is not None:
                observations[requirement_id] = observation
        evaluation_input = {
            "prepare_id": prepare_id,
            "context_hash": context["context_hash"],
            "snapshot_hash": context["snapshot_hash"],
            "algorithm_config_hash": context["algorithm_config_hash"],
            "acquisition_results": records,
        }
        evaluation_input_hash = canonical_json_hash(evaluation_input)
        if infra:
            status, complete, http_status, ranking = "BLOCKED", False, 409, ()
        elif missing_required:
            status, complete, http_status, ranking = "FAILED", False, 422, ()
        else:
            ranking = _evaluate_graph(
                {
                    "nodes": snapshot["nodes_json"],
                    "edges": snapshot["edges_json"],
                    "rules": snapshot["rules_json"],
                },
                requirements,
                observations,
                algorithm_config,
            )
            if not ranking:
                status, complete, http_status = "FAILED", False, 422
            elif missing_optional:
                status, complete, http_status = "PARTIAL", False, 200
            else:
                status, complete, http_status = "COMPLETE", True, 200
        result_payload = {
            "status": status,
            "complete": complete,
            "ranking": ranking,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "infrastructure_failures": infra,
            "context_hash": context["context_hash"],
            "snapshot_hash": context["snapshot_hash"],
            "algorithm_config_hash": context["algorithm_config_hash"],
        }
        artifact = algorithm_config.get("implementation_artifact")
        return EvaluationResult(
            prepare_id=prepare_id,
            status=status,
            complete=complete,
            http_status=http_status,
            ranking=ranking,
            missing_required=missing_required,
            missing_optional=missing_optional,
            infrastructure_failures=infra,
            evaluation_input_hash=evaluation_input_hash,
            result_hash=canonical_json_hash(result_payload),
            context_hash=context["context_hash"],
            model_snapshot_id=context["snapshot_id"],
            model_content_hash=context["snapshot_hash"],
            algorithm_version_id=context["algorithm_version_id"],
            algorithm_config_hash=context["algorithm_config_hash"],
            algorithm_profile_version=context["algorithm_profile_version"],
            algorithm_params=dict(context["algorithm_params_json"]),
            algorithm_artifact=dict(artifact) if isinstance(artifact, Mapping) else {"status": "unknown"},
        )


__all__ = ["EvaluationResult", "ReasoningEvaluateError", "evaluate_case_a_reasoning"]
