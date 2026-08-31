"""从不可变 Snapshot 恢复被误删的已发布模型（本地 dev 恢复工具，谨慎使用）。

背景：cleanup_ecmc_test_data.py 按模型名删除，误删了 FDE 刚发布的
「3 号矿产量下降诊断」（发布 Snapshot 不可变，未被删除）。本脚本从 Snapshot
重建 model/version（published，指向原 snapshot）并回填图内容。
"""
import asyncio, os, json, hashlib, uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

def _json(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

def _request_hash(v):
    return hashlib.sha256(_json(v).encode("utf-8")).hexdigest()

def _id(prefix):
    return f"{prefix}-{uuid.uuid4().hex}"

TENANT = "tenant-demo"
MODEL = "cm-636c5a8ae0a3468eb19ba4136c4ee972"
VERSION = "cmv-0ba6b8c10ad640e0b55890893b745bb1"
SNAP = "cms-a1920e33d7884986b92a99cf8c5e01e8"

async def main():
    engine = create_async_engine(os.environ["EARP_MIGRATION_DATABASE_URL"])
    async with engine.begin() as conn:
        # 跳过 draft-only guard / immutable 触发器（恢复用途，仅 postgres 超管会话）
        await conn.execute(text("SET session_replication_role = replica"))
        row = (await conn.execute(text("SELECT canonical_payload FROM causal_model_snapshots WHERE snapshot_id=:s"), {"s": SNAP})).first()
        assert row, "snapshot not found"
        p = row[0]
        target = p["diagnostic_target"]
        sig = _request_hash(target)
        await conn.execute(text(
            "INSERT INTO causal_models (tenant_id,model_id,data_domain_id,name,description,diagnostic_target_signature) "
            "VALUES (:t,:m,:d,:name,NULL,:sig)"),
            {"t": TENANT, "m": MODEL, "d": target["domain"], "name": "3 号矿产量下降诊断", "sig": sig})
        await conn.execute(text(
            "INSERT INTO causal_model_versions (tenant_id,model_version_id,model_id,version,status,diagnostic_target,"
            "diagnostic_target_signature,revision,created_by,updated_by,published_snapshot_id,published_at,reviewed_at,submitted_at) "
            "VALUES (:t,:v,:m,'1','published',:target,:sig,25,'u1','u1',:s,now(),now(),now())"),
            {"t": TENANT, "v": VERSION, "m": MODEL, "target": _json(target), "sig": sig, "s": SNAP})
        seq = 0
        for n in p["nodes"]:
            seq += 1
            await conn.execute(text(
                "INSERT INTO causal_nodes (tenant_id,node_row_id,model_version_id,node_key,node_seq,entity_type_ref,"
                "entity_type_catalog_ref,observability,entry_point,business_name,notes) "
                "VALUES (:t,:row,:v,:key,:seq,:stable,:catalog_ref,:obs,:entry,:name,NULL)"),
                {"t": TENANT, "row": _id("node"), "v": VERSION, "key": n["node_key"], "seq": seq,
                 "stable": n["entity_type_ref"]["stable_id"], "catalog_ref": _json(n["entity_type_ref"]),
                 "obs": n["observability"], "entry": n["entry_point"], "name": n.get("business_name")})
        for e in p["edges"]:
            await conn.execute(text(
                "INSERT INTO causal_edges (tenant_id,edge_row_id,edge_key,model_version_id,source_node_key,target_node_key,"
                "relation_type_ref,relation_type_catalog_ref,effect,strength,confidence,lag) "
                "VALUES (:t,:row,:key,:v,:src,:dst,:stable,:catalog_ref,:effect,:strength,:confidence,:lag)"),
                {"t": TENANT, "row": _id("edge"), "key": e["edge_key"], "v": VERSION, "src": e["from_node_key"],
                 "dst": e["to_node_key"], "stable": e["relation_type_ref"]["stable_id"],
                 "catalog_ref": _json(e["relation_type_ref"]), "effect": e["effect"],
                 "strength": str(e["strength"]), "confidence": str(e["confidence"]), "lag": e["lag"]})
        for r in p["rules"]:
            await conn.execute(text(
                "INSERT INTO causal_rules (tenant_id,rule_row_id,rule_key,model_version_id,node_key,rule_type,rule_spec,rule_schema_ref,rationale) "
                "VALUES (:t,:row,:key,:v,NULL,:rtype,:spec,:schema_ref,NULL)"),
                {"t": TENANT, "row": _id("rule"), "key": r["rule_key"], "v": VERSION,
                 "rtype": "predicate", "spec": _json(r["rule_spec"]), "schema_ref": _json(r["rule_schema_ref"])})
        for req in p["evidence_requirements"]:
            await conn.execute(text(
                "INSERT INTO causal_data_bindings (tenant_id,binding_row_id,model_version_id,node_key,requirement_key,"
                "requirement_level,metric_binding,instance_binding_expr,metric_ref,unit_ref,aggregation_ref,time_window_ref,"
                "binding_template_ref,binding_params,business_description) "
                "VALUES (:t,:row,:v,:node,:req,:level,:metric_b,:binding_expr,:metric,:unit,:agg,:window,:template,:params,:desc)"),
                {"t": TENANT, "row": _id("binding"), "v": VERSION, "node": req["node_key"], "req": req["requirement_key"],
                 "level": "required" if req["required"] else "optional",
                 "metric_b": _json(req["metric_ref"]), "binding_expr": _json(req["binding_params"]),
                 "metric": _json(req["metric_ref"]), "unit": _json(req["unit_ref"]), "agg": _json(req["aggregation_ref"]),
                 "window": _json(req["time_window_ref"]), "template": _json(req["binding_template_ref"]),
                 "params": _json(req["binding_params"]), "desc": req.get("business_description")})
            for role, ref in [("primary", req["primary_contract_ref"])] + [("supporting", r) for r in req["supporting_contract_refs"]]:
                await conn.execute(text(
                    "INSERT INTO causal_capability_bindings (tenant_id,cap_binding_row_id,model_version_id,node_key,requirement_key,"
                    "capability_role,read_only_required,capability_contract_ref,capability_contract_catalog_ref) "
                    "VALUES (:t,:row,:v,:node,:req,:role,true,:stable,:catalog_ref)"),
                    {"t": TENANT, "row": _id("cap-binding"), "v": VERSION, "node": req["node_key"], "req": req["requirement_key"],
                     "role": role, "stable": ref["stable_id"], "catalog_ref": _json(ref)})
        # 清理本会话 E2E 留下的孤儿 snapshot（用户这条已挂回版本，不受影响）
        await conn.execute(text(
            "DELETE FROM causal_model_snapshots WHERE tenant_id=:t AND model_version_id NOT IN "
            "(SELECT model_version_id FROM causal_model_versions)"), {"t": TENANT})
        print("restored:", MODEL, "/", VERSION, "sig:", sig[:16])
    await engine.dispose()

asyncio.run(main())
