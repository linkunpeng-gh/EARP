 # M8 LLM 流式输出代码评审

 **Commit:** `dfc3b81`
 **日期:** 2026-07-20
 **评审范围:** 6 个文件改动 (connector.py, step_runner.py, types.py, main.py, openapi.yaml, test_m1_walking_skeleton.py)

 ---

 ## 1. connector.py — LLMConnector.stream()

 **结论: PASS（P3 建议 2 项）**

 ### httpx.stream() + NDJSON 解析
 - Ollama `/api/chat` with `stream=true` 返回 NDJSON（每行一个 JSON 对象），用 `resp.aiter_lines()` 逐行解析，策略正确。
 - `chunk.get("done")` 区分普通行与结束行；结束行 `content` 为空（`""`），不会被 yield，不会泄露额外 token。处理正确。
 - `msg = chunk["message"]["content"]` 链式路径使用 `.get("message", {}).get("content", "")`，防御性 OK。
 - `httpx.HTTPError` 异常捕获既覆盖 `RequestError`（连接/超时）也覆盖 `HTTPStatusError`（非 2xx），转换到 `ConnectorError` 后抛出。正确。

 **P3** — `connector.py:237` — `except json.JSONDecodeError: continue`
 遇到非法 NDJSON 行时静默跳过，没有任何日志。如果 Ollama 返回了异常格式（极少见但可能），问题将难以排查。建议至少加一行 `logger.warning`。

 **P3** — `connector.py:242-243` — 空 content 时跳过 yield 且不递增 index
 若 LLM 返回了一个非 done 但 content 为空的行，index 序列会产生空洞（例如 token 0, 1, 3）。生产环境极少触发，但不易防御。建议在 `continue` 前也递增 index，或明确注释这是预期行为。

 ### token yield 健壮性
 - yield 的是 `TokenEvent(token=..., index=index)`，每次 yield 后 `index += 1`。索引连续递增，逻辑清晰。
 - `connector.stream()` 不处理 `step_id`（默认为空字符串），由上层 `step_runner.stream()` 封装到 `StepEvent`。职责分离合理。

 ---

 ## 2. step_runner.py — stream()

 **结论: PASS（P3 建议 2 项）**

 ### ctx 可选默认值
 ```python
 if ctx is None:
     ctx = InvokeContext(
         tenant_id="", execution_id="", session_id="", user_id="", role_id="", step=step,
     )
 ```
 - 调用方可以完全不传 `ctx`，简化了非编排场景的使用。LLM 流式路径不使用这些字段，安全。
 - 与 `_execute_step()`（仅非 LLM 路径调用）的兼容性：`_execute_step` 接收 `ctx` 但内部只传给 `Connector.execute()`，Connector 在第 2 个参数未使用 `ctx` 字段。无副作用。

 ### adapter_type='llm.*' 触发流式路径
 ```python
 if adapter_type.startswith("llm.") and llm is not None:
 ```
 - 前缀匹配 `"llm."` 是一个约定式的路由方案，简单可扩展。合理。
 - `llm is not None` 的二重保障避免意外将非 LLM 步骤路由到流式路径。安全。

 **P3** — `step_runner.py:98` — `adapter_type="llm."` 时（仅前缀无后缀）仍会触发 LLM 路径
 生产不会出现，但理论上 `startswith("llm.")` 在只有 `"llm."` 时也返回 True。不影响功能，仅可读性小瑕疵。

 **P3** — `step_runner.py:108-109 vs 126-127` — `step_completed` 事件数据结构不一致
 LLM 路径: `{"status": "completed"}`，非 LLM 路径: `{"result": ..., "checkpoint_id": ...}`。同一 `event_type` 下 schema 不一致，消费者必须同时兼容两种格式。建议统一至少包含 `status` 字段，或明确文档化。

 ---

 ## 3. types.py — TokenEvent + StepEvent 'token'

 **结论: PASS**

 ### TokenEvent
 ```python
 @dataclass
 class TokenEvent:
     token: str
     step_id: str = ""
     index: int = 0
 ```
 - 新类型，只被 `connector.stream()` 使用。`step_id=""` 是合理的设计选择（connector 不持有 step_id）。
 - connector.py 在 `TYPE_CHECKING` 块中导入了 `TokenEvent`（为类型注解），方法体内又做了 `from earp_server.orchestrator.types import TokenEvent`（运行时实例化）。双导入不优雅但无害，符合 `from __future__ import annotations` 下惯用写法。

 ### StepEvent 'token' event_type
 ```python
 event_type: Literal["step_started", "step_completed", "step_failed", "checkpoint_written", "token"]
 ```
 - 向联合类型中添加新字面量只扩张不收缩，是纯向后兼容的变更。
 - 现有消费者（switch/match/if-elif）只会忽略 `"token"`，不会崩溃。
 - 若某处使用 `Literal` 穷尽匹配（如 `type_guard`），需要更新。Python 生态中极少见。

 ---

 ## 4. main.py — POST /stream/invoke SSE 端点

 **结论: PASS（ISSUE P2 × 1，P3 × 2）**

 ### StreamingResponse 用法
 - `StreamingResponse(event_stream(), media_type="text/event-stream")` 是 FastAPI SSE 端的标准模式。正确。
 - `Cache-Control: no-cache` + `X-Accel-Buffering: no` 头为 nginx 反向代理兼容做好了准备。周到。

 ### 错误处理
 ```python
 try:
     async for token in llm.stream(...):
         yield f"data: {json.dumps(...)}\n\n"
     yield "data: [DONE]\n\n"
 except Exception as e:
     yield f"data: {json.dumps({'error': str(e)})}\n\n"
 ```
 - 所有异常被捕获、以 SSE error event 形式推送。`[DONE]` 在异常时不会发出，客户端可以通过 error event 感知故障。正确。
 - `[DONE]` 信号是行业非标准但常见的 SSE 约定。合理。

 **P2** — `main.py:224-226` — HTTP 状态码在错误时仍为 200
 StreamingResponse 一旦开始发送响应体，无法修改 HTTP 状态码。这是一个已知的 SSE 设计取舍——错误只能通过事件体而非状态码传达。当前方案可工作，但建议在 README 或 API 文档中明确约定客户端需检查 `error` 字段。

 **P3** — `main.py:221-228` — 服务端不记录流式错误日志
 错误只通过 SSE 事件流传递到客户端，服务端无日志。调试生产问题时难以回溯。建议添加 `logger.error(...)`。

 **P3** — `main.py:219-220` — LLMConnector 未使用 lifespan 中的 rate_limiter 和 cache
 `llm = LLMConnector(req.app.state.settings)` 创建了一个轻量实例，没有挂载 `rate_limiter` 和 `cache`。目前 `stream()` 不依赖这两者，所以功能没问题，但与 `_call_ollama()` 使用的完整配置不一致。建议后续统一到 `req.app.state.llm` 的单例。

 ---

 ## 5. openapi.yaml — 重新生成

 **结论: ISSUE P2**

 ### schema 正确性
 - `StreamRequest` schema 增加了 `prompt`, `session_id`, `system` 三个字段，与代码中 `StreamRequest` pydantic 模型一致。正确。
 - `/stream/invoke` 路径和 tags 存在。正确。

 **P2** — `openapi.yaml:515` — Response media type 为 `application/json`，实际是 `text/event-stream`
 FastAPI 对 `StreamingResponse` 的 OpenAPI 生成默认使用了 `application/json`。但端点实际返回 `text/event-stream`（通过 `StreamingResponse(media_type="text/event-stream")` 指定）。OpenAPI spec 与运行时行为不一致。

 **建议修复方案：** 手动修正 openapi.yaml 中的 response content type 为 `text/event-stream`，或使用 FastAPI 的 `responses` 装饰器参数覆盖 OpenAPI schema：
 ```python
 @app.post("/stream/invoke", tags=["streaming"], responses={
     200: {"model": None, "content": {"text/event-stream": {}}}
 })
 ```

 ---

 ## 6. test_stream_yields_events — 覆盖度

 **结论: ISSUE P2（覆盖缺口）**

 ### 当前测试覆盖
 | 场景 | 是否覆盖 | 说明 |
 |------|----------|------|
 | 非 LLM 路径 (echo adapter) | ✅ | `capability_call={}` → adapter_type="demo.echo" |
 | stream 至少 yield 2 个事件 | ✅ | 验证了 start + completed/failed |
 | 首个事件为 step_started | ✅ | `events[0].event_type == "step_started"` |
 | **LLM 流式路径** | ❌ | 未传 `llm` 参数，LLM 分支不会触发 |
 | **Token 事件** | ❌ | 从未验证 event_type="token" |
 | **LLM 路径异常处理** | ❌ | `except` 分支未测试 |
 | **/stream/invoke SSE 端点** | ❌ | 无任何 HTTP 请求到该路由 |
 | **connector.stream()** | ❌ | 无 mock 或集成测试 |

 **P2** — `test_m1_walking_skeleton.py:87-97` — 核心 M8 功能（token 流式输出）未被测试覆盖
 测试重命名为 `test_stream_yields_events`，但只覆盖了先前的非 LLM 路径（旧名 `test_stream_raises_not_implemented` 已测试过相同路径）。新增的 LLM 流式逻辑（包括 `TokenEvent` yield、SSE 端点、错误处理）全部裸露。

 ### 建议补充的测试场景
 1. **step_runner.stream() LLM 路径** — mock `LLMConnector.stream()` 返回 2 个 TokenEvent，验证 yield 顺序为 `step_started → token × 2 → step_completed`。
 2. **step_runner.stream() LLM 路径异常** — mock `llm.stream()` 抛出异常，验证 yield `step_failed` 事件。
 3. **/stream/invoke SSE 端点** — 用 `TestClient` 或 `httpx.AsyncClient` 发送 POST 请求，验证 SSE 事件格式和 `[DONE]`。
 4. **connector.stream()** — 单元测试：mock httpx 响应内容，验证 TokenEvent 索引和 token 值。

 ---

 ## 汇总

 | 检查项 | 结论 | 关键问题 |
 |--------|------|----------|
 | 1. connector.py stream + NDJSON | PASS (P3 × 2) | 静默跳过解析异常；index 空洞 |
 | 2. step_runner.py stream | PASS (P3 × 2) | adapter_type 边界；step_completed schema 不一致 |
 | 3. types.py TokenEvent + 'token' | PASS | 向后兼容，设计合理 |
 | 4. main.py SSE 端点 | PASS (P2 × 1, P3 × 2) | HTTP 200 含错误；无服务端日志；LLMConnector 缺少配置 |
 | 5. openapi.yaml | **ISSUE P2** | response media_type 与运行时不一致 |
 | 6. test_stream_yields_events | **ISSUE P2** | 核心 LLM 流式路径无测试覆盖 |

 **无 P0/P1 问题。** 建议优先修复 openapi.yaml media_type（P2）和补全 LLM 流式路径测试（P2），其余 P3 可在后续迭代中清理。
