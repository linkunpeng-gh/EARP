# L2 规划评审

对我提出的 L2 五阶段方案的技术评估。

---

## 总体结论：完全同意方向，两个调整建议

你判断"先花 30% 的时间写 Runtime Foundation"——这是整个规划中最正确的决策。

---

## Phase 1（Runtime Foundation）—— 完全同意

Runtime / Execution / Context / EventBus 这四份规范一旦写好，下面所有模块依赖它们。

**同意顺序：**
1. Runtime Specification
2. Execution Specification（Task / Step / Retry / Timeout / Compensation）
3. Context Specification
4. EventBus Specification

---

## Phase 2（Reasoning Layer）—— 同意，Decision Engine 移至 Phase 4

你说 Decision Engine 在 Reasoning Layer，我建议它在 Execution Layer。原因：

- Decision（IF 库存 < 安全库存 THEN 采购）依赖**执行中的实时状态**，不是规划时的静态分析
- Decision 的执行路径经过事务、补偿、回滚——属于 Execution Runtime

---

## Phase 3（Capability Layer）—— 完全同意

你说"Capability 是未来最大的竞争力"，我完全同意。Capability Center Specification 重要性仅次于 Runtime Specification。

**同意拆分：** Capability Center / Capability / Service / Connector 四份。

---

## Phase 4（Execution Layer）—— 同意，Workflow 定位是关键

你说"Workflow 不是 Runtime，只是 Runtime 的一种 Execution Pattern"——这是关键判断。Workflow Specification 不应定义执行引擎，应定义 DSL 规范、节点类型注册、对接 Execution Runtime 的方式。

**同意 Agent 的位置**：Agent 利用 Planner（Phase 2）+ Capability（Phase 3）+ Execution（Phase 1），所以在 Phase 4。

---

## Phase 5（Governance）—— 同意，Evaluation 提前到 Phase 2

Policy / Permission / Audit 在最后完全正确——它们定义规则，不参与执行路径。

但 Evaluation 应提前到 Phase 2，因为：
- Evaluation 的输出直接用于 Planner 优化，与 Knowledge 同属"学习"回路
- 放在 Phase 5 意味着前四个阶段都无法学习

---

## 零号文档（Runtime Design Philosophy）—— 完全同意，最佳建议

"新人一天就懂平台，而不是半年"。

建议目录：
- 为什么需要另一个 AI 平台
- Runtime First：统一执行入口
- Domain First：先理解领域，再操作能力
- Capability First：调用业务能力，不直接调 Tool
- Reason-Act 解耦：Reasoning 可迭代，Execution 必须稳定
- CQRS for Enterprise：Query 无副作用，Command 必经审批
- Closed-loop Intelligence：反馈→评估→学习→优化
- Workflow 不是 Runtime，Agent 不是 Planner
- 平台规范 vs 开发文档

---

## 最终优先级

| 优先级 | 文档 | 原因 |
|--------|------|------|
| P0 | 00 Runtime Design Philosophy | 半天写好，框架统一 |
| P1 | Runtime Specification | 定义平台"如何运行" |
| P2 | Capability Center Specification | 定义平台"能做什么" |
| P3 | Execution Specification | 所有执行模式的基石 |
| P4 | Context + EventBus | Runtime 基础设施 |
| P5 | Planner + Knowledge | AI 能力 |
| P6 | 其余 | Workflow / Agent / Connector / Governance |

**P1+P2 先写：Runtime Specification + Capability Center Specification。这两份完成后，EARP 的骨架就建立了。**
