# N01A 生产 Catalog Phase 1 设计（JQMK 煤矿生产域）

**文档编号：** DESIGN-ECMC-N01A-CATALOG-PHASE1-JQMK-20260901
**日期：** 2026-09-01
**状态：** Draft / for discussion
**适用范围：** 金桥煤矿（JQMK）生产域首个 Catalog manifest、Resolver contract vectors、Catalog Pack 与 pack lock、运行门禁证据
**依据：** Phase 0 签署实例 `arch/catalog/signoffs/jqmk-coal-production-20260901-r1.md`（tag `catalog-phase0-jqmk-coal-r1`）、配套计划 `arch/design/2026-08-31-production-catalog-contract-signing-and-onboarding-plan-n01a.md`、Resolver 边界契约、Canonicalization/Hash 契约

> 本文是 Phase 1 设计提案，不是已签署的实现合同。标 **[PROPOSAL]** 的内容需责任人确认后才能进入实现；标 **[FROZEN]** 的内容来自已冻结契约，不得改变。文末列出待讨论决策点。

---

## 1. 概述与目标

Phase 1 的目标是闭合 Phase 0 entry gate 的四个阻塞项，产出可签署的首个煤矿生产域 Catalog manifest，并为 Phase 1 exit gate（进入 Phase 2 只读接入）准备可执行的证据计划。

| Phase 0 阻塞项 | 本文对应章节 | 闭合方式 |
|---|---|---|
| D-01 Metric 权威来源 | §2.5 | 选定 Ontology 扩展 metric projection，定义 metric kind 的 canonical input |
| D-02 各 kind 具体 owner/系统 | §2.6 | 定义 10 种 kind 的 owner 分配与 canonical input/hash 算法 |
| D-03 manifest 权威存储与 revision identity | §2.1–§2.4 | 定义 manifest schema、ID+revision 规则、hash 计算、git 存储布局 |
| D-13 Catalog Pack 分层与 pack lock | §4 | 定义三层 pack 内容、version/hash 规则、effective manifest 组合 |

Phase 1 exit gate 的证据计划见 §5（运行门禁）和 §6（entry/exit gate 映射）。

---

## 2. Catalog manifest 设计

### 2.1 manifest schema [FROZEN]

正式 Schema：`arch/catalog/schemas/catalog-manifest.schema.json`（additionalProperties:false，字段白名单、必填性、正则约束已定义）。以下为结构示例，完整约束以 schema 文件为准。

采用配套计划 §4.1 的 envelope 提案，冻结为 `catalog-manifest/v1`：

```json
{
  "manifest_schema_version": "catalog-manifest/v1",
  "manifest_id": "coal.sdrh.jqmk.production",
  "manifest_revision": 1,
  "scope": {
    "industry_scope": "coal_mining",
    "enterprise_scope": "SDRH",
    "tenant_id": "JQMK",
    "data_domains": ["production"],
    "global_enabled": false
  },
  "pack_lock": [
    {"pack_id": "platform-base", "layer": "platform", "version": "1.0.0", "content_hash": "0000000000000000000000000000000000000000000000000000000000000000"},
    {"pack_id": "coal-mining-industry", "layer": "industry", "version": "1.0.0", "content_hash": "0000000000000000000000000000000000000000000000000000000000000000"},
    {"pack_id": "jqmk-enterprise", "layer": "enterprise", "version": "1.0.0", "content_hash": "0000000000000000000000000000000000000000000000000000000000000000"}
  ],
  "entries": [
    {
      "kind": "unit",
      "stable_id": "common.mass.tonne",
      "version": "1.0.0",
      "content_hash": "dec4a1bbb7569f89000000000000000000000000000000000000000000000000",
      "status": "active",
      "data_domain_id": "production",
      "semantic_schema_version": "catalog-unit/v1",
      "source_pack_id": "platform-base"
    },
    {
      "kind": "metric",
      "stable_id": "coal.raw_coal_output",
      "version": "1.0.0",
      "content_hash": "7962d8041450c20c0000000000000000000000000000000000000000000000",
      "status": "active",
      "data_domain_id": "production",
      "semantic_schema_version": "catalog-metric/v1",
      "source_pack_id": "coal-mining-industry",
      "compatibility_metadata": {"coal_seam_type": "all"},
      "value_semantics": {
        "measurement_type": "continuous_flow",
        "unit_ref": {"kind": "unit", "stable_id": "common.mass.tonne", "version": "1.0.0"},
        "aggregation_ref": {"kind": "aggregation", "stable_id": "common.agg.daily_total", "version": "1.0.0"},
        "time_window_ref": {"kind": "time_window_schema", "stable_id": "common.time.shift", "version": "1.0.0"}
      }
    }
  ],
  "owners": [
    {"role_key": "platform_architect", "name": "隋昕航", "team": "EARP 项目", "contact": null}
  ],
  "resolver_adapter": {
    "identity": "earp.catalog.resolver.api/v1",
    "contract_version": "catalog-resolver/v1.0"
  },
  "manifest_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "signoff": {
    "signoff_tag": "catalog-phase0-jqmk-coal-r1",
    "change_order": "JQMK-BG-20260901-001",
    "attestation": "arch/catalog/attestations/jqmk-coal-production-20260901-r1.json",
    "signed_at": "2026-09-01T00:00:00+08:00",
    "effective_from": "2026-09-01T00:00:00+08:00",
    "effective_until": null
  },
  "generated_at": "2026-09-01T00:00:00+08:00"
}
```

> 以上示例为结构示意。**正式 fixture** 见 `arch/catalog/schemas/fixtures/manifest-example.json`（10 条目，使用完整 golden hash，CI 中通过 schema 正例+负例校验）。文档示例与 fixture 保持一致，避免漂移。

**禁止字段**（[FROZEN]，来自配套计划 §4.2）：manifest 不得包含 `provider_id`、endpoint、URL、credential、token、SQL、query text、执行代码、数据库 row ID 或运行时 observation。`display_name` 仅为非权威展示字段。

### 2.2 manifest ID 与 revision 规则 [PROPOSAL]

- **`manifest_id`**：稳定标识，采用 `catalog_profile_id` 的值（`coal.sdrh.jqmk.production`），不随修订变化。
- **`manifest_revision`**：单调递增整数，从 1 开始。每次 entry 新增/修订/下线、scope/owner/schema/compatibility 变化、resolver adapter identity/contract version 变化，都产生新 revision。
- **`manifest_hash`**：对 manifest JSON（排除 `signoff` 块和 `manifest_hash` 自身）按 Canonicalization 契约（§2.3）计算 SHA-256，作为签署对象。
- **旧修订**：只归档，不覆盖、不删除。composition root 只加载已签署且处于生效窗口的修订。

> **决策点 A**：`manifest_id` 是否需要与 `catalog_profile_id` 解耦（例如用 UUID）？当前提案保持一致以降低认知成本，但解耦可支持一个 profile 对应多份 manifest（如灰度）。

### 2.3 manifest hash 计算 [FROZEN + PROPOSAL]

遵循已冻结的 Canonicalization 契约（`arch/design/2026-08-30-n01a-canonicalization-and-hash-contract.md` §1.1）：

1. 投影白名单：`manifest_schema_version, manifest_id, manifest_revision, scope, pack_lock, entries, owners, resolver_adapter`。**排除** `signoff`、`generated_at`、`effective_from/until`（生效时间是治理元数据，不参与内容 hash）。
2. Unicode NFC、ASCII 小写枚举、JSON key 按 code point 升序、集合按稳定复合键排序。
3. 集合按路径感知策略排序（见下表，作为版本化契约唯一来源）：

| JSON Pointer 路径 | 排序键 | 说明 |
|---|---|---|
| `/entries` | `(kind, stable_id, version)` | manifest 条目 |
| `/pack_lock` | `(layer, pack_id)` | pack 锁定列表 |
| `/owners` | `(role_key)` | 责任人列表 |
| `/signers` | `(role_key, name)` | attestation 签署人 |
| `/attributes` | `(name)` | entity_type 属性 |
| 任意 `/required` | 值排序（type-aware） | JSON Schema 必填字段 |
| 任意 `/enum` | 值排序（type-aware） | JSON Schema 枚举 |
| 任意 `/type`（数组时） | 值排序（type-aware） | JSON Schema 类型数组 |

非集合数组（如 `default`、`examples`、业务有序数组）**保持原顺序**，不排序。集合复合键重复时拒绝输入。
4. UTF-8、`ensure_ascii=false`、无额外空白 JSON，SHA-256 → 64 位小写 hex。

**envelope_hash（FROZEN，评审后新增）**：
- `manifest_hash` 只覆盖内容，不覆盖生效窗口和签署元数据。
- attestation 必须绑定 **envelope_hash** = SHA-256(canonical({manifest_hash, signoff_tag, change_order, signed_at, effective_from, effective_until, signers}))。
- 生效窗口（effective_from/until）的任何修改都会改变 envelope_hash，从而使 attestation 失效，必须重新签署。
- 运行时 Resolver 校验：manifest_hash 一致 + envelope_hash 与 attestation 中记录一致，二者均通过才允许服务。

### 2.4 存储架构：git（治理资产）+ 数据库（运行时数据）[PROPOSAL]

**双层存储，职责分离：**

| 存储 | 内容 | 用途 |
|---|---|---|
| **git**（`arch/catalog/`） | 签署模板、Profile、签署实例、attestation、schema、脚本、设计文档 | 治理审计、不可变证据、版本追溯（Phase 0 已签） |
| **数据库** | 源系统对象（指标/单位/聚合等）、Catalog 引用、pack、manifest 运行时副本 | 产品页面读写、Resolver API 查询、日常运营 |

> **关键原则**：git 不参与 Catalog 运行时数据读写。Resolver 通过 Catalog 模块提供的 API 查询数据库，不读取 git 文件。git 中的 manifest/pack 是签署后的归档副本，用于审计追溯，不是运行时数据源。

**git 目录布局**（治理资产，Phase 0 已签结构不变）：

```
arch/catalog/
├─ templates/          # 签署模板（FROZEN 语义）
├─ schemas/            # Profile schema 等
├─ profiles/           # 项目配置（签署时归档副本）
├─ signoffs/           # 签署实例
├─ attestations/       # 签署证据（hash 绑定）
├─ decisions/          # 决策/证据输入
└─ scripts/            # 校验/渲染脚本
```

**数据库表**（运行时数据，产品页面读写）：

| 表 | 内容 | 来源页面 |
|---|---|---|
| `catalog_profiles` | 项目配置 | profiles.html |
| `metrics` | 指标定义 | metrics.html |
| `catalog_units` | 单位 | catalog-basics.html |
| `catalog_aggregations` | 聚合方式 | catalog-basics.html |
| `catalog_time_windows` | 时间窗口 | catalog-basics.html |
| `catalog_rule_schemas` | 规则模式 | catalog-basics.html |
| `binding_templates` | 绑定模板 | binding-templates.html |
| `catalog_refs` | 已注册引用（stable_id + version + hash + status） | catalog-admin.html |
| `catalog_packs` | pack 定义 + 条目关联 | catalog-admin.html |
| `catalog_manifests` | manifest 修订 + pack 组合 + hash | catalog-admin.html |
| `catalog_change_requests` | 审批流 | catalog-admin.html |

**数据库约束设计（FROZEN）**：

| 约束类型 | 设计 |
|---|---|
| **唯一约束** | `catalog_refs`: UNIQUE(tenant_id, kind, stable_id, version)；`catalog_packs`: UNIQUE(tenant_id, pack_id, version)；`catalog_manifests`: UNIQUE(manifest_id, manifest_revision)；`catalog_active_manifests`: UNIQUE(profile_id) |
| **active pointer** | `catalog_active_manifests` 表：profile_id → active_revision + active_revision_generation（单调递增），CAS 切换用 `WHERE revision=?` |
| **快照表** | `catalog_manifest_entries`（manifest revision → entry 快照，含 content_hash）；`catalog_pack_entries`（pack version → entry 引用快照） |
| **乐观锁** | 所有可更新表含 `version` 整数列，UPDATE 时 `WHERE version=?` 并自增 |
| **软删除** | 所有表含 `deleted_at`（timestamp, null=active），查询默认过滤 `deleted_at IS NULL`；已发布 pack/manifest 不软删除，只撤销 |
| **RLS** | 所有业务表含 `tenant_id` + `data_domain_id`，行级安全策略按租户/数据域隔离 |
| **同步游标** | `catalog_sync_cursors` 表：source_system → last_sync_at + last_object_id，支持增量 pull |
| **outbox** | `catalog_outbox` 表：事件类型（cache_invalidate/git_archive）+ payload + status + retry_count + next_retry_at，事务内写入，异步消费 |
| **审批幂等** | `catalog_change_requests` 含 `idempotency_key`（申请人+资源+操作），防止重复提交；`attempt` 列记录审批尝试次数 |
| **不可变写入** | `catalog_manifests` 和 `catalog_packs` 已发布行禁止 UPDATE（数据库触发器或应用层校验），变更只能 INSERT 新 revision |

**Resolver 运行时**：生产使用 `ApiCatalogResolver`，通过 `/v1/catalog/resolve` 和 `/v1/catalog/validate` API 查询数据库，校验 content_hash 与 manifest 中记录一致，不一致则 fail closed。不使用 GitBackedResolver。

**原子发布流程（FROZEN，评审后修正）**：

manifest 发布分为**数据库事务**和**异步 outbox**两个阶段：

**阶段一：单数据库事务（原子，全部成功或全部回滚）**
1. **签署证据持久化**：将 signoff（signoff_tag、change_order、attestation、envelope_hash、signed_at、effective_from/until）写入 `catalog_signoffs` 表。
2. **manifest revision 不可变写入**：将 manifest 完整内容（含 manifest_hash）写入 `catalog_manifests` 表，状态为 `pending_activation`。
3. **CAS 切换 active pointer**：使用 `UPDATE catalog_active_manifests SET revision=? WHERE profile_id=? AND revision=?` 原子切换。
4. **写入 outbox 事件**：将 `cache_invalidate` 和 `git_archive` 事件写入 `catalog_outbox` 表（同一事务）。

以上 4 步在**单个数据库事务**中完成，任一步失败则整体回滚，不产生部分生效的 revision。

**阶段二：异步 outbox 重试（不阻塞运行时）**
5. **缓存失效**：outbox consumer 读取 `cache_invalidate` 事件，通过 pub/sub 通知所有 Resolver 实例失效缓存。失败则指数退避重试。
6. **git 归档**：outbox consumer 读取 `git_archive` 事件，将 manifest.json 和 pack 定义提交到 git。失败则重试，超过最大重试次数标记为 `archive_failed` 并告警。

**状态与服务可用性**：
- 事务提交后 revision 状态为 `active`，**运行时立即提供服务**（Resolver 从数据库读取新 revision）。
- git 归档成功后状态更新为 `fully_signed`。
- 归档失败时状态为 `active_archive_pending`，运行时正常服务，但审计标记未完成，需人工介入。**归档失败不影响运行时可用性，但影响合规审计完整性。**

**发布状态机**：`draft` → `pending_activation` →（事务提交）`active` →（归档成功）`fully_signed` /（归档失败）`active_archive_pending`。

### 2.5 Metric 权威来源（D-01 闭合）[PROPOSAL]

**选定方案（评审后冻结）：Phase 1 使用独立 Metrics 服务（metrics.html）作为 metric 权威源。**
- Ontology 扩展 metric projection 为 **Phase 2+ 评估方向**，若采用需重新签署 manifest（因为权威源变更影响所有 metric 的 content_hash 和生命周期）。
- Phase 1 中 metric 的编辑、hash 计算、生命周期管理均由 Metrics 服务负责，Catalog 只注册引用。
- entity_type/relation_type 仍由 Ontology 负责（pull 同步），与 metric 解耦。

**metric kind 的 canonical input**（用于 content_hash 计算）：

```json
{
  "metric_schema_version": "catalog-metric/v1",
  "stable_id": "coal.raw_coal_output",
  "version": "1.0.0",
  "value_semantics": {
    "measurement_type": "continuous_flow",
    "unit_ref": {"kind": "unit", "stable_id": "common.mass.tonne", "version": "1.0.0"},
    "aggregation_ref": {"kind": "aggregation", "stable_id": "common.agg.daily_avg", "version": "1.0.0"},
    "time_window_ref": {"kind": "time_window_schema", "stable_id": "common.time.shift", "version": "1.0.0"}
  },
  "semantic_schema_version": "catalog-metric/v1",
  "compatibility_metadata": {"coal_seam_type": "all"}
}
```

> **决策点 B（已确认）**：长期方向为 Ontology 扩展 metric projection，但 Ontology metric projection 目前仅为"希望做"的假设，无明确人和排期。**Phase 1 采用独立 Metrics 服务（metrics.html）作为 metric 权威源**（即原降级预案升级为 Phase 1 实施方案）。09-15 检查点评估 Ontology 进展，若成熟则 Phase 2 评估迁移。迁移不改变 Resolver 契约（metric kind 的 resolve/validate 接口不变），仅切换权威服务和同步方式。详见 §2.9.1 权威源矩阵。

### 2.6 各 kind canonical input 与 hash（D-02 闭合）[FROZEN]

正式 Schema：`arch/catalog/schemas/catalog-kinds.schema.json`（10 种 kind 的 canonical input schema，additionalProperties:false，字段白名单、必填性、排序键已定义）。
Golden Hash：`arch/catalog/schemas/golden-hashes.json`（每种 kind 至少一组 canonical JSON + SHA-256，用于跨服务 hash 一致性校验）。
生成脚本：`arch/catalog/scripts/generate_golden_hashes.py`。

**hash producer trust model（FROZEN，评审后统一为双重校验）**：
- 每种 kind 的 content_hash 由其**权威服务**（§2.9.1）在对象保存时计算并持久化。
- Catalog 引用注册时：从权威服务 API 获取 canonical input + 权威 hash，**独立复算 hash 并与权威 hash 比对**。一致则保存；不一致则拒绝注册并告警（防止源系统 hash 算法错误或数据篡改）。
- Catalog **不信任客户端传入的 hash**，只信任权威服务 API 返回的 hash，且必须通过独立复算验证。
- Resolver 运行时校验：数据库中条目的 content_hash 必须与 manifest 中记录的一致，不一致 fail closed。
- hash 算法统一为：canonical input → canonicalize()（NFC + sort_keys + null 移除 + 数字归一化）→ SHA-256，详见 `generate_golden_hashes.py`。

| kind | 默认 owner 角色（可配置） | canonical input 字段（schema 中定义） | hash 算法 |
|---|---|---|---|
| `data_domain` | 数据域负责人 | kind, stable_id, version, domain_id, semantic_schema_version, name, description | sha256/canonical-json/v1 |
| `entity_type` | 数据域负责人 | kind, stable_id, version, entity_type_id, name, kind_type, data_domain_id, semantic_schema_version, description, attributes | sha256/canonical-json/v1 |
| `relation_type` | 数据域负责人 | kind, stable_id, version, relation_type_id, name, source_type, target_type, cardinality, semantic_schema_version, description | sha256/canonical-json/v1 |
| `metric` | 数据域负责人 | kind, stable_id, version, metric_id, name, data_domain_id, semantic_schema_version, description, value_semantics | sha256/canonical-json/v1 |
| `unit` | 平台架构 | kind, stable_id, version, unit_id, name, symbol, dimension, description | sha256/canonical-json/v1 |
| `aggregation` | 平台架构 | kind, stable_id, version, aggregation_id, name, formula_type, custom_formula, description | sha256/canonical-json/v1 |
| `time_window_schema` | 平台架构 | kind, stable_id, version, window_id, name, duration, alignment, shift_definition, description | sha256/canonical-json/v1 |
| `binding_template` | 平台架构 | kind, stable_id, version, template_id, name, description, params_schema | sha256/canonical-json/v1 |
| `capability_contract` | 平台架构 | kind, stable_id, version, capability_id, name, role, input_schema, output_schema, description | sha256/canonical-json/v1 |
| `rule_schema` | 平台架构 | kind, stable_id, version, rule_id, name, algorithm_profile, params_schema, description | sha256/canonical-json/v1 |

**排序键**：集合按 §2.3 路径感知策略表排序，非集合数组保持原顺序。集合复合键重复时拒绝输入。
**null/缺省规则**：对象中的 optional 字段为 null 或空字符串时省略（等同缺省）；**数组元素完整保留**，包括 null 和空字符串（JSON Schema enum 可合法包含 null/""）。数组为空数组 `[]` 时写入。
**Canonicalizer 版本分派（FROZEN）**：当前算法冻结为 `sha256/canonical-json/v1`。`canonical_json(obj, schema_version=...)` 根据 schema 版本（如 `catalog-manifest/v1`）查 `SCHEMA_CANONICALIZER_MAP` 分派到对应实现；未知版本拒绝。未来破坏性变更创建 `/v2` schema 和 `canonicalize_v2()`，旧 payload 永不重算。`validate_fixtures.py` 必须按 fixture 的 `manifest_schema_version`/`attestation_schema_version` 选择算法。

> **owner 可配置原则（决策点 C 已确认）**：上表"默认 owner 角色"是系统出厂建议，具体每 kind 审批人由 RBAC + Profile 角色绑定动态配置，不在开发时定死。

### 2.7 JQMK 生产域初始引用清单 [PROPOSAL / 待领域确认]

以下条目是 JQMK 项目从各源系统**引用注册**到 Catalog 的第一个实例，用于验证 Catalog 引用治理全链路。**Catalog 不创建语义定义，只注册对源系统对象的引用（stable_id + version + content_hash + status）。** 所有 stable_id、version、content_hash 均为占位，需隋昕航确认源系统对象后填入真实值。

**各 kind 的源系统映射（单一数据源）：**

| kind | 语义定义所在源系统 | Catalog 做什么 |
|---|---|---|
| `data_domain` | EARP 平台域配置 | 注册引用 |
| `entity_type` | Ontology | 注册引用 |
| `relation_type` | Ontology | 注册引用 |
| `metric` | Metrics 服务（metrics.html） | 注册引用 |
| `unit` | EARP 平台基础配置（出厂最小集） | 出厂自带 + 注册引用 |
| `aggregation` | EARP 平台基础配置（出厂最小集） | 出厂自带 + 注册引用 |
| `time_window_schema` | EARP 平台基础配置（出厂最小集） | 出厂自带 + 注册引用 |
| `binding_template` | 模型/能力配置平台 | 注册引用 |
| `capability_contract` | 能力配置平台 | 注册引用 |
| `rule_schema` | EARP 平台基础配置（出厂最小集） | 出厂自带 + 注册引用 |

> 编辑只能在源系统进行：实体/关系在 Ontology 编辑，能力合同在能力平台编辑，基础单位/聚合/规则在 EARP 平台配置。Catalog 只做引用注册、版本锁定、组合和治理。详见 §2.9。

#### 2.7.1 data_domain（1 项）

| stable_id | version | data_domain_id | semantic_schema_version |
|---|---|---|---|
| `jqmk.production` | `1.0.0` | `production` | `catalog-domain/v1` |

#### 2.7.2 entity_type（5 项）

| stable_id | version | 说明 | semantic_schema_version |
|---|---|---|---|
| `coal.mine` | `1.0.0` | 矿井 | `catalog-entity/v1` |
| `coal.working_face` | `1.0.0` | 工作面 | `catalog-entity/v1` |
| `coal.shearer` | `1.0.0` | 采煤机 | `catalog-entity/v1` |
| `coal.conveyor` | `1.0.0` | 运输机 | `catalog-entity/v1` |
| `coal.production_output` | `1.0.0` | 原煤产量（观测实体） | `catalog-entity/v1` |

#### 2.7.3 relation_type（4 项）

| stable_id | version | source → target | semantic_schema_version |
|---|---|---|---|
| `coal.mines` | `1.0.0` | coal.mine → coal.working_face | `catalog-relation/v1` |
| `coal.extracts` | `1.0.0` | coal.working_face → coal.production_output | `catalog-relation/v1` |
| `coal.equips` | `1.0.0` | coal.working_face → coal.shearer | `catalog-relation/v1` |
| `coal.transports` | `1.0.0` | coal.shearer → coal.conveyor | `catalog-relation/v1` |

#### 2.7.4 metric（4 项）

| stable_id | version | unit | aggregation | time_window | semantic_schema_version |
|---|---|---|---|---|---|
| `coal.raw_coal_output` | `1.0.0` | common.mass.tonne | common.agg.daily_total | common.time.shift | `catalog-metric/v1` |
| `coal.effective_production_hours` | `1.0.0` | common.time.hour | common.agg.daily_total | common.time.day | `catalog-metric/v1` |
| `coal.equipment_availability` | `1.0.0` | common.ratio.percent | common.agg.daily_avg | common.time.shift | `catalog-metric/v1` |
| `coal.face_advance_rate` | `1.0.0` | common.length.meter_per_shift | common.agg.shift_avg | common.time.shift | `catalog-metric/v1` |

#### 2.7.5 unit（4 项）

| stable_id | version | 说明 |
|---|---|---|
| `common.mass.tonne` | `1.0.0` | 吨 |
| `common.time.hour` | `1.0.0` | 小时 |
| `common.ratio.percent` | `1.0.0` | 百分比 |
| `common.length.meter_per_shift` | `1.0.0` | 米/班 |

#### 2.7.6 aggregation（3 项）

| stable_id | version | 说明 |
|---|---|---|
| `common.agg.daily_total` | `1.0.0` | 日累计 |
| `common.agg.daily_avg` | `1.0.0` | 日均 |
| `common.agg.shift_avg` | `1.0.0` | 班均 |

#### 2.7.7 time_window_schema（2 项）

| stable_id | version | 说明 |
|---|---|---|
| `common.time.shift` | `1.0.0` | 班次（早/中/夜） |
| `common.time.day` | `1.0.0` | 自然日 |

#### 2.7.8 binding_template（2 项）

| stable_id | version | 说明 | params schema |
|---|---|---|---|
| `coal.equipment_binding` | `1.0.0` | 设备→工作面绑定 | `catalog-binding/v1` |
| `coal.metric_evidence_binding` | `1.0.0` | 指标→证据需求绑定 | `catalog-binding/v1` |

#### 2.7.9 capability_contract（1 项）

| stable_id | version | role | input schema | output schema |
|---|---|---|---|---|
| `coal.production_forecast` | `1.0.0` | primary | `catalog-capability-input/v1` | `catalog-capability-output/v1` |

#### 2.7.10 rule_schema（1 项）

| stable_id | version | algorithm_profile |
|---|---|---|
| `common.rule.sign_propagation_v1` | `1.0.0` | `sign-propagation/v1` |

**初始引用合计：27 项**（1 domain + 5 entity + 4 relation + 4 metric + 4 unit + 3 aggregation + 2 time_window + 2 binding + 1 capability + 1 rule）。

> **定位说明（决策点 D 已确认）**：这 27 项是 **JQMK 项目从各源系统引用注册到 Catalog 的第一个实例**，用于验证 Catalog 引用治理框架能跑通，**不是 EARP 出厂默认，也不是在 Catalog 里创建的语义定义**。语义定义在各源系统编辑，Catalog 只注册引用、锁定版本、组合 pack、生成 manifest。详见 §2.8 和 §2.9。

### 2.8 产品化 Catalog 能力 [PROPOSAL]

EARP 是产品，Catalog 是产品的一项功能，不是为单个项目预配的交付物。用户应能根据项目需要和需求变化，在平台上配置"菜单"，而不是出厂前固定。

#### 2.8.1 出厂最小基础 pack

EARP 出厂自带 `platform-base` pack 的最小集，覆盖跨行业语义一致的基础定义。**冻结为 10 项**（与 §4.3 和 golden hash 一致）：

| kind | 出厂最小集 | 数量 |
|---|---|---|
| `unit` | 吨、小时、百分比、米/班 | 4 |
| `aggregation` | 日累计、日均、班均 | 3 |
| `time_window_schema` | 班次、自然日 | 2 |
| `rule_schema` | sign_propagation_v1 | 1 |

- 出厂最小集**可在平台上扩展**（新增条目），但出厂条目的修改走审批流程，产生新版本。
- 出厂条目的 `stable_id` 采用 `common.*` 命名空间，与用户自定义条目区分。
- 出厂条目同样有 version 和 content_hash，修改即产生新版本，不原地覆盖。
- 项目可在出厂最小集基础上新增自定义条目，不修改出厂条目本身。

#### 2.8.2 平台能力

EARP 提供 Catalog 管理后台（UI + API），用户可：

1. **统一查看**：从 Ontology、Metric、能力平台等源系统聚合语义对象，按 kind/domain/status 统一浏览和搜索（只读视图，不编辑语义）
2. **引用注册管理**：从源系统选择对象，注册引用到 Catalog，锁定版本和 content_hash；源系统发布新版本时 Catalog 提示可升级，用户选择是否采用
3. **pack 管理**：创建行业 pack/企业 pack，向 pack 中添加已注册的引用，发布 pack 版本，导出/导入 `.earppack`
4. **manifest 管理**：选择生效的 pack 组合，平台自动生成 effective manifest、计算 manifest_hash、触发签署
5. **生命周期管理**：引用 active/deprecated/inactive 状态流转、撤销、LKG 策略配置
6. **审批履约**：CatalogChangeRequest 的申请-审批-履约全流程（Phase 0 已签状态机）

**产品页面清单**（详细设计见 `2026-09-01-catalog-product-pages-design.md`）：

| 页面 | 功能 | 优先级 |
|---|---|---|
| `catalog-admin.html` | 治理中心：统一查看/引用注册/pack 管理/manifest 管理/审批中心（5 Tab） | P0 |
| `profiles.html` | 项目配置：scope/角色绑定/变更单 | P0 |
| `metrics.html` | 指标管理：metric 语义定义 | P0 |
| `catalog-basics.html` | 基础配置：unit/aggregation/time_window/rule_schema（4 Tab） | P0 |
| `binding-templates.html` | 绑定模板：params_schema 可视化编辑 | P1 |

> 已有源系统页面不变：`tbox.html`（entity_type + relation_type）、`data-domains.html`（data_domain）、`capabilities.html`（capability_contract）。

引用注册流程：

```
源系统（Ontology/能力平台等）发布对象新版本
    → Catalog 同步/拉取新版本元数据（§2.9）
    → 用户在 Catalog 统一查看中选择对象，注册引用（锁定 version + hash）
    → 引用进入对应 pack → pack 发布新版本
    → 用户选择 pack 组合 → 平台生成 effective manifest revision
    → manifest_hash 计算 → 签署 → Resolver 加载生效
```

> **单一数据源原则**：语义定义的编辑只在源系统进行。Catalog 不提供 entity/relation/metric/capability 的语义编辑功能，只提供引用注册和治理。出厂基础 pack（unit/aggregation/time_window/rule_schema）的编辑在 EARP 平台基础配置中进行，Catalog 注册引用。

#### 2.8.2.1 权限与审批 [PROPOSAL]

所有 pack 和条目的修改都受权限控制和审批流程约束，不是任何人都能改。**权限复用 EARP 已有的 RBAC 可配置能力**，不新增细粒度权限码：

- 基础权限沿用 Phase 0 已签署的 `ecmc.catalog.read` / `ecmc.catalog.request` / `ecmc.catalog.approve`。
- pack 级操作（修改、发布、导出、导入）通过 EARP 角色-权限绑定配置控制，由平台管理员在权限管理后台分配，不硬编码新权限码。
- 出厂基础 pack 的修改权限默认绑定平台架构负责人角色；行业/企业 pack 的修改权限默认绑定对应 pack owner 角色。

**审批流程：**

1. **条目级**：新增/修改条目 → 提交 CatalogChangeRequest → 对应 kind owner 审批（`approved_pending_fulfillment`）→ 目录服务激活（`fulfilled`）。这是 Phase 0 已签署的状态机，不可绕过。
2. **pack 级**：pack 内容变更（增删条目）→ pack owner 审批 → 发布 pack 新版本（version+1）→ 旧版本归档。
3. **manifest 级**：切换生效的 pack 组合 → 平台架构负责人审批 → 生成新 manifest revision → 签署 → Resolver 加载。
4. **出厂基础 pack 修改**：需平台架构负责人审批 + 变更单记录，修改后引用该条目的项目在下次 manifest 生成时可选择是否采用新版本（不强制升级）。

**防越权：**
- 无权限用户的修改请求直接拒绝（403），不进入审批流。
- 审批人不能审批自己提交的申请（separation-of-duties）。
- 所有修改操作进入 audit_logs，记录 actor/role/操作对象/前后版本/时间。

#### 2.8.3 pack 下载与经验资产沉淀

pack 支持**导出下载**和**导入**，作为经验资产在项目间复用：

- **导出**：将一个 pack（含全部条目 canonical input、version、hash、owner 信息）打包为可下载文件（建议格式：`.earppack` = ZIP + manifest.json + entries/）
- **导入**：在新项目中导入 pack 文件，平台校验 hash 和 schema，条目进入草稿状态，经 owner 确认后激活
- **版本兼容**：导入时检查 pack 的 `pack_schema_version` 和 `industry_scope`，不兼容则拒绝或提示迁移
- **资产市场（远期）**：可扩展为 pack 资产市场，行业最佳实践 pack 可共享复用

> 类比：就像 VS Code 的插件包、Docker 的镜像、Figma 的组件库——做好一个行业的 Catalog pack，可以导出给同行业其他项目直接用，不用从零配。

#### 2.8.4 对 Phase 1 的影响

Phase 1 的重点从"为 JQMK 配好 27 个条目"调整为：

1. **做出 Catalog 引用治理功能的最小可用版**（统一查看 + 引用注册 + pack 管理 + manifest 自动生成）
2. **用 JQMK 的 27 个引用作为第一个注册实例**，验证源系统同步→引用注册→生成 manifest→Resolver 加载全链路
3. **出厂基础 pack 最小集**随产品发布（unit/aggregation/time_window/rule_schema），可在 EARP 平台基础配置中修改
4. **pack 导出/导入**作为 Phase 1 可交付能力（至少支持导出，导入可 Phase 2）

contract vectors 也分两层：
- **框架级向量**（产品自带）：验证 Resolver 接口、错误处理、hash 一致性、生命周期——不依赖具体引用
- **实例级向量**（JQMK 注册产生）：验证 27 个具体引用的 resolve/validate——随注册实例生成

### 2.9 源系统与同步机制 [PROPOSAL]

Catalog 遵循单一数据源原则：语义定义在源系统编辑，Catalog 只注册引用和治理。因此需要定义 Catalog 与各源系统的同步机制。

#### 2.9.1 kind 权威源矩阵（FROZEN）

每种 kind 有且仅有一个权威编辑入口和权威服务。Catalog 只从权威服务拉取引用，不提供语义编辑。

| kind | 权威服务 | 编辑页面 | API owner | hash producer | 生命周期 owner | 同步方式 |
|---|---|---|---|---|---|---|
| `data_domain` | EARP 数据域服务 | `data-domains.html` | 平台架构 | 数据域服务 | 平台架构 | 本地直接引用 |
| `entity_type` | Ontology | `tbox.html` | 数据域负责人 | Ontology 服务 | 数据域负责人 | pull 定时同步 |
| `relation_type` | Ontology | `tbox.html` | 数据域负责人 | Ontology 服务 | 数据域负责人 | pull 定时同步 |
| `metric` | **Metrics 服务** | `metrics.html` | 数据域负责人 | Metrics 服务 | 数据域负责人 | 本地直接引用 |
| `unit` | EARP 基础配置服务 | `catalog-basics.html` | 平台架构 | 基础配置服务 | 平台架构 | 本地直接引用 |
| `aggregation` | EARP 基础配置服务 | `catalog-basics.html` | 平台架构 | 基础配置服务 | 平台架构 | 本地直接引用 |
| `time_window_schema` | EARP 基础配置服务 | `catalog-basics.html` | 平台架构 | 基础配置服务 | 平台架构 | 本地直接引用 |
| `rule_schema` | EARP 基础配置服务 | `catalog-basics.html` | 平台架构 | 基础配置服务 | 平台架构 | 本地直接引用 |
| `binding_template` | **绑定模板服务** | `binding-templates.html` | 平台架构 | 绑定模板服务 | 平台架构 | 本地直接引用 |
| `capability_contract` | EARP 能力服务 | `capabilities.html` | 平台架构 | 能力服务 | 平台架构 | 本地直接引用 |

> **关于 metric 的说明**：决策点 B 选定"Ontology 扩展 metric projection"为长期方向，但 Ontology metric projection 目前仅为"希望做"的假设，无明确人和排期。**Phase 1 metric 的权威源是 Metrics 服务（metrics.html）**，不是 Ontology。metrics.html 是 Metrics 服务的前端入口，不是第二套 Metrics Catalog。Ontology 扩展成熟后（Phase 2+），可评估将 metric 权威源迁移到 Ontology，届时需重新签署。

> **hash producer 原则（双重校验，FROZEN）**：每种 kind 的 content_hash 由其权威服务在对象保存时计算并持久化。Catalog 引用注册时从权威服务获取 canonical input + 权威 hash，**独立复算并比对**，一致才保存；不一致则拒绝并告警。Catalog 不信任客户端传入的 hash。权威服务的 hash 算法必须与 §2.6 canonical input 定义一致。

#### 2.9.2 同步机制

**推荐：pull 为主 + webhook 为辅**

1. **pull 定时同步**：Catalog 每小时（可配置）从各源系统拉取最新对象列表和版本，更新本地引用索引（不复制语义定义，只存 stable_id/version/content_hash/status/源系统链接）。
2. **webhook 通知**：源系统发布新版本时，向 Catalog 发送 webhook，Catalog 立即拉取该对象的最新版本，缩短同步延迟。
3. **content_hash 双重校验**：Catalog 从源系统拉取对象的 canonical input + 权威 hash，按 Canonicalization 契约独立复算 SHA-256，与权威 hash 比对一致后保存为引用的 content_hash。
4. **版本提示**：源系统发布新版本后，Catalog 在统一查看中标记"有新版本可用"，用户选择是否升级引用（不自动升级，避免破坏已锁定的 manifest）。

#### 2.9.3 引用注册与锁定

- 用户在 Catalog 统一查看中浏览源系统对象，选择某个版本进行**引用注册**。
- 注册时 Catalog 锁定该版本的 `stable_id + version + content_hash`，写入 pack。
- 源系统后续修改不影响已注册引用（版本不可变原则）。
- 用户可主动升级引用到新版本，升级产生 pack 新版本和 manifest 新 revision。

#### 2.9.4 源系统不可用时的行为

- 同步失败：Catalog 保留已有引用索引，记录同步告警，不影响已注册引用的 Resolver 解析。
- 源系统长时间不可用：新引用注册暂停，已有引用继续服务（fail closed 仅针对未注册/已撤销的引用）。
- **源对象拉取缺失（FROZEN）**：普通 pull 同步中源系统未返回某对象时，**不得自动标记为 inactive**。仅标记为 `suspected_missing` 并触发告警，因为无法区分真实删除、分页错误和同步故障。
  - 必须由权威服务发送 **tombstone/revoke 事件**（含对象 ID、版本、原因、时间戳），或经人工审批，才能将引用标记为 inactive。
  - `suspected_missing` 状态的引用继续服务（LKG），但在统一查看中标黄，提示管理员核实。
  - 连续 3 次同步周期（可配置）仍缺失时，升级告警，要求人工确认。
  - **新 manifest 生成时拒绝 suspected_missing 条目**（FROZEN）：suspected_missing 是同步索引的运行状态，不是正式签署状态。生成新 manifest 时，suspected_missing 条目不得进入 entries；已有 manifest 可继续 LKG 服务，但修订时必须先解决 suspected 状态（确认恢复→active，或确认删除→inactive 后排除）。

#### 2.9.5 对 Phase 1 的影响

- Phase 1 需实现 Ontology 的 pull 同步（最核心的源系统）和 EARP 平台基础配置的本地引用。
- 能力/模型配置平台的同步可 Phase 2 实现（Phase 1 可手动注册 binding_template/capability_contract 的引用）。
- webhook 通知可 Phase 2 实现，Phase 1 先用定时 pull。

### 2.10 源系统编辑页面规划 [PROPOSAL / 已确认]

Catalog 遵循单一数据源原则：6 种暂无编辑页面的 kind 需要先建源系统编辑页，Catalog 再从这些页面同步引用。经分析现状（§2.9.1），确认按复杂度分 3 个页面，导航放在"知识中心"下新增"目录管理"分组。

#### 2.10.1 页面总览

| 页面 | 管理的 kind | 复杂度 | 导航位置 |
|---|---|---|---|
| `metrics.html` | `metric` | 中 | 知识中心 → 目录管理 → 指标管理 |
| `catalog-basics.html` | `unit`、`aggregation`、`time_window_schema`、`rule_schema` | 低 | 知识中心 → 目录管理 → 基础配置 |
| `binding-templates.html` | `binding_template` | 中高 | 知识中心 → 目录管理 → 绑定模板 |

> 已有源系统页面不变：`data-domains.html`（data_domain）、`tbox.html`（entity_type + relation_type）、`capabilities.html`（capability_contract）。

#### 2.10.2 指标管理（metrics.html）

**功能范围**：指标的增删改查、版本管理、停用/恢复、关联 unit/aggregation/time_window。

**核心字段**：

| 字段 | 说明 |
|---|---|
| `metric_id` | 稳定 ID（小写英文/下划线，创建后不可改） |
| `name` | 显示名称 |
| `description` | 业务语义描述 |
| `data_domain_id` | 所属数据域 |
| `unit_ref` | 关联单位（从基础配置选择） |
| `aggregation_ref` | 关联聚合方式（从基础配置选择） |
| `time_window_ref` | 关联时间窗口（从基础配置选择） |
| `owner` | 负责人 |
| `status` | active / deprecated |
| `version` | 语义版本（修改即新版本） |

**操作**：新建、编辑（产生新版本）、停用、恢复、查看版本历史。

**后端 API**：`/v1/metrics`（CRUD + deprecate）。

#### 2.10.3 基础配置（catalog-basics.html）

**功能范围**：4 种简单参考数据的统一管理，页面内按 Tab 切换 kind。

**各 kind 核心字段**：

| kind | 核心字段 | 说明 |
|---|---|---|
| `unit` | unit_id, name, symbol, dimension | 单位（吨、小时、百分比等） |
| `aggregation` | aggregation_id, name, formula_type | 聚合方式（日均、月累计等） |
| `time_window_schema` | window_id, name, duration, alignment | 时间窗口（班次、日、月） |
| `rule_schema` | rule_id, name, algorithm_profile, params_schema | 规则模式（sign_propagation_v1 等） |

**操作**：新建、编辑、停用、恢复。出厂最小集随产品发布，可在平台上修改（走审批）。

**后端 API**：`/v1/catalog-basics/{kind}`（统一 CRUD，kind 为路径参数）。

#### 2.10.4 绑定模板（binding-templates.html）

**功能范围**：绑定模板的增删改查、params_schema 编辑、版本管理。

**核心字段**：

| 字段 | 说明 |
|---|---|
| `template_id` | 稳定 ID |
| `name` | 显示名称 |
| `description` | 用途说明 |
| `params_schema` | JSON Schema，定义绑定参数（含 ref 类型引用其他 kind） |
| `owner` | 负责人 |
| `status` | active / deprecated |
| `version` | 语义版本 |

**操作**：新建、编辑（params_schema 可视化编辑器 + JSON 预览）、停用、恢复、查看被哪些模型引用。

**后端 API**：`/v1/binding-templates`（CRUD + deprecate + usage 查询）。

#### 2.10.5 与 Catalog 的关系

```
用户在源系统页面编辑语义定义（metrics / catalog-basics / binding-templates）
    → 源系统发布新版本
    → Catalog 定时 pull 同步（§2.9.2）
    → 用户在 Catalog 统一查看中选择版本，注册引用
    → 引用进入 pack → 生成 manifest → Resolver 加载
```

- 源系统页面是**唯一编辑入口**，Catalog 不提供这些 kind 的语义编辑。
- Catalog 的"统一查看"聚合所有 10 种 kind（含已有源系统的 4 种和新增 3 个页面的 6 种），提供只读浏览和引用注册。
- 目录选择器（`ecmc-catalog-picker.js`）从 Catalog Resolver 读取 active 引用，不再使用硬编码 mock 数据。

#### 2.10.6 Phase 1 实现优先级

| 优先级 | 页面 | 原因 |
|---|---|---|
| P0 | `catalog-basics.html` | 4 种基础参考数据是 metric 和模型的依赖，必须先有 |
| P0 | `metrics.html` | JQMK 27 引用中 4 个 metric，是核心业务对象 |
| P1 | `binding-templates.html` | Phase 1 可先用静态模板，页面可稍晚 |
| P2 | 目录选择器去 mock | 等源系统页面和 Catalog 同步跑通后替换 |

### 2.11 Profile 管理页面规划 [PROPOSAL / 已确认]

Profile 是项目级配置（当前为手写 YAML），产品化后需做成平台可配置页面。Phase 1 一起实现。

**Profile Schema v2（评审后升级，FROZEN）**：
- v1（`catalog-profile/v1`）：仅用于读取 Phase 0 已签署的历史实例，不再用于新配置。
- v2（`catalog-profile/v2`）：Phase 1 及以后所有 Profile 使用 v2。变更点：
  1. `data_domains`（数组）→ `data_domain`（单值），一 Profile 一 domain。
  2. `roles`（硬编码 6 个角色的 object）→ `roles`（可配置数组，每项含 role_key/name/team/contact）。
  3. 新增 `backup_approver`（候补审批人角色 key，SoD 应急路由）。
- v1→v2 迁移：`data_domains[0]` → `data_domain`；roles object 转为数组（key→role_key）；`backup_approver` 默认填 `audit_compliance_owner`（若不存在则要求手动配置）。
- Schema 文件：`arch/catalog/schemas/catalog-profile-v2.schema.json`；JQMK Profile 已迁移为 v2。

#### 2.11.1 页面与导航

| 页面 | 功能 | 导航位置 |
|---|---|---|
| `profiles.html` | 项目配置列表 + 新建/编辑 | 知识中心 → 目录管理 → 项目配置 |

> "目录管理"分组下共 4 个页面：项目配置（profiles）、指标管理（metrics）、基础配置（catalog-basics）、绑定模板（binding-templates）。

#### 2.11.2 可配置字段

| 字段 | 配置控件 | 说明 |
|---|---|---|
| `industry_scope` | 下拉选择 | 行业（coal_mining 等） |
| `enterprise_scope` | 文本输入 | 企业（SDRH） |
| `tenant_id` | 文本输入 | 租户（JQMK） |
| `data_domain` | 单选 | **一 Profile 一 domain**（FROZEN）。从数据域列表选择一个（生产域/安全域/设备域）。多 domain 项目创建多个 Profile，每个 domain 独立治理和签署 |
| `roles` | 可配置角色列表 | 项目自定义角色名称和数量（不硬编码 6 个），每个角色绑定人员；一人可兼任多角色。JQMK 当前配置为 6 个角色（产品/平台架构/数据域/安全/审计合规/运行平台），小项目可只配 2-3 个 |
| `change_orders` | 文本输入 | 变更单号 + 发布单号 |
| `record_keeper` | 人员选择器 | 记录保管人 |

**系统自动生成（不可手动编辑）：**
- `profile_id`：由 `{tenant}-{industry}-{domain}` 自动生成
- `catalog_profile_id`：由 `{industry}.{enterprise}.{tenant}.{domain}` 自动生成
- `schema_version` / `template_contract_version`：固定值
- `pack_lock`：由 pack 管理流程自动填入，Profile 页只展示不编辑

#### 2.11.3 与 RBAC 的分工（角色可配置原则）

- **系统只定义权限点**：Catalog 定义 `ecmc.catalog.read` / `request` / `approve` / `manifest.publish` 等权限点，不定义固定角色。
- **角色由项目自定义**：项目在 EARP RBAC 中创建角色（可叫"产品负责人""项目总监""运维"等），把 Catalog 权限点绑到角色上，再把人绑到角色上。数量和名称不限，一人可兼任多角色。
- **Profile roles 记录责任绑定**：Profile 里的 roles 列表记录"这个项目用了哪些角色、每个角色谁来填"，用于签署路由、审批人确定、审计追溯。它是 RBAC 角色绑定的项目级快照，不是独立的权限体系。
- **Profile schema v2**：将 `roles` 从固定 6 个属性改为可配置数组（`role_key` + `name` + `team` + `contact`）。v1（JQMK 已签）保持不动，后续可迁移。

#### 2.11.4 存储与生效

- Profile 保存后平台自动生成 YAML，提交到 git 受控目录 `arch/catalog/profiles/`（权威存储已签=git）。
- 新建 Profile 后状态为 `draft`，完成角色绑定和 pack 组合后可签署生效。
- Profile 修改产生新版本，已生效的 manifest 绑定旧版本，不自动升级（版本不可变原则）。

#### 2.11.5 Phase 1 实现范围

- Profile 列表页 + 新建/编辑表单
- 自动生成 profile_id / catalog_profile_id
- 角色绑定的人员选择器（复用现有人员数据源）
- 保存后生成 YAML 并提交 git
- pack_lock 展示区域（只读，由 pack 管理流程填入）

---

## 3. Resolver contract vectors 设计

### 3.1 设计原则 [FROZEN]

- Resolver 是唯一外部目录边界，N01A 不直接读取目录内部表。
- `resolve`/`validate` 调用方合同已冻结（`CatalogRef={kind,stable_id,version}`，五类错误）。
- contract vectors 是**可执行的测试向量**，不是文档描述：每个 vector 包含输入、预期输出或预期错误、断言条件。
- 所有 vectors 必须在 CI 中自动运行，作为 Phase 1 exit gate 的证据。

### 3.2 resolve 正向向量（每 kind 至少 1 条）

对 §2.7 的 27 个 active entry，每个生成一条 resolve 成功向量：

```text
输入: tenant_id="JQMK", ref={kind="metric", stable_id="coal.raw_coal_output", version="1.0.0"}
预期: ResolvedCatalogRef {
  kind="metric", stable_id="coal.raw_coal_output", version="1.0.0",
  content_hash="<manifest 中声明的 hash>",
  status="active",
  data_domain_id="production",
  semantic_schema_version="catalog-metric/v1",
  compatibility_metadata={...}
}
断言: content_hash 与 manifest entry 逐字节一致
```

正向向量覆盖：每 kind 至少 1 条 active resolve、1 条 deprecated 历史 pin 读取（仅读取，不提供新选择）。

### 3.3 resolve 负向向量（五类错误 + 边界）

| 向量 ID | 输入 | 预期错误 | 断言 |
|---|---|---|---|
| RV-NF-01 | ref 指向不存在的 stable_id | `CATALOG_REF_NOT_FOUND` | 不返回任意候选 |
| RV-IN-01 | ref 指向 status=inactive 的 entry | `CATALOG_REF_INACTIVE` | 新引用被拒绝 |
| RV-IN-02 | ref 指向 status=deprecated 的 entry，用于新 Draft | `CATALOG_REF_INACTIVE` | deprecated 不提供新选择 |
| RV-KM-01 | expected_kind 与 entry kind 不匹配 | `CATALOG_REF_KIND_MISMATCH` | 不静默归一化 |
| RV-DF-01 | tenant_id="OTHER" 访问 JQMK tenant_scoped entry | `CATALOG_REF_DOMAIN_FORBIDDEN` | 跨租户不可见（404 语义） |
| RV-DF-02 | 访问 data_domain_id="safety" 的 entry（当前 profile 仅 production） | `CATALOG_REF_DOMAIN_FORBIDDEN` | 跨数据域拒绝 |
| RV-SI-01 | ref 的 semantic_schema_version 与模型期望不兼容 | `CATALOG_REF_SCHEMA_INCOMPATIBLE` | 不降级兼容 |
| RV-GL-01 | 访问标记 global 的 entry（当前无 global entry） | `CATALOG_REF_DOMAIN_FORBIDDEN` | global 默认拒绝（D-04 关闭证据） |
| RV-EX-01 | version="latest" 或 "*" | `CATALOG_REF_NOT_FOUND` | 模糊版本拒绝 |
| RV-EX-02 | manifest_hash 校验失败（篡改 manifest） | Resolver 启动失败 / fail closed | 不加载未签署 manifest |

### 3.4 validate 批量向量

| 向量 ID | 输入 | 预期 |
|---|---|---|
| VV-OK-01 | 10 个 active refs 批量 validate | 全部 resolved，无 issue |
| VV-MIX-01 | 8 active + 1 inactive + 1 kind_mismatch | 8 resolved，2 个 ValidationIssue 定位到具体 ref |
| VV-CTX-01 | validate 带 context（source/target entity types），relation type 不兼容 | `CATALOG_REF_SCHEMA_INCOMPATIBLE` 定位到 edge |

### 3.5 manifest↔Resolver 投影一致性向量

对 manifest 中每个 entry，Resolver 返回的投影必须与 manifest 声明逐字段一致：

```text
对每个 entry e in manifest.entries:
  resolved = resolve(tenant_id, e.ref)
  断言: resolved.content_hash == e.content_hash
  断言: resolved.status == e.status
  断言: resolved.data_domain_id == e.data_domain_id
  断言: resolved.semantic_schema_version == e.semantic_schema_version
  断言: resolved.input_schema == e.input_schema（若适用）
  断言: resolved.output_schema == e.output_schema（若适用）
  断言: resolved.compatibility_metadata == e.compatibility_metadata
```

**漂移检测向量**：构造一个 manifest 中 content_hash 与 Resolver 实际返回不一致的 entry，断言 Resolver 在加载时阻断该 exact ref 的新引用，并记录漂移告警（不静默归一化）。

### 3.6 生命周期向量

| 向量 ID | 场景 | 预期 |
|---|---|---|
| LV-AC-01 | entry 从 active → deprecated | 历史 Snapshot 可读取 pin，新引用被拒绝 |
| LV-AC-02 | entry 从 active → inactive | 新引用/提交/发布/编译/activation 全部拒绝 |
| LV-AC-03 | entry 修订为新 version（旧 version deprecated） | 旧 version 历史可读，新引用必须用新 version |
| LV-RV-01 | manifest revision 1 → revision 2（entry 新增） | composition root 加载新修订，旧修订归档 |
| LV-RV-02 | manifest 撤销（effective_until 设置） | Resolver 切换为 UnavailableCatalogResolver / fail closed |

### 3.7 跨租户/跨域/global 负向向量（D-04 关闭证据）

| 向量 ID | 场景 | 预期 |
|---|---|---|
| XV-TN-01 | tenant A 访问 tenant B 的 entry | `CATALOG_REF_DOMAIN_FORBIDDEN`（不可见=404） |
| XV-DM-01 | production 域用户访问 safety 域 entry | `CATALOG_REF_DOMAIN_FORBIDDEN` |
| XV-GL-01 | 任何用户访问 global entry（当前 profile 无 global） | `CATALOG_REF_DOMAIN_FORBIDDEN`（global 默认拒绝） |
| XV-GL-02 | 尝试在 manifest 中加入 global entry 但未签署 global scope | manifest 校验失败，不允许加载 |

### 3.8 contract vectors 交付物

- `arch/catalog/contract-vectors/jqmk-production/` 目录下按 kind 组织的 JSON 向量文件；
- CI 任务 `catalog-contract-test` 自动加载 manifest + vectors，调用 Resolver adapter 执行全部断言；
- 测试报告作为 Phase 1 exit gate 证据（§6 映射）。

---

## 4. Catalog Pack 与 pack lock 设计（D-13 闭合）

### 4.1 三层 pack 结构 [PROPOSAL / 产品化]

| 层级 | pack_id | 内容 | 来源 | 修改权限 | 审批要求 |
|---|---|---|---|---|---|
| 平台基础包 | `platform-base` | 跨行业语义一致的基础 unit/aggregation/time_window/rule_schema | **EARP 出厂自带最小集**（§2.8.1），可在平台上扩展 | 通过 EARP RBAC 角色绑定配置（不新增细粒度权限码），默认平台架构负责人角色 | 修改需审批，出厂条目修订需走变更单 |
| 行业包 | `coal-mining-industry` | 煤矿共享的 entity_type/relation_type/metric/binding_template/capability_contract | **用户在平台上配置**，支持导出下载为经验资产 | 通过 EARP RBAC 角色绑定配置，默认行业 owner 角色 | 修改需审批，影响在役 manifest 时需二次确认 |
| 企业扩展包 | `jqmk-enterprise` | JQMK 特有的 entity 分类、指标口径、组织映射 | **用户在平台上配置**，支持导出下载 | 通过 EARP RBAC 角色绑定配置，默认企业 owner 角色 | 修改需审批 |

> 产品化定位：EARP 出厂只带 platform-base 最小集；行业包和企业包是用户在平台上创建的配置数据，可导出为 `.earppack` 在项目间复用（§2.8.3）。**所有 pack 修改均需权限校验和审批流程**，权限复用 EARP 已有 RBAC 可配置能力，不新增 `pack.*.edit` 等细粒度权限码（决策点 I 已确认）。

### 4.2 pack 内容与 version 规则 [PROPOSAL]

每个 pack 是一个目录，包含 `pack.yaml`（元数据）和 `entries/`（各 kind 的 canonical input 文件）：

```yaml
# packs/platform-base/pack.yaml
pack_id: platform-base
layer: platform
version: 1.0.0
industry_scope: null  # platform 层跨行业
owners:
  - role: platform_architect
    name: 隋昕航
entry_kinds: [unit, aggregation, time_window_schema, rule_schema]
```

- **version**：语义化版本 `MAJOR.MINOR.PATCH`。entry 新增=MINOR，entry 语义修订=MAJOR，文档/元数据修正=PATCH。
- **content_hash（FROZEN，评审后统一算法）**：pack content_hash = SHA-256(canonical({pack_id, layer, version, entries: [{kind, stable_id, version, content_hash}]}))。即对 **entry 引用数组**（每条含 kind/stable_id/version/content_hash）计算，不包含各 entry 的完整 canonical input（完整语义定义在源系统/数据库中，pack 只存引用）。entries 按 `(kind, stable_id, version)` 排序。
- **pack 不可变**：已发布 version 不修改；变更发布新 version。

### 4.3 初始 pack 内容映射 [PROPOSAL]

将 §2.7 的 27 个条目按层级分配：

| pack | 包含条目 | 数量 |
|---|---|---|
| platform-base | unit(4) + aggregation(3) + time_window(2) + rule_schema(1) | 10 |
| coal-mining-industry | entity_type(5) + relation_type(4) + metric(4) + binding_template(2) + capability_contract(1) | 16 |
| jqmk-enterprise | data_domain(1) | 1 |

> **决策点 E 已确认**：分层标准——换一个煤矿还适用的概念放行业包，只有 JQMK 特有的放企业包。当前 27 个引用中无明显 JQMK 特化实体，企业包仅含 data_domain（tenant 级概念）。未来若 JQMK 有特化实体/指标口径，在企业包中扩展，不修改行业包的通用定义。

### 4.4 effective manifest 组合与冲突规则 [FROZEN]

- effective manifest = platform-base + coal-mining-industry + jqmk-enterprise 的 entry 并集，按 `(kind, stable_id, version)` 唯一。
- **禁止同版本覆盖（FROZEN）**：同一 effective scope 中出现相同 `(kind, stable_id, version)` 但语义/schema/hash 不同，组合必须 **fail closed**，不允许高层级覆盖低层级。
- **企业定制规则**：企业包如需定制行业包或平台包的条目，**必须使用新的 stable_id 或新的 version**，不得复用同 (kind, stable_id, version) 覆盖语义。示例：行业包定义 `coal.raw_coal_output@1.0.0`，企业包如需不同口径，应定义 `jqmk.raw_coal_output@1.0.0` 或 `coal.raw_coal_output@2.0.0`。
- **完全一致允许共存**：相同 `(kind, stable_id, version)` 且 content_hash 完全一致的条目，在多个 pack 中出现不视为冲突，去重后保留一份。
- **跨行业复用**：只有语义与 hash 都一致的基础条目才允许跨行业复用（platform-base 的 unit/aggregation 等）。
- **新增行业**：不修改 N01A 治理契约；新增行业 pack → 指定 owner → 生成该行业/tenant/data-domain 的 effective manifest → 执行 Resolver contract vectors → 独立签署。

**冲突 contract vectors**（Phase 1 exit 证据）：

| 向量 ID | 场景 | 预期 |
|---|---|---|
| CF-01 | 平台包和行业包含相同 (kind,stable_id,version) 但 hash 不同 | manifest 组合失败，fail closed，返回冲突详情 |
| CF-02 | 行业包和企业包含相同 (kind,stable_id,version) 但 hash 不同 | manifest 组合失败，fail closed |
| CF-03 | 三层 pack 含相同 (kind,stable_id,version) 且 hash 一致 | 组合成功，去重保留一份 |
| CF-04 | 企业包使用新 stable_id 定制行业条目 | 组合成功，企业包条目独立存在 |

### 4.5 pack_lock 填实计划 [PROPOSAL / 产品化]

Phase 0 签署时 pack_lock 的 version/hash 为 null（D-13 OPEN）。产品化后填实方式调整为：

1. **平台基础包**：EARP 出厂自带最小集（§2.8.1），version=`1.0.0`，content_hash 随产品发布计算。JQMK 项目可在平台上扩展或修改，修改产生新版本。
2. **行业包**：JQMK 项目在平台上创建 `coal-mining-industry` pack，配置 16 个煤矿行业条目，发布 v1.0.0，平台自动计算 content_hash。
3. **企业包**：JQMK 项目在平台上创建 `jqmk-enterprise` pack，配置 data_domain，发布 v1.0.0。
4. **生成 effective manifest**：平台组合三层 pack，自动计算 manifest_hash，触发签署，生成 manifest revision 1。

**时间线建议**：
- 09-05：出厂基础 pack 最小集确认（产品发布时自带）
- 09-10：行业 pack 通过平台配置完成并发布
- 09-12：企业 pack 通过平台配置完成并发布
- 09-15：平台生成 effective manifest，签署，Resolver 加载验证

pack_lock 填实后，Profile 的 `pack_lock` 字段需更新 version/hash，**profile_hash 会变化，需重算并重新签署签署实例（r2）**。

---

## 5. 运行门禁证据设计

### 5.1 fake/test endpoint admission 控制（D-08 已签控制目标，D-14 实现证据）[PROPOSAL]

Phase 0 已签署 §8 控制目标。Phase 1 需提供实现证据：

| 控制目标 | 实现方式 | 证据 |
|---|---|---|
| test-only endpoint 不得进入生产 composition root | `FixtureDiscoveryAdapter` 独立类型/注册 key，生产 DI 模块不 import | composition-root 测试断言生产 root 不含 Fixture adapter |
| fake/test catalog 不得被生产 Resolver 加载 | manifest 发布时校验 signoff，未签署的 manifest 不允许激活；Resolver API 每次请求校验 content_hash 与 manifest 记录一致，不一致 fail closed | 发布门禁测试 + API 负向测试（篡改 hash → resolve 拒绝） |
| test endpoint 有独立 admission policy | test profile 显式启用 `allow_fixture_adapter=true`，生产 profile 该参数不存在或为 false | 配置文件 + 配置校验测试 |
| production root 保持 fail-closed | 无有效 manifest 时使用 `UnavailableCatalogResolver` | 集成测试：移除 manifest → resolve 返回不可用 |

**Catalog API 接口定义（Phase 1）**：

| 接口 | 方法 | 用途 | 权限 |
|---|---|---|---|
| `/v1/catalog/resolve` | POST | 批量解析 refs，返回 ResolvedRef（含 content_hash 校验） | ecmc.catalog.read |
| `/v1/catalog/validate` | POST | 批量校验 refs 是否在 active manifest 中且 hash 一致 | ecmc.catalog.read |
| `/v1/catalog/browse` | GET | 按 kind/domain/status 分页浏览已注册引用（统一查看页） | ecmc.catalog.read |
| `/v1/catalog/search` | GET | 关键词搜索引用（stable_id/name/description） | ecmc.catalog.read |
| `/v1/catalog/manifests/active` | GET | 获取当前生效 manifest | ecmc.catalog.read |
| `/v1/catalog/manifests/{id}/revisions` | GET | 列出 manifest 历史 revision | ecmc.catalog.read |
| `/v1/catalog/packs` | GET/POST | pack 列表/创建 | ecmc.catalog.read / ecmc.catalog.request |
| `/v1/catalog/packs/{id}/publish` | POST | 发布 pack 新版本（不可变） | ecmc.catalog.approve |
| `/v1/catalog/change-requests` | GET/POST | 引用注册申请列表/提交 | ecmc.catalog.request |
| `/v1/catalog/change-requests/{id}/approve` | POST | 批准申请（进入 approved_pending_fulfillment） | ecmc.catalog.approve |

### 5.2 FixtureDiscoveryAdapter 隔离（D-12）[PROPOSAL]

- 独立类型 `FixtureDiscoveryAdapter`，与生产 `ActiveModelDiscovery`/`ApiCatalogResolver` 不同注册 key。
- 测试 composition root 显式装配；生产 composition root 不 import 该类型。
- 测试断言：
  1. 生产 root 解析 `CatalogResolver` 得到 `ApiCatalogResolver`（或 `UnavailableCatalogResolver`），不是 `FixtureDiscoveryAdapter`。
  2. Fixture adapter 不能经 N01A activate 或生产 Discovery 成为候选。
  3. `testing`/`published_fixture` 状态的 entry 不出现在生产 active gate。

### 5.3 production root fail-closed 与 test root 隔离 [PROPOSAL]

| 场景 | 生产行为 | 测试行为 |
|---|---|---|
| manifest 未签署/哈希不匹配 | `UnavailableCatalogResolver`，启动失败或运行时 fail closed | 允许 Fixture adapter |
| Resolver adapter identity 不匹配 | 拒绝加载，记录审计 | 允许 test adapter |
| 网络超时/owner 5xx | 返回安全不可用（不猜测修复） | 按 test fixture 返回 |
| inactive entry | 新操作全部拒绝 | 同左（FROZEN 语义测试也必须遵守） |

### 5.4 CI/CD 门禁 [PROPOSAL]

Phase 1 exit 必须通过的 CI 任务：

| CI 任务 | 内容 | 对应 exit gate |
|---|---|---|
| `catalog-schema-check` | Profile schema 校验 + 危险开关负向 | — |
| `catalog-manifest-validate` | manifest schema 校验 + manifest_hash 重算一致 | manifest 签署对象 |
| `catalog-contract-test` | §3 全部 Resolver contract vectors | Resolver 兼容 + 一致性 + 负向 |
| `catalog-frozen-anchor-check` | 签署实例 FROZEN 锚点与模板一致 | FROZEN 语义保护 |
| `catalog-attestation-verify` | attestation blob hash + tag 三项校验 | 不可变证据 |
| `composition-root-test` | 生产 root 不含 Fixture + fail-closed 测试 | D-12/D-14 |
| `lint-openapi-diffcheck` | lint、OpenAPI generation、`git diff --check` | 工程质量 |
| `case-a-regression` | Case A 45 项回归继续通过 | 不回归 |

### 5.5 manifest revision load/rollback/revoke 演练 [PROPOSAL]

- **load（激活）**：manifest 发布签署后，通过 API 激活为当前生效版本。激活时校验 signoff 和 manifest_hash，成功后记录审计。Resolver API 从数据库读取当前生效 manifest。
- **rollback**：通过 manifest 管理 API 将生效版本切换为历史 revision（产生新 revision，内容等于历史版本），Resolver 热加载切换，新引用使用旧修订 entry。不直接修改历史版本。
- **revoke**：通过 API 撤销当前 manifest，Resolver 切换为 `UnavailableCatalogResolver`（fail closed），记录撤销原因/审批/传播。
- **drill evidence**：每次演练记录操作人、时间、前后 manifest_hash、Resolver 状态、审计日志，存入运行手册。

### 5.6 RBAC、SoD 与 audit（D-06）[FROZEN]

Phase 1 基础权限（复用 EARP 已有 RBAC 可配置能力，不新增细粒度权限码；pack 级操作通过角色绑定配置，详见 §2.8.2.1）：

| 权限 | 默认角色 | 说明 |
|---|---|---|
| `ecmc.catalog.read` | 所有认证用户 | 统一查看/resolve active 引用 |
| `ecmc.catalog.request` | 数据域用户 | 提交 CatalogChangeRequest / 引用注册申请 |
| `ecmc.catalog.approve` | 各 kind owner | 批准申请（进入 approved_pending_fulfillment） |
| `ecmc.catalog.manifest.publish` | 平台架构负责人 | 发布 manifest 新 revision |

pack 的修改、发布、导出等操作通过 EARP 角色-权限绑定配置控制，由平台管理员在权限管理后台分配，不硬编码新权限码。

**separation-of-duties（SoD）与应急（FROZEN）**：
- 审批人不能审批自己提交的申请。
- 若唯一审批人也是申请人（小团队一人兼任多角色），系统自动路由到 **候补审批人**（Profile 中配置的 `backup_approver` 角色）。
- **候补审批人主体隔离（FROZEN，运行时检查）**：审批路由时按 **用户 ID**（而非角色名或显示名）校验候补审批人与申请人是不同主体。若 backup_approver 角色绑定的人员与申请人为同一用户 ID，则视为候补不可用，进入 break-glass 流程。Profile 校验器只检查 role_key 存在性，主体隔离由运行时强制执行。
- 若候补审批人也不可用，提供 **break-glass 紧急审批**：需双人确认（申请人 + 另一位管理员），全程审计，事后必须补签正式审批。
- break-glass **仅作为审计标记**（audit_logs 中 `emergency=true`），不新增业务状态。请求经双人授权后仍进入 `approved_pending_fulfillment`，遵循正常状态机。

**audit（Phase 1 冻结基础规则）**：
- 复用 `audit_logs`，记录字段：actor、role、correlation_id、resource_type、resource_id、operation、before_hash、after_hash、status、timestamp、approval_id。
- 不记录：凭据、endpoint、原始业务数据、请求体。
- 留存期：Phase 1 不少于 180 天（合规要求，Phase 2 可调整）。
- 访问权限：审计日志仅审计合规角色可查，不可删除（append-only）。
- 失败事件必须记录：审批驳回、履约失败、hash 校验失败、break-glass 使用、权限拒绝。
- 脱敏规则：人员联系方式脱敏（邮箱保留域名，工号保留后 4 位）。

### 5.7 Resolver SLO 与运行时行为 [PROPOSAL]

| 指标 | 目标 | 统计口径 |
|---|---|---|
| resolve 延迟 P50 | < 5ms | 缓存命中，单条 |
| resolve 延迟 P99 | < 50ms | 含缓存未命中查库 |
| validate 批量 | < 200ms | 100 条 refs，缓存命中 |
| 可用性 | 99.9% | 月度，排除计划维护 |
| 缓存 TTL | 5 分钟 | ResolvedRef 缓存键 = `{tenant, profile_id, active_revision, kind, stable_id, version}`（含 revision，撤销后旧缓存自动失效） |
| 缓存失效 | manifest 发布时主动失效 + 每次请求校验 active generation | pub/sub 通知 + Resolver 每次请求比对 `active_revision_generation`，不一致则重建该 profile 缓存（撤销零延迟） |
| 批量上限 | 100 refs/次 | validate 接口 |
| 超时 | resolve 3s / validate 10s | 超过返回 UnavailableCatalogResolver |
| 熔断 | 连续 5 次超时/5xx | 熔断 30s，期间 fail closed |
| 多实例一致性 | 撤销零延迟 | active_revision_generation 每次请求校验；普通发布 30s 内缓存重建 |

**撤销零延迟机制（FROZEN）**：
- `catalog_active_manifests` 表维护 `active_revision_generation`（单调递增整数）。
- Resolver 每次 resolve 请求先读取当前 `active_revision_generation`（轻量查询，<1ms），与本地缓存的 generation 比对。
- 若 generation 变化（manifest 发布或撤销），该 profile 的所有缓存条目立即失效，重新从数据库加载。
- 因此撤销/发布后**第一个请求即感知**，不存在 30 秒旧缓存窗口。
- 普通条目缓存仍保留 5 分钟 TTL 以减少数据库压力，但 generation 校验确保不使用过期 revision。

**数据库不可用行为**：
- Resolver 检测到数据库连接失败 → 切换为 `UnavailableCatalogResolver`，所有 resolve 返回 fail closed。
- 不使用本地文件兜底（防止使用过期 manifest）。
- 数据库恢复后自动恢复，缓存重建。
- 数据库不可用事件触发告警，通知运维负责人。

**hash 校验成本**：
- resolve 时校验 content_hash：从缓存读取已校验的 ResolvedRef，不重复计算 hash。
- 缓存未命中时：从数据库读取条目 + manifest 中的 hash，比对字符串相等（O(1)），不重新计算 SHA-256。
- manifest 发布时预计算所有 entry hash，写入数据库。

---

## 6. Phase 1 entry / exit gate 映射

### 6.1 entry gate 闭合状态（本文设计后）

| Entry gate | 阻塞项 | 本文闭合方式 | 状态 |
|---|---|---|---|
| §2 具名 A/RACI 完整 | 角色定义与联系方式 | **角色可配置机制已设计（决策 M）**：系统不硬编码角色，项目在 RBAC 中自定义角色并绑定权限，Profile 记录责任绑定。联系方式为项目配置，通过 Profile 页面填入，不阻塞 Phase 1 开发；JQMK 具体联系方式上线前填实 | ◐（机制完成，待项目配置） |
| manifest 签署对象/权威存储已定 | D-03 | §2.1–§2.4 定义 schema/ID/hash/git 布局；manifest 条目待填实 hash | ◐（设计完成，待填实） |
| hash/schema canonical input 已确认 | D-02 | §2.6 定义各 kind canonical input + hash 算法 | ◐（设计完成，待 owner 确认） |
| 重签/撤销和 inactive 运营策略已签署 | D-03/D-05 | §2.2 重签规则 + §5.5 revoke 演练 + LKG 已签=继续+告警 | ◐（告警时限/恢复条件仍 HOLD） |
| global scope 已选择且有撤销传播 | D-04 | 机制 A 已选；global 默认拒绝测试在 §3.7；撤销传播 HOLD | ◐（DEFERRED，exit 时关闭） |
| Catalog Pack 分层与 effective profile 已签署 | D-13 | §4 三层 pack + pack_lock 填实计划 | ◐（设计完成，待填实 hash） |
| RBAC 基础矩阵与 audit proposal 已登记 | D-06 | §5.6 基础矩阵 | ☑（已登记） |
| fake/test endpoint admission 控制目标已签署 | D-08 | Phase 0 已签；§5.1 实现证据计划 | ☑（控制目标已签） |

**entry gate 结论**：本文完成了 D-01/D-02/D-03/D-13 的设计，但**仍需以下动作才能正式 entry**：
1. 补全 6 个角色联系方式（林鲲鹏/隋昕航/梁桂岭的邮箱或工号）；
2. 隋昕航确认 §2.7 初始条目业务语义，填实 content_hash；
3. 按 §4.5 时间线填实三层 pack 的 version/hash；
4. 重算 profile_hash，签署签署实例 r2。

### 6.2 exit gate 证据计划

| Exit gate | 证据来源 | 本文章节 |
|---|---|---|
| Resolver resolve/validate 与冻结 v1.0 兼容 | contract vectors §3.2–3.4 | §3 |
| manifest↔Resolver 投影一致性向量通过 | §3.5 | §3 |
| active/deprecated/inactive 行为符合冻结边界 | §3.6 | §3 |
| tenant/domain/global RLS 负向全绿（含 global 默认拒绝） | §3.7 | §3 |
| manifest revision load/rollback/revoke 可演练 | §5.5 | §5 |
| production root fail-closed，test root 隔离 | §5.2–5.3 | §5 |
| 内部 browse/search API | Phase 1 实现内部 API（`/v1/catalog/browse`、`/v1/catalog/search`）供"统一查看"页面使用，支持按 kind/domain/status 筛选和关键词搜索；不对外暴露公共 browse/search contract | §5.1 |
| 未创建 Provider/endpoint/credential 假设 | manifest 禁止字段 §2.1 + scope review | §2 |
| lint/OpenAPI/git diff/回归通过 | §5.4 CI 任务 | §5 |
| FixtureDiscoveryAdapter 独立类型/注册且仅 test 装配 | §5.2 | §5 |

---

## 7. 决策点汇总（全部已确认）

> 13 个决策点（A-M）均已讨论确认。G 为项目实施事项，不阻塞产品设计。详细产品页面设计见 `2026-09-01-catalog-product-pages-design.md`。

| ID | 决策点 | 选项/影响 | 建议 | 责任人 |
|---|---|---|---|---|
| A | manifest_id 是否与 catalog_profile_id 解耦 | 解耦支持灰度多 manifest，但增加复杂度 | **已确认：Phase 1 保持 1:1 不解耦，一个 Profile 对应一个 manifest。灰度/多环境能力 Phase 2 评估** | 隋昕航 |
| B | Metric 权威来源 | Ontology metric projection vs 独立 Metrics 服务 | **已确认（评审后冻结）：Phase 1 使用独立 Metrics 服务（metrics.html）作为 metric 权威源。Ontology 扩展 metric projection 为 Phase 2+ 评估方向，若采用需重新签署 manifest（权威源变更影响所有 metric hash）。entity_type/relation_type 仍由 Ontology 负责（pull 同步），与 metric 解耦** | 隋昕航 |
| C | kind owner 是否在开发时定死 | owner 是项目配置，应由权限配置系统动态分配，不是开发时定死"全归某人"或"按 kind 拆给某人" | **已确认：owner 可配置。系统出厂提供默认 owner 角色映射（§2.6），具体每 kind 审批人由 RBAC + Profile 角色绑定动态配置。JQMK 当前配置为隋昕航兼任，未来项目可按 kind 分配不同人员，无需改代码** | 林鲲鹏 |
| D | 初始条目覆盖度与产品化定位 | EARP 是产品而非临时项目：Catalog 是产品功能，条目由用户在平台上按需配置，不是出厂前固定。基础 pack 出厂带最小集（可修改）；行业/企业 pack 由项目配置，支持下载导出作为经验资产沉淀。§2.7 的 27 条目是 JQMK 配置实例，用于验证产品功能，非出厂默认 | **已确认：产品化方向。新增 §2.8 产品化 Catalog 能力描述；基础 pack 出厂最小集可修改；pack 支持下载/导入；Phase 1 重点从"配好条目"转向"做出配置功能+JQMK 实例验证"** | 林鲲鹏+隋昕航 |
| E | entity_type 分层归属 | coal.mine 等放行业包还是企业包（JQMK 特化） | **已确认：通用煤矿概念放行业包，JQMK 特化放企业包。当前 27 引用无明显特化，企业包仅含 data_domain；未来特化在企业包扩展，不改行业包通用定义** | 隋昕航 |
| F | 联系方式补全方式 | 6 个角色联系方式 TBD 是否阻塞 Phase 1；用什么格式 | **已确认：联系方式是项目配置，不作为 Phase 1 开发阻塞项。系统支持通过 Profile + 人员数据源动态获取联系方式，审批/告警通知复用 EARP 已有消息能力。JQMK 具体联系方式在项目上线前填入即可** | 林鲲鹏 |
| G | pack_lock 填实时间线 | §4.5 建议 09-05/09-10/09-12/09-15，是否可行 | **项目实施事项，非产品设计决策，不阻塞。** 具体填实节奏由 JQMK 项目实施计划决定，产品功能不依赖特定时间线 | 隋昕航 |
| H | Resolver adapter 实现选型 | git-backed（读 manifest.json）vs 独立 registry 服务 | **已确认：Catalog 内容配置后存数据库，Resolver 通过 Catalog 模块提供的独立 API 接口查询（resolve/validate）。git 作为签署后的不可变审计存储，运行时不直接读 git 文件。无需单独部署 registry 服务** | 隋昕航 |
| I | pack 修改的权限与审批 | 所有 pack 修改需权限控制 + 审批流程，非任何人可改 | **已确认：复用 EARP 已有 RBAC 可配置能力，不新增细粒度权限码。基础权限沿用 ecmc.catalog.read/request/approve，pack 级操作通过角色-权限绑定配置；审批走 CatalogChangeRequest 状态机 + separation-of-duties** | 林鲲鹏 |
| J | Catalog 产品定位与源系统同步 | Catalog 是语义聚合与引用治理层（统一查看+引用注册），不是又一套配置系统；语义定义在源系统编辑，Catalog 通过 pull+webhook 同步 | **已确认：单一数据源原则。§2.7 条目改为从源系统引用注册；§2.8.2 平台能力改为统一查看+引用注册；新增 §2.9 源系统与同步机制（pull 为主+webhook 为辅）。Phase 1 实现 Ontology pull 同步，能力平台同步和 webhook 可 Phase 2** | 林鲲鹏+隋昕航 |
| K | 源系统编辑页面规划 | 6 种暂无编辑页的 kind 需建源系统页面；按复杂度分几页、导航放哪 | **已确认：方案 B（按复杂度分 3 页）。metrics.html（指标独立页）、catalog-basics.html（unit+aggregation+time_window+rule_schema 合页）、binding-templates.html（绑定模板独立页）。导航放"知识中心"下新增"目录管理"分组。详见 §2.10** | 林鲲鹏 |
| L | Profile 可配置化 | Profile 当前是手写 YAML，是否做成平台可配置页面；Phase 1 做还是 Phase 2 | **已确认（评审后升级 v2）：Phase 1 一起做。新增 profiles.html（项目配置管理），可配置 industry/enterprise/tenant/**data_domain（单值，一 Profile 一 domain）**/角色绑定/变更单/保管人/backup_approver。Profile schema v2：roles 改为可配置数组（不硬编码 6 个），data_domain 单值，新增 backup_approver。v1（JQMK r1 已签）保持不可变，新配置用 v2。详见 §2.11** | 林鲲鹏 |
| M | 角色是否硬编码 | 当前 Profile schema 固定 6 个角色（product_owner 等），现实项目可能没那么多人，一人可兼任多角色 | **已确认：角色可配置，不硬编码。系统只定义 Catalog 权限点（read/request/approve/publish），角色由项目在 EARP RBAC 中自定义并绑定权限；Profile 记录项目用了哪些角色、谁来填，数量和名称不限。Profile schema v2 将 roles 改为可配置数组；v1（JQMK 已签）保持不动，后续可迁移** | 林鲲鹏 |

---

## 8. Phase 1 范围与下一步

### 8.1 Phase 1 保留（评审后缩减）

1. **可执行 schema 与 golden hash**：manifest/pack/10 kind JSON Schema（`arch/catalog/schemas/`）、golden hash 参考、hash producer trust model
2. **数据库运行时模型**：11 张核心表、原子发布流程（签署→不可变写入→CAS 切换→缓存失效→归档）、active pointer、乐观锁、软删除
3. **Resolver API**：`/v1/catalog/resolve` + `/v1/catalog/validate`、缓存、SLO（§5.7）、fail closed、数据库不可用行为
4. **源系统同步**：Ontology pull 定时同步 + EARP 平台基础配置本地引用（metric/unit/aggregation 等本地服务）
5. **引用治理最小流程**：引用注册、pack 发布（不可变版本）、manifest 发布/回滚、冲突检测（禁止同版本覆盖）
6. **基础安全**：RBAC（4 个权限点）、SoD（候补审批人 + break-glass）、审计（180 天留存 + 脱敏规则）、运行门禁（admission + Fixture 隔离 + CI）
7. **产品页面**：catalog-admin.html（治理中心）、profiles.html（项目配置）、metrics.html（指标管理）、catalog-basics.html（基础配置）
8. **JQMK 27 项端到端实例**：从源系统引用注册 → pack 组合 → manifest 发布 → Resolver 解析全链路验证
9. **contract vectors**：正向/负向/批量/一致性/生命周期/跨域/冲突，CI 自动运行

### 8.2 推迟到 Phase 2

- Pack 导入（`.earppack` 上传）与资产市场
- webhook 实时通知（Phase 1 只用定时 pull）
- binding_template 可视化编辑器（Phase 1 用 JSON 编辑器，可视化推迟）
- 能力平台自动同步（Phase 1 手动注册 capability_contract 引用）
- Profile 复制与 git 自动提交体验优化
- 高级字段级 diff 和通用 JSON Schema 可视化编辑器
- 多数据域 Profile（Phase 1 一 Profile 一 domain）

### 8.3 评审后行动项

| 行动项 | 责任人 | 截止 |
|---|---|---|
| P0 修改已完成（冲突规则/权威源/Schema/存储事务） | 架构 + 数据域 | 2026-09-03 |
| 数据库表 DDL 与索引设计 | 后端/架构 | 2026-09-04 |
| Resolver API 接口定义与缓存方案 | 后端/架构 | 2026-09-04 |
| 前端页面原型（5 个页面） | 前端 | 2026-09-05 |
| P0 修改完成后组织线上复审 | 评审发起人 | 2026-09-05 |
