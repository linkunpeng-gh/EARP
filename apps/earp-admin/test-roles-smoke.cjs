// 冒烟：roles.html 角色域权限管理页（tech-debt #9）
// 验证：脚本可执行 + loadRoles 渲染（admin 徽标/全域标签/权限 chips）+ 新建角色
// （POST /api/roles 携带 is_admin/data_domain_access）+ 编辑（GET /api/roles/{id}）+ 删除
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'pages/roles.html'), 'utf8');
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
const roles = [
  { role_id: 'r1', name: 'Admin', permissions: ['demo.echo', 'tbox.approve'], data_scope: 'all',
    data_domain_access: [], is_admin: true },
  { role_id: 'r-ops', name: '运营', permissions: ['query.alarms'], data_scope: 'org',
    data_domain_access: [{ data_domain_id: 'equipment_data' }], is_admin: false },
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
    if (url === '/api/roles') return roles;
    if (url === '/api/roles/r1') return roles[0];
    if (url.includes('/api/data-domains')) return { items: [{ data_domain_id: 'equipment_data', name: '设备数据' }] };
    if (url.includes('/api/roles/') && opts.method === 'DELETE') return { deleted: true };
    return {};
  },
};

(async () => {
try {
  (0, eval)(biz);
  await global.loadRoles();
  const out = els['role-tbody'].innerHTML;
  const checks = [
    ['角色列表渲染（r1 + r-ops）', out.includes('r1') && out.includes('r-ops')],
    ['名称渲染', out.includes('Admin') && out.includes('运营')],
    ['admin 角色徽标', out.includes('Admin') && out.includes('全域（admin）')],
    ['普通角色白名单域', out.includes('equipment_data')],
    ['权限 chips', out.includes('tbox.approve') && out.includes('query.alarms')],
    ['编辑按钮', out.includes("openRoleModal('r1'")],
    ['删除按钮', out.includes("delRole('r1'")],
    ['新建角色按钮（页面静态 HTML）', html.includes('openRoleModal()')],
  ];
  let fail = 0;
  checks.forEach(([name, ok]) => { console.log((ok ? 'PASS' : 'FAIL') + '  ' + name); if (!ok) fail++; });

  // 新建角色：openRoleModal() → 编辑态 → saveRole() POST /api/roles
  await global.openRoleModal();
  els['r-name'].value = '审计员';
  els['r-perms'].value = 'tbox.approve, query.alarms';
  els['r-admin'].checked = true;
  const before = calls.length;
  await global.saveRole();
  const created = calls.slice(before).find(c => c.includes('/api/roles') && c.includes('POST'));
  console.log((created ? 'PASS' : 'FAIL') + '  saveRole 新建 POST /api/roles' + (created ? ' (' + created + ')' : ''));
  if (!created) fail++;

  // 编辑：openRoleModal('r1') → 预填 + PUT
  await global.openRoleModal('r1');
  const prefillOk = els['r-id'].value === 'r1' && els['r-id'].disabled && els['r-name'].value === 'Admin'
    && els['r-admin'].checked && els['r-perms'].value.includes('tbox.approve');
  console.log((prefillOk ? 'PASS' : 'FAIL') + '  编辑预填（id 锁定/名称/perms/admin 复选）');
  if (!prefillOk) fail++;
  const before2 = calls.length;
  await global.saveRole();
  const updated = calls.slice(before2).find(c => c.includes('/api/roles/r1') && c.includes('PUT'));
  console.log((updated ? 'PASS' : 'FAIL') + '  saveRole 编辑 PUT /api/roles/{id}' + (updated ? ' (' + updated + ')' : ''));
  if (!updated) fail++;

  // 删除
  const before3 = calls.length;
  await global.delRole('r-ops');
  const deleted = calls.slice(before3).find(c => c.includes('/api/roles/r-ops') && c.includes('DELETE'));
  console.log((deleted ? 'PASS' : 'FAIL') + '  delRole DELETE /api/roles/{id}' + (deleted ? ' (' + deleted + ')' : ''));
  if (!deleted) fail++;

  // 2026-08-18 越权修复：非 admin 角色 → 403 → 门禁提示（隐藏管理 UI）
  const err403 = new Error('403 Forbidden'); err403.status = 403;
  global.EARP.fetchJSON = async (url) => { throw err403; };
  const el403 = { innerHTML: 'keep', querySelector: () => null };
  const sec403 = { innerHTML: 'orig' };
  const origGet = global.document.getElementById;
  global.document.getElementById = (id) => id === 'role-tbody' ? el403 : (els[id] || (els[id] = mkEl()));
  global.document.querySelector = () => sec403;
  await global.loadRoles();
  const gateOk = el403.innerHTML === '' && sec403.innerHTML.includes('仅 Admin 角色可访问');
  console.log((gateOk ? 'PASS' : 'FAIL') + '  非 admin 403 → 门禁提示（仅 Admin 角色可访问）');
  if (!gateOk) fail++;
  global.document.getElementById = origGet;

  process.exit(fail ? 1 : 0);
} catch (e) {
  console.log('SMOKE ERROR:', e.message);
  console.log((e.stack || '').split('\n').slice(0, 6).join('\n'));
  process.exit(1);
}
})();
