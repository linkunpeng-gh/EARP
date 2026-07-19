# 短期清理评审报告

**日期:** 2026-07-19
**范围:** 3 个新文件 (workflow_dsl.py + policy_service.py + tenant_service.py)

---

## 逐项判定

| # | 检查项 | 判定 | 证据 | 级别 |
|:--:|:-----|:----:|------|:----:|
| 1 | workflow_dsl.py 四节点覆盖度 | ✅ | Sequential/Conditional/Parallel/StepNode 四节点 — 缺 Loop 节点 (M5 延后) | P2 |
| 1 | Conditional.flatten() | ✅ | L42-44 注释 "compile-time flatten includes both branches" — by design |
| 1 | Parallel.flatten() 退化 | ✅ | L55 注释 "M5: flattened to sequential" — documented |
| 1 | compile_workflow() 调用方 | ⚠️ | 全项目搜索结果为 0 | P2 |
| 2 | create_policy INSERT vs DDL | ❌ | `INSERT INTO policies (policy_id, tenant_id, name, resource_type, action, conditions)` vs DDL 列 `(policy_id, tenant_id, policy_type, rules, status, created_at)` — 不匹配 | P0 |
| 2 | bind_policy INSERT vs DDL | ❌ | `INSERT INTO policy_bindings (binding_id, tenant_id, policy_id, role_id)` vs DDL 列 `(policy_id, entity_type, entity_id, tenant_id)` — 不匹配 | P0 |
| 2 | ON CONFLICT | ✅ | policy_id 是单列 PK (DDL: `policy_id VARCHAR(64) PRIMARY KEY`) — 兼容但 INSERT 无 ON CONFLICT 子句 |
| 3 | ON CONFLICT (tenant_id, user_id) | ✅ | DDL: `PRIMARY KEY (tenant_id, user_id)` ✅ |
| 3 | get_user_tenants 无 tenant_id 过滤 | ⚠️ | 无 SET LOCAL — 依赖连接级别 RLS (tenant_account_joins 表启用了 RLS) | P1 |

---

## 问题清单

| ID | 级别 | 文件:行 | 问题 |
|:---|:----:|:--------|:-----|
| **P0-1** | 🔴 | `policy_service.py:28` | `create_policy` INSERT (policy_id, tenant_id, **name, resource_type, action, conditions**) — DDL 有 **(policy_id, tenant_id, policy_type, rules, status, created_at)**。PostgreSQL 抛 column 不存在错误 |
| **P0-2** | 🔴 | `policy_service.py:48` | `bind_policy` INSERT (**binding_id**, tenant_id, policy_id, **role_id**) — DDL 有 **(policy_id, entity_type, entity_id, tenant_id)**。**binding_id/role_id** 不在 DDL 列中, **entity_type/entity_id** 缺失 |
| **P1-1** | 🟡 | `tenant_service.py:29-33` | `get_user_tenants` 无 `SET LOCAL earp.tenant_id` — 依赖 RLS policy 兜底但 RLS 需要当前连接已设置 GUC |
| **P2-1** | 🔵 | `workflow_dsl.py:76-78` | `compile_workflow` 全项目搜索调用方 = 0 |

---

## 汇总

**2 P0 (DDL 列不匹配, policy_service.py 的 INSERT 无法执行), 1 P1 (tenant get_user_tenants 依赖 RLS), 1 P2 (DSL 编译器未引用)。P0 必须修复。**
