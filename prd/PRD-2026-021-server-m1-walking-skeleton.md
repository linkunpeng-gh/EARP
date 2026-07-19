# PRD-2026-021 v1.0

## M1 — 最小闭环 Walking Skeleton

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-021 |
| **Feature** | 服务端里程碑 M1：Gateway JWT 认证+中间件、Runtime Session 生命周期+invoke+状态机+Checkpoint 最小落盘、Step Runner 三形态接口+Orchestrator Layer 拦截器链(AuditLayer)、Connector tenacity 重试、Capability Registry 注册+发现+demo、进程内 EventBus+Audit 消费。SDK 集成回归全绿。 |
| **对齐规范** | Runtime Spec v1.3 §4.1（状态机）+ §6.3（Session）；EventBus Spec v1.1；Audit Spec v1.1/v1.2；Capability Spec v1.4；Security Spec v1.1 §3.1（JWT）；Tenant Spec v1.2 §5.4（role_id） |
| **前置依赖** | M0（apps/earp-server 骨架+DDL 基线，commit d466103） |
| **优先级** | **P0**（最小闭环——首次端到端跑通 SDK→服务端→DB 全链路） |
| **版本** | v1.1（Gate A r1 修复） |
| **日期** | 2026-07-19 |

> **v1.1 变更：** P1-1 §3.1 补 close 端点 + US-09；P1-2 Checkpoint 行加 checkpoint_writes 说明（M1 单步无需写入，已建表，M5 启用）；P1-3 SDK 测试数 27→37（test_mock_runtime 16+invoker_http 12+security 9）；P1-4 US 拆分为 9 个（US-02 GET session / US-03 invoke）；P1 顺手修 P2-1~P2-4。

---

## 1. 背景

M0 交付了工程骨架和数据库基线，但服务端还无法接受任何真实业务请求（/v1/sessions 返回 501）。M1 目标是把这条链路从头到尾打通——runtime-py SDK 的 `create_session()` → `invoke()` 打真实服务端全绿。这是整个 EARP 服务端的**最小可运行形态**，也是"架构性决定一次到位"的关键里程碑（Step Runner 三形态、Layer 拦截器链、Checkpoint 最小落盘——均在 M1 定型，后续里程碑只扩展不重构）。

## 2. 用户故事

| US | 描述 | 类型 |
|:--:|:-----|:----:|
| US-01 | SDK 调用 `client.create_session(user_id, tenant_id, role_id)` → 服务端创建 Session 并返回 session_id | 正常 |
| US-02 | `GET /v1/sessions/{id}` 返回 Session 状态 | 正常 |
| US-03 | `POST /v1/sessions/{id}/invoke` 执行 demo capability 并返回 InvokeResult | 正常 |
| US-04 | `POST /v1/sessions/{id}/close` → Session 状态变为 closed | 正常 |
| US-05 | JWT 缺失/过期/伪造 → 401；无对应 tenant/role → 403 | 异常 |
| US-06 | 每次 invoke 完成后 audit_logs 自动记录 EXECUTION_COMPLETED 事件（含 checkpoint_id）——AuditLayer 不侵入业务代码 | 横切 |
| US-07 | Step Runner 接口锁定 `invoke` / `stream` / `batch` 三形态（M6 流式只换传输层不动接口） | 架构 |
| US-08 | invoke 完成后 checkpoint 最小落盘（checkpoints + checkpoint_blobs 写入；checkpoint_writes 已建表但 M1 单步无需写入，M5 多步恢复时启用）| 架构 |
| US-09 | Connector 调用失败自动 retry（tenacity），成功无额外延迟 | 可靠性 |
| US-10 | InputGuard 拦截注入攻击 payload→400（无旁路，所有请求必经）| 安全 |
| US-11 | SDK 集成：runtime-py 全部 37 个测试打真实服务端通过（替代 MockRuntime） | 契约 |

## 3. 范围

### 3.1 包含（本 PRD 交付）

| # | 模块 | 内容 |
|:-:|:-----|:-----|
| 1 | Gateway | JWT 中间件（HS256 dev / RS256 prod，解码→注入 tenant_id/role_id/user_id 到 request.state）；InputGuard 基础校验（注入攻击模式黑名单）|
| 2 | Runtime | `POST /v1/sessions` 创建 Session（状态 active）→ DB sesssions 行 |
| 3 | Runtime | `GET /v1/sessions/{id}` 返回 Session 状态 |
| 4 | Runtime | `POST /v1/sessions/{id}/invoke` 执行 capability_call → Orchestrator 编排 → 写 executions 行（status 从 pending→completed/failed） → 返回 InvokeResult |
| 5 | Runtime | `POST /v1/sessions/{id}/close` → Session 状态 active→closed | 
| 6 | Orchestrator | Step Runner 接口：`invoke(Step)` / `stream(Step)` / `batch([Step])` 三形态；M1仅实现 invoke 同步路径，stream/batch 预留接口抛 NotImplemented；stream 返回类型 `AsyncGenerator[StepEvent]` 在接口层锁定 | 
| 7 | Orchestrator | Layer 拦截器链：`AuditLayer`（EXECUTION_STARTED/COMPLETED/FAILED 事件→EventBus 发布）；接口留 PolicyLayer 挂载位（M2 填充） |
| 8 | Checkpoint | invoke 完成后写入 checkpoints 行 + checkpoint_blobs 行（state 小快照 JSONB + channel 值 BYTEA）；checkpoint_writes 已建表但 M1 单步无需写入（M5 多步恢复时启用） |
| 9 | EventBus | 进程内实现（发布/订阅），对齐 EventBus Spec v1.1 CloudEvents 1.0 消息格式 |
| 10 | Audit | 订阅 EventBus → audit_logs 写入（异步，不阻塞 invoke 返回） |
| 11 | Capability | 注册 demo Query Capability "echo"（输入原样返回）；精确发现（GET /capabilities?q=echo） |
| 12 | Connector | tenacity 重试（retry=retry_if_exception_type(ConnectorError), wait=wait_exponential_jitter, max_attempts=3） |

### 3.2 M0 顺手修清单（本 PRD 一并交付）

| # | 来源 | 内容 |
|:-:|:-----|:-----|
| F1 | task-log #16 ① | earp-sdk-core 版本 `0.1.0.dev0` → `0.1.0`；下游 `>=0.1.0` 约束一致 |
| F2 | task-log #16 ② | CI matrix 加入 `earp-sdk-capability-py`（90 测试进 CI） |
| F3 | task-log #16 ③ | runtime SDK `datetime.utcnow()` → `datetime.now(datetime.UTC)`，消 warnings |
| F4 | task-log #16 ④ | TaskQueue 增加 `enqueue_in_session(session, task_name, payload)` API（同会话事务性入队） |
| F5 | task-log #16 ⑤ | RLS 全表数据级矩阵测试 + queue_schema 幂等测试 |

### 3.3 不含（后续里程碑）

- stream/batch 真实实现（M6 流式推送才需要——M1 接口锁定、实现留 NotImplemented）
- PolicyLayer / OutputFilterLayer（M2）
- Capability 语义发现（M4 pgvector）
- 多步编排 / Saga 补偿 / REPLANNING（M5）
- Redis 限流（M2）
- WebSocket 流式推送（M6）
- human_approval 暂停/恢复（M5）
- 并发 token 校验（M1 单会话内单线程，暂不做锁）

## 4. 核心数据结构

> 以下为 M1 新增/修改的数据结构。既有表（sessions/executions/audit_logs/checkpoints 等）在 M0 DDL 中已建，无需迁移。

### 4.1 Session 状态机

```
active ──invoke──→ active  （invoke 完成后保持 active）
  │
  └──close──→ closed
  │
  └──expired──→ expired （TTL 到期后标记）
```

### 4.2 InvokeRequest / InvokeResponse

```python
class InvokeRequest(BaseModel):
    capability_id: str
    input: dict[str, Any]

class InvokeResponse(BaseModel):
    execution_id: str
    status: Literal["completed", "failed"]
    result: dict[str, Any] | None
    error: dict | None
    checkpoint_id: str | None
```

### 4.3 Step / StepResult（Orchestrator 接口锁定）

```python
@dataclass
class Step:
    step_id: str
    capability_call: CapabilityCall         # 已有 M0 DDL 列
    retry_config: RetryConfig | None = None
    timeout_seconds: int | None = None

@dataclass
class StepResult:
    step_id: str
    status: Literal["completed", "failed", "retrying"]
    output: dict | None
    error: str | None
    latency_ms: int
```

### 4.4 EventBus CloudEvent 格式（对齐 EventBus Spec v1.1）

```python
@dataclass
class CloudEvent:
    specversion: str = "1.0"
    type: str                     # "earp.execution.completed" 等
    source: str                   # "earp-server/runtime"
    id: str                       # UUID
    time: str                     # ISO 8601
    tenant_id: str
    datacontenttype: str = "application/json"
    data: dict[str, Any]          # 负载：execution_id/checkpoint_id/session_id等
```

## 5. 验收条件

| ID | 描述 | 验证方式 |
|:--:|:-----|:---------|
| AC-01 | `POST /v1/sessions` 创建成功返回 session_id + 201，无/错 JWT→401，无权→403 | httpx test |
| AC-02 | `GET /v1/sessions/{id}` 返回 session 状态，不存在的 id→404 | httpx test |
| AC-03 | `POST /v1/sessions/{id}/invoke` 调用 demo echo capability 返回结果 | httpx test |
| AC-04 | invoke 完成后 audit_logs 有 EXECUTION_COMPLETED 记录含 checkpoint_id | 集成测试 |
| AC-05 | checkpoints + checkpoint_blobs 表在 invoke 后有数据（一行 checkpoint，≥1 行 blob） | 集成测试 |
| AC-06 | Step Runner 三个接口均可 import 且 invoke 可正常调用，stream/batch 抛 NotImplementedError | 单元测试 |
| AC-07 | Connector 调用失败（mock 抛错）后重试 3 次后抛出——audit_logs 有 FAILED 记录 | 单元测试 |
| AC-08 | `/v1/sessions/{id}/close` → Session status 变为 closed | httpx test |
| AC-09 | **SDK 集成：runtime-py 全部 37 个测试打真实服务端通过** | pytest（testcontainers） |
| AC-10 | demo echo capability 通过 `GET /capabilities?q=echo` 可发现 | httpx test |
| AC-11 | InputGuard 拦截含 SQL 注入模式的 payload→400（Body 级过滤） | httpx test |
| AC-12 | M0 遗留修复 F1-F5 全部兑现 | pytest 全绿（含新增矩阵+RLS 全表+幂等） |

## 6. 依赖

| 依赖 | 状态 |
|------|:----:|
| M0（apps/earp-server + DDL，commit d466103） | ✅ |
| PyJWT / python-jose（JWT 签发与校验） | ⏳ M1 安装 |
| earp-sdk-runtime-py（27 测试用作集成验收） | ✅ 已有 |
| earp-sdk-core-py（AuditEvent 模型复用） | ✅ 已有 |
| tenacity（M0 已安装） | ✅ |
| M0 顺手修 F1：需更新 libs/earp-sdk-core-py/pyproject.toml 版本号 | ⏳ 待改动 |

## 7. 不做（明确排除）

- stream / batch 真实实现（见 §3.3）
- Capability 语义发现 / pgvector 查询（M4）
- Policy / OutputFilter Layer（M2）
- Redis 接入（M2 限流）
- WebSocket（M6）
- Multi-Agent / human_approval（M5）
- Session TTL 自动过期（M5 定时器——M1 只做 DB 标记）

## 8. 验收总结表

| # | 检查项 | 状态 |
|:-:|--------|:----:|
| 1 | US 完整（正常+异常+架构+契约） | ✅ 8 个 US |
| 2 | AC 可测试（全部自动化） | ✅ 12 条 |
| 3 | 依赖完整 | ✅ 6 项 |
| 4 | P0 合理 | ✅ 最小闭环 |
| 5 | M0 遗留包含 | ✅ 5 项（F1-F5） |
| 6 | US 覆盖（正常+异常+架构+安全+契约） | ✅ 11 个 US |
| 7 | 与冻结规范无矛盾 | ✅ |

## 9. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P1-1 | close 端点缺范围行+US | §3.1 补 #5 close + US-04 |
| P1-2 | checkpoint_writes 未说明 | §3.1 #8 + US-08 明确"已建表 M1 无需写入 M5 启用" |
| P1-3 | SDK 测试数 27 实为 37 | AC-09 + US-11 更正为 37 |
| P1-4 | US-02 合并 GET+invoke | 拆 US-02(状态) + US-03(invoke)，整体从 8→11 |
| P2-1 | Capability 测试数 114→90 | F2 更正 |
| P2-2 | InputGuard 无对应 US | 新增 US-10 |
| P2-3 | stream 返回类型未锁定 | §3.1 #6 补 `AsyncGenerator[StepEvent]` |
| P2-4 | executions 写入未列 | §3.1 #4 补"写 executions 行 status pending→completed/failed" |
