/* ECMC N01B — 浏览器级 DOM 冒烟测试（无 jsdom，内置 MiniDom）
 *
 * 评审要求（第 3 轮）：
 *   1. 打开「目录扩展申请」抽屉并完成表单初始化（P0 回归：refInput/multiRefInput
 *      不再使用未定义的 esc，初始化不抛异常、提交监听注册）
 *   2. `?catalog=fake` 可打开模型向导（不是“受控目录不可用”）
 *   3. 无 Catalog adapter 时不提供自由 stable ID 输入（§9.3）
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let allOk = true;
async function check(name, fn) {
  try { await fn(); console.log('  ✓ ' + name); }
  catch (e) { allOk = false; console.error('  ✗ ' + name + ' — ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e)); }
}

/* ═══════════ MiniDom（足以支撑 drawer/dialog/picker/wizard 初始化）═══════════ */
const VOID_TAGS = new Set(['input', 'br', 'img', 'hr', 'meta', 'link']);

function parseAttrs(s) {
  const attrs = {};
  const re = /([a-zA-Z_][\w-]*)(?:="([^"]*)")?/g;
  let m;
  while ((m = re.exec(s))) attrs[m[1]] = m[2] !== undefined ? m[2] : '';
  return attrs;
}

function serializeEl(el) {
  const attrs = Object.keys(el._attrs).map((k) => k + '="' + el._attrs[k] + '"').join(' ');
  const open = '<' + el._tag + (attrs ? ' ' + attrs : '') + '>';
  if (VOID_TAGS.has(el._tag)) return open;
  return open + (el.textContent || '') + el.children.map(serializeEl).join('') + '</' + el._tag + '>';
}

function makeElement(tag, attrs) {
  const el = {
    tagName: tag.toUpperCase(),
    _tag: tag.toLowerCase(),
    children: [],
    parentNode: null,
    _listeners: {},
    style: {},
    dataset: {},
    textContent: '',
    value: '',
    checked: false,
    disabled: false,
    readOnly: false,
    className: '',
    id: '',
    selected: false,
    _attrs: {},
    classList: {
      add: (c) => { if (!el.className.split(/\s+/).includes(c)) el.className = (el.className + ' ' + c).trim(); },
      remove: (c) => { el.className = el.className.split(/\s+/).filter((x) => x && x !== c).join(' '); },
      toggle: (c) => { el.className.split(/\s+/).includes(c) ? el.classList.remove(c) : el.classList.add(c); },
      contains: (c) => el.className.split(/\s+/).includes(c),
    },
    appendChild(c) { c.parentNode = el; el.children.push(c); return c; },
    insertBefore(c, ref) { c.parentNode = el; const i = el.children.indexOf(ref); if (i < 0) el.children.push(c); else el.children.splice(i, 0, c); return c; },
    remove() { if (el.parentNode) { const i = el.parentNode.children.indexOf(el); if (i >= 0) el.parentNode.children.splice(i, 1); el.parentNode = null; } },
    closest(sel) { let p = el; while (p) { if (matches(p, sel)) return p; p = p.parentNode; } return null; },
    addEventListener(t, fn) { (el._listeners[t] = el._listeners[t] || []).push(fn); },
    removeEventListener() {},
    dispatchEvent(ev) { (el._listeners[ev.type] || []).forEach((fn) => fn.call(el, ev)); },
    click() { el.dispatchEvent({ type: 'click', target: el, stopPropagation() {}, preventDefault() {} }); },
    focus() {},
    setAttribute(k, v) { el._attrs[k] = String(v); if (k === 'class') el.className = String(v); if (k === 'id') el.id = String(v); },
    getAttribute(k) { return el._attrs[k] !== undefined ? el._attrs[k] : null; },
    querySelector(sel) { return el.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) { return walk(el, sel); },
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return el.children.map(serializeEl).join('') + (el.textContent || ''); },
    set(html) {
      // 只替换子节点，不清除元素自身的 class/id/data 属性（与真实 DOM 一致）
      el._innerHTML = String(html || '');
      el.children = [];
      el.textContent = '';
      parseFragment(el, el._innerHTML);
    },
  });
  Object.defineProperty(el, 'options', { get() { return el.children.filter((c) => c._tag === 'option'); } });
  if (attrs) {
    Object.keys(attrs).forEach((k) => {
      el._attrs[k] = attrs[k];
      if (k === 'class') el.className = attrs[k];
      else if (k === 'id') el.id = attrs[k];
      else if (k === 'value') el.value = attrs[k];
      else if (k === 'checked') el.checked = true;
      else if (k === 'selected') el.selected = true;
      else if (k === 'disabled') el.disabled = true;
      else if (k === 'readonly') el.readOnly = true;
      else if (k.startsWith('data-')) el.dataset[kebabToCamel(k.slice(5))] = attrs[k];
    });
  }
  // select.value 跟随选中 option（真实 DOM 行为）
  if (el._tag === 'select') {
    Object.defineProperty(el, 'value', {
      get() {
        const sel = el.options.find((o) => o.selected) || el.options[0];
        return sel ? sel._attrs.value || '' : '';
      },
      set(v) { el.options.forEach((o) => { o.selected = o._attrs.value === v; }); },
    });
  }
  return el;
}

function kebabToCamel(s) { return s.replace(/-([a-z])/g, (_, c) => c.toUpperCase()); }

function addText(text, stack, parent) {
  if (!text.trim()) return;
  const target = stack.length ? stack[stack.length - 1] : parent;
  if (target) target.textContent += text;
}

function parseFragment(parent, html) {
  const re = /<(\/?)([a-zA-Z][\w-]*)((?:\s+[a-zA-Z_][\w-]*(?:="[^"]*")?)*)\s*(\/?)>/g;
  const stack = [];
  let last = 0, m;
  while ((m = re.exec(html))) {
    if (m.index > last) addText(html.slice(last, m.index), stack, parent);
    last = re.lastIndex;
    const closing = m[1], tag = m[2].toLowerCase(), attrStr = m[3] || '', selfClose = m[4];
    if (closing) { stack.pop(); continue; }
    const el = makeElement(tag, parseAttrs(attrStr));
    if (stack.length) { stack[stack.length - 1].children.push(el); el.parentNode = stack[stack.length - 1]; }
    else { parent.children.push(el); el.parentNode = parent; }
    if (!selfClose && !VOID_TAGS.has(tag)) stack.push(el);
  }
  if (last < html.length) addText(html.slice(last), stack, parent);
}

function matches(el, simple) {
  // 支持 tag / #id / .class / [attr] / [attr="v"] / :not([attr="v"]) 的简单组合
  const parts = [];
  const re = /([a-zA-Z][\w-]*|#[-\w]+|\.[-\w]+|\[[^\]]+\]|:not\(\[[^\]]+\]\))/g;
  let m;
  while ((m = re.exec(simple))) parts.push(m[1]);
  if (!parts.length) return false;
  return parts.every((p) => {
    if (p[0] === '#') return el.id === p.slice(1);
    if (p[0] === '.') return el.className.split(/\s+/).includes(p.slice(1));
    if (p[0] === '[') {
      const inner = p.slice(1, -1);
      const eq = inner.indexOf('=');
      if (eq === -1) return el._attrs[inner] !== undefined;
      const k = inner.slice(0, eq);
      const v = inner.slice(eq + 1).replace(/^"|"$/g, '');
      return String(el._attrs[k]) === v;
    }
    if (p.startsWith(':not(')) {
      const inner = p.slice(5, -1).replace(/^\[|\]$/g, '');
      const eq = inner.indexOf('=');
      if (eq === -1) return el._attrs[inner] === undefined;
      const k = inner.slice(0, eq);
      const v = inner.slice(eq + 1).replace(/^"|"$/g, '');
      return String(el._attrs[k]) !== v;
    }
    return el._tag === p;
  });
}

function selectorParts(sel) {
  return sel.split(',').map((s) => s.trim()).filter(Boolean);
}

function walk(el, sel) {
  const out = [];
  const parts = selectorParts(sel);
  const visit = (node) => {
    for (const p of parts) {
      // 仅支持单个 compound（无后代组合器）
      if (matches(node, p)) { out.push(node); break; }
    }
    node.children.forEach(visit);
  };
  visit(el);
  return out;
}

function setupDom() {
  global.window = {};
  const body = makeElement('body', '');
  global.document = {
    body,
    createElement: (tag) => makeElement(tag, ''),
    addEventListener() {},
    removeEventListener() {},
    getElementById(id) {
      const found = walk(body, '#' + id);
      return found[0] || null;
    },
    querySelector(sel) { return walk(body, sel)[0] || null; },
    querySelectorAll(sel) { return walk(body, sel); },
    dispatchEvent() {},
  };
  return body;
}

function loadModule(name) {
  const src = fs.readFileSync(path.join(__dirname, 'js', name), 'utf8');
  eval(src);
  global.ECMC = global.window.ECMC;
}

function stubFetch(routes) {
  global.fetch = async (url, opts) => {
    const pathOnly = url.replace(/^https?:\/\/[^/]+/, '');
    const canned = routes[pathOnly];
    if (!canned) return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => '{}' };
    return {
      ok: canned.status < 400, status: canned.status || 200,
      headers: { get: (k) => (k.toLowerCase() === 'content-type' ? 'application/json' : (canned.headers ? canned.headers[k.toLowerCase()] : '')) },
      text: async () => JSON.stringify(canned.body),
    };
  };
  global.EARP = { apiBase: 'http://test', headers: () => ({ 'Content-Type': 'application/json' }) };
}

(async function () {
  /* ── Test 1（P0 回归）：打开目录申请抽屉并完成表单初始化 ── */
  await check('catalogRequestDrawer：初始化不抛异常，表单与提交监听就绪', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    loadModule('ecmc-governance.js');
    stubFetch({ '/catalog-change-requests': { status: 201, body: { request_id: 'ccr-1', status: 'draft' } } });
    ECMC.catalog.enableFake();

    const overlay = ECMC.governance.catalogRequestDrawer(document.body, { onCreated() {} });
    assert.ok(overlay && overlay.el, 'drawer must mount without throwing');

    const typeSel = document.querySelector('#ccr-type');
    assert.ok(typeSel, 'request_type select must exist');
    assert.strictEqual(typeSel.options.length, 10, 'all 10 catalog kinds present');

    // contract 区域按 metric 默认渲染（value_type select + 两个受控多选）
    const contract = document.querySelector('#ccr-contract');
    assert.ok(contract, 'contract section must render');
    assert.ok(contract.querySelector('[data-contract-field="value_type"]'), 'metric value_type field');
    assert.ok(contract.querySelector('[data-contract-reflist="allowed_unit_refs"]'), 'metric allowed_unit_refs reflist');

    // 切换到 relation_type → contract 重渲染
    typeSel.value = 'relation_type';
    typeSel.dispatchEvent({ type: 'change' });
    const contract2 = document.querySelector('#ccr-contract');
    assert.ok(contract2.querySelector('[data-contract-reflist="source_entity_type_refs"]'), 'relation source refs');
    assert.ok(contract2.querySelector('[data-contract-reflist="target_entity_type_refs"]'), 'relation target refs');
  });

  await check('catalogRequestDrawer：选择受控数据域并提交（typed contract）', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    loadModule('ecmc-governance.js');
    let posted = null;
    global.fetch = async (url, opts) => {
      if (opts && opts.method === 'POST') posted = JSON.parse(opts.body);
      return { ok: true, status: 201, headers: { get: () => 'application/json' }, text: async () => '{}' };
    };
    global.EARP = { apiBase: 'http://test', headers: () => ({ 'Content-Type': 'application/json' }) };
    ECMC.catalog.enableFake();

    const overlay = ECMC.governance.catalogRequestDrawer(document.body, { onCreated() {} });
    // 选择数据域：打开 picker 弹层并点击第一项（production）
    const domainRoot = overlay.el.querySelector('#ccr-domain');
    assert.ok(domainRoot, 'domain ref field exists');
    const trigger = domainRoot.querySelector('.ecmc-picker-trigger');
    assert.ok(trigger, 'domain picker trigger (fake adapter)');
    trigger.click();
    const item = domainRoot.querySelector('.ecmc-picker-item');
    assert.ok(item, 'domain picker items listed');
    item.click();

    // 填写表单
    overlay.el.querySelector('#ccr-name').value = '运输周期';
    overlay.el.querySelector('#ccr-def').value = '矿卡完成一次运输循环的分钟数';
    overlay.el.querySelector('#ccr-rationale').value = '用于运输周期诊断';
    overlay.el.querySelector('[data-submit]').click();

    assert.ok(posted, 'submit must POST');
    assert.strictEqual(posted.request_type, 'metric');
    assert.strictEqual(posted.target_data_domain_ref.stable_id, 'production');
    assert.strictEqual(posted.proposed_definition.kind, 'metric');
    assert.strictEqual(posted.proposed_definition.contract.value_type, 'decimal');
  });

  /* ── Test 2：?catalog=fake 可打开模型向导 ── */
  await check('ecmc-models.html?catalog=fake：新建模型打开向导而非“受控目录不可用”', async () => {
    setupDom();
    global.location = { search: '?catalog=fake', href: 'ecmc-models.html?catalog=fake' };
    // 模型资产页静态元素
    const mk = (tag, attrs) => { const el = document.createElement(tag); Object.keys(attrs || {}).forEach((k) => el.setAttribute(k, attrs[k])); document.body.appendChild(el); return el; };
    mk('input', { id: 'ecmc-model-search' });
    mk('select', { id: 'ecmc-model-domain' });
    mk('select', { id: 'ecmc-model-status' });
    mk('button', { id: 'ecmc-new-model' });
    mk('tbody', { id: 'ecmc-model-rows' });
    mk('div', { id: 'ecmc-model-empty' });
    mk('span', { id: 'ecmc-model-count' });
    mk('div', { id: 'ecmc-errorbar' });
    [['all', ''], ['causal', ''], ['decision', 'planned'], ['task', 'planned']].forEach((t) => {
      const tab = mk('button', { class: 'ecmc-tab', 'data-type': t[0] });
      if (t[1]) tab.setAttribute('data-planned', '1');
    });
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    loadModule('ecmc-models.js');
    stubFetch({ '/causal-models': { status: 200, body: [] } });

    // boot 已执行（eval 即执行）
    assert.ok(ECMC.catalog.getAdapter(), '?catalog=fake must enable fake adapter');

    const newBtn = document.getElementById('ecmc-new-model');
    assert.ok(newBtn, 'new-model button exists');
    newBtn.click();
    const dialog = document.querySelector('.ecmc-dialog');
    assert.ok(dialog, 'wizard dialog opens');
    assert.ok(dialog.querySelector('[data-type="causal"]'), 'wizard step-1 causal button present');
    assert.ok(!dialog.textContent.includes('受控目录不可用'), 'NOT the unavailable dialog');
  });

  await check('无 Catalog adapter：refInput 不提供自由 stable ID 输入（§9.3）', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    // 不启用 fake adapter → 生产默认
    const box = document.createElement('div');
    document.body.appendChild(box);
    const input = ECMC.catalog.refInput(box, { kind: 'data_domain', emptyLabel: 'x' });
    assert.strictEqual(box.querySelectorAll('input').length, 0, 'no free stable_id/version inputs');
    assert.strictEqual(box.querySelectorAll('select').length, 0, 'no free kind select');
    const note = box.querySelector('.info-box');
    assert.ok(note && note.textContent.includes('未签署'), 'unavailable explanation shown');
    assert.strictEqual(input.getValue(), null, 'cannot produce a ref without catalog');
  });

  await check('无 Catalog adapter：multiRefInput 只读，禁止新增', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    const box = document.createElement('div');
    document.body.appendChild(box);
    const multi = ECMC.catalog.multiRefInput(box, {
      kind: 'capability_contract',
      value: [{ kind: 'capability_contract', stable_id: 'contract.x', version: 'v1' }],
    });
    assert.ok(box.querySelector('[data-add]') === null, 'no add button without adapter');
    assert.deepStrictEqual(multi.getValue(), [{ kind: 'capability_contract', stable_id: 'contract.x', version: 'v1' }], 'existing values preserved');
  });

  await check('生产无 adapter：目录申请提交按钮禁用并说明', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    loadModule('ecmc-governance.js');
    stubFetch({});
    const overlay = ECMC.governance.catalogRequestDrawer(document.body, { onCreated() {} });
    const btn = overlay.el.querySelector('[data-submit]');
    assert.ok(btn.disabled, 'submit disabled without catalog adapter');
    assert.ok(btn.textContent.includes('合同签署后可提交'), 'clear disabled text');
  });

  await check('paramsRowsComponent：两个标量 schema 字段独立收集（闭包回归）', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    const custom = {
      testOnly: true,
      search: () => [],
      lookup: (ref) => ref && ref.stable_id === 'template.two'
        ? { kind: 'binding_template', stable_id: 'template.two', version: 'v1', display_name: '双标量模板', status: 'active', data_domain_id: 'production_data', params_schema: { properties: [{ name: 'alpha', label: 'A', type: 'string' }, { name: 'beta', label: 'B', type: 'string' }] } }
        : null,
    };
    ECMC.catalog.setAdapter(custom);
    const box = document.createElement('div');
    document.body.appendChild(box);
    const ctl = ECMC.common.paramsRowsComponent(box, { alpha: 'x', beta: 'y' }, { kind: 'binding_template', stable_id: 'template.two', version: 'v1' }, false);
    const inputs = box.querySelectorAll('input.ecmc-params-value');
    assert.strictEqual(inputs.length, 2, 'two scalar fields rendered');
    inputs[0].value = 'A1';
    inputs[1].value = 'B2';
    assert.deepStrictEqual(ctl.collect(), { alpha: 'A1', beta: 'B2' }, 'each field collected independently（闭包共享回归）');
  });

  await check('fake 模式跳转透传 catalog=fake（editorUrl / withCatalogParam）', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    // 非 fake：不附加参数（显式清空 URL，避免前序测试残留）
    global.location = { search: '', href: 'ecmc-models.html' };
    assert.strictEqual(ECMC.common.editorUrl('cm-1', 'cmv-1'), 'ecmc-causal-edit.html?model_id=cm-1&version_id=cmv-1');
    assert.strictEqual(ECMC.common.withCatalogParam('ecmc-models.html?type=causal'), 'ecmc-models.html?type=causal');
    // fake：附加且不重复
    ECMC.catalog.enableFake();
    const url = ECMC.common.editorUrl('cm-1', 'cmv-1');
    assert.ok(url.includes('catalog=fake'), 'editor URL carries catalog=fake');
    const tabUrl = ECMC.common.withCatalogParam('ecmc-models.html?type=causal');
    assert.ok(tabUrl.includes('catalog=fake') && !tabUrl.includes('catalog=fake&catalog=fake'), 'no duplicate param');
  });

  await check('ECMC 内部导航全部经 URL helper（无裸拼接，覆盖实际调用点）', async () => {
    const files = ['ecmc-causal-editor.js', 'ecmc-models.js', 'ecmc-overview.js', 'ecmc-reviews.js', 'ecmc-compiles.js', 'ecmc-catalog-requests.js'];
    const bare = [
      /location\.href\s*=\s*'ecmc-causal-edit\.html\?model_id='/,
      /location\.href\s*=\s*'ecmc-catalog-requests\.html/,
      /location\.href\s*=\s*'ecmc-models\.html'/,
      /location\.href\s*=\s*'ecmc-reviews\.html\?filter='/,
      /location\.href\s*=\s*'ecmc-compiles\.html\?view='/,
    ];
    files.forEach((f) => {
      const src = fs.readFileSync(path.join(__dirname, 'js', f), 'utf8');
      bare.forEach((re) => {
        assert.ok(!re.test(src), f + ' must not concatenate raw page URL (' + re + ')');
      });
    });
    // 反向验证：helper 确实被使用
    ['ecmc-causal-editor.js', 'ecmc-models.js', 'ecmc-overview.js', 'ecmc-reviews.js', 'ecmc-compiles.js'].forEach((f) => {
      const src = fs.readFileSync(path.join(__dirname, 'js', f), 'utf8');
      assert.ok(src.includes('common.editorUrl') || src.includes('common.withCatalogParam'), f + ' uses URL helpers');
    });
  });

  await check('fake 模式：URL 参数本身即可判定（概览/审核/编译页不加载 picker）', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    // 未加载 ecmc-catalog-picker.js，adapter 为 null；仅 URL 带参
    global.location = { search: '?catalog=fake', href: 'ecmc.html?catalog=fake' };
    assert.strictEqual(ECMC.common.isFakeCatalog(), true, 'URL param alone enables fake mode');
    assert.ok(ECMC.common.editorUrl('cm-1', 'cmv-1').includes('catalog=fake'));
    // 非 fake URL → 不附加
    global.location = { search: '', href: 'ecmc.html' };
    assert.strictEqual(ECMC.common.isFakeCatalog(), false);
    assert.ok(!ECMC.common.editorUrl('cm-1', 'cmv-1').includes('catalog=fake'));
  });

  await check('fake 连续导航：模型页 → 待审核 → 编辑器 → 返回模型页', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    // 模型页（fake）→ 审核页链接（经 URL helper）
    global.location = { search: '?catalog=fake&sub=ecmc-reviews-mine', href: 'ecmc-reviews.html?catalog=fake' };
    assert.ok(ECMC.common.isFakeCatalog(), 'reviews page keeps fake via URL');
    const reviewToEditor = ECMC.common.editorUrl('cm-1', 'cmv-1');
    assert.ok(reviewToEditor.includes('catalog=fake'), '审核页 → 编辑器透传');
    // 编辑器（URL 仍带参）→ 驳回 → 返回模型页
    global.location = { search: '?model_id=cm-1&version_id=cmv-1&catalog=fake', href: reviewToEditor };
    assert.ok(ECMC.common.isFakeCatalog(), 'editor keeps fake');
    const back = ECMC.common.withCatalogParam('ecmc-models.html');
    assert.ok(back.includes('catalog=fake'), '返回模型页透传');
    assert.ok(!back.includes('catalog=fake&catalog=fake'), 'no duplicate param');
  });

  await check('nav.js：ECMC 顶栏与抽屉链接透传 catalog=fake', async () => {
    setupDom();
    global.location = { search: '?catalog=fake&sub=ecmc-models', href: 'ecmc-models.html?catalog=fake', pathname: '/pages/ecmc-models.html' };
    global.localStorage = { getItem: () => null, setItem() {} };
    const body = document.body;
    body.dataset = { base: '..', section: 'ecmc', sub: 'ecmc-models' };
    const header = document.createElement('header');
    const main = document.createElement('main');
    body.appendChild(header);
    body.appendChild(main);
    document.readyState = 'complete';
    const navSrc = fs.readFileSync(path.join(__dirname, 'js', 'nav.js'), 'utf8');
    eval(navSrc);

    // 顶栏「认知模型」链接透传
    const ecmcTop = header.querySelectorAll('a[data-nav-section="ecmc"]');
    assert.strictEqual(ecmcTop.length, 1, 'top nav has 认知模型');
    assert.ok(ecmcTop[0].getAttribute('href').includes('catalog=fake'), 'top nav ecmc link carries fake');

    // 抽屉「待审核」链接透传
    const drawer = document.getElementById('app-drawer');
    assert.ok(drawer, 'drawer rendered');
    const reviewLinks = drawer.querySelectorAll('a').filter((a) => (a.getAttribute('href') || '').includes('ecmc-reviews.html'));
    assert.ok(reviewLinks.length >= 1, 'reviews links present');
    reviewLinks.forEach((a) => assert.ok(a.getAttribute('href').includes('catalog=fake'), 'drawer reviews link carries fake'));
  });

  await check('fmtDecimal：服务端 NUMERIC 长尾零归一化显示', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    const f = ECMC.common.fmtDecimal;
    assert.strictEqual(f('0.800000000000000000'), '0.8', 'trailing zeros trimmed');
    assert.strictEqual(f('0.600000000000000000'), '0.6');
    assert.strictEqual(f('0.80'), '0.8');
    assert.strictEqual(f('1.000000000000000000'), '1');
    assert.strictEqual(f('0.5'), '0.5', 'no trailing zeros untouched');
    assert.strictEqual(f('PT0S'), 'PT0S', 'non-decimal returned as-is');
    assert.strictEqual(f(0.8), '0.8', 'number input handled');
  });

  await check('BindingTemplate ref 参数按数据域过滤（domain 透传）', async () => {
    setupDom();
    loadModule('ecmc-api.js');
    loadModule('ecmc-common.js');
    loadModule('ecmc-catalog-picker.js');
    const custom = {
      testOnly: true,
      search: (opts) => opts.kind === 'entity_type'
        ? [
          { kind: 'entity_type', stable_id: 'entity.mine', version: 'v1', display_name: '矿山', status: 'active', data_domain_id: 'production_data' },
          { kind: 'entity_type', stable_id: 'entity.equipment_group', version: 'v1', display_name: '设备组', status: 'active', data_domain_id: 'equipment_data' },
        ].filter((e) => !opts.domain || e.data_domain_id === opts.domain)
        : [],
      lookup: (ref) => ref && ref.stable_id === 'template.ctx'
        ? { kind: 'binding_template', stable_id: 'template.ctx', version: 'v1', display_name: '上下文', status: 'active', data_domain_id: 'production_data', params_schema: { properties: [{ name: 'entity_type_ref', label: '目标实体', type: 'ref', kind: 'entity_type' }] } }
        : null,
    };
    ECMC.catalog.setAdapter(custom);
    const box = document.createElement('div');
    document.body.appendChild(box);
    // 传入 equipment 数据域
    ECMC.common.paramsRowsComponent(box, {}, { kind: 'binding_template', stable_id: 'template.ctx', version: 'v1' }, false, 'equipment_data');
    const trigger = box.querySelector('.ecmc-picker-trigger');
    assert.ok(trigger, 'ref param renders a picker (adapter present)');
    trigger.click();
    const items = box.querySelectorAll('.ecmc-picker-item');
    assert.strictEqual(items.length, 1, 'only same-domain entity type listed');
    assert.strictEqual(items[0].getAttribute('data-ref'), 'entity.equipment_group', 'equipment entry only');
    assert.ok(items[0].querySelector('.pi-name').textContent.includes('设备组'), 'display name correct');
  });

  process.exit(allOk ? 0 : 1);
})();
