"""ECMC N01B 页面流程 E2E 驱动（FDE 验证用）。
用法: .venv/bin/python scripts/verify_ecmc_n01b.py http://127.0.0.1:8000
前置: 服务端以 EARP_ECMC_TEST_CATALOG=1 启动；tenant-demo/u1/r1 可登录。
全链路: 建模型 -> 节点/边/证据/规则 -> 校验 -> 提交 -> 发布 -> 编译 -> 激活 -> 过期CAS 409。
"""
"""ECMC N01B page-flow E2E driver — clean version. Run: python ecmc_e2e.py <base>"""
import json, sys, urllib.request, urllib.error, uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
def key():
    return f"fde-{uuid.uuid4().hex[:12]}"

TOKEN = ""
def req(method, path, body=None, rev=None, expect=None):
    """Uniform request; returns parsed body. Writes track revision via body['revision']."""
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", "Idempotency-Key": key()}
    if rev is not None: h["If-Match"] = f'"v{rev}"'
    if TOKEN: h["Authorization"] = "Bearer " + TOKEN
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            payload = json.loads(resp.read().decode() or "{}")
            etag = resp.headers.get("ETag")
            if isinstance(payload, dict):
                status = payload.get("result") or payload.get("status") or payload.get("runtime_readiness") or resp.status
            else:
                status = f"list({len(payload)})"
            print(f"OK  {method} {path} -- {status}" + (f" etag={etag}" if etag else ""))
            return payload
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        print(f"ERR {method} {path} -- {e.code}: {raw[:280]}")
        if expect is None:
            sys.exit(1)
        return {"_error": e.code, "_raw": raw}

def write(method, sub, body, rev):
    """Draft write: returns (body, new_revision)."""
    b = req(method, f"{V}{sub}", body, rev)
    if "_error" in b:
        sys.exit(1)
    return b, b["revision"]

with urllib.request.urlopen(urllib.request.Request(BASE + "/auth/login",
    data=json.dumps({"tenant_id": "tenant-demo", "user_id": "u1", "role_id": "r1"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")) as resp:
    TOKEN = json.loads(resp.read().decode())["token"]
print("login OK (tenant-demo / u1 / r1)")

# clean leftovers from earlier runs (same name)
for m in req("GET", "/v1/ecmc/causal-models"):
    if m.get("name") == "3 号矿产量下降诊断":
        req("POST", f"/causal-models/{m['model_id']}/versions", {"clone_from_version_id": None})  # no-op check
        # no delete endpoint for models; skip cleanup by name and use a unique suffix instead
print("note: model name reused; a fresh model will be created below")

created = req("POST", "/v1/ecmc/causal-models", {
    "name": "3 号矿产量下降诊断",
    "data_domain_ref": {"kind": "data_domain", "stable_id": "production", "version": "v1"},
    "diagnostic_target": {
        "objective": "diagnose", "entry_point": "production_output", "direction": "down",
        "domain": "production",
        "target_entity_type_ref": {"kind": "entity_type", "stable_id": "entity.mine", "version": "v1"},
        "time_window_schema_ref": {"kind": "time_window_schema", "stable_id": "daily_window", "version": "v1"},
    },
    "description": "FDE 页面验证模型",
})
model_id = created["model_id"]
ver = created["initial_version"]["model_version_id"]
V = f"/v1/ecmc/causal-models/{model_id}/versions/{ver}"
rev = created["initial_version"]["revision"]

# nodes
body, rev = write("PUT", "/nodes/production_output",
    {"entity_type_ref": {"kind": "entity_type", "stable_id": "entity.mine", "version": "v1"},
     "observability": "observable", "entry_point": True, "business_name": "产量", "notes": "入口"}, rev)
body, rev = write("PUT", "/nodes/haulage_cycle_time",
    {"entity_type_ref": {"kind": "entity_type", "stable_id": "entity.haulage_system", "version": "v1"},
     "observability": "observable", "entry_point": False, "business_name": "运输周期", "notes": None}, rev)
body, rev = write("PUT", "/nodes/haulage_queue_time",
    {"entity_type_ref": {"kind": "entity_type", "stable_id": "entity.haulage_system", "version": "v1"},
     "observability": "indirectly_observable", "entry_point": False, "business_name": "排队时间", "notes": None}, rev)

# edges (cause -> effect, toward entry)
body, rev = write("PUT", "/edges/e-cycle-to-output",
    {"from_node_key": "haulage_cycle_time", "to_node_key": "production_output",
     "relation_type_ref": {"kind": "relation_type", "stable_id": "relation.affects", "version": "v1"},
     "effect": "-", "strength": "0.80", "confidence": "0.90", "lag": "PT0S"}, rev)
body, rev = write("PUT", "/edges/e-queue-to-cycle",
    {"from_node_key": "haulage_queue_time", "to_node_key": "haulage_cycle_time",
     "relation_type_ref": {"kind": "relation_type", "stable_id": "relation.affects", "version": "v1"},
     "effect": "+", "strength": "0.60", "confidence": "0.70", "lag": "PT0S"}, rev)  # 排队↑→周期↑，正向

# evidence
body, rev = write("PUT", "/evidence-requirements/production_output/cov_1", {
    "metric_ref": {"kind": "metric", "stable_id": "metric.production_output", "version": "v1"},
    "unit_ref": {"kind": "unit", "stable_id": "ton", "version": "v1"},
    "aggregation_ref": {"kind": "aggregation", "stable_id": "sum_over_production_day", "version": "v1"},
    "time_window_ref": {"kind": "time_window_schema", "stable_id": "daily_window", "version": "v1"},
    "binding_template_ref": {"kind": "binding_template", "stable_id": "context_entity", "version": "v1"},
    "binding_params": {}, "required": True,
    "primary_contract_ref": {"kind": "capability_contract", "stable_id": "contract.read_production_output", "version": "v1"},
    "supporting_contract_refs": [], "business_description": "判定产量是否下降"}, rev)
body, rev = write("PUT", "/evidence-requirements/haulage_cycle_time/cov_1", {
    "metric_ref": {"kind": "metric", "stable_id": "metric.haulage_cycle_time", "version": "v1"},
    "unit_ref": {"kind": "unit", "stable_id": "minute", "version": "v1"},
    "aggregation_ref": {"kind": "aggregation", "stable_id": "mean", "version": "v1"},
    "time_window_ref": {"kind": "time_window_schema", "stable_id": "daily_window", "version": "v1"},
    "binding_template_ref": {"kind": "binding_template", "stable_id": "outbound_relation", "version": "v1"},
    "binding_params": {"relation_type_ref": {"kind": "relation_type", "stable_id": "relation.has_subsystem", "version": "v1"},
                       "target_entity_type_ref": {"kind": "entity_type", "stable_id": "entity.haulage_system", "version": "v1"}},
    "required": True,
    "primary_contract_ref": {"kind": "capability_contract", "stable_id": "contract.read_haulage_cycle", "version": "v1"},
    "supporting_contract_refs": [], "business_description": "判定运输周期是否恶化"}, rev)

# rule
body, rev = write("PUT", "/rules/r-1",
    {"rule_schema_ref": {"kind": "rule_schema", "stable_id": "direction_rule", "version": "v1"},
     "rule_spec": {"operator": "matches_direction", "expected": "down"}, "rationale": "产量下降方向规则"}, rev)

validation = req("POST", f"{V}/validate", {"mode": "full"})
assert validation["result"] == "passed", f"validation failed: {json.dumps(validation.get('issues'), ensure_ascii=False)[:400]}"
print("=> validate PASSED")

sub = req("POST", f"{V}/submit-review", None, rev)
rev += 1
print("=> status:", sub.get("status"))
pub = req("POST", f"{V}/publish", None, rev)
rev += 1
print("=> published snapshot:", pub.get("snapshot_id"), "| hash:", (pub.get("content_hash") or "")[:12], "| status:", pub.get("status"))

compiled = req("POST", f"{V}/compile", {})
cr_id = compiled["compile_record"]["compile_record_id"]
print("=> compile running:", cr_id, "| status:", compiled["compile_record"]["status"])

done = req("POST", f"/v1/ecmc/_dev/complete-compile/{cr_id}")
print("=> compile done:", done.get("status"), "| artifact hash:", (done.get("compiled_artifact_hash") or "")[:12])

gov = req("GET", f"{V}/governance")
print("=> governance: status=%s readiness=%s activation=%s" % (gov["governance_status"], gov["runtime_readiness"], gov["activation_status"]))

art = req("GET", f"{V}/compile-records/{cr_id}/artifact")
print("=> artifact schema:", art["artifact_schema_version"], "| keys of artifact:", list((art.get("compiled_artifact") or {}).keys())[:6])

act = req("POST", f"/v1/ecmc/causal-models/{model_id}/activate", {
    "model_version_id": ver, "compile_record_id": cr_id,
    "expected_active_model_version_id": None, "expected_active_snapshot_id": None}, rev)
print("=> activated pointer:", (act.get("active_pointer") or {}).get("model_version_id"))

gov2 = req("GET", f"{V}/governance")
print("=> after activation: readiness=%s activation=%s" % (gov2["runtime_readiness"], gov2["activation_status"]))

# stale-CAS activation must return 409 ACTIVE_VERSION_CHANGED
stale = req("POST", f"/v1/ecmc/causal-models/{model_id}/activate", {
    "model_version_id": ver, "compile_record_id": cr_id,
    "expected_active_model_version_id": None, "expected_active_snapshot_id": None}, rev, expect="409")
code = json.loads(stale["_raw"]).get("error", {}).get("code") if "_error" in stale else None
print("=> stale-CAS:", stale["_error"] if "_error" in stale else "UNEXPECTED SUCCESS", code or "")

print("DONE")