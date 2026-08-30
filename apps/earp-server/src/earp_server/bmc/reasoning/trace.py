"""Durable Case A reasoning traces and audit-only replay.

The trace is the hand-off from Evaluate to auditability.  It stores the complete
acquisition envelopes and the pinned inputs needed to explain the historical
result.  Replay reads that archive only; it never resolves a provider, reads a
live ontology/model, or invokes an algorithm implementation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.bmc.metamodel import canonical_json_hash
from earp_server.bmc.reasoning.evaluate import EvaluationResult
from earp_server.infra.db import tenant_session


class ReasoningTraceError(ValueError):
    """A trace cannot be archived or its historical hash cannot be verified."""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _one(session: AsyncSession, statement: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
    result = await session.execute(text(statement), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


def _records(value: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = [dict(item) for item in value]
    if not records:
        raise ReasoningTraceError("a reasoning trace requires acquisition records")
    if any(not isinstance(item, dict) for item in records):
        raise ReasoningTraceError("acquisition records must be objects")
    return records


def _trace_id(tenant_id: str, prepare_id: str, evaluation_input_hash: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}\0{prepare_id}\0{evaluation_input_hash}".encode()).hexdigest()
    return f"rtrace-{digest[:56]}"


def _result_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild T11's result hash payload from an archived result."""
    required = (
        "status",
        "complete",
        "ranking",
        "missing_required",
        "missing_optional",
        "infrastructure_failures",
        "context_hash",
        "snapshot_hash",
        "algorithm_config_hash",
    )
    if any(key not in result for key in required if key != "snapshot_hash"):
        raise ReasoningTraceError("archived evaluation result is incomplete")
    snapshot_hash = result.get("snapshot_hash", result.get("model_content_hash"))
    if not isinstance(snapshot_hash, str) or not snapshot_hash:
        raise ReasoningTraceError("archived evaluation result is missing snapshot hash")
    return {**{key: result[key] for key in required if key != "snapshot_hash"}, "snapshot_hash": snapshot_hash}


def _verify_archive_hashes(trace: Mapping[str, Any]) -> None:
    observations = trace.get("observations")
    result = trace.get("result")
    trace_input = result.get("trace_input") if isinstance(result, Mapping) else None
    if not isinstance(observations, list) or not isinstance(result, Mapping) or not isinstance(trace_input, Mapping):
        raise ReasoningTraceError("archived reasoning trace is incomplete")
    evaluation_input = {
        "prepare_id": trace_input.get("prepare_id"),
        "context_hash": trace_input.get("context_hash"),
        "snapshot_hash": trace_input.get("model_content_hash"),
        "algorithm_config_hash": trace_input.get("algorithm_config_hash"),
        "acquisition_results": observations,
    }
    input_hash = canonical_json_hash(evaluation_input)
    if input_hash != trace_input.get("evaluation_input_hash"):
        raise ReasoningTraceError("archived evaluation input hash mismatch")
    result_hash = canonical_json_hash(_result_payload(result))
    if result_hash != result.get("result_hash"):
        raise ReasoningTraceError("archived result hash mismatch")


@dataclass(frozen=True)
class TraceArchiveResult:
    tenant_id: str
    trace_id: str
    prepare_id: str
    evaluation_input_hash: str
    result_hash: str
    status: str
    reused: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "prepare_id": self.prepare_id,
            "evaluation_input_hash": self.evaluation_input_hash,
            "result_hash": self.result_hash,
            "status": self.status,
            "reused": self.reused,
            "replay_mode": "audit_only",
            "executable_replay": False,
        }


@dataclass(frozen=True)
class AuditReplayResult:
    tenant_id: str
    trace_id: str
    prepare_id: str
    observations: tuple[dict[str, Any], ...]
    evidence_items: tuple[dict[str, Any], ...]
    result: dict[str, Any]
    pinned_inputs: dict[str, Any]
    lineage: dict[str, Any]
    status: str
    hashes_verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "prepare_id": self.prepare_id,
            "observations": list(self.observations),
            "evidence_items": list(self.evidence_items),
            "result": self.result,
            "pinned_inputs": self.pinned_inputs,
            "lineage": self.lineage,
            "status": self.status,
            "hashes_verified": self.hashes_verified,
            "replay_mode": "audit_only",
            "executable_replay": False,
        }


async def archive_case_a_reasoning(
    engine: AsyncEngine,
    tenant_id: str,
    evaluation: EvaluationResult,
    acquisition_results: Iterable[Mapping[str, Any]],
    *,
    lineage: Mapping[str, Any] | None = None,
    latency_ms: int | None = None,
) -> TraceArchiveResult:
    """Persist one evaluated attempt and consume its Context atomically.

    The Context row is locked before checking the existing trace.  Therefore a
    retry with the same input returns the existing archive, while a different
    input is rejected even when two workers race.  ``BLOCKED`` is represented as
    the existing schema's ``failed`` trace status; the original status remains
    in the archived result payload.
    """
    if not evaluation.prepare_id or evaluation.prepare_id != evaluation.as_dict()["trace_input"]["prepare_id"]:
        raise ReasoningTraceError("evaluation prepare_id is invalid")
    records = _records(acquisition_results)
    evaluation_dict = evaluation.as_dict()
    trace_input = evaluation_dict["trace_input"]
    if not isinstance(trace_input, Mapping):
        raise ReasoningTraceError("evaluation trace input is missing")
    trace_id = _trace_id(tenant_id, evaluation.prepare_id, evaluation.evaluation_input_hash)
    evidence_items = [
        dict(record["observation"]) for record in records if isinstance(record.get("observation"), Mapping)
    ]
    async with tenant_session(engine, tenant_id) as session:
        context = await _one(
            session,
            "SELECT * FROM reasoning_contexts WHERE tenant_id = :tenant_id AND prepare_id = :prepare_id FOR UPDATE",
            {"tenant_id": tenant_id, "prepare_id": evaluation.prepare_id},
        )
        if context is None:
            raise ReasoningTraceError("ReasoningContext was not found for this tenant")
        for key, expected in (
            ("context_hash", evaluation.context_hash),
            ("snapshot_id", evaluation.model_snapshot_id),
            ("snapshot_hash", evaluation.model_content_hash),
            ("algorithm_version_id", evaluation.algorithm_version_id),
            ("algorithm_config_hash", evaluation.algorithm_config_hash),
        ):
            if context[key] != expected:
                raise ReasoningTraceError(f"evaluation pin does not match Context {key}")

        existing = await _one(
            session,
            "SELECT trace_id, evaluation_input_hash, result_snapshot, status FROM reasoning_traces "
            "WHERE tenant_id = :tenant_id AND prepare_id = :prepare_id",
            {"tenant_id": tenant_id, "prepare_id": evaluation.prepare_id},
        )
        if existing is not None:
            if existing["evaluation_input_hash"] != evaluation.evaluation_input_hash:
                raise ReasoningTraceError(
                    "prepare_id has already been consumed by a different evaluation input; create a new Prepare"
                )
            return TraceArchiveResult(
                tenant_id,
                str(existing["trace_id"]),
                evaluation.prepare_id,
                evaluation.evaluation_input_hash,
                str(existing["result_snapshot"].get("result_hash", evaluation.result_hash)),
                str(existing["status"]),
                True,
            )
        if context["status"] != "prepared":
            raise ReasoningTraceError(f"ReasoningContext is {context['status']} and has no trace to reuse")

        snapshot = await _one(
            session,
            "SELECT model_version_id, snapshot_id, content_hash, nodes_json, edges_json, rules_json, "
            "requirements_json, applicability_snapshot FROM causal_model_snapshots "
            "WHERE tenant_id = :tenant_id AND model_version_id = :model_version_id AND snapshot_id = :snapshot_id",
            {
                "tenant_id": tenant_id,
                "model_version_id": context["model_version_id"],
                "snapshot_id": context["snapshot_id"],
            },
        )
        if snapshot is None or snapshot["content_hash"] != context["snapshot_hash"]:
            raise ReasoningTraceError("pinned Causal Snapshot is unavailable or hash-mismatched")

        pinned_inputs = {
            "context": {
                "prepare_id": context["prepare_id"],
                "context_hash": context["context_hash"],
                "model_version_id": context["model_version_id"],
                "snapshot_id": context["snapshot_id"],
                "snapshot_hash": context["snapshot_hash"],
                "target": context["target_json"],
                "time_window": context["time_window_json"],
                "instance_snapshot": context["instance_snapshot"],
                "evidence_requirements": context["evidence_requirements"],
                "scope_meta": context["scope_meta"],
            },
            "causal_snapshot": {
                key: snapshot[key]
                for key in (
                    "model_version_id",
                    "snapshot_id",
                    "content_hash",
                    "nodes_json",
                    "edges_json",
                    "rules_json",
                    "requirements_json",
                    "applicability_snapshot",
                )
            },
            "algorithm": {
                "algorithm_version_id": evaluation.algorithm_version_id,
                "profile_version": evaluation.algorithm_profile_version,
                "params": evaluation.algorithm_params,
                "config_hash": evaluation.algorithm_config_hash,
                "artifact": evaluation.algorithm_artifact,
            },
        }
        provenance = {
            "schema_version": "case-a-reasoning-trace/v1",
            "replay_mode": "audit_only",
            "executable_replay": False,
            "lineage": dict(lineage or {}),
            "pinned_inputs": pinned_inputs,
        }
        db_status = "failed" if evaluation.status == "BLOCKED" else evaluation.status.lower()
        if db_status not in {"complete", "partial", "failed"}:
            raise ReasoningTraceError(f"unsupported evaluation status: {evaluation.status}")
        await session.execute(
            text(
                "INSERT INTO reasoning_traces (tenant_id, trace_id, prepare_id, evaluation_input_hash, "
                "model_version_id, snapshot_id, observations_json, evidence_items_json, result_snapshot, "
                "status, latency_ms, provenance_json) VALUES (:tenant_id, :trace_id, :prepare_id, "
                ":evaluation_input_hash, :model_version_id, :snapshot_id, :observations_json, "
                ":evidence_items_json, :result_snapshot, :status, :latency_ms, :provenance_json)"
            ),
            {
                "tenant_id": tenant_id,
                "trace_id": trace_id,
                "prepare_id": evaluation.prepare_id,
                "evaluation_input_hash": evaluation.evaluation_input_hash,
                "model_version_id": context["model_version_id"],
                "snapshot_id": context["snapshot_id"],
                "observations_json": _json(records),
                "evidence_items_json": _json(evidence_items),
                "result_snapshot": _json(evaluation_dict),
                "status": db_status,
                "latency_ms": latency_ms,
                "provenance_json": _json(provenance),
            },
        )
        await session.execute(
            text(
                "UPDATE reasoning_contexts SET status = 'consumed' WHERE tenant_id = :tenant_id "
                "AND prepare_id = :prepare_id AND status = 'prepared'"
            ),
            {"tenant_id": tenant_id, "prepare_id": evaluation.prepare_id},
        )
        audit_detail = {
            "trace_id": trace_id,
            "prepare_id": evaluation.prepare_id,
            "evaluation_input_hash": evaluation.evaluation_input_hash,
            "result_hash": evaluation.result_hash,
            "status": evaluation.status,
            "replay_mode": "audit_only",
            "executable_replay": False,
        }
        await session.execute(
            text(
                "INSERT INTO audit_logs (tenant_id, event_type, entity_type, entity_id, detail) "
                "VALUES (:tenant_id, 'earp.reasoning.trace.archived', 'reasoning_trace', :trace_id, :detail)"
            ),
            {"tenant_id": tenant_id, "trace_id": trace_id, "detail": _json(audit_detail)},
        )
        return TraceArchiveResult(
            tenant_id,
            trace_id,
            evaluation.prepare_id,
            evaluation.evaluation_input_hash,
            evaluation.result_hash,
            db_status,
            False,
        )


async def replay_case_a_reasoning_trace(
    engine: AsyncEngine,
    tenant_id: str,
    trace_id: str,
) -> AuditReplayResult:
    """Return an integrity-checked historical explanation without live reads."""
    async with tenant_session(engine, tenant_id) as session:
        trace = await _one(
            session,
            "SELECT trace_id, prepare_id, observations_json, evidence_items_json, result_snapshot, "
            "provenance_json, status FROM reasoning_traces WHERE tenant_id = :tenant_id AND trace_id = :trace_id",
            {"tenant_id": tenant_id, "trace_id": trace_id},
        )
        if trace is None:
            raise ReasoningTraceError("ReasoningTrace was not found for this tenant")
        observations = trace["observations_json"]
        evidence_items = trace["evidence_items_json"]
        result = trace["result_snapshot"]
        provenance = trace["provenance_json"]
        archived = {
            "observations": observations,
            "result": result,
            "trace_input": result.get("trace_input") if isinstance(result, Mapping) else None,
        }
        _verify_archive_hashes(archived)
        if not isinstance(observations, list) or not isinstance(evidence_items, list):
            raise ReasoningTraceError("archived evidence is not a JSON list")
        if not isinstance(provenance, Mapping):
            raise ReasoningTraceError("archived provenance is incomplete")
        pinned_inputs = provenance.get("pinned_inputs")
        lineage = provenance.get("lineage")
        if not isinstance(pinned_inputs, Mapping) or not isinstance(lineage, Mapping):
            raise ReasoningTraceError("archived lineage is incomplete")
        return AuditReplayResult(
            tenant_id=tenant_id,
            trace_id=str(trace["trace_id"]),
            prepare_id=str(trace["prepare_id"]),
            observations=tuple(dict(item) for item in observations if isinstance(item, Mapping)),
            evidence_items=tuple(dict(item) for item in evidence_items if isinstance(item, Mapping)),
            result=dict(result),
            pinned_inputs=dict(pinned_inputs),
            lineage=dict(lineage),
            status=str(trace["status"]),
            hashes_verified=True,
        )


__all__ = [
    "AuditReplayResult",
    "ReasoningTraceError",
    "TraceArchiveResult",
    "archive_case_a_reasoning",
    "replay_case_a_reasoning_trace",
]
