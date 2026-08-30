"""T10 contract tests: business no-data and infrastructure failure are distinct."""

from __future__ import annotations

from pathlib import Path

import pytest

from earp_server.bmc.reasoning.runtime import (
    ACQUIRE_CONTRACT,
    EVALUATE_CONTRACT,
    FixtureReasoningRuntimeAdapter,
    ReasoningInfrastructureError,
)

FIXTURE_DIR = Path(__file__).parent / "scenarios" / "mine_3_production_drop"


def _input(requirement_id: str = "prepared-er-haulage-cycle-observation", *, level: str = "required") -> dict:
    source_id = requirement_id.removeprefix("prepared-")
    return {
        "contract": ACQUIRE_CONTRACT,
        "prepare_id": "prepare-case-a",
        "task_id": f"acquire-{source_id}",
        "requirement_id": requirement_id,
        "source_requirement_id": source_id,
        "requirement_key": "haulage_cycle_observation",
        "node_key": "haulage_cycle_time",
        "requirement_level": level,
        "provider_key": "mock-haulage-operations-v1",
        "provider_resolution_status": "bound",
        "target": {"entity_id": "haulage-system-mine-3", "entity_type": "haulage_system"},
        "time_window": {"start": "2026-08-28T00:00:00+08:00", "end": "2026-08-29T00:00:00+08:00"},
        "measurement": {"unit": "min", "aggregation": "avg"},
    }


@pytest.mark.asyncio
async def test_valid_provider_returns_complete_observation_envelope() -> None:
    result = await FixtureReasoningRuntimeAdapter(FIXTURE_DIR).acquire(_input())

    assert result["task_status"] == "completed"
    assert result["terminal_state"] == "business"
    observation = result["observation"]
    assert observation["schema_version"] == "evidence-observation/v1"
    assert observation["status"] == "VALID"
    assert observation["requirement"]["requirement_id"] == "prepared-er-haulage-cycle-observation"
    assert observation["instance"] == {"entity_id": "haulage-system-mine-3", "entity_type": "haulage_system"}
    assert observation["measurement"]["value"] == 51
    assert observation["measurement"]["baseline_value"] == 38
    assert observation["time_window"]["start"].startswith("2026-08-28")
    assert observation["source"] == "fixture://mine-3/haulage-cycle"
    assert observation["provenance"]["provider_key"] == "mock-haulage-operations-v1"


@pytest.mark.asyncio
async def test_data_unavailable_is_completed_business_observation_even_when_required() -> None:
    result = await FixtureReasoningRuntimeAdapter(
        FIXTURE_DIR, unavailable_provider_keys={"mock-haulage-operations-v1"}
    ).acquire(_input())

    assert result["task_status"] == "completed"
    assert result["terminal_state"] == "business"
    observation = result["observation"]
    assert observation["status"] == "DATA_UNAVAILABLE"
    assert observation["error"]["code"] == "DATA_UNAVAILABLE"
    assert observation["timestamp"]
    assert observation["source"]
    assert observation["quality"]["status"] == "data_unavailable"


@pytest.mark.asyncio
async def test_optional_unbound_is_not_skipped_and_reaches_evaluate() -> None:
    adapter = FixtureReasoningRuntimeAdapter(FIXTURE_DIR)
    unavailable = await adapter.acquire(
        {
            **_input("prepared-er-ore-quality-observation", level="optional"),
            "requirement_key": "ore_quality_observation",
            "node_key": "ore_quality",
            "provider_key": None,
            "provider_resolution_status": "unbound_optional",
            "target": {"entity_id": "mine-3", "entity_type": "mine"},
            "measurement": {"unit": "grade_index", "aggregation": "avg"},
        }
    )
    ready = await adapter.evaluate(
        {
            "contract": EVALUATE_CONTRACT,
            "prepare_id": "prepare-case-a",
            "planned_requirement_ids": ["prepared-er-ore-quality-observation"],
        },
        [unavailable],
    )

    assert unavailable["task_status"] == "completed"
    assert ready["status"] == "READY"
    assert ready["missing_optional"] == ["prepared-er-ore-quality-observation"]


@pytest.mark.asyncio
async def test_stale_or_suspicious_quality_is_still_a_business_terminal_state() -> None:
    result = await FixtureReasoningRuntimeAdapter(
        FIXTURE_DIR,
        quality_overrides={"er-haulage-cycle-observation": {"status": "suspicious", "reason": "late sample"}},
    ).acquire(_input())

    assert result["task_status"] == "completed"
    assert result["observation"]["status"] == "SUSPICIOUS"
    assert result["observation"]["quality"]["reason"] == "late sample"


@pytest.mark.asyncio
async def test_infrastructure_failure_raises_and_evaluate_blocks() -> None:
    adapter = FixtureReasoningRuntimeAdapter(FIXTURE_DIR)
    with pytest.raises(ReasoningInfrastructureError) as exc_info:
        await adapter.acquire({**_input(), "simulate_infrastructure_failure": True})
    assert exc_info.value.code == "connection"

    blocked = await adapter.evaluate(
        {
            "contract": EVALUATE_CONTRACT,
            "prepare_id": "prepare-case-a",
            "planned_requirement_ids": ["prepared-er-haulage-cycle-observation"],
        },
        [
            {
                "requirement_id": "prepared-er-haulage-cycle-observation",
                "task_status": "failed",
                "terminal_state": "infrastructure_failed",
                "error": "provider timeout",
            }
        ],
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["infrastructure_failures"][0]["requirement_id"] == "prepared-er-haulage-cycle-observation"
