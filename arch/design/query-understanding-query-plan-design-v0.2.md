# EARP Query Understanding & Knowledge Query Plan 设计（v0.2 修订版）

**文档编号**：L2-02-REASONING-QUERY
**版本**：v0.2（在 v0.1 基础上修订）
**状态**：Draft / 项目组讨论版
**日期**：2026-08-12
**定位**：L2 Reasoning 子设计
**上游**：Runtime / Planner / Ontology / Knowledge Center / Capability Center
**下游**：Knowledge Retrieval Engine、RAG、Ontology Search、Capability Query、Answer Generation

---

## 0. v0.1 → v0.2 修订说明（评审结论落地）

v0.1 评审确认：方向与原则正确，但存在三类系统性问题，本版逐项修正：

| # | v0.1 问题 | v0.2 修正 |
|:-:|---|---|
| 1 | 与既有 Planner 边界未厘清（有重造风险） | §4 重写为「对齐矩阵」，明确复用 `planner/` + `ontology/search.py::resolve_with_entities()`，不新建并行 intent 分类 |
| 2 | 示例关系类型与冻结 TBox 冲突（`has_component`/`contains` 不存在、方向写反） | §5/§10 示例全部对齐 12 类关系；同时暴露 TBox 真实缺口（部件级供应关系缺失），列入 §20 开放问题 |
| 3 | 与 roadmap 脱节（P1 已完成 / P2 进行中，却当绿地规划） | §1 重写现状；§16 分阶段对齐 roadmap：本文档真正的新增量只有 Query Understanding + 固定策略层 |
| 4 | 「Retrieval DAG」回避与 Orchestrator 关系 | 一期砍掉通用 DAG DSL，改为 5 条固定策略函数（§11）；DAG 引擎推到 Phase 4+ 再评估 |
| 5 | 硬选通道 vs 软融合两套哲学打架 | 统一为「通道优先级而非通道排他」，始终多通道 RRF 融合（§9，QP-05 改写） |
| 6 | 会话上下文完全缺失 | §5 新增 `context` 维度，多轮指代消解纳入 Query Understanding 输入 |
| 7 | Retrieval Need 自相矛盾（§2/§8 已用、§21 又列为开放问题） | 采纳 Retrieval Need 为正式中间层，删除原开放问题 1 |
| 8 | ANSWER/Evidence 与 chat_service 重叠 | 明确复用 P1 已建 `chat_service`（答案生成 + citations），不建平行答案生成器 |
| 9 | `filecite` 未渲染残留 + 缺交叉引用 | 全部清理；交叉引用带版本号（见 §19） |
| 10 | 评估集要新建 `query_plan_eval` | 并入现有 `routing_eval.md` + `verify_*` 体系（§17） |
| 11 | Plan 模型缺租户隔离 | tenant_id + RLS 语义写入 §7/§12，QP-08 补充 |
| 12 | Cost 校验数字拍脑袋 | 与 enterprise-retrieval 已定默认对齐，其余标注「建议值待实验」 |

---

# 1. 背景与现状（对齐当前 roadmap）

## 1.1 已建成的能力（勿重复建设）

截至 2026-08-12，以下链路已实现并有测试覆盖：

```text
用户 Query
   ↓
软路由 route_query()（DD 关键词 ∪ 向量 → 候选 DD → KB 摘要向量 → 候选 KB，权限过滤）
   ↓
三层融合检索 knowledge_search()（实体 Profile + 图谱多跳 + vector/keyword chunk，RRF 融合）
   ↓
chat_service（答案生成 + 引用溯源 citations + SSE 流式）
```

- **P1 问答链路已完成**：`conversation/chat_service.py` —— 软路由 + 检索 + LLM 生成 + citations 落库 + 多轮配对。
- **P2 ontology 接入软路由进行中**：`/knowledge/search` 无 scope 路径与 chat 软路由路径正在接入 `knowledge_search()` 三层检索，让 profile/graph 层参与 RRF 融合。
- **P3 rerank 精排**：下一步（bge-reranker，对应本文 FUSION_RERANK 节点的实现）。
- **既有 Planner**：`planner/` 域（`business_dictionary.py` 规则 intent、`task_planner.py` LLM+规则、`validation.py`）；`ontology/search.py::resolve_with_entities()` 已实现「Intent 实体识别 → capability_entity_map 反查 → 候选收窄」。

## 1.2 真正缺的那一层

现在不缺 Retriever，缺的是：

> **如何先理解问题，再决定按什么策略编排这些已有检索能力。**

即：把「已经散落的 route_query / knowledge_search / graph_query / search_chunks / capability resolution」用一个**理解层 + 固定策略层**串起来，而不是重新建一套检索系统。

---

# 2. 核心设计结论

## 2.1 一句话结论

> **Query Understanding 负责回答「用户要什么、回答它需要什么知识」；Knowledge Query Plan 负责回答「为获得这些知识，按什么顺序调用哪些已有检索能力」。**

两者必须分离。

```text
User Query (+ Conversation Context)
    ↓
Query Understanding
    ↓
Structured Query + Retrieval Need
    ↓
Knowledge Query Planner（一期：固定策略）
    ↓
Knowledge Query Plan（→ 直接编排现有函数）
    ↓
Ontology / RAG / Capability（已有）
    ↓
Evidence Set
    ↓
Answer（复用 chat_service）
```

## 2.2 不做成 Intent 分类器

企业查询同时含实体、关系、属性、时间、结构化约束、聚合、排序、比较、因果、证据要求。Query Understanding 的输出是 **Structured Query Representation**，Intent 只是其中一个字段。

---

# 3. 两个概念的职责边界

## 3.1 Query Understanding

**负责**：识别业务对象/实体提及/关系/问题类型/时间范围/结构化约束/操作意图/回答要求；**并接收会话上下文做指代消解**。

**不负责**：决定走 Graph 还是 Vector、调用哪个 Capability、定 RRF 参数、生成 SQL/Cypher、直接访问数据、执行查询。

## 3.2 Knowledge Query Plan

**负责**：根据 Structured Query 选择检索能力、确定顺序与依赖、定 DD/KB 范围、定 Graph 遍历方向、定融合策略、组装 Evidence Set。

**不负责**：自己理解业务语义、定义实体类型、创建 Capability、实现 Connector、执行 Command。

---

# 4. 与现有 Planner 的关系（v0.2 重写：对齐矩阵）

Knowledge Query Plan 是 Planner **知识检索子链路**的细化，不是新的并行规划器。逐一映射：

| 本文档概念 | 现有实现（已建） | 关系 |
|---|---|---|
| Query Understanding 实体识别 | `ontology/search.py::_entity_hits` + `resolve_with_entities()` | 复用/增强，不重写 |
| `RESOLVE_ENTITY` 节点 | `abox_service.lookup_entities()` | 直接映射 |
| `GRAPH_QUERY` 节点 | `abox_service.graph_query()` | 直接映射 |
| `VECTOR/KEYWORD/METADATA` | `search_chunks()`（已含 hybrid + metadata_filters） | 直接映射 |
| DD/KB 软路由 | `knowledge/routing.py::route_query()` | 直接映射 |
| `FUSION_RERANK` | `ontology/search.py::_rrf_merge` + P3 reranker | 直接映射 |
| `ANSWER` | `conversation/chat_service.py`（P1 已建） | 复用，不重建 |
| 问题类型 intent | 现有 planner intent 是 capability 导向（"query alarms"） | **新增一维，与 capability intent 并存，不替换** |

**关键决策**：本文档的问题类型 intent（FACT/RELATION/AGGREGATION…）是**知识检索维度**的标注，与现有 planner 的 capability intent（query.alarms 等）是两个正交维度——前者描述「问题性质」，后者描述「要调用的业务能力」。两者在 `resolve_with_entities()` 处汇合：问题类型 → 实体类型 → capability 反查。

---

# 5. Query Understanding 设计

## 5.1 总体结构（6 维度 + 会话上下文）

```text
QueryUnderstanding
├── context            # 会话上下文（指代消解）
├── entities
├── relations
├── intent
├── constraints       # 结构化约束 + 时间（合并，避免碎字段）
├── operation         # 聚合/排序/比较
└── answer_requirement
```

## 5.2 context：会话上下文（v0.2 新增）

多轮问答中，指代必须回填到上一轮已解析实体：

```json
{
  "context": {
    "conversation_id": "conv-xxx",
    "last_entities": ["ent-cnc01"],
    "last_intent": "RELATION",
    "references": [{"mention": "它", "resolved_entity_id": "ent-cnc01"}]
  }
}
```

与 ontology 设计 §7.3「实体作为会话上下文持久化（Session Context 带 entity_refs）」对齐。理解阶段只做提及 → 上文实体的映射，绝对时间解析依赖 Runtime Context 当前时间，不让 LLM 猜日期。

## 5.3 entities / relations（示例对齐冻结 TBox）

```json
{
  "entities": [
    {"mention": "CNC-01", "semantic_type": "equipment"},
    {"mention": "供应商", "semantic_type": "supplier", "role": "target"}
  ],
  "relations": [
    {"subject": "CNC-01", "relation": "manufactured_by", "object_type": "supplier"}
  ]
}
```

**Entity Mention ≠ Entity Resolution**：理解只标注「CNC-01 是设备」，具体 `entity_id` 由 `lookup_entities()` 在后续解析。

## 5.4 intent：问题类型（第一版 10 类）

`FACT / ATTRIBUTE / RELATION / MULTI_HOP / LIST / AGGREGATION / COMPARISON / TREND / CAUSAL / MIXED`。

Intent 只描述问题性质，**不直接选 Retriever**。

## 5.5 constraints：结构化约束 + 时间

```json
{
  "constraints": {
    "department": "财务部",
    "year": 2024,
    "doc_type": "制度",
    "time": {"kind": "relative", "expression": "yesterday", "resolved": null}
  }
}
```

结构化约束直接进现有 `search_chunks` 的 `metadata_filters`；`time.resolved` 由运行时回填。

## 5.6 operation / answer_requirement（沿用 v0.1，略）

`operation` 描述 aggregate/group_by/order_by/limit；`answer_requirement` 描述 answer_type / evidence_required / source_preference / citation_required。

---

# 6. Query Understanding 生成策略（规则优先，LLM 升级）

每类查询都过 LLM 会拖慢全链路（连「报销制度是什么」也要先 LLM）。与 enterprise-retrieval §3「低置信度升级 LLM 路由」同构：

```text
Query
  ↓
规则层：正则提取时间/数字 + 词典匹配实体名 + 关键词匹配 intent
  ↓
置信度评估（覆盖是否完整 / 歧义是否可消）
  ↓
足够 → 直接产出 Structured Query（零 LLM）
不足 → LLM 补充（Schema-constrained JSON，禁 SQL/Cypher/API 选择）
```

规则层可用素材：`business_dictionary` 词典、ontology 实体名索引、`match_data_domains` 关键词表。

---

# 7. Knowledge Query Plan 设计

## 7.1 核心原则

> **一个只读、受约束、可验证、可观测的检索编排层。**

一期（Phase 1-3）**不建通用 DAG 引擎**，只做固定策略函数（§11）。DAG DSL 与通用执行器留到 Phase 4+ 评估——避免与 orchestrator 的 `StepRunner/MultiStepExecutor` 并行实现两套执行引擎。

## 7.2 Plan 节点类型（8 类，全部映射现有函数）

| Node Type | 现有实现 |
|---|---|
| `RESOLVE_ENTITY` | `abox_service.lookup_entities()` |
| `GRAPH_QUERY` | `abox_service.graph_query()` |
| `VECTOR_SEARCH` / `KEYWORD_SEARCH` / `METADATA_FILTER` | `search_chunks()`（mode=vector/hybrid + metadata_filters） |
| `DD_ROUTING` / `KB_ROUTING` | `route_query()` |
| `CAPABILITY_QUERY` | Query Capability（经 `resolve_with_entities()` 反查） |
| `FUSION_RERANK` | `_rrf_merge` + P3 reranker |
| `ANSWER` | `chat_service` |

一期不支持：Command、任意 SQL/Cypher/代码、Workflow 子流程。

## 7.3 租户隔离（v0.2 补充）

Plan 的每一步执行都必须显式携带 `tenant_id` 并在 RLS 会话内运行（`tenant_session()` / `SET LOCAL earp.tenant_id`）。Plan 校验（§12）含租户归属校验。

---

# 8. Retrieval Need（v0.2 定为正式中间层）

在 Understanding 与 Plan 之间引入轻量中间结果，让 Planner 不从自然语言直接猜工具：

```json
{
  "needs": {
    "entity_resolution": true,
    "relation_reasoning": true,
    "document_evidence": false,
    "structured_data": false,
    "metadata_filter": false,
    "aggregation": false,
    "real_time": false
  }
}
```

---

# 9. 通道选择原则（v0.2：软融合，非硬路由）

统一为**通道优先级而非通道排他**：Plan 决定各通道的权重与顺序，但可用通道始终参与 RRF 融合，避免「路由错 = 全盘皆空」。

| 问题类型 | 主通道（加权） | 辅助通道（参与融合） |
|---|---|---|
| FACT / ATTRIBUTE | Vector + Keyword + Metadata | Graph（若有实体命中） |
| RELATION / MULTI_HOP | Graph | RAG 补证 |
| AGGREGATION | Capability Query | Graph（范围解析） |
| CAUSAL | Graph + Capability + RAG 三者并重 | — |

**注意**：AGGREGATION 不要把大量业务数据塞进 LLM 统计——Capability 完成聚合，LLM 只归纳。

---

# 10. 典型 Query Plan 例子（示例已对齐 TBox）

## 例 1：报销制度（FACT）

```yaml
intent: FACT
constraints: {year: 2024, department: 财务部, doc_type: 差旅制度}
answer_requirement: {answer_type: summary, citation_required: true}
```

```
DD_ROUTING(finance_data) → KB_ROUTING(费用报销) → METADATA_FILTER
  → VECTOR+KEYWORD → FUSION_RERANK → ANSWER
```

## 例 2：设备供应商（RELATION）

> "CNC-01 是谁生产的？"

```yaml
intent: RELATION
entities: [CNC-01/equipment, supplier/target]
relations: [CNC-01 → manufactured_by → supplier]   # equipment→supplier，方向正确
```

```
RESOLVE_ENTITY(CNC-01) → GRAPH_QUERY(manufactured_by, max_hops=1) → ANSWER
（无图事实时 → VECTOR_SEARCH("CNC-01 供应商") 补证 → 融合）
```

## 例 3：多跳（MULTI_HOP）

> "CNC-01 所在产线的负责人是谁？"

```yaml
relations:
  - CNC-01 → belongs_to → production_line        # equipment→production_line ✓
  - production_line → responsible_for → employee # production_line→employee ✓（N:M 目标可含 department）
```

```
RESOLVE_ENTITY(CNC-01) → GRAPH_QUERY(max_hops=2) → ANSWER
```

## 例 4：聚合（AGGREGATION）

> "昨天华东一厂哪个 CNC 设备高温报警最多？"

```yaml
entities: [华东一厂/plant, CNC/equipment, 高温报警/alarm]
relations:
  - equipment → located_in → plant               # 方向修正：设备位于工厂
  - alarm → caused_by → equipment                 # ✓
intent: AGGREGATION
operation: {aggregate: COUNT, group_by: equipment, order_by: DESC, limit: 1}
```

```
RESOLVE_ENTITY(华东一厂) → GRAPH_QUERY(located_in 反向取设备) 
  → CAPABILITY_QUERY(query_equipment_alarm) → AGGREGATE → ANSWER
```

## 例 5：因果（CAUSAL）

> "为什么 CNC-01 最近故障增加？"

```
RESOLVE_ENTITY(CNC-01) ─┬─ GRAPH_QUERY（关系链：部件/供应商/维护人/报警类型）
                        └─ CAPABILITY_QUERY（最近故障统计）
                              ↓
                         RAG（维修记录/手册/质量报告）
                              ↓
                         FUSION_RERANK → ANSWER
```

结果逻辑：Capability 证实「故障确实增加」→ Graph 提供「关联对象/关系链」→ RAG 提供「解释材料」→ LLM 归纳。

---

# 11. 固定策略函数（一期，替代通用 DAG DSL）

一期实现 5 个策略函数，每个直接编排现有函数并返回 `(evidence, citations)`，不做 JSON DAG 解析：

```python
async def plan_fact(query, context, ...):        # → route_query + search_chunks + rrf
async def plan_relation(query, context, ...):    # → lookup_entities + graph_query (+ chunk 补证)
async def plan_multi_hop(query, context, ...):   # → graph_query(max_hops=2)
async def plan_aggregation(query, context, ...): # → resolve_with_entities + capability query
async def plan_causal(query, context, ...):      # → graph + capability + rag + 融合
```

`select_plan(understanding) -> plan_fn` 由 Retrieval Need 决定（规则映射表，非 LLM 自由规划）。

**通用 DAG DSL（v0.1 §11）与四类校验框架（v0.1 §12）降级为**：策略函数参数约束 + 单测断言。DAG 引擎留到 Phase 4+ 评估，若引入必须明确复用 orchestrator 的 `StepRunner`（加 read_only 约束、去 Saga/补偿），否则不建。

---

# 12. 校验（策略函数内约束，而非独立框架）

| 校验 | 一期落地方式 |
|---|---|
| Schema | 策略函数输入用 Pydantic 约束（Structured Query schema） |
| Scope（权限） | 复用 `route_query` 的 DD 权限过滤 + `search_chunks` 的 accessible_roles + graph 源实体限域（P2 已定语义） |
| Safety | 策略函数只允许调用注册的只读函数；无 Command / SQL / Cypher 入口 |
| Cost | 参数上限：graph max_hops ≤ 3、candidate DD/KB = 3（与 enterprise-retrieval 已定默认一致）、top_k ≤ 50、Capability 调用数有限制（建议值，待实验标定） |
| 租户 | 每步显式 `tenant_id`，RLS 会话内执行 |

---

# 13. 为什么不让 LLM 直接决定「用什么工具」

（沿用 v0.1，结论不变）LLM 擅长语义理解，不应直接拥有任意数据访问权；企业查询必须可审计、可解释、可重放；Capability 已是标准业务能力抽象，Planner 应规划 Capability 而非 API。

---

# 14. Failure / Fallback（沿用 v0.1，补租户语义）

- Entity Resolution 失败 → 显式名称/业务编码 → DD 限域语义搜索 → 仍失败走 RAG
- Graph 无事实 → RAG 补证
- RAG 低置信度 → Graph / Keyword / Metadata 补充
- 多源冲突 → Evidence 显式记录 `source / source_ref / confidence / valid_from / valid_to`（ontology facts 已具备这些字段）

所有 fallback 步骤同样在 tenant 会话内、权限过滤后执行。

---

# 15. Observability（沿用 routing/debug 思想）

调试视图分层展示：Query Understanding（实体/关系/intent/证据需求）→ Query Plan（策略名 + 每步结果）→ 每通道得分 + 引用。复用 `route_debug` 的「分层可解释调试」模式，不新建平行调试体系。

---

# 16. 分阶段实施（对齐 roadmap）

```
Phase 1   Query Understanding（规则优先 + LLM 低置信度升级）
          —— 产出 Structured Query + Retrieval Need，schema 冻结
Phase 2   固定策略 Planner（5 条策略函数，规则映射，无 DAG DSL）
Phase 3   策略接入已有能力（route_query / knowledge_search / graph_query /
          search_chunks / resolve_with_entities）—— 大部分在 P2 已完成
Phase 4   rerank 精排接入 FUSION_RERANK（= roadmap P3）
Phase 5   （远期）低置信度自适应规划 + 通用 DAG 评估——非一期依赖
```

**与 roadmap 的关系**：Phase 1-2 是本文档的净增量；Phase 3 = 当前 P2 的延伸；Phase 4 = P3。P1（chat）已是 ANSWER 节点的现成实现。

---

# 17. 评估集（并入现有体系，不新建平行）

在现有 `tests/fixtures/routing_eval.md` 基础上**扩展**三层，而非新建 `query_plan_eval`：

1. **Understanding 层**：query → expected intent/entities/relations/constraints（新增 fixture）
2. **Plan 层**：query → expected 策略名（5 类固定策略）
3. **Retrieval/Answer 层**：沿用 `routing_eval` + `verify_routing.py` / `verify_chat.py` 的跑分与引用命中口径

复用现有四层验证（CI 机制层 → 真实语义评估 → API → 前端）。

---

# 18. 关键设计原则（QP，修订版）

- **QP-01** Query Understanding 不选工具，只形成结构化查询语义。
- **QP-02** Knowledge Query Plan 不懂自然语言，只组织受控只读检索步骤。
- **QP-03** Ontology 是 Understanding 的语义基础，也是 Graph 检索的执行基础。
- **QP-04** RAG / Graph / Keyword / Metadata / Capability 是互补通道，不互相替代。
- **QP-05**（改）Plan 决定通道**优先级与顺序**，可用通道始终参与 RRF 融合——软融合，非硬路由。
- **QP-06** Query Plan 是只读检索编排，不是 Workflow，不与 orchestrator 并行建执行引擎。
- **QP-07** 一期不允许生成/执行任意 SQL/Cypher/代码。
- **QP-08**（补）所有 Plan 必须满足 Schema / Scope / Safety / Cost / **租户隔离** 约束后才能执行。
- **QP-09** 多源回答保留 evidence source / source_ref / confidence / validity。
- **QP-10** 先固定策略验证架构，再引入 LLM 自适应规划。

---

# 19. 与现有文档衔接（带版本号）

```text
Runtime (runtime-spec v1.4)
  └─ Planner (planner-spec v1.1)
        └─ 本文档：Query Understanding + Knowledge Query Plan
              ├─ Ontology (2026-08-07-ontology-layer-design + l3-design-v1)
              │    ├─ lookup_entities / graph_query / compile_profile
              │    └─ resolve_with_entities (capability_entity_map 反查)
              ├─ Knowledge (knowledge-center-spec v1.2 + 
              │            2026-08-09-enterprise-retrieval-design)
              │    ├─ route_query（软路由）
              │    └─ search_chunks（hybrid + metadata_filters）
              ├─ Capability (capability-center-spec v1.1)
              │    └─ Query Capability（query/command 分离）
              └─ Answer (2026-08-11-chat-agent-design + chat_service)
```

---

# 20. 开放问题（修订后）

1. **TBox 部件级关系缺口**（评审暴露）：`component → supplier` 供应关系、`component → equipment` 归属关系不在冻结 12 类中（ontology 设计 §7.2 的示例本身也用了未定义关系）。需决策：扩展 TBox 或改建模（部件按 material 处理）。
2. `RELATION/MULTI_HOP/CAUSAL` 的关系候选是否必须来自 Ontology，不允许 LLM 发明关系——**建议：必须来自 TBox**，LLM 只能从候选集选。
3. 是否允许同一 Query 多候选 Plan 评分选择——一期不做，固定策略单解。
4. Graph 与 RAG 在 Evidence Fusion 中是否需要非对称权重——P2 先不调权，P@5 提升不足再实验（与 ontology 设计 §11 开放项 4 一致）。
5. Capability Query 输出是否统一包装为 Evidence——**建议：是**。
6. Answer 是否始终经 Evidence Validator——一期仅对 CAUSAL/低置信度强制，其余复用 chat_service 现有引用机制。
7. Query Plan 是否需要持久化——一期仅写 Execution Trace，不落库。
8. 哪些 Understanding 字段进入 Evaluation/Learning 闭环——待 Evaluation 中心细化。

---

# 21. 最容易犯的四个错误（沿用 v0.1）

1. 把 Understanding 做成 Intent 分类（应是 Entity+Relation+Constraint+Time+Operation+AnswerRequirement）。
2. 让 Understanding 直接选工具（应经 Planner）。
3. 把 Query Plan 做成 Workflow（只读检索编排 ≠ 通用工作流引擎）。
4. 过早全自动 Agent Planner（先固定策略，四层评估跑通再升级）。
