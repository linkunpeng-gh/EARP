# EARP 架构设计分析与建议

评审日期：2026-09-05。基于当前工作区快照进行只读调研（monorepo 全量结构 + earp-server 后端 + 前端/SDK/部署三个维度），本次仅新增评审报告，不修改业务实现。同日另有独立评审见 [2026-09-05-architecture-assessment.md](2026-09-05-architecture-assessment.md)，两份报告视角互补。

## 一、对设计目的的理解

EARP 定位为**企业级 AI Runtime Platform（企业 AI 操作系统）**，核心理念是"LLM 在企业场景只占 20%，集成、编排、治理、审计占 80%"（[arch/L0/design-philosophy.md](../L0/design-philosophy.md)），刻意区别于 Dify/Coze 这类以 LLM 为中心的平台。三引擎九层架构（[arch/L1/architecture-v6.md](../L1/architecture-v6.md)），以模块化单体落地（ADR-007），当前重心在知识资产三层演进：RAG 打底 → 本体层（TBox 抽象类型 + ABox 实例/事实 + Compiled Truth）→ 因果模型（ECMC），并以煤矿"3 号矿产量下降诊断"作为贯穿演示场景（`example/`）。

文档驱动程度非常高（L0~L3 架构文档 + 33 份 PRD + 34 份任务书 + CI 跨引用校验），并有持续维护的 [arch/tech-debt.md](../tech-debt.md) 债务台账——这在同类项目中极为罕见，是明确的设计取向："规范≠文档"、架构契约用工具守护（import-linter、OpenAPI drift 检查、catalog golden hash）。

## 二、总体评价：方向正确，执行有亮点，债务集中在前端与巨石文件

**做得好的（应坚持）**：

1. **模块化单体 + import-linter 契约**——比直接上微服务明智，域边界有工具守护；
2. **多租户用 PG RLS 且角色分离**（migration 角色 BYPASSRLS / 应用角色 FORCE RLS，`tenant_session` 封装空租户防御，[infra/db.py:44](../../apps/earp-server/src/earp_server/infra/db.py)）——安全设计正确；
3. **testcontainers 真库集成测试 + 88 个测试文件**，embedding 用确定性 stub 保证 CI 稳定；
4. **单一 PG 承载向量（pgvector）/图（递归 CTE）/全文/队列（Procrastinate）**——早期规模下是正确的简化，避免了过早引入 4 种存储的运维负担；
5. 零依赖静态前端被 FastAPI 同源 mount，演示/交付启动成本极低；
6. 技术债显式登记（代码内 tech-debt #N + 台账 + commit hash），可追溯性上乘。

**核心风险**：文档体系与实现之间已出现明显落差（earp-user 空壳、部署架构仅存在于设计态、观测规范未落地）；前端 7000 行无类型原生 JS 已到可维护性临界点；后端巨石文件（main.py 2092 行、causal service 2378 行）正在侵蚀模块化单体的初衷。

## 三、分维度建议

### 1. 技术架构与代码组织（优先级最高）

- **拆掉 `main.py` 巨石**：main.py 2092 行中 804~2092 行内联了几十个端点（sessions/capabilities/knowledge/planner/chat），而 ontology/catalog/causal 等域已有独立 `routes.py`。建议：所有路由一律 `include_router`，main.py 只保留 `create_app` 工厂 + lifespan + 中间件装配；配套将散落各路由文件的 Pydantic 模型归拢到各域 `schemas.py`（目前 `schemas/` 只有 sessions）。这同时能让 import-linter 契约真正约束到这些域。
- **收敛 `causal_model_management/service.py`（2378 行）**，并厘清它与 `bmc/` 的职责重叠——Case A/BMC/N01A 多套命名指向同一因果推理域，建议统一术语后合并或明确分工边界。
- **统一数据访问风格**：目前 `tenant_session` 封装与手写 `SET LOCAL` 并存，abox_service.py:43 甚至用 f-string 拼 tenant_id。建议强制所有 ABox/TBox 查询走 `tenant_session`，加一条 lint/测试守护"禁止手写 SET LOCAL"。
- **原生 SQL 与无 ORM 的取舍**：全 `text()` 字符串 + `row._mapping` 使 schema 演进靠人肉对齐（已有 `test_repro_stale_schema.py` 这类补丁测试佐证）。不必全面转 ORM，但建议至少：a) 查询 SQL 集中到各域常量/模块便于审计；b) 为核心表定义 TypedDict/dataclass 行模型，pyright strict 才能真正发挥作用。
- **削减 import-linter 豁免**：pyproject 中 20+ 条 `ignore_imports`（chat_service 一处就跨 5 个域）已稀释契约约束力。建议给豁免加"清偿期限"注释并逐季递减；跨域协作优先走已有 EventBus 事件而非直接 import。
- **清理死代码**：`main_v2.py`、tests pycache 中 dbg/tmp 残留、`apps/earp-admin/spikes/drawflow-poc`、根目录一次性报告 `earp-catalog-phase1-review-report.html`（内容已吸收进 tech-debt 台账，建议移入 arch/reviews/ 并可删）。

### 2. 性能

- **给 pgvector 加 ANN 索引**（HNSW，embedding 维度固定后 `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`）——目前余弦检索是全表扫描，chunks 上规模后是第一瓶颈；
- **`lookup_entities` 双向 ILIKE 全表扫**：加 `pg_trgm` 扩展 + GIN 索引即可在不动架构的前提下支撑十万级实体；
- **图打分下推**：`_graph_relevance` 用 Python 对图结果逐条 bigram 打分，实体/事实量增大后应把相关度计算下推到 SQL（ts_rank）或限制进入打分的候选集规模；
- 递归 CTE 已有 max_hops/path 防环/limit，设计是对的，建议补充超过 limit 时的"结果截断"显式提示，避免用户误以为结果完整。

### 3. 数据存储

- 单 PG 路线现阶段正确，但建议在文档中**写明各存储能力的演进阈值**（如 facts > 千万行、图查询 p95 > 500ms 时引入专用方案），避免"永远单一 PG"或"过早分库"两种漂移；
- **Compiled Truth 一致性**：写时失效 + 惰性编译 + 定期 `find_stale_profiles` 的组合可行，但建议给 stale profile 加监控指标（stale 数量/重编译耗时），失效风暴时可观测；
- `.env` 已提交仓库且含环境假设，建议改为 `.env.example` + 真实 env 出库。

### 4. 部署架构（当前文档与实现落差最大处）

- **补齐应用 Dockerfile**：仓库只有基础设施 compose（pg/valkey/minio/langfuse），5 个 entrypoint 进程靠 uv 裸跑；而 [arch/L1/deployment-architecture-v1.md](../L1/deployment-architecture-v1.md) 已设计了 K8s/Istio 拓扑。建议先做最小闭环：单应用镜像（多 entrypoint 用 command 区分）+ 全栈 compose（含 api/worker/scheduler/audit/plugin_daemon 五服务）支持一键起，再谈 K8s；
- **dev 硬编码 JWT 密钥与 `/auth/login` 仅 dev 的设计**可以，但需在配置校验层强制"prod 环境必须提供 RS256 公钥"，防止误配；
- 观测仅接了 Langfuse，OpenTelemetry/Prometheus 规范未落地——建议优先给 5 进程补统一 OTel tracing（尤其 chat→planner→orchestrator 链路），这比 K8s 更早成为排障刚需。

### 5. 技术栈

- **前端已到临界点**：7000 行无类型原生 JS、手写 `esc()` 防 XSS（易漏）、API 契约全靠人肉对齐 + 浅层 smoke 测试。建议不必全面重写，但应：a) 用 `openapi.yaml` 生成 TypeScript client（后端已有导出脚本与 drift 检查，这是现成资产）；b) 新页面引入 Vite + Vue3/React + TS，老页面渐进迁移；c) 至少加 ESLint。`ecmc-causal-editor.js`（1486 行）应优先组件化；
- **SDK 双副本问题**（tech-debt #6，libs/ 与 server 内版本不一致）：引入 uv workspace 或至少建立"SDK 改动必须同步 server 内副本"的 CI 检查；
- monorepo 无统一任务入口，各 app/lib 独立 venv——可用 `just`/`mise` 或根级 Makefile 提供常用命令（bootstrap/test/lint/all），降低新成员上手成本；
- LLMConnector 抽象好，但唯一实现是 Ollama；建议补一个 OpenAI 兼容 provider（绝大多数企业网关都兼容），企业落地说服力更强。

### 6. 可扩展性

- 亮点：能力注册 + 语义发现（pgvector）、插件沙箱独立进程、MCP 端点、Saga 补偿、检查点——Runtime First 的落地是认真的；
- **多租户单库 RLS 的噪音隔离**：大租户的检索/队列负载会影响小租户（共享连接池与 procrastinate 队列）。建议预留"租户分级"能力：队列按租户分 lane、检索层可配 per-tenant 连接池配额，避免未来被迫整体迁移；
- TBox 内置 13 实体类型/12 关系的种子设计对演示友好，但企业客户类型体系差异大，建议把"内置类型"标注为可关闭的 seed 模板而非隐式约定，避免客户实体类型与内置类型语义冲突。

### 7. 易用性

- **首启体验**：登录页硬编码 seed 身份（tenant-demo/u1/r1）、首页统计 API 不可用时回退 DEMO 假数字（用户无法区分真假）。建议：a) 提供 `make seed` 一键灌入 example/ 演示数据并打印登录凭据；b) DEMO 回退数字加"示例数据"角标；
- **文档入口分散**：CLAUDE.md / arch/ / prd/ / tasks/ / docs/ / example/ 各自平行，新用户难寻。建议在根 README 建立文档地图（按"我是外部评估者/FDE/开发者"三条路径索引），根 README 目前只有 3 行与其定位不匹配；
- `earp-user` 是带 TODO 的假数据原型但 PRD-029 已立项——建议在页面显著位置标注"原型未接线"或在 README 状态表中说明，避免外部评估者误判成熟度；
- 注释/文档中存在引用漂移（如 f6_mock_server 引用不存在的 docs/fde-guide.md）——`validate-cross-refs.py` 已存在，可将其扩展到代码注释中的文档路径引用。

## 四、建议的优先顺序（前 6 项）

1. 拆分 main.py 路由 + 统一 tenant_session（消除最大债务，约束力立竿见影）；
2. pgvector HNSW 索引 + pg_trgm（低成本高收益的性能修复）；
3. 应用 Dockerfile + 全栈 compose 一键起（兑现部署文档，服务外部评估/PoC）；
4. OpenAPI → 前端 TS client 生成 + 前端引入 lint（止住契约人肉对齐的持续成本）；
5. 因果域术语/模块收敛（bmc vs causal_model_management）；
6. 首启体验包（make seed + DEMO 角标 + README 文档地图）。
