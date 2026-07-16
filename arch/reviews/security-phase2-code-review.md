# Security Phase 2 — 代码评审报告

## PRD-2026-006 v1.2 — 凭证加密 + 审计通道

| 字段 | 值 |
|------|-----|
| **评审范围** | 8 个文件变更 + 3 个新模块 + 3 个新测试文件 |
| **关联 PRD** | PRD-2026-006 v1.2 |
| **对齐 L3 设计** | security-phase2-l3-design-v1.1 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **问题统计** | P0: 0 / P1: 2 / P2: 3 → **共 5 个** |

---

## 测试结果

| SDK | 测试文件 | 数量 | 结果 |
|:----|:---------|:----:|:----:|
| earp-sdk-core | `test_credential.py` | 21 | ✅ |
| earp-sdk-core | `test_key_source.py` | 8 | ✅ |
| earp-sdk-core | `test_audit.py` | 8 | ✅ |
| earp-sdk-core | `test_masking.py` | 23 | ✅ |
| earp-sdk-connector | `test_connector.py` | 25 | ✅ |
| earp-sdk-runtime | `test_security.py` | 8 | ✅ |
| **合计** | | **93** | **全部通过** |

---

## 总体评价

**实现质量高，与 L3 设计文档精确对齐。** 三个新模块（`key_source.py`、`credential.py`、`audit.py`）结构清晰，测试覆盖全面（93/93 全部通过）。Phase 1 无回归。无 P0 阻塞问题。

核心亮点：lazy init 修复、unpickle 安全（抛异常 + `rehydrate`）、`from_plaintext` 的 `object.__setattr__` 绕过 setter、审计事件的 `except Exception: pass` + fallback 双通道降级。

---

## P0 — 必须修复（0 个）

无。

---

## P1 — 建议修改（2 个）

### P1-1：AUTH_EXPIRED 审计事件中 `tenant_id` 始终为空字符串

**文件**：`libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:93`

```python
publish_audit_event(AuditEvent(
    ...
    tenant_id=getattr(self, "tenant_id", ""),
    ...
))
```

`BaseConnector` 类没有 `tenant_id` 属性（只有 `connector_id`, `name`, `protocol`, `version`, `status`, `config`）。因此 `getattr(self, "tenant_id", "")` 始终返回 `""`。

**影响**：Audit Spec v1.1 §2.1 要求 `tenant_id` 为 MUST 字段。审计事件中 `tenant_id: ""` 意味着无法按租户过滤/聚合 AUTH_EXPIRED 事件。虽然 Phase 2 场景下 connector 确实不感知租户（租户隔离在 Runtime 层），但审计系统期望每个事件都带租户上下文。

**建议**：两种方案——

方案 A（Phase 2 务实方案）：在 docstring/AuditEvent 中注明 `tenant_id=""` 是合法的系统事件标记，与 Audit Spec 的 "system events may have empty tenant_id" 对齐。在 PRD 的 AC-05 中补充说明。

方案 B（后续完善）：在 `ConnectorConfig` 中增加 `tenant_id` 字段，connector 初始化时设置。

建议采用方案 A——Phase 2 的 scope 就是 SDK 侧，租户上下文由 Runtime 注入是合理的分工。

---

### P1-2：`EnvVarSource.get_key()` 的解码顺序（hex 优先）与 L3 设计文档不一致

**文件**：`libs/earp-sdk-core-py/src/earp_sdk_core/key_source.py:39-48`

| | L3 设计文档 v1.0/v1.1 | 实际实现 |
|:--|:----------------------|:---------|
| 解码顺序 | base64 优先，hex fallback | **hex 优先**，base64 fallback |

**设计文档**（`credential.py` 注释和 PRD §6.1）：
```
密钥: 32 字节，从 key_source 获取（默认 EARP_CREDENTIAL_KEY 环境变量，base64 或 hex 编码）
```

**实现代码**：
```python
# Try hex first, then base64
try:
    key = binascii.unhexlify(raw)      # hex first
except Exception:
    try:
        import base64 as _b64
        key = _b64.b64decode(raw, validate=True)  # base64 fallback
```

**风险**：理论上的边缘情况——如果一个 base64 密钥恰好全部由十六进制字符组成（概率极低但可能），会被 `unhexlify` 误解码，产生错误的 32 字节密钥。

**实际影响**：极低。随机生成的 32 字节密钥经 base64 编码后几乎不可能全部是 hex 字符 + 解码后恰好得到 32 字节。且代码会抛 `CredentialKeyError("Key must be 32 bytes")` 而非静默使用错误密钥。

**建议**：改为 base64 优先（与设计文档对齐）：
```python
# Try base64 first, then hex
try:
    key = base64.b64decode(raw, validate=True)
except Exception:
    try:
        key = binascii.unhexlify(raw)
    except Exception:
        raise CredentialKeyError(...)
```

---

## P2 — 优化建议（3 个）

### P2-1：`key_source.py:43` — 函数体内多余的 `import base64 as _b64`

虽然模块顶部已 `import base64`（第 9 行），但 `get_key()` 内部第 43 行又做了 `import base64 as _b64`。顶部导入未被使用，属于冗余代码。

**建议**：删除函数体内的 import，直接使用顶部导入的 `base64`。

---

### P2-2：`base.py:89` — `_on_error` 热路径中的局部 import

```python
if ce.code == ConnectorErrorCode.AUTH_EXPIRED:
    try:
        from earp_sdk_core import AuditEvent, publish_audit_event  # 每次 AUTH_EXPIRED 都 import
        publish_audit_event(AuditEvent(...))
    except Exception:
        pass
```

**分析**：这里局部 import 的设计意图是 "graceful degradation"——如果 `cryptography` 未安装导致 `credential.py` import 失败，audit 功能静默降级。这是正确的降级策略。

但 `earp_sdk_core.__init__` 在模块加载时就会 import `CredentialEncryptor` → `AESGCM`，所以如果 `cryptography` 没装，整个 connector SDK 的 import 会先失败（`test_connector.py` 已验证这一点）。因此这里的 `try/except ImportError` 保护实际上只在 `publish_audit_event` 本身抛出非 ImportError 的异常时有用（例如构造 AuditEvent 参数错误）。

**建议**：可以保持现状（局部 import 作为防御性编程），但考虑将 `except Exception: pass` 改为至少记录一个 debug 日志：
```python
except Exception:
    logger.debug("Audit event publishing failed", exc_info=True)
```

---

### P2-3：审计事件发布失败被静默吞掉

**文件**：`libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:100-101`

```python
except Exception:
    pass  # audit failure must not break error handling
```

**分析**：设计意图正确——审计通道故障绝不能阻止错误处理流程。但完全静默意味着如果 audit pipeline 全线故障（例如代码 bug 导致 AuditEvent 构造失败），运维完全感知不到。Phase 1 的 `logger.critical` fallback 只能覆盖 "audit 调用被 skip" 的场景，无法覆盖 "audit 调用本身抛异常" 的场景。

**建议**：在 except 块中加 debug 级别日志，方便排查：
```python
except Exception:
    logger.debug("Audit event publishing failed", exc_info=True)
```

这与 P2-2 是同一个 `except` 块，两条可以一起修。

---

## 实现与 L3 设计对齐检查

### SDKMUST 条款

| # | SDKMUST 条款 | 实现位置 | 状态 |
|:-:|:-----|:---------|:----:|
| 01 | `secrets.token_bytes(12)` nonce | `credential.py:41` | ✅ |
| 02 | decrypt 认证失败 → `InvalidTag` | `credential.py:48-53` docstring | ✅ |
| 03 | `EncryptedAuthConfig(AuthConfig)` 子类 | `credential.py:65` | ✅ |
| 04 | `__repr__` 不暴露明文 | `credential.py:164-171` | ✅ |
| 05 | `__getstate__` 仅返回密文 | `credential.py:175-182` | ✅ |
| 06 | `key_source` 可选，默认 `EnvVarSource` | `credential.py:26-27` | ✅ |
| 07 | 缺失/错误长度 → `CredentialKeyError` | `key_source.py:35-37, 49-52` | ✅ |
| 08 | `AuditEvent` 11 个字段 | `audit.py:14-32` | ✅ |
| 09 | UUID4 `log_id` + ISO 8601 `timestamp` | `audit.py:44-45` | ✅ |
| 10 | logger `"earp.audit"` INFO JSON | `audit.py:11, 48-49` | ✅ |
| 11 | `_decryptor is None` → `CredentialKeyError` + `rehydrate()` | `credential.py:120-124, 158-160` | ✅ |

**SDKMUST 11/11 全部实现。** ✅

### AC 覆盖

| AC | 描述 | 验证测试 | 状态 |
|:--:|:-----|:---------|:----:|
| AC-01 | encrypt/decrypt roundtrip, nonce 唯一性 | `test_credential.py` TestCredentialEncryptor (10 tests) | ✅ |
| AC-02 | repr/pickle/decrypt | `test_credential.py` TestEncryptedAuthConfig (11 tests) | ✅ |
| AC-03 | key_source + CredentialKeyError | `test_key_source.py` TestEnvVarSource (8 tests) | ✅ |
| AC-04 | 11 字段 JSON → earp.audit logger | `test_audit.py` (8 tests) | ✅ |
| AC-05 | AUTH_EXPIRED → publish + fallback | `test_connector.py` TestSecurityAuditPhase2 (2 tests) | ✅ |

**AC 5/5 全部覆盖。** ✅

---

## 代码质量观察

### 好的方面

- **L3 设计文档精准对齐** — `self.key` lazy init、`object.__setattr__`、`rehydrate()`、`__setstate__` 抛异常，所有设计要点全部准确落地
- **测试全面且有针对性** — P0-1 回归测试（`test_lazy_init_triggers_on_encrypt`）、pickle 安全性测试（密文不在二进制中 + 无 decryptor 抛异常）、nonce 唯一性、corrupted ciphertext、InvalidTag 验证
- **Phase 1 零回归** — 93 个测试全部通过，Phase 1 代码除 `_on_error` 的增量外无改动
- **降级策略务实** — audit 失败被 `except Exception: pass` 兜底 + `logger.critical` fallback 双通道，不会因审计通道故障阻塞核心流程
- **`cryptography` 选库正确** — AESGCM 高级 API 自动处理 tag 的生成和验证，比低级的 Cipher API 更不易出错

---

## 评审总结

### 数据统计

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| ❌ P0 | 0 | — |
| ⚠️ P1 | 2 | tenant_id 始终为空（审计事件质量）；hex 优先解码顺序与设计文档不一致 |
| 💡 P2 | 3 | 冗余 import；热路径 import；audit failure 静默 |

### 结论

**可以合并。** 实现质量高，SDKMUST 11/11 全部落地，93 个测试全部通过。2 个 P1 问题建议在合并后跟进，3 个 P2 问题可在后续迭代中顺手处理。

### 测试覆盖汇总

| 测试维度 | 测试数量 | 关键覆盖 |
|:---------|:--------:|:---------|
| encrypt/decrypt 基础 | 6 | roundtrip, unicode, empty, nonce 唯一性, wrong key, corrupted |
| encrypt/decrypt 初始化 | 3 | lazy init on encrypt, lazy init on decrypt, missing env var |
| EncryptedAuthConfig 行为 | 11 | isinstance, decrypt, repr, setter, empty, pickle, rehydrate |
| KeySource | 8 | base64, hex, custom var name, missing, invalid encoding, wrong/too long |
| AuditEvent | 8 | 11 fields, defaults, auto-gen, system event, JSON, null, unique log_id |
| Phase 1 regression | 31 | masking (23) + JWT propagation (8) |
| Phase 2 integration | 26 | connector (25 — incl. 4 Phase 1 security + 2 Phase 2 audit) |
| **总计** | **93** | |
