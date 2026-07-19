# EARP 服务端技术栈选型分析

**文档编号：DESIGN-TECH-STACK**
**版本：v1.1**
**日期：2026-07-18**
**定位：D1-D9 技术栈决策的依据展开 + 替代方案压力测试。作为 ADR-007（工程形态与技术栈）的证据基础。已被 server-side-development-plan-v1.md v1.4 消费。**
**依赖：arch/reference/server-side-tech-reference-v1.md, arch/reference/opensource-comparison-findings-v1.md, L1/deployment-architecture-v1.md, L1/data-architecture-v1.md（被 server-side-development-plan-v1.md v1.4 消费，非依赖关系）**

> **v1.1 变更（评审修复，见 arch/reviews/tech-stack-analysis-v1-review.md）**：P0-1 新增附录 A"与既有文档的冲突清单"，L2 knowledge-center-spec 已同步 v1.1（Celery→任务队列去实现绑定）；P0-2 taskiq 许可表述修正（源码 BSD-3，wheel 元数据异常与降权理由解耦）；P1 全修——补 SAQ 对比、procrastinate 风险量化（维护者/8.6k 行实测）、pgbouncer prepare_threshold、spike 判定矩阵、SeaweedFS 降为提及+兼容性验证、TaskQueue 抽象远期迁移路径、§五消费状态更新；P2 顺手修 6 项。

---

# 一、结论摘要

| 层 | 现建议 | 压力测试结果 |
|:---|:-------|:-------------|
| 语言 | Python 3.12 | ✅ 维持——生态引力 + SDK 同栈，无真实挑战者 |
| Web 框架 | FastAPI | ✅ 维持——Litestar 性能略优但生态差距大 |
| ASGI 服务器 | uvicorn | ✅ 维持（granian 观察） |
| ORM/迁移 | SQLAlchemy 2 async + Alembic | ✅ 维持 |
| DB 驱动 | asyncpg | ⚠️ **条件化**——任务队列选型联动（见 §4.5） |
| 任务队列 | ~~Celery+Beat~~ | 🔴 **建议重议 D6**——发现"双栈问题"，procrastinate 成为更优候选（§4.4） |
| 定时调度 | ~~Celery Beat~~ | ⚠️ 弱化——Schedule 域本就要自建 DB 驱动调度器，beat 优势缩水 |
| EventBus broker | RabbitMQ（M6） | ⚠️ Redis Streams 作为挑战者，M6 决策（§4.6） |
| 缓存 | Redis | ⚠️ **许可风险需固定策略**（7.4+ 非 OSI；Valkey 备选，§4.7） |
| 向量 | pgvector | ✅ 维持（补 HNSW/halfvec 实施注意点） |
| 对象存储 | MinIO | ⚠️ **AGPL 合规点 + 社区版削功能风险**，S3 兼容层必须可替换（§4.8） |
| 认证 | JWT | ✅ 维持；企业 SSO（OIDC）Phase 2 |
| 可观测 | OTel 全家桶 | ✅ 维持 |
| 工程工具链 | （未定过） | 🆕 新增决策 D9：uv + ruff + 类型检查器 + testcontainers（§4.9） |

---

# 二、选型评估维度（依据从哪来）

所有结论按以下 6 维度评估，权重针对 EARP 现实（单人开发 + AI 流水线 + 企业级交付目标）：

| # | 维度 | 权重 | 说明 |
|:-:|:-----|:----:|:-----|
| 1 | **SDK 同栈性** | 高 | 5 个 SDK 包已锁定 asyncio/httpx/pydantic——服务端偏离此栈 = 永久性阻抗失配 |
| 2 | **单人运维成本** | 高 | 每多一个有状态基础设施 = 长期照看负担；能合并到 PG/Redis 的不新增 |
| 3 | **生态成熟度** | 高 | OTel 埋点、文档、AI 编码器熟悉度（Claude Code 评审/生成质量与生态流行度正相关） |
| 4 | **许可合规** | 中高 | 企业级产品交付——AGPL/SSPL/非 OSI 许可需显式策略，不能默认混入 |
| 5 | **与 L1/L2 约束一致性** | 高 | 部署架构/数据架构/EventBus Spec 已锁定的不轻易翻，翻则走 ADR |
| 6 | **可逆性** | 中 | 接口先行的选型（EventBus/存储抽象）可后换实现，容忍度高；DDL/框架级选型不可逆，从严 |

**依据的三个来源**：① 开源实证（Dify v1.15 / LangGraph / LangChain 本地实码勘察）；② 既有 L1/L2 约束（data-arch §3.1 选型对比、deployment-arch 组件规格）；③ SDK 既成事实（317 测试锁定的契约与技术风格）。

---

# 三、已充分论证的选型（简述依据，不再展开）

## 3.1 Python 3.12
- **依据**：5 个 SDK 包全 Python；LLM 生态（openai/anthropic SDK、embedding、RAG 工具）Python 第一优先；Dify/LangChain/LangGraph 全 Python——开源参考可直接映射；单人生产力。
- **备选压力测试**：Go（并发/部署优）——但失去 SDK 同栈与 AI 生态，仅 Plugin Daemon（M7）保留 Go 选项（Dify plugin_daemon 同款）；Java/Kotlin（企业惯性）——开发速度与 AI 生态劣势明显；TypeScript——服务端 AI 生态弱于 Python。
- **已知限制（documented limitation）**：GIL——但 EARP 服务端负载是 IO 密集（LLM/DB/HTTP），async + 多进程（api×N/worker×N）足够；CPU 密集的 embedding 走外部服务（vLLM/API）。free-threading（3.13+）不赌。

## 3.2 FastAPI + uvicorn
- **依据**：pydantic v2 原生（SDK 同源）；OpenAPI 自动导出直接满足"契约固化 openapi.yaml + 交叉引用校验 R5"的既定需求；OTel instrumentation 现成；Dify 的 Flask+gevent 补丁栈反证（gRPC/psycopg2 都要 monkey-patch，tech-ref §2.2）；AI 编码器对 FastAPI 语料最充分（Gate C 评审质量相关）。
- **备选**：Litestar——benchmark 略优、DI 更强、msgspec 支持，但社区体量差一个数量级，扩展生态（auth/admin/instrumentation）需自拼，单人项目风险大于收益。Django——admin/auth 电池有价值，但 sync-first + Django ORM 对 RLS `SET LOCAL` 会话控制不如 SQLAlchemy 精细，且与 SDK 风格割裂。gRPC-first——SDK 契约是 REST（httpx/MockRuntime），gRPC-first 会废掉"SDK 测试双跑"杠杆；gRPC 作为内部通信在拆分阶段（Phase 2）按部署架构引入。
- **ASGI 服务器**：uvicorn（标准）；granian（Rust，性能更好）列为观察项——切换成本≈0（启动命令级），不值得现在冒险。

## 3.3 SQLAlchemy 2 async + Alembic + PostgreSQL 16 + pgvector
- **依据**：data-arch §3.1/§6.1 已定（PG/pgvector/Alembic 三项均有正式选型对比）；RLS 双防线需要 ORM 层自动注入 + 连接级 `SET LOCAL`——SQLAlchemy 的 session event/execution options 是 Python 生态最精细的控制面；pgvector-sqlalchemy 集成成熟。
- **备选**：SQLModel——FastAPI 亲和但只是 SQLAlchemy 薄封装，损失控制力不减复杂度；Tortoise——迁移与 RLS 控制弱；raw asyncpg——手写实体映射长期成本高。
- **pgvector 实施注意点（新增）**：M4 用 HNSW 索引（查询快，构建慢于 IVFFlat 可接受）；embedding 维度≥2000 时用 halfvec 省一半内存；`accessible_roles` 过滤走 `WHERE` 后置过滤 + 数组 GIN 索引配合，注意 HNSW+filter 的召回率问题（ef_search 调大或 iterative scan，pgvector 0.8+）。

---

# 四、需要重议或新增的决策

## 4.4 ⭐ 任务队列：发现"双栈问题"，D6 建议改推 procrastinate

**Celery 的问题（此前分析未暴露）**：Celery 任务是 sync-first——task 函数内用 async 需 `asyncio.run()` 桥接或全部写同步。EARP 服务端是 FastAPI 全异步栈，选 Celery 意味着：

```
api 进程：   async SQLAlchemy session + async httpx + async 业务逻辑
worker 进程：sync SQLAlchemy session + sync 调用栈（或每任务 asyncio.run 桥接）
           = 同一套 repositories/service 要维护 async/sync 两套调用面
```

**双栈是永久性维护税**——Dify 不痛是因为它全栈同步（Flask），EARP 反过来。这个论据在 D6 原评估（"Dify 生产验证 + OTel 现成 + beat 一体"）中被遗漏。

**候选对比（许可来源：wheel METADATA 实测 + 源码仓库核对，/tmp/pq）**：

| 方案 | 异步 | broker | 定时 | 许可 | 评估 |
|:-----|:----:|:------:|:----:|:----:|:-----|
| Celery 5.6.3+ + Beat | ❌ sync-first | Redis/RabbitMQ | Beat（静态） | BSD | 生态最大、Dify 生产验证（版本来源：Dify api/pyproject.toml `celery>=5.6.3` 实测）；**双栈税**；功能面远超需求 |
| **procrastinate 3.6** | ✅ async 原生（psycopg3） | **PostgreSQL**（LISTEN/NOTIFY） | ✅ 内置 cron（croniter） | **MIT（实测）** | **事务性入队**（任务与业务行同事务提交——KB 索引一致性天然解决）；少一个 broker；单栈 |
| arq 0.28 | ✅ async 原生 | Redis | ✅ cron | MIT（实测） | 轻量；维护节奏放缓（作者转向 pydantic 系）；重试语义较弱 |
| SAQ 0.x（未实测锁版） | ✅ async 原生 | Redis | ✅ cron | MIT | async Redis 队列当前最佳代表（维护活跃度优于 arq）；排除理由：需单独 Redis broker 承担持久性职责、无事务性入队，对 EARP 无相对 procrastinate 的增量优势 |
| taskiq 0.11 | ✅ async 原生 | 多 | 插件 | BSD-3（源码仓库） | 年轻、生态插件化尚在演进——成熟度不足独立构成降权理由。注：其 wheel METADATA License 字段标 "Other/Proprietary"，与源码 BSD-3 不一致，应属打包配置疏漏，不作为降权依据，但企业合规扫描器会误报，实施若选用需先推动上游修复元数据 |
| Dramatiq | ❌ sync-first | Redis/RabbitMQ | 需 APScheduler | LGPL | 同样双栈税且生态小于 Celery |

**procrastinate 的额外收益**：
1. **事务性入队**——"写 documents 行 + 入索引任务"同一个 PG 事务，要么都成功要么都不落（Celery+Redis 做不到，需要 outbox 模式补偿）；审计写入同理。
2. 基础设施 -1：M4 之前不需要为队列引入任何新组件（PG 已在）。
3. 依赖 psycopg3——与 §4.5 驱动决策联动。

**诚实的代价（v1.1 量化）**：
- 吞吐上限低于 Redis/RabbitMQ broker（PG 队列量级：千级任务/秒——EARP 的 KB 索引/归档/清理量级在其之下两个数量级）
- 社区规模：核心维护者少（1-2 人量级，vs Celery 的多维护者团队），企业生产案例少于 Celery
- **Bus factor 风险与兜底**：若上游停更，EARP 需 fork 自维护——包体实测 8,633 行 Python（含 CLI/contrib，/tmp/pq-src wc -l），且职责单一（PG 队列），fork 成本可控；这是接受该风险的量化依据
- LISTEN 需要独立长连接（连接池需留 1-2 个专用连接，pgbouncer transaction 模式不兼容 LISTEN——自管连接即可）

**spike 判定矩阵（M0 PRD 的 AC 直接引用）**：

| 验证点 | 通过标准 | 失败信号 |
|:-------|:---------|:---------|
| 并发 worker 稳定性 | 2 worker × 100 任务并发全部完成，无死锁，PG 连接数稳定无泄漏 | worker 卡死 >30s；连接数持续增长 |
| 失败重试语义 | max_attempts=3 的任务失败后重试 3 次进入失败态；retry 延迟符合配置（±5s） | 跳过重试直接失败，或无限重试 |
| SQLAlchemy async session 共存 | worker 内复用 api 同款 async session factory，事务提交后 session 正确释放 | session 泄漏；"connection checked out" 告警 |
| 事务性入队 | 业务行 INSERT + defer 任务在同一事务：回滚后任务不出现 | 回滚后任务仍被执行 |

**远期迁移路径（spike 通过 ≠ 永久绑定）**：M1 在 `infra/task_queue` 定义 `TaskQueue` 薄抽象（`enqueue(task_name, payload, scheduled_at?)` + 装饰器注册），procrastinate 为实现之一；业务代码不 import procrastinate。若远期吞吐成为瓶颈（概率低，见量级分析），换 Celery/其他实现类即可——与 EventBus 双实现策略同构。

**D6 修订建议**：首选 procrastinate（异步同栈 + 事务性入队 + 基础设施最小化），Celery 降为保守备选。M0 按上表 spike 验证，任一项不过则回退 Celery（psycopg3 统一驱动缓解双栈，见 §4.5）。

**定时调度的连带修正**：Celery Beat 的优势本就虚——Beat 的 schedule 是静态代码定义，而 EARP Schedule 域（M5）是**用户动态创建的 DB 驱动触发器**，无论选谁都要自建"扫描 schedules 表 → 到期入队"的调度循环（Dify 也是 beat 任务里跑 workflow_schedule_task 扫表，本质相同）。procrastinate 内置 cron 覆盖系统级定时（TTL 清理），业务级 Schedule 域自建，Beat 无独特价值。

## 4.5 DB 驱动：asyncpg vs psycopg3（与 D6 联动）

| 场景 | 推荐 |
|:-----|:-----|
| D6 = procrastinate | **psycopg3 全线统一**（procrastinate 依赖 psycopg3；SQLAlchemy async 官方支持 psycopg3-async；一个驱动家族覆盖全部进程角色） |
| D6 = Celery | api 进程 asyncpg（性能），worker 进程 psycopg3 sync——或干脆全线 psycopg3 减少差异 |

asyncpg 基准略快于 psycopg3-async（社区 benchmark 常见区间 ~10-30%，查询密集场景；未做本地复测——EARP 瓶颈在 LLM 调用不在 DB 驱动，该差距不构成实际影响）；**统一驱动 > 极限性能**。新增决策 **D7：默认 psycopg3 全线统一**（若 D6 选 procrastinate 则无悬念）。

> **pgbouncer 兼容注意（v1.1）**：若部署链路使用 pgbouncer transaction 模式，psycopg3 需设置 `prepare_threshold=None` 禁用自动 prepared statements（否则报 "prepared statement already exists"）；且 LISTEN/NOTIFY（procrastinate）与 RLS 的 `SET LOCAL` 会话语义均要求事务内一致的连接——LISTEN 连接绕过 pgbouncer 直连 PG。此条写入部署文档。

## 4.6 EventBus broker：RabbitMQ vs Redis Streams（M6 决策点）

- **现状**：EventBus Spec v1.1 定义的是**契约**（CloudEvents 1.0 + 事件注册表 + 投递语义），broker 是实现细节；deployment-arch 写了 RabbitMQ（3 节点 StatefulSet）。M1 用进程内实现，M6 才需要真 broker。
- **挑战者论据**：Redis Streams（consumer group + at-least-once + pending list）覆盖 EARP 事件量级，且 Redis 已在栈内——**省掉一个 3 节点 StatefulSet**。RabbitMQ 优势（灵活路由拓扑、per-message TTL、成熟 DLX）在 EARP 的"单 Exchange + tenant routing key"用法下未被充分利用。
- **结论**：不现在翻案（尊重 L1 约束 + 可逆性高）。M6 PRD 里做一次带数据的决策 spike：若事件峰值 < 5k msg/s 且路由拓扑保持简单 → 提 ADR 修订 deployment-arch 改 Redis Streams；否则维持 RabbitMQ。**M1 的 EventBus 接口必须同时可背 RabbitMQ/Redis Streams 实现**（接口设计约束，写进 M1 L3 设计）。

> **接口设计注意（v1.1）**：双实现约束意味着接口层只暴露两者的最小公约数（publish / subscribe / ack / nack / consumer group 语义），DLX、per-message TTL、延迟消息等高级特性只能在实现类内部配置，不得进入接口契约——这是双实现的真实成本，M1 L3 设计时显式确认。

## 4.7 Redis 许可策略（企业交付合规，新增决策 D8a）

- 事实：Redis 7.4+ 改为 RSALv2/SSPLv1 双许可（非 OSI）；Redis 8 增加 AGPLv3 选项；Valkey（Linux Foundation，BSD-3）从 7.2.4 分叉，主流云厂商已跟进。
- EARP 是交付给企业的产品，基础设施许可必须给客户明确答案。
- **建议**：兼容层策略——代码只用 Redis 7.2 兼容命令面（EARP 用法：cache/分布式锁/限流计数/可能的 Streams，全部是基础命令），部署文档标注 "Redis 7.2 OSS / Valkey 8.x 二选一，均验证支持"。CI 用 Valkey 镜像跑一遍即完成验证。
- **落地校验（v1.1）**：M0 起在 CI 增加任务"从代码提取实际使用的 redis-py 命令清单，与 Valkey 命令集 diff"——防止后续无意引入 7.4+ 专属命令或模块命令（如 Redis Stack 系列）。

## 4.8 对象存储：MinIO 的 AGPL 与社区版风险（新增决策 D8b）

- 事实：MinIO 自 2021 起 AGPLv3；2025 起社区版持续削减功能（管理控制台等）。deployment-arch/data-arch 当前写死 MinIO。
- 风险：① 企业客户普遍对 AGPL 组件设合规门槛（尽管独立进程聚合分发通常无传染，法务审查成本真实存在）；② 社区版功能面不可控。
- **建议**：EARP 代码层只依赖 **S3 API**（boto3/aioboto3），不依赖任何 MinIO 特有 API；部署文档给出三档：客户自有 S3 兼容存储（企业常见，首选）/ 其他 S3 兼容实现（如 SeaweedFS，Apache 2.0——**仅提及不推荐**，选定前须以 EARP 实际 S3 操作集 PutObject/GetObject/DeleteObject/ListObjectsV2/multipart upload 做全量兼容性验证）/ MinIO（客户自行接受 AGPL）。dev 环境 docker-compose 可继续用 MinIO（内部使用无分发问题）。deployment-arch 下次修订时把 "S3 (MinIO)" 改为 "S3 兼容存储（默认 MinIO，可替换）"。

## 4.9 工程工具链（新增决策 D9，M0 定稿）

| 项 | 建议 | 依据 |
|:---|:-----|:-----|
| 包管理 | **uv**（workspace 模式管 apps/ + libs/ 多包） | Dify api 已用 uv（uv.lock 实测在库）；比 pip/poetry 快一个数量级；lockfile 可复现。⚠️ uv workspaces 仍在快速迭代——M0 落地时验证多包 lockfile 交叉解析稳定后再全面切换，期间 libs/ 可保留现有 per-package 安装方式 |
| Lint/Format | ruff（lint + format 二合一） | 事实标准；单人项目零配置价值最大 |
| 类型检查 | pyright（strict 渐进） | mypy 慢且插件时代结束；pyrefly（Meta，Dify 在用）尚年轻可观察；pyright 与 AI 编码器协作最顺 |
| 测试 | pytest + pytest-asyncio + **testcontainers**（PG/Redis 临时容器） | M1 契约测试需要真 PG（RLS/pgvector 无法用 SQLite 模拟）；testcontainers 让 CI 与本地一致。CI runner 需可访问 Docker socket（GitHub Actions 默认支持；自建 runner 需配置） |
| 迁移检查 | alembic check + squawk（危险 DDL lint） | data-arch §6.3 大表迁移纪律的自动化 |

---

# 五、修订后的决策清单（D1-D9）

| # | 决策 | v1.3 建议 | 本分析修订 |
|:-:|:-----|:----------|:-----------|
| D1 | 工程形态 | 模块化单体 | 维持 |
| D2 | Web 框架 | FastAPI | 维持（uvicorn；granian 观察） |
| D3 | 目录 | apps/earp-server/ | 维持 |
| D4 | 里程碑 | M0-M7 | 维持 |
| D5 | PRD 编号 | 2026-020 起 | 维持 |
| D6 | 任务队列 | Celery+Beat | **改：首选 procrastinate，Celery 备选，M0 半天 spike 定夺**（双栈税 + 事务性入队 + 基础设施-1） |
| D7 | DB 驱动 | （未单列） | **新增：psycopg3 全线统一**（与 D6 联动） |
| D8 | 基础设施许可策略 | （未单列） | **新增**：a) Redis 7.2 命令面 + Valkey 双验证；b) 只依赖 S3 API，MinIO 可替换（SeaweedFS/客户 S3） |
| D9 | 工具链 | （未单列） | **新增：uv + ruff + pyright + testcontainers + squawk** |

**对既有文档的影响**：
- server-side-development-plan：D6 修订 + D7-D9 追加 + M0 procrastinate spike + M1 "EventBus 接口须可背双实现"约束 → **已落 v1.4**（该文档 changelog v1.4 条目引用本文）
- L2 knowledge-center-specification：**已同步 v1.1**——"MUST: 异步处理（Celery 任务）"改为"任务队列"（去实现绑定，见附录 A）
- deployment-arch：MinIO 表述与 Redis 版本策略，在下一次该文档修订时顺手改（非阻塞）
- EventBus broker 翻案与否 → M6 PRD 内带数据决策

---

# 附录 A：与既有文档的冲突清单（v1.1 新增，评审 P0-1）

| 文档位置 | 冲突内容 | 处置 | 状态 |
|:---------|:---------|:-----|:----:|
| arch/L2/02-reasoning/knowledge-center-specification.md §3.3 | `MUST: 异步处理（Celery 任务）`——规范层写死队列实现，与 D6 冲突且违反"规范不写实现细节"原则 | 改为 `MUST: 异步处理（任务队列）`，spec 升 v1.1 并加 changelog | ✅ 已修（2026-07-18） |
| arch/L1/enterprise-architecture.md:401 | 调度一栏写 "Celery Beat" | 该文档属早期探索稿（L1 基线是 architecture-v6.md，其 §9 未绑定 Celery）——不改历史文档，以本清单声明其调度选型表述已被 D6 取代 | 📌 声明取代 |
| arch/L1/deployment-architecture-v1.md | `S3 (MinIO)`、Redis 版本未标注许可策略 | 下次修订该文档时改为"S3 兼容存储（默认 MinIO，可替换）"+ Redis 7.2/Valkey 策略（§4.7/§4.8） | ⏳ 非阻塞待办 |
| arch/reference/server-side-tech-reference-v1.md §三 D6 | "建议 Celery"（该文档结论早于本分析） | 本文 §4.4 取代其 D6 结论；该文档保留历史评估不改（分析链可追溯） | 📌 声明取代 |

---

# 附录 B：评审修复记录

| 轮次 | 评审文件 | 结果 | 修复 |
|:----:|:---------|:-----|:-----|
| r1 | arch/reviews/tech-stack-analysis-v1-review.md（Claude Code） | P0×2 / P1×7 / P2×7 | P0-1 L2 spec v1.1 + 附录 A；P0-2 taskiq 表述修正；P1-1~P1-7 全修（SAQ 行、bus factor 量化 8,633 行实测、pgbouncer prepare_threshold、spike 判定矩阵、SeaweedFS 降级、TaskQueue 抽象、§五状态更新）；P2-1/2/3/4/5/6/7 顺手修 |
| r2 | arch/reviews/tech-stack-analysis-v1-review-r2.md（Claude Code） | **0 新增 P0/P1**，r1 全部确认修复；新 P2×3（格式项） | P2-N1 Celery 版本精度、P2-N2 依赖字段循环声明、P2-N3 SAQ 版本标注——均已顺手修。**评审关闭** |

---

# 六、一句话版本

**"跟着 SDK 的栈走（async Python），跟着 PG 走（能放 PG 的不加新组件），跟着许可干净的走（MIT/Apache/BSD），接口先行保可逆（EventBus/S3/LLM 全部抽象后置实现）。"**

Celery→procrastinate 是本次分析唯一的实质翻案，理由不是新潮，而是三个硬指标：消除 async/sync 双栈维护税、事务性入队解决 KB 索引一致性、基础设施少一个 broker。其余选型经压力测试后维持，但补上了此前缺失的许可合规策略（Redis/MinIO）与工具链决策。
