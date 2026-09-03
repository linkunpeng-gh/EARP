# N01A 生产 Catalog 契约签署与接入计划

**文档编号：** PLAN-ECMC-N01A-CATALOG-PRODUCTION-20260831
**日期：** 2026-08-31
**状态：** Draft / for Product, Platform and Data-owner signature
**适用范围：** N01A 因果模型管理的生产受控 Catalog 接入、行业/企业 Catalog Pack、目录扩展申请履约与上线门禁
**不包含：** 真实 Provider、凭据、端点或 N03 数据接入实现

本文件是生产 Catalog 的签署包和接入顺序，不是 Provider 实现，也不是新的 HTTP/OpenAPI 冻结。凡标注 **[FROZEN]** 的内容来自现有契约；凡标注 **[PROPOSAL]** 的字段、查询能力或运营规则，必须由责任人签署后才能进入实现合同。

## 1. 依据、阅读规则与结论

本计划依赖并引用以下基线：

- [N01A PRD](../../prd/PRD-2026-033-causal-model-management-n01a.md)：发布与运行时激活分离、受控目录、租户/RBAC、Fixture 边界和 N02/N03 边界。
- [N01A 详细设计](2026-08-30-causal-model-management-n01-detailed-design.md)：领域对象、状态机、Resolver 接口、审计、CAS activation 和实施门槛。
- [N01A API 契约](../../api/2026-08-30-n01a-causal-model-management-api-contract.md)：`CatalogRef`、写入字段、错误 HTTP 状态和 CatalogChangeRequest 命令。
- [Canonicalization/Hash 契约](2026-08-30-n01a-canonicalization-and-hash-contract.md)：Snapshot/Artifact 的 pin 和 hash 排除项。
- [CatalogResolver 与 Fixture 边界](2026-08-30-n01a-catalog-resolver-and-fixture-boundary.md)：Resolver、初始 manifest、履约边界和 test-only adapter。
- [L3 Implementation Erratum](2026-08-30-planning-blueprint-l3-implementation-erratum-n01a.md)：Candidate Artifact 与 explicit activation 的实现优先级。
- [下一阶段任务书](../acceptance/2026-08-30-planning-blueprint-next-phase-task-book.md)：N01→N02→N03 的任务顺序和后续真实 Provider 前置条件。

当前结论是：**模型侧 Resolver 合同已冻结，但生产 Catalog 的权威 owner、初始 manifest 和读/履约服务归属尚未签署；在签署前生产默认必须 fail closed。** 现有服务的 `UnavailableCatalogResolver` 和 `FakeCatalogResolver` 只能证明边界，不能被解释成生产 Catalog。

### 1.1 冻结层级

| 层级 | 当前结论 | 本计划的处理 |
|---|---|---|
| 已冻结的调用方合同 | `CatalogRef={kind,stable_id,version}`；`resolve`/`validate`；`ResolvedCatalogRef` 的 pin 字段；五个 `CATALOG_REF_*` 错误；新引用只能用 exact active ref。 | 接入时必须原样实现，不因具体目录产品改变。 |
| 已冻结的治理边界 | 批准目录申请不等于履约；只有权威目录服务返回 active stable ref 才能 `fulfilled`；模型 Snapshot pin `version+content_hash`。 | 所有阶段门以此为硬条件。 |
| 已冻结的测试边界 | Fixture Discovery 只能 test-only 显式注入；`testing`/`published_fixture` 不得进入生产 active gate。 | 生产 composition root 和正式 HTTP 不注册 Fixture adapter。 |
| 尚未冻结的集成形态 | manifest 精确 JSON schema、browse/search 查询参数与排序、owner callback 鉴权、SLA、各 kind 的物理目录实现。 | 仅以 [PROPOSAL] 描述，签署后另行生成实现契约。 |

## 2. 冻结边界与非目标

### 2.1 本计划冻结的边界

1. N01A 模型服务只保存稳定 `CatalogRef` 和发布时解析出的 `content_hash`、解析版本及语义 schema；不保存目录内部主键。
2. Resolver 是唯一外部目录边界。模型服务不直接读取 Ontology、Metrics、Binding Template 或 Capability Registry 的内部表。
3. 新 Draft、提交审核、治理发布、编译和激活都必须使用 exact version；`latest`、`*`、display name 或未解析 ID 不可接受。
4. **[FROZEN]** `status=active` 是新模型引用、提交、发布、编译及 activation revalidation 的最低条件；Catalog entry 一旦不再 active，上述所有新操作必须拒绝。`deprecated` 仅供历史 pin 读取，不能成为新选项。已经 active 且完成 pin 的模型是否继续以 last-known-good 服务，属于另行签署的运营策略，不改变新 activation 必须拒绝的冻结语义。
5. CatalogChangeRequest 的 `approve` 只转为 `approved_pending_fulfillment`；目录 owner 在自己的事务中创建并激活条目，成功返回 active stable ref 后才转 `fulfilled`。
6. 目录不可用、租户/数据域不可见、kind 不匹配、版本不精确或 schema 不兼容时必须 fail closed；不得用自由配置、Provider 参数或临时 URL 补位。

### 2.2 非目标

- 不在本计划内选择或接入任何真实目录产品、Provider、数据库、网络端点、凭据、token、SQL、查询 DSL 或物理 Capability ID。
- 不新增 N01A 公共 API；`browse`、`search` 和履约 callback 的具体路径、请求体、分页/排序和认证形式均待签署。
- 不由 N01A 生成或修改 Ontology/Metric/Capability 的权威定义；申请 payload 只是候选业务语义。
- 不定义真实数据字段字典、刷新频率、Provider readiness 或 N03 的错误映射。
- 不自动激活、自动回退、自动选择多候选目录条目或多候选模型；运行时仍遵循 explicit activation 与 last-known-good。
- 不把 Case A Fixture 的 stable ID、hash、fake catalog 条目或 dev 环境变量提升为生产初始目录。

## 3. 待签署决策表

以下包含进入生产读/写接入前必须确认的冻结约束，以及必须签署的实施决策。标为 **[FROZEN] 确认项** 的内容只能确认遵守，不能选择替代语义；标为 **[PROPOSAL]** 的推荐值是实施建议，不是已冻结 API。签署记录应至少包含责任人、日期、选择项、例外和关联变更单。

| 决策 | 约束/推荐默认 | 可选替代/风险 | 签署责任 | 阻塞门 |
|---|---|---|---|---|
| Metric 权威来源 | 现有 Ontology 提供满足 `unit/aggregation/time semantics` 的 metric projection；若做不到，再采用独立 Metrics Catalog。 | 并行目录会造成 stable ref、生命周期和语义重复。 | 平台架构负责人 + 指标/数据域负责人 | Phase 0→1 |
| 各 kind 的 owner | Data Domain/Entity/Relation 由 Ontology owner；Metric/Unit/Aggregation 由 Metric owner；Binding Template 由知识平台；Capability Contract 由能力平台；Rule/Time Window 由平台。 | 共用 owner 简化治理但扩大事故半径；拆分 owner 需要更细授权。 | 平台负责人 + 数据负责人 | Phase 0→2 |
| manifest 作用域 | 每个 tenant 明确 data-domain scope；真正 global 的条目必须显式标记并经过安全签署。 | 默认全局会产生跨域引用和越权风险；默认全租户复制增加维护成本。 | 数据负责人 + 安全/RBAC owner | Phase 0→1 |
| Case A 初始集 | 仅覆盖 Case A 等价模型实际需要的 domain、entity、relation、metric/unit/aggregation、time window、binding、logical contract、rule/profile。 | 预先铺开完整企业目录会扩大审计和回滚范围。 | 领域负责人 | Phase 0→1 |
| browse/search 归属 | 目录 owner 提供只读查询能力，N01A 只消费稳定投影；目录不可用时无可引用选项。 | N01A 自建索引会复制权威语义并引入同步漂移。 | 平台架构负责人 | Phase 1 |
| 搜索结果语义 | 允许 display name/业务描述搜索，但返回值必须是 exact ref；不得隐式返回 `latest`。 | 仅 stable ID 搜索可减少歧义但降低业务可用性。 | 产品负责人 + 数据负责人 | Phase 1 |
| 履约边界与 callback | **[FROZEN]** approve 只进入 pending，只有 owner 返回并经 Resolver 确认的 active ref 才能 fulfilled。**[PROPOSAL]** callback transport、认证、稳定 operation identity、对账、幂等、重放防护、密钥轮换和审计见 §5.3–§5.4。 | 由客户端直接标 fulfilled 不可审计且可绕过 owner；超时后直接创建新 operation 会造成重复履约。 | 平台负责人 + 各 kind owner + 安全负责人 | Phase 0→3 |
| Catalog 审批权限 | **[PROPOSAL]** 首版使用 `ecmc.catalog.approve`，履约仍按 kind 委派；已有 RBAC 能支持时再拆细权限。 | 细分权限更安全但会延长初始接入。 | 安全/RBAC owner | Phase 0 |
| active 条目变更 | **[FROZEN] 确认项：** 禁止同一 `(kind,stable_id,version)` 改写语义或 content hash；变更必须发布为新 version。 | 无替代语义；owner 只确认遵守。原地修改会破坏 Snapshot/Artifact/Trace 可重放。 | 数据负责人 + 平台架构负责人 | Phase 1 |
| manifest↔Resolver 一致性 | owner 签署的 entry 投影与 Resolver 返回投影必须逐字段一致，`content_hash` 必须逐字节一致；各 kind 的 canonicalization/hash 算法及版本由 owner 签署。 | 仅校验 64 位 hex 形态无法防止不同 canonicalizer 产生漂移。 | 各 kind owner + 平台架构负责人 | Phase 0→1 |
| manifest 版本化与重签 | 每次条目新增、修订、下线、scope/owner/schema 变化都生成不可变的新 manifest 修订、重新签署并归档旧修订；权威存储和标识规则另行签署。 | 原地覆盖 manifest 无法追溯审批事实；仅改 entry version 不能替代 manifest 治理留痕。 | 平台架构负责人 + 数据负责人 + 安全/审计负责人 | Phase 0→1 |
| 目录下线后的模型行为 | **[FROZEN]** entry 不再 active 时，禁止其用于新的引用、提交、发布、编译和 activation revalidation。**[PROPOSAL]** 已经 active 且完成 pin 的模型是否继续以 last-known-good 服务，以及停机、告警和恢复时限，由数据与运行平台负责人签署。 | 冻结的新操作拒绝语义没有替代项；运营策略需权衡立即停机与继续服务的风险窗口。 | 数据负责人 + 运行平台负责人 | Phase 1 结束前（Phase 2 进入门） |
| audit 留存/脱敏 | 复用 `audit_logs`，记录 actor/role/correlation、ref/version/hash、状态和脱敏理由；不写凭据、endpoint、原始业务数据。 | 留存期和监管分区不能由本文件臆定。 | 安全/审计负责人 | Phase 0→2 |

未完成签署的行不得被实现为“默认行为”；可先实现接口、Fake/contract test 和 fail-closed 装配。

## 4. Catalog manifest 最小字段（提案）

本节是进入 Phase 1 前提交给 owner 的 manifest 形状建议。**它不是已冻结的新增 API 或数据库表。** 现有契约只要求 manifest 至少覆盖初始目录项、stable ref/version/content hash、owner 和 resolver adapter 位置；下列具体字段名、版本规则和 `global` 表达需签署后才能冻结。

### 4.1 manifest envelope [PROPOSAL]

```json
{
  "manifest_schema_version": "catalog-manifest/v1",
  "manifest_id": "<stable manifest identity>",
  "scope": {
    "catalog_profile_id": "<signed effective catalog profile>",
    "industry_scope": "<for example coal_mining or finance>",
    "tenant_mode": "tenant_scoped|global",
    "tenant_id": "<only when tenant_scoped>",
    "data_domain_ids": ["<signed domain identities>"]
  },
  "pack_lock": [
    {"pack_id": "<platform|industry|enterprise pack>", "layer": "platform|industry|enterprise", "version": "<exact>", "content_hash": "<64 lowercase hex>"}
  ],
  "entries": [
    {
      "kind": "<CatalogKind>",
      "stable_id": "<stable identity>",
      "version": "<exact version>",
      "content_hash": "<64 lowercase hex>",
      "status": "active",
      "data_domain_id": "<domain identity or signed global marker>",
      "semantic_schema_version": "<kind schema version>",
      "compatibility_metadata": {},
      "input_schema": {},
      "output_schema": {}
    }
  ],
  "owners": [
    {"kind": "<CatalogKind>", "owner_role": "<signed owner reference>"}
  ],
  "resolver_adapter": {
    "identity": "<implementation identity>",
    "contract_version": "<signed adapter contract version>"
  }
}
```

公开 manifest JSON 是否直接携带审批元数据仍待签署，但必须存在一份可验证的审批/变更记录，并把签署对象绑定为 `manifest_id + manifest_schema_version + manifest_hash`。该记录至少包含签署人及责任角色、签署时间、生效时间和关联变更单。manifest 内容、owner、adapter contract version 或 scope 任一变化，都必须产生新的 `manifest_hash` 并重新签署，不得沿用旧审批。

### 4.2 字段约束与禁止项

| 字段/集合 | 最小要求 | 当前状态 |
|---|---|---|
| `kind, stable_id, version` | 与 `CatalogRef` 完全相同；version 必须精确，禁止 `latest`/`*`。entry 在所属 tenant/global scope 内至少按 `(kind,stable_id,version)` 唯一。 | **[FROZEN]** ref 字段和精确性；manifest scope 表达及唯一性实现是 **[PROPOSAL]/待签署**。 |
| `content_hash` | Resolver 返回的稳定 pin，必须是 64 位小写 SHA-256 hex；不接受客户端自报 hash。签署 manifest 中的值必须与 Resolver 对同一 exact ref 返回的值逐字节一致。 | **[FROZEN]** 解析、形态与 hash pin；各 kind 的 canonical input、canonicalization/hash 算法及其版本是 **[PROPOSAL]/待签署**。 |
| `status` | 新引用必须 `active`；历史 pin 可读取 deprecated，但不得提供新选择。 | **[FROZEN]** 语义。 |
| `data_domain_id` | 条目归属数据域；global 例外必须显式且有 owner 批准。 | 语义已冻结，global 表达是 **[PROPOSAL]**。 |
| `semantic_schema_version` | 让模型服务判断 input/output/规则/绑定 schema 兼容性。 | **[FROZEN]** Resolver 返回；各 kind 的取值待 owner 签署。 |
| `input_schema/output_schema` | 仅对需要输入/输出合同的 kind 提供受控投影；不放执行配置。 | **[FROZEN]** 可返回；具体 schema 待签署。 |
| `compatibility_metadata` | 仅放类型、单位、关系端点等语义兼容信息。 | **[FROZEN]** 可返回；字段白名单待签署。 |
| `owners/resolver_adapter` | 记录治理责任与适配器身份，便于审计和回滚。 | **[PROPOSAL]** 不进入模型 `CatalogRef` 或 Snapshot hash，是否入 manifest 待签署。 |
| `catalog_profile_id/industry_scope/pack_lock` | 记录本 manifest 对哪个行业、企业及数据域有效，以及由哪些 exact Catalog Pack 修订组合而成。 | **[PROPOSAL]** 属于治理与 adapter 输入，不新增或改变冻结的 `CatalogRef`。 |
| manifest envelope | schema/version、scope、entry 唯一性、签署人、生成/生效时间、manifest hash、撤销记录。 | **[PROPOSAL]** 不得直接当作 public API。 |

manifest 不得包含 `provider_id`、endpoint、URL、credential、token、SQL、query text、执行代码、数据库 row ID 或运行时 observation。`display_name` 只能作为非权威展示字段；显示名变化不能改变已发布 Snapshot 的语义 hash。

manifest entry 的签署投影是 Resolver 输出的一致性基准：`kind/stable_id/version/content_hash/status/data_domain_id/semantic_schema_version/input_schema/output_schema/compatibility_metadata` 中凡该 kind 适用的字段，运行时投影必须与签署值一致。任何字段漂移都不得被 adapter 静默归一化；应阻断该 exact ref 的新引用、发布、编译和 activation，并由 owner 以新 entry version 和新 manifest 修订处理。

一致性责任分工为：各 kind owner 负责生成并签署 canonical entry 与预期 hash/schema 投影；adapter owner 负责在加载时验证签名、manifest hash，并保证 Resolver 原样投影；N01A/平台团队负责提供跨实现 contract vectors、在部署门比较 manifest↔Resolver，并在保存、发布和 activation 前 re-resolve。任一层不能以“另一层已校验”为由跳过自己的门禁。

### 4.3 Case A 初始 manifest 清单 [待签署]

进入 Phase 1 前，领域和平台负责人必须逐项确认：

- 目标数据域、`production_output` 入口 Entity Type、其余 Node Entity Type、DAG 所需 Relation Type；
- 每条 required Evidence 的 Metric、Unit、Aggregation、Time Window 和 Binding Template；
- Binding Template 的 params schema、源/目标类型兼容性和 resolver identity/hash；
- 一个 primary 及可选 supporting Logical Capability Contract，及其 read-only input/output schema；
- `sign_propagation_v1` algorithm/Rule Schema 版本；
- 每个 kind 的 owner、激活责任、resolver adapter 位置、数据分类和下线联系人。

若某一项没有真实 owner 或 active stable ref，必须把它列为 manifest 缺口并阻断生产写路径；不得用 fake 条目或自由 stable ID 代替。

### 4.4 manifest 权威存储、加载与重签 [PROPOSAL]

1. 平台与安全负责人必须在 Phase 0 选择一个受版本控制、访问审计和不可变保留约束的权威存储；候选可以是签名制品仓库、受控配置仓库或专用 registry，但普通应用数据库行、开发机文件和临时对象存储不能自行成为签署事实。
2. 签署单位必须不可变，签署对象绑定 `manifest_id + manifest_schema_version + manifest_hash`。每次 entry 新增、修订、下线，或 scope、owner、schema/compatibility、resolver adapter identity/contract version 变化，都产生新 manifest hash、新修订并重新签署；旧修订只归档，不覆盖、不删除。
3. `manifest_id` 是每次修订产生新值，还是使用稳定 ID + 单调 `manifest_revision`，属于待签署标识规则；无论采用哪种方式，运行时必须能从 adapter deployment 追溯到唯一 manifest hash、签署记录和生效时间。
4. composition root 只加载已签署且处于生效窗口的修订。加载失败、签名/manifest hash 不匹配、修订撤销或 adapter identity 不一致时保持 `UnavailableCatalogResolver`/fail closed，不回退到 fake 或未签署旧稿。
5. 权威存储位置、签署人及责任角色、签署时间、生效时间、关联变更单、manifest hash、修订关系、撤销原因和部署关联号必须进入审批/审计证据；这些治理元数据可以位于受控审批系统或变更记录中，不要求全部进入公开 manifest JSON，也不进入模型 Snapshot/Artifact hash。

### 4.5 行业、企业与数据域分层 [PROPOSAL/待签署]

Catalog 的业务语义与 EARP 服务的行业和企业直接相关，签署不得默认对所有行业、企业和数据域永久有效。建议采用四层结构：

| 层级 | 内容 | 示例 | 签署边界 |
|---|---|---|---|
| 平台基础包 | 跨行业且语义确实一致的基础定义 | 吨、元、小时、日均、月累计 | 平台 owner 签署；不能因名称相同就宣称可跨行业复用。 |
| 行业包 | 某行业共享的实体、关系、指标和规则 | 煤矿的矿井/工作面/原煤产量；金融的账户/贷款/净息差 | 每个 `industry_scope` 独立 owner、版本、hash 和签署。 |
| 企业扩展包 | 某企业特有的组织、设备分类、指标口径和规则 | 某矿业集团的“有效生产时长” | 绑定 tenant/enterprise；不得静默覆盖行业包。 |
| 数据域授权 | 控制企业内部哪些角色可见、可引用哪些条目 | 生产、安全、设备、财务、风控 | 负责可见性和授权，不改变 entry 的已签语义。 |

一个生效 Catalog 应表现为已签署的 `catalog_profile`，其有效范围至少绑定 `industry_scope + tenant_scope + data_domain_scope + manifest revision/hash + resolver contract version`。例如“煤矿行业 + A 集团 + 生产域”的签署不能授权“金融行业 + B 银行 + 风控域”。

`CatalogRef` 继续严格保持冻结的 `{kind,stable_id,version}`，tenant 和行业权限由 Resolver 的认证上下文与 effective manifest 决定，不把 scope 或权限字段塞进 public ref。为降低跨行业重名风险，`stable_id` 建议采用治理命名空间，例如 `common.mass.tonne`、`coal.raw_coal_output`、`finance.net_interest_margin`、`enterprise_acme.effective_production_hours`；具体命名规则仍待 owner 签署。

effective manifest 类似依赖锁定文件：显式列出平台、行业和企业 pack 的 exact version/hash。禁止“企业包自动覆盖行业包”的隐式优先级；同一 effective scope 中出现相同 exact ref 但语义、schema 或 hash 不同，组合必须 fail closed。需要改变行业定义时发布新 version 或新 stable ID，并生成新的 effective manifest hash 和签署记录。

新增行业时不修改 N01A 模型治理契约：新增行业 pack、指定 owner、生成该行业/tenant/data-domain 的 effective manifest、执行 Resolver contract vectors 并独立签署。只有语义与 hash 都一致的基础条目才允许跨行业复用。

## 5. browse / search / resolve / fulfillment 责任边界

只有 `resolve`/`validate` 的调用方合同已经冻结。`browse`、`search` 是方便目录选择器的读能力，`fulfillment` 是目录 owner 的履约交互；下表中带 [PROPOSAL] 的名称、参数和响应形状不是新增 N01A API。

| 能力 | 责任方 | N01A 允许依赖 | 成功事实 | 失败语义 |
|---|---|---|---|---|
| browse [PROPOSAL] | 目录 owner/其只读投影 | 按 kind、tenant/data domain、active 状态列出候选；返回 display metadata + exact ref。 | 用户拿到可解析的 active ref。 | 无 owner/目录不可用时 fail closed；不返回任意候选、不降级 fake。 |
| search [PROPOSAL] | 目录 owner/其只读投影 | 业务文本搜索只用于发现；结果必须携带 exact `kind/stable_id/version` 和兼容元数据。 | 选择后仍由 N01A `resolve` 再次校验。 | 搜索无结果与目录不可用不可混淆；不得通过错误消息泄露无权条目。具体 transport code 待签署。 |
| resolve **[FROZEN]** | CatalogResolver adapter | `resolve(tenant_id, ref, expected_kind, at_version?, context?)`；不读取模型服务内部表。 | 返回 active `ResolvedCatalogRef`，含 pin/hash/domain/schema/compatibility。 | 仅 `CATALOG_REF_NOT_FOUND`、`CATALOG_REF_INACTIVE`、`CATALOG_REF_KIND_MISMATCH`、`CATALOG_REF_DOMAIN_FORBIDDEN`、`CATALOG_REF_SCHEMA_INCOMPATIBLE`；未知/不精确/跨域 fail closed。 |
| validate **[FROZEN]** | CatalogResolver adapter + N01A validator | 批量校验 refs 和 source/target/schema context；问题映射到可定位 ValidationIssue。 | 每个引用有 resolved version/hash 和兼容结论。 | 模型内容问题以 `422` ValidationResult；权限/可见性/状态冲突仍走 `403/404/409`，不伪装为图校验。 |
| fulfillment **[FROZEN governance boundary / PROPOSAL integration]** | 对应 kind 的权威目录 owner | **[FROZEN]** 批准后由 owner 创建并激活版本化条目，N01A 只消费成功结果。**[PROPOSAL]** 一个申请使用稳定 `fulfillment_operation_id`，retry 产生新 `attempt_id` 但复用 operation identity。 | owner 返回 `status=active` 的 stable ref，且 N01A re-resolve 通过后才标 `fulfilled`。 | 明确拒绝/确定失败可记 `fulfillment_failed`；超时或响应丢失属于不确定提交，必须先按 operation identity 向 owner 对账，不能直接启动新的履约 operation。 |

### 5.1 browse/search 的提案边界

在签署具体查询合同前，实施只应定义内部 `CatalogReadPort` 抽象，不定义路径或字段。若签署通过，读能力至少应遵守：

1. 身份和 tenant 从认证上下文取得；调用方不能提交任意 tenant 或跳过 data-domain authorization。
2. 默认只列 active 且调用者可见的条目；历史 deprecated 仅在审计/历史 Snapshot 读取场景显式请求。
3. 搜索排序不是语义选择依据；客户端必须由用户明确选择精确 version，N01A 再调用 `resolve`。
4. 所有显示名、描述和搜索摘要都是不可信展示数据；不可进入 Snapshot/Artifact hash 或代替 stable ref。
5. 目录 owner 的分页、全文索引、排序、rate limit、缓存、SLA 和 transport status 必须由平台 owner 另立并签署。

### 5.2 resolve/validate 失败处理

现有 `CatalogResolver` 的五个错误枚举是唯一冻结的 resolver failure vocabulary。Resolver failure code 是内部稳定错误分类，不直接决定 HTTP status；HTTP 映射只引用 [N01A API Contract](../../api/2026-08-30-n01a-causal-model-management-api-contract.md)，本计划不重新定义映射表。

- `CATALOG_REF_NOT_FOUND`、`CATALOG_REF_INACTIVE`、`CATALOG_REF_KIND_MISMATCH`、`CATALOG_REF_DOMAIN_FORBIDDEN`、`CATALOG_REF_SCHEMA_INCOMPATIBLE` 均不得被猜测修复。只有冻结 API Contract 明确属于模型内容校验的场景才映射为 `422 ValidationIssue`；命令级权限、不可见和状态冲突继续严格遵循冻结的 `403/404/409` 映射，不得混入 ValidationResult。
- Resolver 未配置时使用现有 fail-closed `UnavailableCatalogResolver`；它不能被透明替换为 fake 或“允许写入但稍后补齐”。
- 读路径如何将目录服务网络超时、限流或 owner 5xx 映射为 transport code 目前未冻结；应先返回安全的不可用结果，再由平台签署稳定错误合同，不能复用错误枚举掩盖基础设施故障。

### 5.3 fulfillment 失败与重试

`approved_pending_fulfillment`、`fulfilled`、`fulfillment_failed` 是冻结的治理事实，不是目录 entry 的状态替代品，也不因以下对账机制新增治理状态。每个申请在首次派发时获得稳定的 `fulfillment_operation_id`；每次 retry 产生独立 `attempt_id`/audit，但必须复用同一 operation identity，不覆盖旧 attempt 或错误。

`fulfillment_operation_id` 是 owner integration 的稳定关联身份，不由本文件新增为公共 N01A API 字段；其持久化、生成方式和是否仅在内部 contract 暴露，须在 Phase 3 的 additive 实现契约中确定。

owner 超时、连接中断或 callback/响应丢失属于“不确定提交”：目录条目可能已经创建并激活，N01A 不得立即创建新的履约 operation，也不得仅凭超时推断失败。授权 retry 前必须先用 `fulfillment_operation_id` 向 owner 查询/对账：若 owner 已成功，则取回原结果并走 callback/re-resolve；若 owner 明确未执行或已终止，才创建新的 attempt；若仍无法确定，保持原治理事实和证据，继续对账或人工处置。具体如何在现有状态字段上表达该事实由实现契约约束，但不得伪造 `fulfilled` 或引入本计划之外的新治理状态。

callback 必须按 `fulfillment_operation_id + attempt_id` 幂等：同一 operation 的相同结果可重复确认；同一 operation 返回冲突 exact ref/hash/status，或 attempt 属于其他 operation 时必须拒绝、零状态写入并审计。成功 callback 仍必须重新通过 `resolve`，确认 tenant/data domain、exact version、`status=active`、content hash 和 semantic schema。callback 不向普通用户暴露“直接 fulfilled”写入口。

### 5.4 callback 最小信任模型 [PROPOSAL/待签署]

阶段 3 开始前，平台、owner 和安全负责人必须逐项签署以下子项；具体协议和 endpoint 仍不在本文件冻结：

1. **传输与调用方身份：** 使用签署的 service identity；候选机制包括 mTLS workload identity 或带签名消息的受控内部通道。“来自内部网络”本身不能作为认证。
2. **授权：** identity 必须绑定允许履约的 Catalog kind、tenant/data-domain scope；不能仅凭 `request_id` 或管理员 UI session 标记 fulfilled。
3. **完整性与防伪：** callback 签名或可信通道必须覆盖 request ID、`fulfillment_operation_id`、`attempt_id`、exact ref、status、content hash、manifest revision 和 correlation ID；服务端随后仍需 re-resolve。
4. **重放防护与幂等：** 使用服务端生成并持久化的 operation/attempt/idempotency identity，结合时间窗及 nonce/唯一事件 ID；重复相同 payload 返回同一事实，不同 payload 复用 identity 必须拒绝并审计。retry 只能新增 attempt，不能更换 operation identity。
5. **密钥与身份生命周期：** 明确签发、轮换、撤销、泄露响应和双密钥过渡；密钥、证书私钥和原始认证材料不得进入申请、审计或错误响应。
6. **失败与可观察性：** 认证、授权、签名、时钟、重放或 Resolver 一致性失败均不得改变申请状态；记录脱敏 reason、correlation、owner identity 和 attempt lineage，并触发安全告警。
7. **暴露面：** callback 不作为普通用户公共 API；若采用 HTTP transport，路由注册、网络策略和 OpenAPI 可见性由单独的安全/API 变更单签署。

## 6. 租户、数据域、权限与审计

### 6.1 租户和数据域

- tenant 由认证上下文取得；客户端不能提交或覆盖 `tenant_id`。
- Catalog entry 若是 tenant-owned，所有读取/解析都在 tenant scope；模型与 entry 必须属于同一 tenant。
- data domain 是第二层隔离；模型所在 domain 必须属于 actor 的 `role_domain_access`。未知角色、空域范围和跨域引用均 fail closed。
- global entry 只有在 §3 签署 global 语义和可见机制后才可使用，并仍需通过 tenant policy、kind compatibility 和审计；不得把 global 当成跨域万能权限。候选机制为：A）由权威 Resolver 服务保存 global 条目并按调用 tenant/domain 做授权投影（推荐候选）；B）经治理流程复制为 tenant-scoped entry；C）独立 shared scope 存储并使用显式 tenant policy/RLS。安全 owner 必须签署其中一种及撤销传播方式；应用层绕过 RLS、默认跨租户可见不属于候选方案。
- N01A 不保存底层 catalog row ID；所有 parent-child/model 引用仍遵守 tenant-scoped composite FK/RLS。

### 6.2 权限矩阵

下列 Catalog permission 名称反映当前详细设计和实现，但尚未作为独立生产 RBAC 契约冻结，因此以 **[PROPOSAL]** 进入安全签署；冻结的是 tenant/data-domain fail-closed、权限与模型内容校验分离等授权语义，而不是本表对权限粒度的推荐。

| 操作 | N01A permission | 允许范围 | 关键限制 |
|---|---|---|---|
| browse/search/resolve 可见目录 | **[PROPOSAL]** `ecmc.catalog.read` | actor tenant + allowed domains | 不因 `audit.read` 获得写或扩大域。 |
| 创建/编辑/取消自己的申请 | **[PROPOSAL]** `ecmc.catalog.request` | 自己的 tenant/domain；仅 draft/submitted 可取消 | 申请 payload 不能含执行配置。 |
| approve/retry fulfillment | **[PROPOSAL]** `ecmc.catalog.approve` | 被授权 domain/kind | approve 只进入 pending；不能直接写权威目录。 |
| 模型引用目录 | `ecmc.causal_model.write_draft` | 模型 tenant/domain | 每次写入和发布再次 Resolver 校验。 |
| 发布/编译/激活 | `ecmc.causal_model.review/compile/activate` | 各自 tenant/domain | 不因目录读取权限获得治理或运行时切换权。 |
| 读取治理/履约审计 | `ecmc.causal_model.audit.read` | 既有 tenant/domain | 只读，不可单独制造审计事件。 |

### 6.3 审计最小记录

每次 browse/search（若产品决定需要访问审计）、resolve failure、申请写入/提交/批准/履约 attempt、模型 publish/compile/activate 至少可通过 correlation 关联。事件命名规范属于 **[PROPOSAL]**：建议沿用当前实现已经发出的 `ecmc.<aggregate>.<past-tense-event>`，例如 `ecmc.catalog_request.fulfillment_completed`，避免再新增不带 `ecmc.` 的第二套名称；详细设计中的 `causal_model.version_published` 样例应在后续 erratum 中与实现统一。事件名尚不是冻结 API，安全/审计 owner 和既有消费者签署前不得据此承诺外部兼容性；已有消费者若需迁移必须另立兼容变更。业务写入必须进入既有 `audit_logs`，最小字段为：

```json
{
  "event_type": "ecmc.catalog_request.fulfillment_completed",
  "tenant_id": "<server-derived>",
  "data_domain_id": "<authorized domain>",
  "entity_type": "catalog_change_request",
  "entity_id": "<opaque request id>",
  "actor_user_id": "<server-derived>",
  "actor_role_id": "<server-derived>",
  "correlation_id": "<request correlation>",
  "fulfillment_operation_id": "<stable owner operation identity when applicable>",
  "attempt_id": "<specific fulfillment attempt when applicable>",
  "catalog_ref": {"kind": "<kind>", "stable_id": "<id>", "version": "<exact>"},
  "content_hash": "<resolved hash when available>",
  "before_status": "approved_pending_fulfillment",
  "after_status": "fulfilled",
  "sanitized_reason": "<no secret or raw payload>"
}
```

凭据、endpoint、原始业务数据、未授权目录内容、完整任意 proposal JSON 和 provider readiness 不得写日志、Trace、Artifact 或审计 payload。留存期限、访问告警和是否记录每次只读 browse/search 是安全/审计 owner 的签署项。

## 7. FixtureDiscoveryAdapter test-only 隔离

Case A 的 `testing` Version、`published_fixture` release label、fixture package hash 和 45 项回归仍是历史测试输入，不是生产目录或治理发布。

### 7.1 装配规则

1. 生产 composition root 使用 `UnavailableCatalogResolver`，直到已签署的 authoritative adapter 通过接入门；不能通过环境变量、请求参数或 UI query string 打开 fake。
2. `FakeCatalogResolver` 只能在 test/dev composition root 显式注入；它的 `test_only=True`、独立注册 key/类型和现有 `EARP_ECMC_TEST_CATALOG=1` 钩子只服务页面/合同测试，不构成生产配置。仅有 `app_env in {dev,test}` 不足以证明是安全沙箱：部署 admission 必须再校验显式 sandbox/test 标记与允许的部署目标；生产/预发误配为 dev/test 时应拒绝启动，或在签署的过渡期至少产生阻断发布的高严重级告警。
3. `FixtureDiscoveryAdapter` 必须实施且仅能由测试 composition root/依赖注入装配，并具有独立类型和注册 key；正式 HTTP、N02 Discovery 和生产 `ActiveModelDiscovery` 不导入、不注册、不调用。
4. 生产 Discovery 只接受 tenant-scoped active pointer、Published Snapshot、passed validation、current compiled Blueprint 和精确 source pin；不接受 `testing`、`published_fixture`、Draft、Published inactive 或 fake 目录条目。
5. Fixture adapter 不得创建/发布/激活 CausalModel，不得绕过 Resolver、RBAC、CAS 或审计；它只返回 hash-locked fixture source/snapshot。

### 7.2 必须存在的负向契约测试

- production composition root 不包含 FixtureDiscoveryAdapter/FakeCatalogResolver；
- 生产/预发部署即使误配 `app_env=dev|test` 和 `EARP_ECMC_TEST_CATALOG=1`，也必须由 deployment admission/启动门拒绝或阻断发布；显式沙箱标记缺失时不得装配 fake；
- 现有测试专用 Catalog HTTP 端点必须与 Fake Resolver 使用同一组 `app_env + test catalog + explicit sandbox` 门控，任一条件缺失时端点不可注册或不可访问；
- 正式 HTTP 不能以 `testing` 或 `published_fixture` 解析出 active candidate；
- 生产 activation 对 Fixture Version 返回状态/权限失败且零 Blueprint、pointer、audit/outbox 写入；
- fake catalog 未配置时目录引用写入继续 fail closed；
- test-only adapter 的 fixture hash 变化被拒绝，且不能由导入器静默重算；
- Case A 既有 fixture import/compile/prepare/evaluate/trace 回归继续通过。

## 8. 分阶段生产接入步骤

| 阶段 | 交付与责任 | 进入条件 | 退出/回滚门 |
|---|---|---|---|
| 0. 签署与威胁建模 | 完成 §3 决策、具名 owner/RACI、manifest 草案及版本化/权威存储/重签流程、各 kind hash 算法、data-domain/global 机制、审计留存、deployment sandbox admission 和 §5.4 callback 信任子项。 | 产品、平台、数据 owner 签署；每个 kind 指向具体责任团队/系统及可追责角色，不能只保留泛化 owner 名称；安全确认禁止项、fake 部署门和 callback 信任模型。 | 任一签署缺失则停在 fail-closed；不写生产 Catalog。 |
| 1. 契约和 adapter 骨架 | 生成 `CatalogRef`/Resolved 投影/错误、manifest↔Resolver 一致性的 contract tests；保留生产 `UnavailableCatalogResolver`；Fake/Fixture/测试 HTTP 端点隔离测试。 | §0 完成；不依赖真实目录或 Provider。 | 一致性或隔离测试失败即不进入读集成；已 active 模型的 last-known-good 运营策略须在本阶段结束前签署，但不改变非 active entry 禁止新操作的冻结语义；回滚为删除未上线 adapter 注册，不动历史。 |
| 2. 只读 browse/search/resolve | 各 kind owner 提供已签署 manifest 和只读投影；N01A 只依赖 read port，并在保存/发布前 re-resolve。 | 初始 manifest 每项 active、manifest↔Resolver hash/schema 投影一致、域/owner 已确认，last-known-good 运营策略已签署。 | 任意 hash/version/domain/schema 漂移或 entry 非 active，均暂停新引用、提交、发布、编译、activation；已经 active 且完成 pin 的模型是否继续服务按已签署运营策略执行；不得切 fake。 |
| 3. 申请与 fulfillment | 接通 CatalogChangeRequest → 稳定 fulfillment operation → owner attempt → authenticated callback → active ref re-resolve；实现超时对账、operation/attempt 幂等、审计和 retry。 | owner callback、脱敏错误、operation identity、对账、冲突拒绝、幂等和重试合同通过。 | 明确拒绝/确定失败可记 `fulfillment_failed`；超时/响应丢失先对账，禁止直接新建 operation；暂停受影响 kind 新申请履约，不把 pending 当 active。 |
| 4. N01A 治理链路 | Draft 引用、validation、publish Snapshot pin、compile Artifact、explicit activation/CAS、archive。 | 见 §9 发布/回滚门；Case A 生产路径仍无 Fixture。 | activation 失败保留旧 pointer/Blueprint；停止新 candidate，不删除 Snapshot/Artifact/audit。 |
| 5. N02 消费验证 | N02 只读 active model/Blueprint/readiness 和历史 pin，验证无 active 的明确状态；不读目录内部表。 | N01A API/contract tests 全绿。 | N02 读到 stale/missing pin 立即 fail closed；不自行选择 candidate。 |
| 6. N03 真实 Provider 前置 | 数据负责人另立 Provider 规格、测试数据、认证和 Observation mapping；logical contract 保持不变。 | N03 明确低风险只读源和安全边界；不是本计划的签署项。 | Provider 故障只影响其 Observation/diagnostic readiness，不回写目录定义；mock/Fixture CI 保留。 |
| 7. 小范围发布与运行 | 只对签署 tenant/domain 开启 authoritative adapter；监测 resolver latency/error、跨域拒绝、履约和 audit。 | 平台变更评审、回滚演练和生产数据 owner 值守。 | 触发门禁即关闭新写/compile/activate，保留已验证 active last-known-good；恢复需重新签署或恢复 exact version。 |

## 9. Contract tests 与质量门

Contract tests 证明“接入方遵守已签署语义”，不证明某个真实 Provider 或目录产品已经上线。最低矩阵如下：

| 测试组 | 必测断言 | 依赖真实目录？ |
|---|---|---:|
| Ref/schema | exact `kind/stable_id/version`；拒绝 `latest/*`、display-only、extra execution fields；Resolved pin 字段完整。 | 否 |
| Resolver errors | 五个冻结错误逐一 fail closed；kind、exact version、tenant/domain、schema compatibility 正负例。 | 否，Fake adapter |
| Active/deprecated | active 可被新 Draft/submit/publish/compile/activate re-resolve；entry 非 active 时上述新操作全部拒绝；deprecated 只能历史读取，不能成为新选项；已有 active 模型是否继续服务只受签署的 last-known-good 运营策略影响。 | 否 |
| Hash pin | content hash 变化导致 Snapshot/Artifact/activation revalidation 不通过；同 version 不可原地换语义。 | 否 |
| Manifest↔Resolver consistency | 对每个 exact ref，manifest 与 Resolver 的 hash 必须逐字节一致，适用的 status/domain/semantic schema/input/output/compatibility 投影逐字段一致；任一漂移 fail closed。 | 签署前可用 contract vector；接入时需真实 adapter |
| Browse/search proposal | 只返回可见 active exact refs；无结果与 unavailable 不混淆；不泄露跨域条目。 | 仅签署后用 adapter |
| Fulfillment | approve→pending；一个申请的 retry 复用稳定 operation identity、产生新 attempt；超时先对账；callback 对 operation/attempt 幂等，冲突结果零写入；成功结果必须 active ref + re-resolve；不可直接 fulfilled。 | 否，可 stub owner |
| Tenant/domain/RBAC | RLS/复合 FK；403/404 fail closed；空域/未知角色拒绝；catalog.read 不扩大治理权限。 | 否 |
| Audit | actor/role/correlation/ref/version/hash/状态正确；无 credential/endpoint/raw data；CAS 冲突零 activation audit。 | 否 |
| Fixture/deployment isolation | production root 无 Fixture/Fake；错误的 dev/test 环境变量不能绕过显式 sandbox admission；测试专用 HTTP 端点同门控；正式 HTTP/Discovery/activation 拒绝 testing/published_fixture；Case A 回归不变。 | 否 |
| Lifecycle integration | publish 不切 active；success compile 不创建 Blueprint；activation 只吃指定 Artifact；CAS/失败保留 last-known-good；archive 原子 withdraw。 | 否 |
| N02/N03 seam | N02 仅消费 active/readiness；N03 仅实现 logical contract 到 Observation，不能改变 CatalogRef 或 Provider-free Artifact。 | 否，可 stub |

现有 [N01A contract tests](../../apps/earp-server/tests/test_n01a_contracts.py)、[API contract tests](../../apps/earp-server/tests/test_n01a_api_contract.py) 和 [lifecycle tests](../../apps/earp-server/tests/test_n01a_lifecycle.py) 应作为基线；新增生产接入测试必须扩展而不是削弱这些负向断言。质量门包括全量 N01A/Case A 回归、PostgreSQL RLS/迁移、OpenAPI contract、lint 和 `git diff --check`。

## 10. 发布、停机与回滚门

### 10.1 发布前门

生产 Catalog adapter 和初始 manifest 只有满足以下条件才可开启：

1. §3 的产品/平台/数据 owner 决策已签署，scope、owner、global 语义、权限和审计留存明确。
2. 每个被引用 kind 有 active stable ref、精确 version、可验证 content hash、semantic schema 和兼容元数据；没有条目的 kind 不能由客户端自由填写。
3. Resolver/adapter contract tests、tenant/domain/RBAC、fail-closed 和 Fixture isolation 全部通过。
4. Draft final validation 能生成包含 `catalog_resolutions` 的 Snapshot；Snapshot canonical hash 由服务端计算，客户端 hash 不具权威性。
5. CompileRecord 只消费 immutable Snapshot；success Artifact 的 source pin/hash 可验证，且不含 Provider/endpoint/credential。
6. Activation 使用显式 Candidate IDs、Version `If-Match` 和 active pointer CAS；只物化指定 Artifact，不扫描或重新编译候选。

### 10.2 运行中门禁

- Catalog entry 非 active、hash/version/schema 漂移、权限配置异常、跨域泄露、owner 不可用或 callback 失去认证时：立即关闭受影响 kind 的新 browse/search 选择、Draft submit/publish、compile/activation；保留证据和审计。已经 active 且完成 pin 的模型是否继续服务，仅按已签署的 last-known-good 运营策略处理。
- 不得将 outbox delivery、目录 pending 或 resolver timeout 写成 CompileRecord `pending`；CompileRecord 仍只有 `running|success|failed`。
- 普通的新候选发布/编译失败不影响已有 active；last-known-good 由数据库 active pointer 和 current compiled Blueprint 继续服务。若关联 Catalog entry 已不再 active，新引用/提交/发布/编译/activation 仍按冻结语义拒绝，已有 active 模型是否继续服务则按已签署运营策略执行。
- 不自动回退历史 Version，不静默切换到其他目录 version；恢复应由 owner 恢复原 exact ref，或走新 version + 新 Snapshot/Artifact + explicit activation。

### 10.3 回滚事实与不可逆操作

| 场景 | 可做动作 | 不可做动作 |
|---|---|---|
| read adapter 新部署失败 | 关闭新 adapter，恢复 `UnavailableCatalogResolver`，保留历史数据和 audit。 | 不把 FakeCatalogResolver 注册到生产。 |
| 某目录条目错误 | 停止选择、提交、发布、编译、activation；经 owner 修订为新 version 后重新校验。 | 不原地改 content hash、删已 pin 条目或重写 Snapshot。 |
| fulfillment 失败/超时 | 保留 operation/attempt/error；确定失败后授权管理员以同一 operation identity retry；超时先向 owner 对账。 | 不将 approved/pending 标成 fulfilled，不因超时直接创建新的履约 operation。 |
| activation 失败/CAS 冲突 | 旧 active pointer/Blueprint 完整保留；刷新 pointers 后由人显式重试。 | 不自动重试、自动回退或写伪 activation audit。 |
| active 模型需下线 | 走 archive transaction：清 pointer、source archived、current Blueprint withdrawn。 | 不清 pointer 后留下 compiled current，也不自动激活旧版本。 |

### 10.4 恢复演练要求 [PROPOSAL]

上线前应在非生产环境演练：目录不可达、单个 kind hash 改变、manifest↔Resolver 投影漂移、manifest 条目修订/重新签署/撤销、跨域请求、callback 伪造与重放、fulfillment 已成功但 callback/响应超时后的 operation 对账、误配 dev/test 环境打开 fake、CAS 竞争、active archive 和 adapter 回退。每个演练应有可观察的 audit/correlation、明确停机负责人和恢复条件；演练频率、RTO/RPO 和告警阈值待运行平台签署。

## 11. N02/N03 依赖和交接

### N02（诊断工作台）

- N02 依赖 N01A 提供的 active Model/Snapshot/Blueprint、`runtime_readiness`、错误语义和历史 pin；不依赖 Catalog 内部表。
- N02 可以展示目录解析摘要，但不能让用户填写 stable ID、Provider 参数或 endpoint；页面只消费 N01A 的 exact refs/validation issues。
- 无 active 时 N02 展示 `MODEL_COMPILE_DELIVERY_PENDING`、`MODEL_COMPILING`、`MODEL_COMPILE_FAILED` 或 `MODEL_NOT_ACTIVATED`；不得自行选候选或以 Fixture 代替。
- N02 的交接门是 API/OpenAPI、RBAC/404/403、last-known-good 和 Fixture isolation contract tests 全绿。

### N03（一个真实只读 Provider）

- N03 依赖 N01A 已签署并 active 的 Logical Capability Contract、Evidence Requirement 的 metric/unit/aggregation/time/binding 语义；N03 不改变 `CatalogRef` 或 Snapshot/Artifact hash contract。
- N03 自己负责 Provider 选型、认证、端点、字段字典、测试数据、Observation 标准化、数据不可用与基础设施失败映射；这些不进入 N01A manifest，也不由本计划假设。
- N03 可以实现 Contract 的物理 adapter，但不得把 provider readiness、credential 或 physical ID 回写 Catalog entry、Blueprint Artifact、Trace 或模型 API。
- Mock Provider 和 Case A Fixture 必须继续支持 CI/离线验收；真实 Provider 不得成为 N01A/N02 的隐式必需依赖。

## 12. 不得假设的目录、Provider、endpoint 和凭据

在签署前、代码和文档中均不得把以下内容当成已存在或已批准：

- 任何具体 Catalog 产品、Ontology/Metric 数据库表、云服务、供应商名称、租户 schema、网络可达性或区域部署；
- 任何 stable ID、display name、目录 version、content hash、Case A fake 条目或 `EARP_ECMC_TEST_CATALOG=1` 作为生产事实；
- 任何 browse/search URL、HTTP path、分页/排序/全文搜索实现、webhook/callback URL、认证协议或 SLA；
- 任何 Provider 名称、物理 capability ID、endpoint/base URL、OAuth/API key/secret/token、数据库 DSN、SQL、query text 或执行参数；
- 任何“批准即 active”“目录不可用自动选 latest”“同 version 原地修订”或“compile success 自动激活”的语义；
- 任何跨 tenant/global 默认可见、跨 data domain 继承、审计可读取无权目录、或由 UI/localStorage 选择器赋予权限的假设；
- 任何 N02/N03 尚未签署的用户界面、真实数据质量、Provider readiness、刷新频率或诊断降级策略。

## 13. 签署清单与交付物

### 13.1 必须签署

- [ ] 产品负责人：初始 Case A manifest 范围、目录选择/搜索体验、无目录时的用户提示和 N01A/N02 边界。
- [ ] 平台架构负责人：为每个 kind 签出具体责任团队/系统及可追责角色，而非仅写泛化 owner；同时确认 Resolver adapter/read port 归属、global 可见机制、entry canonicalization/hash 算法、manifest 版本化/权威存储和版本/hash 不变性。
- [ ] 数据域负责人：data-domain 分类、Entity/Relation/Metric 语义、content owner、下线/修订策略。
- [ ] 安全/RBAC/审计负责人：permission 粒度、RLS/domain scope、deployment sandbox admission、§5.4 callback 信任子项、manifest 签署/撤销、脱敏和留存。
- [ ] 运行平台负责人：不可用/漂移门禁、告警、回滚演练、RTO/RPO/SLA（不纳入当前 API，另立运营契约）。

### 13.2 签署后交付

1. 已签署的 manifest（含每项 exact ref/version/hash、scope、owner、schema/compatibility 和撤销记录），以及绑定 `manifest_id + manifest_schema_version + manifest_hash` 的签署记录、签署人/责任角色、签署/生效时间、关联变更单、权威存储位置、不可变修订标识和 adapter deployment→manifest hash 追溯关系。
2. 各 kind 的 Resolver/read/fulfillment adapter contract；其中公共 `resolve/validate` 必须与现有 v1.0 契约一致。
3. Contract test vectors、错误/审计样例、跨 tenant/domain 负向用例和 Fixture isolation 证据。
4. N01A OpenAPI/Pydantic 若需新增 browse/search/fulfillment 传输能力，另开 API 变更单并遵循 optional-additive/评审流程。
5. N02/N03 handoff note：N02 的只读状态面、N03 的 logical-to-physical Provider 边界和不变的 Snapshot/Artifact pin。

在以上交付物完成前，生产状态应保持“目录未签署、Resolver fail-closed”；这不是临时故障，而是 N01A 的安全默认。

## 14. 术语对齐

| 术语 | 本计划含义 |
|---|---|
| CatalogRef | `{kind, stable_id, version}` 的 exact public ref，在 tenant 认证上下文中解析；引用本身不携带或授予 tenant 权限，也不是 provider ID。 |
| ResolvedCatalogRef | Resolver 返回的 ref + content hash/status/domain/schema/compatibility 投影。 |
| manifest | 经 owner 签署的目录项与治理元数据不可变修订；仅作为 authoritative adapter 的受控输入/审批物，不直接成为 N01A 数据库表或 public API。具体 envelope、存储和修订标识仍是 proposal。 |
| browse/search | 面向目录选择器的只读发现能力；不是 N01A 已冻结的公共 API。 |
| fulfillment | CatalogChangeRequest 批准后由权威目录 owner 创建/激活条目的过程；一个申请保持稳定 operation identity，retry 只新增 attempt。 |
| FixtureDiscoveryAdapter | 仅测试 composition root 注入的 Fixture 发现适配器；不是生产 ActiveModelDiscovery。 |
| active | 目录 entry 可被新模型引用，或 Model pointer/Blueprint 可供运行时使用；二者必须按上下文区分，不能混称。 |
| last-known-good | 新目录/模型候选失败时继续服务已验证 active 的策略；不表示自动回退。 |
