# 多租户隔离 Phase 2 — code-review 报告

## PRD-2026-009 v1.1 — 凭证密钥派生 + tenant_id 全链路补齐

| 字段 | 值 |
|------|-----|
| **评审工具** | /code-review (high effort, 8 angles, ≤10 findings) |
| **评审范围** | 6 个文件变更（rest.py, credential.py, client.py + 3 个测试文件） |
| **关联 PRD** | PRD-2026-009 v1.1 |
| **对齐规范** | Multi-Tenant Isolation Spec v1.1 §4.2, §3.2 |
| **日期** | 2026-07-15 |
| **问题统计** | P0: 0 / P1: 2 / P2: 1 → **共 3 个** |

---

## 测试结果

| SDK | 测试变更 | 数量 | 结果 |
|:----|:---------|:----:|:----:|
| earp-sdk-core | `test_credential.py` (+7 per-tenant tests) | 28 | ✅ |
| earp-sdk-connector | `test_connector.py` (+2 tenant header tests) | 27 | ✅ |
| earp-sdk-runtime | `test_security.py` (tenant_id 参数更新) | 8 | ✅ |
| **合计** | | **63** | **全部通过** |

---

## Finding 详情

### #1 — _ensure_auth_headers 缓存与 tenant_id 修改的冲突

**严重度**: correctness (高)  
**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/rest.py:106`  
**角度**: Angle A — line-by-line diff scan

```python
def _ensure_auth_headers(self) -> None:
    if self._auth_headers:       # ← 首次调用后非空，直接 return
        return
    if self.config and self.config.auth.token:
        ...                       # Authorization header 注入
    if self.tenant_id:            # ← X-EARP-Tenant-Id 注入
        self._auth_headers["X-EARP-Tenant-Id"] = self.tenant_id
```

**问题**：`_auth_headers` 在首次 `execute()` 调用后缓存（dict 非空）。如果 connector 的 `tenant_id` 在运行时被变更（如从一个租户切换到另一个），后续请求中 `X-EARP-Tenant-Id` 仍然发送旧值。

**场景**：
```
connector.tenant_id = "t1"
connector.execute("ping", ...)   # → X-EARP-Tenant-Id: t1  (缓存)
connector.tenant_id = "t2"       # 代码修改租户
connector.execute("ping", ...)   # → X-EARP-Tenant-Id: t1  (错误！仍发旧值)
```

**核心矛盾**：Authorization header（token）是连接级别的——同一个 connector 实例与一个外部系统的认证关系在生命周期内不变。`X-EARP-Tenant-Id` 也是连接级别的——但 tenant_id 有被变更的合法场景（如租户上下文切换）。

**建议**：将 tenant header 的注入逻辑移到 early-exit **之前**：

```python
def _ensure_auth_headers(self) -> None:
    # Tenant header: always apply on each call (may change at runtime)
    if self.tenant_id:
        self._auth_headers["X-EARP-Tenant-Id"] = self.tenant_id
    if self._auth_headers:  # auth headers already set
        return
    ...  # Authorization header 注入
```

或更清晰：将 tenant header 拆分到独立的 `_ensure_tenant_header()` 方法，在 `execute()` 的每个方法中独立调用。

---

### #2 — RuntimeClient.call() 绕过 Sentinel 守卫

**严重度**: correctness (中)  
**文件**: `libs/earp-sdk-runtime-py/src/earp_sdk_runtime/client.py:98`  
**角度**: Angle C — cross-file tracer

```python
# client.py:92-120
async def call(self, ..., *, tenant_id: str = "", ...):  # 默认 ""
    session = await self.create_session(
        user_id=user_id or "anonymous",
        tenant_id=tenant_id,      # ← 传入 ""
    )

# client.py:50-55
async def create_session(self, *, ..., tenant_id: str | object = _UNSET, ...):
    if tenant_id is _UNSET:
        raise ValueError("tenant_id is required ...")
```

**问题**：`call()` 是 `create_session()` 的唯一调用方之一（另一处是 `test_security.py`）。`call()` 的 `tenant_id` 默认值是 `""`（空字符串），不是 Sentinel `_UNSET`。

当调用方不传 tenant_id 时：
1. `call()` → `tenant_id=""`
2. `create_session(tenant_id="")` → `tenant_id is _UNSET` → False → 不抛 ValueError
3. Session 以 `tenant_id=""` 创建

这违反 Multi-Tenant Spec §3.2 MUST——"每个请求必然携带 tenant_id，不可选、不可省"。

**Sentinel 守卫仅对 `create_session()` 的直接调用有效，`call()` 捷径绕过了它。**

**建议**：两种修复方式——

方案 A（推荐）：`call()` 也采用 Sentinel：
```python
async def call(self, ..., *, tenant_id: str | object = _UNSET, ...):
    if tenant_id is _UNSET:
        raise ValueError("tenant_id is required (Multi-Tenant Spec §3.2 MUST)")
```

方案 B：`call()` 调用 `create_session` 前校验 `tenant_id` 非空：
```python
if not tenant_id:
    raise ValueError("tenant_id is required")
```

---

### #3 — _derive_key 手动实现 HKDF

**严重度**: simplification (低)  
**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/credential.py:24`  
**角度**: Reuse (手动实现已有库的功能)

```python
def _derive_key(master_key: bytes, tenant_id: str) -> bytes:
    salt = tenant_id.encode("utf-8") if tenant_id else b""
    prk = hmac.new(salt, master_key, hashlib.sha256).digest()
    okm = hmac.new(prk, _INFO + b"\x01", hashlib.sha256).digest()
    return okm
```

**问题**：`cryptography` 库已是硬依赖（`AESGCM`），其中有 `cryptography.hazmat.primitives.kdf.hkdf.HKDF` 完整实现了 HKDF。

手动实现的问题：
1. 当前 Expand 只产生单个 HMAC 块（32 字节），满足 AES-256 需求但不通用
2. 密码学代码应优先使用经过 review 的库实现

**抵消因素**：手动实现的 HKDF-Extract+Expand 是标准密码学模式（RFC 5869），两行代码逻辑简单正确（28 个测试验证无误），且避免了 `cryptography` 库版本升级对 HKDF API 的潜在 breaking change。

**建议**：当前实现可接受。如未来需要多块输出或多轮 Expand，可切换到 `cryptography.hazmat.primitives.kdf.hkdf.HKDF`。标记 P2，不阻塞合并。

---

## 代码亮点

- **Per-tenant HKDF 实现正确** — 同一 master key 派生不同 tenant 密钥，跨租户解密抛 InvalidTag；7 个新测试全覆盖
- **`_auth_headers` 缓存不变部分分离** — tenant header 可以独立更新（见 #1 建议）
- **测试精准** — 2 个 tenant header 测试覆盖注入+非注入场景；7 个 per-tenant 测试覆盖 key 不等、密文不同、跨租户失败、同租户互通、向后兼容
- **`hasattr` 改为显式类属性** — `BaseConnector.tenant_id` 已在 Phase 4 代码评审中修复
- **Sentinel 模式** — `_UNSET` 守卫模式干净，不 breaking 编译期

---

## 评审总结

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| P1 | **2** | `_auth_headers` 缓存导致 tenant_id 修改后 header 不更新；`call()` 绕过 Sentinel 守卫 |
| P2 | **1** | `_derive_key` 手动实现 HKDF（可用 cryptography 库实现） |

**可以合并。** 2 个 P1 均在调用方使用模式层面，修改量小（每处 <5 行）。P2 为代码共识建议。
