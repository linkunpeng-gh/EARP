# EARP 架构设计 — 会话工作记录

> 记录当前架构设计会话的进展状态、已完成内容和待办事项。
> 下次打开时先读此文，了解当前进展。

---

## 一句话定位

EARP（Enterprise AI Runtime Platform）是一套面向**企业数字化与智能化场景**的 AI Runtime 平台。不是聊天机器人，不是 Workflow 编辑器，而是**企业 AI 的统一运行平台**。

---

## 已完成的核心产出

### 架构设计文档（L0 → L2，~30 份文档 / ~7,800 行）

| 层级 | 文档 | 状态 |
|------|------|:----:|
| **L0** | design-philosophy.md（9 条核心理念） | ✅ 已定稿 |
| **L1** | architecture-v6.md（三引擎 + 九层架构） | ✅ **最新版本** |
| **L1.5** | concept-model-v2.0.md（29 个核心概念） | ✅ **最新版本** |
| **L1** | business-flows.md（5 个场景化流程） | ✅ 已补充 |
| **L2 Runtime** | runtime-specification.md（含 Memory 附录） | ✅ **已冻结 v1.2** |
| **L2 Runtime** | eventbus-specification-v1.1.md | ✅ **已冻结 v1.1** |
| **L2 Reasoning** | planner-specification.md | ✅ v1.0 |
| **L2 Reasoning** | decision-engine-specification.md | ✅ v1.0 |
| **L2 Reasoning** | knowledge-center-specification.md | ✅ v1.0 |
| **L2 Capability** | capability-center-specification.md（含 Connector 附录） | ✅ **已冻结 v1.1** |
| **L2 Execution** | workflow-specification.md | ✅ v1.0 |
| **L2 Execution** | agent-specification.md | ✅ v1.0 |
| **L2 Execution** | scheduler-specification.md | ✅ v1.0 |
| **L2 Execution** | resource-specification.md | ✅ v1.0 |
| **L2 Governance** | policy-center-specification.md | ✅ v1.0 |
| **L2 Governance** | audit-specification-v1.1.md | ✅ v1.1（深化版） |
| **L2 Governance** | observation-specification.md | ✅ v1.0 |
| **L2** | summary-review.md + final-review.md | ✅ 全局回顾 |
| **索引** | README.md | ✅ |

### 评审记录（8 份）

覆盖了 v3 → v4 → v5 → v6 的每次架构迭代评审，以及外部评审分析。

---

## 核心架构决策（已冻结）

| 决策 | 内容 |
|------|------|
| 三引擎 | Reasoning（Python/LLM）+ Execution（Java/Go）+ Coordination 拆分 |
| Capability 三层 | Definition / Execution Contract / Policy |
| CQRS | Query（无副作用）+ Command（必经审批/审计/补偿） |
| Resolution Engine | Capability 调用唯一入口 |
| Capability Graph | 语义关系 + 执行约束（parallel/sequence/transaction） |
| Session | 作为 Runtime 外层容器，包住三个子 Loop |
| Closed-loop | Feedback → Evaluation → Learning（Agent 内循环 + Runtime 外循环） |
| Business Transaction | Saga 模式 + 逆序补偿 |

---

## 技术栈建议（讨论结论，未冻结）

| 方案 | 适用场景 |
|------|---------|
| Phase 1 全 Python | 快速交付验证架构（FastAPI + LiteLLM + Celery） |
| Phase 1 全 Java | 团队 Java 为主（Spring Boot + LangChain4j + Virtual Threads） |
| Python + Java 混合 | gRPC + Kafka：Reasoning(Python) / Execution(Java) / Coordination(Python) |

---

## 架构版本演进

| 版本 | 核心变化 |
|:----:|---------|
| v1 | 基于 Dify 分析的初始六边形架构 |
| v2 | 企业级扩展：Enterprise Kernel + Integration Layer |
| v3 | Domain Layer + Capability 三层 + Planner 双引擎 |
| v4 | 三引擎 + CQRS + Business Transaction |
| v5 | Closed-loop + Decision Engine + Feedback/Evaluation |
| **v6（最新）** | 概念深化 + 多轮评审收敛 + 全部 L2 规范完成 |

---

## 待办事项

| 优先级 | 事项 | 状态 |
|:------:|------|:----:|
| P0 | P6 SDK（Runtime/Capability/Connector/Plugin） | ⏳ 未开始 |
| P1 | Security Specification（凭证管理/数据加密/LLM 安全） | 📝 待补充 |
| P1 | 多租户隔离深度设计 | 📝 待补充 |
| P2 | 交叉引用自动化校验 | 🟡 Low |

---

## 关键入口文件

```
arch/README.md                       ← 文档索引与阅读建议（先读这里）
arch/L0/design-philosophy.md         ← 零号文档（新人从这里开始）
arch/L1/architecture-v6.md           ← 当前架构（最新版本）
arch/L1.5/concept-model-v2.0.md      ← 概念模型（最新版本）
arch/L1/business-flows.md            ← 业务流程场景
```

L2 规范从 `01-runtime/runtime-specification.md` 开始读，它是整个 L2 的核心依赖。

---

**记录位置**：`arch/session-record.md`
**开发流程规范**：`arch/development-process.md`（另一份独立文档）
