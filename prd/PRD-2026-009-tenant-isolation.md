# PRD-2026-009 v1.0

## 多租户隔离落地 — 凭证密钥派生 + tenant_id 全链路补齐

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-009 |
| **Feature** | 凭证加密密钥按 tenant_id 派生 + tenant_id 全链路补齐（JWT→Connector） |
| **对齐规范** | Multi-Tenant Isolation Spec v1.0 §6.2, §4.2; Security Spec v1.1 §2.2 |
| **优先级** | **P0** |
| **版本** | v1.1 |
| **日期** | 2026-07-15 |

> **v1.1 变更**：AC-03 补充过渡说明（tenant_id="" 为过渡模式）；AC-04 明确仅非空时注入 header；AC-05 改用 Sentinel 模式避免编译期 breaking。

---

## 1. 背景

当前 SDK 中 tenant_id 已存在于关键实体（Session/Execution/Context/BaseConnector），但存在两个缺口：

1. **凭证密钥未绑定租户**：`CredentialEncryptor` 使用统一的环境变量 `EARP_CREDENTIAL_KEY`，所有租户的凭证用同一密钥加密。如果某个租户的密文被泄露，攻击者只需获取全局密钥即可解密所有租户的凭证。

2. **Connector HTTP 请求未携带 tenant_id**：`RESTConnector` 的 `_ensure_auth_headers()` 只注入 `Authorization` header，不注入 `X-EARP-Tenant-Id`。外部系统无法区分请求来自哪个租户。

## 2. 用户故事

| US | 描述 | 类型 |
|:--:|:-----|:----:|
| US-01 | `CredentialEncryptor` 支持 `tenant_id` 参数，通过 HKDF 派生 per-tenant 密钥 | 安全 |
| US-02 | 同一 `EARP_CREDENTIAL_KEY` 下不同 tenant 的密文互不可解密 | 安全 |
| US-03 | `RESTConnector._ensure_auth_headers()` 注入 `X-EARP-Tenant-Id` header（当 connector.tenant_id 非空） | 隔离 |
| US-04 | `RuntimeClient.create_session()` 的 `tenant_id` 参数为 MUST（移除默认空字符串） | 隔离 |
| US-05 | `EncryptedAuthConfig.from_plaintext()` 支持 `tenant_id` 参数传递 | 安全 |

## 3. 验收条件

| ID | 描述 | 影响 SDK |
|:--:|:------|:---------|
| AC-01 | `CredentialEncryptor(tenant_id="t1").encrypt("x")` 与 `CredentialEncryptor(tenant_id="t2").encrypt("x")` 产生不同密文 | Core |
| AC-02 | `CredentialEncryptor(tenant_id="t1").decrypt(t2_cipher)` 抛 `InvalidTag` | Core |
| AC-03 | `CredentialEncryptor()` 无参构造保持向后兼容（tenant_id="" 时 salt 为空字节串，使用 HKDF(salt=b"") 派生密钥）。此模式为过渡性——Phase 3 在 TenantContext 就绪后废弃无 tenant_id 的构造。Phase 2+ 期间所有新增密文应使用 per-tenant encryptor | Core |
| AC-04 | `RESTConnector._ensure_auth_headers()` 当 `connector.tenant_id` 非空时注入 `X-EARP-Tenant-Id: {tenant_id}`。系统级 connector（tenant_id=""）不注入此 header | Connector |
| AC-05 | `RuntimeClient.create_session()` 的 `tenant_id` 参数默认值改为 `Sentinel`（`_UNSET = object()`），调用时未传入则运行时抛 `ValueError("tenant_id is required")`。不 breaking 现有调用方的编译期 | Runtime |

## 4. 依赖

| 依赖 | 状态 |
|------|:----:|
| earp-sdk-core (Phase 2 CredentialEncryptor) | ✅ |
| earp-sdk-connector (BaseConnector.tenant_id) | ✅ |
| earp-sdk-runtime | ✅ |
| Multi-Tenant Isolation Spec v1.0 | ✅ |

## 5. 不做

- LLM API Key per-tenant 独立存储（Phase 3）
- 资源配额执行（Phase 4）
- 缓存/文件路径 tenant_id 前缀（Phase 5）
- 数据库 RLS

## 6. 接口预览

### 6.1 CredentialEncryptor 密钥派生

```python
# Phase 2（当前）：统一密钥
enc = CredentialEncryptor()
cipher = enc.encrypt("api-key-123")

# Phase 2+（新增）：per-tenant 密钥
enc_t1 = CredentialEncryptor(tenant_id="t1")
enc_t2 = CredentialEncryptor(tenant_id="t2")

c1 = enc_t1.encrypt("same-secret")
c2 = enc_t2.encrypt("same-secret")
assert c1 != c2  # 不同密文（密钥不同）

# 跨租户解密失败
enc_t1.decrypt(c2)  # → InvalidTag

# 向后兼容：无 tenant_id 时使用 HKDF(salt=b"") 派生密钥（空 salt）
enc_legacy = CredentialEncryptor()  # tenant_id="" → HKDF(salt=b"")
legacy_cipher = enc_legacy.encrypt("old-data")
```

### 6.2 RESTConnector tenant header

```python
connector = RESTConnector()
connector.tenant_id = "t1"
connector.config = ConnectorConfig(
    base_url="http://api",
    auth=AuthConfig(type="bearer", token="sk-xxx"),
)

# _ensure_auth_headers() 注入两个 header:
#   Authorization: Bearer sk-xxx     （已有）
#   X-EARP-Tenant-Id: t1             （新增，当 tenant_id 非空）
```

### 6.3 RuntimeClient — tenant_id required

```python
# 旧（v0.1.0）：tenant_id 可选默认空
client = RuntimeClient(token=jwt, tenant_id="t1")  # tenant_id="t1" or ""

# 新（v0.2.0）：tenant_id 显式传入（创建 Session 时 MUST 非空）
client = RuntimeClient(token=jwt, tenant_id="t1")  # ✅ 显式传入
session = await client.create_session(user_id="u1", tenant_id="t1")
# tenant_id="" → ValueError (MUST)
```

## 7. 验收总结表

| # | 检查项 | 状态 |
|:-:|--------|:----:|
| 1 | US 完整 | ✅ 5 个 US |
| 2 | AC 可测试 | ✅ 5 条 |
| 3 | 依赖完整 | ✅ |
| 4 | P0 合理 | ✅ |
