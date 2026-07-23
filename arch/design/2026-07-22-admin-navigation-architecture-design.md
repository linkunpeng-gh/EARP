# Admin Dashboard 导航架构 - 设计方案

- 日期: 2026-07-22
- 状态: draft
- 关联 PRD: PRD-2026-028-admin-dashboard v1.7

## 1. 背景与目标

Admin Dashboard 现有 10 个页面，导航采用直觉分组（3 组分隔线），未反映 EARP 的平台领域模型。L2 规范定义了 10 个领域模块，前端应与之对齐，使导航成为「平台域地图」而非随意菜单。

**目标**：重组 Admin Dashboard 顶层导航，使其严格映射 EARP L2 领域分区，同时保持当前页面数量不变（9 已实现 + 1 Langfuse Phase 2），并为已知缺口（Roles/Tenants/Policy）预留扩展空间。

## 2. 方案对比

### 方案 A：严格 L2 平铺
每个 L2 域一个顶层导航项。8 个顶层，Execution 当前为空。

### 方案 B：按平台分层聚合
相近域合并为 5-6 个顶层。运行时合并 01-runtime + 04-execution，治理合并 05+06+07。

### 方案 C：核心+扩展 ✅（选定）
核心域直接暴露，低频域折叠到「治理」下拉。6 个顶层，治理用下拉菜单容纳未实现的 Role/Tenant/Policy。

| | A | B | C |
|---|---|---|---|
| 顶层数 | 8 | 6 | 6 |
| 空项 | Execution 为空 | 无 | 无 |
| 扩展性 | 加一项挤一项 | 中 | 下拉加项即可 |
| L2 对齐度 | 精确 | 近似 | 近似 |

**选择理由**：C 保持 6 个顶层无空项，治理用下拉预留 Role/Tenant/Policy 不影响其他域的导航宽度；Audit 作为治理默认入口已有实现。

## 3. 推荐方案详述

### 3.1 导航树

```
OVERVIEW                         /admin/
────────────────────────────────────────────
运行时 (Runtime)                  /admin/sessions
  ├─ Sessions                    /admin/sessions
  └─ Executions                  /admin/executions  (Phase 2)
────────────────────────────────────────────
推理 (Reasoning)                  /admin/plan
  └─ Plan & Invoke               /admin/plan
────────────────────────────────────────────
能力 (Capability)                 /admin/capabilities
  ├─ Capabilities                /admin/capabilities
  └─ Workflows                   /admin/workflows     (新增)
────────────────────────────────────────────
知识 (Knowledge)                  /admin/knowledge
  ├─ Knowledge Base              /admin/knowledge
  └─ Data Domains                /admin/data-domains
────────────────────────────────────────────
对话 (Conversation)               /admin/conversations
  └─ Conversations               /admin/conversations
────────────────────────────────────────────
治理 ▾ (Governance)               /admin/audit
  ├─ Audit Logs                  /admin/audit
  ├─ Roles & Permissions         /admin/roles         (新增)
  ├─ Organization                /admin/org-units      (新增)
  ├─ Tenant Management           /admin/tenants       (新增)
  ├─ Policy Center               /admin/policy        (新增)
  └─ Observability               /admin/observability (Phase 2)
```

### 3.2 L2 领域映射

| 导航项 | L2 目录 | 包含页面 | 状态 |
|---|---|---|---|
| Overview | — | Dashboard Home | ✅ |
| 运行时 | 01-runtime + 04-execution | Sessions, Executions | Sessions ✅, Executions ❌ |
| 推理 | 02-reasoning | Plan & Invoke（含 Streaming） | ✅（Stream 融入 Plan） |
| 能力 | 03-capability | Capabilities | ✅ |
| 知识 | 11-knowledge | Knowledge Base, Data Domains | ✅✅ |
| 对话 | 09-conversation | Conversations | ✅ |
| 治理 | 05-governance + 06-security + 07-tenant | Audit, Roles, Org-Units, Tenants, Policy, Observability | Audit ✅, Observability (Phase 2), 其余 ❌ |

### 3.3 与当前导航的差异

```
当前                                目标
──────────────────────────          ──────────────────────────
Overview                            Overview                   — 不变
── 分隔线 ──
Sessions                            运行时 ▾ Sessions          — 改组名+加子页占位
Plan & Invoke                       推理 ▾ Plan & Invoke       — 改组名
Streaming                                  Streaming
── 分隔线 ──
Knowledge                           知识 ▾ Knowledge Base      — 合并两个知识页
Data Domains                               Data Domains
── 分隔线 ──
Capabilities                        能力   Capabilities        — 独立出组
Conversations                       对话   Conversations       — 独立出组
── 无 ──
Audit                               治理 ▾ Audit Logs          — 降级为下拉项
                                           Roles               — 新增预留
                                           Tenants             — 新增预留
                                           Policy              — 新增预留
── 无 ──
Langfuse (iframe)                   可观测                     — Phase 2 独立
```

**关键变化**：
1. 「Sessions」改称「运行时」——语义从「一个资源列表」提升为「运行时域入口」
2. 「Plan & Invoke + Streaming」归入「推理」——两组当前被分隔线隔开的页面逻辑上属于同一域（02-reasoning）
3. 「Knowledge + Data Domains」合并为「知识」——两个页面处理同一领域，不应分属不同组
4. 「Capabilities」独立——属于 03-capability 域，不与任何其他域合并
5. 「Conversations」独立——属于 09-conversation 域
6. 「Audit」收入治理下拉——治理域包含 Audit Logs + 预留 Roles/Tenants/Policy + Phase 2 Observability(Langfuse)
7. `doc-config.html` 保留——作为 Knowledge Base 的子页面，不在顶层导航中出现

### 3.4 交互规则

- **顶层导航项**（运行时/推理/能力/知识/对话）：点击跳转到该域默认页
- **治理 ▾**：hover/focus-within 展开下拉菜单，点击 Audit Logs 跳转（当前唯一实现）。未来 Role/Tenant/Policy 实现后直接加下拉项
- **活动态**：当前所在域的顶层导航项高亮（accent underline）。子页内保持父域高亮
- **Overview**：特殊处理——不属于任何 L2 域，始终作为首个导航项

### 3.5 HTML 结构变更

现有 `<nav>` 从平铺链接变为分组结构：

```html
<nav>
  <!-- Overview — 独立 -->
  <a href="index.html" class="active" aria-current="page">Overview</a>

  <!-- 运行时 — 分组容器 -->
  <div class="nav-group">
    <a href="pages/sessions.html">运行时</a>
  </div>

  <!-- 推理 — 分组容器 -->
  <div class="nav-group">
    <a href="pages/plan.html">推理</a>
  </div>

  <!-- 能力 — 单页组 -->
  <div class="nav-group">
    <a href="pages/capabilities.html">能力</a>
  </div>

  <!-- 知识 — 含子页 -->
  <div class="nav-group">
    <a href="pages/knowledge.html">知识</a>
  </div>

  <!-- 对话 — 单页组 -->
  <div class="nav-group">
    <a href="pages/conversations.html">对话</a>
  </div>

  <!-- 治理 — 下拉菜单 -->
  <div class="nav-group nav-dropdown">
    <a href="pages/audit.html">治理 ▾</a>
    <div class="dropdown-menu">
      <a href="pages/audit.html">Audit Logs</a>
      <a href="pages/roles.html" class="disabled">Roles &amp; Permissions</a>
      <a href="pages/tenants.html" class="disabled">Tenant Management</a>
      <a href="pages/policy.html" class="disabled">Policy Center</a>
      <a href="pages/observability.html" class="disabled">Observability</a>
    </div>
  </div>
</nav>
```

**状态**：
- `.nav-group` 作为逻辑分组容器，视觉上保持当前顶导风格（无分隔线）
- `.nav-dropdown` 用 CSS `:hover` / `:focus-within` 展开，零 JS 依赖
- `.disabled` 表示未实现页面，灰色不可点击

### 3.6 分页导航的活跃态判断

当前每页独立硬编码 `class="active"`。改为按路由前缀匹配：

| 导航项 | 活跃条件 |
|---|---|
| Overview | `location.pathname === '/admin/'` 或匹配 `index.html` |
| 运行时 | `/admin/sessions` 或 `/admin/executions` |
| 推理 | `/admin/plan` 或 `/admin/stream` |
| 能力 | `/admin/capabilities` |
| 知识 | `/admin/knowledge` 或 `/admin/data-domains` |
| 对话 | `/admin/conversations` |
| 治理 | `/admin/audit` 或 `/admin/roles` 或 `/admin/tenants` 或 `/admin/policy` |

实现：`js/app.js` 中 `EARP.setActiveNav()` 遍历 `<nav>` 内链接，按 `data-nav-group` 属性匹配当前路径。

## 4. 影响分析

### 受影响文件

| 文件 | 变更 |
|---|---|
| `apps/earp-admin/index.html` | 替换 `<nav>` 为分组结构 |
| `apps/earp-admin/pages/*.html` (全部 10 页) | 同步 `<nav>` 为新结构 |
| `apps/earp-admin/css/admin.css` | 新增 `.nav-group` / `.nav-dropdown` / `.dropdown-menu` 样式 |
| `apps/earp-admin/js/app.js` | 新增 `setActiveNav()` 函数 |
| `arch/design/` | 本设计文档 |

### 不影响

- 各页面主体内容
- API 端点
- User App (`apps/earp-user/`)
- 后端服务端代码

### 工作量

- 8 个页面的 `<nav>` 替换（index + 7 个已实现页面 + login？login 不含主导航）
- CSS 新增约 30 行
- JS 新增约 15 行
- 预估：1-2 小时

## 5. 已知限制与风险

| 限制/风险 | 缓解 |
|---|---|
| 导航项从 9 个增加到 6 个分组 + 4 个下拉，部分用户可能不习惯分组语义 | 分组名使用中文业务术语（运行时/推理/知识），非技术缩写 |
| 治理下拉在移动端体验差 | Phase 2 加媒体查询 `@media (max-width: 768px)` 改为折叠菜单 |
| `disabled` 页面占位可能让用户困惑 | 灰色文字 + 禁用光标，hover 时显示 tooltip "Coming in Phase 2" |
| 当前各页面 `<nav>` 各自独立，无法共享头部组件 | Phase 1 接受重复（CDN 无组件系统）；Phase 2 Vite 迁移后抽取为组件 |

## 6. 下一步

- [x] 用户评审本设计文档
- [x] 确认 `doc-config.html` 用途——保留，作为 Knowledge Base 子页
- [x] 确认「可观测」(Langfuse) 入口——治理下拉内
- [ ] 设计批准后 → 加载 `plan` skill 输出实施任务清单
- [ ] 实施 → `frontend-development` skill Phase 1-3
