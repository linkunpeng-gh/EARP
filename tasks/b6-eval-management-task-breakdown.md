# 任务清单 — B6: 评估集管理页（三套评估落库 + admin 跑分可视化）

**状态：规划定稿，开工**
**依据**：`arch/design/2026-08-09-enterprise-retrieval-design.md` §7/§8 Phase 1 ⑥「评估集落库 + 验收」+ session-record（P4 B6）
**关联**：评估体系三套（routing/understanding/planning）现为 markdown fixture + 脚本验证；B6 目标 = 评估从「脚本验证」变「平台能力」
**日期**：2026-08-17

## 目标

三套评估（routing 5 例 / understanding 111 例 / planning 复用 111 例标注）**落库** + **admin 跑分可视化**：
1. **评估集管理**：内置三套种子按租户惰性初始化（`ensure_eval_sets`，tbox 先例）；用例 CRUD（admin 可新增/编辑/启停/删除自定义用例）
2. **跑分平台化**：`POST /v1/evaluations/sets/{id}/runs` 触发跑分（rules 规则层快速 / llm 真 LLM 升级两模式），后台任务执行、结果落库、按 §17/设计 §7 门槛判定 gates
3. **可视化**：admin 页 — 集合卡片（最新跑分率 + gates）+ 用例管理 + 跑分历史 + 单次跑分明细（逐用例 pass/actual/detail）

## 既定决策（对齐现有体系）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | 落库形态 | **4 表**（eval_sets / eval_cases / eval_runs / eval_run_cases），全部 tenant-scoped + RLS 三件套 + 显式 GRANT earp_app（0018 先例） |
| D2 | 种子来源 | 内置三套种子**内联 Python 数据**（`ontology/eval_seed.py`，由 `scripts/gen_eval_seed.py` 从 fixtures 生成，防转写错）；fixtures 保留作 CI 真源（hermetic）；DB 种子按租户惰性初始化（tbox 模式），幂等 ON CONFLICT DO NOTHING |
| D3 | 跑分模式 | `rules`（规则层，CI 机制层口径：understand() 规则 / select_plan 映射 / route_query 软路由）默认；`llm`（真 LLM 升级路径：upgrade_with_llm + execute_plan 端到端，dev 口径）可选——settings 不完整自动回落 rules 语义（不 gate） |
| D4 | 执行模型 | **后台任务**（asyncio.create_task，EventBus 先例）：POST 立即返回 run_id（status=running），GET 轮询；每集合同时仅 1 个 running（409）；失败 → status=failed + summary.error。llm 模式 111 例本地 ~1-2min 不阻塞 HTTP |
| D5 | 门槛 | routing: dd_accuracy ≥ 0.90（设计 §7，kb_accuracy 报告不 gate）；understanding: intent ≥ 0.85 / entity ≥ 0.90 / relation ≥ 0.80 / schema_violations = 0（§17）；planning: strategy_hit_rate ≥ 0.95（§17 Plan 层）；overall = 全部通过 |
| D6 | 权限 | 跑分用当前登录 role_id（route_query 权限过滤天然生效）；评估集/用例 CRUD 不另设角色门禁（治理权限随 #9 统一） |
| D7 | 端点归属 | 新 router `ontology/eval_routes.py`（prefix /v1/evaluations）；ontology 域不在 independence 契约，import knowledge.* 合法 |

## 现状（已核实）

- fixtures：`tests/fixtures/routing_eval.md`（5 例，表头 query/期望 DD/期望 KB/备注）、`understanding_eval.md`（111 例，query/intent/entities/relations/time/constraints/note）
- CI 机制层 runner：test_routing.py effect layer（route_query 期望 DD ∈ top-N）/ test_understanding_eval.py（understand() 规则层四门槛）/ test_planning_eval.py（select_plan 映射 ≥95%）
- dev 真模型：scripts/verify_routing.py / verify_understanding.py / verify_planning.py
- 复用资产：`understand()`（RuleResult + field_hits）/ `upgrade_with_llm(settings=None 跳过)` / `build_structured_query` / `select_plan` / `execute_plan` / `route_query(query_embedding=None 防护)` / `embed_query`（infra/ext 初始化）
- 基线：181 tests 全绿；migration head = 0018

---

## Task 1 — migration 0019：评估 4 表 + RLS

**文件**：`migrations/versions/0019_eval_sets.py`（新建，down_revision=0018）

```sql
CREATE TABLE eval_sets (
    eval_set_id  VARCHAR(64) PRIMARY KEY,
    tenant_id    VARCHAR(64) NOT NULL,
    kind         VARCHAR(16) NOT NULL CHECK (kind IN ('routing','understanding','planning')),
    name         VARCHAR(128) NOT NULL,
    description  TEXT,
    source       VARCHAR(16) NOT NULL DEFAULT 'builtin' CHECK (source IN ('builtin','custom')),
    thresholds   JSONB NOT NULL DEFAULT '{}',
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE eval_cases (
    case_id     VARCHAR(64) PRIMARY KEY,
    tenant_id   VARCHAR(64) NOT NULL,
    eval_set_id VARCHAR(64) NOT NULL,
    sort_order  INT NOT NULL DEFAULT 0,
    query       TEXT NOT NULL,
    expected    JSONB NOT NULL,
    note        TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_eval_cases_set ON eval_cases (tenant_id, eval_set_id, sort_order);
CREATE TABLE eval_runs (
    run_id       VARCHAR(64) PRIMARY KEY,
    tenant_id    VARCHAR(64) NOT NULL,
    eval_set_id  VARCHAR(64) NOT NULL,
    mode         VARCHAR(16) NOT NULL CHECK (mode IN ('rules','llm')),
    status       VARCHAR(16) NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','completed','failed')),
    summary      JSONB NOT NULL DEFAULT '{}',
    gates        JSONB NOT NULL DEFAULT '{}',
    triggered_by VARCHAR(64),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);
CREATE INDEX ix_eval_runs_set ON eval_runs (tenant_id, eval_set_id, started_at DESC);
CREATE TABLE eval_run_cases (
    result_id  VARCHAR(64) PRIMARY KEY,
    run_id     VARCHAR(64) NOT NULL,
    case_id    VARCHAR(64) NOT NULL,
    passed     BOOLEAN NOT NULL,
    actual     JSONB NOT NULL DEFAULT '{}',
    detail     JSONB NOT NULL DEFAULT '{}',
    latency_ms INT
);
CREATE INDEX ix_eval_run_cases_run ON eval_run_cases (run_id);
```

- RLS 三件套（ENABLE + FORCE + tenant_isolation policy，同 0018）+ 显式 GRANT earp_app
- **测试**：test_migrations 跑 head 含 0019（既有用例自动覆盖）

## Task 2 — eval_seed.py（内置三套种子数据）

**文件**：`scripts/gen_eval_seed.py`（新建，生成器）+ `src/earp_server/ontology/eval_seed.py`（生成产物，提交入库）

- 生成器解析 `tests/fixtures/routing_eval.md` + `understanding_eval.md` → 输出 `BUILTIN_EVAL_SETS: dict[kind, {...}]`
  - routing: 5 例 `{query, expected: {data_domain_id, knowledge_base_id}, note}`
  - understanding: 111 例 `{query, expected: {intent, entities: [{mention, semantic_type}], relations: [], time, constraints}, note}`
  - planning: 复用 understanding 标注 → 111 例 `{query, expected: {intent_label}, note}`（select_plan 映射按 §11.2）
- 生成产物带头部注释「由 scripts/gen_eval_seed.py 生成，勿手改；fixtures 为真源」
- **验证**：生成产物与 fixture 数量/内容一致性（脚本内 assert：routing=5、understanding/planning ≥100）

## Task 3 — eval_service.py（种子 + CRUD + 跑分引擎）

**文件**：`src/earp_server/ontology/eval_service.py`（新建）

1. **种子**：`ensure_eval_sets(engine, tenant_id)` — 无 set 时插入 3 builtin（eval_set_id 带租户后缀防跨租户 PK 撞车，如 `evs-{tid}-routing`；case_id `evc-{tid}-{set}-{seq:03d}`）；幂等
2. **CRUD**：list_eval_sets（含 case_count + 最新 run summary）/ create_eval_set（custom）/ get_eval_set（+cases）/ add_eval_case / update_eval_case（含 enabled）/ delete_eval_case / list_runs / get_run（+case results）
3. **跑分**：`start_run(engine, tid, user_id, eval_set_id, mode)` — 校验 set + 无 running 冲突 → INSERT run(running) → 返回 run_id；`run_eval_task(engine, tid, run_id, settings)` — 后台执行：
   - 逐 case 评分 → eval_run_cases 落库
   - 汇总 metrics（n/passed/failed + 各率）→ summary；对照 thresholds → gates（per-metric pass + overall）
   - 异常 → status=failed + summary.error；完成 → status=completed + finished_at
   - 三 kind 评分逻辑对齐 CI runner：
     - **routing**：embed_query（异常 → None 降级，summary.vector_lane=false）→ route_query(top_n=5, top_k=3, role_id) → dd ∈ candidate_dds 判定；kb ∈ kb_summaries 报告项
     - **understanding**：understand(engine, tid, query, context from note ctx:)（+ mode=llm 且 settings 完整时 upgrade_with_llm）→ intent（FALLBACK 回落即中）/ entities（mention+type 命中）/ relations（期望 ⊆ 结果）/ schema（result relation ∈ TBox）
     - **planning**：rules = select_plan(build_structured_query(标注 intent)) 映射；llm = execute_plan 端到端（plan_name == 期望策略 + trace 合法性）
4. **阈值常量**：`THRESHOLDS`（D5），存 eval_sets.thresholds（可覆盖）

## Task 4 — eval_routes.py（API）

**文件**：`src/earp_server/ontology/eval_routes.py`（新建，prefix `/v1/evaluations`，tags=["evaluations"]）

| 端点 | 说明 |
|:---|:---|
| GET `/sets` | 集合列表（+case_count+latest run） |
| POST `/sets` | 新建 custom 集合（kind/name/description） |
| GET `/sets/{eval_set_id}` | 集合详情 + 用例列表 |
| POST `/sets/{eval_set_id}/cases` | 加用例（query/expected/note） |
| PUT `/cases/{case_id}` | 改用例（query/expected/note/enabled） |
| DELETE `/cases/{case_id}` | 删用例 |
| POST `/sets/{eval_set_id}/runs?mode=` | 触发跑分 → run_id（后台任务，409 并发冲突） |
| GET `/runs` | 跑分历史（eval_set_id 过滤） |
| GET `/runs/{run_id}` | 跑分明细（+逐用例结果） |

- 鉴权：JWT 中间件全局；`req.state.tenant_id/role_id/user_id`；跑分任务捕获 `req.app.state.engine/settings`
- 后台任务失败兜底（try/except → failed）

## Task 5 — main.py 挂载 + 契约检查

- `main.py`：`from earp_server.ontology.eval_routes import router as eval_router` + `app.include_router(eval_router)`
- import-linter：ontology 域不在 independence 契约 → 零新增
- `make openapi` 同步基线（test_openapi_export 字节级校验）

## Task 6 — 前端 pages/eval-sets.html + nav.js

**文件**：`apps/earp-admin/pages/eval-sets.html`（新建）+ `apps/earp-admin/js/nav.js`（抽屉项）

- nav.js：知识中心「探索验证」组新增 `{ label: '评估管理', sub: 'eval-sets', path: '{b}/pages/eval-sets.html', group: '探索验证' }`
- 页面结构：
  1. **集合卡片区**：三套 builtin（routing/understanding/planning）+ custom 集合；每卡显示 kind 徽标 / 用例数 / 最新跑分率 + gates 徽标（✅/❌ 带率）；「运行（规则层）」「运行（LLM 升级）」按钮 + 新建集合
  2. **用例管理**：选中集合 → 用例表（query / 期望摘要 / 启用开关 / 删除）+ 新增用例表单（kind 相关字段：routing=期望 DD/KB；understanding=intent/entities/relations；planning=intent 标注）
  3. **跑分历史**：runs 表（模式 / 状态 / 开始时间 / 耗时 / summary 率 / gates）；点行看明细
  4. **跑分明细**：逐用例 passed/actual/detail + 失败原因；轮询 running 状态（2s）
- 样式复用 admin.css（panel/toolbar/badge 现有类）

## Task 7 — 测试 test_eval_service.py

**文件**：`tests/test_eval_service.py`（新建，服务函数级，对齐 test_tbox_approval 模式）

| # | 用例 | 断言 |
|:-:|:---|:---|
| 1 | ensure_eval_sets 幂等 | 两次调用 → 仍 3 套；case 数 routing=5 / understanding≥100 / planning≥100 |
| 2 | 种子数据与 fixture 一致 | seed 的 routing expected 与 fixture 内容一致（抽查 query） |
| 3 | 跨租户隔离 | tenant B list 为空；get A 的 set → None/404 语义 |
| 4 | 用例 CRUD | add/update(enabled)/delete 生效 |
| 5 | custom 集合 | create → source=custom，可跑分 |
| 6 | routing 跑分（bigram stub） | 5 例 dd 命中 ≥ 90% gates；summary.vector_lane=true |
| 7 | understanding 跑分 rules | 四门槛全过（复用 test_understanding_eval seed 租户） |
| 8 | planning 跑分 rules | strategy ≥ 95% |
| 9 | run 状态机 | start_run → running；run_eval_task → completed + finished_at；gates.overall 判定 |
| 10 | 并发冲突 | running 中再 start → 拒绝 |
| 11 | 失败兜底 | 非法 set 跑分 → failed + summary.error |

## Task 8 — 前端冒烟 + 全量验证 + 文档

- `apps/earp-admin/test-eval-sets-smoke.cjs`（新建，node --check + DOM stub，对齐 test-tbox-approval-smoke.cjs）：集合卡片渲染 / 运行按钮触发 POST / 历史渲染 / 明细渲染
- 全量：`uv run pytest`（181 + 新增全绿）+ import-linter + OpenAPI 基线 + ruff/pyright 零新增
- dev 真库冒烟：API 进程上建租户种子 → 跑一次 rules 跑分（真实 DB）
- `arch/session-record.md` 追加 B6 交付记录 + 更新下一步

---

## 验收

1. 三套评估落库：dev 租户打开评估管理页见 3 套内置集合 + 用例
2. rules 跑分平台可跑：understanding/planning 门槛全过（与 CI 口径一致），routing 在真 embedding 环境 ≥90%
3. 用例可增改删、跑分历史可查、明细逐用例可看
4. 全量测试通过 + OpenAPI 基线同步 + lint 零新增
5. llm 模式跑分（dev 真模型）与 verify_planning 口径一致（不 gate，报告）

## 遗留（不在本任务）

- 跑分后台任务为 in-process（asyncio.create_task）：多进程部署下需 Procrastinate worker（记 tech-debt）
- llm 模式 111 例全量跑分在浏览器端仅轮询无进度条（可后加 SSE 进度）
- 评估集治理（共享模板/跨租户同步）留后续
