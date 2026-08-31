"""Artifact-only N01A activation and active-version archival."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import text

from earp_server.infra.db import tenant_session

from .canonicalization import BLUEPRINT_IR_SCHEMA, canonical_hash
from .catalog import CatalogValidationContext
from .errors import conflict
from .schemas import ActivateRequest, CatalogRef
from .service import ActorContext, CausalModelService, _id, _json


class ActivationCoordinator(CausalModelService):
    async def activate(
        self,
        actor: ActorContext,
        model_id: str,
        request: ActivateRequest,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.activate:{model_id}"
        payload = {**request.model_dump(mode="json"), "expected_revision": expected_revision}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.activate")
            model = await self._model(session, actor, model_id, for_update=True)
            version = await self._version(
                session, actor, model_id, request.model_version_id, for_update=True
            )
            self._revision(version, expected_revision)
            if version["status"] != "published" or version["published_snapshot_id"] is None:
                raise conflict("INVALID_STATE_TRANSITION", "Activation requires a published candidate Version.")
            record = (
                await session.execute(
                    text(
                        "SELECT * FROM blueprint_compile_records WHERE compile_id=:compile "
                        "AND n01a_attempt=true FOR UPDATE"
                    ),
                    {"compile": request.compile_record_id},
                )
            ).mappings().first()
            if (
                record is None
                or record["status"] != "success"
                or record["model_version_id"] != request.model_version_id
                or record["snapshot_id"] != version["published_snapshot_id"]
            ):
                raise conflict(
                    "INVALID_STATE_TRANSITION",
                    "Selected success Artifact does not match the candidate Version.",
                )

            actual_version = model["active_model_version_id"]
            actual_snapshot = model["active_snapshot_id"]
            if (
                request.expected_active_model_version_id != actual_version
                or request.expected_active_snapshot_id != actual_snapshot
            ):
                raise conflict(
                    "ACTIVE_VERSION_CHANGED",
                    "The active model version changed before activation.",
                    expected={
                        "model_version_id": request.expected_active_model_version_id,
                        "snapshot_id": request.expected_active_snapshot_id,
                    },
                    actual={"model_version_id": actual_version, "snapshot_id": actual_snapshot},
                    current_model_revision=model["revision"],
                )

            artifact = record["compiled_artifact_json"]
            artifact_hash = record["compiled_artifact_hash"]
            if record["artifact_schema_version"] != BLUEPRINT_IR_SCHEMA or artifact is None:
                raise conflict("CONTENT_CHANGED", "Candidate Artifact schema is invalid.")
            if canonical_hash(artifact, BLUEPRINT_IR_SCHEMA) != artifact_hash:
                raise conflict("CONTENT_CHANGED", "Candidate Artifact hash does not match its immutable payload.")
            await self._revalidate_catalog(session, actor, record["snapshot_id"])

            old_blueprint_version_id = None
            if actual_version is not None:
                old_rows = [
                    dict(row)
                    for row in (
                        await session.execute(
                            text(
                                "SELECT bpv.blueprint_version_id,bpv.blueprint_id FROM planning_blueprint_versions bpv "
                                "JOIN blueprint_source_models src ON src.tenant_id=bpv.tenant_id "
                                "AND src.blueprint_version_id=bpv.blueprint_version_id "
                                "JOIN causal_model_snapshots snap ON snap.tenant_id=src.tenant_id "
                                "AND snap.snapshot_id=src.source_snapshot_id "
                                "WHERE bpv.status='compiled' AND src.model_type='causal' "
                                "AND src.model_id=:model AND src.source_snapshot_id=:snapshot "
                                "AND src.source_content_hash=snap.content_hash FOR UPDATE OF bpv"
                            ),
                            {"model": model_id, "snapshot": actual_snapshot},
                        )
                    ).mappings()
                ]
                if len(old_rows) != 1:
                    raise conflict("CONTENT_CHANGED", "Current Blueprint does not exactly pin the active Snapshot.")
                old_blueprint_version_id = old_rows[0]["blueprint_version_id"]
                await session.execute(
                    text(
                        "UPDATE planning_blueprint_versions SET status='superseded' "
                        "WHERE blueprint_version_id=:version"
                    ),
                    {"version": old_blueprint_version_id},
                )

            blueprint_id, blueprint_version_id = await self._materialize(
                session, actor, model, record, artifact, artifact_hash
            )
            projection = await self.project_blueprint(session, blueprint_version_id)
            projection_hash = canonical_hash(projection, BLUEPRINT_IR_SCHEMA)
            if projection_hash != artifact_hash:
                raise conflict(
                    "CONTENT_CHANGED",
                    "Materialized Blueprint projection does not match the selected Candidate Artifact.",
                    compiled_artifact_hash=artifact_hash,
                    projection_hash=projection_hash,
                )

            if actual_version is not None:
                await session.execute(
                    text(
                        "UPDATE causal_model_versions SET status='superseded',revision=revision+1,updated_at=now(),"
                        "updated_by=:actor WHERE model_version_id=:version AND status='published'"
                    ),
                    {"actor": actor.actor_id, "version": actual_version},
                )
            candidate_revision = int(
                (
                    await session.execute(
                        text(
                            "UPDATE causal_model_versions SET revision=revision+1,updated_at=now(),updated_by=:actor "
                            "WHERE model_version_id=:version RETURNING revision"
                        ),
                        {"actor": actor.actor_id, "version": request.model_version_id},
                    )
                ).scalar_one()
            )
            await session.execute(
                text(
                    "UPDATE causal_models SET active_model_version_id=:version,active_snapshot_id=:snapshot,"
                    "revision=revision+1,updated_at=now() WHERE model_id=:model"
                ),
                {
                    "version": request.model_version_id,
                    "snapshot": record["snapshot_id"],
                    "model": model_id,
                },
            )
            body = {
                "active_pointer": {
                    "model_version_id": request.model_version_id,
                    "snapshot_id": record["snapshot_id"],
                },
                "blueprint_version_id": blueprint_version_id,
                "compiled_artifact_hash": artifact_hash,
                "revision": candidate_revision,
                "superseded": {
                    "model_version_id": actual_version,
                    "blueprint_version_id": old_blueprint_version_id,
                },
            }
            await self._audit(session, actor, "ecmc.causal_model.activated", "causal_model", model_id, body)
            await self._outbox(
                session,
                actor,
                "ecmc.causal_model.activated",
                "causal_model",
                model_id,
                {
                    **body,
                    "compile_record_id": request.compile_record_id,
                    "blueprint_id": blueprint_id,
                    "expected_active_model_version_id": request.expected_active_model_version_id,
                    "expected_active_snapshot_id": request.expected_active_snapshot_id,
                },
                idempotency_key,
                "runtime-discovery-cache",
            )
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}

    async def _revalidate_catalog(self, session, actor: ActorContext, snapshot_id: str) -> None:
        row = (
            await session.execute(
                text(
                    "SELECT catalog_resolutions,diagnostic_target FROM causal_model_snapshots "
                    "WHERE snapshot_id=:snapshot"
                ),
                {"snapshot": snapshot_id},
            )
        ).mappings().one()
        domain = row["diagnostic_target"]["domain"]
        for pin in row["catalog_resolutions"]:
            ref = CatalogRef(kind=pin["kind"], stable_id=pin["stable_id"], version=pin["version"])
            resolved = await self.catalog.resolve(
                actor.tenant_id,
                ref,
                ref.kind,
                context=CatalogValidationContext(
                    actor.tenant_id, domain, {"resource_type": "snapshot", "snapshot_id": snapshot_id}
                ),
            )
            if resolved.content_hash != pin["content_hash"]:
                raise conflict("CONTENT_CHANGED", "Catalog resolution no longer matches the Snapshot pin.")

    async def _materialize(
        self,
        session,
        actor: ActorContext,
        model: dict[str, Any],
        record: Any,
        artifact: dict[str, Any],
        artifact_hash: str,
    ) -> tuple[str, str]:
        blueprint_id = "bp-" + hashlib.sha256(
            f"{actor.tenant_id}:{model['model_id']}".encode()
        ).hexdigest()[:61]
        await session.execute(
            text(
                "INSERT INTO planning_blueprints "
                "(tenant_id,blueprint_id,primary_model_type,primary_model_id,name,description) "
                "VALUES (:tenant,:blueprint,'causal',:model,:name,:description) "
                "ON CONFLICT (tenant_id,primary_model_type,primary_model_id) DO NOTHING"
            ),
            {
                "tenant": actor.tenant_id,
                "blueprint": blueprint_id,
                "model": model["model_id"],
                "name": model["name"],
                "description": model["description"],
            },
        )
        blueprint_id = str(
            (
                await session.execute(
                    text(
                        "SELECT blueprint_id FROM planning_blueprints WHERE primary_model_type='causal' "
                        "AND primary_model_id=:model"
                    ),
                    {"model": model["model_id"]},
                )
            ).scalar_one()
        )
        blueprint_version_id = _id("bpv")
        intent = artifact["intents"][0]
        await session.execute(
            text(
                "INSERT INTO planning_blueprint_versions "
                "(tenant_id,blueprint_version_id,blueprint_id,version,status,compile_record_id,compiler_version,"
                "source_fingerprint,intent_signature,validation_contract,output_contract,fallback_policy,"
                "compiled_artifact_hash,artifact_schema_version,n01a_activation) "
                "VALUES (:tenant,:version_id,:blueprint,:version,'compiled',:compile,:compiler,:fingerprint,"
                ":intent,:validation,:output,:fallback,:hash,:schema,true)"
            ),
            {
                "tenant": actor.tenant_id,
                "version_id": blueprint_version_id,
                "blueprint": blueprint_id,
                "version": f"n01a-{artifact_hash[:16]}",
                "compile": record["compile_id"],
                "compiler": record["compiler_version"],
                "fingerprint": artifact_hash,
                "intent": _json(intent),
                "validation": _json({"artifact_schema_version": BLUEPRINT_IR_SCHEMA}),
                "output": _json(artifact["output_contracts"]),
                "fallback": artifact["fallback_policy"],
                "hash": artifact_hash,
                "schema": BLUEPRINT_IR_SCHEMA,
            },
        )
        source_ids: dict[str, str] = {}
        for source in artifact["source_models"]:
            source_row_id = _id("bp-source")
            source_ids[source["source_ref_key"]] = source_row_id
            await session.execute(
                text(
                    "INSERT INTO blueprint_source_models "
                    "(tenant_id,source_ref_id,source_stable_key,blueprint_version_id,model_type,model_id,model_version,"
                    "source_snapshot_id,source_content_hash,model_role) "
                    "VALUES (:tenant,:source_id,:source_key,:version,:model_type,:model_id,:model_version,"
                    ":snapshot,:hash,:role)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "source_id": source_row_id,
                    "source_key": source["source_ref_key"],
                    "version": blueprint_version_id,
                    "model_type": source["model_type"],
                    "model_id": source["model_id"],
                    "model_version": source["model_version"],
                    "snapshot": source["source_snapshot_id"],
                    "hash": source["source_content_hash"],
                    "role": source["model_role"],
                },
            )
        for item in artifact["intents"]:
            await session.execute(
                text(
                    "INSERT INTO blueprint_intents "
                    "(tenant_id,intent_id,intent_stable_key,blueprint_version_id,entry_point,direction,domain,"
                    "business_objective) VALUES (:tenant,:row,:key,:version,:entry,:direction,:domain,:objective)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("bp-intent"),
                    "key": item["intent_key"],
                    "version": blueprint_version_id,
                    "entry": item["entry_point"],
                    "direction": item["direction"],
                    "domain": item["domain"],
                    "objective": item["business_objective"],
                },
            )
        for item in artifact["constraints"]:
            await session.execute(
                text(
                    "INSERT INTO blueprint_constraints "
                    "(tenant_id,constraint_id,constraint_stable_key,blueprint_version_id,constraint_class,"
                    "constraint_type,constraint_value,source_ref,rationale) "
                    "VALUES (:tenant,:row,:key,:version,:class,:type,:value,:source,:rationale)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("bp-constraint"),
                    "key": item["constraint_key"],
                    "version": blueprint_version_id,
                    "class": item["constraint_class"],
                    "type": item["constraint_type"],
                    "value": _json(item["constraint_value"]),
                    "source": item.get("source_ref"),
                    "rationale": item.get("rationale"),
                },
            )
        output_ids: dict[str, str] = {}
        for item in artifact["output_contracts"]:
            output_row_id = _id("bp-output")
            output_ids[item["output_key"]] = output_row_id
            await session.execute(
                text(
                    "INSERT INTO blueprint_output_contracts "
                    "(tenant_id,output_id,output_stable_key,blueprint_version_id,output_type,output_schema) "
                    "VALUES (:tenant,:row,:key,:version,:type,:schema)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": output_row_id,
                    "key": item["output_key"],
                    "version": blueprint_version_id,
                    "type": item["output_type"],
                    "schema": _json(item["output_schema"]),
                },
            )
        for item in artifact["goal_skeletons"]:
            await session.execute(
                text(
                    "INSERT INTO blueprint_goal_skeletons "
                    "(tenant_id,goal_skeleton_id,goal_skeleton_stable_key,blueprint_version_id,objective,goal_template,"
                    "required_bindings,optional_bindings,constraint_refs,output_contract_ref) "
                    "VALUES (:tenant,:row,:key,:version,:objective,:template,:required,:optional,:constraints,:output)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("bp-goal"),
                    "key": item["goal_skeleton_key"],
                    "version": blueprint_version_id,
                    "objective": item["objective"],
                    "template": item["goal_template"],
                    "required": _json(item["required_bindings"]),
                    "optional": _json(item["optional_bindings"]),
                    "constraints": _json(item["constraint_refs"]),
                    "output": output_ids[item["output_contract_ref"]],
                },
            )
        step_ids: dict[str, str] = {}
        for item in artifact["steps"]:
            step_row_id = _id("bp-step")
            step_ids[item["step_key"]] = step_row_id
            await session.execute(
                text(
                    "INSERT INTO blueprint_steps "
                    "(tenant_id,step_id,step_stable_key,blueprint_version_id,step_seq,step_type_version_id,step_type,"
                    "step_name,params,output_field) "
                    "VALUES (:tenant,:row,:key,:version,:ordinal,:type_version,:type,:name,:params,:output)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": step_row_id,
                    "key": item["step_key"],
                    "version": blueprint_version_id,
                    "ordinal": item["ordinal"],
                    "type_version": item["step_type_version_id"],
                    "type": item["step_type"],
                    "name": item["step_name"],
                    "params": _json(item["params"]),
                    "output": item.get("output_field"),
                },
            )
        for item in artifact["dependencies"]:
            await session.execute(
                text(
                    "INSERT INTO blueprint_step_deps "
                    "(tenant_id,dep_id,blueprint_version_id,from_step_id,to_step_id,dep_type,"
                    "condition,condition_eval_phase) "
                    "VALUES (:tenant,:dep,:version,:source,:target,:type,:condition,:phase)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "dep": _id("dep"),
                    "version": blueprint_version_id,
                    "source": step_ids[item["from_step_key"]],
                    "target": step_ids[item["to_step_key"]],
                    "type": item["dep_type"],
                    "condition": _json(item["condition"]) if item.get("condition") is not None else None,
                    "phase": item.get("condition_eval_phase"),
                },
            )
        for item in artifact["step_sources"]:
            await session.execute(
                text(
                    "INSERT INTO blueprint_step_sources "
                    "(tenant_id,step_source_id,blueprint_version_id,step_id,source_model_ref_id,element_type,"
                    "element_key,element_path,role) "
                    "VALUES (:tenant,:row,:version,:step,:source,:type,:key,:path,:role)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("step-source"),
                    "version": blueprint_version_id,
                    "step": step_ids[item["step_key"]],
                    "source": source_ids[item["source_ref_key"]],
                    "type": item["element_type"],
                    "key": item["element_key"],
                    "path": item.get("element_path"),
                    "role": item["role"],
                },
            )
        for item in artifact["capability_requirements"]:
            await session.execute(
                text(
                    "INSERT INTO blueprint_capability_requirements "
                    "(tenant_id,capability_requirement_id,blueprint_version_id,requirement_key,step_key,contract_ref,"
                    "requirement_schema_version,required) "
                    "VALUES (:tenant,:row,:version,:key,:step,:contract,:schema,:required)"
                ),
                {
                    "tenant": actor.tenant_id,
                    "row": _id("bp-cap-req"),
                    "version": blueprint_version_id,
                    "key": item["requirement_key"],
                    "step": item.get("step_key"),
                    "contract": _json(item["contract_ref"]),
                    "schema": item["requirement_schema_version"],
                    "required": item["required"],
                },
            )
        return blueprint_id, blueprint_version_id

    @staticmethod
    async def project_blueprint(session, blueprint_version_id: str) -> dict[str, Any]:
        version = (
            await session.execute(
                text(
                    "SELECT fallback_policy,artifact_schema_version FROM planning_blueprint_versions "
                    "WHERE blueprint_version_id=:version"
                ),
                {"version": blueprint_version_id},
            )
        ).mappings().one()

        async def rows(query: str) -> list[dict[str, Any]]:
            return [
                dict(row)
                for row in (
                    await session.execute(text(query), {"version": blueprint_version_id})
                ).mappings()
            ]

        sources = await rows(
            "SELECT source_stable_key AS source_ref_key,model_type,model_id,model_version,"
            "source_snapshot_id,source_content_hash,model_role FROM blueprint_source_models "
            "WHERE blueprint_version_id=:version"
        )
        intents = await rows(
            "SELECT intent_stable_key AS intent_key,entry_point,direction,domain,business_objective "
            "FROM blueprint_intents WHERE blueprint_version_id=:version"
        )
        goals = await rows(
            "SELECT goal.goal_skeleton_stable_key AS goal_skeleton_key,goal.objective,goal.goal_template,"
            "goal.required_bindings,goal.optional_bindings,goal.constraint_refs,"
            "out.output_stable_key AS output_contract_ref "
            "FROM blueprint_goal_skeletons goal LEFT JOIN blueprint_output_contracts out "
            "ON out.tenant_id=goal.tenant_id AND out.blueprint_version_id=goal.blueprint_version_id "
            "AND out.output_id=goal.output_contract_ref WHERE goal.blueprint_version_id=:version"
        )
        constraints = await rows(
            "SELECT constraint_stable_key AS constraint_key,constraint_class,constraint_type,constraint_value,"
            "source_ref,rationale "
            "FROM blueprint_constraints WHERE blueprint_version_id=:version"
        )
        outputs = await rows(
            "SELECT output_stable_key AS output_key,output_type,output_schema FROM blueprint_output_contracts "
            "WHERE blueprint_version_id=:version"
        )
        pins = await rows(
            "SELECT t.type_name AS step_type,v.version,v.step_type_version_id,v.handler_version,v.handler_hash,"
            "v.semantic_contract_version FROM step_type_versions v JOIN step_types t ON t.type_id=v.type_id "
            "WHERE v.step_type_version_id IN (SELECT step_type_version_id FROM blueprint_steps "
            "WHERE blueprint_version_id=:version)"
        )
        steps = await rows(
            "SELECT step_seq AS ordinal,step_stable_key AS step_key,step_type,step_type_version_id,"
            "step_name,params,output_field "
            "FROM blueprint_steps WHERE blueprint_version_id=:version"
        )
        deps = await rows(
            "SELECT source.step_stable_key AS from_step_key,target.step_stable_key AS to_step_key,"
            "dep.dep_type,dep.condition,dep.condition_eval_phase FROM blueprint_step_deps dep "
            "JOIN blueprint_steps source ON source.tenant_id=dep.tenant_id "
            "AND source.blueprint_version_id=dep.blueprint_version_id AND source.step_id=dep.from_step_id "
            "JOIN blueprint_steps target ON target.tenant_id=dep.tenant_id "
            "AND target.blueprint_version_id=dep.blueprint_version_id AND target.step_id=dep.to_step_id "
            "WHERE dep.blueprint_version_id=:version"
        )
        step_sources = await rows(
            "SELECT step.step_stable_key AS step_key,source.source_stable_key AS source_ref_key,"
            "link.element_type,link.element_key,link.element_path,link.role FROM blueprint_step_sources link "
            "JOIN blueprint_steps step ON step.tenant_id=link.tenant_id "
            "AND step.blueprint_version_id=link.blueprint_version_id AND step.step_id=link.step_id "
            "JOIN blueprint_source_models source ON source.tenant_id=link.tenant_id "
            "AND source.blueprint_version_id=link.blueprint_version_id "
            "AND source.source_ref_id=link.source_model_ref_id WHERE link.blueprint_version_id=:version"
        )
        capabilities = await rows(
            "SELECT requirement_key,step_key,contract_ref,requirement_schema_version,required "
            "FROM blueprint_capability_requirements WHERE blueprint_version_id=:version"
        )
        return {
            "artifact_schema_version": version["artifact_schema_version"],
            "source_models": sources,
            "intents": intents,
            "goal_skeletons": goals,
            "constraints": constraints,
            "output_contracts": outputs,
            "fallback_policy": version["fallback_policy"],
            "step_type_pins": pins,
            "steps": steps,
            "dependencies": deps,
            "step_sources": step_sources,
            "capability_requirements": capabilities,
        }

    async def archive(
        self,
        actor: ActorContext,
        model_id: str,
        version_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        operation = f"causal-model.archive:{version_id}"
        payload = {"expected_revision": expected_revision}
        async with tenant_session(self.engine, actor.tenant_id) as session:
            replay = await self._replay(session, actor, operation, idempotency_key, payload)
            if replay:
                return replay
            scope = await self._role_scope(session, actor)
            self._require_permission(scope, "ecmc.causal_model.review")
            model = await self._model(session, actor, model_id, for_update=True)
            version = await self._version(session, actor, model_id, version_id, for_update=True)
            self._revision(version, expected_revision)
            if version["status"] == "archived":
                raise conflict("INVALID_STATE_TRANSITION", "Version is already archived.")
            active = model["active_model_version_id"] == version_id
            blueprint_version_id = None
            if active:
                rows = [
                    dict(row)
                    for row in (
                        await session.execute(
                            text(
                                "SELECT bpv.blueprint_version_id FROM planning_blueprint_versions bpv "
                                "JOIN blueprint_source_models src ON src.tenant_id=bpv.tenant_id "
                                "AND src.blueprint_version_id=bpv.blueprint_version_id "
                                "JOIN causal_model_snapshots snap ON snap.tenant_id=src.tenant_id "
                                "AND snap.snapshot_id=src.source_snapshot_id "
                                "WHERE bpv.status='compiled' AND src.model_type='causal' AND src.model_id=:model "
                                "AND src.source_snapshot_id=:snapshot AND src.source_content_hash=snap.content_hash "
                                "FOR UPDATE OF bpv"
                            ),
                            {"model": model_id, "snapshot": model["active_snapshot_id"]},
                        )
                    ).mappings()
                ]
                if len(rows) != 1:
                    raise conflict("CONTENT_CHANGED", "Active Blueprint source pin is not unique and exact.")
                blueprint_version_id = rows[0]["blueprint_version_id"]
                await session.execute(
                    text(
                        "UPDATE planning_blueprint_versions SET status='withdrawn' "
                        "WHERE blueprint_version_id=:version"
                    ),
                    {"version": blueprint_version_id},
                )
                await session.execute(
                    text(
                        "UPDATE causal_models SET active_model_version_id=NULL,active_snapshot_id=NULL,"
                        "revision=revision+1,updated_at=now() WHERE model_id=:model"
                    ),
                    {"model": model_id},
                )
            revision = expected_revision + 1
            await session.execute(
                text(
                    "UPDATE causal_model_versions SET status='archived',revision=:revision,updated_at=now(),"
                    "updated_by=:actor WHERE model_version_id=:version"
                ),
                {"revision": revision, "actor": actor.actor_id, "version": version_id},
            )
            await self._review(session, actor, model_id, version_id, "archive", "archived", None)
            body = {
                "model_version_id": version_id,
                "status": "archived",
                "revision": revision,
                "active_pointer": {"model_version_id": None, "snapshot_id": None} if active else None,
                "withdrawn_blueprint_version_id": blueprint_version_id,
            }
            await self._audit(session, actor, "ecmc.causal_model.archived", "causal_model_version", version_id, body)
            await self._outbox(
                session,
                actor,
                "ecmc.causal_model.archived",
                "causal_model_version",
                version_id,
                body,
                idempotency_key,
                "runtime-discovery-cache",
            )
            await self._remember(session, actor, operation, idempotency_key, payload, 200, body)
            return {"status_code": 200, "body": body, "replayed": False}
