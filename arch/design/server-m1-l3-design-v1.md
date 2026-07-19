# Server M1 — L3 实现设计

**文档编号：DESIGN-SERVER-M1-L3**
**版本：v1.1（Gate B r1 修复）**

> **v1.1 变更：** P0-1 EventBus publish 语义定为 `asyncio.create_task` fire-and-forget（PRD "异步不阻塞 invoke 返回"一致）；P0-2 invoke 流程+StepRunner 明确 executions 行写入责任（端点在 invoke 前创建 pending 行，StepRunner 更新 completed/failed）；P1-3 补 connector.py 模块（Connector 接口+tenacity 装饰器位置）；P1-4 StepResult.status 补 "retrying"；P1-5 CheckpointStore.write 补 channels 参数；P2 全修。

---

# 一、目录结构（相对 M0 增量）

```
apps/earp-server/src/earp_server/
├── gateway/
│   ├── auth.py              # JWT 中间件 + 租户/角色上下文注入
│   └── input_guard.py       # 注入模式黑名单 Body 过滤
├── runtime/
│   ├── session_service.py   # Session CRUD（create/get/close）
│   └── invoke.py            # POST /v1/sessions/{id}/invoke 路由
├── connector.py           # Connector 接口 + tenacity 重试（P1-3 补充）
├── orchestrator/
│   ├── step_runner.py       # Step/StepResult + 三形态接口
│   └── layers.py            # AuditLayer + Layer 基类
├── infra/
│   ├── checkpoint.py        # CheckpointStore（写 3 表）
│   └── eventbus.py          # 进程内 EventBus
├── audit/
│   └── consumer.py          # EventBus 订阅 → db 写入
└── capability/
    └── registry.py          # 注册 + 精确发现端点
```

---

# 二、接口签名

## 2.1 Gateway

```python
# auth.py
async def jwt_middleware(request: Request, call_next) -> Response
# 解码 Authorization: Bearer <token> → request.state.user_id/tenant_id/role_id
# 无/错 token → 401；验证失败 → 403

# input_guard.py
def sanitize_body(body: dict) -> dict | None
# 扫描注入模式（UNION SELECT/DROP TABLE/1=1/xp_cmdshell 等），命中→None
```

## 2.2 Runtime

```python
# session_service.py
async def create_session(...) -> SessionResponse
async def get_session(session_id) -> SessionResponse | None
async def close_session(session_id) -> None

# invoke.py
@router.post("/v1/sessions/{session_id}/invoke", response_model=InvokeResponse)
async def invoke(session_id, request: InvokeRequest, state=Depends(jwt_middleware))
# 1. 通过 request.state 获取 ctx (tenant_id/role_id/user_id)
# 2. 解析 capability_id → 从 Registry 获取 capability 定义
# 3. 构造 execution 行（status=pending, execution_id=UUID）INSERT → executions 表
# 4. 构造 Step → step_runner.invoke(step, layers=[AuditLayer()])
# 5. StepRunner 返回后更新 execution 行 status=completed/failed
# 6. 返回 InvokeResponse(execution_id, status, result, checkpoint_id)
```

## 2.3 Orchestrator

```python
# step_runner.py
@dataclass
class Step:
    step_id: str
    capability_call: dict        # {capability_id, input, tenant_id}
    retry_config: RetryConfig
    timeout_seconds: int | None

@dataclass
class StepResult:
    step_id: str
    status: Literal["completed", "failed", "retrying"]
    output: dict | None
    error: str | None
    latency_ms: int
    checkpoint_id: str | None

@dataclass  
class StepEvent:  # stream/batch 事件类型（接口层锁定）
    step_id: str
    event_type: Literal["step_started", "step_completed", "step_failed", "checkpoint_written"]
    data: dict | None

class StepRunner:
    async def invoke(self, step: Step, *, layers: list[Layer]) -> StepResult:
        # 内部: execution 行已由 invoke 端点预创建 (status=pending)
        # 执行 capability_call → tenacity retry (Connector) → AuditLayer 前后钩子
        # → CheckpointStore.write (state + channels) → 更新 execution 行 status=completed/failed
    async def stream(self, step: Step) -> AsyncGenerator[StepEvent]: raise NotImplementedError("M6 streaming")
    async def batch(self, steps: list[Step]) -> list[StepResult]: raise NotImplementedError("M5 multi-step")

# layers.py
class Layer(Protocol):
    async def before_step(self, ctx: InvokeContext) -> None: ...
    async def after_step(self, ctx: InvokeContext, result: StepResult) -> None: ...

@dataclass
class InvokeContext:
    """Passed to every Layer. Fields stable across M1-M5."""
    tenant_id: str
    execution_id: str
    session_id: str
    user_id: str
    step: Step

class AuditLayer:
    # before_step → publish EXECUTION_STARTED CloudEvent
    # after_step → publish EXECUTION_COMPLETED/FAILED CloudEvent via EventBus

# M2: PolicyLayer goes here (PRD §3.1 #7 挂载位)
class PolicyLayer:  # type: ignore[empty-body] — M2 fills implementation
    """Placeholder——M2 implements permissions/data_scope/rate-limit evaluation."""
    pass
```

## 2.4 Checkpoint

```python
# infra/checkpoint.py
class CheckpointStore:
    def __init__(self, engine: AsyncEngine): ...
    async def write(self, execution_id, session_id, tenant_id, state: dict, channels: dict[str, bytes]) -> str:
        # 写 checkpoints 行（state JSONB 小快照，channel_versions 记录 channels 键名+版本）
        # 写 checkpoint_blobs 行（每个 channel: (channel_name, version, blob BYTEA)）
        # 不写 checkpoint_writes（M1 单步）
        # 返回 checkpoint_id
```

## 2.5 EventBus + Audit

```python
# infra/eventbus.py
@dataclass
class CloudEvent:
    specversion = "1.0"; type: str; source: str; id: str; time: str
    tenant_id: str; datacontenttype = "application/json"; data: dict
    # subject 字段为 L3 设计扩展（CloudEvents 1.0 可选字段），用于事件路由。
    # PRD §4.4 未含此字段——M1 实现中默认为空字符串。

class EventBus:
    def publish(self, event: CloudEvent) -> None: ...
    # fire-and-forget: 使用 asyncio.create_task(handler(event)) 调度所有订阅者，
    # 不阻塞 invoke 返回（PRD §3.1 "异步不阻塞 invoke 返回"）。进程内丢失风险可接受
    # ——订阅者是同一进程的 audit_handler，失败写入 stderr 日志。
    def subscribe(self, event_type: str, handler: Callable[[CloudEvent], Awaitable[None]]) -> None: ...

# audit/consumer.py
async def audit_handler(event: CloudEvent) -> None:
    # INSERT INTO audit_logs (tenant_id, event_type, detail=event.data JSONB, ...)
    # app startup 时: eventbus.subscribe("earp.execution.*", audit_handler)
```

## 2.6 Capability

```python
# capability/registry.py
@router.post("/capabilities", status_code=201)
async def register(cap: CapabilityDefinition, state=Depends(jwt_middleware)): ...
@router.get("/capabilities")
async def discover(q: str | None = None, state=Depends(jwt_middleware)):
    # 精确匹配 capacity_id LIKE '%q%'，无 pgvector
```

## 2.7 Connector（P1-3 补充）

```python
# connector.py
class ConnectorError(Exception): ...

class Connector:
    """Capability 执行通道。tenacity 重试内建于 execute() 方法。"""
    @retry(retry=retry_if_exception_type(ConnectorError),   # from tenacity import retry
           wait=wait_exponential_jitter(),
           stop=stop_after_attempt(3))   # max 3 total attempts (1 initial + 2 retries)
    async def execute(self, capability_call: dict) -> dict:
        # 根据 capability_call 中的 adapter_type 调用对应的 adapter
        # M1 demo: echo adapter 原样返回 input
        ...
    def _on_retry(self, retry_state) -> None:
        # 发布 RETRYING CloudEvent → EventBus（供 AuditLayer 记录）
        ...

---

# 三、Checkpoint 落盘策略（3 表模型的具体语义）

| 表 | M1 行为 | M5 扩展 |
|:---|:-------|:-------|
| checkpoints | invoke 完成后写入 1 行：`state` JSONB 含 capability_call 输入/输出摘要 | 多步执行每步写 checkpoint；parent_checkpoint_id 链式追溯 |
| checkpoint_blobs | invoke 完成后写入 ≥1 行：每个 channel 的完整值作为 BYTEA blob | 同 blob 版本去重（`(thread_id, channel, version)` 唯一） |
| checkpoint_writes | **不写入**（M1 单步无待处理写操作队列） | 多步并发时记录每个 task 的未提交写入，恢复时回放 |

---

# 四、JWT 令牌管理

- Dev：HS256 + 硬编码 secret `"earp-dev-secret-change-in-production"`（M1 documented limitation）
- Prod：RS256 + 环境变量 `EARP_JWT_PUBLIC_KEY`
- 中间件每次请求解码，不维护会话状态（stateless JWT）
- token payload：`{"sub": user_id, "tenant_id": "...", "role_id": "...", "exp": ...}`

---

# 五、AC-09 SDK 集成策略

当前 runtime-py 37 测试分为三组：

| 测试文件 | 数量 | M1 集成目标 |
|:---------|:----:|:----------|
| test_mock_runtime.py | 16 | 全 PASS（MockRuntime 的断言集打真实服务端每一条都过） |
| test_invoker_http.py | 12 | 尽量 PASS；涉及流式/批处理/异常路径的以 `pytest.skip` 标记并说明理由 |
| test_security.py | 9 | 全 PASS（JWT 安全测试与真实服务端交互） |

**集成测试 CI 步骤**：
1. docker compose up pg → alembic upgrade head → queue_schema
2. `uv run uvicorn earp_server.main:app` 后台启动
3. `uv run pytest libs/earp-sdk-runtime-py/tests/ --earp-endpoint http://localhost:8000 -v`（新增 `--earp-endpoint` fixture 让现有测试指向真实服务端）
4. 服务端 shutdown + 清理 testcontainers PG

---

# 六、M0 顺手修 F1-F5 设计

| # | 改动 | 关键点 |
|:-:|:-----|:-----|
| F1 | core-py version → 0.1.0 | 同步下游 >=0.1.0 约束；更新 pyproject.toml |
| F2 | CI matrix +capability | .github/workflows/test.yml 加一行 |
| F3 | utcnow 弃用 | `datetime.utcnow()` → `datetime.now(datetime.UTC)` 两处（core/session.py + runtime/session.py） |
| F4 | enqueue_in_session | TaskQueue Protocol 增加 `async def enqueue_in_session(self, session: AsyncSession, task_name: str, payload: dict) -> str`；procrastinate 实现走同连接 INSERT |
| F5 | RLS 全表矩阵 + 幂等 | test_rls.py 扩展全表数据级验证（24 表逐表 INSERT+SELECT+UPDATE+DELETE 断言）；test_migrations.py 增加 queue_schema 二次执行幂等测试 |

---

# 七、测试策略

| 测试 | 覆盖 AC | 要点 |
|:-----|:-------:|:-----|
| test_jwt_auth.py | AC-01,05 | 有效/缺失/过期 token ×3 场景 |
| test_sessions_api.py | AC-01,02,03,08 | create→get→invoke→close 全生命周期 httpx |
| test_invoke_checkpoint.py | AC-04,05 | invoke 后 audit_logs + checkpoints + blobs 表断言 |
| test_step_runner.py | AC-06,07 | invoke 正常/stream NotImplemented/batch NotImplemented/Connector retry 触发 |
| test_eventbus_audit.py | AC-04 | CloudEvent 格式/发布→订阅/audit_logs 写入 |
| test_capability_registry.py | AC-10 | 注册→精确发现 |
| test_input_guard.py | AC-11 | SQL 注入/命令注入 payload→400 |
| SDK 集成（CI 步骤） | AC-09 | runtime-py 37 测试打真实服务端 |
| RLS 全表矩阵 + 幂等 | AC-12 | F5 |
| SDK 版本回归 | AC-12 | F1-F4 均被既有/新增 CI 覆盖 |
