现在我已经完整读取了所有文件。让我对每个之前发现的问题逐一验证当前状态，然后给出最终复审报告。

---

# EARP 角色级访问控制 — 第4轮（最终）代码复审报告

**复审日期：2026-07-18**
**审查范围：R3 全部 18 项未修复问题（5 P0 + 9 P1 + 4 P2）**
**基线：** `arch/design/role-based-access-control-v1.md` v1.1

---

## 一、R3 遗留问题修复状态总览

| 级别 | R3 未修复 | 本轮已修复 | 仍未修复 | 修复率 |
|:----:|:--------:|:--------:|:--------:|:------:|
| **P0** | 5 | **5** | **0** | **100%** |
| P1 | 9 | **2** | 7 | 22% |
| P2 | 4 | **1** | 3 | 25% |
| **合计** | **18** | **8** | **10** | **44%** |

---

## 二、P0 逐项验证（全部修复 ✅）

### ✅ P0-3: 设计文档 §1.2 规则 4 与 §3.2 三层防线矛盾

**R3 状态：** `role-based-access-control-v1.md:35` 写"RLS 过滤 role_id"，与 §3.2 的"RLS 仅 tenant 隔离"矛盾。

**当前状态（L35）：**
```
| 4 | 数据隔离按角色。应用层按 data_scope 四层过滤（self/department/org/all），RLS 仅做 tenant 隔离兜底 |
```

**结论：已修复。** §1.2 规则 4 现在与 §3.2 三层防线完全一致。

---

### ✅ P0-4: Audit Spec 未列出 MUST 记录 role_id 的具体事件类型

**R3 状态：** detail 字段仍是 SHOULD 级别，未列出具体事件。

**当前状态（`audit-specification-v1.1.md:58-62`）：**
```
- detail: dict — 详细信息，以下事件类型 MUST 包含 role_id + user_roles（v1.2 新增）：
    - role_id:    string    — 操作时的当前角色
    - user_roles: list[str] — 用户拥有的所有角色
    MUST 事件：SESSION_CREATED, EXECUTION_STARTED, EXECUTION_COMPLETED, EXECUTION_FAILED,
              CAPABILITY_CALL, PERMISSION_DENIED, KNOWLEDGE_RETRIEVAL
```

**结论：已修复。** 明确列出了 7 类 MUST 事件，与设计文档 §3.6 要求完全对齐。

---

### ✅ P0-5: Multi-Tenant §5.4.1 影响实体表遗漏 Checkpoint

**R3 状态：** `multi-tenant-isolation-specification-v1.md:202-206` 表格只有 3 行（Session/Execution/AuditLog），Checkpoint 缺失。

**当前状态（L202-207）：**
```
| Session | `role_id: string` | 创建时的当前角色 |
| Execution | `role_id: string` | 继承 Session 的 role_id |
| Checkpoint | `role_id: string` | 继承 Execution 的 role_id |
| AuditLog | `detail.role_id: string`, `detail.user_roles: list` | 操作时的角色上下文 |
```

**结论：已修复。** Checkpoint 已加入表格，共 4 行完整覆盖。

---

### ✅ P0-6: Capability Spec 引用 visible_roles 但未在数据模型中定义

**R3 状态：** `capability-center-specification.md:262` 引用 `visible_roles`，但 §2.2 核心契约和 §3.3 Policy Layer 均无此字段。

**当前状态（`capability-center-specification.md:93`）：**
```
- visible_roles: list[str] — 可见角色列表，空=所有角色可见 (SHOULD，v1.4 新增)
```

**结论：已修复。** `visible_roles` 已在 §2.2 核心契约字段列表中正式定义，与 §5.1 角色筛选规则形成完整闭环。

---

### ✅ NP0-1: Policy Center §5.1 `User.current_role.permissions` 表达歧义

**R3 状态：** `policy-center-specification.md:109` 使用 `User.current_role.permissions`，暗示 ORM 嵌套对象但实际需要 JOIN。

**当前状态（L109-110）：**
```
MUST: 评估：查询当前角色 permissions = Role.find_by_id(User.current_role_id).permissions
        → 与 Capability.required_permissions 做子集判断（role.permissions ⊇ required_permissions）
```

**结论：已修复。** 现在使用明确的 `Role.find_by_id(User.current_role_id).permissions` 查询模式，消除歧义。

---

### 🎉 P0 总结：5/5 全部修复，P0 清零。

---

## 三、P1 逐项验证

### ❌ P1-1: Policy Center §5.3 'department' 命名与实际语义不符

**当前状态（`policy-center-specification.md:129`）：**
```
- department: 只能看到自己拥有角色创建的数据（role_id IN (user_roles)）
```

语义是"用户拥有的所有角色"而非"组织部门"。名称与实际行为不一致。

**建议：** 重命名为 `owned_roles` 或在注释中明确"此处的 department 指用户角色集合"。

---

### ❌ P1-2: Capability Spec 缺少 v1.2、v1.3 变更记录

**当前状态：** 附录 D 仅有 v1.0→v1.1 记录。v1.4 变更说明中提到 v1.1→v1.3 已有变更（三层结构+fallback_capability_id）但未在附录中补充。

---

### ❌ P1-3: client.py switch_role() 无 user_roles 校验

**当前状态（`client.py:51-58`）：**
```python
def switch_role(self, role_id: str) -> None:
    if not role_id:
        raise ValueError("role_id must not be empty")
    self._role_id = role_id
```

对比 `context.py:58-62` 有 `role_id ∈ user_roles` 校验，client.py 无此校验。

**评估：** 可接受的设计差异。client.py 是瘦客户端——`user_roles` 来自服务端 JWT claims，客户端不应自行维护角色列表。服务端在 Policy Center 评估时做权威校验即可。但建议在注释中明确说明。

---

### ✅ P1-4: Chunk 实体缺少 tenant_id

**当前状态（`knowledge-base-specification-v1.md:41`）：**
```
- tenant_id: string — 租户隔离（冗余，避免 RAG 检索时 JOIN Document）
```

**结论：已修复。** Chunk 增加 `tenant_id` 冗余字段，并标注了设计理由。

---

### ❌ P1-5: Knowledge Base Spec 缺少 accessible_roles 管理 API

**当前状态：** 规范定义了语义但无 API 端点（修改 accessible_roles、查询某文档的可访问角色列表等）。

**评估：** 属于后续实施阶段的 API 设计工作，规范层面可接受。

---

### ✅ P1-6: client.py call() 快捷方法不传递 role_id — R2 已修复，维持 ✅

---

### ❌ P1-7: knowledge_scopes vs knowledge_tags 命名不一致

**当前状态：**
- `role-based-access-control-v1.md:25` ER 图：`Role.knowledge_scopes`
- `role-based-access-control-v1.md:79` 实体定义：`knowledge_tags`

同一概念两个名称，实施者会困惑。

---

### ✅ R2-P1: build_data_filter 引用未定义的 user_roles

**当前状态（`role-based-access-control-v1.md:122`）：**
```python
def build_data_filter(role: Role, user_id: str, user_roles: list[str]) -> dict:
```

**结论：已修复。** `user_roles` 已加入函数签名。

---

### ❌ NP1-1: client.py switch_role() 与 context.py switch_role() 行为不一致

**client.py:** 仅校验非空
**context.py:** 校验 `role_id ∈ user_roles`

两个同名方法签名不同、校验逻辑不同。建议统一或在文档中说明差异原因（client 瘦代理 vs server 权威校验）。

---

### ❌ NP1-2: test_security.py 测试未覆盖角色相关功能

**当前状态：** 测试通过 `role_id="r1"` 但无专门的：
- `switch_role()` 行为测试
- `create_session()` role_id 缺失时 ValueError 测试
- `call()` 的 role_id 传递测试

---

## 四、P2 逐项验证

### ✅ P2-1: SDK 注释版本引用不统一 — R2 已修复，维持 ✅

### ⚠️ P2-2: core-py/config.py 变更未落地

**当前状态：** 设计文档 §4.2 明确标注 `core-py | — | —`（无变更）。之前的 P2-2 可能基于旧版设计文档提出，当前版本已明确无需变更。

**结论：** 可关闭——设计层面已确认 core-py 无需变更。

### ❌ P2-3: Capability Spec role_id 为空时行为未定义

**当前状态（`capability-center-specification.md:251`）：**
```
GET /capabilities/search?q={query}&role_id={role_id} — 发现（按角色过滤）
```

`role_id` 为空/未传时的行为未说明——向后兼容（返回全量）还是拒绝（400）？

### ✅ R2-P2: audit_logs DDL 描述自相矛盾

**当前状态（`role-based-access-control-v1.md:259`）：**
```
| audit_logs | 在 detail JSONB 字段中增加 role_id + user_roles（与 Audit Spec v1.2 对齐） |
```

**结论：已修复。** 删除了矛盾的 `ADD role_id VARCHAR`，明确在 JSONB 中存储。

### ❌ NP2-1: Capability Spec §5.1 符号 ⊇ 无文字说明

**当前状态（`capability-center-specification.md:262`）：**
```
- 评估：role.permissions ⊇ capability.required_permissions
```

虽然 Policy Center Spec 中有对应的文字说明，但 Capability Spec 自身缺少补充解释。

---

## 五、新增发现

### 🆕 NF-1（P2）: Policy Center §5.1 审计事件名称与 Audit Spec 不一致

**Policy Center L113：**
```
MUST: 角色切换需记录审计事件 ROLE_SWITCHED（detail: {from_role, to_role, user_id}）
```

**Audit Spec §2.1：** 未列出 `ROLE_SWITCHED` 事件。

Policy Center 要求审计 `ROLE_SWITCHED`，但 Audit Spec 的 MUST 事件列表中无此事件类型。

**建议：** Audit Spec 增加 `ROLE_SWITCHED` 到 MUST 事件列表。

---

## 六、最终统计

| 级别 | R3 遗留 | 本轮修复 | 本轮新增 | 最终未修复 |
|:----:|:------:|:------:|:------:|:--------:|
| **P0** | 5 | **5** | 0 | **0** ✅ |
| P1 | 9 | 2 | 0 | **7** |
| P2 | 4 | 1 | 1 | **4** |
| **合计** | **18** | **8** | **1** | **11** |

---

## 七、结论

### 🔴 核心结论：P0 全部清零，安全模型根基稳固。

**R1→R4 修复历程：**

| 轮次 | P0 数 | 关键修复 |
|:----:|:-----:|:--------|
| R1 初審 | 6 | — |
| R2 | 6→4 | P0-1（权限模型统一）、P0-2（create_session role_id 链路） |
| R3 | 4→5 | NP0-1 新增 |
| **R4 终審** | **5→0** | **P0-3（§1.2 规则4）、P0-4（Audit 事件列表）、P0-5（Checkpoint 表）、P0-6（visible_roles 定义）、NP0-1（评估路径）** |

### 剩余 11 项按严重程度分级：

**可上线前修复（P1 中的高优先级）：**
1. **P1-1** — `department` 命名误导，建议改为 `owned_roles`
2. **P1-7** — `knowledge_scopes` vs `knowledge_tags` 命名统一
3. **NF-1（新）** — Audit Spec 缺少 `ROLE_SWITCHED` 事件

**可在下版本修复（低优先级）：**
4. P1-2 — Capability Spec 补充 v1.2/v1.3 历史
5. P1-3/NP1-1 — client.py switch_role() 行为差异（设计上有合理解释）
6. P1-5 — KB Spec 管理 API
7. NP1-2 — 测试覆盖率补充
8. P2-3 — role_id 为空时行为定义
9. NP2-1 — ⊇ 符号补充文字

**核心安全链路已验证完整：**
- ✅ 单角色权限模型（Policy Center §5.1）
- ✅ create_session → role_id 写入链路（client.py）
- ✅ 三层防线设计一致（设计文档 §1.2 ↔ §3.2 ↔ Multi-Tenant §5.4）
- ✅ 审计角色追溯（Audit Spec §2.1 → 7 类 MUST 事件）
- ✅ 能力角色可见性（Capability Spec §2.2 visible_roles → §5.1 筛选规则）
- ✅ 知识库角色隔离（KB Spec §2.2 → Chunk tenant_id）
- ✅ 所有规范版本引用一致

**建议：修复 NF-1（Audit Spec 补充 ROLE_SWITCHED）+ P1-1/P1-7 两个命名问题后即可推进实施。**
