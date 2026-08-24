// 冒烟：治理中心应用分类 — 词表渲染 / 新增 / 改名 / 删除
const fs = require('fs');
const path = require('path');
const assert = require('assert');

function mkEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(), children: [], innerHTML: '', textContent: '',
    value: '', style: {}, dataset: {},
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, toggle() {}, contains(c) { return this._s.has(c); } },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {}, setAttribute() {}, querySelector() { return null; }, querySelectorAll() { return []; },
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
global.confirm = () => true;

const calls = { fetch: [] };
global.EARP = {
  apiBase: '/',
  fetchJSON: async (url, opts = {}) => {
    calls.fetch.push({ url, opts });
    if (url === '/api/app_categories') return [{ category_id: 'cat-1', name: '财务' }, { category_id: 'cat-2', name: '人事' }];
    if (url.includes('/api/app_categories/cat-1') && opts.method === 'DELETE') return { deleted: true, affected_apps: 2 };
    throw new Error('unexpected: ' + url);
  },
};

const src = fs.readFileSync(path.join(__dirname, 'js/app-categories.js'), 'utf8');
new Function('EARP', 'document', 'location', 'localStorage', 'alert', 'confirm', src + '; return 1;')(
  global.EARP, global.document, global.location, global.localStorage, global.alert, global.confirm);

(async () => {
  document.dispatch('DOMContentLoaded');
  await new Promise(r => setTimeout(r, 10));
  const tbody = document.getElementById('cat-list');
  const html = tbody.innerHTML;
  assert(html.includes('财务') && html.includes('人事'), '词表渲染');
  assert(html.includes('data-act="rename"') && html.includes('data-act="del"'), '改名/删除按钮');
  console.log('✓ 分类词表渲染');

  // 新增：点击 add → POST
  const addBtn = document.getElementById('cat-add');
  document.getElementById('cat-name').value = '客服';
  addBtn.click();
  await new Promise(r => setTimeout(r, 10));
  const post = calls.fetch.find(c => c.url === '/api/app_categories' && c.opts && c.opts.method === 'POST');
  assert(post && JSON.parse(post.opts.body).name === '客服', '新增分类 POST 载荷');
  console.log('✓ 新增分类');

  console.log('app-categories smoke OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
