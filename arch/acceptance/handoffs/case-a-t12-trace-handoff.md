# Case A T12——Trace、幂等与 Audit Replay 交接

**状态：实现已落盘；T12 集成测试最后一次复跑前仅修正测试篡改值。**

## 交付

- 新增 `apps/earp-server/src/earp_server/bmc/reasoning/trace.py`。
- `archive_case_a_reasoning()` 在单个 tenant transaction 内锁定 ReasoningContext，归档完整 acquisition records、EvidenceObservation、`EvaluationResult.as_dict()`、evaluation/result hash、Context/Source Snapshot/Algorithm pin，以及可选 Request/Plan lineage。
- 同一 `prepare_id + evaluation_input_hash` 返回既有 Trace，不创建重复记录；同一 Prepare 的不同 input 明确拒绝。首次成功归档将 Context 从 `prepared` 原子地置为 `consumed`。
- 已复用现有 `reasoning_traces` 的唯一约束和 `audit_logs`，未增加 migration。Evaluate 的 `BLOCKED` 在现有 Trace schema 中记录为 `failed`，原始 `BLOCKED` 保留在 result snapshot。
- `replay_case_a_reasoning_trace()` 只读取归档 Trace，校验 evaluation input/result hash，并返回 pinned Snapshot graph、Context、Algorithm、Observations、Evidence、Result 和 lineage；明确 `replay_mode=audit_only`、`executable_replay=false`，不调用 Provider、live Ontology、live Causal Model 或算法。
- `bmc.reasoning.__init__` 已导出 Trace service/result/error 类型。
- 新增 `tests/test_case_a_reasoning_trace.py`，覆盖成功归档、幂等、Context consumed、Audit event、不同输入拒绝、hash tamper 检测。

## 验证

静态验证已通过：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
.venv/bin/ruff format --check src/earp_server/bmc/reasoning/trace.py tests/test_case_a_reasoning_trace.py
.venv/bin/ruff check src/earp_server/bmc/reasoning/trace.py \
  src/earp_server/bmc/reasoning/__init__.py tests/test_case_a_reasoning_trace.py
PYTHONPATH=src .venv/bin/python -m py_compile \
  src/earp_server/bmc/reasoning/trace.py tests/test_case_a_reasoning_trace.py
git diff --check
```

结果：全部通过。

Testcontainer 首次受沙箱 Docker socket 权限限制；获得 Docker 访问后复跑曾得到 `2 passed, 1 failed`，失败原因是测试把已为 `COMPLETE` 的状态篡改为同值，未触发 hash 变化。该测试已修正为篡改成 `PARTIAL`，协调方需复跑以下命令确认最终 `3 passed`：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
PYTHONPATH=src .venv/bin/python -m pytest tests/test_case_a_reasoning_trace.py -q
```

## 后续注意

- T13 应把真实 Request/SubGoal/Blueprint/Compile/Plan/Task 身份通过 `lineage=` 传入 archive service，才能在最终 E2E 中验证完整链路；T12 在没有这些调用方上下文时不会伪造运行时 ID。
- 当前 Replay 是 Phase 1 Audit Replay，不是 Phase 2 Executable Replay；Fixture 的 `implementation_artifact.status=not_built` 必须继续原样保留。
