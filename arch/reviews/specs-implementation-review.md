 # EARP 安全规范 + 多租户规范 实现状态附录评审
 
 > 评审 commit: `e36635bacb89445d8d7da6d7bd06f02e951d25c0`  
 > 评审日期: 2026-07-21  
 > 评审范围: arch/L2/06-security/security-specification-v1.md 第十章 + arch/L2/07-tenant/multi-tenant-isolation-specification-v1.md 第十章
 
 ---
 
 ## 一、Security Spec 实现状态表（11 条）
 
 ### 1. JWT 认证 (RS256) ✅ PASS
 
 - 落点: `gateway/auth.py`
 - 验证: `JWTMiddleware._decode()` 实现 HS256(dev) / RS256(prod) 双模式切换。`EARP_JWT_PUBLIC_KEY` 环境变量触发 RS256；回退到 HS256 dev secret。
 - 结论: 映射准确。
 
 ### 2. API 速率限制 ✅ PASS
 
 - 落点: `capability/registry.py:TokenBucketRateLimiter`
 - 验证: Redis INCR + EXPIRE 实现 per-tenant token bucket。Redis 不可用时 pass-through。
 - 结论: 映射准确。
 
 ### 3. 凭证加密存储 (AES-256-GCM) ✅ PASS
 
 - 落点: `libs/earp-sdk-core-py/credential.py`
 - 验证: `CredentialEncryptor` 使用 `AESGCM` + HKDF-SHA256 per-tenant 派生。`EncryptedAuthConfig` 实现透明的加密存储/解密读取。
 - 结论: 映射准确。
 
 ### 4. 敏感字段脱敏 (masking) ✅ PASS
 
 - 落点: `libs/earp-sdk-core-py/masking.py`
 - 验证: `mask_sensitive()` 含 dispatch 表，覆盖 password/token/secret/api_key/id_card/ssn/email/phone/authorization/auth。email 保留首字符+域名，phone 保留前3后4。
 - 结论: 映射准确。
 
 ### 5. InputGuard (注入检测) ✅ PASS
 
 - 落点: `gateway/input_guard.py`
 - 验证: `sanitize_body()` 使用 blacklist 正则检测 UNION SELECT / DROP TABLE / \<script\> 等模式。
 - 结论: 映射准确。
 
 ### 6. OutputFilter (LLM 输出) ✅ PASS
 
 - 落点: `libs/earp-sdk-core-py/guard.py`
 - 验证: `OutputFilter.check()` 实现 system prompt leak → blocked、dangerous code → filtered、PII → filtered 三级过滤。
 - 结论: 映射准确。
 
 ### 7. Plugin 沙箱 (Process 隔离) ✅ PASS
 
 - 落点: `libs/earp-sdk-plugin-py/sandbox.py`
 - 验证: `SandboxManager.run()` 通过 `subprocess.Popen` 在子进程中执行 plugin，JSON stdin/stdout 通信，timeout 后 SIGKILL 整个进程组。
 - 结论: 映射准确。
 
 ### 8. Plugin Daemon 独立进程 ✅ PASS
 
 - 落点: `entrypoints/plugin_daemon.py`
 - 验证: FastAPI HTTP 服务器，同步方法通过 `loop.run_in_executor` 线程池执行，异步方法通过 `asyncio.wait_for`。
 - 结论: 映射准确。实际路径为 `apps/earp-server/src/earp_server/entrypoints/plugin_daemon.py`，缩写可接受。
 
 ### 9. 凭证 key 不在日志中 ⚠️ PASS (有 ISSUE)
 
 - 落点: `libs/earp-sdk-connector-py/base.py`
 - 验证:
   - `base.py:_on_error()` 不记录 `config.auth.token` 或 `config.auth.password` 的值。
   - 保护机制是被动的（代码没有显式 log token），非主动的日志脱敏（如全局过滤器）。
   - `credential.py:EncryptedAuthConfig.__repr__` 输出 `<encrypted>` — 但这属于存储层保护，非运行时日志保护。
 - 结论: 功能成立（代码确实不会主动 log token），但"落点"描述过于乐观。**建议 v1.3 添加显式 log filter 或 middleware 级别的 Token 脱敏**。暂给 PASS 但记录为轻度 ISSUE。
 
 ### 10. AUTH_EXPIRED 审计事件 ✅ PASS
 
 - 落点: `libs/earp-sdk-connector-py/base.py`
 - 验证: `_on_error()` 在 `ConnectorErrorCode.AUTH_EXPIRED` 时发布 `AuditEvent(event_type="AUTH_EXPIRED")`。同时 `rest.py:_map_error()` 将 HTTP 401 映射为 `AUTH_EXPIRED`。测试文件 `test_connector.py` 覆盖 Phase 1（CRITICAL log）和 Phase 2（publish_audit_event）。
 - 结论: 映射准确，测试完备。
 
 ### 11. LLM 可观测性 (Langfuse) ✅ PASS
 
 - 落点: `infra/langfuse_tracer.py`
 - 验证: `LangfuseTracer` 封装 `trace_llm()` / `trace_embedding()` / `flush()`。无 key 时静默禁用。
 - 结论: 映射准确。
 
 ### Security Spec 小结
 
 | 状态 | 数量 | 明细 |
 |:---|:---:|:---|
 | ✅ PASS | 10 | #1-#8, #10-#11 |
 | ⚠️ PASS (有 ISSUE) | 1 | #9: 无主动日志脱敏 |
 | ❌ FAIL | 0 | — |
 
 ---
 
 ## 二、Tenant Spec 实现状态表（13 条）
 
 ### 1. tenant_id 全链路传播 ✅ PASS
 
 - 落点: `gateway/auth.py` → `runtime/session_service.py` → `capability/registry.py`
 - 验证:
   - `auth.py`: JWT payload 提取 `tenant_id` → `request.state.tenant_id`。
   - `session_service.py`: `create_session()` 插入 `sessions.tenant_id`。
   - `registry.py`: 所有查询带 `WHERE tenant_id = :tid`。
 - 结论: 全链路已验证，映射准确。
 
 ### 2. DB 层 RLS 隔离 ✅ PASS
 
 - 落点: `infra/db.py:tenant_session()` + 各 service 手动 SET LOCAL
 - 验证:
   - `tenant_session()` 使用 `set_config('earp.tenant_id', :tid, true)` (事务本地)。
   - 各 service（`session_service.py`, `registry.py`, `layers.py` 等）手动执行 `SET LOCAL earp.tenant_id = '{tid}'`。
   - 24 张表 `FORCE ROW LEVEL SECURITY` + tenant_isolation policy。
 - 结论: 映射准确。手动 SET LOCAL 模式存在冗余但功能正确。
 
 ### 3. SDK 层 tenant_id 传播 (X-EARP-Tenant-Id) ✅ PASS
 
 - 落点: `libs/earp-sdk-connector-py/rest.py` + `earp-sdk-runtime-py/client.py`
 - 验证:
   - `rest.py:_ensure_auth_headers()`: `self._auth_headers["X-EARP-Tenant-Id"] = self.tenant_id`。
   - `client.py:RuntimeClient.create_session()`: 接受 `tenant_id` 参数并通过 HTTP API 传递。
 - 结论: 映射准确。
 
 ### 4. 凭证密钥 HKDF per-tenant 派生 ✅ PASS
 
 - 落点: `libs/earp-sdk-core-py/credential.py`
 - 验证: `_derive_key(master_key, tenant_id)` 使用 `HMAC-SHA256(salt=tenant_id_utf8, IKM=master_key)` 作为 HKDF-Extract。
 - 结论: 映射准确。
 
 ### 5. 密文格式 version byte 预留 ⚠️ PASS (有 ISSUE)
 
 - 落点: `libs/earp-sdk-core-py/credential.py`
 - 验证:
   - 实际密文格式: `base64(nonce[12] \|\| ciphertext[N] \|\| tag[16])` — **version byte 不存在**。
   - 文档注释提到"Phase 2 format"和"Phase 3+ will require per-tenant encryptors"，但 ciphertext 中没有版本号前缀。
   - 如果未来升级加密算法，现有代码无法区分旧格式和新格式。
 - 结论: 状态标记 ✅ 过于乐观。Version byte **仅在设计注释中提到，未实际预留**。建议：1) 在 Phase 3 加入 1-byte 版本前缀；2) 或澄清该状态为 "⏳ 设计完成，Phase 3 实现"。
 
 ### 6. 角色级数据隔离 (data_scope) ❌ FAIL
 
 - 落点（声称）: `policy/service.py (data_scope 过滤)`
 - 验证:
   - **`policy/service.py` 是空存根**，仅有 `__all__: list[str] = []`。无 data_scope 过滤逻辑。
   - 实际 data_scope 过滤实现位于 **`orchestrator/layers.py:PolicyLayer.after_step()`**，查询 `roles.data_scope`，对 self/department/org 层级过滤 `result.output`。
 - 结论: ❌ FAIL — 落点文件错误。实现代码不在 `policy/service.py` 而在 `orchestrator/layers.py`。**建议将"落点"修正为 `orchestrator/layers.py:PolicyLayer.after_step()`**。
 
 ### 7. Session/Execution 写入 role_id ✅ PASS
 
 - 落点: `migrations/0001_baseline.py` + `runtime/session_service.py`
 - 验证:
   - DDL: `sessions.role_id VARCHAR(64) NOT NULL`, `executions.role_id VARCHAR(64) NOT NULL`。
   - `session_service.py:create_session()`: `INSERT ... role_id`。
 - 结论: 映射准确。
 
 ### 8. Role-filtered Capability 发现 ✅ PASS
 
 - 落点: `capability/registry.py`
 - 验证: `discover()` 接受 `role_id`，使用 `required_permissions <@ r.permissions` 进行数组包含过滤。
 - 结论: 映射准确。
 
 ### 9. RLS 全表数据级矩阵 ✅ PASS
 
 - 落点: `migrations/0001_baseline.py`
 - 验证: `TENANT_TABLES` 含 24 张表，每张 `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation`。
 - 结论: 映射准确。
 
 ### 10. 多租户账号 (tenant_account_joins) ❌ FAIL — DDL/Service 列名不匹配
 
 - 落点: `runtime/tenant_service.py`
 - 验证结果:
   - DDL 定义 (`0001_baseline.py`):
     ```sql
     tenant_account_joins (
         tenant_id       VARCHAR(64) NOT NULL,
         user_id         VARCHAR(64) NOT NULL,
         role_ids        TEXT[] NOT NULL DEFAULT '{}',
         current_role_id VARCHAR(64),
         PRIMARY KEY (tenant_id, user_id)
     )
     ```
   - Service 代码 (`tenant_service.py`):
     ```python
     INSERT INTO tenant_account_joins (tenant_id, user_id, role_id, org_unit_id)
     ```
 - 问题: **3 处不匹配**:
   1. DDL 无 `role_id` 列（有 `role_ids TEXT[]` 和 `current_role_id VARCHAR(64)`），service 使用 `role_id`。
   2. DDL 无 `org_unit_id` 列，service 使用 `org_unit_id`。
   3. DDL 的 `role_ids` 是 `TEXT[]`（数组类型），service 尝试插入标量字符串（类型不匹配）。
 - 结论: ❌ FAIL — 运行时必然报错。**这是一个 BUG，必须修复**。
 
 ### 11. Rate Limit per-tenant ✅ PASS
 
 - 落点: `capability/registry.py:TokenBucketRateLimiter`
 - 验证: key 格式 `rate:{tenant_id}:{timestamp}`，per-tenant 限流。
 - 结论: 映射准确。
 
 ### 12. 审计日志 tenant_id 必填 ✅ PASS
 
 - 落点: `audit/consumer.py`
 - 验证: DDL `audit_logs.tenant_id VARCHAR(64) NOT NULL`；Consumer 写入 `event.tenant_id`；`SET LOCAL earp.tenant_id` 确保 RLS 通过。
 - 结论: 映射准确。
 
 ### 13. Langfuse 追踪 tenant 隔离 ✅ PASS
 
 - 落点: `infra/langfuse_tracer.py`
 - 验证: `trace_llm()` 接受 `metadata` 参数，可传入 `tenant_id` 作为 Langfuse trace 标签。
 - 结论: 映射准确。注意此为"按 tenant 标记"而非 "strict 隔离"。
 
 ### Tenant Spec 小结
 
 | 状态 | 数量 | 明细 |
 |:---|:---:|:---|
 | ✅ PASS | 10 | #1-#5, #7-#9, #11-#13 |
 | ⚠️ PASS (有 ISSUE) | 1 | #5: version byte 未实际写入密文 |
 | ❌ FAIL | 2 | #6: 落点文件错误; #10: DDL/Service 列名不匹配（BUG） |
 
 ---
 
 ## 三、版本号与依赖引用检查
 
 | 检查项 | 状态 | 说明 |
 |:---|:---:|:---|
 | Security Spec 版本号 | ✅ | v1.1 → v1.2，正确递增 |
 | Tenant Spec 版本号 | ✅ | v1.2 → v1.3，正确递增 |
 | Security Spec 依赖 | ✅ | L2-05-POLICY v1.0, L2-05-AUDIT v1.1, L2-05-OBSERVATION v1.1 均有效 |
 | Tenant Spec 依赖 | ⚠️ 轻微 | 依赖 `L2-06-SECURITY v1.1`，但 Security Spec 已升级到 v1.2。如 Tenant 第10章引用了 Security v1.2 新增内容，则依赖应提升至 v1.2。当前引用内容（§4.2 凭证加密）在 v1.1 中已存在，不影响正确性——但建议同步。 |
 
 ---
 
 ## 四、遗漏的实现项
 
 以下为两规范第十章实现状态表中**未覆盖**的内容。建议评估是否应在 v1.x 阶段纳入。
 
 ### 遗漏项 A — RLS 统一 entry point
 
 - 来源: Tenant Spec §3.2 / DB 层隔离
 - 现状: 各 service 独立调用 `SET LOCAL earp.tenant_id`。`infra/db.py:tenant_session()` 提供了 context manager 但部分 service（如 `session_service.py`, `tenant_service.py`）仍手动执行 SQL。
 - 风险: 低。功能正确但模式不统一，容易因遗忘 `SET LOCAL` 导致跨租户数据泄漏。
 - 建议: 统一使用 `tenant_session()` context manager，消除手动 SET LOCAL 的分散模式。
 
 ### 遗漏项 B — RLS bypass 迁移账号隔离
 
 - 来源: Tenant Spec §4.2
 - 现状: DDL 中 migration 阶段使用 BYPASSRLS 角色（`earp_app` 无 BYPASSRLS），但未验证所有非迁移连接都使用 `earp_app` 角色。
 - 风险: 中。配置错误可能导致 RLS 被绕过。
 - 建议: 在文档中明确部署检查清单，确认 Production 数据库连接字符串对应 `earp_app`（非 BYPASSRLS 角色）。
 
 ### 遗漏项 C — OutputFilter 未串联到 Capability 调用链
 
 - 来源: Security Spec §4.1（Capability 链拦截器）
 - 现状: `guard.py:OutputFilter` 类已实现，但在 `orchestrator/layers.py` 中仅有 `PolicyLayer.after_step()` 做 data_scope 过滤，**未调用 `OutputFilter.check()`**。
 - 风险: 中。OutputFilter 的 PII 检测、危险代码检测、system prompt leak 检测在生产路径上未被激活。
 - 建议: 在 `orchestrator/layers.py` 中新增一个 `SecurityLayer.after_step()` 调用 `OutputFilter.check()`。
 
 ### 遗漏项 D — credential key 运行时日志脱敏
 
 - 来源: Security Spec §2.1 / 本评审 #9
 - 现状: 无主动日志脱敏机制。
 - 建议: 添加 `logging.Filter` 或 structlog 的 `before_send` hook，正则替换日志中的 Bearer token 和 Authorization header。
 
 ### 遗漏项 E — 各 service 手动 SET LOCAL 分散
 
 - 来源: Tenant Spec §3.1 / Security Spec 交叉引用
 - 现状: `capability/registry.py:discover()` 直接使用 `engine.connect()` + 手动 `SET LOCAL`，未复用 `tenant_session()` context manager。
 - 建议: 统一迁移到 `tenant_session()`。
 
 ---
 
 ## 五、总体评价
 
 | 维度 | 评分 | 说明 |
 |:---|:---:|:---|
 | Security Spec 映射准确度 | 10/11 ✅ | #9 功能成立但缺少主动日志脱敏 |
 | Tenant Spec 映射准确度 | 10/13 ✅ | #6 落点错误，#10 DDL/Service 不匹配 |
 | 版本号一致性 | ✅ | 小问题（依赖版本未同步） |
 | BUG | 1 | #10 tenant_account_joins 运行时必报错 |
 | 需紧急修复 | #6 落点说明 / #10 DDL/Service 对齐 | 如果 deploy 了当前代码则 #10 为必须修复的 BUG |
 
 ### 立即修复建议
 
 1. **P0 — `tenant_service.py` DDL/Service 列对齐**: 修复列名不匹配（role_id → current_role_id/role_ids，移除或添加 org_unit_id 列）。
 2. **P1 — 修正 `data_scope` 落点**: 将实现状态表 #6 的落点从 `policy/service.py` 改为 `orchestrator/layers.py:PolicyLayer.after_step()`。
 3. **P2 — 串联 OutputFilter 到运行时**: 在 orchestrator 层添加 SecurityLayer 调用 OutputFilter。
 4. **P3 — version byte 实际预留**: 在 ciphertext 之前加入 1-byte 版本前缀。
 5. **P3 — 统一使用 tenant_session()**: 消除分散的手动 SET LOCAL 模式。
