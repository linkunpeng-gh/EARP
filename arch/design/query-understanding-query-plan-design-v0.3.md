# EARP Query Understanding & Knowledge Query Plan 设计（v0.3 修订版）

**文档编号**：L2-02-REASONING-QUERY
**版本**：v0.3（在 v0.2 基础上修订）
**状态**：Draft / 项目组讨论版
**日期**：2026-08-13
**定位**：L2 Reasoning 子设计
**上游**：Runtime / Planner / Ontology / Knowledge Center / Capability Center
**下游**：Knowledge Retrieval Engine、RAG、Ontology Search、Capability Query、Answer Generation
**关联评审**：`arch/reviews/query-understanding-query-plan-design-v0.2-review.md`

---

## 0. v0.2 → v0.3 修订说明（对抗式评审落地）

v0.2 方向与收缩决策正确，但存在「未达可实施」的三类问题：**跨通道契约未冻结**、**intent→策略映射不闭合**、**两处代码映射可证伪**。本版逐项闭合：

| # | v0.2 问题 | v0.3 修正 |
|:-:|---|---|
| 1 | Evidence Set 全程引用却无 schema | §9 冻结 Evidence schema（channel 多态 + 来源/置信度/时效字段） |
| 2 | QP-05 把 RRF 用到异构通道（范畴错误） | §8 拆「通道内 RRF」与「跨通道 Evidence 组装」两层，QP-05 改写 |
| 3 | Retrieval Need 是一等中间层却无派生规则（双真相） | §7 降为纯函数 `derive_needs()`，加 QP-12「派生不存储」 |
| 4 | 10 类 intent vs 5 策略 vs §9 通道表对不齐 | §11.2 出完整 `intent → 策略 → fallback` 映射表，10 类全覆盖 |
| 5 | §10 例 4「located_in 反向取设备」调用不存在的反向遍历 | §12 例 4 改标注为「反向遍历缺口」，§16 Phase 3 补反向邻接查询 |
| 6 | `resolve_with_entities()` 只吃单字符串，不接收结构化输出 | §6.5 定义接收 Structured Query 的新签名 `resolve_with_query()` |
| 7 | §1.1 混淆「端点级已实现」与「chat 链路已接入」 | §1.1 区分两态；Phase 3 硬任务 = 把 `knowledge_search` 接进 chat 链路 |
| 8 | 8 节点类型与 5 策略函数两套并行抽象 | §10 节点类型降级为「Execution Trace 记录模型」，非执行 DSL |
| 9 | Phase 1 宣称「schema 冻结」却无 schema | §6 附 Pydantic 模型；intent 枚举 + relation 候选必须来自 TBox（写死） |
| 10 | v0.2 删掉了量化验收门槛 | §17 恢复 Understanding/Plan 层数字门槛 + eval 规模下限 |
| 11 | 无端到端延迟预算、规则层置信度不可计算 | §6.4 定义可计算置信度；§11.3 定义每策略 p95 延迟预算 |
| 12 | `answer_requirement` 一期无消费者（投机复杂度） | §6.7 `answer_type` 一期单值 `summary`，其余字段标注 reserved |

---

## 0.1 v0.3 二轮内审修订（2026-08-13）

v0.3 发布后二轮内审补充闭合 4 项：

| # | 问题 | 修正 |
|:-:|---|---|
| 13 | QP-05 与 P2 任务书 / 现有 `knowledge_search` 三层 RRF 直接冲突未处理 | §8.1 采方案 A：三层 RRF 记过渡实现，Phase 3e 重构（tech-debt #10） |
| 14 | `derive_needs` 的 `document_evidence` 漏 CAUSAL/MIXED（与 plan_causal/§8.2 矛盾） | §7 改由 §8.2 单一来源推导，修正 document_evidence 集合 |
| 15 | §6/§9 schema 不一致（`constraints` 自由 dict 吞掉 TimeConstraint、Evidence 无类型） | §5.5/§6.2 拆 `time: TimeConstraint`；§9.1 Evidence 改 Pydantic；§10 补 TraceRecord |
| 16 | TBox 缺口反向阻塞 §17 relation 门槛 | §20 问题 1 标注「Phase B（QU）评估集构建前必须拍板」 |

---

## 0.2 v0.3 三轮修订（2026-08-13，方案 A 定性 + 时序）

| # | 问题 | 修正 |
|:-:|---|---|
| 17 | 方案 A 把「三层 RRF」定性为「范畴错误、必须重构」说重了——RRF 只用 lane 内排序位置，profile/graph/chunk 三层 RRF 是合法 recall 融合，非债 | §8.1/QP-05/QP-13/tech-debt #10/任务书风险 #6/session-record 统一改为「RRF = recall 层，缺角色层，D3 叠加，不替换 RRF」 |
| 18 | 完整 QU + 10 intent planner 前置，撞「通道未就绪无消费者」「误选疼点尚不存在」两个事实 | §16 重排序：先 P2 接三层 → QU 并行 → 最小 planner 后置；§5.4/§11.2/§17 将 intent 收敛为可靠子集 {FACT, RELATION, AGGREGATION} + 其余显式回落 |

---

# 1. 背景与现状（对齐当前 roadmap）

## 1.1 已建成的能力（勿重复建设）——区分「端点级」与「链路级」

截至 2026-08-13，能力分两态，**务必区分**：

**端点级（已实现、有测试，但未必接入用户路径）**：

| 能力 | 实现 | 接入状态 |
|---|---|---|
| 软路由 `route_query()` | `knowledge/routing.py`（keyword ∪ vector → 权限过滤 → KB 兜底） | ✅ 已接入 chat 链路 |
| chunk 检索 `search_chunks()` | `knowledge/search_service.py`（mode=vector/hybrid + metadata_filters + accessible_roles） | ✅ 已接入 chat 链路 |
| 三层融合 `knowledge_search()` | `ontology/search.py`（profile + graph + chunk，RRF） | ⚠️ **仅 `/ontology/search` 端点**，未接入 chat 链路 |
| 实体解析 `lookup_entities()` / `graph_query()` | `ontology/abox_service.py` | ⚠️ 仅 ontology 检索端点，未接入 chat 链路 |
| 能力反查 `resolve_with_entities()` | `ontology/search.py`（intent 字符串 → 实体命中 → capability_entity_map 反查） | ✅ 已接入 `/plan`（M2 收窄） |
| 答案生成 `chat_service` | `conversation/chat_service.py`（route_query + search_chunks + SSE + citations） | ✅ P1 已上线 |

**关键事实（v0.2 混淆处）**：当前用户提问实际走的是 `chat_service._retrieve()` = `route_query` + `search_chunks` **双通道**，**不含 profile/graph 通道**。§1.2 的「缺理解层」之外，还有一个**「已建未接」**的缺口：`knowledge_search`（三层）尚未接进 chat 链路。这是 Phase A 的第一个硬任务，不是 Phase B-C 的附带。

## 1.2 真正缺的那一层

现在不缺 Retriever，缺的是：

> **如何先理解问题，再决定按什么策略编排这些已有检索能力。**

即：把「已散落的 route_query / knowledge_search / graph_query / search_chunks / capability resolution」用一个**理解层 + 固定策略层**串起来。同时，把「已建未接」的 ontology 三层检索接进用户路径。

---

# 2. 核心设计结论

## 2.1 一句话结论

> **Query Understanding 负责回答「用户要什么、回答它需要什么知识」；Knowledge Query Plan 负责回答「为获得这些知识，按什么顺序调用哪些已有检索能力」。**

两者必须分离。中间产物由**三个已冻结契约**串起：Structured Query（§6）、Plan（§11，固定策略）、Evidence Set（§9）；Retrieval Need（§7）是纯派生、不落库；最终 Answer 复用 chat_service。

```text
User Query (+ Conversation Context)
    ↓
Query Understanding（规则优先 + LLM 低置信度升级）
    ↓
Structured Query（§6，schema 冻结）
    ↓
derive_needs()（§7，纯派生，不落库）
    ↓
Knowledge Query Planner（一期：3 策略 + 显式回落）
    ↓
策略函数 → Execution Trace（§10，观测记录）
    ↓
Ontology / RAG / Capability（已有，含「已建未接」的 ontology 三层）
    ↓
Evidence Set（§9，角色层组装）
    ↓
Answer（复用 chat_service）
```

## 2.2 不做成 Intent 分类器

企业查询同时含实体、关系、属性、时间、结构化约束、聚合、排序、比较、因果、证据要求。Query Understanding 的输出是 **Structured Query Representation**，Intent 只是其中一个字段（且是有限枚举）。

---

# 3. 两个概念的职责边界

## 3.1 Query Understanding

**负责**：识别业务对象/实体提及/关系/问题类型/时间范围/结构化约束/操作意图/回答要求；接收会话上下文做指代消解。

**不负责**：决定走 Graph 还是 Vector、调用哪个 Capability、定 RRF 参数、生成 SQL/Cypher、直接访问数据、执行查询。

## 3.2 Knowledge Query Plan

**负责**：根据 Structured Query 选择检索策略、确定调用顺序与依赖、定 DD/KB 范围、定 Graph 遍历方向、定融合策略、组装 Evidence Set。

**不负责**：自己理解业务语义、定义实体类型、创建 Capability、实现 Connector、执行 Command。

---

# 4. 与现有 Planner 的关系（对齐矩阵，含接口缺口标注）

Knowledge Query Plan 是 Planner **知识检索子链路**的细化，不是新的并行规划器：

| 本文档概念 | 现有实现（已建） | 关系 | 缺口 |
|---|---|---|---|
| Query Understanding 实体识别 | `ontology/search.py::_entity_hits` + `lookup_entities()` | 复用/增强 | `lookup_entities` 是 ILIKE 子串匹配，无语义消歧（Phase F） |
| `RESOLVE_ENTITY` | `abox_service.lookup_entities()` | 直接映射 | 同左 |
| `GRAPH_QUERY`（前向） | `abox_service.graph_query()` | 直接映射 | **无反向遍历**（见 §12 例 4、§16） |
| `VECTOR/KEYWORD/METADATA` | `search_chunks()`（mode + metadata_filters） | 直接映射（三节点 = 一函数的 mode 开关） | 无 |
| `DD/KB 软路由` | `route_query()` | 直接映射 | 无 |
| `FUSION_RERANK` | `search_service._rrf_merge`（recall 层）+ P3 reranker | 直接映射 | profile/graph/chunk 文本证据 RRF，capability 结构化行除外（§8.1） |
| `ANSWER` | `chat_service` | 复用 | 无 |
| 问题类型 intent | 现有 planner intent 是 capability 导向 | **新增一维，正交并存** | 汇合点接口需扩展，见 §6.5 |

**关键决策**：本文档的问题类型 intent（FACT/RELATION/…）是**知识检索维度**的标注，与现有 planner 的 capability intent（query.alarms 等）是两个正交维度。两者在 **`resolve_with_query()`（§6.5，新增，接收 Structured Query）** 处汇合：问题类型 + 实体类型 → capability_entity_map 反查。**v0.2 的「在 `resolve_with_entities()` 汇合」表述不成立**——该函数只吃单字符串，故本版新增接收结构化输出的接口。

---

# 5. Query Understanding 设计

## 5.1 总体结构（6 维度 + 会话上下文）

```text
QueryUnderstanding
├── context            # 会话上下文（指代消解）
├── entities           # 实体提及（mention → semantic_type，非 entity_id）
├── relations          # 关系（必须来自 TBox）
├── intent             # 问题类型（10 类枚举）
├── constraints        # 结构化元数据约束（→ metadata_filters）
├── time               # 时间（独立 TimeConstraint 字段）
├── operation          # 聚合/排序/比较
└── answer_requirement # 回答要求（一期 answer_type 单值 summary）
```

## 5.2 context：会话上下文

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

理解阶段只做提及 → 上文实体的映射；绝对时间解析依赖 Runtime Context 当前时间，不让 LLM 猜日期。

## 5.3 entities / relations

- **Entity Mention ≠ Entity Resolution**：理解只标注「CNC-01 是设备」，具体 `entity_id` 由 `lookup_entities()` 后续解析。
- **relation 候选必须来自 TBox**（§20 开放问题 2 已写死为决策）：LLM/规则只能从 `relation_types` 的 12 类中选，不得发明关系。候选集由 `relation_types` 表动态供给（不硬编码在 prompt 里）。

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

## 5.4 intent：问题类型（10 类枚举 + 一期可靠子集）

`FACT / ATTRIBUTE / RELATION / MULTI_HOP / LIST / AGGREGATION / COMPARISON / TREND / CAUSAL / MIXED`。

Intent 只描述问题性质，**不直接选 Retriever**。

**一期可靠分类子集（规则可高置信度识别）= `{FACT, RELATION, AGGREGATION}`**；其余 7 类（ATTRIBUTE / MULTI_HOP / LIST / COMPARISON / TREND / CAUSAL / MIXED）一期**显式回落**（§11.2），不要求规则层在 Phase B 分类它们——COMPARISON/TREND/CAUSAL 连 LLM 都难分，关键词规则必然高误判。§17 的 intent 门槛只对可靠子集计分。

## 5.5 constraints 与 time（独立建模，类型化）

`constraints`（结构化元数据约束）与 `time`（时间）分开建模——前者是自由 key/value，直接进 `metadata_filters`；后者需强类型（`resolved_start/resolved_end`），类型不同不应合并（v0.2「合并避免碎字段」在此让位于类型安全）：

```json
{
  "constraints": {"department": "财务部", "year": 2024, "doc_type": "制度"},
  "time": {"kind": "relative", "expression": "yesterday", "resolved_start": null, "resolved_end": null}
}
```

`constraints` 直接进 `search_chunks` 的 `metadata_filters`；`time.resolved_*` 由运行时回填。

## 5.6 operation

描述 aggregate / group_by / order_by / limit / compare，供 AGGREGATION / COMPARISON / TREND 策略消费（→ capability 调用参数）。

## 5.7 answer_requirement（一期收敛）

- `answer_type`：一期仅支持 `summary`（文本归纳）。`table / explanation` 等值**预留但一期不消费**（避免投机复杂度，对齐 YAGNI）。
- `evidence_required` / `citation_required`：一期由 chat_service 既有机制承载（恒输出 citations）。
- `source_preference`：**reserved，不进代码**（无消费者，待 Evaluation 中心定义后再启用）。

---

# 6. Structured Query 的冻结 schema 与生成策略

## 6.1 为什么规则优先

每类查询都过 LLM 会拖慢全链路（连「报销制度是什么」也要先 LLM）。与 enterprise-retrieval §3「低置信度升级 LLM 路由」同构：

```text
Query
  ↓
规则层：正则提取时间/数字 + 词典匹配实体名 + 关键词匹配 intent
  ↓
置信度评估（§6.4，可计算）
  ↓
confidence ≥ 阈值 → 直接产出 Structured Query（零 LLM）
confidence < 阈值 → LLM 补充（Schema-constrained JSON，禁 SQL/Cypher/API 选择）
```

规则层可用素材：`business_dictionary` 词典、ontology 实体名索引、`match_data_domains` 关键词表、`relation_types` 表（relation 候选来源）。

## 6.2 冻结 schema（Pydantic，Phase B 交付物）

Phase B 宣称「schema 冻结」，本版给出可冻结的模型（非示意 JSON）：

```python
from pydantic import BaseModel, Field
from enum import Enum

class Intent(str, Enum):
    FACT = "FACT"; ATTRIBUTE = "ATTRIBUTE"; RELATION = "RELATION"
    MULTI_HOP = "MULTI_HOP"; LIST = "LIST"; AGGREGATION = "AGGREGATION"
    COMPARISON = "COMPARISON"; TREND = "TREND"; CAUSAL = "CAUSAL"; MIXED = "MIXED"

class TimeConstraint(BaseModel):
    kind: Literal["absolute", "relative", "none"] = "none"
    expression: str | None = None          # "yesterday" / "最近三个月"
    resolved_start: datetime | None = None # 运行时回填
    resolved_end: datetime | None = None

class EntityMention(BaseModel):
    mention: str
    semantic_type: str | None = None       # equipment/supplier/...
    role: Literal["subject", "target", "intermediate", "scope"] | None = None

class RelationMention(BaseModel):
    subject: str
    relation: str                          # MUST be in relation_types.relation_type_id
    object_type: str | None = None
    object_mention: str | None = None

class Operation(BaseModel):
    aggregate: Literal["COUNT","SUM","AVG","MAX","MIN"] | None = None
    group_by: list[str] = []
    order_by: str | None = None
    limit: int | None = None
    compare_subjects: list[str] = []       # COMPARISON 用

class AnswerRequirement(BaseModel):
    answer_type: Literal["summary"] = "summary"   # 一期单值
    evidence_required: bool = False
    citation_required: bool = True

class StructuredQuery(BaseModel):
    context: dict = Field(default_factory=dict)
    entities: list[EntityMention] = []
    relations: list[RelationMention] = []
    intent: Intent
    constraints: dict = Field(default_factory=dict)   # metadata 过滤（department/year/doc_type…），不含 time
    time: TimeConstraint = Field(default_factory=TimeConstraint)  # 时间单独建模（§5.5）
    operation: Operation = Field(default_factory=Operation)
    answer_requirement: AnswerRequirement = Field(default_factory=AnswerRequirement)
    confidence: float = Field(ge=0.0, le=1.0)        # §6.4
```

> 约束：`relations[].relation` 必须在 `relation_types` 中；`intent` 必须是枚举值；`confidence` 必须由 §6.4 计算，不得由 LLM 自报。

## 6.3 规则层实现要点

- 时间/数字：正则提取 → `time` 字段（相对时间只记 `expression`，绝对值运行时回填）。
- 实体名：词典（business_dictionary 词条）+ ontology 实体名索引匹配 → `entities[].mention`。
- intent 关键词：维护 `_INTENT_KEYWORDS` 表（如「为什么/原因」→ CAUSAL、「谁/哪个供应商」→ RELATION、「多少/统计」→ AGGREGATION、「哪个最多/比较」→ COMPARISON/AGGREGATION）。
- relation：规则命中实体后，用 `relation_types` 候选 + 动词词典（「谁生产」→ manufactured_by、「谁负责」→ responsible_for）。

## 6.4 可计算置信度（v0.2 缺失）

`confidence` 由两部分机械计算，**不靠 LLM 自报**：

```text
rule_coverage = 被规则命中的字段数 / 应提取字段数
              （字段：时间、实体、关系、intent、约束、operation）
ambiguity_penalty = 0.2 × 多候选字段数
                  （intent 多候选 / 实体多歧义 / DD 多命中）

confidence = max(0, min(1, rule_coverage - ambiguity_penalty))
```

阈值默认 `0.7`（可配）：`confidence ≥ 0.7` 用规则结果；否则 LLM 补充。**升级只补「未命中字段」，不重做已命中字段**（省 token）。

## 6.5 汇合点接口（新增，替代 v0.2 的错误映射）

新增 `resolve_with_query()`，接收结构化输出（v0.2 的 `resolve_with_entities(intent: str)` 保留给 `/plan` M2 收窄路径，不改其签名）：

```python
async def resolve_with_query(
    engine, tenant_id,
    query: StructuredQuery,      # 新：接收结构化输出
    *, top_k: int = 10,
) -> list[dict]:
    """entities → entity_type_ids → capability_entity_map 反查 → 候选能力。

    与 resolve_with_entities 的区别：直接用 query.entities 的 semantic_type/
    mention，而非从 intent 字符串重新 tokenize；命中实体不再内部丢弃，
    返回 {(capability_id, entity_type_id, matched_entity_ids)}。
    """
```

返回结构补 `matched_entity_ids`（v0.2 缺陷：实体命中被内部丢弃，无法进 Evidence 溯源）。

---

# 7. Retrieval Need（纯派生，不落库）

`derive_needs(structured_query) -> RetrievalNeed` 是**纯函数**，**由 §8.2 通道角色表单一来源机械推导**（禁止另立第二套判断）：

| need | 推导规则 |
|---|---|
| `entity_resolution` | `entities` 非空（graph/profile 通道的解析前提） |
| `relation_reasoning` | `relations` 非空 |
| `document_evidence` | chunk 是主/佐证通道（§8.2）= `intent ∉ {AGGREGATION, COMPARISON, TREND}` |
| `structured_data` | capability 是主/佐证通道（§8.2）= `intent ∈ {AGGREGATION, COMPARISON, TREND, CAUSAL, MIXED}` |
| `metadata_filter` | `constraints` 非空（metadata 过滤，不含 time） |
| `aggregation` | `operation.aggregate` 非空 |
| `real_time` | `time.kind ∈ {relative, absolute}` 且 `structured_data` |

> 说明（修正二轮内审发现）：`document_evidence` 由 §8.2 单一来源推导，**CAUSAL/MIXED 的 chunk 佐证（解释材料）与 RELATION/MULTI_HOP/LIST 的 chunk 佐证（graph 无事实时）均已包含在内**；「graph 无事实 → chunk 补证」是 §14 运行时 fallback，不是 derive_needs 的静态字段，两者不混淆。

**QP-12（新增）**：**派生不存储，存储不派生。** Retrieval Need 只在 §10 trace 里展示，不落库、不单列契约。这从根上消灭 v0.1/v0.2 的「双真相」风险。

---

# 8. 通道与融合

## 8.1 两层：recall（RRF）与角色（Evidence 组装）

| 层 | 作用域 | 机制 | 状态 |
|---|---|---|---|
| **Recall 层** | profile / graph / chunk（可排序文本证据 lane） | RRF（rank 融合，不依赖原始分数尺度） | ✅ 已有（`knowledge_search` 三层） |
| **角色层** | 主证据 vs 佐证/引用 + capability 结构化行 | 按问题类型定主从 + 冲突消解（§9.2） | 本期定义 schema，Phase D3 叠加实现 |

**正确的边界（修正三轮内审定性）**：RRF 只用各 lane 内部的**排序位置**，不依赖分数尺度，因此 profile(1.0) / graph(1/(1+depth)) / chunk(similarity) 三层 RRF 是**合法的 recall 融合，不是债**。真正的边界只有一条：**capability 的结构化输出（表格/聚合行）不是「可排序文本证据 lane」，不进 RRF**，在角色层作主证据。

**⚠️ 与正在进行的 P2 的关系（决策：方案 A）**：现有 `ontology/search.py::knowledge_search` 的三层 RRF 就是 recall 层，**不是范畴错误、不需要重构**。P2 任务书（Task 1「三层 RRF 融合」）照常执行，验收「实体类 P@5 提升」即 recall 层的验证。Phase D3 的「角色层」是**叠加在 recall 之上**（capability 结构化行作主证据、文本证据作引用佐证），不替换 RRF。原 tech-debt #10 定性已按此修正为「缺角色层」。

## 8.2 通道角色（角色层：主证据 vs 佐证，与 recall RRF 正交）

| 问题类型 | 主证据（答案主体） | 佐证（引用） |
|---|---|---|
| FACT / ATTRIBUTE | chunk | profile/graph |
| RELATION / MULTI_HOP / LIST | graph | chunk |
| AGGREGATION / COMPARISON / TREND | capability（结构化行，不进 recall RRF） | graph（范围解析） |
| CAUSAL / MIXED | capability + graph 并重 | chunk（解释材料） |

**注意**：profile/graph/chunk 作为文本证据 lane，在 **recall 层统一 RRF**（§8.1）；本表的「主/佐证」是**角色层**的定权，两者正交。「不参与 RRF」只对 capability 结构化行成立。AGGREGATION 不要把大量业务数据塞进 LLM 统计——Capability 完成聚合，LLM 只归纳。

---

# 9. Evidence Set（v0.2 未定义，本版冻结）

## 9.1 Evidence schema（冻结，Pydantic）

```python
class EvidenceChannel(str, Enum):
    GRAPH = "graph"; CHUNK = "chunk"; CAPABILITY = "capability"; PROFILE = "profile"

class Evidence(BaseModel):
    evidence_id: str
    channel: EvidenceChannel
    content: str                                # 归一化摘要/事实文本（供 LLM）
    source: str                                 # 来源系统/文档名
    source_ref: str                             # document_id | fact_id | capability_call_id
    confidence: float = Field(ge=0.0, le=1.0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    payload: dict = Field(default_factory=dict) # channel 多态
    conflict: bool = False                      # §9.2 冲突标记
```

- `channel` 决定 `payload` 形状：`chunk → {chunk_id, similarity, kb_id, metadata}`；`graph → {relation_type_id, source_entity_id, target_entity_id, depth}`；`capability → {capability_id, rows}`；`profile → {entity_id, key_facts}`。
- `confidence / source_ref / valid_from / valid_to` 由 ontology facts 既有字段与 chunk 元数据直接映射，capability 默认 `confidence=1.0`（业务事实）+ `source_ref=capability_call_id`。

## 9.2 角色层组装规则（叠加在 recall 层之上）

```text
1. recall 层：profile/graph/chunk 文本证据 RRF 召回（§8.1，已有）
2. 角色层：capability 结构化行作主证据（不进 RRF）；文本证据按 §8.2 定主/佐证
3. 主证据 → Evidence 主体；佐证 → Evidence 附录（chunk 恒作引用）
4. 冲突消解（同 channel 内）：
   - 优先 valid_to IS NULL（当前有效）
   - 次优先 confidence 高者
   - 仍冲突 → 双列，标注 conflict=true，交 LLM 归纳（不拍脑袋选一）
```

§20 开放问题 4「非对称权重」**不再悬置**：跨通道不加权（§8.2 定主从），同 channel 冲突按本条规则；是否引入非对称权重留到 P@5 实验后再评估（记入 backlog，不阻塞本期）。

---

# 10. Execution Trace（v0.2「节点类型」的降级）

v0.2 §7.2 的「8 类节点」**降级为 Execution Trace 记录类型**——策略函数执行后产出 trace 记录供观测，**不是执行 DSL，不做 JSON DAG 解析**：

| Trace Type | 来源函数 |
|---|---|
| `RESOLVE_ENTITY` | `lookup_entities()` |
| `GRAPH_QUERY` | `graph_query()` |
| `VECTOR_SEARCH` / `KEYWORD_SEARCH` / `METADATA_FILTER` | `search_chunks()`（mode/meta 参数） |
| `DD_ROUTING` / `KB_ROUTING` | `route_query()` |
| `CAPABILITY_QUERY` | 经 `resolve_with_query()` 反查后调用 |
| `FUSION_RERANK` | `_rrf_merge`（通道内）+ P3 reranker |
| `ANSWER` | `chat_service` |

一期不支持：Command、任意 SQL/Cypher/代码、Workflow 子流程。

```python
class TraceRecord(BaseModel):
    step_id: str
    type: str                    # 上表 Trace Type 之一
    input: dict
    output: dict | None = None
    latency_ms: float
```

**一期实现形态**：3 个固定策略函数（§11）+ 2 预留签名，直接编排现有函数并返回 `PlanResult`。DAG DSL 留到 Phase F 评估，若引入必须复用 orchestrator 的 `StepRunner`（加 read_only 约束、去 Saga/补偿），否则不建。

---

# 11. 固定策略函数（一期，替代通用 DAG DSL）

## 11.1 3 个策略函数（+ 2 预留签名）

```python
# 一期实现（Phase C 最小集）
async def plan_fact(query: StructuredQuery, *, ctx: QueryContext) -> PlanResult        # → route_query + search_chunks(+meta) + recall RRF
async def plan_relation(query: StructuredQuery, *, ctx: QueryContext) -> PlanResult    # → lookup_entities + graph_query（前向，max_hops 参数）+ chunk 补证（一期不依赖 capability 反查）
async def plan_aggregation(query: StructuredQuery, *, ctx: QueryContext) -> PlanResult # → capability 反查（一期 resolve_with_entities，Phase D1 换 resolve_with_query）+ capability query + aggregate

# 预留签名（Phase C 后按疼点启用）
async def plan_multi_hop(query, *, ctx) -> PlanResult   # = plan_relation(max_hops=2)
async def plan_causal(query, *, ctx) -> PlanResult      # = graph + capability（并行）+ rag + 角色层组装

class PlanResult(BaseModel):
    evidence: list[Evidence]        # §9.1
    citations: list[dict]           # chat-agent-design citations 结构
    trace: list[TraceRecord]        # §10
```

`QueryContext` 携带 `tenant_id / role_id / engine / conversation context`（§5.2），显式注入而非隐式全局。

## 11.2 `select_plan` 映射表（一期最小：3 策略 + 显式回落）

| intent | 一期策略 | 说明 |
|---|---|---|
| FACT | `plan_fact` | 文档事实查询 |
| RELATION / ATTRIBUTE / LIST | `plan_relation`（解析失败回落 `plan_fact`） | 单跳关系 / 对象属性 / 多目标列表 |
| MULTI_HOP | `plan_relation(max_hops=2)` | 多跳（并入 plan_relation 参数，不单列函数） |
| AGGREGATION / COMPARISON / TREND | `plan_aggregation`（无 capability → `plan_fact`） | 聚合 / 比较 / 趋势 |
| CAUSAL / MIXED | **显式回落 `plan_fact`**（trace 标注「intent 未绑定策略」） | 一期通道未就绪，不建 plan_causal |

> 一期「可靠分类」只对 `{FACT, RELATION, AGGREGATION}` 计分（§17）；其余 7 类**显式回落并写 trace**（QP-14），不得静默当 FACT。`plan_multi_hop` / `plan_causal` 是 §11.1 预留签名，Phase C 后按疼点启用。

`select_plan(query) -> plan_fn` 是**规则映射表**（非 LLM 自由规划），上表即实现。

## 11.3 p95 延迟预算（v0.2 缺失）

规则理解层应 < 50ms；LLM 升级加 ~500–1500ms（仅低置信度时）。策略函数（不含 LLM 生成）：

| 策略 | p95 预算 | 状态 |
|---|---|---|
| `plan_fact` | ≤ 800ms | 一期 |
| `plan_relation` | ≤ 500ms | 一期 |
| `plan_aggregation` | ≤ 600ms（含 capability） | 一期 |
| `plan_multi_hop` | ≤ 700ms | 预留（Phase C 后） |
| `plan_causal` | ≤ 1500ms（graph ∥ capability 并行） | 预留（Phase C 后） |

**说明**：`plan_causal` 中 graph 与 capability **并行**（rag 依赖二者输出后串行），否则预算不可达。数值为建议值，实测标定。

## 11.4 校验（策略函数内约束）

| 校验 | 一期落地方式 |
|---|---|
| Schema | 策略函数输入用 §6.2 Pydantic 约束 |
| Scope（权限） | 复用 `route_query` DD 权限过滤 + `search_chunks` accessible_roles + graph 源实体限域 |
| Safety | 只允许调用注册的只读函数；无 Command / SQL / Cypher 入口 |
| Cost | max_hops ≤ 3、candidate DD/KB = 3、top_k ≤ 50、Capability 调用数有限制（建议值待实验） |
| 租户 | 每步显式 `tenant_id`，RLS 会话内执行（注：一期 Plan 不落库，此为 Phase F 持久化 Plan 的预留语义） |

---

# 12. 典型 Query Plan 例子（示例已对齐 TBox 与代码能力）

> 例 1（FACT）/ 例 2（RELATION）/ 例 4（AGGREGATION）对应一期 3 策略；例 3（多跳）/ 例 5（因果）是 Phase C 后预留策略（plan_multi_hop / plan_causal）的目标形态。

## 例 1：报销制度（FACT）

```yaml
intent: FACT
constraints: {year: 2024, department: 财务部, doc_type: 差旅制度}
answer_requirement: {answer_type: summary, citation_required: true}
```

```
DD_ROUTING(finance_data) → KB_ROUTING(费用报销) → METADATA_FILTER
  → VECTOR+KEYWORD(通道内 RRF) → ANSWER
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
（无图事实时 → VECTOR_SEARCH("CNC-01 供应商") 补证 → 组装 Evidence）
```

## 例 3：多跳（MULTI_HOP）

> "CNC-01 所在产线的负责人是谁？"

```yaml
relations:
  - CNC-01 → belongs_to → production_line        # equipment→production_line ✓
  - production_line → responsible_for → employee # production_line→employee ✓
```

```
RESOLVE_ENTITY(CNC-01) → GRAPH_QUERY(max_hops=2) → ANSWER
```

## 例 4：聚合（AGGREGATION）——标注反向遍历缺口

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
RESOLVE_ENTITY(华东一厂) → [反向遍历缺口] 取厂内设备
  → CAPABILITY_QUERY(query_equipment_alarm, equipment_ids=?, time=yesterday) → AGGREGATE → ANSWER
```

> **⚠️ 缺口标注（v0.2 遗漏）**：`graph_query` 目前只支持**前向**（source→target），无法从「华东一厂」反向取「位于该厂的设备」。Phase D2 需在 ABox 补**反向邻接查询**（`WHERE target_entity_id = :eid` 分支）或反向索引；在补上之前，本策略回落为「CAPABILITY_QUERY 按 plant 参数直接取数」（capability 内部已按工厂过滤），不依赖图反向。

## 例 5：因果（CAUSAL）

> "为什么 CNC-01 最近故障增加？"

```
RESOLVE_ENTITY(CNC-01) ─┬─ GRAPH_QUERY（关系链：部件/供应商/维护人/报警类型）  ┐ 并行
                        └─ CAPABILITY_QUERY（最近故障统计）                    ┘
                               ↓
                         RAG（维修记录/手册/质量报告）
                               ↓
                         角色层组装 Evidence（§9.2）→ ANSWER
```

结果逻辑：Capability 证实「故障确实增加」→ Graph 提供「关联对象/关系链」→ RAG 提供「解释材料」→ LLM 归纳。

---

# 13. 为什么不让 LLM 直接决定「用什么工具」

LLM 擅长语义理解，不应直接拥有任意数据访问权；企业查询必须可审计、可解释、可重放；Capability 已是标准业务能力抽象，Planner 应规划 Capability 而非 API。

---

# 14. Failure / Fallback

- Entity Resolution 失败 → 显式名称/业务编码 → DD 限域语义搜索 → 仍失败走 RAG
- Graph 无事实 → RAG 补证（chunk 佐证）
- RAG 低置信度 → Graph / Keyword / Metadata 补充
- 反向遍历未就绪（Phase D2 前）→ capability 按参数直取，绕过图反向
- 多源冲突 → Evidence 显式记录 `source / source_ref / confidence / valid_from / valid_to`，按 §9.2 消解，仍冲突则双列交 LLM

所有 fallback 步骤在 tenant 会话内、权限过滤后执行。

---

# 15. Observability（Execution Trace 驱动）

调试视图分层展示：Query Understanding（实体/关系/intent/confidence 分项）→ `derive_needs()` 结果 → 策略名 + **Execution Trace（§10）** + 每步结果 → Evidence Set（含 channel/confidence/conflict）→ citations。复用 `route_debug` 的「分层可解释调试」模式，不新建平行调试体系。

---

# 16. 分阶段实施（对齐 roadmap：先接通道，再按疼点建最小 planner）

```
Phase A   【已在进行 = P2】ontology 三层检索接入 chat 链路
          —— knowledge_search 接进 chat_service._retrieve（§1.1「已建未接」补齐），
             profile/graph 通道先在用户路径生效，度量「路由错=空」「实体类 P@5」
Phase B   【并行】Query Understanding 独立建设（规则优先 + LLM 低置信度升级）
          —— 产出 Structured Query（§6.2 schema 冻结）+ derive_needs()；
             不依赖通道，可独立评估（§17）
Phase C   【后置】最小固定策略 Planner —— 先 3 策略（plan_fact / plan_relation / plan_aggregation）
          —— 在 Phase A 度量到真实疼点后，再按疼点扩展；intent 一期收敛为
             可靠子集 {FACT, RELATION, AGGREGATION} + 其余显式回落（§5.4/§11.2）
Phase D   能力闭环 + 角色层：
          D1. resolve_with_query() 落地（§6.5 新签名）；plan_aggregation 从 resolve_with_entities 升级接入（plan_relation 一期即不依赖 capability 反查，见 §11.1）
          D2. ABox 反向邻接查询（§12 例 4 缺口闭合）
          D3. 角色层 Evidence 组装（§9.2，叠加在 recall 层之上，不替换 RRF）
Phase E   rerank 精排接入 FUSION_RERANK（= roadmap P3，recall 层）
Phase F   （远期）低置信度自适应规划 + 通用 DAG 评估——非一期依赖；
          若引入 DAG，Plan 持久化需重新评估租户/审计语义（§11.4 预留）
```

**与 roadmap 的关系**：Phase A = 当前 P2（接入，非净增量）；Phase B（QU）独立并行；Phase C 最小 planner **后置到 Phase A 度量出真实疼点之后**；D1/D2/D3 是缺口闭合 + 角色层；Phase E = P3。

**时序理由（修正三轮内审）**：完整 QU + 10 intent planner 前置会撞两个事实——(1) AGGREGATION/COMPARISON/TREND/CAUSAL 的唯一消费者是 capability query，通道就绪前无消费者；(2)「graph vs rag 误选」这个 planner 要解决的疼点，在只有两通道、三层未接时尚不存在。故先接通道、度量疼点、再建最小 planner。

---

# 17. 评估集（并入现有体系 + 恢复量化门槛）

在 `tests/fixtures/routing_eval.md` 基础上扩展三层，**每层有数字门槛**：

1. **Understanding 层**（新增 fixture，N ≥ 100 标注查询）：
   - intent 准确率 ≥ 85%（**仅对可靠子集 {FACT, RELATION, AGGREGATION} 计分**；其余 7 类回落即正确，不设门槛）
   - 实体提及召回 ≥ 90%
   - relation（来自 TBox）准确率 ≥ 80%
   - schema 合规率 = 100%（relation 必须 ∈ TBox、intent ∈ 枚举）
2. **Plan 层**（N ≥ 100）：
   - 策略命中率 ≥ 95%（一期 3 策略；7 类回落视为命中「回落」策略）
   - 非法调用 = 0、越权访问 = 0、Command = 0
3. **Retrieval/Answer 层**：沿用 `routing_eval`（DD 命中 ≥ 90%）+ `verify_routing.py` / `verify_chat.py`（引用命中 ≥ 80%）既有口径

**gating**：Understanding 层门槛未达，不启动 Phase C；Plan 层门槛未达，不扩展策略。

---

# 18. 关键设计原则（QP，修订版）

- **QP-01** Query Understanding 不选工具，只形成结构化查询语义。
- **QP-02** Knowledge Query Plan 不懂自然语言，只组织受控只读检索步骤。
- **QP-03** Ontology 是 Understanding 的语义基础，也是 Graph 检索的执行基础。
- **QP-04** RAG / Graph / Keyword / Metadata / Capability 是互补通道，不互相替代。
- **QP-05**（改）**文本证据（profile/graph/chunk）用 RRF 召回；capability 结构化行不进 RRF，作主证据；答案 vs 引用由角色层（§9.2）定。**
- **QP-06** Query Plan 是只读检索编排，不是 Workflow，不与 orchestrator 并行建执行引擎。
- **QP-07** 一期不允许生成/执行任意 SQL/Cypher/代码。
- **QP-08** 所有 Plan 必须满足 Schema / Scope / Safety / Cost / 租户隔离约束后才能执行。
- **QP-09** 多源回答保留 evidence source / source_ref / confidence / validity。
- **QP-10** 先固定策略验证架构，再引入 LLM 自适应规划。
- **QP-11**（补）`select_plan` 是规则映射表，10 类 intent 必须都有落点，不允许未定义。
- **QP-12**（补）**派生不存储，存储不派生**（Retrieval Need 是纯函数输出）。
- **QP-13**（补）`knowledge_search` 三层 RRF 是**合法 recall 层**（§8.1），非债；缺的是「角色层」（主 vs 佐证 + capability 结构化行），Phase D3 叠加实现，不替换 RRF。
- **QP-14**（补）一期只对可靠子集 `{FACT, RELATION, AGGREGATION}` 实现策略；其余 7 类 intent 显式回落并写 trace，不得静默当 FACT 处理。

---

# 19. 与现有文档衔接（带版本号）

```text
Runtime (runtime-spec v1.4)
  └─ Planner (planner-spec v1.1)
        └─ 本文档：Query Understanding + Knowledge Query Plan
              ├─ Ontology (2026-08-07-ontology-layer-design + l3-design-v1)
              │    ├─ lookup_entities / graph_query（前向）/ compile_profile
              │    └─ resolve_with_entities → resolve_with_query（§6.5 新增）
              ├─ Knowledge (knowledge-center-spec v1.2 +
              │            2026-08-09-enterprise-retrieval-design)
              │    ├─ route_query（软路由）
              │    ├─ search_chunks（hybrid + metadata_filters）
              │    └─ knowledge_search（三层，Phase A 接进 chat 链路）
              ├─ Capability (capability-center-spec v1.1)
              │    └─ Query Capability（query/command 分离）
              └─ Answer (2026-08-11-chat-agent-design + chat_service)
```

---

# 20. 开放问题（收敛后）

1. ~~**TBox 部件级关系缺口**~~ ✅ **已决策（2026-08-15，方案 A）**：`belongs_to` 源扩 component（component→equipment）、`supplied_by` 源扩 component（component→supplier）——migration 0016 同步存量租户 + 种子已改 + 设计 §3.2 同步；实体导入校验自动放行（test_component_supply_belong_relations）。**不再阻塞 §17 relation 门槛**。决策备忘见 `arch/design/2026-08-13-tbox-component-relation-decision.md`。
2. ~~关系候选是否来自 TBox~~ ✅ **已决策（本版）**：必须来自 TBox，LLM 只能从候选集选（§5.3、§6.2）。
3. 是否允许同一 Query 多候选 Plan 评分选择——一期不做，固定策略单解。
4. ~~Graph 与 RAG 非对称权重~~ ✅ **已决策（本版）**：跨通道不加权（§8.2 定主从），同 channel 冲突按 §9.2；非对称权重入 backlog，P@5 实验后再评估。
5. ~~Capability Query 输出是否统一包装为 Evidence~~ ✅ **已决策（本版）**：是（§9.1，channel=capability）。
6. Answer 是否始终经 Evidence Validator——一期仅对 CAUSAL/低置信度强制，其余复用 chat_service 引用机制。
7. Query Plan 是否需要持久化——一期仅写 Execution Trace，不落库；Phase F 若引入 DAG 需重新评估。
8. 哪些 Understanding 字段进入 Evaluation/Learning 闭环——待 Evaluation 中心细化；`source_preference` 等 reserved 字段待其定义后启用。

---

# 21. 最容易犯的四个错误

1. 把 Understanding 做成 Intent 分类（应是 Entity+Relation+Constraint+Time+Operation+AnswerRequirement）。
2. 让 Understanding 直接选工具（应经 Planner）。
3. 把 Query Plan 做成 Workflow（只读检索编排 ≠ 通用工作流引擎）；把「节点类型」当执行 DSL（应是 trace 模型）。
4. 过早全自动 Agent Planner（先固定策略，量化门槛跑通再升级）。
