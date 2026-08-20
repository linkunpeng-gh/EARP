// 冒烟：data-source.html 中台对接页（M3 前端）
// 验证：loadAll 渲染连接列表/数据源列表/live 面板 / createDataSource 组装 field_mapping +
//       POST /import/connector / syncDS 触发 / liveFetch 取数
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'pages/data-source.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const biz = scripts[scripts.length - 1];

function mkEl() {
  return {
    children: [], innerHTML: '', _text: '', value: '', style: {}, checked: false,
    selectedOptions: [], options: [],
    appendChild(c) { this.children.push(c); return c; },
    scrollIntoView() {},
    set textContent(v) { this._text = v; this.innerHTML = ''; },
    get textContent() { return this._text; },
    addEventListener() {}, setAttribute() {},
  };
}
const els = {};
['cn-id', 'cn-type', 'cn-config', 'ds-connector', 'ds-etype', 'ds-mode',
  'ds-name-field', 'ds-code-field', 'attr-rows', 'rel-rows', 'ds-msg', 'ds-list', 'cn-list', 'live-list']
  .forEach(function (id) { els[id] = mkEl(); });

const connectors = { items: [
  { connector_id: 'cn-mid-rest', adapter_type: 'rest', status: 'active', config: { credential_masked: true } },
  { connector_id: 'cn-mid-oee', adapter_type: 'rest', status: 'active', config: { credential_masked: true } },
] };
const entityTypes = [
  { entity_type_id: 'equipment', kind: 'object', status: 'active' },
  { entity_type_id: 'oee', kind: 'metric', status: 'active' },
];
const relTypes = [
  { relation_type_id: 'manufactured_by', target_type: 'supplier', status: 'active' },
  { relation_type_id: 'belongs_to', target_type: 'production_line', status: 'active' },
];
const dataSources = { items: [
  { data_source_id: 'ds-sync-1', connector_id: 'cn-mid-rest', entity_type_id: 'equipment',
    source_mode: 'synced', last_sync_status: 'completed', last_synced_at: '2026-08-20T03:00:00+00:00',
    field_mapping: { name_field: 'equip_name', business_code_field: 'equip_code' } },
  { data_source_id: 'ds-virt-1', connector_id: 'cn-mid-oee', entity_type_id: 'oee',
    source_mode: 'virtual', last_sync_status: null, last_synced_at: null,
    field_mapping: { name_field: 'equip_name', business_code_field: 'equip_code' } },
] };
const entities = { items: [
  { entity_id: 'ent-oee-1', name: 'CNC-01 OEE', business_code: 'CNC-OEE-01' },
] };

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
global.EARP = {
  async fetchJSON(url, opts = {}) {
    calls.push(url + ' ' + (opts.method || 'GET') + (opts.body ? ' ' + opts.body : ''));
    if (url === '/v1/ontology/connectors') return connectors;
    if (url === '/v1/ontology/entity-types') return entityTypes;
    if (url === '/v1/ontology/relation-types') return relTypes;
    if (url === '/v1/ontology/data-sources') return dataSources;
    if (url.includes('/v1/ontology/entities?entity_type_id=')) return entities;
    if (url.includes('/live')) return { entity_id: 'ent-oee-1', data: { oee: 0.87 } };
    if (url.startsWith('/v1/ontology/import/connector')) return { data_source_id: 'ds-new', job_status: 'queued' };
    return {};
  },
};

(async () => {
let okCount = 0, failCount = 0;
function check(name, cond) {
  if (cond) { okCount++; console.log('  ✓ ' + name); }
  else { failCount++; console.log('  ✗ FAIL: ' + name); }
}
try {
  (0, eval)(biz);
  await global.loadAll();

  check('连接列表渲染（2 个 connector + 脱敏标记）', els['cn-list'].innerHTML.includes('cn-mid-rest') && els['cn-list'].innerHTML.includes('cn-mid-oee') && els['cn-list'].innerHTML.includes('配置已加密'));
  check('数据源表单下拉填充（connector + 实体类型）', els['ds-connector'].innerHTML.includes('cn-mid-rest') && els['ds-etype'].innerHTML.includes('oee'));
  check('数据源列表渲染（synced 状态徽标 + virtual）', els['ds-list'].innerHTML.includes('ds-sync-1') && els['ds-list'].innerHTML.includes('✅ 完成') && els['ds-list'].innerHTML.includes('🟢 virtual'));
  check('live 面板渲染 virtual 数据源', els['live-list'].innerHTML.includes('ds-virt-1') || els['live-list'].innerHTML.includes('oee'));

  // createDataSource 组装 field_mapping 正确
  els['ds-connector'].value = 'cn-mid-rest';
  els['ds-etype'].value = 'equipment';
  els['ds-mode'].value = 'synced';
  els['ds-name-field'].value = 'equip_name';
  els['ds-code-field'].value = 'equip_code';
  const attr = mkEl(), attr2 = mkEl(); attr.value = 'model'; attr2.value = 'model';
  const attrRow = mkEl(); attrRow.children = [attr, attr2];
  els['attr-rows'].children = [attrRow];
  const relSel = mkEl(), relTf = mkEl(); relSel.value = 'manufactured_by'; relTf.value = 'supplier_code';
  const relRow = mkEl(); relRow.children = [relSel, relTf];
  els['rel-rows'].children = [relRow];
  await global.createDataSource();
  const posted = calls.filter(c => c.startsWith('/v1/ontology/import/connector POST'))[0];
  const body = JSON.parse(posted.split(' POST ')[1]);  check('createDataSource 提交 field_mapping 组装正确', body.field_mapping.name_field === 'equip_name' && body.field_mapping.business_code_field === 'equip_code'
    && body.field_mapping.attr_fields.model === 'model' && body.field_mapping.relations[0].relation_type === 'manufactured_by' && body.field_mapping.relations[0].target_field === 'supplier_code');
  check('注册成功提示（含入队状态）', els['ds-msg'].textContent.includes('已注册') && els['ds-msg'].textContent.includes('入队'));

  // syncDS 触发
  await global.syncDS('ds-sync-1');
  check('syncDS 触发同步端点', calls.some(c => c.startsWith('/v1/ontology/data-sources/ds-sync-1/sync POST')));

  // live 面板
  await global.loadLiveEntities('ds-virt-1', 'oee');
  check('loadLiveEntities 渲染实体行', els['live-ents-ds-virt-1'].innerHTML.includes('CNC-OEE-01'));
  await global.liveFetch('ent-oee-1');
  check('liveFetch 取数渲染返回值', els['livev-ent-oee-1'].textContent.includes('oee'));

} catch (e) {
  console.log('  ✗ EXCEPTION: ' + e.stack);
  failCount++;
}
console.log((okCount + failCount) + ' checks, ' + okCount + ' passed, ' + failCount + ' failed');
process.exit(failCount ? 1 : 0);
})();
