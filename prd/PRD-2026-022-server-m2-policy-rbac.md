# PRD-2026-022 v1.0

## M2 — Policy Center + RBAC 服务端执行面

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-022 |
| **Feature** | PolicyLayer（鉴权+数据范围+输出过滤）+ 令牌桶限流 + Capability 按角色发现 + 审计增强 |
| **里程碑** | M2（依赖 M1 的 Layer 拦截器链 + Gateway JWT + Session/Invoke 基础） |
| **PRD 链** | ← PRD-2026-021(M1) ← PRD-2026-020(M0) |
| **上游设计** | RBAC v1.1 §三(方案设计) + §六(示例场景)；Policy v1.1；Capability v1.4；Tenant v1.2 |
| **状态** | v1.1（自检修复） |

> **v1.1 变更：** §1 补 PolicyLayer 数据获取路径（DB lookup role.permissions via tenant_session）；§2 US-03 明确 data_scope 过滤对象（StepResult.output 中 `created_by` 字段）；§1 #4 补 Redis 依赖说明；§3 AC-06 细化 RBAC §六 两个场景的具体断言；§1 #5 补 Capability discover 过滤算法

---

## 1. 范围表

| # | 域 | 功能 |
|:--|:---|:-----|
| 1 | Policy | PolicyLayer.before_step：从 DB 查 role.permissions（`SELECT permissions FROM roles WHERE role_id = :rid AND tenant_id = :tid`），判断 `required_permissions ⊆ role.permissions`。拒绝→403 + PERMISSION_DENIED CloudEvent |
| 2 | Policy | PolicyLayer.after_step：data_scope 四层过滤（self/department/org/all）——过滤 StepResult.output 中 `created_by` 字段；OutputFilter 按角色脱敏 |
| 3 | Policy | Policy 注册与管理：`POST /policies` → policy_bindings 绑定 capability→required_permissions |
| 4 | Policy | 令牌桶限流：per-tenant `rps=100`，Redis INCR+EXPIRE 实现（依赖：Redis 7.2 命令面已在 docker-compose 中，M2 首次引用；回退：开发环境可用进程内计数器） |
| 5 | Capability | `GET /capabilities?q=echo` 按角色过滤——db 层 JOIN `business_capabilities.required_permissions` 与 `role.permissions`（子集判定），只返回角色有权调用的 capability |
| 6 | Audit | AuditLayer 增强：CloudEvent.data 加 `role_id` + `role_permissions` |
| 7 | Audit | PERMISSION_DENIED 事件（含 denied capability + required_permissions） |

---

## 2. US

| US | 描述 | 类型 |
|:--:|:-----|:----:|
| US-01 | 用户以 R1 角色调用 echo capability（permissions 含 `demo:echo`）→ PolicyLayer before_step 通过 → invoke 成功 | 正常 |
| US-02 | 用户以 R2 角色调用 echo capability（permissions 不含 `demo:echo`）→ PolicyLayer 拒绝 → 403 + PERMISSION_DENIED 事件 | 权限 |
| US-03 | data_scope=self 角色调用 → after_step 过滤结果，只返回 `created_by` 匹配的行 | 过滤 |
| US-04 | 限流：10 请求/秒 → 第 11 次返回 429 | 限流 |
| US-05 | Capability discover 只返回角色有权的能力列表 | 可见性 |
| US-06 | audit_logs 的 EXECUTION_STARTED/COMPLETED 含 `role_id` 和 `role_permissions` | 审计 |

---

## 3. AC

| AC | 内容 | 验证方式 |
|:--:|:-----|:--------|
| AC-01 | 有权限→invoke 200；无权限→403 + audit_logs 有 PERMISSION_DENIED | pytest |
| AC-02 | data_scope=self → 过滤非本人数据 | pytest |
| AC-03 | 令牌桶 10rps → 第 11 个请求 429 | pytest |
| AC-04 | Capability discover 只返回角色可用的 capability | pytest |
| AC-05 | audit COMPLETED/PERMISSION_DENIED 含 role_id | pytest |
| AC-06 | RBAC v1.1 §六 场景可复现：① 角色 R1 有 `demo:echo` 权限→invoke 成功；角色 R2 无 `demo:echo`→403 + PERMISSION_DENIED 事件含 `{denied_capability, role_id, required_permissions}` ② data_scope=self 角色查 sessions 只返回自己创建的记录 | pytest（test_rbac_scenarios.py） |

---

## 4. 对齐检查

| 规范 | 关键条款 | 对齐 |
|:-----|:---------|:----:|
| RBAC v1.1 §3.1 | Role.permissions (list[str] domain:action) | ✅ |
| RBAC v1.1 §3.2 | data_scope 四层 (self/department/org/all) | ✅ |
| RBAC v1.1 §3.3 | Capability.required_permissions | ✅ |
| RBAC v1.1 §3.4 | accessible_roles + RAG 过滤（M4） | M2 只做 Capability 层 |
| RBAC v1.1 §六 | 示例 1(角色隔离) + 示例 2(权限拒绝) | ✅ AC-06 |
| Policy v1.1 | policy_bindings 表已建（M0 DDL） | ✅ |
| Tenant v1.2 | role_id 全链路（JWT → session → execution） | ✅ |
| Capability v1.4 | required_permissions 字段 | ✅ |

---

## 5. Gate 检查

| # | 检查项 | 状态 |
|:--|:-----|:----:|
| 1 | 依赖明确 | ✅ M1（Layer 链 + JWT + Session/Invoke + EventBus） |
| 2 | AC 可测试（全部自动化） | ✅ 6 条 |
| 3 | M0/M1 遗留已处理 | ✅ 0 遗留（全部 M1 清完） |
| 4 | 与冻结规范无矛盾 | ✅ |
