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
    target_id: 'new_equip', payload: { name: '新设备' }, created_at: '2026-08-17T10:00:00+00:00', can_approve: true },
  { change_id: 'tc-2', requested_by: 'u1', change_type: 'relation_type', action: 'deprecate',
    target_id: 'manufactured_by', payload: {}, created_at: '2026-08-17T10:01:00+00:00', can_approve: true },
  { change_id: 'tc-3', requested_by: 'u2', change_type: 'entity_type', action: 'reactivate',
    target_id: 'old_type', payload: {}, created_at: '2026-08-17T10:02:00+00:00', can_approve: false },
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
const _origFetch = global.EARP.fetchJSON;

(async () => {
try {
  (0, eval)(biz);
    // loadPending 渲染
    await global.loadPending();
    const tbody = els['pc-tbody'];
    const out = tbody.innerHTML;
    const checks = [
      ['待审批区渲染（有 pending 行）', out.includes('new_equip') && out.includes('新增')],
      ['请求人渲染', out.includes('u1')],
      ['动作标签（新增/停用）', out.includes('新增') && out.includes('停用')],
      ['目标+名称', out.includes('new_equip') && out.includes('新设备')],
      ['批准按钮（can_approve=true）', out.includes('approveChange')],
      ['拒绝按钮（can_approve=true）', out.includes('rejectChange')],
      // tech-debt #9 审批人角色门禁：can_approve=false → 隐藏按钮 + 提示
      ['无权限行提示（can_approve=false）', out.includes('无审批权限') && !out.includes("approveChange('tc-3'")],
    ];
    let fail = 0;
    checks.forEach(([name, ok]) => { console.log((ok ? 'PASS' : 'FAIL') + '  ' + name); if (!ok) fail++; });
    // 审批调用
    await global.approveChange('tc-1');
    const appr = calls.find(c => c.includes('/approve'));
    console.log((appr ? 'PASS' : 'FAIL') + '  approveChange 调 /tbox/changes/{id}/approve' + (appr ? ' (' + appr + ')' : ''));
    if (!appr) fail++;
    // 空态：无 pending 时显示提示
    global.EARP.fetchJSON = async (url, opts = {}) => {
      if (url.includes('/tbox/changes?status=pending')) return [];
      return {};
    };
    await global.loadPending();
    const emptyOut = els['pc-tbody'].innerHTML;
    console.log((emptyOut.includes('暂无待审批变更') ? 'PASS' : 'FAIL') + '  空态提示（无 pending 显示说明）');
    if (!emptyOut.includes('暂无待审批变更')) fail++;
    global.EARP.fetchJSON = _origFetch;

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
