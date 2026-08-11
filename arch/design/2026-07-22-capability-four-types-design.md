# Capability 设计 — 四类型能力模型 + 权限配置

- 日期: 2026-07-22
- 状态: draft
- 关联文档: `arch/design/2026-07-22-permission-design-principles.md`
- **2026-08-07 修订**：`query/command` 与四类型改为正交并存（评审对齐，见 §2）

## 1. 背景与目标

当前 Capability 模型仅区分 `query`/`command` 两种类型，无法表达 EARP 实际接入的异构能力。参考 Dify 的 ToolProviderType 分类（BUILT_IN/MCP/WORKFLOW/API），将 EARP Capability 重新划分为 4 种类型，每种独立配置，统一权限模型。

**目标**：重构 Capability 类型体系 + 每个 Capability 支持 OrgUnit/Role 权限配置（与 KB 一致）。

## 2. 四类型能力模型

| 类型 | 定位 | 来源 | 原理 |
|---|---|---|---|
| `skill` | 内建能力 | 平台预置或管理员创建 | 纯代码，无外部依赖 |
| `mcp` | MCP Server 对接 | 连接 MCP Server → 自动发现 tools | 每条 tool = 一个 Capability |
| `workflow` | 工作流发布 | 已发布的 EARP 工作流 | 一个 workflow = 一个 Capability |
| `restful` | REST API 直连 | OpenAPI 导入或手动配置 | 一个 endpoint = 一个 Capability |

**`query`/`command` 与四类型正交并存（2026-08-07 修订）**：

```
capability_type（操作语义，CQRS 根基不变）:  query | command
    —— 有无副作用 → 决定审批 / 审计级别 / 事务 / 补偿路径（L0 P5 / ADR-002）

source_type（来源形态，本设计新增）:        skill | mcp | workflow | restful
    —— 能力从哪来、如何实现
```

两者是**正交维度，不是替代关系**：一个 source_type 可以承载任意 capability_type。**配置权限时先定操作语义**：

| 来源形态 | 判定规则 | 示例 |
|---|---|---|
| skill | 看实现是否有副作用 | `query_equipment_alarm`=query，`start_equipment`=command |
| mcp | 按 tool 操作性质（读写）判定 | `list_tools` 内查询类 tool=query，写入类=command |
| workflow | 看流程是否有状态变更，与 approval_required 联动 | 报表生成（无副作用）=query，工单审批流=command |
| restful | **默认按 method 映射**：GET→query，POST/PUT/DELETE/PATCH→command，可手动覆盖 | `GET /sales`=query 不审批，`POST /orders`=command 必经审批 |

## 3. 统一权限模型

4 种类型全部支持权限配置，模型同 KB：

```
Capability
  └─ permissions: OrgUnit OR Role（二选一，mutually exclusive）
```

**skill 也需要权限**：skill 内部可调用 MCP/Workflow/RESTful，不加权限会形成绕过通道。统一权限模型消除此风险。

## 4. 各类型详细配置

### 4.1 Skill

| 字段 | 说明 | 必填 |
|---|---|---|
| name | 名称 | ✅ |
| description | 描述（给 LLM 用于意图匹配） | ✅ |
| domain | Business Domain 归属 | ✅ |
| capability_type | query / command（操作语义，CQRS） | ✅ |
| input_schema | 输入参数 JSONSchema | ✅ |
| output_schema | 返回值结构 | ✅ |
| version | 版本号 | 默认 1.0.0 |
| permissions | OrgUnit OR Role | ✅ |

**页面交互**：+ New Skill → 表单 → 保存。权限配置与 KB 相同的两栏穿梭。

### 4.2 MCP

| 字段 | 说明 | 必填 |
|---|---|---|
| name | Server 名称 | ✅ |
| description | 描述 | ✅ |
| domain | Business Domain | ✅ |
| server_url | MCP Server 地址 | ✅ |
| transport | stdio / sse | ✅ |
| auth_type | none / api_key / oauth | 默认 none |
| api_key | auth_type=api_key 时 | — |
| oauth_* | client_id/secret/grant_type | oauth 时 |
| timeout | 调用超时 | 默认 30s |
| sse_read_timeout | SSE 读取超时 | 默认 60s |
| identity_mode | 是否转发用户身份 | 默认 off |
| capability_type | query / command，按 tool 操作性质判定 | ✅ |
| permissions | OrgUnit OR Role | ✅ |
| tools | 连接后自动发现的 tool 列表 | 管理员勾选注册 |

**流程**：填连接信息 → Test Connection → 自动发现 tools → 勾选注册 → 配置权限 → 保存。

### 4.3 Workflow

| 字段 | 说明 | 必填 |
|---|---|---|
| name | 名称 | ✅ |
| description | 描述 | ✅ |
| domain | Business Domain | ✅ |
| workflow_id | 关联的工作流 ID | ✅ |
| exposed_params | 暴露给 LLM 的参数（从输入中选） | ✅ |
| output_schema | 返回值结构 | ✅ |
| capability_type | query / command，与 approval_required 联动 | ✅ |
| approval_required | 是否需要审批 | 默认 false |
| permissions | OrgUnit OR Role | ✅ |

**流程**：选已发布 workflow → 选暴露参数 → 配置权限 → 保存。

### 4.4 RESTful

| 字段 | 说明 | 必填 |
|---|---|---|
| name | 名称 | ✅ |
| description | 描述 | ✅ |
| domain | Business Domain | ✅ |
| endpoint | API URL | ✅ |
| method | GET/POST/PUT/DELETE | ✅ |
| headers | 自定义请求头 | 可选 |
| body_template | 请求体模板 | POST/PUT 时 |
| auth_type | none/api_key_header/api_key_query/bearer | 默认 none |
| api_key | auth 非 none 时 | — |
| capability_type | query / command，默认按 method 映射（GET→query，POST/PUT/DELETE→command），可手动覆盖 | ✅ |
| input_schema | 输入参数 | ✅ |
| output_schema | 返回值结构 | ✅ |
| timeout | 超时 | 默认 30s |
| retry | 重试策略 | 默认 0 次 |
| permissions | OrgUnit OR Role | ✅ |

**流程**：
- 方式 1：填 OpenAPI URL → 自动解析
- 方式 2：手动填写全部字段 → 配置权限 → 保存

## 5. Capabilities 页面升级

当前是 5 列表格（ID/Domain/Name/Type/Version）。升级后：

```
┌─ Capabilities ────────────────────────────────────────────┐
│                                                            │
│  Type: [all ▾]  Domain: [all ▾]  [Search...]              │
│  [+ New Skill]  [+ MCP]  [+ Workflow]  [+ RESTful]        │
│                                                            │
│  ┌─ 能力列表 ───────────────────────────────────────────┐ │
│  │ ID │ Name │ Type │ Domain │ Version │ Status │ ⚙️     │ │
│  │ cap-01 │ echo │ skill │ demo │ 1.0.0 │ active │ Config│ │
│  │ cap-02 │ query │ mcp │ query│ —     │ active │ Config│ │
│  └────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```

**新增**：
- 类型筛选下拉（all/skill/mcp/workflow/restful）
- 4 个创建按钮（每种类型一个，跳各自表单）
- ⚙️ Config 列 → 打开该 Capability 的编辑+权限配置

## 6. 数据库影响

| 变更 | 说明 |
|---|---|
| `business_capabilities.type` | **保留** `('query','command')`——操作语义，CQRS 根基不变（2026-08-07 修订） |
| `business_capabilities` | 新增 `source_type`（skill/mcp/workflow/restful，来源形态）、`permission_type`（org_unit/role）、`accessible_org_units`、`accessible_roles`、`config` JSONB |
| 新增表 | `mcp_connections`（server_url/auth/transport）、`capability_permissions` |

## 7. 下一步

- [ ] 用户评审
- [ ] 确认 Capabilities 页面是否需要独立设计文档
