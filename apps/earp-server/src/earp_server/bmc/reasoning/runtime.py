"""Case A evidence acquisition runtime boundary.

This module deliberately stops at the EvidenceObservation envelope.  It does
not execute the causal algorithm and it does not turn a missing business row
into an exception.  The distinction is important for the first Blueprint
slice:

* a provider returning no business data is a completed acquisition with a
  ``DATA_UNAVAILABLE`` observation;
* a provider/connector/auth/runtime failure is an exception and therefore a
  failed task;
* Evaluate only receives a readiness envelope.  T11 owns COMPLETE/PARTIAL/
  FAILED causal semantics.

The fixture provider is intentionally explicit and deterministic.  It is a
test-slice adapter, not a replacement for ``tool.fetch`` or a live provider.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ACQUIRE_CONTRACT = "case-a-evidence-acquisition/v1"
OBSERVATION_SCHEMA = "evidence-observation/v1"
EVALUATE_CONTRACT = "case-a-reasoning-evaluate/v1"


class ReasoningRuntimeError(RuntimeError):
    """Invalid runtime input or an unusable fixture provider response."""

    code = "validation"


class ReasoningInfrastructureError(ReasoningRuntimeError):
    """A provider/connector/runtime failure, distinct from business no-data."""

    code = "connection"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReasoningRuntimeError(f"reasoning runtime requires {name}")
    return value


def _load_observations(fixture_dir: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads((fixture_dir / "evidence_observations.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReasoningInfrastructureError("Case A evidence observation fixture is unavailable") from error
    if not isinstance(document, dict) or document.get("schema_version") != "evidence-observations/v1":
        raise ReasoningRuntimeError("unsupported Case A evidence observation fixture schema")
    observations = document.get("observations")
    if not isinstance(observations, list) or not all(isinstance(item, dict) for item in observations):
        raise ReasoningRuntimeError("Case A evidence observation fixture must contain an object list")
    return [dict(item) for item in observations]


def _observation(
    input_: Mapping[str, Any],
    *,
    provider_key: str | None,
    source_ref: str,
    status: str,
    quality: Mapping[str, Any],
    value: object = None,
    baseline_value: object = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable, self-contained EvidenceObservation envelope."""
    requirement_id = _required_string(input_.get("requirement_id"), "requirement_id")
    source_requirement_id = _required_string(input_.get("source_requirement_id"), "source_requirement_id")
    requirement_key = _required_string(input_.get("requirement_key"), "requirement_key")
    node_key = _required_string(input_.get("node_key"), "node_key")
    target = input_.get("target")
    if not isinstance(target, Mapping):
        raise ReasoningRuntimeError("reasoning runtime requires target")
    entity_id = _required_string(target.get("entity_id"), "target.entity_id")
    entity_type = _required_string(target.get("entity_type"), "target.entity_type")
    time_window = input_.get("time_window")
    if not isinstance(time_window, Mapping):
        raise ReasoningRuntimeError("reasoning runtime requires time_window")
    unit = None
    measurement = input_.get("measurement")
    if isinstance(measurement, Mapping):
        unit = measurement.get("unit")
    timestamp = quality.get("observed_at") if isinstance(quality, Mapping) else None
    timestamp = timestamp if isinstance(timestamp, str) and timestamp else _now()
    provenance = {
        "provider_key": provider_key,
        "source_ref": source_ref,
        "prepare_id": input_.get("prepare_id"),
        "task_id": input_.get("task_id") or input_.get("execution_id"),
    }
    # Do not put absent execution identities in an envelope as fabricated IDs.
    provenance = {key: val for key, val in provenance.items() if val is not None}
    result: dict[str, Any] = {
        "schema_version": OBSERVATION_SCHEMA,
        "observation_id": f"{requirement_id}:{timestamp}",
        "status": status,
        "timestamp": timestamp,
        "requirement": {
            "requirement_id": requirement_id,
            "source_requirement_id": source_requirement_id,
            "requirement_key": requirement_key,
            "node_key": node_key,
            "requirement_level": input_.get("requirement_level"),
        },
        "instance": {"entity_id": entity_id, "entity_type": entity_type},
        "measurement": {
            "value": value,
            "baseline_value": baseline_value,
            "unit": unit,
            "aggregation": measurement.get("aggregation") if isinstance(measurement, Mapping) else None,
        },
        "time_window": dict(time_window),
        "source": source_ref,
        "quality": dict(quality),
        "provenance": provenance,
        # Flat aliases make the envelope easy to inspect while the nested
        # fields above remain the canonical contract for downstream services.
        "requirement_id": requirement_id,
        "requirement_key": requirement_key,
        "node_key": node_key,
        "entity_id": entity_id,
        "value": value,
        "baseline_value": baseline_value,
        "unit": unit,
    }
    if error is not None:
        result["error"] = dict(error)
    return result


class FixtureReasoningRuntimeAdapter:
    """Deterministic Case A mock providers plus runtime terminal semantics."""

    def __init__(
        self,
        fixture_dir: Path,
        *,
        unavailable_provider_keys: set[str] | None = None,
        infrastructure_failure_provider_keys: set[str] | None = None,
        quality_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._fixture_dir = fixture_dir
        self._observations = _load_observations(fixture_dir)
        self._unavailable = unavailable_provider_keys or set()
        self._infra_failures = infrastructure_failure_provider_keys or set()
        self._quality_overrides = quality_overrides or {}

    async def acquire(self, input_: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one acquisition and return a completed business envelope.

        ``DATA_UNAVAILABLE`` is intentionally returned, never raised.  An
        optional unbound requirement follows the same path so that its task is
        still present as an Evaluate dependency.
        """
        if not isinstance(input_, Mapping):
            raise ReasoningRuntimeError("reasoning.acquire input must be an object")
        if input_.get("contract") not in {None, ACQUIRE_CONTRACT}:
            raise ReasoningRuntimeError("unsupported reasoning.acquire contract")
        provider_key = input_.get("provider_key")
        if provider_key is not None and not isinstance(provider_key, str):
            raise ReasoningRuntimeError("provider_key must be a string or null")
        provider_key = provider_key or None
        outcome = str(input_.get("provider_outcome") or input_.get("mock_outcome") or "").upper()
        if outcome in {"INFRA_FAILURE", "FAILED", "CRASH", "AUTH_FAILURE"}:
            raise ReasoningInfrastructureError(f"provider {provider_key or '<unbound>'} failed")
        if provider_key in self._infra_failures or input_.get("simulate_infrastructure_failure") is True:
            raise ReasoningInfrastructureError(f"provider {provider_key or '<unbound>'} failed")

        source_requirement_id = _required_string(input_.get("source_requirement_id"), "source_requirement_id")
        target = input_.get("target")
        if not isinstance(target, Mapping):
            raise ReasoningRuntimeError("reasoning.acquire target must be an object")
        unavailable = (
            outcome in {"DATA_UNAVAILABLE", "NO_DATA", "UNAVAILABLE"}
            or input_.get("provider_resolution_status") == "unbound_optional"
            or provider_key in self._unavailable
        )
        source_ref = f"fixture://case-a/{source_requirement_id}"
        match = next((item for item in self._observations if item.get("requirement_id") == source_requirement_id), None)
        if match is not None:
            provenance = match.get("provenance")
            if isinstance(provenance, Mapping):
                source_ref = str(provenance.get("source_ref") or source_ref)
        if unavailable or match is None:
            if match is not None and isinstance(match.get("provenance"), Mapping):
                source_ref = str(match["provenance"].get("source_ref") or source_ref)
            quality: dict[str, Any] = {"status": "data_unavailable", "observed_at": _now()}
            quality_override = self._quality_overrides.get(source_requirement_id)
            if quality_override:
                quality.update(quality_override)
            observation = _observation(
                input_,
                provider_key=provider_key,
                source_ref=source_ref,
                status="DATA_UNAVAILABLE",
                quality=quality,
                error={"code": "DATA_UNAVAILABLE", "message": "provider returned no business data"},
            )
            return {
                "terminal_state": "business",
                "task_status": "completed",
                "requirement_id": input_.get("requirement_id"),
                "requirement_level": input_.get("requirement_level"),
                "observation": observation,
            }

        expected_entity = match.get("entity_id")
        expected_type = (
            input_.get("target", {}).get("entity_type") if isinstance(input_.get("target"), Mapping) else None
        )
        if expected_entity != target.get("entity_id"):
            raise ReasoningRuntimeError("provider observation entity does not match pinned target")
        # Entity type is represented by Prepare's target and by provider scope;
        # the fixture observation intentionally has no second mutable binding.
        if not isinstance(expected_type, str) or not expected_type:
            raise ReasoningRuntimeError("reasoning.acquire target entity type is missing")
        quality = match.get("quality") if isinstance(match.get("quality"), Mapping) else {"status": "valid"}
        quality = dict(quality)
        quality_override = self._quality_overrides.get(source_requirement_id)
        if quality_override:
            quality.update(quality_override)
        observation = _observation(
            input_,
            provider_key=provider_key,
            source_ref=source_ref,
            status=str(quality.get("status") or "valid").upper(),
            quality=quality,
            value=match.get("value"),
            baseline_value=match.get("baseline_value"),
        )
        return {
            "terminal_state": "business",
            "task_status": "completed",
            "requirement_id": input_.get("requirement_id"),
            "requirement_level": input_.get("requirement_level"),
            "observation": observation,
        }

    async def evaluate(
        self,
        input_: Mapping[str, Any],
        acquisition_results: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Check acquisition readiness without performing causal inference."""
        if not isinstance(input_, Mapping):
            raise ReasoningRuntimeError("reasoning.evaluate input must be an object")
        if input_.get("contract") not in {None, EVALUATE_CONTRACT}:
            raise ReasoningRuntimeError("unsupported reasoning.evaluate contract")
        prepare_id = _required_string(input_.get("prepare_id"), "prepare_id")
        planned = input_.get("planned_requirement_ids")
        if not isinstance(planned, list) or not planned or not all(isinstance(item, str) and item for item in planned):
            raise ReasoningRuntimeError("reasoning.evaluate requires planned_requirement_ids")
        records = acquisition_results
        if records is None:
            records = input_.get("acquisition_results")
        if not isinstance(records, Iterable) or isinstance(records, (str, bytes, Mapping)):
            raise ReasoningRuntimeError("reasoning.evaluate requires all acquisition results")
        by_requirement: dict[str, Mapping[str, Any]] = {}
        for record in records:
            if not isinstance(record, Mapping):
                raise ReasoningRuntimeError("reasoning.evaluate acquisition result must be an object")
            observation = record.get("observation")
            requirement_id = (
                observation.get("requirement_id") if isinstance(observation, Mapping) else record.get("requirement_id")
            )
            if isinstance(requirement_id, str):
                by_requirement[requirement_id] = record
        missing = [item for item in planned if item not in by_requirement]
        if missing:
            raise ReasoningRuntimeError(f"reasoning.evaluate started before acquisition terminal state: {missing}")

        infrastructure_failures: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        for requirement_id in planned:
            record = by_requirement[requirement_id]
            task_status = str(record.get("task_status") or record.get("status") or "").lower()
            if task_status in {"failed", "retrying"} or record.get("terminal_state") == "infrastructure_failed":
                infrastructure_failures.append(
                    {"requirement_id": requirement_id, "error": record.get("error") or "infrastructure failure"}
                )
            observation = record.get("observation")
            if isinstance(observation, Mapping):
                observations.append(dict(observation))
        if infrastructure_failures:
            return {
                "contract": EVALUATE_CONTRACT,
                "prepare_id": prepare_id,
                "status": "BLOCKED",
                "terminal": True,
                "observations": observations,
                "infrastructure_failures": infrastructure_failures,
                "missing_required": [],
                "missing_optional": [],
            }
        # Requirement level is kept in the acquisition record by callers; do
        # not guess it from the observation.
        missing_required = []
        missing_optional: list[str] = []
        for requirement_id in planned:
            observation = by_requirement[requirement_id].get("observation")
            if not isinstance(observation, Mapping) or observation.get("status") != "DATA_UNAVAILABLE":
                continue
            level = by_requirement[requirement_id].get("requirement_level")
            if level == "required":
                missing_required.append(requirement_id)
            elif level == "optional":
                missing_optional.append(requirement_id)
        return {
            "contract": EVALUATE_CONTRACT,
            "prepare_id": prepare_id,
            "status": "READY",
            "terminal": True,
            "observations": observations,
            "infrastructure_failures": [],
            "missing_required": missing_required,
            "missing_optional": missing_optional,
        }


def default_case_a_fixture_dir() -> Path:
    """Resolve the checked-in fixture path used by the thin Connector hook."""
    return Path(__file__).resolve().parents[4] / "tests" / "scenarios" / "mine_3_production_drop"


__all__ = [
    "ACQUIRE_CONTRACT",
    "EVALUATE_CONTRACT",
    "FixtureReasoningRuntimeAdapter",
    "OBSERVATION_SCHEMA",
    "ReasoningInfrastructureError",
    "ReasoningRuntimeError",
    "default_case_a_fixture_dir",
]
