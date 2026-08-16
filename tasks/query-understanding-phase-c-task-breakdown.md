# 任务清单 — Phase C: 最小固定策略 Planner（3 策略）

**状态：决策已定（D2/D3 方案 A），待开工**
**依据**：`arch/design/query-understanding-query-plan-design-v0.3.md`（§10 Execution Trace / §11 固定策略 / §12 典型 Plan / §16 Phase C / §17 Plan 层门槛）
**关联**：session-record「下一步：Phase C（最小固定策略 Planner）——§17 gating 已过（Phase B 机制层 100% / dev 真模型 95-100%）」
**日期**：2026-08-16

## 目标

在 Phase B（QU 理解层）之上实现**最小固定策略 Planner**：
- `select_plan` 规则映射表（§11.2，10 类 intent 全覆盖，QP-11）
- 3 个策略函数：`plan_fact` / `plan_relation` / `plan_aggregation`（§11.1）+ 2 预留签名
- `PlanResult`（evidence + citations + trace，§10/§11.1）+ Execution Trace 观测
- debug 端点扩展为完整可解释链（§15：QU → select_plan → 策略 → trace → evidence）
- Plan 层评估门槛（§17：策略命中率 ≥95%）

**范围边界**（本任务书**不含**）：
- `resolve_with_query()` 新签名 → **Phase D1**（plan_aggregation 一期用现有 `resolve_with_entities`）
- **capability query 执行器**（连接 adapter 执行链）→ **Phase D1**（现状：`connector.execute` 仅 `demo.echo`，query adapter 执行体系未建成——plan_aggregation 一期只做候选解析 + 无候选回落 plan_fact，trace 标注「capability 通道未就绪」）
- 角色层 Evidence 组装（§9.2 主/佐证定权）→ **Phase D3**（一期 evidence 为 recall 层通道直接映射，不做冲突消解）
- ABox 反向邻接 → ✅ 已补（G1 backward，2026-08-15）
- Plan 持久化 → 一期不落库（QP-12/§11.4 预留语义）
- chat_service 接入 → 一期 PlanResult 独立（debug 端点验证），chat 保持现状（Phase D 接 answer，避免 conversation→ontology→knowledge 传递 import 新链）

## 既定决策（讨论已对齐，开工前置）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | 模块落点 | 新建 `src/earp_server/ontology/planning.py`（与 understanding.py 同域）。策略函数是 ontology 检索能力的编排层；**不 import conversation**（chat_service → ontology.search 已有一条 ignore，反向 import 会引入循环/新传递链）——plan_fact 独立编排 route_query/knowledge_search/search_chunks（复用 P2 模式，不抽 chat_service 逻辑） |
| D2 | plan_aggregation 一期范围 | **候选解析 + 回落**：`resolve_with_entities` 反查候选 → 无候选/候选无 query type → 显式回落 `plan_fact`（§11.2「无 capability → plan_fact」）；capability 执行链（Phase D1）落地前 trace 标注「capability 通道未就绪」，不 mock 假执行 |
| D3 | chat 接入时机 | 一期不接：PlanResult 通过 debug 端点 + 评估验证；chat_service 保持现状（P1 双通道）。Phase D 接 answer 时按 P2 先例评估 import-linter（chat_service → ontology.planning → knowledge.* 传递链需 ignore） |
| D4 | Plan 不落库 | PlanResult 是内存中间产物（QP-12），trace 仅 debug/评估展示；不建表、无 migration |
| D5 | Evidence 一期形态 | §9.1 schema 冻结落地，但**只做 recall 层通道映射**（chunk/graph/profile 直接转换，confidence/source_ref 映射既有字段）；冲突消解/主佐证定权（§9.2）Phase D3 |
| D6 | 策略函数参数 | `QueryContext` dataclass（§11.1）：tenant_id/role_id/engine/settings/context；显式注入，无隐式全局 |
| D7 | 评估集 | Plan 层门槛（§17：策略命中率 ≥95% / 非法调用 0 / 越权 0 / Command 0）并入 `understanding_eval.md` 扩展列（期望策略）或独立 `plan_eval.md`——机制层 + dev verify_planning.py |

## 现状（已核实）

- `ontology/understanding.py`（Phase B 交付）：`understand()` → RuleResult、`upgrade_with_llm()`、`build_structured_query()`、`derive_needs()`、schema 模型全落地；机制层 100% / dev 95-100% 通过 §17
- `ontology/search.py`：`knowledge_search`（三层 RRF）、`resolve_with_entities`（intent → 实体 → capability_entity_map 反查）
- `ontology/abox_service.py`：`lookup_entities`（双向子串）、`graph_query`（forward/backward）、`get_entity_profile`/`compile_profile`
- `knowledge/routing.py::route_query`：软路由（candidate_dds/candidate_kbs/fallback_used）
- `knowledge/search_service.py::search_chunks`：mode/hybrid + metadata_filters + accessible_roles + rerank
- `conversation/chat_service.py::_retrieve`：P2 三层接入模式（软路由 → knowledge_search；candidate_dds 空 → 全租户 chunk 兜底）——plan_fact 编排模式的参照
- **capability 执行链未建成**：`connector.execute` 仅 demo.echo adapter；`business_capabilities`（type=query/command + input_schema/output_schema）注册层已有（registry.list_for_planning / discover / capability_entity_map 反查）
- import-linter：ontology 不在 independence 域 → 自由 import knowledge/connector；conversation→ontology.search 已有 ignore（P2）
- 基线：141 tests 全绿 + import-linter + OpenAPI 基线同步

---

## Phase C1 — 策略层核心

### Task 1 — PlanResult / TraceRecord / Evidence / QueryContext schema（前置）

**文件**：`src/earp_server/ontology/planning.py`（新建）

**改动点**：
1. `EvidenceChannel` / `Evidence`（§9.1 冻结，channel 多态 payload）：
   ```python
   class EvidenceChannel(str, Enum): GRAPH="graph"; CHUNK="chunk"; CAPABILITY="capability"; PROFILE="profile"
   class Evidence(BaseModel):
       evidence_id: str; channel: EvidenceChannel; content: str; source: str; source_ref: str
       confidence: float = Field(ge=0, le=1); valid_from: datetime|None; valid_to: datetime|None
       payload: dict = Field(default_factory=dict)  # chunk→{chunk_id,similarity,kb_id,metadata} 等
       conflict: bool = False  # §9.2 一期恒 False
   ```
2. `TraceRecord`（§10）：
   ```python
   class TraceRecord(BaseModel):
       step_id: str; type: str  # RESOLVE_ENTITY/GRAPH_QUERY/VECTOR_SEARCH/KEYWORD_SEARCH/METADATA_FILTER/DD_ROUTING/KB_ROUTING/CAPABILITY_QUERY/FUSION_RERANK/ANSWER
       input: dict; output: dict|None; latency_ms: float
   ```
3. `PlanResult`（§11.1）：`evidence: list[Evidence]` + `citations: list[dict]`（chat-agent-design citations 结构）+ `trace: list[TraceRecord]` + `plan_name: str` + `fallback_reason: str|None`
4. `QueryContext` dataclass（D6）：engine/tenant_id/role_id/settings/context/top_k
5. `select_plan(query: StructuredQuery) -> Callable`（Task 2 实现映射，Task 1 定签名）

### Task 2 — `select_plan` 规则映射表（§11.2，10 类全覆盖 QP-11）

**文件**：`src/earp_server/ontology/planning.py`

**改动点**：
```python
# intent → 策略（规则映射表，非 LLM 自由规划）
# FACT → plan_fact
# RELATION / ATTRIBUTE / LIST → plan_relation（解析失败回落 plan_fact）
# MULTI_HOP → plan_relation(max_hops=2)
# AGGREGATION / COMPARISON / TREND → plan_aggregation（无 capability → plan_fact）
# CAUSAL / MIXED → plan_fact（显式回落，trace 标注「intent 未绑定策略」，QP-14 不静默）
```
- 10 类 intent 必须有落点（QP-11）；返回 (plan_fn, plan_name, fallback_reason)
- 一期实现 plan_fact/plan_relation/plan_aggregation 三个签名；`plan_multi_hop`/`plan_causal` 为预留签名（§11.1，Phase C 后按疼点启用，不实现）

### Task 3 — `plan_fact` 策略函数（完整实现）

**文件**：`src/earp_server/ontology/planning.py`

**改动点**（编排现有能力，§12 例 1）：
1. `route_query(query)` → candidate_dds/candidate_kbs
2. candidate_dds 非空 → `knowledge_search`（三层，data_domain_ids=candidate_dds, knowledge_base_ids=candidate_kbs, metadata_filters=query.constraints, query_text, mode, threshold）
3. candidate_dds 空 → `search_chunks` 全租户兜底（P2 D4 语义）
4. trace 记录：DD_ROUTING → KB_ROUTING → METADATA_FILTER → VECTOR/KEYWORD → FUSION_RERANK
5. evidence 组装（D5）：chunk item → Evidence(channel=chunk, payload={chunk_id,similarity,kb_id,metadata}, source=doc_title, source_ref=document_id)；profile/graph item 同映射
6. citations 三源转换（复用 chat_service._retrieve 模式，独立实现）
7. 延迟/成本校验（§11.4）：top_k ≤ 50、候选 DD/KB ≤ 3（超限截断 + trace 标注）

### Task 4 — `plan_relation` 策略函数（完整实现）

**文件**：`src/earp_server/ontology/planning.py`

**改动点**（§12 例 2）：
1. `lookup_entities(query)`（用 StructuredQuery.entities 的 mention/semantic_type，非重新 tokenize）→ 实体命中
2. `graph_query(entity_id, max_hops=1)`（forward；MULTI_HOP → max_hops=2）→ 关系行
3. graph 无事实 → `search_chunks` 补证（chunk 佐证，§14 fallback）+ trace 标注「graph 无事实 → RAG 补证」
4. 无实体命中 → 显式回落 `plan_fact`（§11.2「解析失败回落 plan_fact」）
5. evidence：graph 行 → Evidence(channel=graph, source_ref=fact_id, payload={relation_type_id, source_entity_id, target_entity_id, depth})；chunk 补证同 Task 3
6. trace：RESOLVE_ENTITY → GRAPH_QUERY → [VECTOR_SEARCH 补证]

### Task 5 — `plan_aggregation` 策略函数（候选解析 + 回落，D2）

**文件**：`src/earp_server/ontology/planning.py`

**改动点**（§12 例 4）：
1. `resolve_with_entities(query.intent 或 query 文本)`（Phase D1 换 resolve_with_query）→ 候选 capability
2. 候选存在且 type=query → trace 标注 `CAPABILITY_QUERY`（input=StructuredQuery.operation + entities）+ **「capability 通道未就绪」**（D2：执行器未建成，不 mock）；PlanResult.evidence 不含 capability 行
3. 无候选 / 候选无 query type → 显式回落 `plan_fact`（§11.2）+ fallback_reason
4. 预算：≤600ms（§11.3，含候选解析；执行链 Phase D1 后重标）

---

## Phase C2 — 端点 + 校验

### Task 6 — debug 端点扩展为完整可解释链（§15）

**文件**：`src/earp_server/ontology/routes.py` + `src/earp_server/ontology/planning.py`

**改动点**：
- 新端点 `POST /v1/ontology/understanding/plan-debug`（或扩展 debug 端点加 `run_plan=true` 参数）：
  ```json
  {
    "structured_query": {...},
    "rule_fields": {...},
    "derive_needs": {...},
    "select_plan": {"plan_name": "plan_fact", "fallback_reason": null},
    "plan_result": {"evidence": [...], "citations": [...], "trace": [...], "latency_ms": ...}
  }
  ```
- 前端 understanding-debug.html 增「运行策略」按钮 → 展示 select_plan + trace 步进 + evidence 表（F1 叠加扩展）
- 读端点、无写库、无迁移（D4）

### Task 7 — 校验与成本约束（§11.4）

**文件**：`src/earp_server/ontology/planning.py`

**改动点**：
- Schema：策略函数输入用 §6.2 Pydantic 约束（StructuredQuery 已冻结）
- Scope：复用 route_query DD 权限过滤 + search_chunks accessible_roles + graph 源实体限域（P2 既有语义）
- Safety：只调用注册的只读函数（lookup/graph/search/routing），无 Command/SQL/Cypher 入口（QP-07）
- Cost：max_hops ≤ 3、candidate DD/KB = 3、top_k ≤ 50（Task 3/4 已含，此处统一断言）
- 租户：每步显式 tenant_id（RLS 会话内执行）

---

## Phase C3 — 测试 + 评估

### Task 8 — `test_planning.py` 单元测试

**文件**：`apps/earp-server/tests/test_planning.py`（新建）

| 用例 | 断言 |
|---|---|
| select_plan 10 类全覆盖（QP-11） | 每类 intent → 非 None 策略 + plan_name 正确 |
| select_plan 回落标注 | CAUSAL/MIXED → plan_fact + fallback_reason 非空（QP-14 不静默） |
| plan_fact（实体命中场景） | evidence 含 profile/graph/chunk 通道、citations 三源、trace 步进完整 |
| plan_fact（纯文档 + constraints） | metadata_filters 透传、trace 含 METADATA_FILTER |
| plan_relation（实体+关系） | graph evidence + trace RESOLVE_ENTITY→GRAPH_QUERY |
| plan_relation（无实体） | 回落 plan_fact + fallback_reason |
| plan_relation（graph 无事实） | chunk 补证 + trace 标注 |
| plan_aggregation（有候选 query capability） | trace CAPABILITY_QUERY + 「通道未就绪」标注，无假执行 |
| plan_aggregation（无候选） | 回落 plan_fact |
| 成本约束 | top_k > 50 截断 / max_hops > 3 截断 |
| 非法调用 = 0 / Command = 0 | trace 中无 Command/任意代码步（扫描断言） |

### Task 9 — Plan 层评估（§17）

**文件**：`tests/fixtures/understanding_eval.md`（扩展 intent 列之后加「期望策略」列）或独立 `plan_eval.md` + `test_planning_eval.py`

- N ≥ 100（复用 understanding_eval 111 条，标注期望策略：plan_fact / plan_relation / plan_aggregation / plan_fact(回落)）
- 门槛：策略命中率 ≥ **95%**（3 策略 + 回落均视为命中「回落」策略）；非法调用 = 0、越权访问 = 0、Command = 0
- gating：Plan 层门槛未达 → 不扩展策略（§17）

### Task 10 — `scripts/verify_planning.py`（dev 真模型端到端）

**文件**：`scripts/verify_planning.py`（新建，仿 verify_understanding.py）

- 全链路：understand（+LLM 升级）→ select_plan → 策略函数（真 DB）→ PlanResult
- 报告：策略命中率、trace 完整性、evidence 通道分布、p95 延迟（§11.3：plan_fact ≤800ms / plan_relation ≤500ms / plan_aggregation ≤600ms）
- dev 真 LLM（qwen2.5）+ verify-understanding 租户 seed 复用

---

## Phase C4 — 收尾

### Task 11 — OpenAPI 基线 + import-linter + 全量回归

**文件**：`apps/earp-server/openapi.yaml` + tests

- OpenAPI 基线同步（plan-debug 端点）
- import-linter 保持（planning.py 在 ontology 域 import knowledge/connector 无新增 ignore；chat 不接入故无传递链）
- 全量 pytest 回归（141 + 新增保持绿）

### Task 12 — session-record 更新 + commit

- Phase C 状态 → 已完成；记录评估结果；下一步 Phase D（D1 resolve_with_query + capability 执行链 / D3 角色层）

---

## 依赖关系

```
Task 1（schema + 签名）
  → Task 2（select_plan 映射，依赖签名）
      → Task 3/4/5（三策略，并行）
Task 3-5 → Task 7（统一校验）
Task 1-5 → Task 6（plan-debug 端点，依赖全链路）→ 前端叠加
Task 3-5 → Task 8（单元测试）
Task 2-7 → Task 9（Plan 层评估）
Task 9 → Task 10（verify 脚本）
Task 6/8/9 → Task 11（收尾）→ Task 12（文档 + commit）
```

**建议执行序**：`1 → 2 → (3, 4, 5 并行) → (6, 7) → (8, 9 并行) → 10 → 11 → 12`

## 验收标准（§17 Plan 层数字门槛）

1. 策略命中率 ≥ **95%**（一期 3 策略；7 类回落视为命中「回落」策略）
2. 非法调用 = 0、越权访问 = 0、Command = 0
3. 全量 pytest 回归绿（141 + 新增）；import-linter + OpenAPI 基线同步
4. p95 延迟预算：plan_fact ≤ 800ms / plan_relation ≤ 500ms / plan_aggregation ≤ 600ms（§11.3，dev 实测报告）
5. `select_plan` 10 类 intent 全覆盖（QP-11，无未定义落点）
6. plan_aggregation 不假执行（无 capability 执行器 → 回落 + trace 标注，不 mock 结果）

## 风险提示

1. **capability 执行链缺失（D2 边界）**：plan_aggregation 一期只能解析候选 + 回落——用户若期待真聚合结果会落空；设计上「AGGREGATION 唯一消费者是 capability query，通道未就绪无消费者」（v0.3 §16 时序理由）成立，Phase D1 补执行器
2. **plan_fact 与 chat_service._retrieve 重复编排**：独立实现（D1 决策，避免循环 import）→ 两处相似逻辑；记 tech-debt「Phase D 接 answer 时统一检索编排」（chat 接入时评估抽取公共层）
3. **import-linter 传递风险（Phase D 预留）**：chat_service → ontology.planning → knowledge.routing/search_service 构成传递违反（chat/knowledge 均 independence 域）——本任务书不触碰（chat 不接入）；Phase D 按 P2 先例加 ignore
4. **select_plan 对非可靠子集 intent 的映射**：LLM 升级可能产出 CAUSAL/COMPARISON 等——映射表必须显式回落（QP-14），不得静默当 FACT；评估集标注回落类条目标注「回落」策略
5. **Evidence 一期不做冲突消解（D5）**：多源同 channel 冲突时一期并列（conflict 恒 False），§9.2 消解 Phase D3——评估不考 conflict
6. **延迟预算真实性**：plan_relation 的 graph 遍历 + chunk 补证在无索引大图下可能超预算——dev 实测后按数据微调（§11.3 注明「数值为建议值，实测标定」）

## 人工测试指南（方案，实施后补全）

> 前置：`make migrate` + `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434 make api`（API:8000）。
> Seed：跑一次 `scripts/verify_understanding.py`（verify-understanding 租户实体/事实/评估集）。

```bash
# token（tenant=verify-understanding, role=r-any）
TOKEN=$(cd apps/earp-server && .venv/bin/python -c "
import jwt; print(jwt.encode({'sub':'u1','tenant_id':'verify-understanding','role_id':'r-any','exp':9999999999},'earp-dev-secret-change-in-production',algorithm='HS256'))")
```

### 场景 1：plan_fact（文档事实）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"2024 年财务部的报销制度是什么"}'
#   期望：select_plan=plan_fact、trace=[DD_ROUTING→KB_ROUTING→METADATA_FILTER→VECTOR/KEYWORD→FUSION_RERANK]、evidence 全 chunk
```

### 场景 2：plan_relation（实体+关系）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 由哪家供应商制造"}'
#   期望：select_plan=plan_relation、trace=[RESOLVE_ENTITY→GRAPH_QUERY]、evidence 含 graph（manufactured_by→上海某精机）
```

### 场景 3：plan_aggregation（无 capability 候选 → 回落）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"华东一厂有多少台设备"}'
#   期望：select_plan=plan_aggregation、trace 标注「capability 通道未就绪」或回落 plan_fact + fallback_reason
```

### 场景 4：前端完整调试链

```bash
cd apps/earp-admin && python3 -m http.server 8080
```
- 知识中心 → 「QU 调试」页 → 输入查询 → 点「运行策略」→ 期望：select_plan 卡 + trace 步进 + evidence 表

---
**规划定稿，确认后按执行序开工。**
