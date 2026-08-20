# 任务清单 — Chatflow F2: flow 执行器（DAG JSON → 编译 → 对话节点适配层最小集）

**状态：✅ 已完成（2026-08-20）**，验证见 `arch/session-record.md`（追加 2026-08-20 Chatflow F2 段）
**依据**：`arch/design/2026-08-18-chatflow-integration-design.md` §3（节点类型表）/ §4（复用 connector/knowledge_search/conversations.context）/ §7（F2：flow 执行器 + 对话节点适配层 LLM/Knowledge/Chat History/Condition 最小集）
**依赖**：F0 ✅（compile + gate + _execute_plan）/ F1 ✅（flow_schema 落库 + orchestration）
**日期**：2026-08-19

## 目标

1. **flow 可执行**：`POST /chat_apps/{id}/chat` 在 orchestration='flow' 时走图执行（非流式 JSON 响应）——F0 的声明式图第一次有 API 入口
2. **对话节点适配层最小集**：LLM（llm.prompt）/ Knowledge（knowledge.search）/ Chat History（chat.history）编译为可执行 Step + Connector 适配器；Condition 复用 F0 CondExec；变量引用 `{{query}}` / `{{#node.output.path#}}` 落地
3. **零回归**：auto 模式 SSE 链路逐字节不变；F0/F1 全部用例锁；全量 281 + import-linter + ruff/pyright 零新增；OpenAPI 基线同步（chat 端点响应 union）

## 现状（已核实，2026-08-19）

- `_execute_plan`（F0）：pool（node_id → StepResult）+ chosen + gate/skip——StepExec 执行走 `StepRunner.invoke → Connector.execute(capability_call)`；Connector() 无参构造，只支持 demo.echo（4 处实例化点：step_runner/multi_step×2/test）
- `LLMConnector`：有 stream（流式）/ chat_stream（RAG 流式）/ json_complete（JSON 单发）——**无非流式文本生成**
- `chat_service`：`_recent_pairs(engine, tenant, conversation_id, turns)`（历史配对，可直接复用）；`resolve_llm_override(engine, tenant, app)`（模型三级解析）；chat_sse 的会话创建/消息落库流程（add_message/create_conversation 复用）
- `search_chunks(engine, tenant, query_embedding, role_id, top_k, data_domain_ids, knowledge_base_ids, ...)` + `embed_query(query)`（knowledge 节点链路现成）
- chat_ep 端点：当前只支持 auto（SSE）；F1 已让 `app["orchestration"]`/`app["flow_schema"]` 可从 GET 拿到
- Connector 不在 import-linter domain 列表（cross-cutting glue，F0 已有 connector→planner/orchestrator.types 先例）

## 既定决策

| # | 决策点 | 方案 |
|:-:|:---|:---|
| D1 | 执行模型 | **复用 F0 链路**：`MultiStepExecutor.__init__(engine, bus, *, llm=None)` → `StepRunner(engine, *, llm=None)` → `Connector(eventbus=None, *, engine=None, llm=None)` + `execute(capability_call, *, ctx=None)`（ctx 供适配器取 tenant/role/session）；新适配器 `llm.prompt` / `knowledge.search` / `chat.history` 走 Connector，Condition 走 F0 CondExec——不动 _execute_plan 分派 |
| D2 | LLM 非流式 | `LLMConnector.complete(prompt, system="", *, temperature=0.7, max_tokens=None) -> str | None`（ollama /api/chat stream:false + openai /chat/completions，与 _stream_messages 同构 provider-aware；失败返回 None 不抛）——F2 节点非流式，F5a 步进调试友好；SSE 节点级透传 F4/F5a 再做 |
| D3 | 编译扩展 | `compile_flow_schema(schema) -> CompiledWorkflow`（新函数，workflow_dsl）：validate(FLOW_NODE_TYPES) + 拓扑 + gate（抽共享 `_compile_graph` 与 F0 共用）；节点映射：step/capability 原样、llm→`{adapter_type:"llm.prompt", input:{prompt,system?,temperature?,max_tokens?}}`、knowledge→`{adapter_type:"knowledge.search", input:{query?,kb_ids?,data_domain_ids?,top_k?}}`、chat_history→`{adapter_type:"chat.history", input:{turns?}}`、condition→CondExec；**qu/human_approval/tool/mcp → WorkflowValidationError「节点类型未实现（F3+）」**（声明可存、执行明确报错）；F0 `compile_workflow` 行为不变 |
| D4 | 变量引用 | `resolve_templates(value, pool, flow_input) -> Any`（workflow_dsl 纯函数，递归 dict/list/str）：`{{query}}`→flow_input、`{{#node.output#}}`→pool 整体、`{{#node.output.a.b#}}`→嵌套路径；缺失 → 原样保留（运行时报错兜底）；`_execute_plan` 加 `flow_input: dict | None = None`（pool 初始含 `_input`），StepExec invoke 前对 capability_call 做模板替换——F0 legacy（plan=None）零影响 |
| D5 | 端点 | chat_ep 加 flow 分支（orchestration=='flow'）：会话创建/续接（复用 chat_apps 归属 + add_message user）→ compile_flow_schema（失败 422 防御，发布门禁已保证）→ llm = resolve_llm_override(app) 构造或 app.state.llm → `executor.execute(plan.steps, ctx, layers=[], plan=plan, flow_input={"query","conversation_id"})` → outputs（completed 节点）→ assistant 落库（最后 completed 节点 output 的 text 或 json）→ **非流式 JSON** `{execution_id, conversation_id, status, outputs, message_id}`；auto 模式 SSE 不变（端点返回 Union[JSONResponse, StreamingResponse]） |
| D6 | knowledge 节点 | 适配器内：`embed_query(query)` → `search_chunks(engine, tenant, emb, role, top_k, data_domain_ids, knowledge_base_ids, query_text=query)` → `{"chunks": [...], "citations": [...]}`；ctx 提供 tenant/role |
| D7 | 测试策略 | 纯函数层（compile_flow_schema/resolve_templates）+ 适配器层（FakeLLM.complete mock / 真 DB history / monkeypatch embed+search）+ 端点集成（app + migrated + FakeLLM）；回归 F0 33 + F1 17 |
| D8 | import-linter | connector 不在 domain 列表（cross-cutting），→ knowledge/chat_service 引用无契约约束（注释说明）；main.py 是 root 无约束；无新增 ignore_imports 预期 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — workflow_dsl：compile_flow_schema + resolve_templates（0.5-1 天）
**文件**：`src/earp_server/orchestrator/workflow_dsl.py`
- 抽 `_compile_graph(g, builder)` 共享（拓扑+gate+sequence）；`compile_workflow` 改调它（行为不变）；`compile_flow_schema`：validate(FLOW_NODE_TYPES) + 节点映射（D3）+ 未实现类型报错
- `resolve_templates(value, pool, flow_input)`：递归替换（D4 语法）；`_iter_templates` 提取
- 验证：F0 33 用例不回归 + python -c 冒烟（llm/knowledge/chat_history 映射 + qu 报错 + 模板替换）

### Task 2 — Connector 适配器 + LLMConnector.complete（0.5-1 天）
**文件**：`src/earp_server/connector.py`、`src/earp_server/orchestrator/step_runner.py`、`src/earp_server/orchestrator/multi_step.py`
- `LLMConnector.complete`（D2）
- `Connector.__init__(eventbus=None, *, engine=None, llm=None)` + `execute(capability_call, *, ctx=None)`；适配器 llm.prompt（system 拼 `{{query}}` 后的 prompt，调 llm.complete → `{"text": ...}`；llm None → ConnectorError）/ knowledge.search（embed + search_chunks，ctx.tenant_id/role_id）/ chat.history（复用 `chat_service._recent_pairs` 语义——Connector 内联实现或 import，返回 `{"messages": [...]}`）
- StepRunner：`__init__(engine, *, llm=None)` + `_execute_step` 传 Connector(engine=..., llm=...) + ctx；MultiStepExecutor：`__init__(engine, bus=None, *, llm=None)` 透传；`_execute_plan` 加 `flow_input` 参数 + invoke 前模板替换（import resolve_templates）
- 验证：适配器手测脚本（demo 图 + FakeLLM）

### Task 3 — 端点 flow 分支（0.5 天）
**文件**：`src/earp_server/main.py`、`src/earp_server/conversation/chat_service.py`（如需落库 helper）
- chat_ep：`orchestration == 'flow'` → 非流式 JSON（D5）；会话/消息落库复用既有 helper（create_conversation/add_message）；响应 Union
- 验证：dev 真 API 冒烟（FakeLLM 或真实 Ollama）

### Task 4 — 单测（0.5-1 天）
**文件**：`tests/test_flow_executor.py`（新）
- compile_flow_schema：三节点映射 / qu 未实现报错 / gate 与 F0 一致 / F0 compile_workflow 不回归
- resolve_templates：{{query}} / {{#node.output#}} / 嵌套路径 / dict-list 递归 / 缺失键原样
- 适配器：llm.prompt（FakeLLM.complete 断言 system/prompt/temperature）/ chat.history（seed messages → 配对输出）/ knowledge.search（monkeypatch embed_query + search_chunks 断言参数）
- 端点集成：flow app（chat.history → llm）chat → 200 JSON {outputs, status} + messages 落库（user + assistant）；auto 模式 SSE 回归（既有 test_chat 覆盖）

### Task 5 — 质量门 + dev 冒烟 + 收尾（0.5 天）
- 全量 pytest（281 + 新增）+ import-linter + ruff/pyright 零新增 + `make openapi` 同步（chat 响应 union）
- dev 真 API：flow app（含 chat.history + llm 节点）chat → outputs 正确、消息落库、condition 分支只走命中
- 任务书标 ✅ + session-record 补记 + 设计稿 §7 F2 行标 ✅

## 依赖关系

```
Task 1（编译+模板）→ Task 2（适配器+注入）→ Task 3（端点）→ Task 4（测试）→ Task 5（质量门+收尾）
Task 1 与 Task 2 可并行（compile 产物契约 = capability_call 形状）
```

## 验收标准

1. flow app 可通过 `POST /chat_apps/{id}/chat` 真实执行（LLM/Knowledge/Chat History/Condition 最小集）；condition 只走命中分支
2. `{{query}}` / `{{#node.output.path#}}` 模板替换在节点执行前生效（LLM prompt 可见）
3. qu/human_approval/tool/mcp 节点编译报「节点类型未实现」明确错误；auto 模式 SSE 零回归
4. 会话归属/消息落库与 auto 模式一致（conversations.chat_app_id + user/assistant 消息 + citations 从 knowledge 节点）
5. 全量 pytest 绿 + import-linter + ruff/pyright 零新增 + OpenAPI 基线同步
6. dev 真 API：flow chat 端到端冒烟（含条件分支）

## 风险提示

1. **Connector.execute 签名变化**（加 ctx keyword）——4 处实例化点已核实（step_runner/multi_step×2/test），全部兼容更新；demo.echo 行为不变
2. **LLM 节点非流式**——F2 明确不做 token 级 SSE（F4/F5a 与 Human Approval SSE 一起）；LLM 长输出会阻塞到 complete 返回（Ollama 超时 300s，节点级超时后续加）
3. **模板替换缺失键**——原样保留（不静默吞掉），适配器拿到含 {{}} 的字符串由 LLM 端兜底；F5a 前端校验变量引用
4. **knowledge 节点依赖 embedding 服务**——与 auto 模式同链路（embed_query），无新基础设施；mock 测试时 monkeypatch
5. **端点返回 Union**——OpenAPI 会体现（JSONResponse vs SSE 响应模型）；`make openapi` 必须同步（T3 先例）

---
**规划定稿，确认后按执行序开工。**
