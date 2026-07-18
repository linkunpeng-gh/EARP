# Schedule & Trigger Specification v1.0

## EARP 调度与触发器规范

**文档编号：L2-10-SCHEDULE**  
**版本：v1.0**  
**定位：L2 — 平台规范。定义 EARP 的定时调度和事件触发器——Cron 任务 + Event 触发 + Workflow 自动启动。**  
**依赖：L1/enterprise-architecture.md (Schedule 领域), L2-01-RUNTIME v1.3, L2-04-WORKFLOW v1.1, L2-07-TENANT v1.1**

---

# 第一章：概述

## 1.1 定位

Schedule & Trigger 负责在特定时间或特定事件发生时自动启动 Runtime 执行。

**两种触发模式：**

| 模式 | 触发条件 | 典型场景 |
|:-----|:---------|:---------|
| Schedule（定时） | Cron 表达式 / 固定间隔 | 每日报表生成、库存定时巡检 |
| Trigger（事件） | EventBus 事件到达 | 设备告警→自动诊断、工单状态变更→通知 |

## 1.2 边界

**负责：**
- Schedule 定义（Cron/Interval）
- Trigger 定义（事件匹配规则）
- 触发后自动创建 Session + Execution
- 触发历史记录

**不负责：**
- ❌ Workflow 执行（Workflow Compiler → Runtime）
- ❌ 事件发布（EventBus Spec）
- ❌ 告警通知（Observation Spec 第五章）

---

# 第二章：Schedule（定时调度）

## 2.1 调度类型

```
MUST: 支持以下调度类型
  - cron:    Cron 表达式（如 "0 8 * * 1-5" = 工作日早上 8 点）
  - interval: 固定间隔（如 "every 30m"、"every 2h"）

SHOULD: 支持以下时间窗口
  - timezone: 时区（默认 UTC）
  - start_at: 调度生效开始时间
  - end_at:   调度生效结束时间（可选）
```

## 2.2 Schedule 定义

```
MUST: Schedule 包含以下字段
  - schedule_id:      string        — 全局唯一
  - tenant_id:        string        — 租户隔离
  - name:             string        — 名称
  - schedule_type:    "cron" | "interval"
  - expression:       string        — Cron 表达式 或 间隔字符串
  - workflow_id:      string        — 触发的 Workflow ID
  - input_params:     dict          — 传入 Workflow 的参数（SHOULD）
  - status:           "active" | "paused" | "disabled"
  - last_run_at:      string | null — 最近一次执行时间
  - next_run_at:      string | null — 下一次执行时间
  - created_at:       string
```

## 2.3 执行行为

```
MUST: Schedule 触发时自动创建 Session + Execution
  - session = Runtime.create_session(tenant_id, user_id="system", metadata={schedule_id: ...})
  - execution = Runtime.execute(workflow_id, params=input_params)

MUST: 同一 Schedule 的上一次执行未完成时不触发新执行（skip）
SHOULD: skip 行为可配置为 "skip" | "queue" | "parallel"
```

---

# 第三章：Trigger（事件触发）

## 3.1 触发类型

```
MUST: Trigger 监听 EventBus 上的事件，匹配规则后触发 Workflow

MUST: Trigger 包含以下字段
  - trigger_id:       string        — 全局唯一
  - tenant_id:        string        — 租户隔离
  - name:             string        — 名称
  - event_type:       string        — 匹配的事件类型（支持通配符 *）
  - event_filter:     dict          — 事件字段过滤条件（如 {"alarm_level": "critical"}）
  - workflow_id:      string        — 触发的 Workflow ID
  - status:           "active" | "paused" | "disabled"
```

## 3.2 过滤器语法

```
SHOULD: event_filter 支持以下操作符
  - eq:    等于    {"alarm_level": {"eq": "critical"}}
  - in:    包含    {"alarm_type": {"in": ["overheat", "vibration"]}}
  - gt/lt: 大于/小于  {"temperature": {"gt": 80}}
  - regex: 正则匹配  {"message": {"regex": "ERROR.*timeout"}}
```

## 3.3 执行行为

```
MUST: Trigger 匹配事件后自动创建 Session + Execution
  - 事件数据注入 Execution.params（如原事件 payload）
  - user_id 取自事件中的 user_id 字段，无则为 "system"
```

---

# 第四章：调度历史

## 4.1 执行记录

```
MUST: 每次 Schedule/Trigger 触发后记录执行历史
  - history_id:       string
  - schedule_id/trigger_id: string
  - execution_id:     string        — 关联的 Execution
  - triggered_at:     string        — 触发时间
  - status:           "success" | "failed" | "skipped"
  - error_message:    string | null
```

## 4.2 审计

```
MUST: Schedule/Trigger 触发时发布审计事件
  - schedule.triggered    {schedule_id, execution_id, trigger_reason}
  - trigger.triggered     {trigger_id, event_type, execution_id}
```

---

# 第五章：多租户隔离

```
MUST: Schedule 和 Trigger 按 tenant_id 隔离
MUST: 不可跨租户创建/修改/触发
MUST: 触发后的 Session/Execution 继承 scheduler 的 tenant_id
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec v1.3 | Schedule/Trigger → create_session + execute |
| Workflow Spec v1.1 | workflow_id 绑定 Workflow |
| Multi-Tenant Spec v1.1 | tenant_id 隔离 |
| EventBus Spec v1.1 | Trigger 监听事件；发布 triggered 审计事件 |
| Audit Spec v1.1 | 触发审计事件 |
