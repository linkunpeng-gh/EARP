# 任务清单 — B6 遗留与评估平台化技术债（补记）

**状态：规划定稿，待开工**
**依据**：B6 评估集管理交付（2026-08-18，`arch/session-record.md`）+ FDE 反馈迭代（取消能力/折叠/阈值/执行明细）
**关联**：session-record「下一步（沿用优先级表）」——#9 角色域权限 / #7 复合主键 / P3 rerank / M3 importer / QU 二期均为既有清单，不在此重复建任务书
**日期**：2026-08-18

## 背景

B6 把三套评估（routing/understanding/planning）落库 + 跑分可视化；FDE 迭代补了取消能力、大集合折叠、阈值显示、Plan 执行明细。交付中发现以下遗留，本次补记为可执行任务（按依赖/价值排序）：

| # | 遗留 | 现状 | 影响 |
|:-:|---|---|---|
| T1 | 跑分后台任务 in-process | `asyncio.create_task`（EventBus 先例），仅 API 进程内有效；进程重启则 running 变僵尸 | 多进程部署不可用；dev 卡死任务只能靠 cancel 端点（已补） |
| T2 | LLM 调用超时累积（llm 跑分卡死根因） | json_complete 120s / stream 300s 超时，111 例 × 超时累积可挂数小时；取消粒度按 case 而非按 LLM 调用中断 | llm 跑分体验差，曾挂一天 |
| T3 | 评估集治理扩展 | 无跨租户模板共享；llm 全量跑分无进度；per-set 门槛写死种子 | FDE 现场多租户重复建 custom 用例；长跑分无反馈 |
| T4 | test_routing 既有测试弱点 | `embed_chunks` 传 document_id 导致 embedding 实际未写入（检索靠 NULL 向量假命中）——历史待办 | 路由机制层测试存在假命中盲区 |

## 目标

1. **T1**：跑分任务接入 Procrastinate worker（与 execution 任务同队列），多进程部署可用；补 stale running 恢复（进程重启后标记 failed/cancelled）
2. **T2**：connector LLM 调用统一超时（json_complete/chat 防挂起）+ llm 跑分按调用级取消检查；根因闭环
3. **T3**：评估集跨租户模板共享（builtin 模板升级同步）+ llm 跑分 SSE 进度 + per-set 门槛可配置
4. **T4**：修 test_routing embed_chunks 调用（去 document_id 或断言 embedding 写入），消除假命中盲区

## 既定决策（待开工确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 队列接入 | 复用 infra task queue（Procrastinate，execution 任务同模式）：`run_eval_task` 包装为 job，worker 消费；API 进程不再 create_task |
| D2 | stale 恢复 | worker 启动时扫描 `status='running'` 且 started_at 超时（如 > EARP_EVAL_RUN_TTL，默认 1h）→ 标记 failed + summary.error='interrupted'；cancel 语义不变 |
| D3 | LLM 超时 | `json_complete`/`chat_stream` 增加显式 timeout（默认 30s 调用级），超时回落（schema 合规不破）；取消粒度：run_eval_task 循环内对进行中 LLM 调用无法中断（asyncio task 粒度）→ 以 T2 超时为主、T1 队列取消为辅 |
| D4 | 模板共享 | `ensure_eval_sets` 增加 seed 版本（eval_seed.py 加 `SEED_VERSION`）；租户已有 builtin 集合且版本落后 → admin 触发「同步内置模板」（覆盖 builtin 用例，custom 用例不动）；跨租户复制集合（导出/导入 JSON） |
| D5 | 进度 | llm 跑分 SSE：`GET /runs/{id}/progress` 或 POST runs 时返回流式进度（completed_cases/total）；前端轮询已有，SSE 为增强项（可选） |
| D6 | per-set 门槛 | `PUT /sets/{id}` 支持 thresholds 覆盖（前端集合卡「门槛」可编辑）；校验指标名 ∈ 该 kind 的 gated metrics |

## Task 拆解（建议顺序）

### Task 1 — T4 顺手修复（无依赖，先做）
**文件**：`apps/earp-server/tests/test_routing.py`
- 修 `_index_eval_docs`/相关 embed_chunks 调用（去掉 document_id 错误传参或显式断言向量写入 `chunks.embedding IS NOT NULL`）
- 验证：test_routing 全绿 + 断言非假命中

### Task 2 — T2 connector 超时（依赖 Task 3 前做，防继续卡）
**文件**：`apps/earp-server/src/earp_server/connector.py`、`ontology/understanding.py`
- `json_complete` 显式 timeout（30s）+ 超时回落；chat_stream 保持 300s（流式合理）
- 验证：mock 挂起超时回落测试；llm 跑分 dev 冒烟

### Task 3 — T1 Procrastinate worker 接入（最大块）
**文件**：`apps/earp-server/src/earp_server/ontology/eval_service.py`、`infra/queue_schema.py`（如需）、`entrypoints/worker.py`
- run_eval_task → queue job；start_run 返回后入队（running）；worker 消费执行
- stale running 恢复（D2）
- 验证：worker 进程实测 llm/rules 跑分；模拟进程中断 → stale 恢复

### Task 4 — T3 评估集治理（平台化扩展）
**文件**：`apps/earp-server/src/earp_server/ontology/eval_service.py`、`eval_routes.py`、`apps/earp-admin/pages/eval-sets.html`
- SEED_VERSION + 内置模板同步（D4）
- per-set 门槛 PUT（D6）
- SSE 进度（D5，可选）
- 验证：模板同步不动 custom 用例；门槛覆盖生效

## 验收

1. llm 跑分不再挂起（超时回落）；长跑分可取消/可看进度
2. worker 部署下跑分跨进程可用，进程重启无僵尸 running
3. 多租户可同步内置模板、可导出/导入评估集、门槛可配
4. test_routing 假命中盲区消除
5. 全量测试 + import-linter + OpenAPI 基线 + ruff/pyright 零新增

## 遗留（不在本任务）

- 审批人角色门禁（随 #9 角色权限体系统一接入，session-record 已有）
- builtin 评估用例假设标准种子数据集（自定义租户如实低分属预期——FDE 指南 §5.4 已说明，admin 建 custom 用例）
