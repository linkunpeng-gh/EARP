# 任务清单 — Phase D: 能力闭环（D1 执行器 + chat 接入） + 角色层（D3）

**状态：决策已定（D1/D2/D3 方案 A），待开工**
**依据**：`arch/design/query-understanding-query-plan-design-v0.3.md`（§6.5 resolve_with_query / §8.2 通道角色 / §9.2 角色层组装 / §16 Phase D）
**关联**：session-record「下一步：Phase D——D1 resolve_with_query + capability 执行器（D2 边界解除）+ chat 接入；D3 角色层（tech-debt #10）」
**日期**：2026-08-16

## 目标

Phase C 的 plan_aggregation 是「候选解析 + 回落」（D2 边界：capability 执行链未建成）。Phase D 解除该边界：

- **D1a**：`resolve_with_query()` 新签名（§6.5）——接收 StructuredQuery，返回带 `matched_entity_ids`
- **D1b**：**capability query 执行器**——内置 ontology 事实聚合 adapter，让 plan_aggregation 真实执行聚合
- **D1c**：plan_aggregation 升级（执行器接入 + Evidence(channel=capability)）
- **D1d**：chat 接入 answer（chat_service 走 execute_plan，PlanResult → context block + citations）
- **D3**：角色层 Evidence 组装（§9.2 主/佐证定权 + 冲突消解，叠加在 recall 层之上，不替换 RRF）

**范围边界**：
- D2（ABox 反向邻接）✅ 已闭（G1 backward，2026-08-15）
- 通用 adapter 分发框架 / orchestrator StepRunner 只读执行 → **Phase F**（一期不建通用框架）
- connector.execute 不动（保持 demo.echo；通用分发留 Phase F）
- Plan 持久化、Evaluation 闭环 → 一期不做

## 既定决策（讨论已对齐，开工前置）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | capability 执行器形态 | **内置 ontology 事实聚合 adapter**（新 `ontology/capability_query.py`）：capability_call.input = {entity_type_ids, data_domain_ids, aggregate, group_by, time} → 从 ABox facts/entities 聚合（COUNT/SUM/AVG/MAX/MIN + group_by/order_by/limit + 时间过滤）。一期 1 个通用聚合执行器（capability.type=query 且 input 合规即执行）；不做通用 adapter 框架（Phase F）。**执行器在 ontology 域（有 DB），connector 保持无 DB**——plan_aggregation 直接调执行器，不经过 connector |
| D2 | chat 接入范围 | **全量走 execute_plan**：chat_service._retrieve 替换为 `execute_plan`（理解 → select_plan → 策略 → PlanResult → context block + citations）。import-linter：conversation → ontology.planning → knowledge.* 传递链按 P2 先例加 ignore（3 条）。kb_scope 限定路径保持现状（一期不接 planner，chat_apps 显式 KB 仍走 search_chunks） |
| D3 | 角色层一期深度 | **主/佐证定权 + 冲突消解全做**：§8.2 通道角色表定主/佐证（evidence 打 primary/auxiliary 标记）；冲突消解（valid_to 优先 → confidence 高者 → 双列 conflict=true 交 LLM）。不引入跨通道非对称权重（backlog） |
| D4 | resolve_with_query 位置 | `ontology/search.py`（与 resolve_with_entities 并列，签名新增，旧函数保留给 /plan M2 收窄路径） |
| D5 | plan_aggregation 无候选/执行失败 | 仍显式回落 plan_fact（trace 标注 reason）——执行器是增强，不是兜底 |

## 现状（已核实）

- `ontology/search.py::resolve_with_entities(intent: str)`：intent → _entity_hits → entity_type_ids → capability_entity_map 反查（capability_id/domain/name/type/operation）；**实体命中被内部丢弃**（§6.5 缺陷）
- `business_capabilities`：capability_id（全局单列 PK，tech-debt #7）/tenant_id/domain/name/type(query|command)/input_schema/output_schema/required_permissions/version——**无 adapter_type 列**；demo 用 required_permissions='{demo.echo}' 作标识
- `connector.execute`：仅 demo.echo adapter；未知 adapter → ConnectorError
- `conversation/chat_service.py::_retrieve`：kb_scope 空 → route_query + knowledge_search（三层）/全租户兜底；kb_scope 非空 → search_chunks——P1 双通道，P2 已接三层
- **facts 表结构**：source_entity_id/relation_type_id/target_entity_id/confidence/source_ref/status/valid_to——可支撑「alarm → caused_by → equipment」等聚合
- import-linter：conversation → ontology.search 已有 ignore（P2）；新增 conversation → ontology.planning（→knowledge.* 传递）需 3 条 ignore
- 基线：155 tests 全绿 + import-linter + OpenAPI 基线

---

## Phase D1 — 能力闭环

### Task 1 — `resolve_with_query()`（§6.5 新签名）

**文件**：`src/earp_server/ontology/search.py`

**改动点**：
```python
async def resolve_with_query(
    engine, tenant_id,
    query: StructuredQuery,      # 接收结构化输出（实体/关系/意图）
    *, top_k: int = 10,
) -> list[dict]:
    """entities → entity_type_ids → capability_entity_map 反查 → 候选能力。

    与 resolve_with_entities 的区别：直接用 query.entities 的 semantic_type/
    mention（非从 intent 字符串重新 tokenize）；命中实体不再内部丢弃——
    返回 {(capability_id, entity_type_id, matched_entity_ids, name, type, operation)}。
    """
```
- `resolve_with_entities` 保留（/plan M2 收窄路径，不改签名）
- matched_entity_ids：StructuredQuery.entities 中 semantic_type 匹配的实体（mention → lookup_entities → entity_id；lookup 失败保留 mention 作占位）
- 空 entities → 返回 []（调用方回落，MUST NOT block）

### Task 2 — capability query 执行器（D1b）

**文件**：`src/earp_server/ontology/capability_query.py`（新建）

**改动点**：
1. `execute_capability_query(engine, tenant_id, capability: dict, sq: StructuredQuery, *, ctx) -> dict`：
   - 输入：capability（resolve_with_query 返回）+ sq（StructuredQuery.operation + entities + time）
   - 构造查询：`entity_type_ids`（sq.entities.semantic_type 去重）+ `aggregate`（sq.operation.aggregate，默认 COUNT）+ `group_by`（sq.operation.group_by）+ `order_by`/`limit`（sq.operation）+ 时间过滤（sq.time.resolved_*，一期宽松）
   - 数据源：ABox facts/entities 聚合（Native-SQL，RLS）：
     - 计数：`COUNT(*) FROM entities WHERE entity_type_id = ANY(:ets) AND data_domain_id = ANY(:dds)`（权限过滤 data_domain_ids=角色 data_domain_access）
     - 关系计数（alarm → caused_by → equipment 等）：facts join 聚合
   - 输出：`{rows: [...], aggregate: {count/sum/avg/max/min: value}, capability_id}`
2. 权限：data_domain_ids 过滤（复用 route_query 的权限语义——从 roles.data_domain_access 取）；无权限 → 空
3. 失败（SQL 错误/无实体类型）→ 返回 None（调用方回落）

### Task 3 — plan_aggregation 升级（D1c，D2 边界解除）

**文件**：`src/earp_server/ontology/planning.py`

**改动点**：
1. `resolve_with_entities` → `resolve_with_query(sq)`（Task 1）
2. 有 query 候选 → `execute_capability_query`（Task 2）：
   - 成功 → PlanResult.evidence 追加 `Evidence(channel=CAPABILITY, content=rows, source=capability.name, source_ref=f"capcall-{uuid}", confidence=1.0, payload={capability_id, rows})`；trace `CAPABILITY_QUERY` 标注 executed=true + latency；citations 追加 capability 引用
   - 失败/None → 回落 plan_fact（D5，fallback_reason 标注）
3. 无候选 → 回落 plan_fact（保持）
4. 「capability 通道未就绪」标注移除（边界解除）

### Task 4 — chat 接入 answer（D1d）

**文件**：`src/earp_server/conversation/chat_service.py` + `pyproject.toml`（import-linter ignore）

**改动点**：
1. `_retrieve` 改造：kb_scope 空路径 → `execute_plan`（understand → upgrade_with_llm → select_plan → 策略 → PlanResult）：
   - chunks = PlanResult 的检索项（evidence 转回 item 形状：chunk/profile/graph 保持原结构；capability evidence → 附加结构化行）
   - citations = PlanResult.citations（三源 + capability）
   - trace 记录（debug 观测，不落库）
2. kb_scope 非空路径：保持 search_chunks（一期不接 planner）
3. `_build_context_block`：capability evidence 渲染为「结构化数据」块（表格行）
4. import-linter ignore 3 条（P2 先例）：
   ```
   "earp_server.conversation.chat_service -> earp_server.ontology.planning",
   "earp_server.conversation.chat_service -> earp_server.ontology.understanding",
   "earp_server.conversation.chat_service -> earp_server.ontology.capability_query",
   ```
5. 回归：test_chat 的 kb_scope 用例不动；软路由用例断言 PlanResult 语义（citations 含 capability/entity 徽标）

---

## Phase D3 — 角色层 Evidence 组装

### Task 5 — 主/佐证定权 + 冲突消解（§8.2/§9.2）

**文件**：`src/earp_server/ontology/planning.py`

**改动点**：
1. Evidence 加 `role: Literal["primary", "auxiliary"]` 字段（§8.2 通道角色）：
   ```python
   # FACT/ATTRIBUTE → chunk 主，profile/graph 佐
   # RELATION/MULTI_HOP/LIST → graph 主，chunk 佐
   # AGGREGATION/COMPARISON/TREND → capability 主（不进 RRF），graph 佐
   # CAUSAL/MIXED → capability+graph 并重，chunk 佐
   ```
2. 策略函数组装 evidence 后按 `_role_for(evidence.channel, intent)` 打标
3. 冲突消解（§9.2 同 channel 内）：
   - 优先 valid_to IS NULL（当前有效）
   - 次优先 confidence 高者
   - 仍冲突 → 双列 + conflict=true（交 LLM 归纳）
   - 一期实现于 graph evidence（facts 有 valid_to/confidence）；chunk 冲突（同一内容不同 chunk）按相似度取高
4. `conflict` 字段已有（§9.1），一期首次使用

---

## Phase D4 — 测试 + 评估 + 收尾

### Task 6 — `test_capability_query.py` + `test_planning.py` 扩展

**文件**：`apps/earp-server/tests/test_capability_query.py`（新建）+ `tests/test_planning.py`（扩展）

| 用例 | 断言 |
|---|---|
| resolve_with_query（entities 命中） | 候选含 matched_entity_ids（非空） |
| resolve_with_query（空 entities） | 返回 [] |
| execute_capability_query（COUNT equipment） | rows + aggregate.count 正确、权限过滤生效 |
| execute_capability_query（关系计数 alarm→equipment） | facts join 聚合正确 |
| execute_capability_query（无权限 DD） | 空结果 |
| plan_aggregation 升级（有候选+执行成功） | evidence 含 capability 通道、trace executed=true、无「通道未就绪」 |
| plan_aggregation（执行失败/无候选） | 回落 plan_fact + reason |
| 角色层（FACT evidence 主/佐） | chunk primary、profile/graph auxiliary |
| 角色层（RELATION） | graph primary |
| 角色层冲突消解 | valid_to 非空 vs 空 → 空者保留；confidence 高者保留 |

### Task 7 — chat 接入测试 + verify 更新

**文件**：`tests/test_chat.py`（扩展）+ `scripts/verify_planning.py`（更新）

- test_chat：软路由路径走 planner——citations 含 entity/graph/capability 徽标；AGGREGATION 查询走 plan_aggregation（capability evidence）
- verify_planning：plan_aggregation 执行分布变化（原 2 条通道未就绪 → 真实聚合）；报告 capability evidence 数

### Task 8 — OpenAPI 基线 + import-linter + 全量回归

- OpenAPI 基线同步（chat 响应无变化？plan-debug 无变化；如 capability 引用结构变化则同步）
- import-linter：3 条新 ignore 有效（Task 4）
- 全量 pytest 回归（155 + 新增）

### Task 9 — session-record 更新 + commit

- Phase D 状态 → 已完成；D2 边界解除、chat 接 planner、角色层落地；下一步 P3 rerank / tech-debt 治理

---

## 依赖关系

```
Task 1（resolve_with_query）→ Task 2（执行器）→ Task 3（plan_aggregation 升级）
Task 3 → Task 4（chat 接入，依赖 PlanResult 完整）
Task 3 → Task 5（角色层，叠加在 evidence 组装上）
Task 1-5 → Task 6/7（测试）→ Task 8（收尾）→ Task 9（文档 + commit）
```

**建议执行序**：`1 → 2 → 3 → (4, 5 并行) → (6, 7 并行) → 8 → 9`

## 验收标准

1. plan_aggregation 真实聚合（AGGREGATION 查询 → capability evidence，不再「通道未就绪」回落）
2. chat 软路由路径走 planner（citations 含 entity/graph/capability 徽标），引用命中率不降（verify_chat ≥80%）
3. resolve_with_query 返回 matched_entity_ids（§6.5 缺陷闭合）
4. 角色层：evidence 主/佐标记正确（§8.2 表）、冲突消解规则生效（§9.2）
5. 全量 pytest 回归绿（155 + 新增）+ import-linter（3 条 ignore）+ OpenAPI 基线
6. 无回归：kb_scope 限定路径、/plan M2 收窄路径（resolve_with_entities 保留）

## 风险提示

1. **执行器数据源局限**：ontology facts 聚合只覆盖「实体/关系计数」类 AGGREGATION（alarm 次数、设备数量等）；数值聚合（SUM 温度、AVG 时长）需要属性值——facts/entities 无数值属性支持时执行器返回 None 回落（不假造）。范围外聚合留 Phase F（capability 绑定业务数据源）
2. **chat 行为变化风险**：软路由路径从双通道换 planner——P1 verify_chat 引用命中率必须复测（≥80% 验收线）；若下降需回退策略（chat 接 planner 增加开关配置）
3. **import-linter 新增 ignore**：conversation → ontology.* 4 条（P2 已有 1 条）——架构债累积，Phase F 统一评估检索编排公共层
4. **角色层冲突消解范围**：仅 graph（facts 有 valid_to/confidence）与 chunk（相似度）实现；capability 恒 primary 无冲突——§9.2 完整消解留 Evaluation 数据支撑
5. **resolve_with_query 的 lookup 成本**：matched_entity_ids 需 lookup_entities（每个 mention 一次查询）——候选解析在低延迟预算内（plan_aggregation ≤600ms），大实体表时注意（现状 < 万级可接受）

## 人工测试指南（方案，实施后补全）

> 前置：`make migrate` + `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434 make api`。Seed：`scripts/verify_planning.py`（verify-planning 租户含 capability + facts）。

### 场景 1：AGGREGATION 真实聚合（D2 边界解除）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"华东一厂有多少台设备"}'
#   期望：select_plan=plan_aggregation、trace CAPABILITY_QUERY executed=true、evidence 含 channel=capability（rows+aggregate）
```

### 场景 2：chat 走 planner（实体 + 关系）

```bash
curl -N -X POST localhost:8000/chat_apps/$APP_ID/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 由哪家供应商制造"}'
#   期望：done 事件 citations 含 graph 徽标（plan_relation 语义）；无 kb_scope 时走 planner
```

### 场景 3：角色层调试

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 的维护记录"}'
#   期望：evidence 带 role 字段（primary/auxiliary）；graph 冲突消解生效（无旧事实）
```

---
**规划定稿，确认后按执行序开工。**
