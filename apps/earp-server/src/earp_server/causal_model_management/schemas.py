"""Strict Pydantic source contract for the N01A HTTP and domain boundary."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CatalogKind = Literal[
    "data_domain",
    "entity_type",
    "relation_type",
    "metric",
    "unit",
    "aggregation",
    "time_window_schema",
    "binding_template",
    "capability_contract",
    "rule_schema",
]
GovernanceStatus = Literal["draft", "in_review", "published", "superseded", "archived"]
CompileStatus = Literal["running", "success", "failed"]
DeliveryStatus = Literal["pending_delivery", "queued", "delivered", "retrying", "dead_letter"]

_FORBIDDEN_EXECUTION_KEYS = {
    "sql",
    "query",
    "url",
    "endpoint",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
    "provider",
    "provider_id",
    "provider_params",
    "script",
    "code",
    "dsl",
}
_EXACT_VERSION = re.compile(r"^(?!latest$)(?!\*$)[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_ISO_DURATION = re.compile(r"^P(?=\d|T\d)(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CatalogRef(StrictModel):
    kind: CatalogKind
    stable_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)

    @field_validator("version")
    @classmethod
    def exact_version(cls, value: str) -> str:
        if not _EXACT_VERSION.fullmatch(value):
            raise ValueError("catalog version must be an exact version")
        return value


class DiagnosticTarget(StrictModel):
    objective: Literal["diagnose"]
    entry_point: str = Field(min_length=1, max_length=128)
    direction: Literal["up", "down", "change", "neutral", "any"]
    domain: str = Field(min_length=1, max_length=128)
    target_entity_type_ref: CatalogRef
    time_window_schema_ref: CatalogRef

    @model_validator(mode="after")
    def kinds_match(self) -> DiagnosticTarget:
        if self.target_entity_type_ref.kind != "entity_type":
            raise ValueError("target_entity_type_ref must have kind=entity_type")
        if self.time_window_schema_ref.kind != "time_window_schema":
            raise ValueError("time_window_schema_ref must have kind=time_window_schema")
        return self


class CreateModelRequest(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    data_domain_ref: CatalogRef
    diagnostic_target: DiagnosticTarget
    description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def domain_kind(self) -> CreateModelRequest:
        if self.data_domain_ref.kind != "data_domain":
            raise ValueError("data_domain_ref must have kind=data_domain")
        return self


class CreateVersionRequest(StrictModel):
    clone_from_version_id: str | None = Field(default=None, min_length=1, max_length=64)


class PatchVersionRequest(StrictModel):
    applicability: dict[str, Any] | None = None


class PutNodeRequest(StrictModel):
    entity_type_ref: CatalogRef
    observability: Literal["observable", "indirectly_observable", "latent_hypothesis"]
    entry_point: bool
    business_name: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def entity_kind(self) -> PutNodeRequest:
        if self.entity_type_ref.kind != "entity_type":
            raise ValueError("entity_type_ref must have kind=entity_type")
        return self


class PutEdgeRequest(StrictModel):
    from_node_key: str = Field(min_length=1, max_length=64)
    to_node_key: str = Field(min_length=1, max_length=64)
    relation_type_ref: CatalogRef
    effect: Literal["+", "-"]
    strength: str
    confidence: str
    lag: str

    @field_validator("strength", "confidence")
    @classmethod
    def decimal_probability(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("must be a decimal string") from error
        if not parsed.is_finite() or parsed < 0 or parsed > 1:
            raise ValueError("must be within [0,1]")
        return value

    @field_validator("lag")
    @classmethod
    def iso_duration(cls, value: str) -> str:
        if not _ISO_DURATION.fullmatch(value):
            raise ValueError("lag must be an ISO-8601 duration")
        return value

    @model_validator(mode="after")
    def relation_kind(self) -> PutEdgeRequest:
        if self.relation_type_ref.kind != "relation_type":
            raise ValueError("relation_type_ref must have kind=relation_type")
        return self


class PutRuleRequest(StrictModel):
    rule_schema_ref: CatalogRef
    rule_spec: dict[str, Any]
    rationale: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def rule_kind(self) -> PutRuleRequest:
        if self.rule_schema_ref.kind != "rule_schema":
            raise ValueError("rule_schema_ref must have kind=rule_schema")
        reject_execution_fields(self.rule_spec)
        return self


class PutEvidenceRequirementRequest(StrictModel):
    metric_ref: CatalogRef
    unit_ref: CatalogRef
    aggregation_ref: CatalogRef
    time_window_ref: CatalogRef
    binding_template_ref: CatalogRef
    binding_params: dict[str, Any]
    required: bool
    primary_contract_ref: CatalogRef
    supporting_contract_refs: list[CatalogRef]
    business_description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def reference_contract(self) -> PutEvidenceRequirementRequest:
        expected = (
            (self.metric_ref, "metric"),
            (self.unit_ref, "unit"),
            (self.aggregation_ref, "aggregation"),
            (self.time_window_ref, "time_window_schema"),
            (self.binding_template_ref, "binding_template"),
            (self.primary_contract_ref, "capability_contract"),
        )
        if any(ref.kind != kind for ref, kind in expected):
            raise ValueError("evidence CatalogRef kind does not match its field")
        if any(ref.kind != "capability_contract" for ref in self.supporting_contract_refs):
            raise ValueError("supporting contracts must have kind=capability_contract")
        identities = [(ref.stable_id, ref.version) for ref in self.supporting_contract_refs]
        primary = (self.primary_contract_ref.stable_id, self.primary_contract_ref.version)
        if primary in identities or len(set(identities)) != len(identities):
            raise ValueError("primary/supporting contracts must be distinct")
        reject_execution_fields(self.binding_params)
        return self


class ValidateRequest(StrictModel):
    mode: Literal["incremental", "full"] = "full"


class ReasonRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=4000)


class CompileRequest(StrictModel):
    retry_of_compile_id: str | None = Field(default=None, min_length=1, max_length=64)


class ActivateRequest(StrictModel):
    model_version_id: str = Field(min_length=1, max_length=64)
    compile_record_id: str = Field(min_length=1, max_length=64)
    expected_active_model_version_id: str | None
    expected_active_snapshot_id: str | None

    @model_validator(mode="after")
    def pointer_pair(self) -> ActivateRequest:
        if (self.expected_active_model_version_id is None) != (self.expected_active_snapshot_id is None):
            raise ValueError("expected active pointer fields must both be null or both be non-null")
        return self


class DataDomainContract(StrictModel):
    domain_code: str


class EntityTypeContract(StrictModel):
    semantic_class: str


class RelationTypeContract(StrictModel):
    source_entity_type_refs: list[CatalogRef]
    target_entity_type_refs: list[CatalogRef]


class MetricContract(StrictModel):
    value_type: Literal["decimal", "integer", "string", "boolean"]
    time_semantics: str
    allowed_unit_refs: list[CatalogRef]
    allowed_aggregation_refs: list[CatalogRef]


class UnitContract(StrictModel):
    quantity_kind: str
    symbol: str


class AggregationContract(StrictModel):
    operator: str


class TimeWindowContract(StrictModel):
    input_schema_ref: CatalogRef


class BindingTemplateContract(StrictModel):
    params_schema_ref: CatalogRef
    source_entity_type_refs: list[CatalogRef]
    target_entity_type_refs: list[CatalogRef]
    resolver_identity: str


class CapabilityContract(StrictModel):
    read_only: Literal[True]
    input_schema_ref: CatalogRef
    output_schema_ref: CatalogRef


class RuleSchemaContract(StrictModel):
    rule_kind: Literal["predicate", "threshold", "direction_rule"]
    spec_schema_ref: CatalogRef


CatalogContract = Annotated[
    DataDomainContract
    | EntityTypeContract
    | RelationTypeContract
    | MetricContract
    | UnitContract
    | AggregationContract
    | TimeWindowContract
    | BindingTemplateContract
    | CapabilityContract
    | RuleSchemaContract,
    Field(union_mode="left_to_right"),
]


class ProposedCatalogDefinition(StrictModel):
    schema_version: Literal["catalog-change-request/v1"]
    kind: CatalogKind
    display_name: str = Field(min_length=1, max_length=128)
    semantic_definition: str = Field(min_length=1, max_length=4000)
    contract: CatalogContract

    @model_validator(mode="after")
    def contract_matches_kind(self) -> ProposedCatalogDefinition:
        expected = {
            "data_domain": DataDomainContract,
            "entity_type": EntityTypeContract,
            "relation_type": RelationTypeContract,
            "metric": MetricContract,
            "unit": UnitContract,
            "aggregation": AggregationContract,
            "time_window_schema": TimeWindowContract,
            "binding_template": BindingTemplateContract,
            "capability_contract": CapabilityContract,
            "rule_schema": RuleSchemaContract,
        }[self.kind]
        if not isinstance(self.contract, expected):
            raise ValueError(f"contract shape does not match kind={self.kind}")
        return self


class CreateCatalogChangeRequest(StrictModel):
    request_type: CatalogKind
    target_data_domain_ref: CatalogRef
    rationale: str = Field(min_length=1, max_length=4000)
    proposed_definition: ProposedCatalogDefinition

    @model_validator(mode="after")
    def safe_definition(self) -> CreateCatalogChangeRequest:
        if self.target_data_domain_ref.kind != "data_domain":
            raise ValueError("target_data_domain_ref must have kind=data_domain")
        if self.request_type != self.proposed_definition.kind:
            raise ValueError("request_type must match proposed_definition.kind")
        reject_execution_fields(self.proposed_definition.model_dump())
        return self


class PatchCatalogChangeRequest(StrictModel):
    rationale: str | None = Field(default=None, min_length=1, max_length=4000)
    proposed_definition: ProposedCatalogDefinition | None = None


class ValidationIssue(StrictModel):
    code: str
    severity: Literal["error", "warning"]
    location: dict[str, Any]
    message: str
    expected: Any | None = None
    actual: Any | None = None
    catalog_ref: CatalogRef | None = None
    suggested_action: str | None = None


class ValidationResult(StrictModel):
    validation_run_id: str
    model_version_id: str
    draft_revision: int
    input_hash: str
    result: Literal["passed", "failed"]
    issues: list[ValidationIssue]


def reject_execution_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if lowered in _FORBIDDEN_EXECUTION_KEYS:
                raise ValueError(f"forbidden execution field at {path}.{key}")
            reject_execution_fields(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_execution_fields(item, f"{path}[{index}]")
