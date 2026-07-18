Now let me also check the Knowledge Base spec:

Now I have all the information needed for a comprehensive re-review. Let me compile the findings.

---

# EARP 角色级访问控制 — 第2轮代码复审报告

**复审日期：2026-07-18**
**审查范围：** R1 全部 16 项（6 P0 + 7 P1 + 3 P2）+ R2 全部 4 项（1 P1 + 3 P2）
**基线：** `arch/design/role-based-access-control-v1.md` v1.1

---

## 一、R1 修复状态总览

| 级别 | 总数 | 已修复 | 未修复 | 修复率 |
|:----:|:----:|:------:|:------:|:------:|
| P0 | 6 | **2** | 4 | 33% |
| P1 | 7 | **1** | 6 | 14% |
| P2 | 3 | **1** | 2 | 33% |
| **合计** | **16** | **4** | **12** | **25%** |

---

## 二、逐项验证

### ✅ P0-1: Policy Center §5.1 权限模型自相矛盾 — 已修复

**R1 问题：** MUST（单角色评估）与 SHOULD（多角色并集）矛盾。

**当前状态：** `policy-center-specification.md:113` 新增：
```
MUST: 权限评估以当前角色为准——不可跨角色合并权限（如需更高权限，显式切换角色）
```
旧的 SHOULD 并集条款已删除。安全模型现在完全一致：以 `current_role.permissions` 单一评估。

---

### ✅ P0-2: client.py create_session() 缺失 role_id 参数 — 已修复

**R1 问题：** `create_session()` 不接受 `role_id`，`self._role_id` 从未发送。

**当前状态：** `client.py:62-116` 完整实现：
```python
async def create_session(
    self, *,
    user_id: str,
    tenant_id: str | object = _UNSET,
    role_id: str | object = _UNSET,    # ← 新增
    ...
) -> Session:
    ...
    if role_id is _UNSET:
        if self._role_id:
            role_id = self._role_id
        else:
            raise ValueError("role_id is required ...")  # ← 必须提供
    ...
    json={"user_id": user_id, "tenant_id": tenant_id, "role_id": role_id, ...}  # ← 实际发送
```

参数链条完整：`switch_role()` → `self._role_id` → `create_session()` fallback → JSON body。第一条防线（Session 创建时写入 role_id）已可实施。

---

### ❌ P0-3: 设计文档 §1.2 规则 4 与 §3.2 三层防线矛盾 — 未修复

**当前状态：** `role-based-access-control-v1.md:35` 仍然是：
```
| 4 | 数据隔离按角色。RLS 过滤 `role_id IN (user_roles)` 或当前角色 |
```
与 `:94-100` 的 v1.1 修订（RLS 仅做 tenant 隔离）直接矛盾。R2 已将此标记为其 P2-4，仍未修复。

---

### ❌ P0-4: Audit Spec 未列出 MUST 记录 role_id 的具体事件类型 — 未修复

**当前状态：** `audit-specification-v1.1.md:58-61`：
```
- detail: dict — 详细信息（SHOULD），包含以下角色追踪字段（v1.2 新增）
  - role_id:    string    — 操作时的当前角色
  - user_roles: list[str] — 用户拥有的所有角色
```

两个问题依旧：
1. `detail` 本身仍是 **SHOULD** 级别（设计文档 §3.6 要求 6 类事件 MUST 记录 role_id）
2. **未列出具体事件类型**（SESSION_CREATED / EXECUTION_STARTED / PERMISSION_DENIED 等）

---

### ❌ P0-5: Multi-Tenant §5.4.1 影响实体表遗漏 Checkpoint — 未修复

**当前状态：** `multi-tenant-isolation-specification-v1.md:191` 正文仍说：
```
MUST: Session、Execution、Checkpoint 创建时写入当前 role_id
```
但 `:202-206` 表格只有 3 行（Session / Execution / AuditLog），**Checkpoint 缺失**。设计文档 §4.3 DDL 表同样无 Checkpoint。

---

### ❌ P0-6: Capability Spec 引用 visible_roles 但未在数据模型中定义 — 未修复

**当前状态：** `capability-center-specification.md:262` 仍引用：
```
BusinessCapability.visible_roles 非空时，额外检查 role_id ∈ visible_roles
```
但：
- §2.2 核心契约字段列表中无 `visible_roles`
- §3.3 Policy Layer 中无 `visible_roles`
- 全文无 `visible_roles` 的 Schema 定义

---

### ❌ P1-1: Policy Center §5.3 'department' 命名与实际语义不符 — 未修复

**当前状态：** `policy-center-specification.md:129` 仍为：
```
- department: 只能看到自己拥有角色创建的数据（role_id IN (user_roles)）
```
语义是"自己的所有角色"而非"同一部门"，名称误导。

---

### ❌ P1-2: Capability Spec 缺少 v1.2、v1.3 变更记录 — 未修复

**当前状态：** 附录 D 仅有 v1.0→v1.1 记录。v1.4 变更说明中提到 `v1.1→v1.3 已有变更（三层结构+fallback_capability_id）` 但未补充历史。

---

### ❌ P1-3: client.py switch_role() 无 user_roles 校验 — 未修复

**当前状态：** `client.py:51-58`：
```python
def switch_role(self, role_id: str) -> None:
    if not role_id:
        raise ValueError("role_id must not be empty")
    self._role_id = role_id
```
对比 `context.py:58-62` 有 `role_id ∈ user_roles` 校验。client.py 无 `user_roles` 状态，无法校验。

---

### ❌ P1-4: Chunk 实体缺少 tenant_id — 未修复

**当前状态：** `knowledge-base-specification-v1.md:38-44` Chunk 实体仅含 `chunk_id, doc_id, content, embedding, metadata`。RAG 检索 SQL（§2.2）在 `WHERE tenant_id = ?` 过滤，但 pgvector 搜索直接作用于 Chunk 表——若 Chunk 无 tenant_id，需 JOIN Document，影响向量搜索性能。

---

### ❌ P1-5: Knowledge Base Spec 缺少 accessible_roles 管理 API — 未修复

**当前状态：** 规范定义了 `accessible_roles` 的默认值语义，但未定义修改接口、权限控制、审计要求。

---

### ✅ P1-6: client.py call() 快捷方法不传递 role_id — 已修复

**当前状态：** `client.py:120-152`：
```python
async def call(self, ..., role_id: str | object = _UNSET, ...):
    session = await self.create_session(
        user_id=user_id or "anonymous",
        tenant_id=tenant_id,
        role_id=role_id,  # ← 现在传递
    )
```
`call()` 快捷路径现在有完整的角色上下文。

---

### ❌ P1-7: knowledge_scopes vs knowledge_tags 命名不一致 — 未修复

**当前状态：** 
- `role-based-access-control-v1.md:25` ER 图：`Role.knowledge_scopes`
- `role-based-access-control-v1.md:79` 实体定义：`knowledge_tags`
- 语义相同，名称不同。R2 标记为其 P2-3。

---

### ✅ P2-1: SDK 注释版本引用不统一 — 已修复

**当前状态：** `context.py:47-48` 已更新为 `Policy Center Spec v1.1 §5.1`。

---

### ❌ P2-2: core-py/config.py 变更未落地 — 未修复

**当前状态：** `role-based-access-control-v1.md:249` 仍列出 `core-py | config.py | ConnectorConfig 增加 role_id`，仓库中无对应变更。

---

### ❌ P2-3: Capability Spec role_id 为空时行为未定义 — 未修复

**当前状态：** `GET /capabilities/search?q={query}&role_id={role_id}` 中 `role_id` 为空/未传时的行为仍未说明——向后兼容（返回全量）还是拒绝？

---

## 三、R2 新增发现（单独验证）

R2 仅审查了设计文档自身，其 4 项发现中 **2 项与 R1 重复**（P2-3 = P1-7, P2-4 = P0-3），剩余 2 项为真正新增：

### ❌ R2-P1: build_data_filter 引用未定义的 user_roles — 未修复

`role-based-access-control-v1.md:122-127`：
```python
def build_data_filter(role: Role, user_id: str) -> dict:    # ← 只有 2 个参数
    ...
    elif role.data_scope == "department":
        return {"role_id": ("IN", user_roles)}               # ← user_roles 未定义
```
`user_roles` 既不是参数也不是局部变量。

### ❌ R2-P2: audit_logs DDL 描述自相矛盾 — 未修复

`role-based-access-control-v1.md:259`：
```
| audit_logs | ADD role_id VARCHAR（放入 detail JSONB 字段，与 Audit Spec v1.1 存储格式一致） |
```
`ADD role_id VARCHAR`（独立列）与括号内"放入 detail JSONB 字段"矛盾——实施者不知道该执行 ALTER TABLE 还是改 JSONB。

---

## 四、本轮新增发现

### 🆕 NP0-1: Policy Center §5.1 出现新的 MUST 条款引用 Capability Spec 的 undefined 概念

`policy-center-specification.md:109`：
```
MUST: 评估：User.current_role.permissions → Capability.required_permissions
```
这里使用 `User.current_role.permissions`，但设计文档中 `current_role` 是 `tenant_account_joins` 的一个字段（字符串 ID），不是 User 对象上的嵌套属性。实际评估需要 JOIN Role 表获取 permissions。规范表达有歧义——是 `User.current_role.permissions`（暗示 ORM 嵌套对象）还是 `Role.find(User.current_role_id).permissions`（查询后评估）？

**建议：** 改为 `MUST: 评估时查询当前角色 permissions = Role.find_by_id(User.current_role_id).permissions，与 Capability.required_permissions 做子集判断`。

---

### 🆕 NP1-1: client.py switch_role() 不接受 user_roles 参数——无法客户端校验

`client.py:51-58` 的 `switch_role()` 仅校验非空。但 `context.py:58-62` 的 `switch_role()` 校验 `role_id ∈ user_roles`。两个同名方法行为不一致，且 RuntimeClient 没有一个方法来设置 user_roles 列表供校验使用。

对比设计文档 §3.5：
```python
client.switch_role("finance_manager")  # 设计文档未提需要 user_roles 参数
```
设计文档也未明确 `switch_role()` 是否需要 user_roles。但 context.py 实现了校验，client.py 没实现。

**建议：** 要么给 client.py 加 `set_user_roles()` + 校验，要么在注释中明确说明"校验由服务端执行，client 仅透传"。

---

### 🆕 NP1-2: test_security.py 测试未覆盖角色相关功能

`test_security.py` 虽然传了 `role_id="r1"`，但没有任何测试验证：
- `switch_role()` 行为
- `create_session()` 在 role_id 缺失时的 ValueError
- `role_id` 未设置时的错误路径（`role_id is _UNSET and not self._role_id`）
- `call()` 的 role_id 传递

测试覆盖率有缺口。

---

### 🆕 NP2-1: Capability Spec §5.1 角色筛选符号 ⊇ 的使用不标准

`capability-center-specification.md:261`：
```
MUST: 角色筛选规则
  - 评估：role.permissions ⊇ capability.required_permissions
```
符号 `⊇` 是"包含或等于"（superset-or-equal），语义正确（role.permissions 必须包含所有 required_permissions）。但在 ASCII 规范文档中使用 Unicode 数学符号不利于搜索和工具解析。

**建议：** 补充文字说明：`role.permissions 必须包含 capability.required_permissions 的所有元素（即 role.permissions ⊇ required_permissions）`。

---

## 五、总结

| 级别 | R1 遗留 | R2 新增(去重后) | 本轮新增 | 合计未修复 |
|:----:|:-------:|:-------------:|:-------:|:--------:|
| **P0** | 4 | 0 | **1** | **5** |
| **P1** | 6 | 1 | **2** | **9** |
| **P2** | 2 | 1 | **1** | **4** |
| **合计** | **12** | **2** | **4** | **18** |

### 关键结论

**已修复的 2 个 P0 是安全模型最核心的问题：**
- P0-1（Policy Center MUST/SHOULD 矛盾 → 单角色模型统一）— 安全模型根基修复
- P0-2（create_session 缺失 role_id → 参数链完整）— 数据隔离链路最上游修复

**5 个未修复 P0 按严重程度排序：**
1. **P0-3** — 设计文档内部矛盾（§1.2 vs §3.2），实现者看到错误指示
2. **P0-4** — Audit 缺少事件类型 MUST 列表，关键审计链路（PERMISSION_DENIED）可能遗漏角色信息
3. **P0-6** — `visible_roles` 引用无定义，Capability 角色可见性无法实现
4. **NP0-1（新）** — `User.current_role.permissions` 表达歧义，评估路径不明确
5. **P0-5** — Checkpoint 实体在文本中提及但表中缺失

**最优先修复建议：P0-3 + P0-4**（文档一致性，影响实施者决策），其次是 **P0-6 + NP0-1**（Capability 角色过滤的两个阻塞项）。
