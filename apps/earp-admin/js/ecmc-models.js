/* ════════════════════════════════════════════════════════════════════════
 * ECMC N01B — 模型资产页（ecmc-models.js）
 *
 * 设计: FE-ECMC-2026-0830 §7 模型资产页、§4.2 路由 ecmc-models.html?type=causal
 * 表格字段：模型名称+短 ID / 类型 / 诊断目标 / 数据域 / 最新版本 / Active Version /
 *           最近更新 / 操作（查看·继续编辑·复制草稿·更多）
 * 数据 hydration：GET /causal-models 仅返回摘要（无 versions），统一经
 *   ECMC.common.hydrateModels 补取模型详情与最新 Version 内容后构建 view model。
 * 新建模型向导 §7.2：第一步选类型（仅因果可用）；所有可执行字段（数据域/实体类型/
 *   时间窗口）只能从受控目录选择；无 Catalog adapter 时禁止创建并引导目录申请。
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var api = window.ECMC.api;
  var common = window.ECMC.common;
  var esc = common.esc;

  var state = { hydrated: [], type: 'all', q: '', domain: '', status: '' };

  function targetSummary(h) {
    var t = h.latestDetail && h.latestDetail.diagnostic_target;
    if (!t) return '<span class="cell-id">—</span>';
    return esc((t.entry_point || '') + ' · ' + (t.direction || '') + (t.target_entity_type_ref ? ' · ' + t.target_entity_type_ref.stable_id : ''));
  }

  function activeVersionCell(h) {
    var ap = h.model.active_pointer || {};
    if (!ap.model_version_id) return '<span class="cell-id">未激活</span>';
    var v = h.versions.find(function (x) { return x.model_version_id === ap.model_version_id; });
    return '<span class="ecmc-badge active">运行中</span> <span class="cell-mono">' + esc(ap.model_version_id) + '</span>'
      + (v ? ' <span class="cell-id">v' + esc(v.version) + '</span>' : '');
  }

  function latestVersionCell(h) {
    var v = h.latestVersion;
    if (!v) return '<span class="cell-id">—</span>';
    return '<span class="cell-mono">v' + esc(v.version) + '</span> ' + common.governanceBadge(v.status)
      + '<div class="cell-id">' + esc(v.model_version_id) + '</div>';
  }

  function statusFilterOptions() {
    return ['draft', 'in_review', 'published', 'superseded', 'archived'];
  }

  function rowHtml(h) {
    var latest = h.latestVersion;
    var actions =
      '<button class="row-action" data-act="view">查看</button>'
      + (latest && latest.status === 'draft' ? '<button class="row-action" data-act="edit">继续编辑</button>' : '')
      + (latest ? '<button class="row-action" data-act="clone">复制草稿</button>' : '');
    return '<tr data-model="' + esc(h.model.model_id) + '">'
      + '<td><div class="cell-primary">' + esc(h.model.name || '（未命名）') + '</div><div class="cell-id">' + esc(h.model.model_id) + '</div></td>'
      + '<td>' + common.typeBadge('causal') + '</td>'
      + '<td>' + targetSummary(h) + '</td>'
      + '<td class="cell-mono">' + esc(h.model.data_domain_id || '—') + '</td>'
      + '<td>' + latestVersionCell(h) + '</td>'
      + '<td>' + activeVersionCell(h) + '</td>'
      + '<td>' + esc(common.fmtTime((h.latestDetail && h.latestDetail.updated_at) || h.model.updated_at || h.model.created_at)) + '</td>'
      + '<td class="cell-actions">' + actions + '</td>'
      + '</tr>';
  }

  function filtered() {
    return state.hydrated.filter(function (h) {
      var latest = h.latestVersion;
      var q = state.q.toLowerCase();
      var statusOk = !state.status || (latest && latest.status === state.status);
      if (!statusOk) return false;
      if (state.domain && h.model.data_domain_id !== state.domain) return false;
      if (q && (h.model.name || '').toLowerCase().indexOf(q) === -1 && (h.model.model_id || '').toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
  }

  function render() {
    var rows = filtered();
    var body = document.getElementById('ecmc-model-rows');
    var count = document.getElementById('ecmc-model-count');
    var empty = document.getElementById('ecmc-model-empty');
    if (!rows.length) {
      body.innerHTML = '';
      empty.style.display = 'block';
      count.textContent = '(0)';
      return;
    }
    empty.style.display = 'none';
    body.innerHTML = rows.map(rowHtml).join('');
    count.textContent = '(' + rows.length + ')';
    Array.prototype.forEach.call(body.querySelectorAll('tr[data-model]'), function (tr) {
      tr.addEventListener('click', function (e) {
        var act = e.target.closest('[data-act]');
        if (act) { e.stopPropagation(); handleAction(tr.dataset.model, act.dataset.act); return; }
        openModel(tr.dataset.model);
      });
    });
  }

  function openModel(modelId) {
    location.href = common.editorUrl(modelId);
  }

  function handleAction(modelId, act) {
    var h = state.hydrated.find(function (x) { return x.model.model_id === modelId; });
    var latest = h && h.latestVersion;
    if (act === 'view') openModel(modelId);
    if (act === 'edit') location.href = common.editorUrl(modelId, latest.model_version_id);
    if (act === 'clone') cloneVersion(h.model, latest);
  }

  async function cloneVersion(model, version) {
    if (!version) return common.toast('该模型没有可复制的版本', 'warn');
    var ok = await common.confirmDialog('复制草稿', '为「' + esc(model.name) + '」v' + esc(version.version) + ' 创建新的 Draft Version？<br>Snapshot / 审核 / 编译记录不会被复制。', '复制草稿');
    if (!ok) return;
    try {
      var res = await api.post('/causal-models/' + encodeURIComponent(model.model_id) + '/versions', { clone_from_version_id: version.model_version_id }, { idempotencyKey: api.idempotencyKey() });
      common.toast('已创建新草稿 v' + res.body.version, 'success');
      location.href = common.editorUrl(model.model_id, res.body.model_version_id);
    } catch (e) { common.errorBar(document.getElementById('ecmc-errorbar'), e); }
  }

  async function loadModels() {
    try {
      var res = await api.get('/causal-models');
      state.hydrated = await common.hydrateModels(res.body || []);
      populateFilters();
      render();
    } catch (e) {
      common.errorBar(document.getElementById('ecmc-errorbar'), e);
      document.getElementById('ecmc-model-rows').innerHTML = '';
      document.getElementById('ecmc-model-empty').style.display = 'block';
    }
  }

  function populateFilters() {
    var domains = {};
    state.hydrated.forEach(function (h) { if (h.model.data_domain_id) domains[h.model.data_domain_id] = true; });
    var domainSel = document.getElementById('ecmc-model-domain');
    domainSel.innerHTML = '<option value="">全部数据域</option>'
      + Object.keys(domains).sort().map(function (d) { return '<option value="' + esc(d) + '">' + esc(d) + '</option>'; }).join('');
    var statusSel = document.getElementById('ecmc-model-status');
    statusSel.innerHTML = '<option value="">全部状态</option>'
      + statusFilterOptions().map(function (s) { return '<option value="' + s + '">' + esc(common.GOVERNANCE_LABELS[s] || s) + '</option>'; }).join('');
  }

  /* ── 无可用目录 adapter 时的引导（§9.3：生产 Catalog 合同未签署，不假设目录存在）── */
  function catalogUnavailableDialog() {
    common.dialog(
      '<div class="ecmc-dialog-head"><h3>受控目录不可用</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="info-box">生产 Catalog browse/search API 尚未签署（FE-ECMC-2026-0830 §21）。'
      + '模型创建需要从受控目录选择数据域 / 实体类型 / 时间窗口；在目录合同签署前无法创建。</div>'
      + '<p style="font-size:0.78rem;color:var(--text-tertiary)">可选：<br>'
      + '1. 使用 <code>?catalog=fake</code> 的 test-only 适配器进行界面合成；<br>'
      + '2. 先到「目录扩展申请」提出缺项（需 Catalog Resolver 履约后才能引用）。</p>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>关闭</button>'
      + '<button class="btn" data-goto>前往目录申请</button></div>'
    ).on('[data-goto]', 'click', function () { location.href = common.withCatalogParam('ecmc-catalog-requests.html'); });
  }

  /* ── 新建模型向导（§7.2）：第一步选类型，仅因果可用；可执行字段只能受控选择 ── */
  function openNewModelWizard() {
    if (!ECMC.catalog.getAdapter()) { catalogUnavailableDialog(); return; }
    var d = common.dialog(
      '<div class="ecmc-dialog-head"><h3>新建模型</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="ecmc-field"><label>模型类型</label>'
      + '<div style="display:flex;gap:0.5rem">'
      + '<button class="btn" data-type="causal" style="flex:1">因果模型<span style="display:block;font-size:0.68rem;font-weight:400;opacity:0.85">解释“为什么发生”</span></button>'
      + '<button class="btn secondary" disabled style="flex:1">决策模型<span style="display:block;font-size:0.68rem;font-weight:400;opacity:0.85">规划中</span></button>'
      + '<button class="btn secondary" disabled style="flex:1">任务模型<span style="display:block;font-size:0.68rem;font-weight:400;opacity:0.85">规划中</span></button>'
      + '</div></div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button></div>'
    );
    d.on('[data-type="causal"]', 'click', function () { d.close(); wizardStepDomain(); });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  /* 向导步骤：数据域 → 实体类型 → 方向/入口/时间窗口 → 名称/说明 → 确认签名 */
  function wizardStepDomain() {
    var d = common.dialog('<div class="ecmc-dialog-head"><h3>新建因果模型 · 1/4 选择数据域</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body"><div id="wizard-domain-picker"></div>'
      + '<div class="info-box">目标数据域决定可引用的受控目录范围；创建后不可更改。</div></div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button>'
      + '<button class="btn" data-next disabled>下一步</button></div>');
    var picker = ECMC.catalog.Picker(d.el.querySelector('#wizard-domain-picker'), {
      kind: 'data_domain', emptyLabel: '选择数据域', onChange: function (ref, entry) {
        d.el.querySelector('[data-next]').disabled = false;
        d.el.querySelector('[data-next]').dataset.ref = JSON.stringify(ref);
        d.el.querySelector('[data-next]').dataset.domainId = (entry && entry.data_domain_id) || '';
      },
    });
    d.on('[data-next]', 'click', function () {
      var ref = JSON.parse(d.el.querySelector('[data-next]').dataset.ref);
      var domainId = d.el.querySelector('[data-next]').dataset.domainId || ref.stable_id;
      d.close();
      wizardStepEntity(ref, domainId);
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  function wizardStepEntity(domainRef, domainId) {
    var d = common.dialog('<div class="ecmc-dialog-head"><h3>新建因果模型 · 2/4 目标实体类型</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body"><div id="wizard-entity-picker"></div>'
      + '<div class="info-box">目标实体类型将冻结进 DiagnosticTarget signature，创建后不可修改。</div></div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button>'
      + '<button class="btn" data-next disabled>下一步</button></div>');
    var picker = ECMC.catalog.Picker(d.el.querySelector('#wizard-entity-picker'), {
      kind: 'entity_type', domain: domainId, emptyLabel: '选择目标实体类型', onChange: function (ref) {
        d.el.querySelector('[data-next]').disabled = false;
        d.el.querySelector('[data-next]').dataset.ref = JSON.stringify(ref);
      },
    });
    d.on('[data-next]', 'click', function () {
      var ref = JSON.parse(d.el.querySelector('[data-next]').dataset.ref);
      d.close();
      wizardStepTarget(domainRef, domainId, ref);
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  function wizardStepTarget(domainRef, domainId, entityRef) {
    var d = common.dialog('<div class="ecmc-dialog-head"><h3>新建因果模型 · 3/4 诊断方向与入口</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="ecmc-field"><label>诊断方向（direction）</label><select id="w-direction">'
      + '<option value="down">下降（down）</option><option value="up">上升（up）</option>'
      + '<option value="change">变化（change）</option><option value="neutral">无方向（neutral）</option><option value="any">任意（any）</option></select></div>'
      + '<div class="ecmc-field"><label>入口节点 key（entry_point）</label><input id="w-entry" value="production_output" placeholder="例如 production_output"></div>'
      + '<div class="ecmc-field"><label>时间窗口 Schema</label><div id="wizard-window-picker"></div></div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button>'
      + '<button class="btn" data-next disabled>下一步</button></div>');
    ECMC.catalog.Picker(d.el.querySelector('#wizard-window-picker'), {
      kind: 'time_window_schema', domain: domainId, emptyLabel: '选择时间窗口', onChange: function (ref) {
        d.el.querySelector('[data-next]').disabled = false;
        d.el.querySelector('[data-next]').dataset.ref = JSON.stringify(ref);
      },
    });
    d.on('[data-next]', 'click', function () {
      var windowRef = JSON.parse(d.el.querySelector('[data-next]').dataset.ref);
      var target = {
        objective: 'diagnose',
        entry_point: d.el.querySelector('#w-entry').value.trim() || 'production_output',
        direction: d.el.querySelector('#w-direction').value,
        domain: domainRef.stable_id,
        target_entity_type_ref: entityRef,
        time_window_schema_ref: windowRef,
      };
      d.close();
      wizardStepConfirm(domainRef, target);
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  function wizardStepConfirm(domainRef, target) {
    var d = common.dialog('<div class="ecmc-dialog-head"><h3>新建因果模型 · 4/4 名称与确认</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="ecmc-field"><label>模型名称</label><input id="w-name" placeholder="例如：3 号矿产量下降诊断"></div>'
      + '<div class="ecmc-field"><label>业务说明（可选）</label><textarea id="w-desc" rows="2"></textarea></div>'
      + '<div class="kv"><dt>数据域</dt><dd class="mono">' + esc(domainRef.stable_id) + ' · ' + esc(domainRef.version) + '</dd>'
      + '<dt>DiagnosticTarget</dt><dd class="mono">' + esc(JSON.stringify(target, null, 2).replace(/\n/g, '<br>')) + '</dd></div>'
      + '<div class="warn-box">DiagnosticTarget 创建后不可修改；需要改变目标时必须创建新模型，不能通过编辑 Version 绕过签名约束。</div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button>'
      + '<button class="btn" data-create>创建模型</button></div>');
    d.on('[data-create]', 'click', async function () {
      var name = d.el.querySelector('#w-name').value.trim();
      if (!name) { d.el.querySelector('#w-name').focus(); return; }
      var body = {
        name: name,
        data_domain_ref: domainRef,
        diagnostic_target: target,
        description: d.el.querySelector('#w-desc').value.trim() || null,
      };
      try {
        var res = await api.post('/causal-models', body, { idempotencyKey: api.idempotencyKey() });
        d.close();
        common.toast('模型已创建，进入编辑器', 'success');
        location.href = common.editorUrl(res.body.model_id);
      } catch (e) {
        common.errorBar(document.getElementById('ecmc-errorbar'), e);
      }
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  /* ── boot ── */
  function boot() {
    var q = new URLSearchParams(location.search);
    state.type = q.get('type') === 'causal' ? 'causal' : 'all';
    // test-only 目录适配器：仅显式 ?catalog=fake 开启（§9.3 / §21）
    if (q.get('catalog') === 'fake') ECMC.catalog.enableFake();

    // tabs
    var tabs = document.querySelectorAll('.ecmc-tab[data-type]');
    Array.prototype.forEach.call(tabs, function (tab) {
      if (tab.dataset.type === state.type) tab.classList.add('active');
      tab.addEventListener('click', function () {
        if (tab.dataset.planned === '1') { common.toast('决策/任务模型规划中，不展示虚构数据', 'warn'); return; }
        location.href = common.withCatalogParam(tab.dataset.type === 'causal'
          ? 'ecmc-models.html?type=causal&sub=ecmc-models-causal'
          : 'ecmc-models.html');
      });
    });

    document.getElementById('ecmc-model-search').addEventListener('input', function (e) { state.q = e.target.value; render(); });
    document.getElementById('ecmc-model-domain').addEventListener('change', function (e) { state.domain = e.target.value; render(); });
    document.getElementById('ecmc-model-status').addEventListener('change', function (e) { state.status = e.target.value; render(); });
    document.getElementById('ecmc-new-model').addEventListener('click', openNewModelWizard);

    // 目录选择器「申请新增目录项」→ 目录申请页（透传 fake 模式）
    ECMC.catalog.setRequestHandler(function (kind) {
      location.href = common.withCatalogParam('ecmc-catalog-requests.html?kind=' + encodeURIComponent(kind || ''));
    });

    loadModels();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
