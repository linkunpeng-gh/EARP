# EARP 架构对抗式分析（Adversarial Architecture Analysis）

**文档编号**：adversarial-architecture-analysis
**定位**：架构评审（Architecture Review）— 基于第一性原理 + 对抗式（魔鬼代言人）方法，对 EARP L0/L1(v5)/L1.5 设计假设进行批判性审查，识别可优化点，作为未来优化的输入。
**日期**：2026-08-24
**关联文档**：`L0/design-philosophy.md`、`L1/architecture-v5.md`、`L1.5/concept-model-v1.3.md`

---

## 一、方法论前提

企业 AI 运行时的**根本约束**是：

1. **可靠性** — 不丢、不重、不毁数据
2. **可治理** — 合规、可控、可审计
3. **正确性** — AI 规划准确

三者优先级高于灵活性。任何把防线建在「AI 大概率做对」之上的设计，都是对抗式分析的重点靶子。

分析框架：对每条核心设计决策，拆解其**隐含假设**，再以魔鬼代言人姿态质疑该假设在企业真实场景下的失效模式，最后给出优化方向。

---

## 二、核心假设质疑

### ① 最致命：治理防线建立在 AI 判断之上

- **原假设**（L0 / L1 v5）：Planner 生成 Plan，Execution 按 Plan 执行；Capability 分 Query/Command，Command 必经审批。
- **对抗质疑**：
  - 审批这一关键防线依赖「Planner 正确把能力归类为 Command」以及「Capability 声明诚实」。
  - LLM 规划可能把 `delete_records` 误规划成 Query 类能力，从而**绕过审批**。
  - 对 `query_alarms`（查询）「无副作用绕过审批、审计仅摘要」——但查询敏感 PII 本身是高合规风险动作，GDPR 要求对「谁查了什么」做**详细**记录。CQRS 的二元划分在这里过粗。
- **优化方向**：
  - Capability 的 Query/Command 类型、审批触发、权限必须是**注册期不可变元数据**，由 Execution 层**强制执行**，Planner 无权改写。（*待核实：当前 Planner 是否可覆盖 Capability 类型*）
  - 把「副作用」细分为 `read` / `write_idempotent` / `write_sideeffect` / `destructive`，审批与审计强度按此梯度，而非二元。

### ② 「一切过 Runtime」的单点 + 高频成本

- **原假设**（Runtime First）：所有执行唯一入口，禁止直连 LLM/Capability/外部系统。
- **对抗质疑**：
  - Runtime 成为**系统级单点**——与「Execution 99.99% 可靠」目标自相矛盾：Runtime 挂，全企业 AI 瘫痪。
  - 高频 Query（如查库存每秒上万次）强制走 Validation→Policy→Runtime 链路，latency 与成本不可接受。
  - 文档同时说「Connector 适配第三方、Runtime 不感知」，又说「一切执行过 Runtime」——**Connector 调用企业系统必须过 Runtime，则它并不「不感知」**，存在表述/设计矛盾。
- **优化方向**：区分「受控直连」与「受控编排」。高频只读查询可走轻量 Connector 网关（强制审计 + 限流 + RLS），仅 Command/复杂编排走完整 Runtime。把单点降级为「治理网关」而非「执行单体」。

### ③ Saga 补偿的不可逆命令盲区

- **原假设**（L1 v5 §5.2/§5.3）：每个 Command 注册补偿动作，失败走 Saga 回滚。
- **对抗质疑**：大量企业命令**物理不可逆**——已发出的采购单被供应商接受、已打印单据、已发短信。这些命令无法补偿，Saga 退化为「标记人工介入」。而文档对「补偿链部分成功、人工介入时效与责任」轻描淡写。
- **优化方向**：Command 再分 `compensable` / `non-compensable`。non-compensable 命令在 Plan 校验层就要求**更强人工闸门 / 预执行 dry-run / 双确认**，而非寄望 Saga。把「不可逆」作为一等公民纳入 Plan Validation Layer。

### ④ 闭环自动学习的可治理性

- **原假设**（Closed-loop Intelligence）：Feedback→Evaluation→Learning Injector 自动注入 Memory/Knowledge/Planner，使 Runtime 「越来越聪明」。
- **对抗质疑**：第一性原理——企业场景**自动改变行为本身就是高风险**。Learning Injector 若自动调整规划策略、默认跳过某审批、偏好某 Connector，等于 Runtime 自我修改决策逻辑，但：
  - 变更**如何审计、如何回滚、是否需要审批**？文档未定义。
  - 「执行成功 ≠ 业务正确」（工单建了但字段错），闭环可能**强化错误行为**。
  - 1.0/2.0 冷启动期数据稀少，闭环模块提前投资可能过度设计。
- **优化方向**：Learning Injector 的每次行为变更必须**版本化 + 可回滚 + 受 Policy 审批**；区分「学习建议」（人审后生效）与「自动生效」。把闭环当成「受治理的模型迭代」而非「自由进化」。

### ⑤ Domain First 的单域假设

- **原假设**（L0 / L1）：Planner 先路由到单一 Domain（30 个能力内检索，准确率 95%）。
- **对抗质疑**：真实企业任务常**跨域**（「分析订单延迟并通知客户」= Order + CRM）。单域路由失败或需多域。且路由准确率依赖 Business Dictionary 质量——字典不全则全链路错，是单点脆弱性。
- **优化方向**：规划层支持 **multi-domain / domain-composition**，并显式建模「跨域事务」如何跨 Business Transaction 协调（目前 Saga 是单 Transaction 内，跨域未覆盖）。

### ⑥ 插件/AI 生成能力的「声明即信任」

- **原假设**（Plugin First + L0 §9）：能力可由第三方、AI 生成、客户自写，L2 契约保证接入。
- **对抗质疑**：契约是「声明即信任」。一个恶意/有误的插件**声明自己是 Query 但实际写库**，或 AI 生成的 Capability 直接握有企业写权限——这是**供应链级安全黑洞**，且正好命中 ①② 的防线缺口。
- **优化方向**：插件/生成代码进入 Runtime 前需**沙箱 + 行为验证（实际测一次看是否有副作用）+ 能力分级白名单**。治理不能只靠声明，要有运行时行为校验。

### ⑦ Reason-Act 严格解耦 vs 交互式执行

- **原假设**（Reason-Act 解耦）：Reasoning 全无执行、Execution 全无 AI，二者仅靠 Plan/Event 通信。
- **对抗质疑**：ReAct 范式是「想一步、做一步、看结果、再想」，**推理与行动交错**。严格解耦后，Execution 遇到中途观察（如某步骤返回意外数据）只能**整体上报 RePlanning 重来**，长流程代价高昂；执行层也丧失局部智能（如超时能否自动换 Connector 重试，还是必须回 Reasoning）。
- **优化方向**：在 Plan 契约中允许**结构化分支/条件节点**（Execution 在预定义边界内做局部决策，仍无「自由 AI」），把 RePlanning 作为「预定义兜底分支失败」时的升级路径，而非默认路径。

---

## 三、优先级评估

| 优先级 | 项 | 理由 |
|---|---|---|
| P0（MVP 就该定） | ① 治理防线不依赖 AI 判断 | 安全/合规是生死线，错了不可逆 |
| P0 | ⑥ 插件行为校验 | 供应链级安全黑洞 |
| P0 | ③ 不可逆命令分类 | 直接决定数据一致性是否可信 |
| P1 | ② 受控直连 vs 完整 Runtime | 性能与单点风险 |
| P1 | ⑦ 交互式分支 | 长流程可行性 |
| P2 | ④ 闭环治理 | 随阶段演进，但契约需早预留 |
| P2 | ⑤ 跨域规划 | 随阶段演进，但契约需早预留 |

---

## 四、结论

EARP 架构最优雅的部分（Runtime First / Reason-Act 解耦 / CQRS）恰恰也是最大风险源——它们把「AI 诚实且正确」当成了隐含前提。

**第一性原理要求我们**：把治理与一致性防线从「AI 决策」下沉到「不可变注册元数据 + 执行层强制 + 行为校验」，才能让优雅设计在企业真实环境里站得住。

---

## 五、未来优化行动项（TODO）

> 状态：`[ ]` 待开始 / `[~]` 进行中 / `[x]` 已完成

- [ ] **① 注册期不可变元数据**：核查 `capability-center-specification.md`，确认 Planner 无法改写 Capability 的 Query/Command 类型；若不达标，提出 Execution 层强制校验方案。
- [ ] **① 副作用梯度**：将 CQRS 二元扩展为 `read / write_idempotent / write_sideeffect / destructive` 四级，定义各级审批与审计强度。
- [ ] **② 受控直连网关**：设计高频只读查询的轻量 Connector 网关（审计 + 限流 + RLS），与完整 Runtime 路径区分。
- [ ] **③ 不可逆命令分类**：在 Capability 与 Plan 契约中增加 `compensable / non-compensable` 标记，non-compensable 命令要求预执行闸门。
- [ ] **④ 闭环治理**：为 Learning Injector 定义变更版本化、回滚、审批机制；区分「学习建议」与「自动生效」。
- [ ] **⑤ 跨域规划**：在规划层引入 multi-domain / domain-composition，建模跨域 Business Transaction 协调。
- [ ] **⑥ 插件行为校验**：设计插件/生成代码进入 Runtime 前的沙箱 + 行为验证 + 能力分级白名单机制。
- [ ] **⑦ 交互式分支**：在 Plan 契约中支持结构化分支/条件节点，Execution 在预定义边界内做局部决策。
- [ ] **核对设计矛盾**：厘清「Connector 不感知 Runtime」与「一切执行过 Runtime」的表述冲突，统一为一致模型。

---

*本文档为对抗式架构评审，旨在为后续优化提供输入，不影响现有 L0/L1/L2 规范的正式状态。*
