# PRD-2026-033：N01A 因果建模管理能力

**状态：** v1.0 / Approved / Development Ready  
**日期：** 2026-08-30  
**产品范围：** N01A——因果模型管理 API、版本治理、受控目录、发布、编译与显式激活  
**设计基线：** `arch/design/2026-08-30-causal-model-management-n01-detailed-design.md` v0.3.1  
**前置成果：** Case A 因果诊断纵向切片已验收（Fixture/mock Provider 范围，45 项自动化测试通过）

---

## 1. 背景与问题

Case A 已证明：一份已经发布并固定的因果模型，可以被编译为 Planning Blueprint，完成诊断、原因排序和审计重放。但是，模型当前来自测试 Fixture；业务人员不能以受控方式创建、修改、审核和投产模型。

这会带来四个产品缺口：

- 业务知识无法成为可治理、可追溯的产品资产；
- 模型变更无法区分草稿、审批通过与真正运行时生效；
- 可执行证据需求若允许任意填写，会产生错误语义、不可执行配置和安全风险；
- 新候选模型若编译失败，不能破坏已在服务的诊断模型。

N01A 建立上述治理与运行时衔接能力。它提供后端服务/API；N01B 才提供业务用户操作的可视化建模界面。

## 2. 目标、成功定义与非目标

### 2.1 目标

1. 让授权用户能够管理单一诊断目标的因果模型及其版本、节点、边、规则、证据需求和适用范围。
2. 让模型从草稿经校验、审核、治理发布，形成不可变 Causal Model Snapshot。
3. 让已发布 Snapshot 经可追溯的编译生成不可变 Candidate Blueprint Artifact，并且只能由明确授权者显式激活。
4. 在模型升级、编译排队或编译失败期间，默认继续服务已激活的 last-known-good 模型。
5. 让所有可执行语义只引用受控目录；目录缺项经申请、履约后才可引用。
6. 保持 Case A Fixture 路径、既有诊断、Trace 和租户隔离语义不变。

### 2.2 成功定义

N01A 完成时，在 API/服务层可实现以下闭环：

```text
创建 Draft → 编辑/校验 → 提交审核 → 治理发布 Snapshot
  → 编译 Candidate Artifact → 显式激活 → 供新诊断 Discovery 使用
```

该闭环必须同时满足：已发布内容不可改、由本期正式 active 路径创建/激活的新诊断可定位到 Snapshot/Artifact/Blueprint、未激活候选不会替换生产版本、跨租户或越权访问失败关闭。历史 Case A Fixture/Trace 继续沿用既有 pin/replay 语义；不得为满足本期链路而伪造 N01A Candidate Artifact。

### 2.3 非目标

- N01B 图形画布、自动布局、表单交互和人工建模验收；
- N02 诊断发起、运行状态、结果和 Trace 的用户界面；
- N03 真实 Provider、凭据、端点、物理能力绑定或连接配置；
- 自动因果发现、LLM 自动建模、多模型融合、循环因果图或自由 DSL；
- 诊断/推理算法、动态 Evidence Requirement 展开、Provider readiness、调度器或 Trace 语义重写；
- 自动激活、自动回退、审批 SLA、委托、会签或工作流通知。

## 3. 产品原则与不可违背约束

### 3.1 一个模型只服务一个诊断目标

一个 Logical Causal Model 固化一个 `diagnostic_target_signature`；一个 Version 只承载该目标的一张因果图。首版目标为 `diagnose`。若需要不同目标，必须新建 Logical Model；运行时可由 Discovery 分别选择多个模型/Blueprint，但不得在同一 Version 混合目标。

### 3.2 治理发布不等于运行时生效

`published` 表示模型已审核并拥有不可变 Snapshot；`active` 表示该 Version 的已验证 Artifact 已成功物化为当前 Blueprint，允许新诊断使用。一个 Model 可有多个 `published + inactive` 候选，但任何时刻最多一个 active Version。

### 3.3 Last-known-good

新候选的编译投递排队、编译中或失败时，旧 active Version 继续服务。没有 active Version 时，调用方得到明确的“尚未投产/正在编译/编译失败”状态；服务不得猜测或自动挑选任意候选版本。

### 3.4 可执行字段受控，业务说明自由

实体类型、关系类型、指标、单位、聚合、实例绑定模板、规则 schema 和 Logical Capability Contract 必须从受控目录选择并由服务端解析。名称、备注、假设、业务说明和理由可自由填写。不得提交 SQL、URL、Provider 参数、凭据、物理 Provider ID、任意实体 ID 或自由查询 DSL。

### 3.5 首版只支持 DAG Authoring Profile

N01 Phase 1 的创建、校验和发布仅接受 DAG，并适配 `sign_propagation_v1`。这是 Authoring/Publish Profile 约束，不是底层图存储的永久限制；环路或其他算法 Profile 需另立设计。

### 3.6 不可变性与可重放

已发布 Version/Snapshot、成功 CompileRecord 的 Candidate Artifact 和已物化 Blueprint 不可就地修改或删除。业务变化始终通过复制为新 Draft 处理；历史 Trace 按自身 pin 重放，不受之后发布、激活或归档影响。

## 4. 用户、角色与权限

角色由租户管理员在既有 RBAC 中配置，不新增硬编码的“建模者/审核者”角色。生产租户默认采用提交与审核分离；开发/演示租户可以通过策略允许同一用户完成，但必须记录独立审计事件。

| Permission | 主要用户 | 能力 |
|---|---|---|
| `ecmc.causal_model.read` | 业务查看者、建模者 | 读取模型、版本、校验和可见目录。 |
| `ecmc.causal_model.write_draft` | 建模者 | 创建、复制、编辑、按已确认的删除策略撤销草稿、校验、提交审核。 |
| `ecmc.causal_model.review` | 审核者 | 驳回、治理发布、归档。 |
| `ecmc.causal_model.compile` | 发布运维/平台角色 | 发起或重试已发布 Snapshot 的编译。 |
| `ecmc.causal_model.activate` | 发布运维/业务负责人 | 显式激活指定成功 Artifact。 |
| `ecmc.catalog.read` | 建模者 | 浏览可引用的目录项。 |
| `ecmc.catalog.request` | 建模者 | 创建、取消自己的目录扩展申请。 |
| `ecmc.catalog.approve` | 目录管理员 | 审核目录扩展申请、重试履约。 |
| `ecmc.causal_model.audit.read` | 审计员、负责人 | 阅读治理、校验、编译和激活审计。 |

所有权限都受 tenant 与 data domain 范围限制。未知角色、无域授权或跨租户请求必须 fail closed；资源不可见时返回 404，已知资源但无相应操作权限时返回 403。

## 5. 关键用户旅程

### 5.1 建模者：从草稿到审核

1. 建模者创建一个含诊断目标的新 Logical Model 与初始 Draft Version，或从任一只读历史 Version clone 为新 Draft。
2. 建模者维护节点、边、规则、Evidence Requirement 和适用范围；只有 Draft 可写。
3. 建模者从目录选择所有可执行引用；缺少条目时提交目录扩展申请，而不是临时填写技术配置。
4. 建模者运行增量或全量校验，查看可定位到字段/节点/边的 error 与 warning。
5. 所有阻断项清零后，建模者提交审核；系统重新执行全量校验并锁定内容，Version 进入 `in_review`。

### 5.2 审核者：治理发布而非直接上线

1. 审核者查看锁定版本、诊断目标、来源 Version 引用、当前版本内容、校验结果、目录解析结果和审计信息。N01A 不承诺独立的语义 Diff Engine；N01B 如需基础差异展示，可通过两个 Version 的只读内容自行比较。
2. 审核者可带理由驳回，Version 回到 `draft`；也可发布。
3. 发布事务再次执行最终校验，生成 canonical hash 和 Immutable Snapshot，Version 变为 `published + inactive`。
4. 发布不会改变旧 active Model、当前 Blueprint 或正在运行的诊断。

### 5.3 编译与显式激活者：把候选安全投产

1. 有编译权限者对已发布 Version 请求编译；系统建立 append-only CompileRecord Attempt。
2. 编译成功后，记录完整、规范化的 Candidate Artifact JSON、Artifact hash 和 schema version；失败 Attempt 不可原地复活，重试必须创建带 `retry_of_compile_id` 的新 Attempt。
3. 有激活权限者查看成功 Attempt 的 Artifact 摘要，明确选择 `model_version_id + compile_record_id`，并提交自己看到的当前 active Version/Snapshot 作为 CAS 预期值。
4. 系统只从这个 Artifact 物化 Blueprint，验证 hash，并以单一事务切换 active pointer 与 current Blueprint；旧 active Version 才变为 `superseded`。
5. 若当前 active 已被他人改变，系统返回 `ACTIVE_VERSION_CHANGED`；不创建 Blueprint、不写入 activation 审计，用户刷新后再明确决定是否继续。

### 5.4 目录申请者与目录管理员

1. 申请者说明需要的新指标、实体、关系、绑定模板或逻辑能力合同及其业务理由。
2. 目录管理员批准申请后，状态只是 `approved_pending_fulfillment`；权威目录服务仍需创建并激活版本化条目。
3. 权威服务成功返回 active stable ref 后，申请才是 `fulfilled`，建模者才可选择它。
4. 履约失败标记为 `fulfillment_failed`，保存脱敏错误并允许重试；失败候选永不可被模型引用。

## 6. 范围与功能需求

### 6.1 领域对象与版本状态

实现以下产品对象及其可读 API 投影：

- `CausalModel`：逻辑身份、数据域、固定诊断目标签名和 active Version/Snapshot 指针；
- `CausalModelVersion`：目标、因果图、规则、Evidence Requirement、适用范围、revision 和治理状态；
- `CausalModelSnapshot`：发布时的不可变 canonical 语义内容与 content hash；
- `ModelValidationRun`、`ModelReview`：追加式校验与治理记录；
- `CompileRecord`：编译 Attempt 及其 Build provenance；
- Candidate Artifact：CompileRecord 成功时不可变的纯 Blueprint IR；
- `CatalogChangeRequest`：目录扩展申请和履约状态；
- 最小 relational outbox：可靠投递发布、编译、激活、归档事件。

Governance 状态为 `draft → in_review → published → superseded/archived`。`testing` 与 legacy `deprecated` 仅用于历史兼容/Fixture，不可由 N01A 正式 API 新建或转换。

### 6.2 Draft 管理

- 新建 Model 时服务创建首个 Draft；新 Version 可从空白或历史 Version clone。
- Draft 的“删除/撤销”遵循第 15 节待确认策略；不得为已提交、已发布或已审计引用的 Version 擅自物理删除。
- Draft 可维护元数据、适用范围、节点、边、规则、Evidence Requirement 与 Contract Binding。
- 删除节点前必须先显式删除其边、规则或证据依赖；不得隐式级联删除业务语义。
- 只有 Draft 可修改；非 Draft 的编辑请求返回 `409 INVALID_STATE_TRANSITION`。
- 每次写入及状态变更递增 Version revision；更新和状态变更必须使用 `If-Match`。冲突返回 `409 VERSION_CONFLICT`，禁止 last-write-wins。
- 每个写操作使用 `Idempotency-Key`；相同 key + 相同请求返回原结果，相同 key + 不同请求返回 `409 IDEMPOTENCY_KEY_REUSE`。

### 6.3 图与证据需求的业务规则

- Version 必须与 Logical Model 的目标签名完全一致；入口 Node 恰好一个、为 `observable`，且与诊断目标的入口/实体类型一致。
- Node observability 仅可为 `observable`、`indirectly_observable`、`latent_hypothesis`。后两类没有直接 Evidence 不自动阻断；入口必须直接可观测。
- Phase 1 图不得有自环、环、重复 key、悬空端点或不能通向入口目标的 Node/Edge。
- Edge 必须声明方向、`+/-` effect、有效的强度/置信度/时滞，并与受控 Relation Type 兼容。
- 每个 Evidence Requirement 必须含 metric、unit、aggregation、实例绑定、required/optional 语义；每项恰好一个 primary Logical Capability Contract，可有零到多个 supporting Contract。
- primary 失败不会自动选用 supporting；failover/alternatives 留待独立的 Capability Resolution Policy。
- 规则仅支持受控 `predicate`、`threshold`、`direction_rule` schema；不支持脚本或自由表达式。

### 6.4 校验与审核

Draft 保存进行局部 schema/目录解析；用户可主动运行 `incremental` 或 `full` 校验。提交审核和治理发布都必须在锁定内容上重跑 full/final validation。

下列模型内容 error 阻断提交/发布：目标不一致、DAG 环、入口/引用缺失、非法图语义、当前 Authoring/Algorithm Profile 明确要求的 required Evidence 缺失、primary Contract 缺失、无效实例绑定、目录项不存在/不活跃/不兼容、规则/适用范围无效、hash/schema 不匹配。`indirectly_observable` 与 `latent_hypothesis` 不因没有直接 Evidence 自动阻断。低置信度、过长 lag、宽范围 binding、过窄适用范围等以 warning 呈现但不阻断。

模型校验只回答“模型内容是否有效”，以 `422` 和 `ValidationResult` 返回。权限不足或资源不可见分别为 `403` 或 `404`；非法状态转换、Version revision 冲突和 active pointer CAS 冲突分别为 `409 INVALID_STATE_TRANSITION`、`409 VERSION_CONFLICT`、`409 ACTIVE_VERSION_CHANGED`。后者不得写入 `ValidationResult`，也不得在 N01B 中作为图校验问题展示。

校验结果必须是追加式记录，返回稳定 code、severity、可定位 `location`、expected/actual、catalog ref 与建议操作。N01B 将依赖这些字段高亮图与表单。

### 6.5 受控目录与扩展申请

模型服务通过统一 `CatalogResolver` 解析与校验 `CatalogRef {kind, stable_id, version}`。目录响应需包含 resolved version/content hash、active 状态、数据域、语义 schema 与必要的输入/输出 schema。客户端不可信任显示名称，也不得依赖目录内部数据库主键。

目录项类型包括：Data Domain、Entity Type、Relation Type、Metric/Unit/Aggregation、Binding Template、Logical Capability Contract 和 Rule Schema。`deprecated` 目录项只能支持历史读取，不能被新草稿引用；被 Published Snapshot 引用的目录项不能物理删除。

目录申请的状态为：`draft → submitted → approved_pending_fulfillment → fulfilled`，或 `rejected/cancelled/fulfillment_failed`。批准不等于已创建目录项；只有权威目录服务成功创建且 active 后才可引用。

### 6.6 发布、编译、Candidate Artifact 与激活

发布必须在一个事务中完成 final validation、Snapshot hash、Snapshot 插入、Version 状态更新、Review/audit 及 outbox 记录；绝不切 active pointer。

编译必须只消费已通过校验的 immutable Snapshot。CompileRecord 的状态仅为 `running → success | failed`；delivery 的 `pending_delivery/queued/retrying/dead_letter` 属于 outbox，不得混入 CompileRecord。成功 Attempt 必须有以下不可变三元组：

```text
compiled_artifact_json
compiled_artifact_hash
artifact_schema_version
```

Artifact 是纯、完整、可物化的 Blueprint IR，包含各 BlueprintSource identity/version/snapshot/content hash、Intent、Goal Skeleton、约束、输出合同、fallback、StepType/handler identity、steps、dependencies、step sources、capability requirements 与必要 schema version。Artifact hash 不包含 compiler version/config、请求/幂等 identity、聚合 provenance bookkeeping、Provider 解析、运行时 Observation、数据库 ID、时间戳或审计/outbox 状态；这些 build provenance 仍保存在 CompileRecord。

激活必须满足：

- 调用者显式传 `model_version_id`、`compile_record_id`、`expected_active_model_version_id` 与 `expected_active_snapshot_id`；后两个 expected 字段必须成对出现但允许为 `null`，首次激活必须显式传两个 `null`。缺失任一字段为请求错误，服务端不得按当前值推断；
- Version=`published`、Attempt=`success`、Version/Snapshot/Artifact 精确关联且目录/validation 仍有效；
- 在同一事务中以 active pointers 执行 CAS；
- 只能验证并 materialize 指定 Artifact，禁止重新调用 Compiler 或从多个候选自动选择；
- 物化 Blueprint 的 canonical projection hash 必须严格等于 Artifact hash；
- 成功才原子切换 active pointers/current Blueprint、将旧 Version `superseded`，并写审计与 outbox；任一步失败，旧 active 继续服务。

Activation 同时遵循两类并发契约：`If-Match` 比较所选 Candidate Version 的 revision，用于拒绝陈旧的 Version 治理视图；`expected_active_*` 只比较 Logical Model 的 runtime active pointers，用于阻止陈旧操作覆盖他人已完成的运行时切换。两者均须满足，不能相互替代。

归档 active Version 时，系统须同一事务清空 active pointers、归档 source Version 并将精确对应的 current Blueprint `compiled → withdrawn`；不自动回退旧版本。非 active Version 可正常归档。Phase 1 不提供独立 deactivate。

### 6.7 运行时发现与兼容性

新诊断只能使用同时满足以下条件的 active 组合：active pointers 精确指向 Published Version/Snapshot、Snapshot 有 passed validation、Blueprint 为 current `compiled`、BlueprintSource 精确 pin 该 Snapshot/content hash。Draft、Published inactive、Superseded 与 Archived 版本不得成为隐式回退。

若无 active Version，服务按权限提供 `MODEL_COMPILE_DELIVERY_PENDING`、`MODEL_COMPILING`、`MODEL_COMPILE_FAILED` 或 `MODEL_NOT_ACTIVATED`；无读取权限只返回通用无候选结果。

Case A 的 `testing` Version 与 `published_fixture` 是 hash-locked 测试导入边界，不是生产审核发布状态。N01A 必须通过仅测试装配可用的 Fixture Discovery Adapter 保持其 45 项回归；正式 HTTP、N02 和生产 Discovery 不得以此绕过 active gate。

## 7. API、事件与状态体验

HTTP 是传输实现，domain service 是权威。API 至少覆盖：

| 能力 | 代表接口 |
|---|---|
| Model/Version 查询与 Draft CRUD | `GET/POST /v1/ecmc/causal-models`；`GET/PATCH /.../versions/{version_id}` |
| 节点、边、规则、Evidence Requirement | `PUT/DELETE /.../nodes|edges|rules|evidence-requirements/...` |
| 校验、审核、发布、归档 | `POST /.../validate|submit-review|reject|publish|archive` |
| 编译、激活、治理可读性 | `POST /.../compile|activate`；`GET /.../governance` |
| 目录申请 | `GET/POST /v1/ecmc/catalog-change-requests`；`POST /.../{id}/approve|reject|cancel|retry-fulfillment`。`cancel` 仅申请人可取消自己的未完成申请；`retry-fulfillment` 仅目录管理员可对 `fulfillment_failed` 申请重试。 |

Version/治理详情对获授权用户应同时展示四个事实面：governance、compile、delivery、activation，以及由其确定性推导的 `runtime_readiness`：`active`、`compile_delivery_pending`、`compiling`、`compile_failed`、`ready_to_activate`、`not_activated`。在 last-known-good 情形，Model 保持 `active`，候选进度另列展示。

事件至少覆盖 Draft 写入、校验、提交/驳回、发布、编译请求/完成、激活、归档及目录申请/履约。发布事件必须带 tenant/model/version/snapshot/content hash/schema/correlation ID。outbox 只负责可靠通知和缓存清理；同步 Discovery 的正确性只依赖数据库 active pointer。

## 8. 数据、安全、审计与兼容约束

- 所有新增 tenant-owned 表必须含 `tenant_id`、启用并强制 RLS；所有 parent-child 关系使用 `(tenant_id, parent_id)` 复合 FK，禁止裸 ID 跨租户引用。
- `CausalModel` active pointers 只能指向同租户、同 Logical Model 的 Version/Snapshot；一个 Model 天然至多一个 active Version。
- Snapshot、成功 Artifact、Review、Validation、CompileRecord、Blueprint 与 Trace 为追加式或不可变历史；不执行物理删除来“修正”已发布业务事实。
- 服务端是 canonical hash 唯一计算者。Snapshot/Artifact 采用 UTF-8、`ensure_ascii=false`、排序 key、紧凑 JSON、SHA-256 和语义字段白名单。展示、画布、审批人/时间、revision、数据库 ID、outbox 与 active pointer 不影响语义 hash。
- Audit 写入既有 `audit_logs`，记录 actor、role、correlation、前后状态、相关 ID/hash、校验/Review 引用和脱敏理由；绝不写入 Provider 凭据、端点、原始业务数据或无权目录内容。
- 所有路由仅做身份提取和薄验证；授权、canonicalization、事务、状态转换和审计必须在 domain service 内实现。
- 历史 legacy `deprecated` 可安全映射时转为 `archived`；不可安全映射者只读保留并写 migration report。`testing` Fixture 状态保持原样。

## 9. 验收标准

### 9.1 核心业务验收

1. 授权建模者能经 API 建立与 Case A 业务语义等价的“3 号矿产量下降诊断”Draft，编辑其图、证据需求和适用范围；非 Draft 不可改。
2. 环、悬空引用、多个/错误入口、无效 binding、未解析或非 active Contract、当前 Profile 要求的 required Evidence 缺失、primary Contract 数不为 1 等模型内容 error 阻断 submit 与 publish；`indirectly_observable` 与 `latent_hypothesis` 不因无直接 Evidence 自动失败。warning 不阻断且可定位。
3. 模型内容错误只通过 `422 ValidationResult` 返回；权限/可见性错误分别返回 `403/404`，状态和并发错误返回相应 `409`，不得混入校验结果或图校验展示。
4. 无发布权限者无法发布；生产默认的同人提交/审核必须拒绝，除非租户策略显式允许并留下 policy/审计证据。
5. 发布创建稳定 canonical Snapshot hash。显示字段/审批时间变化不改变同一语义 hash；语义内容或目录解析版本变化必然改变 hash。已发布 Version、Snapshot 不可修改或删除。
6. 当已有正式 active Model 时，新候选的 compile delivery pending、running 或 failed 均不影响该正式 active Model 的 Discovery；Case A Fixture 的连续性仅在第 9.2 节自动化回归的 Fixture Discovery Adapter 中验证，生产 Discovery 不得使用 Fixture。
7. 成功 CompileRecord 必须持有可验证的完整 Artifact JSON/hash/schema；failed Attempt 不能原地重跑，retry 必须形成新的 lineage Attempt。
8. 激活只接受显式 Model Version/CompileRecord、Candidate Version `If-Match` 与 expected active pointers。Version revision 冲突与 active pointer CAS 冲突分别返回 `409 VERSION_CONFLICT` 与 `409 ACTIVE_VERSION_CHANGED` 且零业务写入；成功时从指定 Artifact 物化，Artifact/Blueprint projection hash 严格一致，并原子切换 active Model 与 current Blueprint。
9. 归档 active Version 时，不存在“模型已下线而 Blueprint 仍 current compiled”或相反的中间状态；出错后旧服务完整保留。
10. 目录申请未履约前不可被引用；仅权威目录服务成功创建 active 条目后可选择。申请人可取消自己的未完成申请；目录管理员可重试 `fulfillment_failed` 申请。申请 payload 含 SQL、凭据、URL、Provider endpoint 或执行代码必须拒绝。
11. 任意跨租户读/写/引用均失败；没有可读权限的用户不能通过状态或错误信息推断其他租户模型。

### 9.2 Case A 与回归验收

- 原 Case A Fixture hash、`testing`/`published_fixture` 边界及自动化语义保持不变；固定回归集继续通过。
- 生产 Discovery 不得接受 testing fixture 作为活跃候选；仅测试依赖注入使用 Fixture Discovery Adapter。
- legacy `SimpleTaskPlanner`、现有 `/plan` 路径和既有诊断/Trace 回归不受影响。

### 9.3 人工验收边界

N01A 的验收以 API、服务、迁移、RLS 与自动化测试为主。用户在可视化画布上配置/审核/发布并理解错误提示的人工验收，明确推迟至 N01B 完成后进行。

## 10. 测试策略与质量门槛

| 测试层 | 覆盖重点 |
|---|---|
| Schema/migration | 新状态、签名一致、active pointer、Artifact 不可变、retry lineage、outbox、RLS、legacy/Case A 兼容。 |
| Domain service | RBAC、数据域授权、Draft/Review/Publish/Archive 状态机、revision、幂等、hash、CatalogResolver、目录履约。 |
| Compiler/activation | 纯 IR Artifact、hash 白名单、failed retry、显式 activation、CAS、原子回滚、last-known-good 与 Discovery gate。 |
| API/contract | 正常/越权/不可见/422/409 响应、稳定 issue location、Idempotency-Key、If-Match。 |
| Regression/E2E | 既有 Case A 45 项、Fixture 隔离、legacy planner、Trace/audit replay。 |

最低质量门槛：新增迁移、服务、RLS、API 与回归测试全部通过；PostgreSQL Testcontainer 验证通过；`ruff`、`lint-imports` 与 `git diff --check` 通过。不得以单一黑盒 E2E 取代各层契约测试。

## 11. 分阶段交付

| 阶段 | 交付 | 完成判据 |
|---|---|---|
| 0：实施前收口 | Blueprint L3 Implementation Erratum、OpenAPI/Pydantic schema、canonicalizer 单一实现、权限/目录决策 | 设计基线与实现契约不冲突。 |
| 1：基础与读写 | `0040` schema 增量、RLS、RBAC、Model/Version Draft CRUD、CatalogResolver/目录读取、Validation | 可通过 API 创建和校验 Draft，所有隔离/并发测试通过。 |
| 2：治理与目录 | Review、Publish、Snapshot/hash、CatalogChangeRequest、audit/outbox | 发布得到 immutable inactive Snapshot，未履约目录项不可引用。 |
| 3：编译与激活 | CompileRecord Attempt/Artifact、retry、显式 Activation/CAS、Discovery gate、Archive | 可安全将指定候选投产，旧 active 在失败时持续服务。 |
| 4：回归与交接 | Case A Fixture adapter、全量自动化、实施报告/API 文档 | N01A 达到本 PRD 验收标准，可供 N01B 消费。 |

## 12. 依赖、风险与缓解

| 风险/依赖 | 影响 | 缓解 |
|---|---|---|
| 指标目录与 Logical Capability Contract 的权威来源未定 | CatalogResolver 无真实后端或语义分裂。 | 先冻结 resolver 合同与测试 adapter；在阶段 0 完成所有权决策。 |
| 发布与激活混淆 | 新候选失败会中断诊断。 | 以 published/inactive 与 active pointer 分离；仅显式 CAS 激活。 |
| Artifact 重新编译或 hash 不一致 | 激活内容不可审计、验证对象与运行对象不一致。 | success 冻结纯 IR；激活禁止调用 Compiler，并复算 materialized projection hash。 |
| 目录申请被当作直接配置入口 | 安全和执行语义失控。 | 分离审批与权威服务履约；未 fulfilled 不能引用。 |
| Case A 测试状态泄漏至生产 | 绕过治理/active gate。 | Fixture Discovery Adapter 仅测试 DI 可用；生产路径强制 active gate。 |
| 并发编辑/激活 | 覆盖他人修改或把旧候选切回生产。 | ETag/revision、Idempotency-Key、行锁、active pointer CAS。 |
| 现有 Blueprint L3 文本与 CompileRecord 实现不一致 | 实现理解和迁移漂移。 | 阶段 0 提交/评审 Implementation Erratum，明确 `running → success|failed` 与 outbox 边界。 |

## 13. 与 N01B、N02、N03、N04 的边界

| 范围 | N01A | N01B | N02 | N03 | N04 |
|---|---|---|---|---|---|
| 模型/版本/RBAC/校验/发布/激活 | 权威实现 | 只消费 | 只读消费 active 模型 | 不改 | 不改 |
| 节点、边、证据编辑 | API/服务语义 | 图画布、表单、错误体验 | 不提供 | 不提供 | 不提供 |
| 诊断、结果、Trace UI | 不实现 | 不实现 | 实现 | 仅提供数据 | Case B 只定义衔接 |
| Physical Provider | 只引用 logical contract | 不展示连接配置 | 可显示状态 | 实现真实 read-only adapter | 不实现 |
| 人工业务验收 | API 自动化为主 | 建模人工验收入口 | 诊断人工验收入口 | 真实数据人工验证 | 设计/验收规格 |

## 14. 术语

| 术语 | 定义 |
|---|---|
| Logical Model | 稳定业务身份，绑定单一诊断目标签名并保存 active pointers。 |
| Version | 一个可治理的模型内容版本；只有 Draft 可编辑。 |
| Snapshot | 治理发布时冻结的因果模型语义与 content hash。 |
| Candidate Artifact | 成功 CompileRecord 内冻结的、完整纯 Blueprint IR 及 artifact hash/schema。 |
| Governance publish | 审核通过并生成 Snapshot；不等于运行时激活。 |
| Activation | 以指定 Artifact 原子物化 Blueprint 并切换运行时 active pointers。 |
| Last-known-good | 候选未成功激活前持续服务旧 active 版本的默认策略。 |
| Logical Capability Contract | 与 Provider 无关的、受控的只读输入输出语义合同。 |
| CatalogChangeRequest | 受控目录缺项时的申请与履约记录，不是自由配置通道。 |

## 15. 待确认的产品决策

以下问题不阻塞本 PRD 的原则，但必须在阶段 0 关闭后再进入后续开发实施：

1. **指标目录权威来源：** 扩展既有 Ontology 的 `metric` 概念，还是建立独立 Metrics Catalog；两种方案都必须满足 CatalogResolver 合同。
2. **目录管理员权限粒度：** 是否共用 `ecmc.catalog.approve`，或按 Ontology、Metric、Binding Template、Capability Contract 分拆权限。
3. **Draft 删除体验：** 建议仅物理删除从未提交且未被审计引用的 Draft，其余统一 archive；确认是否需要面向用户的“撤销草稿”动作。
4. **审批体验：** N01A 只提供提交/驳回/发布。提醒、超时、委托与多人会签是否另立治理/Workflow 需求。
5. **首版目录初始集：** 哪些 Case A 相关 Entity/Relation/Metric/Binding Template/Contract 由领域与平台负责人作为可用起始目录确认。

---

## 16. 完成定义

N01A 完成不表示已完成可视化建模或真实数据诊断。其完成结论应表述为：

> Causal Model Management N01A — API, governance publication, candidate compilation and explicit activation accepted.

前提是本 PRD 的自动化验收、Case A 回归及质量门槛全部通过，并已明确记录尚留给 N01B/N02/N03/N04 的工作。
