# Enterprise AI Runtime Platform（EARP）

## 架构设计 v3.0

> 基于 v2.0 评审反馈优化，融合 Domain Layer、Capability 三层拆分、Planner 双引擎等关键建议。
> 定位：**L1（Architecture）文档**，目标支撑 5-10 年持续迭代。

---

# 第一章：产品定位与设计原则

## 1.1 产品定位

Enterprise AI Runtime Platform（EARP）是一套面向**企业数字化与智能化场景**的 AI Runtime 平台。

平台不是聊天机器人，不是 Workflow 编辑器，而是作为**企业 AI 的统一运行平台**。

所有 AI 能力（Chat、Workflow、Agent、Knowledge、Data Analysis 等）均运行于统一 Runtime 之上。

## 1.2 设计原则

```
┌────────────────────────────────────────────────────────────────────┐
│  Runtime First      所有应用均调用 Runtime，不允许直连 LLM          │
│  Domain First       Runtime 先理解业务领域，再操作能力              │
│  Capability First   AI 调用 Business Capability，不直接调 Tool     │
│  Event Driven       Runtime 内部事件驱动，模块间解耦               │
│  Adapter Pattern    所有第三方系统经过 Adapter，Runtime 不感知      │
│  Plugin First       所有能力可插件化（SPI 契约定义）               │
│  Stateless Runtime  Runtime 无状态，状态外置到 Kernel              │
│  Learning Runtime   Runtime 持续学习企业能力，渐进式丰富            │
└────────────────────────────────────────────────────────────────────┘
```

## 1.3 关键架构决策（ADRs）

### ADR-001：Runtime 无状态化

| 决策 | 值 |
|------|-----|
| 状态位置 | 全部外置到 Kernel + Infrastructure |
| 扩容方式 | Runtime 副本数 ≥ 2，水平扩展 |
| 恢复机制 | 基于 Checkpoint 重建，非任务重调度 |
| 失败模式 | 任何 Runtime 节点宕机，Kernel 重新调度到其他节点 |

### ADR-002：Kernel 下沉

| 决策 | 值 |
|------|-----|
| Context 归属 | Kernel 持有 KernelContext，Runtime 通过 API 获取 |
| Checkpoint 归属 | Kernel 统一管理 Checkpoint 生命周期 |
| Artifact 归属 | Artifact Center 统一管理存储和分发 |
| 实施原则 | Runtime 层不出现与 Kernel 同名的模块 |

### ADR-003：Planner 双引擎

| 决策 | 值 |
|------|-----|
| Intent Planner | 自然语言理解 + 实体提取 + 领域路由 + Capability 选择 |
| Task Planner | Plan 生成（DAG）+ 任务分解 + 反思 + 重规划 |
| 默认模式 | Rule-based（Phase 1），LLM（Phase 2+） |
| 验证机制 | Plan Validation Layer（执行前）+ Outcome Verification（执行后） |

---

## 1.4 平台价值图

> 一张图，30 秒理解 EARP 是什么、能做什么、核心价值在哪。
>
> **阅读指引**：从上往下看，每一层回答一个问题。工程细节对读者不可见。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│                     Enterprise AI Runtime Platform                      │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │             用户直接看到什么 ？                                    │   │
│  │                                                                  │   │
│  │     Chat         Workflow         Agent           API / SDK      │   │
│  │   对话/查询    流程编排        自动执行        系统集成           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │             核心引擎是什么 ？                                      │   │
│  │                                                                  │   │
│  │                      ║  Runtime  ║                                │   │
│  │                    ───────────────                                │   │
│  │                                                                  │   │
│  │       Intent        Task        Scheduler       Executor         │   │
│  │      Planner       Planner                   + Lifecycle         │   │
│  │      理解意图      生成计划      调度任务        执行               │   │
│  │                                                                  │   │
│  │    ┌─ Plan Validation Layer ─ 所有计划必经校验 ─────────────┐     │   │
│  │    │  Schema │ 权限 │ 循环检测 │ 深度限制 │ 配额              │     │   │
│  │    └────────────────────────────────────────────────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │             平台积累了什么核心资产 ？                              │   │
│  │                                                                  │   │
│  │  ┌────────────┐  ┌──────────┐  ┌─────────┐  ┌──────────────┐   │   │
│  │  │ Capability │  │ Knowledge│  │  Policy │  │ Observation  │   │   │
│  │  │  Center    │  │  Center  │  │  Center │  │   Center     │   │   │
│  │  │            │  │          │  │         │  │              │   │   │
│  │  │ 业务能力    │  │ 知识     │  │ 权限/   │  │ 可观测/审计/ │   │   │
│  │  │ 注册/发现  │  │ 术语/Dict│  │ 策略/   │  │ 链路追踪     │   │   │
│  │  │ 各领域     │  │ 语义索引  │  │ 审批    │  │              │   │   │
│  │  └────────────┘  └──────────┘  └─────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │             能连接什么系统 ？                                      │   │
│  │                                                                  │   │
│  │   ERP   │   MES   │   CRM   │  SCADA  │   MCP   │   OA    │ DB  │   │
│  │  SAP/金蝶│  生产   │  客户    │  设备    │  AI协议  │  审批   │  数据库 │
│  │  用友    │  执行    │  关系    │  控制    │  接入    │  协同   │       │
│  │                                                                  │   │
│  │              所有系统经过 Connector，Runtime 不感知                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │             跑在什么基础设施上 ？                                  │   │
│  │                                                                  │   │
│  │   PostgreSQL    │    Redis    │    Kafka/消息队列   │   MinIO/S3  │   │
│  │   Sandbox       │   Docker    │   Kubernetes       │   GPU       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 价值图速览

| 层 | 一句话 | 对应 v3.0 章节 |
|----|--------|--------------|
| **应用层** | Chat/Workflow/Agent/API — 用户直接交互的入口 | 第二章 Application |
| **Runtime** | Intent Planner + Task Planner + Scheduler + Executor — 理解意图、生成计划、执行任务、全生命周期管理 | 第三章 |
| **资产层** | Capability Center + Knowledge Center + Policy Center + Observation Center — 平台持续积累的核心企业资产 | 第五~八章 |
| **连接层** | ERP/MES/CRM/SCADA/MCP/OA/DB — 通过 Connector 统一接入，Runtime 不感知底层系统 | 第十章 |
| **基础设施** | PostgreSQL/Redis/Kafka/MinIO/Sandbox/Docker/Kubernetes | 第十四章 |

---

# 第二章：总体架构

## 2.1 系统分层

```
┌──────────────────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER                                                       │
│  Chat │ Workflow Studio │ Agent Studio │ Knowledge Base                  │
│  Dashboard │ Playground │ Prompt Center │ SDK │ API Gateway              │
│  ── 不负责执行，所有执行委托给 Runtime ──                                 │
├──────────────────────────────────────────────────────────────────────────┤
│  RUNTIME LAYER（无状态，水平扩展）                                         │
│                                                                          │
│  ┌─────────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │  Intent Planner     │  │  Task Planner   │  │  Scheduler          │  │
│  │                     │  │                 │  │                     │  │
│  │  NLU → 实体提取     │  │  Plan 生成(DAG)  │  │  Cron/Event/Webhook │  │
│  │  Domain 路由         │  │  任务分解        │  │  MQTT/Condition     │  │
│  │  Capability 选择     │  │  反思/重规划     │  │  Trigger            │  │
│  └──────────┬──────────┘  └────────┬────────┘  └─────────────────────┘  │
│             │                      │                                     │
│             └──────────────────────┼────────────────────────────────────┘
│                                    │
│                   Plan Validation Layer                                   │
│              Schema │ 权限 │ 循环检测 │ 深度限制 │ 配额                      │
├──────────────────────────────────────────────────────────────────────────┤
│  DOMAIN LAYER（业务领域路由，新增）                                        │
│                                                                          │
│  ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Production│ │Equipment │ │ Inventory │ │ Quality  │ │ ……           │ │
│  │ Domain    │ │ Domain   │ │ Domain    │ │ Domain   │ │ (可扩展)      │ │
│  └─────┬─────┘ └────┬─────┘ └─────┬─────┘ └────┬─────┘ └──────┬───────┘ │
│        │            │             │            │              │          │
│        └────────────┴─────────────┴────────────┴──────────────┘          │
│                              │                                           │
│           Domain Repository（领域 → Capability 映射表）                    │
├──────────────────────────────────────────────────────────────────────────┤
│  CAPABILITY LAYER                                                        │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                   Capability Center                             │    │
│  │  Registry │ Discovery │ Version │ Permission │ Health │ Metrics │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │
│  │  Business    │  │  Knowledge   │  │  Analysis    │                   │
│  │  Capability  │  │  Capability  │  │  Capability  │                   │
│  └──────┬───────┘  └──────────────┘  └──────────────┘                   │
│         │                                                               │
│         ▼                                                               │
│  ┌──────────────┐                                                       │
│  │   Service    │  ← 业务逻辑编排层（新增）                                │
│  │  (Alarm Svc  │                                                       │
│  │   Order Svc) │                                                       │
│  └──────┬───────┘                                                       │
│         │                                                               │
│         ▼                                                               │
│  ┌──────────────┐                                                       │
│  │   Connector  │  ← 协议适配层（原 Adapter，拆出）                       │
│  │  (MES/SAP/   │                                                       │
│  │   MQTT/SQL)  │                                                       │
│  └──────────────┘                                                       │
├──────────────────────────────────────────────────────────────────────────┤
│  KERNEL LAYER（有状态基础设施）                                           │
│                                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────────┐  │
│  │ Context  │ │ State    │ │ EventBus │ │ Policy Engine            │  │
│  │ Manager  │ │ Machine  │ │          │ │ (RBAC/限流/数据范围/审批） │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────────┐  │
│  │ Checkpoint│ │ Resource │ │ Lifecycle│ │ Observability            │  │
│  │ Manager  │ │ Manager  │ │ Manager  │ │ Trace/Metrics/Replay     │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────────────┘  │
├──────────────────────────────────────────────────────────────────────────┤
│  KNOWLEDGE CENTER（重新定位）                                             │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  RAG │ Ontology │ Business Dictionary │ Semantic Index          │    │
│  │  Capability Metadata │ Prompt Library                           │    │
│  └─────────────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────────────┤
│  ARTIFACT CENTER（独立模块，新增）                                        │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  PDF │ Excel │ Word │ Image │ SQL Result │ Chart │ Markdown     │    │
│  └─────────────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE LAYER                                                    │
│  PostgreSQL │ Redis │ Object Storage │ Message Queue                     │
│  Sandbox │ Docker │ Kubernetes                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## 2.2 架构主链（关键路径）

```
v3.0 核心路径：

Application
    ↓
Intent Planner  ← Business Dictionary（术语映射）
    ↓
Domain Layer（路由到正确领域）
    ↓
Capability Center（检索能力）
    ↓
Plan Validation Layer（校验）
    ↓
Task Planner（生成执行计划）
    ↓
Executor（执行）
    ↓
Capability → Service → Connector
    ↓
Enterprise System（ERP/MES/DB/...）
```

## 2.3 层间通信契约

| 调用方向 | 通信方式 | 同步/异步 |
|----------|---------|----------|
| Application → Runtime | gRPC + REST | 同步（Chat）/ 异步（Workflow） |
| Runtime → Domain Layer | 内部函数调用 | 同步 |
| Domain → Capability Center | 内部函数调用 | 同步 |
| Capability → Service | 内部函数调用 | 同步 |
| Service → Connector | 内部函数调用 | 同步 |
| Connector → 外部系统 | REST / gRPC / JDBC / MQTT / OPC-UA | 混合 |
| Runtime → Kernel | gRPC（内部） | 同步 |
| Kernel → EventBus | CloudEvents + Avro | 异步 |

---

# 第三章：Runtime 层

## 3.1 部署拓扑

```
                  ┌──────────────┐
                  │  API Gateway │
                  └──────┬───────┘
                         │
          ┌──────────────┼──────────────────┐
          │              │                  │
          ▼              ▼                  ▼
   ┌────────────┐ ┌────────────┐  ┌──────────────┐
   │  Intent    │ │   Task     │  │  Scheduler   │
   │  Planner   │ │  Planner   │  │  Service     │
   │ (2-10副本) │ │ (2-10副本) │  │  (2-5副本)   │
   │   w/ GPU   │ │   w/ GPU   │  │  CPU only    │
   └──────┬─────┘ └─────┬──────┘  └──────┬───────┘
          │             │                │
          └─────────────┼────────────────┘
                        │
                        ▼
               ┌────────────────┐
               │ Plan Validation│
               │ (sidecar)      │
               └────────────────┘
                        │
                        ▼
               ┌────────────────┐
               │   Executor     │
               │  (5-20副本)     │
               │  CPU only      │
               └────────────────┘
                        │
                        ▼
               ┌────────────────┐
               │  Kernel        │
               │  (3-5 主从)    │
               └────────────────┘
```

- **Intent Planner**：NLU 密集型，需要 LLM/GPU，独立扩缩容
- **Task Planner**：任务编排密集型，需要 LLM/GPU，独立扩缩容
- **Executor**：短平快执行，CPU 密集，独立扩缩容
- **Scheduler**：长周期任务调度，轻量级
- **Kernel**：有状态（Checkpoint / State Machine），主从部署

## 3.2 Runtime 模块职责

### 3.2.1 Intent Planner

```
输入: Task（用户请求 + Context）
├── NLU            → 理解自然语言意图
├── Entity Extractor → 提取业务实体（时间/范围/对象）
├── Business Dictionary Lookup → 企业术语映射（"异常"→"Alarm"）
├── Domain Router  → 路由到正确业务领域
├── Capability Selector → 从该领域选择 Capability
└── Output         → 结构化意图（Domain + Capability + Parameters）

支持的 Planner 类型：
  Rule-based    [Phase 1 默认] — 关键词匹配 + 规则路由
  LLM           [Phase 2] — LLM 动态意图理解
  Hybrid        [Phase 2] — Rule + LLM 混合
```

### 3.2.2 Task Planner

```
输入: 结构化意图（来自 Intent Planner）
├── Plan Generator   → 生成 Execution Plan（DAG）
├── Task Decomposer  → 大任务拆解为子任务
├── Planner          → 反思执行结果，自动重规划
├── Optimizer        → Plan 优化（并行/依赖/资源）
└── Output           → Validated Plan

支持的模式：
  Simple Plan     [Phase 1] — 线性执行
  DAG Plan        [Phase 1] — 有向无环图
  Dynamic Plan    [Phase 2] — 根据执行结果动态调整
  Self-Reflection [Phase 3] — 执行后自动反思优化
```

### 3.2.3 Executor

```
输入: Validated Plan
├── Step Runner        → 依次/并行执行 Step
├── Capability Caller  → 调用 Capability（经过 Policy Gate）
├── Streamer           → 流式推送结果
├── Artifact Generator → 产物生成
├── State Reporter     → 报告执行状态到 Kernel
└── Resource Manager   → 管理执行资源（Sandbox/GPU/Worker）

支持：暂停 / 恢复 / 重试 / 超时熔断
```

### 3.2.4 Scheduler

```
输入: 触发事件（Cron / Event / Webhook / MQTT / Condition）
├── Trigger Registry  → 管理所有 Trigger
├── Trigger Evaluator → 评估触发条件
├── Task Enqueuer     → 生成 Task 并入队列
└── Schedule Manager  → Cron 调度管理
```

## 3.3 Runtime Lifecycle（标准化）

```
                    ┌──────────┐
                    │ Created  │
                    └────┬─────┘
                         │
                         ▼
                    ┌──────────┐
                    │ Planning │ ← Intent + Task Planner
                    └────┬─────┘
                         │
                    ┌──────────┐
                    │ Waiting  │ ← 等待资源/审批
                    └────┬─────┘
                         │
                    ┌──────────┐
              ┌────→│ Running  │ ← Executor 执行
              │     └────┬─────┘
              │          │
              │    ┌─────┴──────┐
              │    │            │
              │    ▼            ▼
              │ ┌────────┐ ┌──────────┐
              │ │ Paused │ │ Retrying │ ← 人工审批/失败重试
              │ └───┬────┘ └────┬─────┘
              │     │           │
              │     ▼           ▼
              │ ┌────────┐ ┌──────────┐
              │ │Resumed │ │RetryLimit│
              │ └───┬────┘ └────┬─────┘
              │     │           │
              └─────┘           ▼
                          ┌──────────┐
                          │ Failed   │
                          └────┬─────┘
                               │
                    ┌──────────┼──────────┐
                    │          │          │
                    ▼          ▼          ▼
              ┌────────┐ ┌────────┐ ┌──────────┐
              │Completed│ │Archived│ │Cancelled │
              └────────┘ └────────┘ └──────────┘

对应 State Machine 定义：
  Created → Planning → Waiting → Running → Completed → Archived
                                         → Paused → Resumed → Running
                                         → Retrying → Running
                                                    → Failed → Archived
                                         → Cancelled
```

## 3.4 Plan Validation Layer

```
Plan（来自 Task Planner）
    │
    ▼
┌──────────────────────────────────────────┐
│           Plan Validation Layer          │
│                                          │
│  1. Schema Validation                    │
│     └─ 每个 Step 的 input 符合 Schema    │
│                                          │
│  2. Permission Validation                │
│     └─ 当前用户/角色有权限调用            │
│                                          │
│  3. Capability Existence                 │
│     └─ 调用的 Capability 已注册且可用     │
│                                          │
│  4. Domain Consistency                   │
│     └─ Step 的 Domain 与用户意图一致      │
│                                          │
│  5. Cycle Detection                      │
│     └─ DAG 无环，嵌套深度 < MaxDepth     │
│                                          │
│  6. Resource Quota                       │
│     └─ 不超租户配额 / 速率限制            │
│                                          │
│  输出: Validated Plan / Rejected + Reason│
└──────────────────────────────────────────┘
```

---

# 第四章：Domain Layer（新增）

## 4.1 定位

Domain Layer 是 v3.0 最核心的新增层。它位于 Runtime 和 Capability 之间，负责：

1. **业务领域路由** — Intent Planner 先决定用户在哪个领域
2. **Capability 发现范围缩减** — 只检索当前领域的 Capability
3. **领域语义统一** — 同一领域内的术语、实体、规则一致

```
没有 Domain Layer 时：
  Intent Planner → 检索所有 Capability（500+）→ 准确率低

有 Domain Layer 时：
  Intent Planner → 路由到 Production Domain → 检索 30 个 Capability → 准确率高
```

## 4.2 预定义业务领域

```
┌─────────────────────────────────────────────────────────┐
│                  Business Domains                        │
│                                                         │
│  Production   生产域     工单 / 排产 / OEE / 良率        │
│  Equipment   设备域     设备状态 / 报警 / 维保 / 备件    │
│  Inventory   库存域     库存查询 / 出入库 / 盘点           │
│  Quality     质量域     质检 / 缺陷 / 追溯 / 客诉         │
│  Order       订单域     销售订单 / 采购订单 / 交货        │
│  Finance     财务域     发票 / 付款 / 成本 / 预算         │
│  Logistics   物流域     运输 / 仓储 / 配送 / 报关         │
│  HR          人力域     组织 / 人员 / 考勤 / 绩效          │
│  Maintenance 维护域     工单 / 巡检 / 保养 / 维修         │
│  Safety      安全域     巡检 / 隐患 / 事故 / 整改         │
│  ……                    可扩展                             │
└─────────────────────────────────────────────────────────┘
```

## 4.3 Domain 结构定义

```python
class BusinessDomain:
    """业务领域定义"""
    domain_id: str                    # "production"
    name: str                         # "生产域"
    description: str
    parent_domain: str | None         # 父子域关系（如："manufacturing"）
    
    # 关联的 Capability（Planner 检索范围限制在此）
    capabilities: list[str]           # ["query_work_order", ...]
    
    # 领域术语（用于 Intent Planner 路由）
    domain_terms: list[str]           # ["产线", "工单", "OEE", "良率"]
    
    # 领域对象（关联 Ontology）
    domain_entities: list[str]        # ["ProductionLine", "WorkOrder"]
    
    # 默认策略
    default_policies: list[str]       # 该领域的默认权限/审计策略
```

## 4.4 Domain 间关系

```
Manufacturing（制造根域）
├── Production     生产域
├── Equipment      设备域
├── Quality        质量域
├── Inventory      库存域
├── Maintenance    维护域
└── Safety         安全域

Enterprise（企业根域）
├── Order          订单域
├── Finance        财务域
├── Logistics      物流域
├── HR             人力域
└── ……             （可扩展）

跨域场景示例：
  "查询库存对工单的影响" → Inventory Domain + Production Domain
```

---

# 第五章：Capability Layer（重构）

## 5.1 定位变化

v2.0：

```
Capability → Adapter
```

v3.0：

```
Capability Center（一级模块）
    ↓
Capability（业务语义 — "做什么"）
    ↓
Service（业务逻辑编排 — "怎么做"）
    ↓
Connector（协议适配 — "怎么连"）
    ↓
Enterprise System
```

## 5.2 Capability Center

Capability Center 是**一级模块**，承载所有 Capability 的生命周期管理。

```
Capability Center
│
├── Registry       注册/更新/废弃/版本管理
├── Discovery      语义检索 + 关键词 + 领域筛选
├── Version        Capability 版本管理（兼容/不兼容变更）
├── Permission     Capability 级别的权限配置
├── Health         每个 Capability 的健康状态监控
├── Metrics        调用次数/成功率/延迟统计
└── Marketplace    对外开放（Phase 4）
```

## 5.3 三层接口定义

```python
# ─── Capability（业务语义层） ───

class BusinessCapability:
    """业务能力 — 定义做什么"""
    capability_id: str              # "query_equipment_alarm"
    domain: str                     # "equipment"
    version: str                    # "1.2.0"
    
    name: str                       # "查询设备报警"
    description: str                # "查询设备的历史报警记录"
    
    input_schema: JSONSchema
    output_schema: JSONSchema
    
    required_permissions: list[str]  # ["alarm:read"]
    audit_level: str                 # "detail"
    
    # 绑定到 Service
    service: str                     # "AlarmService"
    service_method: str              # "query_alarms"

# ─── Service（业务逻辑编排层） ───

class BusinessService(ABC):
    """业务服务 — 定义怎么做"""
    
    @abstractmethod
    def execute(self, params: dict, context: KernelContext) -> ServiceResult:
        """编排业务逻辑，可能调用多个 Connector"""
        pass

# ─── Connector（协议适配层） ───

class EnterpriseConnector(ABC):
    """企业连接器 — 定义怎么连"""
    
    connector_id: str                # "mes_connector"
    protocol: str                    # "REST" | "MQTT" | "JDBC" | "OPC-UA"
    
    @abstractmethod
    def connect(self) -> ConnectionResult
    @abstractmethod
    def execute(self, operation: str, params: dict) -> ConnectorResult
    @abstractmethod
    def health_check(self) -> HealthStatus
```

## 5.4 完整调用路径示例

```
用户: "查询昨天 1 号线设备报警"

1. Intent Planner:
   → "查询报警" → Business Dictionary: "报警"="Alarm"
   → Domain Router: Equipment Domain
   → Capability Selector: "query_equipment_alarm"

2. Plan Validation Layer: Schema / 权限 / 领域一致性 校验通过

3. Task Planner:
   → Plan: [query_equipment_alarm(line=1, date=yesterday)]

4. Executor 执行:
   → Capability: query_equipment_alarm（做什么）
        ↓
   → Service: AlarmService.query_alarms（怎么做）
        ↓
   → Connector: MESConnector.call("GetAlarms", params)（怎么连）
        ↓
   → MES 系统返回数据
```

---

# 第六章：Kernel 层

## 6.1 模块清单

Kernel 是**有状态基础设施层**，不包含业务逻辑。

| 模块 | 职责 | 数据存储 |
|------|------|---------|
| Context Manager | 管理请求上下文（Tenant/User/Role/Session） | Redis |
| State Machine | 管理执行状态生命周期 | PostgreSQL |
| EventBus | 事件发布/订阅（CloudEvents 规范） | Redis Streams / Kafka |
| Policy Engine | 策略评估（RBAC / 限流 / 数据范围 / 审批） | PostgreSQL |
| Checkpoint Manager | 执行检查点管理 | Object Storage + PostgreSQL |
| Resource Manager | 管理执行资源（Sandbox/GPU/Worker） | PostgreSQL |
| Lifecycle Manager | 管理 Runtime Lifecycle 流转 | PostgreSQL |
| Observability | Trace / Metrics / Logging / Replay / Profiling | Jaeger + Prometheus |

## 6.2 Resource Manager（预留 Phase 2-3）

```
Resource Manager
│
├── Sandbox Pool       Python 沙箱 / WASM 沙箱
├── GPU Pool           GPU 资源调度
├── Browser Pool       浏览器实例（Browser Agent）
├── Docker Pool        Docker 容器
├── Remote Worker      Remote Execution Worker
└── Resource Quota     租户/任务的资源配额管理

Phase 1：仅实现 Sandbox Pool + 基础 Quota
Phase 2：GPU Pool + Docker Pool
Phase 3：Browser Pool + Remote Worker
```

## 6.3 Observability（统一可观测性）

```
Observability
│
├── Trace         分布式链路追踪（OpenTelemetry）
├── Metrics       性能指标（Prometheus）
│   ├── Runtime 指标（P99延迟/吞吐量/错误率）
│   ├── Capability 指标（调用次数/成功率）
│   └── 资源指标（CPU/内存/GPU）
├── Logging       结构化日志
├── Replay        执行回放（基于 Checkpoint）
└── Profiling     性能剖析（慢查询/慢 Capability）
```

---

# 第七章：Knowledge Center（重新定位）

## 7.1 定位

v2.0 将 Knowledge ≈ RAG。v3.0 将 Knowledge Center 重新定位为 Runtime 的**知识基础设施**，不仅是文档检索。

```
Knowledge Center
│
├── RAG                  文档知识库（向量 + 关键词检索）     → 用于 Chat/Agent
├── Ontology             企业对象关系模型                     → 用于 Planner 推理
├── Business Dictionary  企业术语统一映射                     → ★ 用于 Intent Planner（最核心）
├── Semantic Index       语义索引层                          → 用于 Capability Discovery
├── Capability Metadata  Capability 搜索索引                 → 用于 Capability Center
└── Prompt Library       Prompt 模板管理                     → 用于 LLM 调用
```

## 7.2 Business Dictionary（新增，核心）

Business Dictionary 是 Intent Planner 最重要的依赖。它解决"用户说的和系统理解的不一致"问题。

```python
# Business Dictionary 条目
class BusinessTerm:
    term: str                           # "异常"
    language: str                       # "zh-CN"
    
    # 映射到标准实体
    mapped_entity: str                  # "Alarm"
    mapped_domain: str                  # "equipment"
    
    # 同义词
    synonyms: list[str]                 # ["报警", "告警", "故障"]
    
    # 上下文消歧
    context_rules: list[ContextRule]    # 在"质量"上下文中 → QualityDefect
                                        # 在"设备"上下文中 → EquipmentAlarm
```

**示例**：

| 用户输入 | Business Dictionary 映射 | 路由到 Domain |
|----------|------------------------|--------------|
| "异常" | Alarm（设备上下文） | Equipment Domain |
| "异常" | Defect（质量上下文） | Quality Domain |
| "库存" | Inventory | Inventory Domain |
| "工单" | WorkOrder | Production Domain |
| "良率" | Yield | Production Domain |

## 7.3 Knowledge 在架构中的位置

```
Intent Planner
    │
    ├──→ Business Dictionary（术语映射，必须）
    ├──→ Ontology（实体关系，辅助推理）
    └──→ Capability Metadata（能力发现，辅助路由）
                │
                ▼
         Knowledge Center
```

---

# 第八章：Capability Center

## 8.1 定位

Capability Center 是**一级模块**，不仅仅是 Registry。它是整个平台价值积累的核心。

```
Capability Center
│
├── Registry
│   ├── Register Capability     POST  /capabilities
│   ├── Update Capability       PATCH /capabilities/:id
│   ├── Deprecate Capability    POST  /capabilities/:id/deprecate
│   └── Version Management      Capability 版本追踪
│
├── Discovery
│   ├── Intent-based Search     Embedding + Vector Search
│   ├── Domain-scoped Search    按领域筛选
│   ├── Keyword Search          关键词匹配
│   └── Hybrid Search           向量 + 关键词 + Metadata Filter
│
├── Permission
│   ├── Capability-level RBAC
│   └── Data Scope Control
│
├── Health
│   ├── Connectivity Check      连接健康
│   ├── Latency Monitoring      延迟监控
│   └── Error Rate Tracking    错误率追踪
│
└── Metrics
    ├── Call Count
    ├── Success Rate
    ├── Avg Latency
    └── Top N 最常用 Capability
```

## 8.2 Capability 粒度规范

| 层级 | 粒度 | 示例 | 复用性 |
|------|------|------|--------|
| 原子 Capability | 单数据源，单操作 | `query_work_order` / `get_equipment_status` | 高 |
| 组合 Capability | 2-5 个原子组合 | `analyze_oee` / `generate_daily_report` | 中 |
| 流程 Capability | 跨系统，多步骤 | `handle_equipment_fault` / `process_return` | 低 |

---

# 第九章：Artifact Center

## 9.1 定位

Artifact Center 独立管理所有执行产物。

```
Artifact Center
│
├── 支持类型
│   ├── PDF
│   ├── Excel / CSV
│   ├── Word
│   ├── Image
│   ├── SQL Result
│   ├── Chart
│   ├── Markdown
│   └── 自定义
│
├── 存储
│   ├── Object Storage（MinIO / S3）
│   └── Metadata（PostgreSQL）
│
├── 生命周期
│   ├── Created（执行中）
│   ├── Available（可访问）
│   ├── Expired（TTL 到期）
│   └── Archived（长期归档）
│
└── 共享
    ├── Workflow 产物 → Agent 直接引用
    ├── Agent 产物 → Chat 展示
    └── Schedule 产物 → 自动分发
```

---

# 第十章：企业集成

## 10.1 Connector 生态

```
adapters/connectors/
│
├── sap/              SAP Connector（RFC / OData）
│   ├── connector.py
│   └── capabilities  （由 Capability Center 注册）
│
├── mes/              MES Connector
├── database/         Database Connector（PG/MySQL/SQLServer/Oracle）
├── iot/              IoT Connector（MQTT / OPC-UA / Modbus）
├── im/               Enterprise IM（企业微信/钉钉/飞书）
├── oa/               OA Connector
├── rest/             Generic REST Connector
├── soap/             SOAP WebService Connector
└── mcp/              MCP Connector（Model Context Protocol）
```

## 10.2 MCP 集成策略

```
MCP Server（SAP）
    │
    ▼
MCP Connector
    │
    ├── list_capabilities()   → 注册到 Capability Center
    ├── execute()             → 调用 MCP Tool
    └── health_check()
            │
            ▼
    Capability Center
    ("query_sap_order")
            │
            ▼
        Domain Layer
    (订单域 — 不感知 SAP)
            │
            ▼
        Intent Planner
    (不感知 SAP)
```

---

# 第十一章：Workflow 与 Agent

## 11.1 关系模型

```
Application Layer
    │
    ├── Workflow Studio（编辑流程定义）
    ├── Agent Studio（配置 Agent 行为）
    └── Chat（直接交互）
            │
            ▼
        Runtime
    │
    ├── Workflow Mode
    │   流程定义预先配置，Runtime 按图执行
    │   支持：Business/HumanApproval/Agent/Decision/LLM/Code/Notification 节点
    │
    ├── Agent Mode
    │   Runtime 动态规划执行路径
    │   支持：ReAct / Function Calling / Planning / Multi-Agent
    │
    └── Hybrid Mode
        Agent 调用 Workflow（子流程）
        Workflow 调用 Agent（智能决策节点）
```

## 11.2 嵌套调用防护

```
防护机制：
1. Call Stack 追踪（每次调用入栈）
2. Max Depth = 10（超出拒绝）
3. Cycle Detection（同 Tenant 内 Call ID 唯一）
4. Circuit Breaker（连续 N 次失败后熔断）
```

## 11.3 执行模式矩阵

| 维度 | Chat | Workflow | Agent | Scheduled |
|------|------|----------|-------|-----------|
| 入口 | Web | Studio | API | Scheduler |
| Intent Planner | 语义理解 | 用户指定 | 语义理解 | 触发器指定 |
| Task Planner | 无 | 预定义 DAG | 动态生成 | 预定义 DAG |
| Domain | 自动路由 | 用户指定 | 自动路由 | 触发器指定 |
| 人工介入 | 无 | 审批节点 | 可配置 | 审批节点 |
| 超时 | 30s | 30min | 5min | 60min |
| 可恢复 | 否 | Checkpoint | 否 | Checkpoint |

---

# 第十二章：安全架构

## 12.1 安全域

```
Authentication
├── SSO / OAuth2 / OIDC / LDAP
├── API Key（Service Account）
└── JWT 内部服务间认证

Authorization（通过 Policy Engine）
├── RBAC（Role → Permission → Resource）
├── 行级数据权限（按部门/角色）
└── Capability 级别权限

LLM 安全
├── Prompt Injection 检测（规则 + LLM as Judge）
├── 输出过滤（敏感信息 / PII）
└── LLM 调用审计

数据安全
├── 字段级脱敏
├── TLS 1.3
└── 密钥管理（Vault / KMS）

审计安全
├── 追加写，不可篡改
├── 加密存储
└── 独立存储，与应用数据隔离

沙箱安全
├── Docker / WASM 隔离
├── 网络白名单
├── 资源限制（CPU/Memory/Timeout）
└── 文件系统隔离
```

---

# 第十三章：错误处理与恢复

## 13.1 错误分类

| 分类 | 示例 | 处理策略 |
|------|------|---------|
| 可重试 | 网络超时 / 数据库死锁 / LLM 临时错误 | 自动重试 3 次 + Backoff |
| 不可重试 | 鉴权失败 / Schema 校验失败 / Capability 不存在 | 拒绝执行，记录审计 |
| 需人工介入 | 审批拒绝 / 业务规则冲突 | 挂起任务，等待裁决 |
| 系统故障 | Executor 宕机 / Kernel 主节点切换 | Checkpoint 恢复 + 重新调度 |

## 13.2 恢复策略

| 场景 | 策略 |
|------|------|
| Executor 宕机 | Kernel 检测心跳超时，从最新 Checkpoint 恢复 |
| Planner 宕机 | 任务回队列，其他实例消费 |
| Kernel 主切换 | 主从切换，从 WAL 恢复 |
| Capability 超时 | Kill + Retry |
| Workflow 部分失败 | Saga / 事务补偿 |
| 数据库不可用 | Redis 只读降级 |

---

# 第十四章：非功能性需求

## 14.1 SLA 目标

| 场景 | P99 延迟 | 吞吐量 | 可用性 |
|------|---------|--------|-------|
| Chat 对话 | < 3s | 1000 RPM | 99.9% |
| Workflow 执行 | < 30s | 100 RPM | 99.9% |
| Agent 任务 | < 60s | 50 RPM | 99.9% |
| 知识库检索 | < 2s | 500 RPM | 99.9% |
| 调度触发 | < 5s | 1000 TPM | 99.99% |

**全平台可用性**：99.95%（每月停机 ≤ 22 分钟）

## 14.2 伸缩策略

| Service | 扩容依据 | 水平扩展 |
|---------|---------|---------|
| Intent Planner | LLM 调用队列深度 ≥ 100 | 增加副本（GPU） |
| Task Planner | 计划请求队列深度 ≥ 100 | 增加副本（GPU） |
| Executor | 执行队列深度 ≥ 200 | 增加副本（CPU） |
| Kernel | 状态数量 ≥ 100,000 | 主从 + 读写分离 |

---

# 第十五章：Phase 1 实施路径

## 15.1 Phase 1 范围（1-3 个月）

```
基础运行时
├── Intent Planner（Rule-based）
├── Task Planner（Simple Plan）
├── Executor（线性执行）
├── Plan Validation Layer（Schema + 权限）
└── 无状态部署（2 副本）

Domain Layer
├── 3-5 个预定义 Domain（Production / Equipment / Inventory / Quality / Order）
└── Domain Router（关键词匹配）

Capability Center
├── Registry（CRUD）
├── Discovery（Embedding 检索）
├── 5-10 个原子 Capability
└── Server → Connector 拆分

Multi-Tenant
├── Tenant / Org / User / Role
├── RBAC
└── 行级数据隔离

Knowledge Center
├── RAG（文档检索）
├── Business Dictionary（100+ 企业术语）
└── Capability Metadata

Workflow
├── Studio
├── 节点：Business / HumanApproval / Decision / Notification
└── 暂停/恢复

Artifact Center
├── PDF / Excel / Image
└── Object Storage 集成
```

## 15.2 Phase 1 技术栈

| 层级 | 选型 |
|------|------|
| 后端框架 | Python FastAPI |
| 任务队列 | Celery |
| ORM | SQLAlchemy 2.0 + Alembic |
| 数据库 | PostgreSQL |
| 缓存 | Redis |
| 消息队列 | Redis Streams |
| 向量数据库 | pgvector |
| 对象存储 | MinIO |
| 沙箱 | Docker SDK |
| LLM SDK | LiteLLM |
| 可观测 | OpenTelemetry + Prometheus + Grafana |

## 15.3 【不做清单】Phase 1 不做的

| 模块 | 原因 |
|------|------|
| LLM Planner（Intent + Task） | Phase 1 Rule-based 即可 |
| Multi-Agent Runtime | Phase 3 |
| Ontology 知识图谱 | Phase 3 |
| Semantic Memory | Phase 2 |
| 全量 Connector 生态 | Phase 2 |
| Event Driven Agent | Phase 3 |
| Resource Manager（GPU/浏览器） | Phase 2-3 |
| Capability Marketplace | Phase 4 |

---

# 第十六章：未来演进

## Phase 2（3-6 个月）

```
Intent Planner LLM 化
Task Planner DAG + 动态规划
Ontology 属性扩展
Business Dictionary 自动化抽取
Semantic Memory
Connector 生态扩展（SAP/金蝶/用友/MQTT/OPC-UA）
Capability Health + Metrics
```

## Phase 3（6-12 个月）

```
Multi-Agent Runtime
Enterprise Agent
Event Driven Agent
Long Running Task
Ontology 图推理
Capability Marketplace 内测
Resource Manager（GPU/Browser/Docker）
Coding Agent / Browser Agent
```

## Phase 4（12-24 个月）

```
Enterprise AI OS
Runtime SDK
Capability Marketplace 开放
Agent Marketplace
Self-Learning Runtime
```

---

# 附录 A：v2.0 → v3.0 变更总结

| 变更 | v2.0 | v3.0 |
|------|------|------|
| **Domain Layer** | 无 | 新增 Production/Equipment/Inventory 等 10+ 业务域 |
| **Planner** | 单体 | Intent Planner + Task Planner 双引擎 |
| **Capability** | Capability → Adapter | Capability → Service → Connector 三层 |
| **Knowledge** | ≈ RAG | 6 模块，Business Dictionary 为核心 |
| **Capability Center** | Registry | 一级模块：Registry/Discovery/Version/Health/Metrics |
| **Artifact Center** | Kernel 子模块 | 独立一级模块 |
| **Runtime Lifecycle** | 隐式 | 标准化 Created → Archived 完整状态机 |
| **Resource Manager** | 无 | 预留位置，Phase 2-3 |
| **Observability** | 分散 | 统一：Trace/Metrics/Logging/Replay/Profiling |
| **Business Dictionary** | 无 | 新增，Intent Planner 核心依赖 |
| **Plan Validation** | 基础校验 | + Domain Consistency + 循环检测 + 资源配额 |
| **Learning Runtime** | 无 | 新增为设计原则 |
