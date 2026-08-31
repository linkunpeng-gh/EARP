# ECMC 前端信息架构与页面开发模板

- **文档编号：** FE-ECMC-2026-0830
- **状态：** Draft v0.1（产品布局讨论已确认，待前端评审）
- **日期：** 2026-08-30
- **适用应用：** `apps/earp-admin`
- **当前实施范围：** N01B 因果模型可视化管理
- **未来扩展范围：** 决策模型、任务模型
- **权威后端合同：** N01A API、Canonicalization、CatalogResolver 与 Blueprint Erratum

## 1. 文档目的

本文定义 Enterprise Cognitive Model Center（ECMC，企业认知模型中心）的前端信息架构、页面布局、公共组件、交互状态、API 使用规则和验收模板，供前端开发、测试和产品验收共同使用。

ECMC 是独立一级产品界面，不属于静态知识库、能力注册或系统治理的子页面。其职责是管理可版本化、可审核、可编译、可激活的企业认知模型。

本文不重新定义后端领域合同。前端不得自行计算 Snapshot/Artifact hash，不得绕过发布、编译或激活门禁，也不得引入自由 SQL、Provider 参数、endpoint、凭据或自由 DSL。

## 2. 产品定位与边界

### 2.1 一级导航定位

Admin 一级导航建议调整为：

```text
首页｜工作台｜知识中心｜认知模型｜能力中心｜应用中心｜治理中心｜运行监控
```

现有“插件中心”建议合并到应用中心或能力中心，避免 1280px 视口下一级导航拥挤。最终归属由导航专项评审确认。

一级菜单显示名称为“认知模型”，进入后页面品牌使用：

```text
企业认知模型中心 ECMC
```

### 2.2 与相邻模块的边界

| 模块 | 负责 | 不负责 |
|---|---|---|
| 知识中心 | 文档、Ontology、实体、关系、静态语义资产 | 模型版本治理、编译和激活 |
| ECMC | 因果/决策/任务模型、版本、审核、Snapshot、Artifact、激活 | Provider 配置、运行诊断结果展示 |
| 能力中心 | Capability Contract、连接器、执行能力、LLM 配置 | 认知模型内容与发布治理 |
| 治理中心 | 角色、权限、审计、平台策略 | 重复实现 ECMC 审核工作台 |
| 运行监控 | Session、Trace、基础设施与运行异常 | 模型内容编辑 |

### 2.3 模型族

```text
因果模型：解释“为什么发生”
    ↓ 诊断结果、证据、置信度
决策模型：判断“应该做什么”
    ↓ 推荐措施、约束、审批点
任务模型：定义“如何执行”
    ↓ 步骤、依赖、能力需求
Blueprint / Planner / Runtime
```

当前只实现因果模型。决策模型和任务模型在导航、筛选和公共组件上预留扩展点，但在相应 PRD/API 冻结前必须显示“规划中”，不得复用因果模型 API 伪造功能。

## 3. 设计原则

1. **统一治理外壳，类型内核独立。** Model、Version、Review、Snapshot、Compile、Activation 使用一致的产品语言；不同模型类型使用独立编辑器和校验语义。
2. **列表与编辑分离。** 普通管理页负责查找、筛选、治理；图编辑器使用独立全屏页面。
3. **已发布内容只读。** Published、superseded、archived 版本不得出现可写表单。
4. **受控引用优先。** 可执行字段只能由 Catalog 选择器产生，用户不能手写 Catalog ID、SQL、Provider 或 endpoint。
5. **校验问题可定位。** 每个 ValidationIssue 都必须能定位到节点、边、规则或证据需求。
6. **系统错误与业务校验分离。** 权限、可见性、并发和状态错误使用全局错误反馈，不进入 ValidationResult。
7. **发布与激活分离。** 发布产生 immutable Snapshot；编译产生 Candidate Artifact；激活物化指定 Artifact。
8. **并发显式可见。** 页面必须保存 ETag/revision，冲突时禁止静默覆盖。
9. **不双维护 Blueprint。** 前端只编辑认知模型，不提供 Blueprint 镜像编辑字段。

## 4. 信息架构

### 4.1 ECMC 左侧二级导航

```text
认知模型 ECMC
├─ 概览
├─ 模型资产
│  ├─ 全部模型
│  ├─ 因果模型
│  ├─ 决策模型（规划中）
│  └─ 任务模型（规划中）
├─ 审核发布
│  ├─ 待我审核
│  ├─ 发布记录
│  └─ 驳回记录
├─ 编译与激活
│  ├─ Compile Attempts
│  ├─ Candidate Artifacts
│  └─ Active Versions
├─ 模型依赖（后续）
└─ 目录扩展申请
```

一级页面保留 ECMC 二级抽屉；进入模型编辑器后折叠二级抽屉，将空间交给画布。

### 4.2 推荐路由

当前 `earp-admin` 为静态 HTML/JS 应用，建议使用独立文件加 query 参数：

| 页面 | 路由建议 | 当前范围 |
|---|---|---|
| ECMC 概览 | `pages/ecmc.html` | N01B |
| 模型资产 | `pages/ecmc-models.html?type=causal` | N01B |
| 因果模型编辑器 | `pages/ecmc-causal-edit.html?model_id=…&version_id=…` | N01B |
| 审核发布 | `pages/ecmc-reviews.html` | N01B |
| 编译与激活 | `pages/ecmc-compiles.html` | N01B |
| 目录申请 | `pages/ecmc-catalog-requests.html` | N01B |
| 决策模型编辑器 | `pages/ecmc-decision-edit.html` | 规划中 |
| 任务模型编辑器 | `pages/ecmc-task-edit.html` | 规划中 |

不得把所有功能继续堆叠在现有 `causal-models.html` 单页中。该页面应迁移为模型资产页或在迁移后删除入口。

## 5. 公共页面模板

### 5.1 管理列表页

适用于模型资产、审核列表、Compile Attempts、目录申请。

```text
┌ 页面标题 / 说明 ─────────────────────────────── 主要操作 ┐
├ 类型 Tab / 状态摘要 ────────────────────────────────────┤
├ 搜索 ─ 数据域 ─ 状态 ─ 创建人 ─ 时间 ────────────────┤
├─────────────────────────────────────────────────────────┤
│ 名称 │ 类型 │ 目标 │ 最新版本 │ 状态 │ 活跃版本 │ 操作 │
│ ...                                                     │
├─────────────────────────────────────────────────────────┤
│ 分页                                                     │
└─────────────────────────────────────────────────────────┘
```

规则：

- 表格行点击进入详情或编辑器。
- 行内最多保留一个主要操作和一个“更多”菜单。
- 状态筛选必须使用后端状态枚举，不得创造含义重叠的前端状态。
- 页面空状态应解释下一步，而不是展示模拟业务数据。
- API 不可用时明确展示连接失败，不得回退为伪造模型。

### 5.2 全屏编辑器

```text
┌ 返回 ─ 模型名 / 版本 ─ 状态 ─ revision ─── 校验  提交审核  更多 ┐
├──────────────┬────────────────────────────┬────────────────────┤
│ 图结构/组件   │                            │ 属性 / 证据 / 规则 │
│              │                            │                    │
│ 节点列表      │          DAG 画布           │ Catalog 选择器      │
│ 边列表        │                            │ 业务说明             │
│ 证据需求      │                            │ 可观测性配置          │
│              │                            │                    │
├──────────────┴────────────────────────────┴────────────────────┤
│ 校验结果：阻断 3 · 警告 2 · 点击问题定位到资源                  │
└────────────────────────────────────────────────────────────────┘
```

尺寸基线：

| 区域 | 推荐宽度/高度 |
|---|---:|
| 顶部全局导航 | 56px 高 |
| 编辑器命令栏 | 52px 高 |
| 左侧结构面板 | 220–240px，可折叠 |
| 中央画布 | 自适应，最小 720px |
| 右侧属性面板 | 320–360px，可折叠 |
| 底部校验抽屉 | 收起 40px，展开 240–320px |

编辑器不使用普通页面的 `main { max-width: 1200px }` 限制，应占满剩余视口宽高。

### 5.3 只读审核页

审核页复用编辑器布局，但必须满足：

- 内容控件全部只读。
- 顶部主要操作变为“通过并发布”和“驳回”。
- 右侧默认展示治理信息：提交人、提交时间、校验结果、版本 hash、影响范围。
- 审核人可定位问题，但不可在被审核版本上直接修复。
- 驳回必须填写原因。

## 6. ECMC 概览页

概览页用于进入工作，不承担深度分析。

### 6.1 状态卡片

- 模型总数
- Draft 数量
- 待我审核
- 编译失败
- 当前 Active 模型

卡片必须可点击进入带筛选条件的列表。

### 6.2 工作队列

- 最近编辑的模型
- 待我审核
- 最近失败的 Compile Attempt
- 待处理目录扩展申请

### 6.3 模型族展示

因果模型正常展示数据；决策模型和任务模型显示规划说明，不展示虚构数量。

## 7. 模型资产页

### 7.1 表格字段

| 字段 | 说明 |
|---|---|
| 模型名称 | 业务名称和短 ID |
| 类型 | causal / decision / task 标签 |
| 诊断/决策/任务目标 | 当前模型的业务目标摘要 |
| 数据域 | 受控 DataDomain |
| 最新版本 | 最新 Version 与状态 |
| Active Version | 当前激活指针，无则显示“未激活” |
| 最近更新 | 时间和操作者 |
| 操作 | 查看、继续编辑、复制草稿、更多 |

### 7.2 新建模型向导

第一步选择模型类型。当前只有“因果模型”可用，其他类型显示“规划中”。

因果模型创建步骤：

1. 选择目标数据域。
2. 选择目标实体类型。
3. 定义诊断方向、入口和时间窗口 Schema。
4. 填写模型名称和业务说明。
5. 确认 DiagnosticTarget signature 后创建。

DiagnosticTarget 创建后不可修改；需要改变目标时创建新模型，不能通过编辑 Version 绕过签名约束。

## 8. 因果模型编辑器

### 8.1 顶部命令栏

左侧：

- 返回模型资产
- 模型名称
- Version 选择器
- Governance status
- Active 标记
- revision/保存状态

右侧根据状态显示：

| 状态 | 主要操作 |
|---|---|
| draft | 校验、提交审核、更多 |
| in_review | 通过并发布、驳回 |
| published | 复制为新草稿、编译、查看 Artifact |
| superseded | 查看、复制为新草稿、归档 |
| archived | 查看 |

“提交审核”与“发布”必须使用不同文案和不同权限。不得使用含混的“提交发布”。

### 8.2 左侧结构面板

提供两个 Tab：

1. **图结构：** 节点、边、规则、证据需求的树状大纲。
2. **组件：** 新增节点、边、规则和证据需求的入口。

支持按 key/业务名称搜索。点击条目应选中并居中画布资源。

### 8.3 中央 DAG 画布

最低能力：

- 添加、移动、选择和删除节点。
- 从节点端口创建有向边。
- 显示 effect、strength、confidence 和 lag。
- 缩放、平移、适配屏幕和自动布局。
- 入口节点、required evidence、阻断错误使用不同视觉标记。
- 删除有依赖的节点前展示依赖清单，不直接发送删除请求。

节点卡片展示：

- 业务名称
- node key
- EntityType 简称
- 入口标记
- Required evidence 完整度
- Validation error/warning 数量

画布位置属于视图数据，不进入模型 canonical hash。

**当前合同缺口：** N01A API 未冻结画布坐标持久化字段。签署前首版采用确定性自动布局；可以将个人视图位置保存在浏览器本地，但不得宣称为跨用户模型数据，也不得写入 N01A 内容 API。

### 8.4 右侧属性面板

根据选中资源显示：

#### 节点

- node key（创建后只读）
- 业务名称
- EntityType CatalogRef
- entry point
- observability
- notes

#### 边

- edge key（创建后只读）
- source / target
- RelationType CatalogRef
- effect
- strength
- confidence
- lag

#### 证据需求

- metric、unit、aggregation
- time window
- binding template 与受控参数
- primary/supporting Capability Contract
- required
- 业务说明

#### 规则

- RuleSchema CatalogRef
- 结构化 rule spec
- rationale

可执行字段必须使用 `CatalogRefPicker`。业务说明、备注和 rationale 可以自由输入。

### 8.5 保存模型

所有业务写请求必须：

- 携带唯一 `Idempotency-Key`。
- Version mutation 携带当前 `If-Match: "v<revision>"`。
- 成功后使用响应 revision 更新页面 ETag。
- 同一 Version 的写入串行执行，不允许并发发送多个旧 revision 请求。

推荐交互：表单点击“应用”时立即保存当前资源；画布结构操作完成后立即保存。顶部显示“保存中 / 已保存 / 保存失败”。首版不实现跨资源批量保存事务。

遇到 `409 VERSION_CONFLICT`：

1. 停止该 Version 后续写队列。
2. 展示“版本已被其他用户更新”。
3. 提供“重新加载”按钮。
4. 不提供静默覆盖。

## 9. CatalogRefPicker

### 9.1 展示格式

```text
业务名称
metric.haulage_cycle_time · v1
```

选择器按 `kind`、数据域和 active 状态过滤，只返回精确版本。

### 9.2 缺项流程

搜索无结果时展示“申请新增目录项”，打开 CatalogChangeRequest 侧边抽屉。申请通过并履约前，该引用不能进入模型内容。

### 9.3 禁止行为

- 不提供任意 stable ID 输入框。
- 不接受 `latest`、`*` 或 display name 代替版本。
- 不提供 SQL、URL、endpoint、Provider、credential 或自由 DSL 字段。
- Case A Fixture 目录只能用于 test-only UI composition，禁止进入正式生产页面。

**当前合同缺口：** N01A 只冻结 Resolver interface 和变更申请 API，尚未冻结生产 Catalog browse/search API 与 manifest owner。生产选择器依赖该合同签署；签署前只能完成组件、fake adapter 和 contract test，不得假设真实目录存在。

## 10. 校验面板

底部抽屉分为：

- 阻断发布
- 警告

每条 ValidationIssue 展示：

- code
- message
- resource type
- resource key/location
- 修复建议
- “定位”操作

点击定位：

- 节点/边：画布居中并选中。
- 证据/规则：选中所属节点并打开对应属性 Tab。
- 全局问题：打开 Version/DiagnosticTarget 信息面板。

权限不足、不可见、If-Match 冲突、active CAS 冲突和请求 schema 错误通过全局错误条或对话框展示，不混入校验列表。

## 11. 审核、发布、编译与激活

### 11.1 提交审核

Draft 页面先运行 publish-mode validation。存在阻断问题时禁用“提交审核”，并展开校验面板。

提交成功后页面切换为只读 `in_review`。

### 11.2 驳回

审核人必须填写驳回原因。成功后 Version 回到 draft，revision 更新，建模者可以继续编辑。

### 11.3 发布确认

发布确认对话框展示：

- 模型与 Version
- DiagnosticTarget signature
- 最新校验结果
- 将生成的 Snapshot 信息
- 数据域与 Catalog pins
- 发布后不可变说明

前端不预计算 canonical hash。发布成功后展示服务端返回的 Snapshot ID/hash。

### 11.4 编译

Published Version 页面提供“编译”操作和 Compile Attempts 列表。

- running：展示进度状态，不展示伪 Artifact。
- success：允许查看只读 Candidate Artifact。
- failed：展示稳定错误码，并允许创建新的 retry Attempt。
- retry 必须展示 `retry_of_compile_id` 链路。

### 11.5 激活

激活确认对话框必须展示：

- Candidate Version 与当前 revision。
- 指定 Compile Attempt/Artifact hash。
- 当前 active pointer。
- expected active pointer。
- 将被 supersede/withdraw 的精确来源。

请求同时携带 Candidate `If-Match` 和 active-pointer CAS。收到 `409 ACTIVE_VERSION_CHANGED` 后刷新当前 active pointer，不自动重试，不选择其他 Artifact。

## 12. 模型依赖视图（未来）

跨模型引用必须固定到已发布 Version/Snapshot：

```text
TaskModel v4
└─ DecisionModel v2 / snapshot_hash=…
   └─ CausalModel v3 / snapshot_hash=…
```

规则：

- 不允许引用其他模型 Draft。
- 上游发布新版本不能自动改变下游模型。
- 上游归档前展示依赖影响。
- 不静默重绑 Snapshot。
- 任务模型前端不得修改既有 `/plan` 或 SimpleTaskPlanner 业务语义。

该页面在决策/任务模型合同冻结前仅保留设计，不进入 N01B 实施。

## 13. 公共组件契约

| 组件 | 职责 | 关键输入 | 关键输出 |
|---|---|---|---|
| `EcmcDrawer` | ECMC 二级导航 | active item、permission counts | route navigation |
| `ModelTypeBadge` | 模型类型展示 | causal/decision/task | 无 |
| `GovernanceStatusBadge` | 状态展示 | frozen status enum | 无 |
| `VersionPicker` | 版本选择 | versions、active pointer | selected version |
| `EditorCommandBar` | 状态相关命令 | status、permissions、dirty、revision | command event |
| `ModelOutline` | 资源树与搜索 | nodes/edges/rules/evidence | selected resource |
| `CausalGraphCanvas` | DAG 编辑 | content、selection、issues | graph mutation |
| `ResourceInspector` | 类型化属性编辑 | selected resource、editable | validated mutation |
| `CatalogRefPicker` | 受控目录选择 | kind、domain、value | exact CatalogRef |
| `ValidationDrawer` | 校验展示与定位 | ValidationResult | locate event |
| `PublishDialog` | 发布确认 | governance、validation、pins | confirm/cancel |
| `ActivationDialog` | 双 CAS 确认 | candidate、artifact、active pointer | ActivateRequest |
| `CatalogRequestDrawer` | 目录扩展申请 | missing kind/domain | request created |
| `VersionConflictDialog` | 并发冲突 | local/current revision | reload |

当前应用采用原生 HTML/CSS/JavaScript。公共逻辑放入独立 JS 模块，禁止在多个页面复制状态映射、header 生成、错误处理和 CatalogRef 校验代码。

## 14. 状态与权限矩阵

### 14.1 Version 状态

| 状态 | 内容编辑 | 提交审核 | 发布/驳回 | 编译 | 激活 | 归档 |
|---|---:|---:|---:|---:|---:|---:|
| draft | 是 | 是 | 否 | 否 | 否 | 按合同 |
| in_review | 否 | 否 | 是 | 否 | 否 | 否 |
| published | 否 | 否 | 否 | 是 | success 后 | 是 |
| superseded | 否 | 否 | 否 | 查看 | 否 | 是 |
| archived | 否 | 否 | 否 | 查看 | 否 | 否 |

### 14.2 权限

| 权限 | UI 能力 |
|---|---|
| `ecmc.causal_model.read` | 查看可见模型和版本内容 |
| `ecmc.causal_model.write_draft` | 创建和编辑 Draft、校验、提交审核 |
| `ecmc.causal_model.review` | 驳回和治理发布 |
| `ecmc.causal_model.compile` | 请求 Compile Attempt/retry |
| `ecmc.causal_model.activate` | 激活和 active archive |
| `ecmc.causal_model.audit.read` | 查看治理状态和 Candidate Artifact |
| `ecmc.catalog.read` | 查看目录申请及未来 Catalog 选择器 |
| `ecmc.catalog.request` | 创建、编辑、提交和取消自己的申请 |
| `ecmc.catalog.approve` | 审批与 retry fulfillment |

前端隐藏或禁用无权限操作只用于改善体验；后端仍是最终授权边界。

## 15. HTTP 与错误处理规范

### 15.1 Headers

所有写请求生成新的 `Idempotency-Key`。同一次用户操作发生网络重试时复用原 key，不同用户操作不得复用。

Version mutation 使用最近一次读取/写入响应的 ETag。不得使用本地自增 revision 推测服务端状态。

### 15.2 稳定错误映射

| HTTP/code | 前端处理 |
|---|---|
| 403 | 权限提示，不显示为校验问题 |
| 404 | 返回列表或展示不可见，不泄漏跨域资源 |
| 409 `VERSION_CONFLICT` | 停止写队列并要求重新加载 |
| 409 `ACTIVE_VERSION_CHANGED` | 刷新 active pointer，不自动激活 |
| 409 `IDEMPOTENCY_KEY_REUSE` | 记录前端错误并重新生成业务操作 |
| 422 `MISSING_IF_MATCH` | 前端合同错误，阻止继续写入 |
| 422 `REQUEST_SCHEMA_INVALID` | 定位表单字段，不加入 ValidationResult |
| 422 `MODEL_VALIDATION_FAILED` | 展开校验面板 |

所有错误提示展示 `correlation_id` 的复制入口，便于审计与排障。

## 16. 响应式与可访问性

ECMC 编辑器以桌面建模为主：

- `>= 1440px`：三栏全部展开。
- `1280–1439px`：收起 ECMC 抽屉，保留模型结构与属性面板。
- `1024–1279px`：左/右面板只能展开一个，中央画布保持主要空间。
- `< 1024px`：提供只读查看和审核摘要；不承诺完整拖拽建模体验。

可访问性要求：

- 所有颜色状态同时提供文本或图标含义。
- 画布资源可以从左侧结构树通过键盘选中。
- 表单控件具有 label 和可读错误信息。
- 对话框锁定焦点并支持 Escape 取消。
- `Ctrl/Cmd+S` 触发当前资源保存；不得绕过表单校验。

## 17. 视觉规范

沿用现有 `admin.css` Design Token：背景、边框、主色、状态色和字体不另起一套主题。

状态色建议：

| 状态 | 颜色语义 |
|---|---|
| draft | 中性灰/蓝 |
| in_review | amber |
| published | green |
| active | accent purple + 实心标记 |
| superseded | 灰 |
| archived | 浅灰 |
| blocking error | red |
| warning | amber |

画布节点颜色用于资源状态，不用于区分任意业务类别，避免颜色数量失控。

## 18. 文件组织建议

```text
apps/earp-admin/
├─ pages/
│  ├─ ecmc.html
│  ├─ ecmc-models.html
│  ├─ ecmc-causal-edit.html
│  ├─ ecmc-reviews.html
│  ├─ ecmc-compiles.html
│  └─ ecmc-catalog-requests.html
├─ js/
│  ├─ ecmc-api.js
│  ├─ ecmc-common.js
│  ├─ ecmc-models.js
│  ├─ ecmc-causal-editor.js
│  ├─ ecmc-validation.js
│  ├─ ecmc-catalog-picker.js
│  └─ ecmc-governance.js
└─ css/
   └─ ecmc.css
```

`ecmc-api.js` 统一负责 headers、ETag、Idempotency-Key、错误解析和 correlation ID。业务页面不得直接复制 `fetch` 封装。

如复用 vendored Drawflow，必须建立 ECMC 专属 adapter，将 Drawflow 内部 ID 与稳定的 node/edge key 分离；不得把 Drawflow export 当作 N01A 模型或 Snapshot payload。

## 19. API 映射（N01B）

| UI 操作 | N01A API |
|---|---|
| 模型列表/详情 | `GET /v1/ecmc/causal-models`、`GET /{model_id}` |
| 创建模型 | `POST /v1/ecmc/causal-models` |
| 创建/复制 Version | `POST /{model_id}/versions` |
| 读取 Version 内容 | `GET /{model_id}/versions/{version_id}` |
| 编辑 Version 元数据 | `PATCH /{model_id}/versions/{version_id}` |
| 节点/边/规则/证据 CRUD | 对应 `PUT/DELETE` 资源路由 |
| 校验 | `POST /{version_id}/validate` |
| 提交/驳回/发布/归档 | 对应 command 路由 |
| 编译 | `POST /{version_id}/compile` |
| Artifact 查看 | `GET /compile-records/{compile_record_id}/artifact` |
| 激活 | `POST /causal-models/{model_id}/activate` |
| 治理详情 | `GET /{version_id}/governance` |
| 目录申请 | `/v1/ecmc/catalog-change-requests` 资源与 command 路由 |

完整字段、headers、HTTP status 和错误码以冻结 API 合同为准。

## 20. 测试与验收模板

### 20.1 自动化测试

- JS 单元/冒烟：状态映射、权限动作、ETag 更新、Idempotency 重试、错误映射。
- Canvas adapter：节点/边 round-trip、稳定 key、DAG 定位、删除依赖保护。
- CatalogRefPicker contract test：kind、domain、exact version、active 状态。
- API contract：所有写请求 headers、字段白名单和错误码。
- 静态检查：`node --check`、现有导航 smoke、`git diff --check`。
- 后端回归：N01A、Case A、`ruff`、import-linter。

### 20.2 人工验收主路径

1. 建模者创建“3 号矿产量下降”因果模型。
2. 添加业务语义等价于 Case A 的节点、边、证据和规则。
3. 保存并重新打开 Draft，内容保持一致。
4. 制造环、悬空引用、缺失 required evidence，确认阻断并能定位。
5. 修复问题并提交审核。
6. 审核者驳回一次，建模者修改后重新提交。
7. 审核者发布，确认 Snapshot ID/hash 与只读状态。
8. 请求 Compile，确认 success 只产生 Candidate Artifact。
9. 激活指定 Artifact，确认 Active Version 更新。
10. 使用旧 active pointer 发起激活，确认 `ACTIVE_VERSION_CHANGED` 且页面刷新。
11. 归档 active Version，确认 active pointer 清空和来源 Blueprint withdrawn。
12. 使用两个租户和无权限角色确认不可见/不可操作。

### 20.3 布局验收

- 1440px 下中央画布宽度不少于 720px。
- 1280px 下进入编辑器时 ECMC 抽屉可折叠。
- 校验抽屉展开不永久挤压画布宽度。
- Published/archived 页面不存在可写控件。
- 所有 Catalog 可执行字段均无自由 ID/JSON/SQL 输入入口。

## 21. 开放项与签署门

| 项目 | 当前状态 | 决策前允许的实现 |
|---|---|---|
| 生产 Catalog browse/search API | 未冻结 | 组件、fake adapter、contract test |
| Catalog manifest/owner | 未签署 | 不接生产目录，不假设真实 Provider |
| 画布位置持久化 | 未进入 N01A 合同 | 确定性自动布局或个人本地视图 |
| 决策模型 API/元模型 | 未冻结 | 导航占位与公共外壳 |
| 任务模型 API/元模型 | 未冻结 | 导航占位与公共外壳 |
| 模型依赖图合同 | 未冻结 | 设计保留，不构造业务数据 |
| 插件中心导航合并 | 待导航评审 | ECMC 顶栏在 1280px 做响应式验证 |

任何开放项不得通过自由字段、Fixture 泄漏或前端伪数据绕过。

## 22. 实施顺序

1. 调整一级导航，建立 ECMC shell 和占位路由。
2. 拆分模型资产页与全屏因果编辑器。
3. 建立统一 `ecmc-api.js`、状态/权限/错误组件。
4. 完成节点、边、规则、证据需求编辑与确定性布局。
5. 完成校验定位、提交审核和只读审核页。
6. 完成发布确认、Compile Attempts、Artifact 查看与激活确认。
7. 完成 CatalogChangeRequest 页面；生产 CatalogPicker 等待合同签署。
8. 执行自动化、Case A 人工路径、并发和租户隔离验收。

决策模型和任务模型分别立项，不得作为 N01B 的隐式范围扩张。

## 23. 关联文档

- `arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`
- `arch/design/2026-08-11-admin-navigation-redesign.md`
- `prd/PRD-2026-033-causal-model-management-n01a.md`
- `arch/design/2026-08-30-causal-model-management-n01-detailed-design.md`
- `api/2026-08-30-n01a-causal-model-management-api-contract.md`
- `arch/design/2026-08-30-n01a-canonicalization-and-hash-contract.md`
- `arch/design/2026-08-30-n01a-catalog-resolver-and-fixture-boundary.md`
- `arch/design/2026-08-30-planning-blueprint-l3-implementation-erratum-n01a.md`
