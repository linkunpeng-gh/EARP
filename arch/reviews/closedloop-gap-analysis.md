# Closed-loop 在 Agent / Workflow 规范中体现不足的原因分析

---

## 根因：不是无法实现，是设计分工的遗留问题

三层原因：

### 1. P1 先于 P4 编写，交叉引用遗漏

Runtime Spec（P1）定义 Feedback → Evaluation → Learning 闭环机制。设计意图是"闭环由 Runtime 统一管理，上层模式直接使用，不需要各自重新定义"。

但写 Agent（P4）和 Workflow（P4）规范时，注意力放在核心差异上——Agent 强调"利用 Planner"，Workflow 强调"编译为 Plan"——没有反过来引用 Runtime 的闭环机制。这是文档编写阶段的遗漏。

### 2. Agent 的闭环形态与 Runtime 不同

Runtime 的闭环是**一次执行一次反馈**：`Execution → Feedback → Evaluation → Knowledge`

Agent 的闭环是**多轮迭代**：
```
Round 1: Thought → Action → Observation
Round 2: Thought（基于上轮 Observation）→ Action → Observation
...
```

两套闭环形态不同，不能简单复用。Agent 需要定义自己的内循环和外循环的关系。

### 3. Workflow 的闭环涉及流程治理，P5 未开始

预定义流程的"优化"涉及到流程模板的修改：
- 谁来修改？Runtime 自动改还是人工审核？
- 修改边界？只改参数还是增删节点？
- 旧版本处理？正在执行的实例怎么办？

这些问题涉及 Governance 层（P5）的流程治理规则。P4 规范时选择暂时不涉及。

---

## 结论

不是技术限制，是**设计分工的阶段性产物**。都可以修复。

---

## 修改建议

### Agent Specification（+15 行）

新增"闭环机制"章节，定义内循环和外循环的关系：

```
Agent 闭环：
  内循环（自身迭代）：Round N → 观察 → 判断
    → 未达成 → 继续（内循环）
    → 达成 → Agent 完成 → 触发外循环

  外循环（Runtime 统一）：Agent 完成后触发 Feedback → Evaluation
    → Knowledge / Memory → 下次 Agent 自动受益

MUST: Agent 每次执行完成后触发 Runtime 的 Feedback
SHOULD: Agent 内部反思结果作为 Feedback 的一部分
```

### Workflow Specification（+20 行）

新增"闭环机制"章节，标注治理依赖：

```
MUST: Workflow 每次执行完成后触发 Runtime 的 Feedback

Workflow 闭环限制：
  - 节点参数调整：可自动优化
  - 节点增删：需人工确认（流程治理规则由 Policy Center 定义，Phase 5）
```

---

两处改动都很小，需要我直接执行修改吗？
