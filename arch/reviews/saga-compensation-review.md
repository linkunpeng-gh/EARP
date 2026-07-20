# Saga/TCC 补偿代码评审

**评审范围**: `0e98227..fd7964f` (M12 Saga/TCC 补偿集成)
**评审日期**: 2026-07-20
**评审人**: Codex

---

## 1. `types.py Step.compensate_call`: 向后兼容？

**PASS**

`compensate_call` 定义为 `dict[str, Any] | None = None`，是 dataclass 的可选字段。M5 已有 Step 对象没有此字段时自动获得 `None`，`multi_step.py` 中用 `if step.compensate_call:` 判断后才注册补偿，不传时完全无影响。

向后兼容无问题。

---

## 2. `multi_step.py` SagaCompensation 集成: register/rollback 逻辑

**PASS** — `register()` 追加到列表末尾，`rollback()` 按 `reversed()` 逆序执行，保证 LIFO 语义。每个补偿用 `try/except` 隔离，单步失败不影响后续补偿。`rollback()` 末尾 `self._compensations.clear()` 清理状态。整体设计正确。

**ISSUE (P2)** — `_compensate` 闭包丢失 `InvokeContext`
`multi_step.py` lines 110-115：`_compensate` 函数内部创建 `Connector()`，未传入 `tenant_id`/`user_id`/`role_id` 等身份上下文。`Connector.execute()` 调用补偿 adapter 时，如果 adapter 需要鉴权（例如 REST API 回滚调用需要用户身份），补偿调用将以无身份方式执行。建议将 `ctx` 中的上下文字段持久化到 `saga.register()` 的 context dict 中，供补偿时使用。

**ISSUE (P2)** — 补偿注册仅在内存中，无持久化
`multi_step.py` lines 110-121：补偿注册在 checkpoint write 之前，但 `saga` 是 `execute()` 的局部变量。如果 checkpoint write 失败（数据库瞬断），异常向上传播，`saga` 对象丢失，已注册的补偿全部丢失。恢复重新执行时 step 会重跑（checkpoint 未写入），但之前的补偿信息无法恢复。这是内存协调模式的固有局限，建议后续引入补偿日志持久化。

**ISSUE (P2)** — 补偿调用失败后静默跳过
`compensation.py` lines 29-31：`rollback()` 中 `await compensate(context)` 抛出异常时仅 `logger.exception(...)` 记录，不重试、不入死信队列。若补偿调用本身因为网络瞬断等可恢复错误失败，补偿将永久丢失。建议对 compensation 调用也启用重试（可复用 `tenacity`），或记录失败状态供人工介入。

---

## 3. `multi_step.py` `checkpoint_ns`: 多步场景 PK 冲突是否彻底解决？

**PASS**

`checkpoints` 表 PK 为 `(thread_id, checkpoint_ns, checkpoint_id)`，`checkpoint_id = uuid.uuid4().hex` 全局唯一，PK 冲突在此结构下本来就不可能发生。

本 PR 引入的 namespace 隔离的正确价值在于 **`checkpoint_blobs` 表**（PK: `thread_id, checkpoint_ns, channel, version`）。现在：

| 写入方 | checkpoint_ns | 语义层级 |
|---|---|---|
| `step_runner.py` | `step.step_id` | Step 级 |
| `multi_step.py` (成功) | `f"plan:{step.step_id}"` | Plan 级 |
| `multi_step.py` (中断) | `"interrupt"` | 中断标记 |

旧代码所有写入统一用 `""` namespace，新代码按层级隔离。即便未来两个层级意外使用了相同的 channel 名称，也不会 PK 冲突。Namespace 隔离是彻底且正确的。

---

## 4. `checkpoint.py write()` + `checkpoint_ns` 参数: 向后兼容？

**PASS**

`checkpoint_ns: str = ""` 作为 keyword-only 参数（`*`后），默认值 `""` 与旧代码硬编码的 `ckpt_ns = ""` 完全一致。所有未传此参数的调用方行为不变。

`step_runner.py` line 68 和 `multi_step.py` lines 105, 130 显式传入了 namespace，需要这些调用点的 caller 感知到变化。但这些文件已在同一 PR 中同步更新，无外部 breakage。

---

## 5. 测试 `test_saga.py` 4 个场景: 覆盖度是否足够？边界情况？

**PASS** — 4 个测试覆盖了最核心的 happy/unhappy path：

| 测试 | 场景 | 验证重点 |
|---|---|---|
| `test_saga_rollback_on_step_failure` | Step1 成功 + Step2 失败 → Step1 补偿 | 回滚执行、状态 `ROLLED_BACK`、`rollback_results` 格式 |
| `test_saga_no_rollback_when_no_compensate` | 单步无 compensate_call 且失败 | 状态为 `FAILED` 而非 `ROLLED_BACK` |
| `test_saga_all_steps_succeed_no_rollback` | 全成功 | 状态 `COMPLETED`，无回滚 |
| `test_existing_behavior_unchanged` | 无 compensate_call 的 M5 向后兼容 | 行为不变 |

**ISSUE (P2)** — 边界缺失:

1. **多步回滚**: 3 个以上 step 全部带 `compensate_call`，中间步骤失败。当前单测只测了 1 步回滚，未验证 LIFO 顺序和 saga.count > 1 时多次调用的正确性。
2. **补偿调用失败**: `_compensate` 中 `Connector().execute()` 抛出异常的分支未被测试。`SagaCompensation.rollback()` 对异常仅 log 不重传，当前无测试覆盖此行为。
3. **首步即失败**: `saga.count == 0` → 状态应为 `FAILED`（而非 `ROLLED_BACK`）。这是代码中的显式分支，但无单测覆盖。
4. **混合补偿**: 部分 step 有 `compensate_call`，部分没有。失败时 `rollback_results` 应只包含实际执行了补偿的步骤，此场景无测试。
5. **`rollback_results` 可能过度上报**: `multi_step.py` lines 151-154 从 `results`（所有 completed 步骤）构造 `rollback_results`，而非从 `saga._compensations`（实际注册了补偿的步骤）。如果某个 step 成功完成但 `compensate_call = None`，它仍然会出现在 `rollback_results` 中标记为 `"rolled_back"`，与实际执行的补偿不一致。需要修复为只列出实际注册了补偿的 step_id。（当前测试未触发此问题因为 step2 没有成功完成。）
6. **`resume_from_checkpoint_id` + Saga**: 恢复执行后再失败的回滚路径无测试。恢复场景下 `saga` 是全新创建的，之前成功 step 的补偿不会自动重建。
7. **Interrupt + Saga**: 执行中被打断的步骤如果之前注册了补偿，中断后的清理（或后续失败回滚）无测试。

---

## 总结

| 检查项 | 结论 | 严重度 |
|---|---|---|
| 1. `Step.compensate_call` 向后兼容 | PASS | — |
| 2. SagaCompensation register/rollback 逻辑 | PASS + 3 个 P2 ISSUE | P2 |
| 3. `checkpoint_ns` PK 冲突 | PASS | — |
| 4. `CheckpointStore.write()` 向后兼容 | PASS | — |
| 5. 测试覆盖 | PASS + 7 个边界缺失 (P2) | P2 |

**整体评价**: 实现简洁务实，核心逻辑正确。所有 ISSUE 集中在错误处理边界（补偿上下文丢失、补偿持久化、补偿失败恢复）和测试纵深上。这些在 M12 首次提交时可以接受，建议在后续迭代中补齐。
