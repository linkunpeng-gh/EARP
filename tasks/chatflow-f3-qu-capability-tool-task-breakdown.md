# 任务清单 — Chatflow F3: QU 节点 + Capability/Tool 节点

**状态：✅ 已完成（2026-08-20，connector 适配器 qu.answer/capability.call/tool.fetch 交付，F6 依赖已验证）
**依据**：`arch/design/2026-08-18-chatflow-integration-design.md` §3（节点类型表）/ §7（F3：QU/Plan 节点化 + Capability 节点）
**依赖**：F0 ✅（compile/gate/_execute_plan）/ F1 ✅（flow_schema 落库）/ F2 ✅（flow 执行器最小集 LLM/Knowledge/Chat History/Condition）
**日期**：2026-08-20

## 目标

1. **qu 节点**：`execute_plan` 完整链路包装为图节点（understand → select_plan → 策略执行 → PlanResult evidence/citations）——flow 里放 QU = 自动理解子问题（Dify 没有的差异化）
2. **capability 节点**：flow 的 capability 节点从 demo.echo 扩展到**真实能力执行**（复用 M3 data_adapter / 既有 adapter 分派）+ **审批/审计挂载**（对齐 orchestrator Layers）
3. **tool 节点**：复用 M3 中台连接体系（connector_configs 加密配置 + data_adapter REST/DB 取数）
4. 零回归：F0/F1/F2 全部用例锁（compile_flow_schema 对 qu/tool 从「未实现报错」改为「可编译」）

## 现状（已核实，2026-08-20）

- `FLOW_NODE_TYPES` 含 qu/tool/mcp/capability/human_approval；F2 的 compile_flow_schema 对 **qu/tool/mcp/human_approval 编译报「节点类型未实现（F3+）」**；`capability` 已是 step 别名（`data.capability_call` 同 step 校验，走 `Connector.execute` → **demo.echo 硬编码**）
- `Connector.execute` 现有 adapter：`demo.echo / llm.prompt / knowledge.search / chat.history`（F2）；`execute(capability_call, *, ctx)` 注入 engine/llm
- **M3 `data_adapter.fetch(cfg, params)`**（REST/DB 取数，列名白名单防注入）+ `connector_service.decrypt_config`（AES 加密配置）——tool 节点现成复用点
- `execute_plan(engine, tenant, role, query, structured_query, *, settings, context, top_k)`——需先 `understand()`（`build_structured_query` + `upgrade_with_llm` 可选）得到 StructuredQuery
- **flow 执行 `layers=[]`**（F2 D5）——capability 节点目前无 Policy/Audit 层
- `mcp/server.py` 存在（MCP 端点）但对接成本高——一期不接
- 基线：347 tests 全绿（M3 后）

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | qu 节点输入/输出 | 节点 data：`{query?: 模板表达式（默认 {{query}}）, context_turns?: int}`；适配器内完整链路：`understand(engine, tid, query, context=会话上下文)` →（可选 upgrade_with_llm）→ `select_plan` → `execute_plan` → 输出 `{"selection": {plan_name, fallback_reason}, "evidence": [...], "citations": [...], "chunks": [...]}`——PlanResult 三源直接进 citations（下游 LLM 节点可 `{{#qu.citations#}}`） |
| D2 | capability 节点执行 | adapter 分派扩展：`demo.echo` 保留 + **`capability.call`**（business_capabilities 注册表校验：capability 存在 + required_permissions 含角色权限 → 否则 ConnectorError）；**审批/审计挂载**：flow 执行对 capability 节点启用 `layers=[AuditLayer, PolicyLayer]`（对齐 orchestrator；flow 其它节点不挂）——Saga 补偿留 F4/后续 |
| D3 | tool 节点一期 | **复用 M3 连接体系**：data 含 `{connector_id, params?: 模板表达式}` → 适配器 `decrypt_config` → `data_adapter.fetch` → `{"rows": [...], "count": n}`；REST/DB 两类即覆盖中台对接场景；MCP 节点留后续（mcp/server.py 已存在但对接成本高） |
| D4 | 编译映射 | `compile_flow_schema`：qu → `{adapter_type:"qu.answer", input:{query, context_turns?}}`、capability → `{adapter_type:"capability.call", input:{capability_id?}}`（兼容 step 的 capability_call 形状）、tool → `{adapter_type:"tool.fetch", input:{connector_id, params?}}`；**human_approval/mcp 仍报「未实现（F4 或后续）」** |
| D5 | 变量引用 | `resolve_templates` 复用（`{{#qu.citations#}}` 等嵌套路径已支持）；qu/tool 的 params 模板解析与现有节点一致 |
| D6 | 测试策略 | 适配器层（mock understand/execute_plan / mock data_adapter.fetch / 真 connector_configs 加密配置）+ 编译层（qu/capability/tool 可编译 + human_approval 仍报错）+ 端点集成（flow 含 qu→llm 链、capability 权限拒绝、tool 取数）；回归 F2 17 + F1 17 + F0 33 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — compile_flow_schema 扩展（0.5 天）
**文件**：`src/earp_server/orchestrator/workflow_dsl.py`
- qu/capability/tool 节点编译映射（D4）；human_approval/mcp 保持「未实现」报错
- 校验：qu data.query 模板合法；capability data 兼容 capability_call/input 两种形状；tool data.connector_id 非空
- 验证：编译单测 + 既有报错用例更新（qu/tool 从「未实现」改「可编译」）

### Task 2 — Connector 适配器扩展（0.5-1 天）
**文件**：`src/earp_server/connector.py`
- `qu.answer` 适配器：understand → execute_plan → PlanResult 映射（D1）；ctx 提供 engine/tenant/role/会话上下文
- `capability.call` 适配器：business_capabilities 校验 + 权限（D2）+ `demo.echo` 兼容
- `tool.fetch` 适配器：decrypt_config → data_adapter.fetch（D3，import-linter：connector→ontology.data_adapter 需确认契约——connector 是 cross-cutting 无 domain 约束，参考 F2 先例）
- 验证：适配器单测（mock 各依赖）

### Task 3 — flow 执行挂载 Layers（0.5 天）
**文件**：`src/earp_server/conversation/chat_service.py`、`src/earp_server/orchestrator/layers.py`（如需）
- flow 执行对 capability 节点启用 AuditLayer/PolicyLayer（D2）——审计 earp.capability.call.* 事件 + required_permissions 门禁
- 非 capability 节点（llm/knowledge/qu/tool）不挂层（避免噪音）
- 验证：端点集成（权限拒绝 403、审计事件落 audit_logs）

### Task 4 — 单测 + 集成（0.5-1 天）
**文件**：`tests/test_flow_executor.py`（扩展）、`tests/test_flow_f3_nodes.py`（新，如需）
- 编译：qu/capability/tool 可编译、human_approval/mcp 报错
- 适配器：qu.answer（mock understand/execute_plan 断言 citations 透传）、capability.call（存在/权限拒绝）、tool.fetch（真 connector 加密配置 + mock fetch）
- 集成：flow 图 `start→qu→llm→end`（qu citations 进 llm 上下文）、`start→capability→end`（权限/审计）、`start→tool→end`（取数结果）
- 回归：F0 33 + F1 17 + F2 17

### Task 5 — 质量门 + dev 冒烟 + 收尾（0.5 天）
- 全量 pytest + import-linter + OpenAPI 基线（新 adapter 不新增端点，应无变化）+ ruff/pyright 零新增
- dev 真 API：flow 图含 qu 节点（真模型理解）+ capability/tool 冒烟
- FDE 指南 §14 补 qu/capability/tool 节点说明；session-record 补记 + F3 标 ✅

## 依赖关系

```
Task 1（编译）→ Task 2（适配器）→ Task 3（Layers）→ Task 4（测试）→ Task 5（收尾）
Task 2 的 qu.answer 与 capability/tool 可并行；Task 3 依赖 capability 适配器完成
```

**建议执行序**：`1 → (2a qu, 2b capability/tool 并行) → 3 → 4 → 5`

## 验收标准

1. flow 图可放置 qu/capability/tool 节点并真实执行（非 demo.echo）
2. qu 节点输出 PlanResult citations 供下游引用（`{{#qu.citations#}}`）
3. capability 节点走权限门禁（无权限拒绝）+ 审计事件
4. tool 节点经 M3 connector 体系取数（REST/DB）
5. human_approval/mcp 编译仍明确报错（F4/后续）
6. 全量 pytest 绿 + import-linter + OpenAPI 无变化 + ruff/pyright 零新增
7. dev 真 API 冒烟：qu→llm 链 / capability 权限 / tool 取数

## 风险提示

1. **execute_plan 的 settings 注入**：qu.answer 适配器需要 settings（QueryContext 用）——Connector 无 settings；需从 ctx 或 engine 侧构造（flow_chat 已有 settings，注入 adapter）
2. **business_capabilities 校验语义**：注册表是「能力声明」——真实执行仍是 adapter 分派；「审批」若指 CQRS 命令审批（架构概念），当前未实现命令审批流——**一期 capability 节点只做权限+审计，命令审批流记遗留**（避免范围膨胀）
3. **tool 节点权限**：connector 是 admin 配置（M3 门禁）——tool 节点执行沿用 connector 归属租户即可，无需额外门禁；但**取数结果**进 citations 需过角色域（M3 review 修复 B 的教训——tool 结果若是实体数据要按角色域过滤，一期 tool 输出 raw rows 标注「未过滤」或由上层 knowledge 节点做域过滤）
4. **Layers 作用域**：layers 是 executor 级（全局）——「仅 capability 节点挂层」需 StepRunner 内按 adapter_type 判断或拆分执行（核实 orchestrator 的 layer 钩子粒度，必要时 adapter 内自做审计）

---
**规划定稿，确认后开工。**
