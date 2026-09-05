"""Case A dynamic PlanFragment projection and Blueprint-specific DAG checks.

This module intentionally does not call :func:`planner.validation.validate_plan`.
That legacy validator still validates a linear ``list[Step]`` and treats item
count as depth.  A PlanFragment has explicit dependencies, so its graph depth
is calculated here before the Phase-1 sequential executor consumes the stable
topological ordering.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.capability.resolution import (
    CapabilityResolutionError,
    CapabilityResolver,
    FileDatasetCapabilityResolver,
    FixtureCapabilityResolver,
)
from earp_server.infra.db import tenant_session
from earp_server.orchestrator.types import Step

CASE_A_FRAGMENT_CONTRACT = "case-a-plan-fragment/v1"
EVIDENCE_ACQUISITION_CONTRACT = "case-a-evidence-acquisition/v1"
REASONING_EVALUATE_CONTRACT = "case-a-reasoning-evaluate/v1"


class PlanFragmentError(ValueError):
    """Prepared evidence cannot form a safe executable Case A plan."""


@dataclass(frozen=True)
class PlanDependency:
    predecessor_key: str
    successor_key: str


@dataclass(frozen=True)
class PlanTask:
    task_key: str
    kind: str
    step: Step
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class PlanFragment:
    prepare_id: str
    blueprint_version_id: str
    tasks: tuple[PlanTask, ...]
    dependencies: tuple[PlanDependency, ...]

    def execution_steps(self) -> list[Step]:
        """Stable Phase-1 order: acquisitions, Evaluate, then output."""
        return [task.step for task in self.tasks]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": CASE_A_FRAGMENT_CONTRACT,
            "prepare_id": self.prepare_id,
            "blueprint_version_id": self.blueprint_version_id,
            "tasks": [
                {
                    "task_key": task.task_key,
                    "kind": task.kind,
                    "step_id": task.step.step_id,
                    "capability_call": task.step.capability_call,
                    "depends_on": list(task.depends_on),
                }
                for task in self.tasks
            ],
        }


def _require_str(requirement: Mapping[str, Any], key: str) -> str:
    value = requirement.get(key)
    if not isinstance(value, str) or not value:
        raise PlanFragmentError(f"prepared requirement lacks {key}")
    return value


def _task_key(requirement: Mapping[str, Any]) -> str:
    """Use node identity, not provider identity, for a replay-stable task key."""
    node_key = _require_str(requirement, "node_key")
    return f"acquire-{node_key.replace('_', '-')}"


def _copy_target(requirement: Mapping[str, Any]) -> dict[str, str]:
    return {
        "entity_id": _require_str(requirement, "target_entity_id"),
        "entity_type": _require_str(requirement, "target_entity_type"),
    }


def _copy_time_window(requirement: Mapping[str, Any]) -> dict[str, Any]:
    value = requirement.get("time_window")
    if (
        not isinstance(value, Mapping)
        or not isinstance(value.get("start"), str)
        or not isinstance(value.get("end"), str)
    ):
        raise PlanFragmentError("prepared requirement lacks a valid time window")
    # Copy rather than normalize or resolve again: this is the no-target-rewrite
    # boundary between Prepare and Provider Resolution.
    return dict(value)


def build_case_a_plan_fragment(
    *,
    prepare_id: str,
    blueprint_version_id: str,
    knowledge_query_step_id: str,
    output_step_id: str,
    output_contract_ref: str,
    requirements: Iterable[Mapping[str, Any]],
    resolver: CapabilityResolver,
    file_dataset: Mapping[str, Any] | None = None,
    max_graph_depth: int = 5,
) -> PlanFragment:
    """Project immutable Prepare requirements into Case A physical tasks."""
    # Parameters are already str-typed; only the non-empty contract is checked here.
    if not all(value for value in (prepare_id, blueprint_version_id, knowledge_query_step_id)):
        raise PlanFragmentError("Case A PlanFragment requires pinned Prepare and Blueprint identities")
    if not output_step_id or not output_contract_ref:
        raise PlanFragmentError("Case A PlanFragment requires a pinned output Blueprint step and contract")

    acquisition_tasks: list[PlanTask] = []
    seen_requirement_ids: set[str] = set()
    seen_task_keys: set[str] = set()
    # Prepare's requirement order is intentionally canonical.  The task list
    # preserves that order, allowing sequential Phase 1 execution while the
    # dependencies retain the future-parallel semantics.
    for requirement in requirements:
        requirement_id = _require_str(requirement, "requirement_id")
        if requirement_id in seen_requirement_ids:
            raise PlanFragmentError("Prepare contains duplicate requirement_id")
        seen_requirement_ids.add(requirement_id)
        task_key = _task_key(requirement)
        if task_key in seen_task_keys:
            raise PlanFragmentError("Prepare contains requirements with a duplicate task node")
        seen_task_keys.add(task_key)
        try:
            binding = resolver.resolve(requirement)
        except CapabilityResolutionError as error:
            raise PlanFragmentError(str(error)) from error
        requirement_key = _require_str(requirement, "requirement_key")
        source_requirement_id = _require_str(requirement, "source_requirement_id")
        level = _require_str(requirement, "requirement_level")
        acquisition_input = {
            "contract": EVIDENCE_ACQUISITION_CONTRACT,
            "prepare_id": prepare_id,
            "requirement_id": requirement_id,
            "source_requirement_id": source_requirement_id,
            "requirement_key": requirement_key,
            "node_key": _require_str(requirement, "node_key"),
            "requirement_level": level,
            "capability_contract_ref": binding.contract_ref,
            "provider_key": binding.provider_key,
            "provider_resolution_status": binding.status,
            "target": _copy_target(requirement),
            "time_window": _copy_time_window(requirement),
            "measurement": {"unit": requirement.get("unit"), "aggregation": requirement.get("aggregation")},
            "blueprint": {"blueprint_version_id": blueprint_version_id, "step_id": knowledge_query_step_id},
        }
        if file_dataset is not None:
            acquisition_input["file_dataset"] = dict(file_dataset)
        acquisition_tasks.append(
            PlanTask(
                task_key=task_key,
                kind="evidence_acquisition",
                step=Step(
                    step_id=task_key,
                    capability_call={
                        "capability_id": binding.provider_key or "case-a-unbound-optional",
                        "adapter_type": "reasoning.acquire",
                        "input": acquisition_input,
                    },
                ),
                depends_on=(),
            )
        )

    if not acquisition_tasks:
        raise PlanFragmentError("Case A Prepare produced no evidence requirements")
    evaluation_key = "evaluate-causal-diagnosis"
    acquisition_keys = tuple(task.task_key for task in acquisition_tasks)
    evaluation_task = PlanTask(
        task_key=evaluation_key,
        kind="reasoning_evaluate",
        step=Step(
            step_id=evaluation_key,
            capability_call={
                "capability_id": "case-a-sign-propagation",
                "adapter_type": "reasoning.evaluate",
                "input": {
                    "contract": REASONING_EVALUATE_CONTRACT,
                    "prepare_id": prepare_id,
                    "planned_requirement_ids": [
                        task.step.capability_call["input"]["requirement_id"] for task in acquisition_tasks
                    ],
                    "blueprint": {"blueprint_version_id": blueprint_version_id, "step_id": knowledge_query_step_id},
                },
            },
        ),
        depends_on=acquisition_keys,
    )
    output_key = "output-cause-ranking"
    output_task = PlanTask(
        task_key=output_key,
        kind="output",
        step=Step(
            step_id=output_key,
            capability_call={
                "capability_id": "case-a-cause-ranking-output",
                "adapter_type": "answer.output",
                "input": {
                    "contract": "case-a-cause-ranking-output/v1",
                    "prepare_id": prepare_id,
                    "output_contract_ref": output_contract_ref,
                    "blueprint": {"blueprint_version_id": blueprint_version_id, "step_id": output_step_id},
                },
            },
        ),
        depends_on=(evaluation_key,),
    )
    tasks = tuple([*acquisition_tasks, evaluation_task, output_task])
    dependencies = tuple(
        PlanDependency(predecessor, task.task_key) for task in tasks for predecessor in task.depends_on
    )
    fragment = PlanFragment(prepare_id, blueprint_version_id, tasks, dependencies)
    validate_case_a_plan_fragment(fragment, max_graph_depth=max_graph_depth)
    return fragment


def validate_case_a_plan_fragment(fragment: PlanFragment, *, max_graph_depth: int = 5) -> None:
    """Validate the dynamic graph without changing legacy linear-plan rules."""
    if max_graph_depth < 1:
        raise PlanFragmentError("max_graph_depth must be positive")
    by_key = {task.task_key: task for task in fragment.tasks}
    if len(by_key) != len(fragment.tasks):
        raise PlanFragmentError("PlanFragment task keys must be unique")
    if not by_key:
        raise PlanFragmentError("PlanFragment is empty")
    for task in fragment.tasks:
        if not task.step.capability_call.get("adapter_type"):
            raise PlanFragmentError(f"task {task.task_key} lacks an execution adapter")
        if any(dependency not in by_key for dependency in task.depends_on):
            raise PlanFragmentError(f"task {task.task_key} depends on an unknown task")
    acquisitions = [task for task in fragment.tasks if task.kind == "evidence_acquisition"]
    evaluates = [task for task in fragment.tasks if task.kind == "reasoning_evaluate"]
    outputs = [task for task in fragment.tasks if task.kind == "output"]
    if not acquisitions or len(evaluates) != 1 or len(outputs) != 1:
        raise PlanFragmentError("Case A fragment requires acquisitions, exactly one Evaluate, and exactly one output")
    evaluate = evaluates[0]
    if set(evaluate.depends_on) != {task.task_key for task in acquisitions}:
        raise PlanFragmentError("Evaluate must depend on every planned evidence acquisition")
    if outputs[0].depends_on != (evaluate.task_key,):
        raise PlanFragmentError("output must depend only on Evaluate")
    if any(task.depends_on for task in acquisitions):
        raise PlanFragmentError("Case A evidence acquisitions cannot have dynamic task dependencies")

    visiting: set[str] = set()
    resolved_depth: dict[str, int] = {}

    def depth(task_key: str) -> int:
        if task_key in resolved_depth:
            return resolved_depth[task_key]
        if task_key in visiting:
            raise PlanFragmentError("PlanFragment dependency graph contains a cycle")
        visiting.add(task_key)
        task = by_key[task_key]
        result = 1 if not task.depends_on else 1 + max(depth(parent) for parent in task.depends_on)
        visiting.remove(task_key)
        resolved_depth[task_key] = result
        return result

    actual_depth = max(depth(task.task_key) for task in fragment.tasks)
    if actual_depth > max_graph_depth:
        raise PlanFragmentError(f"PlanFragment graph depth {actual_depth} exceeds max {max_graph_depth}")


class KnowledgeQueryPlanFragmentHandler:
    """Planner-side handler for an already persisted Case A Prepare result."""

    def __init__(self, engine: AsyncEngine, fixture_dir: Path) -> None:
        self._engine = engine
        self._resolver = FixtureCapabilityResolver(fixture_dir)

    async def project(self, tenant_id: str, prepare_id: str) -> PlanFragment:
        """Load immutable Context + Blueprint step pins and create one fragment."""
        async with tenant_session(self._engine, tenant_id) as session:
            context_result = await session.execute(
                text(
                    "SELECT status, scope_meta, evidence_requirements FROM reasoning_contexts "
                    "WHERE tenant_id = :tenant_id AND prepare_id = :prepare_id"
                ),
                {"tenant_id": tenant_id, "prepare_id": prepare_id},
            )
            context = context_result.mappings().first()
            if context is None or context["status"] != "prepared":
                raise PlanFragmentError("only a persisted prepared ReasoningContext can be projected")
            scope_meta = context["scope_meta"]
            requirements = context["evidence_requirements"]
            if isinstance(scope_meta, str):
                scope_meta = json.loads(scope_meta)
            if isinstance(requirements, str):
                requirements = json.loads(requirements)
            if not isinstance(scope_meta, dict) or not isinstance(requirements, list):
                raise PlanFragmentError("ReasoningContext persistence payload is malformed")
            blueprint_version_id = scope_meta.get("blueprint_version_id")
            if not isinstance(blueprint_version_id, str) or not blueprint_version_id:
                raise PlanFragmentError("ReasoningContext does not pin a Blueprint Version")
            steps_result = await session.execute(
                text(
                    "SELECT step_id, step_type FROM blueprint_steps WHERE tenant_id = :tenant_id "
                    "AND blueprint_version_id = :blueprint_version_id ORDER BY step_seq"
                ),
                {"tenant_id": tenant_id, "blueprint_version_id": blueprint_version_id},
            )
            step_ids = {row["step_type"]: row["step_id"] for row in steps_result.mappings()}
            if set(step_ids) != {"knowledge_query", "output"}:
                raise PlanFragmentError("pinned Blueprint does not contain the Case A knowledge_query/output skeleton")
            goal_result = await session.execute(
                text(
                    "SELECT output_contract_ref FROM blueprint_goal_skeletons WHERE tenant_id = :tenant_id "
                    "AND blueprint_version_id = :blueprint_version_id AND objective = 'diagnose'"
                ),
                {"tenant_id": tenant_id, "blueprint_version_id": blueprint_version_id},
            )
            goals = [row["output_contract_ref"] for row in goal_result.mappings()]
            if len(goals) != 1 or not isinstance(goals[0], str) or not goals[0]:
                raise PlanFragmentError("pinned Blueprint has no unambiguous diagnose output contract")
        dataset_pin = scope_meta.get("file_dataset")
        resolver: CapabilityResolver = self._resolver
        if isinstance(dataset_pin, Mapping):
            manifest = dataset_pin.get("manifest")
            if not isinstance(manifest, Mapping):
                raise PlanFragmentError("pinned file dataset manifest is missing")
            resolver = FileDatasetCapabilityResolver(manifest)
        return build_case_a_plan_fragment(
            prepare_id=prepare_id,
            blueprint_version_id=blueprint_version_id,
            knowledge_query_step_id=step_ids["knowledge_query"],
            output_step_id=step_ids["output"],
            output_contract_ref=goals[0],
            requirements=requirements,
            resolver=resolver,
            file_dataset=dataset_pin if isinstance(dataset_pin, Mapping) else None,
        )
