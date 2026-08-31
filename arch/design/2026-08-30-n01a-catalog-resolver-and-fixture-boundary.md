# N01A CatalogResolver、初始目录与 Case A Fixture 边界

**文档编号：** CONTRACT-ECMC-N01A-CATALOG-BOUNDARY
**日期：** 2026-08-30
**状态：** v1.0 / Approved / Development Ready

## 1. CatalogResolver 是唯一外部目录边界

N01A 模型服务不得读取 Ontology、Metric、Binding Template 或 Capability 的内部表，也不得持久化其物理主键、Provider ID、SQL、endpoint 或 credential。它只依赖以下同步服务契约：

```text
CatalogRef = { kind, stable_id, version }

resolve(tenant_id, ref, expected_kind, at_version?)
  -> ResolvedCatalogRef | CatalogResolutionError

validate(tenant_id, refs, context)
  -> CatalogValidationResult
```

`ResolvedCatalogRef` 必须返回：

```text
kind, stable_id, version, content_hash, status, data_domain_id,
semantic_schema_version, display_name?, input_schema?, output_schema?,
compatibility_metadata
```

`status=active` 才可用于新 Draft、submit、publish、compile 和 activation revalidation。历史 Snapshot/Artifact 可读取已 pin 的 deprecated 条目，但它们不因此变成可供新引用的选项。`CatalogResolutionError` 只能为 `CATALOG_REF_NOT_FOUND`、`CATALOG_REF_INACTIVE`、`CATALOG_REF_KIND_MISMATCH`、`CATALOG_REF_DOMAIN_FORBIDDEN` 或 `CATALOG_REF_SCHEMA_INCOMPATIBLE`；在模型校验语境中映射为可定位的 422 issue。

`context` 至少包括 tenant、data_domain、使用位置（node/edge/evidence/rule）、期望输入/输出 schema，以及涉及的 source/target entity types。Resolver 必须 fail closed：未知 kind、版本不精确、跨域和不兼容 schema 都不能被默认接受。

## 2. N01A 可引用的目录种类

| `kind` | 最小语义合同 | N01A 使用位置 |
|---|---|---|
| `data_domain` | active、domain identity | Logical Model/适用范围。 |
| `entity_type` | active、domain、semantic schema | target/node/binding。 |
| `relation_type` | active、domain、允许 source/target 类型 | edge/binding。 |
| `metric` | active、value/time semantics、兼容 unit/aggregation | Evidence Requirement。 |
| `unit` / `aggregation` | active、metric compatibility | Evidence Requirement。 |
| `time_window_schema` | active、input schema | diagnostic target/Evidence。 |
| `binding_template` | active、params schema、resolver identity/hash、类型兼容性 | instance binding。 |
| `capability_contract` | active、read-only、input/output schema | Evidence primary/supporting binding。 |
| `rule_schema` | active、JSON schema/version | rule spec。 |

该表冻结的是调用方语义，不预设具体实现。`metric` 可以由扩展后的 Ontology 或独立 Metrics Catalog 提供；两者都必须完整实现本契约，不能由模型服务设置分支。

## 3. CatalogChangeRequest 履约边界

申请的状态机为：

```text
draft → submitted → approved_pending_fulfillment → fulfilled
                    ├→ rejected
                    └→ fulfillment_failed → retry-fulfillment → approved_pending_fulfillment
draft/submitted → cancelled
```

- `approve` 只记录治理决定并进入 `approved_pending_fulfillment`；它不把 `proposed_definition` 直接写入目录。
- 由该 kind 的权威目录所有者履约，成功后返回一个 `status=active` 的 `ResolvedCatalogRef`；模型服务才可把 request 标为 `fulfilled`。
- `cancel` 只能由申请人对自身 `draft/submitted` 执行；已经 fulfilled 的申请不可取消。
- `retry-fulfillment` 只允许 `fulfillment_failed`，必须由具有 `ecmc.catalog.approve` 权限者发起，并产生新的履约 attempt/audit，不覆盖旧错误。
- `proposed_definition` 是受控业务语义；必须拒绝 SQL、URL、endpoint、credential、Provider 参数、可执行脚本和无受控 schema 的 arbitrary JSON。

履约的异步调度可用 outbox，但 outbox delivery 成功不等于目录条目成功创建。唯一成功依据是 Resolver 可解析到对应 stable ref 且 `status=active`。

## 4. 初始目录：实施前必须冻结的最小清单

Phase 0 不虚构真实目录数据或 Provider。进入 Phase 1 前，产品/领域/平台负责人必须签署一份 tenant-scoped（或明确 global）的初始目录 manifest，至少包含：

1. Case A 要覆盖的数据域、目标 Entity Type、所有 Node Entity Type、Edge Relation Type；
2. 每条 required Evidence 的 Metric/Unit/Aggregation/Time Window；
3. 每个实例绑定所需 Binding Template、params schema、resolver identity/hash；
4. primary/supporting logical Capability Contract 及其 read-only I/O schema；
5. 使用的 rule schema 与 `sign_propagation_v1` algorithm profile/schema versions；
6. 各 kind 的权威 owner、创建/激活责任人及 resolver adapter 实现位置。

manifest 的条目必须由 stable ref/version/content hash 表示，而不是 display name 或数据库 ID。若某种类尚无真实 owner，必须在 Phase 1 前明确选择一个 contract-compliant temporary catalog adapter；不能让 N01A HTTP API 接受自由填写作为替代。

## 5. Case A Fixture Discovery Adapter（仅测试）

Case A 的 `testing` Version、`published_fixture`、Fixture hash 和既有 45 项自动化回归是历史测试边界，不是生产治理或目录实现。

允许一个 test-only `FixtureDiscoveryAdapter`，但它必须同时满足：

- 只能通过测试 composition root/依赖注入显式装配；生产应用装配、正式 HTTP 路由和 N02 Discovery 一律不能注册或调用它。
- 只返回 hash-locked Fixture source/snapshot，不能创建、发布、激活、修改 CausalModel 或绕过 CatalogResolver/RBAC。
- 与生产 `ActiveModelDiscovery` 具有不同的类型/注册 key；生产 Discovery 只接受 Model active pointers 和 current compiled Blueprint 的精确 source pin。
- 测试必须断言 production composition root 不包含该 adapter，并断言 testing Fixture 不能经 N01A activate 或生产 Discovery 成为候选。

因此 Case A 回归可连续运行，而“Fixture 成功”不能被解释为 N01A 的生产发布、artifact 或运行时 active。

## 6. Phase 0 待签署决策

以下是唯一仍会改变集成归属或权限配置的决策；其余接口语义已经冻结：

| 决策 | 推荐默认 | 签署责任 |
|---|---|---|
| Metric 的权威实现 | 在现有 Ontology 增加满足本合同的 metric projection，避免并行目录；若无法满足 time/unit/aggregation 语义，则改为独立 Metrics Catalog。 | 平台架构 + 领域 owner |
| Binding Template/Capability Contract owner | 分别由知识平台与能力平台拥有，N01A 只消费 Resolver；不在 `causal_models` 表中承载。 | 平台负责人 |
| 目录审批权限 | Phase 1 先使用 `ecmc.catalog.approve`，但履约仍委派给各 kind owner；更细权限只在既有 RBAC 支持时拆分。 | 安全/RBAC owner |
| 初始 manifest 范围 | 只覆盖 Case A 等价模型所需项；不把真实 Provider、凭据或 N03 数据接入塞入初始集。 | 领域 owner |

若这些决策未签署，不应开始会依赖相应真实目录的生产写路径；可先实现 Resolver interface、fake/contract test adapter 和 Case A Fixture 隔离测试。
