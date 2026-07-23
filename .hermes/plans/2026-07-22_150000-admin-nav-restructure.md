# Admin Dashboard 导航架构重组 — 实施计划

> **For Hermes:** 按任务顺序执行，每任务改完验证后再继续。全静态 HTML/CSS/JS，零后端变更。

**Goal:** 将 Admin Dashboard 顶层导航从 9 项直觉分组重组为 6 个 L2 领域分组 + 治理下拉菜单。

**Architecture:** 纯静态前端变更——修改 11 个 HTML 的 `<nav>` 块、CSS 新增分组/下拉样式、JS 新增 active 路由判定。不涉及后端 API、数据库、Vue 状态管理。

**Tech Stack:** HTML + CSS (Topnav Light 设计系统) + vanilla JS

---

## 受影响文件

| 文件 | 变更类型 | 变更量 |
|:---|:---|:---|
| `apps/earp-admin/index.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/sessions.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/plan.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/stream.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/knowledge.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/data-domains.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/capabilities.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/conversations.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/audit.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/doc-config.html` | 修改 `<nav>` | ~12 行替换 |
| `apps/earp-admin/pages/login.html` | 修改 `<nav>` | ~12 行替换（简化版导航） |
| `apps/earp-admin/css/admin.css` | 新增样式 | ~40 行新增 |
| `apps/earp-admin/js/app.js` | 新增函数 | ~20 行新增 |

---

### Task 1: CSS — 导航分组和下拉样式

**Objective:** 在 `admin.css` 末尾新增 `.nav-group`、`.nav-dropdown`、`.dropdown-menu`、`.disabled` 样式规则。

**Files:**
- Modify: `apps/earp-admin/css/admin.css` (末尾追加)

**Step 1: 追加 CSS 代码**

在 `admin.css` 文件末尾追加以下代码块：

```css
/* ── Navigation Groups (L2 domain-based) ── */
.nav-group {
  position: relative;
  display: flex;
  align-items: center;
}
.nav-group > a {
  font-size: 0.81rem; font-weight: 500; color: var(--text-tertiary);
  text-decoration: none; padding: 1rem 0; border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s; white-space: nowrap;
}
.nav-group > a:hover { color: var(--text-primary); }
.nav-group > a.active,
.nav-group > a[aria-current] {
  color: var(--text-primary); border-bottom-color: var(--accent);
}

/* ── Dropdown ── */
.nav-dropdown > a::after {
  content: ' ▾';
  font-size: 0.65rem;
  vertical-align: middle;
}
.dropdown-menu {
  display: none;
  position: absolute; top: 100%; left: 0;
  background: var(--bg-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-elevated);
  min-width: 200px; padding: 0.35rem 0;
  z-index: 20;
}
.nav-dropdown:hover .dropdown-menu,
.nav-dropdown:focus-within .dropdown-menu {
  display: block;
}
.dropdown-menu a {
  display: block; padding: 0.45rem 0.9rem;
  font-size: 0.81rem; color: var(--text-secondary);
  text-decoration: none; white-space: nowrap;
  transition: background 0.1s;
}
.dropdown-menu a:hover { background: var(--bg-surface); color: var(--text-primary); }
.dropdown-menu a.active { color: var(--accent); font-weight: 500; }
.dropdown-menu a.disabled {
  color: var(--text-quaternary); cursor: not-allowed; pointer-events: none;
}
```

**Step 2: 验证 CSS 语法**

```bash
# 无实际 lint 工具，人工检查：打开 index.html 在浏览器 DevTools 确认无 CSS 语法错误
open apps/earp-admin/index.html
```

---

### Task 2: JS — setActiveNav() 路由判定

**Objective:** 在 `app.js` 末尾新增 `setActiveNav()` 函数，根据当前页面路径自动高亮对应导航组。

**Files:**
- Modify: `apps/earp-admin/js/app.js` (末尾追加)

**Step 1: 追加 JS 代码**

在 `app.js` 末尾追加：

```js
// ── Navigation active state ──
EARP.setActiveNav = function() {
  const path = location.pathname;
  const nav = document.querySelector('header nav');
  if (!nav) return;
  const links = nav.querySelectorAll('a[data-nav]');
  links.forEach(a => {
    const group = a.getAttribute('data-nav');
    if (!group) return;
    const active = path.includes('/' + group);
    if (active) a.classList.add('active');
  });
};
document.addEventListener('DOMContentLoaded', function() {
  EARP.setActiveNav();
});
```

**Step 2: 验证** — 打开任意页面，确认当前页面对应的导航组高亮。

---

### Task 3: index.html — Dashboard 首页导航

**Objective:** 替换 `index.html` 的 `<nav>` 为 L2 分组结构。

**Files:**
- Modify: `apps/earp-admin/index.html:18-31`

**Step 1: 定位当前 `<nav>` 块**

行 18-31：
```html
    <nav>
    <a href="index.html" class="active" aria-current="page">Overview</a>
    <span class="nav-divider"></span>
    <a href="pages/sessions.html">Sessions</a>
    <a href="pages/plan.html">Plan &amp; Invoke</a>
    <a href="pages/stream.html">Streaming</a>
    <span class="nav-divider"></span>
    <a href="pages/knowledge.html">Knowledge</a>
    <a href="pages/data-domains.html">Data Domains</a>
    <span class="nav-divider"></span>
    <a href="pages/capabilities.html">Capabilities</a>
    <a href="pages/conversations.html">Conversations</a>
    <a href="pages/audit.html">Audit</a>
  </nav>
```

**Step 2: 替换为**

```html
    <nav>
    <a href="index.html" class="active" aria-current="page">Overview</a>
    <div class="nav-group"><a href="pages/sessions.html" data-nav="sessions">运行时</a></div>
    <div class="nav-group"><a href="pages/plan.html" data-nav="plan">推理</a></div>
    <div class="nav-group"><a href="pages/capabilities.html" data-nav="capabilities">能力</a></div>
    <div class="nav-group"><a href="pages/knowledge.html" data-nav="knowledge">知识</a></div>
    <div class="nav-group"><a href="pages/conversations.html" data-nav="conversations">对话</a></div>
    <div class="nav-group nav-dropdown">
      <a href="pages/audit.html">治理</a>
      <div class="dropdown-menu">
        <a href="pages/audit.html" data-nav="audit">Audit Logs</a>
        <a href="pages/roles.html" class="disabled">Roles &amp; Permissions</a>
        <a href="pages/tenants.html" class="disabled">Tenant Management</a>
        <a href="pages/policy.html" class="disabled">Policy Center</a>
        <a href="pages/observability.html" class="disabled">Observability</a>
      </div>
    </div>
  </nav>
```

**Step 3: 验证** — 浏览器打开 `apps/earp-admin/index.html`，确认导航显示为 6 组 + 治理下拉（hover 展开）。

---

### Task 4: sessions.html + plan.html + stream.html — 运行时域 + 推理域

**Objective:** 对齐 Sessions/Plan/Stream 三个运行时和推理域页面的导航。

**Files:**
- Modify: `apps/earp-admin/pages/sessions.html`
- Modify: `apps/earp-admin/pages/plan.html`
- Modify: `apps/earp-admin/pages/stream.html`

**Step 1: sessions.html** — 当前 nav 中有 `class="active"` 在 `<a href="sessions.html">`，替换 `<nav>` 为统一结构，active 放 `<a href="sessions.html" data-nav="sessions" class="active">`。

查找 `<nav>` 中 sessions.html 的链接并更新：

sessions.html 的 `<nav>` 替换为：
```html
    <nav>
    <a href="../index.html">Overview</a>
    <div class="nav-group"><a href="sessions.html" data-nav="sessions" class="active" aria-current="page">运行时</a></div>
    <div class="nav-group"><a href="plan.html" data-nav="plan">推理</a></div>
    <div class="nav-group"><a href="capabilities.html" data-nav="capabilities">能力</a></div>
    <div class="nav-group"><a href="knowledge.html" data-nav="knowledge">知识</a></div>
    <div class="nav-group"><a href="conversations.html" data-nav="conversations">对话</a></div>
    <div class="nav-group nav-dropdown">
      <a href="audit.html">治理</a>
      <div class="dropdown-menu">
        <a href="audit.html" data-nav="audit">Audit Logs</a>
        <a href="roles.html" class="disabled">Roles &amp; Permissions</a>
        <a href="tenants.html" class="disabled">Tenant Management</a>
        <a href="policy.html" class="disabled">Policy Center</a>
        <a href="observability.html" class="disabled">Observability</a>
      </div>
    </div>
  </nav>
```

**Step 2: plan.html** — 同样替换，active 放在 `<a href="plan.html" data-nav="plan" class="active">`。

**Step 3: stream.html** — active 放在 `<a href="stream.html" data-nav="stream">`。但 stream 与 plan 同属推理域，`data-nav` 应为 `plan`（因为路由匹配 `/plan`），或者让 JS 同时匹配 plan 和 stream：

更新 `setActiveNav()` 逻辑：stream 页面路径包含 `/stream`，也要高亮「推理」组。追加特殊处理：

```js
if (path.includes('/stream')) {
  const reasoning = nav.querySelector('a[data-nav="plan"]');
  if (reasoning) reasoning.classList.add('active');
}
```

stream.html 的 nav 中推理链接 `data-nav="plan"`，不设 active class（由 JS 自动设置）。

---

### Task 5: knowledge.html + data-domains.html + doc-config.html — 知识域

**Objective:** 对齐 Knowledge Base、Data Domains、Doc Config 三个知识域页面的导航。

**Files:**
- Modify: `apps/earp-admin/pages/knowledge.html`
- Modify: `apps/earp-admin/pages/data-domains.html`
- Modify: `apps/earp-admin/pages/doc-config.html`

**Step 1: knowledge.html** — active 放在 `<a href="knowledge.html" data-nav="knowledge" class="active">`

**Step 2: data-domains.html** — active 放在 `<a href="data-domains.html" data-nav="data-domains">`，JS 匹配包含 `/data-domains` 时高亮知识组。

更新 `setActiveNav()`：
```js
if (path.includes('/data-domains') || path.includes('/doc-config')) {
  const knowledge = nav.querySelector('a[data-nav="knowledge"]');
  if (knowledge) knowledge.classList.add('active');
}
```

**Step 3: doc-config.html** — 与 data-domains.html 相同处理。doc-config 的 breadcrumb `&larr; Back to Knowledge Base` 保持不变。

---

### Task 6: capabilities.html + conversations.html — 能力域 + 对话域

**Objective:** 对齐 Capabilities 和 Conversations 两个独立域页面。

**Files:**
- Modify: `apps/earp-admin/pages/capabilities.html`
- Modify: `apps/earp-admin/pages/conversations.html`

**Step 1: capabilities.html** — active 放在 `<a href="capabilities.html" data-nav="capabilities" class="active" aria-current="page">`

**Step 2: conversations.html** — `<nav>` 替换同上，active 放 `<a href="conversations.html" data-nav="conversations" class="active">`

---

### Task 7: audit.html — 治理域

**Objective:** Audit Logs 页面的导航，治理下拉中 Active 项高亮。

**Files:**
- Modify: `apps/earp-admin/pages/audit.html`

**Step 1:** `<nav>` 替换为统一结构。治理组内 `<a href="audit.html" data-nav="audit" class="active">` 高亮。

---

### Task 8: login.html — 登录页简化导航

**Objective:** 登录页不需要完整导航，只保留 Overview + 治理下拉（可访问 Audit）。

**Files:**
- Modify: `apps/earp-admin/pages/login.html`

**Step 1:** 替换 `<nav>` 为简化版：

```html
    <nav>
    <a href="../index.html">Overview</a>
    <div class="nav-group nav-dropdown">
      <a href="audit.html">治理</a>
      <div class="dropdown-menu">
        <a href="audit.html">Audit Logs</a>
        <a href="roles.html" class="disabled">Roles &amp; Permissions</a>
        <a href="tenants.html" class="disabled">Tenant Management</a>
        <a href="policy.html" class="disabled">Policy Center</a>
        <a href="observability.html" class="disabled">Observability</a>
      </div>
    </div>
  </nav>
```

---

### Task 9: 最终验证

**Objective:** 逐页打开确认导航正确、无 JS 错误、hover 下拉正常。

**Step 1: 逐页验证**

```bash
# 在浏览器中逐个打开确认：
open apps/earp-admin/index.html
open apps/earp-admin/pages/sessions.html
open apps/earp-admin/pages/plan.html
open apps/earp-admin/pages/stream.html
open apps/earp-admin/pages/knowledge.html
open apps/earp-admin/pages/data-domains.html
open apps/earp-admin/pages/doc-config.html
open apps/earp-admin/pages/capabilities.html
open apps/earp-admin/pages/conversations.html
open apps/earp-admin/pages/audit.html
open apps/earp-admin/pages/login.html
```

**验证清单：**
- [ ] 每个页面导航显示 6 组 + 治理下拉
- [ ] 治理下拉 hover 展开 5 项（1 active + 4 disabled）
- [ ] 当前页面所在组高亮（accent underline）
- [ ] 知识域下 data-domains 和 doc-config 高亮「知识」组
- [ ] 推理域下 stream 高亮「推理」组
- [ ] 运行时域下 sessions 高亮「运行时」组
- [ ] 治理域下 audit 在下拉中高亮
- [ ] login 页显示简化导航
- [ ] 浏览器 Console 无 JS 错误
- [ ] 所有 disabled 项不可点击（灰色 + cursor: not-allowed）

**Step 2: 检查 CSS**

DevTools → Elements → 确认 `.nav-group`、`.nav-dropdown`、`.dropdown-menu` 样式生效。

---

## 最终 setActiveNav() 完整代码

```js
// ── Navigation active state ──
EARP.setActiveNav = function() {
  const path = location.pathname;
  const nav = document.querySelector('header nav');
  if (!nav) return;
  // Top-level group links
  const groups = nav.querySelectorAll('.nav-group > a[data-nav]');
  groups.forEach(a => {
    const group = a.getAttribute('data-nav');
    const active = path.includes('/' + group);
    if (active) a.classList.add('active');
  });
  // Special: stream → 推理
  if (path.includes('/stream')) {
    const reasoning = nav.querySelector('.nav-group > a[data-nav="plan"]');
    if (reasoning) reasoning.classList.add('active');
  }
  // Special: data-domains / doc-config → 知识
  if (path.includes('/data-domains') || path.includes('/doc-config')) {
    const knowledge = nav.querySelector('.nav-group > a[data-nav="knowledge"]');
    if (knowledge) knowledge.classList.add('active');
  }
  // Dropdown items
  const dropdownItems = nav.querySelectorAll('.dropdown-menu a[data-nav]');
  dropdownItems.forEach(a => {
    const group = a.getAttribute('data-nav');
    if (path.includes('/' + group)) a.classList.add('active');
  });
};
document.addEventListener('DOMContentLoaded', function() {
  EARP.setActiveNav();
});
```

---

## 风险与缓解

| 风险 | 缓解 |
|:---|:---|
| 11 页 `<nav>` 手工替换可能遗漏或复制错误 | 逐页打开浏览器验证（Task 9） |
| `data-nav` 属性命名与路径不匹配 | 统一约定：data-nav 值与路径中最有区分度的段一致 |
| CSS `.nav-group > a` 与现有 `header nav a` 选择器冲突 | 用更高优先级的选择器 + 保留旧规则作为 fallback |
| login 简化导航后用户无法访问其他管理页 | 登录后跳转到 index.html，导航恢复正常；login 页仅作认证入口 |

## 注意事项

- 不修改任何页面主体内容（`<main>` 内的部分）
- 不修改 `doc-config.html` 的 breadcrumb
- 不修改 User App (`apps/earp-user/`) 的任何文件
- 不修改后端代码
- 所有 `class="disabled"` 页面尚无对应 HTML 文件，Phase 2+ 创建后去掉 disabled 类即可
