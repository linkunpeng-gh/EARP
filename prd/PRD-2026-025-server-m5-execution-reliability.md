# PRD-2026-025 v1.0

## M5 — Execution 可靠性

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-025 |
| **Feature** | 多步编排(plan→execute→update→checkpoint) + Retry/Timeout/熔断 策略化 + Saga 补偿 + Durability 三档 + REPLANNING + 错误处理 |
| **里程碑** | M5（依赖 M1 StepRunner + M3 SimpleTaskPlanner） |
| **上游** | langgraph v1.1 §2.6(Pregel); Temporal Retry Policy; langchain §2.3(handle_tool_error) |
| **PRD 链** | ← PRD-2026-023(M3) |

---

## 1. 范围表

| # | 域 | 功能 |
|:--|:---|:-----|
| 1 | Orchestrator | 多步编排循环: for step in plan→StepRunner.invoke→CheckpointStore.write→next。Pregel 骨架: plan→execute→update→checkpoint |
| 2 | Orchestrator | Temporal Retry Policy 四参数: initial_interval / backoff / max_attempts / max_interval。步级重试内建引擎层 |
| 3 | Orchestrator | STEP_RETRIED 事件: 每次重试发布 CloudEvent |
| 4 | Orchestrator | Saga 补偿最小版: Command Step 注册 `compensate` 回调, 失败时逆序执行 |
| 5 | Checkpoint | Durability 三档: sync(Command 步强制)/async(默认)/exit(仅终止时写) |
| 6 | Checkpoint | 多步恢复: 从 checkpoint 恢复, 跳过已完成 Step, 从断点继续执行 |
| 7 | Runtime | REPLANNING 状态: 异常驱动 Checkpoint+Resume |
| 8 | Runtime | interrupt 模式: 暂停/恢复(human_approval 节点), task_path 寻址(DDL 已预留) |
| 9 | Runtime | handle_tool_error 三态: 吞错返回预设 / 抛出 / callable 定制 |

---

## 2. US

| US | 描述 |
|:--:|:-----|
| US-01 | 3-Step Plan 执行→成功 3 步, checkpoint 每步后写, audit COMPLETED×3 |
| US-02 | Step 2 失败→重试 2 次(max_attempts=3)→STEP_RETRIED 事件×2 |
| US-03 | Command Step 注册 compensate→执行失败→逆序补偿调用 |
| US-04 | Durability=sync 步→每步后 wait checkpoint 确认; async 步→fire-and-forget |
| US-05 | 从 checkpoint 恢复→跳过 Step 1(已成功)→从 Step 2 继续→完成 |
| US-06 | handle_tool_error=fail→Plan 终止; =swallow→skip 步继续; =custom callable→自定义输出 |

---

## 3. AC

| AC | 内容 | 验证 |
|:--:|:-----|:----|
| AC-01 | 3 步 Plan→3 completed + 3 checkpoint 写入 | pytest |
| AC-02 | Step 失败→retry 到 max_attempts→STEP_RETRIED×2→最终 FAILED | pytest |
| AC-03 | Command 步失败→compensate 逆序调用→audit ROLLBACK×N | pytest |
| AC-04 | sync 步→checkpoint 确认后才继续; async 步→不等待 | pytest |
| AC-05 | 恢复: checkpoint_id 入参→跳过已完成步→从断点执行 | pytest |
| AC-06 | handle_tool_error=swallow→step status=skipped, Plan 继续 | pytest |

---

## 4. 依赖与对齐

| 依赖 | 来源 | M5 引用 |
|:-----|:-----|:------|
| StepRunner.invoke | M1 | 多步循环逐步调用 |
| CheckpointStore | M1 | 扩展 write/read(多步+durability) |
| SimpleTaskPlanner | M3 | 产出 Plan(Steps[]) |
| EventBus | M1 | STEP_RETRIED 事件 |
| checkpoints 表 | M0 DDL | task_path 列 |

---

## 5. Gate

| # | 检查项 | 状态 |
|:--|:-----|:----:|
| 1 | 依赖明确 | ✅ |
| 2 | AC 可测试 | ✅ 6 条 |
| 3 | 与冻结规范无矛盾 | ✅ |
| 4 | 遗留 = 0 | ✅ |
