# 任务清单 — T3: 评估集治理扩展（模板同步 / per-set 门槛 / 跑分进度）

**状态：✅ 已完成（2026-08-19）**，验证见 `arch/session-record.md`（追加 2026-08-19 T3 段）
**依据**：`tasks/b6-followup-techdebt.md` T3 + D4/D5/D6 决策 + 2026-08-18 会话任务简报
**关联**：B6 评估集管理交付遗留——无跨租户模板共享 / per-set 门槛写死种子 / llm 长跑分无进度
**日期**：2026-08-18

## 目标

1. **模板同步（D4）**：内置评估集升级后，老租户可「同步内置模板」（覆盖 builtin 用例，custom 不动）；跨租户复制集合（导出/导入 JSON）
2. **per-set 门槛（D6）**：及格线从代码写死 → 每集合可配（校验指标名 ∈ 该 kind gated metrics）
3. **跑分进度（D5）**：llm 长跑分实时可见进度（N/总数）；前端轮询已有，SSE 为可选增强

## 现状（已核实，2026-08-18）

- `eval_sets`：eval_set_id **已含租户后缀**（`evs-{tid}-{kind}`，无单列主键冲突）、`source`（builtin/custom）、`thresholds JSONB`（ensure_eval_sets 建集时写入 THRESHOLDS 默认）✅
- `eval_seed.py`：`BUILTIN_EVAL_SETS`（routing 5 / understanding 111 / planning 111 用例）+ `KIND_ORDER` + `THRESHOLDS`（routing: dd≥0.9/kb≥0.9；understanding: intent≥0.85/entity≥0.9/relation≥0.8/schema=0；planning: strategy≥0.95）
- `ensure_eval_sets`：幂等建集（无版本概念）——模板改进后老租户不更新
- `run_eval_task`：**已读 set.thresholds**（`thresholds or THRESHOLDS.get(kind)`）——门槛覆盖只需写对 set.thresholds，判定逻辑零改动
- `eval_run_cases`：逐 case 结果落库——进度 = `count(eval_run_cases where run_id) / 启用用例数`
- 端点：`GET/POST /sets`、`GET /sets/{id}`、`POST /sets/{id}/cases`、`PUT/DELETE /cases/{id}`、`POST /sets/{id}/runs`、`POST /runs/{id}/cancel`、`GET /runs`、`GET /runs/{id}`
- 前端 `eval-sets.html`：集合卡（kind 徽标/用例数/最新跑分/gates）+ 用例管理 + 跑分历史 + 明细（轮询已有）
- 基线：**223 tests 全绿**（T1 已完成：`eval_jobs.py` eval.run 任务 + migration 0022 heartbeat_at + `recover_stale_runs` + worker 启动注册/恢复）；dev DB 到 **0022**

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D4-1 | 版本记录 | `eval_sets.seed_version INT`（**migration 0023**——T1 已占 0022 心跳列；custom 集合 seed_version NULL）；`eval_seed.py` 加 `SEED_VERSION = 1`，ensure_eval_sets 写当前版本 |
| D4-2 | 同步语义 | `POST /sets/{id}/sync`（admin 门禁对齐 roles）：仅 builtin 集合可用；重建 builtin 用例（DELETE builtin 来源 + 重插种子用例），**custom 用例不动**；seed_version 更新为当前 |
| D4-3 | 跨租户复制 | `GET /sets/{id}/export`（JSON：name/kind/thresholds/cases）+ `POST /sets/import`（目标租户建 custom 集合）——导出无敏感字段 |
| D4-4 | **builtin/custom 用例区分**（已核实：eval_cases **无来源列**） | migration 给 eval_cases 加 `source VARCHAR(16) NOT NULL DEFAULT 'builtin'`；**存量回填**：`UPDATE eval_cases SET source = (SELECT source FROM eval_sets WHERE eval_set_id = eval_cases.eval_set_id)`（builtin 集合的存量用例标 builtin，custom 集合标 custom）；种子插入写 'builtin'，`add_eval_case` 写 'custom'。同步 = `DELETE WHERE source='builtin'` + 重插种子 |
| D6-1 | 覆盖语义 | `PUT /sets/{id}` 支持 `thresholds`：**服务端合并默认**（`{**THRESHOLDS[kind], **override}` 全量存储）——避免部分覆盖导致其他 gates 缺指标；校验指标名 ∈ gated metrics + 数值范围 0-1（schema_violations 允许整数） |
| D6-2 | 生效 | 判定逻辑零改动（run_eval_task 已读 set.thresholds）；门槛编辑仅 admin（对齐 roles 门禁） |
| D5-1 | 进度形态 | 最小：`GET /runs/{id}` 响应加 `progress: {completed, total, percent}`（polling 已有直连）——eval_run_cases 计数 + 启用用例数；**T1 已完成**——run_eval_task 已有每 case heartbeat（`heartbeat` 参数），SSE 流（`GET /runs/{id}/progress`）可直接做（心跳作活跃信号） |
| D5-2 | T1 依赖 | **已解除**（T1 完成：队列 + 心跳 + worker 就绪）——进度可用心跳作 alive 信号，SSE 增强不再可选待定 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — migration 0023：eval_sets.seed_version + eval_cases.source（0.5 天）
**文件**：`migrations/versions/00XX_eval_sets_seed_version.py`（新）、`eval_seed.py`
- migration：`ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS seed_version INT` + `ALTER TABLE eval_cases ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'builtin'` + **存量回填**（D4-4：按所属集合 source 回填 eval_cases.source）
- `eval_seed.py`：`SEED_VERSION = 1` + `GATED_METRICS: dict[str, list[str]]`（每 kind 的 gated 指标名清单，与 THRESHOLDS 对齐）
- `ensure_eval_sets`：建集时写 seed_version；种子用例插入带 source='builtin'
- `add_eval_case`：写 source='custom'
- 验证：迁移应用 + ensure 幂等 + test_migrations EXPECTED 表数不变

### Task 2 — 门槛覆盖 PUT（0.5 天）
**文件**：`eval_service.py`、`eval_routes.py`
- `update_eval_set(engine, tid, set_id, *, thresholds=None, enabled=None)`：服务端合并默认 + 校验（指标名 ∈ GATED_METRICS[kind]、数值范围、schema_violations 整数）
- 路由 `PUT /sets/{id}`（新增；现有 GET/POST 保留）+ admin 门禁（`is_admin_role` 对齐 roles_routes）
- 校验失败 → 422/409 明确错误
- 验证：test_eval_service +3（合并默认/非法指标拒绝/数值范围）

### Task 3 — 模板同步 + 导出/导入（1 天）
**文件**：`eval_service.py`、`eval_routes.py`、`eval_seed.py`
- `sync_builtin_set(engine, tid, set_id)`：仅 builtin；`DELETE FROM eval_cases WHERE eval_set_id=... AND source='builtin'` → 重插种子用例 → seed_version=SEED_VERSION；**custom 用例不动**（D4-4 source 列区分）
- `export_eval_set(engine, tid, set_id)` / `import_eval_set(engine, tid, payload)`（导入为 custom 集合，id 自动生成）
- 路由：`POST /sets/{id}/sync`、`GET /sets/{id}/export`、`POST /sets/import`（均 admin 门禁）
- 前端 `eval-sets.html`：集合卡「同步内置模板」（builtin 且 seed_version < 当前 时显示）+ 「导出」；「导入」按钮
- 验证：test_eval_service +4（同步覆盖 builtin 保留 custom/幂等/版本更新、导出→导入往返、非 builtin 拒绝同步、import 校验）

### Task 4 — 跑分进度（0.5 天，可选 SSE）
**文件**：`eval_service.py`、`eval_routes.py`、前端 `eval-sets.html`
- `get_run` 响应加 `progress`（completed=eval_run_cases 计数、total=启用用例数、percent）
- 前端跑分历史 running 行进度条（轮询已有，复用 2s 间隔）
- 可选增强：`GET /runs/{id}/progress` SSE（T1 心跳就绪后）
- 验证：test_eval_service +2（running 中 progress 计数、完成后 100%）

### Task 5 — 收尾（0.5 天）
- dev 真 API 冒烟：老租户同步（含 custom 保留）、门槛改后 gates 变化、llm/rules 跑分进度可见
- FDE 指南 §5 补：模板同步/门槛编辑/进度说明
- session-record 补记 + b6-followup-techdebt.md 标 T3 ✅

## 依赖关系

```
Task 1（版本列+基座）→ Task 2（门槛）→ Task 3（同步/导出导入）→ Task 4（进度）→ Task 5（收尾）
Task 2 与 Task 3 可并行（不同端点）；Task 4 依赖 eval_run_cases 落库（已有）
```

**建议执行序**：`1 → (2, 3 并行) → 4 → 5`

## 验收标准

1. 内置模板升级（SEED_VERSION 递增）→ 老租户同步后题量与最新种子一致；custom 用例保留；幂等
2. per-set 门槛覆盖生效于 gates 判定（部分覆盖合并默认，非法指标拒绝）
3. llm/rules 跑分中实时可见进度（N/总数）；取消后进度冻结
4. 跨租户导出→导入往返一致（custom 集合）
5. 全量 pytest 绿 + import-linter + OpenAPI 基线同步 + ruff/pyright 零新增
6. dev 真 API 冒烟全链路

## 风险提示

1. **migration 编号**：T1 已占 0022（heartbeat）——本任务用 **0023**（seed_version + eval_cases.source），已定，无冲突
2. **eval_cases 来源标记**：已核实无 source 列 → D4-4 已定（加列 + 按集合回填 + 种子/API 各自写）。**存量租户的「builtin 集合里手工加的用例」会被回填成 builtin、同步时被覆盖**——可接受（同步前前端提示），文档注明
3. **门槛部分覆盖**：客户端只传一个指标 → 服务端必须合并默认（否则 run_eval_task 的 gates 判定缺指标报错）——D6-1 已定，勿偷懒直接覆盖
4. **同步是破坏性操作**：确认弹窗 + 前端提示「将覆盖内置题，custom 题保留」；admin 门禁（roles 体系既有）
5. **进度准确性**：total 以「启用用例数」为准（禁用用例不参与跑分）；取消后 completed 冻结不回落

---
**规划定稿，确认后按执行序开工。**
