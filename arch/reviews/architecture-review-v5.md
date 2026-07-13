# EARP 架构文档体系 评审报告 (v5.0)

> 评审日期：2026-06-29
> 评审范围：arch/ 目录 L0 → L1 → L1.5 → L2 全部 16 份核心文档 + 7 份历史评审记录 + 4 份历史版本
> 评审方法：遵循 software-architecture-review skill 的七维度框架

---

## 评审概览

| 维度 | 评分 | 问题数 |
|------|:----:|:------:|
| 一致性 (Consistency) | 7/10 | 3 |
| 完整性 (Completeness) | 8/10 | 4 |
| 合理性 (Soundness) | 7/10 | 4 |
| 可行性 & 演进性 (Feasibility & Evolvability) | 8/10 | 3 |
| 规范质量 (Spec Quality) | 8/10 | 3 |
| 评审延续性 (Review Continuity) | 6/10 | 4 |
| **综合** | **7.3/10** | **21** |

---

## 1. 一致性评审 (Consistency) — 7/10

### ✅ 已确认项

- **L0 理念在 L2 中的传导**：Runtime First / Domain First / Capability First / Reason-Act 解耦 / CQRS / Closed-loop 这 6 条核心理念在 L2 规范中均有体现
- **术语引用链**：L1.5 Concept Model 被所有 L2 规范正确引用（依赖字段均包含 `L1.5/concept-model-v1.3.md`）
- **跨文档引用完整性**：Runtime Spec (v1.2) 被 Planner / Decision / Knowledge / Capability / Workflow / Agent / Scheduler / Resource / EventBus / Policy / Audit / Observation 共 12 份规范正确引用
- **模块边界声明一致性**：每份 L2 规范均包含 "负责/不负责"（Scope/Not Scope）明确声明
- **MUST/SHOULD/MAY 统一使用**：所有 L2 规范遵循 RFC 2119，使用一致

### ❌ 问题项

**C1 [中] L0 与 L1 的设计原则集不一致**

L0 (design-philosophy.md) 定义了 9 条原则：
```
1. Runtime First   2. Domain First   3. Capability First
4. Reason-Act 解耦  5. CQRS for Enterprise  6. Closed-loop Intelligence
7. Workflow ≠ Runtime  8. Agent ≠ Planner  9. 规范 ≠ 文档
```

L1 (architecture-v5.md 第一章) 的设计原则表有 10 条——**双方有 4 条互相不存在**：

| 在 L0 但不在 L1 | 在 L1 但不在 L0 |
|---|---|
| CQRS for Enterprise | Event Driven |
| Workflow ≠ Runtime | Adapter Pattern |
| Agent ≠ Planner | Plugin First |
| 规范 ≠ 文档 | Stateless Runtime |
| | Learning Runtime |

这表明 L0 和 L1 是两个独立维护的原则列表。L0 是"哲学"，L1 是"架构设计原则"——但分开定义且不互相引用，读者会困惑"该以哪个为准"。

> **建议**：在 L0 中增加附录说明"这些原则在 L1 中展开为架构设计原则"，或统一为单一原则体系并在 L1 中明确"以下原则是 L0 第 X 条的架构体现"。

**C2 [中] Concept Model 与 Runtime Spec 的"链/循环"模型未映射**

Concept Model (L1.5) 定义 4 条链：
```
执行链、业务链、事务链、闭环链
```

Runtime Spec (L2) 定义 3 个 Loop：
```
Loop 1: 主动执行链、Loop 2: 事件驱动响应链、Loop 3: 反思与重规划链
```

两组概念有不同的抽象层次，但文档中没有显式映射关系。例如：Concept Model 的 "闭环链" 对应 Runtime Spec 中 Loop 3 的哪部分？"事务链"对应哪个 Loop 的哪个子流程？

> **建议**：在 Runtime Spec 第二章补充一段说明，将 4 条链映射到 3 个 Loop，标明"业务链在 Capability 执行路径中体现，事务链在 Execution 生命周期中体现"。

**C3 [低] Concept Model 章节编号重复**

concept-model-v1.3.md 中存在两处 `## 5.6`（第 282 行的 Domain 和第 305 行的 Business Object），导致后续章节编号错位。Domain 应为 5.5（紧接 5.4 ValidationResult 之后），Business Object 应为 5.6。

> **建议**：修正编号，Domain → 5.5, Business Object → 5.6, Plan → 5.7, Task → 5.8, Execution → 5.9, Capability → 5.10, Service → 5.11, Connector → 5.12, Enterprise System → 5.13, Policy → 5.14。

---

## 2. 完整性评审 (Completeness) — 8/10

### ✅ 已确认项

- **分层完整**：L0 (理念) → L1 (架构) → L1.5 (概念) → L2 (规范) 层次清晰
- **L2 五阶段基本完成**：P1 Runtime + P2 Reasoning + P3 Capability + P4 Execution + P5 Governance
- **核心对象定义完整**：Concept Model 定义了 27+ 个核心对象及关系
- **CQRS 差异表**：在 Concept Model、Capability Spec、Architecture 中均有完整定义
- **错误处理有覆盖**：Architecture-v5 第八章专章描述错误处理
- **SPI/扩展点**：Runtime Spec 第十三章定义了扩展点

### ❌ 问题项

**CP1 [高] P6 SDK 未开始**

L2 路线图中 P6 SDK 包含：Runtime SDK / Capability SDK / Connector SDK / Plugin SDK — 全部未开始。

没有 SDK 意味着所有 L2 规范的契约只能通过手工实现来验证。SDK 是"规范可测试"的前提——没有 SDK 的规范等同于没有编译器的语言规范。

> **建议**：至少为 Runtime SDK 和 Capability SDK 启动 L2 规范设计，定义 SPI 接口和基础类型。即使 Phase 1 不实现完整 SDK，契约的 IDL 定义（protobuf / OpenAPI / 接口签名）也应纳入规范。

**CP2 [中] 缺少架构视图矩阵**

当前文档以"功能分解"视图为主（按模块划分），缺少：
- **部署视图**：各模块如何部署（微服务/单体/混合）？Kernel 中的多个 Center 是独立进程还是同一进程内的模块？
- **数据视图**：核心实体（Session / Execution / Plan / Capability / Policy）的 ER 关系及主要数据流
- **交互视图**：关键场景下模块间的时序交互图（Sequence Diagram）

架构-v5 有分层架构图（静态结构），但没有足够的动态行为描述。

> **建议**：增加一个 L1 文档或一节，用 C4 模型或 4+1 视图方法论补充部署视图和数据视图。至少需要：
> - 部署架构图（哪些模块一起部署、哪些独立部署）
> - 核心实体的 ER 关系
> - 2-3 个关键场景的时序图（如：Chat 请求路径、Workflow 编译执行路径、Agent 多轮迭代路径）

**CP3 [中] Memory 是一个定义不足的核心概念**

Concept Model 的闭环链中，Memory 与 Knowledge 并列作为学习的结果：
```
Feedback → Evaluation → Memory / Knowledge → Planner
```
Memory 也在 Runtime Spec 第十二章（Feedback & Learning）中被引用。

但 Memory 在 Concept Model 中没有独立的章节定义（仅有 Supporting Concepts 表格中的一句话），在 L2 中也没有独立的规范文档。Memory 和 Knowledge 的分界线是什么？

> **建议**：在 Concept Model 中增加 Memory 对象定义（至少说明它与 Knowledge 的区别：Memory ≈ 执行经验/短期上下文，Knowledge ≈ 企业知识/长期资产），或在 L2 中规划 Memory 规范。

**CP4 [低] ConditionTrigger 定义过于简单**

Resource Spec 中 ConditionTrigger 定义为：
```
MUST: 定义条件表达式和评估频率
示例：condition: "temperature > 50 AND status == 'running'"
```
"温度 50" 从哪来？ConditionTrigger 需要连接 IoT/MES 数据源，这涉及数据获取的协议、认证、轮询方式——规范中没有提及 ConditionTrigger 的数据获取方式，只有条件表达式格式。

> **建议**：明确 ConditionTrigger 的数据源获取方式（轮询 MQTT / 订阅 EventBus / 调用 Capability），或者标注为 Phase 2+ 设计。

---

## 3. 合理性评审 (Soundness) — 7/10

### ✅ 已确认项

- **三引擎分离合理**：Reasoning / Execution / Coordination 职责边界清晰，互不重叠
- **Domain Layer 的设计正确**：在 Planner 和 Capability 之间插入 Domain 层是 v2→v3 评审的关键改进
- **Capability→Service→Connector 三层**：职责分离正确，符合企业软件标准模式
- **CQRS 的前置判断标准明确**：是否产生副作用是 Query vs Command 的分界线
- **Lifecycle 状态机设计合理**：覆盖了主要状态（Created→Planning→...→Completed/Archived）
- **闭环反馈机制的正确定义**：Feedback（原始数据）→ Evaluation（分析结论）→ Learning（注入）链路清晰

### ❌ 问题项

**S1 [高] Execution Runtime 仍然过载**

尽管 v1.1 评审已经指出 Execution Runtime 过载问题（#4 Execution 过载—同意），且评审结论建议移动 Decision Engine / Approval Manager / Human Task Manager，但当前 architecture-v5 第 5.2 节的 Execution Runtime 仍然包含：

```
Executon Runtime
├── Orchestrator          ← 核心职责 ✓
├── Decision Engine       ← 评审建议移出但未移
├── Transaction Manager   ← 核心职责 ✓
├── Compensation Manager  ← 核心职责 ✓
├── Approval Manager      ← 评审建议合并到 Policy Engine
├── Retry/Timeout Manager ← 核心职责 ✓
├── Human Task Manager    ← 评审建议移到 Coordination Runtime
└── Feedback/Evaluation   ← 地位不明确（架构图在 Execution 层，Kernel 层也有 Evaluation Center）
```

v1.1 评审明确说 "Execution 只做三件事：Run Task、Guarantee Consistency、Handle Failure"——但当前架构仍然包含 8 个子模块。

> **建议**：按照 v1.1 评审的共识方向，将：
> - Approval Manager → 合并到 Policy Center（审批是策略评估的一部分）
> - Human Task Manager → 移到 Coordination Runtime（人机交互是协调职责）
> - Feedback/Evaluation → 明确为独立模块（或移到 Kernel 层），不归 Execution Runtime
> 
> 这样 Execution Runtime 收窄为：Orchestrator + Transaction/Compensation + Retry/Timeout，真正"极度稳定"。

**S2 [中] Kernel Layer 的组件过于庞杂**

架构图 Kernel Layer 包含：
```
Context Manager | State Machine | EventBus | Policy Center
Checkpoint Manager | Resource Manager | Lifecycle Manager
Evaluation Center | Observability Center | Knowledge Center | Artifact Center
```

Kernel 本意是"有状态基础设施层"，但它承载了 11 个组件，从基础设施（EventBus）到业务模块（Policy Center / Knowledge Center / Artifact Center）。这种"除了 Application / Coordination / Reasoning / Execution / Domain / Capability 之外的所有东西扔到 Kernel"的做法削弱了分层意义。

> **建议**：重构 Kernel，至少拆为：
> - **Infra Layer**（有状态基础设施）：EventBus、Context Manager、State Machine、Checkpoint Manager
> - **Resource Layer**：Resource Manager、Lifecycle Manager
> - **Centers（保持独立）**：Policy Center / Knowledge Center / Observation Center / Artifact Center（不应作为 Kernel 的子组件）

**S3 [中] Feedback/Evaluation 的架构归属未定**

Feedback/Evaluation 同时出现在三个地方：
1. Architecture-v5 三层架构图中：不属于任何一层，在 Execution Runtime 下方作为独立块
2. Architecture-v5 第 5.2 节：作为 Execution Runtime 的子模块（`Feedback / Evaluation（新增）`）
3. Architecture-v5 Kernel 层：`Evaluation Center`

同一组件在三处有不同归属。具体来说：Feedback Collector 在 Execution Runtime 中合理（因为执行结果在这里产生），但 Evaluation Analyzer 和 Learning Injector 应独立或归入 Knowledge Center。

> **建议**：在架构图中明确 Feedback 和 Evaluation 的分离位置：
> - **Feedback Collector** → Execution Runtime（执行时收集原始数据）
> - **Evaluation Center** → 独立模块（或并入 Observation Center）
> - **Learning Injector** → Knowledge Center（将评估结果写入 Knowledge/Memory）

**S4 [低] 缺少对 Agent 与 Coordination Runtime 关系的细化**

Architecture-v5 说 Coordination Runtime 负责 "Multi-Agent 协调"，Agent Spec 有第七章 "Multi-Agent"。

但 Coordination Runtime 的职责描述中，"Multi-Agent Coordinator" 负责任务分配和信息交换，而 Agent Spec 说 Agent 本身也可以管理自己的生命周期。这两处的 Multi-Agent 协调机制可能重复——当 Agent 自行决定协作（Agent-to-Agent 通信）时，Coordination Runtime 还参与吗？

> **建议**：明确 Coordination Runtime 介入 Multi-Agent 的时机（冲突解决 / 死锁检测 / 资源争用），哪些协调由 Agent 自行完成，哪些必须经过 Coordination Runtime。

---

## 4. 可行性 & 演进性评审 (Feasibility & Evolvability) — 8/10

### ✅ 已确认项

- **Phase 分阶段可行**：P1→P2→P3→P4→P5→P6 的路线图合理
- **降级路径明确**：LLM Planner → Rule Planner，LLM Decision → Rule-based 兜底，Confidence < 阈值使用默认分支
- **Stateless Runtime → Stateful Kernel 的设计**：让 Runtime 可以水平扩展，符合生产部署要求
- **技术栈选择合理**：PostgreSQL (状态持久化) + Redis (缓存) + Kafka (消息) + K8s (部署) + Prometheus (监控) + OpenTelemetry (链路) — 都是成熟、广泛使用的技术

### ❌ 问题项

**F1 [中] CloudEvents 1.0 vs 2.0 不一致**

EventBus Spec 第 2.1 节说：
```
MUST: 事件格式符合 CloudEvents 2.0
MUST: ... specversion: "1.0"
```

CloudEvents 2.0 的 specversion 应该是 "1.0"（CloudEvents 规范的版本，不是协议版本号 2.0）。这里 "2.0" 和 "1.0" 的混用容易误导实现者——到底该实现哪个版本？

> **建议**：统一为 "CloudEvents 1.0 (specversion: 1.0)"，或者说明 "CloudEvents 2.0 规范版本对应 specversion 1.0"。

**F2 [中] 多个 MUST 不可验证/不可测试**

检查可测试性时发现：

| 规范 | 条款 | 问题 |
|------|------|------|
| Resource Spec | `MUST: 文件系统隔离` | "文件系统隔离"的程度未定义（chroot？Docker？seccomp？） |
| Runtime Spec | `MUST: 支持每秒 10,000+ 事件` | 10K/s 的量化要求需要在架构文档中定义测试标准（什么硬件？什么事件大小？） |
| Knowledge Spec | `SHOULD: 至少覆盖 100+ 企业术语` | "至少 100+" 是产品要求，写在 SHOULD 里有误导性 |
| Audit Spec | `MUST: 审计日志不可删除（管理员也不允许）` | 这是产品安全策略，不是规范契约。实现者无法自行实现"不可删除"——需要操作系统或硬件层面的配合 |

> **建议**：
> - 将不可验证的 MUST 降级为 SHOULD 或移到产品需求文档
> - 性能类 MUST 应附带测试条件（硬件配置、数据量级）
> - 安全策略类条款应注明依赖项（如"依赖操作系统审计文件的不可变存储"）

**F3 [低] Resource Spec 的 Browser 和 Sandbox 之间缺失隔离策略**

如果 Agent 同时使用 Sandbox（Python 代码执行）和 Browser（网页浏览），两者运行在同一进程/容器中吗？Sandbox 和 Browser 资源的关系没有定义——Sandbox 执行 Python 脚本可能操作 Browser 实例的文件或状态。

> **建议**：在 Resource Spec 中定义资源间的隔离策略（默认全隔离，除非显式授权跨资源访问）。

---

## 5. 规范质量评审 (Spec Quality) — 8/10

### ✅ 已确认项

- **MUST/SHOULD/MAY 使用准确**：12 份 L2 规范 ~145 条 MUST，区分度好
- **每份规范有 Scope / Not Scope 声明**：边界清晰
- **依赖关系表完备**：每份规范末尾附录包含依赖关系表
- **示例丰富**：Workflow DSL 有完整 yaml 示例，Decision 有 yaml 示例，EventBus 有 JSON 示例，Business Dictionary 有 yaml 示例
- **版本号管理合理**：Runtime Spec v1.2（已冻结），Capability Center v1.1（已冻结），其余 v1.0

### ❌ 问题项

**Q1 [中] 跨规范的事件类型定义重复，存在不一致风险**

EventBus Spec 第 3.2 节定义 30+ 事件类型（`runtime.execution.created`、`runtime.decision.evaluated` 等）。Audit Spec 第 2.2 节也定义了类似的事件类型列表。

两组列表结构相似但不同源：

| 事件 | EventBus Spec | Audit Spec |
|------|:-------------:|:----------:|
| `runtime.execution.created` / `completed` / `failed` | ✅ | ✅ |
| `runtime.session.created` / `completed` | ✅ | ✅ |
| `runtime.decision.evaluated` / `fallback` | ✅ | ✅ |
| `capability.called` / `succeeded` / `failed` / `compensation.triggered` | ❌ | ✅ |
| `runtime.transaction.*` | ✅ | ❌ |
| `runtime.resource.*` | ✅ | ❌ |
| `runtime.feedback.*` | ✅ | ❌ |
| `policy.approval.*` | ✅ | ✅ |
| `planner.intent.parsed` / `plan.generated` | ❌ | ✅ |

两个列表应该统一为单一事件类型注册表，审计规范引用 EventBus 规范的事件类型，而不是重新定义。

> **建议**：将事件类型定义集中到 EventBus Spec，Audit Spec 改为引用 EventBus 的事件类型（"Audit 订阅的事件类型见 EventBus Spec 第 3.2 节"），移除 Audit Spec 中的事件类型列表。

**Q2 [中] Architecture-v5 错误处理章节内容为空**

Architecture-v5 第八章标题为"错误处理"，但内容为空（文件在该章标题后截断，没有任何实际内容）。

> **建议**：补充错误处理章节，至少包括：错误分类（系统错误 / 业务错误 / 超时错误）、错误码体系、全局错误处理策略、各模块错误处理要求。

**Q3 [低] 多个规范缺少错误码和错误响应格式定义**

绝大多数 L2 规范定义了输入契约（参数格式、字段要求），但没有定义输出错误契约：

| 规范 | 有输入 Schema | 有输出 Schema | 有错误码定义 |
|------|:------------:|:-------------:|:-----------:|
| Runtime Spec | ✅ | ✅ | ❌ |
| Planner Spec | ✅ | ✅ | ❌ |
| Decision Spec | ✅ | ✅ | ❌ |
| Capability Spec | ✅ | ✅ | ❌ |
| Resource Spec | ✅ | ❌ | ❌ |

没有错误码意味着不同的实现可能使用不同的错误格式——Plan Validation 失败时，A 实现返回 `{ error: "permission denied" }`，B 实现返回 `{ code: 403, message: "..." }`。

> **建议**：在 Runtime Spec 附录中定义统一错误响应格式和通用错误码。
>

---

## 6. 评审延续性评审 (Review Continuity) — 6/10

### ✅ 已确认项

- **评审与版本演进的对应关系清晰**：v2→v3 评审（10 条建议，全部采纳/部分采纳）、v1.1→v1.2 评审（5 条建议，已处理）、v4→v5 评审（4 条建议，全部采纳）
- **三条主要评审记录的问题都得到了较完整的回应**
- **版本变更说明标注到位**：Architecture-v5 的 header 明确标注了"基于 v4.0 评审反馈优化"

### ❌ 问题项

**R1 [高] v1.1 评审#4 "Execution 过载"未完全落地**

v1.1-review-analysis.md 中明确指出：
> 建议：Decision Engine → 移到 Decision Layer；Approval Manager → 与 Policy Engine 合并；Human Task Manager → Coordination Runtime
> 评价："Execution 过载 — 同意"
> 优先级："P0 | Execution 职责收窄"

但 architecture-v5 的 Execution Runtime 仍然包含所有这些子模块。这不是"未采纳"，而是"已同意但未执行"。

> **建议**：要么在架构图中实际移出这些模块（反映评审共识），要么在架构文档中说明"保留的原因"（形成新的 ADR）。

**R2 [中] 缺乏问题的"关闭"状态标记**

历次评审记录（v3-review / v1.1-review-analysis / v4-feedback）都只记录了问题和决定，但没有后续的"关闭状态"：

- 每条建议是 `✅ 已实现 / ⏳ 实现中 / 🔄 方向对但等待 / ❌ 否决`？
- v3-review #7 "Resource Layer — 部分采纳，预留位置"——v5 架构图中 Resource Manager 在 Kernel 层，算实现了还是仍然只是"预留"？

> **建议**：在 L2/reviews/ 目录中维护一份 TRACKING.md，列出所有评审建议的当前状态（Open / In Progress / Resolved / Won't Do / Deferred），并标注对应实现文档版本。

**R3 [低] L2 规范版本号与评审版本没有对应关系**

评审记录引用的是 "v1.1 runtime spec"、"v4 architecture"，但 L2 规范当前的版本号（Runtime v1.2, 其他 v1.0）与评审版本难以直接对应。例如：Runtime Spec v1.2 是否包含了 v1.1 评审的全部改进？

> **建议**：每份规范的 CHANGELOG 应记录"vX.Y: 根据 vX 评审 #N 调整了 Chapter Z"。

**R4 [低] Observation Spec 中 "Replay" 被列为可观测能力但未展开**

v3-review #9 "增加 Observation" 决定中包含 Replay（执行回放）作为模块之一。Observation Spec (v1.0) 目前只定义了 Metrics / Trace / Logging / 告警，缺少 Replay。

> **建议**：明确 Replay 是 Observation Spec 的后续扩展项（Phase 2+），或在当前规范中注明。

---

## Top 5 优先修复

| 优先级 | 问题 | 维度 | 影响 | 建议方案 |
|:------:|------|:----:|:----:|---------|
| **P0** | **Execution Runtime 过载未解决** | 合理性 + 评审延续性 | 高—评审共识未落地，8 个子模块的 Execution Runtime 无法保证"极度稳定" | 将 Approval Manager → Policy Center, Human Task Manager → Coordination Runtime, 明确 Feedback/Evaluation 归属 |
| **P0** | **Kernel Layer 组件过于混杂** | 合理性 | 高—11 个组件挤在一个 Kernel 层，削弱分层意义 | 拆为 Infra Layer (EventBus/Context/State/Checkpoint) + Resource Layer + 独立 Centers |
| **P1** | **L0 与 L1 的原则集不一致** | 一致性 | 中—读者困惑"以哪个为准" | 统一原则体系，或在 L0/L1 中互相对照引用 |
| **P1** | **反馈输出错误码未定义** | 规范质量 | 中—各规范定义输入但缺少输出错误契约 | 在 Runtime Spec 附录中定义统一错误响应格式 + 通用错误码 |
| **P2** | **Memory 概念未充分定义** | 完整性 | 中—闭环的核心概念但缺少章节定义 | 在 Concept Model 中增加 Memory 定义，说明与 Knowledge 的边界 |

---

## 总体结论

**有条件通过**。EARP 的架构文档体系（L0→L2）质量总体良好，是经过多次迭代的系统性架构设计，其核心理念（三引擎分离、Domain First、CQRS、Closed-loop）和分层方法都是正确的。

需要优先处理的 3 个架构级问题：

1. **Execution Runtime 职责收窄** — 评审 v1.1 已同意但未落地，这是最紧急的"知道该做但没做"的问题
2. **Kernel Layer 重构** — 11 个组件的"万能 Kernel"需要在分层上进一步细化
3. **L0/L1 原则统一** — 基础文档之间的一致性影响所有阅读者的理解

建议在进入 L2 P6（SDK 设计）之前先解决 P0 问题，否则 SDK 的契约设计将基于一个已知有过度内聚问题的架构。
