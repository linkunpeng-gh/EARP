# Case A T06——Causal Blueprint Compiler 交接

**状态：完成（2026-08-29）**

## 交付

- 新增 `earp_server.bmc.compiler.causal_compiler`：
  - `seed_case_a_step_types(registry_engine)` 在受控 platform connection 下 seed 两个
    全局、只读的 StepType/Version：`knowledge_query` 和 `output`；每个 handler 有固定
    `handler_version` / `handler_hash`。
  - `compile_case_a_causal_blueprint(engine, tenant_id, snapshot_id, ...)` 只接受本租户、已有
    `passed` validation run 的 immutable Causal Snapshot。
  - 输出固定的 `knowledge_query → output` Blueprint Version，pin Causal Snapshot、Compiler
    identity、StepType Version/handler 以及 canonical Blueprint hash。
  - Evidence Requirement 与 Capability Provider 不写入 Blueprint Step；它们保留为 Snapshot
    的动态需求，由 T08 Prepare 与 T09 PlanFragment 投影处理。
  - 同一输入（snapshot + compiler version/config + dry-run 标识）使用确定性 CompileRecord 和
    Blueprint identity；重复编译返回同一成功记录和 hash。输入配置变化会 supersede 旧
    `compiled` Version，数据库始终只保留一个 current compiled Version。
  - `dry_run=True` 只将 canonical draft/hash 写入成功 CompileRecord 的
    `validation_result`，不创建 Blueprint/Version/child rows。
  - 验证失败（例如 Snapshot 不存在或未验证）会提交 `failed` CompileRecord 与 error log，
    不创建 BlueprintVersion。
- 新增 `tests/test_case_a_causal_compiler.py`。

## Discovery / T07 查询契约

T07 必须只从当前租户的 `planning_blueprint_versions.status = 'compiled'` 发现候选版本，并按
以下链路匹配固定 Intent：

```text
planning_blueprints (tenant_id, blueprint_id, primary_model_type='causal')
  → planning_blueprint_versions (status='compiled')
  → blueprint_intents
    (entry_point, direction, domain, business_objective)
```

Case A Discovery 的唯一匹配键为：

```text
entry_point=production_output
direction=down
domain=production
business_objective=diagnose
```

在匹配完成后，T07 可通过 BlueprintVersion 读取 `blueprint_goal_skeletons`、`blueprint_steps`
和 `blueprint_source_models`。不得以 Logical Blueprint 或可编辑 Causal Model 代替已 pin 的
BlueprintVersion / Source Snapshot；不得返回 `superseded` 或 `withdrawn` 版本。

## 已验证

在 PostgreSQL 16 Testcontainer 中执行：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_case_a_fixture_validation.py \
  tests/test_case_a_snapshot_import.py \
  tests/test_case_a_causal_compiler.py -q
```

结果：`11 passed`。

另已通过：

```bash
.venv/bin/ruff check src/earp_server/bmc/compiler tests/test_case_a_causal_compiler.py
.venv/bin/lint-imports
git diff --check
```

## 有意保留的边界

- 未实现 HTTP route、Discovery/Goal instantiation（T07）、Prepare/ReasoningContext（T08）、
  Provider Resolution 或 Evaluate。
- StepType seed 是 Case A 的受控测试 bootstrap；不是后台 StepType 注册 API。
- 非验证类数据库写入异常由外层事务整体回滚；本任务的显式编译验证失败会留下可审计的
  CompileRecord。T12 将补齐完整 trace/idempotency/replay 语义。
