# Enterprise AI Runtime Platform（EARP）

## 架构设计 v5.0

> 基于 v4.0 评审反馈优化。
> **核心变更**：增加 Closed-loop Intelligence 设计原则；Execution Runtime 嵌入 Decision Engine；增加 Feedback / Evaluation 闭环；Concept Model 增加 Goal / Constraint / Feedback / Decision 概念。
> 定位：**L1（Architecture）基线文档**，目标支撑 5-10 年持续迭代。

---

# 第一章：产品定位与设计原则

## 1.1 产品定位

Enterprise AI Runtime Platform（EARP）是一套面向**企业数字化与智能化场景**的 AI Runtime 平台。

平台不是聊天机器人，不是 Workflow 编辑器，不是 BPM 引擎，而是**企业 AI 的统一运行平台**——覆盖从"问"到"想"到"做"的完整链路。

## 1.2 设计原则

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Runtime First        所有应用均调用 Runtime，不允许直连 LLM               │
│  Domain First         Runtime 先理解业务领域，再操作能力                   │
│  Capability First     AI 调用 Business Capability，不直接调 Tool           │
│  Reason-Act 解耦      Reasoning 与 Execution 彻底分离，互不影响            │
│  Event Driven         Runtime 内部事件驱动，模块间解耦                     │
│  Adapter Pattern      所有第三方系统经过 Connector，Runtime 不感知          │
│  Plugin First         所有能力可插件化（SPI 契约定义）                     │
│  Stateless Runtime    Runtime 无状态，状态外置到 Kernel                    │
│  Closed-loop Intel.   Runtime 持续反馈→评估→学习→优化，形成自我演进闭环    │
│  Learning Runtime     Runtime 持续学习企业能力，渐进式丰富                  │
└────────────────────────────────────────────────────────────────────────────┘
```

## 1.3 关键架构决策（ADRs）

### ADR-001：Runtime 三引擎拆分

| 决策 | 值 |
|------|-----|
| Reasoning Runtime | 负责：理解、推理、规划、反思、重规划 — AI 密集 |
| Execution Runtime | 负责：调用 Capability、事务、补偿、回滚、审批、重试 — 稳定优先 |
| Coordination Runtime | 负责：Multi-Agent 协调、人机交互、Event/Workflow 协调 |
| 状态位置 | 全部外置到 Kernel |
| 解耦原则 | Reasoning 可高频升级，Execution 必须极度稳定 |

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

---

# 第二章：平台价值图

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
│  │  │ Intent Planner │  │ Decision Engine  │  │ Multi-Agent 协调  │   │   │
│  │  │ Task Planner   │  │ Transaction      │  │ 人机交互          │   │   │
│  │  │ Reflection     │  │ Compensation     │  │ Event 编排        │   │   │
│  │  │ RePlanning     │  │ Approval         │  │ Workflow 协调     │   │   │
│  │  │ Goal/Constraint│  │ Retry/Timeout    │  │                   │   │   │
│  │  │                │  │ Rollback/Saga    │  │ 协调者            │   │   │
│  │  │ AI 密集        │  │ Process Instance │  │                   │   │   │
│  │  │ 高频迭代       │  │ 极度稳定         │  │                   │   │   │
│  │  └────────────────┘  └──────────────────┘  └────────────────────┘   │   │
│  │                                                                      │   │
│  │    Reasoning 与 Execution 彻底解耦 —— 互不依赖                         │   │
│  │                   │                                                   │   │
│  │                   ▼                                                   │   │
│  │          ┌──────────────────┐                                         │   │
│  │          │  Feedback        │  →  Evaluation  →  Knowledge/Memory      │   │
│  │          │  (闭环学习)      │     →  Planner（下次更聪明）               │   │
│  │          └──────────────────┘                                         │   │
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

## 3.1 系统分层

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
├──────────────────────────────────────────────────────────────────────────────┤
│  EXECUTION LAYER（无状态，水平扩展，极度稳定）                                │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     Execution Runtime                                │   │
│  │                                                                      │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────┐                 │   │
│  │  │ Orchestrator│  │  Transaction  │  │  Compensation │                 │   │
│  │  │             │  │  Manager     │  │  Manager     │                 │   │
│  │  │ 步骤编排    │  │  Saga 事务   │  │  补偿动作    │                 │   │
│  │  │ 流程控制    │  │  一致性保证  │  │  回滚        │                 │   │
│  │  └────────────┘  └──────────────┘  └──────────────┘                 │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────┐                 │   │
│  │  │ Decision   │  │  Approval    │  │  Retry /     │                 │   │
│  │  │ Engine     │  │  Manager     │  │  Timeout     │                 │   │
│  │  │            │  │              │  │              │                 │   │
│  │  │ Rule/LLM/  │  │ 审批路由     │  │ 重试策略     │                 │   │
│  │  │ ML 决策    │  │ 审批策略     │  │ 超时熔断     │                 │   │
│  │  └────────────┘  └──────────────┘  └──────────────┘                 │   │
│  │  ┌────────────┐  ┌──────────────┐                                   │   │
│  │  │ Human Task │  │  Process     │                                   │   │
│  │  │ Manager    │  │  Instance    │                                   │   │
│  │  │            │  │  Manager     │                                   │   │
│  │  │ 人工任务   │  │ 长流程管理   │                                   │   │
│  │  │ 通知/催办  │  │             │                                   │   │
│  │  └────────────┘  └──────────────┘                                   │   │
│  │                                                                      │   │
│  │  ↓ 执行 Capability（经过 Decision → Policy → Approval → Audit）       │   │
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
│                                                                              │
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
│  KERNEL LAYER（有状态基础设施）                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────────┐      │
│  │ Context  │ │ State    │ │ EventBus │ │ Policy Center            │      │
│  │ Manager  │ │ Machine  │ │          │ │ (RBAC/限流/审批/审计)    │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────────────┘      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────────┐      │
│  │ Checkpoint│ │ Resource │ │ Lifecycle│ │ Evaluation Center       │      │
│  │ Manager  │ │ Manager  │ │ Manager  │ │ (Feedback/评价/学习注入)  │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────────────┘      │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  Observability Center / Knowledge Center / Artifact Center        │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 3.2 架构主链

```
v5.0 核心路径（含闭环）：

Application
    ↓
Coordination Runtime（协调：Multi-Agent / 人机交互 / 事件）
    ↓
Reasoning Runtime（推理：Intent + Goal/Constraint → Plan）
    ↓
Plan Validation Layer（校验）
    ↓
Execution Runtime（执行：Decision → Transaction → Capability）
    │
    ├──→ Domain Layer → Capability Center → Service → Connector → System
    │
    └──→ Artifact → Feedback → Evaluation → Memory/Knowledge → Planner


## 3.3 三引擎职责边界

| 维度 | Reasoning Runtime | Execution Runtime | Coordination Runtime |
|------|------------------|------------------|---------------------|
| 职责 | 理解/推理/规划 | 可靠执行/事务/补偿 | 协调/编排/人机交互 |
| AI 依赖度 | 高（LLM 是核心） | 低（LLM 可选） | 中（LLM 辅助决策） |
| 变更频率 | 高（模型/策略迭代） | 极低（稳定优先） | 中 |
| 核心能力 | NLU / Planner / Reflection | Transaction / Approval / Retry / Saga / Compensation | Multi-Agent / Human Task / Event |
| 失败影响 | 重新规划 | **业务数据一致性** | 协调失败 |
| 扩容依据 | GPU 密集 | CPU 密集 | 连接数 |
| 产出 | Execution Plan | Execution Result | 协调完成的最终结果 |

---

# 第四章：Reasoning Runtime

## 4.1 定位

Reasoning Runtime 是平台的 **"大脑"**，负责一切需要 AI 推理的活动。不参与任何实际执行。

```
Coordination Runtime
    ↓
Reasoning Runtime
    │
    ├── Intent Planner
    │   ├── NLU
    │   ├── Entity Extractor
    │   ├── Business Dictionary Lookup
    │   ├── Domain Router
    │   └── Capability Selector
    │   └── 输出：Intent
    │
    ├── Task Planner
    │   ├── Plan Generator（Execution Plan / DAG）
    │   ├── Task Decomposer
    │   └── Optimizer
    │   └── 输出：Plan
    │
    ├── Reflection
    │   ├── Outcome Analysis
    │   └── Plan Optimization
    │
    └── RePlanning
        ├── Failure Analysis
        └── Alternative Plan
```

## 4.2 特点

- **AI 密集**：核心组件全部依赖 LLM
- **可高频迭代**：Planner 策略可频繁更新，不影响业务执行
- **无副作用**：只产生 Plan，不调用任何企业系统
- **可降级**：LLM Planner 失败时回退到 Rule Planner

---

# 第五章：Execution Runtime

## 5.1 定位

Execution Runtime 是平台的 **"手"**，负责一切需要可靠执行的活动。这是 v4.0 新增的一级模块。

## 5.2 核心模块

```
Execution Runtime
│
├── Orchestrator
│   ├── Step Runner（按序/并行执行 Step）
│   ├── Flow Controller（条件/循环/分支）
│   └── Process Instance Manager（长流程实例管理）
│
├── Decision Engine（新增）
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
├── Approval Manager
│   ├── Approval Router（一人/会签/或签）
│   ├── Approval Strategy（角色/金额/级别）
│   ├── Timeout Escalation（超时升级）
│   └── Notification
│
├── Retry / Timeout Manager
│   ├── Retry Strategy（固定/指数退避/自定义）
│   ├── Timeout Control（每个 Step 独立超时）
│   └── Circuit Breaker（连续失败 N 次后熔断）
│
├── Human Task Manager
│   ├── Task Assignment
│   ├── Deadline Management
│   ├── Escalation（超时→通知上级）
│   └── Delegation
│
└── Feedback / Evaluation（新增）
    ├── Feedback Collector（收集执行结果、用户评价、指标）
    ├── Evaluation Analyzer（分析成功率、耗时、效果）
    └── Learning Injector（注入 Memory / Knowledge / Planner）
```

## 5.3 Business Transaction 示例

```
Business Transaction: "create_purchase_order"

Step 1: Query 库存（Query Capability — 无副作用）
    → 确认是否需要采购

Step 2: Command 创建采购单（Command — 必经审批）
    → Policy → Approval → Wait

Step 3: Command 更新库存锁定（Command）
    → 锁定库存数量

Step 4: Command 通知采购员（Command）
    → 发送企微消息

失败场景 —— Step 3 失败：
    → Compensate Step 2: 作废采购单
    → Compensate Step 4: 通知取消

Business Transaction 状态：
    Created → Executing → Completed
                         → Failed → Compensating → Compensated
```

## 5.4 Process Instance

对于跨小时/天/周的长期业务流程：

```
Process Instance（实例）
    ├── 实例 ID: PROC-2026-0001
    ├── 模板: 维修流程
    ├── 状态: Running | Paused | Completed | Failed
    ├── 当前 Step: 等待审批
    ├── 创建时间: 2026-06-27 08:00
    ├── 截止时间: 2026-06-28 08:00
    └── 关联: Execution / Task / Business Transaction
```

---

# 第六章：Coordination Runtime

```
Coordination Runtime
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

## 7.1 分类

```
Capability
│
├── Query Capability（无副作用）
│   ├── 查询库存 / 报警 / 工单 / 订单
│   └── Policy(只读检查) → Service → Connector
│
└── Command Capability（有副作用）
    ├── 创建工单 / 审批采购 / 启动设备
    ├── 发送消息 / 更新订单
    └── Policy(读写检查) → Approval → Audit → Service → Connector
```

## 7.2 CQRS 处理差异

| 处理 | Query | Command |
|------|-------|---------|
| Policy Check | 只读权限 | 读写权限 |
| Approval | 不需要 | 可能需要 |
| Audit | 摘要记录 | 详细记录 |
| Transaction | 无 | Saga 事务 |
| Compensation | 无 | 必须注册补偿 |
| Retry | 幂等可重试 | 需确认幂等性 |
| Timeout | 短（5s） | 长（按业务场景） |

---

# 第八章：错误处理

## 8.1 三引擎失败模式

| 故障 | Reasoning | Execution | Coordination |
|------|-----------|-----------|--------------|
| LLM 超时 | 回退 Rule Planner | 无影响 | 降级默认策略 |
| Capability 失败 | 触发 RePlanning | 执行补偿/回滚 | 通知协调者 |
| Process Instance 中断 | 无影响 | Checkpoint 恢复 | 重新协调 |
| 审批超时 | 无影响 | 升级/催办 | 通知人员 |
| Saga 补偿失败 | 无影响 | 标记人工介入 | 创建人工任务 |

---

# 第九章：Phase 1 实施

```
Phase 1（1-3 个月）：
  ├── Coordination：最小版本（Workflow 协调 + 基础 Human Task）
  ├── Reasoning：Intent Planner（Rule）+ Task Planner（Simple Plan）
  └── Execution：Orchestrator + Retry/Timeout + 基础 Approval

Phase 2（3-6 个月）：
  ├── Coordination：Multi-Agent + Event 协调
  ├── Reasoning：LLM Planner + Reflection
  └── Execution：Transaction Manager + Compensation

Phase 3（6-12 个月）：
  ├── Coordination：完整 Multi-Agent + 人机交互
  ├── Reasoning：完整 Self-Reflection + RePlanning
  └── Execution：Full Saga + Process Instance + Business Transaction

Phase 4（12-24 个月）：
  ├── 三引擎完全独立部署
  ├── Execution 达到企业级可靠性
  └── Enterprise Autonomous Runtime
```

---

# 第十章：版本演进

```
EARP 1.0（Phase 1）
  Knowledge + Workflow + Chat
      │
      ▼
EARP 2.0（Phase 2）
  Planner + Capability CQRS + Enterprise RAG
      │
      ▼
EARP 3.0（Phase 3）
  Reasoning Runtime + Execution Runtime
  AI 不仅会分析，还能可靠执行企业业务
      │
      ▼
EARP 4.0（Phase 4）
  Enterprise Autonomous Runtime
  长期运行、多智能体协作、事件驱动、自主执行
```

---

# 附录 A：版本演进路线图

## EARP 1.0（Phase 1 — 1-3 个月）

**定位**：企业知识库 + 基础 Workflow + Chat

```
能力范围：
  ├── 企业知识库问答（RAG + 多源知识）
  ├── 基础 Workflow 编排（Business / HumanApproval / Decision 节点）
  ├── Chat 对话（简单的问答交互）
  ├── Intent Planner（Rule-based）
  ├── Task Planner（Simple Plan）
  ├── Execution Orchestrator + Retry/Timeout + 基础 Approval
  ├── Coordination Runtime（最小版本：Workflow 协调 + 基础 Human Task）
  ├── Capability Center（5-10 个原子 Capability）
  ├── Multi-Tenant（Tenant / Org / User / Role + RBAC）
  └── Artifact Center（PDF / Excel / Image）

三引擎成熟度：
  Reasoning:  ★★☆☆☆（Rule-based，有限场景）
  Execution:  ★★☆☆☆（基础执行 + 重试 + 审批）
  Coordination: ★☆☆☆☆（仅 Workflow 协调）
```

## EARP 2.0（Phase 2 — 3-6 个月）

**定位**：Planner + Capability CQRS + Enterprise RAG

```
能力范围：
  ├── LLM Planner（Intent Planner + Task Planner）
  ├── Capability CQRS（Query / Command 正式拆分）
  ├── Transaction Manager + Compensation Manager
  ├── Multi-Agent 基础协调
  ├── Event 协调（Event → Agent / Workflow 触发）
  ├── Ontology 属性扩展
  ├── Business Dictionary 自动化抽取
  ├── Semantic Memory
  ├── Connector 生态扩展（SAP / 金蝶 / 用友 / MQTT / OPC-UA）
  └── Capability Health + Metrics

三引擎成熟度：
  Reasoning:  ★★★★☆（LLM + Rule 混合规划）
  Execution:  ★★★☆☆（Transaction + Compensation 就绪）
  Coordination: ★★★☆☆（Multi-Agent + Event 协调）
```

## EARP 3.0（Phase 3 — 6-12 个月）

**定位**：Reasoning Runtime + Execution Runtime 全面就绪

```
能力范围：
  ├── 完整 Self-Reflection + RePlanning
  ├── Full Saga + Process Instance + Business Transaction
  ├── 完整 Multi-Agent（Agent A↔B↔C 依赖与通信）
  ├── 完整 Human-in-the-loop（升级 / 委托 / 催办）
  ├── Ontology 图推理（Graph RAG）
  ├── Capability Marketplace 内测
  ├── Resource Manager（GPU / Docker）
  ├── Coding Agent / Browser Agent
  └── Long Running Task 全面支持

三引擎成熟度：
  Reasoning:  ★★★★★（自反思 + 重规划）
  Execution:  ★★★★★（Saga + 补偿 + 长流程）
  Coordination: ★★★★☆（人机 + 多 Agent + 事件）
```

## EARP 4.0（Phase 4 — 12-24 个月）

**定位**：Enterprise Autonomous Runtime

```
能力范围：
  ├── 三引擎完全独立部署 / 独立扩缩容
  ├── Execution Runtime 达到企业级可靠性（99.99%）
  ├── Capability Marketplace 对外开放
  ├── Agent Marketplace
  ├── Runtime SDK（开放平台）
  ├── Self-Learning Runtime（Runtime 持续学习企业能力）
  ├── 事件驱动 Agent（长期自主执行）
  └── Enterprise AI OS 形态

三引擎成熟度：
  Reasoning:  ★★★★★
  Execution:  ★★★★★
  Coordination: ★★★★★
```

## 版本演进总览

```
EARP 1.0                    EARP 2.0                    EARP 3.0                    EARP 4.0
Phase 1 (1-3月)             Phase 2 (3-6月)             Phase 3 (6-12月)            Phase 4 (12-24月)
─────────────               ─────────────               ──────────────              ──────────────
Knowledge +                 Planner +                   Reasoning Runtime +          Enterprise
Workflow + Chat             Capability CQRS +           Execution Runtime           Autonomous
                            Enterprise RAG                                         Runtime
                                                                                   
                                                                                   
Reasoning ★★                Reasoning ★★★★             Reasoning ★★★★★              Reasoning ★★★★★
Execution ★★                Execution ★★★               Execution ★★★★★              Execution ★★★★★
Coordination ★              Coordination ★★★            Coordination ★★★★          Coordination ★★★★★
                                                                                   
──── 企业知识库 ────         ──── AI 规划 ────           ──── 可靠执行 ────          ──── 完全自主 ────
```

# 附录 B：v3.0 → v4.0 变更

| 变更 | v3.0 | v4.0 |
|------|------|------|
| Runtime 架构 | 单体（Intent/Task/Executor/Scheduler） | 三引擎：Reasoning + Execution + Coordination |
| 设计原则 | 7 条 | 9 条（+ Reason-Act 解耦 + CQRS） |
| Execution | Executor Service | **Execution Runtime**（Transaction/Approval/Compensation/Saga 等一等公民） |
| Capability | 单一类型 | **Query / Command CQRS** |
| Business Transaction | 无 | Saga 模式 |
| Process Instance | 仅 Execution | 增加 Process Instance，支持跨天流程 |
| 架构层 | 7 层 | 9 层 |

# 附录 C：v4.0 → v5.0 变更

| 变更 | v4.0 | v5.0 |
|------|------|------|
| 设计原则 | 9 条 | 10 条（+ Closed-loop Intelligence） |
| Execution Runtime | 6 模块 | 8 模块（+ Decision Engine + Feedback/Evaluation） |
| Concept Model | 26 概念 | 30 概念（+ Goal / Constraint / Decision / Feedback / Evaluation） |
| 架构主线 | 单向执行链 | **闭环学习链** |
| 价值图 | 4 层 | 5 层（+ Feedback 闭环层） |
| Event 列表 | 20 事件 | 23 事件（+ DecisionMade / FeedbackCollected / EvaluationCompleted） |
