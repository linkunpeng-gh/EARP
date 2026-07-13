# Runtime SDK 设计 v1 — 评审报告

## 文档位置：arch/L3/runtime-sdk-design-v1.md

| 字段 | 值 |
|------|-----|
| **文档** | Runtime SDK 设计 v1（L3） |
| **评审人** | Review Agent |
| **日期** | 2026-07-12 |
| **状态** | ✅ 全部 P0/P1/P2 已修复（v1.0 → v1.1） |

> **2026-07-12 更新**：PM Agent 已按本评审报告逐条修复。详见设计文档 §10 评审修复记录。

---

## 总体评价

**方向正确，结构清晰，与 Capability SDK 互补定位合理。** Session 模型对齐 L2-01 v1.2，事件订阅对齐 EventBus，包结构与已完成的 Capability SDK 一致。

共发现 **3 个 P0（必须修复）、7 个 P1（建议修改）、3 个 P2（建议性优化）**。

> **2026-07-12 更新**：PM Agent 已按本评审报告逐条修复 PRD（v1.0 → v1.1）。修复详情见 PRD §10 评审修复记录。
> 当前 PRD 就绪，可进入 **实现阶段**。

---

## P0 — 必须修复（建议退回修改后再进入实现）

### P0-1：`CapabilityInvoker.search()` 方法重复定义

**涉及段落：** §3.3（第 219-233 行）

`search()` 方法在同一类中出现了两次——第一次返回 `list[CapabilityInfo]`，第二次返回 `SearchResponse`：

```python
# 第一次定义（第 219 行）
async def search(self, query: str, domain: str | None = None) -> list["CapabilityInfo"]:
    ...

# 第二次定义（第 225 行）——同名方法，签名不同
async def search(
    self,
    query: str,
    *,
    domain: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> "SearchResponse":
    ...
```

Python 不支持方法重载——第二次定义会静默覆盖第一次。`SearchResponse` 的翻页信息（`总条数 / 总页数`）是必需的，但第一次定义完全没有翻页参数。

**建议方案：**

只保留带分页的版本，去掉第一个无分页的签名。如果一定要提供无分页快捷方法，在内部调分页版本时传入一个很大的 `page_size`：

```python
async def search(
    self,
    query: str,
    *,
    domain: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SearchResponse:
    ...
```

---

### P0-2：缺少 MUST/SHOULD/MAY 约束条款

**涉及段落：** 全文

**问题描述：**

Capability SDK 设计文档定义了 **6 条 SDKMUST**，实现代码评审时有 15 条 AC 对齐。但本 Runtime SDK 设计文档**没有任何 MUST/SHOULD/MAY 条款**。

L2-01 RUNTIME v1.2 有 **44+ 条 MUST 条款**定义 Session、Context、Execution、Event、Lifecycle。本设计文档作为 L3 实现层，必须将这些 MUST 条款映射为 SDK 级别的约束，否则：
- 实现没有可验证的合规标准
- 调用者不知道哪些行为是 SDK 保证的
- 跨 SDK 集成时可能违反 L2 规范

缺少的核心条款举例：

| 领域 | L2 MUST 引用 | 缺少的 SDK 级别约束 |
|:----|:------------|-------------------|
| Session | §6.3 — Session 包含 7 个 MUST 字段 | SDK 必须保证创建 Session 时这些字段都填充 |
| Execution | §2.2 — 所有应用必须通过 Runtime 提交 Request | SDK 必须保证 `invoke()` 经过 Resolution Engine |
| Trace | §2.2 — 每次执行产生 Trace | SDK 必须自动注入 trace context |
| Context | §3.2 — Context 为只读 | SDK 必须在调用链中传递完整 Context |

**建议方案：**

在文档中新增一个 MUST/SHOULD 章节（参考 Capability SDK §5），至少覆盖：

```
SDKMUST-R-001: Session 创建请求必须包含 session_id / tenant_id / user_id（对齐 L2-01 §6.3）
SDKMUST-R-002: 所有 HTTP 请求必须包含 User-Agent: earp-sdk-runtime/{version}
SDKMUST-R-003: invoke() 的请求必须经过 Resolution Engine（不对齐则相当于跳过 Policy 检查）
SDKMUST-R-004: 所有请求必须自动注入 trace_id（对齐 L2-01 §2.2）
SDKMUST-R-005: 错误码必须对齐 earp-sdk-core 定义的 CapabilityError / ConnectorError
```

---

### P0-3：`CapabilityInvoker.invoke()` 返回 `dict`，与 Capability SDK 的 typed 输出不匹配

**涉及段落：** §3.3（第 197 行）

```python
async def invoke(self, capability_id: str, params: dict, ...) -> dict:
```

Runtime SDK 返回 `dict`，但 Capability SDK 的 `execute()` 返回的是 Pydantic 模型实例（`OutputT`）。这意味着：

- Capability 开发者写 `return AlarmResult(alarms=[], total=0)`（类型安全）
- 应用开发者调 `session.capabilities.invoke()` 拿到 `dict`（需手动 `AlarmResult(**result)` 解包）
- **同样的 Capability，调用的两端类型体验不对称**

**建议方案：**

选项 A（推荐）：`invoke()` 返回 `Any`，文档说明 response 结构由对应 Capability 的 output_schema 决定。提供可选泛型参数：

```python
async def invoke(
    self,
    capability_id: str,
    params: dict,
    *,
    timeout_seconds: int = 30,
    idempotency_key: str | None = None,
) -> Any:
```

选项 B：保持 `dict`，但文档明确说明"调用方需要根据 Capability 的 output_schema 自行解析"。

---

## P1 — 建议修改

### P1-1：事件订阅缺少连接管理语义

**涉及段落：** §3.4 `EventSubscriber.subscribe()`

`subscribe()` 返回 `AsyncIterator[RuntimeEvent]`，但没有定义：
- **重连策略**：连接断开后自动重连？指数退避？
- **背压**：消费速度跟不上事件产生速度时的行为？
- **过滤语义**：`event_types=None` 是"订阅全部"还是"不订阅"？
- **取消订阅**：如何优雅退出事件循环？

**建议：** 在 Subscription 语义中至少明确重连策略和退出机制，或在 §7 未定事项中列出。

---

### P1-2：`RuntimeClient.call()` 与 Session 模式的接口不一致

**涉及段落：** §3.1（第 133-146 行）

`call()` 是快捷方法（创建临时 Session → 调用 → 关闭），但：
- 不支持 `idempotency_key`（对 Command Capability 至关重要）
- 返回 `dict` 但没有说明 Session 关闭后返回值是否仍可用
- 事件订阅场景无法使用此模式

**建议：** 为 `call()` 增加 `idempotency_key` 参数，或文档明确说明"Command 场景建议使用 Session 模式"。

---

### P1-3：Session.pause()/resume() 与同步 invoke 的交互未定义

**涉及段落：** §3.2 `Session.pause()` / `resume()`

SDK 设计中说 Session pause 会"挂起所有活跃 Execution"。但如果应用代码正在同步等待 `await session.capabilities.invoke(...)` 的结果：
- invoke() 的 HTTP 请求会保持连接还是超时？
- pause 后 resume，invoke() 的返回值是什么？
- 超时时间怎么算？

**建议：** 明确 pause/resume 对同步 invoke 调用的影响，或在文档中标注"当前版本仅支持 Standalone 模式，pause/resume 为预留接口"。

---

### P1-4：§7 "未定事项"中的 4 个决策需要升级到 ADR 级别

**涉及段落：** §7

| 事项 | 问题 |
|:-----|:-----|
| 传输协议（gRPC vs HTTP） | 影响整个 SDK 的异步模型和连接管理 |
| 认证方式（API Key vs JWT） | 影响 Client 构造函数和 middleware 设计 |
| 流式响应（SSE vs WebSocket） | 影响 EventSubscriber 架构 |
| 重试策略 | 影响 invoke 的可靠性保证 |

这些不是"未定事项"——它们是影响 SDK 整体架构的**架构决策**，必须在 L3 设计阶段确定。如果在实现阶段才决定协议，可能导致 SDK 重大重构。

**建议：** 协议和认证在 L3 设计阶段确定（推荐 HTTP + Bearer JWT），其他可以作为实现阶段的决策。或按 ADR 格式记录备选方案和选择理由。

---

### P1-5：缺少与 Capability SDK 的错误映射关系

**涉及段落：** §3.3 异常说明

`invoke()` 的 docstring 列了 3 种异常类型（`CapabilityNotFoundError`、`PermissionDeniedError`、`CapabilityError`），但没有：
- 定义这些异常类（不在本文中，也不在 earp-sdk-core 中）
- 与 Capability SDK 的 `CapabilityErrorCode`（8 个码）的映射关系
- 指出哪些异常是可重试的

**建议：**
1. 新增错误类到 earp-sdk-core（或在本文中定义）
2. 提供异常码映射表：`Runtime SDK Error` ⇔ `CapabilityErrorCode` ⇔ `HTTP Status Code`

---

### P1-6：`CapabilityInvoker.resolve()` 的意图不清晰

**涉及段落：** §3.3（第 235-243 行）

```python
async def resolve(
    self,
    intent: str,
    domain: str | None = None,
) -> list["ResolvedCapability"]:
```

`resolve()` 定义为"语义解析：输入自然语言意图，返回匹配合适的 Capability"。但：
- `ResolvedCapability` 类型未定义（只在 docstring 中出现了一次）
- 输入自然语言 → Capability 列表，排在第一个的就是要找的？还是需要调用方自行判断？
- 与 `search()` 的语义区别是什么？search 是关键词搜索，resolve 是语义匹配？

**建议：** 明确定义 `ResolvedCapability` 数据类，以及与 `search()` 的区别。考虑在文档中说明典型使用场景。

---

### P1-7：`testing/mock_runtime.py` 仅有文件名，缺少设计内容

**涉及段落：** §5 包结构

Capability SDK 的 MockRuntime 是开发者最核心的测试工具。Runtime SDK 的 mock 同样重要——它模拟 Capability Center 的行为（响应 invoke、返回 search 结果）。但本设计文档只列了文件名，没有设计 mock 的行为和接口。

**建议：** 至少用一段话描述 MockRuntimeClient 的核心行为：
- 注册 mock handler 的接口
- 是否支持模拟错误场景
- 是否需要真实 Runtime 还是完全本地

---

## P2 — 建议性优化

### P2-1：§6 "与现有架构的映射" 缺少 Capability SDK 的三层结构映射

现有 §6 只映射了 L2 Runtime Spec。但 Runtime SDK 作为 Capability SDK 的"对端"，应该也要展示与 Capability 三层结构的对应关系：

| Capability 三层结构 | Runtime SDK | 说明 |
|:-------------------|:-----------|:------|
| input_schema | `invoke(params)` 的 params | 调用方按 input_schema 传参 |
| output_schema | `invoke()` 的返回值 | 返回结构按 output_schema |
| execution_contract | 隐含在 invoke 的 timeout/retry 参数中 | 调用方可覆盖 |
| policy | 无对应 | Runtime SDK 不直接暴露 Policy |

---

### P2-2：Session 的 `create_session()` 参数 `user_id` 和 `tenant_id` 默认空字符串

```python
async def create_session(
    self,
    *,
    user_id: str = "",
    tenant_id: str = "",
) -> "Session":
```

L2-01 §6.3 要求 Session 的 `user_id` 和 `tenant_id` 为 MUST 字段。空字符串默认值意味着参数可能被忽略，导致不合法的 Session 创建。

**建议：** 将 `user_id` 设为必传参数（去掉默认值），或在 RuntimeClient 构造函数中统一注入身份信息，避免每次调用都传。

---

### P2-3：缺少 `__init__` 包导出清单

§5 包结构中 `__init__.py` 只标注了"RuntimeClient, Session"。建议像 Capability SDK 一样写出完整导出清单：

```python
__all__ = [
    "RuntimeClient",
    "Session",
    "CapabilityInvoker",
    "EventSubscriber",
    "CapabilityInfo",
    "RuntimeEvent",
    "SessionStatus",
    "CapabilityError",
    # ...
]
```

---

## 对齐检查表（v1.1 修复后）

### 与 L2-01 RUNTIME v1.2 的对齐

| L2 参考 | 对应设计 | v1.0 | v1.1 | 备注 |
|:--------|:---------|:----:|:----:|------|
| §2.2 — Runtime 是唯一执行入口 | `session.capabilities.invoke()` 作为调用入口 | ✅ | ✅ | |
| §2.2 — 所有请求经过 Resolution | `invoke()` 经过 Resolution Engine | ⚠️ | ✅ | SDKMUST-R-005 确保 |
| §2.2 — 同步/异步模式 | `call()` 同步；预留 `submit()` 异步 | ⚠️ | ⚠️ | 异步模式 v1.1（已标注） |
| §2.2 — 每次执行产生 Trace | SDK 自动注入 `X-Trace-Id` | ⚠️ | ✅ | SDKMUST-R-004 |
| §3 — Context | SDK 自动传递用户身份 | ⚠️ | ✅ | Context 字段对齐 |
| §5 — EventBus | `session.events.subscribe()`/`publish()` | ✅ | ✅ | 未变 |
| §6.3 — Session 契约 | `Session` dataclass + `create_session()` | ✅ | ✅ | user_id 改为 MUST |
| §6.3 — Session 生命周期 | `pause()` / `resume()` / `close()` | ⚠️ | ✅ | pause/resume 标注"v1.1 实现" |
| §8 — Execution（原） | `CapabilityInvoker.invoke()` | ✅ | ✅ | |
| 附录 C — Connector 错误码 | 共享 earp-sdk-core 异常映射表 | ❌ | ✅ | §4.6 完整映射表 |
| MUST 条款整体对齐（44+ 条） | 9 条 SDKMUST-R | ❌ P0-2 | ✅ | 5 MUST + 3 SHOULD + 1 MAY |

### 与 L0 设计哲学的对齐

| 理念 | v1.0 | v1.1 | 说明 |
|:----|:----:|:----:|------|
| Runtime First | ✅ | ✅ | 未变 |
| Domain First | ✅ | ✅ | 未变 |
| Capability First | ✅ | ✅ | 未变 |
| Reason-Act 解耦 | ✅ | ✅ | 未变 |
| CQRS | ⚠️ | ⚠️ | invoke 未区分 Query/Command 路径；通过 idempotency_key 和文档弥补 |
| 规范 ≠ 文档 | ❌ P0-2 | ✅ | 新增 9 条 SDKMUST-R |

### 与 Capability SDK 设计文档的对比

| 维度 | Capability SDK | Runtime SDK v1.0 | Runtime SDK v1.1 |
|:----|:--------------|:----------------:|:----------------:|
| MUST 条款 | 6 条 SDKMUST | 0 条 ❌ P0-2 | 9 条 SDKMUST-R ✅ |
| 错误类型定义 | `errors.py` + 映射表 | 无 ⚠️ | §4.6 完整映射表 + 3 个新异常类 ✅ |
| 数据类定义 | 完整 | 缺少 ResolvedCapability ⚠️ | 全部 7 个数据类已定义 ✅ |
| 包结构 | 源文件齐全 | 8 个源文件（合理）| 9 个源文件 ✅ |
| 测试工具 | MockRuntime（完整设计）| 只有文件名 ❌ P1-7 | §9 完整 MockRuntimeClient 设计 ✅ |
| 架构决策 | 设计即决策 | 4 个未定事项 ❌ | §2 ADR 风格确定协议/认证/流式/重试 ✅ |
| CLI | earp 命令 | 无 CLI | 无 CLI（合理，保持简约） ✅ |

---

## 评审总结

### 数据统计（v1.1 修复后）

| 类别 | v1.0 发现 | v1.1 状态 |
|:----|:---------:|:---------:|
| ✅ 通过的检查项 | 10+ | 保持不变 |
| ❌ P0（必须修复） | 3 | ✅ **全部已修复** |
| ⚠️ P1（建议修改） | 7 | ✅ **全部已修复** |
| 💡 P2（建议性优化） | 3 | ✅ **全部已修复** |

### 三个 P0 全部已修复

| # | 问题 | 修复位置 | 验证 |
|:-|------|:---------|:----:|
| 1 | `search()` 重复定义 | 删除无分页版本，只保留带分页的签名 | ✅ |
| 2 | 缺少 MUST 条款 | 新增 9 条 SDKMUST-R（5 MUST + 3 SHOULD + 1 MAY） | ✅ |
| 3 | invoke 返回 dict | 添加设计说明文档解释原因，新增三层结构映射表 §6.3 | ✅ 降级为 P1（设计决策已文档化） |

### 新增内容（本轮回评审值得注意的亮点）

1. **§2 架构决策** — 4 个 ADR（HTTP/JWT/SSE/指数退避）一次性收敛，而不是留到实现阶段
2. **§4.6 错误映射表** — 7 种异常 × CapabilityErrorCode × HTTP Status × 可重试标记 × 场景，比 Capability SDK 对齐表更完整
3. **§6.3 三层结构映射** — 展示了 Capability SDK ↔ Runtime SDK 在两个域中的对称设计
4. **§9 MockRuntimeClient** — 完整接口设计（register handler / create_session / call），与 Capability SDK 的 MockRuntime 对称
5. **v1.1 文档号** + **§10 评审修复记录** — 让评审→修复→追踪的闭环可追溯

### 总体建议

设计文档 v1.1 已满足对 API 设计评审的标准。所有 P0/P1/P2 问题均已合理修复。文档覆盖了：

- ✅ 清晰的定位（§1）
- ✅ 明确的架构决策（§2）
- ✅ 完整的开发者体验示例（§3）
- ✅ 清晰的核心接口定义（§4）
- ✅ 完整的数据模型定义（§4.5）
- ✅ 完整的错误映射表（§4.6）
- ✅ 可验证的 MUST 约束条款（§5）
- ✅ SDK 关系与映射（§6/§8）
- ✅ 包结构和导出清单（§7）
- ✅ 测试工具设计（§9）

建议进入 **实现阶段（Phase 3）**。
