# Gate B 审查：DESIGN-SERVER-M0-L3 v1.0

## 审查结论：**有条件通过（3×P0 阻塞，修复后放行）**

---

## P0 — 阻塞合并

### P0-1. LangGraph checkpoint 三表兼容性未论证

**位置**：§三 Runtime-Checkpoint

DDL 在 LangGraph 原生 checkpoint/checkpoint_blobs/checkpoint_writes 三表中插入 `tenant_id` 列。LangGraph 的 `AsyncPostgresSaver` 通过内部 migration 自行建表并假设固定 schema。EARP 自定义 DDL 意味着：
- 不能使用 LangGraph 内置 `setup()` 建表
- 需自维护 SQLAlchemy 模型映射额外列
- LangGraph 版本升级可能改变基表 schema，与 EARP 扩展列冲突

**建议**：§三增补一段兼容性声明：明确 (a) 放弃 LangGraph 内置 migration，EARP 自维护三表 DDL；(b) `tenant_id` 列有 DEFAULT（如空字符串或 `'__no_tenant__'`），确保 LangGraph 内部 INSERT（不指定 tenant_id）不报错；(c) 将三表纳入 `spikes/` 增加一个 `langgraph_checkpoint_spike.py` 验证 AsyncPostgresSaver 对扩展列的容忍度。或者降级方案：三表不加 tenant_id，改用 `checkpoint->metadata->>'tenant_id'` 做应用层过滤。

### P0-2. FORCE RLS 阻断 migration seed DML

**位置**：§三 RLS 策略模板 + §五 CI（squawk）

```sql
ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
```

`FORCE RLS` 对 table owner 也生效。M0 的 `0001_baseline.py` 做纯 DDL 不受影响（CREATE TABLE 不走 RLS），但：
- 若后续 migration 需要 seed 数据（INSERT 默认租户行），会被 `tenant_id = current_setting('earp.tenant_id', true)` 过滤掉全部行导致 INSERT…RETURNING 静默失败或写入 NULL tenant_id
- CI 中 `squawk` 检查 alembic upgrade --sql 生成的 SQL 不包含 `SET LOCAL earp.tenant_id`，CI 无法发现此问题

**建议**：§三明确 migration 连接使用 **superuser 角色**（superuser 绕过 RLS 包括 FORCE RLS），或 env.py 中执行 DDL 前 `SET LOCAL role = 'earp_migration_superuser'`（BYPASSRLS 属性）。§六 test_migrations 增加 seed + rollback 场景验证。

### P0-3. Spike 与 app 包循环依赖

**位置**：§四 spike 设计

> `任务内使用 earp_server.infra.db 的 session factory 做一次查询`

`spikes/procrastinate_spike.py` 标注"不进包"，但场景 3（session-coexist）要求 import `earp_server.infra.db`。这会：
- 要求 spike 运行前必须 `uv sync`（安装 app 包自身）
- app 包的 infra.db 尚未验证可用（这正是 M0 要搭建的），形成鸡生蛋蛋生鸡

**建议**：场景 3 改为 spike 内独立创建 `AsyncEngine` + `async_sessionmaker`（直接从 DATABASE_URL 构建），不依赖 app 包。测试目标不变：验证 procrastinate 任务内连接获取/归还不冲突。

---

## P1 — 合并前应修复

### P1-1. Alembic async env.py 模式缺失

**位置**：§一 `migrations/env.py` 描述仅 `# async engine + psycopg3`

Alembic 的 async 模式需特定写法（`connectable.sync_engine` 或 `run_async()` 包装），且 `env.py` 本身是同步文件。当前描述不足以编码。

**建议**：§一补充关键代码片段：
```python
# env.py 核心模式
from earp_server.infra.db import build_engine
engine = build_engine(settings)

def run_migrations_online():
    connectable = engine.sync_engine  # async engine → sync engine
    with connectable.connect() as connection:
        context.configure(connection=connection, ...)
        with context.begin_transaction():
            context.run_migrations()
```
或明确使用 `alembic.op.run_async()` 包装每个 migration 的 upgrade/downgrade。

### P1-2. `tenant_session()` 事务上下文契约不明确

**位置**：§一 infra/db.py + §二

```python
@asynccontextmanager async def tenant_session(engine, tenant_id: str) -> AsyncIterator[AsyncSession]
```

`SET LOCAL earp.tenant_id = 'xxx'` 必须在事务内执行。当前签名无 transaction 管理：
- 调用者是否需自行 `async with session.begin()`？
- 若 session 未在事务中，SET LOCAL 会报错还是静默无效果？
- 退出上下文时是否 commit/rollback？

**建议**：明确为两个变体之一：
- (A) `tenant_session` 内部 `async with session.begin()`：进入设 tenant_id → yield → commit。适合单次读写。
- (B) `tenant_session` 仅设变量，事务由调用者管理：文档明确调用者 MUST 先 `session.begin()`。test_rls 示例代码应体现此模式。

### P1-3. OpenAPI 导出 diff 稳定性机制不完整

**位置**：§二 export_openapi.py + §六 test_openapi_export

> "key 排序固定，保证 diff 稳定" + "导出两次字节级相等"

仅 key 排序不足以保证 FastAPI openapi.json 字节级稳定。风险点：
- `$defs`（schema definitions）的 key 顺序取决于 Pydantic 模型首次被引用的顺序
- `paths` 的 key 顺序取决于路由注册顺序
- metadata（title/version）可能含时间戳

**建议**：明确排序策略——导出后做 JSON → Python dict → `json.dumps(dict, sort_keys=True, indent=2)` + 固定的 `info.title`/`info.version`。test_openapi_export 应说明：若首次导出无基线则直接 PASS（建立基线），后续与基线 diff。

### P1-4. 测试表中 AC-06/AC-09 无覆盖

**位置**：§六 测试策略表 + §七 AC 映射

AC-06（import-linter 9 模块契约）在测试策略表中无对应行——仅靠 CI `make lint` 间接覆盖，但无 pytest 验证。AC-09（ADR-007）标注"任务清单含"但无测试/校验步骤。

**建议**：
- AC-06：test_import_linter.py（subprocess 调用 `lint-imports`，断言 exit 0）
- AC-09：test_adr.py（断言 `arch/adr/ADR-007-*.md` 存在且包含 spike 结论章节），或至少 §六标注"AC-09 由 spike 脚本 PASS 后 ADR 文件存在性 CI 检查覆盖"

### P1-5. Testcontainers PG 生命周期与并行风险

**位置**：§六 test_conftest（session 级 fixture）

Session 级 fixture 意味着所有测试共享一个 PG 容器。风险：
- pytest-xdist 并行：每个 worker 各自启一个容器（或冲突）
- RLS 测试通过 `SET LOCAL` 隔离数据，但同一 session 内不同测试可能在同一事务边界内打架
- 容器启动 10-30s，session 级 fixture 的超时未设

**建议**：conftest.py 明确：(a) 明确 `scope="session"` 且 `autouse=False`；(b) 禁止 xdist（`-p no:xdist` 或 `@pytest.mark.no_parallel`）；(c) testcontainers 超时 60s；(d) 每个 test 使用 `function` 级 transaction rollback 隔离（`async with session.begin() → yield → rollback`）。

---

## P2 — 可随后修复（建议）

### P2-1. FK 约束声明缺失
- `executions.session_id → sessions.session_id`：有标注 FK，但 sessions 无 tenant_id 参与外键——跨租户 session_id 引用在 FK 层面无隔离（RLS 补足，但 FK 层应 `(tenant_id, session_id)` 复合外键更安全）
- `service_accounts.api_key_id → api_keys.api_key_id`：有列无 FK 声明
- `connector_bindings.connector_id → connector_configs.connector_id` + `capability_id → business_capabilities.capability_id`：均无 FK
- `documents.kb_id → knowledge_bases.kb_id`：有 FK 标注
- `chunks.doc_id → documents.doc_id`：有 FK 标注

### P2-2. scheduler.py SIGTERM 优雅退出无实现细节
§一 `scheduler.py` 描述"空转调度循环骨架（asyncio loop + SIGTERM 优雅退出）"但无代码级约定。test_entrypoints 要求 <5s 退出，需明确实现方式（`signal.signal(SIGTERM, handler)` + `asyncio.Event` 或 `anyio` 信号）。

### P2-3. 命名不一致
- `service_accounts.sa_id` vs 其他表全称 `service_account_id`
- 建议统一为 `service_account_id` 或全文统一短前缀风格

### P2-4. `encrypted_credentials` 缺所有权字段
无 `owner_type`/`owner_id` 列——无法关联凭据属于哪个实体（service_account? connector_config?）。SEC-002 凭据模型可能需要。

### P2-5. `export_openapi.py` 函数签名未在 §二 列出
§二 仅文字描述其行为，未像其他接口给出完整签名。建议统一格式。

### P2-6. sessions 表缺少 user_id/role_id 外键
`sessions.user_id → users.user_id` 和 `sessions.role_id → roles.role_id` 未标 FK——多租户下 user_id 唯一性限定在 (tenant_id, user_id) 组合内，跨表引用用单列可能指向错误租户的行。RLS 补足但 FK 层应体现约束。

---

## 审查总结

| 等级 | 数量 | 关键项 |
|:---|:---:|:---|
| P0 | 3 | LangGraph 表兼容性、FORCE RLS + seed、spike 循环依赖 |
| P1 | 5 | async env.py、tenant_session 契约、openapi diff、测试覆盖缺口、testcontainers 生命周期 |
| P2 | 6 | FK 约束、SIGTERM 实现、命名、凭据所有权、export signature、sessions FK |

**核心判断**：设计骨架完整，目录结构/接口/DDL/RLS 模板/spike 矩阵均可编码。3 个 P0 均属可修复的设计缺口（非架构推翻），修复后 Gate B PASS。
