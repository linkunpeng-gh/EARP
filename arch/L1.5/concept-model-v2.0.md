# Runtime 核心概念模型（Concept Model）

**Version：v2.1**

> 定位：**L1.5** — 介于 L1 Architecture 与 L2 Specification 之间的 Ubiquitous Language。
>
> 所有 L2 文档（Runtime / Planner / Capability / Workflow / Agent 的技术规范）的"核心概念"章节必须引用本文，**不允许重新定义** `Task`、`Execution`、`Capability`、`Goal`、`Decision`、`Feedback` 等术语。
>
> 本文不涉及具体实现，不定义数据库，不定义接口，仅定义系统核心对象及对象关系。

---

# 一、文档目的

> 与 v1.3 第 1 章一致。

---

# 二、设计目标

> 与 v1.3 第 2 章一致。

---

# 三、核心设计思想

> 与 v1.3 第 3 章一致。

---

# 四、核心对象总览

> 与 v1.3 第 4 章一致，但对象编号已修正（见第五章）。

---

# 五、Runtime 核心对象

**v2.0 变更**：修正了 v1.3 中的章节编号重复问题（5.4 和 5.6 各出现两次）。编号从 5.1 到 5.32 连续，无跳跃无重复。

## 5.1 User
> 与 v1.3 5.1 节一致。

## 5.2 Request
> 与 v1.3 5.2 节一致。

## 5.3 Intent
> 与 v1.3 5.3 节一致。

## 5.4 Goal
> 与 v1.3 5.4 节一致（原为 5.4，不变）。

## 5.5 Constraint
> 与 v1.3 5.5 节一致。

## 5.6 ValidationResult
> 与 v1.3 5.4（错标）节一致。v1.3 中此节被误标为 5.4（与 Goal 重复），v2.0 修正为 5.6。

## 5.7 Business Domain
> 与 v1.3 5.6 节一致。

> **v2.1 变更**：从 Domain 更名为 **Business Domain**，明确其 Capability 归属边界的语义。新增平行概念 Data Domain（§5.8）。
>
> Business Domain 回答的是"这是哪个业务领域的能力"，Data Domain 回答的是"这是哪个领域的数据和知识"。两者是平行关系，一个 Business Domain 可能对应一个或多个 Data Domain。
>
> ### Business Domain 结构
>
> | 字段 | 说明 |
> |------|------|
> | domain_id | 全局唯一标识 |
> | name | 业务领域名称（如"设备管理""人力资源"） |
> | description | 业务描述 |
> | owner | 领域负责人/团队 |
> | mapped_data_domains | 关联的 Data Domain 列表（N:M） |
>
> ### Business Domain 与 Data Domain 的关系
>
> | 关系模式 | 说明 | 示例 |
> |----------|------|------|
> | 1:1 | 一个业务领域对应一个数据域 | Equipment BD ↔ Equipment Data |
> | 1:N | 一个业务领域引用多个数据域 | Production BD ↔ Equipment Data + Quality Data |
> | N:M | 多个业务领域共享同一数据域 | HR BD + Finance BD 共享 Corporate Data（公司制度） |
> | BD only | 只有业务能力，无专属知识 | 某些纯网关型 Capability |
> | DD only | 只有知识，无业务能力 | 企业价值观文档、全员安全手册 |
>
> ### Business Domain 契约
>
> ```
> MUST: Business Domain 是 Capability 的唯一归属边界
> MUST: 一个 Capability 只能属于一个 Business Domain
> SHOULD: Business Domain 至少关联一个 Data Domain
> MAY: 一个 Business Domain 关联多个 Data Domain
> MAY: 存在无对应 Business Domain 的 Data Domain（纯知识域）
> ```

## 5.8 Data Domain（v2.1 新增）

> **v2.1 新增**。Data Domain 是企业数据与知识的**领域归属边界**，是 Business Domain 的平行概念。
>
> Data Domain 回答"这些数据/知识属于哪个业务领域"，确保 AI 在回答用户问题时始终基于企业知识，而非 LLM 自身知识。
>
> ### 定义
>
> Data Domain 是企业数据的逻辑分组——它不是存储分区，不是数据库实例，而是知识治理和检索路由的基本单元。
>
> ### Data Domain 结构
>
> | 字段 | 说明 |
> |------|------|
> | data_domain_id | 全局唯一标识 |
> | name | 数据域名称（如"设备数据""HR 政策""财务制度"） |
> | description | 域描述 |
> | data_classification | 数据分类等级（public / internal / confidential / restricted） |
> | owner | 域负责人 |
> | mapped_business_domains | 关联的 Business Domain 列表（N:M） |
>
> ### Data Domain 包含的内容
>
> 一个 Data Domain 包含三类知识资产：
>
> | 资产类型 | 说明 | 管理位置 |
> |----------|------|---------|
> | 业务文档 | 政策、手册、报告、制度文件 | Knowledge Center（RAG） |
> | 业务词典 | 该领域的术语映射和同义词 | Knowledge Center（Business Dictionary） |
> | 本体模型 | 该领域的实体关系和属性 | Knowledge Center（Ontology） |
>
> ### 与 Business Domain 的关系
>
> | 维度 | Business Domain | Data Domain |
> |------|----------------|-------------|
> | 关注点 | 能力归属（能做什么） | 知识归属（知道什么） |
> | 主要消费者 | Resolution Engine / Planner | Planner（RAG）/ Chat / Agent |
> | 变更频率 | 低（月/季度级） | 中（天/周级，文档持续更新） |
> | 生命周期 | 与 Capability 版本耦合 | 与知识资产生命周期耦合 |
> | 治理维度 | 权限（谁可以调用） | 权限 + 数据分类（谁可以查看） |
> | 为空时的影响 | 无 Capability 可用 | AI 回答依赖 LLM 自身知识 |
>
> ### Data Domain 契约
>
> ```
> MUST: 每个知识资产（文档 / 词条 / 实体）必须属于一个 Data Domain
> MUST: Knowledge Center 的 RAG 检索支持按 Data Domain 过滤
> MUST: Business Dictionary 词条标注所属 Data Domain
> MUST: Ontology 实体标注所属 Data Domain
> SHOULD: 一次检索请求可以指定多个 Data Domain（跨域查询）
> SHOULD: Data Domain 支持 level 层级（如 Equipment 可拆为 Equipment-Sensor 子域）
> MAY: Data Domain 可与 Business Domain 同名，但概念上各自独立
> ```

## 5.9 Business Object
> 与 v1.3 5.6（第二个）节一致。

## 5.10 Plan
> 与 v1.3 5.7 节一致。

## 5.11 Task
> 与 v1.3 5.8 节一致。

## 5.12 Execution
> 与 v1.3 5.9 节一致。

## 5.13 Capability（CQRS）
> 与 v1.3 5.10 节一致。

## 5.14 Service
> 与 v1.3 5.11 节一致。

## 5.15 Connector（Adapter）
> 与 v1.3 5.12 节一致。

## 5.16 Enterprise System
> 与 v1.3 5.13 节一致。

## 5.17 Policy
> 与 v1.3 5.14 节一致。

## 5.18 Resource
> 与 v1.3 5.15 节一致。

## 5.19 Artifact
> 与 v1.3 5.16 节一致。

## 5.20 Trace
> 与 v1.3 5.17 节一致。

## 5.21 Checkpoint
> 与 v1.3 5.18 节一致。

## 5.22 Memory

> **v2.0 新增正式定义**。v1.3 中 Memory 仅有简要表格，但未与 Knowledge 明确分界。v2.0 扩展为完整章节。
>
> 变化矩阵：v1.3 5.19 → v2.1 5.22

Memory 表示 Runtime 的**经验累积** — 它记录"过去发生了什么"以及"什么有效、什么无效"。Memory 是 Runtime 学习能力的短期/中期存储。

### Memory 与 Knowledge 的分界

| 维度 | Memory | Knowledge |
|------|--------|-----------|
| 性质 | 经验（动态、上下文相关） | 知识（静态、企业级权威） |
| 来源 | Execution 执行结果 + Feedback | 企业文档 / 人工录入 / 系统导入 |
| 生命周期 | Session 级到日级别 | 月级别到年级别（很少变更） |
| 所有权 | Runtime / 租户 | 企业（统一管理） |
| 典型内容 | "用户李四上次查了 A 产线的报警" | "A 产线报警阈值 = 85°C" |
| 更新频率 | 每次 Execution 后可能更新 | 按需（人工 / 批量导入）|
| 对 Planner 的影响 | 短期行为适配 | 长期业务理解 |

### Memroy 分层

| 层级 | 说明 | 范围 | Phase |
|------|------|------|-------|
| Conversation Memory | 当前 Session 的对话历史 | Session 内 | Phase 1 |
| Episodic Memory | 最近 N 次 Execution 的摘要 | 用户/租户级别 | Phase 1 |
| Working Memory | 执行上下文临时状态（Checkpoint 等） | Session/Execution | Phase 2 |
| Semantic Memory | 实体间的关系和模式识别结果 | 租户级别 | Phase 3 |
| Business Memory | 业务规则调用模式 / 用户偏好 | 租户级别 | Phase 3 |

### 契约

```
MUST: Memory 与 Knowledge 存储分离（不同存储或同一存储的不同命名空间）
MUST: Memory 可过期（TTL 策略，分层不同）
SHOULD: Conversation Memory 保留当前 Session 完整对话
SHOULD: Episodic Memory 保留最近 100 次 Execution 摘要
MUST: Memory 内容由 Evaluation Center 写入（自动化学习）
SHOULD: 支持手动清除 Memory（用户隐私需求）
```

---

## 5.23 Knowledge

> 从 v1.3 5.20 提升。内容与 v1.3 一致。

## 5.24 Decision

> 与 v1.3 5.23 节一致。v1.3 中 5.21/5.22 缺失已补为 Memory 和 Knowledge。

## 5.25 Feedback

> 与 v1.3 5.24 节一致。

## 5.26 Evaluation

> 与 v1.3 5.25 节一致。

## 5.27 Business Transaction

> 与 v1.3 5.26 节一致。

## 5.28 Compensation

> 与 v1.3 5.27 节一致。

## 5.29 Process Instance

> 与 v1.3 5.28 节一致。

## 5.30 Coordination Runtime

> 与 v1.3 5.29 节一致。

## 5.31 Event

> 与 v1.3 5.30 节一致。

## 5.32 Trigger / Schedule

> 与 v1.3 5.31 节一致。

---

# 六、对象关系

## 6.1 关联关系总表

> 与 v1.3 6.1 节一致。

> **v2.1 新增关系**：
>
> | 源对象 | 关系 | 目标对象 | 基数 |
> |--------|------|---------|:----:|
> | Business Domain | maps_to | Data Domain | N:M |
> | Data Domain | owns | Knowledge（文档/词条/实体） | 1:N |
> | Knowledge | belongs_to | Data Domain | N:1 |
>
> Data Domain 是独立于 Business Domain 的一级概念。两者的关系不是包含关系，而是映射关系——一个 Business Domain 映射到零到多个 Data Domain，一个 Data Domain 映射到零到多个 Business Domain。

## 6.2 完整闭环生命周期

> 与 v1.3 6.2 节一致。

## 6.3 Request 生命周期

> 与 v1.3 6.3 节一致。

## 6.4 企业业务关系

> 与 v1.3 6.3 节一致。

## 6.6 Runtime 生命周期

> 与 v1.3 6.6 节一致。

---

# 七、对象职责边界

> 与 v1.3 第 7 章一致。

> **v2.1 新增**：Data Domain 的职责边界
>
> | 职责 | 说明 |
> |------|------|
> | 知识组织 | 将企业数据和文档按域归类，保证检索精度 |
> | 治理边界 | 按 data_classification 控制数据访问权限 |
> | 检索路由 | 作为 Knowledge Center 检索的第一级过滤条件 |
> | 跨域协调 | 支持一次查询跨多个 Data Domain（如对比分析）|
>
> Data Domain **不负责**：存储数据内容（由 Knowledge Center 各模块负责）、定义业务逻辑（由 Business Domain 负责）、执行推理（由 Planner 负责）。

---

# 附录 A：概念链与 Runtime Loop 映射

> **v2.0 新增**。将 Concept Model 的 4 条概念链映射到 Runtime Spec 的 3 个执行循环，消除读者在概念层和规范层之间的理解断层。

## A.1 五条概念链回顾（v2.1 新增知识链）

```
执行链（Runtime 视角）：
  User → Request → Intent → ValidationResult → Plan → Task → Execution → Artifact

业务链（企业视角）：
  Business Domain → Business Object → Capability(Query/Command) → Policy → Service → Connector → Enterprise System

知识链（企业视角 — v2.1 新增）：
  User Request → Intent → Data Domain → Knowledge Center(RAG/Dictionary/Ontology) → LLM 综合回答
  说明：当用户查询答案来自企业知识而非 Capability 调用时，Planner 路由到 Data Domain，
        在限定的知识空间内检索，确保回答基于企业知识而非 LLM 自身知识。

事务链（Execution 保证）：
  Execution → Business Transaction(Saga) → Compensation → Capability → Service → Connector

闭环链（AI Execution Loop）：
  Execution → Artifact → Feedback → Evaluation → Memory/Knowledge → Planner（再次决策——更聪明）
```

## A.2 Runtime Spec 的三个 Loop

```
Session（外层容器）
    ├── Loop 1: 主动执行链
    │   Request → Intent → Goal → Plan → Validation → Execution → Result → Feedback → Evaluation
    │                                                                                        │
    │   └── Memory/Knowledge → Planner（下一次更聪明）←─────────────────────────────────────────┘
    │
    ├── Loop 2: 事件驱动响应链
    │   External Event → Decision → Execution → Result → Feedback → Evaluation → Learning
    │
    └── Loop 3: 反思与重规划链
        Execution Result → Evaluation → Planner(反思)
            ├── 满意 → 继续 / 结束
            └── 不满意 → Replan → 新 Execution
```

## A.3 映射关系（v2.1 更新）

| 概念链 | 对应 Loop / 路径 | 说明 |
|--------|-----------------|------|
| **执行链** | Loop 1 的 `Request → Execution → Artifact` 段 | 主线：用户发起到产物生成 |
| **业务链** | Loop 1 中 `Execution → Capability → Service → Connector → System` 段 | 执行链到达 Capability 后进入业务领域 |
| **知识链** | Loop 1 中 `Intent → Data Domain → Knowledge Center` 段 | v2.1 新增。与业务链平行——用户意图既可能路由到 Business Domain（调用能力），也可能路由到 Data Domain（检索知识）。两者是 or/and 关系 |
| **事务链** | Loop 1 中 Execution 内部 `Business Transaction → Compensation` 路径 | Execution 执行 Capability 时自动触发 |
| **闭环链** | Loop 1 末段 `Execution → Feedback → Evaluation → Memory/Knowledge → Planner` | 这是唯一的闭环学习路径 |

### 补充说明

- **业务链不单独成为一个 Loop**：因为它触发在 Execution 调用 Capability 时，是 Loop 1 的子路径。Coordination Runtime 不直接参与业务链，但 Agent/Workflow 可通过 Coordination Runtime 触发 Execution。
- **知识链不单独成为一个 Loop**：因为它触发在 Intent Parsing 之后、Execution 之前——Planner 在此阶段完成 Domain Routing 的二维决策（Business Domain + Data Domain）。Data Domain 路由到 Knowledge Center 检索后，结果注入 LLM 综合回答，不需要进入 Execution Loop。
- **事务链不单独成为一个 Loop**：因为它内嵌在 Execution 的 Step 执行流程中，是 Loop 1 的子路径。Compensation 是事务链的异常分支——Execution 在失败时从主路径进入补偿子路径。
- **Loop 2（事件驱动）不直接对应任何概念链**：外部事件（MES 报警、审批回调）是系统的输入来源之一，Trigger 生成 Request 后进入 Loop 1。这是作为 Runtime 的统一入口机制，不是独立的概念链。
- **Loop 3（反思与重规划）是闭环链的子集**：当闭环链中的 Evaluation 判定"不满意"时，触发重规划（Replan），形成 Loop 3。

```
可视化映射：

概念链：    执行链 ──→ 业务链 ──→ 知识链 ──→ 事务链 ──→ 闭环链
            │          │          │          │          │
            ▼          ▼          ▼          ▼          ▼
Runtime：   [───────── Loop 1: 主动执行链 ─────────]    ← 主线
            │                     │
            │     Loop 2: 事件驱动                  ← 旁路（外部输入）
            │                     │
            │     Loop 3: 反思/重规划               ← 旁路（闭环的子集）
            │
            │  知识链在 Loop 1 中的位置：
            │  Request → Intent → {Business Domain → Capability（业务路径）
            │                             │
            │                    Data Domain → Knowledge Center（知识路径）}
            │                    ↓
            │                   Planner 合并两条路径的结果 → Plan
```

---

# 附录 B：v1.3 → v2.1 变更

## B.1 v1.3 → v2.0 变更

| 变更 | v1.3 | v2.0 |
|------|------|------|
| 章节编号 | 5.4 重复（Goal / ValidationResult），5.6 重复（Domain / Business Object），5.21/5.22 缺失 | 全部修正为连续编号 5.1-5.31 |
| Memory | 仅有简要分层表格（5.19），无与 Knowledge 的分界 | 扩展为独立完整章节（5.21），增加 Memory vs Knowledge 分界表 |
| 链-Loop 映射 | 无 | 附录 A，消除概念层与规范层之间的理解断层 |
| v1.3 原文内容 | — | 所有未标记"v2.0 新增"的章节内容与 v1.3 完全一致 |

## B.2 v2.0 → v2.1 变更

| 变更 | v2.0 | v2.1 |
|------|------|------|
| §5.7 Domain | 名为 Domain，Capability 归属边界 | 更名为 **Business Domain**，新增 Data Domain 为平行概念（§5.8）|
| §5.8 Data Domain（新增） | 不存在 | 新增为企业数据与知识的领域归属边界，独立于 Business Domain |
| 章节编号 | 5.1-5.31 连续 | 5.1-5.32 连续（新增 Data Domain 后扩展）|
| 对象关系（§6） | Business Domain 与其他对象的关系 | 新增 Business Domain ↔ Data Domain 的 N:M 映射关系 |
| 概念链（附录 A） | 4 条概念链 | 新增"知识链"作为第 5 条概念链，与业务链平行并列 |
| Architecture v6 | Planner 只路由 Business Domain 到 Capability | Planner 同时路由 Business Domain 到 Capability 和 Data Domain 到 Knowledge |
| Knowledge Center | 知识扁平存储，无域级组织 | 知识按 Data Domain 组织，检索支持按域过滤 |
| Policy Center | RBAC 基于 Business Domain | RBAC 同时基于 Business Domain 和 Data Domain |

> **设计动机**：v2.1 的核心目的是让 EARP 在回答业务用户的 Chat 问题时始终基于企业知识（Data Domain），而非 LLM 自身知识。这补全了"Domain First"原则在设计时的缺口——Domain 不仅应该作用于 Capability 的组织（Business Domain），也应该作用于企业知识的组织（Data Domain）。
