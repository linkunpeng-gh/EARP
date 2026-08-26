// 冒烟：Chatflow 运行历史（tech-debt #17 Task 4）
// 验证：js/run-history.js — 模态构建 / 运行列表渲染（状态/时间/attempts/耗时）/
//       展开 trace 表格（node/status/branch/in-out/error/error_code/latency）/ 空态与错误路径。
const fs = require('fs');
const path = require('path');
const assert = require('assert');

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
    querySelector() { return null; },
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
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  dispatch() {},
});
global.document = mkDoc();
global.alert = () => {};

const runs = [
  {
    execution_id: 'run-1', chat_app_id: 'app-1', conversation_id: 'conv-1', status: 'completed',
    attempts: 2, created_at: '2026-08-26T10:00:00Z', updated_at: '2026-08-26T10:00:05Z', finished_at: '2026-08-26T10:00:05Z',
    trace: [
      { node_id: 'start', status: 'completed', branch: null, input: null, output: {}, error: null, error_code: null, latency_ms: 1 },
      { node_id: 'h1', status: 'completed', branch: null, input: { q: 'hi' }, output: { reply: 'yes' }, error: null, error_code: null, latency_ms: 3 },
      { node_id: 'l1', status: 'failed', branch: null, input: { q: 'hi' }, output: null, error: '连接失败', error_code: 'connection', latency_ms: 502 },
    ],
  },
  { execution_id: 'run-2', chat_app_id: 'app-1', conversation_id: 'conv-1', status: 'timeout', attempts: 1,
    created_at: '2026-08-26T09:00:00Z', updated_at: '2026-08-26T09:10:00Z', finished_at: '2026-08-26T09:10:00Z', trace: [] },
];

const calls = { fetch: [] };
global.EARP = {
  fetchJSON: async (url, opts = {}) => {
    calls.fetch.push({ url, opts });
    if (url.endsWith('/runs')) return runs;
    throw new Error('unexpected: ' + url);
  },
};

const src = fs.readFileSync(path.join(__dirname, 'js/run-history.js'), 'utf8');
const EARPRunHistory = new Function('EARP', 'document', 'alert', src + '; return EARPRunHistory;')(
  global.EARP, global.document, global.alert);

(async () => {
  // 1. open：构建模态 + 加载列表
  EARPRunHistory.open('app-1', '设备维修流');
  assert(registry['run-history-modal'], '模态已构建');
  assert(registry['run-history-modal'].style.display === 'flex', '模态已打开');
  assert(registry['rh-title'].textContent.includes('设备维修流'), '标题含应用名');
  await new Promise(r => setTimeout(r, 10));
  const body = document.getElementById('rh-body').innerHTML;
  assert(body.includes('已完成') && body.includes('超时'), '状态徽标');
  assert((body.match(/2026-08-26/g) || []).length >= 2, '时间渲染（本地时区日期）');
  assert(body.includes('attempts 2'), 'attempts 显示');
  assert(body.includes('5000ms'), '耗时计算（finished-created）');
  assert(calls.fetch.some(c => c.url.endsWith('/runs')), '拉取 /chat_apps/{id}/runs');
  console.log('✓ 运行列表（状态/时间/attempts/耗时）');

  // 2. trace 表格（列表渲染时已生成，display:none 容器内；toggle 只切显示）
  const trace = document.getElementById('rh-body').innerHTML;
  assert(trace.includes('start') && trace.includes('h1') && trace.includes('l1'), '节点渲染');
  assert(trace.includes('in:') && trace.includes('out:'), 'input/output 字段');
  assert(trace.includes('连接失败') && trace.includes('connection'), 'error + error_code');
  assert(trace.includes('502ms'), 'latency');
  EARPRunHistory.toggle('run-1');
  const d1 = document.getElementById('rh-trace-run-1').style.display;
  EARPRunHistory.toggle('run-1');
  const d2 = document.getElementById('rh-trace-run-1').style.display;
  assert(d1 !== d2, 'toggle 切换显示（fake DOM 无 CSS 初始态，验证可切换即可）');
  console.log('✓ trace 表格（node/status/in-out/error/error_code/latency + 展开收起）');

  // 3. 空态 + 错误路径
  global.EARP.fetchJSON = async (url) => {
    if (url.endsWith('/runs')) return [];
    throw new Error('unexpected');
  };
  await EARPRunHistory.loadRuns();
  assert(document.getElementById('rh-body').innerHTML.includes('暂无运行记录'), '空态提示');
  global.EARP.fetchJSON = async () => { const e = new Error('404'); e.status = 404; throw e; };
  await EARPRunHistory.loadRuns();
  assert(document.getElementById('rh-body').innerHTML.includes('加载失败'), '错误路径提示');
  console.log('✓ 空态 + 错误路径');

  console.log('run-history smoke OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
