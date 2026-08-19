# 任务清单 — T1: 跑分接入 Procrastinate worker + stale running 恢复

**状态：✅ 已完成（2026-08-19）**，验证见 `arch/session-record.md`（追加 2026-08-19 段）
**依据**：`tasks/b6-followup-techdebt.md` T1（最大块）+ `arch/session-record.md`（2026-08-18 补记）
**关联**：B6 评估集管理交付遗留——跑分后台任务 in-process（`asyncio.create_task`），仅 API 进程内有效；进程重启则 running 变僵尸，多进程部署不可用
**日期**：2026-08-18

## 目标

1. **队列接入**：跑分任务从 API 进程 in-process 迁移到 Procrastinate worker（与 execution 任务同队列模式），多进程部署可用；API 进程不再 `create_task`
2. **stale 恢复**：进程重启后遗留的 `running` 僵尸任务自动标记 failed（+ summary.error='interrupted'），cancel 语义不变
3. **零回归**：既有 14 个 eval 服务测试（直调 run_eval_task）不动；并发 409 / cancel 端点 / 前端轮询全保持

## 现状（已核实，2026-08-18）

- **队列基础设施已就绪**：`infra/task_queue.py`（ProcrastinateTaskQueue：open/close/assert_schema/enqueue/enqueue_in_session/task/run_worker）+ `entrypoints/worker.py`（worker 进程，`run_worker(concurrency=4)`，SIGTERM 优雅退出）+ `queue_schema.py`（`make migrate` 建 procrastinate schema + grants）
- ⚠️ **没有任何业务任务注册/消费队列**——worker 空跑；execution 任务也未接队列（任务书「与 execution 任务同模式」是展望，T1 是第一个真实消费方）
- 跑分触发链：`eval_routes.start_eval_run` → `start_run`（建 running 行，同集合并发 409）→ `asyncio.create_task(_background())` → `run_eval_task(engine, tid, run_id, settings=..., role_id=...)`（逐 case 评分，每 case 前 `_is_running` 检查——cancel 提前终止既有）
- `config.py` 无 EVAL_RUN_TTL 类配置（有 llm_cache_ttl 等）
- `spikes/procrastinate_spike.py`：sync task 冒烟（workers=2/tasks=100）——async task 支持未验证
- `test_entrypoints.py::test_worker_entrypoint_graceful`：worker 进程起停冒烟
- 基线：220 tests 全绿

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 队列接入 | 复用 `ProcrastinateTaskQueue`：任务名 `eval.run`，payload `{tenant_id, run_id, role_id}`；API lifespan 初始化 queue 注入 `app.state`；`start_eval_run` 从 create_task 改 `enqueue`（返回体不变 running+run_id，前端零改动） |
| D1b | async 桥接 | **Task 1 先验证 procrastinate async task 支持**（worker 是 `run_worker` async 模式）：支持则 task 函数直接 async；不支持则 sync task 内 `asyncio.run()` 桥接（engine 是 async，worker 侧从 Settings 构造，注意 event loop 隔离） |
| D2 | stale 判定 | **心跳方案（推荐）**：migration 0022 给 eval_runs 加 `heartbeat_at`（job 内每 case 更新）；worker 启动扫描 `running AND heartbeat_at < now()-TTL`（`EARP_EVAL_RUN_TTL` 默认 3600s）→ failed。❌ 不用 started_at 一刀切——llm 跑分 111 例 × 30s 超时 ≈ 55min，TTL=1h 会**误杀还在跑的合法任务** |
| D3 | 恢复不覆盖 | stale 恢复只处理 running；cancelled/completed/failed 不动；cancel 端点语义不变（job 内 `_is_running` 提前终止仍生效） |
| D4 | 测试策略 | 服务级直调保持（test_eval_service 14 用例不动）；路由级 worker 集成测试用真实 queue（testcontainers schema 已建）——enqueue → 真 worker 消费 → completed |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — 验证 async task + 任务注册（0.5-1 天）
**文件**：`src/earp_server/ontology/eval_jobs.py`（新）、`src/earp_server/infra/task_queue.py`（如需）
- 先做 spike：确认 procrastinate 版本 async task 支持（worker `run_worker` 已是 async 模式）——写 10 行临时 job 在 worker 里跑通
- `eval_jobs.py`：`@queue.task(name="eval.run")` 注册——sync/async 桥接（D1b），函数内从 `Settings()` 构造 engine（对齐 worker 侧），调 `eval_service.run_eval_task(engine, tenant_id, run_id, settings=..., role_id=...)`
- job 内更新心跳（D2）：每 case 前 `UPDATE eval_runs SET heartbeat_at = now()`（migration 0022 之后）
- 验证：spike 脚本 + 单测（mock enqueue 后直调 job 函数）

### Task 2 — API 入队改造（0.5 天）
**文件**：`src/earp_server/main.py`（lifespan）、`src/earp_server/ontology/eval_routes.py`
- lifespan 初始化 `ProcrastinateTaskQueue(settings)` + `assert_schema()` → `app.state.queue`（API 进程只 enqueue 不消费）
- `start_eval_run`：删 `asyncio.create_task`，改 `await req.app.state.queue.enqueue("eval.run", {...})`
- 返回体不变；**删除 now-unused import（asyncio）**，ruff 零新增
- 验证：dev 真 API POST /evaluations/runs → running → 起 worker 后 completed（Task 4 前可先手动）

### Task 3 — migration 0022 heartbeat + stale 恢复（0.5 天）
**文件**：`migrations/versions/0022_eval_runs_heartbeat.py`（新）、`src/earp_server/ontology/eval_service.py`、`src/earp_server/entrypoints/worker.py`、`src/earp_server/config.py`
- migration 0022：`ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ`（start_run 时默认 now()）+ RLS 无感（列级）
- `config.py`：`eval_run_ttl: int = 3600`（env `EARP_EVAL_RUN_TTL`）
- `eval_service.recover_stale_runs(engine) -> int`：全租户扫描 `running AND heartbeat_at < now()-TTL` → 标 failed + `summary.error='interrupted'`（migration 角色或应用角色逐租户——**注意 RLS**：running 行分布在多租户，应用角色需逐租户 SET LOCAL 或直接全局 UPDATE 在 tenant_id 维度处理）
- `worker.py`：启动时（open 后）调 `recover_stale_runs` + 日志；后续可落 scheduler 定期扫（本次不做，记遗留）
- 验证：伪造 running+旧心跳 → worker 启动标记 failed；新 running 不动

### Task 4 — 测试（0.5-1 天）
**文件**：`tests/test_eval_worker.py`（新）、`tests/test_eval_service.py`（+stale）、`tests/test_entrypoints.py`（如需）
- worker 集成：enqueue → 真 worker 消费（`ProcrastinateTaskQueue.run_worker` 短跑或直调 job 函数+状态断言）→ eval_runs completed
- stale 恢复：插 running+旧 heartbeat → `recover_stale_runs` → failed+interrupted；cancelled/completed 不动；新 running 不动
- 回归：test_eval_service 全绿（服务级直调不经队列）；并发 409；cancel 提前终止
- 前端冒烟：eval-sets-smoke 不动（响应格式无变化）

### Task 5 — dev 实测 + 收尾（0.5 天）
- 单机实测：起 worker 进程（`make worker` 或 python -m earp_server.entrypoints.worker）→ dev 真 API 触发 rules/llm 跑分 → completed；kill worker → stale 恢复
- 环境注意：worker 进程需带 `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434`（与 API 同 env，跑分在 worker 进程调 Ollama）
- FDE 指南 §5.2 补「跑分由独立 worker 进程执行」说明（若 dev 无 worker 进程跑分不动的排障条目）
- session-record 补记 + b6-followup-techdebt.md 标 T1 ✅

## 依赖关系

```
Task 1（任务注册）→ Task 2（API 入队）→ Task 3（心跳+stale）→ Task 4（测试）→ Task 5（实测收尾）
Task 3 与 Task 1/2 可部分并行（心跳列先建，job 内更新后补）
```

**建议执行序**：`1 → 2 → 3 → 4 → 5`

## 验收标准

1. 跑分任务由 worker 进程消费（API 进程无 create_task）；多进程部署下 API 重启不丢任务
2. 进程中断后遗留 running → 重启 worker 自动标记 failed（interrupted），不误杀心跳新鲜的在跑任务
3. cancel 语义不变（running → cancelled 提前终止）；并发 409 保持；前端零改动
4. 既有 eval 服务测试全绿（直调模式保留）；新增 worker 集成 + stale 测试
5. 全量 pytest 绿 + import-linter + OpenAPI 无变化 + ruff/pyright 零新增
6. dev 单机实测：rules + llm 两种模式经 worker 跑通

## 风险提示

1. **async task 桥接**：procrastinate 对 async task 的支持需 Task 1 先行验证；`asyncio.run` 桥接注意 worker 事件循环隔离（每个 task 独立 loop）
2. **TTL 误杀**：llm 跑分合法时长可 >1h——必须心跳方案（D2），勿回退 started_at 一刀切
3. **RLS 与多租户 stale 扫描**：running 行跨租户，应用角色恢复需逐租户处理或明确全局语义（跑分任务是租户隔离的，恢复也应按租户归属）
4. **worker 环境一致性**：dev 多进程（API+worker+audit+scheduler）各自 env 需一致（Ollama/DB URL）；无 worker 进程时跑分永远 running（FDE 指南排障条目）
5. **测试容器内队列**：testcontainers 单容器内 procrastinate schema 已建（migrated fixture）——worker 集成测试无需额外基础设施

---
**规划定稿，确认后按执行序开工。**
