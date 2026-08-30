# Case A T10——Evidence Acquisition Runtime 交接

**状态：完成（2026-08-29）**

## 交付

- 新增 `apps/earp-server/src/earp_server/bmc/reasoning/runtime.py`：
  `FixtureReasoningRuntimeAdapter.acquire()` 读取固定 Case A observation fixture，输出完整
  `evidence-observation/v1` envelope；保留 requirement、Prepare target、time window、measurement、
  source、quality、provenance 和错误信息。
- `DATA_UNAVAILABLE`、optional `unbound_optional`、stale/suspicious 均返回
  `task_status=completed` + `terminal_state=business`，业务空数据不会抛异常；Observation 带
  `status=DATA_UNAVAILABLE`、`error.code=DATA_UNAVAILABLE`、`timestamp`、`source`。
- Provider/connector/auth/crash 模拟或显式基础设施失败抛出
  `ReasoningInfrastructureError(code="connection")`，供现有 StepRunner 收敛为 Task `FAILED`。
- `evaluate()` 仅做 acquisition terminal/readiness gate：缺少任一 planned result 时拒绝提前启动；基础设施
  FAILED 返回 `status=BLOCKED`；其余返回 `status=READY`，并完整转发 observations、missing required/optional。
  COMPLETE/PARTIAL/FAILED 因果结论留给 T11，不在 T10 偷做推理。
- `connector.py` 增加两个最小显式分派：`reasoning.acquire`、`reasoning.evaluate`。未改写或复用
  legacy `tool.fetch`，未修改 adapter whitelist。

## 测试证据

新增 `apps/earp-server/tests/test_case_a_reasoning_runtime.py`，覆盖：

- valid observation envelope；
- required business `DATA_UNAVAILABLE` 仍 completed；
- optional unbound 不跳过并可到达 Evaluate；
- stale/suspicious 仍为业务终态；
- infrastructure failure 与 Evaluate BLOCKED。

执行结果：

```text
PYTHONPATH=src .venv/bin/pytest tests/test_case_a_reasoning_runtime.py -q
5 passed
ruff check：通过；ruff format：通过；git diff --check：通过
```

## T11 对接说明

Evaluate 调用必须把所有 acquisition 的返回记录放入 `acquisition_results`（或作为第二个参数传入），
每条记录至少保留 `requirement_id`、`requirement_level`、`task_status`、`terminal_state`、`observation`。
当前 adapter 不持久化 Observation，也不实现算法、ranking 或 ReasoningTrace；这些属于 T11/T12。
默认 Connector hook 使用测试 fixture 路径，仅用于 Case A deterministic slice，不代表真实 Provider 已接入。
