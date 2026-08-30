# Case A T07——确定性 Blueprint Planning Entry 交接

**状态：完成（2026-08-29）**

## 交付

- 新增 `earp_server.planner.blueprint_discovery`：只按当前租户、`status='compiled'`
  的 `planning_blueprint_versions` 发现 Causal Blueprint Version，并以
  `entry_point/direction/domain/business_objective` 精确匹配。零或多个候选均 fail closed；
  不回退到 Logical Blueprint、可编辑 Causal Model 或 legacy planner。
- 新增 `earp_server.planner.blueprint_entry`：读取并校验固定
  `intent_goal_fixture.json` 的 semantic hash，检查固定 request text/tenant、一个 diagnose
  SubGoal、role tenant scope、ABox target entity/type、timezone-aware time window 和 pinned Source
  Snapshot applicability；随后实例化一个 Goal。
- 新增薄 HTTP 路由：`POST /v1/ecmc/planning/entry`，body 为
  `{ "text": "为什么 3 号矿昨天产量下降？" }`，tenant/role 来自现有 JWT middleware。
  未匹配或未准备状态返回 `422`，不会经过 `/plan`。
- 保留 `SimpleTaskPlanner`、`/plan`、`task_planner.py` 和 legacy
  `MAX_PLAN_DEPTH` 原样不动。

## T08 的准确输入合同

T07 响应的 `blueprint` 与唯一 `goals[0]` 是 T08 的输入定位信息：

```json
{
  "blueprint": {
    "blueprint_id": "…",
    "blueprint_version_id": "…",
    "blueprint_version": "…",
    "compile_record_id": "…",
    "source_snapshot_id": "cms-mine-3-production-drop-v1",
    "source_content_hash": "…"
  },
  "goals": [{
    "goal_instance_key": "sg-diagnose-production-drop",
    "goal_skeleton_id": "…",
    "objective": "diagnose",
    "entry_point": "production_output",
    "bindings": {
      "entity_id": "mine-3",
      "entity_type": "mine",
      "time_window": {
        "start": "2026-08-28T00:00:00+08:00",
        "end": "2026-08-29T00:00:00+08:00"
      }
    },
    "output_contract_ref": "…"
  }],
  "prepare": {"status": "not_prepared", "prepare_id": null}
}
```

T08 应接收 `tenant_id + blueprint_version_id + goal_skeleton_id + bindings`，并自行回读和验证
Blueprint/Source Snapshot pin；不得信任调用方提供的 snapshot hash，也不得把 T07 的 fixture
解析视为已经 Prepare。此阶段没有 Evidence Requirement、Provider Resolution 或 acquisition
task。

## 测试

新增 `tests/test_case_a_blueprint_entry.py`，覆盖：

- 固定 Fixture hash、一个 diagnose Goal、`mine-3` 和固定时窗绑定；
- request text、role scope、无匹配 intent 的 fail-closed；
- HTTP 入口；
- legacy `/plan` 的 `echo` 回归。

已通过：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
PYTHONPATH=src .venv/bin/pytest tests/test_case_a_blueprint_entry.py tests/test_e2e.py -q
.venv/bin/lint-imports
git diff --check
```

结果：`4 passed`；`ruff check`、`ruff format` 和 import-linter 通过。

## 边界

- Case A fixture 位于当前测试资产目录；这是 T07 的 deterministic test-slice adapter。若要把该
  路由部署到不携带测试资产的环境，必须在后续发布工作中把已审核 fixture 作为只读 runtime
  asset/config 显式交付；缺失时当前实现安全失败，不会转向 legacy 或 live LLM。
- 该完成结论只适用于 provisional Fixture 的技术合同，不代表领域知识或生产 Provider 已确认。
