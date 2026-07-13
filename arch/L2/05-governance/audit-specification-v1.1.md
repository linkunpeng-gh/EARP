# Audit Specification v1.1

## EARP 审计规范

**文档编号：L2-05-AUDIT**
**版本：v1.1**
**定位：L2 — 平台规范。Audit 是 EARP 的统一审计基础设施，负责所有执行的日志记录与溯源。**
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-01-runtime/runtime-specification.md, L2-01-runtime/eventbus-specification-v1.1.md（事件类型来源）**

---

> **v1.1 变更**：移除独立的事件类型列表。Audit 订阅 EventBus 事件（事件类型由 EventBus Specification 第 3 章唯一注册表定义），本文仅定义各模块的审计记录**详细程度和要求**，不再重复定义事件类型名称。

---

# 第一章：概述

## 1.1 定位

所有模块的审计要求统一由 Audit 规范定义，不在各模块中各自为政。

### 边界

**负责：** 审计日志格式、存储与保留、溯源、防篡改
**不负责：** ❌ 策略评估、❌ 指标收集、❌ 执行追踪

### 事件来源

Audit 系统通过订阅 **EventBus** 获取审计事件。事件类型由 **EventBus Specification v1.1+ 第 3 章** 统一注册表定义，本文不重复定义。

Audit 自动订阅的事件类型包括（完整列表见 EventBus Spec 第 3 章）：
- `runtime.*` — 运行时生命周期事件
- `planner.*` — 规划器事件
- `decision.*` — 决策事件（v1.0 中的 `runtime.decision.*`）
- `capability.*` — Capability 调用事件
- `policy.*` — 策略评估事件

---

# 第二章：审计日志格式

## 2.1 统一字段

```
MUST: 每条审计日志包含
  - log_id:        string    — 全局唯一
  - timestamp:     timestamp — 事件时间
  - source:        string    — 来源（runtime/planner/decision/capability/policy）
  - event_type:    string    — 事件类型（引用 EventBus Spec 第 3 章注册表）
  - tenant_id:     string    — 租户
  - user_id:       string    — 用户
  - execution_id:  string    — Execution（SHOULD）
  - subject:       string    — 操作对象（SHOULD）
  - action:        string    — 操作
  - result:        "success" | "failure" | "pending"
  - detail:        dict      — 详细信息（SHOULD）
```

> **v1.1 变更**：`event_type` 字段从"本文定义"改为"引用 EventBus Spec 第 3 章"。

---

# 第三章：各模块审计要求（v1.1 更新）

本章定义各模块的**审计详细程度**，不定义事件类型。事件类型已在 EventBus Spec 中注册。

| 模块 | 审计要求 |
|------|---------|
| **Runtime** | 记录 Execution/Session 创建与完成、状态转换、超时、Checkpoint。事件来源：`runtime.*` |
| **Planner** | 记录 Intent Parsing（输入+输出）、Plan 生成（完整 DAG）、Validation 失败、RePlan。事件来源：`planner.*` |
| **Decision** | 记录每次评估（类型、分支、置信度）、Fallback。事件来源：`runtime.decision.*` |
| **Capability** | Command 记录完整输入输出（detail），Query 记录摘要（summary），补偿触发。事件来源：`capability.*` |
| **Policy** | 记录每次评估（policy_id/result/reason）、审批请求、Rate Limit 触发。事件来源：`policy.*` |

### LLM 审计特别要求

```
MUST: LLM Planner 和 LLM Decision 的完整 Prompt + Response 必须记录
SHOULD: LLM Prompt+Response 保留 30 天
MUST: LLM 审计记录受哈希链保护（见第五章）
```

### v1.1 规范补充

```
MUST: Audit 订阅者在 EventBus 上注册对以下事件组的所有匹配事件：
  - runtime.*.succeeded / runtime.*.failed
  - runtime.*.created / runtime.*.completed
  - planner.* / capability.* / policy.*
  - runtime.decision.*
  
SHOULD: 通过 EventBus 的事件过滤功能（按 type / source / tenant_id）分流审计记录
MUST: 事件体（data 字段）的原始内容与审计日志中的 detail 字段保持一致
```

---

# 第四章：存储与保留

> 与 v1.0 第 4 章一致。

---

# 第五章：防篡改

> 与 v1.0 第 5 章一致。

---

# 第六章：决策链溯源

> 与 v1.0 第 6 章一致。

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| EventBus Spec v1.1 — 第 3 章 | **事件类型唯一来源**。Audit 订阅 EventBus 事件 |
| Runtime Spec — Event | Audit 订阅 Runtime Event（事件类型引用 EventBus Spec）|
| Planner Spec | Plan 记录进入审计 |
| Decision Engine Spec | 决策记录进入审计 |
| Capability Center Spec | 调用记录进入审计 |
| Policy Center Spec | 评估记录进入审计 |

---

# 附录 B：v1.0 → v1.1 变更

| 变更 | v1.0 | v1.1 |
|------|------|------|
| 事件类型定义 | 第 2.2 节独立定义 ~15 种事件类型 | **删除**，改为"事件类型引用 EventBus Spec 第 3 章" |
| 事件类型风险 | 与 EventBus Spec 各自维护，存在不一致 | 单一注册表（EventBus Spec），消除不一致 |
| 第 2.1 节 event_type | 依赖于本文定义的事件列表 | 指向 EventBus Spec 注册表 |
| 新增条款 | 无 | 第 3 章增加 Audit 订阅者 MUST 条款 |
