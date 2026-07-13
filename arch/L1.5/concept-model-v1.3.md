# Runtime 核心概念模型（Concept Model）

**Version：v1.3**

> 定位：**L1.5** — 介于 L1 Architecture 与 L2 Specification 之间的 Ubiquitous Language。
>
> 所有 L2 文档（Runtime / Planner / Capability / Workflow / Agent 的技术规范）的"核心概念"章节必须引用本文，**不允许重新定义** `Task`、`Execution`、`Capability`、`Goal`、`Decision`、`Feedback` 等术语。
>
> 本文不涉及具体实现，不定义数据库，不定义接口，仅定义系统核心对象及对象关系。

---

# 一、文档目的

本文档定义 Enterprise AI Runtime Platform 的核心领域模型（Concept Model）。

本模型用于统一整个系统的概念、术语及对象关系，是所有架构设计（L1）、技术规范（L2）及产品需求（L3）的基础。

---

# 二、设计目标

建立统一的 Runtime 世界模型（Runtime World Model）。

保证：

- 所有模块使用统一术语
- 所有对象职责单一
- 所有关系清晰
- Runtime 能够持续扩展
- Workflow、Agent、Chat、Scheduled 共用同一 Runtime
- Reasoning、Execution、Coordination 三引擎各司其职

---

# 三、核心设计思想

整个 Runtime 只回答三个问题：

**用户想做什么？**

Intent Planner 理解意图，Task Planner 生成 Plan，Goal 定义目标，Constraints 约束边界

**怎么完成？**

Capability 执行，Service 编排，Connector 对接

**执行得怎么样？**

Execution 管理生命周期，Policy 确保合规，Trace 记录全程，Feedback 驱动持续改进

Runtime 不关心业务系统。Runtime 只负责：理解任务、规划任务、决策、执行任务、反馈、评估、学习——形成自我演进的闭环。

---

# 四、核心对象总览

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       Runtime Concept Model                             │
│                                                                          │
│  ┌──────────┐     ┌──────────┐     ┌──────────────┐     ┌──────────┐   │
│  │ Request  │────→│  Intent  │────→│  Validation  │────→│   Plan   │   │
│  └──────────┘     └──────────┘     │    Result    │     └────┬─────┘   │
│                                    └──────────────┘          │         │
│                                         OK│                  │         │
│                                     ┌─────┘                  ▼         │
│                                     │                  ┌──────────┐   │
│                                     │                  │   Task   │   │
│                                     ▼                  └────┬─────┘   │
│                              Rejected                         │         │
│                              → User 通知                    ▼         │
│                                                      ┌──────────────┐ │
│                                                      │  Execution   │ │
│                                                      └──┬───┬───┬───┘ │
│                                    ┌────────────────────┘   │   └────┐│
│                                    ▼                        ▼        ▼│
│    ┌──────────────────────────────────────────────────────────────┐  │
│    │                   Capability (CQRS)                          │  │
│    │  ┌─────────────────────┐    ┌──────────────────────────┐    │  │
│    │  │  Query Capability   │    │   Command Capability     │    │  │
│    │  │  (无副作用)          │    │   (有副作用，必经审批)     │    │  │
│    │  │  查询库存/报警/工单  │    │  创建工单/审批/启动设备   │    │  │
│    │  └─────────────────────┘    └───────────┬──────────────┘    │  │
│    └──────────────────────────────────────────┼───────────────────┘  │
│                                               │                      │
│                                               ▼                      │
│                                    ┌──────────────────────┐         │
│                                    │   Business           │         │
│                                    │   Transaction        │         │
│                                    │   (Saga 事务)        │         │
│                                    └──────────┬───────────┘         │
│                                               │                      │
│                                    ┌──────────┴──────────┐          │
│                                    │  Compensation       │          │
│                                    │  (补偿动作/回滚)    │          │
│                                    └──────────┬──────────┘          │
│                                               │                      │
│                                    ┌──────────┴──────────┐          │
│                                    │      Policy          │          │
│                                    │  权限/限流/审批/审计  │          │
│                                    └──────────┬──────────┘          │
│                                               │                      │
│                                    ┌──────────┴──────────┐          │
│                                    │      Service         │          │
│                                    └──────────┬──────────┘          │
│                                               │                      │
│                                    ┌──────────┴──────────┐          │
│                                    │     Connector        │          │
│                                    └──────────┬──────────┘          │
│                                               │                      │
│                                    ┌──────────┴──────────┐          │
│                                    │  Enterprise System  │          │
│                                    └─────────────────────┘          │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  配套概念：                                                        │   │
│  │  Process Instance（长期流程实例） / Compensation（补偿动作）         │   │
│  │  Resource（执行资源） / Artifact（执行成果） / Trace（决策链）      │   │
│  │  Checkpoint（快照） / Memory（记忆） / Knowledge（知识） / Event   │   │
│  │  Trigger / Schedule（触发/调度）                                   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### 三条链

**执行链（Runtime 视角）**：

```
User → Request → Intent → ValidationResult → Plan → Task → Execution → Artifact
```

**业务链（企业视角）**：

```
Domain → Business Object → Capability(Query/Command) → Policy → Service → Connector → Enterprise System
```

**事务链（Execution 保证）**：

```
Execution → Business Transaction(Saga) → Compensation → Capability → Service → Connector
```

### 闭环链（AI Execution Loop）

```
Request → Intent → Goal(带 Constraints) → Plan → Decision → Task → Execution → Artifact
                                                                               │
                                                                               ▼
                                                                          Feedback
                                                                               │
                                                                          Evaluation
                                                                               │
                                                            ┌──────────────────┼──────────────────┐
                                                            ▼                  ▼                  ▼
                                                       Memory            Knowledge          Planner
                                                    (执行经验积累)      (执行结果注入)       (下一次更聪明)
```

### 四条链的关系

```
执行链：  Request → Intent → Goal → Plan → Decision → Task → Execution → Artifact → Feedback → Evaluation
业务链：  Domain → Business Object → Capability(Query/Command) → Policy → Service → Connector → Enterprise System
事务链：  Execution → Business Transaction(Saga) → Compensation → Capability → Service → Connector
闭环链：  Execution → Artifact → Feedback → Evaluation → Memory/Knowledge → Planner（再次决策——更聪明）
```

四条链在 **Capability** 处汇聚，通过 **Feedback + Evaluation** 实现闭环。

---

# 五、Runtime 核心对象

## 5.1 User

表示任务发起者。

可以是：

- 人（终端用户）
- 系统（API / SDK）
- Workflow（流程发起）
- Agent（智能体发起）
- Scheduler（定时任务）
- Trigger（Cron / Event / Webhook / MQTT / Condition）
- Event（事件触发）

User 不参与执行，仅产生 Request。

---

## 5.2 Request

表示一次业务请求。

例如：

- "统计昨天所有产线异常"
- "查询库存"
- "生成日报"
- 每天 8:00 自动触发

Request 是 Runtime **唯一入口**。任何执行必须由 Request 创建。

---

## 5.3 Intent

Planner 对 Request 的语义理解结果。

例如：

| Request | Intent |
|---------|--------|
| 统计昨天所有产线异常 | 动作: 统计 / 对象: 产线异常 / 时间: 昨天 / Domain: Production |
| 查询库存 | 动作: 查询 / 对象: 库存 / Domain: Inventory |
| 生成日报 | 动作: 生成 / 对象: 日报 / Domain: 通用 |

Intent 是 **Intent Planner 的输出**。不是 LLM 的直接输出，而是经过 Business Dictionary 术语映射和 Domain 路由之后的结构化结果。

---

## 5.4 Goal

Goal 表示 Intent 经过细化后的**可量化目标**。Goal 携带 Constraints（约束条件），Planner 在 Goal 和 Constraints 的约束下生成 Plan。

例如：

| Intent（来自 Request） | Goal | Constraints |
|----------------------|------|------------|
| 统计产线异常 | 目标: 统计昨天所有产线异常并汇总 | 时间范围: 昨天 / 只统计 1-3 号线 / 含维修记录 |
| 降低库存 | 目标: 将 A 类物料库存降低 20% | 不能影响交付 / 周期: 30 天 / 预算: 50 万 |
| 创建采购单 | 目标: 为库存低于安全库存的物料生成采购单 | 金额 > 10 万需审批 / 供应商白名单 |

Goal + Constraints 是 **Task Planner 的输入**。

---

## 5.5 Constraint

Constraint 表示 Goal 执行时必须遵守的限制条件。

类型：

| 类型 | 说明 | 示例 |
|------|------|------|
| Time Constraint | 时间范围 | 昨天、本月、Q3 |
| Resource Constraint | 资源限制 | 预算 50 万、人工 2 人 |
| Policy Constraint | 策略限制 | 金额 > 10 万需审批 |
| Data Constraint | 数据范围 | 只看本部门、只看 1-3 号线 |
| Quality Constraint | 质量要求 | 准确率 > 95% |
| Priority Constraint | 优先级 | 紧急、常规 |

---

## 5.4 ValidationResult

计划校验结果。Planner 输出的 Plan 必须经过校验才能执行。

表示 Plan 验证的最终结论：

- **Valid**：校验通过，进入 Execution
- **Invalid**：校验失败，返回原因，Request 回退或通知 User

校验内容包括：

| 校验项 | 说明 |
|--------|------|
| Schema Validation | 每个 Step 的 input 符合 Capability Schema |
| Permission Validation | 当前 User / Role 有权调用所选 Capability |
| Capability Existence | 调用的 Capability 已注册且可用 |
| Domain Consistency | Step 的 Domain 与用户意图一致 |
| Cycle Detection | DAG 无环，嵌套深度 < MaxDepth |
| Resource Quota | 不超过租户配额 / 速率限制 |

---

## 5.6 Domain

Domain 表示企业业务领域。Planner 首先确定 Domain，然后在该领域内检索 Capability。

例如：

| Domain | 说明 | 示例 Capability |
|--------|------|----------------|
| Production | 生产域 | 查询工单 / 计算 OEE / 排产 |
| Equipment | 设备域 | 查询报警 / 设备状态 / 维保 |
| Inventory | 库存域 | 查询库存 / 出入库 / 盘点 |
| Quality | 质量域 | 质检 / 缺陷追溯 / 客诉 |
| Order | 订单域 | 销售订单 / 采购订单 / 交货 |
| Finance | 财务域 | 发票 / 付款 / 成本 |
| Logistics | 物流域 | 运输 / 仓储 / 配送 |
| HR | 人力域 | 组织 / 考勤 / 绩效 |
| Maintenance | 维护域 | 巡检 / 保养 / 维修 |
| Safety | 安全域 | 隐患 / 事故 / 整改 |

Domain 与 Capability 的关系：**一个 Domain 包含 N 个 Capability，一个 Capability 属于一个 Domain**。

---

## 5.6 Business Object

Business Object 是企业核心业务对象，构成 Ontology 的基础。

例如：

- 设备
- 工单
- 订单
- 库存
- 物料
- 报警
- 产线
- 人员
- 客户
- 部门

Business Object 之间的关系构成 Ontology，Planner 基于 Ontology 进行推理。

---

## 5.7 Plan

Plan 表示解决 Request 的整体方案。

Plan **不包含具体执行细节**，仅描述需要完成哪些目标。

例如：Request="统计昨天所有产线异常"

```
Plan:
  1. 查询报警（设备域）
  2. 查询维修记录（设备域）
  3. 分析异常原因（设备域）
  4. 汇总生成报告（通用域）
```

一个 **Request 对应一个 Plan**。

Plan 由 **Task Planner** 生成。

---

## 5.8 Task

Task 是 Plan 的最小执行单元。

例如：

```
Plan:
  Task1: 查询报警（调用 query_alarms）
  Task2: 查询维修记录（调用 query_maintenance_logs）
  Task3: 分析关联（调用 LLM 分析）
  Task4: 生成报告（调用 generate_report）
```

Task 的特性：

- **可动态生成**：Task Planner 根据执行结果生成后续 Task
- **可动态拆分**：一个大 Task 可拆为多个子 Task
- **可重新规划**：失败后可重新规划替代方案
- **可并行**：无依赖的 Task 可并行执行

---

## 5.9 Execution

Execution 表示 Task 的一次执行实例。Execution 是 Runtime 生命周期管理的核心对象。

包含：

| 属性 | 说明 |
|------|------|
| 状态 | 当前生命周期阶段 |
| 上下文 | 执行上下文（租户/用户/角色/参数） |
| 日志 | 每一步的执行日志 |
| Trace | 决策链追踪记录 |
| Checkpoint | 可恢复快照（列表） |
| Retry | 重试策略与次数 |
| Mode | 执行模式：chat / workflow / agent / scheduled |

Execution 必须遵循统一生命周期（见第七章）。

---

## 5.10 Capability（CQRS）

Capability 表示 Runtime 可以完成的一项**业务能力**，是平台最核心的资产。

Capability 分为 **Query**（查询）和 **Command**（命令）两种类型：

### Query Capability

无副作用，只读操作，不改变企业数据。

```
示例：
  - 查询库存
  - 查询设备报警
  - 查询工单
  - 查询订单
  - 查询良率

执行路径：
  Execution → Capability → Policy(只读检查) → Service → Connector → System
```

### Command Capability

有副作用，会改变企业数据，必须经过严格管控。

```
示例：
  - 创建工单
  - 审批采购
  - 启动设备
  - 关闭设备
  - 发送消息
  - 更新订单
  - 创建维修任务

执行路径：
  Execution → Capability → Policy(读写检查) → Approval → Audit → Service → Connector → System
```

### CQRS 差异

| 处理 | Query Capability | Command Capability |
|------|-----------------|-------------------|
| Policy Check | 只读权限 | 读写权限 |
| Approval | 不需要 | 可能需要（可配置） |
| Audit | 摘要记录 | 详细记录（输入+输出） |
| Transaction | 无（单次查询） | Saga 事务（跨多步） |
| Compensation | 无 | 必须注册补偿动作 |
| Retry | 幂等可重试 | 需确认幂等性 |
| Timeout | 短（5s） | 长（按业务场景） |

### Capability 的通用要点

- **不暴露底层接口** — 调用者不知道底层是 MES 还是 SAP
- **代表业务能力** — 不是技术操作（不是 execute_sql，而是 query_inventory）
- **属于一个 Domain** — 每个 Capability 归属一个业务领域
- **由 Capability Center 管理** — 注册 / 发现 / 版本 / 权限 / 健康 / 指标

---

## 5.11 Service

Service 是 Capability 的实现层，负责业务逻辑编排。

例如：

```
Capability: "查询设备报警"
    ↓（Capability 不实现，仅定义做什么）
Service: "AlarmService.query_alarms(params)"
    ↓（Service 编排业务逻辑）
可能调用：MES Connector（查询报警记录）+ Database Connector（查询维修记录）
```

Capability 永远不直接访问外部系统，必须通过 Service。一个 Capability 对应一个 Service，一个 Service 可调用多个 Connector。

---

## 5.12 Connector（Adapter）

Connector 表示企业系统连接器，负责协议适配，屏蔽外部系统差异。

例如：

| Connector | 协议 | 对接系统 |
|-----------|------|---------|
| MES Connector | REST / gRPC | 制造执行系统 |
| SAP Connector | RFC / OData | SAP ERP |
| Database Connector | JDBC / SQL | PostgreSQL / MySQL / Oracle |
| MQTT Connector | MQTT | IoT 设备 |
| OPC-UA Connector | OPC-UA | SCADA / PLC |
| MCP Connector | MCP | MCP Server |
| IM Connector | HTTP | 企业微信 / 钉钉 / 飞书 |

Connector 不提供业务语义，只提供技术连接。

---

## 5.13 Enterprise System

企业实际业务系统，Runtime 永远不知道这些系统的存在。

例如：MES / ERP / SCADA / CRM / 数据库 / 对象存储 / 文件系统

---

## 5.14 Policy

Policy 表示 Capability 执行时必须遵守的策略规则。每次 Capability 调用前由 Policy Engine 评估。

包括：

| 类型 | 说明 |
|------|------|
| RBAC Policy | 基于角色的访问控制（谁能调用） |
| Rate Limit Policy | 限流（调用频率限制） |
| Data Scope Policy | 数据范围（只能看本部门数据） |
| Approval Policy | 审批策略（执行需要审批） |
| Audit Policy | 审计策略（记录级别） |
| Time Restriction Policy | 时间限制（仅在业务时间可用） |

Policy 是 Capability 与 Service 之间的**强制关卡**：

```
Capability → Policy → Service
```

---

## 5.15 Resource

Resource 表示 Runtime 可使用的执行资源。

不属于业务能力，仅提供执行能力：

- LLM（大语言模型）
- Python / Code 执行引擎
- Browser（浏览器实例）
- Sandbox（安全沙箱）
- GPU
- Remote Worker（远程执行节点）
- Docker（容器）

Resource 由 Kernel / Resource Manager 统一管理（Phase 2-3 全面实现，Phase 1 仅 Sandbox）。

---

## 5.16 Artifact

Artifact 表示 Runtime 产生的执行成果，由 Artifact Center 统一管理。

例如：

- PDF
- Word
- Excel / CSV
- Markdown
- SQL 查询结果
- 图片/图表
- 代码

Artifact 可作为下一次 Request 的输入（跨执行引用）。

---

## 5.17 Trace

Trace 表示 Execution 的完整决策链记录，用于审计溯源和执行回放。

包含：

- 每一次 Capability 调用记录（谁调了什么、传入参数、返回结果）
- 每一次 LLM 调用记录（完整 Prompt + Response）
- 每一次 Policy 决策记录（谁通过了什么策略）
- 数据来源记录（数据从哪个系统、哪个查询得来）

Trace 是 **Observability Center** 的核心组成部分。

---

## 5.18 Checkpoint

Checkpoint 是 Execution 在某个时刻的**可恢复快照**，由 Kernel / Checkpoint Manager 管理。

用途：

- **故障恢复**：Executor 宕机后从最新 Checkpoint 恢复
- **暂停恢复**：Human-in-the-loop 场景，审批通过后从 Checkpoint 恢复
- **执行回放**：基于 Checkpoint 序列回放执行过程

---

## 5.19 Memory

Memory 表示 Runtime 的长期状态，服务于 Planner。

分层：

| 层级 | 说明 | Phase |
|------|------|-------|
| Conversation Memory | 当前对话历史 | Phase 1 |
| Long-term Memory | 用户偏好/配置 | Phase 1 |
| Working Memory | 执行上下文临时状态 | Phase 2 |
| Semantic Memory | 实体关系 | Phase 3 |
| Business Memory | 业务规则/调用模式 | Phase 3 |

---

## 5.20 Knowledge

Knowledge 表示 Runtime 的知识来源。**不等于 RAG**，RAG 只是 Knowledge 的一种使用方式。

包括：

| 模块 | 用途 |
|------|------|
| RAG | 文档知识库（向量 + 关键词检索） |
| Business Dictionary | 企业术语统一映射（"异常"→"Alarm"） |
| Ontology | 企业对象关系模型 |
| Semantic Index | 语义索引层 |
| Capability Metadata | Capability 搜索索引 |
| Prompt Library | Prompt 模板管理 |

其中 **Business Dictionary** 是 Intent Planner 最核心的依赖。

---

## 5.23 Decision

Decision 表示 Execution Runtime 在执行过程中做的**动态决策**。

与 Planner 的区别：

| 维度 | Planner（规划时） | Decision（执行时） |
|------|-----------------|-------------------|
| 时机 | 执行前 | 执行中 |
| 输入 | Intent + Goal | 实时执行状态 |
| 输出 | Plan | 分支选择（IF-THEN-ELSE） |
| 依赖 | Knowledge + Memory | 当前上下文 + Policy |
| 机制 | Rule / LLM | Rule / LLM / ML |

Decision 由 Execution Runtime / Decision Engine 负责。

来源：

```
Decision Engine
├── Rule-based：  IF 库存 < 安全库存 THEN 采购
├── LLM-based：   IF 异常原因不明 THEN 调用 LLM 分析
└── ML-based：    IF 预测良率 < 阈值 THEN 提前干预（Phase 3）
```

---

## 5.24 Feedback

Feedback 表示 Execution 执行完成后产生的**原始反馈数据**，是闭环学习的基础。

包含：

| 反馈类型 | 说明 | 示例 |
|---------|------|------|
| Execution Result | 执行成功/失败/部分成功 | Capability 返回 "success" |
| Execution Metrics | 执行指标 | 耗时: 2.3s / 重试次数: 1 |
| User Feedback | 用户评价 | 👍 / 👎 / 评分: 4/5 |
| Data Change | 数据变化 | 库存从 100 变为 80 |
| Business Outcome | 业务效果 | 工单已关闭 |

Feedback 由 **Evaluation Center** 消费。

---

## 5.25 Evaluation

Evaluation 表示对 Feedback 的分析结论。

```
Feedback（原始数据）
    │
    ▼
Evaluation Center
    │
    ├── Capability Evaluation
    │   ├── query_alarms: 成功率 99%, P99 2.1s
    │   └── create_work_order: 成功率 97%, 平均审批 4.5h
    │
    ├── Plan Evaluation
    │   ├── Plan 执行成功率 95%
    │   └── 平均 Plan 完成时间 12.3s
    │
    ├── LLM Evaluation
    │   ├── Intent 解析准确率 92%
    │   └── Plan 合理性评分 4.1/5
    │
    └── KPI Evaluation
        ├── 全平台可用性 99.95%
        └── SLA 达标率 98.7%

Evaluation 输出 → Memory（保存趋势）/ Knowledge（注入结论）/ Planner（优化策略）
```

---

## 5.26 Business Transaction

Business Transaction 表示一个跨多个 Capability 调用的**业务操作单元**，由 Execution Runtime 管理。

一个 Business Transaction 包含多个 Execution Step。如果某个 Step 失败，已成功的 Step 将被补偿（Saga 模式）。

状态：

```
Created → Executing → Completed
                     → Failed → Compensating → Compensated
```

---

## 5.27 Compensation

Compensation 表示 Command Capability 的**回滚/撤销动作**，用于 Saga 补偿。

每个 Command Capability 可注册一个补偿动作：

```
Command Capability          Compensating Capability
─────────────────           ────────────────────────
创建采购单      →             作废采购单
锁定库存        →             释放库存锁定
发送通知        →             发送"取消"通知
启动设备        →             停止设备
更新订单        →             回退订单状态
```

由 Execution Runtime / Compensation Manager 自动触发。

---

## 5.28 Process Instance

Process Instance 表示一个**长期运行的业务流程实例**（小时/天/周级）。

与 Execution 的区别：

| 维度 | Execution | Process Instance |
|------|-----------|-----------------|
| 时长 | 秒/分钟 | 小时/天/周 |
| 跨度 | 单次 Task | 跨多 Task / Execution / Transaction |
| 状态 | 执行完即完成 | 可暂停/等待/恢复/催办 |
| 核心特征 | 自动执行 | 人工审批、超时升级、委托 |

由 Execution Runtime / Orchestrator / Process Instance Manager 管理。

---

## 5.29 Coordination Runtime

Coordination Runtime 是 v4.0 三引擎中的协调引擎。

职责：

- **Multi-Agent 协调**：Agent 间的通信、任务分配、冲突解决
- **Human-in-the-loop**：暂停/恢复、审批/驳回、人工输入、升级催办
- **Workflow ↔ Agent 双向编排**：Agent 调用 Workflow，Workflow 调用 Agent
- **Event 协调**：Event → Agent / Workflow / Scheduled 的触发

---

## 5.30 Event

Runtime 所有状态变化均产生 Event。所有 Event 通过 **EventBus** 发布 / 订阅，遵守 **CloudEvents** 规范。

典型事件：

| Event | 触发时机 |
|-------|---------|
| RequestCreated | Request 被创建 |
| PlanGenerated | Plan 生成完成 |
| PlanValidationFailed | Plan 校验失败 |
| TaskStarted | Task 开始执行 |
| CapabilityCalled | Capability 被调用 |
| ExecutionFinished | Execution 完成 |
| ArtifactGenerated | Artifact 生成 |
| MemoryUpdated | Memory 更新 |
| PolicyEvaluated | Policy 完成评估 |
| CheckpointCreated | Checkpoint 创建完成 |
| BusinessTransactionStarted | Business Transaction 开始 |
| BusinessTransactionCompleted | Business Transaction 完成 |
| BusinessTransactionFailed | Business Transaction 失败 |
| CompensationTriggered | 补偿动作被触发 |
| ProcessInstanceCreated | Process Instance 创建 |
| ProcessInstancePaused | Process Instance 暂停 |
| ProcessInstanceResumed | Process Instance 恢复 |
| ProcessInstanceCompleted | Process Instance 完成 |
| DecisionMade | 决策完成 |
| FeedbackCollected | 反馈已收集 |
| EvaluationCompleted | 评估完成 |
| ApprovalRequested | 审批请求 |
| ApprovalCompleted | 审批完成 |
| HumanTaskCreated | 人工任务创建 |
| HumanTaskCompleted | 人工任务完成 |

---

## 5.31 Trigger / Schedule

Trigger 表示任务启动的条件。Scheduler 管理所有 Trigger 的注册与评估。

支持类型：

| 类型 | 说明 |
|------|------|
| CronTrigger | 定时触发（每天 8:00） |
| EventTrigger | 事件触发（当某个 Event 发生时） |
| WebhookTrigger | 外部 HTTP 回调触发 |
| MessageTrigger | 消息触发（MQTT / Kafka） |
| ConditionTrigger | 条件触发（温度 > 50°C） |

---

# 六、对象关系

## 6.1 关联关系总表

```
Request → 1 : Intent
Intent → 1 : Goal
Goal → N : Constraint
Goal → 1 : Plan
Intent → N : Domain（跨域场景）
Plan → 1 : ValidationResult
Plan → N : Task
Plan → N : Decision（执行中决策）
Task → N : Execution
Execution → N : Capability(Query/Command)
Execution → N : Resource
Execution → N : Artifact
Execution → N : Event
Execution → N : Checkpoint
Execution → 1 : Trace
Execution → N : Business Transaction
Execution → 1 : Process Instance（可选）
Execution → 1 : Feedback
Feedback → 1 : Evaluation
Evaluation → N : Memory（学习结果）
Evaluation → N : Knowledge（知识注入）

Capability → 1 : Domain（归属领域）
Capability → N : Policy（绑定的策略）
Capability → 1 : Service
Capability → 1 : Compensation（Command 类型必选）
Service → N : Connector
Connector → 1 : Enterprise System

Domain → N : Business Object
Domain → N : Capability

Business Transaction → N : Execution
Business Transaction → N : Compensation
Process Instance → N : Business Transaction
Process Instance → N : Task

Decision → N : Capability（执行决策选择哪个 Capability）

Planner → Knowledge（依赖知识）
Planner → Memory（依赖记忆）
Planner → Evaluation（依赖评估结果优化下一步规划）
```

## 6.2 完整闭环生命周期

```
User → Request → Intent → Goal(带 Constraints)
    ↓
Planner → Plan → ValidationResult
    Valid → Task → Execution → Decision → Capability → Artifact
    ↓                                                     ↓
Invalid → 通知 User                                    Feedback
                                                          ↓
                                                     Evaluation
                                                          ↓
                                              Memory / Knowledge  →  Planner（再次决策）
```

## 6.3 Request 生命周期

```
User → Request → Intent → ValidationResult
    Valid → Plan → Task → Execution → Artifact
    Invalid → 通知 User
```

## 6.3 企业业务关系

```
Domain → Business Object → Capability(Query/Command) → Policy → Service → Connector → Enterprise System
```

## 6.4 事务关系

```
Execution → Business Transaction(Saga)
    → Capability → Service → Connector → System
    → Compensation（失败时触发）
```

## 6.5 Runtime 执行关系

```
Execution → Business Transaction → Capability(Query/Command) → Policy → Service → Connector → Enterprise System
Execution → Resource
Execution → Artifact
Execution → Checkpoint
Execution → Trace

Business Transaction → Compensation（失败时触发）
Process Instance → Business Transaction
```
Execution → Trace
```

## 6.5 Planner 工作关系

```
Knowledge (Business Dictionary / Ontology / Capability Metadata)
    ↓
Intent Planner → Intent
    ↓
Task Planner → Plan
    ↓
ValidationResult
```

Planner 不直接访问数据库。Planner 依赖 Knowledge。

## 6.6 Runtime 生命周期

所有 Execution 必须遵循统一生命周期：

```
                    ┌──────────┐
                    │ Created  │
                    └────┬─────┘
                         │
                         ▼
                    ┌──────────┐
                    │ Planning │
                    └────┬─────┘
                         │
                    ┌──────────┐
                    │ Waiting  │
                    └────┬─────┘
                         │
                    ┌──────────┐
              ┌────→│ Running  │
              │     └────┬─────┘
              │          │
              │    ┌─────┴──────┐
              │    │            │
              │    ▼            ▼
              │ ┌────────┐ ┌──────────┐
              │ │ Paused │ │ Retrying │
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
                               │
                               ▼
                         ┌──────────┐
                         │ Feedback │
                         └──────────┘
                               │
                               ▼
                         ┌────────────┐
                         │ Evaluation │
                         └────────────┘
                               │
                    ┌──────────┼──────────┐
                    │          │          │
                    ▼          ▼          ▼
               ┌────────┐ ┌────────┐ ┌────────────┐
               │ Memory  │ │Knowledge│ │  Planner   │
               │ (经验)  │ │ (注入)  │ │ (优化)     │
               └────────┘ └────────┘ └────────────┘
```

---

# 七、对象职责边界

| 对象 | 职责 | 不负责 | 依赖 |
|------|------|--------|------|
| Request | 接收需求 | 不执行 | 无 |
| Intent | 理解需求 | 不规划 | Knowledge / Business Dictionary |
| ValidationResult | 校验计划 | 不执行 | Policy Engine |
| Plan | 描述目标 | 不执行 | 无 |
| Task | 最小工作单元 | 不管理状态 | Capability Center |
| Execution | 管理执行 | 不理解业务 | Resource / Capability / Policy |
| Capability | 提供业务能力 | 不连接系统 | Domain / Service |
| Policy | 控制访问 | 不处理业务 | Policy Engine |
| Service | 实现业务逻辑 | 不理解 Runtime | Connector |
| Connector | 对接企业系统 | 不提供业务语义 | Enterprise System |
| Resource | 提供执行资源 | 不提供业务能力 | Resource Manager |
| Artifact | 保存执行成果 | 不参与执行 | Artifact Center |
| Trace | 记录决策链 | 不参与执行 | Observability Center |
| Checkpoint | 保存可恢复快照 | 不参与执行 | Checkpoint Manager |
| Knowledge | 提供知识 | 不执行推理 | Knowledge Center |
| Memory | 保存状态 | 不提供知识 | Memory Manager |
| Event | 通知变化 | 不处理业务 | EventBus |
| Trigger | 触发执行 | 不解析意图 | Scheduler |
| Business Transaction | 保证跨多 Step 一致性 | 不执行具体 Capability | Execution Runtime |
| Compensation | 回滚/撤销执行结果 | 不执行正向逻辑 | Compensation Manager |
| Process Instance | 管理长期业务流程 | 不执行单次 Task | Execution Runtime |
| Coordination Runtime | 协调多方参与者 | 不推理/不执行 | 无 |
| Goal | 定义可量化目标 | 不生成 Plan | Intent / Constraint |
| Constraint | 定义限制条件 | 不执行 | Goal |
| Decision | 执行中动态决策 | 不规划 | Execution Runtime / Policy |
| Feedback | 收集原始反馈数据 | 不分析 | Execution / Artifact |
| Evaluation | 分析反馈产出结论 | 不执行 | Feedback / Knowledge |

---

# 八、系统设计原则

所有设计必须遵守以下原则：

1. **Runtime 永远操作 Concept，而不是系统。**
2. **Planner 永远规划 Capability，而不是 API。**
3. **Capability 永远代表业务能力，而不是技术能力。**
4. **Capability 区分 Query（查询）和 Command（命令），Command 必须经过审批。**
5. **Connector 永远隐藏企业系统。**
6. **Capability 必须经过 Policy 才能执行。**
7. **Plan 必须经过 Validation 才能执行。**
8. **Knowledge 永远提供语义。**
9. **Memory 永远保存状态。**
10. **Execution 永远管理生命周期。**
11. **所有 Business Transaction 必须注册 Compensation。**
12. **Runtime 必须形成"反馈 → 评估 → 学习 → 优化"的闭环。**
13. **所有模块职责单一，所有对象可独立扩展。**

---

# 九、未来演进

随着平台演进，以下所有模式共享同一套 Concept Model：

- Chat（对话交互）
- Workflow（流程编排）
- Agent（智能代理）
- Multi-Agent（多智能体）
- Scheduled（定时任务）
- Coding Agent（代码代理）
- Browser Agent（浏览器代理）

所有模式跑在 **三引擎（Reasoning + Execution + Coordination）** 之上，通过 **Feedback + Evaluation** 形成持续学习的闭环。

Concept Model 保持稳定，实现可以持续迭代。

**Concept 是平台最稳定的资产。**

---

# 附录 A：v1.2 → v1.3 变更记录

| 变更 | 类型 | 说明 |
|------|------|------|
| Intent | 重构 | 新增 Goal / Constraint 作为输出部分 |
| 5.4 Goal | 🔴 新增 | 可量化目标，携带 Constraints |
| 5.5 Constraint | 🔴 新增 | 目标执行的限制条件 |
| 5.23 Decision | 🔴 新增 | 执行中动态决策（Rule / LLM / ML） |
| 5.24 Feedback | 🔴 新增 | 原始执行反馈数据 |
| 5.25 Evaluation | 🔴 新增 | Feedback 的分析结论 |
| 第四章核心对象总览图 | 重构 | 增加闭环链，变三条链为四条链 |
| 第 12 条设计原则 | 新增 | Closed-loop Intelligence |
| 生命周期 | 重构 | 增加 Feedback / Evaluation / Memory / Knowledge 作为生命周期延续 |
| 事件表 | 优化 | 增加 DecisionMade / FeedbackCollected / EvaluationCompleted |

---

# 附录 B：v1.1 → v1.2 变更记录

| 变更 | 类型 | 说明 |
|------|------|------|
| 5.10 Capability | 重构 | 拆分为 Query / Command CQRS 模式 |
| 5.22 Business Transaction | 🔴 新增 | 跨多 Capability 的 Saga 事务单元 |
| 5.23 Compensation | 🔴 新增 | Command Capability 的补偿/回滚动作 |
| 5.24 Process Instance | 🔴 新增 | 长期运行的业务流程实例 |
| 5.25 Coordination Runtime | 🔴 新增 | 协调引擎的概念定义 |
| 第四章核心对象总览图 | 重构 | 增加 Capability CQRS、Business Transaction、Compensation 节点 |
| 三条链 | 重构 | 增加"事务链"（Execution → Transaction → Compensation） |
| 第七章职责边界表 | 优化 | 增加 Business Transaction / Compensation / Process Instance / Coordination Runtime |

---

# 附录 B：v1.0 → v1.1 变更记录

| 变更 | 类型 | 说明 |
|------|------|------|
| 5.4 ValidationResult | 🔴 新增 | Plan 的校验结果，使架构中 Planner 防御机制在概念层体现 |
| 5.14 Policy | 🔴 新增 | Capability 的执行策略关卡 |
| 5.17 Trace | 🟡 新增 | Execution 的决策链记录 |
| 5.18 Checkpoint | 🟡 新增 | Execution 的可恢复快照 |
| 5.22 Trigger / Schedule | 🟡 新增 | 任务启动条件 |
| 第四章核心对象总览图 | 重构 | 增加 ValidationResult / Policy 节点，标注两条链汇聚点 |
| 第六章对象关系 | 重构 | 增加新概念的关联关系和事件表 |
| 第七章职责边界表 | 优化 | 补充"依赖"列 |
