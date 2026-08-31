# N01A 生产 Catalog Phase 0 签署记录与门禁清单

**记录编号：** SIGNOFF-ECMC-N01A-CATALOG-PHASE0-20260831
**日期：** 2026-08-31
**状态：** `PENDING_SIGN-OFF`
**配套计划：** [N01A 生产 Catalog 契约签署与接入计划](2026-08-31-production-catalog-contract-signing-and-onboarding-plan-n01a.md)
**适用范围：** Phase 0 的 owner、manifest、Resolver、一致性、信任、部署隔离与 Phase 1 门禁确认

本记录是可填写的签署表，不代表任何决策已经批准。所有姓名、团队、系统、存储位置、变更单、日期、证据链接和结论均留空，待责任人填写。不得用 Case A Fixture、`FakeCatalogResolver`、具体 Provider 或未签署配置补齐空白。

## 0. 填写规则与状态标签

- **[FROZEN-CONFIRM]**：仅确认遵守现有契约，不能改成另一种语义。
- **[PROPOSAL-DECIDE]**：配套计划中的建议，必须选择、记录理由并签署后才可实施。
- **[OWNER-INPUT]**：必须由具名责任人填写，不能只写“平台”或“数据团队”。
- **[EVIDENCE]**：附上可复核的 manifest、测试、部署 admission 或审计证据位置。

签署时填写 `决定/值`、`责任人`、`日期`、`证据/变更单` 和 `□ APPROVE / □ HOLD`。未填写项按 `HOLD` 处理。

## 1. 记录元数据

| 项目 | 待填写值 |
|---|---|
| 变更单/发布单 | |
| 目标环境与 tenant/data-domain 范围 | |
| 本次签署的 manifest 修订 | |
| `manifest_id` | |
| `manifest_schema_version` | |
| `manifest_hash`（64 位小写 SHA-256） | |
| 计划生效时间/窗口 | |
| 失效/撤销记录位置 | |
| 关联 Resolver adapter identity + contract version | |
| 关联测试向量/报告 | |
| 记录保管人 | |

## 2. 具名 owner 与 RACI

### 2.1 责任人登记

| 责任域 | 姓名 | 团队/系统 | 责任范围 | 代理人/联系方式 | 签署日期 | 决定 |
|---|---|---|---|---|---|---|
| 产品负责人 | | | 初始 manifest 范围、选择器体验、N01A/N02 边界 | | | □ APPROVE □ HOLD |
| 平台架构负责人 | | | Catalog kind 归属、Resolver/read port、版本/hash、manifest 存储 | | | □ APPROVE □ HOLD |
| 数据域负责人 | | | Entity/Relation/Metric 语义、域分类、owner、下线策略 | | | □ APPROVE □ HOLD |
| 安全/RBAC 负责人 | | | tenant/domain 授权、global scope、部署 fake 门、callback 信任 | | | □ APPROVE □ HOLD |
| 审计/合规负责人 | | | 审计字段、脱敏、留存、撤销证据 | | | □ APPROVE □ HOLD |
| 运行平台负责人 | | | 运行门禁、告警、回滚、last-known-good 运营策略 | | | □ APPROVE □ HOLD |

### 2.2 RACI 矩阵 [OWNER-INPUT]

`A` 必须是一个具名 accountable owner；`R` 可以是多个执行团队；`C/I` 也必须填写，不得默认推断。

| 活动 | A | R | C | I | 当前证据/变更单 |
|---|---|---|---|---|---|
| Data Domain / Entity / Relation 定义 | | | | | |
| Metric / Unit / Aggregation 定义 | | | | | |
| Time Window / Rule Schema 定义 | | | | | |
| Binding Template 定义与 resolver | | | | | |
| Logical Capability Contract 定义 | | | | | |
| 生成并签署 manifest entry | | | | | |
| manifest 权威存储与生效加载 | | | | | |
| Resolver adapter 实现与发布 | | | | | |
| browse/search 只读投影（如批准） | | | | | |
| CatalogChangeRequest 履约 | | | | | |
| callback 鉴权密钥/身份管理 | | | | | |
| manifest 重签/撤销 | | | | | |
| 部署 admission 与 fake/test 隔离 | | | | | |
| 生产事故停写与恢复 | | | | | |

## 3. manifest 签署对象与权威存储

### 3.1 签署对象 [FROZEN-CONFIRM]

以下事实来自现有 Catalog 边界：模型侧引用只能是 exact `CatalogRef={kind,stable_id,version}`；Resolver 必须返回 `content_hash`、`status`、`data_domain_id`、`semantic_schema_version` 及适用的 schema/compatibility 投影。模型 Snapshot/Artifact 保存发布时 pin，不能保存 Provider ID 或目录内部主键。

本次签署对象必须明确绑定：

```text
manifest_id + manifest_schema_version + manifest_hash
```

| 签署对象字段 | 待填写值 | 责任人 | 证据 |
|---|---|---|---|
| manifest identity/修订规则 | | | |
| manifest schema version | | | |
| manifest hash | | | |
| 覆盖 tenant/data-domain/global scope | | | |
| entry 列表/附件位置 | | | |
| signer identity 与责任角色 | | | |
| 签署时间与生效时间 | | | |
| 关联变更单 | | | |

### 3.2 权威存储 [PROPOSAL-DECIDE]

必须选择一个可版本化、访问审计、不可变保留并可追溯部署的权威存储。候选仅用于决策，不代表采用：签名制品仓库、受控配置仓库或专用 registry。普通应用数据库行、开发机文件和临时对象存储不能自行成为签署事实。

| 决策项 | 选择/值 | 责任人 | 证据 |
|---|---|---|---|
| 权威存储类型与位置 | | | |
| 读取 identity/权限 | | | |
| 不可变保留证明 | | | |
| 部署 revision→manifest hash 追溯 | | | |
| 生效窗口与撤销传播 | | | |
| 备份/恢复与审计 | | | |
| 决定 | □ APPROVE □ HOLD | | |

### 3.3 manifest 最小 entry 一致性 [FROZEN + SIGN-OFF]

对每个 exact ref，manifest 和 Resolver 投影中适用的字段必须一致：

```text
kind, stable_id, version, content_hash, status, data_domain_id,
semantic_schema_version, input_schema, output_schema,
compatibility_metadata
```

| 检查项 | 结果/证据 |
|---|---|
| 每个 entry 的 `(kind,stable_id,version)` 唯一性已验证 | |
| `version` 不含 `latest`、`*` 或模糊范围 | |
| `status=active` 的确切 entry 可由 Resolver 解析 | |
| manifest hash 与 Resolver 返回的 content hash 逐字节一致 | |
| status/domain/schema/input/output/compatibility 逐字段一致 | |
| adapter 不静默归一化或改写签署投影 | |
| 缺失、非 active、跨域、kind mismatch、schema incompatible 均 fail closed | |
| 逐 kind contract vectors 已执行 | |
| 决定 | □ APPROVE □ HOLD |

各 kind 的 canonical input、canonicalization/hash 算法及算法版本若尚未冻结，必须填写在下表并标记 HOLD；仅验证 64 位 hex 形态不足以证明一致性。

| Catalog kind | canonical input/schema | hash 算法/版本 | owner | contract vector 证据 | 决定 |
|---|---|---|---|---|---|
| `data_domain` | | | | | □ APPROVE □ HOLD |
| `entity_type` | | | | | □ APPROVE □ HOLD |
| `relation_type` | | | | | □ APPROVE □ HOLD |
| `metric` | | | | | □ APPROVE □ HOLD |
| `unit` | | | | | □ APPROVE □ HOLD |
| `aggregation` | | | | | □ APPROVE □ HOLD |
| `time_window_schema` | | | | | □ APPROVE □ HOLD |
| `binding_template` | | | | | □ APPROVE □ HOLD |
| `capability_contract` | | | | | □ APPROVE □ HOLD |
| `rule_schema` | | | | | □ APPROVE □ HOLD |

## 4. 重签、修订与撤销

### 4.1 触发条件 [FROZEN-CONFIRM]

以下任一变化必须产生新的不可变 manifest 修订和新的签署记录：entry 新增、语义/compatibility/schema/version/hash/status 变化、scope/owner 变化、Resolver adapter identity 或 contract version 变化。旧修订只归档，不覆盖或删除。

| 触发/规则 | 决定/值 | 责任人 | 证据 |
|---|---|---|---|
| manifest ID：稳定 ID + revision，或每修订新 ID | | | |
| 修订号/生效窗口规则 | | | |
| 新 hash 计算与签署流程 | | | |
| 旧修订归档与读取规则 | | | |
| 撤销原因、审批与传播 | | | |
| adapter 发现撤销/漂移的 fail-closed 行为 | | | |
| 决定 | □ APPROVE □ HOLD | | |

### 4.2 撤销后的运行语义

| 语义 | 状态 | 责任人 | 证据/理由 |
|---|---|---|---|
| 新 Draft/引用/submit/publish/compile/activation revalidation 拒绝非 active entry | **[FROZEN-CONFIRM]** | | |
| 已经 active 且完成 pin 的模型是否继续 last-known-good | **[PROPOSAL-DECIDE]** □ 继续 □ 停止 □ 按域分类 | | |
| 停止/继续的告警、时限、恢复条件 | **[PROPOSAL-DECIDE]** | | |
| 冲突时的 incident commander | **[OWNER-INPUT]** | | |

## 5. global scope 与域授权

global 不是默认跨租户万能权限。必须选择一种实现，并留下撤销传播证据；在选择前所有条目按 tenant/data-domain scope 处理。

| 选项 [PROPOSAL-DECIDE] | 选择 | 约束/验收证据 |
|---|---|---|
| A. 权威 Resolver 保存 global entry，按调用 tenant/domain 投影授权 | □ | 需证明每次 resolve 都执行 tenant/domain policy 和 RLS 等价隔离。 |
| B. 按治理流程复制为 tenant-scoped entry | □ | 需证明复制产生独立 version/hash/owner，撤销不会静默跨租户。 |
| C. shared scope 存储 + 显式 tenant policy/RLS | □ | 需证明 shared scope 不是应用层绕过 RLS 的特例。 |
| 不允许的默认项：应用层直接跨 tenant 可见 | **拒绝** | 不得选择。 |

| global 允许的 kind | | |
| global entry 的 owner 与撤销人 | | |
| tenant/domain grant 规则 | | |
| 解析、选择、审计中的可见性证明 | | |
| 决定 | □ APPROVE □ HOLD | |

## 6. RBAC 与 audit（提案签署）

tenant/data-domain fail-closed、资源不可见用 404、已知资源无操作权限用 403、模型内容问题与权限/状态问题分离，是冻结语义。Catalog permission 粒度和审计运营规则仍需签署。

### 6.1 RBAC [PROPOSAL-DECIDE]

| 操作 | 推荐 permission | 选择/实际 permission | domain/kind scope | 责任人 | 决定 |
|---|---|---|---|---|---|
| browse/search/resolve | `ecmc.catalog.read` | | | | □ APPROVE □ HOLD |
| 创建/编辑/取消自己的申请 | `ecmc.catalog.request` | | | | □ APPROVE □ HOLD |
| approve/retry fulfillment | `ecmc.catalog.approve` | | | | □ APPROVE □ HOLD |
| Resolver adapter service identity | 另立 service identity | | | | □ APPROVE □ HOLD |
| 审计读取 | `ecmc.causal_model.audit.read` | | | | □ APPROVE □ HOLD |

必须验证：未知角色、空域范围、跨 tenant/domain、仅有 `audit.read` 或仅有 `catalog.read` 时均不能扩大权限；取消只限申请人自己的未完成申请；approve 不能直接写权威目录。

### 6.2 audit [PROPOSAL-DECIDE]

建议复用 `audit_logs`，并至少记录 actor/role、tenant/domain、correlation、request/manifest/ref/version/hash、前后状态、operation/attempt（如适用）和脱敏理由。不得记录 credential、endpoint、原始业务数据、未授权目录内容或完整任意 proposal JSON。

| 决策项 | 选择/值 | 责任人 | 证据 | 决定 |
|---|---|---|---|---|
| 必审计事件集合（读/写/失败） | | | | □ APPROVE □ HOLD |
| event naming/version policy | | | | □ APPROVE □ HOLD |
| 留存期限与监管分区 | | | | □ APPROVE □ HOLD |
| 脱敏规则/检测测试 | | | | □ APPROVE □ HOLD |
| audit.read 可见范围 | | | | □ APPROVE □ HOLD |
| browse/search 是否逐次审计 | | | | □ APPROVE □ HOLD |

## 7. fulfillment callback 信任与对账

本节不冻结公共 HTTP。它只记录 Phase 3 前必须形成的内部 service contract；空白表示尚未授权接入。

### 7.1 必须签署的控制项 [PROPOSAL-DECIDE]

| 控制项 | 选择/值 | 责任人 | 证据 | 决定 |
|---|---|---|---|---|
| owner service identity/调用方 | | | | □ APPROVE □ HOLD |
| 传输信任（如 mTLS/签名消息/其他） | | | | □ APPROVE □ HOLD |
| kind + tenant/domain 授权绑定 | | | | □ APPROVE □ HOLD |
| callback 完整性覆盖字段 | | | | □ APPROVE □ HOLD |
| 密钥/证书签发、轮换、撤销 | | | | □ APPROVE □ HOLD |
| 认证/授权/签名失败告警 | | | | □ APPROVE □ HOLD |
| 普通用户不可直接标 `fulfilled` | **确认** | | | □ APPROVE □ HOLD |

完整性覆盖至少应包括 request ID、exact ref、status、content hash、manifest revision、correlation；若采用 operation/attempt，还必须覆盖以下两个身份。

### 7.2 operation/attempt、对账、幂等与重放 [PROPOSAL-DECIDE]

| 控制项 | 必须记录/选择 | 责任人 | 证据 | 决定 |
|---|---|---|---|---|
| `fulfillment_operation_id` 生成与持久化 | 一个申请首次派发后稳定；值/规则： | | | □ APPROVE □ HOLD |
| `attempt_id` 规则 | 每次 retry 新 attempt；值/规则： | | | □ APPROVE □ HOLD |
| retry lineage | 同一 operation，不覆盖旧 attempt/error | | | □ APPROVE □ HOLD |
| timeout/response lost | 先按 operation 对账；不确定时不直接创建新 operation | | | □ APPROVE □ HOLD |
| owner 对账接口/证据 | 查询/确认“成功、未执行、已终止、仍不确定”的证据位置： | | | □ APPROVE □ HOLD |
| callback 幂等 | 同一 operation+attempt+相同结果重复确认；冲突结果零写入 | | | □ APPROVE □ HOLD |
| 重放防护 | nonce/event ID/时间窗/唯一约束： | | | □ APPROVE □ HOLD |
| callback 成功条件 | active ref + tenant/domain/schema/hash re-resolve 通过 | | | □ APPROVE □ HOLD |
| 不确定结果的最终处置人 | | | | □ APPROVE □ HOLD |

明确拒绝只能记录 `fulfillment_failed`；超时或响应丢失不是确定失败，不能伪造失败或 fulfilled，也不能新增本表之外的治理状态。

## 8. fake/test endpoint 部署门禁

当前服务中的 `UnavailableCatalogResolver` 是生产 fail-closed 默认，`FakeCatalogResolver` 和 `EARP_ECMC_TEST_CATALOG=1` 只应服务 dev/test。以下控制目标必须在 Phase 0 签署，并在 Phase 1 形成可执行的部署 admission 证据；本表不宣称已有门禁已经实现。

| 门禁 | 通过证据 | 责任人 | 决定 |
|---|---|---|---|
| production/预发禁止 FixtureDiscoveryAdapter/FakeCatalogResolver | composition root/部署配置审查： | | □ APPROVE □ HOLD |
| fake 需同时满足 app_env、显式 sandbox/test 标记和 test catalog flag | admission policy/启动日志测试： | | □ APPROVE □ HOLD |
| production/预发误配 dev/test + flag 时拒绝启动或阻断发布 | 负向部署测试： | | □ APPROVE □ HOLD |
| test-only Catalog HTTP endpoint 与 fake 使用同一门控 | route registry/OpenAPI/访问测试： | | □ APPROVE □ HOLD |
| endpoint 不在 production OpenAPI/网络暴露面 | 生成 spec/网络策略证据： | | □ APPROVE □ HOLD |
| `testing`/`published_fixture` 不能成为 production active candidate | activation/Discovery 零写入测试： | | □ APPROVE □ HOLD |
| fake fixture hash 变化不能静默重算 | fixture manifest 负向测试： | | □ APPROVE □ HOLD |
| Case A 45 项回归继续通过 | 测试报告： | | □ APPROVE □ HOLD |

### 8.1 独立审查发现的未闭合门禁

以下项目来自本阶段独立验收，不是已批准的实现承诺。它们必须由具名 owner 补齐证据并签署；在关闭前不得以 Blueprint 状态、管理员权限或 test fixture 推断生产就绪。

| 未闭合门禁 | 当前边界/不得推断的语义 | 关闭证据 | owner | 决定 |
|---|---|---|---|---|
| production compile outbox consumer 尚无 | 仅有 outbox/event 记录或 compile 调用不等于生产消费、重试和对账已具备 | consumer 部署/运行证据、失败重试与幂等测试、告警/回滚演练 | | □ APPROVE □ HOLD |
| Discovery 必须显式 join N01A active pointers | 不能只依赖 Blueprint `status` 推断可发现性；必须同时满足 CausalModel active pointer 与 current compiled Blueprint 的 exact source pin，并通过 Catalog exact ref/status/domain/schema/hash 校验 | join 查询/Resolver contract vector、非 active/漂移/跨域负向测试 | | □ APPROVE □ HOLD |
| production separation-of-duties 策略尚未配置 | 不能默认 admin 可自行发布、批准并使 manifest/模型生效；admin 权限不构成签署事实 | RBAC policy、相互排斥角色负向测试、审计记录与 break-glass 规则 | | □ APPROVE □ HOLD |
| FixtureDiscoveryAdapter 独立类型/注册尚未发现 | 不得把 fixture adapter 的存在、注册或生产装配当作已确立事实；test-only 仍需显式隔离 | 独立 type/registry/composition-root 证据、production 禁止装配测试 | | □ APPROVE □ HOLD |

## 9. Phase 1 entry / exit gates

### 9.1 Phase 1 entry gate

Phase 1 仅实现 Resolver/read-port 抽象、manifest↔Resolver contract vectors、fail-closed 装配和 test-only 隔离；不写真实 Provider 或未签署目录。

| Entry gate | 必须证据 | owner | 决定 |
|---|---|---|---|
| §2 具名 A/RACI 完整 | 责任表 + 联系方式 + 代理人 | | □ APPROVE □ HOLD |
| manifest 签署对象/权威存储已定 | manifest hash、签署记录、存储/部署追溯 | | □ APPROVE □ HOLD |
| hash/schema canonical input 已确认 | 各 kind 算法/版本表 | | □ APPROVE □ HOLD |
| 重签/撤销和 inactive 运营策略已签署 | 变更/撤销 runbook | | □ APPROVE □ HOLD |
| global scope 已选择且有撤销传播 | policy/RLS 测试 | | □ APPROVE □ HOLD |
| RBAC 基础矩阵与 audit proposal 已登记 | 权限矩阵、审计字段/留存提案；细粒度生产策略仍按后续放行门禁签署 | | □ APPROVE □ HOLD |
| fake/test endpoint admission 控制目标已签署 | admission policy 与 deployment negative test 计划 | | □ APPROVE □ HOLD |

### 9.2 Phase 1 exit gate（进入 Phase 2 只读接入前）

| Exit gate | 必须证据 | owner | 决定 |
|---|---|---|---|
| Resolver `resolve/validate` 与冻结 v1.0 完全兼容 | adapter contract test + 五类 error test | | □ APPROVE □ HOLD |
| manifest↔Resolver 投影一致性向量通过 | hash/status/domain/schema/compatibility 逐字段测试报告 | | □ APPROVE □ HOLD |
| active/deprecated/inactive 行为符合冻结边界 | lifecycle/negative tests | | □ APPROVE □ HOLD |
| tenant/domain/global RLS 与权限负向全绿 | cross-tenant/cross-domain report | | □ APPROVE □ HOLD |
| manifest revision load/rollback/revoke 可演练 | runbook + drill evidence | | □ APPROVE □ HOLD |
| production root 保持 fail-closed，test root 明确隔离 | composition root test + deployment evidence | | □ APPROVE □ HOLD |
| browse/search 若实现，仍仅为签署后的 read contract | additive API/change record；否则保留 internal port | | □ APPROVE □ HOLD |
| 未创建 Provider/endpoint/credential 假设 | scope review | | □ APPROVE □ HOLD |
| lint、OpenAPI generation、`git diff --check` 和相关回归通过 | CI/build report | | □ APPROVE □ HOLD |
| FixtureDiscoveryAdapter 有独立类型/注册且仅 test 装配 | type/registry、composition-root 及 production 禁止装配证据 | | □ APPROVE □ HOLD |

Phase 1 exit decision：`□ APPROVE FOR PHASE 2`　`□ HOLD`
签署人：________________　责任角色：________________　日期：________________

### 9.3 Phase 3 callback / fulfillment gate

本门禁属于履约接入阶段，不是 Phase 1 adapter skeleton 的 entry 条件。没有本节签署，不能把 callback、重试或 owner 结果接入生产治理链路。

| Gate | 必须证据 | owner | 决定 |
|---|---|---|---|
| owner service identity 与 callback 认证/授权已确定 | identity、传输信任、kind + tenant/domain 绑定、密钥轮换测试 | | □ APPROVE □ HOLD |
| callback 完整性覆盖 operation/attempt 与 exact ref 投影 | 签名/可信通道覆盖字段和伪造负向测试 | | □ APPROVE □ HOLD |
| timeout/response lost 对账流程可执行 | owner 查询证据、不得直接新 operation 的测试、人工处置路径 | | □ APPROVE □ HOLD |
| operation/attempt 幂等与冲突零写入 | retry lineage、相同结果重复确认、冲突结果拒绝报告 | | □ APPROVE □ HOLD |
| 重放防护与 audit/告警已签署 | nonce/event ID/时间窗/唯一约束、审计和告警证据 | | □ APPROVE □ HOLD |
| callback 成功前重新 resolve active exact ref | tenant/domain/schema/hash/status re-resolve 测试 | | □ APPROVE □ HOLD |
| 普通用户不可直接标记 fulfilled | route/permission 负向测试 | | □ APPROVE □ HOLD |

Phase 3 gate decision：`□ APPROVE FOR FULFILLMENT ONBOARDING`　`□ HOLD`
签署人：________________　责任角色：________________　日期：________________

### 9.4 N01A 治理链路与生产放行门禁

以下三项是独立验收识别的 N01A/production release-readiness 缺口，不属于 Phase 1 adapter skeleton 的 entry。compile consumer 与 Discovery active gate 必须在 Phase 4 退出前关闭；职责分离最迟在 Phase 7 生产放行前关闭。

| Gate | 当前未闭合边界 | 必须证据 | owner | 最迟关闭阶段 | 决定 |
|---|---|---|---|---|---|
| production compile outbox consumer | outbox/event 记录或 compile 调用不等于生产消费、重试、幂等和对账已具备 | consumer 部署/运行、失败重试/幂等、告警与回滚演练 | | Phase 4 exit | □ APPROVE □ HOLD |
| Discovery join N01A active pointers | 不能只依赖 Blueprint `status`；需 join CausalModel active pointer 与 current compiled Blueprint exact source pin，再校验 Catalog exact ref/status/domain/schema/hash | join 查询/Resolver vectors、非 active/漂移/跨域负向测试 | | Phase 4 exit | □ APPROVE □ HOLD |
| production separation-of-duties | 不能默认 admin 可自行发布、批准并使 manifest/模型生效 | RBAC policy、发布/批准/生效角色隔离、admin 负向测试、审计与 break-glass 规则 | | Phase 7 release | □ APPROVE □ HOLD |

生产放行门禁决策：`□ APPROVE FOR RELEASE`　`□ HOLD`
签署人：________________　责任角色：________________　日期：________________

## 10. 未决项登记

| ID | 未决项 | 影响 | 责任人 | 截止日期 | 关闭证据 | 状态 |
|---|---|---|---|---|---|---|
| D-01 | Metric 权威来源 | | | | | `OPEN` |
| D-02 | 各 kind 具体 owner/系统 | | | | | `OPEN` |
| D-03 | manifest 权威存储与 revision identity | | | | | `OPEN` |
| D-04 | global scope 实现与撤销传播 | | | | | `OPEN` |
| D-05 | inactive entry 的已 active 模型 LKG 运营策略 | | | | | `OPEN` |
| D-06 | RBAC 粒度与 audit 留存 | | | | | `OPEN` |
| D-07 | callback 信任/对账/operation/attempt/重放 | | | | | `OPEN` |
| D-08 | fake/test endpoint admission | | | | | `OPEN` |
| D-09 | production compile outbox consumer 与运行/回滚证据 | Phase 4 exit | | | | `OPEN` |
| D-10 | Discovery 显式 join N01A active pointers，而非只依赖 Blueprint status | active candidate correctness；Phase 4 exit | | | | `OPEN` |
| D-11 | production separation-of-duties 策略与 admin 自发布负向门禁 | sign-off integrity；Phase 7 release | | | | `OPEN` |
| D-12 | FixtureDiscoveryAdapter 独立类型/注册及 production 禁止装配证据 | test-only isolation；Phase 1 exit | | | | `OPEN` |

## 11. 签署总表

| 签署角色 | 具名签署人 | 责任团队 | 结论 | 日期 | 签名/批准记录 |
|---|---|---|---|---|---|
| 产品负责人 | | | □ APPROVE □ HOLD | | |
| 平台架构负责人 | | | □ APPROVE □ HOLD | | |
| 数据域负责人 | | | □ APPROVE □ HOLD | | |
| 安全/RBAC 负责人 | | | □ APPROVE □ HOLD | | |
| 审计/合规负责人 | | | □ APPROVE □ HOLD | | |
| 运行平台负责人 | | | □ APPROVE □ HOLD | | |

**Phase 0 总结：** `□ READY FOR PHASE 1`　`□ HOLD`
**总负责人：** ____________________　**日期：** ____________________
**结论/例外说明：**

____________________________________________________________________

____________________________________________________________________
