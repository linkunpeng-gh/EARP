# EARP Server M0 Gate C 代码审查

**审查范围**: 16 文件（FastAPI 工厂、配置、异步 DB 辅助函数、TaskQueue 协议/impl、队列 schema、3 个进程入口、OpenAPI 导出、sessions schema、alembic env + 0001_baseline DDL、procrastinate 尖峰测试、testcontainers conftest、RLS + 迁移测试）  
**前置验证**: 14/14 pytest 全绿、spike 4/4 PASS、ruff/pyright strict/import-linter/squawk 全通过、openapi 字节稳定

---

## P1 — 应在 M1 前修复

### 1. worker.py:23-47 — 连接泄漏：`queue.close()` 异常路径未执行

```python
# src/earp_server/entrypoints/worker.py
async def _run() -> int:
    settings = Settings()
    init_all(settings)
    queue = ProcrastinateTaskQueue(settings)
    await queue.open()          # 打开连接池
    await queue.ensure_schema() # 如果这里抛异常...
    # ... signal handlers, run_worker ...
    await queue.close()         # 永远不会执行!
```

**漏洞**: `queue.open()` 成功但 `ensure_schema()` 或 `run_worker()` 抛异常时，procrastinate 连接池泄漏。进程退出后由 OS 回收，但若未来重构为长生命周期调用则累积。

**修复**:
```python
async def _run() -> int:
    queue = ProcrastinateTaskQueue(Settings())
    try:
        await queue.open()
        await queue.ensure_schema()
        # ... signal + worker logic ...
    finally:
        await queue.close()
```

---

### 2. db.py:33 — `tenant_session` 无 `tenant_id` 输入校验

```python
# src/earp_server/infra/db.py
async def tenant_session(engine: AsyncEngine, tenant_id: str) -> AsyncGenerator[AsyncSession]:
```

**漏洞**: 若调用方传入空字符串 `""`，`SET LOCAL earp.tenant_id = ''` 会成功执行，RLS 策略匹配 `tenant_id = ''` 的行（实际不存在），导致所有操作静默返回空集。虽 API 层 Pydantic 有 `min_length=1` 校验，但此函数作为底层基础设施应自卫。

**修复**:
```python
if not tenant_id or not tenant_id.strip():
    raise ValueError("tenant_id must be non-empty")
```

---

### 3. task_queue.py:40-48 — `ensure_schema` TOCTOU 竞态

```python
# src/earp_server/infra/task_queue.py
async def ensure_schema(self) -> None:
    rows = await self._app.connector.execute_query_one_async(
        "SELECT to_regclass('public.procrastinate_jobs') AS reg"
    )
    if rows["reg"] is None:  # 两个 worker 同时看到 None
        await self._app.schema_manager.apply_schema_async()  # 并发 DDL
```

**漏洞**: 两个 worker 进程同时启动时，都可能看到 `reg IS NULL` 并尝试 `CREATE TABLE`。procrastinate 的 DDL 可能有 `IF NOT EXISTS` 保护，但不能保证所有 DDL 语句安全。

**修复**: 使用 advisory lock 或让部署编排工具（systemd/K8s init container）确保单实例初始化。`queue_schema.py` 已提供单独入口，推荐从 worker 中移除 `ensure_schema()` 调用。

---

### 4. 0001_baseline.py — 缺失 3 个自引用外键

| 表 | 列 | 缺失 FK |
|---|---|---|
| `org_units` | `parent_id` | → `org_units(org_unit_id)` |
| `checkpoints` | `parent_checkpoint_id` | → `checkpoints(checkpoint_id)` |
| `business_capabilities` | `fallback_capability_id` | → `business_capabilities(capability_id)` |

**修复**: 在 DDL 中添加 `REFERENCES` 约束（允许 NULL）。

---

### 5. 0001_baseline.py — `chunks.kb_id` 与 `conversations.user_id` 缺失外键

```sql
-- chunks 表：kb_id 为普通列，但 documents 有 kb_id，chunks 有 doc_id
-- 可能导致 chunk.kb_id ≠ document.kb_id
chunks.kb_id → knowledge_bases(kb_id)  -- 缺失

-- conversations 表：user_id 无 FK
conversations.user_id → users(user_id)  -- 缺失
```

**修复**: 在 DDL 中添加 `REFERENCES` 约束。

---

### 6. 0001_baseline.py:72 — `policy_bindings` 主键缺少 `tenant_id`

```sql
CREATE TABLE policy_bindings (
    policy_id   VARCHAR(64) NOT NULL REFERENCES policies (policy_id),
    entity_type VARCHAR(24) NOT NULL,
    entity_id   VARCHAR(64) NOT NULL,
    tenant_id   VARCHAR(64) NOT NULL,
    PRIMARY KEY (policy_id, entity_type, entity_id)  -- 无 tenant_id!
);
```

**漏洞**: 依赖 `policy_id` 全局唯一（UUID），但 `entity_id` 可能跨租户重复（如两个租户都有 `user-1`）。若未来某些表允许非 UUID 的 `entity_id`，可能导致跨租户主键冲突。`connector_bindings` 表主键包含了 `tenant_id`，此处不一致。

**修复**:
```sql
PRIMARY KEY (policy_id, entity_type, entity_id, tenant_id)
```

---

### 7. task_queue.py:68-73 — `enqueue` 可创建未注册任务的 job

```python
async def enqueue(self, task_name: str, payload: dict[str, Any], *, scheduled_at=None) -> str:
    deferrer = self._app.configure_task(name=task_name, schedule_at=scheduled_at)
    job_id = await deferrer.defer_async(**payload)
    return str(job_id)
```

**漏洞**: `configure_task` 不验证 `task_name` 是否已注册（task 注册在 worker 进程）。若 API 进程调用 `enqueue('nonexistent_task', ...)`, job 入库但 worker 执行时失败 → 静默数据丢失。

**修复**: M1 时在 enqueue 前增加任务名验证（维护已注册任务列表或调用 procrastinate 的 task 查询接口），或将 job 失败计入审计日志。

---

### 8. 测试覆盖盲区

| 盲区 | 位置 | 说明 |
|---|---|---|
| RLS 仅覆盖 4/24 表 | `test_rls.py:42` | 只测了 sessions/executions/audit_logs/documents |
| 无 UPDATE/DELETE RLS 测试 | `test_rls.py` | 仅测试 SELECT + INSERT 隔离 |
| 无 `earp.tenant_id` 未设置时的行为测试 | — | 未验证 GUC 未设置时所有操作被拒绝 |
| 无 `queue_schema.apply` 幂等性测试 | — | 第二次运行是否报错 |
| 无 `check_db` 失败路径测试 | — | `/ready` 返回 503 的路径 |
| `policy_bindings`/`connector_bindings` 未测 | — | 连表约束的跨租户完整性 |

**修复**: M1 扩展 RLS 测试矩阵（至少覆盖 polymorphic 关联表 + 自引用表），增加 `FORCE RLS` 生效验证。

---

### 9. spike/procrastinate_spike.py:102-129 — S4 场景未真实测试 procrastinate 事务入队

```python
# 直接用 raw SQL INSERT INTO procrastinate_jobs, 绕过 defer_async
await conn.execute(insert_job)
```

**漏洞**: S4 验证的是 PostgreSQL 事务行为（两个 raw INSERT 在同一事务中原子提交/回滚），而非 procrastinate 的 `defer_async` 能否参与调用方事务。procrastinate 默认从连接池取新连接，`defer_async` 并不在调用方事务中执行。如需事务入队，需显式传递 `connector` 参数。

**修复**: 重写 S4 验证为使用 procrastinate 的 `defer_async` + 显式 connection 传递，或明确文档说明当前架构不支持事务入队（M0 决策记录）。

---

## P2 — 迭代中改进

1. **db.py:33** — `build_session_factory` 每次调用 `tenant_session` 时重复创建，建议提取为模块级单例或 engine 属性。

2. **config.py:17-18** — 默认数据库密码硬编码（`earp_app:earp_app`, `postgres:postgres`），生产部署时需通过环境变量覆盖。建议增加启动时密码默认值警告。

3. **main.py:36** — `/ready` 端点返回类型 `-> Any` 不一致（可返回 `dict` 或 `JSONResponse`），建议统一为 `Response` 或显式声明 `Union`。

4. **scheduler.py:13** — `TICK_SECONDS = 1.0` 纯空闲循环每秒轮询浪费 CPU，建议改为 30s 或使用 PG LISTEN/NOTIFY 驱动。

5. **0001_baseline.py:122** — `uq_sessions_tenant_session UNIQUE (tenant_id, session_id)` 冗余：`session_id` 已是 PRIMARY KEY，全局唯一自动满足此约束。保留无错但增加维护成本（额外索引）。

6. **worker.py:31-34** — `add_signal_handler` 不支持 Windows（ProactorEventLoop），若需跨平台部署需增加条件判断。

7. **queue_schema.py:29-30** — `_GRANTS` 与 `0001_baseline.py:_ROLE_AND_GRANTS` 重复授权 `earp_app`，虽幂等但维护两处相同逻辑，建议仅保留 alembic 侧。

8. **test_rls.py:69** — `pytest.raises(Exception, match="row-level security")` 异常消息可能在 PostgreSQL 大版本间变化（hyphen 有无），建议匹配 `row.level.security` 正则。

9. **export_openapi.py:15-16** — `json.dumps` → `json.loads` → `yaml.safe_dump` 的 JSON 往返可能丢失非 JSON 类型（如 `datetime`），当前 OpenAPI spec 全是 JSON 兼容类型故安全，但注释中应注明此假设。

10. **0001_baseline.py:88-89** — `service_accounts.api_key_id` 可空但 `api_keys` 表中无 `service_account_id` 回引，无法反向查询某个 API key 属于哪个 service account。

---

## 总结

| 等级 | 数量 | 关键主题 |
|---|---|---|
| P0 | **0** | M0 步行骨架未发现阻塞性问题 |
| P1 | **9** | 连接泄漏、输入校验缺失、TOCTOU 竞态、外键/主键缺口、测试盲区、spike 验证失真 |
| P2 | **10** | 代码异味、性能小优化、跨平台兼容、文档/注释改进 |

**整体评价**: M0 代码质量高。双角色 RLS 策略正确实施、架构层次清晰、测试基建扎实。P1 中外键缺口和测试覆盖盲区建议在 M1 表结构稳定后优先处理；连接泄漏修复成本极低，建议立即纳入。卡点通过。
