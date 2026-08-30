# Case A T05——Causal Snapshot 导入、校验与测试发布交接

**状态：完成（2026-08-29）**

## 交付

- 新增 `earp_server.bmc.metamodel.snapshot_import`，提供
  `import_case_a_snapshot_fixture(engine, registry_engine, fixture_dir)`。
- 在导入前验证 raw-byte manifest/package hash 与 canonical semantic hash；mismatch 不重算、不
  替换，直接拒绝。
- 验证 Causal DAG、节点/边/规则/Requirement 引用、ABox binding 和 Ontology 前置条件；悬空
  引用、环或不兼容图均拒绝。
- 在一个 `tenant_session` 内按 data domain → TBox → ABox → causal projection → immutable
  Snapshot/validation run 导入。metrics 只保留为 fixture metadata，未假称进入 Ontology API。
- `published_fixture` 仅登记 `testing` 模型版本的 validated Snapshot pointer，绝不把持久化
  model status 改为 `published`；T05 未实现 Prepare。
- 新增连续 migration `0038_algorithm_fixture_contract`：unbuilt artifact hash 可空，增加
  `algorithm_config_hash/json`，并将 `profile_version` 扩为 64。全局 Registry 继续仅允许受控
  `registry_engine` 写入，tenant app 仍通过 RLS。
- Global Algorithm Registry 写入在 tenant transaction 成功之后；因此 tenant import 失败不会
  留下孤立 Registry 行。若 registry 写失败，immutable snapshot import 可安全幂等重试。

## 测试

新增 `tests/test_case_a_snapshot_import.py`，覆盖正常导入、fixture-only publication、RLS、幂等、
hash mismatch、悬空因果图与不完整 Ontology 前置条件。同步更新 schema/migration 测试。

已通过：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_case_a_fixture_validation.py tests/test_case_a_snapshot_import.py \
  tests/test_case_a_schema.py tests/test_migrations.py -q
```

结果：`19 passed`。

并通过：

```bash
.venv/bin/ruff check src/earp_server/bmc/metamodel/snapshot_import.py \
  tests/test_case_a_snapshot_import.py migrations/versions/0038_algorithm_fixture_contract.py \
  tests/test_case_a_schema.py tests/test_migrations.py
```

## T06/T08/T11 注意事项

- T06 只消费 validation run 为 `passed` 的 immutable Snapshot；动态 Evidence/provider 不进入
  Blueprint。
- T08 必须自行实现 Prepare/ReasoningContext，不能把 T05 的导入期 binding 校验当运行时结果。
- T11 必须发布有真实 artifact hash 的新 Fixture release；不得使用 T05 的 config hash 冒充
  executable artifact hash。
