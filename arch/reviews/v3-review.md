# v2.0 评审反馈 — 逐条评价

## #1 增加 Domain Layer — ✅ 完全采纳，架构级修正

**评价：这是 v2.0 最大的架构缺失，没有之一。**

当前 v2.0 中 Planner → Capability 的直连，在 50 个 Capability 时还能工作，到了 500+ 就会全面崩溃。Planner 需要先确定"用户在哪个业务领域"，再检索该领域的 Capability，准确率才有保障。

Domain Layer 的引入会改变整个架构的中段结构：

```
v2.0:       Planner → Capability
v3.0:       Planner → Domain Layer → Capability
```

**采纳方式**：在 Runtime 和 Capability 之间插入 Domain Layer，Domain 作为 Capability 的逻辑分组和路由边界。

---

## #2 Capability 拆为 Capability → Service → Connector — ✅ 完全采纳

**评价：这是企业软件设计的标准模式，v2.0 把这三层合并了。**

v2.0 的 `Capability → Adapter` 过于扁平。MES 更换时，如果 Capability 逻辑被 Adapter 的变更牵连，就违背了 Adapter Pattern 的初衷。

拆三层后：
- **Capability**：业务语义（做什么）— "查询设备报警"
- **Service**：业务逻辑编排（怎么做）— 调用 Alarm Service
- **Connector**：协议适配（怎么连）— MES Connector

这样 MES 更换时，Capability 和 Service 完全不动，只换 Connector。

---

## #3 Planner 拆为 Intent Planner + Task Planner — ✅ 完全采纳

**评价：两个职责确实不同，拆开后各自的测试性和可替换性都更好。**

- **Intent Planner**：理解自然语言、提取实体、路由到 Domain、选择 Capability
- **Task Planner**：生成执行计划（DAG）、任务分解、反思、重规划

前者是 NLU + 语义路由，后者是任务编排。耦合在一起时，修改任务编排逻辑可能影响自然语言理解。

---

## #4 Knowledge 重新定位 — ✅ 完全采纳

**评价：v2.0 的 Knowledge 定位确实偏窄，Business Dictionary 是关键洞察。**

Planner 真正依赖的不是 RAG，而是**企业术语映射**。用户说"异常"，系统需要知道 = `Alarm`。这是 Business Dictionary 的职责，不是向量检索。

v3.0 的 Knowledge Center 重新定义为 6 个模块：
- **RAG**：文档检索
- **Business Dictionary**：企业术语统一映射（新增，核心）
- **Ontology**：对象关系模型
- **Capability Metadata**：Capability 搜索索引
- **Prompt Library**：模板管理
- **Semantic Index**：语义索引层

---

## #5 Runtime 增加 Lifecycle — ✅ 完全采纳

**评价：缺少标准生命周期是 v2.0 的状态管理不够系统化的原因。**

标准生命周期让 State Machine、Checkpoint、Audit 都有了统一的参照系：

```
Created → Planning → Waiting → Running → Completed → Archived
                          ↓          ↓
                       Paused    Retrying
                          ↓          ↓
                       Resumed    RetryLimit → Failed
```

---

## #6 Capability Registry → Capability Center — ✅ 完全采纳

**评价：确实应该提升为一级模块，尤其是为未来的 Marketplace 做准备。**

Capability Center 作为独立模块，承载注册、发现、版本、权限、健康、指标，将来 Marketpace 就是 Capability Center 的开放版本。

---

## #7 增加 Resource Layer — ⚠️ 部分采纳

**评价：方向正确，但时机需要斟酌。**

v2.0 把资源管理散落在 Runtime 各模块中。对于 Coding Agent / Browser Agent 场景，确实需要一个统一的资源管理器。但 Phase 1 的核心场景（Chat + Workflow + Agent）对 GPU/浏览器/Docker 的需求不是刚需。

**采纳方式**：架构图中**预留 Resource Manager 位置**，但在 L1 文档中标注为 Phase 2-3 范围，Phase 1 快速实现（Sandbox + 基础资源限制即可）。

---

## #8 增加 Artifact Center — ✅ 完全采纳

**评价：Artifact 在 v2.0 中被埋在 Kernel 的 Artifact Manager 里，确实地位不够。**

企业执行完成后产生的大量产物（报表、Excel、图片、SQL 结果）应该被统一管理、跨模块共享。独立为 Artifact Center 后，Workflow 的产物 Agent 可以直接引用。

---

## #9 增加 Observation — ✅ 采纳（v2.0 已有但重新组织）

**评价：Kernel 中已有 Trace / Metrics / Logging / Audit，但分散且不够系统化。**

重新组织为统一的 Observability 模块，包含：
- **Trace**：调用链追踪
- **Metrics**：性能指标
- **Logging**：结构化日志
- **Replay**：执行回放
- **Profiling**：性能剖析

---

## #10 Runtime 是"学习型"平台 — ✅ 采纳为核心理念

**评价：不是架构变更，但需要在架构文档中明确作为非功能性指导原则。**

v3.0 在第一章设计原则中增加 **Learning Runtime** 原则，指明架构设计中所有模块都应支持渐进式丰富（Capability 持续注册、Domain 持续扩展、Knowledge 持续积累）。

---

## 汇总

| # | 建议 | 决定 | 影响范围 |
|---|------|------|---------|
| 1 | 增加 Domain Layer | ✅ 采纳 | 架构中段大改 |
| 2 | Capability → Service → Connector | ✅ 采纳 | Capability 层重构 |
| 3 | Intent Planner + Task Planner | ✅ 采纳 | Runtime 重构 |
| 4 | Knowledge 重新定位 | ✅ 采纳 | Knowledge Center 重构 |
| 5 | Runtime Lifecycle | ✅ 采纳 | Runtime 状态管理 |
| 6 | Capability Center | ✅ 采纳 | 提升为一级模块 |
| 7 | Resource Layer | ⚠️ 部分采纳 | 预留位置，Phase 2-3 |
| 8 | Artifact Center | ✅ 采纳 | 独立模块 |
| 9 | Observation | ✅ 采纳 | 重新组织 |
| 10 | Learning Runtime | ✅ 采纳 | 核心理念 |
