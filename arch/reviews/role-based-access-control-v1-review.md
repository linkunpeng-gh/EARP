# role-based-access-control-v1.md 设计复审

**复审日期：2026-07-17（第 3 轮）**
**复审范围：** `arch/design/role-based-access-control-v1.md` v1.1 — 上一轮 1 P0 + 2 P1 的修复情况

---

## 上一轮修复验证

| 编号 | 问题 | 状态 | 证据（行号） |
|:----:|:-----|:----:|------|
| P0 | RAG SQL 丢失空数组兜底 | ✅ | L176: `(accessible_roles @> ARRAY[current_role] OR accessible_roles = '{}')` |
| P1 | §6 示例场景未同步三层防线 | ✅ | L306: `应用层 data_scope="all" → 无 role_id 过滤` |
| P1 | department 场景与实现偏差 | ✅ | L307: `只能看到自己拥有角色的执行记录（market_analyst + reporter，即 role_id IN (user_roles)）` |

---

## 🟡 本轮新增 P1

### 1. `build_data_filter` 引用了未定义的 `user_roles`

**位置：** §3.2 第 122-133 行

```python
def build_data_filter(role: Role, user_id: str) -> dict:  # ← 只有 2 个参数
    ...
    elif role.data_scope == "department":
        return {"role_id": ("IN", user_roles)}             # ← user_roles 不在参数中
```

`user_roles` 变量未作为函数参数传入，也未在函数体内定义。实施者无法知道这个变量的来源——是从全局上下文取，还是需要调用方注入。

**修复建议：** 改为 `def build_data_filter(role: Role, user_id: str, user_roles: list[str]) -> dict:`。

---

## 🔵 本轮新增 P2（3 个）

### 2. §4.3 DDL — audit_logs 变更描述自相矛盾

**位置：** §4.3 第 259 行

```
| audit_logs | ADD role_id VARCHAR（放入 detail JSONB 字段，与 Audit Spec v1.1 存储格式一致） |
```

`ADD role_id VARCHAR` 是新增独立列的 DDL，括号内又说"放入 detail JSONB 字段"。两句话矛盾——实施者不知道该执行 `ALTER TABLE audit_logs ADD COLUMN role_id VARCHAR` 还是在 JSONB 中追加字段。

**根因：** 上一轮 P2-2 修复时，作者想表达"不在 audit_logs 加独立列，用 detail JSONB 存储"，但保留了 `ADD role_id VARCHAR` 行头未改。

**修复建议：**
```
| audit_logs | 无需新增列 — detail JSONB 字段增加 role_id + user_roles（与 Audit Spec v1.1 一致） |
```

### 3. 同一概念两个名称：`knowledge_scopes` vs `knowledge_tags`

**位置：** §1.1 第 25 行 vs §3.1 第 79 行

| 位置 | 字段名 |
|------|--------|
| §1.1 实体关系图 | `Role.knowledge_scopes` |
| §3.1 Role 实体 | `knowledge_tags` |

语义相同（都是"角色可访问的知识文档标签"），但名称不一致。实施者在两个位置看到不同字段名会造成困惑。

**修复建议：** 统一为 `knowledge_tags`（与 §3.1 的实体定义保持一致）。

### 4. §1.2 规则 4 与 §3.2 三层防线矛盾

**位置：** §1.2 第 35 行

```
| 4 | 数据隔离按角色。RLS 过滤 `role_id IN (user_roles)` 或当前角色 |
```

§3.2 的 v1.1 修订已将 RLS 退为纯 tenant 隔离（`CREATE POLICY tenant_isolation`），角色过滤由应用层 `build_data_filter()` 承担。但这条规则仍写"RLS 过滤 role_id"，与设计方案矛盾——读者读完 §1.2 再看 §3.2 会困惑。

**修复建议：** 改为 `应用层按 role.data_scope 过滤角色数据（self/department/org/all），RLS 仅兜底 tenant 隔离`。

---

## 总结

| 级别 | 本轮 | 关键项 |
|:----:|:----:|:------|
| P0 | 0 | — |
| P1 | 1 | `user_roles` 变量在 `build_data_filter` 签名中缺失 |
| P2 | 3 | audit_logs DDL 自相矛盾 + knowledge_scopes/tags 命名不一致 + §1.2 规则 4 引用过时 |

**结论：核心设计逻辑全部正确。上一轮 P0 已修复，本轮无新增 P0。1 个 P1 + 3 个 P2 均为伪代码/文档文本一致性瑕疵，不影响设计语义，可随下个版本修复。**
