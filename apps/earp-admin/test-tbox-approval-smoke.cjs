// 冒烟：tbox.html 审批流前端（tech-debt #12）
// 验证：脚本可执行 + loadPending 渲染待审批区（批准/拒绝按钮）+ saveEt 提交变更请求
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'pages/tbox.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const biz = scripts[scripts.length - 1];

function mkEl() {
  return {
    children: [], innerHTML: '', _text: '', value: '', style: {}, checked: false,
    selectedOptions: [], options: [],
    appendChild(c) { this.children.push(c); return c; },
    set textContent(v) { this._text = v; this.innerHTML = ''; },
    get textContent() { return this._text; },
    addEventListener() {}, setAttribute() {},
  };
}
const els = {};
const pendingRows = [
  { change_id: 'tc-1', requested_by: 'u1', change_type: 'entity_type', action: 'create',
    target_id: 'new_equip', payload: { name: '新设备' }, created_at: '2026-08-17T10:00:00+00:00' },
  { change_id: 'tc-2', requested_by: 'u1', change_type: 'relation_type', action: 'deprecate',
    target_id: 'manufactured_by', payload: {}, created_at: '2026-08-17T10:01:00+00:00' },
];
const calls = [];
global.document = {
  getElementById(id) { return els[id] || (els[id] = mkEl()); },
  createElement() { return mkEl(); },
  querySelector() { return null; },
  addEventListener() {},
};
global.window = global;
global.location = { search: '' };
global.alert = (m) => calls.push('alert: ' + m);
global.confirm = () => true;
global.prompt = () => '测试原因';
global.EARP = {
  async fetchJSON(url, opts = {}) {
    calls.push(url + ' ' + (opts.method || 'GET'));
    if (url.includes('/tbox/changes?status=pending')) return pendingRows;
    if (url.includes('/tbox/changes/') && url.includes('/approve')) return { status: 'applied' };
    if (url.includes('/entity-types')) return [{ entity_type_id: 'equipment', name: '设备', status: 'active', kind: 'object' }];
    if (url.includes('/relation-types')) return [{ relation_type_id: 'manufactured_by', name: '由…制造', status: 'active' }];
    if (url.includes('/api/data-domains')) return [];
    return {};
  },
};

(async () => {
try {
  (0, eval)(biz);
    // loadPending 渲染
    await global.loadPending();
    const sec = els['pending-section'];
    const tbody = els['pc-tbody'];
    const out = tbody.innerHTML;
    const checks = [
      ['待审批区显示', sec.style.display !== 'none'],
      ['请求人渲染', out.includes('u1')],
      ['动作标签（新增/停用）', out.includes('新增') && out.includes('停用')],
      ['目标+名称', out.includes('new_equip') && out.includes('新设备')],
      ['批准按钮', out.includes('approveChange')],
      ['拒绝按钮', out.includes('rejectChange')],
    ];
    let fail = 0;
    checks.forEach(([name, ok]) => { console.log((ok ? 'PASS' : 'FAIL') + '  ' + name); if (!ok) fail++; });
    // 审批调用
    await global.approveChange('tc-1');
    const appr = calls.find(c => c.includes('/approve'));
    console.log((appr ? 'PASS' : 'FAIL') + '  approveChange 调 /tbox/changes/{id}/approve' + (appr ? ' (' + appr + ')' : ''));
    if (!appr) fail++;
    // saveEt 提交变更请求（不再直调 /entity-types POST）
    ['et-id', 'et-name'].forEach(function (id) { if (!els[id]) els[id] = { value: '' }; });
    els['et-id'].value = 'new_x'; els['et-name'].value = '新X';
    const before = calls.length;
    await global.saveEt();
    const sub = calls.slice(before).find(c => c.includes('/tbox/changes') && c.includes('POST'));
    console.log((sub ? 'PASS' : 'FAIL') + '  saveEt 提交 /tbox/changes (POST)' + (sub ? ' (' + sub + ')' : ''));
    if (!sub) fail++;
    process.exit(fail ? 1 : 0);
} catch (e) {
  console.log('SMOKE ERROR:', e.message);
  console.log((e.stack || '').split('\n').slice(0, 6).join('\n'));
  process.exit(1);
}
})();
