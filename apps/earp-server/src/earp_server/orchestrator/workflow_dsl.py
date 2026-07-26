"""Workflow DSL — simple sequential + conditional + parallel step definitions.

M5 extension: replaces raw for-loop in MultiStepExecutor with structured DSL.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from earp_server.orchestrator.types import Step

# ── DSL Nodes ─────────────────────────────────────────────────────────────────


@dataclass
class WorkflowNode:
    """Base node in a workflow graph."""

    node_id: str

    def flatten(self) -> list[Step]:
        raise NotImplementedError


@dataclass
class Sequential(WorkflowNode):
    """Ordered sequence of child nodes."""

    children: list[WorkflowNode] = field(default_factory=list)

    def flatten(self) -> list[Step]:
        steps: list[Step] = []
        for child in self.children:
            steps.extend(child.flatten())
        return steps


@dataclass
class Conditional(WorkflowNode):
    """If-then-else branching based on runtime condition."""

    condition: str = ""  # expression evaluated at runtime
    then_branch: WorkflowNode | None = None
    else_branch: WorkflowNode | None = None

    def flatten(self) -> list[Step]:
        # M5: compile-time flatten includes both branches. Runtime evaluation
        # is handled by MultiStepExecutor's conditional skip logic.
        steps: list[Step] = []
        if self.then_branch:
            steps.extend(self.then_branch.flatten())
        if self.else_branch:
            steps.extend(self.else_branch.flatten())
        return steps


@dataclass
class Parallel(WorkflowNode):
    """Concurrent execution of child nodes. M5: flattened to sequential."""

    children: list[WorkflowNode] = field(default_factory=list)

    def flatten(self) -> list[Step]:
        steps: list[Step] = []
        for child in self.children:
            steps.extend(child.flatten())
        return steps


@dataclass
class StepNode(WorkflowNode):
    """Leaf node — wraps a single Step."""

    step: Step

    def flatten(self) -> list[Step]:
        return [self.step]


# ── DSL Compiler ──────────────────────────────────────────────────────────────


def compile_workflow(root: WorkflowNode) -> list[Step]:
    """Compile a workflow DSL tree into a flat step list for MultiStepExecutor."""
    return root.flatten()
