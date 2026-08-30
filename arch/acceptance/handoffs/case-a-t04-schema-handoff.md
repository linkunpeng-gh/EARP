# Case A T04——Schema / RLS 交接记录

**状态：完成（2026-08-29）**

本记录只描述 T04 的可用数据库基础设施；不代表 T05 Snapshot 导入、T06 Compiler、
Prepare/Evaluate 或端到端 Case A 已完成。

## 已交付

新增连续 Alembic revisions：

- `0035_causal_source_schema`：Causal logical model/version、node/edge/rule/data/capability
  binding、applicability、不可变 Snapshot、validation run，以及全局 Algorithm Registry。
- `0036_blueprint_registry_schema`：Compile Record、Logical Blueprint/Version、source model、
  intent、constraint、output contract、goal skeleton、Step、StepDep、StepSource，以及全局
  StepType Registry。
- `0037_reasoning_runtime_schema`：持久化 `reasoning_contexts` 与 `reasoning_traces`。

所有 23 张 tenant-owned 表均启用并强制 RLS，使用现有
`current_setting('earp.tenant_id', true)` session-variable policy，并向 `earp_app` 授予
必要 DML 权限。四张 Registry 表是 platform-global read-only 表，不使用 tenant RLS。

## 已落实的数据库契约

- 所有已存在的 tenant parent-child 关联使用含 `tenant_id` 的复合 FK。
- `causal_model_snapshots` 禁止 `UPDATE` 和 `DELETE`；发布/validation 状态必须在 Snapshot
  外部表达。
- Compile Record 初始状态为 `running`，允许独立 `failed` 记录而不创建 BlueprintVersion。
- 每个 Logical Blueprint 至多一条 `status = 'compiled'` 的 Version（partial unique index）。
- StepDep 的 from/to Step、StepSource 的 Step/source model reference 均在同一
  BlueprintVersion 中由复合 FK 强制。
- `blueprint_source_models` 对已落地的 `model_type='causal'` 增加数据库触发器：Snapshot
  必须同时匹配 tenant、model ID、semantic version 和 content hash；不能跨租户借用或篡改
  hash。
- `reasoning_traces` 同时以 `(tenant_id, prepare_id, evaluation_input_hash)` 表示相同输入
  幂等身份，并以 `(tenant_id, prepare_id)` 拒绝同一个 Prepare 的不同输入二次消费。

## 验证结果

在 PostgreSQL 16 Testcontainers（非 SQLite）中执行：

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_migrations.py tests/test_rls.py tests/test_case_a_schema.py -q
18 passed
```

覆盖：空库 upgrade、leaf revision downgrade/upgrade、历史 downgrade/re-upgrade、RLS policy
数量与读写隔离、跨 tenant parent 引用、Snapshot 不可变、CompileRecord running/failed、唯一
current compiled、跨版本 StepDep/StepSource、Causal Snapshot pin、Trace 幂等键。

另外已通过：

```text
.venv/bin/ruff check migrations/versions/0035_causal_source_schema.py \
  migrations/versions/0036_blueprint_registry_schema.py \
  migrations/versions/0037_reasoning_runtime_schema.py src/earp_server/bmc \
  tests/test_case_a_schema.py tests/test_migrations.py tests/test_rls.py
.venv/bin/lint-imports
git diff --check
```

## 后续任务使用说明

### T05

- 先验证 Fixture hash，再写入 `causal_models`、`causal_model_versions`、projection rows、
  `causal_model_snapshots` 和 Algorithm Registry。
- Snapshot 创建后不可更新或删除；published pointer 通过
  `causal_model_versions.published_snapshot_id` 写入（该 FK 为 deferred，以允许同一事务
  创建 Snapshot 后设置指针）。
- 不要绕开 `blueprint_source_models` 的 Causal Snapshot guard；T06 写入时应提供精确的
  model/version/snapshot/content hash。

### T06

- 先创建 `blueprint_compile_records(status='running')`，成功时创建
  `planning_blueprint_versions` 并由其单向引用 Compile Record；失败时仅完成 Compile Record。
- Causal Case A 只能编译 `knowledge_query → output`；动态 Evidence Requirement 与物理
  Provider 不是 Blueprint 子表数据。
- 编译版本切换必须在一个事务中处理旧 `compiled` Version 的 `superseded` 状态，避免触发
  current-compiled partial unique index。

## 有意保留的边界

- T04 只为 Case A Causal slice 实现 Causal Snapshot 的数据库 guard。Decision/Scenario
  source model 表尚未存在；未来启用其 `model_type` 前，必须在同一迁移中扩展等价的
  tenant/model/version/hash 完整性约束。
- `reasoning_contexts.status` 的实际状态转换、Trace 的“同 hash 返回既有结果”服务逻辑和
  Context `consumed` 更新由 T08/T11/T12 完成；本任务提供持久化枚举和唯一约束，而不实现
  业务服务。
- 没有新增 HTTP API、Repository service 或自动 Snapshot import；这些不在 T04 范围。

## T05 勘误（0038）

Frozen Algorithm Fixture 的 `not_built` artifact 与 T04 的 `implementation_hash NOT NULL`、
32 字符 `profile_version` 不兼容，且缺少独立 config hash/json 列。连续 revision
`0038_algorithm_fixture_contract` 修复这些字段；不授予 `earp_app` 写平台 Registry，也不把
algorithm config hash 当 executable artifact hash。详见 `case-a-t05-snapshot-handoff.md`。
