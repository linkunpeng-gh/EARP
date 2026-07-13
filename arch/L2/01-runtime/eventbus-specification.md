# EventBus Specification

## EARP 事件总线规范

**文档编号：L2-01-EVENTBUS**
**版本：v1.0**
**定位：L2 — 平台规范。EventBus 是 EARP 的统一事件基础设施，负责模块间的事件发布、订阅、回放与持久化。**

---

# 第一章：概述

## 1.1 定位

EventBus 是 EARP 的**事件基础设施层**。所有模块通过 EventBus 异步通信——Runtime 发布生命周期事件、Planner 发布规划事件、Capability 发布调用事件、Policy 发布策略评估事件。

### 与 MessageBus 的关系

```
EventBus（本规范）: Runtime 内部模块间通信。轻量、进程内优先、CloudEvents 标准。
MessageBus（集成层）: 外部系统消息接入（Kafka / RabbitMQ / MQTT）。重量、持久化、重试。

EventBus 用于 Runtime 内部，MessageBus 用于与外部系统集成。
```

### 边界

**负责：** 事件发布/订阅、持久化/回放、路由/过滤、格式标准化

**不负责：** ❌ 执行 Capability、❌ 消息队列集成、❌ 审计日志存储

---

# 第二章：事件格式

## 2.1 CloudEvents 2.0

```
MUST: 事件格式符合 CloudEvents 2.0
MUST: 每个事件包含
  - id:              string    — 全局唯一
  - source:          string    — 来源（如 "earp.runtime"）
  - specversion:     string    — "1.0"
  - type:            string    — 事件类型
  - time:            timestamp — 事件时间
  - subject:         string    — 关联对象 ID（SHOULD）
  - datacontenttype: string    — "application/json"
  - data:            any       — 负载（SHOULD）
```

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

# 第三章：事件类型

## Runtime 生命周期

runtime.session.created / completed
runtime.execution.created / planning / decisioning / queued / running / waiting / paused / resumed / retrying / compensating / succeeded / failed / cancelled / archived / completed

## Decision

runtime.decision.evaluated / fallback

## Transaction

runtime.transaction.started / completed / failed / compensated

## Resource

runtime.resource.allocated / exhausted / released

## Policy

policy.evaluated / approval.requested / approval.completed / rate_limit.exceeded

## Feedback

runtime.feedback.collected / evaluation.completed / learning.injected

---

# 第四章：发布与订阅

## 4.1 发布

```
MUST: 通过 EventBus.publish() 发布
SHOULD: 支持同步（等订阅者处理完）和异步（立即返回）模式
MUST: 发布失败不影响发布者正常流程
```

## 4.2 订阅

```
MUST: 通过 EventBus.subscribe(type, handler) 注册
SHOULD: 支持按 type / source / tenant_id 过滤
MUST: handler 是幂等的
MUST: handler 超时不超过 5 秒
```

## 4.3 内置持久订阅者

```
MUST: Audit 订阅者（记录所有事件）
MUST: Trace 订阅者（记录事件到链路追踪）
MUST: Feedback 订阅者（收集 Execution 事件用于闭环学习）
```

---

# 第五章：持久化与回放

## 5.1 持久化

```
MUST: 事件保留至少 24 小时
SHOULD: 按类型可配置（Policy 7 天 / Error 30 天）
MUST: 追加写，不可修改已有记录
```

## 5.2 回放

```
SHOULD: 支持按时间范围 / 事件类型 / Session ID 回放
```

---

# 第六章：约束

## 6.1 性能

```
MUST: 发布延迟 < 10ms（同步）
MUST: 支持每秒 10,000+ 事件
MUST: 单个事件不超过 256KB
```

## 6.2 可靠性

```
MUST: 至少投递一次语义
SHOULD: 支持确认机制
SHOULD: 失败自动重试（最多 3 次）
MUST: 重试 3 次失败后进入死信队列
```

---

# 第七章：死信队列

```
MUST: 死信事件保留 7 天
SHOULD: 支持手动重试
MUST: 死信事件记录审计日志
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec — Lifecycle | 状态转换触发事件 |
| Runtime Spec — Feedback | Feedback 通过 EventBus 驱动 |
| Audit Spec | Audit 订阅 EventBus |
| Observation Spec | Trace 订阅 EventBus |
| Policy Center Spec | 策略事件通过 EventBus 发布 |
