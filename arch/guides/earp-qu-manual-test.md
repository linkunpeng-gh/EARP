# EARP QU 链路手动功能测试指南（Phase B/C/D + 前端适配）

> 覆盖：Query Understanding 理解层（Phase B）→ 固定策略 Planner（Phase C）→
> 能力闭环 + 角色层 + chat 接入（Phase D）→ 前端展示。
> 测试方式：API curl（真实模型 bge-m3 + qwen2.5:1.5b）+ 浏览器前端。
> 依据：QU 设计 v0.3（§6/§11/§17）+ 任务书 Phase B/C/D。

---

## 0. 前置准备

### 0.1 环境（已就绪，无需重启）

| 服务 | 地址 | 状态 |
|---|---|---|
| API | http://127.0.0.1:8000 | ✅ 运行中（已带 `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434` 重启，LLM 升级场景可用） |
| Ollama | http://127.0.0.1:11434 | ✅ qwen2.5:1.5b + bge-m3 |
| Dev DB | localhost:5433 | ✅ alembic head 0016 |

> 若 API 进程是旧代码启动的（uvicorn --reload 会自动重载），遇行为不符可重启：
> ```bash
> cd apps/earp-server && EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434 make api
> ```

### 0.2 Seed 数据（verify-planning 租户）

已通过 `scripts/verify_planning.py` 灌入（本指南测试依赖）：

**实体**（7 个）：CNC-01(设备) / 华东一厂(工厂) / A产线(产线) / 上海某精机(供应商) / 张工(员工) / 高温报警(报警) / 主轴轴承(部件)

**关系事实**（8 条）：CNC-01→manufactured_by→上海某精机、CNC-01→located_in→华东一厂、CNC-01→belongs_to→A产线、高温报警→caused_by→CNC-01、主轴轴承→belongs_to→CNC-01、主轴轴承→supplied_by→上海某精机、A产线→responsible_for→张工、CNC-01→maintained_by→张工

**知识库**（3 个）：kb-vp-maint(设备维护手册/equipment_data)、kb-vp-alarm(报警阈值配置/equipment_data)、kb-vp-fin(费用报销手册/finance_data)

**能力**：cap-vp-alarm（query_equipment_alarm，type=query，映射 equipment）

**角色**：vp-role（data_domain_access = equipment_data + finance_data）

> 重新灌 seed（幂等，清空重灌）：
> ```bash
> cd apps/earp-server && EARP_MIGRATION_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5433/earp' \
>   EARP_OLLAMA_BASE_URL='http://127.0.0.1:11434' EARP_OLLAMA_CHAT_MODEL='qwen2.5:1.5b' \
>   uv run python scripts/verify_planning.py
> ```

### 0.3 Token

```bash
TOKEN=$(cd apps/earp-server && .venv/bin/python -c "
import jwt; print(jwt.encode({'sub':'u1','tenant_id':'verify-planning','role_id':'vp-role','exp':9999999999},'earp-dev-secret-change-in-production',algorithm='HS256'))")
echo $TOKEN
```

### 0.4 JSON 阅读辅助

```bash
alias jq='python3 -m json.tool'   # 或直接用 jq 工具
```

---

## A. Query Understanding 理解层（Phase B）

> 端点：`POST /v1/ontology/understanding/debug`
> 体：`{"query": "...", "context": {...}}`（context 可选，指代消解用）
> 核心响应字段：`structured_query`（intent/entities/relations/constraints/time/confidence）、`rule_fields`（hit/miss）、`field_reasons`、`derive_needs`、`llm_upgraded`

### A1. 高置信 FACT（规则层零 LLM）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"2024 年财务部的报销制度是什么"}'
```

**期望**：
- `structured_query.intent` = `FACT`
- `structured_query.constraints` = `{"year": 2024}`
- `rule_fields.intent` = `hit`；`relevant_fields` 含 intent/constraints
- `confidence` ≥ 0.7；`llm_upgraded` = **false**（规则层直接产出，零 LLM）

### A2. RELATION + 实体命中

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 由哪家供应商制造"}'
```

**期望**：
- `structured_query.intent` = `RELATION`
- `structured_query.entities` 含 `{"mention": "CNC-01", "semantic_type": "equipment"}`
- `structured_query.relations` 含 `{"subject": "CNC-01", "relation": "manufactured_by", "object_type": "supplier"}`
- `derive_needs.relation_reasoning` = true；`derive_needs.entity_resolution` = true

### A3. 低置信度 → LLM 升级（真实 qwen 调用）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"为什么主轴轴承最近故障增加"}'
```

**期望**：
- `llm_upgraded` = **true**（低置信 → 走 qwen 升级，仅补未命中字段）
- `structured_query.intent` 被 LLM 补为 `CAUSAL`（或仍回落——取决于 LLM；此时 `rule_fields.intent=miss` + `field_reasons.intent` 有回落说明，**符合 QP-14 不静默当 FACT**）
- `relation_candidates_used` 非空（TBox 动态候选溯源）

### A4. 回落类 intent（COMPARISON，7 类不建关键词）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"A产线和B产线的设备故障率对比"}'
```

**期望**：
- 规则层 `rule_fields.intent` = `miss`（"对比"不在关键词表）→ LLM 升级尝试
- 若 LLM 判定 COMPARISON → intent=COMPARISON（映射 plan_aggregation）；若未升级 → 兜底 FACT + `field_reasons` 标注
- **不得**静默给 FACT 而不标注（QP-14 检查点）

### A5. 指代消解（多轮上下文）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"它是哪家供应商生产的","context":{"conversation_id":"c1","last_entities":[{"mention":"CNC-01","semantic_type":"equipment"}]}}'
```

**期望**：
- `structured_query.entities` 含 CNC-01（"它" → 上文实体映射）
- `structured_query.relations` 含 manufactured_by（subject=CNC-01）

### A6. 纯中文实体长查询（反向子串修复回归）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"高温报警由什么引起"}'
```

**期望**：
- `structured_query.entities` 含 `{"mention": "高温报警", "semantic_type": "alarm"}`
- `structured_query.relations` 含 caused_by

---

## B. 固定策略 Planner（Phase C）+ 能力执行（Phase D）

> 端点：`POST /v1/ontology/understanding/plan-debug`
> 体同 debug（额外返回 `select_plan` + `plan_result`）
> 核心字段：`select_plan`（plan_name/fallback_reason）、`plan_result`（evidence[channel/role/conflict/payload]/citations/trace[type/input/output/latency_ms]）

### B1. plan_fact（文档事实）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"2024 年财务部的报销制度是什么"}'
```

**期望**：
- `select_plan.plan_name` = `plan_fact`
- `plan_result.trace` 步进完整：`DD_ROUTING → VECTOR_SEARCH → FUSION_RERANK`（finance_data 无 keyword，走向量 lane + 全租户/DD 兜底）
- `plan_result.evidence` 全 `channel=chunk`（报销制度是文档事实）
- evidence 带 `role`：FACT → chunk 为 `primary`

### B2. plan_relation（实体 + 图谱）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 由哪家供应商制造"}'
```

**期望**：
- `select_plan.plan_name` = `plan_relation`
- `plan_result.trace` 含 `RESOLVE_ENTITY → GRAPH_QUERY`
- `plan_result.evidence` 含 `channel=graph`（content 含 `manufactured_by → 上海某精机`）；RELATION → graph 为 `primary`（§8.2）
- `plan_result.citations` 含 `{"source":"graph", ...}`

### B3. plan_relation 解析失败 → 回落 plan_fact

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"不存在的实体xyz"}'
```

**期望**：
- `plan_result.plan_name` = `plan_fact`
- `plan_result.fallback_reason` 含 `entity resolution failed`

### B4. plan_aggregation 真实聚合（D2 边界解除，Phase D 核心）

```bash
# 用 equipment 实体查询（cap-vp-alarm 映射 equipment）→ 真实聚合
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 有多少次故障"}'
```

**期望**：
- `structured_query.intent` = `AGGREGATION`；`select_plan.plan_name` = `plan_aggregation`
- `plan_result.trace` 含 `CAPABILITY_QUERY`，其中一步 `output.executed = true`
- `plan_result.evidence` 含 `channel=capability`：
  - `payload.aggregate.count` = 1（equipment 域设备计数）
  - `payload.capability_id` = `cap-vp-alarm`
  - `role` = `primary`（AGGREGATION → capability 主证据，§8.2）
- `plan_result.fallback_reason` = **null**（不再「通道未就绪」回落）

**边界演示（resolve 无候选 → 回落，正确行为）**：
```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"华东一厂有多少台设备"}'
```
→ `select_plan=plan_aggregation` 但 `plan_result.plan_name=plan_fact` + `fallback_reason` 含 `no query capability candidate`——因为 cap-vp-alarm 只映射 equipment，plant 实体反查不到 capability（§6.5 按实体类型反查），**属预期回落**

### B5. 角色层主/佐证（§9.2）

```bash
# RELATION → graph primary（上文 B2 已验）；FACT → chunk primary
curl -s -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"设备维护手册"}'
```

**期望**：
- FACT → evidence 首个 `role=primary` 且 `channel=chunk`
- 若含 graph/profile 佐证 → `role=auxiliary`

---

## C. Chat 链路（Phase D：软路由路径走 planner）

> 端点：`POST /chat_apps/{id}/chat`（SSE）
> 先建 chat_app（无 kb_scope → 软路由走 planner）：
> ```bash
> APP_ID=$(curl -s -X POST localhost:8000/chat_apps -H "Authorization: Bearer $TOKEN" \
>   -H 'Content-Type: application/json' -d '{"name":"手动测试助手"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['chat_app_id'])")
> echo $APP_ID
> ```

### C1. 实体 + 关系查询（引用溯源）

```bash
curl -N -X POST localhost:8000/chat_apps/$APP_ID/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 由哪家供应商制造"}'
```

**期望**（SSE 流式：token* → done）：
- done 事件 `citations` 含 `{"source":"graph", "title":"图谱：manufactured_by → 上海某精机", ...}`
- 回答内容包含 "上海某精机" + 引用编号 `[N]`（图证据 → context block）

### C2. 聚合查询（capability 结构化结果）

```bash
curl -N -X POST localhost:8000/chat_apps/$APP_ID/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 有多少次故障"}'
```

**期望**：
- done 事件 `citations` 含 `{"source":"capability", "capability_id":"cap-vp-alarm", "aggregate":{"count":1}, ...}`
- 回答基于聚合数据（"1 次"类表述）+ 引用编号（📊聚合引用卡）

### C3. kb_scope 限定路径（一期不接 planner，回归）

```bash
APP_KB=$(curl -s -X POST localhost:8000/chat_apps -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"限定KB助手"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['chat_app_id'])")
curl -s -X PATCH localhost:8000/chat_apps/$APP_KB -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"kb_scope":["kb-vp-alarm"]}' > /dev/null
curl -N -X POST localhost:8000/chat_apps/$APP_KB/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"设备维护"}'
```

**期望**：citations 全部为 chunk 且 `kb_id` 均为 `kb-vp-alarm`（限定 KB，不走 planner 三层）

---

## D. 前端展示

> 启动：`cd apps/earp-admin && python3 -m http.server 8080` → 浏览器打开 http://localhost:8080
> 登录态：API 端口 8000 已在后台跑，前端相对链接即可访问（或直接开 index.html）

### D1. QU 调试页（理解 + 运行策略）

1. 知识中心 → 「探索验证」组 → 「QU 调试」（`pages/understanding-debug.html`）
2. 输入 `CNC-01 由哪家供应商制造` → 点 **🧠 理解**
   - **期望**：intent=RELATION、entities 卡（CNC-01·equipment·subject）、relations 卡（CNC-01 → manufactured_by → supplier）、confidence 数值、字段命中表全 hit
3. 点 **🗺 运行策略**
   - **期望**：select_plan 卡（plan_relation）、Execution Trace 表（RESOLVE_ENTITY → GRAPH_QUERY，含耗时 ms）、Evidence 表（🕸 graph 行 + **主证据**徽标）
4. 输入 `为什么主轴轴承最近故障增加` → 理解
   - **期望**：低置信度 → **🧠 LLM 升级**徽标 + intent 被补（CAUSAL 或回落标注）
5. 输入 `A产线和B产线的设备故障率对比` → 理解
   - **期望**：intent 显示**显式回落**徽标 + 原因（QP-14）

### D2. Chat 编辑页引用卡（四源徽标）

1. 工作台 → 应用中心 → Chat 智能体 → 进入编排页（`pages/chat-edit.html`）或直接开 `pages/chat-edit.html?app={APP_ID}`
2. 问 `CNC-01 由哪家供应商制造`
   - **期望**：引用卡「依据」区出现 **🕸图谱** 徽标卡（title=图谱：manufactured_by → 上海某精机）
3. 问 `华东一厂有多少台设备`
   - **期望**：引用卡出现 **📊聚合** 徽标 + 「聚合 {count: N}」摘要
4. 问 `设备维护手册`（文档查询）
   - **期望**：普通文档引用卡（kb 名 + 相似度）

### D3. plan-debug 角色层展示（浏览器）

- QU 调试页「运行策略」→ Evidence 表每行带 **主证据/佐证** 徽标；capability 行内联 **聚合={...}**
- RELATION 查询 → graph 行主证据；FACT 查询 → chunk 行主证据（可对比验证 §8.2）

---

## 附：验证脚本一键回归（可选）

```bash
# 后端机制层 + dev 真模型门槛（等价于 CI 验收线）
cd apps/earp-server && uv run pytest tests/test_understanding.py tests/test_understanding_eval.py tests/test_planning.py tests/test_planning_eval.py tests/test_capability_query.py -q

# dev 真模型端到端（qwen + bge-m3）
EARP_MIGRATION_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5433/earp' \
  EARP_OLLAMA_BASE_URL='http://127.0.0.1:11434' EARP_OLLAMA_CHAT_MODEL='qwen2.5:1.5b' \
  uv run python scripts/verify_planning.py
```

---

## 已知边界（非 bug）

1. **A3 的 LLM 升级依赖 qwen 可用**——升级只补未命中字段；LLM 不可达时 `llm_upgraded=true` + field_reasons 标注「LLM 不可达——保持规则结果」（回落路径，符合设计）
2. **B4 聚合是实体/关系计数**——数值属性聚合（SUM 温度等）无数值属性支撑会回落 plan_fact（trace 标注 no numeric support）
3. **C2 的聚合引用**：chat 回答质量依赖 qwen 归纳能力；引用卡（📊聚合）保证溯源，回答措辞可能不同
4. **A4 回落类**：LLM 判定 COMPARISON 时 select_plan → plan_aggregation（§11.2 映射），是"更准确的理解"，不算错
