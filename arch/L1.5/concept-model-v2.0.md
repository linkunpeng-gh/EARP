# Runtime 核心概念模型（Concept Model）

**Version：v2.0**

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

**v2.0 变更**：修正了 v1.3 中的章节编号重复问题（5.4 和 5.6 各出现两次）。编号从 5.1 到 5.31 连续，无跳跃无重复。

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

## 5.7 Domain
> 与 v1.3 5.6 节一致。

## 5.8 Business Object
> 与 v1.3 5.6（第二个）节一致。

## 5.9 Plan
> 与 v1.3 5.7 节一致。

## 5.10 Task
> 与 v1.3 5.8 节一致。

## 5.11 Execution
> 与 v1.3 5.9 节一致。

## 5.12 Capability（CQRS）
> 与 v1.3 5.10 节一致。

## 5.13 Service
> 与 v1.3 5.11 节一致。

## 5.14 Connector（Adapter）
> 与 v1.3 5.12 节一致。

## 5.15 Enterprise System
> 与 v1.3 5.13 节一致。

## 5.16 Policy
> 与 v1.3 5.14 节一致。

## 5.17 Resource
> 与 v1.3 5.15 节一致。

## 5.18 Artifact
> 与 v1.3 5.16 节一致。

## 5.19 Trace
> 与 v1.3 5.17 节一致。

## 5.20 Checkpoint
> 与 v1.3 5.18 节一致。

## 5.21 Memory

> **v2.0 新增正式定义**。v1.3 中 Memory 仅有简要表格，但未与 Knowledge 明确分界。v2.0 扩展为完整章节。
>
> 变化矩阵：v1.3 5.19 → v2.0 5.21

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

## 5.22 Knowledge

> 从 v1.3 5.20 提升。内容与 v1.3 一致。

## 5.23 Decision

> 与 v1.3 5.23 节一致。v1.3 中 5.21/5.22 缺失已补为 Memory 和 Knowledge。

## 5.24 Feedback

> 与 v1.3 5.24 节一致。

## 5.25 Evaluation

> 与 v1.3 5.25 节一致。

## 5.26 Business Transaction

> 与 v1.3 5.26 节一致。

## 5.27 Compensation

> 与 v1.3 5.27 节一致。

## 5.28 Process Instance

> 与 v1.3 5.28 节一致。

## 5.29 Coordination Runtime

> 与 v1.3 5.29 节一致。

## 5.30 Event

> 与 v1.3 5.30 节一致。

## 5.31 Trigger / Schedule

> 与 v1.3 5.31 节一致。

---

# 六、对象关系

## 6.1 关联关系总表

> 与 v1.3 6.1 节一致。

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

---

# 附录 A：概念链与 Runtime Loop 映射

> **v2.0 新增**。将 Concept Model 的 4 条概念链映射到 Runtime Spec 的 3 个执行循环，消除读者在概念层和规范层之间的理解断层。

## A.1 四条概念链回顾

```
执行链（Runtime 视角）：
  User → Request → Intent → ValidationResult → Plan → Task → Execution → Artifact

业务链（企业视角）：
  Domain → Business Object → Capability(Query/Command) → Policy → Service → Connector → Enterprise System

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

## A.3 映射关系

| 概念链 | 对应 Loop / 路径 | 说明 |
|--------|-----------------|------|
| **执行链** | Loop 1 的 `Request → Execution → Artifact` 段 | 主线：用户发起到产物生成 |
| **业务链** | Loop 1 中 `Execution → Capability → Service → Connector → System` 段 | 执行链到达 Capability 后进入业务领域 |
| **事务链** | Loop 1 中 Execution 内部 `Business Transaction → Compensation` 路径 | Execution 执行 Capability 时自动触发 |
| **闭环链** | Loop 1 末段 `Execution → Feedback → Evaluation → Memory/Knowledge → Planner` | 这是唯一的闭环学习路径 |

### 补充说明

- **业务链不单独成为一个 Loop**：因为它触发在 Execution 调用 Capability 时，是 Loop 1 的子路径。Coordination Runtime 不直接参与业务链，但 Agent/Workflow 可通过 Coordination Runtime 触发 Execution。
- **事务链不单独成为一个 Loop**：因为它内嵌在 Execution 的 Step 执行流程中，是 Loop 1 的子路径。Compensation 是事务链的异常分支——Execution 在失败时从主路径进入补偿子路径。
- **Loop 2（事件驱动）不直接对应任何概念链**：外部事件（MES 报警、审批回调）是系统的输入来源之一，Trigger 生成 Request 后进入 Loop 1。这是作为 Runtime 的统一入口机制，不是独立的概念链。
- **Loop 3（反思与重规划）是闭环链的子集**：当闭环链中的 Evaluation 判定"不满意"时，触发重规划（Replan），形成 Loop 3。

```
可视化映射：

概念链：    执行链 ──→ 业务链 ──→ 事务链 ──→ 闭环链
            │          │          │          │
            ▼          ▼          ▼          ▼
Runtime：   [────── Loop 1: 主动执行链 ──────]    ← 主线
            │                     │
            │          Loop 2: 事件驱动        ← 旁路（外部输入）
            │                     │
            │          Loop 3: 反思/重规划     ← 旁路（闭环的子集）
```

---

# 附录 B：v1.3 → v2.0 变更

| 变更 | v1.3 | v2.0 |
|------|------|------|
| 章节编号 | 5.4 重复（Goal / ValidationResult），5.6 重复（Domain / Business Object），5.21/5.22 缺失 | 全部修正为连续编号 5.1-5.31 |
| Memory | 仅有简要分层表格（5.19），无与 Knowledge 的分界 | 扩展为独立完整章节（5.21），增加 Memory vs Knowledge 分界表 |
| 链-Loop 映射 | 无 | 附录 A，消除概念层与规范层之间的理解断层 |
| v1.3 原文内容 | — | 所有未标记"v2.0 新增"的章节内容与 v1.3 完全一致 |
