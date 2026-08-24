# 任务清单 — 应用中心（智能体）：列表/运行/收藏 + 权限矩阵 + 分类词表 + flow SSE 流式

**状态：✅ 已完成（2026-08-24）**——14 任务全部落地；后端 pytest 全量绿（基线持平）、3 个 smoke cjs 绿；待人工前端验收（见验收脚本）
**依据**：`docs/superpowers/specs/2026-08-24-agent-center-design.md`（含两轮修订：access_mode fail-closed、QU 节点流式边界）
**依赖**：chat_apps CRUD/publish ✅、PolicyLayer RBAC ✅、MultiStepExecutor + flow_runs ✅、能力中心（0028）✅、Roles 页 ✅
**日期**：2026-08-24
**基线**：全量 pytest 绿（开工时以实际为准）

## 目标

1. 工作台（chat/chatflow）发布的应用在「应用中心 → 智能体」页可见，支持类型/分类筛选 + 多字段搜索 + 最新/最热排序
2. 点击卡片在权限满足时直接运行：内嵌对话抽屉 + 独立运行页（会话历史、SSE 流式、chatflow 节点执行过程实时展示、human_approval 挂起恢复）
3. 「我的应用」：用户收藏集（按 user_id 存库、跨设备、幂等），卡片与运行页均可收藏
4. 治理中心统一定义：角色×应用权限矩阵（access_mode 显式开关 + fail-closed）+ 租户级业务分类词表（种子 + CRUD + rename 同步快照）
5. flow 节点级 SSE 流式（落地 F5a 遗留「LLM 节点流式透传」）：llm.prompt 节点 token 逐字；QU 节点仅节点级事件（边界见设计 §4.2）

## 既定决策（设计已确认，开工前置）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | 权限默认策略 | 默认开放（`access_mode=open`）；治理中心矩阵勾选 ≥1 角色 → `restricted` 白名单；0 勾选回 open |
| D2 | fail-closed | 删除角色 CASCADE 清矩阵行后，应用保持 `restricted` 无授权行 → 非 admin 不可访问（不回退全员可见）；`restricted + roles=[]` 为合法防御态 |
| D3 | 管理员兜底 | `is_admin` 角色始终可见/可运行所有已发布应用（跳过白名单过滤） |
| D4 | 分类形态 | 单选业务分类（存 `app_categories.name` 快照）+ 多自由标签；发布时校验分类必填；词表 rename 同事务同步 chat_apps.category |
| D5 | 我的应用行为 | 回草稿 → 收藏隐藏保留记录，重发布自动恢复；删除 → CASCADE 清理；收藏幂等 ON CONFLICT DO NOTHING |
| D6 | flow 流式范围 | token 事件仅 llm.prompt 节点；/chat 与 /chat/stream 共享挂起恢复逻辑；原非流式 /chat 保持兼容 |
| D7 | 可见范围 | 智能体页仅展示已发布；草稿仅工作台可见（现有行为） |
| D8 | 审计 | 发布/编辑/删除（已有）+ `earp.app_category.created/updated/deleted` + `earp.app_access.updated`；收藏不审计 |

## Task 拆解（执行序 1→2→…→7，8 起可并行于 2-7 收尾后）

### Task 1 — Migration 0029：数据模型（后端前置） ✅
**文件**：`apps/earp-server/migrations/versions/0029_agent_center.py`（新）
- `chat_apps` ALTER：`category VARCHAR(64) NULL`、`tags TEXT[] NOT NULL DEFAULT '{}'`、`created_by VARCHAR(64) NULL`、`access_mode VARCHAR(16) NOT NULL DEFAULT 'open' CHECK IN ('open','restricted')`
- `app_categories`：PK `category_id`（全局唯一 `cat-{uuid hex 10}`，对齐 roles.role_id）、`UNIQUE (tenant_id, name)`、`sort_order`；种子：财务/人事/客服/IT 运维/数据分析/其他
- `app_role_access`：PK `(chat_app_id, role_id, tenant_id)`；`role_id` FK `ON DELETE CASCADE`；`chat_app_id` FK
- `user_app_favorites`：PK `(user_id, chat_app_id, tenant_id)`；`chat_app_id` FK `ON DELETE CASCADE`
- 每表 RLS 三件套（ENABLE/FORCE + tenant_isolation policy）+ 显式 GRANT earp_app（对齐 0014/0019 先例；favorites 仅 SELECT,INSERT,DELETE）
- 验证：`make migrate` 干净通过、`test_migrations.py` 通过

### Task 2 — chat_app_service 扩展（读侧核心） ✅
**文件**：`apps/earp-server/src/earp_server/conversation/chat_app_service.py`、`main.py`
- `_UPDATABLE` 增加 `category / tags`；`_row_to_dict` 增加新字段（tags 数组化）
- `create_chat_app` 写入 `created_by=user_id`；category 校验存在于租户词表（422）
- `publish_chat_app`：body 可带 `category/tags`；**category 必填校验**
- `list_chat_apps` 签名扩展 `(role_id, user_id)` + 参数：`q`（name/description/tags/created_by ILIKE 模糊）、`type`、`category`、`tag`、`sort=latest|hot`（hot LEFT JOIN favorites 按租户 COUNT 聚合）、`fav=1`
- 可见性过滤：`access_mode='restricted'` 且非 admin 且 role 不在 `app_role_access` → 排除；返回增加 `category/tags/created_by/favorite/favorite_count/access_mode`
- `GET /chat_apps/{id}` 返回新增字段
- 验证：pytest 新用例（见 Task 7）

### Task 3 — 收藏 API ✅
**文件**：`chat_app_service.py`、`main.py`
- `POST /chat_apps/{id}/favorite`：INSERT `ON CONFLICT DO NOTHING`，幂等返回 `{favorited: true}`
- `DELETE /chat_apps/{id}/favorite`：无条件 DELETE，幂等
- `fav=1` 走 Task 2 的列表过滤（仅已发布 + 当前可见）
- 验证：pytest 幂等/过滤/CASCADE/回草稿隐藏用例

### Task 4 — 分类词表 admin API ✅
**文件**：`apps/earp-server/src/earp_server/admin/app_center_routes.py`（新）、`conversation/category_service.py`
- `GET/POST/PATCH/DELETE /admin/app_categories`：`is_admin_role` 门禁；POST 同名校验（422）；PATCH rename **同事务** `UPDATE chat_apps SET category=:new WHERE category=:old AND tenant_id=:tid`；DELETE 被引用 → 应用 category 置空（返回受影响数供前端提示）
- 审计：`earp.app_category.created/updated/deleted`
- 验证：pytest CRUD/租户隔离/rename 同步/删除置空用例

### Task 5 — 权限矩阵 admin API ✅
**文件**：`admin/app_center_routes.py`（新）、`policy/app_access_service.py`
- `GET /admin/app_access?chat_app_id=`：返回 `{mode, roles: [role_id...]}`（JOIN roles 取 name）
- `PUT /admin/app_access/{chat_app_id}`：body `{mode, roles}`；open → 清行 + access_mode='open'；restricted → 写白名单（先清后插，同事务）+ access_mode='restricted'；roles 校验存在且非 admin 角色；**restricted + roles=[] 合法（fail-closed 防御态）**
- 门禁 `is_admin_role`；审计 `earp.app_access.updated`
- 验证：pytest 默认开放/白名单/is_admin 兜底/非 admin 过滤/唯一角色删除后 fail-closed 用例

### Task 6 — flow SSE 节点级流式 ✅
**文件**：`orchestrator/multi_step.py`、`orchestrator/step_runner.py`、`connector.py`、`conversation/chat_service.py`、`main.py`
- `MultiStepExecutor`/`StepRunner` 增加可选事件回调：`on_node_start/on_node_end/on_token/on_branch`（默认 no-op）
- **LLM 节点适配器 `_execute_llm_prompt` 改造**：stream 模式切 `llm.stream()` 逐 token 转发 `on_token`，汇总输出保持 `{"text": ...}` 语义（非流式路径不变）
- `flow_chat` 增加 `stream` 模式：回调桥接 SSE；`node_start/token/node_end/branch/human_approval/done/error` 事件序列；挂起恢复复用 flow_runs（与 `/chat` 共享恢复逻辑）
- 新端点 `POST /chat_apps/{id}/chat/stream`（chat 模式 = 现有 SSE；flow = 节点事件流）
- QU 节点（qu.answer 含 upgrade_with_llm）仅节点级事件，不发 token
- 验证：pytest 事件序列/挂起恢复/非 LLM 节点无 token 用例；dev 手测流式表现

### Task 7 — 后端 pytest 全量补齐 ✅
**文件**：`tests/test_agent_center.py`（新，16 用例）、`tests/test_agent_center_stream.py`（新，4 用例）
- 覆盖 Task 2-6 全部用例（设计 §6.1）：搜索多字段/排序 hot 聚合/发布分类必填/收藏幂等/CASCADE/回草稿恢复/矩阵四态/词表 CRUD+rename+置空/SSE 事件序列
- 验证：`make test` 全量绿（含既有用例回归）

### Task 8 — 智能体页重构（admin 前端） ✅
**文件**：`apps/earp-admin/pages/apps.html`、`apps/earp-admin/js/apps.js`（新）、`css/admin.css`
- 工具栏：搜索框（q）/ 分类下拉 / 类型筛选（全部/chat/chatflow）/ 排序（最新/最热）/ Tab（全部智能体/我的应用）
- 卡片：名称/描述/类型徽标/分类/标签/创建人/收藏数/⭐收藏按钮（点击即收藏，乐观更新）
- 运行抽屉：点击卡片右侧滑出（SSE 流式对话；chatflow 节点执行折叠面板）；「全屏」→ run.html
- 空态/加载/错误；权限不可见由后端过滤（前端不额外判断）
- 验证：手动 + smoke（Task 13）

### Task 9 — 独立运行页 run.html ✅
**文件**：`apps/earp-admin/pages/run.html`、`js/run.js`（新）、`css/admin.css`
- 左栏会话历史（按 app + user_id；新建/切换/删除，复用现有 conversation API）
- 主区：SSE 渲染（chat 逐字；chatflow 节点实时进度：名称/状态✓⏳✗/耗时/分支/token）
- human_approval：挂起确认条 + 问题，确认/拒绝后续跑（/chat/stream 恢复）
- 顶部：返回列表、应用名/分类/⭐收藏
- 验证：手动 + smoke

### Task 10 — 治理中心两页 ✅
**文件**：`apps/earp-admin/pages/app-categories.html`、`js/app-categories.js`、`pages/app-access.html`、`js/app-access.js`
- 分类页：词表表格 CRUD（名称/排序/操作）；删除被引用 → 提示「该分类下存在 N 个应用，删除后置空」
- 矩阵页：行=角色（非 admin）、列=已发布应用；每应用 mode 开关（open 默认/restricted）+ 角色勾选；0 勾选回 open；应用搜索；保存调 PUT；删除角色 fail-closed 提示
- 验证：手动 + smoke

### Task 11 — 工作台发布表单 + 编辑字段 ✅
**文件**：`apps/earp-admin/pages/chat-edit.html`、`chatflow-edit.html`
- 编辑面板加「业务分类（下拉，词表数据）+ 标签（逗号分隔）」字段，随保存带上（PATCH category/tags）
- 「发布」弹窗 → 发布表单：名称/描述确认 + 分类下拉（必填）+ 标签（可改）；前端校验 + 后端 422 兜底
- 验证：手动 + smoke

### Task 12 — 导航调整 ✅
**文件**：`apps/earp-admin/js/nav.js`
- apps 抽屉「概览」→「智能体」；「我的应用」占位移除（页内 Tab）
- 治理中心新增「应用分类」「应用权限」（与 Roles 同区，替代 Policy 占位或并列）
- 验证：页面导航可达

### Task 13 — 前端 smoke 测试 ✅
**文件**：`apps/earp-admin/test-apps-smoke.cjs`、`test-app-categories-smoke.cjs`、`test-app-access-smoke.cjs`（新，沿用现有 cjs 模式）
- 智能体页：加载/筛选/搜索/收藏/我的应用切换/运行抽屉 DOM 断言
- 治理中心两页：CRUD 交互断言
- 发布表单校验断言
- 验证：node 运行全绿

### Task 14 — 联调 + e2e 验收 ⏳（待人工）
**文件**：dev 环境 + 人工验收（脚本见 `docs/` 验收方案）
- 手动验收流：建 chatflow → 填分类/标签 → 发布 → 智能体页可见 → 运行（SSE 节点实时）→ 收藏 → 我的应用 → 治理中心配白名单 → 换无权限角色不可见 → fail-closed 验证
- 回归：chat 智能体发布-运行全流程不受影响；原非流式 /chat 兼容
- 验证：验收流全通，写验收记录

## 验收标准（DoD）

1. `make test` 全量绿 + 3 个 smoke cjs 绿
2. e2e 验收流全通（含权限矩阵 fail-closed、收藏下架恢复、flow SSE 挂起恢复）
3. 原非流式 flow / chat 路径无回归
4. openapi 导出含新端点
