/* EARP Admin — shared navigation shell (一级菜单 + 左侧抽屉)
 *
 * Design: arch/design/2026-08-11-admin-navigation-redesign.md
 *
 * Pages declare their context on <body>:
 *   data-base     path prefix back to the repo root ("." for index.html, ".." for pages/)
 *   data-section  active top-level menu id (home|workspace|knowledge|ecmc|capability|apps|governance|monitor)
 *   data-sub      active drawer item id (see DRAWERS below; planned.html passes ?section=&item= instead)
 *   data-nav      "none" → minimal header (brand + meta only, no menu/drawer, e.g. login.html)
 *                 "editor" → brand + top menu + meta, no drawer (fullscreen editor, e.g. ecmc-causal-edit.html)
 *
 * The header content and the left drawer are rendered at DOMContentLoaded, so a
 * page only needs <header></header> + <main>…</main>; the drawer element and the
 * .app-shell wrapper are created here. Every href is built from data-base so the
 * app works under file://, /admin/ and any static origin.
 */
(function () {
  'use strict';

  // ── Top-level menu (一级菜单) ──
  // FE-ECMC-2026-0830 §2.1: 首页｜工作台｜知识中心｜认知模型｜能力中心｜应用中心｜治理中心｜运行监控
  // 插件中心已合并入能力中心（规划中），避免 1280px 视口下导航拥挤；归属以导航专项评审为准。
  var SECTIONS = [
    { id: 'home',        label: '首页',     path: '{b}/index.html' },
    { id: 'workspace',   label: '工作台',   path: '{b}/pages/planned.html?section=workspace' },
    { id: 'knowledge',   label: '知识中心', path: '{b}/pages/knowledge.html' },
    { id: 'ecmc',        label: '认知模型', path: '{b}/pages/ecmc.html' },
    { id: 'capability',  label: '能力中心', path: '{b}/pages/capabilities.html' },
    { id: 'apps',        label: '应用中心', path: '{b}/pages/planned.html?section=apps' },
    { id: 'governance',  label: '治理中心', path: '{b}/pages/audit.html' },
    { id: 'monitor',     label: '运行监控', path: '{b}/pages/sessions.html' },
  ];

  // ── Left drawer (左抽屉), order = menu order ──
  // planned: roadmap key (see PLANNED below) → 弱化「规划中」，点击进占位页
  var DRAWERS = {
    home: [
      { label: '概览', sub: 'home', path: '{b}/index.html' },
      { label: '知识资产看板', sub: 'kboard', planned: 'home/kboard' },
    ],
    workspace: [
      { label: 'chat', sub: 'chat', path: '{b}/pages/chat.html' },
      { label: 'chatflow', sub: 'chatflow', path: '{b}/pages/chatflow.html' },
      { label: 'workflow', sub: 'workflow', planned: 'workspace/workflow' },
      { label: 'Agent', sub: 'agent', planned: 'workspace/agent' },
      { label: 'Skills', sub: 'skills', planned: 'workspace/skills' },
    ],
    knowledge: [
      { label: '数据域', sub: 'data-domains', path: '{b}/pages/data-domains.html', group: '文档知识' },
      { label: '知识库', sub: 'knowledge', path: '{b}/pages/knowledge.html', group: '文档知识' },
      { label: '本体管理', sub: 'tbox', path: '{b}/pages/tbox.html', group: '结构化知识' },
      { label: '实体管理', sub: 'entities', path: '{b}/pages/entities.html', group: '结构化知识' },
      { label: '实体导入', sub: 'entity-import', path: '{b}/pages/entity-import.html', group: '结构化知识' },
      { label: '中台对接', sub: 'data-source', path: '{b}/pages/data-source.html', group: '结构化知识' },
      { label: '图谱探索', sub: 'entity-graph', path: '{b}/pages/entity-graph.html', group: '探索验证' },
      { label: '召回测试', sub: 'test-retrieval', path: '{b}/pages/test-retrieval.html', group: '探索验证' },
      { label: 'QU 调试', sub: 'understanding-debug', path: '{b}/pages/understanding-debug.html', group: '探索验证' },
      { label: '评估管理', sub: 'eval-sets', path: '{b}/pages/eval-sets.html', group: '探索验证' },
    ],
    capability: [
      { label: '能力注册', sub: 'capabilities', path: '{b}/pages/capabilities.html' },
      { label: '推理测试', sub: 'plan', path: '{b}/pages/plan.html' },
      { label: '流式推理', sub: 'stream', path: '{b}/pages/stream.html' },
      { label: '连接器', sub: 'connector', planned: 'capability/connector' },
      { label: '插件管理', sub: 'plugins-manage', planned: 'capability/plugins-manage' },
      { label: '模型配置', sub: 'models', path: '{b}/pages/models.html' },
    ],
    // FE-ECMC-2026-0830 §4.1 — ECMC 左侧二级导航；编辑器页折叠抽屉（data-nav="editor"）
    ecmc: [
      { label: '概览', sub: 'ecmc', path: '{b}/pages/ecmc.html' },
      { label: '全部模型', sub: 'ecmc-models', path: '{b}/pages/ecmc-models.html', group: '模型资产' },
      { label: '因果模型', sub: 'ecmc-models-causal', path: '{b}/pages/ecmc-models.html?type=causal&sub=ecmc-models-causal', group: '模型资产' },
      { label: '决策模型', sub: 'ecmc-decision', planned: 'ecmc/decision-models', group: '模型资产' },
      { label: '任务模型', sub: 'ecmc-task', planned: 'ecmc/task-models', group: '模型资产' },
      { label: '待审核', sub: 'ecmc-reviews-mine', path: '{b}/pages/ecmc-reviews.html?filter=mine&sub=ecmc-reviews-mine', group: '审核发布' },
      { label: '发布记录', sub: 'ecmc-reviews-published', path: '{b}/pages/ecmc-reviews.html?filter=published&sub=ecmc-reviews-published', group: '审核发布' },
      { label: '驳回记录', sub: 'ecmc-reviews-rejected', path: '{b}/pages/ecmc-reviews.html?filter=rejected&sub=ecmc-reviews-rejected', group: '审核发布' },
      { label: '最新编译状态', sub: 'ecmc-compiles', path: '{b}/pages/ecmc-compiles.html', group: '编译与激活' },
      { label: 'Candidate Artifacts', sub: 'ecmc-artifacts', path: '{b}/pages/ecmc-compiles.html?view=artifacts&sub=ecmc-artifacts', group: '编译与激活' },
      { label: 'Active Versions', sub: 'ecmc-active', path: '{b}/pages/ecmc-compiles.html?view=active&sub=ecmc-active', group: '编译与激活' },
      { label: '模型依赖', sub: 'ecmc-dependencies', planned: 'ecmc/model-dependencies', group: '后续' },
      { label: '目录扩展申请', sub: 'ecmc-catalog-requests', path: '{b}/pages/ecmc-catalog-requests.html' },
    ],
    apps: [
      { label: '智能体', sub: 'overview', path: '{b}/pages/apps.html' },
      { label: '我的应用', sub: 'mine', path: '{b}/pages/my-apps.html' },
    ],
    governance: [
      { label: 'Audit', sub: 'audit', path: '{b}/pages/audit.html' },
      { label: 'Roles', sub: 'roles', path: '{b}/pages/roles.html' },
      { label: '应用分类', sub: 'app-categories', path: '{b}/pages/app-categories.html' },
      { label: '应用权限', sub: 'app-access', path: '{b}/pages/app-access.html' },
      { label: 'Org', sub: 'org', planned: 'governance/org' },
      { label: 'Tenants', sub: 'tenants', planned: 'governance/tenants' },
      { label: 'Policy', sub: 'policy', planned: 'governance/policy' },
    ],
    monitor: [
      { label: 'Sessions 执行', sub: 'sessions', path: '{b}/pages/sessions.html' },
      { label: '对话日志', sub: 'conversations', path: '{b}/pages/conversations.html' },
    ],
  };

  // ── 规划中 roadmap（占位页数据；不假装有功能）──
  var PLANNED = {
    'home/kboard': {
      label: '知识资产看板', section: 'home', phase: '二期', priority: '—',
      desc: '知识资产总览看板（KB / 数据域 / 文档 / 引用统计），需要新增首页聚合接口。',
      related: [['知识库', '{b}/pages/knowledge.html'], ['数据域', '{b}/pages/data-domains.html']],
    },
    'workspace/workflow': {
      label: 'workflow', section: 'workspace', phase: '第三期', priority: '三期',
      desc: 'workflow 配置 UI。可视化对话编排（chatflow）为未来立项，本轮不做。',
      related: [],
    },
    'workspace/agent': {
      label: 'Agent', section: 'workspace', phase: '第三期', priority: '三期',
      desc: 'Agent 配置与管理界面，随 roadmap 逐一点亮。',
      related: [],
    },
    'workspace/skills': {
      label: 'Skills', section: 'workspace', phase: '第三期', priority: '三期',
      desc: 'Skills（技能）管理界面，随 roadmap 逐一点亮。',
      related: [],
    },
    'capability/connector': {
      label: '连接器', section: 'capability', phase: '第三期', priority: '三期',
      desc: '连接器配置页。连接器（MCP / REST / DB 三类）是 capability 的执行后端，归能力中心（架构一致、配置闭环）；首期实现 MCP，REST/DB 占位。',
      related: [['能力注册', '{b}/pages/capabilities.html'], ['模型配置', '{b}/pages/models.html']],
    },
    'capability/plugins-manage': {
      label: '插件管理', section: 'capability', phase: '规划中', priority: '—',
      desc: '插件生命周期管理（安装 / 启停 / 版本）。按 FE-ECMC-2026-0830 §2.1 插件中心并入能力中心，归属以导航专项评审为准。',
      related: [['能力注册', '{b}/pages/capabilities.html']],
    },
    'ecmc/decision-models': {
      label: '决策模型', section: 'ecmc', phase: '规划中', priority: '—',
      desc: '决策模型编辑器（N01B 范围外）。决策模型 API/元模型尚未冻结，不得复用因果模型 API 伪造功能。',
      related: [['认知模型概览', '{b}/pages/ecmc.html'], ['因果模型', '{b}/pages/ecmc-models.html?type=causal']],
    },
    'ecmc/task-models': {
      label: '任务模型', section: 'ecmc', phase: '规划中', priority: '—',
      desc: '任务模型编辑器（N01B 范围外）。任务模型 API/元模型尚未冻结，仅保留导航占位。',
      related: [['认知模型概览', '{b}/pages/ecmc.html']],
    },
    'ecmc/model-dependencies': {
      label: '模型依赖', section: 'ecmc', phase: '后续', priority: '—',
      desc: '跨模型引用必须固定到已发布 Version/Snapshot；决策/任务模型合同冻结前仅保留设计，不进入 N01B 实施。',
      related: [['认知模型概览', '{b}/pages/ecmc.html']],
    },
    'governance/org': {
      label: 'Org', section: 'governance', phase: '规划中', priority: '—',
      desc: '组织单元管理。',
      related: [],
    },
    'governance/tenants': {
      label: 'Tenants', section: 'governance', phase: '规划中', priority: '—',
      desc: '租户管理。',
      related: [],
    },
    'governance/policy': {
      label: 'Policy', section: 'governance', phase: '规划中', priority: '—',
      desc: '策略中心（RBAC 权限策略）。',
      related: [],
    },
  };

  var ICONS = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
    workspace: '<path d="M12 3l8 4.5-8 4.5-8-4.5L12 3z"/><path d="M4 12l8 4.5 8-4.5"/><path d="M4 16.5 12 21l8-4.5"/>',
    knowledge: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    capability: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    apps: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    plugins: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    governance: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    monitor: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  };

  function icon(id) {
    var p = ICONS[id];
    return p
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + p + '</svg>'
      : '';
  }

  function href(base, path) { return path.replace(/\{b\}/g, base); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function renderBrand(base) {
    return '<span class="brand"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg><a href="' + href(base, '{b}/index.html') + '" style="color:inherit;text-decoration:none">EARP</a></span>';
  }

  function renderTopNav(base, sectionId, ecmcFake) {
    var items = SECTIONS.map(function (s) {
      var active = s.id === sectionId ? ' class="active" aria-current="page"' : '';
      var p = href(base, s.path);
      // test-only Catalog 模式：ECMC 顶栏入口透传 catalog=fake（§9.3）
      if (ecmcFake && s.id === 'ecmc') p = appendFake(p, true);
      return '<a href="' + p + '" data-nav-section="' + s.id + '"' + active + '>'
        + icon(s.id) + '<span>' + esc(s.label) + '</span></a>';
    }).join('');
    return '<nav>' + items + '</nav>';
  }

  // 透传 test-only Catalog 参数，避免重复
  function appendFake(href, fake) {
    if (!fake) return href;
    if (/[?&]catalog=fake(?:&|$)/.test(href)) return href;
    return href + (href.indexOf('?') === -1 ? '?' : '&') + 'catalog=fake';
  }

  function jwtMeta() {
    // JWT payload 解码兜底（token 有 tenant_id/sub/role_id；login 存的明文优先）
    try {
      var token = localStorage.getItem('earp_token');
      if (!token) return null;
      var payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      return { tenant: payload.tenant_id || '', user: payload.sub || '', role: payload.role_id || '' };
    } catch (e) { return null; }
  }

  function renderMeta(base) {
    var tenant = localStorage.getItem('earp_tenant_id') || '';
    var user = localStorage.getItem('earp_user_id') || '';
    var role = localStorage.getItem('earp_role_id') || '';
    if (!tenant || !user) {
      var jm = jwtMeta();
      if (jm) { tenant = jm.tenant; user = jm.user; role = jm.role || role; }
    }
    var label = (tenant && user)
      ? (esc(tenant) + ' · ' + esc(user) + (role ? ' · ' + esc(role) : ''))
      : '未登录';
    return '<div class="meta">' + label + ' · <a href="' + href(base, '{b}/pages/login.html') + '">' + (tenant ? '切换' : '登录') + '</a></div>';
  }

  function renderDrawer(base, sectionId, subId, ecmcFake) {
    var items = DRAWERS[sectionId] || [];
    if (!items.length) return '';
    var html = '';
    var lastGroup = null;
    items.forEach(function (it) {
      // 分组标题：group 变化时插入（其它 section 无 group → 保持平铺）
      if (it.group && it.group !== lastGroup) {
        html += '<div class="drawer-group-title">' + esc(it.group) + '</div>';
      }
      lastGroup = it.group || lastGroup;
      var isActive = it.sub === subId;
      var cls = 'drawer-item' + (isActive ? ' active' : '');
      var aria = isActive ? ' aria-current="page"' : '';
      if (it.planned) {
        var plannedHref = href(base, '{b}/pages/planned.html?section=' + sectionId + '&item=' + it.sub);
        // test-only Catalog 模式：ECMC 抽屉导航透传 catalog=fake（§9.3）
        if (ecmcFake) plannedHref = appendFake(plannedHref, true);
        html += '<a class="' + cls + '" href="' + plannedHref + '"' + aria + '>'
          + '<span>' + esc(it.label) + '</span><span class="planned-tag">规划中</span></a>';
        return;
      }
      var p = href(base, it.path);
      if (ecmcFake) p = appendFake(p, true);
      html += '<a class="' + cls + '" href="' + p + '"' + aria + '><span>' + esc(it.label) + '</span></a>';
    });
    var section = SECTIONS.filter(function (s) { return s.id === sectionId; })[0];
    return '<div class="drawer-section-title">' + esc(section ? section.label : '') + '</div>' + html;
  }

  // ── Boot ──
  function boot() {
    var body = document.body;
    if (!body) return;
    var base = body.dataset.base || '.';
    var navMode = body.dataset.nav || 'full';
    var q = new URLSearchParams(location.search);
    // planned.html passes ?section=&item= in the URL; regular pages declare on <body>;
    // ecmc pages may pass ?sub= to select a drawer item that differs from body.dataset.sub
    var sectionId = q.get('section') || body.dataset.section || '';
    var subId = q.get('item') || q.get('sub') || body.dataset.sub || '';

    var header = document.querySelector('header');
    if (header) {
      // test-only Catalog 模式：ECMC 内部导航透传（仅当前为 ECMC 页面且 URL 显式带参时）
      var ecmcFake = q.get('catalog') === 'fake' && sectionId === 'ecmc';
      header.innerHTML = renderBrand(base)
        + (navMode === 'none' ? '' : renderTopNav(base, sectionId, ecmcFake))
        + renderMeta(base);
    }
    if (navMode === 'none') return;

    if (navMode === 'editor') {
      // Fullscreen editor (FE-ECMC-2026-0830 §5.2): keep the top nav, skip the drawer
      body.classList.add('ecmc-editor-page');
      return;
    }

    var main = document.querySelector('main');
    if (!main) return;

    var shell = main.closest('.app-shell');
    if (!shell) {
      shell = document.createElement('div');
      shell.className = 'app-shell';
      main.parentNode.insertBefore(shell, main);
      var drawer = document.createElement('aside');
      drawer.className = 'app-drawer';
      drawer.id = 'app-drawer';
      shell.appendChild(drawer);
      shell.appendChild(main);
    }
    var drawerEl = document.getElementById('app-drawer');
    if (drawerEl) drawerEl.innerHTML = renderDrawer(base, sectionId, subId, q.get('catalog') === 'fake' && sectionId === 'ecmc');
    if (sectionId) body.classList.add('section-' + sectionId);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // Exposed for planned.html
  window.EARP_NAV = {
    SECTIONS: SECTIONS,
    DRAWERS: DRAWERS,
    PLANNED: PLANNED,
    href: href,
    esc: esc,
    icon: icon,
  };
})();
