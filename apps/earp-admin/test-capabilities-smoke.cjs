// 冒烟：capabilities.html 能力中心（tech-debt #14 + 通用执行器执行声明）
// 验证：脚本可执行 + loadCapabilities 渲染（权限 chips / execution 摘要 / 状态）
// + 新建（POST 带 execution）+ 编辑（GET 详情预填 → PATCH）+ 停用（DELETE）
// + 详情（GET）+ Register Demo（空 body POST）+ 坏 JSON 前端拦截
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'pages/capabilities.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const biz = scripts[scripts.length - 1];

function mkEl() {
  return {
    children: [], innerHTML: '', _text: '', value: '', style: {}, checked: false, disabled: false,
    selectedOptions: [], options: [],
    appendChild(c) { this.children.push(c); return c; },
    set textContent(v) { this._text = v; this.innerHTML = ''; },
    get textContent() { return this._text; },
    addEventListener() {}, setAttribute() {},
  };
}
const els = {};
const caps = [
  { capability_id: 'cap-demo-echo', domain: 'demo', name: 'echo', type: 'query', version: '1.0.0',
    required_permissions: ['demo.echo'], execution: { adapter: 'demo.echo' }, status: 'active' },
  { capability_id: 'cap-query-alarms', domain: 'equipment', name: 'query_alarms', type: 'query', version: '1.0.0',
    required_permissions: ['alarm:read'], execution: {}, status: 'deprecated' },
];
const calls = [];
global.document = {
  getElementById(id) { return els[id] || (els[id] = mkEl()); },
  createElement() { return mkEl(); },
  querySelectorAll() { return []; },
  querySelector() { return null; },
  addEventListener() {},
};
global.window = global;
global.location = { search: '' };
global.alert = (m) => calls.push('alert: ' + m);
global.confirm = () => true;
global.EARP = {
  async fetchJSON(url, opts = {}) {
    calls.push(url + ' ' + (opts.method || 'GET'));
    if (url === '/capabilities' && (!opts.method || opts.method === 'GET')) return caps;
    if (url === '/capabilities/cap-demo-echo' && (!opts.method || opts.method === 'GET')) return caps[0];
    if (url === '/capabilities' && opts.method === 'POST') return { capability_id: 'cap-new', status: 'active' };
    if (url.includes('/capabilities/') && opts.method === 'PATCH') return { capability_id: 'cap-demo-echo' };
    if (url.includes('/capabilities/') && opts.method === 'DELETE') return { capability_id: 'cap-demo-echo', status: 'deprecated' };
    return {};
  },
};

(async () => {
try {
  (0, eval)(biz);
  await global.loadCapabilities();
  const out = els['caps-tbody'].innerHTML;
  const checks = [
    ['列表渲染（cap-demo-echo + cap-query-alarms）', out.includes('cap-demo-echo') && out.includes('cap-query-alarms')],
    ['权限 chips 渲染', out.includes('demo.echo') && out.includes('alarm:read')],
    ['execution 摘要（adapter 渲染）', out.includes('demo.echo') && out.includes('未声明（回退猜测）')],
    ['状态区分 active / 已停用', out.includes('active') && out.includes('已停用')],
    ['详情按钮', out.includes("showDetail('cap-demo-echo'")],
    ['编辑按钮', out.includes("openCapModal('cap-demo-echo'")],
    ['停用按钮仅 active 显示', out.includes("deprecateCap('cap-demo-echo'") && !out.includes("deprecateCap('cap-query-alarms'")],
    ['新建能力按钮（页面静态 HTML）', html.includes('openCapModal()')],
  ];
  let fail = 0;
  checks.forEach(([name, ok]) => { console.log((ok ? 'PASS' : 'FAIL') + '  ' + name); if (!ok) fail++; });

  // 新建能力：openCapModal() → 填表 → saveCap() POST /capabilities（带 execution）
  await global.openCapModal();
  els['c-domain'].value = 'equipment';
  els['c-name'].value = 'query_alarms';
  els['c-type'].value = 'query';
  els['c-perms'].value = 'alarm:read';
  els['c-adapter'].value = 'tool.fetch';
  els['c-exec-params'].value = '{"connector_id":"cn-1"}';
  const before = calls.length;
  await global.saveCap();
  const created = calls.slice(before).find(c => c.includes('/capabilities') && c.includes('POST'));
  console.log((created ? 'PASS' : 'FAIL') + '  saveCap 新建 POST /capabilities' + (created ? ' (' + created + ')' : ''));
  if (!created) fail++;

  // 编辑：openCapModal('cap-demo-echo') → GET 详情预填 → PATCH
  await global.openCapModal('cap-demo-echo');
  const prefillOk = els['c-id'].value === 'cap-demo-echo' && els['c-id'].disabled
    && els['c-domain'].value === 'demo' && els['c-adapter'].value === 'demo.echo'
    && els['c-perms'].value.includes('demo.echo');
  console.log((prefillOk ? 'PASS' : 'FAIL') + '  编辑预填（id 锁定/domain/adapter/perms）');
  if (!prefillOk) fail++;
  const before2 = calls.length;
  await global.saveCap();
  const updated = calls.slice(before2).find(c => c.includes('/capabilities/cap-demo-echo') && c.includes('PATCH'));
  console.log((updated ? 'PASS' : 'FAIL') + '  saveCap 编辑 PATCH /capabilities/{id}' + (updated ? ' (' + updated + ')' : ''));
  if (!updated) fail++;

  // 停用：deprecateCap('cap-demo-echo') → DELETE
  const before3 = calls.length;
  await global.deprecateCap('cap-demo-echo');
  const deprecated = calls.slice(before3).find(c => c.includes('/capabilities/cap-demo-echo') && c.includes('DELETE'));
  console.log((deprecated ? 'PASS' : 'FAIL') + '  deprecateCap DELETE /capabilities/{id}' + (deprecated ? ' (' + deprecated + ')' : ''));
  if (!deprecated) fail++;

  // 详情：showDetail('cap-demo-echo') → GET /capabilities/{id}
  const before4 = calls.length;
  await global.showDetail('cap-demo-echo');
  const detailed = calls.slice(before4).find(c => c.includes('/capabilities/cap-demo-echo') && c.includes('GET'));
  console.log((detailed ? 'PASS' : 'FAIL') + '  showDetail GET /capabilities/{id}' + (detailed ? ' (' + detailed + ')' : ''));
  if (!detailed) fail++;

  // Register Demo：空 body POST → 种子 cap-demo-echo
  calls.length = 0;
  const before5 = calls.length;
  await global.registerDemo();
  const demo = calls.slice(before5).find(c => c === '/capabilities POST');
  console.log((demo ? 'PASS' : 'FAIL') + '  registerDemo 空 body POST /capabilities' + (demo ? ' (' + demo + ')' : ''));
  if (!demo) fail++;

  // 坏 JSON 前端拦截：input_schema 非合法 JSON → 不发起请求
  calls.length = 0;
  await global.openCapModal();
  els['c-domain'].value = 'x';
  els['c-name'].value = 'y';
  els['c-perms'].value = 'p';
  els['c-input-schema'].value = '{bad json';
  await global.saveCap();
  const blocked = !calls.some(c => c.includes('POST') && c.includes('/capabilities'));
  const errShown = els['cap-form-error'].textContent.includes('input_schema');
  console.log((blocked && errShown ? 'PASS' : 'FAIL') + '  坏 JSON 前端拦截（不发起请求 + 错误提示）' + (blocked ? '' : ' (发了请求!)'));
  if (!(blocked && errShown)) fail++;

  process.exit(fail ? 1 : 0);
} catch (e) {
  console.log('SMOKE ERROR:', e.message);
  console.log((e.stack || '').split('\n').slice(0, 6).join('\n'));
  process.exit(1);
}
})();
