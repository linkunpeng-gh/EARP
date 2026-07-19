# Server M0 — L3 实现设计

**文档编号：DESIGN-SERVER-M0-L3**
**版本：v1.1**
**日期：2026-07-18**
**定位：L3 — PRD-2026-020 v1.1 的实现设计。给出可编码的目录结构、接口签名、DDL 全列定义、spike 设计与测试策略。**
**依赖：PRD-2026-020 v1.1（Gate A PASS）、server-side-development-plan v1.4、tech-stack-analysis v1.1、RBAC 设计 v1.1、data-architecture v1.0、langgraph-earp-mapping v1.1、arch/impact/server-m0-impact.md**

> **v1.1 变更（Gate B r1 修复）**：P0-1 增补 checkpoint 三表"自维护声明"（EARP 不引 LangGraph 库、不用其 migration/Saver，表模型仅为设计参考——不存在库兼容问题）；P0-2 迁移/应用双角色策略（migration=BYPASSRLS，app=受限角色）；P0-3 spike 场景 3 去除对 earp_server 包依赖；P1-1 env.py async 模式片段；P1-2 tenant_session 事务契约定为方案 A；P1-3 openapi 排序与基线 diff 机制；P1-4 补 AC-06/AC-09 测试覆盖；P1-5 testcontainers 生命周期细则；P2 全部顺手修（复合 FK/SIGTERM/命名 service_account_id/credentials owner 列/export 签名/sessions 引用说明）。

---

# 一、目录结构（完整）

```
apps/earp-server/
├── pyproject.toml              # uv 管理；deps 见 PRD §5；tool.ruff/pyright/importlinter 配置
├── Makefile                    # dev / test / lint / migrate / openapi 五个 target
├── docker-compose.yml          # pg(pgvector/pgvector:pg16) + redis(valkey/valkey:8, M0 不连接) + minio(dev)
├── alembic.ini
├── openapi.yaml                # AC-08 导出产物（入库）
├── migrations/
│   ├── env.py                  # async engine + psycopg3
│   └── versions/
│       └── 0001_baseline.py    # §三 全部 DDL + RLS
├── spikes/
│   └── procrastinate_spike.py  # AC-05，独立脚本，不进包
├── src/earp_server/
│   ├── __init__.py
│   ├── main.py                 # create_app() 工厂：FastAPI + lifespan + /health /ready + v1 占位路由
│   ├── config.py               # Settings(pydantic-settings)：DATABASE_URL/LOG_LEVEL/APP_ENV
│   ├── export_openapi.py       # python -m earp_server.export_openapi
│   ├── entrypoints/
│   │   ├── api.py              # uvicorn.run(create_app())
│   │   ├── worker.py           # TaskQueue.run_worker()（spike 后=procrastinate 实现）
│   │   └── scheduler.py        # 空转调度循环骨架（asyncio loop + SIGTERM 优雅退出）
│   ├── infra/
│   │   ├── db.py               # async engine/session factory + SET LOCAL earp.tenant_id 钩子
│   │   ├── task_queue.py       # TaskQueue 薄抽象（Protocol）+ ProcrastinateTaskQueue 实现
│   │   └── ext/                # 装配模式（Dify ext_* 同款）
│   │       ├── ext_logging.py  #   init_app(app) 各自实现
│   │       └── ext_otel.py     #   （M0 仅 logging；otel 占位）
│   ├── gateway/    __init__.py + service.py   # M0 空壳（/health /ready 在 main.py）
│   ├── runtime/    __init__.py + service.py   # 空壳
│   ├── capability/ __init__.py + service.py   # 空壳
│   ├── policy/     __init__.py + service.py   # 空壳
│   ├── planner/    __init__.py + service.py   # 空壳
│   ├── knowledge/  __init__.py + service.py   # 空壳
│   ├── conversation/ __init__.py + service.py # 空壳
│   ├── schedule/   __init__.py + service.py   # 空壳
│   ├── audit/      __init__.py + service.py   # 空壳
│   └── schemas/
│       └── sessions.py         # SessionCreateRequest/SessionResponse（AC-08 占位 schema）
└── tests/
    ├── conftest.py             # testcontainers PG fixture（session 级）+ alembic upgrade
    ├── test_health.py          # AC-01
    ├── test_entrypoints.py     # AC-02（subprocess 启动 + SIGTERM）
    ├── test_migrations.py      # AC-03（幂等 + downgrade）
    ├── test_rls.py             # AC-04
    └── test_openapi_export.py  # AC-08（二次导出 diff 稳定）
```

**关键设计点**：
1. `src/` 布局 + uv 独立项目（workspace 暂不纳管 libs/，impact §2 风险 1 决议）。
2. 域模块 M0 只有 `__init__.py + service.py`（空壳但被 import-linter 契约覆盖，AC-06）。
3. `TaskQueue` Protocol 先行（tech-stack v1.1 §4.4 迁移路径）：
```python
class TaskQueue(Protocol):
    async def enqueue(self, task_name: str, payload: dict, *, scheduled_at: datetime | None = None) -> str: ...
    def task(self, name: str, *, max_attempts: int = 3) -> Callable: ...   # 装饰器注册
    async def run_worker(self, *, concurrency: int = 4) -> None: ...
```
4. `infra/db.py` 暴露 `tenant_session(engine, tenant_id)` 上下文管理器，**事务契约=方案 A（P1-2 定案）**：进入即开启事务并 `SET LOCAL earp.tenant_id`（SET LOCAL 仅在事务内有效），正常退出 commit、异常 rollback；单上下文 = 单事务。需要多事务的调用方自行多次进入。test_rls 按此模式书写。
5. **migrations/env.py async 模式（P1-1）**：
```python
# env.py 核心（async engine → sync 桥接）
from sqlalchemy.ext.asyncio import async_engine_from_config
def run_migrations_online() -> None:
    connectable = async_engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.")
    asyncio.run(_run(connectable))
async def _run(connectable):
    async with connectable.connect() as conn:
        await conn.run_sync(_do_run_migrations)   # context.configure + run_migrations 在 sync 回调内
```
6. **scheduler/worker 优雅退出（P2-2）**：`loop.add_signal_handler(SIGTERM, stop_event.set)` + 主循环 `await stop_event.wait()`，收到信号后取消在途 task 并 `sys.exit(0)`；test_entrypoints 断言 <5s。**api 进程语义注（Phase 4 实测）**：uvicorn 优雅关停后按惯例向自身重抛原信号——SIGTERM 下退出码为 143（K8s 视为正常终止），优雅性以 "Application shutdown complete" 日志为准，测试按此断言。
7. tests 增补：`test_import_linter.py`（AC-06：subprocess 调 `lint-imports`，断言 exit 0）。

# 二、接口签名（M0 全部公开面）

```python
# main.py
def create_app(settings: Settings | None = None) -> FastAPI
# GET /health  -> {"status": "ok"}                     无认证（K8s liveness）
# GET /ready   -> {"db": "ok"|"fail"} 503 on fail      无认证（readiness）

# config.py
class Settings(BaseSettings):
    database_url: PostgresDsn          # postgresql+psycopg://...
    app_env: Literal["dev","test","prod"] = "dev"
    log_level: str = "INFO"

# infra/db.py
def build_engine(settings) -> AsyncEngine
async def check_db(engine) -> bool                      # /ready 用
@asynccontextmanager async def tenant_session(engine, tenant_id: str) -> AsyncIterator[AsyncSession]

# export_openapi.py（P2-5）
def export_openapi() -> str        # json.dumps(create_app().openapi(), sort_keys=True) → YAML 字符串
# __main__: print(export_openapi())   固定 info.title="EARP Server", info.version="0.1.0"

# schemas/sessions.py —— 对齐 runtime-py client.py（AC-08）
class SessionCreateRequest(BaseModel):
    user_id: str; tenant_id: str; role_id: str          # 三者 MUST（Tenant Spec v1.2 §5.4）
    metadata: dict[str, Any] = {}
class SessionResponse(BaseModel):
    session_id: str; tenant_id: str; user_id: str; status: str = "active"
```

# 三、DDL 全列定义（0001_baseline）

> 约定：`id` 均为 `VARCHAR(64)` 业务主键（与 SDK 的 sess-xxx/exec-xxx 风格一致，不用 UUID 类型强绑定）；时间列 `TIMESTAMPTZ NOT NULL DEFAULT now()`；所有租户域表 `tenant_id VARCHAR(64) NOT NULL` + RLS 策略；`embedding vector(1536)` 仅建列（PRD §3）。RLS 会话变量：`current_setting('earp.tenant_id', true)`。

## Workspace 域
```sql
tenants(tenant_id PK, name TEXT NOT NULL, status VARCHAR(16) DEFAULT 'active', created_at)          -- 无 RLS（顶层实体）
org_units(org_unit_id PK, tenant_id, parent_id NULL, name, created_at)                              -- RLS
users(user_id PK, tenant_id, name, email UNIQUE(tenant_id,email), status, created_at)               -- RLS
roles(role_id PK, tenant_id, name, permissions TEXT[] DEFAULT '{}', data_scope VARCHAR(16) NOT NULL DEFAULT 'self'
      CHECK (data_scope IN ('self','department','org','all')), knowledge_tags TEXT[] DEFAULT '{}', created_at)  -- RLS；RBAC §3.1
service_accounts(service_account_id PK, tenant_id, name, api_key_id NULL FK api_keys, created_at)   -- RLS；P2-3 全称命名
tenant_account_joins(tenant_id, user_id, role_ids TEXT[] DEFAULT '{}', current_role_id NULL,
      PRIMARY KEY(tenant_id, user_id))                                                              -- RLS；RBAC §4.3
```

## Runtime 域
```sql
sessions(session_id PK, tenant_id, user_id, role_id VARCHAR(64) NOT NULL, status VARCHAR(16) DEFAULT 'active',
         context JSONB DEFAULT '{}', metadata JSONB DEFAULT '{}', expires_at NULL, created_at,
         UNIQUE(tenant_id, session_id))                       -- 供 executions 复合 FK（P2-1）
  IDX: (tenant_id, session_id), (tenant_id, status), (created_at)                                   -- data-arch §1.1
executions(execution_id PK, tenant_id, session_id, role_id NOT NULL, status VARCHAR(24),
           plan JSONB NULL, result JSONB NULL, error JSONB NULL, created_at, finished_at NULL,
           FOREIGN KEY(tenant_id, session_id) REFERENCES sessions(tenant_id, session_id))            -- 复合 FK
  IDX: (tenant_id, session_id), (tenant_id, status)
```

## Runtime-Checkpoint（LangGraph 3 表模型的 EARP 自维护版；三表冗余 tenant_id 系 Gate A P1-5 定案）

> **自维护声明（P0-1）**：EARP **不引入 langgraph/langgraph-checkpoint 依赖，不使用其 setup()/migration/AsyncPostgresSaver**——三表 DDL 由 EARP Alembic 全权维护，Checkpoint 读写由 M5 自研 CheckpointStore 实现（langgraph-earp-mapping v1.1 §三"独立实现 Checkpoint 协议"）。LangGraph 仅为表模型设计参考，其版本演进对 EARP 无兼容性影响。tenant_id 列 `NOT NULL`（EARP 自己的写入路径始终携带租户上下文，无第三方库绕过写入的场景）。

```sql
checkpoints(thread_id, checkpoint_ns DEFAULT '', checkpoint_id, tenant_id NOT NULL, parent_checkpoint_id NULL,
            type NULL, checkpoint JSONB NOT NULL, metadata JSONB DEFAULT '{}',
            PRIMARY KEY(thread_id, checkpoint_ns, checkpoint_id))
checkpoint_blobs(thread_id, checkpoint_ns DEFAULT '', channel, version, tenant_id NOT NULL, type NOT NULL, blob BYTEA,
            PRIMARY KEY(thread_id, checkpoint_ns, channel, version))
checkpoint_writes(thread_id, checkpoint_ns DEFAULT '', checkpoint_id, task_id, idx INT, tenant_id NOT NULL,
            channel, type NULL, blob BYTEA NOT NULL, task_path TEXT DEFAULT '',
            PRIMARY KEY(thread_id, checkpoint_ns, checkpoint_id, task_id, idx))
  IDX: 三表各 (thread_id)、(tenant_id)                                                              -- RLS 全启用
```

## Capability 域
```sql
business_capabilities(capability_id PK, tenant_id, domain, name, type VARCHAR(8) CHECK (type IN ('query','command')),
            input_schema JSONB, output_schema JSONB, required_permissions TEXT[] DEFAULT '{}',
            visible_roles TEXT[] DEFAULT '{}', fallback_capability_id NULL, embedding vector(1536) NULL,
            version VARCHAR(16), status, created_at)  IDX: (domain, tenant_id)                       -- RLS
capability_calls(call_id PK, tenant_id, execution_id, capability_id, status, latency_ms INT NULL,
            error JSONB NULL, created_at)  IDX: (tenant_id, execution_id)                            -- RLS
connector_bindings(capability_id, connector_id, tenant_id, PRIMARY KEY(capability_id, connector_id, tenant_id))  -- RLS
```

## Governance 域
```sql
policies(policy_id PK, tenant_id, policy_type VARCHAR(24), rules JSONB, status, created_at)
  IDX: (tenant_id, policy_type)                                                                     -- RLS
policy_bindings(policy_id, entity_type VARCHAR(24), entity_id, tenant_id,
  PRIMARY KEY(policy_id, entity_type, entity_id))                                                   -- RLS
audit_logs(log_id BIGSERIAL PK, tenant_id, event_type VARCHAR(48), entity_type NULL, entity_id NULL,
  user_id NULL, detail JSONB DEFAULT '{}', created_at)   -- detail 内约定 role_id/user_roles（Audit v1.2）
  IDX: (tenant_id, event_type, created_at)                                                          -- RLS
```

## Security / Knowledge / Conversation / Integration 域
```sql
encrypted_credentials(credential_id PK, tenant_id, credential_type, owner_type VARCHAR(24) NULL,
  owner_id VARCHAR(64) NULL, ciphertext BYTEA NOT NULL, key_version VARCHAR(16) NOT NULL, created_at)
  IDX: (tenant_id, credential_type)                          -- RLS；owner 列见引用完整性段（P2-4）
api_keys(api_key_id PK, tenant_id, name, key_hash TEXT NOT NULL, status, created_at, last_used_at NULL) -- RLS
knowledge_bases(kb_id PK, tenant_id, name, created_at)  IDX: (kb_id, tenant_id)                     -- RLS
documents(doc_id PK, tenant_id, kb_id FK, name, source_type, accessible_roles TEXT[] DEFAULT '{}',
  status, created_at)                                                                               -- RLS；RBAC §3.4
chunks(chunk_id PK, tenant_id, doc_id FK, kb_id, content TEXT, embedding vector(1536) NULL,
  metadata JSONB DEFAULT '{}')  IDX: (chunk_id, kb_id)   -- 列按 KB Spec v1.0 §1.1；无向量索引（M4）  -- RLS
conversations(conversation_id PK, tenant_id, user_id, title NULL, created_at)
  IDX: (tenant_id, user_id, created_at)                                                             -- RLS
messages(message_id PK, tenant_id, conversation_id FK, seq INT, role VARCHAR(16), content TEXT,
  created_at, UNIQUE(conversation_id, seq))                                                         -- RLS
connector_configs(connector_id PK, tenant_id, adapter_type, config_ciphertext BYTEA, key_version,
  status, created_at)  IDX: (connector_id, tenant_id)                                               -- RLS
```

## RLS 策略模板（每租户域表一条）
```sql
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {t} FORCE ROW LEVEL SECURITY;      -- owner 也受限，测试可信
CREATE POLICY tenant_isolation ON {t} USING (tenant_id = current_setting('earp.tenant_id', true));
```
> migration 内以表清单循环生成；`tenants` 表除外（顶层实体无 tenant_id 归属，平台管理面访问，M2 管理端点再加防护）。

**双角色策略（P0-2）**：
- `earp_migration`（或容器默认 postgres superuser）：具 BYPASSRLS——alembic 专用连接，DDL 与未来 seed DML 不被 FORCE RLS 拦截；test_migrations 增加"seed 一行 + downgrade 回退"验证该路径
- `earp_app`：普通角色，无 BYPASSRLS——应用与 RLS 测试连接，保证 FORCE RLS 真实生效
- docker-compose 初始化脚本创建两角色；Settings.database_url（app）与 alembic.ini 的 url（migration）分开配置

**引用完整性（P2-1/P2-6）**：
- `executions(tenant_id, session_id)` → 复合 FK → `sessions(tenant_id, session_id)`（sessions 补 UNIQUE(tenant_id, session_id)，与 data-arch 索引重合）
- chunks.doc_id→documents、documents.kb_id→knowledge_bases、connector_bindings 两列→各自表、service_accounts.api_key_id→api_keys：单列 FK
- sessions.user_id / role_id：**不建 FK**——多租户下的权威校验属 M2 应用层（Policy），M0 由 RLS + 应用层保证；documented limitation
- `service_accounts` 主键统一命名为 `service_account_id`（P2-3）
- `encrypted_credentials` 增加 `owner_type VARCHAR(24) NULL + owner_id VARCHAR(64) NULL`（凭据归属实体，P2-4；M2 启用校验）

# 四、spike 设计（AC-05）

`spikes/procrastinate_spike.py`：单文件，argparse（--workers/--tasks/--dsn），四个场景函数对应判定矩阵（tech-stack v1.1 §4.4），输出 JSON 证据 `spikes/spike-evidence.json` + 控制台 PASS/FAIL 摘要。**独立性（P0-3）：spike 不 import earp_server 包**——场景 3 在脚本内直接以 DATABASE_URL 构建独立的 AsyncEngine + async_sessionmaker（与 app 无共享代码），验证目标不变（procrastinate 任务内连接获取/归还与 SQLAlchemy async 连接池并存无冲突）：
1. concurrency：2 worker × 100 no-op 任务，采样 `pg_stat_activity` 连接数（前/中/后）
2. retry：注册 max_attempts=3 的必败任务，断言重试轨迹与终态 failed
3. session-coexist：任务内使用脚本内自建 async_sessionmaker 做一次查询，断言无 "connection checked out" 告警、连接归还
4. tx-enqueue：同事务 INSERT 临时表行 + defer 任务后 ROLLBACK，断言任务不出现在 procrastinate_jobs 表

结论落 ADR-007 §spike；失败则证据留档 + 切 CeleryTaskQueue 备选方案（仅实现 TaskQueue 接口的第二实现，M0 范围内允许）。

# 五、工程配置要点

| 项 | 配置 |
|:---|:-----|
| pyproject | `[project]` deps 按 PRD §5；`[tool.uv]`；`[tool.ruff]` line-length=120, select 默认+I；`[tool.pyright]` strict=["src"]；`[tool.importlinter]` independence 契约 9 模块（PRD §7） |
| Makefile | dev（compose up + migrate + uvicorn）/ test（pytest）/ lint（ruff+pyright+lint-imports）/ migrate / openapi |
| CI（.github/workflows/test.yml） | 新增 job `server`: uv sync → make lint → make test → squawk migrations/versions/*.py 内嵌 SQL（生成 SQL via alembic upgrade --sql）→ openapi diff 检查；既有 sdk matrix job 不改 |
| docker-compose | pgvector/pgvector:pg16（POSTGRES_DB=earp）、valkey/valkey:8-alpine（预置不连接）、minio/minio（dev 占位） |
| logging | ext_logging：structlog 或 stdlib JSON formatter（M0 用 stdlib，减依赖） |

# 六、测试策略

**testcontainers 生命周期（P1-5）**：PG 容器 fixture `scope="session"`、启动超时 60s；测试串行（M0 不启用 pytest-xdist）；每个测试函数使用独立事务并在 teardown rollback（function 级 fixture 包装），RLS 数据级测试自建/自清理租户数据。

**openapi 基线机制（P1-3）**：导出实现为 `json.dumps(app.openapi(), sort_keys=True, indent=2)` 转 YAML，`info.title/version` 固定常量（version 跟 M0 里程碑号 "0.1.0"，与时间无关）；仓库内 openapi.yaml 即基线，test_openapi_export 重新导出与基线逐字节比对（首次生成即基线）。

| 测试 | 覆盖 AC | 要点 |
|:-----|:-------:|:-----|
| test_health | AC-01 | httpx AsyncClient against app；/ready 在停 PG 容器后 503 |
| test_entrypoints | AC-02 | subprocess 启 3 entrypoint，2s 后 SIGTERM，断言 exit 0 且 <5s |
| test_migrations | AC-03 | upgrade head → 再次 upgrade（幂等）→ downgrade -1 → upgrade；information_schema 断言全部表；**BYPASSRLS 路径：seed 一行 + 回退（P0-2）** |
| test_rls | AC-04 | 全表策略断言（pg_policies 计数=租户域表数）；4 表数据级：earp_app 角色连接，t1 插入 → SET earp.tenant_id=t2 → count=0 |
| test_import_linter | AC-06 | subprocess `lint-imports`，断言 exit 0（P1-4） |
| test_openapi_export | AC-08 | 与基线逐字节比对；schema 含 role_id 必填 |
| spike | AC-05 | 独立脚本（不进 pytest，Makefile target spike） |
| ADR 存在性 | AC-09 | CI 步骤断言 `arch/design/ADR-007-*.md` 存在且含 "spike 结论" 章节（P1-4） |
| SDK 回归 | AC-10 | CI 既有 job 不动即覆盖 |

# 七、AC ↔ 设计映射

| AC | 设计落点 |
|:--:|:---------|
| AC-01 | §一 main.py + §二 create_app/check_db + test_health |
| AC-02 | §一 entrypoints/ + test_entrypoints |
| AC-03 | §三 0001_baseline + test_migrations |
| AC-04 | §三 RLS 模板 + test_rls |
| AC-05 | §四 spike + ADR-007 |
| AC-06 | §一 域空壳 + §五 importlinter 契约 |
| AC-07 | §五 pyproject/Makefile/CI |
| AC-08 | §二 export_openapi + schemas/sessions + test_openapi_export |
| AC-09 | ADR-007（任务清单含）|
| AC-10 | §五 CI（既有 job 不动） |
