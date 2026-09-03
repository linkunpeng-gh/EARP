# EARP Catalog Phase 1 运维与验收手册

本手册只覆盖 Catalog Phase 1 的引用治理能力。Catalog 不保存权威语义编辑副本；所有注册、同步和导出操作都必须通过已配置的 SourceAdapter 从源系统复核。

## 发布前门禁

1. 运行 golden hash、fixture/schema、Profile 和 Catalog 校验脚本。
2. 运行服务端 Catalog contract、迁移升降级、OpenAPI 和页面 smoke 测试。
3. 确认每个生产 SourceAdapter 的 source identity、密钥、分页游标和真实 owner 已配置；缺失时保持 readiness HOLD。
4. 生成 Manifest preview，核对三层 Pack lock、effective entries、data domain 和 `manifest_hash`。
5. 将外部签署的 attestation 通过治理流程提交，使用新的幂等键激活；激活前填写 active revision CAS 值。

## 故障处置

- Resolver 返回五类冻结错误码之一时，先检查 tenant/profile/active revision、Ref 状态和 hash 漂移；不要通过 fixture 或放宽 fail-closed 绕过。
- pull 或 webhook 失败时，检查 `catalog_sync_runs` / `catalog_webhook_events`。已有签署 Manifest 继续按 LKG 提供服务；不得用单次缺失推断 inactive。
- `suspected_missing` 只能由权威源确认删除后刷新为 inactive；它不能进入新 Manifest。
- Pack hash 或 source hash 不一致时停止发布/导出，保留失败审计，修复源数据或注册的精确版本后重新申请。
- Manifest 需要撤销时使用 revoke；需要恢复历史内容时使用 rollback，必须生成更高的新 revision 和新 attestation，历史 revision 不可修改。

## 演练证据

每次演练记录：操作者 user ID、role、tenant、时间、相关幂等键、前后 manifest/pack hash、Resolver 状态、同步游标、审计 ID、故障原因、恢复动作和结论。真实通知接收人、响应 SLA 和升级路径由部署环境配置；未配置时不得宣称生产 readiness 已关闭。

## 当前 readiness HOLD

- 3 个生产 `pack_lock` 的真实 version/content hash 尚未填实。
- 产品负责人真实联系方式尚未由部署方配置。
- 10 个 kind 的 owner 和 canonical input/schema 尚待业务确认。
- JQMK 初始引用清单尚缺真实 stable ID、version 和 content hash。
- 真实源系统 endpoint、认证密钥、webhook 接收配置尚未接入；当前仅有明确隔离的 MockCatalogSourceAdapter 测试替身。
