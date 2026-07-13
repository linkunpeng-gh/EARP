# EventBus Specification v1.1

## EARP 事件总线规范

**文档编号：L2-01-EVENTBUS**
**版本：v1.1**
**定位：L2 — 平台规范。EventBus 是 EARP 的事件基础设施层，负责模块间事件发布、订阅、回放与持久化。EventBus 规范是所有事件的**唯一注册表**——Audit/Observation 等规范引用此处，不重新定义事件类型。
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-01-runtime/runtime-specification.md**

---

> **v1.1 变更**：
> 1. CloudEvents 版本修正：统一为 CloudEvents 1.0 (specversion: "1.0")
> 2. 事件类型列表宣布为唯一注册表

---

# 第一章：概述

> 与 v1.0 第 1 章一致，仅补充以下声明：

**v1.1 声明**：本文定义 EARP 全部事件类型的**唯一注册表**。以下规范不得重新定义事件类型，应引用本文：
- Audit Specification — 审计事件类型引用本文 3.2 节
- Observation Specification — Trace 订阅事件类型引用本文 3.2 节
- Runtime Specification — 生命周期事件引用本文 3.2 节
- Policy Center Specification — 策略事件引用本文 3.2 节

任何新增事件类型必须在本规范中注册。

### 与 MessageBus 的关系

```
EventBus（本规范）: Runtime 内部模块间通信。轻量、进程内优先、CloudEvents 标准。
MessageBus（集成层）: 外部系统消息接入（Kafka / RabbitMQ / MQTT）。重量、持久化、重试。

EventBus 用于 Runtime 内部，MessageBus 用于与外部系统集成。
```

### 边界

**负责：** 事件发布/订阅、持久化/回放、路由/过滤、格式标准化、**事件类型注册表（唯一）**
**不负责：** ❌ 执行 Capability、❌ 消息队列集成、❌ 审计日志存储

---

# 第二章：事件格式

## 2.1 CloudEvents 1.0

```
MUST: 事件格式符合 CloudEvents 1.0 规范
MUST: 每个事件包含
  - id:              string    — 全局唯一
  - source:          string    — 来源（如 "earp.runtime"）
  - specversion:     string    — "1.0"
  - type:            string    — 事件类型（见第三章注册表）
  - time:            timestamp — 事件时间
  - subject:         string    — 关联对象 ID（SHOULD）
  - datacontenttype: string    — "application/json"
  - data:            any       — 负载（SHOULD）
```

> **v1.1 修正**：CloudEvents 规范的版本编号为 **1.0**（specversion: "1.0"），事件遵循 CloudEvents 1.0 规范。v1.0 中误写为 "CloudEvents 2.0"（指 CloudEvents 规范的概念版本而非 specversion 字段值），v1.1 更正。

示例：

```json
{
  "id": "evt_001",
  "source": "earp.runtime",
  "specversion": "1.0",
  "type": "runtime.execution.succeeded",
  "time": "2026-06-27T08:30:00Z",
  "subject": "exec_001",
  "datacontenttype": "application/json",
  "data": { "tenant_id": "t1", "duration_ms": 2340 }
}
```

## 2.2 扩展属性

```
SHOULD: 可携带 tenant_id / correlation_id / priority
```

---

# 第三章：事件类型注册表（唯一来源）

> **v1.1 声明**：本章是 EARP **事件类型的唯一注册表**。任何规范（Audit、Observation、Policy等）不得重新定义事件类型列表。新增事件类型必须在此注册。
>
> 事件类型按来源模块分组，每组有统一的前缀命名空间。

## 3.1 Runtime 生命周期

| 事件类型 | 触发时机 | 负载示例 |
|----------|---------|---------|
| `runtime.session.created` | Session 创建 | `{ session_id, tenant_id, user_id }` |
| `runtime.session.completed` | Session 完成 | `{ session_id, duration_ms }` |
| `runtime.execution.created` | Execution 创建 | `{ execution_id, mode, session_id }` |
| `runtime.execution.planning` | 开始规划 | `{ execution_id, planner_type }` |
| `runtime.execution.decisioning` | 开始决策 | `{ execution_id, step_id }` |
| `runtime.execution.queued` | 进入队列 | `{ execution_id, queue_position }` |
| `runtime.execution.running` | 开始执行 | `{ execution_id, step_id }` |
| `runtime.execution.waiting` | 等待（审批/外部） | `{ execution_id, wait_reason }` |
| `runtime.execution.paused` | 暂停 | `{ execution_id }` |
| `runtime.execution.resumed` | 恢复 | `{ execution_id }` |
| `runtime.execution.retrying` | 重试 | `{ execution_id, retry_count }` |
| `runtime.execution.compensating` | 补偿 | `{ execution_id, step_id }` |
| `runtime.execution.succeeded` | 执行成功 | `{ execution_id, duration_ms }` |
| `runtime.execution.failed` | 执行失败 | `{ execution_id, error_code, error_message }` |
| `runtime.execution.cancelled` | 取消 | `{ execution_id, reason }` |
| `runtime.execution.archived` | 归档 | `{ execution_id }` |
| `runtime.execution.completed` | 执行完成（终态） | `{ execution_id, final_status }` |

## 3.2 Decision

| 事件类型 | 触发时机 | 负载示例 |
|----------|---------|---------|
| `runtime.decision.evaluated` | 决策评估完成 | `{ decision_id, decision_type, selected_branch, confidence }` |
| `runtime.decision.fallback` | 使用兜底分支 | `{ decision_id, fallback_reason }` |

## 3.3 Transaction

| 事件类型 | 触发时机 | 负载示例 |
|----------|---------|---------|
| `runtime.transaction.started` | 事务开始 | `{ transaction_id, execution_id }` |
| `runtime.transaction.completed` | 事务完成 | `{ transaction_id, steps }` |
| `runtime.transaction.failed` | 事务失败 | `{ transaction_id, failed_step_id }` |
| `runtime.transaction.compensated` | 事务已补偿 | `{ transaction_id, compensation_actions }` |

## 3.4 Resource

| 事件类型 | 触发时机 | 负载示例 |
|----------|---------|---------|
| `runtime.resource.allocated` | 资源分配 | `{ resource_type, resource_id, execution_id }` |
| `runtime.resource.exhausted` | 资源耗尽 | `{ resource_type, tenant_id }` |
| `runtime.resource.released` | 资源释放 | `{ resource_type, resource_id }` |

## 3.5 Policy

| 事件类型 | 触发时机 | 负载示例 |
|----------|---------|---------|
| `policy.evaluated` | 策略评估完成 | `{ policy_id, result, execution_id }` |
| `policy.approval.requested` | 审批请求 | `{ approval_id, policy_id, execution_id }` |
| `policy.approval.completed` | 审批完成 | `{ approval_id, result, approver }` |
| `policy.rate_limit.exceeded` | 限流触发 | `{ policy_id, tenant_id, capability_id }` |

## 3.6 Feedback & Evaluation

| 事件类型 | 触发时机 | 负载示例 |
|----------|---------|---------|
| `runtime.feedback.collected` | 反馈已收集 | `{ execution_id, feedback_type, metrics }` |
| `runtime.evaluation.completed` | 评估完成 | `{ evaluation_id, capability_id, score }` |
| `runtime.learning.injected` | 学习注入完成 | `{ target: "memory"|"knowledge"|"planner", summary }` |

## 3.7 Capability

| 事件类型 | 触发时机 | 负载示例 |
|----------|---------|---------|
| `capability.called` | Capability 被调用 | `{ capability_id, execution_id, type(Query/Command) }` |
| `capability.succeeded` | Capability 成功 | `{ capability_id, duration_ms }` |
| `capability.failed` | Capability 失败 | `{ capability_id, error_code }` |
| `capability.compensation.triggered` | 补偿触发 | `{ capability_id, origin_execution_id }` |

## 3.8 Planner

| 事件类型 | 触发时机 | 负载示例 |
|----------|---------|---------|
| `planner.intent.parsed` | Intent 解析完成 | `{ plan_id, intent, domain }` |
| `planner.plan.generated` | Plan 生成完成 | `{ plan_id, task_count, planner_type }` |
| `planner.plan.validation_failed` | Plan 校验失败 | `{ plan_id, reason }` |
| `planner.plan.replanned` | Plan 重规划 | `{ plan_id, original_plan_id, reason }` |

---

# 第四章：发布与订阅

> 与 v1.0 第 4 章一致。

---

# 第五章：持久化与回放

> 与 v1.0 第 5 章一致。

---

# 第六章：约束

> 与 v1.0 第 6 章一致。

---

# 第七章：死信队列

> 与 v1.0 第 7 章一致。

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec — Lifecycle | 状态转换触发事件，事件类型引用本文第 3 章 |
| Runtime Spec — Feedback | Feedback 通过 EventBus 驱动，事件类型引用本文 3.6 节 |
| Audit Spec | Audit 订阅 EventBus，**事件类型引用本文第 3 章，不重新定义** |
| Observation Spec | Trace 订阅 EventBus，事件类型引用本文第 3 章 |
| Policy Center Spec | 策略事件通过 EventBus 发布，事件类型引用本文 3.5 节 |

---

# 附录 B：v1.0 → v1.1 变更

| 变更 | v1.0 | v1.1 |
|------|------|------|
| CloudEvents 版本 | "CloudEvents 2.0" + specversion "1.0"（矛盾） | 统一为 "CloudEvents 1.0"，specversion "1.0" |
| 事件类型声明 | 隐含为参考列表 | 显式声明为**唯一注册表**，Audit/Observation 等规范须引用 |
| 事件类型扩展 | Runtime 23 种 + 其他杂项 | 按模块分组 8 个命名空间，~45 种事件，组名前缀清晰 |
| 规范依赖 | 被动引用 | 主动声明哪些规范应引用本文的事件类型 |
