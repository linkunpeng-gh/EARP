# Observation Specification

## EARP 可观测性规范

**文档编号：L2-05-OBSERVATION**
**版本：v1.0**
**定位：L2 — 平台规范。Observation 是统一可观测性基础设施，负责 Metrics、Trace、Logging、Replay、告警的规范定义。**

---

# 第一章：概述

## 1.1 定位

Metrics 回答"系统现在怎么样"，Trace 回答"请求经过的完整路径"，Logging 回答"发生了什么"。

### 边界

**负责：** Metrics、Trace、Logging、告警
**不负责：** ❌ 审计日志、❌ 执行

---

# 第二章：Metrics

## 2.1 指标

### Runtime

| 指标 | 类型 | 维度 |
|------|------|------|
| runtime.execution.count | Counter | tenant_id, status |
| runtime.execution.duration | Histogram | tenant_id, mode |
| runtime.execution.active | Gauge | tenant_id |
| runtime.session.active | Gauge | tenant_id |
| runtime.error.count | Counter | error_code |

### Capability

| 指标 | 类型 | 维度 |
|------|------|------|
| capability.call.count | Counter | capability_id, status |
| capability.call.duration | Histogram | capability_id |
| capability.health | Gauge | capability_id |

### Planner

| 指标 | 类型 | 维度 |
|------|------|------|
| planner.plan.count | Counter | planner_type |
| planner.plan.duration | Histogram | planner_type |

### Resource

| 指标 | 类型 | 维度 |
|------|------|------|
| resource.usage | Gauge | resource_type |
| resource.quota | Gauge | resource_type, tenant_id |

## 2.2 收集

```
MUST: Prometheus 格式暴露
SHOULD: 采集频率 30s，保留 30 天
```

---

# 第三章：Trace

```
MUST: 每次 Request 一条 Trace，使用 OpenTelemetry
MUST: Trace 包含以下 Span
  - runtime: 整体生命周期
  - planner: Intent → Plan
  - capability: 每次 Capability 调用
  - decision: 每次决策
  - policy: 每次策略评估
```

```
SHOULD: 默认 100% 采样（企业场景需要完整审计）
SHOULD: Trace 保留 7 天
```

---

# 第四章：Logging

```
MUST: 结构化 JSON 格式
MUST: 每条日志包含 timestamp / level / module / execution_id / message
SHOULD: 默认日志级别 info
```

---

# 第五章：告警

```
SHOULD: 以下情况触发告警
  - Capability 成功率 < 90%（持续 5 分钟）
  - Runtime P99 延迟 > 基线 2 倍（持续 5 分钟）
  - Capability unreachable
  - Resource 使用率 > 80%
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec | Runtime 指标来源 |
| Capability Center Spec — Health | Health 数据来源 Metrics |
| Resource Spec | Resource 使用率来源 |
| Audit Spec | Trace 关联 Audit 日志 |
