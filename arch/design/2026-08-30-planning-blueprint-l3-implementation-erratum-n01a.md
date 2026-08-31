# Planning Blueprint L3 — N01A Implementation Erratum

**文档编号：** ERRATUM-DESIGN-ECMC-BLUEPRINT-L3-N01A
**日期：** 2026-08-30
**状态：** v1.0 / Approved / Development Ready
**适用基线：** `arch/design/2026-08-28-planning-blueprint-l3-design.md` v1.0
**权威上游：** `prd/PRD-2026-033-causal-model-management-n01a.md` v1.0、`arch/design/2026-08-30-causal-model-management-n01-detailed-design.md` v0.3.1

## 1. 目的与优先级

本勘误只收口 N01A 引入的“因果模型治理发布 → Candidate Artifact → 显式激活”链路。它不重写 Blueprint L3 的元模型、Planner 消费语义或版本冻结原则。

若本文件与 L3 v1.0 的下列段落冲突，实施 N01A 时以本文件为准：L3 §3.2 的“新版本编译成功即替换当前版本”、§3.4 的 CompileRecord 状态、§4 的触发/落库步骤，以及 §8 的编译 API 解释。其他 L3 v1.0 内容继续有效。

## 2. 已修正的语义冲突

| L3 v1.0 原表述 | N01A 勘误后的实现规则 |
|---|---|
| CompileRecord 仅有 `success`、`failed`。 | CompileRecord 是 append-only build Attempt，状态机固定为 `running → success | failed`。没有 `pending`，终态不可回到 `running`。 |
| 发布可自动触发编译，编译成功即写 BlueprintVersion，并令旧 `compiled → superseded`。 | 治理发布只生成 Snapshot 和发布 outbox 事件，不改运行时指针，也不创建/替换 current Blueprint。编译命令创建 `running` Attempt；成功只冻结 Candidate Artifact。 |
| CompileRecord 是 build log，成功后创建 BlueprintVersion。 | 对 N01A 因果模型，成功 CompileRecord 先成为可审计的 Artifact holder；只有明确的 Activation 命令才从该指定 Artifact 创建 BlueprintVersion。 |
| 编译事件/排队状态可被视为编译状态。 | 可靠投递完全属于 relational outbox。`pending_delivery`、`queued`、`retrying`、`dead_letter` 只能出现在 delivery 记录，绝不写入 CompileRecord。 |

## 3. CompileRecord Attempt 与 Outbox 边界

### 3.1 CompileRecord

`blueprint_compile_records` 保留 build provenance（输入 Snapshot、`compiler_version`、`compiler_config`、build request identity、`source_model_hashes`、错误日志）并新增：

```text
compiled_artifact_json    JSONB NULL
compiled_artifact_hash    VARCHAR(64) NULL
artifact_schema_version   VARCHAR(32) NULL
retry_of_compile_id       VARCHAR(64) NULL
```

- 创建 Attempt 时为 `running`；它可由同步 worker 或被 outbox 消费的 worker 完成，但状态含义不随调度方式变化。
- 成功事务只能写入一次完整 Artifact 三元组，并同时转换为 `success`。`success` 缺少任一字段或 hash 不匹配即为约束违例。
- 失败事务转换为 `failed`，不产生可激活 Artifact。
- 重试只能对 `failed` Attempt 创建新行，且 `retry_of_compile_id` 精确指向其父 Attempt；不得原地重跑，也不得把 success 作为 retry 父节点。
- 相同 `(tenant, actor, operation, Idempotency-Key)` 的同一请求必须回放同一 Attempt；幂等回放不是新 Attempt。

### 3.2 Relational outbox

`outbox_events` 与 `outbox_deliveries` 是 N01A 的最小实现范围。发布、编译请求、激活、归档的业务事务各自与相应 event 同事务提交；delivery 的租约、尝试次数、最后错误和状态独立维护。

Outbox 的成功、失败、重试或积压不会改变已写入的 Snapshot、Artifact、Blueprint 或 active pointer。它用于可靠通知、异步编译调度和缓存失效；Discovery 的正确性只读数据库中的 active pointers 与当前 compiled Blueprint。

## 4. Candidate Artifact 是纯、可物化的 IR

成功 Attempt 保存的 Candidate Artifact 是完整 Blueprint IR，不是 Compiler log、部分 patch 或对 live Causal Model 的引用。它必须足以在不读取可变模型内容、不调用 Compiler 的条件下物化一份 BlueprintVersion。

Artifact 必须包含：

- `artifact_schema_version`；
- 每个将写为 `BlueprintSource` 的 `model_type`、稳定 `model_id`、`model_version`、`source_snapshot_id`、`source_content_hash`、`model_role`；
- intent、goal skeleton、constraints、output contracts、fallback policy；
- 被 pin 的 StepType/handler identity 与 schema version；
- steps、dependencies、step sources、capability requirements 及它们的 schema versions。

Artifact 不得包含：Compiler version/config、build request 或 Idempotency-Key、聚合 provenance `source_model_hashes` bookkeeping、运行时 Observation/Task、Provider 解析结果、数据库行 ID、时间戳、审计/outbox 状态、active pointers 或展示布局。前述 build provenance 继续属于 CompileRecord，但不影响 Artifact hash。

`compiled_artifact_hash` 只针对本纯 IR 依照 [canonicalization/hash contract](2026-08-30-n01a-canonicalization-and-hash-contract.md) 计算；它与 Causal Snapshot 的 `content_hash` 是不同身份。

## 5. 严格 Artifact-only activation

激活是唯一能让 N01A 候选成为 current Blueprint 和 runtime active 的命令。它必须在一个数据库事务内完成，并且调用者必须显式指定：

```json
{
  "model_version_id": "cmv-…",
  "compile_record_id": "cr-…",
  "expected_active_model_version_id": "cmv-old-…",
  "expected_active_snapshot_id": "cms-old-…"
}
```

首次激活时后两个字段必须出现并为 JSON `null`。Activation Coordinator 必须：

1. 锁定 Logical Model、指定 candidate Version、CompileRecord 和旧 current Blueprint；验证 Version=`published`、Attempt=`success`、Snapshot/Artifact/目录引用精确关联且仍有效。
2. 在锁内比较两个 `expected_active_*` 与当前 Model active pointers；不匹配返回 `409 ACTIVE_VERSION_CHANGED`，且零业务写入。
3. 读取并验证保存的 Artifact JSON/hash/schema。**禁止**重新调用 Compiler、重新读取 live Draft/Model 以生成 IR，或扫描多个 candidate 自动选择。
4. 从该 Artifact materialize BlueprintVersion 及子表；其 projection canonical hash 必须严格等于 `compiled_artifact_hash`。
5. 仅在第 1–4 步全成功后，原子执行旧 Blueprint `compiled → superseded`、新 Blueprint 成为唯一 `compiled`、旧 active CausalModelVersion `published → superseded`、新 Version/Snapshot 写为 active pointer，并追加 audit/outbox。

任一步失败都必须回滚，保留旧 active/compiled 组合。这是 last-known-good 的实现定义，而不是靠 outbox 或调用方重试保证。

## 6. Archive 对齐

当归档 active CausalModelVersion，必须在同一事务清空 Model active pointers、将该 Causal Version 设为 `archived`，并将**精确 pin 该 source snapshot/content hash** 的 current Blueprint `compiled → withdrawn`。找不到唯一精确匹配 BlueprintSource、发现不匹配或事务失败时一律回滚。不得自动激活历史 superseded 版本。

`archived` 只用于因果源模型；`withdrawn` 仍只用于 BlueprintVersion。

## 7. N01A 实施验收

- `0040_n01_causal_model_management` 以 `running → success|failed`、Artifact 三元组不可变、retry lineage 和独立 outbox 状态落库。
- 成功编译不会创建或替换 current Blueprint；只有 activation 会替换。
- activation 的测试必须证明：不会调用 Compiler；CAS 冲突零写入；materialized projection hash 与 Artifact hash 相等；失败仍保留旧 active。
- Case A `testing` Fixture 不参与以上生产 activation 链路；它只经测试依赖注入的 Fixture Discovery Adapter 保留回归。
