/* Minimal DOM stub to smoke-test nav.js rendering (no browser needed). */
const fs = require('fs');
const path = require('path');

function makeEl(tag) {
  return {
    tagName: tag,
    children: [],
    className: '',
    id: '',
    innerHTML: '',
    _text: '',
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    insertBefore(c, ref) {
      const i = this.children.indexOf(ref);
      if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
      c.parentNode = this;
      return c;
    },
    closest(sel) {
      let p = this.parentNode;
      while (p) { if (p.className === sel.slice(1)) return p; p = p.parentNode; }
      return null;
    },
    set _shell(v) { this.__shell = v; },
    get _shell() { return this.__shell; },
    querySelector(sel) { return null; },
    querySelectorAll(sel) { return []; },
  };
}

function runScenario(name, bodyAttrs, url, asserts) {
  // reset global-ish state
  global.location = { search: url, pathname: '/' + name };
  global.URLSearchParams = URLSearchParams;
  global.window = {};
  global.localStorage = {
    _s: { earp_tenant_id: 'verify-planning', earp_user_id: 'vp-user', earp_role_id: 'vp-role', earp_token: '' },
    getItem(k) { return this._s[k] != null ? this._s[k] : null; },
    setItem(k, v) { this._s[k] = v; },
  };
  global.document = {
    readyState: 'loading',
    listeners: {},
    body: Object.assign(makeEl('body'), { dataset: bodyAttrs }),
    createElement(tag) { return makeEl(tag); },
    addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    querySelector(sel) {
      if (sel === 'header') return this._header || (this._header = Object.assign(makeEl('header'), { innerHTML: '' }));
      if (sel === 'main') return this._main || (this._main = Object.assign(makeEl('main'), { innerHTML: '' }));
      return null;
    },
    getElementById(id) {
      const walk = (el) => {
        if (el.id === id) return el;
        for (const c of el.children || []) { const r = walk(c); if (r) return r; }
        return null;
      };
      return walk(this.body);
    },
  };
  // main is a child of body
  document.body.appendChild(document.querySelector('main'));
  document.body.appendChild(document.querySelector('header'));

  // load nav.js fresh
  const src = fs.readFileSync(path.join(__dirname, 'js', 'nav.js'), 'utf8');
  const prev = global.window.EARP_NAV;
  delete require.cache[require.resolve('./js/nav.js')];
  try { eval(src); } catch (e) { console.error('[' + name + '] eval FAILED:', e.message); return false; }

  // fire DOMContentLoaded
  (document.listeners['DOMContentLoaded'] || []).forEach((fn) => fn());

  const h = document.querySelector('header').innerHTML;
  const main = document.querySelector('main');
  const shell = main.closest('.app-shell');
  const drawer = shell ? shell.children[0] : null;
  if (process.env.NAV_DEBUG) console.log('[debug]', name, '\n  header:', h.slice(0, 300), '\n  shell:', !!shell);

  let ok = true;
  const fail = (msg) => { ok = false; console.error('  ✗ ' + msg); };
  asserts({ h, shell, drawer, main, nav: global.window.EARP_NAV, fail, ok: () => ok });
  console.log((ok ? '  ✓ ' : '  ✗ ') + name);
  return ok;
}

let allOk = true;

allOk = runScenario('index.html', { base: '.', section: 'home', sub: 'home' }, '', ({ h, shell, drawer, main, fail }) => {
  if (!h.includes('>首页<') || !h.includes('data-nav-section="home"')) fail('top nav missing 首页');
  if (!h.includes('>知识中心<')) fail('top nav missing 知识中心');
  if (!h.includes('class="active"')) fail('active section not marked');
  if (!shell) fail('main not wrapped in .app-shell');
  if (!drawer || drawer.className !== 'app-drawer') fail('drawer missing');
  if (!main.parentNode || main.parentNode.className !== 'app-shell') fail('main not inside shell');
  const d = drawer.innerHTML;
  if (!d.includes('概览')) fail('drawer missing 概览');
  if (d.includes('快捷入口')) fail('drawer should not contain 快捷入口');
  if (!d.includes('知识资产看板')) fail('drawer missing 知识资产看板');
  if (!d.includes('planned-tag')) fail('planned tag missing');
  if (!d.includes('class="drawer-item active"')) fail('active drawer item not marked');
  // tech-debt #9 用户信息：右上角 meta 含 tenant · user · role
  if (!h.includes('verify-planning · vp-user · vp-role')) fail('meta missing role id');
});

allOk = runScenario('knowledge.html', { base: '..', section: 'knowledge', sub: 'knowledge' }, '', ({ h, drawer, fail }) => {
  if (!h.includes('data-nav-section="knowledge"')) fail('knowledge section not active');
  ['数据域', '知识库', '召回测试'].forEach((t) => {
    if (!drawer.innerHTML.includes(t)) fail('drawer missing ' + t);
  });
  if (drawer.innerHTML.includes('分段配置')) fail('drawer should NOT contain 分段配置');
  if (!drawer.innerHTML.includes('data-domains.html')) fail('数据域 link wrong');
  if (!drawer.innerHTML.includes('test-retrieval.html')) fail('召回测试 link wrong');
  if (!drawer.innerHTML.includes('class="drawer-item active"')) fail('知识库 not active');
});

allOk = runScenario('planned.html', { base: '..', nav: 'full' }, '?section=capability&item=connector', ({ h, drawer, fail, nav }) => {
  if (!h.includes('data-nav-section="capability"')) fail('capability section not active from URL');
  if (!drawer.innerHTML.includes('连接器') || !drawer.innerHTML.includes('planned-tag')) fail('connector planned item missing');
  if (!drawer.innerHTML.includes('class="drawer-item active"')) fail('connector not active');
  if (!nav.PLANNED['capability/connector']) fail('PLANNED data missing for connector');
  if (nav.PLANNED['workspace/chat']) fail('workspace/chat should NOT be in PLANNED (implemented)');
});

allOk = runScenario('login.html', { base: '..', nav: 'none' }, '', ({ h, shell, main, fail }) => {
  if (h.includes('<nav>')) fail('login should have no nav');
  if (!h.includes('EARP')) fail('login brand missing');
  if (!h.includes('切换')) fail('login meta missing（应显示登录态/切换链接）');
  if (shell) fail('login should not wrap main in shell');
});

allOk = runScenario('stream.html', { base: '..', section: 'capability', sub: 'stream' }, '', ({ h, drawer, fail }) => {
  if (!drawer.innerHTML.includes('流式推理')) fail('drawer missing 流式推理');
  if (!drawer.innerHTML.includes('class="drawer-item active"')) fail('stream not active');
  if (!drawer.innerHTML.includes('推理测试')) fail('drawer missing 推理测试');
});

allOk = runScenario('workspace.html', { base: '..', section: 'workspace', sub: 'chat' }, '', ({ h, drawer, fail }) => {
  if (!drawer.innerHTML.includes('pages/chat.html')) fail('workspace drawer chat should link chat.html');
  if (!drawer.innerHTML.includes('workflow') || !drawer.innerHTML.includes('Agent') || !drawer.innerHTML.includes('Skills')) fail('workspace drawer missing planned items');
  const chatEl = drawer.innerHTML.match(/<a class="drawer-item[^"]*"[^>]*>\s*<span>chat<\/span>/);
  if (!chatEl || !chatEl[0].includes('active')) fail('chat drawer item not active');
  if (!drawer.innerHTML.includes('pages/chat.html')) fail('chat should NOT be planned anymore');
});

allOk = runScenario('apps.html', { base: '..', section: 'apps', sub: 'overview' }, '', ({ drawer, fail }) => {
  if (!drawer.innerHTML.includes('pages/apps.html')) fail('apps drawer 智能体 should link apps.html');
  if (!drawer.innerHTML.includes('pages/my-apps.html')) fail('apps drawer 我的应用 should link my-apps.html');
  if (drawer.innerHTML.includes('planned.html?section=apps&item=overview')) fail('智能体 should not be planned');
  if (drawer.innerHTML.includes('planned.html?section=apps&item=mine')) fail('我的应用 should not be planned anymore');
});

allOk = runScenario('monitor-audit.html', { base: '..', section: 'monitor', sub: 'audit' }, '', ({ drawer, fail }) => {
  if (!drawer.innerHTML.includes('Sessions 执行')) fail('monitor drawer missing sessions');
  if (!drawer.innerHTML.includes('对话日志')) fail('monitor drawer missing conversations');
  if (drawer.innerHTML.includes('审计')) fail('monitor drawer should NOT contain 审计');
});

// ── ECMC（FE-ECMC-2026-0830 §2.1 / §4.1）──
allOk = runScenario('ecmc.html', { base: '..', section: 'ecmc', sub: 'ecmc' }, '', ({ h, drawer, fail, nav }) => {
  if (!h.includes('data-nav-section="ecmc"')) fail('ecmc section not in top nav');
  if (!h.includes('>认知模型<')) fail('top nav missing 认知模型');
  if (h.includes('data-nav-section="plugins"')) fail('插件中心 should be merged out of top nav (FE-ECMC-2026-0830 §2.1)');
  const d = drawer.innerHTML;
  ['概览', '全部模型', '因果模型', '决策模型', '任务模型', '待审核', '发布记录', '驳回记录',
   '最新编译状态', 'Candidate Artifacts', 'Active Versions', '模型依赖', '目录扩展申请'].forEach((t) => {
    if (!d.includes(t)) fail('ECMC drawer missing ' + t);
  });
  if (!d.includes('ecmc-models.html')) fail('ECMC drawer 全部模型 link wrong');
  if (!d.includes('ecmc-models.html?type=causal')) fail('ECMC drawer 因果模型 link wrong');
  if (!d.includes('ecmc-reviews.html')) fail('ECMC drawer 审核发布 link wrong');
  if (!d.includes('ecmc-compiles.html')) fail('ECMC drawer 编译与激活 link wrong');
  if (!d.includes('ecmc-catalog-requests.html')) fail('ECMC drawer 目录申请 link wrong');
  if (!d.includes('class="drawer-item active"')) fail('ECMC 概览 not active');
  if (!d.includes('planned-tag')) fail('ECMC drawer should contain planned tags');
  if (!d.includes('planned.html?section=ecmc&item=ecmc-decision')) fail('ECMC 决策模型 planned link wrong');
  if (!d.includes('planned.html?section=ecmc&item=ecmc-task')) fail('ECMC 任务模型 planned link wrong');
  if (!d.includes('planned.html?section=ecmc&item=ecmc-dependencies')) fail('ECMC 模型依赖 planned link wrong');
  if (!nav.PLANNED['ecmc/decision-models']) fail('PLANNED data missing for decision models');
  if (!nav.PLANNED['ecmc/task-models']) fail('PLANNED data missing for task models');
  if (!nav.PLANNED['ecmc/model-dependencies']) fail('PLANNED data missing for model dependencies');
  if (!nav.PLANNED['capability/plugins-manage']) fail('PLANNED data missing for plugins-manage (merged into capability)');
});

allOk = runScenario('ecmc-models.html?type=causal', { base: '..', section: 'ecmc', sub: 'ecmc-models-causal' }, '', ({ drawer, fail }) => {
  if (!drawer.innerHTML.includes('class="drawer-item active"')) fail('因果模型 drawer item not active');
});

allOk = runScenario('ecmc-causal-edit.html', { base: '..', section: 'ecmc', nav: 'editor' }, '?model_id=cm-1&version_id=cmv-1', ({ h, shell, main, fail }) => {
  if (!h.includes('data-nav-section="ecmc"')) fail('editor should keep top nav section');
  if (shell) fail('editor should NOT wrap main in .app-shell (no drawer)');
});

allOk = runScenario('capability-plugins.html', { base: '..', section: 'capability', sub: 'plugins-manage' }, '', ({ drawer, fail }) => {
  if (!drawer.innerHTML.includes('插件管理') || !drawer.innerHTML.includes('planned-tag')) fail('插件管理 should be planned under capability');
  if (!drawer.innerHTML.includes('planned.html?section=capability&item=plugins-manage')) fail('插件管理 planned link wrong');
});

process.exit(allOk ? 0 : 1);
