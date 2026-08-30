"""Deterministic Case A Causal Model -> Planning Blueprint compiler.

The compiler consumes an already-validated immutable Snapshot.  It produces only
the stable method skeleton (``knowledge_query -> output``); evidence requirements
and physical providers deliberately remain runtime concerns for T08/T09.
"""

# SQL statements are intentionally kept as readable, contiguous contracts.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.bmc.metamodel import canonical_json_hash
from earp_server.infra.db import tenant_session

# ``blueprint_compile_records.compiler_version`` is VARCHAR(16).
COMPILER_VERSION = "causal-c-v1"
# ``step_type_versions.semantic_contract_version`` is VARCHAR(16); retain a
# compact registered identity while the CompileRecord carries the full draft.
COMPILER_CONTRACT = "causal-bp-v1"
KNOWLEDGE_QUERY_STEP_TYPE = "knowledge_query"
OUTPUT_STEP_TYPE = "output"

_STEP_TYPE_SEED = (
    {
        "type_id": "st-knowledge-query",
        "type_name": KNOWLEDGE_QUERY_STEP_TYPE,
        "step_type_version_id": "stv-knowledge-query-v1",
        "handler_version": "case-a-prepare/v1",
        "handler_hash": "4f2047920c409d2e24a24269c2f1083a3f47a6dca48becc631425419b4fce010",
    },
    {
        "type_id": "st-output",
        "type_name": OUTPUT_STEP_TYPE,
        "step_type_version_id": "stv-output-v1",
        "handler_version": "case-a-output/v1",
        "handler_hash": "0b3d075d167fbca5c0a19728fb8f0d73f98b07692c97f823024394dd79a5c397",
    },
)


class CausalCompileError(ValueError):
    """The selected source cannot produce a valid Case A Blueprint."""


@dataclass(frozen=True)
class CompileResult:
    tenant_id: str
    compile_id: str
    status: str
    blueprint_id: str | None
    blueprint_version_id: str | None
    blueprint_version: str | None
    canonical_blueprint_hash: str | None
    dry_run: bool


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    # All T04 identity columns are VARCHAR(64); prefixes differ in length.
    return f"{prefix}-{digest[: 64 - len(prefix) - 1]}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def seed_case_a_step_types(registry_engine: AsyncEngine) -> None:
    """Bootstrap Case A's platform-global StepType Registry under a trusted role."""
    async with registry_engine.begin() as connection:
        for step_type in _STEP_TYPE_SEED:
            await connection.execute(
                text(
                    "INSERT INTO step_types (type_id, type_name, is_core) "
                    "VALUES (:type_id, :type_name, true) ON CONFLICT (type_id) DO NOTHING"
                ),
                step_type,
            )
            await connection.execute(
                text(
                    "INSERT INTO step_type_versions (step_type_version_id, type_id, version, handler_version, "
                    "handler_hash, params_schema, semantic_contract_version, status) "
                    "VALUES (:step_type_version_id, :type_id, '1', :handler_version, :handler_hash, "
                    "'{}'::jsonb, :semantic_contract_version, 'active') "
                    "ON CONFLICT (step_type_version_id) DO NOTHING"
                ),
                {**step_type, "semantic_contract_version": COMPILER_CONTRACT},
            )
        result = await connection.execute(
            text(
                "SELECT type_name, step_type_version_id, handler_version, handler_hash, status "
                "FROM step_types JOIN step_type_versions USING (type_id) "
                "WHERE type_name IN ('knowledge_query', 'output') ORDER BY type_name"
            )
        )
        rows = [dict(row) for row in result.mappings()]
    expected = {
        row["type_name"]: {
            "step_type_version_id": row["step_type_version_id"],
            "handler_version": row["handler_version"],
            "handler_hash": row["handler_hash"],
        }
        for row in _STEP_TYPE_SEED
    }
    actual = {
        row["type_name"]: {
            "step_type_version_id": row["step_type_version_id"],
            "handler_version": row["handler_version"],
            "handler_hash": row["handler_hash"],
        }
        for row in rows
        if row["status"] == "active"
    }
    if actual != expected:
        raise CausalCompileError("Case A StepType Registry conflicts with pinned handler identities")


async def _one(session: AsyncSession, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
    result = await session.execute(text(query), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def _load_source(
    session: AsyncSession, tenant_id: str, snapshot_id: str
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    source = await _one(
        session,
        "SELECT snapshot.snapshot_id, snapshot.content_hash, snapshot.nodes_json, snapshot.edges_json, "
        "snapshot.rules_json, snapshot.requirements_json, snapshot.applicability_snapshot, "
        "model.model_id, model_version.model_version_id, model_version.version AS model_version, "
        "validation.result AS validation_result "
        "FROM causal_model_snapshots AS snapshot "
        "JOIN causal_model_versions AS model_version "
        "  ON model_version.tenant_id = snapshot.tenant_id "
        " AND model_version.model_version_id = snapshot.model_version_id "
        "JOIN causal_models AS model "
        "  ON model.tenant_id = model_version.tenant_id AND model.model_id = model_version.model_id "
        "LEFT JOIN causal_snapshot_validation_runs AS validation "
        "  ON validation.tenant_id = snapshot.tenant_id AND validation.snapshot_id = snapshot.snapshot_id "
        " AND validation.result = 'passed' "
        "WHERE snapshot.tenant_id = :tenant_id AND snapshot.snapshot_id = :snapshot_id "
        "ORDER BY validation.finished_at DESC NULLS LAST LIMIT 1",
        {"tenant_id": tenant_id, "snapshot_id": snapshot_id},
    )
    if source is None:
        raise CausalCompileError("causal snapshot was not found for this tenant")
    if source["validation_result"] != "passed":
        raise CausalCompileError("causal snapshot has no passed validation run")

    registry = await session.execute(
        text(
            "SELECT type_name, step_type_version_id, handler_version, handler_hash "
            "FROM step_types JOIN step_type_versions USING (type_id) "
            "WHERE type_name IN ('knowledge_query', 'output') AND status = 'active'"
        )
    )
    handler_rows = {row["type_name"]: dict(row) for row in registry.mappings()}
    if set(handler_rows) != {KNOWLEDGE_QUERY_STEP_TYPE, OUTPUT_STEP_TYPE}:
        raise CausalCompileError("required active Case A StepType handlers are not registered")
    return source, handler_rows


def _build_draft(
    source: dict[str, Any], handlers: dict[str, dict[str, str]], compiler_version: str, compiler_config: dict[str, Any]
) -> dict[str, Any]:
    nodes = source["nodes_json"]
    if not isinstance(nodes, list) or not any(node.get("node_key") == "production_output" for node in nodes):
        raise CausalCompileError("Case A source must contain production_output")
    requirements = source["requirements_json"]
    if not isinstance(requirements, list) or not requirements:
        raise CausalCompileError("Case A source must carry dynamic evidence requirements")
    source_identity = {
        "model_type": "causal",
        "model_id": source["model_id"],
        "model_version": source["model_version"],
        "snapshot_id": source["snapshot_id"],
        "content_hash": source["content_hash"],
    }
    skeleton = {
        "compiler_contract": COMPILER_CONTRACT,
        "compiler_version": compiler_version,
        "compiler_config": compiler_config,
        "source": source_identity,
        "intent": {
            "entry_point": "production_output",
            "direction": "down",
            "domain": source["applicability_snapshot"].get("domain", "production"),
            "business_objective": "diagnose",
        },
        "goal": {
            "objective": "diagnose",
            "goal_template": "diagnose {entry_point} for {entity_id} during {time_window}",
            "required_bindings": ["entity_id", "time_window"],
        },
        "output": {
            "output_type": "cause_ranking",
            "output_schema": {"schema_version": "case-a-cause-ranking/v1", "required": ["status", "ranking"]},
        },
        "steps": [
            {
                "step_key": "prepare-causal-diagnosis",
                "step_type": KNOWLEDGE_QUERY_STEP_TYPE,
                "handler": handlers[KNOWLEDGE_QUERY_STEP_TYPE],
                "params": {"operation": "prepare", "reasoning_mode": "causal_diagnosis"},
            },
            {
                "step_key": "output-cause-ranking",
                "step_type": OUTPUT_STEP_TYPE,
                "handler": handlers[OUTPUT_STEP_TYPE],
                "params": {"operation": "render_cause_ranking"},
            },
        ],
        "dependencies": [{"from": "prepare-causal-diagnosis", "to": "output-cause-ranking", "type": "data_flow"}],
        # Evidence Requirement/provider expansion is deliberately absent.
        "dynamic_evidence_requirement_count": len(requirements),
    }
    return skeleton


def _validate_draft(draft: dict[str, Any]) -> None:
    steps = draft["steps"]
    if [step["step_type"] for step in steps] != [KNOWLEDGE_QUERY_STEP_TYPE, OUTPUT_STEP_TYPE]:
        raise CausalCompileError("Case A Blueprint must be knowledge_query -> output")
    if any("capability" in step["params"] for step in steps):
        raise CausalCompileError("dynamic evidence must not be compiled into Blueprint steps")
    if draft["goal"]["objective"] != draft["intent"]["business_objective"]:
        raise CausalCompileError("goal objective must match Blueprint intent")
    if draft["dependencies"] != [
        {"from": "prepare-causal-diagnosis", "to": "output-cause-ranking", "type": "data_flow"}
    ]:
        raise CausalCompileError("Case A Blueprint dependency is invalid")


async def _insert_compile_record(
    session: AsyncSession,
    tenant_id: str,
    compile_id: str,
    snapshot_id: str,
    compiler_version: str,
    compiler_config: dict[str, Any],
) -> dict[str, Any]:
    await session.execute(
        text(
            "INSERT INTO blueprint_compile_records (tenant_id, compile_id, primary_model_type, primary_model_id, "
            "primary_model_version, source_models_snapshot, source_model_hashes, compiler_version, compiler_config, "
            "input_snapshot, validation_result) "
            "VALUES (:tenant_id, :compile_id, 'causal', :model_id, :model_version, :source_models_snapshot, "
            ":source_model_hashes, :compiler_version, :compiler_config, :input_snapshot, '{}'::jsonb) "
            "ON CONFLICT (tenant_id, compile_id) DO NOTHING"
        ),
        {
            "tenant_id": tenant_id,
            "compile_id": compile_id,
            "model_id": "unresolved",
            "model_version": "unresolved",
            "source_models_snapshot": _json({"snapshot_id": snapshot_id}),
            "source_model_hashes": _json({}),
            "compiler_version": compiler_version,
            "compiler_config": _json(compiler_config),
            "input_snapshot": _json(
                {"snapshot_id": snapshot_id, "compiler_version": compiler_version, "compiler_config": compiler_config}
            ),
        },
    )
    row = await _one(
        session,
        "SELECT status, validation_result, error_log FROM blueprint_compile_records "
        "WHERE tenant_id = :tenant_id AND compile_id = :compile_id",
        {"tenant_id": tenant_id, "compile_id": compile_id},
    )
    assert row is not None
    return row


async def _set_compile_failure(session: AsyncSession, tenant_id: str, compile_id: str, error: Exception) -> None:
    await session.execute(
        text(
            "UPDATE blueprint_compile_records SET status = 'failed', error_log = :error_log, finished_at = now() "
            "WHERE tenant_id = :tenant_id AND compile_id = :compile_id AND status = 'running'"
        ),
        {"tenant_id": tenant_id, "compile_id": compile_id, "error_log": _json([{"message": str(error)}])},
    )


async def compile_case_a_causal_blueprint(
    engine: AsyncEngine,
    tenant_id: str,
    snapshot_id: str,
    *,
    compiler_version: str = COMPILER_VERSION,
    compiler_config: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> CompileResult:
    """Compile a validated Case A Causal Snapshot under tenant RLS.

    Identical input resolves to the same compile record and immutable Blueprint
    identity.  A dry-run records the validated canonical draft but creates no
    Blueprint aggregate children.
    """
    config = compiler_config or {}
    input_identity = {
        "tenant_id": tenant_id,
        "snapshot_id": snapshot_id,
        "compiler_version": compiler_version,
        "compiler_config": config,
        "dry_run": dry_run,
    }
    compile_id = _stable_id("compile", input_identity)
    failure: CausalCompileError | None = None
    async with tenant_session(engine, tenant_id) as session:
        prior = await _insert_compile_record(session, tenant_id, compile_id, snapshot_id, compiler_version, config)
        if prior["status"] == "success":
            validation = prior["validation_result"]
            # A successful compile record is immutable, but its Blueprint
            # version may have been superseded by a later compile with a
            # different configuration.  Replaying this exact compile must
            # restore the requested pinned version as the sole current
            # compiled version; otherwise a deterministic caller receives a
            # version that Prepare correctly refuses to use.
            replay_version_id = validation.get("blueprint_version_id")
            replay_blueprint_id = validation.get("blueprint_id")
            if not bool(validation.get("dry_run")) and replay_version_id and replay_blueprint_id:
                await session.execute(
                    text(
                        "UPDATE planning_blueprint_versions SET status = 'superseded' "
                        "WHERE tenant_id = :tenant_id AND blueprint_id = :blueprint_id "
                        "AND blueprint_version_id <> :blueprint_version_id AND status = 'compiled'"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "blueprint_id": replay_blueprint_id,
                        "blueprint_version_id": replay_version_id,
                    },
                )
                await session.execute(
                    text(
                        "UPDATE planning_blueprint_versions SET status = 'compiled' "
                        "WHERE tenant_id = :tenant_id AND blueprint_id = :blueprint_id "
                        "AND blueprint_version_id = :blueprint_version_id"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "blueprint_id": replay_blueprint_id,
                        "blueprint_version_id": replay_version_id,
                    },
                )
            return CompileResult(
                tenant_id,
                compile_id,
                "success",
                validation.get("blueprint_id"),
                validation.get("blueprint_version_id"),
                validation.get("blueprint_version"),
                validation.get("canonical_blueprint_hash"),
                bool(validation.get("dry_run")),
            )
        if prior["status"] == "failed":
            raise CausalCompileError(str(prior["error_log"]))
        try:
            source, handlers = await _load_source(session, tenant_id, snapshot_id)
            draft = _build_draft(source, handlers, compiler_version, config)
            _validate_draft(draft)
            draft_hash = canonical_json_hash(draft)
            blueprint_id = _stable_id("blueprint", {"tenant_id": tenant_id, "model_id": source["model_id"]})
            blueprint_version_id = _stable_id(
                "blueprint-version", {"blueprint_id": blueprint_id, "draft_hash": draft_hash}
            )
            blueprint_version = f"fixture-{draft_hash[:16]}"
            validation = {
                "contract": COMPILER_CONTRACT,
                "canonical_draft": draft,
                "canonical_blueprint_hash": draft_hash,
                "dry_run": dry_run,
                "blueprint_id": None if dry_run else blueprint_id,
                "blueprint_version_id": None if dry_run else blueprint_version_id,
                "blueprint_version": None if dry_run else blueprint_version,
            }
            await session.execute(
                text(
                    "UPDATE blueprint_compile_records SET primary_model_id = :model_id, primary_model_version = :model_version, "
                    "source_models_snapshot = :source_models_snapshot, source_model_hashes = :source_model_hashes, "
                    "validation_result = :validation_result WHERE tenant_id = :tenant_id AND compile_id = :compile_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "compile_id": compile_id,
                    "model_id": source["model_id"],
                    "model_version": source["model_version"],
                    "source_models_snapshot": _json([draft["source"]]),
                    "source_model_hashes": _json({snapshot_id: source["content_hash"]}),
                    "validation_result": _json(validation),
                },
            )
            if dry_run:
                await session.execute(
                    text(
                        "UPDATE blueprint_compile_records SET status = 'success', finished_at = now() "
                        "WHERE tenant_id = :tenant_id AND compile_id = :compile_id"
                    ),
                    {"tenant_id": tenant_id, "compile_id": compile_id},
                )
                return CompileResult(tenant_id, compile_id, "success", None, None, None, draft_hash, True)

            await _persist_blueprint(
                session,
                tenant_id,
                source,
                draft,
                compile_id,
                blueprint_id,
                blueprint_version_id,
                blueprint_version,
                draft_hash,
            )
            await session.execute(
                text(
                    "UPDATE blueprint_compile_records SET status = 'success', finished_at = now() "
                    "WHERE tenant_id = :tenant_id AND compile_id = :compile_id"
                ),
                {"tenant_id": tenant_id, "compile_id": compile_id},
            )
            return CompileResult(
                tenant_id,
                compile_id,
                "success",
                blueprint_id,
                blueprint_version_id,
                blueprint_version,
                draft_hash,
                False,
            )
        except CausalCompileError as error:
            await _set_compile_failure(session, tenant_id, compile_id, error)
            # Do not raise inside tenant_session: it would roll back the
            # auditable failed CompileRecord.  There are no Blueprint writes
            # before the validation paths handled above.
            failure = error
    # Every non-exception path above returned, so failure is set when we get here.
    raise failure


async def _persist_blueprint(
    session: AsyncSession,
    tenant_id: str,
    source: dict[str, Any],
    draft: dict[str, Any],
    compile_id: str,
    blueprint_id: str,
    blueprint_version_id: str,
    blueprint_version: str,
    draft_hash: str,
) -> None:
    await session.execute(
        text(
            "INSERT INTO planning_blueprints (tenant_id, blueprint_id, primary_model_type, primary_model_id, name, description) "
            "VALUES (:tenant_id, :blueprint_id, 'causal', :model_id, :name, :description) "
            "ON CONFLICT (tenant_id, blueprint_id) DO NOTHING"
        ),
        {
            "tenant_id": tenant_id,
            "blueprint_id": blueprint_id,
            "model_id": source["model_id"],
            "name": "Case A production-drop diagnosis",
            "description": "Deterministic fixture Causal Blueprint",
        },
    )
    existing = await _one(
        session,
        "SELECT primary_model_id FROM planning_blueprints WHERE tenant_id=:tenant_id AND blueprint_id=:blueprint_id",
        {"tenant_id": tenant_id, "blueprint_id": blueprint_id},
    )
    if existing != {"primary_model_id": source["model_id"]}:
        raise CausalCompileError("logical Blueprint identity conflicts with source model")
    await session.execute(
        text(
            "UPDATE planning_blueprint_versions SET status = 'superseded' WHERE tenant_id = :tenant_id "
            "AND blueprint_id = :blueprint_id AND status = 'compiled'"
        ),
        {"tenant_id": tenant_id, "blueprint_id": blueprint_id},
    )
    await session.execute(
        text(
            "INSERT INTO planning_blueprint_versions (tenant_id, blueprint_version_id, blueprint_id, version, status, "
            "compile_record_id, compiler_version, source_fingerprint, intent_signature, validation_contract, "
            "output_contract, fallback_policy) VALUES (:tenant_id, :blueprint_version_id, :blueprint_id, :version, "
            "'compiled', :compile_id, :compiler_version, :source_fingerprint, :intent_signature, :validation_contract, "
            ":output_contract, 'restricted')"
        ),
        {
            "tenant_id": tenant_id,
            "blueprint_version_id": blueprint_version_id,
            "blueprint_id": blueprint_id,
            "version": blueprint_version,
            "compile_id": compile_id,
            "compiler_version": draft["compiler_version"],
            "source_fingerprint": draft_hash,
            "intent_signature": _json(draft["intent"]),
            "validation_contract": _json({"contract": COMPILER_CONTRACT, "canonical_blueprint_hash": draft_hash}),
            "output_contract": _json(draft["output"]),
        },
    )
    source_ref_id = _stable_id(
        "source", {"blueprint_version_id": blueprint_version_id, "snapshot_id": source["snapshot_id"]}
    )
    await session.execute(
        text(
            "INSERT INTO blueprint_source_models (tenant_id, source_ref_id, blueprint_version_id, model_type, model_id, "
            "model_version, source_snapshot_id, source_content_hash, model_role) VALUES (:tenant_id, :source_ref_id, "
            ":blueprint_version_id, 'causal', :model_id, :model_version, :snapshot_id, :content_hash, 'primary_model')"
        ),
        {
            "tenant_id": tenant_id,
            "source_ref_id": source_ref_id,
            "blueprint_version_id": blueprint_version_id,
            "model_id": source["model_id"],
            "model_version": source["model_version"],
            "snapshot_id": source["snapshot_id"],
            "content_hash": source["content_hash"],
        },
    )
    output_id = _stable_id("output", blueprint_version_id)
    await session.execute(
        text(
            "INSERT INTO blueprint_output_contracts (tenant_id, output_id, blueprint_version_id, output_type, output_schema) VALUES (:tenant_id,:output_id,:blueprint_version_id,'cause_ranking',:output_schema)"
        ),
        {
            "tenant_id": tenant_id,
            "output_id": output_id,
            "blueprint_version_id": blueprint_version_id,
            "output_schema": _json(draft["output"]["output_schema"]),
        },
    )
    goal_id = _stable_id("goal", blueprint_version_id)
    await session.execute(
        text(
            "INSERT INTO blueprint_goal_skeletons (tenant_id, goal_skeleton_id, blueprint_version_id, objective, goal_template, required_bindings, optional_bindings, constraint_refs, output_contract_ref) VALUES (:tenant_id,:goal_id,:blueprint_version_id,'diagnose',:goal_template,:required_bindings,'[]'::jsonb,'[]'::jsonb,:output_id)"
        ),
        {
            "tenant_id": tenant_id,
            "goal_id": goal_id,
            "blueprint_version_id": blueprint_version_id,
            "goal_template": draft["goal"]["goal_template"],
            "required_bindings": _json(draft["goal"]["required_bindings"]),
            "output_id": output_id,
        },
    )
    intent_id = _stable_id("intent", blueprint_version_id)
    await session.execute(
        text(
            "INSERT INTO blueprint_intents (tenant_id,intent_id,blueprint_version_id,entry_point,direction,domain,business_objective) VALUES (:tenant_id,:intent_id,:blueprint_version_id,:entry_point,:direction,:domain,:business_objective)"
        ),
        {
            "tenant_id": tenant_id,
            "intent_id": intent_id,
            "blueprint_version_id": blueprint_version_id,
            **draft["intent"],
        },
    )
    step_ids: dict[str, str] = {}
    for sequence, step in enumerate(draft["steps"], start=1):
        step_id = _stable_id("step", {"blueprint_version_id": blueprint_version_id, "step_key": step["step_key"]})
        step_ids[step["step_key"]] = step_id
        await session.execute(
            text(
                "INSERT INTO blueprint_steps (tenant_id,step_id,blueprint_version_id,step_seq,step_type_version_id,step_type,step_name,params,output_field) VALUES (:tenant_id,:step_id,:blueprint_version_id,:step_seq,:step_type_version_id,:step_type,:step_name,:params,:output_field)"
            ),
            {
                "tenant_id": tenant_id,
                "step_id": step_id,
                "blueprint_version_id": blueprint_version_id,
                "step_seq": sequence,
                "step_type_version_id": step["handler"]["step_type_version_id"],
                "step_type": step["step_type"],
                "step_name": step["step_key"],
                "params": _json(step["params"]),
                "output_field": "reasoning_context" if sequence == 1 else "cause_ranking",
            },
        )
        source_id = _stable_id("step-source", {"step_id": step_id, "source_ref_id": source_ref_id})
        await session.execute(
            text(
                "INSERT INTO blueprint_step_sources (tenant_id,step_source_id,blueprint_version_id,step_id,source_model_ref_id,element_type,element_key,element_path,role) VALUES (:tenant_id,:step_source_id,:blueprint_version_id,:step_id,:source_ref_id,'node','production_output','/nodes/production_output','primary')"
            ),
            {
                "tenant_id": tenant_id,
                "step_source_id": source_id,
                "blueprint_version_id": blueprint_version_id,
                "step_id": step_id,
                "source_ref_id": source_ref_id,
            },
        )
    dependency = draft["dependencies"][0]
    await session.execute(
        text(
            "INSERT INTO blueprint_step_deps (tenant_id,dep_id,blueprint_version_id,from_step_id,to_step_id,dep_type) VALUES (:tenant_id,:dep_id,:blueprint_version_id,:from_step_id,:to_step_id,'data_flow')"
        ),
        {
            "tenant_id": tenant_id,
            "dep_id": _stable_id("dep", blueprint_version_id),
            "blueprint_version_id": blueprint_version_id,
            "from_step_id": step_ids[dependency["from"]],
            "to_step_id": step_ids[dependency["to"]],
        },
    )
