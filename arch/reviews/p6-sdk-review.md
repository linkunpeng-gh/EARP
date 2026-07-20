# P6 Runtime SDK 代码评审报告

**评审范围**: `d962666..b7c6141`
**提交**: `b7c6141` — feat: P6 Runtime SDK — stream_invoke() + plan()
**评审日期**: 2026-07-20

---

## 1. `client.py stream_invoke()`: SSE 解析

**结论：PASS（功能正确，含 2 个 P1 问题）**

`httpx.AsyncClient().stream()` + `response.aiter_lines()` 的模式对当前场景可用。`aiter_lines()` 按 `\n` 切分，代码用 `if not line or not line.startswith("data: ")` 跳过空行和非 data 行，准确提取 `data:` 前缀行，SSE 事件边界处理正确。

**ISSUE-1 (P1)**: `stream_invoke()` 新建独立的 `httpx.AsyncClient(timeout=300)`，没有复用 `self._client`。
- 行: [client.py:177](/Users/linkunpeng/work/EARP/libs/earp-sdk-runtime-py/src/earp_sdk_runtime/client.py#L177)
- 问题: 新建 client 丢失了 `__init__` 中配置的 `User-Agent` header，且无法利用已有的连接池。虽然手动传了 `Authorization` header（条件式），但整体与 `create_session()`、`call()`、`plan()` 等方法不一致——那些方法都走 `self._client`。
- 建议: 将 SSE streaming 逻辑改为使用 `self._client`（可能配合 `httpx.Timeout(connect=10, read=300, pool=10)` 更精细的 timeout 配置）。如果不能复用（例如担心连接池阻塞），应至少从 `self._client` 继承 headers。

**ISSUE-2 (P1)**: timeout 硬编码且未区分 timeout 阶段。
- 行: [client.py:177](/Users/linkunpeng/work/EARP/libs/earp-sdk-runtime-py/src/earp_sdk_runtime/client.py#L177)
- 问题: `AsyncClient(timeout=300)` 将所有 timeout 阶段（connect、read、write、pool）都设为 300s。connect 超时 300s 会阻塞 SDK 调用方过久，无法快速发现服务不可达。pool 超时 300s 对连接池而言也过于宽松。
- 建议: 使用 `httpx.Timeout(connect=10, read=300, pool=5)` 或类似分级值。

观察（非 issue）: `import json` 写在函数体而非文件顶部，与其他 import 风格不一致。功能无影响。

---

## 2. `client.py stream_invoke()`: `[DONE]` 终止信号

**结论：PASS**

```python
if data_str == "[DONE]":
    yield {"token": "[DONE]", "index": -1}
    return
```

- `yield` 后立即 `return` 触发 `StopAsyncIteration`，生成器正确终止。yield 的事件结构与 docstring 承诺一致（`{"token": "[DONE]", "index": -1}`）。
- 如果服务端在 `[DONE]` 后继续发数据，这些数据被忽略——符合 SSE 约定，服务端不应在终止信号后发数据，无问题。

---

## 3. `client.py stream_invoke()`: 错误事件 `{"error": ...}`

**结论：PASS（含 1 个 P2 优化点）**

错误事件按普通 JSON 事件 yield 出去，调用方需要检查 dict 中是否有 `"error"` 键。功能正确。

**ISSUE-3 (P2)**: 错误事件后继续 yield 后续事件。
- 行: [client.py:192-196](/Users/linkunpeng/work/EARP/libs/earp-sdk-runtime-py/src/earp_sdk_runtime/client.py#L192-L196)
- 说明: 如果服务端发送 `{"error": ...}` 事件后仍继续推送数据，当前实现会继续 yield 下来。建议在 yield error 事件后 return，因为一旦服务端报了 error，后续数据通常不可信。但这是后端行为的假设，且该 SDK 版本可能有意暴露低层级透传，不强制。

**ISSUE-4 (P2)**: 事件类型过于宽松。
- 行: [client.py:175](/Users/linkunpeng/work/EARP/libs/earp-sdk-runtime-py/src/earp_sdk_runtime/client.py#L175)
- 说明: 返回类型 `AsyncGenerator[dict[str, Any], None]` 对事件结构无约束。建议引入 `@dataclass` 或 `TypedDict` 区分 token 事件和 error 事件，让调用方能更安全地 match。

---

## 4. `client.py plan()`: POST /plan 端点

**结论：PASS**

- 使用 `self._client` 发起 POST，和 `create_session()` 等保持一致。
- body `{"intent": intent}` 符合预期接口设计。
- timeout=30 合理（非 streaming 请求）。
- `raise_for_status()` 处理 HTTP 错误，`data.get("steps", [])` 对缺失字段有防御性。

**ISSUE-5 (P2)**: 缺少对 `steps` 中条目结构的验证。
- 行: [client.py:207-215](/Users/linkunpeng/work/EARP/libs/earp-sdk-runtime-py/src/earp_sdk_runtime/client.py#L207-L215)
- 说明: 返回 `list[dict[str, Any]]`，如果服务端返回异常结构（如 `capability_id` 为 null 或缺失），调用方会拿到格式异常的 dict，问题暴露在 SDK 使用层。建议在发现无效条目时 logging warning 并过滤，或抛出一个明确的解析异常。

---

## 5. `test_stream_plan.py`: 测试覆盖 + Mock Transport

**结论：PASS（覆盖合理，含 2 个 P2 优化点）**

### 已有覆盖

| 测试 | 覆盖路径 |
|------|----------|
| `test_stream_tokens` | SSE 正常 token 流 → yield 3 个事件 + [DONE] 终止 |
| `test_plan_intent` | plan() 正常调用 → 解析 steps 列表 |
| `test_stream_error_event` | SSE error 事件 → yield `{"error": ...}` |

### Mock Transport 模式

`httpx.MockTransport` 替换 `self._client` 的 transport，是 httpx 官方推荐的 mock 方式。handler 在 `httpx.Request` 上 assert 并返回 `httpx.Response`，模式正确。

**ISSUE-6 (P2)**: `_make_client` 重建 `_client` 时丢失 `User-Agent` header。
- 行: [test_stream_plan.py:15-20](/Users/linkunpeng/work/EARP/libs/earp-sdk-runtime-py/tests/test_stream_plan.py#L15-L20)
- 说明: `httpx.AsyncClient(transport=MockTransport(handler), headers={"Authorization": "Bearer test-token"})` 没有设置 `User-Agent`。真实 `RuntimeClient.__init__` 的 client 包含 `{"User-Agent": USER_AGENT}`。MockTransport 不检查 headers 所以测试能通过，但环境和生产不完全一致。
- 此外，`_make_client` 先创建了带真实 transport 的 `RuntimeClient`，马上又替换掉 `_client`，多创建了一个 `AsyncClient`。虽然测试场景下不严重，但可重构为：在构造 `RuntimeClient` 前就注入 mock client。

**ISSUE-7 (P2)**: 缺失覆盖路径建议。
- `stream_invoke()` HTTP 非 2xx 响应（如 401/500）→ `raise_for_status()` 是否会抛出合理异常
- `stream_invoke()` JSON 解析失败的行 → `json.JSONDecodeError` 被 `continue` 安静跳过
- SSE 事件中非 `data:` 前缀行（如注释 `:` 开头）被忽略
- `plan()` 响应中缺少 `"steps"` 键 → 返回 `[]`
- `plan()` 返回空 steps 列表 → 返回 `[]`
- 建议补充至少 HTTP 错误和 JSON 解析失败两个边缘 case，放在 `TestStreamInvoke` 和 `TestStreamError` 中。

---

## 汇总

| 检查项 | 结论 | 关键问题 |
|--------|------|----------|
| 1. SSE 解析 | PASS | ISSUE-1 (P1) 新建独立 client 丢失 User-Agent；ISSUE-2 (P1) timeout 未分阶段 |
| 2. [DONE] 终止 | PASS | 无问题 |
| 3. 错误事件 | PASS | ISSUE-3 (P2) error 后继续 yield；ISSUE-4 (P2) 类型可加强 |
| 4. /plan 端点 | PASS | ISSUE-5 (P2) 缺少 steps 条目结构验证 |
| 5. 测试覆盖 | PASS | ISSUE-6 (P2) mock 缺 User-Agent；ISSUE-7 (P2) 建议补充边缘 case |

**P0: 0 | P1: 2 | P2: 5**

主要风险：`stream_invoke()` 的独立 `AsyncClient` 设计不一致（P1），建议优先对齐到 `self._client`。其余为优化级，不影响当前功能正确性。
