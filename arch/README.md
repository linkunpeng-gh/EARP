# EARP 架构文档索引

Enterprise AI Runtime Platform 架构文档体系说明。

---

# 文档层次

```
L0  架构思想层  — 设计理念与原则
L1  架构设计层  — 系统架构与概念模型
L2  平台规范层  — 各模块的契约规范
```

---

# L0 — 架构思想层

| 文档 | 说明 |
|------|------|
| **design-philosophy.md** | EARP 的 9 条核心理念：Runtime First、Domain First、Capability First、Reason-Act 解耦、CQRS、Closed-loop Intelligence。新人从这里开始，一天理解平台。 |

---

# L1 — 架构设计层

| 文档 | 说明 |
|------|------|
| **architecture-v5.md** | 系统总体架构。三引擎（Reasoning / Execution / Coordination）、九层分层、价值图、版本演进（EARP 1.0 → 4.0）。 |
| **concept-model-v1.3.md** | 核心概念模型。定义 27 个核心对象及其关系，所有 L2 规范的术语来源。 |

---

# L2 — 平台规范层

## 01-runtime

| 文档 | 说明 |
|------|------|
| **runtime-specification.md** | 运行时核心规范。Session（外层容器）、Context、Lifecycle、Event、Execution（Step/Retry/Checkpoint/Compensation）、Business Transaction、Resource、Feedback & Learning、Memory（附录 A）。L2 体系的核心依赖。 |
| **eventbus-specification.md** | 事件总线规范。CloudEvents 2.0 格式、30+ 事件类型、发布/订阅契约、持久化与回放、死信队列。 |

## 02-reasoning

| 文档 | 说明 |
|------|------|
| **planner-specification.md** | 规划器规范。Intent Parsing → Goal Generation → Domain Routing → Capability Discovery → Plan Generation（DAG）→ Reflection & RePlanning。Rule / LLM / Hybrid 三种模式。 |
| **decision-engine-specification.md** | 决策引擎规范。执行中的实时分支选择。Rule（确定性）/ LLM（分析型）/ ML（预测型）三种来源。明确定义与 Policy/Approval 的边界。 |
| **knowledge-center-specification.md** | 知识中心规范。Business Dictionary（企业术语映射）、RAG、Ontology、Semantic Index、Capability Metadata、Prompt Library。 |

## 03-capability

| 文档 | 说明 |
|------|------|
| **capability-center-specification.md** | 能力中心规范。三层结构（Definition/Execution Contract/Policy）、CQRS、Capability Graph（语义+执行约束）、Resolution Engine、Health。附录 C 定义 Connector 基类契约和 MCP 映射规则。 |

## 04-execution

| 文档 | 说明 |
|------|------|
| **workflow-specification.md** | 工作流规范。Workflow 是 Runtime 的一种执行模式。DSL 结构、11 种节点类型、编译为 Plan、闭环机制。 |
| **agent-specification.md** | Agent 规范。Agent 是 Runtime 的消费者。ReAct / Function Calling / Planning 三种模式。闭环机制（内循环+外循环）。Multi-Agent 协作。 |
| **scheduler-specification.md** | 调度器规范。Coordination Runtime 的一部分。5 种 Trigger（cron/event/webhook/message/condition）。 |
| **resource-specification.md** | 资源规范。管理 LLM / Sandbox / Python / Browser / GPU 等底层执行资源。生命周期和配额。 |

## 05-governance

| 文档 | 说明 |
|------|------|
| **policy-center-specification.md** | 策略中心规范。6 种策略（RBAC / Rate Limit / Data Scope / Approval / Time Restriction / Cost Limit）。评估时机和绑定规则。 |
| **audit-specification.md** | 审计规范。统一格式、30+ 事件、各模块审计要求、存储保留（30-180 天）、哈希链防篡改、决策链溯源。 |
| **observation-specification.md** | 可观测性规范。Metrics（4 类 14 个指标）、Trace（OpenTelemetry）、Logging（JSON 结构化）、告警规则。 |

---

# 文档统计

| 层级 | 文档数 | 行数 |
|------|:----:|:----:|
| L0 | 1 | ~170 |
| L1 | 2 | ~1,800 |
| L2 | 13 | ~3,400 |
| **合计** | **16** | **~5,400** |

---

# 阅读建议

| 读者 | 顺序 |
|------|------|
| 新成员 | design-philosophy → concept-model → runtime-spec |
| 架构师 | L0 → L1 → L2 全部 |
| Runtime 开发者 | runtime-spec → eventbus-spec |
| Capability 开发者 | capability-center-spec → runtime-spec(Execution) |
| Planner 开发者 | planner-spec → capability-center-spec(Resolution Engine) |
| Agent 开发者 | agent-spec → planner-spec → runtime-spec |
| 运维/安全 | governance 三份 |
