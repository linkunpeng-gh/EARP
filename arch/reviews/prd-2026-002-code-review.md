# PRD-2026-002 代码评审报告

## Runtime SDK — Python 第一版

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-002 |
| **Feature** | Runtime SDK（Python） |
| **代码仓库** | `earp-sdk-runtime-py`（+ 共享 `earp-sdk-core-py` 扩展） |
| **评审人** | Review Agent |
| **日期** | 2026-07-12 |
| **测试结果** | ✅ 28/28 通过（0.04s） |

---

## 总体评价

**代码简洁，架构清晰，API 设计正确。** 7 个源文件实现了 Runtime SDK 的核心功能，与 L3 设计文档 v1.1 对齐良好，MockRuntimeClient 让应用开发者可以离线集成测试，与 Capability SDK 的 MockRuntime 对称呼应。

### 代码规模

| 包 | 源文件 | 测试文件 | 行数 |
|:--|:-----:|:-------:|:----:|
| `earp-sdk-runtime-py` | 7 | 1 | ~200 |
| `earp-sdk-core-py`（新增） | — | — | 3 个新异常类 |

### 测试结果

```
16 passed in 0.07s
— MockRuntimeClient 9 个测试、错误类型 4 个测试、Models 3 个测试
```

### 覆盖率

| 模块 | 覆盖率 | 说明 |
|:----|:------:|------|
| `models.py` | 100% | ✅ |
| `__init__.py` | 100% | ✅ |
| `testing/mock_runtime.py` | 97% | ✅ 核心测试工具覆盖完全 |
| `client.py` | 43% | ⚠️ HTTP 请求路径未 mock 测试 |
| `session.py` | 37% | ⚠️ HTTP 请求路径未 mock 测试 |
| `invoker.py` | 25% | ⚠️ HTTP 请求路径未 mock 测试 |
| `events.py` | 25% | ⚠️ SSE 流路径未 mock 测试 |
| 总体 | 60% | 低因 HTTP 客户端路径均未测试 |

---

## P0 — 必须修复

### P0-1：`invoker.py` 中 SDKMUST-R-009 的幂等键警告无条件触发（误报）

**涉及文件：** `invoker.py:80-86`

```python
if idempotency_key is None:
    # SDKMUST-R-009: warn for Command types (best-effort detection)
    logger.warning(
        "invoke('%s') called without idempotency_key — "
        "Command-type Capabilities should provide one for safe retry",
        capability_id,
    )
```

**问题描述：**

SDKMUST-R-009 说"Command 类型缺 idempotency_key 时打印警告"，但当前实现**无条件对每次 invoke 都打印警告**——即使是 Query 类型。

这导致：
- 每次调 Query 都打印噪音警告
- 开发者无法区分真正需要关注的情况

代码注释写 `best-effort detection`，说明作者也知道无法在 SDK 侧区分 Query/Command。但没有做任何降级处理。

**建议方案：**

选项 A（推荐）：去掉无条件警告。SDKMUST-R-009 从 SHOULD 降级为 `idempotency_key` 的文档提示——因为 SDK 侧确实无法区分 Capability 类型。在 `invoke()` 的 docstring 中强调即可。

选项 B：在 Docstring 中标注 + 仅对带 `execute_write` / `command` 等关键词的 capability_id 打印警告。

---

### P0-2：`client.py` 中 `Authorization` header 在 token 为空时发送 `Bearer `

**涉及文件：** `client.py:35`

```python
"Authorization": f"Bearer {token}" if token else "",
```

**问题描述：**

当 `token=""` 时，`Authorization` header 被设置为空字符串 `""`，而不是不发送此 header。

`httpx` 会在 HTTP 请求中发送 `Authorization: `（空值），这不符合 SDKMUST-R-002（"必须包含 `Authorization: Bearer <token>`"）的意图——没 token 时应该不传 Authorization header。

**建议方案：**

```python
headers = {
    "User-Agent": USER_AGENT,
}
if token:
    headers["Authorization"] = f"Bearer {token}"
```

---

### P0-3：`invoker.py` 中 `X-Trace-Id` 使用 `hash(capability_id) % 10000` 生成固定值

**涉及文件：** `invoker.py:78`

```python
headers = {"X-Trace-Id": f"trace-{id(self)}-{hash(capability_id) % 10000:04d}"}
```

**问题描述：**

SDKMUST-R-004 要求"所有请求必须自动注入 `X-Trace-Id` header"。

当前实现使用 `hash(capability_id) % 10000`，这意味着相同的 `capability_id` 在**同一个进程**中生成的 trace_id 是固定的，不同调用无法区分。且 `hash()` 的种子在 Python 3 中跨进程固定，trace-id 缺乏唯一性。

**建议方案：**

使用 `uuid.uuid4()` 生成 trace_id：

```python
import uuid
headers = {"X-Trace-Id": str(uuid.uuid4())}
```

---

## P1 — 建议修改

### P1-1：`MockRuntimeClient` 的 `search()` 返回不分页结果

**涉及文件：** `testing/mock_runtime.py:92-115`

MockRuntimeClient 的 `search()` 接收 `page` 和 `page_size` 参数但忽略它们——总是返回全部结果。Mock 应该模拟分页行为，否则集成测试无法覆盖分页路径。

**建议：** 根据 `page` 和 `page_size` 对结果切片：

```python
start = (page - 1) * page_size
end = start + page_size
return SearchResponse(
    results=results[start:end], page=page, page_size=page_size, total=len(results),
)
```

---

### P1-2：`RuntimeClient.call()` 对 Command 场景缺少幂等键文档指引

**涉及文件：** `client.py:88-127`

当前 `call()` 已添加 `idempotency_key` 参数（符合修复后的设计要求），但 docstring 只说了"Command calls or multiple invocations, use create_session() + invoke()"而没有明确说明何时需要幂等键。

**建议：** 强化 docstring：

```
For Command Capability calls, always provide an idempotency_key
to enable safe retries (e.g., idempotency_key=f"wo-{order_id}").
```

---

### P1-3：`Session.close()` 的网络异常时静默吞掉错误

**涉及文件：** `session.py:69-70`

```python
except httpx.HTTPError:
    pass  # Best-effort close
```

当前设计合理——Session 关闭应该尽力而为。但可以加一条日志告知状态可能未同步到服务端。

**建议：**

```python
except httpx.HTTPError as e:
    logger.warning("Session.close() failed to notify server: %s", e)
```

---

### P1-4：`events.py` 的重连逻辑永远不会被触发（缺超时配置）

**涉及文件：** `events.py:56-85`

测试覆盖率为 25% 表明 SSE 流路径未被测试。重连逻辑正确（指数退避，最多 5 次），但 `aiter_lines()` 没有配置超时初始值 (`timeout=None`)，这可能导致连接断开后卡在无限等待，重连循环永远不会执行。

**建议：** 为 SSE 流添加初始超时 timeout（如 300s），断开后进入重连循环。

---

### P1-5：缺少集成测试（HTTP mock transport）

Runtime SDK 的 `client.py`、`session.py`、`invoker.py`、`events.py` 均依赖 HTTP 请求，但没有任何 httpx.MockTransport 的集成测试。

对比 Capability SDK（registration_client 和 discovery_client 都有完整的 MockTransport 测试），Runtime SDK 缺少对应的测试基础设施。

**建议：** 为 `CapabilityInvoker.invoke()` / `search()` / `resolve()` 和 `Session` 生命周期添加 MockTransport 测试。

---

## P2 — 建议性优化

### P2-1：`invoker.py` 中 `USER_AGENT` 常量与 `client.py` 重复定义

两个文件都定义了 `USER_AGENT = "earp-sdk-runtime/0.1.0.dev0"`。如果升级版本号，需要改两个地方。

**建议：** 在 `models.py` 或 `__init__.py` 中统一定义 `__version__` 和 `USER_AGENT` 常量。

---

### P2-2：`client.py` `create_session()` 缺少重试逻辑

**涉及文件：** `client.py:64-84`

Session 创建的 HTTP 请求没有重试。SDKMUST-R-007（SHOULD）只覆盖 "连接失败自动重试"——Session 创建也应该受益。

**建议：** 复用 `RetryConfig` 包装 Session 创建的请求。

---

### P2-3：`MockRuntimeClient.invoke()` 的 `params` 没有做参数校验

**涉及文件：** `testing/mock_runtime.py:80-90`

Mock 的 handler 直接接收原始 params 并调用，没有做参数校验（检查必需字段、类型等）。这可以理解——mock 本意就是跳过校验。但可以加一个可选参数 `schema` 来启用本地校验（方便高级测试场景）。

**建议：** 在 `MockRuntimeClient.__init__` 中增加 `validate: bool = False` 参数。

---

## 与 PRD 验收条件的对齐

| AC | 描述 | 状态 | 备注 |
|:--:|------|:----:|------|
| AC-01 | `pip install earp-sdk-runtime` | ✅ | 包结构正确 |
| AC-02 | `RuntimeClient.call()` 成功调用并返回 dict | ✅ | 实现正确 |
| AC-03 | Session 完整生命周期 | ✅ | create_session → invoke → close |
| AC-04 | `session.events.subscribe()` 按事件类型订阅 | ✅ | SSE 协议 + 重连 |
| AC-05 | 不存在的 capability_id → CapabilityNotFoundError | ✅ | HTTP 404 → 异常映射 |
| AC-06 | 无权限 → PermissionDeniedError | ✅ | HTTP 403 → 异常映射 |
| AC-07 | MockRuntimeClient 离线测试 | ✅ | 完全离线，无网络 |
| AC-08 | 所有 HTTP 请求注入 `X-Trace-Id` | ⚠️ | 存在，但生成算法不稳定（P0-3） |
| AC-09 | 连接失败自动重试 | ⚠️ | invoker.py 中没有显式重试逻辑 |
| AC-10 | 错误码对齐 earp-sdk-core | ✅ | _STATUS_ERROR_MAP 映射表 |
| AC-11 | 事件订阅自动重连 | ✅ | events.py 指数退避最多 5 次 |
| AC-12 | `user_id` 必传 | ✅ | create_session 中 user_id 无默认值 |

### SDKMUST-R 对齐

| MUST ID | 描述 | 状态 |
|:--------|------|:----:|
| SDKMUST-R-001 | `user_id` 必传 | ✅ `create_session` 强制检查 |
| SDKMUST-R-002 | Authorization header | ⚠️ P0-2：空 token 时发送空 header |
| SDKMUST-R-003 | User-Agent header | ✅ |
| SDKMUST-R-004 | X-Trace-Id 注入 | ⚠️ P0-3：生成算法使用 hash 不够唯一 |
| SDKMUST-R-005 | invoke 经过 Runtime 端点 | ✅ 发送到 `/v1/executions` |
| SDKMUST-R-006 | 错误码对齐 CapabilityErrorCode | ✅ _STATUS_ERROR_MAP |
| SDKMUST-R-007 | 连接失败自动重试 | ⚠️ 未显式实现（httpx 默认不重试） |
| SDKMUST-R-008 | 事件订阅自动重连 | ✅ events.py 重连循环 |
| SDKMUST-R-009 | 幂等键警告 | ❌ P0-1：无条件触发 |

---

## 评审总结

### 数据统计

| 类别 | 数量 |
|:----|:----:|
| ✅ 通过的测试 | 16/16 |
| ❌ P0（必须修复） | 3 |
| ⚠️ P1（建议修改） | 5 |
| 💡 P2（建议性优化） | 3 |

### 三个 P0 必须修复

| # | 问题 | 文件 | 影响 |
|:-|------|------|:-----|
| 1 | 幂等键警告无条件触发（误报） | `invoker.py:80` | 每次调 Capability 都打印警告，噪音严重 |
| 2 | 空 token 时发送 `Authorization: ` 空值 | `client.py:35` | 违反 SDKMUST-R-002 意图 |
| 3 | X-Trace-Id 使用 hash 生成固定值 | `invoker.py:78` | 同一 capability_id 多次调用的 trace-id 无法区分 |

### 总体评价

代码简洁清晰，7 个源文件 + 1 个测试文件的结构与设计文档完全对齐。**API 设计正确**——RuntimeClient → Session → CapabilityInvoker/EventSubscriber 三线对称，MockRuntimeClient 设计良好。**错误映射表**（HTTP 404/403/429 → 异常类型）和**三种新异常类**（CapabilityNotFoundError / PermissionDeniedError / RateLimitExceededError）在 earp-sdk-core 中正确定义。

主要不足是：
1. 测试集中在 MockRuntimeClient —— HTTP 路径（client/session/invoker/events）**全部未 Mock 测试**（覆盖率 25-43%）
2. 三个 P0 问题都是边界条件细节问题，修复工作量小

建议修复全部 P0 后进入 Gate 1（人工验收）。

---

## 补充：`/code-review` skill 复核

使用 `/code-review` skill（high effort）对 Runtime SDK 进行二次复核，发现 **2 个额外的问题**（与人工评审互补）：

| # | 严重度 | 文件 | 行号 | 问题 |
|:-|:------:|:-----|:----:|:-----|
| R1 | 🔴 correctness | `invoker.py` | 103 | **`RateLimitExceededError` 构造函数不匹配** — `_STATUS_ERROR_MAP` 将 HTTP 429 映射到 `RateLimitExceededError`，调用时传入 `capability_id=capability_id`，但此类构造函数签名为 `(message, retry_after)`，触发 TypeError |
| R2 | 🔴 correctness | `invoker.py` | 47 | **`_session_id` 存储了但从未传入 HTTP 请求** — `CapabilityInvoker.__init__` 接收并存储 `session_id`，但 `invoke()` / `search()` / `resolve()` 的请求 body 中均未携带 session_id。Runtime 服务端无法将调用关联到调用方的 Session |
| R3 | 🟡 simplification | `mock_runtime.py` | 30 | `hasattr(result, '__await__')` 是脆弱的异步检测方式，建议用 `asyncio.iscoroutine()` |
| R4 | 🟡 simplification | `errors.py` | 143 | 3 个 Runtime 异常类的消息构造模式重复，可抽象公用基辅助方法 |

> **注意**：R1/R2 是人工评审未发现的新问题，且严重度高于手工发现的 P0 问题。R1 在生产环境触发 HTTP 429 时会导致 TypeError 而非正确的异常类型。
