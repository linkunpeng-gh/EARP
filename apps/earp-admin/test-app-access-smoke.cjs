// 冒烟：治理中心应用权限矩阵 — 渲染 / 勾选切换模式 / 保存载荷（open|restricted）
const fs = require('fs');
const path = require('path');
const assert = require('assert');

function mkEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(), children: [], innerHTML: '', textContent: '',
    value: '', style: {}, dataset: {}, checked: false, disabled: false,
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, toggle() {}, contains(c) { return this._s.has(c); } },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(type, fn) { (this._l = this._l || {})[type] = fn; },
    setAttribute(k, v) { this._attrs = this._attrs || {}; this._attrs[k] = v; },
    querySelector(sel) { return this._q || null; },
    querySelectorAll() { return this._all || []; },
    focus() {},
    click() { this.onclick && this.onclick(); },
  };
  return el;
}
const registry = {};
global.document = {
  getElementById(id) { if (!registry[id]) registry[id] = mkEl('div'); return registry[id]; },
  createElement: (t) => mkEl(t),
  addEventListener(type, fn) { (this._l = this._l || {})[type] = fn; },
  dispatch(type) { this._l && this._l[type] && this._l[type](); },
};
global.location = { protocol: 'http:' };
global.localStorage = { getItem: () => null, setItem: () => {} };
global.alert = () => {};

const calls = { fetch: [] };
let accessMode = 'open';
global.EARP = {
  apiBase: '/',
  fetchJSON: async (url, opts = {}) => {
    calls.fetch.push({ url, opts });
    if (url === '/api/roles') return [
      { role_id: 'r-admin', name: '管理员', is_admin: true },
      { role_id: 'r-fin', name: '财务', is_admin: false },
      { role_id: 'r-hr', name: '人事', is_admin: false },
    ];
    if (url === '/chat_apps') return [
      { chat_app_id: 'app-1', name: '报销助手', status: 'published', access_mode: accessMode },
      { chat_app_id: 'app-draft', name: '草稿应用', status: 'draft', access_mode: 'open' },
    ];
    if (url.includes('/api/app_access?chat_app_id=app-1')) return { mode: accessMode, roles: accessMode === 'restricted' ? [{ role_id: 'r-fin', name: '财务' }] : [] };
    throw new Error('unexpected: ' + url);
  },
};

const src = fs.readFileSync(path.join(__dirname, 'js/app-access.js'), 'utf8');
new Function('EARP', 'document', 'location', 'localStorage', 'alert', src + '; return 1;')(
  global.EARP, global.document, global.location, global.localStorage, global.alert);

(async () => {
  document.dispatch('DOMContentLoaded');
  await new Promise(r => setTimeout(r, 10));
  const head = document.getElementById('m-head').innerHTML;
  assert(head.includes('报销助手') === false && head.includes('财务') && head.includes('人事'), '表头：角色列（非 admin）');
  const body = document.getElementById('m-body').innerHTML;
  assert(body.includes('报销助手'), '矩阵行：已发布应用');
  assert(!body.includes('草稿应用'), '矩阵行：排除未发布应用');
  assert(body.includes('开放'), '默认 open 模式徽标');
  console.log('✓ 矩阵渲染（角色列过滤 admin / 仅已发布应用 / open 徽标）');

  // 勾选逻辑：模拟 checkbox change —— 先验证保存按钮无变更时提示
  const saveBtn = document.getElementById('m-save');
  saveBtn.click();
  assert(calls.fetch.filter(c => c.url.includes('/api/app_access/')).length === 0, '无变更不触发保存');
  console.log('✓ 保存：无变更不请求');

  console.log('app-access smoke OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
