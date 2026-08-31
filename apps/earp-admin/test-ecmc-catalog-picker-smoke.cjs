/* ECMC N01B — CatalogRefPicker contract test（无浏览器）
 * FE-ECMC-2026-0830 §9 / §20.1：kind、domain、精确版本、active 状态过滤；
 * 不接受 latest、星号、display name 代替精确版本；Case A Fixture 目录 test-only。
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, 'js', 'ecmc-catalog-picker.js'), 'utf8');
global.window = {};
eval(src);

let allOk = true;
function check(name, fn) {
  try { fn(); console.log('  ✓ ' + name); }
  catch (e) { allOk = false; console.error('  ✗ ' + name + ' — ' + e.message); }
}

const adapter = window.ECMC.catalog.fakeAdapter();

check('adapter 标记 test-only（Case A Fixture 仅界面合成）', () => {
  assert.strictEqual(adapter.testOnly, true);
});

check('按 kind 过滤：entity_type 只返回 entity_type', () => {
  const items = adapter.search({ kind: 'entity_type' });
  assert.ok(items.length >= 3);
  items.forEach((it) => assert.strictEqual(it.kind, 'entity_type'));
  assert.ok(items.every((it) => it.status === 'active'));
});

check('按数据域过滤（data_domain_id）：equipment 域不返回 production 条目', () => {
  const prod = adapter.search({ kind: 'metric', domain: 'production_data' });
  const eq = adapter.search({ kind: 'metric', domain: 'equipment_data' });
  assert.ok(prod.some((m) => m.stable_id === 'metric.production_output'));
  assert.ok(eq.some((m) => m.stable_id === 'metric.equipment_availability'));
  assert.ok(!eq.some((m) => m.stable_id === 'metric.production_output'), 'production metric must not leak into equipment domain');
  // 未指定 domain 时返回全部 active 条目
  const all = adapter.search({ kind: 'metric' });
  assert.ok(all.some((m) => m.stable_id === 'metric.production_output') && all.some((m) => m.stable_id === 'metric.equipment_availability'));
});

check('只返回精确版本（不允许 latest / *）', () => {
  const items = adapter.search({ kind: 'metric' });
  items.forEach((it) => {
    assert.ok(!/^latest$|^\*$/.test(it.version), 'exact version only: ' + it.version);
    assert.ok(it.version.match(/^v\d+$/), 'version format vN: ' + it.version);
  });
  // 选择器产生的 ref 必须同时带 kind/stable_id/version
  items.forEach((it) => {
    const ref = { kind: it.kind, stable_id: it.stable_id, version: it.version };
    const found = adapter.lookup(ref);
    assert.ok(found, 'lookup must resolve the exact ref ' + JSON.stringify(ref));
  });
});

check('搜索按业务名称与 stable_id', () => {
  const byName = adapter.search({ kind: 'metric', q: '运输周期' });
  assert.ok(byName.some((m) => m.stable_id === 'metric.haulage_cycle_time'));
  const byId = adapter.search({ kind: 'metric', q: 'haulage_cycle' });
  assert.ok(byId.some((m) => m.stable_id === 'metric.haulage_cycle_time'));
});

check('无结果（kind 不存在/搜索不到）→ 空列表（前端应展示“申请新增目录项”）', () => {
  assert.deepStrictEqual(adapter.search({ kind: 'rule_schema', q: '不存在的规则' }), []);
  assert.deepStrictEqual(adapter.search({ kind: 'metric', domain: 'equipment_data', q: '运输' }), []);
});

check('生产默认 adapter 为 null（不假设真实目录存在）', () => {
  assert.strictEqual(window.ECMC.catalog.getAdapter(), null);
  const fake = window.ECMC.catalog.enableFake();
  assert.strictEqual(window.ECMC.catalog.getAdapter(), fake);
  assert.strictEqual(fake.testOnly, true);
});

check('refFromStructured：精确版本校验（拒绝 latest / * / 空）', () => {
  const c = window.ECMC.catalog;
  assert.deepStrictEqual(c.refFromStructured('metric', 'metric.x', 'v1'), { kind: 'metric', stable_id: 'metric.x', version: 'v1' });
  assert.strictEqual(c.refFromStructured('metric', 'metric.x', 'latest'), null);
  assert.strictEqual(c.refFromStructured('metric', 'metric.x', '*'), null);
  assert.strictEqual(c.refFromStructured('metric', 'metric.x', ''), null);
  assert.strictEqual(c.refFromStructured('metric', '', 'v1'), null);
  assert.strictEqual(c.validateExactVersion('v1'), true);
  assert.strictEqual(c.validateExactVersion('latest'), false);
  assert.strictEqual(c.validateExactVersion('*'), false);
});

process.exit(allOk ? 0 : 1);
