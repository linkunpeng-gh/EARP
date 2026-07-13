# Audit Specification

## EARP 审计规范

**文档编号：L2-05-AUDIT**
**版本：v1.0**
**定位：L2 — 平台规范。Audit 是 EARP 的统一审计基础设施，负责所有执行的日志记录与溯源。**

---

# 第一章：概述

## 1.1 定位

所有模块的审计要求统一由 Audit 规范定义，不在各模块中各自为政。

### 边界

**负责：** 审计日志格式、存储与保留、溯源、防篡改
**不负责：** ❌ 策略评估、❌ 指标收集、❌ 执行追踪

---

# 第二章：审计日志格式

## 2.1 统一字段

```
MUST: 每条审计日志包含
  - log_id:        string    — 全局唯一
  - timestamp:     timestamp — 事件时间
  - source:        string    — 来源（runtime/planner/decision/capability/policy）
  - event_type:    string    — 事件类型
  - tenant_id:     string    — 租户
  - user_id:       string    — 用户
  - execution_id:  string    — Execution（SHOULD）
  - subject:       string    — 操作对象（SHOULD）
  - action:        string    — 操作
  - result:        "success" | "failure" | "pending"
  - detail:        dict      — 详细信息（SHOULD）
```

## 2.2 事件类型

```
Runtime:      runtime.execution.created / completed / failed
              runtime.session.created / completed
Planner:      planner.intent.parsed / plan.generated / plan.validation_failed
Decision:     decision.evaluated / decision.fallback_used
Capability:   capability.called / succeeded / failed / compensation.triggered
Policy:       policy.evaluated / policy.approval.requested / policy.rate_limit.exceeded
```

---

# 第三章：各模块审计要求

```
Runtime:    Execution/Session 创建与完成、状态转换、超时、Checkpoint
Planner:    Intent Parsing（输入+输出）、Plan 生成（完整 DAG）、Validation 失败、RePlan
Decision:   每次评估（类型、分支、置信度）、Fallback
Capability: Command 完整输入输出（detail）、Query 摘要（summary）、补偿触发
Policy:     每次评估（policy_id/result/reason）、审批请求、Rate Limit 触发
```

```
MUST: LLM Planner 和 LLM Decision 的完整 Prompt + Response 必须记录
```

---

# 第四章：存储与保留

```
MUST: 追加写存储，不可修改已有记录
SHOULD: 保留策略
  - Runtime/Planner/Decision 日志：90 天
  - Capability 日志（Command）：180 天
  - Policy 审计：180 天
  - LLM Prompt+Response：30 天
SHOULD: 自动归档到冷存储，归档后仍可查询（延迟 < 5s）
```

---

# 第五章：防篡改

```
SHOULD: 哈希链完整性校验
MUST: 审计日志不可删除（管理员也不允许）
SHOULD: 审计存储与应用数据存储分离
```

---

# 第六章：决策链溯源

```
MUST: 每个 Execution 的 Trace 可关联以下记录
  - Runtime 生命周期事件
  - Planner Intent/Goal/Plan
  - Decision 分支选择
  - Capability 调用记录
  - Policy 评估记录

SHOULD: 支持查询："为什么做了这个决策？"
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec — Event | Audit 订阅 Runtime Event |
| Planner Spec | Plan 记录进入审计 |
| Decision Engine Spec | 决策记录进入审计 |
| Capability Center Spec | 调用记录进入审计 |
| Policy Center Spec | 评估记录进入审计 |
