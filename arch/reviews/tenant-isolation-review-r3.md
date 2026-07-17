# 多租户设计文档三次评审报告

## Multi-Tenant Isolation Spec v1.1 + PRD-2026-009 v1.1

| 字段 | 值 |
|------|-----|
| **Spec 版本** | v1.1 |
| **PRD 版本** | v1.1 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **上一轮** | [tenant-isolation-review-r2.md](../reviews/tenant-isolation-review-r2.md) — 2 个问题（1 P1 / 1 P2） |
| **本轮** | P0: 0 / P1: 0 / P2: 0 → **共 0 个** |

---

## 总体评价

**上一轮的 2 个问题全部修复。** Spec v1.1 + PRD v1.1 一致性好，可以进入 Gate 0。

无新增问题。

---

## 上一轮问题修复确认（2/2 ✅）

### P1-1（R2）：Spec §4.2.2 version byte 与 Phase 2 实现不一致 ✅

**修复**：Spec §4.2.2 改为两阶段格式：

```
Phase 2 当前格式: base64(nonce[12 bytes] + ciphertext[N bytes] + tag[16 bytes])
Phase 3+ 扩展格式: base64(version[1 byte] + nonce[12] + ciphertext[N] + tag[16])
         version = 0x01 → v1 格式（含 tenant 元信息）

Phase 2 密文不含 version byte。Phase 3+ 引入 version byte，与当前格式向后兼容
（密文长度不同，解密时自动识别：37+N bytes = Phase 2, 38+N bytes = Phase 3+）。
```

- ✅ Phase 2 格式明确无 version byte（与实现一致）
- ✅ Phase 3+ 升级路径清晰（长度自动识别）
- ✅ 向后兼容（37+N vs 38+N bytes）

---

### P2-1（R2）：PRD §6.1 代码注释 "HKDF 跳过" 与 AC-03 `HKDF(salt=b"")` 冲突 ✅

**修复**：PRD §6.1 line 82-84：

```python
# 向后兼容：无 tenant_id 时使用 HKDF(salt=b"") 派生密钥（空 salt）
enc_legacy = CredentialEncryptor()  # tenant_id="" → HKDF(salt=b"")
```

- ✅ 注释统一为 `HKDF(salt=b"")`（而非"跳过"）
- ✅ 与 AC-03 定义一致

---

## 终审：Spec vs PRD 双向一致性检查

| 主题 | Tenant Spec v1.1 | PRD-2026-009 v1.1 | 一致？ |
|:-----|:-----------------|:------------------|:------:|
| HKDF 算法 | §4.2.1: `HKDF-SHA256(IKM=32B, salt=UTF-8, info=b"...")` | — (implied by ref) | ✅ |
| tenant_id="" salt 行为 | §4.2.1: `salt 为空字节串 b""` | AC-03: `HKDF(salt=b"")` | ✅ |
| 向后兼容模式定位 | §4.2.1: "Phase 2 向后兼容模式" | AC-03: "过渡性，Phase 3 废弃" | ✅ |
| 密文格式 (Phase 2) | §4.2.2: `base64(nonce[12]+ciphertext+tag[16])` | （不在 PRD 范围） | ✅ |
| 密文格式 (Phase 3+) | §4.2.2: `version[1]=0x01` + 自动识别 | （不在 PRD 范围） | ✅ |
| X-EARP-Tenant-Id | §3.2: 非空时注入，系统级不注入 | AC-04: 非空时注入，系统级不注入 | ✅ |
| create_session tenant_id | （不在 Spec 范围） | AC-05: Sentinel 模式 | ✅ |
| 系统事件 tenant_id | §3.2: 绑定租户时携带，全局可为空 | （不在 PRD 范围） | ✅ |

---

## 最终评审总结

| 轮次 | P0 | P1 | P2 |
|:----:|:--:|:--:|:--:|
| R1 | 2 | 4 | 2 |
| R2 | 0 | 1 | 1 |
| R3 | **0** | **0** | **0** |

**三审零发现。Spec v1.1 + PRD v1.1 可以进入 Gate 0。**
