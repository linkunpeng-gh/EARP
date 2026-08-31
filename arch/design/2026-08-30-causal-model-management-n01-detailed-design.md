# 因果建模管理能力 N01A 详细设计

**文档编号：** DESIGN-ECMC-N01A-CAUSAL-MODEL-MANAGEMENT
**版本：** v1.0 / Architecture Approved / Development Baseline
**日期：** 2026-08-30
**状态：** Architecture Approved
**产品上游：** `prd/PRD-2026-033-causal-model-management-n01a.md` v1.0
**技术继承：** `prd/PRD-2026-032-ecmc-causal-diagnostic-vertical-slice.md` v1.0、`arch/design/2026-08-28-planning-blueprint-l3-design.md` v1.0
**配套实施契约：** `arch/design/2026-08-30-planning-blueprint-l3-implementation-erratum-n01a.md` v1.0、`api/2026-08-30-n01a-causal-model-management-api-contract.md` v1.0、`arch/design/2026-08-30-n01a-canonicalization-and-hash-contract.md` v1.0、`arch/design/2026-08-30-n01a-catalog-resolver-and-fixture-boundary.md` v1.0
**范围：** N01A（因果模型管理 API、版本治理、发布与编译衔接）；N01B（可视化建模界面）只定义其消费的接口和边界。

---

## 1. 目标、结论与边界

N01A 要把 Case A 中由 Fixture 导入的因果模型，升级为可由受权业务人员治理的产品资产。它不改变已冻结的推理、Planning Blueprint、Trace 或 Provider 执行语义。

发布主链如下：

```text
建模者编辑 Draft Version
  → 运行校验并修复问题
  → 提交审核（in_review）
  → 审核者治理发布（canonical hash + Immutable Snapshot）
  → 显式/事件触发 Compiler（CompileRecord）
  → Activation Coordinator 原子激活
  → Immutable BlueprintVersion
  → 诊断消费 Logical Model 当前 active Snapshot
```

本版确定以下产品原则：

1. 一个 **Causal Model Version** 只承载一个因果图和一个诊断业务目标；需要多个目标时，由请求的 Goal Resolution / Discovery 分别选择多个模型或 Blueprint，不在一个版本混合多个目标。
2. 模型治理使用既有可配置 RBAC。生产租户默认遵循“建模者提交、审核者发布”；开发/演示租户可由角色配置允许同一用户完成两步，但操作仍必须留下独立审计记录。
3. 所有可执行字段只能引用受控目录；允许业务说明、假设、备注等自由文本。缺项走目录扩展申请，不能在模型中填写 SQL、端点、Provider 参数或任意 ID。
4. N01 Phase-1 的**创作、校验、发布**只接受 DAG，且只对应 `sign_propagation_v1` 算法 Profile；底层因果图存储保留 general directed graph 能力，数据库不得施加全局无环限制。未来环路/其他算法 Profile 必须另行定义 authoring validator 与完成度语义。
5. 已发布版本及其 Snapshot 永不就地修改或删除；业务变化必须复制为新 Draft Version。

### 1.1 非目标

- 不接入真实 Provider、凭据、连接地址或物理 Capability Binding（N03）。
- 不实现诊断发起、运行结果或 Trace UI（N02）。
- 不改变 Causal Prepare 的动态 Evidence Requirement 展开；编译器仍不得静态预展开节点级 Provider。
- 不把 Blueprint 当作可编辑业务模型。Blueprint 仍是编译产物，生命周期保持 `compiled → superseded/withdrawn`。
- 不在本任务实现 N01B 的图画布、自动布局或前端交互；其仅调用本设计的 API。

---

## 2. 术语与领域对象

### 2.1 对象关系

```text
CausalModel（逻辑身份 + target signature + active version/snapshot pointer） 1 ── * CausalModelVersion（可治理版本）
                                                │
                                                ├─ * CausalNode
                                                ├─ * CausalEdge
                                                ├─ * CausalRule
                                                ├─ * EvidenceRequirement / DataBinding
                                                ├─ * CapabilityContractBinding
                                                ├─ * ApplicabilityScope
                                                ├─ * ModelValidationRun
                                                ├─ * ModelReview
                                                └─ 1 Published CausalModelSnapshot（仅治理发布成功后）
                                                           │
                                                           └─ * CompileRecord（success 时冻结 Candidate Artifact）
                                                                                                  │
                                                                                                  └─ * BlueprintVersion（仅由指定 Artifact 物化并钉 hash）

受控目录：Ontology（DataDomain / EntityType / RelationType / Metric）
          BindingTemplate（实例绑定模板）
          CapabilityContract（逻辑能力合同）
          ↓ 被 EvidenceRequirement、Node、Edge、Rule 只读引用

目录扩展申请（CatalogChangeRequest） ──→ 受控目录条目（审批后才 active）
```

| 对象 | 身份与职责 | 可变性 |
|---|---|---|
| `CausalModel` | 稳定逻辑身份、名称、所属数据域、`diagnostic_target_signature`，以及唯一 runtime `active_model_version_id/active_snapshot_id` 指针；例如“矿山产量下降诊断”。 | 可改展示信息；目标签名和 active 指针只能按治理/激活契约改，不承载图内容。 |
| `CausalModelVersion` | 一个可治理的单一诊断目标、图和适用范围的版本聚合根；治理发布可与 runtime activation 分离。 | 仅 `draft` 可编辑。 |
| `CausalNode` | 某一业务变量/现象；引用受控 Entity/Metric 语义，标识入口或中间/结果节点，并声明 `observability`。 | 归属 Draft Version。 |
| `CausalEdge` | 有方向因果关系；引用受控 Relation Type，含正负效应、强度、置信度、时滞。 | 归属 Draft Version。 |
| `CausalRule` | 受限的 predicate / threshold / direction rule；其结构必须符合受控 schema。 | 归属 Draft Version。 |
| `EvidenceRequirement` | 对 observable 节点的可执行取证语义：指标、单位、聚合、时间窗口、实例绑定、required/optional。 | 归属 Draft Version。 |
| `CapabilityContractBinding` | 每个 Evidence Requirement 恰好一个 primary、零到多个 supporting 的**逻辑** Capability Contract 绑定。 | 不保存物理 Provider；不表达 alternatives。 |
| `CausalModelSnapshot` | 发布时由完整语义内容生成的不可变 JSON 与 canonical hash。 | 仅插入；数据库已禁止 update/delete。 |
| `Candidate Artifact` | CompileRecord success 时保存的完整、规范化、不可变 Blueprint IR、artifact schema version 与 canonical hash。 | 仅在 `running → success` 时写入；之后不可更新。 |
| `ModelValidationRun` | 对一个 Draft 内容或已生成 Snapshot 的结构化校验结果。 | 新建记录；不得覆盖历史。 |
| `ModelReview` | 提交、批准、驳回、撤回等人机治理决定及理由。 | 追加式审计记录。 |
| `CatalogChangeRequest` | 对缺少的指标、实体、关系、绑定模板或逻辑能力合同的扩展申请。 | 独立流程，不可绕过目录。 |

### 2.2 单一诊断目标合同

`CausalModel` 新增一个不可变的 `diagnostic_target_signature`；`CausalModelVersion` 有必填 `diagnostic_target` JSON 及由其 canonicalization 得出的同名签名。它们至少包括：

```json
{
  "objective": "diagnose",
  "entry_point": "production_output",
  "direction": "down",
  "domain": "production",
  "target_entity_type_ref": "mine",
  "time_window_schema_ref": "daily_window/v1"
}
```

- `objective` 在 N01 只能为 `diagnose`；字段保留是为了与已冻结 `blueprint_intents` 对齐。
- `entry_point/direction/domain/objective` 是将来 Compiler 生成 `blueprint_intents` 的权威来源，不能和任何 Node 的入口标记相矛盾。
- Version 的 `diagnostic_target_signature` 必须逐字等于其 Logical Model 的 signature；服务和数据库复合 FK/trigger 都要拒绝不匹配。换目标必须新建 Logical Model，不能为同一 Model 创建不同目标的 Version。
- 版本至少有一个 `entry_point=true` 的 Node，且该节点的 key、实体类型与 `diagnostic_target` 一致。首版要求恰好一个入口节点，且它必须是 `observable`。

### 2.3 与已落地 Case A Schema 的映射

T04 已有 `causal_models`、`causal_model_versions`、节点/边/规则/数据绑定/能力绑定、适用范围、不可变 Snapshot 和 validation run。N01A 复用这些表的聚合关系，不复制 Case A 的 Fixture 导入表或字段。

| 现有对象/字段 | N01A 用法或调整 |
|---|---|
| `causal_models` | 保持 Logical Model 身份；新增 `diagnostic_target_signature` 与 runtime `active_model_version_id/active_snapshot_id`，名称在 `(tenant_id, data_domain_id)` 内唯一。 |
| `causal_model_versions` | 扩展状态机、诊断目标/签名、创建/修改者、乐观锁版本；`published_snapshot_id` 继续是该治理发布 Version 的不可变 Snapshot 指针，而不是 runtime active 的替代品。 |
| `causal_nodes` / `causal_edges` / `causal_rules` | 保持 tenant-scoped 复合引用；N01A 增加服务层/DB guard，禁止非 Draft 写入。 |
| `causal_data_bindings` / `causal_capability_bindings` | 作为 Evidence Requirement 和逻辑能力绑定的存储投影；N01A 明确 schema 与受控目录解析规则。 |
| `causal_applicability` | 版本的适用范围；发布时序列化到 `applicability_snapshot`。 |
| `causal_model_snapshots` | 继续只插入；Snapshot 的 hash 覆盖完整发布语义。 |
| `causal_snapshot_validation_runs` | 保留为 Snapshot 校验记录；N01A 另增 Draft 校验记录，避免伪造尚未发布的 Snapshot。 |

Case A 的 `testing` Version 和 `published_fixture` 是测试导入边界，不是生产审批状态。它们必须继续可被现有测试消费，但不进入 N01A 的提交审核/正式发布 API。

---

## 3. 生命周期、编译与激活状态机

### 3.1 三个独立状态面

N01A 不用一个“已发布”状态同时表达治理、编译和运行时可用性。对外状态必须由以下三个事实源组合，任何字段都不能冒充另一个：

| 状态面 | 权威对象/字段 | 值 | 说明 |
|---|---|---|---|
| Governance | `CausalModelVersion.status` | `draft`、`in_review`、`published`、`superseded`、`archived` | 业务内容是否通过审核并拥有 Snapshot。 |
| Compile | 已有 `blueprint_compile_records` append-only Attempt | `running`、`success`、`failed` | 每个 Attempt 终态不可复活；`success` 必须同时持有不可变 Candidate Artifact；不存在 `pending`。 |
| Delivery | outbox delivery record | `pending_delivery`、`queued`、`delivered`、`retrying`、`dead_letter` | 发布/编译/激活事件的投递状态；不属于 CompileRecord。 |
| Activation | `causal_models.active_model_version_id/active_snapshot_id` | `inactive` 或 `active`（由指针是否精确指向此 Version/Snapshot 导出） | 唯一运行时选择权威；不新建第二套 Activation Job 表。 |

`published` 仅表示**治理发布**，可以是 inactive；一个 Logical Model 在升级期间可有多个 Published Version，但至多一个 Active Version。`superseded` 只在另一个 Version 成功 activation 后产生。`archived` 是因果源模型的统一下线术语；`withdrawn` 只属于已冻结 Planning Blueprint Version，二者不得混用。

对外 API 必须同时返回原始状态面和唯一派生的 `runtime_readiness`，不得把 delivery 状态伪装为 CompileRecord 状态：

```json
{
  "governance_status": "published",
  "compile_record": {"id": "cr-…", "status": "running"},
  "delivery_status": "delivered",
  "activation_status": "inactive",
  "runtime_readiness": "compiling"
}
```

`runtime_readiness` 只能为：`active`、`compile_delivery_pending`、`compiling`、`compile_failed`、`ready_to_activate`、`not_activated`。它是由前四项确定性派生的展示/调用结果，不是新的持久化 Job 状态；在 `last_known_good` 模式下，Logical Model 有 active 指针时 `runtime_readiness=active`，同时在 `candidate` 字段暴露新版本的 delivery/compile/activation 进度。

为兼容 Case A，保留 `testing` 与 legacy `deprecated`：`testing` 仅 Fixture/import 使用；能安全判断为历史终态的 `deprecated` 迁移为 `archived`，不能安全映射的记录保留只读 `deprecated` 并写 migration report。新 N01A API 不创建或转换这两种 legacy 状态。

### 3.2 治理发布、编译、激活与归档

```text
draft ──submit──> in_review ──governance publish──> published + inactive
  │                    │                                 │
  ├──validate──> draft └──reject──> draft                ├──CompileRecord running → success|failed
  └──archive──> archived                                 │                 │
                                                        success              failed
                                                          │                   │
                                                    activation tx             └─ retry compile / keep last-known-good active
                                                          │
                    old active published ──> superseded  +  new published ──> active

任何只读状态 ──clone──> 新 draft
```

| 命令 | 前置条件 | 原子结果 |
|---|---|---|
| `submit_review` | `draft`、`write_draft`、阻断校验为零。 | `in_review`，写 Review/audit，递增 revision。 |
| `reject` | `in_review`、`review`、必须理由。 | 回 `draft`，保留内容，写 Review/audit，递增 revision。 |
| `publish` | `in_review`、`review`、final validation/目录解析均通过。 | 创建 immutable Snapshot，Version→`published` + `inactive`，写 Review/audit/outbox，递增 revision；**不**改变旧 active Version 或 runtime pointer。 |
| `compile` | `published`、`compile`。 | 新建 append-only CompileRecord Attempt；仅该 Attempt 可 `running → success|failed`。failed retry 必须新建 Attempt 并以 `retry_of_compile_id` 指向失败 Attempt，绝不 `failed → running` 原地复活。success 原子写入完整 Candidate Artifact JSON/hash/schema version，尚未成为 runtime Blueprint。 |
| `activate` | **显式请求**提供 `model_version_id + compile_record_id + expected_active_model_version_id + expected_active_snapshot_id`；后两者在无 active 时显式为 `null`。Version/Record/Model/Snapshot 精确关联，Version=`published`、Record=`success`、artifact/hash/目录仍合法；调用者有 `activate`。 | 在锁内对 active pointers 做 CAS；不匹配即 `409 ACTIVE_VERSION_CHANGED`、不切换。匹配时只从该 Record Artifact 物化 Blueprint，并在一个事务内切换 current Blueprint、`CausalModel.active_*` 指针、旧 active Version→`superseded`，写 audit/outbox；所有涉及 Version 状态变更递增 revision。Phase 1 不自动激活、不扫描或猜测 candidate。 |
| `archive` | `review`。 | 非 active Version：Version→`archived`。Active Version：在同一事务清空 active pointers、Version→`archived`、其 Source 对应 current Blueprint `compiled→withdrawn`；不得自动回退到旧 Version。均写 audit/outbox、递增 revision。 |
| `clone` | `read` + `write_draft`。 | 建新 `draft`，复制语义内容与 derived-from，绝不复制 Snapshot/Review/Blueprint；新 Version revision 从 1 开始。 |

默认 activation policy 为 `last_known_good`：新 Version 已 published 但 compile-request delivery 为 `pending_delivery/queued`、或 CompileRecord 为 `running/failed` 时，Discovery 继续选择现有 Active Version 的 Snapshot/Blueprint。若 Model 尚无 Active Version，返回可诊断的“无可用激活版本”。未来 `fail_closed` safety profile 可以在存在一个更新的 Published-but-inactive Version 时暂时拒绝新诊断，但仍不改写 active pointer；这项 profile 不在 N01 Phase-1 启用范围。

### 3.3 Activation 原子事务与 Discovery gate

当前 Blueprint v1.0 每个 Logical Blueprint 至多一条 `compiled` Version。为保持 last-known-good，N01A Compiler 在 activation 前只把候选 IR 写入**已有** CompileRecord；不提前把候选写为 `planning_blueprint_versions.status='compiled'`，也不 supersede 旧 Blueprint。CompileRecord 从 `running → success` 的同一事务必须写入：

```text
compiled_artifact_json       完整规范化 Blueprint IR
compiled_artifact_hash       对该 IR 的 canonical SHA-256
artifact_schema_version      Artifact 合同版本
```

Artifact 是完整 Blueprint IR，而不是局部 compiler log：必须包含 materialize 所需的每个 Source Model identity/version 与 Source Snapshot pin/content hash（这些字段将物化为 `BlueprintSource`）、intent、goal skeleton、constraints、output contract、fallback policy、pinned StepType/handler identities、steps、dependencies、step sources、capability requirements及其 schema versions 等所有能决定 Blueprint 语义的内容。它只覆盖**纯、可 materialize 的 IR**，排除 compiler version/config、CompileRecord 的 build-request identity、请求幂等键，以及不直接物化的 provenance/聚合 `source_model_hashes` bookkeeping、runtime task/observation、Provider readiness/物理 binding、数据库 row ID、时间戳、审计/outbox、active pointer 和其他非语义字段。Compiler version/config、build-request identity 与 provenance bookkeeping 保留在 CompileRecord（现有 `compiler_version/compiler_config/input_snapshot/source_model_hashes` 等字段），不参与 `compiled_artifact_hash`。`success` 没有三项完整且 hash 验证通过即为数据库约束违例；`failed` 不得持有可激活 Artifact。Artifact 的 canonicalization 与版本化 schema 必须由 Compiler 和 Activation 共享单一实现。

Phase 1 的 Activation Coordinator 不自动运行，也不从多条 Published inactive Candidate 中扫描选择。调用者必须显式提交 `model_version_id + compile_record_id`；旧 success Candidate 可保留，日后选择它必须再次使用其精确 ID 显式发起并留下审计。Coordinator 锁定 Logical Model、指定 candidate/old Version、指定 CompileRecord 和旧 current Blueprint，并在单一事务内：

1. 验证 request 的 Version/Record/Model/Snapshot 精确关联，Version=`published`、Record=`success`、Artifact schema/hash/目录与 Snapshot 仍有效；
2. 在 Logical Model 锁内比较 `expected_active_model_version_id/expected_active_snapshot_id` 与当前 active pointers（无 active 时两个 expected 均必须显式 `null`）；任一不一致立即 `409 ACTIVE_VERSION_CHANGED`，不物化、不切换；
3. **只**读取 `compiled_artifact_json`，校验 `compiled_artifact_hash`，严禁重新运行 Compiler 或按 live Model 重建 IR；
4. 将旧 current Blueprint `compiled → superseded`，从该 Artifact materialize candidate BlueprintVersion/子表为 `compiled`；
5. 以 materialized Blueprint 的规范化 projection 重算 artifact hash，并要求严格等于 CompileRecord hash；同时 BlueprintVersion 记录 `compiled_artifact_hash`（及 schema version）；不等则事务失败；
6. 更新 `causal_models.active_model_version_id/active_snapshot_id`，将旧 active CausalModelVersion `published → superseded`，保留其 Snapshot/Trace；
7. 写 artifact hash、CompileRecord ID、expected/actual 旧 active pointers、旧/新 Blueprint ID 的 activation audit，并创建 outbox cache-invalidation/notification 记录；所有 Version 状态修改递增 revision。

强不变式：每条由 N01A activation 创建的 BlueprintVersion 都必须记录并可验证与其 CompileRecord **完全相同**的 `compiled_artifact_hash`；从其 materialized projection canonicalize 的 hash 也必须严格相等。任一步失败，整个 activation transaction 回滚：旧 active pointer 与旧 compiled Blueprint 继续服务，candidate 保持 Published+inactive，CompileRecord/Artifact 保持 success 且不可变，可安全以相同显式 ID 和最新 expected pointers 重试 activation。CAS 不匹配不写任何业务状态；调用者刷新后若仍要激活旧 Candidate，必须带刷新后的 expected pointers 再次明确操作并留审计。Outbox 失败只使 delivery record 处于 `pending_delivery/retrying`，不回滚已提交 activation；同步 Discovery 使用 DB pointer，不依赖事件正确性。

所有 Discovery 必须在同一个 tenant-scoped 查询/服务操作中验证：

```text
CausalModel.active_model_version_id = CausalModelVersion.model_version_id
AND CausalModel.active_snapshot_id = SourceSnapshot.snapshot_id
AND CausalModelVersion.status = published
AND CausalModelVersion.published_snapshot_id = SourceSnapshot.snapshot_id
AND SourceSnapshot.content_hash = BlueprintSource.source_content_hash
AND SourceSnapshot 有 passed validation run
AND BlueprintVersion.status = compiled
AND BlueprintSource 精确 pin 同一 tenant/model version/snapshot/hash
```

只有满足以上条件的 Blueprint 才可用于新诊断。Trace/replay 按历史 pin 读取，不执行 active gate，也不因 activation/supersede 改变。Discovery 没有 Active Version 时，按调用者权限返回：`MODEL_COMPILE_DELIVERY_PENDING`（delivery=`pending_delivery|queued`、尚未有 CompileRecord）、`MODEL_COMPILING`（被用户选择/最近请求的 CompileRecord=`running`）、`MODEL_COMPILE_FAILED`（被用户选择/最近请求的 CompileRecord=`failed`）或 `MODEL_NOT_ACTIVATED`（有 success Artifact 但尚未被显式 activate/没有 candidate）。无读取权限时返回通用无候选结果。绝不以 Draft、inactive Published candidate 或 superseded Version作为隐式回退。

### 3.4 冻结架构的 Implementation Erratum

Planning Blueprint L3 v1.0 的原始文字曾将 CompileRecord 描述为 `success|failed`，而 N01A 的 `0040_n01_causal_model_management` 以 `running → success|failed` 作为权威数据库契约。该冲突已由 [Planning Blueprint L3 — N01A Implementation Erratum](2026-08-30-planning-blueprint-l3-implementation-erratum-n01a.md) v1.0 正式收口，其冻结内容为：

- CompileRecord 是现有唯一 Build Job，状态为 `running/success/failed`；`pending_delivery/queued` 是 outbox delivery，不能写进 CompileRecord。
- CompileRecord 是 append-only Attempt；failed retry 新建 lineage Attempt，不能把 failed 原地复活为 running。
- Candidate 编译成功与 runtime activation 是不同事实；success 必须冻结纯 IR Artifact JSON/hash/schema，Activation 不引入第二张 CompileJob 表，也不暗改 Blueprint v1.0 的 Version 表状态集。
- 对带 last-known-good 的因果模型，Blueprint current-version 切换必须在带 active-pointer CAS 的 activation transaction 中从指定 Artifact 物化发生，而不是 Candidate CompileRecord 一成功就切换或重新编译。

该 Erratum 是本详细设计的配套实施契约；本 N01A 设计不直接改写原冻结 L3 文档或现有 migration。

### 3.5 可验证状态、权限、不可变性与恢复

未列出的命令一律 `409 INVALID_STATE_TRANSITION`。所有状态转换（submit/reject/publish/supersede/archive）均递增该 Version revision 并追加 Review/audit。

| Governance / Activation | 可执行命令与权限 | 不可变性与恢复 |
|---|---|---|
| `draft` | `write_draft`：CRUD/validate/submit/clone；`review`：archive。 | 仅此状态可改语义；写失败原子回滚，ETag/幂等冲突 409。 |
| `in_review` | `review`：reject/publish/archive；`read`：查看/clone。 | 内容锁定；publish 失败保持 in_review 且无半成品 Snapshot。 |
| `published + inactive` | `compile`、显式 `activate(model_version_id, compile_record_id)`、`review`：archive、`read`：clone。 | Snapshot/内容只读。compile failed 不回滚发布；success Artifact 不可变，activation failed 只能以相同显式 Artifact 重试。 |
| `published + active` | `read`、`compile`（新 Candidate）、`review`：archive。 | 内容/Snapshot 只读；last_known_good 默认继续服务，只有 activation transaction 才能被替换。archive 会同时 withdraw 对应 current Blueprint；归档是本期唯一的运行时下线操作。 |
| `superseded` / `archived` | `read/audit.read`、`write_draft`：clone；`review`：archive（仅 superseded）。 | 永远只读且历史可追溯；不能原地重新发布/激活，恢复只能 clone→review→publish→compile→activate。 |
| `testing` / legacy `deprecated` | 仅 Case A fixture/import 与只读。 | N01A 不编辑或转换；兼容迁移按 §9。 |

归档 Active Version 的服务端事务还必须锁定并验证 current Blueprint 的 `blueprint_source_models` 精确 pin 该 active `(tenant, model_version_id, snapshot_id, content_hash)`；随后在同一事务中清空 active pointers、将源 Version 设为 `archived`、该 Blueprint `compiled → withdrawn`，并写 audit/outbox。若找不到精确对应的 current Blueprint、其状态非 `compiled` 或任一写入失败，整个事务回滚，旧 active 保持服务；Discovery 的 active gate 是正确性兜底，outbox 仅用于缓存清理和通知。

---

## 4. RBAC、租户隔离与审计

### 4.1 可配置角色权限

不新增硬编码“建模者/审核者”角色。复用 `roles.permissions`，由租户管理员将以下 permission strings 赋予任意角色：

| 权限 | 允许动作 |
|---|---|
| `ecmc.causal_model.read` | 读取模型、版本、校验报告及可见目录。 |
| `ecmc.causal_model.write_draft` | 创建、复制、更新、删除 Draft 内容；提交审核。 |
| `ecmc.causal_model.review` | 查看 in_review、驳回、批准/发布、归档、下线。 |
| `ecmc.causal_model.compile` | 对已发布 Snapshot 显式触发/重试编译；不等于发布权限。 |
| `ecmc.causal_model.activate` | 对指定 CompileRecord 成功 Artifact 的 Published candidate 显式激活；Phase 1 不提供自动 activation service。 |
| `ecmc.catalog.read` | 浏览可被引用的目录。 |
| `ecmc.catalog.request` | 创建和取消自身目录扩展申请。 |
| `ecmc.catalog.approve` | 审核目录扩展申请；具体条目仍由对应 Ontology/Capability 管理服务创建。 |
| `ecmc.causal_model.audit.read` | 读取完整治理、发布、校验与编译审计。 |

`is_admin` 可作为现有通用兜底，但服务仍应检查 tenant 和数据域范围。对于非管理员，模型所在 `data_domain_id` 必须属于 `role_domain_access` 返回的允许集合；未知角色或空范围均 fail closed。

### 4.2 RLS 与服务层规则

- 所有新增 tenant-owned 表都有 `tenant_id`，启用 `ENABLE/FORCE ROW LEVEL SECURITY`，使用 `tenant_session()` / `SET LOCAL earp.tenant_id`。
- 所有 parent-child 关联使用 `(tenant_id, parent_id)` 复合 FK；禁止以裸 `model_version_id`、`snapshot_id` 或 `catalog_id` 建跨租户引用。
- Snapshot、Blueprint、Trace 的历史读取仍只允许所属租户；`audit.read` 不越过 RLS。
- HTTP route 只做身份提取和薄验证；授权、状态转换、canonicalization、事务和审计必须在 domain service 中完成。
- `audit.read` 只授权读取既有审计记录；任何会追加审计的业务命令（Draft 写入、validate、submit/reject/publish、compile、目录申请/审批）必须先通过它各自的写入/审核权限，不能以 audit.read 单独写入审计。

### 4.3 审计事件

每次状态转换、Draft 写入、目录申请、校验、发布、编译触发/完成必须向既有 `audit_logs` 写追加事件。至少记录：

```json
{
  "event_type": "causal_model.version_published",
  "tenant_id": "...",
  "entity_type": "causal_model_version",
  "entity_id": "...",
  "actor_user_id": "...",
  "actor_role_id": "...",
  "correlation_id": "...",
  "before_status": "in_review",
  "after_status": "published",
  "snapshot_id": "...",
  "content_hash": "...",
  "validation_run_id": "...",
  "review_id": "..."
}
```

审计只保存必要的引用、hash、状态与脱敏理由，不保存 Provider credential、端点、原始业务数据或未经授权的目录内容。

---

## 5. 受控目录与目录扩展申请

### 5.1 为什么不能自由填写可执行字段

Evidence Requirement 会生成真实取证任务。若自由填写实体、指标、能力或参数，发布后可能出现不可解析对象、指标/单位语义漂移、错误目标绑定、无法定位 Provider，甚至将界面退化为暴露 SQL/接口配置的安全风险。因此，模型服务接受的可执行字段一律为已解析的受控引用，不能接受自由文本 ID 或任意 JSON DSL。

### 5.2 目录分类与引用规则

| 类别 | 权威来源 / N01A 策略 | 模型可引用字段 |
|---|---|---|
| Data Domain、Entity Type、Relation Type | 复用既有 Ontology；状态必须 `active`。 | node `entity_type_ref`、edge `relation_type_ref`、applicability。 |
| Metric / Unit / Aggregation | 现有 Ontology `entity_types.kind='metric'` 可承载概念，但 N01A 需要显式指标目录投影，包含 unit、允许 aggregation、值类型、时间语义和状态。 | `metric_ref`、`unit_ref`、`aggregation_ref`。 |
| Time Window Schema | 版本化受控时间窗口 schema，定义诊断目标和 Evidence 所用时间语义与输入约束。 | `diagnostic_target.time_window_schema_ref`、Evidence `time_window_ref`。 |
| Binding Template | 新增版本化受控模板目录，例如 `context_entity/v1`、`outbound_relation/v1`；每个模板有输入 schema、允许 source/target 类型和解析器版本。 | `instance_binding_template_ref` + schema-validated params。 |
| Logical Capability Contract | 新增/对接逻辑合同目录，定义输入输出 schema、read-only 语义、状态与兼容版本；绝不是 `business_capabilities.capability_id` 或 Provider 参数。 | `capability_contract_ref`。 |
| Rule Schema | 平台维护的 `predicate` / `threshold` / `direction_rule` JSON Schema 版本。 | `rule_type` + `rule_schema_version` + `rule_spec`。 |

目录选择 API 返回稳定 ref、展示名、版本、状态和可选项；服务端在写入和发布时再次解析，不信任客户端提交的显示名称。`deprecated` 条目只允许历史读取，不能被新 Draft 引用；条目在被 Published Snapshot 引用后不能物理删除。

在不预先锁死 Ontology、Metrics 或 Capability Catalog 的实现归属前，N01A 冻结统一的 `CatalogResolver` 契约：

```text
resolve(tenant_id, CatalogRef, expected_kind, at_version?)
  -> ResolvedCatalogRef | CatalogResolutionError

validate(tenant_id, [CatalogRef], context)
  -> [ValidationIssue]  # 必须包含 ref、kind、resolved version/hash、active 状态与上下文兼容性
```

`CatalogRef` 的传输与 Snapshot 形式固定为 `{kind, stable_id, version}`；`ResolvedCatalogRef` 额外返回 `{content_hash, status, data_domain_id, semantic_schema_version, input_schema?, output_schema?}`。调用者只能保存原始 Ref 与发布时解析得到的 version/hash，不能直接依赖底层表主键、Provider ID 或目录服务内部实现。`CatalogResolutionError` 的完整、唯一枚举以及 fail-closed 语义以 [CatalogResolver / Fixture Boundary Contract](2026-08-30-n01a-catalog-resolver-and-fixture-boundary.md) v1.0 为权威，本设计不再复制维护。所有模型写入、final validation 和 Snapshot 生成均必须通过该契约；CatalogResolver 的具体模块归属由实施 PRD 决定。

### 5.3 CatalogChangeRequest

当建模者找不到目录项时，可提出申请，不能绕过目录：

```text
draft（申请人编辑） → submitted → approved_pending_fulfillment → fulfilled
                                      │                   │
                                      │                   └→ fulfillment_failed（可重试）
                                      └→ rejected | cancelled

approved_pending_fulfillment / fulfillment_failed
  → 权威目录服务成功创建并激活版本化条目
  → fulfilled（返回新的 stable ref，才可被模型选择）
```

申请字段至少包括：`request_id`、`tenant_id`、`request_type`、`proposed_definition`、`rationale`、`target_data_domain_id`、`status`、申请/审核人和时间、`resolved_catalog_ref`、`fulfillment_attempts`、`last_fulfillment_error`。`proposed_definition` 只能描述候选业务语义，不能含 SQL、凭据、URL、Provider endpoint 或执行代码。

目录申请和因果模型审批可由同一用户承担，取决于租户角色授权；但“批准申请”不等于“将任意 payload 直接写入 Ontology/Capability Registry”。批准只把申请置为 `approved_pending_fulfillment`，然后由权威目录服务在自己的事务内创建并激活版本化条目。只有目录服务成功返回 active stable ref 后，申请才原子更新为 `fulfilled`；此前目录查询不得返回它，模型服务不得接受它作为引用。服务失败则保存脱敏错误、置为 `fulfillment_failed` 并允许具备 `catalog.approve` 的人员重试；不允许显示为 fulfilled，也不允许任何模型引用该候选项。

---

## 6. Draft 内容与 API 合同

### 6.1 API 资源

HTTP 仅是传输层参考实现，服务契约才是权威。所有写请求均要求 `Idempotency-Key`；更新/状态转换还要求 `If-Match`（Draft revision/ETag）。

| 方法 | 路径 | 权限 | 语义 |
|---|---|---|---|
| `GET` | `/v1/ecmc/causal-models` | read | 仅列出调用者数据域可见的模型，可按状态/域过滤。 |
| `POST` | `/v1/ecmc/causal-models` | write_draft | 创建 Logical Model 与其第一个 Draft Version。 |
| `GET` | `/v1/ecmc/causal-models/{model_id}` | read | 返回模型元信息、active pointer、版本摘要，以及 governance/compile/delivery/activation 四个状态面。 |
| `GET` | `/v1/ecmc/causal-models/{model_id}/versions/{version_id}` | read | 返回指定版本内容；已发布版本返回 Snapshot 引用和只读投影。 |
| `POST` | `/.../versions` | write_draft | 从空白或指定历史 Version 复制创建 Draft。 |
| `PATCH` | `/.../versions/{version_id}` | write_draft | 更新 Draft 的元数据、适用范围；诊断目标必须保持与 Logical Model signature 一致，换目标拒绝并要求新建 Model。 |
| `PUT` | `/.../nodes/{node_key}` | write_draft | upsert 一个 Draft Node；服务端解析受控引用。 |
| `DELETE` | `/.../nodes/{node_key}` | write_draft | 删除 Node；若有边/规则/需求引用则 409，要求先显式删除依赖。 |
| `PUT/DELETE` | `/.../edges/{edge_key}` | write_draft | 维护 Draft Edge；不得创建自环。 |
| `PUT/DELETE` | `/.../rules/{rule_key}` | write_draft | 维护规则。 |
| `PUT/DELETE` | `/.../evidence-requirements/{node_key}/{requirement_key}` | write_draft | 维护 DataBinding 及其 Contract Binding。 |
| `POST` | `/.../validate` | write_draft | 运行 Draft 校验并创建追加式 Draft Validation Run，不改变状态；可选 `mode=full|incremental`。 |
| `POST` | `/.../submit-review` | write_draft | 最终 full validation 成功后提交审核。 |
| `POST` | `/.../reject` | review | 驳回至 Draft，必须包含说明。 |
| `POST` | `/.../publish` | review | 最终校验、Snapshot 与**治理发布**事务；返回 inactive candidate，不激活 runtime。 |
| `POST` | `/.../archive` | review | 归档，不删除历史。 |
| `POST` | `/.../compile` | compile | 对 Published Snapshot 发起 CompileRecord Attempt；`retry_of_compile_id` 只能指向 failed Attempt，重试总是新 Attempt。 |
| `POST` | `/.../activate` | activate | Body 必须提供 `model_version_id`、`compile_record_id`、`expected_active_model_version_id`、`expected_active_snapshot_id`（无 active 显式 null）；仅从该 success Artifact 原子物化并激活，不执行自动选择或重新编译。 |
| `GET` | `/.../governance` | audit.read | 读取 review/validation/audit/compile 摘要。 |
| `GET/POST` | `/v1/ecmc/catalog-change-requests` | catalog.read / catalog.request | 查看/创建目录扩展申请。 |
| `POST` | `/v1/ecmc/catalog-change-requests/{id}/approve|reject` | catalog.approve | 处理申请；批准后由目录服务创建条目。 |
| `POST` | `/v1/ecmc/catalog-change-requests/{id}/cancel` | catalog.request | 申请人仅可取消自己的 `draft`/`submitted` 申请。 |
| `POST` | `/v1/ecmc/catalog-change-requests/{id}/retry-fulfillment` | catalog.approve | 仅可重试 `fulfillment_failed` 申请；新建履约 attempt，不覆盖旧错误。 |

N01B 使用这些接口实现侧栏、校验面板和发布确认页；前端不直接写基础表，也不自行计算发布 hash。

对有 `audit.read` 的调用者，版本/治理响应必须展示 Candidate Artifact 的可验证摘要，而不是仅显示“编译成功”：

```json
{
  "model_version_id": "cmv-…",
  "compile_record": {
    "compile_record_id": "cr-…",
    "status": "success",
    "artifact_schema_version": "blueprint-ir/v1",
    "compiled_artifact_hash": "<64-char-sha256-hex>",
    "artifact_ready": true
  },
  "activation": {"status": "inactive", "activation_mode": "explicit"}
}
```

激活成功的 audit/event 至少记录 `model_version_id`、`compile_record_id`、`compiled_artifact_hash`、旧/新 active snapshot、旧/新 BlueprintVersion 与 actor/role/correlation ID。Artifact JSON 本体通过审计授权的只读端点或数据库审计对象读取，不复制进每一条 event payload。

编译与激活请求的关键负载如下：

```json
{
  "compile": {"idempotency_key": "…", "retry_of_compile_id": "cr-failed-…"},
  "activate": {
    "model_version_id": "cmv-candidate-…",
    "compile_record_id": "cr-success-…",
    "expected_active_model_version_id": "cmv-current-…",
    "expected_active_snapshot_id": "cms-current-…"
  }
}
```

首次激活/无 active 的 Model 必须传两个 expected 字段为 `null`，不能省略。若锁内比较失败，响应为 `409 ACTIVE_VERSION_CHANGED`，包含当前 active pointers 和可安全展示的 revision；客户端刷新后只能以最新 pointers 显式重试。Compile 的幂等规则是：同一请求/`Idempotency-Key` 返回同一 Attempt；已有同一成功 Artifact 返回该 success Attempt；同一 build 正在运行返回该 running Attempt；只有显式 retry 一个 failed Attempt 才创建新 Attempt。

### 6.2 Draft 负载示例

```json
{
  "diagnostic_target": {
    "objective": "diagnose",
    "entry_point": "production_output",
    "direction": "down",
    "domain": "production",
    "target_entity_type_ref": "mine",
    "time_window_schema_ref": "daily_window/v1"
  },
  "node": {
    "node_key": "haulage_cycle_time",
    "entity_type_ref": "haulage_system",
    "entry_point": false,
    "business_name": "运输周期",
    "notes": "自由文本说明"
  },
  "evidence_requirement": {
    "requirement_key": "haulage_cycle_time_required",
    "requirement_level": "required",
    "metric_ref": "metric.haulage_cycle_time/v1",
    "unit_ref": "minute/v1",
    "aggregation_ref": "mean/v1",
    "instance_binding": {
      "template_ref": "outbound_relation/v1",
      "params": {"relation_type_ref": "has_subsystem", "target_entity_type_ref": "haulage_system"}
    },
    "capability_contracts": [
      {"ref": "contract.read_haulage_cycle/v1", "role": "primary"},
      {"ref": "contract.read_haulage_quality/v1", "role": "supporting"}
    ],
    "business_description": "用于判定运输环节是否恶化"
  }
}
```

`business_name`、`notes`、`business_description`、假设与 rationale 是允许的自由文本；其余 `*_ref` 及 `template_ref` 必须按 §5.2 的 `CatalogResolver` 在 active catalog 中解析。每个 Evidence Requirement 必须恰好有一个 `role=primary` Contract，允许零到多个 `supporting` Contract；primary 失败不自动改选 supporting，未来 alternatives/failover 必须另立 Capability Resolution Policy。客户端不得传 `provider_id`、SQL、URL、token、任意 query text 或能力执行参数。

### 6.3 并发、幂等与错误

- Draft Version 有单调 `revision`；每个 `PATCH/PUT/DELETE/submit/publish/archive/activate` 必须匹配 `If-Match`。所有状态转换也递增 revision；不匹配返回 `409 VERSION_CONFLICT` 和当前 revision，不做静默 last-write-wins。
- `Idempotency-Key` 在 `(tenant_id, actor_id, operation, key)` 内唯一，保存请求 hash、响应状态和资源 ID。相同 key + 相同请求返回原响应；相同 key + 不同请求返回 `409 IDEMPOTENCY_KEY_REUSE`。
- `publish` 使用行级锁锁定目标 Version；Snapshot 插入、published pointer、Review/audit/outbox 必须同一事务提交，但绝不切换 active pointer 或 supersede 旧 active Version。同一 Draft 的两个提交/发布竞争时，只有一个可完成。
- `activate` 锁定 Logical Model、请求指定的 candidate/old Version、指定 CompileRecord 与当前 Blueprint；在锁内执行 expected active pointers 的 CAS，事务见 §3.3。一个 Model 至多一个 active pointer，不得产生两个 Active Version；服务不得扫描或推断要使用的 Candidate。
- CompileRecord 是 append-only Attempt。幂等请求返回同一 Attempt；成功 Artifact 可复用其 success Attempt，running 返回进行中 Attempt；`retry_of_compile_id` 只允许失败 Attempt，并创建新 Attempt lineage。outbox delivery 以独立 delivery idempotency 管理，模型服务不创造 `pending` CompileRecord 状态。

---

## 7. 校验设计

### 7.1 校验时机

| 时机 | 校验范围 | 是否改变状态 |
|---|---|---:|
| Draft 保存 | 局部 schema / 目录可解析性；允许图尚未完成。 | 否，仅内容写入递增 revision |
| 手工 Validate | 全量结构、图、语义、目录、适用范围校验。 | 否，新增 Draft Validation Run |
| Submit review | 重新全量校验；存在阻断项即拒绝。 | 成功才进 `in_review` |
| Publish | 在事务中对锁定内容重跑 final validation，并验证目录活动状态。 | 成功才生成 Snapshot / governance `published + inactive` |
| Compiler | 使用已通过验证的 immutable Snapshot，执行 Blueprint 专属校验。 | 仅 CompileRecord `running → success|failed`；不改 active pointer |
| Activate | 复核成功 Candidate、Snapshot、hash、目录版本与旧 active 指针。 | 成功才切换 runtime active / current Blueprint，失败完整回滚 |

Draft 校验结果与 Snapshot 校验结果必须分开保存。Draft 没有 Snapshot ID，不能借用 `causal_snapshot_validation_runs` 伪称已发布验证；建议新增 `causal_model_validation_runs`，其中存 `model_version_id`、`draft_revision`、`input_hash`、`validator_version`、`result`、issues、执行人/时间。只有 `write_draft` 可发起并写入该 Validation Run；具有 `read`/`audit.read` 的用户只能读取其结果，不能借“查看校验”权限制造新审计记录。

### 7.2 阻断项与警告

本节的 Validation 只回答“模型内容是否有效”。权限与资源可见性由 Command Guard 在校验前分别以 `403/404` 处理；非法状态、ETag/revision 冲突和幂等 key 冲突由 Command Guard 以相应 `409` 处理。它们不得写入 `ValidationResult`，也不得由 N01B 作为图或表单校验问题展示。

| 类别 | 阻断发布（error） | 警告（warning，不阻断） |
|---|---|---|
| 目标 | 目标缺失、objective 非 diagnose、入口 Node 非唯一或与目标不一致。 | 描述/业务名称为空。 |
| 图结构 | 对 N01 Phase-1 + `sign_propagation_v1`：自环、环、悬空 Node 引用、重复 key、Edge 自身或端点不存在。此为 authoring/publish validator，不是 DB 全局约束。 | 孤立但标注为 future/optional 的草稿节点；首版仍建议移除。 |
| 语义 | Edge effect 非 `+/-`、strength/confidence 超范围、Relation Type 不适配源/目标类型。 | 低 confidence/过长 lag，提示领域复核。 |
| 可观测性/证据 | 入口不是 `observable`、入口缺 Profile 要求的直接 Evidence、Evidence 缺 metric/unit/aggregation、每项没有恰好一个 primary Contract、required/optional 非法。`indirectly_observable` 和 `latent_hypothesis` 不因无直接 Evidence 自动阻断。 | indirect/latent 节点缺少推断 rationale 或可观测路径，提示领域复核。 |
| 实例绑定 | 模板不存在/非 active、params 不合 schema、关系类型或源/目标类型不匹配、无法从诊断目标静态证明可解析。 | binding 可解析但范围很宽，提示可能采集过多实体。 |
| 能力 | Capability Contract 不存在/非 active、不兼容输入输出 schema、声明非 read-only；primary 数量不是 1。 | supporting contract 即将 deprecated；Profile 不要求的 optional evidence。 |
| 规则/范围 | Rule schema 无效；Applicability 空、跨域或与目标实体类型冲突。 | 范围过窄或仅测试实体。 |
| 目录引用 | 目录项不存在、不活跃、跨数据域、kind 不匹配或 schema 不兼容；包括发布时已失效的引用。 | supporting contract 即将 deprecated。 |
| 兼容/编译 | Snapshot 内容 hash 不匹配、schema 不受支持。 | 编译预检提示 Blueprint 将 supersede 旧版本。 |

节点最小增加 `observability ∈ {observable, indirectly_observable, latent_hypothesis}`。入口必须 `observable`。`sign_propagation_v1` 的 Profile（而非通用 CRUD）定义哪些 observable Evidence 是 COMPLETE 所必需、哪些缺失导致 PARTIAL；`indirectly_observable` 仅可由已获证据路径推断，`latent_hypothesis` 只能作为明确标注的假设参与解释。首版对“无路径通向入口目标”的 Node/Edge 仍为阻断项，避免把不可参与诊断的业务逻辑发布进单目标模型。

### 7.3 标准错误结构

所有校验与状态转换返回稳定、可定位的 issue 结构，供 N01B 高亮节点、边或表单字段：

```json
{
  "code": "CAUSAL_BINDING_RELATION_TYPE_MISMATCH",
  "severity": "error",
  "message": "实例绑定模板的关系类型不能从 mine 解析到 haulage_system。",
  "location": {
    "resource_type": "evidence_requirement",
    "model_version_id": "cmv-...",
    "node_key": "haulage_cycle_time",
    "requirement_key": "haulage_cycle_time_required",
    "field": "instance_binding.params.relation_type_ref"
  },
  "expected": {"source_type": "mine", "target_type": "haulage_system"},
  "actual": {"relation_type_ref": "has_equipment_group"},
  "catalog_ref": "has_equipment_group",
  "help_action": "request_or_select_catalog_item"
}
```

顶层响应：

```json
{
  "validation_run_id": "...",
  "result": "failed",
  "input_revision": 12,
  "input_hash": "sha256:...",
  "validator_version": "n01a/v1",
  "summary": {"errors": 2, "warnings": 1},
  "issues": []
}
```

HTTP 状态约定：请求 schema 错误为 `422`，权限为 `403`，资源不可见为 `404`，状态/ETag/幂等冲突为 `409`，提交/发布被业务校验阻断为 `422`（带上述 validation result）。

Activation CAS 冲突使用同一错误合同：

```json
{
  "code": "ACTIVE_VERSION_CHANGED",
  "message": "当前 active 模型版本已在本次激活期间改变。",
  "expected": {"model_version_id": "cmv-old", "snapshot_id": "cms-old"},
  "actual": {"model_version_id": "cmv-new", "snapshot_id": "cms-new"},
  "current_model_revision": 27
}
```

它必须返回 HTTP `409`，且不得 materialize Blueprint、更新 active pointers 或写 activation audit；调用者刷新后以最新 pointers 显式决定是否继续激活同一 Candidate。

---

## 8. Canonical Hash、Snapshot 与 Compiler 集成

### 8.1 Canonical content hash

N01A 沿用 Case A PRD §6.1 的 canonical JSON 规范：UTF-8、`ensure_ascii=false`、key 排序、紧凑分隔符 `(',', ':')`，以 SHA-256 计算。Hash 采用字段白名单，避免实现把展示或治理字段意外纳入语义。

```text
**semantic 字段（必须纳入）**：snapshot_schema_version；logical model_id；model version semantic identifier；diagnostic_target + signature；algorithm profile/ref；normalized nodes（含 observability）/edges/rules；normalized Evidence Requirements + primary/supporting logical contracts；normalized applicability；每个 CatalogRef 的 kind/stable_id/version/resolved content_hash；binding/rule/semantic-contract schema versions。

**presentation 字段（明确排除）**：画布坐标、颜色、分组、折叠状态、UI layout、草稿注释展示顺序和纯展示标签。

**governance / runtime 字段（明确排除）**：created/updated/published/reviewed 时间，用户/角色、Review 理由、Draft revision、ETag、validation run ID、CompileRecord 状态/ID、outbox delivery、active pointer、Blueprint ID、审计 ID、数据库 row ID、自己的 content_hash。
```

除上述 semantic 白名单外一律不得纳入。这样同一语义内容在不同时间重新验证仍得到同一 hash，而目录项版本变化会产生不同 hash；展示和审批变化不会伪造新业务模型。

发布服务是 hash 的唯一计算者。客户端、UI 和导入脚本可显示或验证 hash，但不能要求服务接受自报 hash；若客户端提供预期 hash，用于并发确认，不匹配则返回 `409 CONTENT_CHANGED`。

### 8.1.1 Candidate Artifact canonical hash

`compiled_artifact_hash` 与 Causal Snapshot content hash 是不同身份：前者只冻结**纯、可 materialize 的**完整 Blueprint IR。它沿用同一 canonical JSON 算法，但 payload schema 为 `artifact_schema_version`，白名单必须覆盖：每个将 materialize 为 `BlueprintSource` 的 Source Model identity/version、Source Snapshot pin/content hash，以及 intent、goal skeleton、constraints、output contract、fallback policy、StepType version/handler identities、steps、dependencies、step sources、capability requirements及其 schema versions。它明确排除 compiler version/config、CompileRecord 的 build-request identity、请求幂等键与不直接物化的 provenance/聚合 `source_model_hashes` bookkeeping（这些保留于 CompileRecord build provenance）、运行时 Task/Observation、物理 Provider 解析、数据库生成 ID、审计/outbox、激活指针及 timestamps。

Compiler 在完成前先对规范化纯 IR 计算 hash，再在同一 `CompileRecord running → success` 事务写入 JSON/hash/schema version。Activation 只验证/读取该三元组；不得再调用 Compiler。Blueprint materializer 必须实现与 Artifact schema 相同的 projection canonicalizer，供 §3.3 的强不变式复算验证。

### 8.2 Snapshot 生成

在 publish transaction 内：

1. 按稳定 key 排序读取 Draft 子对象与已解析目录投影；
2. 执行 final validation；
3. 组装 `nodes_json`、`edges_json`、`rules_json`、`requirements_json`、`applicability_snapshot`；
4. 计算 hash 并插入 `causal_model_snapshots`；相同 `(tenant, model_version_id, content_hash)` 的重试只复用同一 Snapshot；
5. 写 passed Snapshot Validation Run；
6. 将 `causal_model_versions.published_snapshot_id` 设置为该 Snapshot；
7. 完成 Version→`published + inactive`、Review/audit/outbox；不修改 Logical Model active pointer，也不 supersede 旧 active Version。

Snapshot 不复制物理 Provider 状态，也不重新读取实时 ABox。Prepare 仍在运行时利用已 pin Snapshot、目标/时间窗口和 ABox 解析实例绑定，符合 Case A 的动态 Evidence Requirement 语义。

### 8.3 Compiler 与诊断消费

- 发布事件的 payload 必须含 `tenant_id`、`model_id`、`model_version_id`、`snapshot_id`、`content_hash`、`schema_version` 与 `correlation_id`；不得只发布 mutable Model ID。outbox delivery 单独表示 pending/queued/retry。
- Compiler 必须只接受该租户、Version=`published`、有 `passed` validation 的 immutable Snapshot；复用 CompileRecord `running → success|failed`。success 必须持有不可变完整 Artifact JSON/hash/schema，不能提前改变 current Blueprint 或 active pointer。
- Compiler 从 `diagnostic_target` 生成 Intent、Goal Skeleton、`knowledge_query → output`，把全部 Blueprint 语义冻结到 Artifact；Activation 再由 Artifact materializer 写入 `blueprint_source_models` 的 `snapshot_id + content_hash` pin。节点级 Evidence / Provider 不进入 Blueprint 静态子表。
- 默认 last-known-good 下，候选 delivery pending/queued、或 CompileRecord running/failed 时都继续使用旧 active Snapshot/Blueprint；只有 Activation Coordinator 的原子事务才 supersede 旧 Blueprint/Version 并切换 Discovery。没有 old active 才返回 §3.3 的可诊断 not-activated/compile 状态。
- 历史 Trace 继续通过自身 pin 保持可重放，不受 candidate、activation 或 supersede 影响。

---

## 9. 数据库迁移与历史兼容策略

N01A 实施从连续 Alembic revision `0040_n01_causal_model_management` 开始；不得重写既有迁移。`0040` 包含本任务需要的治理/模型 Version、Candidate Artifact、最小 relational outbox、目录/申请与审计增量；如因数据库变更策略必须拆分，后续 revision 仍以 `0040` 为父节点。

### 9.1 建议 Schema 增量

| 表/约束 | 变更 |
|---|---|
| `causal_models` | 新增不可变 `diagnostic_target_signature`，以及 nullable `active_model_version_id/active_snapshot_id`；以 tenant-scoped 复合 FK 保证指针属于同一 Model/Version/Snapshot。至多一个 active 由单行 Logical Model 指针天然保证。 |
| `causal_model_versions` | 扩展 status CHECK：新增 `in_review/superseded/archived`，保留 legacy `testing/deprecated`；新增 `diagnostic_target`、`diagnostic_target_signature`、`revision`、`created_by`、`updated_by`、`submitted_at/by`、`reviewed_at/by`、`derived_from_model_version_id`。**不**创建 `(tenant_id, model_id) WHERE status='published'` unique index，因为可存在 Published+inactive candidate；以复合 FK/trigger 强制 Version signature 等于 Logical Model signature。 |
| `causal_model_reviews` | 新增治理决定追加表：`review_id`、tenant/model/version、action、decision、reason、actor、policy snapshot、created_at；复合 FK。 |
| `causal_model_validation_runs` | 新增 Draft 校验追加表，持有 `draft_revision/input_hash/validator_version/result/issues/started/finished`。 |
| `causal_model_snapshots` | 不改不可变约束；记录 canonical payload schema/algorithm profile projection 时仅新增插入时必填列，不更新历史行。 |
| `blueprint_compile_records` | 保持既有 build provenance（`compiler_version/compiler_config/input_snapshot/source_model_hashes` 等）并新增 `compiled_artifact_json JSONB`、`compiled_artifact_hash VARCHAR(64)`、`artifact_schema_version VARCHAR(32)`、`retry_of_compile_id VARCHAR(64) NULL` tenant-scoped self-FK。它是 append-only Attempt：`status='success'` 时三 Artifact 字段必填且 hash 与纯 IR canonical JSON 相符；`failed/running` 不可标作可激活 Artifact；failed retry 只能 INSERT 新行且 `retry_of_compile_id` 指向 failed Attempt；触发器禁止终态 Attempt 回到 running、禁止 success 后更新 Artifact 或把 success 改写为别的 Artifact。 |
| `planning_blueprint_versions` | 新增 `compiled_artifact_hash`、`artifact_schema_version`；对 N01A activation 创建的 Version，二者必填并等于 `compile_record` 对应值。Materialized child rows 由服务复算 projection hash 验证。 |
| `metric_catalog_entries` | 新增指标/单位/聚合受控目录投影，或由专门 Metrics 域服务提供等价 API；必须有 version/status/data-domain/schemas。 |
| `entity_binding_templates` | 新增全局或 tenant-scoped、版本化、只读模板目录与 params schema、适配类型、resolver identity/hash。 |
| `logical_capability_contracts` | 新增逻辑合同目录；仅描述 read-only 输入输出语义，不能存 endpoint/credential/physical provider。 |
| `catalog_change_requests` | 新增申请、审核、resolved ref 和审计字段。 |
| `outbox_events` + `outbox_deliveries` | N01A 范围内建设最小 relational outbox：governance publish、compile request、activation、archive 事件与业务事务同写；delivery 表拥有独立 `pending_delivery/queued/...` 状态、attempt/error/lease/idempotency key，不能污染 CompileRecord。 |

子表 Draft-only 写保护可由 service 的 `WHERE status='draft' AND revision=:expected` 实现，并辅以 PostgreSQL trigger，防止脚本或未来 route 绕过；Snapshot 的现有 immutable trigger 保持不变。

### 9.2 数据迁移与回滚

1. 先部署新增列/表、读路径兼容逻辑和权限；尚未启用 N01A 写入口。
2. 对历史 `deprecated`：可由终态/历史引用安全判定者映射为 `archived`；无法安全判定者保留 read-only legacy `deprecated`，写入逐项 migration report。`testing` 保留原值且标记 `legacy_fixture=true` 或等价服务判定。
3. 为已有 Logical Model/Published Version回填 `diagnostic_target` 与 signature：仅当可从已有入口 Node/Blueprint Intent 唯一推导时回填；不能唯一推导者保留只读 legacy，并禁止新发布/重编译直到人工补齐。
4. 为每个可安全回填的 Logical Model，从其已有 current compiled Blueprint 的精确 Source Snapshot 推导并设置 active pointers；没有唯一候选则 pointers 保持 null，禁止 Discovery 猜测。不得把多 Published Version 静默转 superseded。
5. 后端发布后才启用 UI；回滚时停止新 API 写入，但**不删除**新增 Snapshot、Review、Validation、CompileRecord Artifact、outbox 或 Blueprint 历史。数据库结构如需 down migration，只允许在未有生产 N01A 数据的部署窗口执行。

Case A Fixture 导入继续走其专用 `testing` 路径，保持包 hash、`published_fixture` 和 45 项验收测试语义不变。N01A 不重新解释或升级该 Fixture 为生产审核发布。

---

## 10. N01A/N01B 与后续任务的边界

| 范围 | N01A | N01B | N02 / N03 |
|---|---|---|---|
| 模型版本、状态机、RBAC、受控目录、校验、Snapshot、Compile / Activate API | 实现权威服务与测试。 | 只消费。 | 只读消费。 |
| 节点/边/证据编辑 | 提供 CRUD/校验语义。 | 图画布、表单、冲突与错误定位体验。 | 不编辑。 |
| 治理发布 / runtime activation | 服务原子事务、审计与状态面。 | 发布确认、候选/激活状态展示。 | 显示 active 模型/Blueprint 版本。 |
| 取证 Provider | 只引用逻辑 Capability Contract。 | 不暴露连接参数。 | N03 解析并接入物理 Provider。 |
| 诊断与结果 | 不实现。 | 不实现。 | N02 发起、状态/结果/Trace UI。 |

N01B 必须使用服务返回的 `validation issues.location` 精确高亮图元素；UI 的草稿自动保存要传 ETag 和 idempotency key；其任何 UI layout、颜色、节点位置只能作为非语义 Draft presentation 元数据，禁止进入 Snapshot content hash。

---

## 11. 验收测试矩阵

| 层级 | 场景 | 通过标准 |
|---|---|---|
| Schema / migration | `0040` 新状态、active pointer 复合 FK、signature 一致性、CompileRecord Artifact 不可变、append-only retry lineage、Blueprint artifact hash、最小 relational outbox、RLS、历史 Case A 数据升级 | PostgreSQL migration up/down（受控窗口）、跨租户读写/引用失败；一个 Model 至多一个 active、可有多个 Published+inactive；success Artifact 必填且不可改，failed 不可原地变 running。 |
| RBAC | 建模者可编辑不能发布/activate；审核者可治理发布；显式 activation 角色可激活；无域权限不可见；开发 tenant self-approval policy | 403/404 fail closed；Phase 1 无自动 activation service；审计包含 actor/role/policy。 |
| CRUD / concurrency | Draft 创建、复制、节点/边/需求维护、非 Draft 修改、ETag 冲突、幂等重放 | 仅 Draft 可改；同 key 同请求返回同结果；并发只一方成功。 |
| Catalog | 有效目录引用、deprecated/missing ref、错误 relation type、目录扩展申请审批与履约失败 | 未激活/不兼容项阻断；approve 后先为 `approved_pending_fulfillment`；权威目录服务成功创建并 active 后才 `fulfilled` 且可选择；服务失败为 `fulfillment_failed`、可重试且无模型可引用它。 |
| Validation | Phase-1 DAG 环/悬空边/多个入口、observable entry、observability 分类、Profile evidence、无效 binding、primary 数量、无 contract、警告 | 错误结构能定位字段；indirect/latent 不因没有直接 Evidence 误阻断；warning 不阻断，error 阻断 submit/publish。 |
| Governance | submit、reject、governance publish、compile、显式 activate、supersede、archive、clone | 所有状态转换递增 revision；publish 不替换 active；生产默认禁止自审；旧版本和 Trace 不被删除；archive active 同一事务按精确 Source pin 清 pointer、source→archived、current Blueprint `compiled→withdrawn`；任一不匹配/失败完整回滚。 |
| Hash / snapshot | 同 semantic 字段 hash 稳定；presentation/governance 字段不影响；目录版本改变影响；hash 不能被客户端覆盖 | Published Snapshot 不可变，hash 与白名单 canonical payload 一致。 |
| Candidate Artifact | 编译成功完整纯 IR、canonical artifact hash、schema version、success 后篡改、failed Artifact、逐源 BlueprintSource pin 与 provenance 区分、Blueprint projection hash | success 缺 Artifact/哈希不匹配被拒绝；每个将物化的 source identity/version/snapshot/content hash 必须进入 Artifact hash，而 compiler version/config、build-request identity、idempotency key 与聚合 `source_model_hashes` bookkeeping 不进入；Artifact success 后不可变；Activation 不调用 Compiler；BlueprintVersion 记录的 hash 与从子表 materialized projection 复算的 hash 都严格等于 CompileRecord。 |
| Compile retry / explicit activation / Discovery | Attempt 幂等、running 返回、failed retry lineage、success Artifact reuse、outbox delivery 独立；多个 inactive candidates、指定 record/version 与 expected active pointers 激活、Source pin、旧 Blueprint supersede | 同请求/Idempotency-Key 返回同 Attempt；failed retry 新建 `retry_of_compile_id` Attempt；last-known-good：新 candidate delivery queued/pending 或 CompileRecord running/failed 时旧 active 继续服务；只接受显式 IDs，不扫描/猜测；CAS 不匹配返回 `409 ACTIVE_VERSION_CHANGED` 且零写入；activation 成功才同时切 active pointer 与 current Blueprint；事务失败旧 active 完整保留；无 active 才返回诊断状态，Trace 不受影响。 |
| Case A regression | Fixture import/compile/prepare/evaluate/trace | 既有 45 项测试继续通过，且 Case A `testing` 语义不改变。 |
| N01B E2E（后续） | 业务用户在 UI 配置 Case A 等价模型、校验、提交、发布、发起诊断 | 发布的 hash/Snapshot/Golden Top 1 与受控预期一致；人工测试从此阶段开始。 |

发布 N01A 的最低自动化门槛：所有新增服务/迁移/RLS/API 测试通过、Case A 45 项回归通过、`ruff`、`lint-imports` 与 `git diff --check` 通过。N01B 完成前不宣称已完成业务用户的可视化人工验收。

---

## 12. 实施前置与未决项

### 12.1 已决定的实施前置

以下不是开放设计项，必须在 N01A 服务开发前落实：

1. **Candidate Artifact / Attempt lineage：** `0040` 为 CompileRecord 增加不可变 `compiled_artifact_json/compiled_artifact_hash/artifact_schema_version` 和 `retry_of_compile_id`；Artifact hash 覆盖纯可 materialize IR 中每个 BlueprintSource 的 identity/version/snapshot/content hash，而 build-request identity、idempotency key 与聚合 provenance bookkeeping 留在 CompileRecord；并为 BlueprintVersion 增加 Artifact hash/schema 投影。activation 只能物化指定 Artifact、带 active-pointer CAS，并必须执行强不变式验证。
2. **最小 relational outbox：** `0040` 建立 `outbox_events/outbox_deliveries`，将 delivery 状态与 CompileRecord 分离；它是 N01A 范围，不再作为基础设施待定项。
3. **Blueprint L3 Implementation Erratum：** 已由 [Planning Blueprint L3 — N01A Implementation Erratum](2026-08-30-planning-blueprint-l3-implementation-erratum-n01a.md) v1.0 冻结，统一 append-only CompileRecord Attempt、真实状态、纯 IR Candidate Artifact 与 CAS activation finalisation。

`CatalogResolver.resolve/validate` 的统一 `CatalogRef` 契约已在 §5.2 冻结，不再是 N01A 架构阻塞；具体目录服务的业务所有权仍按下列产品未决项处理。

### 12.2 仍需 PRD/产品确认

1. **指标目录权威来源：** 是在现有 Ontology 的 `kind='metric'` 上扩展 unit/aggregation/time semantics，还是建立独立 Metrics Catalog；两者都必须实现 §5.2 契约。
2. **目录管理员分工：** Ontology、Metric、Binding Template、Capability Contract 是否共用 `ecmc.catalog.approve`，或按领域拆为更细 permission，由安全/平台负责人确认。
3. **Draft 删除语义：** 建议仅允许从未提交、未被审计引用的 Draft 物理删除；其余使用 archived，以降低审计歧义。需产品确认是否需要“撤销草稿”体验。
4. **规则表达与 Profile 扩展：** 首版只支持三种 rule type、DAG authoring 和 sign_propagation_v1；环路、复杂公式、脚本、自由 DSL 或其他算法 Profile 必须另立安全/验证设计。
5. **审批 SLA/通知：** `in_review` 的提醒、超时、委托和多人会签不属于 N01A 核心；若产品需要，纳入独立治理/Workflow 需求，不能塞入 Blueprint。

---

## 13. 实施前检查清单

- [ ] `0040` migration 评审通过：Artifact 不可变/哈希约束、Blueprint hash 投影、active pointer、最小 relational outbox 与已有 Case A Fixture 兼容。
- [x] Blueprint L3 Implementation Erratum v1.0 已评审通过。
- [ ] N01 PRD 确认 §12.2 的产品未决项，尤其指标目录与审批治理。
- [ ] 安全评审确认 permission strings、self-approval tenant policy、RLS 与审计字段。
- [x] API / 数据契约与 canonical payload schema 已冻结；实现阶段须以其生成 OpenAPI / Pydantic 与单一 Canonicalizer。
- [ ] 在 N01A 服务测试完成后，再进入 N01B 图编辑器与人工测试。
