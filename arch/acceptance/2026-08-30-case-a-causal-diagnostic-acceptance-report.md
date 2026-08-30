# Case A 因果诊断纵向切片——验收报告

**验收日期：2026-08-30**  
**结论：`Planning Blueprint Causal Diagnostic Vertical Slice — Accepted`（仅限 Fixture/mock Provider 验收范围）。**

## 已验证范围

- G1：Fixture hash、Causal Snapshot、Ontology 的 data domain → TBox → ABox 导入、租户隔离、不可变 Snapshot 与编译记录。
- G2：固定 Case A 意图只发现唯一 current compiled Blueprint；旧 `/plan` 未改动。
- G3：Prepare 使用 Blueprint source pin 解析五个 ABox target；Capability Resolution 生成 5 个 acquisition、Evaluate、output 的 DAG。
- G4：完整路径返回 Golden Top 1 `haulage_cycle_time`，其证据链为 `haulage_cycle_time → effective_production_capacity → production_output`；required `DATA_UNAVAILABLE` 形成 completed business Observation 并令评估为 `FAILED/422`，基础设施故障令评估为 `BLOCKED/409`。
- G5：Trace 归档、同输入幂等、不同输入拒绝、hash 篡改检测以及 audit-only replay。

## 最终验证证据

在干净的 PostgreSQL Testcontainer 中执行：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_case_a_fixture_validation.py tests/test_case_a_schema.py \
  tests/test_case_a_snapshot_import.py tests/test_case_a_causal_compiler.py \
  tests/test_case_a_blueprint_entry.py tests/test_case_a_reasoning_prepare.py \
  tests/test_case_a_plan_fragment.py tests/test_case_a_reasoning_runtime.py \
  tests/test_case_a_reasoning_evaluate.py tests/test_case_a_reasoning_trace.py \
  tests/test_case_a_e2e.py -q
```

结果：**45 passed**（另有 1 条既有 FastAPI TestClient deprecation warning）。

另已通过：Ruff format/check、`git diff --check`。本轮修复了一项真实的顺序依赖：重放旧的成功 CompileRecord 时，编译器现在会把该 pinned Blueprint Version 恢复为唯一 `compiled` current version；回归测试已加入。

## 人工验收建议

1. 查看 [Case A E2E 测试](/Users/linkunpeng/work/EARP/apps/earp-server/tests/test_case_a_e2e.py:1)，确认三条路径和业务语义。
2. 查看 [最终任务清单](/Users/linkunpeng/work/EARP/arch/acceptance/2026-08-29-case-a-causal-diagnostic-implementation-task-list.md:42) 与各 T04–T12 handoff。
3. 在本机允许 Docker 后复跑上述命令。

## 明确不在本次结论中

- T14：尚未接入真实的只读企业数据 Provider；当前 Provider 是可控 Fixture/mock。
- T15：尚未启动 Case B 决策推荐验收设计。
- 未验证性能、并行 DAG 调度、UI 或 Phase 2 executable replay。
- Fixture 的 `implementation_artifact.status=not_built` 保持原样；本报告不把 algorithm config hash 说成可执行产物 hash。
