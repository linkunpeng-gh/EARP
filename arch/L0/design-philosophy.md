# Runtime Design Philosophy

## EARP 架构设计哲学

**文档编号：00**
**定位：L0 — 架构思想层，L1/L2 所有文档的思想基础**

> 本文不定义任何技术接口、不描述任何模块细节、不涉及任何实现方案。本文只回答一个问题：**为什么 EARP 要这样设计？** 新人请从这里开始。读完本文，你应该在一天之内理解整个平台的核心理念，而不是花半年。

---

# 一、为什么需要另一个 AI 平台？

## 1.1 我们面对的问题

2024-2025 年，市场上出现大量 AI 平台——Dify、Coze、Langflow、AutoGPT、CrewAI——但它们有一个共同的问题：**都是面向 LLM 设计的，而不是面向企业设计的。**

```
Dify 的核心抽象：     App → Workflow → Tool → LLM
企业在乎的抽象：      Request → Domain → Capability → Connector → ERP
```

LLM 在企业场景只占 20%。集成、编排、治理、审计占了 80%。所以我们需要一个以**企业能力为中心**的 AI 平台，而不是以 **LLM 为中心**的 AI 平台。这就是 EARP 诞生的原因。

## 1.2 我们的目标

不是做一个"企业版 Dify"。而是做一个 Enterprise AI Runtime Platform。

```
Linux Kernel         → 管理硬件资源，为应用程序提供运行环境
Java Virtual Machine → 管理字节码执行，为 Java 程序提供运行时
EARP                 → 管理企业 AI 执行，为 AI 应用提供运行时
```

EARP 不关心你是 Chat 还是 Workflow 还是 Agent。EARP 只关心：**理解任务 → 规划任务 → 决策 → 执行任务 → 反馈 → 学习 → 下一次更聪明。**

---

# 二、Runtime First

**所有应用均调用 Runtime，不允许直接调用 LLM、不允许直接调用 Capability、不允许直接调用任何外部系统。**

没有 Runtime 时，每个应用都在重复造轮子——Chat 自己调 LLM、Workflow 自己实现引擎、Agent 自己实现规划。有 Runtime 时，所有执行路径统一。

Runtime 是**唯一的执行入口**。没有例外。好处是：

- **统一治理**：权限、审计、策略不用在每个应用中重复实现
- **统一生命周期**：所有 Execution 遵循同一状态机
- **统一可观测**：Trace / Metrics / Logging 自动覆盖所有执行
- **统一补偿**：失败、重试、回滚由 Runtime 保证

---

# 三、Domain First

**Runtime 先理解业务领域，再操作能力。**

没有 Domain 时，Planner 检索全部 1000 个 Capability，匹配准确率不到 60%。有 Domain 时，只检索 30 个 Capability，准确率 95% 以上。

Domain 是**业务领域的逻辑分组**——不是技术模块，不是数据库表，不是微服务。一个 Domain 包含 N 个 Capability，一个 Capability 属于一个 Domain。

---

# 四、Capability First

**AI 调用 Business Capability，不直接调用 Tool。**

没有 Capability First 时，AI 需要知道数据库结构、SQL 语法、表名，而且可能写出危险 SQL。有 Capability First 时，AI 只需要知道业务参数。

Capability 和 Tool 的区别：

| | Tool | Capability |
|---|---|---|
| 关注点 | "怎么调" | "做什么" |
| 命名 | `execute_sql` | `query_alarms` |
| 参数 | SQL/URL/Header | 日期/产线/设备 |
| 权限 | 无 | 有 |
| 底层 | HTTP API | SAP/MES/DB 任意 |

**Tool 是 Capability 的内部实现细节。Runtime 不应该知道 Tool 的存在。**

---

# 五、Reason-Act 解耦

**推理（Reasoning）与执行（Execution）彻底分离，互不影响。**

Reasoning 和 Execution 有完全不同的质量要求：

```
Reasoning:   必须聪明、可失败、可慢、可每周变更
Execution:   必须稳定、不能失败、必须快、尽量少变更
```

解耦后，Reasoning 升级不影响任何执行逻辑，Execution 出 Bug 排查范围缩到执行层。

---

# 六、CQRS for Enterprise

**Capability 分为 Query（查询）和 Command（命令）。Query 无副作用，Command 必经审批。**

不区分 Query 和 Command 的平台，在企业中无法通过合规审计。

| | Query | Command |
|---|---|---|
| 权限 | 只读 | 读写 + 审批 |
| 审计 | 摘要 | 详细 |
| 事务 | 无 | Saga |
| 补偿 | 无 | 必须注册 |

---

# 七、Closed-loop Intelligence

**Runtime 不仅负责理解和执行。Runtime 必须持续完成"反馈 → 评估 → 学习 → 优化"的闭环。**

没有闭环时，第 100 次执行和第一次一样笨。有闭环时，Runtime 越来越懂企业。

```
理解 → 规划 → 决策 → 执行 → 反馈 → 评估 → 学习 → 再理解（更聪明）
```

这是 **Runtime 的生命循环（AI Execution Loop）**。

---

# 八、Workflow 不是 Runtime，Agent 不是 Planner

**Workflow 是 Runtime 的一种执行模式**，不是 Runtime 本身。Workflow 不定义执行引擎，Workflow 定义流程描述规范，执行统一交给 Runtime。

**Agent 是 Runtime 的消费者**，不是 Runtime 的一部分。Agent 利用 Planner 做规划，利用 Execution Runtime 做执行，自身管理 Agent 生命周期。

---

# 九、平台规范 vs 开发文档

**L2 是平台规范（Platform Specification），不是开发文档（Development Documentation）。**

开发文档回答"这个模块怎么实现"。平台规范回答"这个模块必须遵守什么契约"。

因为将来 Capability 可能是第三方插件、AI 自动生成的、甚至是客户自己写的。平台规范确保不同来源的模块都能无缝接入 Runtime。

---

# 十、总结

## 九个核心理念

1. **Runtime First** — 所有执行统一入口
2. **Domain First** — AI 先理解领域，再操作能力
3. **Capability First** — AI 调用业务能力，不直接调 Tool
4. **Reason-Act 解耦** — 推理可迭代，执行必须稳定
5. **CQRS for Enterprise** — Query 无副作用，Command 必经审批
6. **Closed-loop** — 持续反馈 → 评估 → 学习 → 优化
7. **Workflow ≠ Runtime** — Workflow 是执行模式，不是引擎
8. **Agent ≠ Planner** — Agent 是消费者
9. **规范 ≠ 文档** — 平台规范定义契约

## 一句话定义 EARP

> **Enterprise AI Runtime Platform 是一个以业务能力为中心、面向企业场景的 AI 运行时平台。所有执行统一经过 Runtime，所有能力经过 Capability Center，所有执行形成持续学习的闭环。**

---

*本文档为 EARP 架构思想层（L0），作为所有 L1/L2 文档的思想基础。*
