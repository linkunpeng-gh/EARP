# PRD-2026-002 v1.1

## Runtime SDK — Python 第一版

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-002 |
| **Feature** | Runtime SDK（Python） |
| **影响域** | SDK/API |
| **影响规范** | L2-01-RUNTIME v1.2 |
| **对齐设计文档** | arch/L3/runtime-sdk-design-v1.md v1.1 |
| **优先级** | **P0**（应用程序调用 EARP 的唯一入口） |
| **版本** | v1.1 |
| **作者** | PM Agent |
| **日期** | 2026-07-12 |

---

## 1. 背景

Capability SDK 完成了"怎么写 Capability"，但还缺"怎么调 Capability"。应用程序开发者需要一个 SDK 来创建 Session、调用 Capability、订阅事件。

### 三个断层

| 问题 | 现状 |
|:-----|:-----|
| 应用程序要自己拼 HTTP 请求 | 无统一编程入口 |
| Session 生命周期需手动管理 | 每个应用各自实现 |
| 事件驱动场景靠轮询 | 无标准事件订阅机制 |

---

## 2. 设计文档

L3 设计已在 `arch/L3/runtime-sdk-design-v1.md` 完成并经过评审修复（v1.1）。关键架构决策：

| 决策 | 选择 | 说明 |
|:-----|:-----|:-----|
| 传输协议 | **HTTP/REST**（v1），gRPC（v2） |
| 认证方式 | **Bearer JWT**（v1），API Key（v2） |
| 流式协议 | **Server-Sent Events**（v1），WebSocket（v2） |
| 重试策略 | 指数退避，默认 3 次 |

### 与 Capability SDK 的差异

| 维度 | Capability SDK | Runtime SDK |
|:----|:---------------|:------------|
| **使用者** | Capability 开发者（写 Capability） | 应用开发者（调 Capability） |
| **核心 API** | `class MyCap(QueryCapability).execute()` | `session.capabilities.invoke()` |
| **测试工具** | MockRuntime（mock 外部系统） | MockRuntimeClient（mock Runtime） |
| **错误类型** | ConnectorError + CapabilityError | CapabilityNotFoundError + PermissionDeniedError 等 |
| **返回类型** | Pydantic 模型（`OutputT`） | `dict`（由 output_schema 定义结构） |
| **包大小** | 17 个源文件 + CLI | 7 个源文件，无 CLI |
| **注册** | `earp register` 注册到平台 | 不需要注册 |

---

## 3. 用户故事

### US-01：正常路径——应用程序调用一个 Capability

> 作为**设备管理应用的开发者**，我希望**通过 SDK 调用 `query_equipment_alarm` Capability**，以便**查询设备报警数据展示在界面上**。

```
预期流程：
  1. pip install earp-sdk-runtime
  2. 创建 RuntimeClient（传入 Runtime 端点 + JWT token）
  3. 调用 client.call("query_equipment_alarm", {"equipment_id": "EQ-001"})
  4. 拿回 dict 结果 {"alarms": [...], "total": 42}

返回类型说明：调用方拿回的是 dict 而非 Pydantic 模型。
因为应用开发者没有 Capability 的 Pydantic 模型源码（由 Capability 开发者维护）。
可通过 Discovery API 查询 Capability 的 output_schema 了解返回字段。
```

### US-02：Session 模式——多次调用带上下文

> 作为**工单应用的开发者**，我希望**在同一个 Session 中先查报警再创建工单**，以便**两次调用共享上下文和 trace**。

```
预期行为：
  - 调用 client.create_session(user_id="u-001") 创建 Session（user_id 为 MUST）
  - 在 Session 内多次调用 session.capabilities.invoke() 复用上下文
  - Command 类型 Capability 应传入 idempotency_key 确保幂等
  - 调用 session.close() 关闭 Session，释放资源
  - Session 生命周期内自动注入 X-Trace-Id，调用方不感知
```

### US-03：事件订阅——事件驱动处理

> 作为**运维平台的开发者**，当 **MES 发出 critical 级报警事件**时，我希望**SDK 自动收到事件并触发处理 Capability**。

```
预期行为：
  - 通过 session.events.subscribe(event_types=["alarm.critical"]) 订阅事件
  - event_types=None 时订阅全部事件
  - 连接断开后自动重连（指数退避，最多 5 次）
  - 通过 break 或 .aclose() 优雅退出订阅
  - 收到事件后可通过 session.capabilities.invoke() 响应
```

### US-04：异常——Capability 不存在

> 作为**应用开发者**，当我**调用的 capability_id 不存在**时，我希望**SDK 抛出 `CapabilityNotFoundError`**。

```
预期行为：
  - 服务端返回 404，SDK 抛出 CapabilityNotFoundError
  - 不可重试
```

### US-05：异常——无权限

> 作为**应用开发者**，当**当前用户的 token 没有权限调某个 Capability**时，我希望**SDK 抛出 `PermissionDeniedError`**。

```
预期行为：
  - 服务端返回 403，SDK 抛出 PermissionDeniedError
  - 不可重试
```

### US-06：边界——离线测试

> 作为**应用开发者**，当**开发环境没有真实 EARP Runtime**时，我希望**用 `MockRuntimeClient` 在本地模拟 Capability 调用**。

```
预期行为：
  - MockRuntimeClient.register(capability_id, handler) 注册 mock handler
  - MockRuntimeClient.call() / invoke() 直接调本地 handler，不走网络
  - 不支持事件订阅（无真实 SSE 连接）
```

---

## 4. 验收条件（AC）

| ID | 描述 | 对应 US | SDKMUST-R |
|:--:|------|:-------:|:---------:|
| AC-01 | SDK 可通过 `pip install earp-sdk-runtime` 安装 | US-01 | — |
| AC-02 | `RuntimeClient.call()` 成功调用 Capability 并返回 dict | US-01 | R-005 |
| AC-03 | `create_session()` → 多次 `invoke()` → `close()` 完整 Session 生命周期 | US-02 | R-001 |
| AC-04 | `session.events.subscribe()` 按事件类型订阅事件流 | US-03 | R-008 |
| AC-05 | 调用不存在的 capability_id 抛出 `CapabilityNotFoundError` | US-04 | R-006 |
| AC-06 | 无权限时抛出 `PermissionDeniedError` | US-05 | R-006 |
| AC-07 | `MockRuntimeClient` 无需真实 Runtime 即可完成 invoke 测试 | US-06 | — |
| AC-08 | 所有 HTTP 请求自动注入 `X-Trace-Id` | — | R-004 |
| AC-09 | 连接失败时自动重试（指数退避，不超过 RetryConfig.max_attempts） | — | R-007 |
| AC-10 | 错误码对齐 earp-sdk-core 的 CapabilityErrorCode | — | R-006 |
| AC-11 | 事件订阅断开后自动重连（指数退避，最多 5 次） | — | R-008 |
| AC-12 | `user_id` 在 `create_session()` 中为必传参数（无默认值） | — | R-001 |
| **AC-13** | 所有 HTTP 请求自动注入 `Authorization: Bearer <token>` | — | **R-002** |
| **AC-14** | 所有 HTTP 请求包含 `User-Agent: earp-sdk-runtime/{version}` | — | **R-003** |
| **AC-15** | `invoke()` 必须发送 HTTP 请求到 Runtime 端点，不直接调 Capability | — | **R-005** |
| **AC-16** | Command 类型 Capability 调用缺少 `idempotency_key` 时打印警告日志 | — | **R-009** |

**SDKMUST-R 覆盖情况：9/9 全部对齐。**

---

## 5. 依赖分析

### 5.1 内部依赖

| 依赖 | 状态 | 说明 |
|------|:----:|------|
| L2-01-RUNTIME v1.2 | ✅ 已冻结 | Session / Execution / Event 契约 |
| earp-sdk-core-py | ✅ 已实现 | 共享错误码和数据模型。`CapabilityNotFoundError`、`PermissionDeniedError`、`RateLimitExceededError` 在此包中新增 |
| arch/L3/runtime-sdk-design-v1.md v1.1 | ✅ 已评审 | L3 设计完整 |

### 5.2 外部依赖

| 依赖 | 用途 | 是否新增 |
|------|------|:--------:|
| httpx | HTTP 客户端 | 已有（与 Capability SDK 共享） |

### 5.3 技术约束（已在 L3 设计中确定）

| 约束 | 选择 |
|:-----|:-----|
| 传输协议 | HTTP/REST + JSON（v1） |
| 认证 | Bearer JWT（`Authorization: Bearer <token>`） |
| 事件流 | SSE（v1），WebSocket（v2） |
| 重试 | 指数退避，默认 3 次，可配置 |

### 5.4 风险

| 风险 | 概率 | 影响 | 应对 |
|:----:|:----:|:----:|------|
| EARP Runtime 服务端未实现 | 高 | SDK 不可端到端测试 | MockRuntimeClient 本地模拟；HTTP 请求用 mock transport 测试 |
| 认证兼容性（JWT 签发方未定） | 中 | token 格式可能变动 | 定义 `Client.token` 为通用字符串，不变动 SDK 接口 |

---

## 6. 不做（Out of Scope）

| 事项 | 原因 |
|:-----|:------|
| gRPC 传输协议 | 第二阶段 |
| Session pause/resume | 预留接口，v1.1 实现 |
| `submit()` 异步调用模式 | v1.1 实现 |
| WebSocket 事件流 | 第二阶段（v1 用 SSE） |
| API Key 认证模式 | 第二阶段（v1 用 Bearer JWT） |

> **新增异常类型**在 earp-sdk-core-py 中定义（`CapabilityNotFoundError`、`PermissionDeniedError`、`RateLimitExceededError`），与 Capability SDK 共享错误基类。

---

## 7. 交付物

```
earp-sdk-runtime-py/
├── pyproject.toml              # 依赖: earp-sdk-core, httpx
├── README.md
└── src/earp_sdk_runtime/
    ├── __init__.py              # RuntimeClient, Session, CapabilityInvoker...
    ├── client.py                # RuntimeClient 主入口
    ├── session.py               # Session 生命周期管理
    ├── invoker.py               # CapabilityInvoker + CapabilityDiscovery
    ├── events.py                # EventSubscriber（SSE 协议）
    ├── models.py                # CapabilityInfo, ResolvedCapability, RuntimeEvent 等
    └── testing/
        ├── __init__.py
        └── mock_runtime.py      # MockRuntimeClient
```

---

## 8. 验收总结表

| # | 检查项 | 状态 | 备注 |
|:-:|--------|:----:|------|
| 1 | 用户故事完整性（US-01 ~ US-06） | ✅ 覆盖正常+异常+边界 | 正常(1) + 异常(2) + 边界(1) + Session(1) + 事件(1) |
| 2 | 验收条件可测试性（AC-01 ~ AC-16） | ✅ 全部可写自动化测试 | 9/9 SDKMUST-R 全覆盖 |
| 3 | 依赖分析完整性 | ✅ 内/外/协议/风险均覆盖 | HTTP + JWT + SSE 已确定 |
| 4 | 优先级合理性 | ✅ P0 | 应用调 EARP 的唯一入口 |
| 5 | 无矛盾需求 | ✅ 对齐 L2-01 v1.2 和 L3 设计 v1.1 | 所有架构决策已收敛 |

---

## 9. 评审修复记录

| 编号 | 评审问题 | 修复方式 |
|:----:|---------|---------|
| P0-1 | US-02/US-03 缺少预期行为 | 补充完整 `预期行为` 块（Session 流程、事件订阅语义） |
| P0-2 | SDKMUST-R 缺少 4 条 AC | 新增 AC-13 ~ AC-16，覆盖 Authorization / User-Agent / Resolution Engine / idempotency_key |
| P1-1 | call() 返回值未说明 | US-01 补充 dict 返回类型说明 |
| P1-2 | 架构决策未体现 | §2 + §5.3 新增协议/认证/SSE/重试决策 |
| P1-3 | 缺少差异对比表 | §2 新增 Capability SDK vs Runtime SDK 对比表 |
| P1-4 | 异常类定义位置不明确 | §6 明确标注新增异常类型定义在 earp-sdk-core |
| P2-1 | 缺少验收总结表和修复记录 | 新增 §8 和 §9 |
| P2-2 | 版本号 v1.0→v1.1 | 更新文档头版本号 |
