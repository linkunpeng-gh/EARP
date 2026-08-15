# EARP Query Understanding & Knowledge Query Plan 设计

**文档编号**：L2-02-REASONING-QUERY
**版本**：v0.1
**状态**：Draft / 项目组讨论版
**日期**：2026-08-12
**定位**：L2 Reasoning 子设计
**上游**：Runtime / Planner / Ontology / Knowledge Center / Capability Center
**下游**：Knowledge Retrieval Engine、RAG、Ontology Search、Capability Query、Answer Generation

---

## 0. 文档定位与阅读方式

本文不是在重新设计 Runtime、Planner、Knowledge Center 或 Capability Center，而是在它们之间补齐一个此前缺少、但对融合检索至关重要的中间层：

> **用户自然语言问题 → Query Understanding → Knowledge Query Plan → Graph / RAG / Capability → Evidence → Answer**

本文重点回答四个问题：

1. Query Understanding 到底理解什么？
2. Query Understanding 与 Query Plan 的边界是什么？
3. Query Plan 如何决定走 Graph、RAG、Metadata、Keyword、Capability 中的哪一种或哪几种能力？
4. 项目组应该按什么阶段实现，才能避免一次性做成复杂 Agent / Workflow 系统？

本文是**设计方向稿**，不意味着所有字段和实现方式已经冻结。标记为“建议”的内容需要项目组评审后再进入正式 L2 规范。

---

# 1. 背景与现状

## 1.1 当前 EARP 已有基础

现有设计已经形成了较完整的知识检索基础：

```text
用户 Query
   ↓
Data Domain 路由
   ↓
Knowledge Base 路由
   ↓
Chunk Retrieval
```

企业级精准召回设计已经落地了软路由：DD 描述向量 + KB 摘要向量形成三级漏斗，路由采用 Top-N 候选而不是硬路由；同时提供文档级 metadata 过滤。fileciteturn3file7

Ontology 设计进一步增加了结构化语义层：

```text
Entity
   ↓
Entity Profile / Compiled Truth
   ↓
Graph Traversal
   ↓
Chunk Retrieval
```

当前 `knowledge_search()` 已经具备“实体 → Profile、图谱多跳、Vector/Keyword Chunk”三层检索并用 RRF 融合的实现基础；Ontology 接入软路由的下一步任务也已经明确。

另一方面，Runtime 已经定义了：

```text
Request → Intent → Goal → Plan → Validation → Execution → Result
```

且 Runtime 规定所有能力调用必须经过 Runtime；Planner 负责规划，Capability 负责业务能力，Knowledge 负责提供知识。fileciteturn3file2turn3file17

因此，现在缺少的不是更多 Retriever，而是：

> **如何先理解问题，再决定应该调用哪些知识检索能力。**

---

# 2. 核心设计结论

## 2.1 一句话结论

> **Query Understanding 负责回答“用户到底要什么，以及回答这个问题需要什么知识”；Knowledge Query Plan 负责回答“为了获得这些知识，应该按什么顺序调用哪些检索能力”。**

两者必须分离。

```text
User Query
    ↓
Query Understanding
    ↓
Structured Query / Retrieval Need
    ↓
Knowledge Query Planner
    ↓
Knowledge Query Plan
    ↓
Graph / RAG / Capability / Metadata / Keyword
    ↓
Evidence Set
    ↓
Answer
```

## 2.2 不把 Query Understanding 做成 Intent 分类器

传统做法往往是：

```text
Query → Intent = "查询设备"
```

EARP 不应停留在这一层。

企业查询经常同时包含：

- 实体
- 关系
- 属性
- 时间
- 结构化约束
- 聚合操作
- 排序
- 比较
- 因果解释
- 证据要求

因此 Query Understanding 的核心输出不是一个 Intent，而是：

> **Structured Query Representation（结构化查询表示）**

Intent 只是其中一个字段。

---

# 3. 两个概念的职责边界

## 3.1 Query Understanding

### 负责

- 理解自然语言中的业务对象
- 识别实体与实体提及
- 识别用户想查询的关系
- 判断问题类型
- 提取时间范围
- 提取结构化约束
- 识别是否需要聚合、排序、比较等操作
- 判断回答需要哪类证据
- 判断问题是否需要实时/结构化业务数据

### 不负责

- 决定使用 Graph 还是 Vector
- 决定调用哪个 Capability
- 决定 RRF 参数
- 生成 SQL / Cypher
- 直接访问数据库
- 直接调用企业系统
- 执行查询

---

## 3.2 Knowledge Query Plan

### 负责

- 根据 Query Understanding 选择 Retrieval 能力
- 确定能力调用顺序
- 建立依赖关系
- 确定哪些步骤可以并行
- 确定 DD / KB 的检索范围
- 确定 Graph 的遍历方向和范围
- 决定是否需要 RAG 补证
- 决定是否调用 Query Capability
- 决定证据如何融合
- 为后续 Answer Generation 准备 Evidence Set

### 不负责

- 自己理解用户业务语义
- 自己定义业务实体类型
- 自己创建 Capability
- 自己实现 Connector
- 执行 Command

---

# 4. 与现有 Planner 的关系

这里必须明确，否则项目组容易产生“Query Plan 与 Planner Plan 重复”的误解。

## 4.1 全局 Planner

现有 EARP Planner 面向完整目标，负责：

```text
Request
  ↓
Intent / Goal
  ↓
Execution Plan
  ↓
Task / Capability
```

Runtime 的主链已经明确是 `Request → Intent → Goal → Plan → Validation → Execution`。

## 4.2 Knowledge Query Planner

本文新增的是 Planner 内部的一个**专门子规划器**：

```text
Global Planner
      │
      ├── Task 1: 查询知识
      │       ↓
      │   Knowledge Query Planner
      │       ↓
      │   Knowledge Query Plan
      │
      ├── Task 2: 调用业务 Capability
      └── Task 3: 执行 Command
```

因此：

> **Knowledge Query Plan 是 Read-only Retrieval Plan，不是新的 Workflow。**

它重点解决的是“如何获得证据”，而不是“如何完成整个业务任务”。

---

# 5. Query Understanding 设计

## 5.1 总体结构

建议第一版固定为 7 个核心维度：

```text
QueryUnderstanding
├── entities
├── relations
├── intent
├── constraints
├── time
├── operation
└── answer_requirement
```

这是逻辑模型，不要求一期全部字段都有值。

---

## 5.2 Entities：实体对象

描述问题涉及哪些业务对象。

示例：

> “CNC-01 主轴轴承由哪家供应商提供？”

```json
{
  "entities": [
    {
      "mention": "CNC-01",
      "semantic_type": "equipment"
    },
    {
      "mention": "主轴轴承",
      "semantic_type": "component"
    },
    {
      "mention": "供应商",
      "semantic_type": "supplier",
      "role": "target"
    }
  ]
}
```

注意：

> **Entity Mention ≠ Entity Resolution。**

Query Understanding 只需要理解“CNC-01 是设备”；后续 Resolution Engine / Ontology Search 再把它映射到具体 `entity_id`。

现有 Ontology 已支持 `lookup_entities()`，并以名称 / business_code、DD 权限等进行实体解析。

---

## 5.3 Relations：关系语义

这是知识图谱真正参与 Query Understanding 的关键。

例如：

> “CNC-01 是谁生产的？”

```json
{
  "subject": "CNC-01",
  "relation": "manufactured_by",
  "object_type": "supplier"
}
```

又例如：

> “谁负责 A 产线？”

```json
{
  "subject": "A产线",
  "relation": "responsible_for",
  "object_type": ["employee", "department"]
}
```

EARP 当前 Ontology 第一批关系本身就是业务动词，例如 `manufactured_by`、`supplied_by`、`maintained_by`、`responsible_for`、`caused_by` 等，因此 Ontology 可以成为 Query Understanding 的语义词汇表，而不是单纯数据库结构。

---

## 5.4 Intent：问题类型

第一版建议控制在有限集合：

| Intent | 含义 | 典型问题 |
|---|---|---|
| `FACT` | 查询事实 | 报销标准是什么？ |
| `ATTRIBUTE` | 查询对象属性 | CNC-01 型号是什么？ |
| `RELATION` | 查询对象关系 | CNC-01 供应商是谁？ |
| `MULTI_HOP` | 多跳关系 | CNC-01 所在产线的负责人是谁？ |
| `LIST` | 列表 | 所有负责 CNC 设备的人是谁？ |
| `AGGREGATION` | 聚合统计 | 昨天各产线报警多少次？ |
| `COMPARISON` | 比较 | A、B 两条产线谁故障更多？ |
| `TREND` | 趋势 | 最近三个月故障是否增加？ |
| `CAUSAL` | 原因/解释 | 为什么 CNC-01 最近频繁报警？ |
| `MIXED` | 多种查询混合 | 统计报警并分析原因 |

Intent 不用于直接选择 Retriever，只用于描述问题性质。

---

## 5.5 Constraints：结构化约束

用于表达年份、部门、文档类型、版本、分类等确定性约束。

例如：

> “找 2024 年财务部发布的报销制度。”

```json
{
  "constraints": {
    "department": "财务部",
    "year": 2024,
    "doc_type": "制度"
  }
}
```

这些约束可以直接进入现有 Knowledge Search 的 metadata filter。当前实现已经把“语义路由”和“结构化 metadata 过滤”明确分成两类能力。

---

## 5.6 Time：时间范围

时间应独立建模。

例如：

> “昨天所有产线的异常次数。”

```json
{
  "time": {
    "kind": "relative",
    "expression": "yesterday",
    "resolved": {
      "start": "<runtime-resolved>",
      "end": "<runtime-resolved>"
    }
  }
}
```

理解阶段负责识别“昨天”；时间的绝对值解析应依赖 Runtime Context 的当前时间，而不是让 LLM 自己猜日期。

---

## 5.7 Operation：操作意图

用于描述统计、排序、比较等操作。

例如：

> “找出昨天报警最多的设备。”

```json
{
  "operation": {
    "aggregate": "COUNT",
    "metric": "alarm",
    "group_by": ["equipment"],
    "order_by": {
      "field": "count",
      "direction": "DESC"
    },
    "limit": 1
  }
}
```

注意：这仍然只是“理解”。

Query Understanding 不决定这个 COUNT 是由 Graph、Capability 还是 SQL 完成。

---

## 5.8 Answer Requirement：回答要求

建议至少描述：

- answer_type：single / list / table / summary / explanation
- evidence_required：是否必须带证据
- source_preference：是否优先结构化事实、原文、实时数据
- citation_required：是否需要文档引用

例如：

> “为什么 CNC-01 最近频繁报警？”

```json
{
  "answer_requirement": {
    "answer_type": "explanation",
    "evidence_required": true,
    "source_preference": [
      "live_data",
      "structured_fact",
      "document"
    ],
    "citation_required": true
  }
}
```

---

# 6. Query Understanding 完整示例

## 示例 1：纯 RAG 型

用户：

> “公司的 2024 年报销标准是什么？”

```yaml
entities: []
relations: []
intent: FACT
constraints:
  year: 2024
  doc_type: 制度
operation: null
time: null
answer_requirement:
  answer_type: summary
  evidence_required: true
```

理解结论：

> 这是一个文档事实查询，需要结构化约束和原文证据；没有明确实体关系需求。

---

## 示例 2：纯 Graph 型

用户：

> “CNC-01 的供应商是谁？”

```yaml
entities:
  - CNC-01 / equipment
  - supplier / target
relations:
  - CNC-01 → manufactured_by → supplier
intent: RELATION
constraints: {}
time: null
operation: null
answer_requirement:
  answer_type: single
  evidence_required: true
```

理解结论：

> 核心需求是结构化关系事实。

---

## 示例 3：Graph 多跳型

用户：

> “CNC-01 所在产线的负责人是谁？”

```yaml
entities:
  - CNC-01 / equipment
  - production_line / intermediate
  - employee|department / target
relations:
  - CNC-01 → belongs_to → production_line
  - production_line → responsible_for → employee|department
intent: MULTI_HOP
```

理解结论：

> 至少需要两跳关系。

---

## 示例 4：结构化 Capability Query

用户：

> “统计昨天华东一厂所有 CNC 设备的高温报警次数。”

```yaml
entities:
  - 华东一厂 / plant
  - CNC / equipment type
  - 高温报警 / alarm type
relations:
  - plant → contains → equipment
  - alarm → caused_by → equipment
intent: AGGREGATION
constraints:
  equipment_type: CNC
  alarm_type: high_temperature
time:
  expression: yesterday
operation:
  aggregate: COUNT
  group_by: equipment
answer_requirement:
  answer_type: table
  evidence_required: true
```

理解结论：

> 需要实时/结构化业务数据和聚合，不应把 RAG 当主要数据源。

---

## 示例 5：Graph + RAG + Capability 混合型

用户：

> “为什么 CNC-01 最近故障增加？”

```yaml
entities:
  - CNC-01 / equipment
intent: CAUSAL
time:
  expression: 最近
answer_requirement:
  answer_type: explanation
  evidence_required: true
  citation_required: true
```

此时 Query Understanding 不直接决定检索路径，只表达：

> 要解释“故障增加”的原因，需要时间范围、设备实体以及多源证据。

真正的 Graph / RAG / Capability 组合由 Query Plan 决定。

---

# 7. Knowledge Query Plan 设计

## 7.1 核心原则

Knowledge Query Plan 是：

> **一个只读、受约束、可验证、可观测的 Retrieval DAG。**

它不是 Workflow，也不是任意代码执行计划。

---

## 7.2 Plan Node 第一版类型

建议一期只支持 8 类节点：

| Node Type | 作用 | 对应现有能力 |
|---|---|---|
| `RESOLVE_ENTITY` | 自然语言实体 → Entity | Ontology lookup |
| `GRAPH_QUERY` | 关系/多跳查询 | graph_query |
| `VECTOR_SEARCH` | 语义检索 Chunk | pgvector / RAG |
| `KEYWORD_SEARCH` | 精确关键词 | tsvector / keyword |
| `METADATA_FILTER` | 结构化过滤 | documents.metadata |
| `CAPABILITY_QUERY` | 实时/结构化业务查询 | Query Capability |
| `FUSION_RERANK` | 证据融合与精排 | RRF / reranker |
| `ANSWER` | 基于 Evidence 生成答案 | LLM |

第一版明确不支持：

- Command Capability
- 任意 SQL
- 任意 Cypher
- Python 执行
- Browser 操作
- Workflow 子流程

原因：知识查询首先是 Read-only Retrieval，必须控制边界。

---

# 8. Query Plan 的生成逻辑

## 8.1 生成流程

```text
User Query
   ↓
Query Understanding
   ↓
Retrieval Need
   ↓
Candidate Retrieval Strategies
   ↓
Plan Construction
   ↓
Plan Validation
   ↓
Execute
```

---

## 8.2 Retrieval Need

建议在 Query Understanding 与 Query Plan 之间引入一个轻量中间结果：

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

这一步很重要，因为它让 Planner 不必从原始自然语言直接猜“应该调用什么工具”。

例如：

> “CNC-01 的供应商是谁？”

```text
entity_resolution = true
relation_reasoning = true
document_evidence = optional
structured_data = false
```

而：

> “2024 年报销标准是什么？”

```text
entity_resolution = false
relation_reasoning = false
document_evidence = true
metadata_filter = true
```

---

# 9. Query Plan 的选择原则

## 9.1 Fact / Document Query

```text
FACT
 ↓
DD Routing
 ↓
KB Routing
 ↓
Metadata Filter（如有）
 ↓
Vector + Keyword
 ↓
Rerank
 ↓
Answer
```

---

## 9.2 Relation Query

```text
RELATION
 ↓
Resolve Entity
 ↓
Graph Query
 ↓
Answer
```

RAG 可以作为 fallback 或 evidence enrichment，而不是默认主通道。

---

## 9.3 Multi-hop Query

```text
MULTI_HOP
 ↓
Resolve Entity
 ↓
Graph Query(max_hops = N)
 ↓
Answer
```

例如：

```text
CNC-01
  ↓ belongs_to
A产线
  ↓ responsible_for
张工
```

当前设计使用 PostgreSQL 递归 CTE 支持约 2～3 跳关系，暂不引入独立图数据库。fileciteturn3file0turn3file11

---

## 9.4 Aggregation Query

```text
AGGREGATION
 ↓
Resolve Scope / Entity
 ↓
Capability Query
 ↓
Aggregate
 ↓
Answer
```

不要把大量业务数据先塞进 LLM 再让 LLM 统计。

---

## 9.5 Causal / Explanation Query

这是 EARP 最重要的混合场景之一：

```text
CAUSAL
 ↓
Resolve Entity
 ↓
Graph Expansion
 ↓
Capability Query（实时事实）
 ↓
RAG（解释材料）
 ↓
Evidence Fusion
 ↓
Answer
```

这类查询体现了 Graph 与 RAG 的互补：

- Graph 找“关联对象和关系链”
- Capability 找“当前真实数据”
- RAG 找“制度、手册、报告等解释材料”

---

# 10. 典型 Query Plan 例子

## 例 1：报销制度

问题：

> “2024 年财务部的差旅报销标准是什么？”

### Query Understanding

```yaml
intent: FACT
entities: []
constraints:
  year: 2024
  department: 财务部
  doc_type: 差旅制度
time: null
operation: null
answer_requirement:
  answer_type: summary
  evidence_required: true
  citation_required: true
```

### Query Plan

```text
P1: DD_ROUTING(finance)
  ↓
P2: KB_ROUTING(expense/travel)
  ↓
P3: METADATA_FILTER(year=2024, department=财务部)
  ↓
P4: VECTOR_SEARCH + KEYWORD_SEARCH
  ↓
P5: FUSION_RERANK
  ↓
P6: ANSWER
```

对应现有的 DD → KB → Chunk 软路由体系。

---

## 例 2：设备供应商

问题：

> “CNC-01 的主轴轴承是哪家供应商提供的？”

### Query Understanding

```yaml
intent: RELATION
entities:
  - CNC-01 / equipment
  - 主轴轴承 / component
  - supplier / target
relations:
  - supplied_by
```

### Query Plan

```text
P1: RESOLVE_ENTITY(CNC-01)
  ↓
P2: GRAPH_QUERY(
      relation=has_component / supplied_by,
      max_hops=2
    )
  ↓
P3: ANSWER
```

如 Graph 没有完整关系：

```text
P2: GRAPH_QUERY
       ↓
P3: VECTOR_SEARCH("CNC-01 主轴轴承 供应商")
       ↓
P4: FUSION_RERANK
       ↓
P5: ANSWER
```

这体现“Graph 主、RAG 补证”的策略。

---

## 例 3：昨天报警最多的设备

问题：

> “昨天华东一厂哪个 CNC 设备高温报警最多？”

### Query Understanding

```yaml
intent: AGGREGATION
entities:
  - 华东一厂 / plant
  - CNC / equipment type
  - 高温报警 / alarm type
time: yesterday
constraints:
  equipment_type: CNC
  alarm_type: high_temperature
operation:
  aggregate: COUNT
  group_by: equipment
  order_by: count DESC
  limit: 1
```

### Query Plan

```text
P1: RESOLVE_ENTITY(华东一厂)
  ↓
P2: GRAPH_QUERY(plant → equipment)
  ↓
P3: CAPABILITY_QUERY(query_equipment_alarm)
      input:
        equipment_ids = P2.result
        time = yesterday
        alarm_type = high_temperature
  ↓
P4: AGGREGATE(COUNT BY equipment)
  ↓
P5: SORT DESC + LIMIT 1
  ↓
P6: ANSWER
```

注意：这里真正的企业数据访问由 Query Capability 完成。Capability 设计本身将 `query` 与 `command` 分开，Query Capability 是无副作用操作。

---

## 例 4：为什么 CNC-01 最近故障增加

问题：

> “为什么 CNC-01 最近故障增加？”

### Query Understanding

```yaml
intent: CAUSAL
entities:
  - CNC-01 / equipment
time:
  expression: 最近
answer_requirement:
  answer_type: explanation
  evidence_required: true
  citation_required: true
```

### Query Plan

```text
P1: RESOLVE_ENTITY(CNC-01)
        │
        ├───────────────┐
        ↓               ↓
P2: GRAPH_QUERY      P3: CAPABILITY_QUERY
    CNC-01 的关系        查询最近故障/报警
        │               │
        │               ↓
        │          时间序列/统计事实
        │
        ↓
    关联部件/供应商/
    维护人员/报警类型
        │
        └───────────────┐
                        ↓
                 P4: RAG_SEARCH
                   维修记录/
                   设备手册/
                   质量报告
                        ↓
                 P5: FUSION_RERANK
                        ↓
                 P6: ANSWER
```

### 结果的逻辑

```text
Capability：告诉我们“故障确实增加了”
Graph：告诉我们“可能关联哪些部件/供应商/关系”
RAG：告诉我们“手册、维修记录、质量报告怎么解释这些现象”
LLM：基于 Evidence 做归纳，而不是凭知识猜原因
```

---

# 11. Query Plan DAG 数据结构（建议）

一期不需要做复杂通用 DAG DSL，建议采用受限 JSON：

```json
{
  "plan_id": "qp_001",
  "mode": "knowledge_query",
  "read_only": true,
  "steps": [
    {
      "id": "s1",
      "type": "RESOLVE_ENTITY",
      "input": {
        "mention": "CNC-01"
      },
      "output": "equipment_id"
    },
    {
      "id": "s2",
      "type": "GRAPH_QUERY",
      "depends_on": ["s1"],
      "input": {
        "relation_types": ["supplied_by"],
        "max_hops": 2
      },
      "output": "supplier_candidates"
    },
    {
      "id": "s3",
      "type": "ANSWER",
      "depends_on": ["s2"],
      "input": {
        "evidence": ["s2"]
      }
    }
  ]
}
```

### 必须支持

- step id
- type
- dependencies
- input
- output reference
- read_only
- timeout / limit（建议）

### 一期不支持

- 任意代码
- 动态 Python
- 任意 SQL
- 任意图查询语言
- Command
- 无限递归

---

# 12. Plan Validation

Query Plan 生成后必须经过校验，不允许直接执行。

## 12.1 Schema Validation

检查：

- Node 类型是否合法
- 输入 Schema 是否匹配
- 输出引用是否存在
- dependency 是否存在
- 是否形成环

## 12.2 Scope Validation

检查：

- DD 是否在用户权限范围
- Graph Entity 是否具有可见权限
- KB 是否具有可见权限
- Capability 是否允许当前用户/角色调用

现有软路由已经要求候选 DD 权限过滤；Ontology 三层检索也要求 Profile/Graph 与 Chunk 的权限语义一致。fileciteturn2file1

## 12.3 Safety Validation

必须拒绝：

- Query Plan 包含 Command Capability
- 任意数据库语句
- 任意未注册 Capability
- 无限 Graph Hop
- 无上限 Chunk 拉取

## 12.4 Cost Validation

建议一期至少支持：

- 最大 Graph Hop：默认 3
- 最大 Candidate DD：默认 3
- 最大 Candidate KB：默认 3
- 最大 Chunk：默认 20～50
- 最大 Capability Query 数：默认有限制
- 最大 Plan Step：默认 10

---

# 13. 为什么不让 LLM 直接决定“用什么工具”

不建议：

```text
Query
 ↓
LLM
 ↓
“我决定调用某个 API / SQL / Cypher”
 ↓
执行
```

建议：

```text
Query
 ↓
LLM / Rule
 ↓
Structured Query
 ↓
受约束 Query Planner
 ↓
受约束 Plan
 ↓
Plan Validator
 ↓
注册的 Retrieval / Capability
```

原因：

1. LLM 擅长语义理解，不应直接拥有任意数据访问权。
2. 企业查询必须可审计、可解释、可重放。
3. Capability 已经是 EARP 的标准业务能力抽象；Planner 应规划 Capability，而不是 API。
4. Graph / RAG 本身也应该作为受控 Retrieval 能力，而不是暴露任意查询语言。

---

# 14. Failure / Fallback 机制

企业环境里，Query Understanding 和 Retrieval 都可能失败，因此必须允许逐级降级。

## 14.1 Entity Resolution 失败

```text
Resolve Entity 失败
   ↓
尝试 Query 中的显式名称/业务编码
   ↓
尝试 DD 限域的语义 Entity Search
   ↓
仍失败 → RAG fallback
```

## 14.2 Graph 无事实

```text
Graph Query
   ↓
无结果
   ↓
RAG Search
```

## 14.3 RAG 低置信度

```text
RAG
 ↓
低置信度
 ↓
Graph / Keyword / Metadata 补充
```

## 14.4 多源证据冲突

不要让 LLM 自己“拍脑袋”。

建议 Evidence Fusion 显式记录：

```text
source
source_ref
confidence
observed_at
valid_from
valid_to
```

Ontology Fact 当前已经设计了 `confidence`、`source_ref`、`valid_from`、`valid_to`、`status` 等字段，可直接作为后续证据质量模型基础。fileciteturn1file3

---

# 15. Observability：必须能看懂“为什么这样查”

这是项目实施时非常重要的一点。

调试界面至少应该能看到：

```text
User Query
  ↓
Query Understanding
  ├─ Entity: CNC-01 / equipment
  ├─ Relation: supplied_by
  ├─ Intent: RELATION
  └─ Evidence: structured_fact
        ↓
Query Plan
  ├─ s1 Resolve Entity
  ├─ s2 Graph Query
  └─ s3 Answer
        ↓
Results
  ├─ Entity Match
  ├─ Graph Fact
  └─ Citation
```

不能只显示：

```text
“最终回答：上海某精机”
```

否则一旦答错，项目组无法判断是：

- Query Understanding 错
- Entity Resolution 错
- Plan 错
- Graph 数据缺失
- RAG 没找到
- Capability 返回错
- Rerank 错

现有 DD/KB 路由已经有 `routing/debug`，可以沿用同样的“分层可解释调试”思想。fileciteturn3file12

---

# 16. 分阶段实施路线

原则：

> **先把“能理解、能计划、能执行、能解释”跑通，再增加复杂度。**

---

## Phase 0：接口与边界冻结

### 目标

不写复杂代码，先冻结概念。

### 输出

1. QueryUnderstanding schema
2. RetrievalNeed schema
3. KnowledgeQueryPlan schema
4. 8 类 Plan Node
5. Query Understanding / Query Plan 职责边界
6. 典型评估集

### 验收

至少覆盖：

- FACT
- ATTRIBUTE
- RELATION
- MULTI_HOP
- AGGREGATION
- CAUSAL
- MIXED

每一类至少 5 条真实问题。

---

## Phase 1：Rule + LLM Query Understanding

### 目标

先让系统稳定地产生 Structured Query，不进入复杂自动规划。

### 实现

```text
Query
 ↓
Query Understanding
 ↓
JSON
```

可以采用：

- 规则/词典：时间、数字、明显实体名、业务关键词
- LLM：关系、Intent、Answer Requirement
- Ontology：实体类型与关系类型约束

### 重点

LLM 输出必须 Schema-constrained。

不能直接产生 SQL / Cypher / API。

### 验收

- Entity extraction accuracy
- Relation classification accuracy
- Intent accuracy
- Time / metadata constraint accuracy
- JSON Schema compliance

---

## Phase 2：Knowledge Query Planner

### 目标

从：

```text
Structured Query
```

生成：

```text
Knowledge Query Plan
```

### 第一批只实现固定策略

例如：

```text
RELATION → Resolve → Graph
MULTI_HOP → Resolve → Graph
FACT → DD/KB → RAG
AGGREGATION → Scope → Capability Query
CAUSAL → Graph + Capability + RAG
```

这一阶段**不要让 LLM 自由规划 DAG**。

先用规则 Planner 验证架构。

### 验收

每一类问题：

- Plan 正确率 ≥ 95%
- 不产生非法 Node
- 不访问无权限 DD / KB / Entity
- 不调用 Command

---

## Phase 3：Plan Execution + Evidence Fusion

### 目标

让 Query Plan 真正驱动已有能力：

```text
Plan
 ↓
Ontology Search
RAG Search
Capability Query
 ↓
Evidence Set
```

### 重点

把现有：

- `route_query()`
- `knowledge_search()`
- `graph_query()`
- `search_chunks()`
- metadata filter
- Capability Resolution

统一成为 Plan Node 可调用能力。

当前 Ontology 的 `knowledge_search()` 已经具备 Profile / Graph / Chunk 三层检索基础；当前软路由任务则是把 candidate DD / KB 喂给这三层。fileciteturn2file1turn3file16

---

## Phase 4：低置信度升级与自适应规划

### 目标

只有简单规则不确定时才使用更强的 LLM 推理。

例如：

```text
Query Understanding confidence < threshold
   ↓
LLM clarification / enhanced understanding
```

或者：

```text
Plan confidence < threshold
   ↓
Alternative Plan
   ↓
Evaluate
   ↓
Choose
```

注意：这是后续优化，不作为一期核心依赖。

---

## Phase 5：复杂混合问题 / Re-plan

进一步支持：

```text
Graph → Capability → RAG
        ↓
     新发现实体
        ↓
     Re-plan
```

这时才与 EARP 已有 Runtime Closed-loop / Re-plan 能力进一步结合。Runtime 已有“事件 → Replan → Execution”以及 Feedback / Evaluation / Learning 的整体框架。fileciteturn3file5

---

# 17. 推荐的项目实施顺序

项目组不要同时开发 Query Understanding、Graph Planner、Reranker、Agent。

推荐严格按下面顺序：

```text
Step 1
冻结 Schema
        ↓
Step 2
建设 Query Understanding
        ↓
Step 3
建设固定规则 Query Planner
        ↓
Step 4
接入已有 RAG
        ↓
Step 5
接入已有 Ontology
        ↓
Step 6
接入 Query Capability
        ↓
Step 7
Evidence Fusion
        ↓
Step 8
Observability + Eval
        ↓
Step 9
LLM Adaptive Planning
```

这样每一步都可独立验证。

---

# 18. 第一批评估集建议

建议直接建立一个 `query_plan_eval`，而不是只做最终答案评估。

## 18.1 Query Understanding Eval

格式：

```yaml
query: CNC-01 的供应商是谁？
expected:
  intent: RELATION
  entities:
    - CNC-01
  relations:
    - manufactured_by
  time: null
```

## 18.2 Query Plan Eval

```yaml
query: CNC-01 的供应商是谁？
expected_plan:
  - RESOLVE_ENTITY
  - GRAPH_QUERY
  - ANSWER
```

## 18.3 Retrieval Eval

```yaml
query: CNC-01 的供应商是谁？
expected_sources:
  - graph
```

## 18.4 Answer Eval

```yaml
expected_answer_contains:
  - Supplier-A
citation_required: true
```

也就是说以后评估要拆成：

```text
Understanding Accuracy
        ↓
Plan Accuracy
        ↓
Retrieval Recall
        ↓
Evidence Quality
        ↓
Answer Accuracy
```

只有这样才能知道系统哪一层出了问题。

---

# 19. 关键设计原则（建议冻结）

## QP-01

> **Query Understanding 不负责选择工具，只负责形成结构化查询语义。**

## QP-02

> **Knowledge Query Plan 不负责理解自然语言，只负责组织受控的只读检索步骤。**

## QP-03

> **Ontology 是 Query Understanding 的业务语义基础，也是 Graph Retrieval 的执行基础。**

## QP-04

> **RAG、Graph、Keyword、Metadata、Capability 是互补 Retrieval Channel，而不是互相替代。**

## QP-05

> **Graph 优先解决实体与关系；RAG 优先解决原文与解释材料；Capability 优先解决实时/结构化业务数据。**

## QP-06

> **Query Plan 是 Retrieval DAG，不是 Workflow。**

## QP-07

> **一期不允许 Query Plan 直接生成或执行任意 SQL/Cypher/代码。**

## QP-08

> **所有 Plan 必须经过 Schema、Permission、Safety、Cost 四类验证后才能执行。**

## QP-09

> **所有多源回答必须保留 evidence source / source_ref / confidence / validity 等来源信息。**

## QP-10

> **先用固定策略验证架构，再引入 LLM 自适应规划。**

---

# 20. 与当前项目文档的衔接关系

```text
Runtime
  │
  │ Request → Intent → Goal → Plan
  ▼
Planner / Reasoning
  │
  ├── Query Understanding
  │       ↓
  │   Structured Query
  │       ↓
  ├── Knowledge Query Planner
  │       ↓
  │   Knowledge Query Plan
  │       │
  │       ├── Ontology
  │       │     ├── Entity Lookup
  │       │     ├── Profile
  │       │     └── Graph Query
  │       │
  │       ├── Knowledge
  │       │     ├── DD Routing
  │       │     ├── KB Routing
  │       │     ├── Metadata Filter
  │       │     └── Vector / Keyword
  │       │
  │       └── Capability Center
  │             └── Query Capability
  │
  ▼
Evidence Fusion
  │
  ▼
Answer
```

现有设计已经分别具备：

- Runtime 的 Request → Intent → Goal → Plan 生命周期
- DD / KB 软路由
- Ontology 三层检索
- Capability Query / Command 分离
- Capability 与 Entity Type 的显式关联

本文做的是把这些已有能力通过 **Query Understanding + Knowledge Query Plan** 连接成一个可控的融合查询机制，而不是重新建设新的知识系统。fileciteturn3file2turn3file15turn3file7

---

# 21. 本阶段尚未冻结的开放问题

以下问题建议在项目组评审时逐项确认，而不是在实现中自行决定：

1. Query Understanding 是否需要显式增加 `retrieval_need` 一级对象，还是直接由 Planner 从结构化查询推导。
2. `RELATION / MULTI_HOP / CAUSAL` 的关系候选是否必须来自 Ontology，而不允许 LLM 直接发明关系。
3. Query Plan 是否允许同一个 Query 同时存在多个候选 Plan，再通过评分选择。
4. Graph 结果与 RAG 结果在 Evidence Fusion 中是否需要非对称权重。
5. Capability Query 的输出是否统一包装为 Evidence，而不是直接成为 Answer Context。
6. Answer Generation 是否始终需要经过 Evidence Validator，还是仅对高风险/低置信度结果强制验证。
7. Query Plan 是否需要持久化，还是一期仅写入 Execution Trace。
8. 哪些 Query Understanding 字段需要进入后续 Evaluation / Learning 闭环。

---

# 22. 项目组最容易犯的四个错误

### 错误 1：把 Query Understanding 做成 Intent 分类

错误：

```text
query → "查询设备"
```

正确：

```text
query → Entity + Relation + Constraint + Time + Operation + Answer Requirement
```

### 错误 2：让 Query Understanding 直接选工具

错误：

```text
LLM → “调用 graph_query”
```

正确：

```text
LLM → “这是关系查询，需要实体解析和关系证据”
                    ↓
              Query Planner
                    ↓
               graph_query
```

### 错误 3：把 Query Plan 做成 Workflow

知识查询需要的是受限的 Read-only DAG，不应该演化成一个新的通用工作流引擎。

### 错误 4：过早追求全自动 Agent Planner

一期先用固定策略验证：

```text
理解正确
→ Plan 正确
→ Retrieval 正确
→ Answer 正确
```

等四层评估体系跑起来，再逐步让 LLM 参与自适应规划。

---

# 23. 最终目标

EARP 最终不是：

```text
RAG + GraphRAG
```

而是：

```text
                    Enterprise Query
                           │
                           ▼
                 Query Understanding
                           │
                           ▼
                  Retrieval Need
                           │
                           ▼
                Knowledge Query Planner
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          Ontology        RAG        Capability
          Retrieval     Retrieval     Query
             │             │             │
             ▼             ▼             ▼
         Relations       Content      Live Data
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                    Evidence Fusion
                           │
                           ▼
                         Answer
```

最终形成的能力不是“会搜索”，而是：

> **知道一个问题需要什么知识，并能自主选择最合适的知识获取路径。**

这才是 EARP Knowledge Center 从“RAG 检索系统”向“Enterprise Knowledge Retrieval Engine”演进的关键一步。
