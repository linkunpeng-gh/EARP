# PRD-2026-005 v1.1

## Security Spec 落地 — SDK 安全增强

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-005 |
| **Feature** | SDK 安全增强（跨 4 个 SDK + core） |
| **对齐规范** | arch/L2/06-security/security-specification-v1.md v1.1 |
| **优先级** | **P0** |
| **版本** | v1.1 |
| **日期** | 2026-07-14 |

---

## 1. 背景

Security Spec v1.1 定义了 40 条安全约束，但当前 SDK 代码中关键安全要求未落实。本 PRD 覆盖 Phase 1 的 3 项最大缺口。

## 2. 用户故事

| US | 描述 | 类型 |
|:--:|:-----|:----:|
| US-01 | JWT 已通过 `Authorization: Bearer <token>` 传递，permissions 在 JWT payload 中，服务端自行解析 | 正常 |
| US-02 | Connector SDK 的 `auth.token` 在日志中自动脱敏 | 安全 |
| US-03 | earp-sdk-core 提供 `mask_sensitive(data)` 函数，使用平台内置敏感字段列表自动脱敏 | 基础设施 |
| US-04 | AUTH_EXPIRED 时使用结构化日志记录审计事件 | 审计 |

## 3. 验收条件

| ID | 描述 | 影响 SDK |
|:--:|:------|:---------|
| AC-01 | JWT `Authorization: Bearer <token>` 在 Runtime SDK 的所有 HTTP 请求中正确传递（token 含 permissions，服务端解析） | Runtime |
| AC-02 | `RESTConnector._ensure_auth_headers()` 不将 token 明文写入任何日志调用 | Connector |
| AC-03 | `mask_sensitive(data)` 使用内置敏感字段列表自动脱敏，调用方不需要传 fields | Core |
| AC-04 | `mask_sensitive` 覆盖 Security Spec §3.2 的全部字段：password/token/secret/api_key → `"***"` | Core |
| AC-05 | AUTH_EXPIRED 时使用结构化 extra 字典记录审计事件（`logger.critical(msg, extra={"audit_type": ...})`) | Connector |

## 4. 依赖

| 依赖 | 状态 |
|------|:----:|
| earp-sdk-core | ✅ |
| earp-sdk-runtime | ✅ |
| earp-sdk-connector | ✅ |
| Security Spec v1.1 | ✅ |

## 5. 不做

- 凭证 AES-256 加密存储（Phase 2）
- InputGuard / OutputFilter（Phase 3）
- 完整审计事件发布通道（Phase 2）

## 6. 用户故事预期行为

### US-02：日志脱敏

```
预期行为：
  - auth.token 在任何 logger.info/warn/error 调用中不出现明文
  - mask_sensitive() 在日志输出前处理包含 token 的 dict
```

### US-04：审计事件

```
预期行为：
  - AUTH_EXPIRED 触发时，使用 logger.critical 记录结构化事件
  - extra dict 包含：audit_type="AUTH_EXPIRED", connector_id, timestamp
  - Phase 2 升级为 Audit Spec 定义的完整审计事件通道
```

## 7. 验收总结表

| # | 检查项 | 状态 |
|:-:|--------|:----:|
| 1 | US 完整 | ✅ 4 个 US，覆盖认证/脱敏/审计 |
| 2 | AC 可测试 | ✅ 5 条 |
| 3 | 依赖完整 | ✅ |
| 4 | P0 合理 | ✅ |

## 8. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | `mask_sensitive` 调用方传入字段列表与 Spec 冲突 | 改为 `mask_sensitive(data)` 内置敏感字段列表 |
| P0-2 | AC-01 permissions 注入方式未定义 | 明确 JWT 已含 permissions，SDK 只需要正确传递 token |
| P1-1 | logger.critical 非结构化 | AC-05 改为结构化 extra dict |
| P1-2 | 缺 §8/§9 | 新增验收总结表和修复记录 |
