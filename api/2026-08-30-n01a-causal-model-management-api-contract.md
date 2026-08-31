# N01A 因果模型管理 API 与数据契约

**文档编号：** API-ECMC-N01A-CAUSAL-MODEL-MANAGEMENT
**日期：** 2026-08-30
**状态：** v1.0 / Approved / Development Ready
**上游：** `prd/PRD-2026-033-causal-model-management-n01a.md` v1.0、`arch/design/2026-08-30-causal-model-management-n01-detailed-design.md` v0.3.1

本文件是后续 FastAPI/Pydantic 与导出 OpenAPI 的 source contract。路由实现、字段命名和 HTTP status 必须与之相同；任何新增字段遵循向后兼容的 optional-additive 原则。

## 1. 通用传输规则

- API 前缀：`/v1/ecmc`；所有 resource ID 是不透明、tenant-scoped 的稳定 public ID。
- 身份/tenant 从认证上下文取得；客户端不得提交 `tenant_id`、actor、role、active pointer、hash 或审计字段。
- 每个会造成业务写入的 `POST`、`PATCH`、`PUT`、`DELETE` 都必须有 `Idempotency-Key`。该 key 在 `(tenant_id, actor_id, operation, key)` 唯一；相同 semantic request 回放原 HTTP status/body，相同 key 不同 request 为 `409 IDEMPOTENCY_KEY_REUSE`。
- 版本内容写、submit/reject/publish/archive/activate 均必须有 `If-Match: "v<revision>"`。缺失或格式非法为 `422 MISSING_IF_MATCH`；revision 不匹配为 `409 VERSION_CONFLICT`，响应的 `current_revision` 可供调用者刷新。Create/clone/compile/CatalogChangeRequest create 不使用 If-Match。
- `activate` 同时要求 Candidate Version 的 `If-Match` 和 body 的 `expected_active_*` CAS；两者职责不同，不能互相替代。
- 所有成功的 Version response 必须带 `ETag: "v<revision>"`。所有响应带 `X-Correlation-Id`；请求可传该 header，否则服务生成。

## 2. 公共数据对象

```json
{
  "catalog_ref": {"kind": "metric", "stable_id": "metric.haulage_cycle_time", "version": "v1"},
  "active_pointer": {
    "model_version_id": "cmv-…",
    "snapshot_id": "cms-…"
  },
  "compile_record_summary": {
    "compile_record_id": "cr-…",
    "status": "running|success|failed",
    "retry_of_compile_id": null,
    "artifact_schema_version": "blueprint-ir/v1",
    "compiled_artifact_hash": null
  }
}
```

`catalog_ref.version` 是精确版本，不允许 `latest`、`*` 或仅 display name。`active_pointer` 的两个字段要么同时为 non-null，要么同时为 null。CompileRecord 在 `success` 时 Artifact schema/hash 必填，在 `running/failed` 时均为 null。

Version 的治理状态只允许 `draft|in_review|published|superseded|archived`（legacy `testing/deprecated` 只读）；编译状态与 delivery 状态分别出现在不同对象，禁止客户端或服务端把 `pending_delivery` 写成 compile status。

### 2.1 最小写入 payload 与公共 schema

所有 object 使用 JSON；未列出的字段一律拒绝（`extra=forbid`），以防 API 在不经架构评审的情况下吸收自由 DSL 或物理执行配置。除明确的可选字段外，字段均为必填且不可为 null。客户端始终不得提交 `tenant_id`、actor/role、任何 `*_hash`、`active_pointer`、Snapshot/CompileRecord/Blueprint ID、审计字段或 Provider/endpoint/credential/SQL/query 字段。

```json
// CatalogRef：所有 *_ref 字段唯一接受的形式
{"kind":"entity_type","stable_id":"entity.mine","version":"v1"}

// CreateModelRequest
{
  "name":"矿山产量下降诊断",
  "data_domain_ref":{"kind":"data_domain","stable_id":"production","version":"v1"},
  "diagnostic_target":{
    "objective":"diagnose",
    "entry_point":"production_output",
    "direction":"down",
    "domain":"production",
    "target_entity_type_ref":{"kind":"entity_type","stable_id":"entity.mine","version":"v1"},
    "time_window_schema_ref":{"kind":"time_window_schema","stable_id":"daily_window","version":"v1"}
  },
  "description":"可选的展示说明"
}
```

`CatalogRef` 的字段固定为 `kind`、`stable_id`、`version` 三个非空字符串，`kind` 必须与使用位置匹配，`version` 必须是精确版本。CreateModel 的 `description` 可选；`diagnostic_target` 的六个字段均为必填，`objective` 仅能为 `diagnose`，`direction` 仅能为 `up|down|change|neutral|any`。服务从该 payload 计算并冻结 Logical Model target signature；之后的 Version PATCH 不得变更它。

```json
// PUT .../nodes/{node_key}；node_key 只来自 path，不在 body 重复
{
  "entity_type_ref":{"kind":"entity_type","stable_id":"entity.haulage_system","version":"v1"},
  "observability":"observable",
  "entry_point":false,
  "business_name":"运输系统",
  "notes":"可选的自由文本说明"
}

// PUT .../edges/{edge_key}；edge_key 只来自 path
{
  "from_node_key":"haulage_cycle_time",
  "to_node_key":"production_output",
  "relation_type_ref":{"kind":"relation_type","stable_id":"relation.affects","version":"v1"},
  "effect":"-",
  "strength":"0.80",
  "confidence":"0.90",
  "lag":"PT0S"
}

// PUT .../rules/{rule_key}；rule_key 只来自 path
{
  "rule_schema_ref":{"kind":"rule_schema","stable_id":"direction_rule","version":"v1"},
  "rule_spec":{"operator":"matches_direction","expected":"down"},
  "rationale":"可选的业务说明"
}
```

Node 的 `observability` 仅为 `observable|indirectly_observable|latent_hypothesis`；`business_name`、`notes` 可选且只作展示。Edge 的六个字段均必填，`effect` 仅为 `+|-`，`strength` 与 `confidence` 是范围 `[0,1]` 的 decimal string，`lag` 为 ISO-8601 duration。Rule 的 `rule_spec` 必须由 `rule_schema_ref` 指向的受控 JSON Schema 验证；它不是自由 DSL。

```json
// PUT .../evidence-requirements/{node_key}/{requirement_key}
{
  "metric_ref":{"kind":"metric","stable_id":"metric.haulage_cycle_time","version":"v1"},
  "unit_ref":{"kind":"unit","stable_id":"minute","version":"v1"},
  "aggregation_ref":{"kind":"aggregation","stable_id":"mean","version":"v1"},
  "time_window_ref":{"kind":"time_window_schema","stable_id":"daily_window","version":"v1"},
  "binding_template_ref":{"kind":"binding_template","stable_id":"outbound_relation","version":"v1"},
  "binding_params":{"relation_type_ref":{"kind":"relation_type","stable_id":"has_subsystem","version":"v1"},"target_entity_type_ref":{"kind":"entity_type","stable_id":"entity.haulage_system","version":"v1"}},
  "required":true,
  "primary_contract_ref":{"kind":"capability_contract","stable_id":"contract.read_haulage_cycle","version":"v1"},
  "supporting_contract_refs":[{"kind":"capability_contract","stable_id":"contract.read_haulage_quality","version":"v1"}],
  "business_description":"可选的业务说明"
}
```

Evidence 的前九个字段均必填，`supporting_contract_refs` 可为空数组，`business_description` 可选。`primary_contract_ref` 恰好一个；supporting refs 不得与 primary 重复，且全部为 `capability_contract`。`binding_params` 只可含 `binding_template_ref` 所指 params schema 声明的字段和值；它不能携带 provider/endpoint/credential 或任意 query。

```json
// CreateCatalogChangeRequest
{
  "request_type":"metric",
  "target_data_domain_ref":{"kind":"data_domain","stable_id":"production","version":"v1"},
  "rationale":"需要用于运输周期诊断的受控指标。",
  "proposed_definition":{
    "schema_version":"catalog-change-request/v1",
    "kind":"metric",
    "display_name":"运输周期",
    "semantic_definition":"矿卡完成一次运输循环所需的分钟数。",
    "contract":{"value_type":"decimal","time_semantics":"event_interval","allowed_unit_refs":[{"kind":"unit","stable_id":"minute","version":"v1"}],"allowed_aggregation_refs":[{"kind":"aggregation","stable_id":"mean","version":"v1"}]}
  }
}
```

`request_type`/`proposed_definition.kind` 必须相同，且只可为 `data_domain|entity_type|relation_type|metric|unit|aggregation|time_window_schema|binding_template|capability_contract|rule_schema`。`proposed_definition` 采用 discriminated typed envelope：共同字段为 `schema_version,kind,display_name,semantic_definition,contract`；`contract` 按 kind 严格校验。`metric` 如上；`entity_type` 为 `{semantic_class}`；`relation_type` 为 `{source_entity_type_refs,target_entity_type_refs}`；`unit` 为 `{quantity_kind,symbol}`；`aggregation` 为 `{operator}`；`time_window_schema` 为 `{input_schema_ref}`；`binding_template` 为 `{params_schema_ref,source_entity_type_refs,target_entity_type_refs,resolver_identity}`；`capability_contract` 为 `{read_only:true,input_schema_ref,output_schema_ref}`；`rule_schema` 为 `{rule_kind:"predicate"|"threshold"|"direction_rule",spec_schema_ref}`；`data_domain` 为 `{domain_code}`。这些 contract 字段只能引用受控 `CatalogRef` 或其 enum/string 标量，不能提交 raw JSON Schema、脚本或执行配置。

## 3. 资源与命令

| 操作 | HTTP 路径 | 权限 | 必须条件/关键结果 |
|---|---|---|---|
| 列表/创建 Model | `GET/POST /causal-models` | read / write_draft | POST 创建 Logical Model 与首个 Draft；body 含 `name,data_domain_ref,diagnostic_target`。 |
| Model 详情 | `GET /causal-models/{model_id}` | read | 返回 active pointer、versions 摘要和四状态面。 |
| Version 详情/创建 | `GET/POST /causal-models/{model_id}/versions`、`GET /.../versions/{version_id}` | read / write_draft | POST 可 `clone_from_version_id` 或 blank；clone 不复制 Snapshot/Artifact/Review。 |
| Draft 元数据 | `PATCH /.../versions/{version_id}` | write_draft | `If-Match`；target signature 不能改变。 |
| Node | `PUT/DELETE /.../nodes/{node_key}` | write_draft | `If-Match`；Node body 必含 `entity_type_ref,observability,entry_point`。 |
| Edge | `PUT/DELETE /.../edges/{edge_key}` | write_draft | `If-Match`；body 含 endpoints、relation ref、effect/strength/confidence/lag。 |
| Rule | `PUT/DELETE /.../rules/{rule_key}` | write_draft | `If-Match`；body 含 `rule_schema_ref,rule_spec`。 |
| Evidence | `PUT/DELETE /.../evidence-requirements/{node_key}/{requirement_key}` | write_draft | `If-Match`；body 含 metric/unit/aggregation/binding/contracts/required。 |
| 校验/提交/驳回/发布/归档 | `POST /.../validate|submit-review|reject|publish|archive` | write_draft / write_draft / review / review / review | 除 validate 以外均 `If-Match`；validate 也产生新的 validation run，要求 Idempotency-Key。 |
| 编译 | `POST /.../compile` | compile | body 可含 `retry_of_compile_id`；返回 `202` + running Attempt，或对应的幂等 Attempt。 |
| 激活 | `POST /causal-models/{model_id}/activate` | activate | `If-Match` + 显式 Candidate/Attempt/expected active pointers；成功 `200`。 |
| 治理视图/Artifact | `GET /.../governance`、`GET /.../compile-records/{compile_record_id}/artifact` | audit.read | 只读；Artifact body 仅供有审计权者读取。 |
| 目录申请列表/创建 | `GET/POST /catalog-change-requests` | catalog.read / catalog.request | POST 创建 `draft`，body 含 `request_type,proposed_definition,rationale,target_data_domain_ref`。 |
| 目录申请详情 | `GET /catalog-change-requests/{request_id}` | catalog.read | 仅可见 tenant/权限范围。 |
| 编辑/提交目录申请 | `PATCH /catalog-change-requests/{request_id}`、`POST /catalog-change-requests/{request_id}/submit` | catalog.request | 仅申请人自己的 `draft`；submit 转为 `submitted`。 |
| 目录申请命令 | `POST /catalog-change-requests/{id}/approve|reject|cancel|retry-fulfillment` | approve / approve / request / approve | 各自均 Idempotency-Key；cancel/retry 的状态前置条件见 §6。 |

所有 Draft 子资源的写命令都只能作用于 `draft` Version；否则为 `409 INVALID_STATE_TRANSITION`。删除被仍存依赖引用的 Node/Edge/Rule/Evidence 为 `409 RESOURCE_HAS_DEPENDENTS`，不自动级联删除。

## 4. 关键命令 request/response

### 4.1 `POST …/compile`

```json
// request
{"retry_of_compile_id": "cr-failed-…"}

// 202 response
{
  "compile_record": {
    "compile_record_id": "cr-…",
    "model_version_id": "cmv-…",
    "snapshot_id": "cms-…",
    "status": "running",
    "retry_of_compile_id": "cr-failed-…",
    "artifact_schema_version": null,
    "compiled_artifact_hash": null
  }
}
```

仅 `published` Version 可以编译。retry id 必须精确关联同一 tenant/Version 的 `failed` Attempt；否则为 `409 INVALID_RETRY_PARENT`。worker 的最终结果通过 `GET Version/governance` 读取，不在另一个 API 中把 `running` 改为成功。

### 4.2 `POST /causal-models/{model_id}/activate`

```json
{
  "model_version_id": "cmv-candidate-…",
  "compile_record_id": "cr-success-…",
  "expected_active_model_version_id": null,
  "expected_active_snapshot_id": null
}
```

两个 `expected_active_*` 必须都出现；首次激活为两个 null。成功 `200`：

```json
{
  "active_pointer": {"model_version_id": "cmv-candidate-…", "snapshot_id": "cms-candidate-…"},
  "blueprint_version_id": "bpv-…",
  "compiled_artifact_hash": "<64-lowercase-hex>",
  "superseded": {"model_version_id": "cmv-old-…", "blueprint_version_id": "bpv-old-…"}
}
```

请求 Candidate Version ETag 不匹配为 `409 VERSION_CONFLICT`；active pointer 不匹配为 `409 ACTIVE_VERSION_CHANGED` 且不得产生 Blueprint、改变状态、写 audit/outbox 或消费 Artifact。服务只能 materialize 指定 success Artifact，不能重编译或选择其他 success Attempt。

### 4.3 Validate / publish

`POST …/validate` 成功总是 `200`，返回一个追加式 `ValidationResult`，即使含 error：

```json
{
  "validation_run_id": "cvr-…",
  "model_version_id": "cmv-…",
  "draft_revision": 7,
  "input_hash": "<64-lowercase-hex>",
  "result": "passed|failed",
  "issues": [{"code":"CAUSAL_DAG_CYCLE","severity":"error","location":{"resource_type":"edge","edge_key":"e-2","field":"to_node_key"},"message":"…"}]
}
```

submit/publish 发现模型内容阻断项时返回 `422 MODEL_VALIDATION_FAILED`，并把相同 `ValidationResult` 放在 `details.validation_result`。权限、可见性、并发与状态错误不得伪装成 validation issue。

## 5. 稳定错误合同

所有非 2xx 响应均为：

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "The version revision is stale.",
    "correlation_id": "corr-…",
    "details": {"current_revision": 8}
  }
}
```

| HTTP | stable code | 语义 |
|---:|---|---|
| 422 | `REQUEST_SCHEMA_INVALID`, `MISSING_IF_MATCH`, `MODEL_VALIDATION_FAILED`, `CATALOG_REF_*` | 请求结构或模型内容无效；只有 `MODEL_VALIDATION_FAILED` 可含 ValidationResult。 |
| 403 | `PERMISSION_DENIED`, `DOMAIN_ACCESS_DENIED` | 资源可见但没有对应操作权限/数据域授权。 |
| 404 | `CAUSAL_MODEL_NOT_FOUND`, `MODEL_VERSION_NOT_FOUND`, `CATALOG_CHANGE_REQUEST_NOT_FOUND` | 不存在或对调用者不可见；不得泄露其他 tenant 信息。 |
| 409 | `VERSION_CONFLICT`, `ACTIVE_VERSION_CHANGED`, `INVALID_STATE_TRANSITION`, `IDEMPOTENCY_KEY_REUSE`, `INVALID_RETRY_PARENT`, `RESOURCE_HAS_DEPENDENTS`, `CONTENT_CHANGED` | 状态、并发或不可恢复的命令冲突。 |

`ACTIVE_VERSION_CHANGED.details` 只可包含当前调用者可见的 `{model_version_id,snapshot_id}`（均可为 null）和 Model 状态摘要；它不能包含 Artifact 或其他 tenant/无权版本详情。

## 6. CatalogChangeRequest 请求状态

| 命令 | 允许源状态 | 结果 |
|---|---|---|
| create | — | `draft`；申请人可编辑后显式 submit。 |
| submit | `draft` | `submitted`；执行申请 payload schema/safety validation。 |
| approve | `submitted` | `approved_pending_fulfillment`，触发目录 owner 履约；不直接创建目录项。其他状态为 `409 INVALID_STATE_TRANSITION`。 |
| reject | `submitted` | `rejected`，必须 `reason`。其他状态为 `409 INVALID_STATE_TRANSITION`。 |
| cancel | `draft`,`submitted` | `cancelled`；申请人只能取消自己的申请。其他状态为 `409 INVALID_STATE_TRANSITION`。 |
| retry-fulfillment | `fulfillment_failed` | 新建 attempt，回到 `approved_pending_fulfillment`。其他状态为 `409 INVALID_STATE_TRANSITION`。 |
| fulfillment callback | `approved_pending_fulfillment` | Resolver 已返回 active stable ref 才能 `fulfilled`；失败转 `fulfillment_failed`，保存脱敏错误。其他状态为内部 `INVALID_STATE_TRANSITION`。 |

回调是目录 owner 的内部 service contract，不向普通 HTTP 客户端暴露“直接 fulfilled”写接口。

## 7. OpenAPI/Pydantic 落地门槛

实现开始前必须以本文件生成/确认：共享 headers、`CatalogRef`、`ValidationIssue`、`ValidationResult`、`ErrorResponse`、所有状态 enum、ActivateRequest 与 CatalogChangeRequest command schemas。导出的 OpenAPI 必须列出每个写操作的 Idempotency-Key、每个 Version mutation 的 If-Match、以及所有 422/403/404/409 响应。
