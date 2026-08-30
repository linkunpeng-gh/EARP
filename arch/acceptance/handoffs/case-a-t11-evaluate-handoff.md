# Case A T11——sign_propagation_v1 Evaluate 交接

**状态：最小实现已落盘；PostgreSQL Testcontainer 待协调方复跑。**

## 交付

- `bmc.reasoning.evaluate.evaluate_case_a_reasoning()` 只从 Context 获取 pin，并按 tenant、model version、snapshot ID 和 hash 读取 immutable Snapshot；不读 Ontology、Provider、Capability 或 live Causal Model。
- 验证 Context pin 的 sign_propagation algorithm version、profile、params 和 config hash。Fixture 的 `implementation_artifact.status=not_built` 原样输出为 `algorithm_artifact`；没有把 config hash 当 artifact hash，也不声称 Executable Replay。
- 实现 direction、正/负边传播、max-depth 路径枚举、方向冲突 veto、路径乘积 score、max-path aggregation 和稳定 tie-breaker。固定数据的 cycle=0.796005、queue=0.70756。
- required `DATA_UNAVAILABLE` 为 `FAILED`/422，optional 为 `PARTIAL`，infrastructure failed 为 `BLOCKED`/409，完整有效 evidence 为 `COMPLETE`。
- 返回 `evaluation_input_hash` 与 `result_hash`；`as_dict().trace_input` 提供 T12 持久化 trace 所需 pin/hash。T11 不写 Trace 或消费 Context。

## 测试

- 新增 `tests/test_case_a_reasoning_evaluate.py`，覆盖 Golden Top 2/分数/Evidence Chain、required/optional/infra 三态，以及输入记录顺序变化下 pin/result 稳定性。
- 已通过 `py_compile`、ruff check、ruff format check、`git diff --check`。
- Testcontainer 用例需要 Docker daemon；受限环境 Docker socket 被拒绝，协调方需复跑：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
PYTHONPATH=src .venv/bin/python -m pytest tests/test_case_a_reasoning_evaluate.py -q
```

## T12 输入

T12 应归档原始 `acquisition_results`（完整 Observation）、`EvaluationResult.as_dict()` 和 `trace_input` 到 `reasoning_traces`，实现 `prepare_id + evaluation_input_hash` 同输入复用、不同输入拒绝、Context consumed 与 Audit Replay。不得以 Fixture `not_built` algorithm 声称 executable replay。
