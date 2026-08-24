# 应用中心（智能体）设计文档

- 日期：2026-08-24
- 状态：已与需求方逐条确认，待实现
- 范围：admin 端先行；earp-user 端二期复用同一套后端 API

## 1. 背景与目标

工作台已支持 chat / chatflow 智能体的创建、编排、测试与发布（`POST /chat_apps/{id}/publish`）。当前应用中心 `apps.html` 只读展示已发布应用，卡片不可点击、无收藏、无分类检索。

本期目标：

1. 工作台（admin）搭建的 chat / chatflow 应用发布后，在应用中心「智能体」页可见。
2. 点击卡片，在权限满足的情况下直接运行（内嵌对话抽屉 + 独立运行页）。
3. 用户可把喜欢的智能体收藏到「我的应用」（跨设备，按 user_id 存库）。
4. chatflow 改为节点级 SSE 流式，运行界面实时展示节点执行过程（清掉 F5a 遗留「LLM 节点流式透传」）。
5. 治理中心统一定义应用使用权限（角色×应用矩阵）与业务分类词表。

## 2. 需求要点（已确认）

| # | 需求 | 结论 |
|---|---|---|
| R1 | 目标前端 | admin 先行，earp-user 二期复用后端 API（选 C） |
| R2 | 智能体列表范围 | 所有已发布应用（chat + chatflow，未来 workflow 等类型并入）；「概览」改名「智能体」；需分类 + 查找 |
| R3 | 分类 | 按类型（chat/chatflow）筛选 + 业务分类（发布时创建人填写，来源为租户级预设词表） |
| R4 | 查找 | 名字 / 描述 / 创建人 / 标签 模糊搜索 |
| R5 | 运行交互 | 列表内嵌快速对话抽屉 + 「进入完整对话页」入口，两者都要 |
| R6 | chatflow 流式 | 本期做 flow 节点级 SSE 流式完整版（选 A），清掉 F5a 遗留 |
| R7 | 权限模型 | 应用级可见/可运行权限（治理中心统一定义，角色粒度）+ 执行期 PolicyLayer 双重把关（选 C） |
| R8 | 权限默认策略 | 默认开放：发布即默认所有人可见可运行；治理中心只对需限制的应用做白名单例外 |
| R9 | 治理中心形态 | 角色×应用矩阵（行=角色、列=应用，勾选即授权） |
| R10 | 我的应用 | 当前登录用户个人收藏集，按 user_id 存库跨设备同步；收藏入口：卡片 + 运行页 |
| R11 | 下架/删除行为 | 回草稿 → 收藏隐藏但保留记录，重新发布自动恢复；删除 → 收藏 CASCADE 清理并提示 |
| R12 | 我的应用页 | 复用同一套分类/搜索组件 |
| R13 | 分类形态 | 单个业务分类（单选，预设词表）+ 多个自由标签（逗号分隔）；词表租户级，治理中心维护 |
| R14 | 分类/标签填写时机 | 编辑页可填 + 发布弹窗可改，发布时校验分类必填 |
| R15 | 列表可见范围 | 只展示已发布应用（草稿仅工作台可见） |
| R16 | 会话管理 | 按智能体维度：会话历史侧边栏，可新建/切换/删除 |
| R17 | 执行过程展示 | chatflow 节点执行过程（节点/状态/耗时/分支）在运行界面展示（折叠面板） |
| R18 | 管理员兜底 | is_admin 角色不受应用级权限限制（沿用现有「跳过数据域过滤」模式） |
| R19 | 卡片信息/排序 | 名称/描述/类型徽标/业务分类/标签/创建人/收藏星标；默认最新发布，可切最热（按收藏数） |
| R20 | 词表种子 | 财务、人事、客服、IT 运维、数据分析、其他 |
| R21 | 审计 | 发布/编辑/删除/权限矩阵变更/分类变更写 audit_logs（沿用 _audit + 事件总线）；收藏不审计 |

## 3. 数据模型（新 migration `0032_agent_center`）

### 3.1 `chat_apps` ALTER

| 列 | 类型 | 说明 |
|---|---|---|
| `category` | VARCHAR(64) NULL | 业务分类（取值来自租户词表） |
| `tags` | TEXT[] NOT NULL DEFAULT '{}' | 自由标签 |
| `created_by` | VARCHAR(64) NULL | 创建人 user_id（历史数据 NULL，列表显示「—」） |

- `create_chat_app` 写入 `created_by = user_id`；历史数据迁移置空不追溯。

### 3.2 `app_categories`（租户级预设词表）

```
category_id VARCHAR(64) PK
tenant_id   VARCHAR(64) NOT NULL
name        VARCHAR(64) NOT NULL
sort_order  INTEGER NOT NULL DEFAULT 0
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE (tenant_id, name)
```

- 种子：财务、人事、客服、IT 运维、数据分析、其他。
- RLS 租户隔离，与既有表一致。

### 3.3 `app_role_access`（角色×应用权限矩阵，白名单语义）

```
chat_app_id VARCHAR(64) NOT NULL REFERENCES chat_apps (chat_app_id)
role_id     VARCHAR(64) NOT NULL REFERENCES roles (role_id)
tenant_id   VARCHAR(64) NOT NULL
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
PRIMARY KEY (chat_app_id, role_id, tenant_id)
```

- **语义**：某应用在表内无任何行 → 默认开放（所有人可看可运行）；存在行 → 白名单模式（仅行内角色可访问）。
- **is_admin 角色始终可见/可运行**（沿用现有跳过数据域过滤的兜底模式）。
- 治理中心矩阵页：勾选 ≥1 角色 = 白名单；0 勾选 = 开放。

### 3.4 `user_app_favorites`（我的应用）

```
user_id     VARCHAR(64) NOT NULL
chat_app_id VARCHAR(64) NOT NULL REFERENCES chat_apps (chat_app_id) ON DELETE CASCADE
tenant_id   VARCHAR(64) NOT NULL
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
PRIMARY KEY (user_id, chat_app_id, tenant_id)
```

- 回草稿（下架路径 = 编辑已发布应用回 draft）→ 收藏行保留但列表隐藏；重新发布自动恢复。
- 删除应用 → CASCADE 清理收藏。

## 4. 后端 API

| 端点 | 说明 |
|---|---|
| `GET /chat_apps` | 扩展参数：`q`（名字/描述/标签/创建人 模糊）、`type`（chat\|flow）、`category`、`tag`、`sort=latest\|hot`（hot 按收藏数）、`fav=1`（只看我的收藏）；返回增加 `category / tags / created_by / favorite / favorite_count`；可见性过滤（非 admin + 白名单应用 → 仅矩阵内角色可见） |
| `GET /chat_apps/{id}` | 返回新增字段 |
| `POST /chat_apps` | 支持 `category / tags` 字段 |
| `PATCH /chat_apps/{id}` | 支持 `category / tags` 更新 |
| `POST /chat_apps/{id}/publish` | 发布表单可带 `category / tags`；**校验 category 必填** |
| `POST /chat_apps/{id}/favorite` | 收藏（幂等） |
| `DELETE /chat_apps/{id}/favorite` | 取消收藏（幂等） |
| `GET /admin/app_categories` | 分类词表列表（is_admin 门禁） |
| `POST /admin/app_categories` | 新增分类（同名校验） |
| `PATCH /admin/app_categories/{id}` | 改名称/排序 |
| `DELETE /admin/app_categories/{id}` | 删除；若被 chat_apps 引用 → 应用 category 置空 |
| `GET /admin/app_access?chat_app_id=` | 某应用授权角色 + 当前模式（open / restricted） |
| `PUT /admin/app_access/{chat_app_id}` | body `{roles: []}`；空数组 = 开放（清行），非空 = 白名单 |
| `POST /chat_apps/{id}/chat/stream` | flow 新增 SSE 流式；chat 模式与现有 SSE 一致；原非流式 `POST /chat_apps/{id}/chat` 保持兼容 |

### 4.1 flow SSE 事件序列

| 事件 | 字段 | 说明 |
|---|---|---|
| `node_start` | `node_id, node_type, label` | 节点开始执行 |
| `token` | `node_id, text` | LLM 节点逐字输出 |
| `node_end` | `node_id, status, output_summary, latency_ms` | 节点完成（含 error） |
| `branch` | `branch_id, side` | 条件分支走向 |
| `human_approval` | `execution_id, conversation_id, question` | 挂起等待人工确认 |
| `done` | `conversation_id, message_id, status` | 整轮完成 |
| `error` | `message` | 执行失败 |

- 恢复：用户答复后调用 stream 端点续跑（复用现有 `flow_runs` 挂起恢复机制）。

### 4.2 实现要点

- `MultiStepExecutor` / `StepRunner` 增加事件回调：`on_node_start / on_node_end / on_token / on_branch`（默认 no-op，flow stream 时注入）。
- LLM 节点适配器把 `LLMConnector.stream()` 的 token 转发给 `on_token`。
- `flow_chat` 增加 stream 模式：回调桥接到 SSE（`text/event-stream`）；挂起恢复复用 `flow_runs`。
- 原非流式 flow 路径保持兼容（调试 trace 输出不变）。

## 5. 前端（admin）

### 5.1 智能体页（`apps.html` 重构）

- 工具栏：搜索框（名字/描述/标签/创建人）｜ 分类下拉（词表）｜ 类型筛选（全部/chat/chatflow）｜ 排序（最新/最热）｜ Tab：全部智能体 / 我的应用。
- 卡片网格：名称 / 描述 / 类型徽标 / 分类 / 标签 / 创建人 / 收藏数 / ⭐收藏按钮。
- 运行抽屉：点击卡片 → 右侧滑出内嵌对话面板（SSE 流式；chatflow 显示节点执行过程折叠面板）；抽屉内「全屏」→ 跳独立运行页。
- 空态 / 加载中 / 错误提示；「我的应用」Tab 复用同一套筛选搜索组件（仅数据源 `fav=1`）。

### 5.2 独立运行页（`run.html`）

- 左栏：会话历史（按当前应用 + user_id 归属），新建/切换/删除会话。
- 主区：对话流（SSE 渲染；chat 逐字；chatflow 实时节点进度：节点名、状态 ✓/⏳/✗、耗时、分支、token 流式）。
- human_approval：挂起显示确认条 + 问题内容，确认/拒绝后续跑。
- 顶部：返回列表、应用名/分类、⭐收藏。

### 5.3 治理中心两页（新增）

- `app-categories.html`：词表 CRUD（名称/排序/操作）；删除被引用分类提示「该分类下存在 N 个应用，删除后置空」。
- `app-access.html`：矩阵页——行=角色（非 admin）、列=已发布应用，勾选即授权；0 勾选 = 开放（默认）；带应用搜索；保存写 `app_role_access`。

### 5.4 工作台改造（chat / chatflow 编辑页）

- 编辑面板新增「业务分类（下拉，词表数据）+ 标签（输入，逗号分隔）」字段，随保存带上。
- 「发布」确认弹窗 → 发布表单：名称/描述确认 + 分类下拉（必填）+ 标签（可改）；后端校验分类必填。

### 5.5 导航调整（`nav.js`）

- apps 抽屉：「概览」→「智能体」（进入重构后的 `apps.html`）；「我的应用」由占位改为智能体页内 Tab（不单独建页）。
- 治理中心：新增「应用分类」「应用权限」入口（与 Roles 同区）。

### 5.6 earp-user 二期（不在本期）

- 后端 API 天然支持（user_id 维度 + 可见性过滤）；earp-user 端新增「应用中心」页直接复用。本期只保证 API 面就绪。

## 6. 测试计划

### 6.1 后端 pytest

- chat_app_service：新字段读写、搜索（名称/描述/标签/创建人）、排序 hot、发布分类必填校验。
- 收藏：收藏/取消幂等、`fav=1` 过滤（已发布 + 可见）、删除 CASCADE、回草稿隐藏-重发布恢复。
- 权限矩阵：默认开放 / 白名单 / is_admin 兜底 / 非 admin 不可见过滤。
- 分类词表：CRUD、租户隔离、删除被引用分类置空。
- flow SSE：事件序列（node_start/token/node_end/branch/human_approval/done）、挂起恢复续跑。

### 6.2 前端 smoke（沿用 `test-*.cjs` 模式）

- `test-apps-smoke.cjs`：智能体页加载/筛选/搜索/收藏/我的应用切换/运行抽屉。
- `test-app-access-smoke.cjs`、`test-app-categories-smoke.cjs`：治理中心两页 CRUD。
- 发布表单校验 smoke。

### 6.3 e2e 手动验收流

建 chatflow → 填分类/标签 → 发布 → 智能体页可见 → 运行（SSE 节点执行实时展示）→ 收藏 → 我的应用 → 治理中心配白名单 → 换无权限角色登录不可见。

## 7. 不在本期范围（YAGNI）

- earp-user 端界面（二期）。
- workflow / Agent 类型发布（本期仅预留列表兼容，无新类型引入）。
- 应用级「黑名单」权限（本期仅白名单 + 默认开放）。
- 收藏分享 / 应用评分 / 评论。
