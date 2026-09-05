"""Case A deterministic Planning Blueprint entry.

T07 is deliberately limited to intent/goal resolution and immutable Blueprint
discovery.  It returns a planning context for T08; it does not create Evidence
tasks, call a provider, or use the legacy ``/plan`` implementation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.bmc.metamodel import canonical_json_hash
from earp_server.file_dataset import published_snapshot
from earp_server.infra.db import tenant_session
from earp_server.planner.blueprint_discovery import (
    DiscoveredBlueprint,
    discover_compiled_causal_blueprint,
)

DEFAULT_CASE_A_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "scenarios" / "mine_3_production_drop"


class BlueprintEntryError(ValueError):
    """The Case A fixture request cannot enter the Blueprint path safely."""


@dataclass(frozen=True)
class PlanningEntryRequest:
    text: str
    tenant_id: str
    role_id: str
    dataset_id: str | None = None


@dataclass(frozen=True)
class PlanningEntryResult:
    fixture_hash: str
    prompt_version: str
    structured_output_schema_version: str
    parsed_intent: dict[str, str]
    blueprint: DiscoveredBlueprint
    goal: dict[str, Any]
    file_dataset: dict[str, Any] | None = None
    prepare_status: str = "not_prepared"

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_contract": "case-a-blueprint-entry/v1",
            "intent_fixture": {
                "fixture_hash": self.fixture_hash,
                "prompt_version": self.prompt_version,
                "structured_output_schema_version": self.structured_output_schema_version,
            },
            "parsed_intent": self.parsed_intent,
            "blueprint": {
                "blueprint_id": self.blueprint.blueprint_id,
                "blueprint_version_id": self.blueprint.blueprint_version_id,
                "blueprint_version": self.blueprint.blueprint_version,
                "compile_record_id": self.blueprint.compile_record_id,
                "source_snapshot_id": self.blueprint.source_snapshot_id,
                "source_content_hash": self.blueprint.source_content_hash,
            },
            "goals": [self.goal],
            "execution_profile": {"file_dataset": self.file_dataset},
            # T08 consumes this immutable selection + bindings as input.  It is
            # intentionally clear that Prepare and dynamic Evidence expansion
            # have not happened at the planning-entry boundary.
            "prepare": {"status": self.prepare_status, "prepare_id": None},
        }


@dataclass(frozen=True)
class _IntentFixture:
    fixture_hash: str
    prompt_version: str
    structured_output_schema_version: str
    input: dict[str, Any]
    parsed_intent: dict[str, str]
    sub_goal: dict[str, Any]
    resolved_context: dict[str, Any]


def _read_intent_fixture(fixture_dir: Path) -> _IntentFixture:
    path = fixture_dir / "intent_goal_fixture.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BlueprintEntryError("Case A intent fixture is unavailable or invalid") from error
    if not isinstance(document, dict) or document.get("schema_version") != "intent-goal-fixture/v1":
        raise BlueprintEntryError("unsupported Case A intent fixture schema")
    fixture_hash = document.get("fixture_hash")
    payload = {key: value for key, value in document.items() if key != "fixture_hash"}
    if not isinstance(fixture_hash, str) or canonical_json_hash(payload) != fixture_hash:
        raise BlueprintEntryError("Case A intent fixture semantic hash mismatch")
    output = document.get("output")
    if not isinstance(output, dict):
        raise BlueprintEntryError("Case A intent fixture output is required")
    parsed = output.get("parsed_intent")
    sub_goals = output.get("sub_goals")
    context = output.get("resolved_context")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("primary_intent"), dict):
        raise BlueprintEntryError("Case A intent fixture primary intent is required")
    if not isinstance(sub_goals, list) or len(sub_goals) != 1 or not isinstance(sub_goals[0], dict):
        raise BlueprintEntryError("Case A intent fixture must contain exactly one SubGoal")
    if not isinstance(context, dict):
        raise BlueprintEntryError("Case A intent fixture resolved context is required")
    primary = parsed["primary_intent"]
    required_intent = {"entry_point", "direction", "domain", "business_objective"}
    if set(primary) != required_intent or not all(
        isinstance(primary[key], str) and primary[key] for key in required_intent
    ):
        raise BlueprintEntryError("Case A intent fixture has an incomplete primary intent")
    sub_goal = sub_goals[0]
    if any(sub_goal.get(key) != primary[key] for key in ("entry_point", "direction", "domain")):
        raise BlueprintEntryError("Case A SubGoal does not match its parsed intent")
    if sub_goal.get("objective") != primary["business_objective"] or sub_goal.get("objective") != "diagnose":
        raise BlueprintEntryError("Case A fixture only supports one diagnose SubGoal")
    if sub_goal.get("dependencies") != []:
        raise BlueprintEntryError("Case A fixture SubGoal must not have dependencies")
    if not isinstance(document.get("input"), dict):
        raise BlueprintEntryError("Case A intent fixture input is required")
    versions = (document.get("prompt_version"), document.get("structured_output_schema_version"))
    if not all(isinstance(value, str) and value for value in versions):
        raise BlueprintEntryError("Case A intent fixture versions are required")
    return _IntentFixture(
        fixture_hash=fixture_hash,
        prompt_version=document["prompt_version"],
        structured_output_schema_version=document["structured_output_schema_version"],
        input=document["input"],
        parsed_intent=primary,
        sub_goal=sub_goal,
        resolved_context=context,
    )


def _validated_time_window(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise BlueprintEntryError("Case A time window must contain only start and end")
    start, end = value["start"], value["end"]
    if not isinstance(start, str) or not isinstance(end, str):
        raise BlueprintEntryError("Case A time window values must be strings")
    try:
        parsed_start, parsed_end = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError as error:
        raise BlueprintEntryError("Case A time window is not ISO-8601") from error
    if parsed_start.tzinfo is None or parsed_end.tzinfo is None or parsed_start >= parsed_end:
        raise BlueprintEntryError("Case A time window must be timezone-aware and ordered")
    return {"start": start, "end": end}


class BlueprintPlanningEntry:
    """Fixture-backed adapter for the new, explicit Case A route."""

    def __init__(self, engine: AsyncEngine, fixture_dir: Path = DEFAULT_CASE_A_FIXTURE_DIR) -> None:
        self._engine = engine
        self._fixture_dir = fixture_dir

    async def resolve(self, request: PlanningEntryRequest) -> PlanningEntryResult:
        fixture = _read_intent_fixture(self._fixture_dir)
        if request.tenant_id != fixture.input.get("tenant_id") or request.text != fixture.input.get("text"):
            raise BlueprintEntryError("request does not match the fixed Case A intent fixture")
        if not request.role_id:
            raise BlueprintEntryError("a role-scoped request is required")

        context = fixture.resolved_context
        entity_id, entity_type = context.get("entity_id"), context.get("entity_type")
        if not isinstance(entity_id, str) or not entity_id or not isinstance(entity_type, str) or not entity_type:
            raise BlueprintEntryError("Case A fixture target identity is incomplete")
        time_window = _validated_time_window(context.get("time_window"))
        blueprint = await discover_compiled_causal_blueprint(
            self._engine,
            request.tenant_id,
            **fixture.parsed_intent,
        )
        await self._validate_role_and_target(request.tenant_id, request.role_id, entity_id, entity_type, blueprint)
        if entity_type not in blueprint.applicability.get("entity_types", []):
            raise BlueprintEntryError("fixture target type is outside the pinned Source Snapshot applicability")
        if blueprint.applicability.get("domain") != fixture.parsed_intent["domain"]:
            raise BlueprintEntryError("pinned Source Snapshot applicability conflicts with the resolved intent")
        if set(blueprint.required_bindings) != {"entity_id", "time_window"}:
            raise BlueprintEntryError("Case A Goal Skeleton bindings are incompatible with the fixed entry contract")

        goal = {
            "goal_instance_key": fixture.sub_goal["sub_goal_key"],
            "goal_skeleton_id": blueprint.goal_skeleton_id,
            "objective": fixture.sub_goal["objective"],
            "entry_point": fixture.parsed_intent["entry_point"],
            "bindings": {"entity_id": entity_id, "entity_type": entity_type, "time_window": time_window},
            "output_contract_ref": blueprint.output_contract_ref,
        }
        dataset_pin = None
        if request.dataset_id:
            snapshot = await published_snapshot(self._engine, request.tenant_id, request.dataset_id)
            if snapshot is None:
                raise BlueprintEntryError("selected file dataset is not published or not visible to this tenant")
            dataset_pin = {
                "dataset_id": snapshot["dataset_id"],
                "content_hash": snapshot["content_hash"],
                "manifest": snapshot["manifest"],
            }
        return PlanningEntryResult(
            fixture_hash=fixture.fixture_hash,
            prompt_version=fixture.prompt_version,
            structured_output_schema_version=fixture.structured_output_schema_version,
            parsed_intent=fixture.parsed_intent,
            blueprint=blueprint,
            goal=goal,
            file_dataset=dataset_pin,
        )

    async def _validate_role_and_target(
        self,
        tenant_id: str,
        role_id: str,
        entity_id: str,
        entity_type: str,
        blueprint: DiscoveredBlueprint,
    ) -> None:
        async with tenant_session(self._engine, tenant_id) as session:
            role = (
                await session.execute(
                    text("SELECT role_id FROM roles WHERE tenant_id = :tenant_id AND role_id = :role_id"),
                    {"tenant_id": tenant_id, "role_id": role_id},
                )
            ).scalar_one_or_none()
            if role is None:
                raise BlueprintEntryError("request role is not visible in this tenant")
            entity = (
                await session.execute(
                    text(
                        "SELECT entity_type_id FROM entities "
                        "WHERE tenant_id = :tenant_id AND entity_id = :entity_id AND status = 'active'"
                    ),
                    {"tenant_id": tenant_id, "entity_id": entity_id},
                )
            ).scalar_one_or_none()
        if entity != entity_type:
            raise BlueprintEntryError("fixture target is absent or has an incompatible entity type")
        # The pin is read through the discovered Blueprint and is intentionally
        # not substituted by a live model lookup here.
        if not blueprint.source_snapshot_id or not blueprint.source_content_hash:
            raise BlueprintEntryError("compiled Blueprint does not pin a source Snapshot identity")
