# Case A T09——Capability Resolution 与 PlanFragment 投影交接

**状态：完成（2026-08-29）**

## 交付

- 新增 `earp_server.capability.resolution.FixtureCapabilityResolver`：从冻结的
  `capability_fixture.json` 解析 **logical contract → deterministic mock provider**。
  这是明确的 Case A fixture adapter；现有 `business_capabilities` 仍是物理 Capability
  Registry，尚不等同于 logical Capability Contract registry。
- Resolver 只依据 `capability_contract_ref`、Prepare 已解析的 target entity type、以及
  requirement/provider binding 选择 Provider。它不写入、替换或重新解析
  `target_entity_id`、`target_entity_type` 和 `time_window`。
- required requirement 无可用兼容 Provider 时 fail closed；optional requirement 未绑定或
  不可用时仍创建一个 `reasoning.acquire` Task，payload 标记
  `provider_resolution_status=unbound_optional`。T10 必须把它结束为缺失 optional 的业务
  Observation，不能在规划期静默跳过。
- 新增 `planner.plan_fragment`：
  - `KnowledgeQueryPlanFragmentHandler.project()` 只消费持久化、状态为 `prepared` 的
    ReasoningContext，并从其 pin 的 BlueprintVersion 读取 `knowledge_query`/`output` Step
    identity；
  - 投影 **5 个 acquisition + 1 个 reasoning.evaluate + 1 个 output**；
  - 每个 acquisition payload 带 `prepare_id`、runtime/source requirement identity、contract、
    provider binding、原样 Prepare target/time window、measurement 和 Blueprint Step pin；
  - Evaluate payload（`case-a-reasoning-evaluate/v1`）带相同 `prepare_id` 与全部 planned
    runtime requirement IDs；其依赖严格等于全部 acquisition（required 与 optional 都包括）；
  - output 只依赖 Evaluate。
- 添加独立 `validate_case_a_plan_fragment()`：检查引用完整性、唯一性、Cycle、Case A
  shape 和真实最长依赖路径。默认深度阈值仍为 5，但本例最长路径为 3，因此七个 Task 不会被
  legacy `planner.validation.MAX_PLAN_DEPTH` 的线性 item-count 规则误拒绝。旧
  `validate_plan()` 与 `/plan` 未修改。
- `reasoning.acquire` 与 `reasoning.evaluate` 当前是 **T10 的 adapter payload contract**，
  本任务没有把它们接入 Connector 或 Runtime 白名单，避免虚假宣称已可执行。

## 测试

新增 `tests/test_case_a_plan_fragment.py`，覆盖：

- 五个 acquisition、一个 Evaluate、一个 output，及其稳定依赖；
- target/time window 未被 Provider Resolution 改写；
- graph depth=3，而非 seven-task count；
- required Provider unavailable fail closed；optional unavailable 仍进入 Evaluate dependency；
- 从真实 T05–T08 migrated Context 读取 pin 后投影；不存在/非 prepared Context 被拒绝。

已通过：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_case_a_reasoning_prepare.py tests/test_case_a_plan_fragment.py -q
```

结果：`6 passed`（PostgreSQL 16 Testcontainer）。

已通过：

```bash
.venv/bin/ruff check src/earp_server/capability/resolution.py \
  src/earp_server/planner/plan_fragment.py tests/test_case_a_plan_fragment.py
.venv/bin/ruff format --check src/earp_server/capability/resolution.py \
  src/earp_server/planner/plan_fragment.py tests/test_case_a_plan_fragment.py
```

`lint-imports` 仍因仓库既有的两条无匹配 `ignore_imports`
(`conversation.chat_service → knowledge.routing` 和 `→ ontology.capability_query`) 失败；
本任务新增的两条 PlanFragment exception 已被配置，未报告新的 independence violation。

## T10 输入

T10 应实现并注册/路由以下已冻结 payload contracts：

- `reasoning.acquire`：根据 `provider_resolution_status` 调用 fixture Mock Provider，正常数据、
  `DATA_UNAVAILABLE` 与 stale/suspicious 都返回 `StepResult.completed` + EvidenceObservation；
  connector/auth/crash 返回 `StepResult.failed`。
- `reasoning.evaluate`：只消费 payload 的 `prepare_id` 和 planned requirement IDs；它必须等待
  PlanFragment 所有 acquisition 的业务终态，并在任何基础设施 `FAILED` 时 blocked。

不要让 T10 重新 Prepare、重新解析 Provider，或以 live target/algorithm 替代 Context pin。
