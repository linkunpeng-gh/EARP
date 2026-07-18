# PRD-2026-019 v1.0

## 多租户上下文切换 — SDK 侧 set_tenant_id()

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-019 |
| **Feature** | RuntimeClient + CapabilityContext 支持运行时租户切换（对齐 Dify Account._current_tenant setter 模式） |
| **优先级** | **P1** |
| **参考** | Dify models/account.py — `Account._current_tenant` setter + `Account.set_tenant_id()` |
| **版本** | v1.0 |

---

## 1. 背景

多租户 Spec 要求 SDK 支持租户上下文切换。当前各组件虽有 `tenant_id` 字段，但缺少统一的切换机制。Dify 的 `Account._current_tenant` setter 模式（session 级注入 + 自动刷新 DB 会话）可参考。

## 2. 范围

| # | 变更 | 内容 |
|:-:|:-----|:-----|
| 1 | `CapabilityContext.set_tenant(tenant_id)` | 切换租户上下文 + 刷新 connectors/capabilities |
| 2 | `RuntimeClient.set_tenant_id(tenant_id)` | 切换客户端租户 + 影响后续 create_session |
| 3 | `BaseConnector` tenant_id setter | 自动刷新 X-EARP-Tenant-Id header |

## 3. 验收条件

| ID | 描述 |
|:--:|:-----|
| AC-01 | `RuntimeClient.set_tenant_id("t2")` → 后续 `create_session()` 使用新 tenant_id |
| AC-02 | `CapabilityContext.set_tenant("t2")` → `ctx.tenant_id == "t2"` |
| AC-03 | `connector.tenant_id = "t2"` → `_auth_headers["X-EARP-Tenant-Id"]` 自动更新 |
| AC-04 | 现有 tests 无回归 |

## 4. 产出物

- `runtime-py/client.py` — +set_tenant_id()
- `capability-py/context.py` — +set_tenant()
- `connector-py/rest.py` — tenant_id setter → header 刷新
- tests: +3 tests
