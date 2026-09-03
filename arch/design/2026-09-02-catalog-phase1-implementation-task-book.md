# EARP Catalog Phase 1 实施任务书

> 状态：待执行
> 编制日期：2026-09-02
> 依据：Catalog Phase 1 技术设计、产品页面设计及十一轮设计评审结论
> 适用范围：EARP Catalog Phase 1 开发、联调、验收与上线准备

## 1. 目标

将 Catalog Phase 1 已通过评审的设计转化为可开发、可验证、可上线的产品能力，交付语义引用注册、三层 Pack、Manifest 治理、Resolver、源系统同步、安全审批、5 个产品页面及运行门禁。

Catalog 的产品定位保持不变：**语义聚合与引用治理层**。语义定义由权威源系统维护，Catalog 只注册并治理 `{kind, stable_id, version, content_hash}` 引用，不成为第二语义编辑源。

## 2. 实施原则

1. 已冻结的 schema、canonicalization、hash、Resolver 错误语义和 fail-closed 规则不得在开发中隐式修改。
2. 对冻结契约的破坏性变更必须创建新 schema/canonicalizer 版本，旧 payload 不升级重算。
3. 每个工作包必须同时交付实现、自动化测试、运行证据和文档更新。
4. 安全、租户隔离、审计和故障降级不是上线后的补充项，必须随功能同步实现。
5. Phase 1 只实现本任务书范围；超出范围的需求进入 Phase 2 backlog。

## 3. 工作包总览

| 编号 | 工作包 | 核心结果 | 前置依赖 |
|---|---|---|---|
| M0 | 设计基线固化 | 形成可追溯、不可漂移的开发基线 | 无 |
| M1 | 数据与契约基础 | 数据模型、迁移、schema 和共享 hash 契约可用 | M0 |
| M2 | Catalog 核心服务 | 引用、Pack、Manifest 生命周期 API 可用 | M1 |
| M3 | Resolver | 精确解析、批量校验、缓存与 fail-closed 可用 | M2 |
| M4 | 源系统同步 | pull + webhook、幂等、LKG 和缺失确认闭环 | M2、M3 |
| M5 | 安全与治理 | RBAC、审批、SoD、审计和租户隔离闭环 | M2 |
| M6 | 产品页面 | 5 个页面完成业务闭环并与 API 联调 | M2–M5 |
| M7 | 上线准备 | CI、监控、演练、灰度和 readiness 门禁闭合 | M1–M6 |

建议主执行顺序：`M0 → M1 → M2 → M3/M5 → M4 → M6 → M7`。M3 与 M5 可在 M2 接口稳定后并行。

## 4. M0：设计基线固化

### 4.1 目标

把评审通过的设计、schema、fixture、canonicalizer 和 CI 校验固化为 Phase 1 开发的唯一依据。

### 4.2 任务

- [ ] 修正 `canonical_json_v1_for_test()` docstring 中的生产入口笔误。
- [ ] 将 Catalog Phase 1 新增设计、schema、fixture、脚本和 workflow 正式纳入 Git。
- [ ] 记录最终评审结论及保留的 readiness HOLD。
- [ ] 执行并保存以下基线证据：
  - [ ] 55 项 canonicalization 自测通过；
  - [ ] 10/10 golden fixtures 全字段匹配；
  - [ ] manifest 与 attestation schema/hash 校验通过；
  - [ ] r1/v1 与 v2 Profile 校验通过；
  - [ ] workflow YAML 解析通过；
  - [ ] `git diff --check` 通过。
- [ ] 确认当前算法正式冻结为 `sha256/canonical-json/v1`。
- [ ] 为 M1–M7 建立可跟踪的开发任务，并关联本任务书。

### 4.3 交付物

- Phase 1 设计基线 commit。
- 评审通过记录。
- CI 基线运行记录。
- M1–M7 开发任务清单。

### 4.4 退出标准

- 工作区内所有 Phase 1 资产均已纳入版本控制。
- 基线校验全部通过且结果可追溯。
- 冻结契约不存在未决 P0/P1。

## 5. M1：数据与契约基础

### 5.1 目标

建立 Catalog 服务的数据持久化、版本化契约和跨服务 hash 一致性基础。

### 5.2 任务

- [ ] 完成数据库表和 ORM 模型：
  - [ ] `catalog_refs`；
  - [ ] `catalog_packs`；
  - [ ] `catalog_pack_entries`；
  - [ ] `catalog_manifests`；
  - [ ] `catalog_manifest_entries`；
  - [ ] `catalog_active_manifests`；
  - [ ] `catalog_change_requests`；
  - [ ] `catalog_approvals`；
  - [ ] `catalog_sync_runs`；
  - [ ] `catalog_audit_logs`。
- [ ] 落实 tenant 维度唯一约束、外键、索引和状态约束。
- [ ] 落实 immutable revision、撤销、软删除和 active pointer 边界。
- [ ] 持久化 schema version、canonicalizer version、content hash 和 manifest hash。
- [ ] 抽取生产可复用的 canonicalization/hash 组件；生产入口强制提供 schema version。
- [ ] 接入 10 kind schema、manifest、pack、attestation 和 profile schema。
- [ ] 实现数据库 migration upgrade/downgrade 测试。
- [ ] 建立跨服务 golden fixture 一致性测试。

### 5.3 交付物

- 数据库 migration 和 ORM 模型。
- Catalog 契约/领域模型模块。
- 共享 canonicalizer/hash 组件。
- 数据模型及 hash 契约自动化测试。

### 5.4 退出标准

- Migration 可升级、可回退、可在空库重建。
- 唯一约束和不可变约束均有负向测试。
- 10/10 golden fixtures 在生产组件中计算一致。
- 未知 schema/canonicalizer version fail closed。

## 6. M2：Catalog 核心服务

### 6.1 目标

实现引用注册、Pack 组合和 Manifest 治理的完整后端生命周期。

### 6.2 任务

- [ ] 实现引用的注册、查询、列表、状态变更和撤销。
- [ ] 注册时从权威源系统获取 canonical input + 权威 hash，Catalog 独立复算并比较。
- [ ] 实现 Pack 创建、条目管理、不可变版本发布、导入和导出。
- [ ] 实现 platform/industry/enterprise 三层 Pack 组合。
- [ ] 实现相同 `(kind, stable_id, version)` 的一致去重与冲突 fail closed。
- [ ] 实现 pack lock 生成和校验。
- [ ] 实现 Manifest 生成、校验、发布、激活、撤销和回滚产生新 revision。
- [ ] 实现 manifest hash、attestation envelope hash 及签署绑定。
- [ ] 所有写操作支持幂等并记录审计。
- [ ] 输出并维护 OpenAPI 契约。

### 6.3 交付物

- Catalog Ref、Pack、Manifest API。
- Pack 组合器和 Manifest 生成器。
- OpenAPI 文档。
- 生命周期、冲突和 hash 负向测试。

### 6.4 退出标准

- 权威 hash 不一致时引用注册被拒绝并告警。
- 同版本不同语义/不同 hash 的 Pack 组合被拒绝。
- 已发布 Pack/Manifest 不可原地修改。
- 回滚产生新 revision，历史 revision 保持不可变。
- 未签署或已撤销 Manifest 不可激活。

## 7. M3：Resolver

### 7.1 目标

实现生产 Resolver API、缓存和运行时门禁，保证所有语义引用精确、隔离且可验证。

### 7.2 任务

- [ ] 实现 `/v1/catalog/resolve`。
- [ ] 实现 `/v1/catalog/validate`。
- [ ] 实现 exact ref 查询和批量解析。
- [ ] 返回统一的 `ResolvedRef` 和五类冻结错误语义。
- [ ] 校验 tenant、profile、active revision、kind、stable_id、version 和 content_hash。
- [ ] 实现缓存键 `{tenant, profile_id, active_revision, kind, stable_id, version}`。
- [ ] 实现 Manifest 激活/撤销后的缓存失效策略。
- [ ] 实现未注册、inactive、已撤销、hash 漂移、adapter identity 不匹配的 fail-closed。
- [ ] 确保生产 composition root 不可加载 Fixture Resolver。
- [ ] 落地正向、负向、批量、一致性、生命周期、跨域和冲突 contract vectors。

### 7.3 交付物

- Resolver API 与 adapter。
- Resolver cache。
- 全量 contract vectors 自动化测试。
- 性能测试和故障注入结果。

### 7.4 退出标准

- 全部 Resolver contract vectors 通过。
- 缓存命中性能达到设计目标。
- tenant A 无法观察 tenant B 的引用存在性。
- Fixture 不可进入生产 composition root。
- content hash 漂移时 exact ref 新引用被阻断并产生告警。

## 8. M4：源系统同步

### 8.1 目标

建立权威源系统与 Catalog 引用索引之间可靠、可审计且不会误下线的同步机制。

### 8.2 任务

- [ ] 定义统一 Source Adapter 接口。
- [ ] 实现可配置的定时 pull、分页、游标和断点续传。
- [ ] 实现 webhook 签名验证、防重放、幂等和乱序处理。
- [ ] 实现 pull 与 webhook 的一致性收敛。
- [ ] 实现超时、限流、5xx、部分分页失败的重试和告警。
- [ ] 实现 `suspected_missing` 状态及人工确认流程。
- [ ] 区分源对象真实删除、权限错误、分页错误和同步故障。
- [ ] 已有 Manifest 在同步异常时按 LKG 继续服务并告警。
- [ ] 新 Manifest 拒绝包含 `suspected_missing` 条目。
- [ ] 明确告警响应时限、恢复条件和审计字段。

### 8.3 交付物

- Source Adapter SDK/接口。
- pull scheduler 和 webhook handler。
- 同步状态机、告警和审计记录。
- 同步故障与恢复测试。

### 8.4 退出标准

- 重复或乱序事件不会产生重复版本或状态倒退。
- 单次 pull 缺失不会自动把引用标记为 inactive。
- 同步故障不影响已签署 Manifest 的 LKG 服务。
- 恢复后状态、告警和审计能够闭环。

## 9. M5：安全与治理

### 9.1 目标

实现最小可用且不可绕过的 RBAC、审批职责隔离、租户隔离和审计能力。

### 9.2 任务

- [ ] 落实 `read`、`request`、`approve`、`manifest.publish` 权限点。
- [ ] 角色可配置，权限点和系统危险能力不可由项目随意扩展。
- [ ] 实现变更申请、审批、驳回、撤回、候补审批和过期流程。
- [ ] 运行时按用户 ID 校验申请人与审批人不是同一主体。
- [ ] 实现 break-glass，强制理由、时限和 `audit_logs.emergency=true`。
- [ ] 实现 Pack 导出权限：仅 pack owner 或平台管理员。
- [ ] 实现 tenant 数据隔离和不可见 404 语义。
- [ ] 审计记录 actor、subject、tenant、资源、前后状态、原因、时间、request/correlation ID。
- [ ] 落实 180 天留存、脱敏和审计完整性要求。

### 9.3 必测负向场景

- [ ] 申请人审批自己的请求。
- [ ] 同一用户使用不同角色作为候补审批人。
- [ ] 无 `manifest.publish` 权限发布 Manifest。
- [ ] 非 pack owner/平台管理员导出 Pack。
- [ ] tenant A 读取或探测 tenant B 数据。
- [ ] 客户端伪造 content hash。
- [ ] 未签署或已撤销 Manifest 激活/解析。
- [ ] break-glass 未写 emergency 审计字段。
- [ ] 审计日志泄露敏感字段。

### 9.4 退出标准

- 所有越权和审批绕过测试均被拒绝。
- 用户主体隔离不依赖角色名或显示名。
- break-glass 全程可审计且自动失效。
- 审计字段和留存满足设计要求。

## 10. M6：产品页面

### 10.1 目标

实现 5 个页面及从配置、注册、审批、发布到生效和回滚的用户闭环。

### 10.2 建议实施顺序

1. `catalog-basics.html`：基础配置。
2. `metrics.html`：指标引用管理。
3. `binding-templates.html`：绑定模板管理。
4. `profiles.html`：项目 Profile 和 Pack Lock。
5. `catalog-admin.html`：治理中心和集成收口。

### 10.3 任务

- [ ] 按页面设计实现字段、操作流、权限态和审批态。
- [ ] 实现“选源系统 → 选对象 → 选版本”的引用注册流程。
- [ ] 实现 Pack 创建、发布新版本、导出、升级和冲突提示。
- [ ] 实现 Manifest 生成、审批、发布、激活、撤销和回滚入口。
- [ ] 实现同步状态、hash 不一致、`suspected_missing` 和 LKG 告警展示。
- [ ] 实现空状态、加载状态、部分成功、失败重试和无权限状态。
- [ ] 危险操作使用一致的确认与结果反馈。
- [ ] 完成可访问性、响应式和前端自动化测试。

### 10.4 退出标准

- 用户可从新建 Profile 完成到 Manifest 生效的全链路。
- 页面权限与 API 权限一致，不能仅依赖按钮隐藏。
- 发布新版本、升级、撤销和回滚语义清晰。
- 异常场景提供明确原因、影响范围和恢复动作。
- 产品验收和 API 联调通过。

## 11. M7：上线准备

### 11.1 目标

建立可观测、可灰度、可回滚、可演练的生产运行能力，关闭全部上线门禁。

### 11.2 任务

- [ ] 将 Catalog schema、golden、fixture、Profile、Resolver vectors 纳入 CI。
- [ ] 落实设计中的全部 `catalog-*` exit gate。
- [ ] 建立 API 延迟、错误率、缓存命中率、同步延迟、hash 漂移和审批积压监控。
- [ ] 配置告警级别、接收人、响应时限和升级路径。
- [ ] 制定灰度发布、数据库迁移、回滚和数据恢复方案。
- [ ] 执行 Manifest load、rollback、revoke 演练。
- [ ] 执行源系统超时、5xx、webhook 重放和 LKG 演练。
- [ ] 执行权限绕过、跨租户和 hash 篡改安全演练。
- [ ] 保存演练人、时间、前后 hash、Resolver 状态、审计记录和结论。
- [ ] 完成上线检查清单和运维手册。

### 11.3 Readiness HOLD

- [ ] 填实 3 个 `pack_lock` 的 version 和 content hash。
- [ ] 填写产品负责人真实联系方式。
- [ ] 10 kind owner 完成 canonical input/schema 确认。
- [ ] JQMK 初始引用清单使用真实 stable ID、version 和 content hash。

### 11.4 退出标准

- 所有 CI exit gate 通过。
- 所有 readiness HOLD 清零。
- 灰度、回滚、撤销和故障恢复演练通过。
- 产品、架构、数据、安全和运维共同确认上线。

## 12. Phase 2 Backlog（不进入本期）

- Ontology metric projection 切换。
- global scope / `global_enabled=true`。
- Pack 市场、跨组织分发和复杂导入迁移。
- 自动语义迁移和大规模批量升级。
- 高级语义血缘、影响分析和可视化。
- 多级、条件化审批编排。
- 智能语义推荐和自动匹配。

以上事项如需提前进入 Phase 1，必须重新评估范围、外部依赖、schema 版本和上线风险。

## 13. 项目级完成定义

Phase 1 只有同时满足以下条件才算完成：

- [ ] M0–M7 全部达到退出标准。
- [ ] 冻结设计与实现无漂移。
- [ ] 所有 P0/P1 已关闭，P2 已登记 backlog。
- [ ] 自动化测试、contract vectors 和安全负向测试全部通过。
- [ ] 5 个产品页面完成验收。
- [ ] 监控、告警、运维手册和演练证据完整。
- [ ] Readiness HOLD 清零。
- [ ] 最终版本提交 Git 并形成可追溯发布基线。
