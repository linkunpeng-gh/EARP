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
