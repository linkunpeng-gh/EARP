# Policy Center Specification

## EARP 策略中心规范

**文档编号：L2-05-POLICY**
**版本：v1.0**
**定位：L2 — 平台规范。Policy Center 管理所有策略的定义、评估与执行，控制"谁能做什么、什么时候能做、做到什么程度"。**

---

# 第一章：概述

## 1.1 定位

Policy Center 是 EARP 的**策略基础设施层**。策略在 Plan Validation 和 Capability 调用前评估，不在执行路径内部。

### 边界

**负责：** 策略定义与注册、评估、绑定、合规检查

**不负责：** ❌ 执行 Capability、❌ 决策选择、❌ 生成 Plan

---

# 第二章：策略定义

## 2.1 结构

```
MUST: 每个 Policy 包含
  - policy_id:   string    — 全局唯一
  - name:        string    — 名称
  - type:        string    — 策略类型
  - rules:       list[Rule]— 规则列表
  - effect:      "allow" | "deny" | "require_approval" | "audit"
  - priority:    int       — 优先级（越低越高）
  - status:      "active" | "inactive"
```

## 2.2 类型

| 类型 | 说明 | 评估时机 |
|------|------|---------|
| rbac | 基于角色的访问控制 | Plan Validation |
| rate_limit | 速率限制 | Plan Validation + 运行时 |
| data_scope | 数据范围控制 | Plan Validation |
| approval | 审批策略 | Plan Validation |
| time_restriction | 时间窗口限制 | Plan Validation |
| cost_limit | 成本上限 | Plan Validation |

## 2.3 优先级

```
MUST: deny 优先于 allow（拒绝优先）
SHOULD: 同一类型策略取最高优先级结果
```

---

# 第三章：策略评估

## 3.1 评估时机

```
Plan Validation（执行前，静态）：
  评估：rbac / data_scope / time_restriction / cost_limit / approval
  输出：Valid / Invalid / Pending(approval)

运行时（Capability 调用时）：
  评估：rate_limit
  输出：Allow / Deny
```

```
MUST: Plan Validation 阶段的策略评估在 Execution 开始前完成
SHOULD: 策略评估不超过 100ms
```

## 3.2 评估路径

```
Plan Validation → Policy Center
    ├── Valid → Execution Runtime → rate_limit(运行时) → 执行
    └── Invalid → Denied（返回原因）
```

---

# 第四章：绑定

```
MUST: Policy 可绑定到 Capability / Domain / Role / Tenant
MUST: 继承关系：Tenant → Domain → Capability
SHOULD: 子级可覆盖父级（更严格的生效）
MUST: 显式绑定优先于继承
```

---

# 第五章：内建策略

## 5.1 RBAC

```
MUST: 使用 "domain:action" 格式（alarm:read / work_order:write）
MUST: 评估：User.Role.permissions → Capability.required_permissions
```

## 5.2 Rate Limit

```
MUST: 按 tenant + capability_id 统计
MUST: 超出返回 RATE_LIMIT_EXCEEDED
```

## 5.3 Data Scope

```
MUST: 定义范围：self / department / org / all
SHOULD: 通过 Context.org_id 判断
```

## 5.4 Approval

```
MUST: 定义 trigger_condition / approver_role / timeout / escalation
MUST: 审批前 Execution 处于 Waiting
```

## 5.5 Time Restriction

```
MUST: 定义 allowed_days 和 allowed_hours
```

## 5.6 Cost Limit

```
MUST: 定义单次/每日/每月成本上限
```

---

# 第六章：审计

```
MUST: 每次评估记录：policy_id / type / user_id / result / reason
SHOULD: 保留 90 天
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec — Plan Validation | Policy Center 在 Validation 阶段调用 |
| Capability Center Spec — Policy Layer | Capability 的 Policy 配置由此评估 |
| Planner Spec | Planner 需了解 Policy 约束以生成合规 Plan |
| Decision Engine Spec | Policy(Approval) 与 Decision 分工明确 |
