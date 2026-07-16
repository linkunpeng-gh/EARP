# PRD-2026-005 评审报告

## Security Spec 落地 — SDK 安全增强

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-005 |
| **Feature** | SDK 安全增强（跨 4 个 SDK + core） |
| **对齐规范** | L2-06-SECURITY v1.1 |
| **评审人** | Review Agent |
| **日期** | 2026-07-14 |
| **状态** | ✅ 所有 P0/P1 已修复（v1.0 → v1.1） |

> **2026-07-14 更新**：PM Agent 已按本评审报告逐条修复。修复详情见 PRD §8 评审修复记录。当前 PRD 就绪，可进入 Gate 0 验收。

---

## 总体评价

**方向正确，4 个 User Story 精准对应 Security Spec 的 4 个缺口。** 跨 4 个 SDK 的范围定义合理——不是建一整套安全系统，而是补齐当前代码中的前 4 个安全缺口。

共发现 **2 个 P0（必须修复）、2 个 P1（建议修改）**。

---

## P0 — 必须修复

### P0-1：US-03/AC-03 `mask_sensitive()` 与 Security Spec §3.2 的要求不一致

**涉及段落：** §3 AC-03/AC-04

PRD 的 `mask_sensitive(data, fields)` 接受"敏感字段列表"作为参数，让**调用方**决定哪些字段是敏感的。但 Security Spec §3.2 的要求是：

```
MUST: 以下字段在日志/审计/API 响应中自动脱敏：
  - password, token, secret, api_key（全部替换为 "***"）
  - email ...
  - phone ...
  - id_card / ssn ...
MUST: 脱敏规则在 Gateway 层统一执行，不依赖各服务自行实现
```

Security Spec 要求的是**自动**、**统一**执行——脱敏的目标字段列表是平台级硬编码的，不是由调用方传入的。当前 PRD 的设计让调用方自己传 `fields`，这意味着：
- 每个调用方可能传不同的字段列表 → 不一致
- 调用方可能忘记传敏感字段 → 泄露风险

**建议方案：**

```python
# 改为：内置敏感字段列表，调用方不需要传 fields
def mask_sensitive(data: dict) -> dict:
    """自动脱敏内置敏感字段列表中的字段。
    
    内置列表：password, token, secret, api_key, email, phone, id_card, ssn
    """
    _SENSITIVE_FIELDS = {"password", "token", "secret", "api_key", ...}
    ...
```

或者保留 `fields` 参数但提供默认值——默认值使用 Security Spec 定义的完整敏感字段列表，调用方可选地传入额外字段。

---

### P0-2：US-01 "permissions 注入到 invoke 请求头" 不够具体

**涉及段落：** §3 AC-01

```
AC-01: RuntimeClient 创建时 token 解析出 permissions，注入到 invoke 请求头
```

Security Spec §5.1 要求：
```
MUST: JWT payload 包含 user_id、tenant_id、permissions
```

但 PRD 只说要"注入请求头"，没有定义具体格式：
- 是 `X-EARP-Permissions: read,write` 还是 `Authorization: Bearer <jwt>` 已经包含 permissions？
- 如果 JWT 已包含 permissions，为什么还要单独注入？
- 服务端如何消费这个 header？

**建议方案：**

明确 permissions 的传递方式。如果 JWT 已携带 permissions 声明，只需确保 JWT 正确解析并传递给服务端即可，不需要额外 header。

---

## P1 — 建议修改

### P1-1：US-04 审计日志使用 `logger.critical` — Security Spec 要求结构化审计

**涉及段落：** §3 AC-05

```
AC-05: ConnectorError(AUTH_EXPIRED) 触发时写入 logger.critical（审计通道占位）
```

这里明确说了是"审计通道占位"——但审计规范（L2-05-AUDIT v1.1）要求审计日志是结构化的（含 log_id、timestamp、tenant_id、event_type 等字段）。`logger.critical(...)` 是纯文本，不满足结构化要求。

**建议：** 明确第一阶段使用结构化日志格式（如 `logger.critical(msg, extra={"audit_type": "AUTH_EXPIRED", "connector_id": ..., "timestamp": ...})`），或在 AC 中注明"Phase 1 使用临时通道，Phase 2 升级为完整的审计事件发布"。

---

### P1-2：缺少 §8 验收总结表和 §9 评审修复记录

与其他四个 PRD（v1.1 格式）对齐，补充这两个章节。

---

## 对齐检查表

### 与 Security Spec v1.1 的对齐

| Security Spec 要求 | PRD 对应 | 状态 |
|:-------------------|:---------|:----:|
| JWT payload 含 permissions（§5.1） | AC-01 | ⚠️ 格式未定义 |
| auth.token 不在日志中出现（§2.2 MUST） | AC-02 | ✅ |
| 敏感字段脱敏（§3.2） | AC-03/AC-04 | ❌ P0-1 调用方传入字段列表 |
| 认证失败写入审计（§6.2 MUST） | AC-05 | ⚠️ logger.critical 非结构化 |

### 与先前 4 个 PRD 的对比

| 维度 | 之前 4 个 PRD | Security PRD |
|:----|:-----|:-----|
| US | 4-7 | 4 ✅ |
| AC | 9-15 | 5 ✅（范围小） |
| 跨 SDK | 单 SDK | **4 个 SDK 同时修改** ✅ |
| 交付物 | 详细文件列表 | ❌ 缺 |
| 用户故事预期行为 | 有 | ❌ 缺 |
| 评审修复记录 | §9 | ❌ |

---

## 评审总结

| 类别 | 数量 |
|:----|:----:|
| ✅ 检查项 | 5+ |
| ❌ P0 | 2 |
| ⚠️ P1 | 2 |

### 两个 P0

| # | 问题 | 修复 |
|:-|------|:-----|
| 1 | `mask_sensitive` 调用方传入敏感字段 → 与 Security Spec 的自动/统一要求冲突 | 内置敏感字段列表，调用方不需要传 |
| 2 | AC-01 permissions 注入方式未定义 | 明确 header 名和格式，或说明 JWT 已包含 |

### 好的方面

- 4 个 US 精准命中 4 个最大的安全缺口，没有试图覆盖全部 40 条 MUST
- AC 跨 SDK（Runtime/Connector/Core）的交叉影响定义清楚
- OOS 明确 Phase 2/3 的延期项（凭证加密、InputGuard/OutputFilter）
