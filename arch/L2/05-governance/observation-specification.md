# Observation Specification

## EARP 可观测性规范

**文档编号：L2-05-OBSERVATION**  
**版本：v1.1**  
**定位：L2 — 平台规范。Observation 是统一可观测性基础设施，负责 Metrics、Trace、Logging、Replay、告警的规范定义。**  

> **v1.1 变更**：新增 §6 Replay（沙箱回放/决策链追溯/差异对比/LLM 调试）。§1 依赖列表更新。

---

# 第一章：概述

## 1.1 定位

Metrics 回答"系统现在怎么样"，Trace 回答"请求经过的完整路径"，Logging 回答"发生了什么"，Replay 回答"能复现吗"。

### 边界

**负责：** Metrics、Trace、Logging、Replay、告警  
**不负责：** ❌ 审计日志（Audit Spec）、❌ 执行（Runtime Spec）

### 依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec v1.2 | Runtime 指标来源、Execution.payload 结构 |
| Capability Center Spec | Health 数据来源 Metrics |
| Resource Spec | Resource 使用率来源 |
| Audit Spec v1.1 | Trace 关联 Audit 日志；Replay 决策链追溯依赖 AuditLog |
| Security Spec v1.1 | Replay 沙箱隔离依赖 SandboxManager |
| Tenant Spec v1.1 | Replay 租户隔离约束 |

---

# 第二章：Metrics

（v1.0 内容不变）

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

（v1.0 内容不变）

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

（v1.0 内容不变）

```
MUST: 结构化 JSON 格式
MUST: 每条日志包含 timestamp / level / module / execution_id / message
SHOULD: 默认日志级别 info
```

---

# 第五章：告警

（v1.0 内容不变）

```
SHOULD: 以下情况触发告警
  - Capability 成功率 < 90%（持续 5 分钟）
  - Runtime P99 延迟 > 基线 2 倍（持续 5 分钟）
  - Capability unreachable
  - Resource 使用率 > 80%
```

---

# 第六章：Replay（v1.1 新增）

## 6.1 概述

Replay 使用已采集的观测数据（Execution、AuditLog、CapabilityCall），在隔离沙箱中回放重现历史执行过程。

**适用场景**：生产问题复现、LLM 行为调试、Capability 回归验证、决策链审查。

## 6.2 核心能力

| 能力 | 描述 | 数据来源 |
|:-----|:-----|:---------|
| 沙箱回放 | 在 SandboxManager 隔离环境中用历史 params+context 重跑 Capability 调用 | Execution.payload, Execution.context |
| 决策链追溯 | 按 AuditLog 事件时间线重放执行顺序，输出结构化时间线 | AuditLog (event_type, timestamp, entity_id) |
| 差异对比 | 对比 replay 结果与原始结果 | Execution.result vs replay output |
| LLM 调试 | 回放 Planner 的 Prompt+Response，定位幻觉/注入来源 | AuditLog.detail (LLM Prompt+Response) |

## 6.3 MUST 约束

```
MUST: Replay 在沙箱环境中执行——复用 SandboxManager（Security Spec §7.2），
      被重放的 Capability 产生的任何写操作不触及生产环境
MUST: Replay 仅适用于无副作用或沙箱可截获副作用的 Capability——
      idempotent Query 直接允许；Command 需沙箱保护；
      网络调用若沙箱无法截获则直接拒绝 Replay
MUST: Replay 不能跨租户访问数据——复用 Tenant Spec 的 RLS + Auth
MUST: Replay 基础设施本身 read-only——不修改任何 Execution/AuditLog/原始数据
MUST: Replay 结果差异对比使用以下格式：
      - Plan diff: DAG 节点增删改（结构化 diff）
      - Result diff: RFC 6902 JSON Patch
      - Timing diff: abs(replay_duration - original_duration) / original_duration × 100%
SHOULD: 单次 Replay 超时上限与原始 Execution 超时一致 + 30s 余量
SHOULD: Replay 结果保留 7 天
```

## 6.4 触发与存储

```
触发方式: 通过 Execution ID 触发 Replay
存储格式: JSON { replay_id, execution_id, tenant_id, timestamp, original_result, replay_result, diff }
并发策略: 同一 Execution 可被多次 Replay，每次产生独立的 replay_id
```

## 6.5 机制细节

| 维度 | 策略 |
|:-----|:-----|
| 触发方式 | 通过 Execution ID 触发 |
| 存储格式 | JSON：`replay_id`, `execution_id`, `tenant_id`, `timestamp`, `original_result`, `replay_result`, `diff` |
| 隔离保证 | SandboxManager（复用 Security Spec §7.2 Phase 4 Plugin 沙箱），被重放 Capability 的写操作不触及生产 |
| 副作用策略 | idempotent Query 直接允许；Command 需沙箱保护；无法截获的网络调用直接拒绝 |
| 租户隔离 | 复用 Tenant Spec RLS + Auth，不可跨 tenant_id 访问数据 |
| 保留策略 | Replay 结果保留 7 天 |
| 并发策略 | 同一 Execution 多次 Replay 各自独立，通过 `replay_id` 区分 |
| 失败模式 | SandboxManager 不可用 → 返回错误；原始 Execution 数据损坏 → 拒绝 Replay |

---

# 附录：规范依赖（v1.1 更新）

| 规范 | 关系 |
|------|------|
| Runtime Spec v1.2 | Runtime 指标来源；Replay 依赖 Execution.payload |
| Capability Center Spec | Health 数据来源 Metrics |
| Resource Spec | Resource 使用率来源 |
| Audit Spec v1.1 | Trace 关联 Audit 日志；Replay 决策链追溯依赖 AuditLog |
| Security Spec v1.1 | Replay 沙箱隔离依赖 SandboxManager |
| Tenant Spec v1.1 | Replay 租户隔离约束 |
