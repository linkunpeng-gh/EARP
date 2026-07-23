# 权限设计原则 — 组织架构 + 角色双维度访问控制

- 日期: 2026-07-22
- 状态: draft
- 关联文档: `arch/design/role-based-access-control-v1.md` v1.1

## 1. 背景与目标

现有 RBAC v1.1 基于 Role 的 data_scope 四层模型（self/department/org/all），其中 `department` 语义为「同 role 数据」。但企业实际组织架构是「部门/团队」而非「角色分组」。需要引入 OrgUnit 实体，修正 data_scope 语义，并为 KB/Doc 提供双维度（组织+角色）权限配置。

**目标**：
1. 引入 OrgUnit 实体（树形，支持外部同步 + 手动创建）
2. 修正 data_scope 的 `department` 语义为组织单元
3. KB 层支持双维度权限（按组织 OR 按角色，二选一）
4. Doc 层同样双维度，未配则继承 KB

## 2. 方案对比

### 方案 A：纯 Role 模型（当前 v1.1）
KB/Doc 只能按 Role 配权限。data_scope 的 `department` = 同 role。

**问题**：企业组织是按部门管理知识的，不是按角色。HR 经理创建的 KB 应该面向「人事部」而非「HR 经理角色」。

### 方案 B：OrgUnit + Role 双维度 ✅

| | OrgUnit 维度 | Role 维度 |
|---|---|---|
| KB 授权 | 选组织单元（部门→人） | 选角色 |
| Doc 授权 | 同上，未配继承 KB | 同上 |
| data_scope | `department` = 同 OrgUnit | self/org/all 不变 |

**选择理由**：覆盖企业实际组织的两种管理方式——按架构（部门树）和按职能（角色）。

## 3. 推荐方案详述

### 3.1 实体模型

```
Tenant
  ├── OrgUnit（树形）
  │    ├── 设备部
  │    │    ├── 设备一组
  │    │    │    ├── 张三（User）
  │    │    │    └── 李四（User）
  │    │    └── 设备二组
  │    └── 人事部
  │         └── 王五（User）
  │
  └── Role（跨 OrgUnit）
       ├── 设备工程师（permissions, data_scope）
       └── HR 经理
```

**OrgUnit 属性**：

| 字段 | 说明 |
|---|---|
| id | 唯一标识 |
| tenant_id | 租户 |
| name | 名称（如 "设备一组"） |
| parent_id | 父节点（null = 根） |
| source | `manual` / `ldap` / `ad` / `hr_system` |
| external_id | 外部系统 ID（source ≠ manual 时） |
| external_path | LDAP DN 路径（如 `ou=设备一组,ou=设备部,dc=example,dc=com`） |
| users | 归属该 OrgUnit 的用户列表 |

**LDAP 对接**（Phase 2）：OrgUnit 可从 LDAP/AD 目录树同步：
- 支持 LDAPS 连接（`ldaps://dc.example.com:636`）
- 映射 LDAP OU 到 EARP OrgUnit 树
- 定期增量同步用户归属关系
- 手动创建的 OrgUnit 与 LDAP 同步的 OrgUnit 共存

### 3.2 权限链

```
DD            → 无权限，纯数据分组
  └── KB      → accessible_org_units OR accessible_roles（二选一）
       └── Doc → accessible_org_units OR accessible_roles（二选一）
                未配置 → 继承 KB 权限
```

**互斥规则**：KB/Doc 的权限必须二选一。同时设置 org_units 和 roles = 歧义。

**继承规则**：
- KB 有权限 → Doc 可选继承或不继承
- KB 无权限（默认全开放） → Doc 独立配置

### 3.3 data_scope 语义修正

| 等级 | 修正前（v1.1） | 修正后 |
|---|---|---|
| self | 只看自己创建的 | 不变 |
| department | 同 role 的数据 | **同 OrgUnit 的数据** |
| org | 同租户所有数据 | 不变 |
| all | 无限制 | 不变 |

部门语义含义：用户所属 OrgUnit（含子 OrgUnit）内所有用户产生的数据。

### 3.4 KB/Doc 权限配置界面

**两栏穿梭模式**：左侧候选区，右侧已选区。

```
┌─ KB 权限配置 ─────────────────────────────────────┐
│                                                     │
│  权限类型: ○ 按组织架构    ○ 按角色                 │
│                                                     │
│  ┌─ 可选 ──────────────┐  ┌─ 已授权 ─────────────┐ │
│  │  ☐ 设备部            │  │  ☑ 设备一组          │  │
│  │    ☐ 设备一组         │  │    ☑ 张三            │  │
│  │      ☐ 张三           │  │                      │  │
│  │      ☐ 李四           │  │                      │  │
│  │    ☐ 设备二组        │  │                      │  │
│  │  ☐ 人事部            │  │                      │  │
│  │    ☐ 王五            │  │                      │  │
│  └──────────────────────┘  └──────────────────────┘ │
│                                                     │
│  提示：全选一个部门 = 该部门（含子部门）所有人      │
│                                                     │
│                              [保存]  [取消]          │
└─────────────────────────────────────────────────────┘
```

**切换「按角色」时**：左侧显示角色列表，右侧已授权角色。

### 3.5 Capability 权限（后续讨论）

Capability 的可见性可直接沿用此模式：
- 按组织：Capability 授权给特定 OrgUnit（某部门的设备工程师才能调用某能力）
- 按角色：Capability 授权给特定 Role（当前 v1.1 的 `required_permissions` 机制）

### 3.6 变更影响

### 新增实体

| 实体 | 说明 |
|---|---|
| OrgUnit | 树形组织单元，支持外部同步 |

### 修改实体

| 实体 | 变更 |
|---|---|
| Role.data_scope | `department` 语义改为「同 OrgUnit」 |
| KB | 新增 `accessible_org_units`, `accessible_roles`（二选一） |
| Document | 新增 `accessible_org_units`, `accessible_roles`（二选一，可为空=继承KB） |
| User | 新增 `org_unit_id` |

### 受影响文档

| 文档 | 变更 |
|---|---|
| `role-based-access-control-v1.md` | data_scope 修正 + 新增 OrgUnit 章节 |
| `knowledge-base-specification-v1.md` | KB/Doc 新增 org_unit 权限字段 |
| `multi-tenant-isolation-specification-v1.md` | RLS 策略 + data_scope 适配 |

## 4. 已知限制与风险

| 限制/风险 | 缓解 |
|---|---|
| OrgUnit 外部同步（LDAP/AD）复杂度高 | Phase 1 仅支持手动创建，Phase 2 对接外部系统 |
| 二选一权限模型导致误配 | UI 层面 radio 强制二选一，不能同时设置 |
| Doc 继承 KB 权限 → KB 权限变更后需同步 Doc | KB 权限变更时提示「是否同步应用到下属文档」 |
| 树形 OrgUnit 深度过大导致递归查询性能 | 限制深度 5 层 + 物化路径缓存 |

## 5. 下一步

- [ ] 用户评审
- [ ] 确认 OrgUnit 是否需要独立管理页面（治理下拉中新增「组织架构」）
- [ ] 后续 Capability 权限讨论
