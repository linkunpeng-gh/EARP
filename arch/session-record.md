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

### 最近会话（2026-08-11）— 后台导航改版第一期已实施（纯前端）

> 设计：`arch/design/2026-08-11-admin-navigation-redesign.md`（8 项决策 + 蓝图 + 分期，本会话实施第一期）

**会话主线**：一级菜单 + 左侧抽屉导航框架；已有页面归位（知识/能力/治理/监控点亮）；首页重构（快捷入口 + 最近操作）；「规划中」统一占位页；治理中心 disabled 统一改「规划中」口径。纯 earp-admin 前端，后端 API 未动。

**关键产出**：
- `js/nav.js`（新增）：共享导航壳——8 个一级菜单（首页/工作台/知识中心/能力中心/应用中心/插件中心/治理中心/运行监控）+ 按 `data-section` 渲染左抽屉 + 规划中 roadmap 数据（`window.EARP_NAV`）；页面只需 `<body data-base data-section data-sub>` + 空 `<header>`，运行时自动注入 header/drawer/`.app-shell` 包裹，file:// 与 /admin/ 挂载均可用（相对链接）
- `pages/planned.html`（新增）：通用「规划中」占位页（?section=&item= 参数化，显示 phase/priority/roadmap 说明/同域已实现入口），不假装有功能
- `index.html` 重构：实时统计（KB/数据域/能力/模型配置/Sessions，API 不可用回退示例值并标注「离线」）+ 快捷入口 8 卡 + 最近操作（/v1/sessions 实时流水）
- 14 个页面全部挂接：剥离旧顶栏/下拉菜单硬编码导航（每页 -30 行死代码），body 上下文属性归位；login 走 `data-nav="none"` 极简头
- 页面归位：知识中心（数据域/知识库/召回测试）、能力中心（能力注册/推理测试/流式推理/模型配置，连接器规划中）、治理中心（Audit 已实现，Roles/Org/Tenants/Policy 规划中）、运行监控（Sessions 执行/对话日志）
- 孤儿页修复：stream.html（原无入口）新增抽屉项「流式推理」；models.html 从 ⚙️ 图标升级为抽屉项「模型配置」；doc-seg.html 无 doc_id 时自动跳回知识库（抽屉「分段配置」入口不落空）
- 样式：抽屉/首页快捷卡/规划中卡片/响应式（<900px 隐藏抽屉）；移除废弃 dropdown 样式
- 验证：node --check + 自建 DOM stub 冒烟测试（`apps/earp-admin/test-nav-smoke.cjs` / `test-planned-smoke.cjs`，6+4 场景全绿）+ 静态服务 200 全通

**实施说明（对设计的落地决策与后续调整）**：
1. 蓝图「运行监控」与「治理中心」均列 Audit（决策 #3 观测三件套）→ 初版两处抽屉均指向 audit.html；**按 PM 反馈已去掉运行监控下的「审计」子项**（Audit 仅留在治理中心）
2. 蓝图「推理测试」单入口 → 拆为「推理测试（plan.html）+ 流式推理（stream.html）」两项，解决 stream 孤儿页问题（决策 #4：plan/stream 均为能力调试工具）
3. 「分段配置」初版作为抽屉项指向 doc-seg.html；**按 PM 反馈已从抽屉去掉**（doc-seg/doc-config 仍可从知识库文档行 ✂️ 进入，页面 data-sub 归入「知识库」高亮）

**下一步（沿用 2026-08-11 优先级表）**：P1 问答链路（chat 落地 + 引用溯源，P7 并入）→ P2 ontology 接入软路由 → …；导航二期（知识资产看板首页聚合接口）随 P1 后推进

---

### 最近会话（2026-08-11）— Chat 智能体一期已实施（P1 问答链路）

> 设计：`arch/design/2026-08-11-chat-agent-design.md`（r1 12/12 + r2 2/2 评审闭环，9.2/10 通过）
> 计划：`tasks/chat-agent-task-breakdown.md`（19 任务）

**会话主线**：工作台 chat = 智能体编排工作台（创建/配置/调试/发布），最终使用界面归应用中心二期。后端 chat_apps 实体 + SSE 链路 + 引用溯源；前端 Dify 风格（卡片列表 → 编排页左右分栏）；发布评审 + 可见范围明确二期。

**关键产出**：
- migration 0014：chat_apps（retrieval 默认值 + RLS 三件套 + **显式 GRANT earp_app**——queue_schema 的 GRANT ALL TABLES 不覆盖升级路径新表）+ messages.citations + conversations.chat_app_id（ON DELETE SET NULL）
- chat_app_service：CRUD + 发布状态机（编辑已发布→回 draft）+ 审计 earp.chat_app.*
- chat_service：POST /chat_apps/{id}/chat SSE（会话/多轮配对/软路由+限定/结构尾巴 [N] 编号/citations 落库/模型三级解析含 credentials 解密）
- LLMConnector.chat_stream + 修 stream() 忽略 model_override base_url（评审实证 bug）
- 端点：/chat_apps CRUD+publish+chat、GET /conversations（列表）、GET /chat_apps/{id}、messages 补 citations
- 前端：chat.html 卡片列表+新建模态、chat-edit.html 编排页（左配置/右调试预览+流式+引用卡）、apps.html 应用中心、nav 点亮（chat/应用中心概览）
- 测试：test_chat_apps 7 项 + test_chat 7 项（bigram stub + FakeLLM）；验证 77 passed + import-linter + OpenAPI 基线
- 端到端真模型：bge-m3 + qwen2.5:1.5b —— 单轮/元数据/多轮追问（指代消解）/拒答全链路；scripts/verify_chat.py 引用命中 5/5=100%（≥80% 验收）
- 顺手发现并记录：test_routing 的 embed_chunks 传 document_id 导致 embedding 实际未写入（检索靠 NULL 向量假命中）——既有测试弱点，记入待办

**下一步**：P2 ontology 接入软路由 → P3 rerank 精排 → B6 评估集管理页；chat 二期：发布评审+可见范围、应用中心使用界面、对话日志 UI 升级（P7）

---

### 最近会话（2026-08-12）— Query Understanding & Query Plan 设计评审（产出 v0.2）

> 设计稿：`arch/design/query-understanding-query-plan-design-v0.1.md` → 评审后修订为 `-v0.2.md`

**会话主线**：评审 Query Understanding + Knowledge Query Plan 设计稿，逐项对齐既有实现（planner / ontology / chat / 软路由）后修订。方向与原则（QU 不选工具 / Plan 只读编排 / Ontology 是语义基础）认可；修正三类系统性问题：与既有 Planner 边界未厘清、示例关系类型与冻结 TBox 冲突、与 roadmap 脱节（当绿地规划）。

**关键产出**：
- `query-understanding-query-plan-design-v0.2.md`（新文件，v0.1 留作历史）：§4 对齐矩阵（QU 问题类型 intent 定位为知识检索维度，与 capability intent 正交并存，在 resolve_with_entities() 汇合）；§11 一期砍通用 DAG DSL → 5 条固定策略函数；§9/QP-05 软融合（通道优先级而非排他）；§5.2 新增会话上下文 context 维度；§7.3/QP-08 补租户隔离；评估并入 routing_eval/verify_* 体系；filecite 残留清理 + 交叉引用带版本号
- 分阶段对齐 roadmap：Phase 1-2 = 本文档净增量（QU + 固定策略）；Phase 3 = 当前 P2 延伸；Phase 4 = P3 rerank；P1 chat 即 ANSWER 节点现成实现

**评审暴露的两个实质判断（待项目组拍板）**：
1. **TBox 部件级关系缺口**（开放问题 1）：`supplied_by` 源类型只有 material、`manufactured_by` 源类型只有 equipment，`component → supplier` 供应关系、`component → equipment` 归属关系均不在冻结 12 类中（ontology 设计 §7.2 示例本身也用了未定义关系）——需决策扩展 TBox 或改建模（部件按 material 处理）
2. **关系候选必须来自 TBox**（开放问题 2）：RELATION/MULTI_HOP/CAUSAL 的关系只允许 LLM 从 ontology 关系候选集选，不允许发明关系

**下一步**：P2 ontology 接入软路由（沿用任务书 `tasks/ontology-soft-routing-task-breakdown.md`，4 决策点已对齐）→ 项目组对开放问题 1/2 拍板后进 Phase 1（QU schema 冻结）

---

### 最近会话（2026-08-13）— Query Understanding & Query Plan 对抗式评审（产出 v0.3）

> 评审：`arch/reviews/query-understanding-query-plan-design-v0.2-review.md`（对抗式 + 代码事实核对，19 问题）
> 设计：`arch/design/query-understanding-query-plan-design-v0.3.md`（v0.2 → v0.3 闭合 + 二轮内审 §0.1）

**会话主线**：对 v0.2 做第一性原理对抗式评审，代码核对发现「直接映射」两处可证伪（`graph_query` 无反向遍历、`resolve_with_entities` 只吃单字符串）、跨通道 RRF 范畴错误、intent→策略映射不闭合、Evidence/Structured Query schema 未冻结；产出 v0.3 闭合。二轮内审再补 4 项（§0.1 修订 13-16）、三轮修订再补 2 项（§0.2 修订 17-18：方案 A 定性修正 + intent 收敛/Phase 重排序）。

**关键决策**：
1. **方案 A（三层 RRF 定性修正）**：`knowledge_search` 三层 RRF（profile/graph/chunk 文本证据）是**合法 recall 融合，非债、无需重构**；唯一真实边界是「capability 结构化行不进 RRF」。缺的是「角色层」（答案 vs 引用 + capability 主证据），Phase D3 叠加实现。P2 照常执行（验收「实体类 P@5 提升」即 recall 层验证）。写死：tech-debt #10 + P2 任务书风险 #6 + 本记录。
2. **TBox 部件级关系缺口阻塞 Phase B（QU）**：§6.2 写死「relation 必须来自 TBox」，而 TBox 缺 `component → supplier`，将打穿 §17「relation 准确率 ≥ 80%」——**Phase B 评估集构建前必须拍板**（扩展 TBox 或部件按 material 处理）。
3. **intent 收敛 + planner 后置（§0.2 修订 18）**：一期可靠分类子集 = {FACT, RELATION, AGGREGATION}，其余 7 类显式回落（QP-14），§17 只对可靠子集计分；Phase 顺序 = A（P2 接三层）→ B（QU 并行）→ C（最小 planner 后置）→ D（能力闭环 + 角色层）→ E（P3 rerank）。理由：AGG/COMP/TREND/CAUSAL 唯一消费者是 capability query（通道未就绪无消费者）；「graph vs rag 误选」疼点在通道接通前无法度量。

**下一步**：项目组拍板 TBox 缺口 → Phase A（P2 三层接入 chat 链路，沿用任务书）→ Phase B（QU 独立并行建设）→ Phase C（最小 planner，度量疼点后扩展）

---

### 最近会话（2026-08-15）— P2 ontology 接入软路由已实施（A3）

> 计划：`tasks/ontology-soft-routing-task-breakdown.md`（规划定稿版：9+2 任务，D1-D5 决策固化）

**会话主线**：按规划执行序 1 → (2,3 并行) → (5,6,F1,F2 并行) → 7 → 8 → 9。让 ontology 三层检索（profile/graph/chunk）在无 scope 查询路径生效。

**关键产出（后端）**：
- `ontology/search.py::knowledge_search` 增强：新增 `knowledge_base_ids/query_text/mode/threshold/metadata_filters/eventbus` 透传（L3 直通 search_chunks，kb 优先于 dd 回退）；profile/graph item 补 `title` 字段；**修复 L3 chunk item 字段保留**（原实现丢弃 kb_id/kb_name/metadata/similarity → chat citation 缺 kb_id/similarity，测试实证抓到）
- `/knowledge/search` 无 scope：route_query → cand_dds 非空 → knowledge_search 三层（L1/L2 限 DD、L3 限 KB）；cand_dds 空 → 全租户 chunk 兜底（决策 D4）
- `chat_service._retrieve`：软路由路径接入三层（kb_scope 限定路径保持现状）；citations 三源转换（chunk 保持原结构；profile/graph 带 source/entity_id/entity_type/title/key_facts，决策 D3）
- **import-linter 传递检查实证**：任务书「无新增 ignore_imports 需求」判断被推翻——conversation.chat_service → ontology.search → knowledge.search_service 构成传递违反（conversation/knowledge 均 independence 域），已加 ignore 条目

**关键产出（前端）**：
- test-retrieval.html：结果卡 source 徽标（📇实体档案/🕸图谱/📄文档），chunk_id 缺失不渲染 undefined，score 兼容 rrf_score
- chat-edit.html：引用卡实体/图谱徽标（cc-badge），聚合 key 兼容 entity_id

**测试与验证**：
- test_ontology_search.py +4（纯 chunk 回归/字段保留、kb 透传 L3 限定、DD 权限限域、端点无 scope 三层）；test_chat.py +1（软路由三层 citations 含 profile/graph）；seed 用 suffix 隔离全局唯一 id（knowledge_base_id/role_id 非复合主键）
- `scripts/verify_ontology.py`（新建）：dev 真模型实体类问题集 6 问，三层 vs 纯 vector 基线 P@5（验收 ≥+10）；CI 机制层由 pytest 覆盖
- 全量 85 passed + import-linter + OpenAPI 基线同步（改动了 search 端点响应含 source 字段）
- main.py I001（import 排序）为既有问题，未在本次范围

**效果层验证（dev 真模型 bge-m3，2026-08-15）**：`scripts/verify_ontology.py` 跑分 PASS ✅——三层 P@5 命中 3/6 = 50% vs 纯 vector 0%，提升 **+50 个百分点（验收线 ≥+10）**。3 个未命中归因：
1. 纯中文实体长查询（「A产线由谁负责」「高温报警由什么设备引起」）实体层未命中——`_entity_hits` 的 CJK tokenize 把整句当一个 token，`lookup_entities` 的 ILIKE 方向是「实体名包含查询串」而非「查询包含实体名」——**QU Phase B 范畴**（已知项）
2. 「CNC-01 由哪家供应商制造」实体层命中但 manufactured_by 被 RRF top-5 截断——graph lane 排序按 target entity_id 字典序、与查询无关（RRF 边界效应，每次 seed 随机翻转）——**QU Phase C plan_relation 定向关系查询范畴**
3. 脚本从 build_engine（应用角色）改为迁移角色 engine + 跨租户 purge（knowledge_base_id/role_id 非复合主键、dev 库被 verify_routing/verify_chat 复用过）——对齐 verify_routing 模式

**下一步**：P3 rerank 精排（recall 层）→ Phase B（QU 独立并行建设）→ 项目组拍板 TBox 缺口（阻塞 QU relation 门槛，见 2026-08-13 记录）

### 追加（2026-08-15）— 实体/事实批量导入（模板 + 干跑校验 + profile 联动）

> 需求来源：应用角度——手工导入需要一个文件模板，否则用户不知道上传什么样的数据（ontology 设计 §6 无中台兕底路径的落地）

**关键产出**：
- `ontology/import_service.py`（新）：CSV 解析（跳过 # 注释行）+ 校验（entity_type ∈ TBox 且 kind=object、data_domain ∈ DD、attributes JSON 合法、business_code 按 (type,code) 判重；facts 的 relation ∈ TBox、源/目标实体类型匹配关系类型集合、business_code 引用解析、confidence 0-1）+ 干跑不写库 + 执行写库（upsert_entity 幂等 + add_fact）
- **profile 联动**：导入后对涉及实体（source+target）重编 profile——tech-debt #11 ① 写时失效场景的现成载体
- 端点：`GET /v1/ontology/import/templates`（下载含说明头+示例行的 CSV）、`POST /v1/ontology/import`（multipart entities_file/facts_file + dry_run 参数，默认 true）
- 测试 test_ontology_import.py 4 项：模板内容、干跑合法不写库、干跑逐行错误收集（类型/域/JSON/编码重复/关系方向/confidence）、执行+profile 重编（key_facts 含新事实）
- 人工测试指南补场景 7（任务书）；修正指南 ontology 路径缺 /v1 前缀
- **前端临时页**：`pages/entity-import.html`（知识中心抽屉「实体导入」）——模板下载（带 BOM 供 Excel 识别中文）+ 上传 + 干跑结果表格（来源/行号/原因）+ 确认导入；API-only → 有 UI，可并入 M4
- 验证：92 passed + 真实 API 冒烟（模板下载 → 干跑报错 → 执行 → lookup/profile 联动验证全通）

**下一步**：前端导入入口并入 M4 admin 实体管理页（现为 API-only）→ P3 rerank → Phase B（QU）

### 追加（2026-08-15）— P3 rerank 接入 + G1 graph 反向遍历

**P3 rerank（enterprise-retrieval §8 Phase 2 ⑧）**：
- `infra/ext/ext_reranker.py`（新）：可插拔 RerankerProvider（Ollama `/api/rerank` + OpenAI 兼容 `/rerank`）+ 工厂 singleton，`rerank_provider` 默认 `none`（本地 Ollama 0.32 无 rerank API）
- `search_chunks` 加 rerank 步骤：RRF/vector 召回后对 top-N 候选（`rerank_top_n=20`）cross-encoder 精排取 top_k；provider 未配置/失败 → 原序返回（优雅降级，日志告警）；结果打 `rerank_score` 字段
- 透传链：knowledge_search → main.py（lifespan init + DB model_config 的 rerank 类型 reinit）→ chat_service
- 测试 test_rerank.py 3 项：mock 重排/截断/score、禁用保序、search_chunks 全链路（启用排序变化 + 禁用原样）
- **真模型验证待环境**：本地 Ollama 无 `/api/rerank`（404）+ 远程不可达——实现可插拔、环境就绪即用（拉 bge-reranker 模型 + `EARP_RERANK_PROVIDER=ollama`）

**G1 graph 反向遍历（QU §12 例 4 / Phase D2 缺口闭合）**：
- `graph_query` 加 `direction` 参数（forward 默认 | backward）：backward 从 target 反走到 source（递归 CTE 镜像 + 环保护），邻居实体统一以 `target_*` 呈现（消费方无感）
- API `GET /v1/ontology/entities/{id}/graph?direction=backward`；测试 test_graph_query_backward（工厂 forward 空 / backward 找到 2 台设备）

**验证**：93 passed + import-linter + OpenAPI 基线；P3 无行为回归（rerank 默认禁用）

**下一步**：P3 真模型验证（待 rerank 环境）→ G2 图谱可视化 → Phase B（QU，等 TBox 拍板）

### 追加（2026-08-15）— G2 图谱可视化（图谱探索页）

- `pages/entity-graph.html`（新）：实体 lookup → forward+backward 图查询 → vanilla SVG 渲染（中心实体 + 环形邻居 + 关系标签 + 方向图例，绿=前向/琥珀=反向），点击节点以它为中心展开；文本关系明细列表
- nav.js 知识中心抽屉新增「图谱探索」
- 真 API 冒烟：CNC-01 forward（belongs_to→A产线 / located_in→华东一厂 / manufactured_by→上海某精机）+ backward（caused_by←高温报警）全通
- 至此图谱能力从「API 文本」补全为「可视化探索」（G1 反向遍历 + G2 可视化 + 导入数据 = 完整闭环）

**下一步**：Phase B（QU，等 TBox 拍板）→ M4 实体管理页（导入/图谱并入）→ P3 真模型验证（待 rerank 环境）

### 追加（2026-08-15）— TBox 部件级关系缺口闭合（方案 A）

> 决策简报拍板：方案 A（扩源类型，不引入 has_component；YAGNI）——「主轴轴承由谁供应」「主轴轴承属于哪台设备」可建模，不再阻塞 QU §17 relation 门槛

**落地**：
- `tbox_service.SEED_RELATION_TYPES`：`belongs_to` 源扩 component（target 加 equipment）、`supplied_by` 源扩 component（仍 12 类）
- **migration 0016**：存量租户全量同步（`init_tenant_tbox` 是 ON CONFLICT DO NOTHING，已存在行不更新——migration superuser 显式 UPDATE）；downgrade 回退
- 测试：test_component_supply_belong_relations（component→supplier / component→equipment 导入校验放行）；修 test_migrations downgrade 断言（head 变 0016，`-2` 语义过时）
- 文档：ontology 设计 §3.2 表格同步（belongs_to/supplied_by 源加 component）、QU v0.3 §20 问题 1 标记已决策关闭
- 验证：94 passed + migration 0016 应用成功

**下一步**：Phase B（QU 理解层）——TBox 缺口已解除，可直接开工 → M4 实体管理页 → P3 真模型验证

### 追加（2026-08-15）— M4 admin 实体管理页（PRD-2026-030）

**后端**：
- `abox_service.list_entities`（分页 + 类型/数据域过滤 + status）+ `deprecate_entity`（软停用，facts 保留）
- `GET /v1/ontology/entities`（列表）、`POST /v1/ontology/entities/{id}/deprecate`；**graph_query 返回 fact_id**（前端可真撤销事实）

**前端**：
- `pages/entities.html`（知识中心抽屉「实体管理」）：列表（类型/数据域下拉 + 搜索 + 分页）+ 新建实体模态（TBox 类型/DD 下拉 + attributes JSON）+ 详情内联展开（实体信息 + 📇profile 档案 + 🔗前向/反向关系 + 真撤销 + 添加关系）+ 跳转图谱/导入
- nav.js 新增「实体管理」；图谱探索页已支持 ?entity= 直达

**验证**：95 passed（+list/deprecate/fact_id 测试）+ OpenAPI 基线 + 真 API 冒烟（列表 total 8 / 类型过滤 / graph 含 fact_id）

**下一步**：M4 后续可加 TBox 管理（tech-debt #12 审批流一并设计）→ Phase B（QU 理解层）→ P3 真模型验证

### 收尾（2026-08-15）— 会话完结状态

**交付汇总**（14 commits）：P2 三层接入软路由 → 实体导入（API+前端+TBox 一览）→ P3 rerank（可插拔）→ G1 反向遍历 → G2 图谱探索 → TBox 缺口闭合（migration 0016）→ M4 实体管理页。**95 tests 全绿** + import-linter + OpenAPI + 多轮真 API 冒烟；verify_ontology 效果层 PASS（+50%）。评审链文档（v0.1/v0.2/review/TBox 决策）已入库。

**遗留提醒（不阻塞）**：
1. 8000 端口有残留 API 进程（PID 97205）——不需要可 kill
2. **P3 真模型验证待 rerank 环境**：本地 Ollama 0.32 无 `/api/rerank`（404）+ 远程不可达；升级 + 拉 bge-reranker + `EARP_RERANK_PROVIDER=ollama` 即生效（零代码）
3. **Phase B（QU 理解层）**：TBox 缺口已解除，随时可开工（3-5 天）；Structured Query schema（v0.3 §6.2）已冻结，评估门槛（§17）已定义
4. M4 延伸：TBox 管理页（可并入 tech-debt #12 审批流）
5. tech-debt #11（profile 无过期管理）/ #12（TBox 无审批流）待治理

**知识资产方向当前能力闭环**：导入（建数据）→ 管理（M4 CRUD/关系）→ 探索（图谱）→ 检索（三层）→ 档案（profile 联动）；软路由 + 元数据 + rerank（待环境）构成企业检索管线

---

### 会话续接（2026-08-16）— FDE 使用反馈迭代 + TBox 管理页

> 本会话从「P2 实施」延续到「FDE 反馈驱动的产品化迭代」，102 tests 全绿。

**2026-08-16 新增交付**：
- **TBox 类型管理页**（`pages/tbox.html`）：实体/关系类型新增与停用自助（ID 校验/类型多选/基数）；后端补 `deprecate_relation_type`；一期约束禁改集合/ID（tech-debt #12）
- **路由调试三层明细**：`route_debug` 返回 ontology_layers（profile/graph/chunk 逐层命中 + RRF 融合），前端 Level 3 展示；按检索顺序重排（实体→图谱→文档漏斗）；分数尺度说明（不可跨层比较，RRF 用排名/rerank 仅文档层）
- **实体识别修复**：`lookup_entities` 反向子串匹配——「主变压器是哪个公司生产的」等纯中文实体长查询现在命中实体层
- **停用体验系列**：TBox/实体 create 重复优雅 409（禁自动重新启用，停用=软终态）；停用幂等；「显示已停用」开关（list 支持 status=all）；停用实体详情/图谱可查看（get_entity/compile_profile 放宽 deprecated，检索仍排除）
- **知识中心抽屉分组**：文档知识（数据域/知识库）/ 结构化知识（类型管理/实体管理/实体导入）/ 探索验证（图谱探索/召回测试）——nav.js 支持 group 分组渲染
- FDE 使用说明 `arch/guides/earp-fde-user-guide.md`（实体管理/导入/图谱/检索全流程 + 示例 + FAQ）

**验证状态**：102 tests 全绿 + import-linter + OpenAPI 基线 + 多轮真 API 冒烟（导入/图谱/TBox/检索/停用全链路）

**未完成清单（下次会话续接）**：
1. **Phase B（QU 理解层）**——最大块（3-5 天）：TBox 缺口已解除、schema 已冻结（v0.3 §6.2）、评估门槛已定义（§17）；规则优先 + LLM 低置信度升级
2. **P3 rerank 真模型验证**——待 rerank 环境（本地 Ollama 0.32 无 /api/rerank；升级 + 拉 bge-reranker + `EARP_RERANK_PROVIDER=ollama`，零代码）
3. **tech-debt 治理**：#12 TBox 审批流（draft→approved + 审计 + 停用恢复路径）、#11 profile 无过期管理（写时失效/读时 freshness/enrichment 落 scheduler）、#9 角色域权限、#7 business_capabilities 复合主键、#8 indexing_technique
4. **M3 中台 importer + Enrichment**（PRD-2026-030，P5）；**B6 评估集管理页**（P4）
5. **M4 延伸**：TBox 管理页与审批流整合（#12）；FDE 指南 FAQ 更新（纯中文实体已修，可删对应条目）
6. 8000 端口残留 API 进程（PID 97205）可 kill

**知识中心当前能力**（8 项分 3 组）：文档知识（数据域/知识库）+ 结构化知识（类型管理/实体管理/实体导入）+ 探索验证（图谱探索/召回测试）——实体知识闭环（导入→管理→图谱→检索→档案）完整

---

### 会话续接（2026-08-16）— Phase B（QU 理解层）已实施

> 任务书：`tasks/query-understanding-phase-b-task-breakdown.md`（14 Task + 前端 F1；D4/D7 讨论定稿方案 A）
> 设计：`arch/design/query-understanding-query-plan-design-v0.3.md`（§5/§6/§7/§17）

**会话主线**：规则优先 + LLM 低置信度升级的理解层独立建设（Phase B 净增量）——Structured Query schema 冻结落地、六维规则层（时间/实体/intent/relation/operation/约束）、置信度（§6.4 机械计算）、derive_needs 纯函数、LLM 升级（只补未命中字段 + TBox 过滤）、评估集（N=111）、debug 端点 + 前端调试视图。

**关键产出（后端）**：
- `ontology/understanding.py`（新建）：§6.2 Pydantic 冻结模型（Intent 10 枚举/TimeConstraint/EntityMention/RelationMention/Operation/AnswerRequirement/StructuredQuery）+ `_INTENT_KEYWORDS`（可靠子集 {FACT, RELATION, AGGREGATION}，其余 7 类显式回落 QP-14）+ 规则层六维 + `understand()` 主入口 + `derive_needs()`（§7 单源推导）+ `upgrade_with_llm()`（低置信度升级）
- `connector.py::json_complete()`（新方法，D4 方案 A）：无 DB（model_override 参数化），ollama/openai JSON 单发，不可达返回 None 回落；`main.py::_llm_suggest` 保留薄封装（签名/响应不变，两处调用点零改动）
- `POST /v1/ontology/understanding/debug`（D7）：StructuredQuery + 字段命中明细 + derive_needs + LLM 升级标记 + relation 候选溯源（复用 route_debug 分层可解释模式，§15）
- **评估集** `tests/fixtures/understanding_eval.md`（N=111 标注查询）+ `test_understanding_eval.py`（机制层 runner）+ `scripts/verify_understanding.py`（dev 真 LLM）

**关键产出（前端）**：`pages/understanding-debug.html`（QU 调试视图，标注调试工具）+ nav 抽屉「探索验证」组加「QU 调试」

**规则层关键决策（实施中修正）**：
1. AGG 关键词收紧：裸「多少」→「有多少/多少台/多少次」等复合量词（「更换周期是多少」是属性查询非聚合）
2. 消歧顺序 AGGREGATION > RELATION > FACT（「哪个设备故障最多」聚合语义强于疑问词）
3. RELATION 关键词去掉「哪些/供应商」（LIST 误伤）；「由什么/是什么引起的/生产什么/哪条」加入
4. relation 提取只做「实体作 subject」被动模式（方向校验 source_type）；「谁负责 A产线」等主动疑问一期不提取（Phase C 范畴），方向校验失败不强行用首实体（避免 CNC-01→produces 类错误）
5. `_llm_suggest` 抽取：D4 方案 A（json_complete 无 DB + 薄封装）——回归面 = 内部实现替换
6. LLM 升级 relations/entities 额外允许「LLM 主动输出 + result 为空」（schema 校验=TBox 硬门槛）；intent 非法拒绝（合规率 100% 不破）

**验证**：141 tests passed（102 → +39）+ import-linter + OpenAPI 基线同步（新端点）+ ruff/pyright 零新增；评估集机制层 **intent 100% / entity 100% / relation 100% / schema 0 违规**；dev 真模型（qwen2.5:1.5b 真 LLM 升级路径）**intent 95% / entity 100% / relation 100% / schema 0 违规 / 规则层 p95 8.7ms（预算 <50ms）**——全部超 §17 门槛（≥85%/≥90%/≥80%/100%），gating 通过可启动 Phase C

**下一步（沿用 2026-08-16 优先级表）**：
1. **Phase C（最小固定策略 Planner）**——§17 gating 已过；3 策略（plan_fact/plan_relation/plan_aggregation）按疼点启用；`select_plan` 规则映射表 + Execution Trace + `resolve_with_entities` 接入 plan_aggregation
2. **Phase D**：D1 `resolve_with_query()` 落地；D2 ABox 反向邻接（已补 G1，收尾确认）；D3 角色层 Evidence 组装（tech-debt #10）
3. **P3 rerank 真模型验证**——待 rerank 环境（本地 Ollama 0.32 无 /api/rerank；升级 + 拉 bge-reranker + `EARP_RERANK_PROVIDER=ollama`）
4. **tech-debt 治理**：#12 TBox 审批流、#11 profile 过期管理、#9 角色域权限、#7 business_capabilities 复合主键、#8 indexing_technique
5. **M3 中台 importer + Enrichment**（PRD-2026-030）；**B6 评估集管理页**（routing_eval 落库 + 跑分可视化）
6. 8000 端口残留 API 进程（PID 97205/72523）可 kill；FDE 指南 FAQ 更新（纯中文实体已修）

---

### 会话续接（2026-08-16）— Phase C（最小固定策略 Planner）已实施

> 任务书：`tasks/query-understanding-phase-c-task-breakdown.md`（12 Task；D2/D3 方案 A 已确认）
> 设计：`arch/design/query-understanding-query-plan-design-v0.3.md`（§10/§11/§12/§16/§17）

**会话主线**：QU 理解层之上实现最小固定策略 Planner——select_plan 规则映射表（10 类全覆盖）+ 3 策略函数（plan_fact/plan_relation/plan_aggregation）+ Execution Trace + plan-debug 完整可解释链端点 + Plan 层评估。

**关键产出（后端）**：
- `ontology/planning.py`（新建）：Evidence/EvidenceChannel/TraceRecord/PlanResult/QueryContext schema（§9.1/§10/§11.1 冻结）+ `select_plan`（§11.2 规则映射表，10 类全覆盖 QP-11，CAUSAL/MIXED 显式回落 QP-14）+ `_Tracer`（trace 记录器）+
  - `plan_fact`：route_query → 三层检索（candidate_dds 非空）/全租户 chunk 兜底（D4），metadata_filters 透传 + trace 步进 + citations/evidence 三源转换
  - `plan_relation`：lookup_entities（用 StructuredQuery.entities mention）→ graph_query（forward，MULTI_HOP max_hops=2）→ graph 无事实 RAG 补证（§14）；无实体回落 plan_fact
  - `plan_aggregation`（D2）：resolve_with_entities 候选解析 → 无 query 候选回落 plan_fact / 有候选 trace 标注「capability 通道未就绪」（Phase D1 接入执行器，不 mock）
  - `execute_plan` 入口（debug 端点/verify 脚本共用）
- `POST /v1/ontology/understanding/plan-debug`（§15 完整可解释链：QU → select_plan → 策略执行 → PlanResult）
- `knowledge/routing.py::route_query` 增强：**query_embedding=None 防护**（vector lane 跳过，keyword lane 兜底，优雅降级——plan_fact 在 embedding 不可达时不崩）
- Plan 层评估：`test_planning.py`（13 用例）+ `test_planning_eval.py`（策略命中率 ≥95%）+ `scripts/verify_planning.py`（dev 真 LLM + 真检索端到端）

**关键产出（前端）**：understanding-debug.html 加「🗺 运行策略」按钮 → plan-debug 端点 → select_plan 卡 + Execution Trace 步进表 + Evidence 通道表

**Phase C 关键决策落地**：
1. D2（plan_aggregation 一期=候选解析+回落）：capability 执行链仅 demo.echo（已核实）→ 有候选 trace 标注通道未就绪，不假执行；无候选回落 plan_fact——「AGGREGATION 唯一消费者是 capability query，通道未就绪无消费者」（§16 时序理由）成立
2. D3（chat 一期不接）：PlanResult 经 plan-debug 验证；chat_service 保持 P1 双通道——避免 conversation→ontology.planning→knowledge.* 传递 import 链（Phase D 接 answer 时按 P2 先例加 ignore）
3. Plan 不落库（QP-12）；Evidence 为 recall 层通道映射（§9.2 消解 Phase D3）
4. 顺手修复：route_query 对 embedding=None 的健壮性（P2 后遗漏路径，plan_fact 触发）；test 全局主键撞车（kb-maint-tN 与 test_ontology_search p2-tN 同 id——suffix 改 pcN）

**验证**：155 tests passed（141 → +14）+ import-linter + OpenAPI 基线同步（plan-debug 端点）+ ruff/pyright 零新增；Plan 层机制层**策略命中率 100%**（test_planning_eval，≥95% 门槛）；dev 真模型（qwen2.5:1.5b + bge-m3 真检索）**select_plan 映射命中 111/111=100%**、执行分布 plan_fact 79/plan_relation 30/plan_aggregation 2、非法 trace 0、延迟全在预算内（fact p95=222ms<800 / relation 211ms<500 / agg 8ms<600）

**下一步（沿用优先级表）**：
1. **Phase D**：D1 `resolve_with_query()` 落地 + **capability query 执行器**（plan_aggregation 从候选解析升级为真实聚合——D2 边界解除）+ chat 接入 answer；D3 角色层 Evidence 组装（tech-debt #10）
2. **P3 rerank 真模型验证**——待 rerank 环境（升级 Ollama + 拉 bge-reranker + `EARP_RERANK_PROVIDER=ollama`，零代码）
3. **tech-debt 治理**：#12 TBox 审批流、#11 profile 过期管理、#9 角色域权限、#7 business_capabilities 复合主键、#8 indexing_technique
4. **M3 中台 importer + Enrichment**（PRD-2026-030）；**B6 评估集管理页**
5. 8000 端口残留 API 进程（PID 97205/72523）可 kill

---

### 会话续接（2026-08-16）— Phase D（能力闭环 D1 + 角色层 D3）已实施

> 任务书：`tasks/query-understanding-phase-d-task-breakdown.md`（9 Task；D1/D2/D3 方案 A 已确认）
> 设计：`arch/design/query-understanding-query-plan-design-v0.3.md`（§6.5/§8.2/§9.2/§16 Phase D）

**会话主线**：解除 Phase C 的 D2 边界（plan_aggregation 从「候选解析+回落」升级为**真实聚合**）+ chat 软路由路径接入 planner + 角色层 Evidence 组装（tech-debt #10 清偿）。

**关键产出（后端）**：
- `ontology/search.py::resolve_with_query()`（§6.5 新签名）：接收 StructuredQuery，直接消费 entities.semantic_type（非重新 tokenize），返回带 **matched_entity_ids**（v0.2 缺陷闭合）；resolve_with_entities 保留（/plan M2 收窄路径）
- `ontology/capability_query.py`（新建）：内置 ontology 事实聚合执行器——COUNT + group_by + 关系计数（facts join）+ 角色 data_domain_access 权限过滤（fail-closed）；SUM/AVG/MAX/MIN 无数值属性支撑返回 None（调用方回落，不假造）；**connector 保持无 DB**（执行器在 ontology 域直连 DB）
- `plan_aggregation` 升级（D1c）：resolve_with_query → 执行器 → Evidence(channel=capability) + trace executed=true；「capability 通道未就绪」标注移除（D2 边界解除）；无候选/执行失败仍显式回落 plan_fact（D5）
- **chat 接入 answer**（D1d）：chat_service._retrieve 软路由路径 → execute_plan（理解→select_plan→策略→PlanResult→chunks/citations）；kb_scope 限定路径保持 search_chunks；import-linter 加 3 条 ignore（conversation→ontology.planning/understanding/capability_query，P2 先例）；LLM 升级仅 settings 完整时触发（测试环境跳过）
- **角色层**（D3）：Evidence 加 `role` 字段 + `_role_for`（§8.2 通道角色表）+ `apply_role_layer`（§9.2 冲突消解：同 (channel, source_ref) 保留 confidence 高者其余 conflict=true + primary 优先排序）；三策略 evidence 组装后过角色层

**测试与验证**：`test_capability_query.py`（9 用例：resolve_with_query matched_entity_ids / COUNT + 权限 / 关系计数 / fail-closed / group_by / 角色层纯函数）+ test_planning 更新（plan_aggregation 执行语义）+ test_chat 回归（软路由走 planner）；**164 tests passed**（155 → +9）+ import-linter（3 条新 ignore 生效）+ OpenAPI 无变化 + ruff/pyright 零新增；dev 真模型 verify_planning：**select_plan 映射 111/111=100%**、执行分布 plan_fact 76 / plan_relation 32 / plan_aggregation **3（真实聚合，capability evidence 3）**、fallbacks 不再含「通道未就绪」、延迟全在预算内、非法 trace 0

**顺手修复**：test_chat `_purge` 动态清理同 DD KB（跨租户语义 id 冲突，debt #7 模式）；chat_service route_query unused import

**下一步（沿用优先级表）**：
1. **P3 rerank 真模型验证**——待 rerank 环境（升级 Ollama + 拉 bge-reranker + `EARP_RERANK_PROVIDER=ollama`，零代码）
2. **tech-debt 治理**：#12 TBox 审批流、#11 profile 过期管理（写时失效/读时 freshness）、#9 角色域权限、#7 business_capabilities 复合主键、#8 indexing_technique
3. **M3 中台 importer + Enrichment**（PRD-2026-030）；**B6 评估集管理页**（routing_eval 落库 + 跑分可视化）
4. **QU 二期**：chat 发布评审+可见范围（应用中心使用界面）、Phase F（通用 DAG/低置信度自适应规划）评估
5. 8000 端口残留 API 进程（PID 97205/72523）可 kill

---

### 会话续接（2026-08-17）— tech-debt #11 profile 过期管理已清偿

> 任务书：`tasks/techdebt-11-profile-staleness.md`（5 Task；D1-D4 方案 A 已确认）
> 影响：QU v0.3 recall 层 profile lane 依赖——之前事实变更后 profile 一直给旧事实

**关键产出**：
- **migration 0017**：facts 加 `updated_at`（freshness 第三时间源，覆盖存量 revoke——facts 原无 updated_at，revoke 是 status 软删 created_at 不变）
- **写时失效（D1）**：abox_service 加 `_log_timeline`（entity.created/updated + fact.added/revoked 写 entity_timeline——recent_events 首次生效）+ `_invalidate_profiles`（已有 profile 的实体重编译；`_profile_exists` 轻量检查避免 freshness 递归编译）；add_fact/revoke_fact/upsert_entity 接入（revoke 先查 source + updated_at 更新）
- **读时 freshness（D2）**：get_entity_profile 集中校验——last_change = GREATEST(timeline MAX, facts.updated_at MAX, entities.updated_at) vs compiled_at，过期即重编译；knowledge_search 的 profile lane 复用该函数自动获得校验（检索代码零改动）
- **scheduler enrichment（D3）**：scheduler 进程 idle → 心跳 + 每 EARP_ENRICHMENT_INTERVAL_SECONDS（默认 3600s）扫描所有租户 stale profile（`find_stale_profiles`：无 profile 或 compiled_at < last_change）批量重编译（规则聚合，LLM summary 留 M2）
- 测试：`test_profile_staleness.py`（8 用例：add/revoke/merge 写时失效、绕过钩子存量变更读时重编译、timeline 事件、find_stale_profiles、scheduler enrichment 冒烟）

**验证**：172 tests passed（164 → +8）+ import-linter + ruff/pyright 零新增（pyright 65，比基线 67 少 2——compile_profile r 断言修复顺带消了 2 个既有错误）；scheduler 本地实测 enrichment 38 profiles 重编译；顺手修复：scheduler.py 重写时丢失 `if __name__ == "__main__"` 块（-m 方式不调 main，test_entrypoints 抓到）

**下一步（沿用优先级表）**：
1. **tech-debt #12 TBox 审批流**（draft→approved + 审计 + 停用恢复）——知识资产方向治理最重的下一项
2. **B6 评估集管理页**（三套评估落库 + 跑分可视化）；**#9 角色域权限**；**#7 capability 复合主键**
3. **P3 rerank 真模型验证**（待 Ollama 升级）；**M3 中台 importer + Enrichment**
4. **QU 二期**：chat 发布评审+可见范围、Phase F 评估

---

### 会话续接（2026-08-17）— tech-debt #12 TBox 审批流已清偿 + 会话收尾

> 任务书：`tasks/techdebt-12-tbox-approval.md`（6 Task；D1-D5 方案 A 已确认）

**关键产出**：
- **migration 0018**：tbox_changes 变更请求表（change_type/action/target_id/payload/status/请求人/审批人/原因 + RLS 三件套 + 显式 GRANT earp_app）
- tbox_service：submit_change（create 预检冲突，deprecated 提示走恢复）/ list_changes / approve_change（apply 真实变更→applied；提交者不能审自己 403）/ reject_change（原因）/ reactivate_entity_type|relation_type（**恢复路径**闭环）
- routes：POST/GET /v1/ontology/tbox/changes + approve/reject + 审计 earp.tbox.change.submitted/approved/rejected
- 前端 tbox.html：新增/停用/恢复全部改为**提交变更请求** + 「待审批」区（批准/拒绝+原因）始终显示（无 pending 空态提示）+ 恢复按钮
- 测试：test_tbox_approval 9 用例 + 前端冒烟 test-tbox-approval-smoke.cjs（8 场景）

**验证**：181 tests passed（#11 后 172 → +9）+ import-linter + OpenAPI 基线（+155 行）+ ruff/pyright 零新增

**顺手修复（FDE 反馈驱动）**：
1. 右上角账号显示：nav.js renderMeta 原硬编码 `tenant-demo · Admin` 不读登录态 → login 存 earp_tenant_id/user_id/role_id + renderMeta 读登录态（JWT 解码兜底），链接改「切换/登录」
2. tbox 待审批区：①无 pending 时 display:none 隐藏（改始终显示 + 空态提示）；②**init 缺 loadPending 调用**（页面加载后待审批区永远「加载中…」，需手动点刷新——python 替换未匹配实际格式静默漏掉）
3. dev 环境加 u2 审批员（tenant-demo，单用户无法审批自己提交的请求——任务书风险 #3 实证）

**遗留提醒**：
1. **P3 rerank 真模型验证**：本地 Ollama 0.32.6 无 /api/rerank（404）——升级 + `ollama pull bge-reranker-v2-m3` + `EARP_RERANK_PROVIDER=ollama` 即生效（零代码）
2. **审批人角色门禁未接入**（一期=任意非提交者）：roles.permissions 无 tbox 权限概念，随 #9 角色权限体系统一接入
3. dev DB 新增 u2（tenant-demo）；8000 端口 API 进程带 EARP_OLLAMA_BASE_URL=127.0.0.1:11434 运行中
4. 评估体系三套（routing/understanding/planning）仍是 markdown fixture + 脚本——B6 落库候选

**下一步（沿用优先级表，下会话续接）**：
1. **B6 评估集管理页**（三套评估落库 + admin 跑分可视化）——评估从「脚本验证」变「平台能力」
2. **tech-debt #9 角色域权限**（roles 页开放配置 + Admin 全权限通用机制；审批人角色门禁随此接入）
3. **tech-debt #7 business_capabilities 复合主键**（migration + 存量清理）
4. **P3 rerank 真模型验证**（待 Ollama 升级，零代码）；**M3 中台 importer + Enrichment**（PRD-2026-030）
5. **QU 二期**：chat 发布评审+可见范围（应用中心使用界面）、对话日志 UI（P7）、Phase F（通用 DAG）评估

**QU 链路当前完整闭环**：理解（QU 规则+LLM 升级）→ 规划（select_plan 3 策略 + Execution Trace）→ 检索（三层 RRF + 软路由）→ 执行（capability 聚合）→ 角色层 Evidence → Answer（chat）；Plan 层 gating 100% 通过

---

### 会话续接（2026-08-17）— B6 评估集管理已实施（三套评估落库 + 跑分可视化）

> 任务书：`tasks/b6-eval-management-task-breakdown.md`（8 Task；D1-D7 决策已对齐）
> 依据：`arch/design/2026-08-09-enterprise-retrieval-design.md` §7/§8 ⑥「评估集落库 + 验收」

**会话主线**：三套评估（routing 5 / understanding 111 / planning 111）从 markdown fixture 落库为平台能力——评估集管理（按租户惰性种子 + 用例 CRUD）+ 跑分引擎（rules 规则层 / llm 真 LLM 两模式，后台任务，按 §17/设计 §7 门槛判定 gates）+ admin 可视化页面。

**关键产出（后端）**：
- **migration 0019**：eval_sets / eval_cases / eval_runs / eval_run_cases 四表（tenant-scoped + RLS 三件套 + 显式 GRANT earp_app；eval_run_cases 补 tenant_id 列——RLS 策略需要）
- `ontology/eval_seed.py`（由 `scripts/gen_eval_seed.py` 从 fixtures 生成，提交入库；fixtures 保持 CI 真源）——内置三套种子，`ensure_eval_sets` 按租户惰性初始化（tbox 先例，幂等）
- `ontology/eval_service.py`：评估集 CRUD（create/add/update/delete + kind 校验）+ 跑分引擎——`start_run`（running 并发 409）+ `run_eval_task`（后台执行，异常兜底 failed + error）
  - 三 kind 评分对齐 CI runner：routing（embed_query 异常降级 keyword lane + route_query top-5 期望 DD ∈ 候选；kb 报告项不 gate）/ understanding（understand 规则层 + llm 模式 upgrade_with_llm；intent 可靠子集计分 FALLBACK 回落即中、实体提及召回、relation 期望 ⊆ 结果、schema ∈ TBox）/ planning（rules=select_plan 纯映射 ≥95%，llm=execute_plan 端到端）
  - gates 判定（D5）：routing dd ≥0.90 / understanding intent ≥0.85 + entity ≥0.90 + relation ≥0.80 + schema=0 / planning strategy ≥0.95；overall = 全过
- `ontology/eval_routes.py`：`/v1/evaluations` 7 端点（sets/cases/runs + 跑分触发后台 asyncio 任务，EventBus 先例；同集合并发 409；空用例集显式 failed）

**关键产出（前端）**：`pages/eval-sets.html`（知识中心「探索验证」组新增「评估管理」）——集合卡片（kind 徽标/用例数/最新跑分率 + gates ✅❌ + 规则层/LLM 跑分按钮）+ 选中集合用例管理（增/启停/删，kind 相关表单）+ 跑分历史表 + 跑分明细（逐用例 passed/actual/失败原因，running 2s 轮询）

**FDE 指南**：`arch/guides/earp-fde-user-guide.md` v1.0 → v1.1（新增 §5 评估管理：三套内置评估集/跑分与判定/明细排查表/用例管理与 custom 集合/评估驱动迭代流程；FAQ +3 条、验证命令 +3 条、概念速览 +2 行）

**测试与验证**：
- `test_eval_service.py` 12 用例（种子幂等与 fixture 一致性/跨租户隔离/用例 CRUD/custom 集合/三 kind 跑分 gates/并发冲突/失败兜底/无实体租户如实低分回归）；`test_migrations` EXPECTED_TABLES 39→43 + downgrade -5；`test_rls` 38→42；前端冒烟 test-eval-sets-smoke.cjs 12 场景
- **193 tests passed**（181 → +12）+ import-linter + OpenAPI 基线（+330 行）+ ruff 零新增 + pyright 24=24 零新增（main.py I001 / understanding UP042 为既有）
- **dev 真库冒烟（bge-m3 + ollama）**：tenant-demo 惰性种子 3 套 → planning rules 111/111=100% ✅；verify-planning understanding rules **111/111 全门槛通过**（intent 1.0 / entity 1.0 / relation 1.0 / schema 0，与 CI 口径一致）；verify-planning routing 真语义 **dd_accuracy 0.8**（唯一 miss=hr_data 不存在，如实低分）；tenant-demo understanding 如实低分（entity 0.018/relation 0.045——评估实体不在 demo 租户）证明平台诚实报告

**顺手修复（验证中发现）**：
1. **eval_run_cases 缺 tenant_id**（RLS 策略报 UndefinedColumn）——4 表全部 tenant-scoped 保持一致
2. **_aggregate entity_recall bug**：`sum(len(entity_hits))` 把期望实体数当命中数（tenant-demo 跑分暴露 entity_recall 虚高 1.0）——改数命中的 True；补回归测试（无实体租户 → 如实 0.018 含 ctx 指代消解合法命中）
3. **start_run 前缺惰性种子**：直接 POST /runs 对未访问租户 404——路由加 `_ensure`（与 /sets 一致）
4. JSONB 参数统一 json.dumps（text() 查询无法适配 dict，对齐 tbox_service 先例）

**下一步（沿用优先级表）**：
1. **tech-debt #9 角色域权限**（roles 页开放配置 + Admin 全权限；审批人角色门禁随此接入）
2. **tech-debt #7 business_capabilities 复合主键**（migration + 存量清理）
3. **P3 rerank 真模型验证**（待 Ollama 升级 + bge-reranker，零代码）；**M3 中台 importer + Enrichment**（PRD-2026-030）
4. **QU 二期**：chat 发布评审+可见范围、对话日志 UI（P7）、Phase F 评估；评估集扩展（llm 模式全量跑分、SSE 进度、跨租户模板共享）

**遗留提醒**：
1. 跑分后台任务为 in-process（asyncio.create_task）——多进程部署需 Procrastinate worker（记 tech-debt）
2. builtin 评估用例假设标准种子数据集（finance_data/equipment_data/hr_data + 标准实体）；自定义租户（如 tenant-demo）跑分如实低分——admin 按自有数据加 custom 用例
3. 8000 端口 API 进程（--reload）已热载新端点；dev DB 已到 0019

### 追加（2026-08-18）— FDE 反馈：文档元数据保存后无法二次打开（esc 作用域泄漏）

**现象**：修改某文件的元数据后，再点该文件的 🏷️ 元数据按钮无反应（弹窗打不开）。

**根因**：knowledge.html 中 `autoMetaHtml()`（全局函数）引用 `esc()`——但 `esc` 是 `editDocMetadata` **函数内部的局部 var**，词法作用域不可见。首次打开不触发：KB 无 metadata_schema 且文档 metadata 为空时 autoMetaHtml 全走「无值」分支（不调用 esc）；**保存后后端写入 updated_at → 二次打开 autoMetaHtml 渲染自动字段值 → ReferenceError: esc is not defined → editDocMetadata 中断 → 弹窗打不开**。

**修复**：`esc` 提升为全局函数（`function esc(s)` 移到 docMetaState 声明处，editDocMetadata 删局部定义；其它页面 esc 均为全局，仅 knowledge.html 泄漏）。

**验证**：`test-docmeta-smoke.cjs`（新建，11 断言：首开/保存/二次打开/有 schema 回填）；修复前 git stash 对比精确复现 ReferenceError，修复后 11/11 全过；全量前端冒烟绿。

### 追加（2026-08-18）— 跑分取消能力（FDE 反馈：llm 跑分卡死无法停止）

**现象**：理解层评估集 llm 模式跑分（111 例 × 真模型升级）从 08-17 15:02 挂到 08-18 仍 running——无取消机制，只能重启进程或改 DB。

**根因**：llm 模式每例低置信度触发 upgrade_with_llm（真 qwen 调用，json_complete 超时 120s）+ execute_plan 端到端，111 例 × 超时累积可挂数小时/卡死；后台任务无取消入口。

**落地**：
- **migration 0020**：eval_runs.status CHECK 加 `'cancelled'`（无新表）
- eval_service：`cancel_run`（running → cancelled + finished_at；已完成/已取消幂等返回当前态；不存在 → None）+ `_is_running` 检查——run_eval_task 每 case 前查 status != running 提前终止（不覆盖 cancelled，已执行结果保留）
- routes：`POST /v1/evaluations/runs/{run_id}/cancel`
- 前端：跑分历史 running 行「停止」按钮（确认后 POST cancel）+ cancelled 状态显示「已取消」
- 测试：test_eval_service +1（cancel 状态机：running→cancelled / 任务提前终止无 results / 幂等 / 已完成不破坏 / 404）→ 14 用例
- FDE 指南 §5.2 补「停止跑分」说明

**验证**：dev 真 API 停掉卡死的 evr-26782bdbdb9e → cancelled（15 条已执行结果保留，finished_at 写入）；13+1 tests + import-linter + OpenAPI 基线（+35）+ ruff/pyright 零新增；前端冒烟 17 项全绿（+停止按钮/已取消断言）

**遗留**：卡死根因（LLM 调用超时累积）未根治——llm 跑分建议限制用例数或先规则层；connector 超时与 llm 跑分取消粒度（按 case 而非按 LLM 调用中断）留后续（记 tech-debt）。

> **遗留任务书**：`tasks/b6-followup-techdebt.md`（T1 队列 worker / T2 LLM 超时根治 / T3 评估集治理 / T4 test_routing 假命中盲区）——本会话遗留已补记为可执行任务，下会话按序执行。

### 追加（2026-08-18）— 评估页大集合折叠/展开（FDE 反馈：理解层 111 条影响查看）

- **用例列表**：默认显示前 10 条 + 底部提示「共 N 条，已显示前 10 条」；标题栏「展开全部 (N) / 收起」按钮（>10 条才显示；切换集合自动重置折叠）
- **跑分明细**：默认前 20 条 + 提示 + 「展开全部 (N) / 收起」（每次打开明细重置；toggle 保留展开态 keepExpand）
- 测试：test-eval-sets-smoke.cjs +6 断言（明细折叠 20/22、用例折叠 10/12、展开按钮文案）→ 21 项全绿；纯前端零后端改动
- **FDE 指南 §5.4**：补「理解层期望字段说明」（intent 10 类 + FALLBACK 含义与计分规则表、实体/关系类型的 TBox 来源）
- **FDE 指南 §10（新附录）**：理解层实现原理技术参考——双引擎 + 六维拆解 + 规则层各维机制（关键词表/双向子串/动词词典+TBox 候选+方向校验/正则/聚合词）+ 置信度机械计算 + LLM 升级 + 完整链路示例 + 验收门槛（§9 指代消解归位、§10 附录置末）
- **FDE 指南 §5.1**：补「理解层 vs Plan 层评估怎么区分」说明（认识问题 vs 执行决策、判定口径差异、rules 100% 属正常、医生诊断类比）
- **FDE 指南 §11（新附录）**：Plan 层实现原理技术参考——3 种策略（plan_fact/plan_relation/plan_aggregation）+ 10 类 intent 映射表（§11.2）+ 两级回落 + 与评估关系（rules 100% 属正常的解释）
- **FDE 指南 §7.1**：补「判断理解 vs Plan 问题」分层排障方法论（先理解后 Plan 再下游、判定矩阵、两个实例、平台化评估定位）
- **FDE 反馈修复**：Plan 层评估集 rules 跑分明细原来只有 select_plan 映射（无执行结果，FDE 困惑）——rules 模式映射判定不变（gates/CI 口径），**同时执行策略函数并记录 trace/evidence/耗时**进 actual/detail（执行失败不拉低命中率，异常兜底）；dev 实测 111/111 带 trace；指南 §5.3 补「Plan 层跑分的执行结果」说明
- **前端明细可读化**：跑分明细「实际」列由 JSON 截断改为友好渲染——Plan 层展示 Execution Trace 步骤串（`DD_ROUTING → KB_ROUTING → VECTOR_SEARCH`）+ 📊 evidence 通道徽标（通道 + 条数），完整 JSON 悬停查看；冒烟 +2 断言

---

### 会话续接（2026-08-18）— T4/T2 顺手 + tech-debt #9 角色域权限已实施

> 任务书：`tasks/b6-followup-techdebt.md`（T4 ✅ / T2 ✅，T1/T3 待开工）
> 本会话从「B6 遗留技术债」续接：先确认真实基线（194 tests）→ 按建议序 T4 → T2 → #9。

**基线确认**：194 tests 全绿（裸跑 pytest 曾挂起——shell 无 `EARP_OLLAMA_BASE_URL` 走了默认远程 10.188.2.230 经 Clash 代理挂死；需带 `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434` + `EARP_OLLAMA_CHAT_MODEL=qwen2.5:1.5b` 运行，与 dev API 进程同 env）

**T4 test_routing 假命中盲区（顺手）**：`embed_chunks` 传 document_id（应传 create_chunks 返回的 chunk_ids）→ embedding 从未写入，NULL 向量靠 `ORDER BY <=>` 末位排序在候选少时仍「命中」= 假命中。修：传 cids + 新增回归断言（embedding IS NOT NULL + similarity 非 NULL，修复前必挂）

**T2 connector LLM 超时根治**：`json_complete` 默认 120s → **30s**（超时回落 None，schema 合规不破）；`plan`/`_call_ollama` 120s → 30s + timeout 透传（挂起抛 ConnectorError → 调用方回落规则规划器）；`chat_stream` 保持 300s（流式合理）。新增 `test_connector_timeout.py` 6 用例——**真实 TCP 滞留服务器**验证超时机制（httpx MockTransport 不经过网络层，handler 内 sleep 不受 timeout 约束，必须真 socket；teardown 不能 await server.wait_closed()——Py3.12 下等 keep-alive 连接回收挂死）。llm 跑分根因闭环：111 例 × 120s → 30s 调用级上限 + 按 case 取消检查既有

**#9 角色域权限（大块，完整交付）**：
- migration 0021 roles.is_admin（读侧通用机制——admin 跳过 data_domain_access 域过滤，新建 DD 自动可见；替代 seed 特判，registry.seed_demo_tenant 简化 + r1 加 tbox.approve）
- `policy/roles_service.py`（新）：roles CRUD（唯一性/scope 枚举/幽灵域 fail-closed 校验/最后一名 admin 保护）+ `role_domain_access` 共享域过滤 + `check_permission` 通用门禁
- 三处 data_domain_access 读取方合一（policy_service/capability_query/knowledge.routing，import-linter ignore 一条）；capability_query admin → None 不过滤（**教训：勿用「allowed==全量」推断 admin**——实体 data_domain_id 可指向非 active DD 行）
- **TBox 审批人角色门禁**：approve/reject 需 `tbox.approve` 权限或 admin（403）；`GET /tbox/changes` 每项附 can_approve（不泄露角色权限明细）
- 前端 `pages/roles.html`（新，治理中心 Roles 点亮）+ tbox.html 待审批区按 can_approve 隐藏按钮
- dev DB：r1 提升 is_admin + tbox.approve；保留 r-auditor（tbox.approve）作审批角色；存量租户需手动提升 admin（seed 只管新租户）

**验证**：211 passed（194 → +17：connector_timeout 6 / roles_service 8 / tbox +2 / capability_query +1）+ import-linter + OpenAPI 基线同步 + ruff/pyright 零新增；前端冒烟 8 个全绿（roles 12 断言 + tbox +1 + planned 断言更新）；dev 真 API 冒烟全链路（CRUD/409/最后 admin 保护/TBox 无权限 403 → admin 通过 → applied）

**下一步（沿用优先级表）**：
1. **T1 Procrastinate worker 接入**——✅ 已完成（2026-08-19，见下方追加补记）；跑分由独立 worker 进程消费 + 心跳 stale 恢复
2. **T3 评估集治理**（模板同步 / per-set 门槛 / SSE 进度）
3. **#7 business_capabilities 复合主键**；**P3 rerank 真模型验证**（待 Ollama 升级）；**M3 中台 importer**
4. **QU 二期**：chat 发布评审+可见范围、Phase F 评估

**遗留提醒**：
1. **测试运行需带 Ollama env**（见上「基线确认」）——否则默认远程 URL 经系统代理挂起（本次曾挂 3 次才定位）
2. roles 页无「成员归属」展示（users 无 role FK，JWT 直带 role_id）——多用户角色分配属 Org/IdP 范畴，不在本期
3. 8000 端口 API 进程（--reload）已热载新端点；dev DB 已到 0021

### 追加（2026-08-18）— #9 漏洞修复：search_chunks 域门禁（FDE 反馈：单域角色可召回其他部门）

**现象**：普通角色只授权一个部门（数据域），召回测试可召回其他部门数据。

**根因**：`search_chunks._build_conditions` 只按 `kb.accessible_roles`（大多为空 → 全放行）过滤，**不按角色 `data_domain_access` 过滤** → 三条泄露路径：① 无候选 DD 全租户 chunk 兜底（/knowledge/search + plan_fact）；② plan_relation graph 无事实 RAG 补证（无 scope）；③ **显式 data_domain_ids/knowledge_base_ids 可绕过**（请求体自传其他域，chat kb_scope 同源）。

**修复**：search_chunks 一律解析角色允许域（`_role_scope_domains` → policy.roles_service 共享实现，import-linter ignore 一条）并与检索范围交叠——admin 不过滤；角色缺失/空授权 fail-closed；NULL 域 KB 不在允许集（严格过滤）。双保险于 route_query 候选过滤。

**验证**：test_search_role_gate.py 4 用例（修复前 4 全挂/修复后全过）；test_rerank/test_knowledge_pipeline 补角色 seed（域门禁后无 roles 行 = fail-closed，r-any → rr-any/kbpipe-any 避免单列主键冲突）；**215 passed** + ruff/pyright 零新增；dev 真 API：单域角色搜「制度」只回 shebeiyunwei 域 KB、显式传 jihuacaiwu → 0 结果、admin 不受影响。

**顺手**：右上角用户信息补 role id（tenant · user · role，nav.js renderMeta + jwtMeta 兜底；nav 冒烟 +1 断言）。

**遗留观察（未修，随 #9 后续）**：`/ontology/entities/lookup`、`/ontology/entities`（M4 实体管理）端点不做角色域过滤——普通角色可枚举/查询任意域实体（实体层与 chunk 层门禁不对称）；knowledge_search 的 profile/graph lane 依赖调用方传候选 DD（plan 路径已过滤），独立端点未收敛。下个 FDE 反馈若涉及实体层可见性再统一接入（可复用 role_domain_access）。

### 追加（2026-08-18）— 泄露根因二：D4 兜底 KB 域门禁（FDE 反馈：路由调试仍见权限外 chunk + 页面卡死）

**现象**：单域角色（r3）在路由调试视图 3.2 KB 定位仍看到其他域 KB（运维规程/综合管理/计划财务）；且点几次后页面不动。

**根因二（route 层）**：`route_query` 全租户 KB 兜底（D4）只按 `accessible_roles` 过滤，不按角色 `data_domain_access`——top-N 向量候选全被权限滤掉时（单域角色查「制度」：关键词命中多域但全被滤 → candidate_dds=[]）兜底返回任意域 KB。**双伤**：① 调试视图一览越权 KB（泄露）；② 本域 KB（电站运行调度）被其他域 KB 挤掉 → `/knowledge/search` 0 结果（误伤授权角色）。

**修复**：兜底 KB 限定角色允许域（`_role_allowed_domain_ids` → policy.roles_service 共享实现；admin 不过滤；缺失/空授权 fail-closed）——与 search_chunks 域门禁（上一修复）构成 route + chunk 双保险。

**页面卡死排查**：后端 route_debug 稳定 0.3s（含三层检索路径）、前端渲染无异常（DOM stub 复现）——非确定性 bug；大概率是 embedding 慢响应（30s 上限）时「路由中...」挂起 + 连点竞态叠加的感知卡死。加固：doRouteDebug 加请求序号防护（对齐 doSearch，丢弃过期响应）+ onto 防御。

**验证**：test_search_role_gate +1（构造 top-3 候选全被滤掉场景，修复前挂/后过；admin 对照可见其他域）；**216 passed** + ruff/pyright 零新增；dev 真 API：r3 查「制度」兜底只回本域 KB，/knowledge/search 0 结果 → 10 条本域结果。

### 追加（2026-08-18）— 管理端门禁：角色/数据域/模型配置变更仅 Admin（FDE 反馈：r3 可直接改权限）

**现象**：普通角色（r3）登录后可直接在 roles 页面修改权限（含自提 admin）——`/api/roles*` 及 `/api/data-domains`、`/api/model-configs` 变更端点完全无门禁（任何登录角色可调）。

**修复**：`roles_service.is_admin_role()` 共享检查 → `/api/roles*`（router 级依赖）+ `/api/data-domains` POST/DELETE/PATCH + `/api/model-configs` POST/PUT/DELETE/test + `/api/system-model-settings` PUT 全部 403 封堵；只读端点（列表/下拉）保持开放（不泄露 credentials）。前端 roles.html 403 → 「仅 Admin 角色可访问」门禁提示。

**验证**：test_admin_gate.py 3 用例（角色/数据域/模型配置：非 admin 全 403、admin 正常、只读开放）；roles 冒烟 +1；**219 passed** + ruff/pyright 零新增（main.py I001 既有）+ OpenAPI 无变化；dev 真 API r3 403 / r1 200。

**同类遗留（未修）**：`/v1/ontology` 写端点（实体导入/实体管理/文档上传等）仍无管理门禁——普通角色可上传文档/导入实体到其权限域（读侧已由域门禁限制，写侧未收敛）；审计 earp.* 事件目前无权限门禁（应仅 admin 可查）。随后续治理统一接入 is_admin 门禁。

### 追加（2026-08-18）— 实体层与路由解耦：profile/graph 按角色允许域生效（FDE：召回测试 profile/graph 不生效）

**现象**：召回测试中 profile/graph 层经常不生效（实体明明存在且有 profile）。

**根因**：L1/L2 实体层按「路由候选 DD」限定域——实体名不在 DD 描述中，软路由对齐性差（如「张建国」路由候选 [anquanhuanbao, sales_data, jishuguanli] 不含其实体域 shengchangyunxing）→ 实体查找被域过滤掉 → profile/graph 静默为空。另有：D4 兜底路径（cand_dds 空）完全不触发三层。

**修复**：① `_knowledge_layers` L1/L2 实体层改按**角色允许域**限定（`_role_scope_domains` 共享实现；admin 不限域；角色缺失/无授权 fail-closed）——与文档层路由解耦，权限不变；② `/knowledge/search` 与 plan_fact 的 D4 兜底改走三层（此前纯 chunk → 实体类查询完全不触发）；③ route_debug ontology_layers 兜底照常触发（fallback_mode 标注）。

**验证**：test_ontology_search +1（实体层脱离路由候选生效 + 跨域实体 fail-closed，修复前挂/后过）；fixture 补 data_domain_id + 角色 seed（实体层域门禁后 NULL 域实体不可见——既有 fixture 无域实体依赖「不设 data_domain_ids 即不滤」的旧语义）；**220 passed** + ruff/pyright 零新增；dev 真 API：r1/r3 查「张建国」profile+graph 均生效（r3 兜底路径亦然）、「高温报警」（无该实体）仍 chunk-only 如实。

**遗留观察**：graph lane 多跳可达实体未按域过滤（matched 实体已域限，但 graph_query 目标实体可跨域——如设备域实体关系的供应商在销售域）；chat 软路由路径已随 plan_fact 修复。后续可对 graph 目标补角色域过滤（与实体层同源）。

### 追加（2026-08-19）— T1 跑分接入 Procrastinate worker + stale 恢复（任务书定稿交付）

**任务书**：`tasks/t1-eval-worker-task-breakdown.md`（D1-D4 决策：队列复用/心跳 stale 判定/async 桥接待验证/测试策略，执行序 1→5）。

**D1b 先行验证（Task 1）**：procrastinate 3.9 worker 为 async 模式，spike S1/S3 已用 `async def` 任务验证（100 任务/2 worker 全过 + async SQLAlchemy 会话共存）——**原生支持 async task，无需 asyncio.run 桥接**。

**实现（按执行序）**：
1. **任务注册**：`ontology/eval_jobs.py`（新）——`register(queue)` 注册 `eval.run`，payload `{tenant_id, run_id, role_id}`；job 从 worker 侧 `Settings()` 构造 engine（env 一致），调 `run_eval_task` + 每 case 心跳回调；`run_eval_task` 加可选 `heartbeat` 参数（既有服务直调零改动）
2. **API 入队**：main.py lifespan 建 `ProcrastinateTaskQueue`（open + assert_schema，失败容忍——/ready 503 语义保持，AC-01 不动）→ `app.state.queue`；`start_eval_run` 删 `asyncio.create_task` 改 `enqueue`，返回体不变（前端零改动）
3. **心跳 + stale**：migration 0022 `eval_runs.heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now()` + 索引；`config.eval_run_ttl=3600`（`EARP_EVAL_RUN_TTL`）；`eval_service.recover_stale_runs` 逐租户扫描（tenants 无 RLS，scheduler 先例）`running AND heartbeat_at < now()-TTL` → failed + `summary.error=interrupted`；worker 启动时注册任务 + 恢复（恢复失败不阻塞启动）

**验证**：新增 `tests/test_eval_worker.py` 3 用例（真 worker 消费队列 → completed / stale 恢复只标僵尸不误杀新鲜/cancelled/completed / heartbeat 每 case 报到刷新）——**223 passed**（220 基线 + 3）+ import-linter + OpenAPI 无变化 + ruff/pyright 零新增；既有 13 个 eval 服务测试直调模式零改动全绿。

**dev 真 API 实测**（rules + llm 两种模式经 worker）：
- rules：routing（5 例）+ understanding（111 例）经 worker completed，指标如实
- llm：understanding llm 走 deepseek provider（每 case ~10s，111 例 ≈ 30min——正是心跳方案要防误杀的合法时长）；2 用例 custom 集 llm run completed（llm_upgraded=2，gates 如实）；cancel 端点经队列路径 running → cancelled、job 提前终止
- **API 重启不丢任务**：触发 understanding rules → 立即 kill API 进程 → worker 独立消费 completed/111 → 重启 API 正常
- **僵尸恢复**：SIGKILL worker（llm 跑分中，2 case done）→ 手动把心跳改旧 2h（模拟进程死久）→ 重启 worker 启动日志 `recover_stale_runs: 1 stale eval runs marked failed (interrupted)` → failed + summary.error=interrupted；已 completed run 不受影响
- 前端零改动（返回体 running+run_id 不变，轮询照常）

**遗留**：① 后续可把 stale 扫描落到 scheduler 定期（本次仅 worker 启动时，任务书已记）；② eval.run job 默认 max_attempts=3（retry=3 → 4 次执行）——失败重试对已 failed 的 run 是无害 no-op（_is_running 提前返回）；③ graph lane 多跳可达实体域过滤（上段遗留）未动。

**FDE 指南**：§5.2 补「跑分由独立 worker 进程执行」+ 排障表「跑分一直 ⏳ running → worker 未启动」。

### 追加（2026-08-19）— T3 评估集治理：模板同步 / per-set 门槛 / 跑分进度（任务书定稿交付）

**任务书**：`tasks/t3-eval-governance-task-breakdown.md`（D4 模板同步 / D6 per-set 门槛 / D5 进度，执行序 1 → (2,3) → 4 → 5）。T1 完成后开工（migration 0023，进度复用心跳/轮询）。

**实现**：
1. **migration 0023**：`eval_sets.seed_version INT`（custom NULL）+ `eval_cases.source VARCHAR(16) NOT NULL DEFAULT 'builtin'` + **存量回填**（按所属集合 source 回填——builtin 集合→builtin，custom→custom）；`eval_seed.py` 生成脚本加 `SEED_VERSION=1` + `GATED_METRICS`（routing 仅 dd_accuracy 参与 gate——kb_accuracy 是报告项，**保持既有行为不回归**；understanding/planning 与 THRESHOLDS 对齐）；`ensure_eval_sets` 写 seed_version + 种子用例 source='builtin'；`add_eval_case` 写 'custom'
2. **per-set 门槛**：`update_eval_set`（服务端**合并默认** `{**THRESHOLDS[kind], **override}` 全量存储——防部分覆盖缺指标；校验指标名 ∈ GATED_METRICS + 数值 0-1 + schema_violations 非负整数）；`PUT /sets/{id}`（admin 门禁，端点级依赖——评估列表对普通角色保持开放）
3. **模板同步/导出导入**：`sync_builtin_set`（仅 builtin；DELETE source='builtin' 重插种子 → custom 保留；seed_version 更新）；`export_eval_set`（name/kind/thresholds/cases，无敏感字段）/ `import_eval_set`（目标租户建 custom，id 自动生成，expected 校验）；`POST /sets/{id}/sync`、`GET /sets/{id}/export`、`POST /sets/import`（均 admin）
4. **跑分进度**：`get_run` 响应加 `progress {completed, total, percent}`（eval_run_cases 计数 / 启用用例数；取消后冻结不回落）；前端 running 行进度条（pollRun 原地更新 DOM，不整表重建）+ 历史 running 行自动轮询
5. **前端**：集合卡「↻ 同步内置模板」（builtin 且 seed_version < 当前时显示）/「导出」；「导入评估集（JSON）」虚线卡 + file input；同步确认弹窗（破坏性操作提示）

**验证**：`tests/test_eval_governance.py` 8 用例（合并默认/未知指标/数值范围/schema_violations 整数/同步覆盖 builtin 保留 custom + 幂等/非 builtin 拒绝/导出导入往返/import 校验/running 进度 0-N→100/取消冻结）——**231 passed**（223 + 8）+ import-linter + OpenAPI 基线同步（+173 行：4 新端点 + EvalSetUpdate/EvalSetImport schema）+ ruff/pyright 零新增；前端冒烟 **30 断言全绿**（+6：同步按钮条件/导出/导入/进度条）

**dev 真 API 实测**：① 老租户（seed_version NULL）routing 集：加 custom 用例 → `POST /sync` → seed_version=1、5 内置重建 + custom 保留（source 区分正确）；② `PUT` 部分覆盖 `{intent_accuracy:0.5}` → 响应合并默认全量（entity_recall 0.9/relation_accuracy 0.8/schema_violations 0 保留）；非法指标 400 明确报错；非 admin（r3）403；③ llm 2 用例集跑分中 `GET /runs/{id}` progress **1/2=50%** 中间态 → completed 2/2=100%；④ 导出 custom 集 JSON → 导入 → 新 custom 集合（2 用例）往返一致

**遗留**：① SSE 流式进度未做（轮询进度条已满足 FDE 需求，任务书标可选）；② 同步按钮的「版本落后」判断依赖前端 SEED_VERSION 常量（模板升级发版时同步）；③ 存量「builtin 集合里手工加的用例」被回填为 builtin、同步时会被覆盖（任务书风险 2 已注明，同步确认弹窗提示）。

**FDE 指南**：§5 新增 5.1b（模板同步/门槛编辑/导出导入说明）+ 5.2/5.3 进度条说明。

### 会话续接（2026-08-19）— Chatflow F0: workflow 真实化（声明式 JSON → 编译 → 执行闭环）

**任务书**：`tasks/chatflow-f0-workflow-task-breakdown.md`（D1-D8 决策：graph-shaped schema 对齐 Dify/ReactFlow、条件结构化表达式、gate 门控/join 交集、plan 参数接线、skip 语义、校验项、失败语义，执行序 1→5）。基线 231 tests 全绿。

**现状核实**：`workflow_dsl` 死代码坐实（零 import/零测试，docstring 声称的「MultiStepExecutor skip 逻辑」不存在）；`MultiStepExecutor` 真实可用但只吃手工拼的 Step 列表；`resume_from_checkpoint_id` 无调用方。

**实现（按执行序）**：
1. **workflow_dsl 重写**（`orchestrator/workflow_dsl.py`，删树形 dataclass）：Pydantic 模型 `WorkflowGraph{nodes,edges}`/`WorkflowNode`/`WorkflowEdge{source,target,sourceHandle}`/`ConditionExpr{left,op,right}`（op 白名单 `== != > >= < <= contains exists`）；`validate_workflow -> list[str]`（id 唯一/类型白名单 start·end·step·condition/恰一 start·end/边引用/自环/重复边/condition 恰 2 出边 handle true·false 各一/非 condition 出边 ≤1（F0 无并行）/step 必有 capability_call/left 路径形 `<node>.output.<path>`/Kahn 判环/start 可达 + 可达 end）；`compile_workflow -> CompiledWorkflow`（拓扑序 + **gate 门控前向计算**：join 多入边处取各入边上下文交集——series-parallel 下即嵌套分支上下文，汇合点交集为空无条件执行）；`evaluate_condition` 纯函数（数值 coerce/字符串数字友好/contains/exists/引用缺失抛 `ConditionEvaluationError`）
2. **MultiStepExecutor 接线**（`multi_step.py` + `types.py`）：`execute(..., plan: CompiledWorkflow | None = None)`——plan=None 走 legacy 路径逐字节不变；`_execute_plan` 循环 sequence：CondExec 被门控不求值、命中才求值（错误→failed 结果 + FAILED，不回滚——控制流非业务步）；StepExec 未命中分支→`skipped` 结果 + 轻量 checkpoint（`StepResult.status` Literal 扩 `"skipped"`），逐步 `dataclasses.replace(ctx, step=item.step)`（PolicyLayer 权限查当前步）；checkpoint/Saga/retry/interrupt 全镜像 legacy；resume 从 step_results blob（JSON dict，legacy repr 经 ast.literal_eval 兼容）重建 pool + prior_count 游标——决策确定性重放
3. **单测**：`tests/test_workflow_f0.py` 33 用例——编译层（顺序/分支两分支都编译/gate 断言/嵌套/join 汇合点不门控/空图）+ 校验层（环/未知类型/缺 start·end/悬空边/condition 出边数/坏 op/无 capability_call/fan-out/不可达/重复 id/自环/left 路径形）+ 求值层（各 op/数值 coerce/contains/exists/缺失抛错）+ 执行层（顺序/分支命中 skip 另一分支副作用断言/分支未命中/嵌套/未命中分支内条件不求值/空图/条件求值错误 failed/plan 路径 Saga 补偿回滚）
4. **质量门**：264 passed（231 基线 + 33）+ import-linter + OpenAPI 无变化（F0 零端点）+ ruff/pyright 零新增（pyright 24==24、ruff 17==17 均与 HEAD 同数）

**dev 真 DB 冒烟**（5433 earp_app 角色 + RLS）：设备维修单示例图（顺序 + 条件分支）compile → 3 steps + 1 condition；执行 status=completed，命中分支 `fault` 执行、未命中分支 `ok` **skipped**（output null 无副作用）；checkpoint 落库核实：`plan:q1/fault`（执行）+ `plan:ok`（status=skipped idx=3）各自独立 checkpoint。

**遗留**：① 条件失败不回滚（控制流非业务步，若需业务一致性 F2+ 决策）；② checkpoint resume 的条件决策重放无专属测试（pool 重建路径已实现，靠 blob 兼容解析；对话节点接入时补）；③ F0 无端点/无 flow_schema 持久化（F1 做）；④ Parallel 树形 dataclass 随重写移除（F0 一期无并行，Phase F 开放）。

**FDE 指南**：无需变更（F0 无用户可见功能，F1 flow 模式才涉及）。

### 会话续接（2026-08-19）— Chatflow F1: flow_schema 落库 + orchestration 模式（migration 0024）

**任务书**：`tasks/chatflow-f1-flow-schema-task-breakdown.md`（D1-D7 决策：migration 0024 / 节点类型白名单参数化 / 扩展类型只做结构校验 / orchestration 语义与发布门禁 / 端点 / import-linter / 测试策略，执行序 1→5）。基线 264 tests 全绿。

**实现（按执行序）**：
1. **workflow_dsl 参数化**（F0 校验复用）：`validate_workflow(graph, *, allowed_types=NODE_TYPES)` 默认行为不变；新增 `FLOW_NODE_TYPES = NODE_TYPES ∪ {capability(step 声明别名), llm, knowledge, qu, chat_history, human_approval, tool, mcp}`（设计稿 §3 全节点类型）+ `validate_flow_schema(schema)` 包装；fan-out ≤1 检查推广到所有非 condition 节点（图级约束）；扩展类型只做通用结构校验（节点级 data 校验 F2+ 适配层负责）
2. **migration 0024**：`chat_apps.orchestration VARCHAR(16) NOT NULL DEFAULT 'auto' CHECK IN ('auto','flow')` + `flow_schema JSONB`；存量行 auto+NULL 后端兼容；列级改动 RLS 不动
3. **service + 端点**（chat_app_service.py + main.py）：`_check_flow_fields`（orchestration 白名单；flow 模式 schema 必填 + validate_flow_schema；auto 模式传 schema 也校验——坏图存不进去、切回 flow 不重画）；`_UPDATABLE`/create/update/_row_to_dict/list 加两字段；**publish 门禁**：flow 模式强制重校验（§9 开放问题 1 落地：flow 变更纳入发布评审）；ChatAppCreate/ChatAppUpdate 加字段（默认 auto 前端零改动）；import-linter 例外 `conversation.chat_app_service -> orchestrator.workflow_dsl`（图校验单一实现）
4. **单测**：`tests/test_chat_app_flow.py` 17 用例——create（默认 auto/flow 合法/扩展类型图/缺 schema/环/orchestration 非法/auto 坏图）+ update（切 flow 用已有 schema/坏图不落库/auto→flow→auto 保留/published 回 draft）+ publish 门禁（合法过/手工改坏图拒/auto 不受门禁）+ 路由级 422 透传（含 JWT）
5. **质量门**：281 passed（264 + 17）+ import-linter + ruff/pyright 零新增（pyright 24==24；ruff 14<17——format 顺手修了 3 个存量，main.py 存量 I001 未动）+ OpenAPI 基线 +21 行（仅 ChatApp schema 两字段）

**dev 真 API 实测**（8000 --reload + dev DB 到 0024）：① 建 flow app（顺序图 3 节点）→ 201 orchestration=flow；② 自环坏图 → 422 `invalid flow_schema: self-loop; F0 无并行…`（错误信息明确）；③ publish → 200 published（门禁过）；④ GET 往返 flow_schema 内容等价（JSONB 键序无关，dict 值比较成立）。

**遗留**：① F1 只存不跑——扩展类型节点（qu/llm/human_approval…）无执行（F2 适配层报「节点类型未实现」）；② flow 变更的「重新测试发布」提示未做（前端 F5a 时补）；③ publish 门禁只校验结构，不校验语义（如 condition 引用的 node 存在性——运行时求值兜底）。

**FDE 指南**：无需变更（flow 模式无用户可见功能，F2 执行端点/F5a 页面才涉及）。

### 会话续接（2026-08-20）— Chatflow F2: flow 执行器（DAG JSON → 编译 → 对话节点适配层最小集）

**任务书**：`tasks/chatflow-f2-flow-executor-task-breakdown.md`（D1-D8 决策：复用 F0 链路注入 llm、LLM 非流式 complete、compile_flow_schema 节点映射、变量引用模板、chat 端点 flow 分支、knowledge 适配器、测试策略、import-linter，执行序 1→5）。基线 281 tests 全绿。

**实现（按执行序）**：
1. **compile_flow_schema + resolve_templates**（workflow_dsl）：抽共享 `_compile_graph`（拓扑+gate+线性序，F0/F2 共用）；对话节点映射——llm→`llm.prompt`/knowledge→`knowledge.search`/chat_history→`chat.history` 适配器 Step（input 透传），condition 复用 CondExec，**qu/human_approval/tool/mcp 编译报「未实现（F3+）」**（声明可存、执行明确报错）；`resolve_templates` 递归替换 `{{query}}`/`{{#node.output#}}`/`{{#node.output.path#}}`（缺失原样保留）；F0 compile_workflow 行为不变
2. **对话节点适配器**（connector）：`LLMConnector.complete` 非流式文本生成（ollama+openai 兼容，失败 None 不抛）；Connector 注入 engine/llm + `execute(capability_call, *, ctx)`（ctx 供 tenant/role/session）；llm.prompt（→`{"text"}`）/ knowledge.search（embed_query + search_chunks 三层检索 → `{"chunks","citations"}`）/ chat.history（复用 _recent_pairs → `{"messages"}`）；StepRunner/MultiStepExecutor 注入 llm；`_execute_plan` 加 flow_input + invoke 前模板替换
3. **端点**（main.py + chat_service.flow_chat）：chat_ep flow 分支——会话创建/续接（chat_apps 归属）+ user 消息先落 → compile_flow_schema（防御）→ resolve_llm_override + llm 注入 → MultiStepExecutor 图执行 → outputs → assistant 落库（最后 completed 节点 text）+ citations（knowledge 节点）→ 非流式 JSON `{execution_id, conversation_id, status, outputs, message_id, answer}`；auto 模式 SSE 零回归（端点 `response_model=None` 防 FastAPI Union 报错）
4. **单测**：`tests/test_flow_executor.py` 17 用例——编译映射/未实现类型/gate/模板替换（query/整体/路径/递归/缺失）/适配器（FakeLLM 断言参数、真 DB history 配对、monkeypatch knowledge）/flow_chat 端到端（{{query}} 替换进 prompt、消息落库、**condition 只走命中分支**——FakeLLM.calls 断言未命中分支零调用）
5. **质量门**：298 passed（281 + 17）+ import-linter + ruff/pyright 零新增（ruff 17==17、pyright 24==24，diff 仅存量行号）+ OpenAPI 基线仅 chat 端点描述 +1 行

**dev 真 API 实测**（8000 + 真实 Ollama qwen2.5:1.5b）：设备维修单 flow（chat_history → llm → condition → 分支 llm）——chat 200 completed，outputs = {h1, l1("CNC-01 温度正常。"), **ok("一切正常。")**}——condition contains "正常" 命中 true 分支、fault 未执行（无副作用）；answer=命中分支输出、message 落库。**flow 图第一次真实跑通（含 LLM + 条件分支）**

**遗留**：① LLM 节点非流式（token 级 SSE 透传 F4/F5a 与 Human Approval 一起）；② 节点级超时未做（complete 300s 全局）；③ flow 执行失败 422/500 语义可细化（F5a 前端对齐）；④ chat.history 适配器未做会话上下文指代消解（设计稿 F6 联动）；⑤ condition 求值错误回滚未做（F0 遗留延续）

**FDE 指南**：无需变更（flow 无前端入口，F5a 页面才涉及）。

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
| P3 | knowledge_search 叠加「角色层」（capability 主证据 + 答案/引用分层） | 🟡 arch/tech-debt.md #10（QU v0.3 Phase D3） |
| P2 | **test_routing 既有测试弱点**：embed_chunks 传 document_id 导致 embedding 实际未写入（检索靠 NULL 向量假命中）——P2 碰 test_routing 时顺手修 | 🟡 待修 |
| P2 | **ontology 设计 §7.2 示例用了未定义关系**（component→equipment 归属 / component→supplier 供应）——TBox 缺口文档侧，与 QU 设计开放问题 1 同源 | 🟡 待拍板 |
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
