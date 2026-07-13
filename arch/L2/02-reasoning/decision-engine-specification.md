# Decision Engine Specification

## EARP 决策引擎规范

**文档编号：L2-02-DECISION**
**版本：v1.0**
**定位：L2 — 平台规范。本文定义 Decision Engine 的契约，负责 Runtime 执行过程中的实时分支决策。**
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-01-runtime/runtime-specification.md, L2-02-reasoning/planner-specification.md**

---

# 第一章：概述

## 1.1 定位

Decision Engine 负责 Runtime 执行过程中的**实时分支选择**。它与 Planner 的区别：

| 维度 | Planner（规划时） | Decision Engine（执行时） |
|------|-----------------|--------------------------|
| 时机 | 执行前 | 执行中 |
| 输入 | Intent + Goal | 当前 Step 实时状态 |
| 输出 | Plan（DAG） | 分支选择 |
| 依赖 | Knowledge + Memory | 当前上下文 |
| 频率 | 每 Request 一次 | 每 Step 可能一次 |

### 明确边界

**负责：**
- 执行中的实时分支选择
- 基于规则、LLM、ML 三种决策机制

**不负责：**
- ❌ Policy 检查（Plan Validation 负责）
- ❌ Approval 判断（Policy Engine 负责）
- ❌ 生成 Plan（Planner 负责）
- ❌ 执行 Capability（Execution Runtime 负责）

## 1.2 范围

| 模块 | 说明 | 章节 |
|------|------|------|
| Decision 定义 | 结构与输出 | 第二章 |
| Decision 来源 | Rule / LLM / ML | 第三章 |
| 与 Execution 协作 | 调用路径 | 第四章 |
| 审计 | 决策记录 | 第五章 |

---

# 第二章：Decision 定义

## 2.1 结构

```
MUST: Decision 包含
  - decision_id:     string    — 全局唯一
  - execution_id:    string    — 所属 Execution
  - step_id:         string    — 触发 Step
  - decision_type:   "rule" | "llm" | "ml" | "hybrid"
  - input_context:   dict      — 当前执行状态
  - result:          DecisionResult
  - timestamp:       timestamp

MUST: DecisionResult 包含
  - selected_branch: string    — 选择的分支
  - confidence:      float 0-1 — 置信度
  - reason:          string    — 理由
  - fallback_used:   bool      — 是否使用兜底
```

示例：

```yaml
decision:
  decision_id: "dec_001"
  execution_id: "exec_001"
  step_id: "step_3"
  decision_type: "rule"
  input_context:
    inventory_level: 85
    safety_stock: 100
  result:
    selected_branch: "purchase"
    confidence: 1.0
    reason: "库存 85 低于安全库存 100"
    fallback_used: false
```

## 2.2 分支定义

```
MUST: 每个 Decision 点有明确的 2 个以上分支
MUST: 分支包含 branch_id、description、default(bool)
MUST: 有且仅有一个默认分支（作为兜底）
```

---

# 第三章：Decision 来源

## 3.1 Rule-based

```
MUST: 使用 IF-THEN-ELSE 格式
SHOULD: 支持组合（AND/OR/NOT）
MUST: 评估时间不超过 100ms
MUST: 置信度始终为 1.0

示例：
  IF inventory < safety_stock THEN purchase
  IF alarm_level = "critical" THEN emergency_stop
```

## 3.2 LLM-based

```
MUST: 附带当前执行状态 + 分支定义 + 历史记录
MUST: 输出必须包含置信度评分
MUST: 置信度 < 0.4 时使用默认分支兜底
MUST: LLM 调用上下文不超过 4000 token
MUST: 不可重试（每次上下文不同）
```

## 3.3 ML-based（Phase 3+）

```
SHOULD: 使用预训练模型
MUST: 输出包含预测置信度
MUST: 置信度 < 0.6 时使用默认分支
```

## 3.4 优先级

```
Rule-based（最优先）→ LLM-based → ML-based（Phase 3+）
```

---

# 第四章：与 Execution 协作

## 4.1 调用路径

```
Execution Step(decision)
    │
    ├── Decision Engine 读取 input_context
    ├── 按优先级尝试决策（Rule → LLM → ML）
    ├── 选择分支
    ├── 记录审计
    └── 返回 selected_branch
```

## 4.2 RePlan 触发

```
MUST: 当 Decision 结果导致 Plan 无法继续时
  - Execution 暂停
  - 通知 Planner 进行 RePlanning
```

---

# 第五章：审计

```
MUST: 每次 Decision 记录：decision_id、type、input、selected_branch、confidence、reason、latency_ms
MUST: LLM Decision 记录完整 Prompt + Response
MUST: 审计日志保留至少 90 天
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec — Execution Step | Decision 是 Step 类型之一 |
| Runtime Spec — Plan Validation | Decision 不覆盖 Policy 检查 |
| Planner Spec — RePlanning | 4.2 RePlan 触发 |
