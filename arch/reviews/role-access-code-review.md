现在我已读完所有 7 份文件。以下是完整审查结果。

---

# EARP 角色级访问控制 — 代码审查报告

**基线文档：** `arch/design/role-based-access-control-v1.md` (v1.1)  
**审查范围：** 6 项变更（1 份设计文档 + 4 份规范更新 + 1 份新建 + 2 份 SDK 代码）  
**审查维度：** 正确性、一致性、设计文档对齐

---

## P0（阻塞级 — 安全/正确性问题，必须修复）

### P0-1: Policy Center §5.1 权限模型自相矛盾（与设计文档冲突）

**文件：** `arch/L2/05-governance/policy-center-specification.md:107-114`  
**摘要：** §5.1 中 MUST 条款与 SHOULD 条款矛盾——MUST 要求以 `current_role.permissions` 评估，SHOULD 却说多角色权限取并集。

```markdown
MUST: 评估：User.current_role.permissions → Capability.required_permissions  ← 单角色模型
...
SHOULD: 多角色权限为各角色权限的**并集**——用户拥有其所有角色权限之和           ← 并集模型
```

**冲突点：**
- 设计文档 §3.3 过滤条件为 `capability.required_permissions ⊆ role.permissions`（单角色）
- 设计文档 §6 示例：market_analyst 的 permissions = `["marketing:read", "report:read"]` 无法调用 `finance:read`——按单角色评估
- 如果权限取并集，则用户拥有 market_analyst + reporter 的所有权限之和，不需要"选择当前角色"即可获得全部权限，这与规则 3（操作前选择当前角色）矛盾

**影响：** 若实现取并集逻辑，角色边界形同虚设——低权限角色用户只要同时拥有一个高权限角色即可绕过限制。若实现单角色逻辑，则 SHOULD 条款误导实现者。

**建议：** 删除或降级 SHOULD 并集条款，统一为"以 current_role 为准"。如需临时提权，应有显式的角色切换操作 + 审计记录。

---

### P0-2: client.py create_session() 缺失 role_id 参数且 self._role_id 从未被发送

**文件：** `libs/earp-sdk-runtime-py/src/earp_sdk_runtime/client.py:57-104`  
**摘要：** 设计文档 §3.5 明确要求 `create_session` 接受 `role_id` 参数并传给服务端。

设计文档要求的签名：
```python
session = await client.create_session(
    user_id="u1",
    tenant_id="t1",
    role_id="market_analyst"     # 新增：当前操作角色
)
```

实际代码签名：
```python
async def create_session(
    self, *,
    user_id: str,
    tenant_id: str | object = _UNSET,
    ttl_seconds: int = 3600,
    metadata: dict[str, Any] | None = None,
) -> Session:
```

**问题：**
- 没有 `role_id` 参数
- 请求体 JSON 不含 `role_id` 字段
- `self._role_id` 虽然被 `switch_role()` 设置，但在 `create_session()` 中完全没有被读取或发送
- Session 创建时服务端无法获知当前角色，第一层防线（"创建时写入 role_id"）无法实现

**影响：** 即使 SDK 用户调用了 `client.switch_role("finance_manager")`，创建的 Session 的 `role_id` 仍为空——整个角色级数据隔离链路在最上游断开。

---

### P0-3: 设计文档 §1.2 规则 4 与 §3.2 三层防线描述矛盾

**文件：** `arch/design/role-based-access-control-v1.md:35` vs `:94-106`  
**摘要：** 设计文档 v1.1 修订了 §3.2（RLS 仅做 tenant 隔离），但 §1.2 规则 4 未同步更新。

| 位置 | 内容 |
|------|------|
| §1.2 规则 4 | "数据隔离按角色。**RLS 过滤** `role_id IN (user_roles)` 或当前角色" |
| §3.2 三层防线 | "第三层：数据库 RLS 策略 — **仅做 tenant 隔离**（兜底防线）" |

**影响：** 实现者若只看 §1.2 摘要表，会在 RLS 中写入 role 过滤逻辑——而设计决策明确拒绝了这个方案（"RLS 内无法高效读取 Role 表做四层判断"）。两份互相矛盾的设计指示会导致实现错误。

---

### P0-4: Audit Spec v1.2 未列出 MUST 记录 role_id 的具体事件类型

**文件：** `arch/L2/05-governance/audit-specification-v1.1.md:58-61`  
**摘要：** 设计文档 §3.6 明确列出了 6 类事件必须记录 role_id：

```markdown
MUST: 以下事件记录 role_id
  - SESSION_CREATED
  - EXECUTION_STARTED / COMPLETED / FAILED
  - CAPABILITY_CALL
  - PERMISSION_DENIED
  - KNOWLEDGE_RETRIEVAL
```

Audit Spec §2.1 仅在 `detail` 字段中声明包含 `role_id` + `user_roles`（且 detail 本身是 SHOULD 级别），**未具体列出哪些事件类型必须包含**。

另外，`detail` 字段标记为 `SHOULD`，但设计文档要求 role_id 为 `MUST`——存在级别冲突。

**影响：** 实现者不知道哪些事件必须写入 role_id，可能导致关键审计链路（如 PERMISSION_DENIED）遗漏角色信息，无法追溯"以什么角色被拒绝"。

---

### P0-5: Multi-Tenant §5.4.1 影响实体表遗漏 Checkpoint

**文件：** `arch/L2/07-tenant/multi-tenant-isolation-specification-v1.md:202-206`  
**摘要：** §5.4 正文明确说 "Session、Execution、**Checkpoint** 创建时写入当前 role_id"，但 §5.4.1 表中仅列出 Session、Execution、AuditLog，无 Checkpoint。

设计文档 §4.3 DDL 表中同样未列出 Checkpoint。

**影响：** Checkpoint 是否包含 role_id 没有明确指示，实现时可能遗漏。

---

### P0-6: Capability Spec 引用 visible_roles 但未在数据模型中定义

**文件：** `arch/L2/03-capability/capability-center-specification.md`  
**摘要：** §5.1 角色筛选规则引用了 `BusinessCapability.visible_roles`：

```markdown
MUST: 角色筛选规则
  - BusinessCapability.visible_roles 非空时，额外检查 role_id ∈ visible_roles
```

但：
- 第二章（核心契约 §2.2）的 MUST 字段列表中无 `visible_roles`
- 第三章（三层结构）的 Policy Layer §3.3 中无 `visible_roles`
- 全文找不到 `visible_roles` 的数据模型定义位置

**影响：** 实现者不知道 visible_roles 应该放在哪一层——是 BusinessCapability 的顶层属性还是 Policy Layer 的一部分。缺少 Schema 定义会导致数据模型不一致。

---

## P1（重要级 — 逻辑/设计问题，建议修复）

### P1-1: Policy Center §5.3 data_scope 中 'department' 命名与实际语义不符

**文件：** `arch/L2/05-governance/policy-center-specification.md:129-130`  
**语义实际：** `department` = `role_id IN (user_roles)`——用户能看自己所有角色创建的数据。  
**命名暗示：** 同一"部门"内不同角色的数据互见。

示例冲突：用户有 `[market_analyst, reporter]` 两个角色，`data_scope=department` 时可以看到 reporter 角色创建的数据。如果 market_analyst 和 reporter 在组织上不属于同一部门，这个语义就错了。

**建议：** 将 `department` 重命名为 `own_roles` 或 `assigned_roles`，或在此层增加角色分组（RoleGroup）概念。若短期不改名，至少加注释澄清 `department` 的实际过滤逻辑。

---

### P1-2: Capability Spec 缺少 v1.2、v1.3 变更记录

**文件：** `arch/L2/03-capability/capability-center-specification.md`  
**摘要：** 版本从 v1.0→v1.1（附录 D 有记录）直接跳到 v1.4。v1.2（引入三层结构？）和 v1.3（引入 fallback_capability_id？）的变更记录缺失。v1.4 变更说明中承认了这个跳跃但未补充历史。

**影响：** 规范版本不可追溯，新的团队成员无法了解中间版本引入了什么变更。

---

### P1-3: client.py switch_role() 无校验，与 context.py 不一致

**文件：** `client.py:51-53` vs `context.py:58-62`  
- `context.py` 的 `switch_role()` 校验 `role_id ∈ user_roles`，不在列表中抛出 `ValueError`
- `client.py` 的 `switch_role()` 直接赋值 `self._role_id = role_id`，无任何校验

**影响：** 用户可以通过 client.py 切换到任意不存在的角色，错误将在服务端才暴露（或在 create_session 时静默接受无效 role_id），排查困难。校验应前置。

---

### P1-4: Knowledge Base Spec Chunk 实体缺少 tenant_id

**文件：** `arch/L2/11-knowledge/knowledge-base-specification-v1.md:38-44`  
**摘要：** RAG 检索 SQL (§3) 的 WHERE 子句同时过滤 `tenant_id` 和 `accessible_roles`：

```sql
WHERE tenant_id = ? AND (accessible_roles @> ARRAY[current_role] OR accessible_roles = '{}')
```

但 Chunk 实体定义中只有 `chunk_id, doc_id, content, embedding, metadata`，无 `tenant_id`。此 SQL 要生效，要么 Chunk 冗余存储 tenant_id，要么 pgvector 索引需要 JOIN Document 表（增加复杂度且可能影响向量搜索性能）。

**建议：** Chunk 增加 `tenant_id` 冗余字段（反范式化），或明确说明通过 JOIN Document 实现过滤。

---

### P1-5: Knowledge Base Spec 缺少 accessible_roles 管理 API

**文件：** `arch/L2/11-knowledge/knowledge-base-specification-v1.md`  
**摘要：** 规范定义了 `accessible_roles` 的创建默认值和检索过滤逻辑，但未定义：
- 谁可以修改 accessible_roles（§2.2 仅说"管理员"但什么是管理员？）
- 通过什么接口修改（PATCH /documents/{id} 的哪个字段？）
- 修改是否需要审计记录

**影响：** 文档上传后 accessible_roles 被锁死（无人能改），或任意用户可修改（失去隔离意义），取决于实现者的自行判断。

---

### P1-6: client.py call() 快捷方法不传递 role_id

**文件：** `libs/earp-sdk-runtime-py/src/earp_sdk_runtime/client.py:108-146`  
**摘要：** `call()` 内部调用 `create_session()` 但不传递 `role_id`（create_session 本身也不支持）。通过 `call()` 创建的临时 Session 永远没有角色上下文。

**影响：** 使用 `call()` 快捷方式的所有调用都绕过了角色级访问控制。如果这是主要 API（文档中的示例用法），则大量流量不受角色约束。

---

### P1-7: 设计文档 §1.1 实体关系图中 Role.knowledge_scopes 与 §3.4 accessible_roles 机制不同

**文件：** `arch/design/role-based-access-control-v1.md:25` vs `:157-180`  
**摘要：** §1.1 实体关系图中角色具有 `knowledge_scopes (文档标签过滤)`，但 §3.4 实际设计使用的是 `Document.accessible_roles`（文档标注可访问角色列表），而非 Role → 标签 → 文档的间接映射。

这两种机制本质不同：
- **knowledge_scopes（标签过滤）：** Role 定义可访问的标签，文档被打上标签，间接匹配
- **accessible_roles（角色列表）：** 文档直接列出可访问的角色 ID，直接匹配

设计文档的 Knowledge Base Spec 和 RAG 示例均使用 `accessible_roles` 模型，§1.1 的 ER 图描述与实际设计不一致。

---

## P2（建议级 — 文档/注释优化）

### P2-1: SDK 注释中的版本引用不统一

| 文件 | 注释 | 问题 |
|------|------|------|
| `context.py:47-48` | `# 当前角色 — Policy Center §5.1 (v1.2 新增)` | 设计文档版本为 v1.1，Policy Center 为 v1.1 |
| `context.py:48` | `# 用户所有角色 (v1.2 新增)` | 同上 |

版本号应统一为设计文档版本或引用规范版本号 `Policy Center Spec v1.1`。

---

### P2-2: 设计文档 §4.2 变更清单中 core-py/config.py 变更未落地

**文件：** `arch/design/role-based-access-control-v1.md:249`  
**摘要：** 变更清单列出 `core-py/config.py: ConnectorConfig 增加 role_id`，但仓库中无对应文件变更。如果这项变更不在本次审查范围内，应在清单中标注"待实施"。

---

### P2-3: Capability Spec §5.1 role_id 参数为空时的行为未定义

**文件：** `arch/L2/03-capability/capability-center-specification.md:250`  
**摘要：** `GET /capabilities/search?q={query}&role_id={role_id}` 中 `role_id` 为空或未传时的行为未说明——是返回全量（向后兼容）还是拒绝请求？向后兼容模式可能被攻击者利用（不传 role_id 绕过过滤）。

---

## 总结

| 级别 | 数量 | 关键问题 |
|:----:|:----:|:-----|
| **P0** | 6 | 权限模型矛盾（Policy）、create_session 缺失 role_id（SDK）、设计文档内部矛盾、Audit 缺少角色事件列表、可见角色未定义 |
| **P1** | 7 | 命名误导、版本变更缺失、校验不一致、Chunk 缺字段、API 缺口 |
| **P2** | 3 | 注释版本引用、变更未落地、向后兼容行为未定义 |

**最关键的两个问题：**
1. **P0-2 (client.py)：** `create_session()` 不传 `role_id`，整个角色数据隔离链路的最上游断开——Session 创建时没有 role_id，后续所有过滤都无从谈起。这是必须立即修复的功能缺口。
2. **P0-1 (Policy Center)：** 权限评估模型的 MUST/SHOULD 矛盾直接影响安全模型的实现——如果团队按 SHOULD（并集）实现，角色边界就被破坏了。
