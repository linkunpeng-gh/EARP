// 临时冒烟：真实 API 环境模拟 entities.html 前端流程（init/loadList/showDetail/deprecate）
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'pages/entities.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const biz = scripts[scripts.length - 1];
const token = process.env.TOKEN;

function mkEl() {
  return { value: '', textContent: '', innerHTML: '', style: {}, files: [],
    addEventListener() {}, appendChild() {}, insertAdjacentHTML() {}, setAttribute() {}, click() {},
    querySelector() { return null; } };
}
const els = {};
const document = {
  getElementById(id) { return els[id] || (els[id] = mkEl()); },
  createElement() { return mkEl(); },
  createElementNS() { return mkEl(); },
  querySelector() { return null; },
};
global.window = global;
global.document = document;
global.EARP = {
  apiBase: 'http://127.0.0.1:8000',
  token,
  async fetchJSON(url, opts = {}) {
    const res = await fetch(EARP.apiBase + url, { headers: { Authorization: 'Bearer ' + EARP.token }, ...opts });
    if (!res.ok) throw new Error(res.status + ' ' + url);
    return res.json();
  },
};

(async () => {
  try {
    (0, eval)(biz); // 全局作用域执行页面脚本 → init/loadList/showDetail/deprecate 为全局函数
    await global.init();
    await global.loadList();
    console.log('list rows innerHTML len:', els['ent-tbody'].innerHTML.length);
    console.log('count text:', els['ent-count'].textContent);
    const lu = await EARP.fetchJSON('/v1/ontology/entities/lookup?q=DEMO-CNC-99');
    await global.showDetail(lu[0].entity_id);
    console.log('detail len:', els['ent-detail'].innerHTML.length);
    console.log('detail head:', els['ent-detail'].innerHTML.replace(/\n/g, ' ').slice(0, 160));
    try { await global.deprecate('ent-nonexist', 'x'); } catch (e) { console.log('deprecate err path ok:', e.message); }
    console.log('ALL FLOW OK');
  } catch (e) {
    console.log('FRONTEND ERROR:', e.message);
    console.log((e.stack || '').split('\n').slice(0, 6).join('\n'));
  }
})();
