# EARP 服务端技术方案参考（开源对齐）

**文档编号：REF-SERVER-TECH**
**版本：v1.0**
**日期：2026-07-18**
**定位：服务端开发前的技术方案分析——汇总既有 3 份开源分析中适用于服务端的结论，并基于本地 Dify v1.15.0 代码库补做服务端工程形态勘察，为 server-side-development-plan 的 D1-D5 决策提供证据。**
**依赖：arch/reference/opensource-analysis.md, arch/reference/dify-earp-mapping.md, arch/reference/langgraph-earp-mapping.md, arch/design/server-side-development-plan-v1.md**

> **注意**：本文是 Dify v1.15.0 的勘察记录。D6（异步任务框架）分析阶段推荐 Celery（§三），该建议已在 server-side-development-plan v1.4 中更新为 procrastinate 首选（依据 tech-stack-analysis v1.1 §4.4 与 PRD-2026-020 spike 结论）。本文不作更新——保持勘察时的原样以保留决策链可追溯性。
**勘察对象：`/Users/linkunpeng/code/dify-code/dify` @ v1.15.0（api/pyproject.toml version=1.15.0）**

---

# 一、既有分析结论回顾（哪些直接适用于服务端）

三份分析文档均存在且结论有效，当时的落款原则是"SDK 先行、服务端实现阶段再引入参考"——现在进入该阶段，逐条提取：

## 1.1 来自 opensource-analysis.md（8 项目全景）

| 结论 | 服务端适用性 | 落到里程碑 |
|:-----|:------------|:----------:|
| LangGraph Checkpoint 协议是最高优先复用点（估省 2-3 周） | ✅ 直接决定 checkpoints 表 DDL | M0(DDL)/M5 |
| Dify 是最接近 EARP 的产品形态，学架构不抄代码 | ✅ 服务端工程形态的主参考（见 §二） | M0-M7 |
| Temporal Retry Policy + Saga 补偿模式 | ✅ Execution 可靠性设计参考 | M5 |
| vLLM 作为 LLM 推理后端，Connector 对接 | ✅ 不自建推理层 | M3 |
| Haystack Document/Chunk/Retriever 抽象 | ✅ KB 服务分层参考 | M4 |
| n8n 仅 UI 参考且 License 受限 | ⏸ 前端阶段再启用 | — |

## 1.2 来自 dify-earp-mapping.md（全栈对照）

| 结论 | 服务端适用性 |
|:-----|:------------|
| NodeRunResult 统一结果类型 + RetriableError/FatalError 错误分类 | ✅ EARP StepResult / 错误码体系（v6 §8）实现模式 |
| Plugin Daemon = subprocess + gRPC（映射度 90%） | ✅ M7 Plugin gRPC Daemon 直接参考 |
| 租户上下文 session 级注入（Account._current_tenant） | ✅ 已在 SDK 落地；服务端中间件按同模式 |
| Human Input 暂停 = 返回 PAUSED 状态由 RunLoop 挂起 | ✅ M5 human_approval 节点 |
| Agent 回调链（tool_call 前后自动审计） | ✅ M1 审计拦截器模式 |
| Dify License 限制：学架构不抄代码，代码注释标注参考来源 | ✅ 全程适用 |

## 1.3 来自 langgraph-earp-mapping.md（状态管理）

| 结论 | 服务端适用性 |
|:-----|:------------|
| CheckpointTuple/Checkpoint 字段模型 + PostgresSaver 表结构（§2.5 已给出 EARP 版 DDL） | ✅ **M0 DDL 基线直接采用** |
| thread_id + checkpoint_ns 复合主键解决 RePlan 命名空间 | ✅ checkpoints 表设计 |
| interrupt() = 异常驱动 Checkpoint + Resume | ✅ M5 暂停/恢复实现模式 |
| add_messages reducer = Context 增量追加 | ✅ Execution Context 更新语义 |
| 可选项：编排复杂化后直接引入 LangGraph 作状态引擎（MIT） | ⏸ M5 后重评估 |

**小结：既有分析已覆盖"执行引擎内核怎么写"。缺的是"服务端以什么工程形态组装"——进程模型、异步任务、流式通道、装配模式、安全部署单元。以下为本次补勘结果。**

---

# 二、Dify v1.15.0 服务端工程形态勘察（本次新增）

> 方法：实地阅读本地代码库 docker/docker-compose-template.yaml、api/app_factory.py、api/extensions/、api/repositories/、api/schedule/、api/core/workflow/workflow_entry.py、api/pyproject.toml。以下所有事实均可在对应文件复核。

## 2.1 部署拓扑：一个镜像，四种进程角色 ⭐ 最重要发现

docker-compose-template.yaml 中，同一个 `langgenius/dify-api:1.15.0` 镜像跑出 4 个服务：

| 服务 | 角色 | EARP 对应 |
|:-----|:-----|:----------|
| `api` | Flask HTTP（gunicorn + gevent） | Gateway + 各域 REST API |
| `api_websocket` | SocketIO 实时推送（独立进程） | WebSocket Gateway（M6） |
| `worker` | Celery 异步任务（索引/清理/邮件/异步工作流） | 异步任务进程（KB 索引、归档、TTL 清理） |
| `worker_beat` | Celery Beat 定时调度（api/schedule/ 下 14 个定时任务） | Scheduler/Trigger 域 + data-arch TTL 任务 |

外围独立服务：`db_postgres`(PG15) / `redis`(6) / `nginx` / `sandbox`(dify-sandbox 0.2.15，代码执行沙箱) / `plugin_daemon`(dify-plugin-daemon 0.6.3，**Go 实现的独立插件守护进程**) / `ssrf_proxy`(ubuntu/squid，**沙箱出站流量强制代理**) / 向量库可插拔（默认 weaviate，pgvector 是受支持选项之一）。

**对 EARP 的直接证据价值：**
1. **Dify 服务多租户 SaaS 生产环境，业务面就是一个模块化单体**——console/web/service_api/inner_api/mcp/trigger/files 七组 controller 装在同一个 Flask app（api/controllers/）。这直接验证 server-side-development-plan 的 ADR-007（模块化单体先行）不是妥协，而是同类产品的生产实践。
2. **"拆进程不拆代码库"**：扩展性靠同一镜像的不同 entrypoint（api/celery_entrypoint.py、app.py），而不是微服务拆分。EARP M0 脚手架应同样预置 api/worker/beat 三个进程角色（websocket M6 加入）。
3. **安全边界才拆独立服务**：sandbox、plugin_daemon、ssrf_proxy 是仅有的独立业务进程——与 EARP 部署架构中 Plugin gRPC Daemon/Connector Daemon 独立化的判断一致（M7）。
4. **ssrf_proxy（squid 强制出口代理）**是 EARP 部署架构 §3.3 Connector Egress 白名单的现成实现模式：不依赖 K8s NetworkPolicy 也能在 compose/dev 环境落地出站管控。

## 2.2 技术栈事实表（api/pyproject.toml）

| 维度 | Dify 选择 | 说明 / EARP 取舍 |
|:-----|:----------|:-----------------|
| Web 框架 | Flask 3 + flask-restx + fastopenapi | 历史包袱（2023 起步）；异步靠 gevent monkey-patch + psycogreen。**EARP 无此包袱，SDK 全线 asyncio/httpx/pydantic → FastAPI 原生 async 是更优解**（D2 维持） |
| WSGI | gunicorn + gevent，gRPC/psycopg2 都要打 gevent 补丁（celery_entrypoint.py 前 8 行） | 这是 Flask 同步生态引入异步的代价——EARP 用 uvicorn/asyncio 可整体规避 |
| ORM/迁移 | SQLAlchemy + flask-migrate（=Alembic） | 与 EARP data-arch §6.1 一致 |
| 异步任务 | Celery 5.6 + Redis broker + Beat | **EARP M0 需对应决策**：建议同选 Celery（成熟、beat 自带、OTel instrumentation 现成）；备选 arq（纯 asyncio 但生态弱） |
| 实时推送 | python-socketio 独立进程 | EARP M6 WebSocket Gateway 同构；EARP 走原生 WS/SSE 不必用 socketio 协议 |
| 可观测 | opentelemetry-instrumentation-{flask,celery,httpx,redis,sqlalchemy} 全家桶 + after_request 注入 X-Trace-Id（app_factory.py） | EARP 直接采纳同款 OTel 自动埋点组合（FastAPI 版），对齐 Observation Spec |
| 装配模式 | extensions/ext_*.py 30+ 个，每个提供 init_app(app)（ext_database/ext_redis/ext_celery/ext_storage/ext_otel/ext_login…） | **值得抄的模式**：EARP 用 FastAPI lifespan + 同风格 infra/ext_* 装配，模块可测试、可禁用 |
| 数据访问 | repositories/ 层：接口 + sqlalchemy_* 实现 + factory（api/repositories/） | 与 EARP"模块边界=服务边界"配套——仓储接口化，未来拆服务时替换实现 |
| 多租户 | 纯应用层过滤（TenantAccountJoin + current_tenant_id），**无 RLS** | EARP 的 RLS 兜底是超越 Dify 的强化，保留（Tenant Spec v1.2） |
| API 文档 | flask-restx + fastopenapi 双轨 | EARP 用 FastAPI 原生 OpenAPI 导出，一步到位（补 openapi.yaml 固化） |

## 2.3 执行引擎形态：事件流驱动（v1.15 已抽库为 graphon）

workflow_entry.py 显示 Dify 已把图引擎抽为独立库 `graphon`：

```
GraphEngine.run() → Generator[GraphEngineEvent]     # 引擎产出事件流
  ├── layers: LLMQuotaLayer / ObservabilityLayer /   # 横切层挂在引擎上
  │           ExecutionLimitsLayer / DebugLoggingLayer
  ├── command_channels: InMemoryChannel              # 外部向运行中引擎发指令(stop等)
  └── filter_graph_events(...) → 流式响应过滤器
```

**对 EARP 的证据价值：**
1. **执行引擎产出事件流，审计/观测/流式推送/配额全部是事件消费者或引擎横切层**——与 EARP"EventBus 唯一事件注册表 + Audit 订阅 + Feedback Collector"的设计（时序图 6、EventBus Spec v1.1）同构。M1 的进程内 EventBus + 审计订阅按此模式实现即可，M6 换 RabbitMQ 时消费者不动。
2. **Layers 模式**：Policy/Observation 等横切关注点作为引擎可插拔层，而非散落在节点实现里——EARP Orchestrator 应预留同样的 interceptor 链（M2 OutputFilter、M2 Policy 评估、M1 审计都挂这里）。
3. **command channel**：外部对运行中 Execution 发 stop/resume 指令的通道——EARP human-in-loop 暂停/恢复（M5）与取消语义的实现参考。
4. Dify 把引擎抽成独立库的动作本身，佐证 EARP"runtime 模块保持无框架依赖、可单测"的边界纪律。

## 2.4 Beat 定时任务清单（api/schedule/）与 EARP 映射

Dify 用 worker_beat 承载：workflow_schedule_task（定时触发工作流）、clean_messages / clean_workflow_runs_task / clean_unused_datasets_task / clean_embedding_cache_task（数据 TTL 清理）、queue_monitor_task（队列监控告警）等 14 个任务。

**映射**：EARP Schedule Spec v1.0 的定时触发（M5）+ data-architecture §4.1 的 TTL 归档任务（Session 24h/Execution 30d/AuditLog 90d 归档到 S3）落地形态就是 beat 任务，不需要独立调度服务。M0 脚手架预置 beat 进程后，M4/M5 只是往里加任务。

## 2.5 EARP 明确不跟随 Dify 的点

| Dify 做法 | EARP 不跟随的理由 |
|:----------|:-----------------|
| Flask + gevent 补丁栈 | EARP 无历史包袱，原生 asyncio 更简单且与 SDK 一致 |
| 无 RLS、纯应用层租户过滤 | EARP Tenant Spec v1.2 要求 RLS 兜底（更强的默认安全） |
| 向量库可插拔 8+ 种 | EARP data-arch 已定 pgvector 单选（零额外运维），Retriever 留抽象即可 |
| 内置 30+ LLM Provider | EARP 经 Connector 对接（A7 Adapter 原则） |
| socketio 协议 | EARP 用原生 WebSocket（部署架构已定 WS GW） |
| 无独立 Policy Center（权限散在 controller 装饰器） | EARP Policy Center 是独立域（P5 治理），不降级 |

---

# 三、对 server-side-development-plan 决策项的证据结论

| 决策 | 结论（证据） |
|:-----|:------------|
| D1 工程形态 | **确认模块化单体** — Dify 同形态服务生产级多租户 SaaS（§2.1）；修订：M0 起即按"一镜像三进程"（api/worker/beat）组织，M6 增 websocket 进程 |
| D2 Web 框架 | **确认 FastAPI** — Dify 的 Flask+gevent 是历史包袱的代价展示（§2.2），EARP SDK asyncio 栈与 FastAPI 同源 |
| D3 目录 | **确认 apps/earp-server/** — 补充 Dify 的 extensions 装配 + repositories 仓储两个组织模式 |
| D4 里程碑 | **微调** — M0 增加：Celery+beat 脚手架、checkpoints 表 DDL（LangGraph PostgresSaver 模型）；M1 审计走"引擎事件流消费者"模式；M5 引入 command channel 模式；M7 增加 ssrf_proxy 式出口代理选项 |
| D5 PRD 编号 | 不受影响，服务端自 PRD-2026-020 起 |
| 新增 D6 异步任务框架 | **建议 Celery**（Dify 生产验证 + OTel instrumentation 现成 + beat 一体）；备选 arq。M0 PRD 中定稿 |

---

# 四、遗留补充分析（可选，不阻塞 M0）

| 项目 | 用途 | 建议 |
|:-----|:-----|:-----|
| ~~LangChain 框架本体~~ | 接口/横切机制/KB 增量索引 | ✅ **已完成**（2026-07-18）—— arch/reference/langchain-earp-mapping.md：callbacks 19 钩子对照查漏、BaseChatModel 挂点清单、RecordManager 增量索引、text-splitters 依赖决策、LangGraph PostgresSaver 真实 3 表 DDL 修正（langgraph-earp-mapping v1.1） |
| LiteLLM (MIT) | LLM 网关：多 Provider 路由、per-tenant key/预算/限流 | M3 前浅析——EARP 已有 LLM Key 管理（Phase 2 深化），确认是对接还是自研补齐 |
| Langfuse (MIT 核心) | LLM 应用观测（trace/eval） | Phase 2 Observation 完整版时再看 |
| Temporal 代码级细读 | Saga/重试的实现细节 | M5 的 L3 设计阶段按需，模式层面已有结论 |

---

# 五、License 合规重申

- Dify v0.6+ 限制性 License：**学架构、学模式，不 copy 代码**；EARP 实现处注释标注 `# Inspired by Dify <path>`（模式级参考）。
- LangGraph MIT / Temporal MIT / Haystack Apache 2.0 / vLLM Apache 2.0 / LiteLLM MIT：概念与接口模式可自由参考。
- 本文档所有 Dify 结论均来自结构与模式勘察，未复制任何实现代码。
