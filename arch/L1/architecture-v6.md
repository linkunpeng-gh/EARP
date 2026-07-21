# Enterprise AI Runtime Platform（EARP）
# 架构设计 v6.0

> 基于 v5.0 架构评审（2026-06-29）反馈优化。
> **核心变更**：
> 1. 设计原则体系统一 —— L0 哲学原则与 L1 架构原则建立映射关系
> 2. Execution Runtime 职责收窄 —— Approval Manager 合并至 Policy Center，Human Task Manager 移至 Coordination Runtime
> 3. Kernel Layer 重构 —— 拆分为 Infra Layer / Resource Layer / 独立 Centers
> 4. Feedback/Evaluation 架构归属明确 —— Feedback Collector 归 Execution Runtime，Evaluation Center 独立
> 5. 错误处理章节补全 —— 统一错误码、错误响应格式
> 6. CloudEvents 版本修正
> 7. 事件类型集中管理 —— 由 EventBus 规范定义唯一事件类型注册表
>
> 定位：**L1（Architecture）基线文档**，目标支撑 5-10 年持续迭代。

---

# 第一章：产品定位与设计原则

## 1.1 产品定位

Enterprise AI Runtime Platform（EARP）是一套面向**企业数字化与智能化场景**的 AI Runtime 平台。

平台不是聊天机器人，不是 Workflow 编辑器，不是 BPM 引擎，而是**企业 AI 的统一运行平台**——覆盖从"问"到"想"到"做"的完整链路。

## 1.2 设计原则体系

EARP 的设计原则分两层——**L0 哲学原则**回答"为什么这样设计"，**L1 架构原则**回答"架构上怎么落地"。两者一体两面，共同构成完整的设计约束。

### L0 哲学原则（来源：design-philosophy.md）

| # | 原则 | 核心主张 |
|---|------|---------|
| P1 | Runtime First | 所有执行统一入口，禁止直连 LLM/Capability/外部系统 |
| P2 | Domain First | AI 先理解业务领域，再操作能力 |
| P3 | Capability First | AI 调用业务能力（做什么），不直接调 Tool（怎么调） |
| P4 | Reason-Act 解耦 | 推理可高频迭代，执行必须极度稳定 |
| P5 | CQRS for Enterprise | Query 无副作用，Command 必经审批 |
| P6 | Closed-loop Intelligence | 持续反馈 → 评估 → 学习 → 优化 |
| P7 | Workflow ≠ Runtime | Workflow 是执行模式，Runtime 是执行引擎 |
| P8 | Agent ≠ Planner | Agent 是消费者，利用 Planner 但管理自身生命周期 |
| P9 | 规范 ≠ 文档 | L2 契约定义平台规范，不是开发文档 |

### L1 架构原则（架构落地约束）

| # | 原则 | 落地约束 | 对应 L0 |
|---|------|---------|:-------:|
| A1 | Runtime First | 三引擎（Reasoning/Execution/Coordination）对外统一接受 Request | P1 |
| A2 | Domain First | Planner 先路由 Business Domain（→ Capability）和 Data Domain（→ Knowledge），二维并行决策 | P2 |
| A3 | Capability First | Capability 封装业务语义，隐藏底层 Tool/Connector | P3 |
| A4 | Reason-Act 解耦 | Reasoning Runtime 与 Execution Runtime 独立部署、独立迭代 | P4 |
| A5 | CQRS | Capability 分为 Query（绕过审批）和 Command（必经审批） | P5 |
| A6 | Event Driven | Runtime 内部模块通过 EventBus 异步通信 | — |
| A7 | Adapter Pattern | 所有外部系统经 Connector 接入，Runtime 不感知 | P3 |
| A8 | Plugin First | 所有 Capability 可通过 SPI 插件化注册 | P3 |
| A9 | Stateless Runtime | 三个 Runtime 无状态，状态外置到 Infra Layer | — |
| A10 | Closed-loop | Feedback → Evaluation → Knowledge/Memory → Planner | P6 |

> **说明**：L1 原则 A6 Event Driven、A9 Stateless Runtime 是架构层面的基础设施决策，属于 L0 原则的补充而非派生。L0 P7/P8/P9 是产品原则和文档原则，不直接映射为架构原则，但在 L2 规范中有对应体现。

## 1.3 关键架构决策（ADRs）

### ADR-001：Runtime 三引擎拆分

| 决策 | 值 |
|------|-----|
| Reasoning Runtime | 负责：理解、推理、规划、反思、重规划 — AI 密集 |
| Execution Runtime | 负责：调用 Capability、事务、补偿、回滚、重试 — 稳定优先 |
| Coordination Runtime | 负责：Multi-Agent 协调、人机交互、Event/Workflow 协调 |
| 状态位置 | 全部外置到 Infra Layer |
| 解耦原则 | Reasoning 可高频升级，Execution 必须极度稳定（P4） |

### ADR-002：Capability CQRS

| 决策 | 值 |
|------|-----|
| Query Capability | 无副作用，绕过审批，直接查询（如：查询库存） |
| Command Capability | 有副作用，必须经过 Policy → Approval → Audit（如：创建工单） |
| 实施原则 | Runtime 必须区分 Query 和 Command，不可混用 |

### ADR-003：Business Transaction

| 决策 | 值 |
|------|-----|
| Transaction Scope | 跨多个 Capability 调用的业务操作视为一个 Business Transaction |
| 一致性模型 | Saga 模式（非分布式事务）— 每个 Step 有补偿动作 |
| Process Instance | 长期运行（小时/天/周）的业务流程作为 Process Instance 管理 |

### ADR-004（新增）：Execution Runtime 职责收窄

| 决策 | 值 |
|------|-----|
| 决策内容 | Execution Runtime 只做三件事：Run Task、Guarantee Consistency、Handle Failure |
| 移出模块 | Approval Manager → Policy Center (P5 Governance 统一管理) |
| 移出模块 | Human Task Manager → Coordination Runtime |
| 保留模块 | Orchestrator、Transaction Manager、Compensation Manager、Retry/Timeout Manager |
| 新增模块 | Feedback Collector（仅收集，不分析）|
| 动机 | 评审反馈 v1.1 #4 — Execution 过载，需收窄职责保证"极度稳定" |

### ADR-005（新增）：Kernel Layer 重构

| 决策 | 值 |
|------|-----|
| 决策内容 | 原 Kernel Layer 拆为三个子层 |
| Infra Layer | EventBus、Context Manager、State Machine、Checkpoint Manager（有状态基础设施）|
| Resource Layer | Resource Manager、Lifecycle Manager |
| 独立 Centers | Policy Center、Knowledge Center、Observation Center、Evaluation Center、Artifact Center |
| 动机 | 评审反馈 v5.0 #S2 — Kernel 承载 11 个组件，过于混杂 |

### ADR-006（新增）：Feedback/Evaluation 归属

| 决策 | 值 |
|------|-----|
| Feedback Collector | 归属 Execution Runtime（执行时收集原始数据） |
| Evaluation Center | 独立模块（分析 Feedback 产出评估结论） |
| Learning Injector | 归属 Knowledge Center（将评估结果写入 Knowledge/Memory） |
| 动机 | 评审反馈 v5.0 #S3 — Feedback/Evaluation 在三处位置定义不一致 |

---

# 第二章：平台价值图

> 与 v5.0 第 2 章一致，但将 Feedback 闭环层独立为一层（不再内嵌在 Execution 中）。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Enterprise AI Runtime Platform                      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   用户直接看到什么 ？                                  │   │
│  │                                                                      │   │
│  │     Chat / 对话       Workflow / 流程        Agent / 智能体           │   │
│  │     Ask（问）         编排（做）              自主（想+做）             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                  │                                          │
│                                  ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   核心引擎是什么 ？                                    │   │
│  │                                                                      │   │
│  │  ┌────────────────┐  ┌──────────────────┐  ┌────────────────────┐   │   │
│  │  │  Reasoning     │  │  Execution       │  │  Coordination     │   │   │
│  │  │  Runtime       │  │  Runtime         │  │  Runtime          │   │   │
│  │  │                │  │                  │  │                   │   │   │
│  │  │ Intent Planner │  │ Orchestrator     │  │ Multi-Agent 协调  │   │   │
│  │  │ Task Planner   │  │ Transaction      │  │ 人机交互          │   │   │
│  │  │ Reflection     │  │ Compensation     │  │ Human Task 管理   │   │   │
│  │  │ RePlanning     │  │ Retry/Timeout    │  │ Event 编排        │   │   │
│  │  │ Goal/Constraint│  │ Feedback Collector│ │ Workflow 协调     │   │   │
│  │  │                │  │                  │  │                   │   │   │
│  │  │ AI 密集        │  │ 极度稳定         │  │ 协调者            │   │   │
│  │  │ 高频迭代       │  │                 │  │                   │   │   │
│  │  └────────────────┘  └──────────────────┘  └────────────────────┘   │   │
│  │                                                                      │   │
│  │    Reasoning 与 Execution 彻底解耦 —— 互不依赖                         │   │
│  │                   │                                                   │   │
│  │                   ▼                                                   │   │
│  │          ┌────────────────────────────┐                               │   │
│  │          │  Evaluation Center         │                               │   │
│  │          │  (独立模块：分析 Feedback， │                               │   │
│  │          │   产出评估结论)            │                               │   │
│  │          └───────────┬────────────────┘                               │   │
│  │                      ▼                                                │   │
│  │          ┌────────────────────────────┐                               │   │
│  │          │  Knowledge Center          │                               │   │
│  │          │  (接收评估结果 → 优化      │                               │   │
│  │          │   Memory/Planner)          │                               │   │
│  │          └────────────────────────────┘                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                  │                                          │
│                                  ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   平台积累了什么核心资产 ？                            │   │
│  │                                                                      │   │
│  │  ┌────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐     │   │
│  │  │ Capability │  │ Knowledge│  │  Policy  │  │ Observation  │     │   │
│  │  │  Center    │  │  Center  │  │  Center  │  │   Center     │     │   │
│  │  │            │  │          │  │          │  │              │     │   │
│  │  │ Query/     │  │ RAG/     │  │ RBAC/    │  │ Trace/       │     │   │
│  │  │ Command    │  │ Dict/    │  │ 限流/    │  │ Metrics/     │     │   │
│  │  │ 注册/发现  │  │ Ontology │  │ 审批     │  │ Replay       │     │   │
│  │  └────────────┘  └──────────┘  └──────────┘  └──────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                  │                                          │
│                                  ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   能连接什么系统 ？                                    │   │
│  │                                                                      │   │
│  │   ERP   │   MES   │   CRM   │  SCADA  │   MCP   │   OA    │   DB   │   │
│  │  SAP/金蝶│  生产   │  客户    │  设备    │  AI协议  │  审批   │  数据库 │   │
│  │  用友    │  执行    │  关系    │  控制    │  接入    │  协同   │        │   │
│  │                                                                      │   │
│  │              所有系统经过 Connector，Runtime 不感知                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                  │                                          │
│                                  ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   跑在什么基础设施上 ？                                │   │
│  │                                                                      │   │
│  │   PostgreSQL    │    Redis    │    Kafka    │   MinIO/S3   │   K8s   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

# 第三章：总体架构

## 3.1 系统分层（v6.0 更新）

架构从 v5.0 的 9 层演进为 v6.0 的 **11 层**，核心变化：
1. 原 Kernel Layer 拆分为 Infra Layer + Resource Layer + 独立 Centers
2. Execution Runtime 职责收窄（Approval Manager → Policy Center, Human Task Manager → Coordination Runtime）
3. Feedback/Evaluation 从 Execution Runtime 移出

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER                                                           │
│  Chat / Workflow Studio / Agent Studio / Knowledge Base                      │
│  Dashboard / Playground / Prompt Center / SDK / API Gateway                  │
│  ── 不负责执行，所有执行委托给 Runtime ──                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│  COORDINATION LAYER（无状态，水平扩展）                                       │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     Coordination Runtime                             │   │
│  │                                                                      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │   │
│  │  │ Multi-Agent  │  │ Human-in-    │  │ Workflow / Event 编排    │   │   │
│  │  │ 协调器        │  │ the-loop     │  │                          │   │   │
│  │  │              │  │ 管理器        │  │ Agent↔Workflow 协调      │   │   │
│  │  │ Agent A↔B↔C  │  │ 暂停/审批/   │  │                          │   │   │
│  │  │ 任务分配     │  │ 驳回/恢复    │  │ Scheduler 触发           │   │   │
│  │  │              │  │              │  │                          │   │   │
│  │  │              │  │ Human Task   │  │                          │   │   │
│  │  │              │  │ 管理/催办    │  │                          │   │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────────────┤
│  REASONING LAYER（无状态，水平扩展，AI 密集）                                │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     Reasoning Runtime                                │   │
│  │                                                                      │   │
│  │  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────────┐   │   │
│  │  │  Intent Planner  │  │ Task Planner │  │ Reflection / RePlan  │   │   │
│  │  │                  │  │              │  │                      │   │   │
│  │  │  NLU → 实体提取  │  │ Plan 生成    │  │ 执行结果反思         │   │   │
│  │  │  Domain 路由      │  │ (DAG)        │  │ 计划调整             │   │   │
│  │  │  Business Dict   │  │ 任务分解      │  │ 失败重规划           │   │   │
│  │  │  Capability 选择  │  │ 并行优化      │  │                      │   │   │
│  │  └─────────────────┘  └──────────────┘  └──────────────────────┘   │   │
│  │                                                                      │   │
│  │  ↓ 输出: Execution Plan（不涉及具体执行）                               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────────────┤
│                    Plan Validation Layer                                      │
│         Schema │ 权限 │ Domain 一致性 │ 循环检测 │ 深度限制 │ 配额            │
│         (Policy Center 负责策略评估)                                         │
├──────────────────────────────────────────────────────────────────────────────┤
│  EXECUTION LAYER（无状态，水平扩展，极度稳定）                                │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     Execution Runtime（v6.0 职责收窄）               │   │
│  │                                                                      │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────┐                 │   │
│  │  │ Orchestrator│  │  Transaction  │  │  Compensation │                 │   │
│  │  │             │  │  Manager     │  │  Manager     │                 │   │
│  │  │ 步骤编排    │  │  Saga 事务   │  │  补偿动作    │                 │   │
│  │  │ 流程控制    │  │  一致性保证  │  │  回滚        │                 │   │
│  │  └────────────┘  └──────────────┘  └──────────────┘                 │   │
│  │  ┌────────────┐  ┌────────────────┐  ┌─────────────────────┐       │   │
│  │  │ Decision   │  │  Retry /       │  │  Process            │       │   │
│  │  │ Engine     │  │  Timeout       │  │  Instance Manager   │       │   │
│  │  │            │  │  Manager       │  │                     │       │   │
│  │  │ Rule/LLM/  │  │ 重试策略      │  │ 长流程/Checkpoint   │       │   │
│  │  │ ML 决策    │  │ 超时熔断      │  │                     │       │   │
│  │  └────────────┘  └────────────────┘  └─────────────────────┘       │   │
│  │  ┌────────────────────────────┐                                    │   │
│  │  │  Feedback Collector        │   ← 新增：仅收集，不分析           │   │
│  │  │  (执行结果 → 原始数据)     │                                    │   │
│  │  └────────────────────────────┘                                    │   │
│  │                                                                      │   │
│  │  ↓ 执行 Capability（经过 Decision → Policy → Audit）                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Evaluation Center（新增独立模块）                                   │   │
│  │                                                                      │   │
│  │  ┌────────────────────┐  ┌──────────────────────┐                    │   │
│  │  │  Evaluation        │  │  Learning Injector   │                    │   │
│  │  │  Analyzer          │  │                      │                    │   │
│  │  │                    │  │  评估结果 →          │                    │   │
│  │  │  分析 Feedback     │  │  Memory/Knowledge/   │                    │   │
│  │  │  产出评估结论      │  │  Planner             │                    │   │
│  │  └────────────────────┘  └──────────────────────┘                    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────────────┤
│  DOMAIN LAYER（业务领域路由）                                                │
│                                                                              │
│  Production │ Equipment │ Inventory │ Quality │ Order │ Finance │ ……         │
│  Domain Repository（领域 → Capability 映射表）                               │
├──────────────────────────────────────────────────────────────────────────────┤
│  CAPABILITY LAYER（CQRS 模式）                                               │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     Capability Center                                │   │
│  │  Registry │ Discovery │ Version │ Health │ Metrics                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────┐  ┌──────────────────┐                                │
│  │   Query          │  │   Command        │                                │
│  │   Capability     │  │   Capability     │                                │
│  │                  │  │                  │                                │
│  │  查询库存        │  │  创建工单        │                                │
│  │  查询报警        │  │  审批采购        │                                │
│  │  查询订单        │  │  关闭设备        │                                │
│  │                  │  │  发送消息        │                                │
│  │  无副作用        │  │  有副作用        │                                │
│  │  绕过审批        │  │  必经 Policy     │                                │
│  └────────┬─────────┘  └────────┬─────────┘                                │
│           │                     │                                           │
│           ▼                     ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Service 层                                                          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│           │                                                                  │
│           ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Connector 层（MES / SAP / Database / MQTT / MCP / ……）              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────────────┤
│  POLICY LAYER（v6.0 从 Kernel 提升）                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Policy Center                                                        │   │
│  │  RBAC │ Rate Limit │ Data Scope │ Approval(含审批) │ Time │ Cost     │   │
│  │                                                                        │   │
│  │  v6.0 变更：合并原 Execution Runtime 的 Approval Manager                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────────────┤
│  INFRA LAYER（有状态基础设施）— v6.0 从 Kernel 拆分                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐                │
│  │ Context  │ │ State    │ │ EventBus │ │ Checkpoint     │                │
│  │ Manager  │ │ Machine  │ │          │ │ Manager        │                │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘                │
│  ┌──────────┐ ┌──────────┐                                                │
│  │ Resource │ │ Lifecycle│                                                │
│  │ Manager  │ │ Manager  │                                                │
│  └──────────┘ └──────────┘                                                │
├──────────────────────────────────────────────────────────────────────────────┤
│  CENTERS（独立业务/资产层）— v6.0 从 Kernel 提升为独立层                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐   │
│  │ Knowledge    │ │ Observation  │ │ Evaluation   │ │ Artifact         │   │
│  │ Center       │ │ Center       │ │ Center       │ │ Center           │   │
│  │              │ │              │ │              │ │                  │   │
│  │ Business Dict│ │ Metrics      │ │ 分析         │ │ 报表/Excel/图片  │   │
│  │ RAG/Ontology │ │ Trace/Log    │ │ Feedback     │ │ SQL 结果         │   │
│  │ Cap Meta     │ │ Alert        │ │ Learning     │ │ 跨模块共享       │   │
│  │ Prompt Lib   │ │              │ │ 注入         │ │                  │   │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 3.2 架构主链

```
v6.0 核心路径（含闭环，v2.1 新增 Data Domain 知识路径）：

Application
    ↓
Coordination Runtime（协调：Multi-Agent + Human Task/人机交互 + 事件/Scheduler）
    ↓
Reasoning Runtime（推理：Intent + Goal/Constraint → Plan）
    │
    │── Plan Validation Layer（校验 — Policy Center 参与策略评估）
    │
    │── Domain Routing（二维决策 — v2.1 新增）
    │   ├── Business Domain → Capability Center → Service → Connector → System
    │   │                                （操作路径：执行具体业务能力）
    │   │
    │   └── Data Domain → Knowledge Center（RAG/Dictionary/Ontology）
    │                                    （知识路径：检索企业知识）
    │
    │── 合并结果 → Plan → Execution Runtime
    │            （执行：Orchestrator → Decision → Transaction/Capability）
    │
    ├──→ Feedback Collector → Evaluation Center → Knowledge Center → Planner
    │                                                               (闭环)
    │
    └──→ Policy Center（Plan Validation + 运行时治理）
```

## 3.3 三引擎职责边界（v6.0 更新）

| 维度 | Reasoning Runtime | Execution Runtime | Coordination Runtime |
|------|------------------|------------------|---------------------|
| 职责 | 理解/推理/规划 | 可靠执行/事务/补偿 | 协调/编排/人机交互 |
| AI 依赖度 | 高（LLM 是核心） | 低（LLM 可选） | 中（LLM 辅助决策） |
| 变更频率 | 高（模型/策略迭代） | **极低（稳定优先）** | 中 |
| 核心能力 | NLU / Planner / Reflection | Orchestrator / Transaction / Retry / Saga / Compensation / Decision | Multi-Agent / Human-in-the-loop / Human Task / Event / Scheduler |
| 失败影响 | 重新规划 | **业务数据一致性** | 协调失败 |
| 扩容依据 | GPU 密集 | CPU 密集 | 连接数 |
| 产出 | Execution Plan | Execution Result | 协调完成的最终结果 |

> v6.0 变更：Execution Runtime 移除了 Approval Manager（归 Policy Center）和 Human Task Manager（归 Coordination Runtime），专注执行可靠性和一致性。

---

# 第四章：Reasoning Runtime

> 与 v5.0 第 4 章一致。

> **v2.1 更新**：Planner 的 Domain Routing 从单一路径扩展为二维并行决策。
>
> ### Domain Routing 二维决策（v2.1 新增）
>
> 在 Intent Parsing 和 Goal Generation 完成后，Planner 不再只路由到一个 Business Domain，而是同时完成两个维度的路由：
>
> ```
> Intent → Goal
>     │
>     ├── Business Domain Routing
>     │   └──→ Resolution Engine → Candidate Capabilities（操作路径）
>     │
>     └── Data Domain Routing
>         └──→ Knowledge Center → Candidate Knowledge（知识路径）
> ```
>
> ### 决策规则
>
> | 用户意图类型 | Business Domain 路由 | Data Domain 路由 | 示例 |
> |-------------|:-------------------:|:----------------:|------|
> | 纯知识查询 | 不路由 | 路由 | "休假政策是什么？" |
> | 纯操作请求 | 路由 | 不路由 | "创建工单" |
> | 知识+操作混合 | 路由 | 路由 | "分析近期报警趋势并对比安全标准" |
>
> ### 契约
>
> ```
> MUST: Planner 在 Intent Parsing 后同时评估是否路由 Business Domain 和 Data Domain
> MUST: 两个路由决策互不阻塞（一个失败不影响另一个）
> SHOULD: 混合模式时，两条路径的结果由 LLM 合并为统一回答
> MAY: 纯知识查询跳过 Execution Runtime，直接返回 Knowledge Center 结果
> ```

---

# 第五章：Execution Runtime（v6.0 职责收窄）

## 5.1 定位

Execution Runtime 是平台的 **"手"**，负责一切需要可靠执行的活动。

**Execution Runtime 只做三件事：**
1. **Run Task** — Orchestrator 编排并执行 Step
2. **Guarantee Consistency** — Transaction Manager 保证 Saga 事务一致性
3. **Handle Failure** — Retry/Timeout 管理重试和超时，Compensation Manager 处理回滚

## 5.2 核心模块

```
Execution Runtime（v6.0 职责收窄）
│
├── Orchestrator
│   ├── Step Runner（按序/并行执行 Step）
│   ├── Flow Controller（条件/循环/分支）
│   └── Process Instance Manager（长流程实例管理）
│
├── Decision Engine
│   ├── Rule-based（IF 库存 < 安全库存 THEN 采购）
│   ├── LLM-based（IF 异常原因不明 THEN 调用 LLM 分析）
│   └── ML-based（IF 预测良率 < 阈值 THEN 提前干预，Phase 3）
│
├── Transaction Manager
│   ├── Saga Coordinator（Saga 事务协调）
│   ├── TCC（Try-Confirm-Cancel）
│   └── Consistency Checker
│
├── Compensation Manager
│   ├── Compensating Action Registry
│   ├── Rollback Executor
│   └── Partial Success Handler
│
├── Retry / Timeout Manager
│   ├── Retry Strategy（固定/指数退避/自定义）
│   ├── Timeout Control（每个 Step 独立超时）
│   └── Circuit Breaker（连续失败 N 次后熔断）
│
└── Feedback Collector（新增 — 仅收集执行结果原始数据）
    ├── 执行结果（成功/失败/耗时）
    ├── 用户评价（满意/不满意）
    └── 运行时指标
```

> **v6.0 移出模块**：
> - ~~Approval Manager~~ → 合并至 Policy Center（审批是策略评估的一部分）
> - ~~Human Task Manager~~ → 移至 Coordination Runtime（人机交互是协调职责）
> - ~~Feedback/Evaluation（分析部分）~~ → 独立为 Evaluation Center

## 5.3 Business Transaction 示例

> 与 v5.0 第 5.3 节一致。

---

# 第六章：Coordination Runtime（v6.0 扩展）

## 6.1 定位

> v6.0 新增 Human Task Manager，移入原 Execution Runtime 的人机交互职责。

```
Coordination Runtime（v6.0 扩展）
│
├── Multi-Agent Coordinator
│   ├── Agent 注册与发现
│   ├── 任务分配
│   ├── 信息交换
│   └── 冲突解决
│
├── Human-in-the-loop Manager
│   ├── 暂停/恢复
│   ├── 审批/驳回
│   ├── 人工输入
│   └── 升级/催办
│
├── Human Task Manager（v6.0 从 Execution Runtime 移入）
│   ├── Task Assignment
│   ├── Deadline Management
│   ├── Escalation（超时→通知上级）
│   └── Delegation
│
├── Workflow Coordination
│   ├── Agent ↔ Workflow 双向调用
│   └── 死锁检测
│
└── Event Coordination
    ├── Event → Agent 触发
    ├── Event → Workflow 触发
    └── Event → Scheduled 触发
```

---

# 第七章：Capability CQRS

> 与 v5.0 第 7 章一致。

---

# 第八章：错误处理（v6.0 补全）

## 8.1 错误分类

| 类别 | 说明 | 示例 | 处理方式 |
|------|------|------|---------|
| 系统错误 | Runtime 内部错误 | DB 连接失败、EventBus 不可用 | 告警 + 熔断 + 自动恢复 |
| 资源错误 | 执行资源不可用 | LLM 超时、Sandbox OOM | 降级 + 重试 + 回退 |
| 业务错误 | Capability 执行失败 | 创建工单失败、库存不足 | 补偿 + 通知 + 人工介入 |
| 策略错误 | 策略检查不通过 | 权限不足、超过限流 | 拒绝 + 返回错误原因 |
| 超时错误 | 执行超过时间限制 | Plan 超时 30s、Capability 超时 | 熔断 + 降级 + 告警 |
| 数据错误 | 数据格式或一致性错误 | Capability 输入 Schema 校验失败 | 拒绝 + 返回校验详情 |

## 8.2 统一错误码体系

所有模块返回的错误必须使用统一错误码格式：

```
错误码格式：ERR-[模块]-[错误类型]-[编号]
             │       │        │       │
             │       │        │       └── 3 位数字编号 (001-999)
             │       │        │
             │       │        └── RUNTIME / RESOURCE / BUSINESS /
             │       │            POLICY / TIMEOUT / DATA / INTERNAL
             │       │
             │       └── 2 位字母模块代码
             │           RT=Runtime  PL=Planner  DE=Decision
             │           CP=Capability  WF=Workflow  AG=Agent
             │           SC=Scheduler  PO=Policy  AU=Audit
             │           RS=Resource  EV=Evaluation
             │
             └── 固定前缀 "ERR"
```

### 通用错误码

| 错误码 | HTTP 等价 | 说明 |
|--------|:---------:|------|
| ERR-RT-INTERNAL-001 | 500 | Runtime 内部未知错误 |
| ERR-RT-TIMEOUT-002 | 504 | Execution 超时 |
| ERR-RT-RESOURCE-003 | 503 | 资源不可用（LLM / Sandbox 等）|
| ERR-PL-VALIDATION-001 | 400 | Plan 校验失败 |
| ERR-DE-NO-BRANCH-001 | 400 | 决策无匹配分支（使用默认分支）|
| ERR-CP-NOT-FOUND-001 | 404 | Capability 不存在或未注册 |
| ERR-CP-SCHEMA-002 | 400 | Capability 输入参数校验失败 |
| ERR-CP-EXECUTION-003 | 500 | Capability 执行失败 |
| ERR-PO-DENIED-001 | 403 | 策略拒绝（权限/限流/数据范围）|
| ERR-PO-APPROVAL-002 | 403 | 待审批未完成 |
| ERR-WF-COMPILE-001 | 400 | Workflow DSL 编译失败 |
| ERR-AG-MAX-ITER-001 | 400 | Agent 达到 max_iterations 上限 |

## 8.3 统一错误响应格式

所有 Runtime API 的错误响应格式：

```json
{
  "error": {
    "code": "ERR-RT-INTERNAL-001",
    "message": "Runtime 内部未知错误",
    "details": {
      "execution_id": "exec_001",
      "step_id": "step_3"
    },
    "suggestion": "请稍后重试",
    "trace_id": "trace_abc123"
  }
}
```

| 字段 | 必须 | 说明 |
|------|:----:|------|
| error.code | MUST | 统一错误码 |
| error.message | MUST | 人类可读的错误描述 |
| error.details | SHOULD | 错误上下文（execution_id、step_id、capability_id 等）|
| error.suggestion | SHOULD | 用户操作建议（"请稍后重试""联系管理员"）|
| error.trace_id | MUST | 关联 Trace（用于运维排查）|

## 8.4 三引擎失败模式

| 故障 | Reasoning | Execution | Coordination |
|------|-----------|-----------|--------------|
| LLM 超时 | 回退 Rule Planner | 无影响 | 降级默认策略 |
| Capability 失败 | 触发 RePlanning | 执行补偿/回滚 | 通知协调者 |
| Process Instance 中断 | 无影响 | Checkpoint 恢复 | 重新协调 |
| 审批超时 | 无影响 | 升级/催办 | 通知人员 |
| Saga 补偿失败 | 无影响 | 标记人工介入 | 创建人工任务 |

## 8.5 降级路径

| 场景 | 正常路径 | 降级路径 |
|------|---------|---------|
| LLM Planner 不可用 | LLM Intent Planner → LLM Task Planner | Rule Intent Planner → Simple Task Planner |
| LLM Decision 不可用 | LLM Decision | Rule-based 决策（默认分支）|
| Capability 不可用 | 调用 Capability | 返回 503 + 自动 Failover（备选 Connector）|
| Knowledge Center 不可用 | RAG + Ontology 检索 | 仅 Business Dictionary 精确匹配 |
| EventBus 不可用 | 异步事件通信 | 降级为同步调用 + 日志记录 |

---

# 第九章：Phase 1 实施（v6.0 更新）

> 基于 v5.0 第 9 章，调整 Execution Runtime 范围并增加 Infra/Centers 的实施说明。

```
Phase 1（1-3 个月）：
  ├── Coordination：最小版本（Workflow 协调 + 基础 Human Task）
  ├── Reasoning：Intent Planner（Rule）+ Task Planner（Simple Plan）
  ├── Execution：Orchestrator + Retry/Timeout（Approval 归 Policy Center）
  ├── Policy Center：RBAC + 基础审批
  ├── Infra：EventBus（进程内）+ Context Manager + State Machine
  └── Centers：Knowledge Center（Business Dictionary 初始化）

Phase 2（3-6 个月）：
  ├── Coordination：Multi-Agent + Event 协调 + Human Task Manager
  ├── Reasoning：LLM Planner + Reflection
  ├── Execution：Transaction Manager + Compensation + Decision Engine
  ├── Policy Center：Rate Limit + Data Scope + 完整审批策略
  ├── Infra：EventBus（Kafka）+ Checkpoint Manager
  └── Centers：Evaluation Center + Artifact Center

Phase 3（6-12 个月）：
  ├── Coordination：完整 Multi-Agent + 人机交互
  ├── Reasoning：完整 Self-Reflection + RePlanning
  ├── Execution：Full Saga + Process Instance + Business Transaction
  ├── Policy Center：Cost Limit + Time Restriction
  ├── Infra：Resource Manager（GPU/Docker）
  └── Centers：完整 Feedback → Evaluation → Learning 闭环

Phase 4（12-24 个月）：
  ├── 三引擎完全独立部署
  ├── Execution 达到企业级可靠性
  └── Enterprise Autonomous Runtime
```

---

# 第十章：版本演进

> 与 v5.0 第 10 章一致。

---

# 附录 A：版本演进路线图

> 与 v5.0 附录 A 一致。

---

# 附录 B：v5.0 → v6.0 变更

| 变更 | v5.0 | v6.0 |
|------|------|------|
| 设计原则 | L0 9 条 + L1 10 条（独立定义） | L0 与 L1 建映射表，互相引用 |
| Execution Runtime | 8 模块（含 Approval / Human Task / Full Feedback） | 6 模块（移出 Approval Manager → Policy Center, Human Task → Coordination Runtime, Feedback 仅保留 Collector）|
| Coordination Runtime | 3 个子模块 | 5 个子模块（+ Human Task Manager, + Human-in-the-loop 扩展）|
| 分层 | 9 层（Kernel 层含 11 个组件） | 11 层（Kernel 拆为 Infra Layer + Policy Layer + Centers）|
| Evaluation | Execution Runtime 内部子模块 | 独立 Evaluation Center |
| 错误处理 | 3.1 节"错误处理"内容为空 | 完整定义错误分类、统一错误码、统一响应格式、降级路径 |
| 事件类型定义 | EventBus + Audit 各自定义 | EventBus 唯一注册表，Audit 引用（不重定义）|
| CloudEvents 版本 | 2.0 / 1.0 不一致 | 统一为 CloudEvents 1.0 (specversion: 1.0) |
| 概念模型 | 章节编号 5.5-5.6 重复 | 已修正编号 |
| Memory | 仅引用，无独立定义 | 新增 Memory 对象章节（Concept Model v2.0）|

---

# 附录 C：v6.0 架构评审采纳状态

| 评审问题 | 采纳 | v6.0 改进 |
|----------|:----:|-----------|
| C1 L0/L1 原则不一致 | ✅ | 1.2 节建立原则映射表 |
| C2 链/循环未映射 | ✅ | 新增章节说明映射关系 |
| C3 章节编号重复 | ✅ | 编号修正（Concept Model v2.0）|
| CP1 P6 SDK 未开始 | ⏳ | L1 层面标记，待 L2 阶段规划 |
| CP2 缺少架构视图 | ⏳ | L1 架构图更新，部署/数据/时序图作为 P6 补充 |
| CP3 Memory 定义不足 | ✅ | Concept Model v2.0 新增 Memory 章节 |
| CP4 ConditionTrigger 过简 | ⏳ | 标注为 P4 扩展 |
| S1 Execution Runtime 过载 | ✅ | 5.2 节收窄职责；ADR-004 |
| S2 Kernel Layer 混杂 | ✅ | 3.1 节拆为三层；ADR-005 |
| S3 Feedback/Evaluation 归属 | ✅ | 2 章、3.1 节明确归属；ADR-006 |
| S4 Multi-Agent 协调细化 | ⏳ | 需 Coordination Spec 细化 |
| F1 CloudEvents 版本 | ✅ | 统一为 CloudEvents 1.0 |
| F2 MUST 不可验证 | ⏳ | 性能型 MUST 标注测试条件，安全策略注明依赖 |
| F3 资源隔离策略 | ⏳ | 待 Resource Spec 更新 |
| Q1 事件类型重复 | ✅ | EventBus 规范 v1.1 唯一注册表 |
| Q2 错误处理为空 | ✅ | 第 8 章补全 |
| Q3 错误码缺失 | ✅ | 8.2 节统一错误码，8.3 节统一响应格式 |
| R1 Execution 过载未落地 | ✅ | ADR-004 + 5.2 节移除 |
| R2 无问题关闭状态 | ✅ | 附录 C 跟踪表 |
| R3 版本评审对应 | ✅ | 附录 A/B 变更说明 |
| R4 Observation 缺少 Replay | ⏳ | 标注 Observation Spec P3 扩展 |
