# Agent Specification

## EARP Agent 规范

**文档编号：L2-04-AGENT**
**版本：v1.0**
**定位：L2 — 平台规范。Agent 是 Runtime 的消费者——利用 Planner 做规划，利用 Execution Runtime 做执行，利用 Knowledge 做理解。不是 Runtime 的一部分。**
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-01-runtime/runtime-specification.md, L2-02-reasoning/planner-specification.md**

---

# 第一章：概述

## 1.1 定位

Agent 是 Runtime 的**消费者**，不是 Runtime 的一部分。

```
Agent 不是 Planner：Agent 利用 Planner 做规划，但管理自身生命周期
Agent 不是 Execution：Agent 利用 Execution Runtime 做执行，不参与 Step 管理
```

### 明确边界

**负责：**
- 任务理解（利用 Planner）
- 执行规划（利用 Planner）
- 调用 Capability（通过 Execution Runtime）
- 反思与重规划
- 生命周期管理

**不负责：**
- ❌ 执行 Capability（Execution Runtime 负责）
- ❌ 审批/权限（Policy Engine 负责）
- ❌ 术语映射（Knowledge Center 负责）

## 1.2 范围

| 模块 | 说明 | 章节 |
|------|------|------|
| Agent 定义 | 结构与配置 | 第二章 |
| 执行模式 | ReAct / Function Calling / Planning | 第三章 |
| 生命周期 | 创建→执行→完成 | 第四章 |
| 闭环机制 | 内循环（多轮迭代） + 外循环（Runtime 反馈） | 第五章 |
| 与 Runtime 协作 | 调用路径 | 第六章 |
| Multi-Agent | 多 Agent 协作 | 第七章 |

---

# 第二章：Agent 定义

## 2.1 结构

```
MUST: Agent 包含
  - agent_id:          string    — 全局唯一
  - name:              string    — 名称
  - description:       string    — 描述
  - mode:              "react" | "function_calling" | "planning" | "multi_agent"
  - max_iterations:    int       — 最大执行轮次（默认 10）
  - goal:              string    — 目标描述
  - constraints:       list      — 约束条件（SHOULD）
  - allowed_capabilities: list   — 允许调用的 Capability（SHOULD）
  - llm_config:        LLMConfig — LLM 配置（SHOULD）
```

示例：

```yaml
agent_id: "agent_daily_report"
name: "日报生成助手"
mode: "planning"
max_iterations: 15
goal: "汇总昨天所有产线的异常和生产数据，生成日报"
allowed_capabilities:
  - query_equipment_alarm
  - query_production_data
  - generate_report
llm_config:
  model: "claude-sonnet-4-6"
  temperature: 0.3
```

---

# 第三章：执行模式

## 3.1 ReAct

```
每轮：Thought → Action(Capability) → Observation → 循环或终止
```

```
MUST: 每轮 Action 调用一个 Capability
MUST: 通过 Execution Runtime 执行
MUST: 超时 30s/轮
MUST: 达到 max_iterations 强制终止
SHOULD: Agent 可自行判断达成目标后提前终止
```

## 3.2 Function Calling

```
LLM Function Calling → 选择 Capability → Execution Runtime → 继续
```

```
MUST: Capability 列表由 Resolution Engine 提供
MUST: 传入 Capability Schema 作为 tool 定义
```

## 3.3 Planning

```
Planner → Plan → Execution → 反思 → RePlan → 继续
```

```
MUST: 调用 Planner 生成初始 Plan
MUST: 每个 Plan step 通过 Execution Runtime 执行
SHOULD: 支持执行后反思和动态 RePlan
```

---

# 第四章：生命周期

## 4.1 状态

```
Pending → Running → Completed / Failed / Cancelled
Running → Waiting（等待外部输入）→ Running
```

```
MUST: Agent 状态映射 Runtime Lifecycle
MUST: Agent 每次 Capability 调用是独立 Execution
```

## 4.2 流程

```
Agent Created → Pending（等待触发）→ Running（循环调用 Planner → Execution → 反思）
    → Completed（目标达成）/ Failed（不可恢复）/ Cancelled（用户取消）
```

```
SHOULD: 支持暂停/恢复（保存 Checkpoint）
```

---

# 第五章：闭环机制

Agent 的运行涉及两套闭环——**内循环**（Agent 自身多轮迭代）和**外循环**（Runtime 统一反馈学习）。两者独立运行，互不阻塞。

## 5.1 内循环（Agent 自身迭代）

Agent 在执行过程中通过多轮迭代逼近目标，每轮结果影响下一轮的决策。

```
Round N: 执行（Thought → Action → Observation）
    │
    ├── 判断是否达成目标
    │   ├── 已达成 → Agent 完成
    │   └── 未达成 → Round N+1（继续内循环）
    │
    └── 超过 max_iterations → 强制终止
```

```
SHOULD: Agent 的内循环反思结果（每轮 Capability 选择、执行成功率、耗时等）应收集为内部指标
SHOULD: 内循环不阻塞外循环——Agent 完成后再触发外循环
```

## 5.2 外循环（Runtime 统一反馈）

Agent 完成 Execution 后，触发 Runtime 的 Feedback → Evaluation → Learning 机制。外循环使 Agent 跨 Session 越来越聪明。

```
Agent 完成 → Execution 完成 → Feedback → Evaluation
    │
    ├── Evaluation → Knowledge Center（Agent 执行模式记录）
    ├── Evaluation → Capability Graph（更新关系权重）
    └── Evaluation → Planner（优化 Agent 规划策略）
            │
            ▼
        下次 Agent 运行时自动受益
```

```
MUST: Agent 每次执行完成后触发 Runtime 的 Feedback 收集（见 Runtime Spec 第十二章）
SHOULD: Agent 内循环中收集的内部指标应作为 Feedback 的一部分上报
```

## 5.3 内循环与外循环的关系

```
内循环（同一 Session 内）：
  Agent 多轮迭代反思，每轮逐步逼近目标
  结果影响本轮后续决策

外循环（跨 Session）：
  Agent 完成后触发 Runtime 统一反馈
  结果影响 Agent 未来的 Capability 选择和执行策略

Agent 不需要等待外循环完成即可开始下一次执行
外循环的注入不强制要求 Agent 行为改变（Planner 和 Memory 自适应）
```

---

# 第六章：与 Runtime 协作
```
User → Agent → Planner（规划）→ Execution Runtime（执行 Capability）→ 结果
             → Knowledge Center（辅助理解）
```

```
MUST: 所有 Capability 调用经过 Execution Runtime
MUST: 每一步产生 Trace
```

---

# 第七章：Multi-Agent

```
Master Agent（协调者）
    ├── Worker Agent 1
    ├── Worker Agent 2
    └── Worker Agent 3
```

```
MUST: Multi-Agent 需要 Coordination Runtime 协调
MUST: Worker Agent 共享同一 Session Context
SHOULD: 支持并行执行
SHOULD: 支持 Deadlock 检测
SHOULD: 支持 Agent 间 EventBus 通信
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec — Execution | Agent 调用 Capability 经过 Execution Runtime |
| Runtime Spec — Session | 上下文持续演进 |
| Runtime Spec — Lifecycle | 状态映射 |
| Runtime Spec — Checkpoint | 暂停/恢复 |
| Planner Spec | Agent 利用 Planner 做规划 |
| Knowledge Center Spec | Agent 使用 Business Dictionary / RAG |
