"""Pure N01A API, CatalogResolver and canonical hash contracts."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from earp_server.causal_model_management.canonicalization import (
    BLUEPRINT_IR_SCHEMA,
    CAUSAL_SNAPSHOT_SCHEMA,
    CanonicalizationError,
    canonical_hash,
    canonical_json,
)
from earp_server.causal_model_management.catalog import (
    CatalogResolutionError,
    CatalogValidationContext,
    FakeCatalogResolver,
    ResolvedCatalogRef,
)
from earp_server.causal_model_management.schemas import (
    CatalogRef,
    CreateCatalogChangeRequest,
    PutEdgeRequest,
    PutEvidenceRequirementRequest,
)


def _ref(kind: str, stable_id: str) -> dict[str, str]:
    return {"kind": kind, "stable_id": stable_id, "version": "v1"}


def snapshot_payload() -> dict:
    return {
        "snapshot_schema_version": "causal-snapshot/v1",
        "model_identity": {"model_id": "model.é", "model_version": "1"},
        "diagnostic_target": {
            "objective": "diagnose",
            "entry_point": "output",
            "direction": "down",
            "domain": "production",
            "target_entity_type_ref": _ref("entity_type", "entity.mine"),
            "time_window_schema_ref": _ref("time_window_schema", "daily"),
        },
        "algorithm_profile": {"stable_id": "sign_propagation", "version": "v1"},
        "nodes": [
            {
                "node_key": "output",
                "entity_type_ref": _ref("entity_type", "entity.mine"),
                "observability": "observable",
                "entry_point": True,
            },
            {
                "node_key": "cause",
                "entity_type_ref": _ref("entity_type", "entity.system"),
                "observability": "observable",
                "entry_point": False,
            },
        ],
        "edges": [
            {
                "edge_key": "e1",
                "from_node_key": "cause",
                "to_node_key": "output",
                "relation_type_ref": _ref("relation_type", "relation.affects"),
                "effect": "-",
                "strength": Decimal("0.8000"),
                "confidence": Decimal("0.90"),
                "lag": "PT0S",
            }
        ],
        "rules": [],
        "evidence_requirements": [
            {
                "node_key": "cause",
                "requirement_key": "metric",
                "metric_ref": _ref("metric", "metric.cycle"),
                "unit_ref": _ref("unit", "minute"),
                "aggregation_ref": _ref("aggregation", "mean"),
                "time_window_ref": _ref("time_window_schema", "daily"),
                "binding_template_ref": _ref("binding_template", "outbound"),
                "binding_params": {},
                "required": True,
                "primary_contract_ref": _ref("capability_contract", "contract.read"),
                "supporting_contract_refs": [],
            }
        ],
        "applicability": {"scope": "tenant"},
        "catalog_resolutions": [
            {**_ref("entity_type", "entity.mine"), "content_hash": "1" * 64},
            {**_ref("metric", "metric.cycle"), "content_hash": "2" * 64},
        ],
        "semantic_schema_versions": {"causal_graph": "v1"},
    }


def artifact_payload() -> dict:
    return {
        "artifact_schema_version": "blueprint-ir/v1",
        "source_models": [
            {
                "source_ref_key": "primary",
                "model_type": "causal",
                "model_id": "model.é",
                "model_version": "1",
                "source_snapshot_id": "cms-1",
                "source_content_hash": "a" * 64,
                "model_role": "primary_model",
            }
        ],
        "intents": [
            {
                "intent_key": "diagnose-output",
                "entry_point": "output",
                "direction": "down",
                "domain": "production",
                "business_objective": "diagnose",
            }
        ],
        "goal_skeletons": [
            {
                "goal_skeleton_key": "diagnose",
                "objective": "diagnose",
                "goal_template": "diagnose {entry_point}",
                "required_bindings": ["entry_point"],
                "optional_bindings": [],
                "constraint_refs": [],
                "output_contract_ref": "ranking",
            }
        ],
        "constraints": [],
        "output_contracts": [
            {"output_key": "ranking", "output_type": "cause_ranking", "output_schema": {"version": "v1"}}
        ],
        "fallback_policy": "restricted",
        "step_type_pins": [
            {
                "step_type": "knowledge_query",
                "version": "1",
                "step_type_version_id": "stv-knowledge",
                "handler_version": "prepare/v1",
                "handler_hash": "b" * 64,
                "semantic_contract_version": "v1",
            },
            {
                "step_type": "output",
                "version": "1",
                "step_type_version_id": "stv-output",
                "handler_version": "output/v1",
                "handler_hash": "c" * 64,
                "semantic_contract_version": "v1",
            },
        ],
        "steps": [
            {
                "ordinal": 2,
                "step_key": "output",
                "step_type": "output",
                "step_type_version_id": "stv-output",
                "step_name": "Output",
                "params": {},
                "output_field": "ranking",
            },
            {
                "ordinal": 1,
                "step_key": "prepare",
                "step_type": "knowledge_query",
                "step_type_version_id": "stv-knowledge",
                "step_name": "Prepare",
                "params": {"threshold": Decimal("1.00")},
                "output_field": "evidence",
            },
        ],
        "dependencies": [
            {
                "from_step_key": "prepare",
                "to_step_key": "output",
                "dep_type": "data_flow",
                "condition": None,
                "condition_eval_phase": None,
            }
        ],
        "step_sources": [
            {
                "step_key": "prepare",
                "source_ref_key": "primary",
                "element_type": "node",
                "element_key": "output",
                "element_path": None,
                "role": "primary",
            }
        ],
        "capability_requirements": [],
    }


def test_snapshot_golden_hash_order_unicode_decimal_and_exclusions() -> None:
    first = snapshot_payload()
    second = deepcopy(first)
    second["model_identity"]["model_id"] = "model.e\u0301"
    second["nodes"].reverse()
    second["catalog_resolutions"].reverse()
    second["edges"][0]["strength"] = Decimal("0.8")
    expected = "fed5deacfb6d7a30319ea1e24ce9130adcbf21c07e949a082ed48b95252bdf67"
    assert canonical_hash(first, CAUSAL_SNAPSHOT_SCHEMA) == expected
    assert canonical_hash(second, CAUSAL_SNAPSHOT_SCHEMA) == canonical_hash(first, CAUSAL_SNAPSHOT_SCHEMA)
    changed = deepcopy(first)
    changed["catalog_resolutions"][0]["content_hash"] = "9" * 64
    assert canonical_hash(changed, CAUSAL_SNAPSHOT_SCHEMA) != canonical_hash(first, CAUSAL_SNAPSHOT_SCHEMA)
    with pytest.raises(CanonicalizationError, match="unknown"):
        canonical_hash({**first, "revision": 7}, CAUSAL_SNAPSHOT_SCHEMA)


def test_artifact_golden_hash_projection_and_semantic_pins() -> None:
    artifact = artifact_payload()
    expected = "818ad834e662406970558e4c23472308e7c8a94ee24145e7c8d5541cd830ea63"
    assert canonical_hash(artifact, BLUEPRINT_IR_SCHEMA) == expected
    projection = deepcopy(artifact)
    projection["steps"].reverse()
    projection["step_type_pins"].reverse()
    assert canonical_hash(projection, BLUEPRINT_IR_SCHEMA) == expected
    projection["source_models"][0]["source_content_hash"] = "d" * 64
    assert canonical_hash(projection, BLUEPRINT_IR_SCHEMA) != expected
    with pytest.raises(CanonicalizationError, match="binary floats"):
        broken = artifact_payload()
        broken["steps"][0]["params"] = {"value": 0.1}
        canonical_json(broken, BLUEPRINT_IR_SCHEMA)


async def test_fake_catalog_resolver_contract_is_exact_active_and_domain_scoped() -> None:
    entry = ResolvedCatalogRef(
        kind="metric",
        stable_id="metric.cycle",
        version="v1",
        content_hash="1" * 64,
        status="active",
        data_domain_id="production",
        semantic_schema_version="metric/v1",
    )
    resolver = FakeCatalogResolver([entry])
    ref = CatalogRef(kind="metric", stable_id="metric.cycle", version="v1")
    context = CatalogValidationContext("tenant", "production", {"resource_type": "evidence"})
    assert (await resolver.resolve("tenant", ref, "metric", context=context)).pin()["content_hash"] == "1" * 64
    with pytest.raises(CatalogResolutionError) as wrong_kind:
        await resolver.resolve("tenant", ref, "unit", context=context)
    assert wrong_kind.value.code == "CATALOG_REF_KIND_MISMATCH"
    forbidden_context = CatalogValidationContext("tenant", "finance", {"resource_type": "evidence"})
    with pytest.raises(CatalogResolutionError) as wrong_domain:
        await resolver.resolve("tenant", ref, "metric", context=forbidden_context)
    assert wrong_domain.value.code == "CATALOG_REF_DOMAIN_FORBIDDEN"


def test_api_schemas_reject_execution_fields_and_inexact_values() -> None:
    with pytest.raises(ValidationError):
        CatalogRef(kind="metric", stable_id="m", version="latest")
    with pytest.raises(ValidationError):
        PutEdgeRequest(
            from_node_key="a",
            to_node_key="b",
            relation_type_ref=_ref("relation_type", "affects"),
            effect="-",
            strength="NaN",
            confidence="0.9",
            lag="PT0S",
        )
    with pytest.raises(ValidationError):
        PutEvidenceRequirementRequest(
            metric_ref=_ref("metric", "m"),
            unit_ref=_ref("unit", "u"),
            aggregation_ref=_ref("aggregation", "mean"),
            time_window_ref=_ref("time_window_schema", "daily"),
            binding_template_ref=_ref("binding_template", "bind"),
            binding_params={"endpoint": "https://forbidden.example"},
            required=True,
            primary_contract_ref=_ref("capability_contract", "read"),
            supporting_contract_refs=[],
        )
    with pytest.raises(ValidationError):
        CreateCatalogChangeRequest(
            request_type="metric",
            target_data_domain_ref=_ref("data_domain", "production"),
            rationale="needed",
            proposed_definition={
                "schema_version": "catalog-change-request/v1",
                "kind": "metric",
                "display_name": "Cycle",
                "semantic_definition": "Cycle time",
                "contract": {
                    "value_type": "decimal",
                    "time_semantics": "interval",
                    "allowed_unit_refs": [_ref("unit", "minute")],
                    "allowed_aggregation_refs": [_ref("aggregation", "mean")],
                    "provider": "forbidden",
                },
            },
        )
