# Case A T08——Reasoning Prepare 与 ReasoningContext 交接

**状态：完成（2026-08-29）**

## 交付

- 新增 `earp_server.bmc.reasoning.prepare`：
  - `prepare_case_a_reasoning(engine, tenant_id, blueprint_version_id, goal_bindings, *, goal_skeleton_id, reasoning_mode, authz_scope)`；
  - `get_reasoning_context` 与 `cancel_reasoning_context`，提供 `prepared → expired/cancelled` 的基础生命周期；
  - `PrepareResult` 返回持久化 `prepare_id`、上下文 hash、pin 与**逻辑** Evidence Requirements。
- 新增迁移 `0039_ctx_profile_pin`。T05 Fixture 的
  `sign-propagation-default-profile/v1` 超过原 `reasoning_contexts.algorithm_profile_version`
  的 32 字符限制；迁移将其扩为 64，与 Registry 的 0038 契约一致，不截断算法身份。
- 新增 `tests/test_case_a_reasoning_prepare.py`。

## T07 调用合同

T07 的 `PlanningEntryResult.as_dict()` 产生一个 Blueprint 和一个 Goal。调用方取：

```python
await prepare_case_a_reasoning(
    engine,
    tenant_id,
    entry["blueprint"]["blueprint_version_id"],
    entry["goals"][0]["bindings"],
    goal_skeleton_id=entry["goals"][0]["goal_skeleton_id"],
    reasoning_mode="explainable",
)
```

服务不信任调用方传入的 Snapshot/hash：它在同一 tenant session 中回读 `compiled`
BlueprintVersion、primary causal `blueprint_source_models`、immutable Snapshot 及其 `passed`
validation run，并验证 source content hash、Goal Skeleton 和 model applicability。

## Prepare 行为与边界

- 按已 pin Snapshot 的 `case-a-abox-binding/v1` 解析 target：mine 级 requirement 绑定
  `mine-3`，设备组/运输 requirement 经 active Fact 绑定到对应子实体；`unknown`、零个或多个
  target、错误 type/binding、无效时间窗、越权 scope、跨 tenant 和不匹配 source pin 都 fail closed。
- 每个 Context 动态生成唯一 requirement ID，保留 fixture `requirement_key`、source requirement ID、
  required/optional、unit、aggregation、target 和 time window。`instance_snapshot` 保存 context
  entity、实际解析出的实体和 Fact，Context 可在服务重建后读取。
- `explainable` 与 `causal_diagnosis` 确定性选择 Case A 的
  `sign-propagation-v1-fixture`。该版本尚无 executable artifact，因此仅能 Prepare/规划，不能
  Evaluate；T11 必须显式发布 artifact-bearing Fixture 版本。
- 此模块不导入 Capability/Connector/Provider 模块，且不会读取 readiness 或获取业务数据。

## T09 输入

T09 仅消费 `PrepareResult.prepare_id` 或 `get_reasoning_context()` 中的
`evidence_requirements`。每项已有 `requirement_id`、`requirement_key`、
`capability_contract_ref` 与已冻结 `target_entity_id`；Capability Resolution 只能选择 provider，
不得推导或改写 target/requirement。

## 验证

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_case_a_reasoning_prepare.py tests/test_migrations.py tests/test_case_a_schema.py -q
```

结果：`15 passed`（PostgreSQL 16 Testcontainer）。

并通过：

```bash
.venv/bin/ruff format --check src/earp_server/bmc/reasoning \
  tests/test_case_a_reasoning_prepare.py migrations/versions/0039_reasoning_context_profile_pin.py \
  tests/test_migrations.py
.venv/bin/ruff check src/earp_server/bmc/reasoning tests/test_case_a_reasoning_prepare.py \
  migrations/versions/0039_reasoning_context_profile_pin.py tests/test_migrations.py
```
