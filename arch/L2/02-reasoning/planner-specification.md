# Planner Specification

## EARP 规划器规范

**文档编号：L2-02-PLANNER**
**版本：v1.0**
**定位：L2 — 平台规范。本文定义 Planner 的契约，是 Runtime 推理层的核心组件，负责理解意图、设定目标、生成 Plan。**
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-01-runtime/runtime-specification.md, L2-03-capability/capability-center-specification.md**

---

# 第一章：概述

## 1.1 Planner 的定位

Planner 是 EARP **Reasoning Runtime** 的核心，是平台的"大脑"。它不参与执行、不做决策判断——只负责理解意图、设定目标、生成 Plan。

### 明确边界

**Planner 负责：**
- 理解用户意图（NLU）
- 将意图转化为量化目标（Goal）
- 通过 Resolution Engine 发现和路由 Capability
- 生成 Execution Plan（DAG）
- 执行后反思与重规划

**Planner 不负责：**
- ❌ 执行 Capability（由 Execution Runtime 负责）
- ❌ 决策"是否执行"（由 Decision Engine 负责）
- ❌ 审批/权限判断（由 Policy Engine 负责）
- ❌ Capability 的注册与元数据（由 Capability Center 负责）

## 1.2 范围

| 模块 | 说明 | 章节 |
|------|------|------|
| Planner 核心循环 | 理解 → 规划 → 交付 → 反思 | 第二章 |
| Intent Parsing | 自然语言理解 + 实体提取 | 第三章 |
| Goal Generation | 将 Intent 转化为可量化 Goal | 第四章 |
| Domain Routing & Discovery | 领域路由 + 能力/知识发现（Business Domain + Data Domain 二维决策） | 第五章 |
| Plan Generation | DAG 生成 + 并行优化 | 第六章 |
| Reflection & RePlanning | 执行后反思 + 失败重规划 | 第七章 |
| Planner 类型 | Rule / LLM / Hybrid 模式规范 | 第八章 |
| Planner 与 Runtime 协作 | 执行路径定义 | 第九章 |

本文不涉及：
- Decision Engine 的决策逻辑（由 Decision Specification 定义）
- Capability 的 Resolution 细节（由 Capability Center Specification 定义）
- Execution 的执行细节（由 Runtime Specification 定义）

## 1.3 规范性要求

本文中的"必须（MUST）""应该（SHOULD）""可以（MAY）"按 RFC 2119 解释。

---

# 第二章：Planner 核心循环

```
Planner 处理一次 Request 的完整路径：

Phase 1: Intent Parsing
  输入：原始 Request
  输出：Intent
  依赖：Business Dictionary

Phase 2: Goal Generation
  输入：Intent
  输出：Goal + Constraints
  依赖：Knowledge / Ontology

Phase 3a: Business Domain Routing & Capability Discovery
  输入：Goal
  输出：Business Domain + Candidate Capabilities
  依赖：Resolution Engine

Phase 3b: Data Domain Routing & Knowledge Discovery
  输入：Goal
  输出：Data Domain + Candidate Knowledge
  依赖：Knowledge Center（RAG + Business Dictionary）

Phase 4: Plan Generation
  输入：Goal + Candidates
  输出：Plan（DAG）
  依赖：Capability Graph

Plan Validation（由 Runtime 执行）
  输入：Plan → Valid / Invalid

Phase 5: Execution（由 Execution Runtime 执行）

Phase 6: Reflection（可选）
  输入：Execution Result + Feedback
  输出：Memory / Planner Update
```

### 契约

```
MUST: Planner 所有输出必须通过 Validation 才能交付执行
MUST: 每次 Planner 调用必须产生完整 Trace
SHOULD: 支持降级模式（LLM → Rule）
MUST: Planner 执行时间不超过 30 秒（超时降级到 Rule Planner）
```

---

# 第三章：Intent Parsing

## 3.1 Intent 结构

```
MUST: Intent 包含
  - action:        string    — 用户意图动作
  - object:        string    — 操作对象
  - domain:        string    — 推测的业务领域
  - parameters:    dict      — 提取的参数（SHOULD）
  - confidence:    float 0-1 — 解析置信度（SHOULD）
```

示例：

| 用户输入 | Intent |
|---------|--------|
| "统计昨天所有产线异常" | action: "统计", object: "产线异常", domain: "equipment" |
| "查询库存" | action: "查询", object: "库存", domain: "inventory" |

## 3.2 Business Dictionary

```
MUST: Intent Parsing 使用 Business Dictionary 进行术语映射
  - "异常" → "Alarm"
  - "良率" → "Yield"

MUST: Business Dictionary 支持上下文消歧
  - "异常" 在设备上下文 → EquipmentAlarm
  - "异常" 在质量上下文 → QualityDefect
```

## 3.3 Parsing 模式

```
MUST: 至少支持一种模式
  - Rule-based：关键词匹配 + 规则引擎（Phase 1 默认）
  - LLM-based：LLM Prompt 理解（Phase 2+）

SHOULD: 支持 Hybrid 模式（Rule 置信度 < 阈值时调 LLM）
```

---

# 第四章：Goal Generation

## 4.1 Goal 结构

```
MUST: Goal 包含
  - goal_id:         string    — 全局唯一
  - objective:       string    — 目标描述
  - domain:          string    — 所属领域
  - constraints:     list      — 约束条件（SHOULD）
  - success_criteria: list[str] — 成功标准（SHOULD）
  - priority:        1-5       — 优先级（SHOULD）

MUST: Constraint 包含
  - type:            string    — 约束类型
  - description:     string    — 描述
  - severity:        "hard" | "soft"
```

示例：

```yaml
goal:
  objective: "将 A 类物料库存降低 20%"
  domain: "inventory"
  constraints:
    - type: "policy"
      description: "不能影响交付"
      severity: "hard"
    - type: "resource"
      description: "预算不超过 50 万"
      severity: "hard"
  success_criteria:
    - "库存下降 20%"
    - "交付准时率不低于 99%"
```

## 4.2 约束类型

| 类型 | 说明 |
|------|------|
| time | 时间范围 |
| resource | 资源限制 |
| policy | 策略限制 |
| data | 数据范围 |
| quality | 质量要求 |

## 4.3 生成规则

```
MUST: hard 约束必须满足，否则 Plan 不通过 Validation
SHOULD: soft 约束作为优化目标
```

---

# 第五章：Domain Routing & Discovery（v2.1 更新）

## 5.1 Business & Data Domain Routing（二维决策）

### 5.1.1 Business Domain Routing

```
MUST: Planner 根据 Goal.domain 路由到对应 Business Domain
跨域场景：Goal 含多个 Business Domain → Resolution Engine 分别检索
```

### 5.1.2 Data Domain Routing（v2.1 新增）

```
MUST: Planner 在 Intent Parsing 后同时评估 Data Domain 路由
MUST: Data Domain 路由不通过 Resolution Engine——直接请求 Knowledge Center
MUST: 路由输出为 Data Domain 列表（支持多域并行检索）

Planner → Knowledge Center
  输入：Goal + Data Domain
  输出：KnowledgeResult（匹配文档 / 词条 / 实体 / ABox 事实）
```

> **v1.1 更新（2026-08-07）**：KnowledgeResult 的检索为三层流水线——Ontology 导航（TBox 关系链 → ABox 事实）+ vector 检索（文档 chunks）+ keyword（BM25）。DD 路由（空间裁剪）在前，Ontology 导航（语义线索）并行，详见 arch/design/2026-08-07-ontology-layer-design.md §7。

### 5.1.3 路由判别逻辑

| 用户意图特征 | Business Domain | Data Domain | 路由模式 |
|-------------|:--------------:|:-----------:|---------|
| 包含操作动词（创建/查询/提交） | 路由 | 可选 | 操作优先 |
| 包含知识性措辞（什么是/政策/说明） | 不路由 | 路由 | 知识优先 |
| 两者兼备（分析/比较/评估） | 路由 | 路由 | 混合模式 |
| 无法判断（置信度 < 阈值） | Rule-based 默认路由 | Rule-based 默认路由 | 兜底 |

### 5.1.4 契约

```
MUST: Business Domain 路由和 Data Domain 路由互不阻塞
SHOULD: 混合模式下，两条路径的结果由 LLM 合并
SHOULD: 纯知识模式跳过 Execution Runtime，直接返回 Knowledge Center 结果
MUST: Data Domain 路由失败时（如无可匹配域），不阻塞 Business Domain 路由
MUST: 当两条路由均失败时，返回 LLM 自身知识作为最低兜底
```

### 5.1.5 实体识别与候选收窄（v1.1 新增）

Intent Parsing 的实体提取（§3.1）产出的实体，用于两处：

```
1. Data Domain 路由辅助：
   实体类型（entity_types.kind）→ 所属 Data Domain → 辅助 DD 路由判定

2. Capability 候选收窄（经 capability_entity_map 反查）：
   Intent 实体识别（"CNC-01 高温报警" → equipment 实例 + alarm 意图）
   → capability_entity_map 反查可操作该实体类型的 Capability
   → 候选集从全库缩小到几类 → 再交 Resolution Engine 语义匹配

MUST: 实体识别结果不阻塞路由——识别失败时走原有全库语义匹配
MUST: capability_entity_map 反查结果作为 Resolution Engine 的候选集输入，不替代语义匹配
```

> capability_entity_map 定义见 arch/design/2026-08-07-ontology-layer-design.md §3.3 / §5。

## 5.2 Capability Discovery

```
MUST: Planner 不直接查询 Registry——必须通过 Resolution Engine
MUST: Planner 接收 ResolutionResult 的 selected_capabilities 和 fallback_capabilities

Planner → Resolution Engine
  输入：Goal + Business Domain
  输出：ResolutionResult
```

## 5.3 Graph 辅助选择

```
MUST: Planner 利用 Graph 做以下判断
  - depends_on：按序执行
  - substitutes：首选不可用时替代
  - conflicts_with：互斥不共存
  - composition：组合展开
```

---

# 第六章：Plan Generation

## 6.1 Plan 结构

```
MUST: Plan 包含
  - plan_id:         string    — 全局唯一
  - goal_id:         string    — 关联 Goal
  - tasks:           list[Task]
  - edges:           list[Edge]
  - execution_constraints: dict（SHOULD）

MUST: Task 包含
  - task_id:         string
  - capability_id:   string
  - input:           dict
  - depends_on:      list[string]（SHOULD）
  - timeout:         int（SHOULD）

MUST: Edge 包含
  - from:            string
  - to:              string
```

示例：

```yaml
plan:
  tasks:
    - task_id: "t1"
      capability_id: "query_equipment_alarm"
      input: { start_time: "2026-06-26", end_time: "2026-06-26" }
      depends_on: []
    - task_id: "t2"
      capability_id: "query_maintenance_log"
      input: { date: "2026-06-26" }
      depends_on: []
    - task_id: "t3"
      capability_id: "llm_analysis"
      input: { prompt: "分析报警与维修的关联" }
      depends_on: ["t1", "t2"]
```

## 6.2 Plan 生成规则

```
MUST: Plan 必须是无环图（DAG）
MUST: 每个 Task 引用的 Capability 必须 Active
MUST: 不能包含互斥 Capability（conflicts_with）
SHOULD: 优先利用 parallel_allowed 做并行
SHOULD: 设置 fallback
```

## 6.3 Validation 规则

Validation 由 Runtime 执行，Planner 需理解规则以便生成合规 Plan：

```
检查项：
  - Schema：Task input 符合 Capability Schema
  - Permission：User/Role 有权调用
  - Domain 一致性
  - 无环
  - 资源配额

Rejected 处理：
  - Planner 接收原因
  - 可调整后重新提交（最多 3 次）
  - 超限后降级到 Rule Planner
```

---

# 第七章：Reflection & RePlanning

## 7.1 Reflection

```
MUST: Reflection 可选（默认开启）
SHOULD: 接收原始 Plan + Execution Result + Feedback
SHOULD: 产出 Capability 选择优化 + Plan 结构优化
MUST: 结果存储在 Memory 中
```

## 7.2 RePlanning

```
MUST: 仅在以下条件触发
  - Plan Validation 失败
  - Execution 失败且不可恢复
  - 外部事件要求调整

SHOULD: 复用已成功的 Task 结果
SHOULD: 使用 substitutes 关系
MUST: 不超过 3 次 RePlan
```

## 7.3 学习

```
SHOULD: 支持以下渐进式优化
  - 调用模式学习
  - Evaluation 注入调整 Capability 排序
  - 反馈循环更新 Graph 权重

MUST: 学习结果不影响当前 Execution，下次生效
```

---

# 第八章：Planner 类型

## 8.1 Rule Planner（Phase 1 默认）

```
MUST: 基于预定义规则
SHOULD: 覆盖固定模式查询、简单单步操作、预定义组合流程
MUST: 不需要 LLM 调用
MUST: 执行时间不超过 5 秒
```

## 8.2 LLM Planner（Phase 2+）

```
MUST: 使用 LLM 进行动态推理
SHOULD: 附带 Domain + Capability 列表 + Graph 关系作为上下文
MUST: 输出必须经过 Plan Validation
MUST: 输出需 LLM 置信度评分
  - < 0.7 → 标记人工确认
  - < 0.4 → 降级 Rule Planner
```

## 8.3 Hybrid Planner（Phase 2+）

```
SHOULD: 同时使用 Rule 和 LLM
  - 匹配明确规则 → Rule
  - 意图模糊/跨域 → LLM
  - LLM 失败 → Rule 兜底
```

## 8.4 Self-Reflection Planner（Phase 3+）

```
SHOULD: 每次 Execution 后反思，自动调整 Graph 权重
```

---

# 第九章：Planner 与 Runtime 协作

```
Coordination Runtime → Planner → Plan Validation → Execution Runtime
                          ↑                             │
                          └── RePlanning ←──────────────┘
```

## 接口契约

```
Planner Input:
  - request:        RuntimeRequest
  - context:        RuntimeContext
  - business_dict:  BusinessDictionary
  - resolution:     ResolutionEngine

Planner Output:
  - plan:           Plan（DAG）
  - confidence:     float 0-1
```

---

# 附录 A：与 Concept Model 的对应关系

| Concept Model | 本规范章节 |
|-------------|-----------|
| Intent | 第三章 |
| Goal | 第四章 |
| Constraint | 4.2 |
| Plan | 第六章 |
| Task | 6.1 |
| Capability Graph | 5.3、6.2 |
| Knowledge | 3.2 |

---

# 附录 B：与其他规范的对应关系

| 规范 | 本规范章节 |
|------|-----------|
| Capability Center Spec — Resolution Engine | 第五章 |
| Capability Center Spec — Capability Graph | 5.3 |
| Runtime Spec — Plan Validation | 6.3 |
| Runtime Spec — Execution | 第九章 |
