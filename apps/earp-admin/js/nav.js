/* EARP Admin — shared navigation shell (一级菜单 + 左侧抽屉)
 *
 * Design: arch/design/2026-08-11-admin-navigation-redesign.md
 *
 * Pages declare their context on <body>:
 *   data-base     path prefix back to the repo root ("." for index.html, ".." for pages/)
 *   data-section  active top-level menu id (home|workspace|knowledge|capability|apps|plugins|governance|monitor)
 *   data-sub      active drawer item id (see DRAWERS below; planned.html passes ?section=&item= instead)
 *   data-nav      "none" → minimal header (brand + meta only, no menu/drawer, e.g. login.html)
 *
 * The header content and the left drawer are rendered at DOMContentLoaded, so a
 * page only needs <header></header> + <main>…</main>; the drawer element and the
 * .app-shell wrapper are created here. Every href is built from data-base so the
 * app works under file://, /admin/ and any static origin.
 */
(function () {
  'use strict';

  // ── Top-level menu (一级菜单) ──
  var SECTIONS = [
    { id: 'home',        label: '首页',     path: '{b}/index.html' },
    { id: 'workspace',   label: '工作台',   path: '{b}/pages/planned.html?section=workspace' },
    { id: 'knowledge',   label: '知识中心', path: '{b}/pages/knowledge.html' },
    { id: 'capability',  label: '能力中心', path: '{b}/pages/capabilities.html' },
    { id: 'apps',        label: '应用中心', path: '{b}/pages/planned.html?section=apps' },
    { id: 'plugins',     label: '插件中心', path: '{b}/pages/planned.html?section=plugins' },
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
      { label: 'workflow', sub: 'workflow', planned: 'workspace/workflow' },
      { label: 'Agent', sub: 'agent', planned: 'workspace/agent' },
      { label: 'Skills', sub: 'skills', planned: 'workspace/skills' },
    ],
    knowledge: [
      { label: '数据域', sub: 'data-domains', path: '{b}/pages/data-domains.html' },
      { label: '知识库', sub: 'knowledge', path: '{b}/pages/knowledge.html' },
      { label: '实体管理', sub: 'entities', path: '{b}/pages/entities.html' },
      { label: '实体导入', sub: 'entity-import', path: '{b}/pages/entity-import.html' },
      { label: '图谱探索', sub: 'entity-graph', path: '{b}/pages/entity-graph.html' },
      { label: '召回测试', sub: 'test-retrieval', path: '{b}/pages/test-retrieval.html' },
    ],
    capability: [
      { label: '能力注册', sub: 'capabilities', path: '{b}/pages/capabilities.html' },
      { label: '推理测试', sub: 'plan', path: '{b}/pages/plan.html' },
      { label: '流式推理', sub: 'stream', path: '{b}/pages/stream.html' },
      { label: '连接器', sub: 'connector', planned: 'capability/connector' },
      { label: '模型配置', sub: 'models', path: '{b}/pages/models.html' },
    ],
    apps: [
      { label: '概览', sub: 'overview', path: '{b}/pages/apps.html' },
      { label: '我的应用', sub: 'mine', planned: 'apps/mine' },
    ],
    plugins: [
      { label: '插件管理', sub: 'manage', planned: 'plugins/manage' },
    ],
    governance: [
      { label: 'Audit', sub: 'audit', path: '{b}/pages/audit.html' },
      { label: 'Roles', sub: 'roles', planned: 'governance/roles' },
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
    'apps/mine': {
      label: '我的应用', section: 'apps', phase: '第三期', priority: '三期',
      desc: 'user 端「我的应用」使用流程（earp-user 侧），随 user 端迭代。',
      related: [],
    },
    'plugins/manage': {
      label: '插件管理', section: 'plugins', phase: '规划中', priority: '—',
      desc: '插件生命周期管理（安装 / 启停 / 版本），随 roadmap 点亮。',
      related: [],
    },
    'governance/roles': {
      label: 'Roles', section: 'governance', phase: '规划中', priority: 'P8',
      desc: '角色与权限管理页（tech-debt #9：roles 页开放配置 + Admin 全权限通用机制）。',
      related: [['Audit', '{b}/pages/audit.html']],
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

  function renderTopNav(base, sectionId) {
    var items = SECTIONS.map(function (s) {
      var active = s.id === sectionId ? ' class="active" aria-current="page"' : '';
      return '<a href="' + href(base, s.path) + '" data-nav-section="' + s.id + '"' + active + '>'
        + icon(s.id) + '<span>' + esc(s.label) + '</span></a>';
    }).join('');
    return '<nav>' + items + '</nav>';
  }

  function renderMeta(base) {
    return '<div class="meta">tenant-demo · <a href="' + href(base, '{b}/pages/login.html') + '">Admin</a></div>';
  }

  function renderDrawer(base, sectionId, subId) {
    var items = DRAWERS[sectionId] || [];
    if (!items.length) return '';
    var html = items.map(function (it) {
      var isActive = it.sub === subId;
      var cls = 'drawer-item' + (isActive ? ' active' : '');
      var aria = isActive ? ' aria-current="page"' : '';
      if (it.planned) {
        return '<a class="' + cls + '" href="' + href(base, '{b}/pages/planned.html?section=' + sectionId + '&item=' + it.sub) + '"' + aria + '>'
          + '<span>' + esc(it.label) + '</span><span class="planned-tag">规划中</span></a>';
      }
      return '<a class="' + cls + '" href="' + href(base, it.path) + '"' + aria + '><span>' + esc(it.label) + '</span></a>';
    }).join('');
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
    // planned.html passes ?section=&item= in the URL; regular pages declare on <body>
    var sectionId = q.get('section') || body.dataset.section || '';
    var subId = q.get('item') || body.dataset.sub || '';

    var header = document.querySelector('header');
    if (header) {
      header.innerHTML = renderBrand(base)
        + (navMode === 'none' ? '' : renderTopNav(base, sectionId))
        + renderMeta(base);
    }
    if (navMode === 'none') return;

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
    if (drawerEl) drawerEl.innerHTML = renderDrawer(base, sectionId, subId);
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
