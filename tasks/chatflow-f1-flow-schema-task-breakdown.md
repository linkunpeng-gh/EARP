# 任务清单 — Chatflow F1: flow_schema 落库 + orchestration 模式（migration + 校验 + 端点）

**状态：✅ 已完成（2026-08-19）**，验证见 `arch/session-record.md`（追加 2026-08-19 Chatflow F1 段）
**依据**：`arch/design/2026-08-18-chatflow-integration-design.md` §2（chat_apps.orchestration auto|flow）+ §7（F1：migration + flow_schema JSONB + 节点类型白名单校验）+ §9 开放问题 1（flow 变更纳入发布评审——F1 落地）
**依赖**：F0 ✅（`workflow_dsl.validate_workflow` 图校验复用）
**日期**：2026-08-19

## 目标

1. **migration 0024**：`chat_apps.orchestration VARCHAR(16) DEFAULT 'auto' CHECK IN ('auto','flow')` + `flow_schema JSONB`（列级 RLS 无感）
2. **flow_schema 校验落端点**：复用 F0 `validate_workflow`（参数化节点类型白名单——设计稿 §3 全部节点类型声明层放开，F2 执行逐步跟上）；create/update/publish 三处校验
3. **零回归**：`orchestration='auto'` 存量语义逐字节不变（前端零改动）；F0 校验默认白名单行为不变；全量 264 + import-linter + ruff/pyright 零新增；OpenAPI 基线同步（`make openapi`）

## 现状（已核实，2026-08-19）

- `chat_apps` 表（migration 0014）：chat_app_id/tenant_id/name/description/system_prompt/kb_scope/retrieval/model_config_id/context_turns/status/created_at/updated_at，RLS 三件套 + earp_app GRANT
- 最新 migration **0023**（eval_sets_governance）→ F1 是 **0024**
- 端点全在 `main.py`：GET/POST/PATCH/DELETE `/chat_apps` + `/chat_apps/{id}/publish` + `/chat_apps/{id}/chat`；`ChatAppCreate`（name 必填）/`ChatAppUpdate`（exclude_unset 全字段）在 main.py 定义
- `chat_app_service.py`：`_UPDATABLE` 白名单 + `_row_to_dict`（JSONB 解析）+ publish 状态机（published 编辑 → 回 draft）；`get_chat_app` 用 `SELECT *`（新列自动带出，`_row_to_dict` 需补 flow_schema 解析）
- F0 `validate_workflow`：节点类型白名单硬编码 `NODE_TYPES={start,end,step,condition}`；节点级校验（step 需 capability_call / condition 需 condition 表达式）；非 condition 节点出边 ≤1
- OpenAPI 基线 `openapi.yaml`（`make openapi` 导出，test_openapi_export 字节比对）
- import-linter：conversation 是独立 domain 模块，跨域 import 需显式 ignore_imports

## 既定决策

| # | 决策点 | 方案 |
|:-:|:---|:---|
| D1 | migration 0024 | `ALTER TABLE chat_apps ADD COLUMN orchestration VARCHAR(16) NOT NULL DEFAULT 'auto' CHECK (orchestration IN ('auto','flow'))` + `ADD COLUMN flow_schema JSONB`；存量行 auto+NULL（后端兼容）；列级改动 RLS 策略不动 |
| D2 | 节点类型白名单 | F0 `validate_workflow` 加参数 `allowed_types: frozenset[str] = NODE_TYPES`（默认行为不变）；新增 `FLOW_NODE_TYPES = NODE_TYPES ∪ {llm, knowledge, qu, chat_history, human_approval, tool, mcp}`（设计稿 §3 全量，snake_case）+ `validate_flow_schema(schema) -> list[str]` 包装（放 workflow_dsl，单一校验实现） |
| D3 | 非内置类型的校验深度 | 扩展类型（llm/knowledge/…）只做**通用图结构校验**（白名单/边引用/无环/start 可达 + 可达 end/非 condition 出边 ≤1）；节点级 data 校验（prompt 存在性等）F2 各自节点适配层做——F1 存合法结构，F2 报「节点类型未实现」明确错误 |
| D4 | orchestration 语义 | 'auto'：现状，flow_schema 可 NULL；'flow'：flow_schema 必填（非空 dict）+ `validate_flow_schema` 通过。create 默认 'auto'（前端零改动）。update 切 flow 时要求合法；改回 auto 时 flow_schema **保留**（切回不重画，flow_schema 是资产）。publish 时 orchestration='flow' 强制重校验（§9 开放问题 1 落地：flow 变更纳入发布评审） |
| D5 | 端点/OpenAPI | ChatAppCreate + `orchestration: str = 'auto'`（非法值 422）+ `flow_schema: dict | None`；ChatAppUpdate + `orchestration`/`flow_schema`（exclude_unset 天然增量）；`_UPDATABLE` + `_row_to_dict` 补两字段；GET 响应带 orchestration/flow_schema；`make openapi` 同步基线 |
| D6 | import-linter | `earp_server.conversation.chat_app_service -> earp_server.orchestrator.workflow_dsl`（flow 图校验单一实现：orchestrator workflow_dsl，F0 编译层与 F1 声明层共用；仿既有 conversation → connector/orchestrator 编排依赖先例） |
| D7 | 测试策略 | 服务级直调（镜像 test_chat_apps 的 app_engine fixture 模式）+ 路由级断言 422；F0 `validate_workflow` 默认白名单不回归（F0 33 用例已锁） |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — workflow_dsl 参数化 + FLOW_NODE_TYPES（0.5 天）
**文件**：`src/earp_server/orchestrator/workflow_dsl.py`
- `validate_workflow(graph, *, allowed_types: frozenset[str] = NODE_TYPES)`：白名单检查改用 allowed_types；fan-out ≤1 检查推广到所有非 condition 节点（图级约束，不只 step）；节点级 data 校验仅对内置类型生效
- `FLOW_NODE_TYPES` 常量 + `validate_flow_schema(schema: dict) -> list[str]` 包装
- 验证：F0 33 用例不回归 + `python -c` 冒烟扩展类型图（llm 节点过校验）

### Task 2 — migration 0024（0.5 天）
**文件**：`migrations/versions/0024_chat_apps_flow.py`（新）
- 两个 ADD COLUMN + CHECK 约束；downgrade 两列
- 验证：`make migrate` 或 pytest migrated fixture 自动应用（全量测试跑一遍即验证）

### Task 3 — service + schema + 端点（0.5-1 天）
**文件**：`src/earp_server/conversation/chat_app_service.py`、`src/earp_server/main.py`
- service：`_ORCHESTRATIONS = ("auto", "flow")`；`_validate_flow(fields)`（flow 模式 schema 必填 + validate_flow_schema；auto 模式 schema 可空）；`_UPDATABLE` 加两字段；`create_chat_app` 加 orchestration/flow_schema 参数（校验后落库）；`update_chat_app` 处理（含 published 回 draft 语义不变）；`publish_chat_app` flow 模式强制重校验；`_row_to_dict` 解析 flow_schema JSONB
- main.py：ChatAppCreate/ChatAppUpdate 加字段；create/update 端点 catch ValueError → 422（flow 校验错误）
- pyproject.toml：ignore_imports 加 `conversation.chat_app_service -> orchestrator.workflow_dsl`（注释说明）
- 验证：dev 真 API 冒烟（见 Task 5）

### Task 4 — 测试（0.5-1 天）
**文件**：`tests/test_chat_app_flow.py`（新，镜像 test_chat_apps fixture 模式）
- create：默认 auto + flow_schema null；flow + 合法图 → 201 orchestration=flow；flow + 非法图（环/未知类型/悬空边）→ 422 明确错误；flow 无 schema → 422；orchestration 非法值 → 422；llm 扩展类型图过校验（白名单放开）
- update：切 flow + 合法图；flow 非法图 → 422 不落库；published 编辑回 draft（既有语义）；auto→flow→auto schema 保留
- publish：flow 模式非法图 → 422（发布门禁）；合法图 → published
- get：flow_schema JSONB 往返解析正确
- 回归：F0 33 用例 + test_chat_apps 既有 7 用例全绿

### Task 5 — 质量门 + dev 冒烟 + 收尾（0.5 天）
- 全量 pytest（264 + 新增）+ import-linter + ruff/pyright 零新增
- `make openapi` 同步基线（openapi.yaml 差异仅 ChatApp schema 两个字段）
- dev 真 API：建 flow app（合法图）→ 201；改非法图 → 422；publish → 校验通过/拒绝；GET 返回 flow_schema
- 任务书标 ✅ + session-record 补记 + 设计稿 §7 F1 行标 ✅

## 依赖关系

```
Task 1（validate 参数化）→ Task 2（migration，可并行）→ Task 3（service+端点）→ Task 4（测试）→ Task 5（质量门+收尾）
```

## 验收标准

1. `chat_apps.orchestration`（auto|flow）+ `flow_schema JSONB` 落库；存量 app 保持 auto 语义不变
2. flow_schema 校验落 create/update/publish：非法图（环/未知类型/边引用/不可达/出边超限）422 明确错误；设计稿 §3 全节点类型白名单可存
3. publish flow 模式强制重校验（flow 变更纳入发布评审）；published 编辑回 draft 语义保持
4. F0 `validate_workflow` 默认白名单行为不变（F0 33 用例锁）；既有 chat_apps 7 用例全绿
5. 全量 pytest 绿 + import-linter + ruff/pyright 零新增；OpenAPI 基线同步且 diff 仅 ChatApp schema
6. dev 真 API：flow app 建/改/发布/读全链路冒烟

## 风险提示

1. **白名单放开的执行缺口**：F1 允许存 llm/knowledge 等节点，但 F0 编译层不认——F2 执行器对未实现类型报「节点类型未实现」，勿在 F1 造执行假象（无执行端点，只存不跑）
2. **OpenAPI 基线**：必须 `make openapi` 同步，否则 test_openapi_export 挂（T3 先例：+173 行）
3. **create 语义变化面**：ChatAppCreate 加字段是 additive——前端不传 orchestration 时默认 'auto'，零改动
4. **publish 门禁误伤**：存量 flow 模式 app 若 flow_schema 非法（早期手工改库），publish 会被拒——属预期（发布评审），报错信息要指明是 flow_schema 校验失败
5. **RLS**：列级改动无感；flow_schema 是 tenant 作用域数据（随行走 RLS），无独立表

---
**规划定稿，确认后按执行序开工。**
