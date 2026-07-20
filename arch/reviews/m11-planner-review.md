# M11 LLM Planner 真实调用 — 代码评审报告

**评审范围**: commit `d0b48be` (diff `608dd9a..d0b48be`)
**评审日期**: 2026-07-20

---

## 1. `_build_plan_system_prompt()` — 动态 prompt 模板

**文件**: `connector.py:70-91`

**结论**: PASS

`capabilities` 入参使用 `list[dict] | None`，`if capabilities` 判空同时覆盖 `None` 和 `[]` 两种 falsy 值，回退到硬编码 demo capabilities。JSON 结构指令 + 可用能力列表 + "Output ONLY valid JSON" 约束都正确写入 system prompt。

注意点：当 `capabilities=[]`（租户无任何注册能力）时回退到 demo 列表，可能让 LLM 输出 demo 场景的 capability_id。但下游 `plan()` 中的校验对此场景不会触发（见第 2 项），存在隐患。该问题与第 2 项联动，在第 2 项中详述。

---

## 2. `plan()` — capability_id 校验逻辑

**文件**: `connector.py:197-211`

**结论**: ISSUE — P2

校验逻辑本身正确：

- `capabilities` 非空时才校验
- 构建 `valid_ids` set，过滤非法 capability_id
- 过滤后 steps 为空抛 `ConnectorError` — 行为正确

**问题**: 当 `capabilities=[]`（租户无能力）时，`if capabilities:` 为 `False`，校验**完全跳过**。同时 `_build_plan_system_prompt([])` 回退到硬编码 demo capabilities（`cap-demo-echo` 等），LLM 可能据此生成步骤。这些 capability_id 实际不存在于该租户的 `business_capabilities` 表，后续执行必然失败，且错误提示不直观。

**建议**: 在 `main.py` 的 `plan_endpoint` 中或 `_build_plan_system_prompt` 入口处增加对空列表的短路处理：要么报错（"no capabilities registered"），要么向 prompt 传递空能力列表使 LLM 知晓无可用能力。

---

## 3. Cache key — capabilities 顺序稳定性

**文件**: `connector.py:190`

**结论**: ISSUE — P2

```python
cache_key = f"{self._model}||{prompt}||{json.dumps(capabilities or [])}"
```

`json.dumps` 对 Python dict 序列化时保持 key 插入顺序（Python 3.7+），dict key 顺序没问题。但 `list_for_planning()` 的 SQL 查询**缺少 `ORDER BY`**：

```sql
SELECT capability_id, domain, name, type, input_schema
FROM business_capabilities WHERE tenant_id = :tid
```

PostgreSQL 不保证无 `ORDER BY` 时行序一致。同样一组能力在不同请求中可能以不同顺序返回，导致 `json.dumps` 输出不同、cache key 哈希不同、缓存频繁 miss。

**建议**: `list_for_planning()` 的 SQL 加 `ORDER BY capability_id`。或者 cache key 中改为 `json.dumps(sorted(capabilities, key=lambda c: c['capability_id']))`，后者容错性更好（不依赖 SQL 层保证）。

---

## 4. `list_for_planning()` — 无 role 过滤

**文件**: `registry.py:40-56`

**结论**: PASS

函数 docstring 已明确记录 "No role filtering — the planner needs full visibility"，是经过设计的决策。Planner 需要看到全部能力才能构造跨角色工作流。实际执行时会有独立的 permission check 拦截越权调用。

不过若后续在角色可见性层面引入按 role 过滤能力列表的需求，此函数需同步改造。当前无安全问题。

---

## 5. `task_planner.py` — capabilities 透传

**文件**: `task_planner.py:37-57`

**结论**: PASS

`SimpleTaskPlanner.plan()` 签名明确声明 `capabilities` keyword-only 参数，类型为 `list[dict[str, Any]] | None`，直接透传给 `self._llm.plan(intent, capabilities=capabilities)`。Fallback 路径（`RuleIntentPlanner`）不使用该参数，符合设计——规则引擎的 intent 表是静态的，不依赖动态能力注入。

`_cap_id_to_adapter` 转换逻辑（第 77-91 行）正确性已验证：`cap-demo-echo` → `demo.echo`。

---

## 6. `/plan` — 每次请求都查 business_capabilities 表

**文件**: `main.py:174-183`

**结论**: PASS（有优化空间）

`list_for_planning()` 执行 `SELECT ... FROM business_capabilities WHERE tenant_id = :tid`。对于典型 SaaS 场景：

- `business_capabilities` 表很小（几十到几百行/租户）
- 查询无 JOIN、无聚合
- PostgreSQL 可轻松承担数千 QPS

当前设计在合理负载下不是瓶颈。但该查询结果对同一租户几乎不变（能力注册是低频操作），可以考虑对 capability 列表做应用层短缓存（例如 TTL=60s），减少不必要的 DB 往返。

---

## 汇总

| 检查项 | 结论 | 严重度 |
|--------|------|--------|
| 1. 动态 prompt 模板 | PASS | — |
| 2. capability_id 校验（空列表跳过校验） | ISSUE | P2 |
| 3. Cache key 因无 ORDER BY 不稳定 | ISSUE | P2 |
| 4. 无 role 过滤 | PASS | — |
| 5. capabilities 透传 | PASS | — |
| 6. 每请求查 DB | PASS | — |

**P0: 0 | P1: 0 | P2: 2 | 全部 PASS: 4/6**
