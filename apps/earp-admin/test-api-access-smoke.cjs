// 冒烟：应用详情「API 访问」密钥管理（tech-debt #18 Task 5）
// 验证：js/api-access.js — 模态构建/密钥列表渲染（名称/状态/最后使用）/ 生成（明文一次展示+复制）/
//       吊销（confirm → POST → 刷新列表）/ 空列表与错误路径。
const fs = require('fs');
const path = require('path');
const assert = require('assert');

// ── fake DOM（注册式：getElementById 恒返回同一对象，appendChild 按 id 注册）──────
const registry = {};
function mkEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(), children: [], innerHTML: '', textContent: '',
    value: '', style: {}, dataset: {}, className: '', disabled: false, onclick: null,
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); }, remove(c) { this._set.delete(c); },
      toggle(c, on) { if (on === undefined) on = !this._set.has(c); on ? this._set.add(c) : this._set.delete(c); return on; },
      contains(c) { return this._set.has(c); },
    },
    set id(v) { this._id = v; registry[v] = this; },
    get id() { return this._id; },
    appendChild(c) { this.children.push(c); if (c.id) registry[c.id] = c; return c; },
    append(...cs) { cs.forEach(c => this.appendChild(c)); },
    addEventListener(type, fn) { (this._listeners = this._listeners || {})[type] = fn; },
    setAttribute(k, v) { this._attrs = this._attrs || {}; this._attrs[k] = v; },
    querySelector(sel) { return null; }, // 模态内元素经 getElementById 取，querySelector 不模拟
    querySelectorAll() { return []; },
    closest() { return null; },
    focus() {}, click() { (this._listeners && this._listeners.click) && this._listeners.click(); },
  };
  return el;
}
const mkDoc = () => ({
  body: mkEl('body'),
  getElementById(id) { if (!registry[id]) registry[id] = mkEl('div'); return registry[id]; },
  createElement(tag) { return mkEl(tag); },
  querySelector(sel) { return null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  dispatch() {},
});
global.document = mkDoc();
global.alert = (m) => { alerts.push(m); };
global.confirm = () => true;
const clipboardStub = { clipboard: { writeText: async (t) => { copied.push(t); } } };

const calls = { fetch: [] };
const copied = [];
const alerts = [];

const keyRows = [
  { api_key_id: 'k1', name: 'prod-报销助手', status: 'active', created_at: '2026-08-25T10:00:00Z', last_used_at: '2026-08-26T02:00:00Z' },
  { api_key_id: 'k2', name: 'dev-测试', status: 'revoked', created_at: '2026-08-24T10:00:00Z', last_used_at: null },
];
global.EARP = {
  fetchJSON: async (url, opts = {}) => {
    calls.fetch.push({ url, opts });
    if (url.endsWith('/api-keys') && (!opts.method || opts.method === 'GET')) return keyRows;
    if (url.endsWith('/api-keys') && opts.method === 'POST') {
      const name = JSON.parse(opts.body).name;
      return { chat_app_id: 'app-1', name, plaintext: 'app-abcdef0123456789abcdef0123456789' };
    }
    if (url.endsWith('/revoke')) return { api_key_id: 'k1', revoked: true };
    throw new Error('unexpected: ' + url);
  },
};

const src = fs.readFileSync(path.join(__dirname, 'js/api-access.js'), 'utf8');
const EARPApiAccess = new Function('EARP', 'document', 'location', 'localStorage', 'alert', 'confirm', 'navigator', src + '; return EARPApiAccess;')(
  global.EARP, global.document, {}, {}, global.alert, global.confirm, clipboardStub);

(async () => {
  // 1. open：构建模态 + 拉取列表渲染
  EARPApiAccess.open('app-1');
  assert(registry['api-access-modal'], '模态已构建');
  assert(registry['api-access-modal'].style.display === 'flex', '模态已打开');
  await new Promise(r => setTimeout(r, 10));
  const rows = document.getElementById('api-key-rows').innerHTML;
  assert(rows.includes('prod-报销助手') && rows.includes('有效'), '列表：名称 + 有效徽标');
  assert(rows.includes('dev-测试') && rows.includes('已吊销'), '列表：已吊销徽标');
  assert(rows.includes('2026-08-26') && rows.includes('2026-08-25'), '列表：创建时间/最后使用渲染');
  assert(!rows.includes('key_hash'), '列表：绝不渲染 key_hash');
  assert(rows.includes('onclick="EARPApiAccess.revoke(\'k1\')"'), '有效密钥显示吊销按钮');
  assert(!rows.includes('revoke(\'k2\')'), '已吊销密钥不显示吊销按钮');
  console.log('✓ 列表渲染（名称/状态/时间/吊销按钮，无 key_hash）');

  // 2. 生成：POST + 明文一次性展示 + 复制
  document.getElementById('api-key-name').value = 'prod-新密钥';
  await EARPApiAccess.create();
  const created = calls.fetch.filter(c => c.url.endsWith('/api-keys') && c.opts.method === 'POST');
  assert(created.length === 1 && created[0].opts.body.includes('prod-新密钥'), '生成：POST /api-keys');
  assert(registry['api-key-created'].style.display === 'block', '生成：明文展示框出现');
  assert(registry['api-key-plain'].textContent === 'app-abcdef0123456789abcdef0123456789', '生成：明文一次展示');
  EARPApiAccess.copyPlain();
  await new Promise(r => setTimeout(r, 10));
  assert(copied[0] === 'app-abcdef0123456789abcdef0123456789', '复制：明文写入剪贴板');
  console.log('✓ 生成密钥（明文一次展示 + 复制）');

  // 3. 吊销：confirm → POST /revoke → 刷新列表
  await EARPApiAccess.revoke('k1');
  const revokeCalls = calls.fetch.filter(c => c.url.endsWith('/revoke'));
  assert(revokeCalls.length === 1, '吊销：POST /revoke');
  assert(registry['api-key-rows'].innerHTML.includes('prod-报销助手'), '吊销后刷新列表');
  console.log('✓ 吊销（confirm → POST → 刷新）');

  // 4. 空列表 + 无名称校验
  global.EARP.fetchJSON = async (url, opts = {}) => {
    if (url.endsWith('/api-keys') && (!opts.method || opts.method === 'GET')) return [];
    throw new Error('unexpected: ' + url);
  };
  await EARPApiAccess.loadKeys();
  assert(document.getElementById('api-key-rows').innerHTML.includes('暂无密钥'), '空列表提示');
  document.getElementById('api-key-name').value = '   ';
  await EARPApiAccess.create();
  assert(alerts.length === 0 && document.getElementById('api-key-err').textContent.includes('请输入密钥名称'), '空名称不请求');
  console.log('✓ 空列表 + 名称必填校验');

  console.log('api-access smoke OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
