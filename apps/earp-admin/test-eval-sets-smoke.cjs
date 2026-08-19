// 冒烟：eval-sets.html 评估管理页（B6）
// 验证：集合卡片渲染（3 内置 + 新建）/ selectSet 用例表 + 表单 / addCase POST /
//       runEval POST / loadRuns 历史渲染 / showRunDetail 明细渲染
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'pages/eval-sets.html'), 'utf8');
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
// 预创建表单输入元素（DOM stub 不解析 innerHTML）
['nc-query', 'nc-dd', 'nc-kb', 'nc-intent', 'nc-entities', 'nc-relations'].forEach(function (id) { els[id] = mkEl(); });
const sets = [
  { eval_set_id: 'evs-t-routing', kind: 'routing', name: '路由评估集', source: 'builtin', case_count: 5,
    description: '路由评估集', thresholds: { dd_accuracy: 0.9, kb_accuracy: 0.9 },
    latest_run: { status: 'completed', mode: 'rules', finished_at: '2026-08-17T10:00:00+00:00',
      summary: { n: 5, dd_accuracy: 1.0 }, gates: { overall: true } } },
  { eval_set_id: 'evs-t-understanding', kind: 'understanding', name: '理解层评估集', source: 'builtin', case_count: 111,
    description: '理解层评估集', thresholds: { intent_accuracy: 0.85, entity_recall: 0.9, relation_accuracy: 0.8, schema_violations: 0 },
    latest_run: null },
  { eval_set_id: 'evs-t-planning', kind: 'planning', name: 'Plan 层评估集', source: 'builtin', case_count: 111,
    description: 'Plan 层评估集', thresholds: { strategy_hit_rate: 0.95 },
    latest_run: null },
];
const setDetail = { eval_set_id: 'evs-t-routing', kind: 'routing', name: '路由评估集', enabled: true,
  thresholds: { dd_accuracy: 0.9, kb_accuracy: 0.9 },
  cases: [
    { case_id: 'evc-t-001', query: '报销制度是什么', expected: { data_domain_id: 'finance_data', knowledge_base_id: '费用报销流程手册' }, note: '语义路由', enabled: true },
    { case_id: 'evc-t-002', query: '设备报警阈值是多少', expected: { data_domain_id: 'equipment_data' }, note: '', enabled: true },
  ] };
// 大集合（理解层 12 条）——折叠场景
const setDetailBig = { eval_set_id: 'evs-t-understanding', kind: 'understanding', name: '理解层评估集', enabled: true,
  thresholds: { intent_accuracy: 0.85 },
  cases: Array.from({ length: 12 }, (_, i) => ({ case_id: 'evc-b' + i, query: '理解用例 ' + (i + 1),
    expected: { intent: 'FACT', entities: [], relations: [] }, note: '', enabled: true })) };
const runs = [
  { run_id: 'evr-1', mode: 'rules', status: 'completed', started_at: '2026-08-17T10:00:00+00:00', finished_at: '2026-08-17T10:00:01+00:00',
    summary: { n: 5, dd_accuracy: 1.0 }, gates: { overall: true } },
  { run_id: 'evr-2', mode: 'llm', status: 'running', started_at: '2026-08-17T10:05:00+00:00', finished_at: null, summary: {}, gates: {} },
  { run_id: 'evr-3', mode: 'llm', status: 'cancelled', started_at: '2026-08-17T09:00:00+00:00', finished_at: '2026-08-17T09:10:00+00:00', summary: {}, gates: {} },
];
const runDetail = { run_id: 'evr-1', mode: 'rules', status: 'completed', started_at: '2026-08-17T10:00:00+00:00',
  summary: { n: 5, passed: 5, dd_accuracy: 1.0 }, gates: { dd_accuracy: true, overall: true },
  results: [
    { case_id: 'evc-t-001', query: '报销制度是什么', passed: true,
      actual: { candidate_dds: ['finance_data'], plan_name: 'plan_fact', mode: 'rules', trace: ['DD_ROUTING', 'KB_ROUTING', 'VECTOR_SEARCH'], evidence_channels: ['chunk'], evidence_count: 5 }, detail: { dd_ok: true }, latency_ms: 3 },
    { case_id: 'evc-t-002', query: '设备报警阈值是多少', passed: false, actual: { candidate_dds: [] }, detail: { dd_ok: false, expected_dd: 'equipment_data' }, latency_ms: 2 },
    ...Array.from({ length: 20 }, (_, i) => ({ case_id: 'evc-f' + i, query: '填充用例 ' + (i + 1), passed: true, actual: {}, detail: {}, latency_ms: 1 })),
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
global.prompt = (label, dflt) => (label.includes('类型') ? 'understanding' : '我的集合');
global.setInterval = () => 1;
global.clearInterval = () => {};
global.EARP = {
  async fetchJSON(url, opts = {}) {
    calls.push(url + ' ' + (opts.method || 'GET'));
    if (url === '/v1/evaluations/sets') return { items: sets };
    if (url.includes('/v1/evaluations/sets/') && url.includes('/runs')) return { run_id: 'evr-new', status: 'running', mode: 'rules' };
    if (url.includes('/v1/evaluations/runs/')) return runDetail;
    if (url.startsWith('/v1/evaluations/runs')) return { items: runs };
    if (url.includes('evs-t-understanding')) return setDetailBig;
    if (url.startsWith('/v1/evaluations/sets/')) return setDetail;
    return {};
  },
};

(async () => {
try {
  (0, eval)(biz);
  // 1) 集合卡片渲染
  await global.init();
  let grid = els['sets-grid'].innerHTML;
  const checks = [
    ['三套内置集合卡片', grid.includes('路由评估集') && grid.includes('理解层评估集') && grid.includes('Plan 层评估集')],
    ['最新跑分徽标（✅ 通过）', grid.includes('✅ 通过') && grid.includes('DD 路由命中 100%')],
    ['门槛显示（≥ 90%）', grid.includes('门槛') && grid.includes('DD 路由命中 ≥ 90%')],
    ['新建集合卡片', grid.includes('新建自定义评估集')],
    ['规则层/LLM 跑分按钮', grid.includes('规则层跑分') && grid.includes('LLM 跑分')],
    // T3: 治理操作
    ['同步内置模板按钮（老 builtin 集 seed_version 落后）', grid.includes('同步内置模板')],
    ['导出按钮', grid.includes('>导出<')],
    ['导入评估集卡片', grid.includes('导入评估集')],
    ['同步按钮隐藏（builtin 已最新版本）', !global.showSyncBtn({ source: 'builtin', seed_version: 1, eval_set_id: 'x' }).includes('同步')],
    ['同步按钮隐藏（custom 集）', !global.showSyncBtn({ source: 'custom', eval_set_id: 'x' }).includes('同步')],
    ['进度条渲染（N/总数 + 百分比）', global.progressBar({ completed: 2, total: 5, percent: 40 }).includes('2/5') && global.progressBar({ completed: 2, total: 5, percent: 40 }).includes('40%')],
  ];

  // 2) 选中集合 → 用例表 + 表单
  await global.selectSet('evs-t-routing');
  checks.push(['选中集合标题', els['sd-title'].textContent === '路由评估集']);
  checks.push(['用例表渲染', els['cases-tbody'].innerHTML.includes('报销制度是什么')]);
  checks.push(['routing 新增表单（期望 DD 输入框）', els['nc-fields-inputs'].innerHTML.includes('nc-dd')]);

  // 3) 新增用例 → POST
  els['nc-query'].value = '新产品发布流程';
  els['nc-dd'].value = 'hr_data';
  await global.addCase();
  checks.push(['新增用例 POST 到 /sets/{id}/cases', calls.some(c => c.includes('/cases POST'))]);

  // 4) 跑分触发 → POST runs
  await global.runEvalFor('evs-t-routing', 'rules');
  checks.push(['触发跑分 POST /runs', calls.some(c => c.includes('/runs?mode=rules POST'))]);

  // 5) 跑分历史渲染
  await global.loadRuns();
  checks.push(['历史表渲染（completed + running + cancelled）', els['runs-tbody'].innerHTML.includes('evr-1') && els['runs-tbody'].innerHTML.includes('⏳') && els['runs-tbody'].innerHTML.includes('已取消')]);
  checks.push(['running 行显示停止按钮', els['runs-tbody'].innerHTML.includes('停止')]);

  // 6) 跑分明细渲染（含失败原因）
  await global.showRunDetail('evr-1');
  const rd = els['rd-tbody'].innerHTML;
  checks.push(['明细逐用例渲染', rd.includes('报销制度是什么') && rd.includes('✅') && rd.includes('❌')]);
  checks.push(['失败原因展示', rd.includes('DD 未命中: equipment_data')]);
  checks.push(['Plan 层执行结果可读化（trace 步骤串）', rd.includes('DD_ROUTING → KB_ROUTING → VECTOR_SEARCH')]);
  checks.push(['Plan 层 evidence 徽标', rd.includes('📊 chunk') && rd.includes('5 条证据')]);
  const rdM = els['rd-metrics'].innerHTML;
  checks.push(['明细指标卡含门槛（≥ 90%）', rdM.includes('门槛') && rdM.includes('≥ 90%')]);
  checks.push(['明细指标卡含达标状态', rdM.includes('✅') && rdM.includes('DD 路由命中')]);

  // 7) 明细折叠（22 条 → 默认 20 + 提示，展开后全量）
  const rdRows = () => (els['rd-tbody'].innerHTML.match(/<tr/g) || []).length;
  checks.push(['明细默认折叠（20 条 + 提示）', rdRows() === 21 && els['rd-tbody'].innerHTML.includes('已显示前 20')]);
  checks.push(['明细展开按钮显示', els['rd-toggle'].textContent === '展开全部 (22)']);
  await global.toggleRunCases();
  checks.push(['明细展开全量（22 条）', rdRows() === 22 && els['rd-toggle'].textContent === '收起']);
  await global.toggleRunCases();  // 收起还原

  // 8) 大集合用例折叠（理解层 12 条 → 默认 10 + 提示，展开后全量）
  await global.selectSet('evs-t-understanding');
  const caseRows = () => (els['cases-tbody'].innerHTML.match(/<tr/g) || []).length;
  checks.push(['大集合用例默认折叠（10 条 + 提示）', caseRows() === 11 && els['cases-tbody'].innerHTML.includes('已显示前 10')]);
  checks.push(['用例展开按钮显示', els['cases-toggle'].textContent === '展开全部 (12)']);
  global.toggleCases();
  checks.push(['用例展开全量（12 条）', caseRows() === 12 && els['cases-toggle'].textContent === '收起']);

  const failed = checks.filter(([, ok]) => !ok);
  console.log('eval-sets smoke:', checks.length, 'checks,', checks.length - failed.length, 'passed');
  checks.forEach(([name, ok]) => console.log('  ' + (ok ? '✅' : '❌') + ' ' + name));
  if (failed.length) { console.error('FAILED:', failed.map(f => f[0])); process.exit(1); }
} catch (e) {
  console.error('smoke error:', e);
  process.exit(1);
}
})();
