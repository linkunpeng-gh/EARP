# N01A Canonicalization 与 Hash 契约

**文档编号：** CONTRACT-ECMC-N01A-CANONICALIZATION
**日期：** 2026-08-30
**状态：** v1.0 / Approved / Development Ready
**适用对象：** CausalModelSnapshot、Candidate Artifact、materialized Blueprint projection

## 1. 共同规则

服务端的单一 Canonicalizer 是所有 hash 的唯一计算者。客户端可以显示或本地校验 hash，但传入的 hash 不能替代服务端计算；若命令带 `expected_content_hash`，它仅作确认用途，不匹配返回 `409 CONTENT_CHANGED`。

三个 payload family 使用相同的编码算法、不同的字段白名单：

| family | schema 标识 | hash 字段 | 用途 |
|---|---|---|---|
| Causal Snapshot | `causal-snapshot/v1` | `content_hash` | 治理发布的因果模型语义身份。 |
| Candidate Artifact | `blueprint-ir/v1` | `compiled_artifact_hash` | 可由 activation 物化的纯 Blueprint IR。 |
| Blueprint projection | `blueprint-ir/v1` | 不单独持久化 | 从已 materialize 的 BlueprintVersion/子表投影，必须等于对应 Artifact hash。 |

### 1.1 规范化算法

1. 先按本文件的 family schema 投影白名单；未知字段一律拒绝，不能“顺便”参与 hash。
2. 对所有文本作 Unicode NFC；禁止不可见控制字符（允许 `\n`、`\t` 的说明字段除外）。枚举值、stable ID、schema version、hash 均为 ASCII 小写规范形式；ID 不得通过大小写折叠变更。
3. JSON object key 按 Unicode code point 升序排序；object 不保留输入顺序。
4. 语义集合在 schema 指定的稳定复合键上排序后再编码；明确有业务顺序的数组（例如 ordered goal steps）保留其 `ordinal` 且按 ordinal 排序。无稳定键的 set 是 schema error。
5. 数值先按 Decimal 语义解析；禁止 NaN、Infinity 和二进制 float 比较。以最短十进制非指数形式输出，移除无意义尾零，`-0` 规范为 `0`。
6. 使用 UTF-8、`ensure_ascii=false`、无额外空白的 JSON（等价 Python `sort_keys=True, separators=(',', ':')`，但必须满足前四步的 domain normalization）。对 UTF-8 bytes 求 SHA-256，持久化为 64 位小写 hex；传输中可标注 `sha256:<hex>`，数据库值不含前缀。

Canonicalizer 版本须随 schema 标识一同记录。任何需要改变白名单、集合键、数字或编码规则的修改必须创建新的 schema version；旧 payload 一律使用旧版本实现校验，绝不“升级后重算”。

## 2. Causal Snapshot payload (`causal-snapshot/v1`)

Snapshot payload 的顶层字段固定为：

```text
snapshot_schema_version, model_identity, diagnostic_target,
algorithm_profile, nodes, edges, rules, evidence_requirements,
applicability, catalog_resolutions, semantic_schema_versions
```

`model_identity` 只包含稳定 Logical Model ID 与因果 Version 的业务版本标识；不包含数据库 row ID。`diagnostic_target` 采用完整 target signature。节点按 `node_key`、边按 `(from_node_key,to_node_key,edge_key)`、规则按 `rule_key`、Evidence Requirement 按 `(node_key,requirement_key)`、Capability Contract 按 `(role,stable_id,version)`、目录 resolution 按 `(kind,stable_id,version)` 排序。

必须纳入的语义字段包括：节点 observability/受控实体引用/入口标记，边方向/效应/强度/置信度/lag/Relation Type，规则 schema 与 spec，Evidence 的 metric/unit/aggregation/time/binding/required 性质及 primary/supporting contracts，适用范围，以及每个 CatalogRef 的 `{kind,stable_id,version,content_hash}` 和相关 semantic schema version。

明确排除：名称、描述、notes、rationale、画布位置/颜色/分组/折叠状态、展示排序、Draft revision/ETag、创建/审核/发布时间、用户和角色、Validation/Review/Audit ID、active pointers、CompileRecord、outbox、Blueprint ID 与该 Snapshot 自己的 hash。自由文本说明可持久化和审计，但不是 executable semantic payload；若未来要使某类文本参与推理，必须新增 schema version 后显式纳入。

## 3. Candidate Artifact 与 Blueprint projection (`blueprint-ir/v1`)

Artifact 顶层固定为：

```text
artifact_schema_version, source_models, intents, goal_skeletons,
constraints, output_contracts, fallback_policy, step_type_pins,
steps, dependencies, step_sources, capability_requirements
```

`source_models` 按 `(model_type,model_id,model_version,source_snapshot_id,model_role)` 排序，且每项必须含 `source_content_hash`。其余集合分别按 intent 五元组、goal skeleton key、constraint key、output key、step type identity、step stable key、dependency `(from,to,dep_type)`、step source `(step_key,source_ref_key,element_type,element_key,role)`、capability requirement key 排序。

纳入 hash 的是足以物化 Blueprint 子表的纯 IR：source pins、intent、goal skeleton、constraint、output、fallback、StepType/handler identity 与 semantic/schema versions、steps/params、deps/conditions、step sources、capability requirements/contract refs。`BlueprintSource` 的 `source_snapshot_id + source_content_hash` 必须在 hash 内。

明确排除：`compiler_version`、`compiler_config`、compiler build request、Idempotency-Key、CompileRecord ID、聚合 `source_model_hashes`、Artifact/Blueprint 数据库 ID、物理 Provider/Capability 解析、Observation/Task、timestamps、audit/outbox、active pointer、UI layout。若某项只为 build provenance 而不 materialize，就不能进入 Artifact hash。

Activation materialize 后，以同一 schema 把 BlueprintVersion 和其子表投影为上述 payload；将数据库 generated IDs 转换为 Artifact 中的 stable keys，并省略 Artifact 不存在的 build provenance。投影 hash 不相等即 transaction failure，禁止部分提交。

## 4. 输入、存储和验证边界

- Draft API 接受业务负载，但发布服务先解析 CatalogRef、完成 schema/语义校验，再生成 Snapshot payload；Draft JSON 本身不是 hash 输入。
- Compiler 只读取 immutable Snapshot 和固定的 compiler configuration，构造 Artifact payload；它必须在把 Attempt 改为 `success` 的同一事务验证 Artifact hash。
- Activation 只验证已保存 Artifact 与 materialized projection；它不得改写 Artifact 来适应当前目录、当前模型或新编译器版本。
- 目录条目的 `content_hash` 与 version 是 Snapshot/Artifact 的 pin；catalog 显示名或数据库内部主键不参与任何 hash。

## 5. 必须纳入的测试向量

实施前必须将下列最小 golden fixtures 与 expected hash 入库，并由 Snapshot、Compiler、Activation 共用：

1. 相同语义但 object key/集合输入顺序不同，hash 相同。
2. NFC 与等价分解 Unicode 输入，hash 相同；语义文本变更、stable ref/version/content hash 变更，hash 不同。
3. UI layout、审计时间、actor、revision、outbox 或 Compiler config 变更，不改变对应 Snapshot/Artifact hash。
4. Artifact 内任一 source snapshot/content hash、StepType handler pin、step/dependency/contract 变更，Artifact hash 不同。
5. 从 Artifact materialize 的 Blueprint projection hash 与 Artifact hash 相同；移除一个 step source 或改变 pin 必须失败。
