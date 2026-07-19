# EARP 服务器端开发计划分析

**文档编号：DESIGN-SERVER-PLAN**
**版本：v1.4**
**日期：2026-07-18**
**定位：分析文档 — 盘点服务端现状、识别缺口、给出里程碑分解与决策建议。经确认后逐里程碑进入 Phase 0 PRD。**
**依赖：L1/architecture-v6.md, L1/deployment-architecture-v1.md (v1.1), L1/data-architecture-v1.md (v1.0), L1/sequence-diagrams-v1.md, L2 全部 11 域规范, arch/design/role-based-access-control-v1.md (v1.1), arch/design/tech-stack-analysis-v1.md (v1.0), arch/reference/server-side-tech-reference-v1.md (v1.0), arch/reference/opensource-comparison-findings-v1.md (v1.0)**

> **v1.1 变更：** 完成开源技术方案对齐（详见 arch/reference/server-side-tech-reference-v1.md）。ADR-007 获得 Dify v1.15 生产实践佐证；进程模型明确为"一镜像多进程"（api/worker/beat，M6 增 websocket）；新增决策项 D6 异步任务框架（建议 Celery+Beat）；M0 增补 checkpoints 表 DDL（LangGraph PostgresSaver 模型）与 worker/beat 脚手架；M1 审计明确为"引擎事件流消费者"模式。
> **v1.2 变更：** LangChain 代码级分析完成（arch/reference/langchain-earp-mapping.md + langgraph-earp-mapping v1.1）。M0 增补：tenacity 依赖、checkpoints 采用真实 3 表模型（含 blob 分离）、chunks 表 content_hash/source_updated_at 列；M4 增补 RecordManager 式增量索引与 text-splitters 依赖决策。
> **v1.3 变更（依据 opensource-comparison-findings 全量优化）：** ① M1 架构升级——Step Runner 一次定义三形态调用、Orchestrator 内置 Layer 拦截器链（graphon 模式）、最小 Checkpoint 落盘前移进 M1、Connector 调用带 tenacity 基础重试；② M2 改为"以 Layer 挂入 M1 拦截器链"（不侵入引擎）；③ M3 增补 LLMConnector 五挂点接口与 structured output Plan 约束；④ M5 增补 Durability 三档、handle_tool_error 三态、Temporal Retry/Saga/Heartbeat 细则；⑤ M7 增补 Plugin 五段安装流程与 ssrf_proxy 出口代理；⑥ 新增"里程碑 ↔ L2 规范升级映射表"（Gate A 检查表）；⑦ 风险表补开源结论时效性条目。
> **v1.4 变更（技术栈终选定稿，依据 tech-stack-analysis-v1.md）：** §5.2 改为技术栈终选全表；D6 修订为 procrastinate 首选（Celery 回退备选，M0 spike 定夺）；新增 D7（psycopg3 全线统一）、D8（Redis 7.2 命令面+Valkey 双验证；S3 API only，MinIO 可替换）、D9（uv/ruff/pyright/testcontainers/squawk）；M0 增加 procrastinate spike 与工具链落地；EventBus 接口明确"必须可背 RabbitMQ/Redis Streams 双实现"，M6 改为带数据决策。

---

# 一、结论摘要（TL;DR）

1. **服务端代码量为 0**。当前仓库全部代码资产是 5 个客户端/开发者 SDK 包（317 个测试函数），服务端（Runtime Service、Capability Registry、Policy Center 等 11 个业务组件）尚未开工。
2. **文档基线已足够启动**：L1 三视图（部署/数据/时序）+ 20 份 L2 规范（11 域）齐备，服务端的契约（API 形态、实体、错误码、事件、隔离规则）基本被规范锁定，不存在"边写边设计"的风险。
3. **最大缺口不是文档而是 4 项工程决策**：技术栈确认、单体 vs 微服务的落地形态、DDL/迁移基线、服务端 L3 设计（现有 L3 只覆盖 SDK）。
4. **推荐策略：模块化单体先行**（modular monolith），模块边界 = 部署架构中的服务边界，Phase 2 再按部署架构拆分。单人开发直接照搬 11 个微服务 + Istio + K8s 是不可承受的运维负担。
5. **建议按 8 个里程碑（M0-M7）垂直切片推进**，每个里程碑 1-3 个 PRD，走既有流水线 v2.0（Gate A/B/C）。M1 结束即获得可运行的"最小闭环"：RuntimeClient SDK 直接打真实服务端跑通 Session → Invoke → Audit。
6. **角色级访问控制（RBAC v1.1 设计）的剩余工作本质上就是服务端工作**——SDK 侧 role_id 已实现（client.py switch_role），规范侧已更新（Policy v1.1/Tenant v1.2/Capability v1.4/KB v1.0），剩下的 data_scope 过滤、discover 过滤、RAG 过滤、RLS、DDL 全部落在服务端，应并入服务端里程碑而非单独立项。

---

# 二、现状盘点

## 2.1 已有资产

| 层 | 资产 | 状态 |
|:---|:-----|:-----|
| L0 | design-philosophy.md（9 原则） | ✅ 稳定 |
| L1 | architecture-v6.md（11 层架构 + ADR-001~006 + 错误码体系 + Phase 1-4 演进） | ✅ 基线 |
| L1 | deployment-architecture-v1.md v1.1（K8s 拓扑、19 组件规格、通信矩阵、多租户部署） | ✅ |
| L1 | data-architecture-v1.md v1.0（8 数据域、ER、选型、TTL、迁移策略） | ✅ |
| L1 | sequence-diagrams-v1.md（6 核心流：执行/Session/认证/LLM 安全/Plugin 沙箱/审计） | ✅ |
| L1.5 | concept-model v2.0 | ✅ |
| L2 | 11 域 20 份规范（Runtime v1.3 / EventBus v1.1 / Capability v1.4 / Policy v1.1 / Audit v1.1 / Security v1.1 / Tenant v1.2 / Conversation v1.0 / Schedule v1.0 / Knowledge v1.0 等） | ✅ 全量 |
| L3 | capability-sdk-design-v1.md、runtime-sdk-design-v1.md | ✅（仅 SDK 侧） |
| 代码 | libs/ 5 个 SDK 包：core / runtime / capability / connector / plugin，317 个测试函数 | ✅ |
| 工程 | CI（4 SDK matrix + 全量测试）、validate-cross-refs.py（R1-R4） | ✅ |
| 设计 | role-based-access-control-v1.md v1.1（2 轮评审 P0=0） | ✅ 待服务端落地 |

## 2.2 SDK 已经替服务端锁定的契约（重要）

服务端不是从零设计——以下契约已被 SDK 代码固化，服务端实现必须与之对齐：

| SDK 资产 | 锁定的服务端契约 |
|:---------|:-----------------|
| runtime-py `client.py` | `POST /v1/sessions`（user_id/tenant_id/role_id MUST）、JWT Bearer、RetryConfig 语义 |
| runtime-py `session.py`/`invoker.py` | Session invoke / events / close 的 REST 形态与响应字段 |
| runtime-py `testing/mock_runtime.py` | **服务端行为参照实现**——真实服务端必须通过与 MockRuntime 相同的契约测试 |
| capability-py `registration/` `discovery/` | Capability Registry 的注册/发现 API（含 role_id 过滤参数） |
| plugin-py `grpc_protocol.py` | Plugin Daemon gRPC 协议 |
| core-py（audit/credential/masking/guard/knowledge_rag/conversation/schedule/tenant_keys） | 服务端可直接复用的共享库（审计事件模型、凭证加密、脱敏、InputGuard/OutputFilter、RAG 检索模型等） |

**杠杆点**：SDK 测试套件（尤其 MockRuntime 契约测试）可以直接改造为服务端的验收测试——"SDK 打 MockRuntime 通过的用例，打真实服务端也必须通过"。这是现成的、零额外成本的集成测试资产。

## 2.3 缺失项

| # | 缺口 | 影响 |
|:-:|:-----|:-----|
| 1 | **服务端代码 0 行**（无 apps/、无 services/、无 server/） | 一切待建 |
| 2 | **无 DDL/迁移基线**（data-architecture 定义了实体与索引，但无 alembic 目录、无一行 SQL） | M0 必须先建 |
| 3 | **无服务端 L3 设计**（L3 目录只有 2 份 SDK 设计） | 每个里程碑需按流水线补 L3 |
| 4 | **无 OpenAPI/proto 契约文件**（契约散落在 L2 规范文字 + SDK 代码中） | 建议 M0 固化为 openapi.yaml，纳入交叉引用校验 |
| 5 | **技术栈未做正式决策**（部署架构隐含 python:3.12 + Nginx + Envoy，但无 ADR） | M0 决策 |
| 6 | RBAC 服务端执行面（data_scope 过滤 / discover 过滤 / RAG 过滤 / RLS / DDL） | 并入 M2/M4 |

---

# 三、服务端组件全景与构建清单

按部署架构 v1.1 §1.2，服务端共 19 个组件。按"业务组件 / 网关 / 守护进程 / 数据存储"分类，标注每个组件的规范支撑与建议落地阶段：

| 组件 | L2 规范支撑 | SDK 复用 | 复杂度 | 落地里程碑 |
|:-----|:-----------|:---------|:------:|:----------:|
| Runtime Service（Session/Execution/编排入口） | Runtime v1.3 | runtime-py 契约 + MockRuntime | 高 | M1 |
| Capability Registry（注册/发现/版本/健康） | Capability v1.4 | capability-py 双端客户端 | 中 | M1 |
| Audit Service（事件订阅+写入+归档） | Audit v1.1, EventBus v1.1 | core-py audit | 中 | M1（进程内）/ M6（独立） |
| Policy Center（RBAC/限流/data_scope/审批） | Policy v1.1 | core-py guard | 高 | M2 |
| Planner Service（Intent/Task Planner） | Planner v1.0, Decision v1.0 | — | 高 | M3 |
| Workflow Engine | Workflow v1.1 | — | 高 | M5 |
| Knowledge Base（RAG + pgvector + 角色过滤） | Knowledge v1.0 | core-py knowledge_rag | 中 | M4 |
| Conversation（会话/消息/摘要） | Conversation v1.0 | core-py conversation | 中 | M4 |
| Scheduler/Trigger | Schedule v1.0 | core-py schedule | 中 | M5 |
| Gateway REST + InputGuard | Security v1.1 §InputGuard | core-py guard | 中 | M1（框架中间件形态） |
| WebSocket Gateway（流式推送） | Runtime v1.3 事件 | runtime-py events | 中 | M6 |
| gRPC Gateway | — | — | 低 | Phase 2 拆分时 |
| MCP Server | — | connector-py mcp | 中 | M7 |
| Plugin gRPC Daemon（子进程隔离） | Security v1.1 沙箱 | plugin-py sandbox/manager | 高 | M7 |
| Connector Daemon | — | connector-py | 中 | M7（M1 先进程内） |
| OutputFilter（嵌入式拦截器） | Security v1.1 | core-py masking | 低 | M2 |
| PostgreSQL + pgvector DDL/RLS | Tenant v1.2, Data Arch | — | 中 | M0 |
| Redis（Session 热数据/限流计数） | Tenant v1.2 §5.2 | — | 低 | M2 |
| RabbitMQ EventBus | EventBus v1.1 | — | 中 | M6（M1 先进程内实现） |

**观察**：architecture-v6 §9 Phase 1 的圈定范围（Coordination 最小版 + Rule Planner + Orchestrator + RBAC + 进程内 EventBus + Business Dictionary）与上表 M1-M3 高度吻合，说明 L1 既有分期判断依然有效，只需按单人 + AI 流水线的现实重新切片。

---

# 四、既有分期计划评估

| 来源 | 内容 | 评估 |
|:-----|:-----|:-----|
| architecture-v6 §9 | Phase 1（1-3 月）/ Phase 2（3-6 月）/ Phase 3（6-12 月）/ Phase 4（12-24 月） | 方向正确，但按团队月历编制。单人 + 流水线 v2.0 场景下应改为"里程碑 = N 个 PRD 周期"的粒度；且未回答单体/微服务落地形态 |
| enterprise-architecture §演进建议 | Phase 1 MVP → Phase 2 成熟 → Phase 3 规模化 | 与 v6 一致，同样缺工程落地形态 |
| deployment-architecture v1.1 | 11 业务服务 + Istio mTLS + 4 网关 + per-tenant namespace | 这是**目标态（prod）**拓扑。若第一天就按此开发：11 个服务 × (Dockerfile + Helm + mTLS + 独立 CI)，单人不可承受；且三引擎彻底拆分是 v6 明确的 Phase 4 目标，不是起点 |

**结论**：既有文档回答了"最终长什么样"和"先做哪些能力"，没有回答"以什么工程形态起步"。这正是本分析要补的决策（见 §五）。

---

# 五、推荐开发策略

## 5.1 形态：模块化单体先行（需确认，建议落 ADR-007）

```
apps/earp-server/                  ← 单一 FastAPI 应用 + 单一镜像
  src/earp_server/
    gateway/        ← REST 路由 + InputGuard 中间件 + JWT/租户/角色上下文
    runtime/        ← Session/Execution/Orchestrator（对应 Runtime Service）
    capability/     ← Registry + Discovery（对应 Capability Registry）
    policy/         ← Policy Center（RBAC/data_scope/限流/审批）
    planner/        ← Intent/Task Planner（Rule 先行，LLM 置于接口后）
    knowledge/      ← KB + RAG
    conversation/   ← 会话域
    schedule/       ← Scheduler/Trigger
    audit/          ← 审计订阅与写入
    infra/          ← EventBus 抽象(进程内→RabbitMQ)、DB、Redis、State Machine
  migrations/       ← alembic
  tests/
```

**规则**：
1. 模块边界 = 部署架构服务边界，**模块间只准走各自的 service 接口 + EventBus，禁止跨模块 import 内部实现**（用 import-linter 在 CI 强制）。
2. 所有状态外置 PG/Redis（对齐 A9 Stateless），保证未来拆分时模块可直接搬出为服务。
3. EventBus 先用进程内实现（v6 §9 Phase 1 明确允许），接口对齐 EventBus Spec v1.1 且**必须可背 RabbitMQ / Redis Streams 双实现**；M6 带数据决策后替换实现类（若选 Redis Streams 则提 ADR 修订部署架构）。
4. 与部署架构的偏差记录为 ADR：**部署架构是 prod 目标态，dev/MVP 以单体承载同一套逻辑拓扑**。
5. **进程模型：一镜像多进程**（Dify v1.15 生产实践同款，tech-reference §2.1）——同一代码库/镜像以不同 entrypoint 跑出 `api`（HTTP）、`worker`（异步任务：KB 索引/归档/TTL 清理）、`scheduler`（调度循环：Schedule 域扫表触发 + 系统级 cron，v1.4 起不再依赖 Celery Beat）三个角色，M6 增加 `websocket`（事件流推送）。扩容拆进程不拆代码库；仅安全边界（Plugin Daemon/沙箱/出口代理）才独立成服务（M7）。

## 5.2 技术栈终选（v1.4 定稿，依据见 tech-stack-analysis-v1.md）

| 层 | 终选 | 关键依据 / 约束 |
|:---|:-----|:----------------|
| 语言 | Python 3.12（全异步栈） | SDK 同栈；GIL 为 documented limitation（IO 密集 + 多进程） |
| Web 框架 | FastAPI + uvicorn | pydantic 同源；OpenAPI 导出即契约固化；Dify Flask+gevent 反证 |
| ORM/迁移 | SQLAlchemy 2.x async + Alembic | data-arch §6.1 已定；RLS SET LOCAL 控制面最精细 |
| DB | PostgreSQL 16 + pgvector（HNSW，高维 halfvec） | data-arch §3.1 已定；注意 HNSW+角色过滤召回率（ef_search/iterative scan） |
| DB 驱动 | **psycopg3 全线统一**（D7） | 与 procrastinate 联动；统一驱动 > 极限性能 |
| 任务队列 | **procrastinate**（PG broker，async 原生，事务性入队；D6 修订）；Celery 为回退备选 | 消除 async/sync 双栈税；KB 索引任务与业务行同事务；基础设施 -1。**M0 半天 spike 定夺** |
| 定时调度 | 系统级（TTL 清理/归档）= procrastinate cron；业务级 Schedule 域 = 自建 DB 驱动调度循环 | Beat 静态 schedule 无独特价值（Dify 亦是 beat 内扫表） |
| 缓存/限流/锁 | Redis——**锁定 7.2 命令面，CI 对 Valkey 双验证**（D8a） | Redis 7.4+ 非 OSI 许可；Valkey=BSD |
| EventBus | M1 进程内实现（接口对齐 EventBus Spec，**必须可背 RabbitMQ/Redis Streams 双实现**）→ M6 带数据决策 | broker 是实现细节，契约不变 |
| 对象存储 | **只依赖 S3 API**（aioboto3）；dev=MinIO，交付可替换 SeaweedFS/客户 S3（D8b） | MinIO AGPL + 社区版削功能风险 |
| 认证 | JWT（HS256 dev / RS256 prod），middleware 注入 tenant_id/role_id；OIDC SSO=Phase 2 | 时序图 3 |
| 重试 | tenacity（映射 ConnectorRetryConfig 字段） | langchain §2.2 |
| KB 分块 | langchain-text-splitters（MIT，M4 PRD 终审） | langchain §2.6 |
| 可观测 | OTel instrumentation（fastapi/sqlalchemy/redis/httpx）+ 响应注入 X-Trace-Id | Dify 同款组合（OTel 套件） |
| 流式推送 | 原生 WebSocket 独立进程（不用 socketio 协议） | 部署架构 WS GW；Dify api_websocket 形态 |
| 包管理 | **uv**（workspace 管 apps/ + libs/）（D9） | Dify 已用（uv.lock 实测）；lockfile 可复现 |
| Lint/类型 | ruff + pyright（strict 渐进）（D9） | 单人零配置价值最大 |
| 测试 | pytest + pytest-asyncio + **testcontainers**（真 PG 跑 RLS/pgvector）（D9） | SQLite 无法模拟 RLS/pgvector |
| 迁移安全 | alembic check + squawk（D9） | data-arch §6.3 大表纪律自动化 |
| API 契约 | openapi.yaml 由 FastAPI 导出 + 入库固化，交叉引用校验新增规则 R5（SDK 端点 vs OpenAPI） | 缺口 #4 |
| 本地基础设施 | docker-compose（PG+pgvector / Redis / MinIO；broker 视 M6 决策再加） | dev 环境策略（部署架构 §5.1） |

## 5.3 质量策略

- 每条服务端 MUST → 测试（沿用 R3/R4 交叉引用校验，扩展到 apps/earp-server）。
- **契约回归**：CI 中把 runtime-py / capability-py 的集成测试指向真实服务端（docker-compose 服务化跑），MockRuntime 与真实服务端行为强制一致。
- 每里程碑走流水线 v2.0：PRD → Gate A → (影响分析/L3) → Gate B → 任务清单（人工确认）→ 编码 → Gate C。

---

# 六、里程碑分解（M0-M7）

> 粒度说明：1 个里程碑 = 1-3 个 PRD；参照流水线 Cycle Time（中等 Feature 2.5-4h），M0+M1 合计约 4-6 个工作日可交付最小闭环。

## M0 — 决策与脚手架（1 PRD）
- ADR-007（单体先行 + 技术栈终选 §5.2 定稿）
- **procrastinate spike（半天）**：验证并发 worker 稳定性 / 失败重试语义 / 与 SQLAlchemy async session 共存——通过则 D6 定稿 procrastinate，否则回退 Celery（psycopg3 统一驱动缓解双栈）
- apps/earp-server 脚手架（api/worker/调度循环三进程角色 + ext_* 装配模式 + repositories 仓储接口层）、docker-compose、CI 接入
- 工具链落地（D9）：uv workspace + ruff + pyright + testcontainers + squawk
- Alembic 基线 DDL：8 数据域核心表（**含 role_id 列与 RLS tenant 策略，RBAC DDL 一步到位**，避免二次迁移）+ **checkpoints 3 表**（采用 LangGraph PostgresSaver 真实模型：checkpoints/checkpoint_blobs/checkpoint_writes，三表冗余 tenant_id，大小值分离，langgraph-earp-mapping v1.1 §2.5）。注：chunks 表的 content_hash/source_updated_at 列改在 M4（PRD-2026-020 Gate A P0-2 决议：先升 KB Spec v1.1 再 ADD COLUMN，非破坏性）
- 基础依赖定稿：tenacity（重试）、procrastinate（D6，spike 后）、psycopg3（D7）等（tech-stack-analysis §五）
- openapi.yaml 初版（sessions 域，从 runtime-py 契约反推）
- 依赖：无。产出后 M1 才能开工。

## M1 — 最小闭环 Walking Skeleton（2 PRD）🎯 关键里程碑
- Gateway：JWT 认证 + 租户/角色上下文中间件 + InputGuard 接入
- Runtime：`POST /v1/sessions` / invoke / close / 状态机（对齐 Runtime Spec v1.3 §4.1）
- **执行内核骨架一步到位（v1.3，架构性决定，避免 M5/M6 返工）：**
  - Step Runner 接口一次定义三形态：同步结果 / 流式事件 / 批量（Runnable 协议结论，langchain §2.2）——M6 流式只换传输层不动接口
  - Orchestrator 内置 **Layer 拦截器链**（graphon Layers 模式，tech-ref §2.3）：M1 挂 AuditLayer，M2 挂 PolicyLayer/OutputFilterLayer，引擎本体不改
  - **最小 Checkpoint 落盘**：invoke 完成即写 checkpoint（3 表模型已在 M0 DDL；LangGraph 结论"Checkpoint 是所有闭环能力的 P0 基础"）——M5 只扩展多步/恢复/Durability，不从零引入
  - Connector 调用带 tenacity 基础重试（映射 ConnectorRetryConfig 字段，langchain §2.2）；熔断/策略化重试留 M5
- Capability Registry：注册 + 精确发现（pgvector 语义检索放 M4）+ 一个 demo Query Capability（走 connector-py Mock）
- Audit：进程内 EventBus 订阅 → audit_logs 写入（引擎事件流消费者模式，对齐时序图 6）
- **验收：runtime-py SDK 集成测试打真实服务端全绿；时序图 1/2/6 可走通；audit 记录含 checkpoint_id**
- 依赖：M0

## M2 — Policy Center + RBAC 服务端执行面（2 PRD）
- RBAC 评估（required_permissions ⊆ role.permissions）、Query/Command 分流（CQRS，Command 必经 Policy）
- **接入形态（v1.3）**：Policy 评估与 OutputFilter 以 Layer 挂入 M1 拦截器链，不侵入引擎与节点实现
- data_scope 四层过滤（应用层 ORM 注入）+ RLS SET LOCAL 链路
- Capability discover 按 role 过滤
- 审计补 role_id/user_roles；PERMISSION_DENIED 事件
- Redis 限流：令牌桶三参数模型（rps / 检查间隔 / 突发桶上限，langchain §2.7），对齐部署架构 §2.3 LLM 并发控制
- **验收：RBAC 设计 v1.1 §六 两个示例场景端到端可复现**
- 依赖：M1。⚠️ 本里程碑完成 = 角色级访问控制设计正式落地

## M3 — Reasoning 最小版（1-2 PRD）
- Rule Intent Planner（Business Dictionary 精确匹配）+ Simple Task Planner（单步/顺序 Plan）
- Plan Validation Layer（Schema/权限/循环/深度，Policy Center 参与）
- **LLMConnector 接口定稿（v1.3，五挂点一次定义，langchain §2.4）**：rate_limiter / cache / bind_tools（Capability 候选注入）/ with_structured_output / 流式开关——实现可分期（cache Phase 2 开启），接口不返工
- LLM Planner 的 Plan 产出用 structured output 约束（Pydantic schema），校验失败 → ERR-PL-VALIDATION-001（v6 §8.2）
- LLM 不可用降级路径 = v6 §8.5 表（Rule Planner 兜底）
- 依赖：M1（Execution Plan 落到 M1 的 invoke 链）

## M4 — Knowledge + Conversation（2 PRD）
- KB：Document/Chunk 入库、pgvector 检索、accessible_roles RAG 过滤（RBAC §3.4）
- 增量索引：RecordManager 模式（content_hash 去重 + incremental 清理，防重复嵌入与幽灵检索，langchain-earp-mapping §2.5）；分块采用 langchain-text-splitters 依赖（MIT，PRD 定稿，同 §2.6）
- 检索可观测：补 RETRIEVAL_FAILED 事件（callbacks 钩子对照查漏，langchain §2.1）
- Capability 语义发现切 pgvector
- Conversation：会话/消息/摘要（core-py conversation 模型复用）
- 依赖：M2（角色过滤）

## M5 — Execution 可靠性 + Workflow/Schedule（2-3 PRD）
- Orchestrator 多步编排（plan→execute→update→checkpoint 循环，Pregel 骨架印证，langgraph v1.1 §2.6）
- Retry/Timeout/熔断：Temporal Retry Policy 四参数（InitialInterval/BackoffCoefficient/MaximumAttempts/MaximumInterval）落到策略化重试；步级重试内建引擎层并发 STEP_RETRIED 事件
- 补偿最小版：Saga 补偿注册模式（每个 Command Step 注册 compensate，Temporal 结论；完整 Saga/TCC 按 v6 属 Phase 3）；长任务 Heartbeat 进度上报
- **Checkpoint 扩展（v1.3）**：多步/恢复 + **Durability 三档**（sync/async/exit，langgraph v1.1 §2.6）——Command 步骤强制 sync，常规默认 async；嵌套 Workflow 用 task_path 寻址（M0 DDL 已预留）
- REPLANNING 状态 + interrupt 模式暂停/恢复（异常驱动 Checkpoint+Resume，langgraph §2.4；human_approval 节点）
- 错误策略：handle_tool_error 三态（吞错返回预设 / 抛出 / callable 定制，langchain §2.3）——业务性失败不炸整个 Plan
- Workflow Engine（DSL 编译 + 状态机 + Agent↔Workflow 协调最小版）
- Scheduler/Trigger（Schedule Spec v1.0，落 scheduler 进程：扫表触发 + 系统级 cron）
- 依赖：M3

## M6 — 事件与流式（1-2 PRD）
- EventBus 切独立 broker：**RabbitMQ vs Redis Streams 带数据决策 spike**（事件峰值/路由复杂度实测；选 Redis Streams 则提 ADR 修订部署架构）——接口不变，仅换实现类
- WebSocket Gateway：执行事件流式推送（runtime-py events 对接；独立进程形态，Dify api_websocket 同款）——传输层替换，Step Runner 流式接口 M1 已定
- 流式 token 事件类型入 EventBus 注册表（对齐 on_llm_new_token，langchain §2.1）；工具调用期间流式边界处理（disable_streaming="tool_calling" 语义，langchain §2.4）
- Audit Service 拆为独立消费者进程（第一个"拆分"演练）
- 依赖：M1（EventBus 抽象）

## M7 — 隔离与生态（2-3 PRD）
- Plugin gRPC Daemon（plugin-py grpc_protocol 对接，子进程沙箱，时序图 5）
- **Plugin 安装五段流程（v1.3，Dify plugin_service 模式，dify-mapping §3.2）**：download → verify → unpack → register → health_check；PluginManager 现缺 verify/health_check 两段
- Connector Daemon 独立化 + Vault/KMS 凭证注入（core-py credential/tenant_keys）
- **出口管控（v1.3）**：dev/compose 环境用 squid 强制出口代理（Dify ssrf_proxy 模式，tech-ref §2.1）承载 Connector Egress 白名单；prod 仍走 NetworkPolicy（部署架构 §3.3）
- MCP Server
- 依赖：M2（权限）、M6（事件）

## 明确排除（本轮不做，对齐 v6 Phase 3/4）
- 三引擎独立部署、Istio mTLS、per-tenant namespace、K8s Helm 全套
- Multi-Agent Coordinator、Evaluation Center 闭环、ML Decision、完整 Saga/TCC
- Kafka、独立向量库（qdrant/milvus）

## 依赖图

```
M0 ─→ M1 ─→ M2 ─→ M4
       │     └──→ M7
       ├──→ M3 ─→ M5
       └──→ M6 ─→ M7
```

## 里程碑 ↔ L2 规范升级映射（v1.3 新增，Gate A 检查表）

> 治理规则：L3 实现不得违背 L2——对比发现要求的增强凡涉及契约变化，必须在对应里程碑的 PRD 中先行升级 L2 规范（走 Gate A），再进入实现。下表是每个里程碑 PRD 的规范变更预算：

| 里程碑 | 需升级的 L2 规范 | 变更内容 | 来源发现 |
|:------:|:-----------------|:---------|:---------|
| M1 | Runtime Spec v1.3→v1.4 | Checkpoint 创建点补"invoke 完成即落盘"最小语义；Step Runner 三形态调用契约 | langgraph P0 结论 / langchain §2.2 |
| M2 | 无（Policy v1.1 / Tenant v1.2 已含 RBAC 条款） | rate_limit 参数命名对齐令牌桶三参数（若现有条款字段不一致则 v1.2） | langchain §2.7 |
| M3 | Planner Spec v1.0→v1.1 | Plan 产出 structured output 约束 + 校验失败错误码；LLMConnector 五挂点接口条款 | langchain §2.4 |
| M4 | Knowledge Base Spec v1.0→v1.1 | 增量索引语义（content_hash 去重 / incremental 清理）；EventBus 注册表补 RETRIEVAL_FAILED | langchain §2.5/§2.1 |
| M5 | Runtime Spec v1.4→v1.5；EventBus v1.1→v1.2 | Durability 三档参数（Command 强制 sync）；STEP_RETRIED 事件；handle_tool_error 三态错误策略条款 | langgraph v1.1 §2.6 / langchain §2.1/§2.3 |
| M6 | EventBus v1.2→v1.3 | 流式 token 事件类型；WS 推送事件序列约定 | langchain §2.1 |
| M7 | 无（Security v1.1 沙箱条款已覆盖） | Plugin 安装五段流程若入规范则 Capability/Security Spec 小版本 | dify §3.2 |

> 注：具体版本号以实施时各 Spec 的当前版本为准（上表按 2026-07-18 版本快照推算）；每次升级跑 `scripts/validate-cross-refs.py` 保证 R1/R2 一致。

---

# 七、风险与缓解

| # | 风险 | 等级 | 缓解 |
|:-:|:-----|:----:|:-----|
| 1 | 规范-实现漂移（20 份 L2 规范，服务端逐条对齐工作量大） | 高 | MUST→测试映射沿用 R3/R4；每 PRD 只圈定关联 Spec 章节，不整本对齐 |
| 2 | 单体形态与部署架构文档不一致，造成后续评审混乱 | 中 | ADR-007 显式记录"dev 单体 = prod 拓扑的逻辑等价承载"；部署架构不改 |
| 3 | MockRuntime 与真实服务端行为分叉 | 中 | M1 起 CI 双跑：SDK 测试 × {MockRuntime, real server} |
| 4 | LLM 依赖引入不稳定（Planner/Decision） | 中 | M3 Rule 先行；LLM 一律置于接口后 + 降级路径（v6 §8.5） |
| 5 | DDL 返工（RBAC 列、分区、索引后补） | 中 | M0 一次性纳入 role_id/索引/RLS；大表迁移遵守 data-arch §6.3 |
| 6 | 单人带宽：服务端 + SDK 双线维护 | 低 | SDK 已稳定（317 测试），冻结新特性，仅随服务端契约变更被动更新 |
| 7 | 开源结论时效性（LangGraph 月级演进、Dify graphon 持续重构，勘察快照会过时） | 低 | 分析文档均标注勘察版本与文件路径；实施时以 EARP L2 规范为准，开源仅作模式参考不作依赖（text-splitters/tenacity 除外，均为稳定小包） |

---

# 八、待确认决策项（阻塞 M0）

| # | 决策 | 建议 | 备选 |
|:-:|:-----|:-----|:-----|
| D1 | 工程形态 | 模块化单体（ADR-007）——Dify v1.15 同形态服务生产级多租户 SaaS，佐证见 tech-reference §2.1 | 直接微服务（不建议） |
| D2 | Web 框架 | FastAPI——Dify 的 Flask+gevent 补丁栈是历史包袱代价展示（tech-reference §2.2），EARP SDK asyncio 栈与 FastAPI 同源 | Litestar / gRPC-first |
| D3 | 服务端目录 | `apps/earp-server/`（monorepo 内） | 独立仓库（不建议，交叉引用校验会断） |
| D4 | 里程碑顺序 | M0→M7 如上 | 调整（如 KB 提前） |
| D5 | PRD 编号 | 服务端从 PRD-2026-020 起 | — |
| D6 | 任务队列 | **procrastinate**（v1.4 修订：async 原生消除双栈税 + PG 事务性入队 + 基础设施-1；MIT 实测；M0 半天 spike 定夺，tech-stack-analysis §4.4） | Celery+Beat（spike 不过时回退；psycopg3 统一驱动缓解双栈） |
| D7 | DB 驱动 | psycopg3 全线统一（api/worker/队列同一驱动家族，tech-stack-analysis §4.5） | asyncpg（api 单独提速，不建议混用） |
| D8 | 基础设施许可策略 | a) Redis 锁 7.2 命令面 + CI 对 Valkey(BSD) 双验证；b) 代码只依赖 S3 API，MinIO 可替换（SeaweedFS/客户 S3）（tech-stack-analysis §4.7/§4.8） | 忽略许可风险（不建议——企业交付合规门槛真实存在） |
| D9 | 工程工具链 | uv workspace + ruff + pyright + testcontainers + squawk（tech-stack-analysis §4.9） | poetry/mypy 等传统组合 |

确认后即可产出 M0 的 PRD-2026-020（脚手架+DDL 基线）进入流水线。

---

# 附录 A：服务端与 11 个 L2 域的覆盖对照

| L2 域 | 服务端落地点 | 里程碑 |
|:------|:------------|:------:|
| 01-runtime（Runtime v1.3 / EventBus v1.1） | runtime/ + infra/eventbus | M1, M6 |
| 02-reasoning（Planner / Decision / Knowledge Center） | planner/ | M3 |
| 03-capability（Capability v1.4） | capability/ | M1, M2, M4 |
| 04-execution（Agent / Workflow / Scheduler / Resource） | runtime/orchestrator + workflow/ + schedule/ | M5 |
| 05-governance（Audit v1.1 / Observation v1.1 / Policy v1.1） | audit/ + policy/ + 指标标签 | M1, M2（Observation 完整版 Phase 2） |
| 06-security（Security v1.1） | gateway/InputGuard + OutputFilter + 凭证 | M1, M2, M7 |
| 07-tenant（Tenant v1.2） | RLS + Redis 前缀 + 中间件上下文 | M0, M1, M2 |
| 09-conversation（v1.0） | conversation/ | M4 |
| 10-schedule（v1.0） | schedule/ | M5 |
| 11-knowledge（v1.0） | knowledge/ | M4 |
