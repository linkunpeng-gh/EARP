"""N01A immutable Snapshot -> Candidate Blueprint Artifact compiler."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from earp_server.infra.db import tenant_session

from .canonicalization import BLUEPRINT_IR_SCHEMA, canonical_hash
from .catalog import CatalogValidationContext
from .errors import N01AError, conflict
from .schemas import CatalogRef
from .service import ActorContext, CausalModelService, _id, _json

COMPILER_VERSION = "n01a-causal-v1"


class CandidateCompileService(CausalModelService):
    async def request_compile(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        retry_of_compile_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.compile:{version_id}"
        payload = {"retry_of_compile_id": retry_of_compile_id}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.compile")
            version = await self._version(session, actor, model_id, version_id, for_update=True)
            if version["status"] != "published" or version["published_snapshot_id"] is None:
                raise conflict("INVALID_STATE_TRANSITION", "Only a published immutable Snapshot can be compiled.")
            if retry_of_compile_id is not None:
                parent = (
                    (
                        await session.execute(
                            text(
                                "SELECT status,model_version_id FROM blueprint_compile_records "
                                "WHERE compile_id=:compile AND n01a_attempt=true"
                            ),
                            {"compile": retry_of_compile_id},
                        )
                    )
                    .mappings()
                    .first()
                )
                if parent is None or parent["status"] != "failed" or parent["model_version_id"] != version_id:
                    raise conflict("INVALID_RETRY_PARENT", "Retry parent must be a failed Attempt for this Version.")
            passed = await session.execute(
                text(
                    "SELECT 1 FROM causal_snapshot_validation_runs "
                    "WHERE snapshot_id=:snapshot AND result='passed' LIMIT 1"
                ),
                {"snapshot": version["published_snapshot_id"]},
            )
            if passed.first() is None:
                raise conflict("INVALID_STATE_TRANSITION", "Published Snapshot has no passed validation.")
            compile_id = _id("cr")
            await session.execute(
                text(
                    "INSERT INTO blueprint_compile_records "
                    "(tenant_id,compile_id,primary_model_type,primary_model_id,primary_model_version,"
                    "source_models_snapshot,source_model_hashes,compiler_version,compiler_config,input_snapshot,"
                    "validation_result,status,model_version_id,snapshot_id,retry_of_compile_id,"
                    "requested_by,n01a_attempt) "
                    "SELECT :tenant,:compile,'causal',v.model_id,v.version,"
                    "jsonb_build_array(jsonb_build_object('snapshot_id',s.snapshot_id,'content_hash',s.content_hash)),"
                    "jsonb_build_object(s.snapshot_id,s.content_hash),:compiler,'{}'::jsonb,"
                    "jsonb_build_object('snapshot_id',s.snapshot_id,'content_hash',s.content_hash),'{}'::jsonb,'running',"
                    "v.model_version_id,s.snapshot_id,:retry,:actor,true "
                    "FROM causal_model_versions v JOIN causal_model_snapshots s "
                    "ON s.tenant_id=v.tenant_id AND s.snapshot_id=v.published_snapshot_id "
                    "WHERE v.model_version_id=:version"
                ),
                {
                    "tenant": actor.tenant_id,
                    "compile": compile_id,
                    "compiler": COMPILER_VERSION,
                    "retry": retry_of_compile_id,
                    "actor": actor.actor_id,
                    "version": version_id,
                },
            )
            await self._outbox(
                session,
                actor,
                "ecmc.causal_model.compile_requested",
                "compile_record",
                compile_id,
                {
                    "tenant_id": actor.tenant_id,
                    "model_id": model_id,
                    "model_version_id": version_id,
                    "snapshot_id": version["published_snapshot_id"],
                    "compile_record_id": compile_id,
                    "retry_of_compile_id": retry_of_compile_id,
                },
                idempotency_key,
                "causal-compiler-worker",
            )
            body = {
                "compile_record": {
                    "compile_record_id": compile_id,
                    "model_version_id": version_id,
                    "snapshot_id": version["published_snapshot_id"],
                    "status": "running",
                    "retry_of_compile_id": retry_of_compile_id,
                    "artifact_schema_version": None,
                    "compiled_artifact_hash": None,
                }
            }
            await self._audit(session, actor, "ecmc.causal_compile.requested", "compile_record", compile_id, body)
            await self._remember(session, actor, operation, idempotency_key, payload, 202, body)
            return {"status_code": 202, "body": body, "replayed": False}

    async def complete_attempt(self, actor: ActorContext, compile_id: str) -> dict[str, Any]:
        failure: Exception | None = None
        result: dict[str, Any] | None = None
        async with tenant_session(self.engine, actor.tenant_id) as session:
            record = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM blueprint_compile_records WHERE compile_id=:compile "
                            "AND n01a_attempt=true FOR UPDATE"
                        ),
                        {"compile": compile_id},
                    )
                )
                .mappings()
                .first()
            )
            if record is None:
                raise N01AError("MODEL_VERSION_NOT_FOUND", "Compile Attempt was not found.", 404)
            if record["status"] == "success":
                return {
                    "compile_record_id": compile_id,
                    "status": "success",
                    "artifact_schema_version": record["artifact_schema_version"],
                    "compiled_artifact_hash": record["compiled_artifact_hash"],
                }
            if record["status"] == "failed":
                raise conflict("INVALID_STATE_TRANSITION", "Failed Attempt must be retried as a new Attempt.")
            try:
                artifact = await self._build_artifact(session, actor, dict(record))
                artifact_hash = canonical_hash(artifact, BLUEPRINT_IR_SCHEMA)
                await session.execute(
                    text(
                        "UPDATE blueprint_compile_records SET status='success',compiled_artifact_json=:artifact,"
                        "compiled_artifact_hash=:hash,artifact_schema_version=:schema,"
                        "validation_result=:validation,finished_at=now() WHERE compile_id=:compile AND status='running'"
                    ),
                    {
                        "artifact": _json(artifact),
                        "hash": artifact_hash,
                        "schema": BLUEPRINT_IR_SCHEMA,
                        "validation": _json({"result": "passed", "artifact_hash": artifact_hash}),
                        "compile": compile_id,
                    },
                )
                result = {
                    "compile_record_id": compile_id,
                    "status": "success",
                    "artifact_schema_version": BLUEPRINT_IR_SCHEMA,
                    "compiled_artifact_hash": artifact_hash,
                }
                await self._audit(session, actor, "ecmc.causal_compile.succeeded", "compile_record", compile_id, result)
            except Exception as error:  # noqa: BLE001 - failed Attempt is an auditable terminal result
                await session.execute(
                    text(
                        "UPDATE blueprint_compile_records SET status='failed',error_log=:error,finished_at=now() "
                        "WHERE compile_id=:compile AND status='running'"
                    ),
                    {"error": _json([{"code": "COMPILE_FAILED", "message": str(error)[:1000]}]), "compile": compile_id},
                )
                await self._audit(
                    session,
                    actor,
                    "ecmc.causal_compile.failed",
                    "compile_record",
                    compile_id,
                    {"code": "COMPILE_FAILED"},
                )
                failure = error
        if failure is not None:
            raise N01AError("MODEL_VALIDATION_FAILED", "Candidate compilation failed.", 422) from failure
        assert result is not None
        return result

    async def _build_artifact(self, session, actor: ActorContext, record: dict[str, Any]) -> dict[str, Any]:
        source = (
            (
                await session.execute(
                    text(
                        "SELECT s.snapshot_id,s.content_hash,s.canonical_payload::text AS canonical_payload_text,"
                        "s.catalog_resolutions,"
                        "v.version AS model_version,v.status,v.model_id "
                        "FROM causal_model_snapshots s JOIN causal_model_versions v "
                        "ON v.tenant_id=s.tenant_id AND v.model_version_id=s.model_version_id "
                        "WHERE s.snapshot_id=:snapshot AND v.model_version_id=:version"
                    ),
                    {"snapshot": record["snapshot_id"], "version": record["model_version_id"]},
                )
            )
            .mappings()
            .one()
        )
        if source["status"] != "published" or source["canonical_payload_text"] is None:
            raise ValueError("compiler input is not an immutable N01A published Snapshot")
        snapshot = json.loads(source["canonical_payload_text"], parse_float=Decimal)
        if canonical_hash(snapshot, "causal-snapshot/v1") != source["content_hash"]:
            raise ValueError("Snapshot canonical content hash mismatch")
        for pin in source["catalog_resolutions"]:
            ref = CatalogRef(kind=pin["kind"], stable_id=pin["stable_id"], version=pin["version"])
            resolved = await self.catalog.resolve(
                actor.tenant_id,
                ref,
                ref.kind,
                context=CatalogValidationContext(
                    actor.tenant_id,
                    snapshot["diagnostic_target"]["domain"],
                    {"resource_type": "snapshot", "snapshot_id": source["snapshot_id"]},
                ),
            )
            if resolved.content_hash != pin["content_hash"]:
                raise ValueError("Catalog pin content hash changed")
        registry = [
            dict(row)
            for row in (
                await session.execute(
                    text(
                        "SELECT t.type_name AS step_type,v.version,v.step_type_version_id,v.handler_version,"
                        "v.handler_hash,v.semantic_contract_version FROM step_types t JOIN step_type_versions v "
                        "ON v.type_id=t.type_id WHERE t.type_name IN ('knowledge_query','output') "
                        "AND v.status='active' "
                        "ORDER BY t.type_name"
                    )
                )
            ).mappings()
        ]
        if {item["step_type"] for item in registry} != {"knowledge_query", "output"}:
            raise ValueError("required active StepType pins are unavailable")
        pins = {item["step_type"]: item for item in registry}
        target = snapshot["diagnostic_target"]
        source_model = {
            "source_ref_key": "primary",
            "model_type": "causal",
            "model_id": source["model_id"],
            "model_version": source["model_version"],
            "source_snapshot_id": source["snapshot_id"],
            "source_content_hash": source["content_hash"],
            "model_role": "primary_model",
        }
        return {
            "artifact_schema_version": BLUEPRINT_IR_SCHEMA,
            "source_models": [source_model],
            "intents": [
                {
                    "intent_key": "primary-intent",
                    "entry_point": target["entry_point"],
                    "direction": target["direction"],
                    "domain": target["domain"],
                    "business_objective": target["objective"],
                }
            ],
            "goal_skeletons": [
                {
                    "goal_skeleton_key": "primary-goal",
                    "objective": target["objective"],
                    "goal_template": "diagnose {entry_point} for {entity_id} during {time_window}",
                    "required_bindings": ["entity_id", "time_window"],
                    "optional_bindings": [],
                    "constraint_refs": [],
                    "output_contract_ref": "cause-ranking",
                }
            ],
            "constraints": [],
            "output_contracts": [
                {
                    "output_key": "cause-ranking",
                    "output_type": "cause_ranking",
                    "output_schema": {"schema_version": "cause-ranking/v1", "required": ["status", "ranking"]},
                }
            ],
            "fallback_policy": "restricted",
            "step_type_pins": registry,
            "steps": [
                {
                    "ordinal": 1,
                    "step_key": "prepare-causal-diagnosis",
                    "step_type": "knowledge_query",
                    "step_type_version_id": pins["knowledge_query"]["step_type_version_id"],
                    "step_name": "Prepare causal diagnosis",
                    "params": {"operation": "prepare", "reasoning_mode": "causal_diagnosis"},
                    "output_field": "evidence",
                },
                {
                    "ordinal": 2,
                    "step_key": "output-cause-ranking",
                    "step_type": "output",
                    "step_type_version_id": pins["output"]["step_type_version_id"],
                    "step_name": "Output cause ranking",
                    "params": {"operation": "render_cause_ranking"},
                    "output_field": "ranking",
                },
            ],
            "dependencies": [
                {
                    "from_step_key": "prepare-causal-diagnosis",
                    "to_step_key": "output-cause-ranking",
                    "dep_type": "data_flow",
                    "condition": None,
                    "condition_eval_phase": None,
                }
            ],
            "step_sources": [
                {
                    "step_key": "prepare-causal-diagnosis",
                    "source_ref_key": "primary",
                    "element_type": "node",
                    "element_key": target["entry_point"],
                    "element_path": None,
                    "role": "primary",
                }
            ],
            # Evidence remains dynamic and is expanded by Prepare, never into
            # physical Provider steps or bindings.
            "capability_requirements": [],
        }
