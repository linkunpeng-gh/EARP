# Runtime SDK 设计 v1.1

> **定位**：L3 — 实现层设计。定义 Runtime SDK 的接口契约，是应用程序**调用** EARP 平台的入口。
> **目标语言**：Python（第一版）
> **依赖**：L2-01-RUNTIME v1.2（Runtime 规范），earp-sdk-core-py（共享错误码）
> **传输协议**：HTTP/REST（第一版），后续支持 gRPC
> **认证方式**：Bearer JWT（第一版），后续支持 API Key

---

## 1. 设计目标

### 1.1 SDK 定位

| SDK | 使用者 | 用途 |
|:----|:-------|:-----|
| Capability SDK | Capability 开发者 | **写** Capability |
| **Runtime SDK** | **应用程序开发者** | **调用** EARP 平台 |
| Connector SDK | 集成开发者 | **连接**外部系统 |

Runtime SDK 的使用者是**上层应用**——它不关心 Capability 内部怎么实现的，只关心"调用一个 Capability 拿到结果"。

### 1.2 SDK 要解决的问题

| 问题 | SDK 的应对 |
|------|-----------|
| 应用程序需要自己拼 HTTP 请求调 Capability Center | 提供 `session.capabilities.invoke()` 统一编程入口 |
| Session 生命周期管理分散 | 提供 `RuntimeClient.create_session()` / `session.close()` |
| 事件驱动场景需要手动轮询 | 提供 `session.events.subscribe()` 异步订阅 |
| 生产环境需要 tracing、认证、重试 | SDK 自动注入 trace context，支持 auth 中间件 |

### 1.3 SDK 不做什么

- ❌ 不实现 Resolution Engine（Runtime 端负责）
- ❌ 不实现 Planner（Reasoning 层负责）
- ❌ 不实现 Policy Center（Governance 层负责）
- ❌ 不替代 Capability SDK（开发者写 Capability 仍用 Capability SDK）

---

## 2. 架构决策

### 2.1 传输协议：HTTP/REST（第一版）

**决策**：第一阶段用 HTTP/REST + JSON。后续版本加 gRPC 支持。

**理由**：
- HTTP 对 Python 生态友好（httpx 原生支持 async/await）
- REST 容易调试（curl 就可以验证）
- gRPC 的优势（双向流、强类型）在第二阶段引入

### 2.2 认证方式：Bearer JWT

**决策**：Bearer JWT（`Authorization: Bearer <token>`）。API Key 模式在第二阶段支持。

**理由**：
- JWT 可携带身份和权限声明，减少 Runtime 端查询
- 与 Capability Center Registry API 的认证方式一致

### 2.3 流式响应：Server-Sent Events

**决策**：SSE 用于事件流（EventSubscriber）。WebSocket 在第二阶段评估。

**理由**：
- SSE 单向流足以覆盖事件订阅场景
- SSE 基于 HTTP，不需要额外的连接管理

### 2.4 重试策略：指数退避，可配置

**决策**：默认指数退避（3 次，初始 1s），可在 RuntimeClient 构造函数中覆盖。

---

## 3. 开发者体验

### 3.1 最短路径：调用一个 Capability

```python
from earp_sdk_runtime import RuntimeClient

async with RuntimeClient(endpoint="http://runtime:8080", token="...") as client:
    # 自动创建 Session，调用 Capability，关闭 Session
    result = await client.call(
        capability_id="query_equipment_alarm",
        params={"equipment_id": "EQ-001"},
    )
    print(result["alarms"])
```

> **返回值说明**：`invoke()` / `call()` 返回 `dict`，结构对应 Capability 的 output_schema。
> 应用程序没有 Capability 的 Pydantic 模型（由 Capability 开发者维护），所以返回原始 JSON dict。
> 可通过 Discovery API 查询 Capability 的 output_schema 了解返回字段。

### 3.2 Session 模式：多次调用带上下文

```python
async with RuntimeClient(endpoint="http://runtime:8080", token="...") as client:
    # 创建 Session（跨多次调用保持上下文）
    session = await client.create_session(
        user_id="u-001",        # 必传，对齐 L2-01 §6.3
        tenant_id="t-001",
        ttl_seconds=3600,
    )

    # 第一次调用
    r1 = await session.capabilities.invoke("query_equipment_alarm", {
        "equipment_id": "EQ-001",
    })
    alarm_id = r1["alarms"][0]["alarm_id"]

    # 第二次调用（复用 Session 上下文，带幂等键）
    r2 = await session.capabilities.invoke("create_work_order", {
        "equipment_id": "EQ-001",
        "alarm_id": alarm_id,
        "description": "温度传感器异常",
    }, idempotency_key=f"wo-{alarm_id}")

    await session.close()
```

### 3.3 事件订阅模式

```python
async with RuntimeClient(endpoint="http://runtime:8080", token="...") as client:
    session = await client.create_session(user_id="u-001")

    # subscribe 返回 AsyncIterator，可在 async for 中消费
    # 连接断开后自动重连（指数退避，最多 5 次）
    # 使用 AIterator.aclose() 或 break 退出订阅
    async for event in session.events.subscribe(
        event_types=["alarm.critical", "work_order.completed"],
    ):
        print(f"收到事件: {event.type} → {event.data}")
        if event.type == "alarm.critical":
            await session.capabilities.invoke("handle_critical_alarm", event.data)
```

---

## 4. 核心接口

### 4.1 RuntimeClient

```python
from earp_sdk_runtime import RuntimeClient
from earp_sdk_core import CapabilityError

class RuntimeClient:
    """应用程序连接 EARP 平台的入口点。

    Args:
        endpoint: EARP Runtime 的 HTTP 端点。
        token: JWT Bearer Token。
        retry_config: 重试策略（可选，默认指数退避 3 次）。
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:8080",
        token: str = "",
        retry_config: RetryConfig | None = None,
    ):
        ...

    async def create_session(
        self,
        *,
        user_id: str,               # MUST: 对齐 L2-01 §6.3
        tenant_id: str = "",
        ttl_seconds: int = 3600,
        metadata: dict | None = None,
    ) -> "Session":
        """创建一个新的 EARP Session。

        Session 是 Runtime 的外层容器，包住多次 Execution。
        调用方应复用 Session，而不是每次调用都创建新的。
        """
        ...

    async def call(
        self,
        capability_id: str,
        params: dict,
        *,
        user_id: str = "",
        tenant_id: str = "",
        timeout_seconds: int = 30,
        idempotency_key: str | None = None,   # Command 场景建议传入
    ) -> dict:
        """快捷方法：创建临时 Session → 调用 → 关闭。

        适用于一次性调用/Query 场景。
        Command 场景建议使用 Session 模式（传入 idempotency_key）。
        """
        ...

    async def close(self) -> None:
        """关闭客户端，释放连接池。"""
        ...
```

### 4.2 Session

```python
class Session:
    """EARP Session — 持续执行上下文。

    对应 L2-01-RUNTIME §6.3 定义的 Session 契约。
    """

    session_id: str
    tenant_id: str
    user_id: str
    status: str  # "active" | "paused" | "completed"
    created_at: datetime

    capabilities: "CapabilityInvoker"  # 调用 Capability 的统一入口
    events: "EventSubscriber"          # 事件订阅入口

    async def pause(self) -> None:
        """⚠️ 预留接口，当前版本不支持。

        SDK 当前为 Standalone 模式，pause/resume 在 v1.1 实现。
        """

    async def resume(self) -> None:
        """⚠️ 预留接口，当前版本不支持。"""

    async def close(self) -> None:
        """关闭 Session。未完成的 Execution 标记为 cancelled。"""

    async def status_info(self) -> "SessionStatus":
        """获取 Session 当前状态详情。"""
```

### 4.3 CapabilityInvoker

```python
class CapabilityInvoker:
    """调用 Capability 的统一入口。

    每次 invoke 都经过 Resolution Engine（语义匹配 → Graph 遍历 → Policy 过滤 → 可用性检查）。
    这是 Capability SDK 中 MockRuntime 的生产环境对应物。

    返回 dict 而非 Pydantic 模型的原因：
    - 应用开发者没有 Capability 的 Pydantic 模型源码（由 Capability 开发者维护）
    - 返回值结构对应 Capability 的 output_schema（可通过 discovery API 查询）
    """

    async def invoke(
        self,
        capability_id: str,
        params: dict,
        *,
        timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict:
        """调用一个 Capability。

        Args:
            capability_id: Capability 标识。
            params: 输入参数（与 Capability 的 input_schema 对齐）。
            timeout_seconds: 超时。
            idempotency_key: 幂等键（Command 类型建议传入，基于 capability_id + key 去重）。

        Returns:
            dict — 输出结果（与 Capability 的 output_schema 对齐）。
            调用方可根据 output_schema 解析返回字段。

        Raises:
            CapabilityNotFoundError: capability_id 不存在。
            PermissionDeniedError: 当前用户无权限。
            RateLimitExceededError: 超出限流（可重试）。
            CapabilityError: 执行失败（含错误码和可重试标记）。
        """

    async def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> "SearchResponse":
        """搜索可用的 Capability（分页）。

        search() 是**关键词检索**，返回注册表中命中的 Capability。
        与 resolve() 的区别：search = 精确匹配，resolve = 语义理解。
        """

    async def resolve(
        self,
        intent: str,
        domain: str | None = None,
    ) -> list["ResolvedCapability"]:
        """语义解析：输入自然语言意图，返回 Resolution Engine 推荐的能力。

        resolve() 是**语义匹配**，经过 Resolution Engine 的完整流程：
          语义匹配 → Graph 遍历 → Policy 过滤 → 可用性检查
        输出按置信度排序，第一个为推荐候选。

        与 search() 的区别：
        - search: 关键词检索 Registry，返回注册表匹配结果
        - resolve: 语义理解 + 图遍历 + 策略过滤，返回可执行的推荐

        典型场景：
            用户说"查一下这条产线的报警" → resolve("查产线报警", domain="equipment")
            → 返回 [query_equipment_alarm(c=0.95), query_alarm_summary(c=0.70)]
        """
```

### 4.4 EventSubscriber

```python
class EventSubscriber:
    """事件订阅接口。

    使用 SSE（Server-Sent Events）协议。
    连接断开后自动重连（指数退避，最多 5 次）。
    背压策略：消费速度跟不上时，缓冲区满则丢弃最早的事件。
    """

    async def subscribe(
        self,
        event_types: list[str] | None = None,
        *,
        session_id: str | None = None,
    ) -> AsyncIterator["RuntimeEvent"]:
        """订阅事件流。

        Args:
            event_types: 要订阅的事件类型列表。
                         ["alarm.critical", "work_order.completed"]。
                         None = 订阅服务端所有事件。
            session_id: 可选，只订阅特定 Session 的事件。

        Yields:
            RuntimeEvent 事件对象。

        Cancel:
            使用 async for 循环时通过 break 或
            AIterator.aclose() 优雅退出。
        """

    async def publish(
        self,
        event_type: str,
        data: dict,
        *,
        source: str = "sdk",
    ) -> None:
        """发布事件到 EventBus。"""
```

### 4.5 数据模型

```python
@dataclass
class CapabilityInfo:
    """Capability 元信息（来自 Discovery API）。"""
    capability_id: str
    name: str
    description: str
    domain: str
    version: str
    capability_type: str  # "query" | "command"
    tags: list[str]

@dataclass
class ResolvedCapability:
    """Resolution Engine 的推荐结果。"""
    capability_id: str
    confidence: float          # 0-1 置信度
    reason: str                # 推荐理由
    fallback_capabilities: list[str] = field(default_factory=list)

@dataclass
class SearchResponse:
    """分页搜索结果。"""
    results: list[CapabilityInfo]
    page: int
    page_size: int
    total: int

@dataclass
class RuntimeEvent:
    """EventBus 事件。"""
    event_id: str
    event_type: str
    source: str
    data: dict
    timestamp: str
    session_id: str | None

@dataclass
class SessionStatus:
    """Session 状态信息。"""
    session_id: str
    status: str
    created_at: str
    expires_at: str | None
    execution_count: int
    active_executions: int

@dataclass
class RetryConfig:
    """重试策略配置。"""
    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
```

### 4.6 错误映射

```python
# 错误类型定义（在 earp-sdk-core 中新增）
class CapabilityNotFoundError(CapabilityError):
    """capability_id 不存在。不可重试。"""
    ...

class PermissionDeniedError(CapabilityError):
    """当前用户无权限。不可重试。"""
    ...

class RateLimitExceededError(CapabilityError):
    """超出限流。可重试（等待后）。"""
    ...
```

**错误码映射表：**

| Runtime SDK 异常 | CapabilityErrorCode | HTTP Status | 可重试 | 场景 |
|:-----------------|:--------------------|:-----------:|:------:|------|
| `CapabilityNotFoundError` | CAPABILITY_NOT_FOUND | 404 | ❌ | capability_id 不存在 |
| `PermissionDeniedError` | PERMISSION_DENIED | 403 | ❌ | 无权限 |
| `RateLimitExceededError` | RATE_LIMIT_EXCEEDED | 429 | ✅（等待后） | 超出限流 |
| `CapabilityError(code=CONNECTOR_ERROR)` | CONNECTOR_ERROR | 502 | ✅ | 底层 Connector 故障 |
| `CapabilityError(code=BUSINESS_ERROR)` | BUSINESS_ERROR | 422 | ❌ | 业务逻辑拒绝 |
| `CapabilityError(code=TIMEOUT)` | TIMEOUT | 504 | ✅ | 执行超时 |
| `CapabilityError(code=SYSTEM_ERROR)` | SYSTEM_ERROR | 500 | ✅ | 系统内部错误 |

---

## 5. MUST/SHOULD/MAY 约束

| ID | 条款 | 级别 | 验证方式 |
|:---|:-----|:----:|:---------|
| SDKMUST-R-001 | Session 创建请求必须包含 `user_id`（对齐 L2-01 §6.3） | MUST | 缺少 `user_id` 时抛出 TypeError |
| SDKMUST-R-002 | 所有 HTTP 请求必须包含 `Authorization: Bearer <token>` | MUST | 集成测试 |
| SDKMUST-R-003 | 所有 HTTP 请求必须包含 `User-Agent: earp-sdk-runtime/{version}` | MUST | 集成测试 |
| SDKMUST-R-004 | 所有请求必须自动注入 `X-Trace-Id` header（对齐 L2-01 §2.2） | MUST | 集成测试 |
| SDKMUST-R-005 | 调用 `invoke()` 时 SDK 必须发送请求到 Runtime 端点，不直接调 Capability（确保经过 Resolution Engine） | MUST | 集成测试 |
| SDKMUST-R-006 | 错误类型必须对齐 CapabilityErrorCode（见 §4.6 映射表） | MUST | 单元测试 |
| SDKMUST-R-007 | 连接失败时自动重试（指数退避，不超过 `RetryConfig.max_attempts`） | SHOULD | 集成测试 |
| SDKMUST-R-008 | 事件订阅断开后自动重连（最多 5 次） | SHOULD | 集成测试 |
| SDKMUST-R-009 | `call()` 中 `idempotency_key` 未传时，Command 类型应打印警告 | SHOULD | 单元测试 |

---

## 6. 与 Capability SDK 的关系

### 6.1 互补而非重叠

```
              Capability SDK                    Runtime SDK
              ──────────────                    ──────────
定位          写 Capability                     调 Capability
使用者        Capability 开发者                  应用开发者
核心操作      class MyCap extends QueryCapability  session.capabilities.invoke()
测试工具      MockRuntime（本地离线）              MockRuntimeClient（mock Capability Center）
注册          earp register                      不需要
调用          自己写的 Capability                 任何已注册的 Capability
```

### 6.2 共享基础

两个 SDK 共享 `earp-sdk-core-py` 的错误类型和基础模型：

```python
from earp_sdk_core import CapabilityError, ConnectorError
# Capability SDK 和 Runtime SDK 都使用同一套错误码
```

### 6.3 三层结构映射

| Capability 三层结构 | Runtime SDK 对应 | 说明 |
|:-------------------|:----------------|:------|
| `input_schema` | `invoke(params)` 的 params | 调用方按 input_schema 传参 |
| `output_schema` | `invoke()` 的返回值 | 返回 dict 结构按 output_schema。调用方可通过 Discovery API 查询 schema |
| `execution_contract` | 隐含在 invoke 的 timeout/retry 参数中 | 调用方可覆盖（如 `timeout_seconds`） |
| `policy` | 无直接对应 | 调用方不感知 Policy——检查由 Resolution Engine 在服务端执行 |

### 6.4 包依赖

```
earp-sdk-core-py          ← 共享基础（错误码 + 数据模型）
    ↑            ↑
    |            |
earp-sdk-capability-py    ← 写 Capability
    ↑
earp-sdk-runtime-py       ← 调 Capability（只依赖 core，不依赖 capability）
```

---

## 7. 包结构

```
libs/earp-sdk-runtime-py/
├── pyproject.toml              # 依赖: earp-sdk-core, httpx
├── README.md
└── src/earp_sdk_runtime/
    ├── __init__.py              # 公共 API 导出
    ├── client.py                # RuntimeClient 主入口
    ├── session.py               # Session 生命周期管理
    ├── invoker.py               # CapabilityInvoker
    ├── events.py                # EventSubscriber（SSE 协议）
    ├── models.py                # 数据模型（CapabilityInfo, RuntimeEvent 等）
    └── testing/
        ├── __init__.py
        └── mock_runtime.py      # MockRuntimeClient

## 包导出

```python
# src/earp_sdk_runtime/__init__.py
__all__ = [
    "RuntimeClient",
    "Session",
    "CapabilityInvoker",
    "EventSubscriber",
    "CapabilityInfo",
    "ResolvedCapability",
    "SearchResponse",
    "RuntimeEvent",
    "SessionStatus",
    "RetryConfig",
    "CapabilityNotFoundError",
    "PermissionDeniedError",
    "RateLimitExceededError",
]
```

---

## 8. 与现有架构的映射

### 8.1 与 L2-01 Runtime Spec 的映射

| L2 Runtime Spec | Runtime SDK | 说明 |
|:---------------|:------------|:-----|
| §2.2 — Runtime 唯一执行入口 | `session.capabilities.invoke()` 经过 Resolution Engine | SDKMUST-R-005 确保 |
| §2.2 — 同步/异步模式 | `call()` 同步模式；预留 `submit()` 异步模式 | 异步模式 v1.1 |
| §2.2 — Trace | SDK 自动注入 `X-Trace-Id` | SDKMUST-R-004 |
| §3.2 — Context | SDK 自动传递用户身份到请求 | 调用方不感知 |
| §5 — EventBus | `session.events.subscribe()` / `publish()` | SSE 协议 |
| §6.3 — Session 契约 | `Session` dataclass + `create_session()` | 字段对齐，user_id 为 MUST |
| §6.3 — Session 生命周期 | `close()` 实现，`pause()`/`resume()` 预留 | v1.1 实现 |
| §8 — Execution（原） | `CapabilityInvoker.invoke()` | ❌ Decision（新 §8）SDK 不涉及 |
| Resolution Engine | `resolve()` 语义解析入口 | 返回 `ResolvedCapability` |

### 8.2 与 L0 设计哲学的映射

| 理念 | 对齐度 | 说明 |
|:----|:------:|------|
| Runtime First | ✅ | SDK 封装 Runtime 调用入口 |
| Domain First | ✅ | search/resolve 支持 domain 筛选 |
| Capability First | ✅ | 调用方只通过 capability_id + params 调用 |
| Reason-Act 解耦 | ✅ | SDK 不涉及 Reasoning |
| CQRS | ⚠️ | invoke 未区分 Query/Command 路径；通过 idempotency_key 和用户文档弥补 |
| 规范 ≠ 文档 | ✅ | 新增 9 条 SDKMUST-R |

---

## 9. 测试工具：MockRuntimeClient

```python
# src/earp_sdk_runtime/testing/mock_runtime.py

class MockRuntimeClient:
    """模拟 EARP Runtime，用于应用层集成测试。

    行为：
    - 注册 Capability mock handler（类似 MockConnector）
    - invoke() 直接调本地 handler，不经过真实的 Resolution Engine
    - 不依赖任何外部服务（完全离线）
    - 支持模拟错误场景（超时、权限拒绝）
    """

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self.sessions: list[MockSession] = []

    def register(self, capability_id: str, handler: Callable[[dict], dict]):
        """注册一个 mock handler。

        Args:
            capability_id: 要模拟的 Capability ID。
            handler: 接收 params(dict) 返回 result(dict) 的函数。
        """
        ...

    async def create_session(self, *, user_id: str, ...) -> "MockSession":
        """创建 mock Session（不发送网络请求）。"""
        ...

    async def call(self, capability_id: str, params: dict, ...) -> dict:
        """直接调本地 handler（不走网络）。"""
        ...
```

---

## 10. 评审修复记录

| 评审问题 | 修复方式 |
|:---------|---------|
| P0-1 search() 重复定义 | 删除无分页版本，只保留带分页的 search() |
| P0-2 缺少 MUST 条款 | 新增 9 条 SDKMUST-R（5 MUST + 3 SHOULD + 1 MAY） |
| P0-3(→P1) invoke 返回 dict | 添加说明文档解释原因 + 三层结构映射表 |
| P1-1 事件订阅缺连接管理 | 定义重连策略(5次指数退避)、背压策略、cancel 方式 |
| P1-2 call() 缺 idempotency_key | 为 call() 新增 idempotency_key 参数 |
| P1-3 pause/resume 交互未定义 | 标注为"预留接口，当前版本不支持" |
| P1-4 协议决策未定 | §2 新增架构决策章节，确定 HTTP + JWT + SSE |
| P1-5 错误映射缺失 | §4.6 新增错误映射表（7 种异常 × HTTP 码 × 可重试性） |
| P1-6 resolve() 意图不清 | 定义 ResolvedCapability 数据类，说明 search vs resolve 区别 |
| P1-7 MockRuntime 缺失 | §9 新增 MockRuntimeClient 设计和接口 |
| P2-1 三层结构映射 | §6.3 新增 Capability 三层 ↔ Runtime SDK 映射表 |
| P2-2 user_id 空字符串 | create_session() 的 user_id 改为必传参数（去掉默认值） |
| P2-3 缺少 __all__ | §7 新增完整导出清单 |
