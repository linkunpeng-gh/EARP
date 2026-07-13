# Runtime 核心概念模型 — 评审报告

> 评审对象：Concept Model v1.0
> 对照基准：EARP Architecture v3.0
> 定位：L1.5（Architecture → **Concept Model** → Specification）

---

## 总体评价

**9.0 / 10 分**

这是目前我看到的方向最正确的文档之一。两条链（执行链 + 业务链）的设计是真正的概念提炼。概念模型作为 L1.5 的定位完全正确。

文档质量：优秀。不需要重写，只需要**补充 2 个 Critical 缺失概念 + 优化几个点**。

---

## 一、与 v3.0 架构完全一致的部分（通过）

| 概念 | v3.0 对应 | 评价 |
|------|-----------|------|
| User | 顶层发起者（人/系统/Workflow/Agent/Scheduler/Event） | ✅ |
| Request | Application Layer → Runtime 的唯一入口 | ✅ |
| Intent | Intent Planner 的输出 | ✅ |
| Domain | Domain Layer | ✅ |
| Business Object | Ontology 的核心实体 | ✅ |
| Plan | Task Planner 的输出 | ✅ |
| Task | Plan 的最小执行单元 | ✅ |
| Execution | Executor 管理的执行实例 | ✅ |
| Capability | Capability Center 管理的业务能力 | ✅ |
| Service | Capability → Service → Connector 中的 Service | ✅ |
| Connector | Capability → Service → Connector 中的 Connector | ✅ |
| Enterprise System | Integration Layer 的外部系统 | ✅ |
| Resource | Kernel / Resource Manager（Phase 2-3 预留） | ✅ |
| Artifact | Artifact Center | ✅ |
| Memory | Kernel / Memory Manager | ✅ |
| Knowledge | Knowledge Center（6 模块） | ✅ |
| Event | Kernel / EventBus | ✅ |
| 生命周期状态机 | Runtime Lifecycle（Chapter 3.3） | ✅ |

**对应关系完整，无一遗漏。**

---

## 二、必须补充的概念（Critical）

### 🔴 缺失 1：Policy

**严重程度**：Critical

**原因**：v3.0 架构中 Capability 的执行必须经过 Policy Gate（权限 / 限流 / 数据范围 / 审批）。Concept Model 中 Execution → Capability 之间缺少 Policy，意味着 Capability 的调用是"无管理"的。这在企业级场景中不可接受。

**建议补充**：在 Capability → Service 之间增加 Policy：

```text
Execution
    ↓
Capability
    ↓
Policy ← 新增
  ├── Permission（能否调用）
  ├── RateLimit（频率）
  ├── DataScope（数据范围）
  ├── Approval（审批要求）
  └── AuditLevel（审计级别）
    ↓
Service → Connector
```

**对应 v3.0 章节**：第一章 ADR-003、第六章 Policy Engine

---

### 🔴 缺失 2：ValidationResult

**严重程度**：Critical

**原因**：v3.0 架构的 Plan Validation Layer 是核心防御关卡，Intent → Plan → **Validation** → Execution 是标准路径。在 Concept Model 中缺少 Validation，意味着架构中解决 Planner 不可靠问题的主要机制在概念层面没有体现。

```text
Request → Intent → Plan → Validation ← 新增
                         → 通过 → Task → Execution
                         → 拒绝 → Request 回退 + 通知用户
```

**对应 v3.0 章节**：第三章 3.4 Plan Validation Layer

---

## 三、建议补充的概念（Major）

### 🟡 3. Trace

Execution 中提及了 Trace，建议明确定义为独立概念："Trace 是 Execution 的完整决策链记录，用于审计溯源和回放。"

### 🟡 4. Trigger / Schedule

User 概念中已涵盖 Scheduler，建议在 User 枚举中明确增加 `Trigger（Cron/Event/Webhook/MQTT/Condition）`。

### 🟡 5. Checkpoint

当前作为 Execution 的属性，建议在文档中明确："Checkpoint 是 Execution 在某个时刻的可恢复快照。"

---

## 四、可优化的设计点

### 4.1 两条链的汇聚点建议标注

执行链和业务链在 **Capability** 处汇聚，建议在模型中标注这个关键节点：

```text
Execution（执行链）
    │
    ▼
Capability ← Domain（业务链）
    │
Service → Connector → System
```

### 4.2 Event 通信机制

建议明确："所有 Event 通过 EventBus 发布/订阅，遵循 CloudEvents 规范，而非点对点通信。"

### 4.3 Execution 增加模式属性

文档提到"Workflow、Agent、Chat 共用同一 Runtime"，但概念模型未体现。建议在 Execution 中增加：

```text
Execution.mode: "chat" | "workflow" | "agent" | "scheduled"
```

### 4.4 对象职责边界表 — 建议补充"依赖"列

| 对象 | 职责 | 不负责 | **依赖** |
|------|------|--------|---------|
| Intent | 理解需求 | 不规划 | Knowledge / Business Dictionary |
| Plan | 描述目标 | 不执行 | 无 |
| Task | 最小工作单元 | 不管理状态 | Capability Center |
| Execution | 管理执行 | 不理解业务 | Resource / Capability / Policy |

---

## 五、你的最终建议（全部采纳）

| 建议 | 决定 |
|------|------|
| Concept Model 作为 L1.5，介于 L1 和 L2 之间 | ✅ 完全同意 |
| 补充 UML 类图 | ✅ 类图比文字更不易产生歧义 |
| 补充 Runtime Sequence Diagram | ✅ 时序图是对概念模型最好的验证 |

### 建议的 UML 类图骨架

```
Request → 1 : Intent → 1 : Plan → 1 : ValidationResult
  Plan → N : Task
    Task → N : Execution
      Execution → N : Capability
      Execution → N : Resource
      Execution → N : Artifact
      Execution → N : Event

Capability → 1 : Domain（领域归属）
Capability → N : Policy（策略绑定）
Capability → 1 : Service
  Service → N : Connector
    Connector → 1 : Enterprise System

Domain → N : Business Object
Domain → N : Capability
```

---

## 六、文档位置建议

```
L1（Architecture）      ← earp-architecture-v3.md
      ↓
L1.5（Concept Model）   ← 本文，Ubiquitous Language
      ↓
L2（Specification）
   ├── Runtime Specification
   ├── Planner Specification
   ├── Capability Specification
   ├── Workflow Specification
   └── Agent Specification
      ↓
L3（PRD）
```

**规则**：所有 L2 文档的"核心概念"章节必须引用 Concept Model，不允许重新定义 `Task`、`Execution`、`Capability` 等术语。

---

## 七、总结

| 维度 | 评分 | 说明 |
|------|:----:|------|
| 概念完整性 | 8/10 | 缺 Policy 和 ValidationResult 两个 Critical 概念 |
| 架构一致性 | 10/10 | 与 v3.0 架构完全对齐 |
| 边界清晰度 | 9/10 | 对象职责表是整个文档的最大亮点 |
| 统一语言价值 | 9/10 | 定位为 Ubiquitous Language 是正确的方向 |
| **综合** | **9/10** | **不需要重写，补 2 个 Critical 概念即可发布为 L1.5** |
