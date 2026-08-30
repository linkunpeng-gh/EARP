"""Tenant-scoped discovery for immutable Planning Blueprint versions.

This module is intentionally separate from the legacy ``SimpleTaskPlanner``.
It discovers only already-compiled Blueprint *versions*; it never falls back
to a mutable model or the legacy rule/LLM planning path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session


class BlueprintDiscoveryError(ValueError):
    """A Blueprint cannot be selected unambiguously and safely."""


@dataclass(frozen=True)
class DiscoveredBlueprint:
    blueprint_id: str
    blueprint_version_id: str
    blueprint_version: str
    compile_record_id: str
    source_snapshot_id: str
    source_content_hash: str
    goal_skeleton_id: str
    goal_template: str
    required_bindings: list[str]
    output_contract_ref: str
    applicability: dict[str, Any]


async def discover_compiled_causal_blueprint(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    entry_point: str,
    direction: str,
    domain: str,
    business_objective: str,
) -> DiscoveredBlueprint:
    """Return exactly one matching, current Causal Blueprint Version.

    The query deliberately anchors at ``planning_blueprint_versions`` with
    ``status = 'compiled'``.  A zero or many match is an explicit error; a
    caller must never silently select an older version or another planner.
    """
    async with tenant_session(engine, tenant_id) as session:
        result = await session.execute(
            text(
                "SELECT b.blueprint_id, v.blueprint_version_id, v.version AS blueprint_version, "
                "v.compile_record_id, source.source_snapshot_id, source.source_content_hash, "
                "goal.goal_skeleton_id, goal.goal_template, goal.required_bindings, goal.output_contract_ref, "
                "snapshot.applicability_snapshot "
                "FROM planning_blueprint_versions AS v "
                "JOIN planning_blueprints AS b "
                "  ON b.tenant_id = v.tenant_id AND b.blueprint_id = v.blueprint_id "
                "JOIN blueprint_intents AS intent "
                "  ON intent.tenant_id = v.tenant_id AND intent.blueprint_version_id = v.blueprint_version_id "
                "JOIN blueprint_goal_skeletons AS goal "
                "  ON goal.tenant_id = v.tenant_id AND goal.blueprint_version_id = v.blueprint_version_id "
                "JOIN blueprint_source_models AS source "
                "  ON source.tenant_id = v.tenant_id AND source.blueprint_version_id = v.blueprint_version_id "
                " AND source.model_role = 'primary_model' AND source.model_type = 'causal' "
                "JOIN causal_model_snapshots AS snapshot "
                "  ON snapshot.tenant_id = source.tenant_id AND snapshot.snapshot_id = source.source_snapshot_id "
                " AND snapshot.content_hash = source.source_content_hash "
                "WHERE v.tenant_id = :tenant_id AND v.status = 'compiled' AND b.primary_model_type = 'causal' "
                " AND intent.entry_point = :entry_point AND intent.direction = :direction "
                " AND intent.domain = :domain AND intent.business_objective = :business_objective "
                " AND goal.objective = :business_objective "
                "ORDER BY v.blueprint_version_id, goal.goal_skeleton_id"
            ),
            {
                "tenant_id": tenant_id,
                "entry_point": entry_point,
                "direction": direction,
                "domain": domain,
                "business_objective": business_objective,
            },
        )
        rows = [dict(row) for row in result.mappings()]

    if len(rows) != 1:
        raise BlueprintDiscoveryError(
            f"expected exactly one current compiled Causal Blueprint Version for the resolved intent; found {len(rows)}"
        )
    row = rows[0]
    required_bindings = row["required_bindings"]
    applicability = row["applicability_snapshot"]
    if not isinstance(required_bindings, list) or not all(isinstance(item, str) for item in required_bindings):
        raise BlueprintDiscoveryError("compiled Blueprint Goal Skeleton has invalid required bindings")
    if not isinstance(applicability, dict):
        raise BlueprintDiscoveryError("pinned source Snapshot has invalid applicability")
    output_contract_ref = row["output_contract_ref"]
    if not isinstance(output_contract_ref, str) or not output_contract_ref:
        raise BlueprintDiscoveryError("compiled Blueprint Goal Skeleton lacks an output contract")
    return DiscoveredBlueprint(
        blueprint_id=row["blueprint_id"],
        blueprint_version_id=row["blueprint_version_id"],
        blueprint_version=row["blueprint_version"],
        compile_record_id=row["compile_record_id"],
        source_snapshot_id=row["source_snapshot_id"],
        source_content_hash=row["source_content_hash"],
        goal_skeleton_id=row["goal_skeleton_id"],
        goal_template=row["goal_template"],
        required_bindings=required_bindings,
        output_contract_ref=output_contract_ref,
        applicability=applicability,
    )
