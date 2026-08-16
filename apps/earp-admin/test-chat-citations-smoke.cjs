// 冒烟：chat-edit.html appendCitations 对 capability 引用（Phase D）的渲染
// 验证：capability 徽标（📊聚合）+ aggregate 摘要；profile/graph 徽标回归
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'pages/chat-edit.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const biz = scripts[scripts.length - 1];

function mkEl() {
  return {
    children: [], innerHTML: '', className: '', _text: '',
    appendChild(c) { this.children.push(c); return c; },
    insertAdjacentHTML(pos, s) { if (pos === 'beforeend') this.innerHTML += s; },
    set textContent(v) { this._text = v; this.innerHTML = ''; },
    get textContent() { return this._text; },
    get scrollTop() { return 0; }, set scrollTop(v) {},
    get scrollHeight() { return 0; },
    addEventListener() {}, focus() {}, setAttribute() {}, style: {},
  };
}
const els = {};
global.document = {
  getElementById(id) { return els[id] || (els[id] = mkEl()); },
  createElement() { return mkEl(); },
  querySelector() { return null; },
  addEventListener() {},
};
global.window = global;
global.location = { search: '' };
global.appId = 'app-test';  // biz 顶层 if (!appId) return 守卫
// EARP 顶层引用（script 定义阶段不调用，但防御性 stub）
global.EARP = { fetchJSON() {}, streamSSE() {} };

try {
  (0, eval)(biz); // 全局作用域执行 → appendCitations/esc 为全局函数
  const citations = [
    { source: 'capability', capability_id: 'cap-1', title: 'query_equipment_alarm', aggregate: { count: 5 } },
    { source: 'profile', entity_id: 'e1', entity_type: 'equipment', title: 'CNC-01（实体档案）', key_facts: [] },
    { source: 'graph', entity_id: 'e2', entity_type: 'supplier', title: '图谱：manufactured_by → 上海某精机' },
    { chunk_id: 'c1', document_id: 'd1', title: '维护手册v1', kb_name: '设备维护手册', similarity: 0.82 },
  ];
  global.appendCitations(citations);
  const area = els['msg-area'];
  const block = area.children[0];
  const out = block ? block.innerHTML : '';
  const checks = [
    ['capability 徽标', out.includes('📊聚合')],
    ['profile 徽标', out.includes('📇实体')],
    ['graph 徽标', out.includes('🕸图谱')],
    ['capability aggregate 摘要', out.includes('聚合') && out.includes('count')],
    ['chunk 标题', out.includes('维护手册v1')],
    ['capability 标题', out.includes('query_equipment_alarm')],
  ];
  let fail = 0;
  checks.forEach(([name, ok]) => {
    console.log((ok ? 'PASS' : 'FAIL') + '  ' + name);
    if (!ok) fail++;
  });
  console.log('cite cards:', (out.match(/cite-card/g) || []).length, '(expect 4)');
  process.exit(fail || (out.match(/cite-card/g) || []).length !== 4 ? 1 : 0);
} catch (e) {
  console.log('SMOKE ERROR:', e.message);
  console.log((e.stack || '').split('\n').slice(0, 6).join('\n'));
  process.exit(1);
}
