from enum import StrEnum
from typing import Protocol, runtime_checkable

class ExtensionPoint(StrEnum):
    PLANNER_STRATEGY = "planner.strategy"
    PLANNER_REFLECTION = "planner.reflection"
    DECISION_RULE = "decision.rule"
    DECISION_LLM_JUDGE = "decision.llm_judge"
    POLICY_EVALUATOR = "policy.evaluator"
    AUDIT_HOOK = "audit.hook"
    EVALUATION_METRIC = "evaluation.metric"
    EVALUATION_EXPORTER = "evaluation.exporter"
    RESOURCE_PROVIDER = "resource.provider"

@runtime_checkable
class PlannerStrategyProtocol(Protocol):
    async def plan(self, intent: dict, goals: list[dict]) -> list[dict]: ...

@runtime_checkable
class PlannerReflectionProtocol(Protocol):
    async def reflect(self, plan: list[dict], result: dict) -> dict: ...

@runtime_checkable
class DecisionRuleProtocol(Protocol):
    async def decide(self, context: dict, branches: list[dict]) -> dict: ...

@runtime_checkable
class DecisionLLMJudgeProtocol(Protocol):
    async def prompt(self, context: dict) -> str: ...

@runtime_checkable
class PolicyEvaluatorProtocol(Protocol):
    async def evaluate(self, context: dict) -> dict: ...

@runtime_checkable
class AuditHookProtocol(Protocol):
    async def on_audit(self, record: dict) -> None: ...

@runtime_checkable
class EvaluationMetricProtocol(Protocol):
    async def compute(self, result: dict) -> float: ...

@runtime_checkable
class EvaluationExporterProtocol(Protocol):
    async def export(self, metrics: list[dict]) -> None: ...

@runtime_checkable
class ResourceProviderProtocol(Protocol):
    async def allocate(self, request: dict) -> dict: ...

EXTENSION_POINT_PROTOCOLS: dict[ExtensionPoint, type] = {
    ExtensionPoint.PLANNER_STRATEGY: PlannerStrategyProtocol,
    ExtensionPoint.PLANNER_REFLECTION: PlannerReflectionProtocol,
    ExtensionPoint.DECISION_RULE: DecisionRuleProtocol,
    ExtensionPoint.DECISION_LLM_JUDGE: DecisionLLMJudgeProtocol,
    ExtensionPoint.POLICY_EVALUATOR: PolicyEvaluatorProtocol,
    ExtensionPoint.AUDIT_HOOK: AuditHookProtocol,
    ExtensionPoint.EVALUATION_METRIC: EvaluationMetricProtocol,
    ExtensionPoint.EVALUATION_EXPORTER: EvaluationExporterProtocol,
    ExtensionPoint.RESOURCE_PROVIDER: ResourceProviderProtocol,
}
