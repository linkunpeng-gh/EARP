# Runtime Specification

## EARP 运行时规范

**文档编号：L2-01-RUNTIME**
**版本：v1.4**
**定位：L2 — 平台规范。本文定义 Runtime 核心层的契约，所有上层模块（Planner、Workflow、Agent）必须遵守此规范。**  
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-05-OBSERVATION v1.1**

> **v1.4 变更（2026-08-07）**：附录 A 明确 Memory 与 ABox 的边界——ABox（实体/事实/档案）属于 Knowledge，不属于 Memory；与本体层设计（arch/design/2026-08-07-ontology-layer-design.md）对齐。

> **v1.3 变更**：§4.1 新增 Replanning 状态；§4.2 新增 3 条 Replanning 转换路径和 3 个事件；进入 Replanning 时同 Execution 内其他在途并行 Step 保持等待（不取消）

---

# 第一章：概述

## 1.1 范围

本文定义 EARP 运行时核心的规范：

| 模块 | 说明 | 章节 |
|------|------|------|
| Runtime 核心循环 | Session 为外层容器，包住三个子 Loop | 第二章 |
| Runtime Context | 执行上下文 | 第三章 |
| Runtime Lifecycle | 状态机 | 第四章 |
| Runtime Event | 内建事件 | 第五章 |
| Session | 持续执行模型（跨多次 Request） | 第六章 |
| Goal 规范 | 目标的正式结构 | 第七章 |
| Execution | Task/Step 执行规范 | 第八章 |
| Business Transaction | 业务事务生命周期 | 第九章 |
| Decision 规范 | 执行中分支决策 | 第十章 |
| Resource 规范 | 执行资源（LLM/沙箱/浏览器/GPU） | 第十一章 |
| Feedback & Learning | 闭环学习规范（内嵌 Session 核心循环） | 第十二章 |
| 扩展点 | SPI 接口 | 第十三章 |

本文不涉及：
- Planner 如何规划（由 Planner Specification 定义）
- Capability 如何编写（由 Capability Specification 定义）
- Workflow/Agent 如何编排（由各自规范定义）

## 1.2 规范性要求

本文中的"必须（MUST）" "应该（SHOULD）" "可以（MAY）" 按 RFC 2119 解释。

任何违反 MUST 条款的实现属于不合规的 Runtime 实现。

---

# 第二章：Runtime 核心循环

## 2.1 主循环：Session 作为统一抽象

Runtime 的核心不是单次 Request/Execution，而是 **Session**。Session 是 Runtime 的**外层容器**，包住三个子循环。

```
Session（唯一生命周期容器）
    │
    ├── Loop 1: 主动执行链
    │   Request → Intent → Goal → Plan → Validation → Execution → Result
    │                                                               │
    │                                                               ▼
    │                                                     → Feedback → Evaluation
    │                                                               │
    │                                            ┌──────────────────┼──────────────────┐
    │                                            ▼                  ▼                  ▼
    │                                        Memory            Knowledge          Planner
    │                                     (执行经验积累)      (执行结果注入)       (下一次更聪明)
    │
    ├── Loop 2: 事件驱动响应链
    │   External Event（MES 报警 / 审批回调 / MQTT 消息）
    │       │
    │       ▼
    │   Decision Engine（是否响应 / 如何响应）
    │       │
    │       ▼
    │   Execution → Result → Feedback → Evaluation → Learning
    │
    └── Loop 3: 反思与重规划链
        Execution Result → Evaluation → Planner（反思）
            │
            ├── 满意 → 继续 / 结束
            └── 不满意 → Replan → 新 Execution
```

**三个 Loop 的关系**：

```
Loop 1 是主链 —— 用户发起请求，Runtime 执行，产生结果，形成反馈，持续学习
Loop 2 是副链 —— 外部系统或事件自发触发，Runtime 自动响应
Loop 3 是优化链 —— 执行结果不理想时，Runtime 自动重规划

三条链共享同一 Session Context，共享同一 Knowledge/Memory 基础。
```

## 2.2 契约

```
MUST: Runtime 是平台唯一的执行入口
  - 所有应用必须通过 Runtime 提交 Request
  - 不允许直接调用 LLM
  - 不允许直接调用 Capability
  - 不允许直接调用任何外部系统

MUST: Runtime 必须支持同步和异步两种执行模式
  - 同步（Sync）：调用者等待执行完成，适用 Chat
  - 异步（Async）：调用者立即获得 Execution ID，适用 Workflow/Agent

MUST: 每次完整的 Request 执行必须产生一条 Trace

MUST: Runtime 必须支持 Session 模型
  - Session 跨多个 Request
  - Session 内的 Context 持续演进
  - Session 支持事件驱动触发新的 Execution

SHOULD: Runtime 支持流式输出（Streaming）

MUST: 每次 Execution 完成后必须触发 Feedback 收集
```

## 2.3 输入输出

```
Input: Request (RuntimeRequest)
  - request_id:        string          — 全局唯一（MUST）
  - user_id:           string          — 发起者（MUST）
  - tenant_id:         string          — 租户（MUST）
  - input:             any             — 请求内容（MUST）
  - mode:              "sync" | "async" | "stream"（MUST）
  - session_id:        string | null   — 所属 Session（MUST）
  - metadata:          dict            — 扩展元数据（SHOULD）

Output: RuntimeResult
  - execution_id:      string          — 全局唯一（MUST）
  - session_id:        string          — 所属 Session（MUST）
  - status:            string          — 最终状态（MUST）
  - output:            any             — 执行结果（SHOULD）
  - artifacts:         list[ArtifactRef] — 产物引用（SHOULD）
  - trace_id:          string          — 完整链路追踪 ID（MUST）
  - feedback_uri:      string          — Feedback 收集端点（MUST）
  - error:             RuntimeError | null — 错误信息（SHOULD）
```

---

# 第三章：Runtime Context

## 3.1 定义

Runtime Context 是执行过程中贯穿始终的上下文对象。它在 Session 创建时初始化，在整个 Session 生命周期中持续演进，Session 完成时归档。

## 3.2 契约

```
MUST: 每次 Execution 拥有唯一 Context 实例，继承自 Session Context
MUST: Context 包含以下字段
  - execution_id:      string          — 执行 ID（MUST）
  - session_id:        string          — Session ID（MUST）
  - request_id:        string          — 原始请求 ID（MUST）
  - tenant_id:         string          — 租户（MUST）
  - org_id:            string | null   — 组织（SHOULD）
  - user_id:           string          — 发起者（MUST）
  - role:              string          — 当前角色（MUST，用于权限判断）
  - mode:              string          — 执行模式（MUST）
  - start_time:        timestamp       — 开始时间（MUST）
  - locale:            string          — 语言地区（SHOULD）

MUST: Context 是只读的。任何模块不能修改 Context 字段
SHOULD: Context 支持扩展字段（通过 metadata dict）
MUST NOT: Context 不能包含任何业务逻辑
```

## 3.3 Context 传递规则

```
Runtime → Reasoning（Planner），传递 Context（只读）
Runtime → Execution（Executor），传递 Context（只读）
Runtime → Capability：传递 Context（只读，Capability 可读取 tenant_id/user_id 用于数据过滤）
Runtime → Decision Engine：传递 Context（只读，含当前 Step 实时状态）
```

## 3.4 Context 生命周期（Session 级别）

```
Session Created → Context Created
    │
    ├── Request 1 → Context Active（Execution 中）
    ├── Request 2 → Context Active（持续演进）
    ├── Event Trigger → Context Active
    │
    └── Session Completed → Context Archived
```

Context 在 Session 创建时初始化，在 Session 完成时归档。多个 Execution 共享同一 Session Context。

---

# 第四章：Runtime Lifecycle

## 4.1 状态定义

所有 Execution 必须遵循以下生命周期状态机：

| 状态 | 说明 |
|------|------|
| Created | 刚创建，未开始处理 |
| Planning | Reasoning 正在规划 |
| Decisioning | Decision Engine 正在决策 |
| Queued | 已入队，等待 Executor |
| Running | 正在执行 |
| Waiting | 等待外部事件（审批/人工输入/外部回调） |
| Paused | 已暂停（可恢复） |
| Retrying | 失败后正在重试 |
| Compensating | 正在执行补偿/回滚 |
| Replanning | 失败后 Planner 正在生成修正 Plan（v1.3 新增） |
| Succeeded | 执行成功 |
| Failed | 执行失败（不可恢复） |
| Cancelled | 被取消 |
| Archived | 已归档（保留审计，不可再恢复） |

## 4.2 状态转换规则

```
MUST:  状态只能沿定义路径转换
MUST:  非法转换必须被拒绝并记录审计日志
MUST:  状态转换必须触发对应 Event

合法路径：

Created → Planning → Decisioning → Queued → Running → Succeeded → Archived
                                              → Waiting → Running
                                              → Retrying → Running
                                                          → Failed（重试耗尽）
                                              → Compensating → Failed
                                                              → Compensated
Running ↔ Paused（可多次暂停/恢复）
Created → Cancelled
Queued → Cancelled
Running → Cancelled

Failed → Replanning（v1.3 新增：Capability 失败 + 可重试条件 + 次数 < 3。进入 Replanning 时同 Execution 内其他在途并行 Step 保持等待，不取消）
Replanning → Planning（生成新 Plan，继承原 session_id）
Replanning → Failed（Planner 无法生成修正 Plan 或达到 3 次上限）

状态转换事件对照：
  转换                         事件
  ─────────────────────       ──────────────────────
  Created → Planning           runtime.execution.planning
  Planning → Decisioning       runtime.execution.decisioning
  Decisioning → Queued         runtime.execution.queued
  Queued → Running             runtime.execution.running
  Running → Waiting            runtime.execution.waiting
  Waiting → Running            runtime.execution.resumed
  Running → Paused             runtime.execution.paused
  Running → Retrying           runtime.execution.retrying
  Running → Compensating       runtime.execution.compensating
  Running → Succeeded          runtime.execution.succeeded
  Retrying → Failed            runtime.execution.failed
  Running → Cancelled          runtime.execution.cancelled
  Compensating → Failed        runtime.execution.failed
  Succeeded → Archived         runtime.execution.archived
  Failed → Replanning           runtime.execution.replanning          (v1.3)
  Replanning → Planning         runtime.execution.replan_generated    (v1.3)
  Replanning → Failed           runtime.execution.replan_exhausted    (v1.3)
```

## 4.3 超时规则

| 状态 | 超时 | 超时处理 |
|------|------|---------|
| Planning | 30s | 降级 Rule Planner |
| Decisioning | 15s | 降级到默认规则决策 |
| Queued | 5min | 触发排队超时事件 |
| Running | 按 Capability 声明（默认 5min） | 重试或补偿 |
| Waiting | 按配置（默认 24h） | 升级/通知/自动驳回 |
| Retrying | 总时长不超过 30min | 进入 Failed |
| Compensating | 10min | 标记人工介入 |

---

# 第五章：Runtime Event

## 5.1 事件格式

所有事件必须遵循 CloudEvents 2.0 规范：

```
id:        string      — 全局唯一
source:    string      — "earp.runtime"
specversion: "2.0"
type:      string      — 事件类型
time:      timestamp   — 事件发生时间
subject:   string      — 关联的 execution_id / session_id
data:      any         — 事件负载
```

## 5.2 内建事件

### 生命周期事件

| 事件类型 | 触发时机 | data 说明 |
|---------|---------|----------|
| `runtime.session.created` | Session 创建 | `{session_id, tenant_id, user_id}` |
| `runtime.session.completed` | Session 完成 | `{session_id, execution_count, duration}` |
| `runtime.execution.created` | Execution 创建 | `{execution_id, session_id, request_id}` |
| `runtime.execution.planning` | 开始规划 | `{execution_id, intent}` |
| `runtime.execution.decisioning` | 开始决策 | `{execution_id, decision_context}` |
| `runtime.execution.queued` | 入队 | `{execution_id, queue_depth}` |
| `runtime.execution.running` | 开始执行 | `{execution_id, step_index}` |
| `runtime.execution.waiting` | 进入等待 | `{execution_id, wait_reason, estimated_duration}` |
| `runtime.execution.paused` | 暂停 | `{execution_id, reason}` |
| `runtime.execution.resumed` | 恢复 | `{execution_id}` |
| `runtime.execution.retrying` | 重试 | `{execution_id, retry_count, last_error}` |
| `runtime.execution.compensating` | 执行补偿 | `{execution_id, step_index, compensating_capability}` |
| `runtime.execution.succeeded` | 成功 | `{execution_id, duration_ms}` |
| `runtime.execution.failed` | 失败 | `{execution_id, error_code, error_message}` |
| `runtime.execution.replan_triggered` | RePlan 触发（审计） | `{execution_id, session_id, failure_capability_id, replan_count}` | (v1.3)
| `runtime.execution.cancelled` | 取消 | `{execution_id, reason}` |
| `runtime.execution.archived` | 归档 | `{execution_id, final_status}` |

### 决策事件

| 事件类型 | 触发时机 | data 说明 |
|---------|---------|----------|
| `runtime.decision.evaluated` | 决策完成 | `{execution_id, decision_source, outcome}` |
| `runtime.decision.fallback` | 决策降级 | `{execution_id, reason, fallback_to}` |

### 事务事件

| 事件类型 | 触发时机 | data 说明 |
|---------|---------|----------|
| `runtime.transaction.started` | Business Transaction 开始 | `{transaction_id, execution_id}` |
| `runtime.transaction.completed` | 事务成功 | `{transaction_id, steps_completed}` |
| `runtime.transaction.failed` | 事务失败 | `{transaction_id, failed_step, error}` |
| `runtime.transaction.compensated` | 补偿完成 | `{transaction_id, steps_compensated}` |

### 资源事件

| 事件类型 | 触发时机 | data 说明 |
|---------|---------|----------|
| `runtime.resource.allocated` | 资源分配 | `{resource_id, resource_type, execution_id}` |
| `runtime.resource.exhausted` | 资源耗尽 | `{resource_type, quota_remaining}` |
| `runtime.resource.released` | 资源释放 | `{resource_id, duration_ms}` |

### 闭环学习事件

| 事件类型 | 触发时机 | data 说明 |
|---------|---------|----------|
| `runtime.feedback.collected` | 反馈已收集 | `{execution_id, feedback_type, summary}` |
| `runtime.evaluation.completed` | 评估完成 | `{execution_id, evaluation_summary}` |
| `runtime.learning.injected` | 学习结果注入 | `{target, injection_type}` |

### 异常事件

| 事件类型 | 触发时机 | data 说明 |
|---------|---------|----------|
| `runtime.error.timeout` | 超时 | `{execution_id, state, timeout_s}` |
| `runtime.error.state_transition` | 非法状态转换 | `{execution_id, from_state, to_state}` |
| `runtime.error.compensation_failed` | 补偿失败 | `{execution_id, step, error}` |

## 5.3 事件订阅

```
MUST:  事件总线支持多个订阅者
MUST:  事件至少保留 24 小时
SHOULD: 支持事件回放

MUST:  Runtime 内置以下订阅者：
  - Trace 订阅者（记录所有事件到 Trace）
  - Audit 订阅者（记录审计相关事件）
  - Feedback 订阅者（收集执行结果用于学习）
```

---

# 第六章：Session（持续执行模型）

## 6.1 定义

Session 是跨多个 Request 的持续执行上下文。一个 Session 可以包含多次 Request 和 Execution，Context 在 Session 内持续演进。

Session 使 Runtime 从"单次执行模型"升级为"持续执行模型"。

## 6.2 Session 与 Execution 的关系

```
Session（持续运行）
    │
    ├── Execution 1（Request: "查询昨天产线异常"）
    ├── Execution 2（Request: "分析异常原因"）
    ├── Execution 3（Event: MES 报警触发 → 自动处理）
    ├── Execution 4（Replan: 审批回退 → 调整方案）
    │
    └── Session 持续 → 直到超时或主动关闭
```

## 6.3 契约

```
MUST: Session 包含以下字段
  - session_id:        string          — 全局唯一（MUST）
  - tenant_id:         string          — 租户（MUST）
  - user_id:           string          — 创建者（MUST）
  - status:            "active" | "paused" | "completed" | "archived"（MUST）
  - created_at:        timestamp       — 创建时间（MUST）
  - expires_at:        timestamp | null — 过期时间（SHOULD）
  - context:           dict            — 累积上下文（MUST）
  - metadata:          dict            — 扩展元数据（SHOULD）

MUST: 一个 Session 包含 N 个 Execution
MUST: 一个 Execution 属于一个 Session
MUST: Session 的 Context 在每次 Execution 后持续演进
SHOULD: Session 支持事件驱动触发
  - 外部事件（MES 报警）→ Session → 新 Execution
  - 审批回调 → Session → 恢复等待中的 Execution
  - 定时触发 → Session → 新 Execution

SHOULD: Session 支持暂停/恢复（整个 Session 暂停，所有活跃 Execution 挂起）
SHOULD: Session 支持超时自动归档

Session 生命周期状态：
  Active → Paused ↔ Active
  Active → Completed → Archived
  Active → TimedOut → Archived
```

---

# 第七章：Goal 规范

## 7.1 定义

Goal 是 Intent Planner 输出的结构化目标。Goal 携带 Constraints，Planner 在 Goal 和 Constraints 的约束下生成 Plan。

## 7.2 契约

```
MUST: Goal 包含以下字段
  - goal_id:           string          — 全局唯一（MUST）
  - objective:         string          — 目标描述（MUST，如"统计昨天产线异常"）
  - constraints:       list[Constraint]— 约束条件列表（SHOULD）
  - success_criteria:  list[Criteria]  — 成功标准（SHOULD）
  - priority:          1 | 2 | 3 | 4 | 5 — 优先级，1 最高（SHOULD）
  - sla:               SLAConfig | null— SLA 要求（SHOULD）
  - domain:            string          — 所属领域（MUST）
  - source:            "user" | "system" | "agent" | "trigger"（MUST）

MUST: Constraint 包含以下字段
  - type:              "time" | "resource" | "policy" | "data" | "quality" | "priority"（MUST）
  - description:       string          — 约束描述（MUST）
  - severity:          "hard" | "soft" — 硬约束（必须满足）或软约束（尽量满足）（MUST）

示例：
  Goal:
    objective:        "将 A 类物料库存降低 20%"
    constraints:
      - type:         "policy"
        description:  "不能影响交付"
        severity:     "hard"
      - type:         "resource"
        description:  "预算不超过 50 万"
        severity:     "hard"
      - type:         "time"
        description:  "周期 30 天内完成"
        severity:     "soft"
    success_criteria:
      - "A 类物料库存量下降 20%"
      - "交付准时率不低于 99%"
    priority:         2
    domain:           "inventory"
```

## 7.3 Goal 在 Runtime 中的位置

```
Request → Intent → Goal(带 Constraints) → Planner → Plan → Validation → Execution
```

Planner 在 Goal 和 Constraints 的约束下生成 Plan。违反硬约束的 Plan 必须被拒绝。

---

# 第八章：Decision 规范

## 8.1 定义

Decision 表示 Execution 在执行过程中做的**实时分支选择**。Decision **不负责** Policy 检查、Approval 判断——这些属于 Plan Validation 的职责。

| 维度 | Planner（规划时） | Decision（执行时） | Plan Validation（执行前） |
|------|-----------------|-------------------|--------------------------|
| 时机 | 执行前 | 执行中 | 执行前 |
| 输入 | Intent + Goal | 当前 Step 实时状态 | Plan + Policy |
| 输出 | Plan（DAG） | 分支选择（IF-THEN-ELSE） | Valid / Invalid |
| 依赖 | Knowledge + Memory | 当前上下文 | Policy Engine |
| 机制 | Rule / LLM | Rule / LLM | 规则引擎 |

**职责边界**：

```
Policy / Approval 检查 → Plan Validation（执行前，静态）
  判断：用户是否有权限？是否需要审批？是否合规？
  
执行分支选择 → Decision（执行中，动态）
  判断：IF 库存 < 安全库存 THEN 采购 ELSE 等待
  判断：IF 异常原因不明 THEN 调用分析 Capability
```

## 8.2 Decision Step 契约

```
MUST: Decision Step 作为 Step 类型之一（decision），在 Execution 中执行

MUST: Decision Step 包含以下字段
  - decision_id:       string          — 唯一标识（MUST）
  - decision_type:     "rule" | "llm" | "ml" | "hybrid"（MUST）
  - input_context:     dict            — 决策输入（当前执行状态）（MUST）
  - rules:             list[Rule]      — 规则引擎的规则列表（SHOULD）
  - fallback:          "default_branch" | "fail"（SHOULD）

MUST: Decision 的输出是一个分支选择
  - selected_branch:   string          — 选择的分支标识（MUST）
  - confidence:        float           — 置信度 0-1（SHOULD）
  - reason:            string          — 决策理由（SHOULD）

SHOULD: Decision Engine 支持以下来源
  - Rule Engine:      IF 库存 < 安全库存 THEN 采购（确定性的）
  - LLM Judge:       IF 异常原因不明 THEN 调用分析 Capability（AI 判断）
  - ML Model:        IF 预测良率 < 阈值 THEN 提前干预（预测性）

MUST: 所有 Decision 必须记录审计日志

Decision Step 的执行路径：
  Step Enter → Decision Engine → Branch A（继续执行）
                               → Branch B（继续执行）
                               → Fallback（降级）
```

## 8.3 Decision 与 Execution 的协作关系

```
Execution → Step N（decision）
    │
    ├── Decision Engine 评估当前状态
    │      ├── 读取 Policy
    │      ├── 读取 Context 中的实时状态
    │      └── 输出分支选择
    │
    ├── Branch A → Step N+1（业务逻辑）
    ├── Branch B → Step N+1（不同的业务逻辑）
    └── Fallback  → 通知 Planner 重新规划
```

---

# 第九章：Execution

## 9.0 职责边界

Execution 是 Runtime 的"执行器"——只负责**可靠地执行预定义的操作**，不负责判断"做不做"或"怎么做"。

```
Execution 只做三件事：
1. Run Task        — 按序或并行执行 Step
2. Guarantee Consistency — Transaction / Compensation / Retry / Checkpoint
3. Handle Failure  — 超时、重试耗尽、补偿失败

Execution 不负责：
  - Policy 检查（由 Plan Validation 负责）
  - Approval 判断（由 Policy Engine 负责）
  - 智能 Agent 逻辑（由 Reasoning Runtime / Agent 负责）
  - 决策路径选择（由 Decision Engine 作为独立的 Step 类型）
```

## 9.1 Step 类型

Step 是 Execution 的原子执行单元。Execution 只管理以下 Step 类型：

| Step 类型 | 说明 | 要求 |
|----------|------|------|
| capability_call | 调用一个 Capability（核心） | MUST |
| business_transaction | 执行一个 Business Transaction | SHOULD |
| sub_execution | 启动子 Execution | MAY |
| wait | 等待外部事件（审批/回调/条件） | SHOULD |
| notify | 发送通知 | MAY |

## 9.2 Step 状态

```
Pending → Running → Succeeded
                  → Failed → Retrying → Running
                                   → Failed
```

每个 Step 有唯一 step_id。Step 的超时独立于 Execution。

## 9.3 Retry 规范

```
MUST:  每个 Step 可独立配置重试策略
  - max_attempts:  int（默认 3）
  - backoff:       "fixed"（默认） | "exponential"
  - initial_delay: int ms（默认 1000）
  - retryable_errors: list[str]

MUST:  以下错误不可重试
  - 鉴权失败 / Schema 校验失败 / Capability 不存在 / 业务逻辑错误

SHOULD: 以下错误可重试
  - 网络超时 / 服务不可用 / 限流
```

## 9.4 Timeout 规范

```
MUST:  每个 Step 有独立 timeout
MUST:  Timeout 处理策略：retry（默认）| fail | compensate
```

## 9.5 Checkpoint 规范

```
MUST:  以下时刻自动创建 Checkpoint
  - 每个 Step 完成后
  - 进入 Waiting 前
  - 进入 Paused 前
  - Business Transaction 的每个子 Step 完成后

MUST:  Checkpoint 保留 7 天
```

## 9.6 Compensation 规范

```
MUST:  Command Capability 的 Step 必须注册补偿动作
MUST:  补偿在 Business Transaction 失败或 Execution 取消时触发
SHOULD: 补偿按逆序执行
MUST:  补偿失败后标记人工介入
```

---

# 第十章：Business Transaction

## 10.1 定义

Business Transaction 表示一个跨多个 Capability 调用的业务操作单元。如果其中某个 Step 失败，已成功的 Step 将被补偿（Saga 模式）。

## 10.2 契约

```
MUST: Business Transaction 包含以下字段
  - transaction_id:    string          — 全局唯一（MUST）
  - execution_id:      string          — 所属 Execution（MUST）
  - status:            "active" | "completing" | "compensating" | "compensated" | "failed"（MUST）
  - steps:             list[TransactionStep] — 事务步骤列表（MUST）
  - compensation_strategy: "saga" | "tcc"（MUST）

MUST: TransactionStep 包含
  - step_index:        int             — 步骤序号（MUST）
  - capability_id:     string          — 调用的 Capability（MUST）
  - input:             dict            — 输入参数（MUST）
  - compensating_capability: string    — 补偿 Capability（Command 类型必选）
  - compensating_input: dict          — 补偿输入参数映射（Command 类型必选）
  - status:            "pending" | "succeeded" | "failed" | "compensated"（MUST）
```

## 10.3 Business Transaction 生命周期

```
Transaction Created（Active）
    │
    ├── Step 1 → Succeeded
    ├── Step 2 → Succeeded
    ├── Step 3 → Failed
    │              │
    │              ▼
    │    Transaction → Compensating
    │       ├── Compensate Step 2（逆序）
    │       ├── Compensate Step 1（逆序）
    │       │
    │       ├── All Compensated → Compensated
    │       └── Compensate Failed → Manual Intervention Required
    │
    └── All Steps Succeeded → Completed
```

## 10.4 补偿执行规则

```
MUST:  补偿按逆序执行（后完成的 Step 先补偿）
MUST:  补偿的 Capability 必须与正向 Capability 一一对应
SHOULD: 每个 Command Capability 在注册时声明 compensating_capability
MUST:  补偿失败后标记人工介入，等待运维人员处理
```

---

# 第十一章：Resource 规范

## 11.1 定义

Resource 表示 Execution 可使用的执行资源。Resource 不属于业务能力，仅提供执行能力。

## 11.2 资源类型

| 资源类型 | 说明 | 用途 |
|---------|------|------|
| llm | 大语言模型 | Planner、Agent、LLM Node |
| python | Python 代码执行引擎 | Code Node、Sandbox |
| browser | 浏览器实例 | Browser Agent、Web 自动化 |
| docker | Docker 容器 | 沙箱执行、隔离运行 |
| sandbox | 安全沙箱 | 不可信代码执行 |
| gpu | GPU 资源 | LLM 推理、模型训练 |
| remote_worker | 远程执行节点 | 分布式执行 |
| mcp | MCP Tool | MCP Server 提供的工具 |

## 11.3 契约

```
MUST:  Resource 包含以下字段
  - resource_id:       string          — 全局唯一（MUST）
  - resource_type:     "llm" | "python" | "browser" | "docker" | "sandbox" | "gpu" | "remote_worker" | "mcp"（MUST）
  - status:            "available" | "allocated" | "exhausted" | "error"（MUST）
  - capacity:          int             — 最大并发容量（MUST）
  - allocated:         int             — 已分配量（MUST）
  - metadata:          dict            — 扩展元数据（SHOULD）

MUST:  Execution 在使用 Resource 前必须调用 Resource Manager 申请
MUST:  Resource 使用完后必须释放
SHOULD: Resource 支持配额管理（租户级/项目级）
SHOULD: Resource Manager 支持资源池化（预热/复用）

Resource 生命周期：
  Available → Allocated（给 Execution 使用）→ Released（Execution 完成）→ Available
```

---

# 第十二章：Feedback & Learning

## 12.1 定义

Feedback 和 Learning 构成 Runtime 的闭环学习机制。每个 Execution 完成后，Feedback 收集原始数据，Evaluation 产出分析结论，Learning 将结论注入知识系统。

## 12.2 契约

```
MUST:  每个 Execution 完成后必须触发 Feedback 收集
MUST:  Feedback 包含以下字段
  - feedback_id:       string          — 全局唯一（MUST）
  - execution_id:      string          — 关联的执行（MUST）
  - status:            "succeeded" | "failed" | "partial"（MUST）
  - duration_ms:       int             — 执行耗时（MUST）
  - retry_count:       int             — 重试次数（MUST）
  - user_rating:       int | null      — 用户评分 1-5（SHOULD）
  - user_comment:      string | null   — 用户评价（SHOULD）
  - capability_results: list[CapabilityResult] — 各 Capability 执行结果（SHOULD）

MUST:  Evaluation 消费 Feedback，产出：
  - execution_quality: dict            — 执行质量评分（SHOULD）
  - capability_health: dict            — Capability 健康度（SHOULD）
  - planner_accuracy:  dict            — Planner 准确率（SHOULD）
  - recommendations:   list[str]       — 改进建议（SHOULD）

SHOULD: 以下 Learning 注入路径
  - Evaluation → Memory（长期趋势保存）
  - Evaluation → Knowledge（Capability 成功率更新）
  - Evaluation → Planner（优化策略）

闭环路径：
  Execution → Feedback → Evaluation → Memory / Knowledge / Planner
```

## 12.3 Learning Loop

```
第一次执行：
  User: "查询昨天产线异常"
  → Planner 从头理解（LLM 调用）
  → Execution → Feedback → Evaluation
  → 存入 Memory："产线异常"→ EquipmentDomain / query_alarms

第二次执行：
  User: "查一下昨天产线的情况"
  → Memory 匹配："与产线异常模式相似度 87%"
  → 直接路由到 EquipmentDomain / query_alarms
  → 不需要 LLM 重新理解

第 N 次执行：
  Runtime 越来越了解企业术语、模式、偏好
  → Planner 准确率持续提升
  → Capability 选择越来越精准
  → 人工干预越来越少
```

---

# 第十三章：扩展点

```
SPI: RuntimeHook
  - before_execution(context, plan)
  - after_execution(context, result)
  - on_error(context, error)

SPI: StateValidator
  - validate_transition(from: State, to: State) -> bool

SPI: EventSubscriber
  - on_event(event: RuntimeEvent)

SPI: ResourceProvider
  - allocate(resource_type, quota) -> Resource
  - release(resource_id)
  - health_check(resource_type) -> HealthStatus

SPI: DecisionProvider
  - evaluate(context, rules) -> DecisionResult

SPI: FeedbackHandler
  - collect(feedback) -> EvaluationResult
  - inject_learning(evaluation) -> LearningResult
```

所有扩展点通过 SPI 加载，非硬编码。

---

# 附录 A：Memory 规范

Memory 是 Runtime 的**经验存储层**，服务于 Planner 和 Agent。Memory 与 Knowledge 的边界：Memory 存储执行经验（运行时产生的临时或半持久数据），Knowledge 存储企业知识（经过验证的结构化数据）。

> **v1.4 补充（2026-08-07）**：ABox（实体/事实/事实档案，见 knowledge-center-spec v1.2 第四章）属于 **Knowledge**——企业知识事实，持久、治理、可审计。Semantic Memory（Phase 3）仅记录**运行时经验**（调用模式、用户偏好、反思结果），与 ABox 分离存储，分界同 v2.1 Memory vs Knowledge。

## A.1 分层定义

| 层级 | 存储内容 | 存储介质 | TTL | Phase |
|------|---------|---------|-----|-------|
| Conversation Memory | 当前对话历史 | Redis | 会话结束 | Phase 1 |
| Working Memory | 执行上下文临时状态 | Redis | Execution 完成 | Phase 1 |
| Long Memory | 用户偏好/跨会话知识 | PostgreSQL | 90 天 | Phase 1 |
| Semantic Memory | 实体关系 | VectorDB | 持久 | Phase 3 |
| Business Memory | 业务规则/调用模式 | PostgreSQL | 持久 | Phase 3 |

## A.2 Memory Manager 接口

```
MUST: Memory Manager 提供以下接口

  store(key, value, layer, ttl) -> void
    写入 Memory，指定层级和可选 TTL
    layer 取值：conversation | working | long | semantic | business

  retrieve(key, layer) -> any | None
    读取 Memory，按层级检索

  search(query, layer, top_k) -> list[MemoryResult]
    语义搜索（仅 semantic 和 long 层支持）

  delete(key, layer) -> void
    删除指定条目

  clear_layer(layer) -> void
    清空整个层级（用于会话结束、Execution 完成时清理）

MUST: store 操作记录审计日志
MUST: clear_layer 不影响其他层级
```

## A.3 生命周期

```
Conversation Memory: Session 结束时自动 clear_layer("conversation")
Working Memory:     Execution 完成时自动 clear_layer("working")
Long Memory:        TTL 到期自动删除
Semantic Memory:    持久保留，基于写入时间淘汰最旧数据
Business Memory:    持久保留，需主动维护

MUST: store 时未指定 TTL 的使用层级默认 TTL
SHOULD: Long Memory 基于访问频率延长 TTL
```

## A.4 使用规范

```
Planner:
  - Reflection 结果写入 Long Memory（MUST）
  - 不直接写入 Conversation Memory（由 Agent/Chat 负责）

Agent:
  - 对话历史写入 Conversation Memory（MUST）
  - 反思结果写入 Long Memory（SHOULD）

MUST: Agent 不直接写入 Working Memory（由 Execution Runtime 负责）
```

---

# 附录 B：v1.3 → v1.4 变更记录

| 变更 | 类型 | 说明 | 章节 |
|------|------|------|------|
| Memory vs ABox 边界 | 新增 | 明确 ABox（实体/事实/档案）属于 Knowledge 不属于 Memory；Semantic Memory 仅存运行时经验 | 附录 A |

# 附录 B：v1.2 → v1.3 变更记录

| 变更 | 类型 | 说明 | 章节 |
|------|------|------|------|
| REPLANNING 状态 | 新增 | Execution 新增 Replanning 状态（失败→重规划→新执行，上限 3 次） | 第四章 |
| 状态转换规则 | 新增 | 3 条 Replanning 转换路径（Failed→Replanning→Planning/Failed） | §4.2 |
| 状态转换事件 | 新增 | 3 个 Replanning 事件（replanning/replan_generated/replan_exhausted） | §4.2 |
| REPLAN_TRIGGERED 审计 | 新增 | 审计事件 `runtime.execution.replan_triggered`（含 session_id、failure_capability_id、replan_count） | §5.2 |
| 并行 Step 行为 | 新增 | 进入 Replanning 时同 Execution 内其他在途并行 Step 保持等待 | §4.2 |
| 依赖更新 | 优化 | +Observation Spec v1.1 | 文件头 |

# 附录 B：v1.1 → v1.2 变更记录

| 变更 | 类型 | 说明 | 章节 |
|------|------|------|------|
| 核心循环 | 重构 | Session 作为外层容器，包住三个子 Loop（主动执行/事件响应/反思重规划） | 第二章 |
| Execution 职责 | 重构 | 明确"只做三件事"边界；移除 decision step 类型 | 第九章 |
| Decision 定义 | 重构 | 缩小为"执行中分支选择"；Policy/Approval 划归 Plan Validation | 第八章 |
| Lifecycle 状态 | 优化 | 状态转换表增加 12 个对应的 Event | 第四章 |

# 附录 B：v1.0 → v1.1 变更记录

| 变更 | 类型 | 说明 | 章节 |
|------|------|------|------|
| Session | 🔴 新增 | 持续执行模型，跨多次 Request | 第六章 |
| Goal 规范 | 🔴 新增 | 目标的正式结构 + Constraints | 第七章 |
| Decision 规范 | 🔴 新增 | Decision Step + Decision Engine 契约 | 第八章 |
| Business Transaction | 🔴 新增 | 事务生命周期 + 补偿规范 | 第十章 |
| Resource 规范 | 🔴 新增 | LLM/Python/Browser/GPU 等执行资源 | 第十一章 |
| Feedback & Learning | 🔴 新增 | 闭环学习规范 | 第十二章 |
| Lifecycle 状态增加 | 优化 | +Decisioning、+Compensating 状态 | 第四章 |
| Event 表扩展 | 优化 | 增加 Session / Decision / Transaction / Resource / Learning 事件 | 第五章 |
| 核心循环 | 重构 | 从单次执行模型升级为 Session 级持续循环 + 事件驱动 | 第二章 |
| Context 生命周期 | 重构 | 从 Execution 级别升级为 Session 级别 | 第三章 |

---

# 附录 B：与 Concept Model 的对应关系

| Concept Model v1.3 | 本规范章节 |
|-------------------|-----------|
| Request | 2.3 |
| Session | 第六章 |
| Goal | 第七章 |
| Constraint | 7.2 |
| Decision | 第八章 |
| Execution | 第九章 |
| Business Transaction | 第十章 |
| Compensation | 9.6、10.4 |
| Context | 第三章 |
| Event | 第五章 |
| Checkpoint | 9.5 |
| Resource | 第十一章 |
| Feedback | 第十二章 |
| Evaluation | 第十二章 |
| Memory / Knowledge | 12.3 |
