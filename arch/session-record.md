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

### 最近会话（2026-08-07）— 知识资产方向：决策 → 规范 → PRD → 实施 → 验证

> 完整记录：`arch/reviews/2026-08-07-knowledge-implementation.md`（下次从这里续）

**会话主线**：企业知识库优先 → RAG 打底 + 本体层（TBox/ABox）渐进 → 图谱点缀；gBrain 三机制借鉴（Compiled Truth / Enrichment / 零 LLM 建图）；数据中台分工（EARP 聚焦知识资产）；BD vs DD 概念钉死；三层检索流水线；Capability 类型正交（query/command × source_type）。

**关键产出**：
- 设计：`arch/design/2026-08-07-ontology-layer-design.md`（L2.5）+ `-l3-design-v1.md`（L3）
- 规范：knowledge-center v1.2 / planner v1.1 / KB v1.1 / runtime v1.4
- PRD：`PRD-2026-030` 新增；028/023 修订
- 代码：migration 0007（schema 对齐）/ 0008（ontology 7 表）+ ontology 模块 + 三层检索 + 前端接线
- 修复 4 个存量 bug（M4 schema 脱节 / 上传永远 unchanged / embedding 未初始化 / 单列主键跨租户冲突）
- 验证：51 tests passed + 端到端脚本 `scripts/verify_knowledge.py` 跑通

**下一步**：PRD-2026-030 M3（中台 importer + Enrichment）→ M4（admin 实体管理页）→ business_capabilities 复合主键

**待开新会话（2026-08-09）**：**企业级精准召回实施**——设计已定稿：`arch/design/2026-08-09-enterprise-retrieval-design.md`。内容：软路由（DD routing_description 向量 + KB summary_embedding，三级漏斗 top-N 候选）+ 元数据过滤（chunks.metadata JSONB + KB metadata_schema）+ 评估集（routing_eval）。落地路径 Phase 1（migration 0010 + routing.py + search 过滤 + 调试视图）→ Phase 2（LLM 路由 + rerank）。

---

### 最近会话（2026-08-09）— 企业级精准召回 Phase 1 已实施

> 设计：`arch/design/2026-08-09-enterprise-retrieval-design.md`（本会话讨论定稿后实施）

**会话主线**：软路由（DD 描述向量 + KB summary 向量三级漏斗）+ 元数据过滤（documents.metadata 权威）+ 评估集。逐项讨论定稿：migration 0012（非 0010，编号已被占用）；GIN 用 containment `@>` 而非 `->>` 等值；metadata 是**文档级**属性（schema=模板，doc=值，chunks.metadata 保留不填充）；自动字段存 id 不可手工覆盖（写时级联）；软路由接 `/knowledge/search` 无 scope 路径（ontology 三层检索留未来）；DD 描述不含文档标题（文档操作不触发域级重建）；关键词表下沉 knowledge 域（D-13）。

**关键产出**：
- migration `0012_routing`（routing_description/routing_embedding/routing_hash + summary_embedding/summary_hash/metadata_schema + documents.metadata + GIN jsonb_path_ops）
- `knowledge/routing.py`（关键词表下沉 + build_routing_index 幂等局部重建 + route_query 软路由 + route_debug 三层得分/覆盖自检/新鲜度）
- search_chunks 加 metadata_filters（documents.metadata @>，类型敏感）；/knowledge/search 无 scope 自动路由
- 新端点：routing/debug、routing/rebuild、documents/{id}/metadata、data-domains/{id}/suggest-description（AI 生成 DD 描述）
- 前端：test-retrieval 路由调试视图 + knowledge KB schema 编辑器/文档元数据弹窗 + data-domains routing_description/AI 生成
- 三层验证：机制层（pytest test_routing.py 8 项：触发/局部性/幂等/权限/类型敏感）+ 内容层（覆盖自检 + hash 新鲜度）+ 效果层（routing_eval.md 跑分 ≥90%，CI 大gram 伪向量/dev 真 bge-m3）
- `scripts/verify_routing.py`（dev 真模型评估）
- 验证：63 tests passed + import-linter kept + OpenAPI 基线同步；真实 bge-m3 语义评估 5/5 = 100%（≥90% 验收线）
- 追加（同日）：自动字段扩展公共默认（original_file_name / uploaded_at / updated_at / source），文档元数据弹窗只读展示，updated_at 随编辑刷新；测试补断言
- 追加（同日）：data_classification 移出自动字段（可变业务值），分类变更时清理 metadata 旧快照
- 追加（2026-08-10）：KB 检索摘要对齐 DD——migration 0013 summary_text（空=自动聚合/非空=人工覆盖）+ suggest-summary AI 生成端点（LLM 调用抽公共 helper `_llm_suggest`，DB 模型优先支持 ollama/openai）+ 前端 KB 编辑模态框字段与按钮 + 调试视图展示 KB 摘要文本；tech-debt #8（indexing_technique 仅存储未生效）
- 验证指南见设计文档 §0.1（四层：CI 测试 → 真实语义评估 → API → 前端）

**下一步（2026-08-11 定稿优先级，按序执行）**：

| 优先级 | 方向 | 内容 | 关联 |
|:---:|---|---|---|
| P1 | **A1 问答链路** | 真正的问答入口（query → 检索 → LLM 生成回答 → 带引用溯源「依据：财务部《报销制度》v3（2024-03）」）——RAG 最后一公里 | §4.3 |
| P2 | A3 ontology 接入软路由 | 候选 DD 限域喂给三层检索（实体查找 + chunk 层），图谱能力生效 | 2026-08-07 设计 |
| P3 | A2 Phase 2 精排 | bge-reranker 重排 + 低置信度 LLM 路由升级（<0.6 触发） | 设计 §3/§8 |
| P4 | B6 评估集管理页 | routing_eval 从 fixture 落库 + admin 管理页（跑分可视化） | 设计 §7/§8 ⑥ |
| P5 | B4 中台 importer + Enrichment | PRD-2026-030 M3 | PRD-030 |
| P6 | B5 admin 实体管理页 | PRD-2026-030 M4 | PRD-030 |
| P7 | C7 引用溯源展示 | 检索结果携带文档元数据 → 回答带引用 | §4.3 |
| P8 | C8 角色域权限管理页 | tech-debt #9（roles 页开放配置 + Admin 全权限通用机制） | tech-debt #9 |
| P9 | D10 embedding 容灾 | 远端 Ollama 不可用时自动切换 embedding 提供商 | 2026-08-10 踩坑 |
| P10 | D9 business_capabilities 复合主键 | tech-debt #7 | tech-debt #7 |

> 注：P7（引用溯源）与 P1（问答链路）天然耦合，可在 P1 内一并实现。
> 另：后台导航改版已定稿（8 项决策 + 蓝图 + 分期），见 `arch/design/2026-08-11-admin-navigation-redesign.md`——纯前端重构，可与 P1 并行或穿插。

---

### 历史待办

| 优先级 | 事项 | 状态 |
|:------:|------|:----:|
| P0 | P6 SDK（Runtime/Capability/Connector/Plugin） | ✅ 已完成 (2026-07-20) |
| P1 | Security Specification（凭证管理/数据加密/LLM 安全） | ✅ v1.2 追加实现状态附录 (2026-07-21) |
| P1 | 多租户隔离深度设计 | ✅ v1.3 追加实现状态附录 (2026-07-21) |
| P2 | 交叉引用自动化校验 | 🟡 Low |
| — | Phase 2 (embedding/structured output/cache) | ✅ 已完成 |
| — | M8 LLM 流式输出 | ✅ 已完成 |
| — | M11 LLM Planner 真实调用 | ✅ 已完成 |
| — | #10 Audit Service 拆独立进程 | ✅ 已完成 |
| — | #12 Saga/TCC 完整补偿 | ✅ 已完成 |
| — | #14 Plugin Daemon 独立进程 | ✅ 已完成 |
| — | #15 Langfuse 可观测性 | ✅ 已完成 |
| — | Langfuse 可观测性 | ✅ 已完成 |
| — | 技术债务追踪 | ✅ arch/tech-debt.md |
| P1 | PRD-2026-030 M3 中台对接 + Enrichment | 🟡 待实施 (2026-08-07 设计完成) |
| P1 | PRD-2026-030 M4 admin 实体管理页 | 🟡 待实施 |
| P2 | business_capabilities 复合主键 | 🟡 arch/tech-debt.md #7 |
| P1 | **企业级精准召回实施**（另开会话）：软路由（DD/KB 描述向量）+ 元数据过滤 + 评估集——设计见 `arch/design/2026-08-09-enterprise-retrieval-design.md` | ✅ 已完成 (2026-08-09 Phase 1) |

---

## 关键入口文件

```
arch/README.md                       ← 文档索引与阅读建议（先读这里）
arch/L0/design-philosophy.md         ← 零号文档（新人从这里开始）
arch/L1/architecture-v6.md           ← 当前架构（最新版本）
arch/L1.5/concept-model-v2.0.md      ← 概念模型（最新版本）
arch/L1/business-flows.md            ← 业务流程场景
arch/reviews/2026-08-07-knowledge-implementation.md  ← 最近会话记录（知识资产方向）
```

L2 规范从 `01-runtime/runtime-specification.md` 开始读，它是整个 L2 的核心依赖。

---

**记录位置**：`arch/session-record.md`
**开发流程规范**：`arch/development-process.md`
**开发运维备忘**：`arch/development-ops.md`（服务启停/重启/日志/排查速查）
