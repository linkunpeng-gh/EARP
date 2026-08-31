/* ════════════════════════════════════════════════════════════════════════
 * ECMC N01B — CatalogRefPicker（ecmc-catalog-picker.js）
 *
 * 设计: FE-ECMC-2026-0830 §9 CatalogRefPicker、§13 公共组件契约
 * 合同缺口（§21 开放项）：生产 Catalog browse/search API 未冻结。签署前只能完成
 *   组件、fake adapter 和 contract test，不得假设真实目录存在。
 *
 * 契约约束（§9.3）：
 *   - 可执行字段只能由选择器产生 {kind, stable_id, version}，不接受任意 stable ID 输入框
 *   - 不接受 latest / '*' / display name 代替精确版本
 *   - 搜索无结果时提供“申请新增目录项”，打开 CatalogChangeRequest 抽屉
 *   - Case A Fixture 目录仅 test-only UI composition（?catalog=fake 显式开启），
 *     生产默认不启用，绝不伪造目录
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ── Fake adapter：Case A Fixture 受控目录（test-only）──
   * 仅用于 ?catalog=fake 的界面合成与 contract test；生产页面默认 adapter=null。 */
  var KIND_DISPLAY = {
    data_domain: '数据域', entity_type: '实体类型', relation_type: '关系类型',
    metric: '指标', unit: '单位', aggregation: '聚合', time_window_schema: '时间窗口',
    binding_template: '绑定模板', capability_contract: '能力合同', rule_schema: '规则 Schema',
  };

  function fakeAdapter() {
    var E = function (kind, stable_id, version, display_name, data_domain_id) {
      return { kind: kind, stable_id: stable_id, version: version, display_name: display_name, status: 'active', data_domain_id: data_domain_id || 'production_data' };
    };
    var entries = [
      // data domains
      E('data_domain', 'production', 'v1', '生产数据'),
      E('data_domain', 'equipment', 'v1', '设备数据'),
      // entity types
      E('entity_type', 'entity.mine', 'v1', '矿山'),
      E('entity_type', 'entity.haulage_system', 'v1', '运输系统'),
      E('entity_type', 'entity.equipment_group', 'v1', '设备组'),
      // relation types
      E('relation_type', 'relation.affects', 'v1', '影响'),
      E('relation_type', 'relation.has_subsystem', 'v1', '拥有子系统'),
      E('relation_type', 'relation.has_equipment_group', 'v1', '拥有设备组'),
      // metrics
      E('metric', 'metric.production_output', 'v1', '产量', 'production_data'),
      E('metric', 'metric.haulage_cycle_time', 'v1', '运输周期'),
      E('metric', 'metric.haulage_queue_time', 'v1', '排队时间'),
      E('metric', 'metric.equipment_availability', 'v1', '设备可用率', 'equipment_data'),
      // units
      E('unit', 'minute', 'v1', '分钟'),
      E('unit', 'ton', 'v1', '吨'),
      E('unit', 'ratio', 'v1', '比率'),
      // aggregations
      E('aggregation', 'mean', 'v1', '均值'),
      E('aggregation', 'sum_over_production_day', 'v1', '日累计'),
      E('aggregation', 'availability_over_production_day', 'v1', '日可用率'),
      // time window schemas
      E('time_window_schema', 'daily_window', 'v1', '日窗口'),
      // binding templates（含 params schema，供 binding_params 结构化渲染）
      { kind: 'binding_template', stable_id: 'context_entity', version: 'v1', display_name: '上下文实体', status: 'active', data_domain_id: 'production_data',
        params_schema: { properties: [{ name: 'entity_type_ref', label: '目标实体类型', type: 'ref', kind: 'entity_type' }] } },
      { kind: 'binding_template', stable_id: 'outbound_relation', version: 'v1', display_name: '出向关系', status: 'active', data_domain_id: 'production_data',
        params_schema: { properties: [
          { name: 'relation_type_ref', label: '关系类型', type: 'ref', kind: 'relation_type' },
          { name: 'target_entity_type_ref', label: '目标实体类型', type: 'ref', kind: 'entity_type' },
        ] } },
      // capability contracts
      E('capability_contract', 'contract.read_production_output', 'v1', '读取产量'),
      E('capability_contract', 'contract.read_haulage_cycle', 'v1', '读取运输周期'),
      E('capability_contract', 'contract.read_haulage_quality', 'v1', '读取运输质量'),
      E('capability_contract', 'contract.read_equipment_health', 'v1', '读取设备健康'),
      // rule schemas
      E('rule_schema', 'direction_rule', 'v1', '方向规则'),
      E('rule_schema', 'threshold_rule', 'v1', '阈值规则'),
    ];
    var byRef = {};
    entries.forEach(function (e) { byRef[e.kind + ':' + e.stable_id + ':' + e.version] = e; });

    return {
      testOnly: true,
      name: 'case-a-fixture（test-only）',
      search: function (opts) {
        opts = opts || {};
        var q = (opts.q || '').trim().toLowerCase();
        return entries.filter(function (e) {
          if (opts.kind && e.kind !== opts.kind) return false;
          // 数据域按条目 data_domain_id 匹配（global 条目对所有域可用）
          if (opts.domain && e.data_domain_id !== opts.domain && e.data_domain_id !== 'global') return false;
          if (e.status !== 'active') return false;
          if (q && (e.display_name || '').toLowerCase().indexOf(q) === -1 && e.stable_id.toLowerCase().indexOf(q) === -1) return false;
          return true;
        }).slice(0, 50);
      },
      lookup: function (ref) {
        if (!ref) return null;
        return byRef[ref.kind + ':' + ref.stable_id + ':' + ref.version] || null;
      },
      kinds: KIND_DISPLAY,
    };
  }

  /* ── 激活 adapter：仅显式开启（?catalog=fake 或测试注入）── */
  var requestHandler = null; // 全局「申请新增目录项」处理器（页面 boot 注入）
  var catalogState = {
    adapter: null, // 生产默认：无目录后端；不得假设真实目录存在
    enableFake: function () {
      catalogState.adapter = fakeAdapter();
      return catalogState.adapter;
    },
    getAdapter: function () { return catalogState.adapter; },
  };

  /* ── CatalogRefPicker 组件 ── */
  function mountPicker(container, options) {
    options = options || {};
    var adapter = catalogState.adapter;
    var value = options.value || null;

    var root = document.createElement('div');
    root.className = 'ecmc-picker';
    container.appendChild(root);

    function refLine(ref) {
      if (!ref) return '';
      return ref.kind + '.' + ref.stable_id + ' · ' + ref.version;
    }

    function renderTrigger() {
      var name = '';
      if (value && adapter) {
        var found = adapter.lookup(value);
        if (found) name = found.display_name;
      }
      root.innerHTML =
        '<button type="button" class="ecmc-picker-trigger" data-trigger ' + (options.readOnly ? 'disabled' : '') + '>'
        + (value
          ? '<span class="pt-value"><span class="pt-name">' + ECMC.common.esc(name || value.stable_id) + '</span><span class="pt-ref">' + ECMC.common.esc(refLine(value)) + '</span></span>'
          : '<span class="pt-value pt-empty">' + ECMC.common.esc(options.emptyLabel || '选择目录项') + '</span>')
        + '<span class="pt-caret">▾</span></button>';
      var trigger = root.querySelector('[data-trigger]');
      if (trigger) trigger.addEventListener('click', function () { openPopover(); });
    }

    function openPopover() {
      closePopover();
      var pop = document.createElement('div');
      pop.className = 'ecmc-picker-pop';
      root.appendChild(pop);
      pop.innerHTML =
        '<div class="ecmc-picker-search"><input type="search" placeholder="搜索业务名称或 stable_id" value=""></div>'
        + '<div class="ecmc-picker-list"></div>'
        + (adapter && adapter.testOnly
          ? '<div class="ecmc-picker-note">开发目录适配器（test-only）— 生产 Catalog 合同未签署，仅用于界面合成。</div>'
          : '<div class="ecmc-picker-note">受控目录 browse API 未签署；缺失目录项请走「目录扩展申请」。</div>');
      var input = pop.querySelector('input');
      var list = pop.querySelector('.ecmc-picker-list');

      function renderList() {
        var q = input.value;
        var items;
        if (adapter) {
          items = adapter.search({ kind: options.kind, domain: options.domain, q: q });
        } else {
          items = [];
        }
        if (items.length) {
          list.innerHTML = items.map(function (item) {
            var sel = value && value.stable_id === item.stable_id && value.version === item.version ? ' selected' : '';
            return '<div class="ecmc-picker-item' + sel + '" data-ref="' + ECMC.common.esc(item.stable_id) + '" data-version="' + ECMC.common.esc(item.version) + '">'
              + '<span class="pi-name">' + ECMC.common.esc(item.display_name || item.stable_id) + '</span>'
              + '<span class="pi-ref">' + ECMC.common.esc(item.kind + '.' + item.stable_id + ' · ' + item.version) + '</span>'
              + (item.data_domain_id ? '<span class="pi-domain">' + ECMC.common.esc(item.data_domain_id) + '</span>' : '')
              + '</div>';
          }).join('');
          Array.prototype.forEach.call(list.querySelectorAll('.ecmc-picker-item'), function (el) {
            el.addEventListener('click', function () {
              var ref = { kind: options.kind, stable_id: el.dataset.ref, version: el.dataset.version };
              value = ref;
              renderTrigger();
              closePopover();
              if (options.onChange) options.onChange(ref, adapter ? adapter.lookup(ref) : null);
            });
          });
        } else {
          list.innerHTML = '<div class="ecmc-picker-empty">未找到可选的 ' + ECMC.common.esc(KIND_DISPLAY[options.kind] || options.kind) + ' 目录项'
            + '<br><button type="button" class="btn" data-request>申请新增目录项</button></div>';
          var req = list.querySelector('[data-request]');
          if (req) req.addEventListener('click', function () {
            closePopover();
            var fn = options.onRequestMissing || requestHandler;
            if (fn) fn(options.kind, options.domain);
          });
        }
      }

      input.addEventListener('input', renderList);
      renderList();
      input.focus();

      var onDocClick = function (e) { if (!root.contains(e.target)) closePopover(); };
      var onKey = function (e) { if (e.key === 'Escape') closePopover(); };
      function closePopover() {
        document.removeEventListener('mousedown', onDocClick);
        document.removeEventListener('keydown', onKey);
        if (pop && pop.parentNode) pop.remove();
      }
      document.addEventListener('mousedown', onDocClick);
      document.addEventListener('keydown', onKey);
    }

    renderTrigger();

    return {
      el: root,
      getValue: function () { return value; },
      setValue: function (ref) { value = ref; renderTrigger(); },
      clear: function () { value = null; renderTrigger(); },
    };
  }

  /* ── 受控引用结构化构建器（无目录 adapter 时兜底）──
   * 仍只产生 {kind, stable_id, version}，version 必须是精确版本；
   * 不接受 latest / '*'；不提供 SQL/URL/endpoint 等自由字段。 */
  var EXACT_VERSION_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/;
  function validateExactVersion(v) {
    return v && !/^(latest|\*)$/.test(v) && EXACT_VERSION_RE.test(v);
  }

  function refFromStructured(kind, stableId, version) {
    var s = String(stableId || '').trim();
    var v = String(version || '').trim();
    if (!kind || !s || !validateExactVersion(v)) return null;
    return { kind: kind, stable_id: s, version: v };
  }

  /* 受控引用输入：adapter 可用时用 Picker；否则展示不可用态（§9.3 禁止任意 stable ID 输入框）。
   * 结构化 kind/stable_id/version 仅存在于 test-only 工具，不进入正式页面兜底。 */
  function refInput(container, options) {
    options = options || {};
    var adapter = catalogState.adapter;
    if (adapter) {
      return mountPicker(container, options);
    }
    var root = document.createElement('div');
    root.className = 'ecmc-ref-input';
    var value = options.value || null;
    var hasValue = !!(value && value.stable_id && value.version);
    root.innerHTML = '<div class="info-box" style="font-size:0.72rem">受控目录 browse API 未签署（§21）：无法选择目录项。'
      + '请使用 <code>?catalog=fake</code> 的 test-only 适配器进行界面合成，或先到「目录扩展申请」提出缺项。</div>'
      + (hasValue
        ? '<div class="ecmc-multi-ref-chip" style="font-family:ui-monospace,monospace;font-size:0.7rem;border:1px solid var(--border-standard);border-radius:var(--radius-md);padding:0.3rem 0.5rem">'
          + ECMC.common.esc(value.kind + '.' + value.stable_id + ' · ' + value.version) + '</div>'
        : '');
    container.appendChild(root);
    return {
      el: root,
      getValue: function () { return hasValue ? value : null; },
      setValue: function (ref) { value = ref; hasValue = !!(ref && ref.stable_id && ref.version); },
    };
  }

  /* 多选受控引用（如 supporting contracts）：支持去重、排除指定 ref、移除。
   * 无 adapter 时只读展示已保存引用，禁止新增（§9.3）。 */
  function multiRefInput(container, options) {
    options = options || {};
    var values = (options.value || []).slice();
    var adapter = catalogState.adapter;
    var root = document.createElement('div');
    root.className = 'ecmc-multi-ref';
    container.appendChild(root);

    function render() {
      var html = '';
      values.forEach(function (ref, i) {
        html += '<div class="ecmc-multi-ref-row" style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.3rem">'
          + '<span class="ecmc-multi-ref-chip" style="flex:1;font-family:ui-monospace,monospace;font-size:0.7rem;border:1px solid var(--border-standard);border-radius:var(--radius-md);padding:0.3rem 0.5rem">'
          + ECMC.common.esc((adapter && adapter.lookup(ref) && adapter.lookup(ref).display_name) || '') + ' · ' + ECMC.common.esc(ref.kind + '.' + ref.stable_id + ' · ' + ref.version) + '</span>'
          + (options.readOnly ? '' : '<button type="button" class="btn-sm secondary" data-rm="' + i + '">移除</button>') + '</div>';
      });
      if (!adapter) {
        html += '<div class="info-box" style="font-size:0.72rem">受控目录未签署：仅可查看已保存引用，不可新增；使用 <code>?catalog=fake</code> 可进行 test-only 合成。</div>';
      } else if (!options.readOnly) {
        html += '<button type="button" class="btn-sm secondary" data-add style="margin-top:0.2rem">+ 添加</button>';
      }
      root.innerHTML = html;
      Array.prototype.forEach.call(root.querySelectorAll('[data-rm]'), function (btn) {
        btn.addEventListener('click', function () {
          values.splice(parseInt(btn.dataset.rm, 10), 1);
          render();
          emit();
        });
      });
      var add = root.querySelector('[data-add]');
      if (add) add.addEventListener('click', function () {
        var row = document.createElement('div');
        row.className = 'ecmc-multi-ref-add';
        row.style.marginBottom = '0.4rem';
        root.insertBefore(row, add);
        var input = refInput(row, { kind: options.kind, domain: options.domain, emptyLabel: '选择 ' + (KIND_DISPLAY[options.kind] || options.kind), onChange: function () {} });
        var confirmBtn = document.createElement('button');
        confirmBtn.className = 'btn-sm';
        confirmBtn.textContent = '确定';
        confirmBtn.style.marginTop = '0.25rem';
        row.appendChild(confirmBtn);
        confirmBtn.addEventListener('click', function () {
          var ref = input.getValue();
          if (!ref) { return; }
          // 去重 + 排除指定 ref（如 primary contract）
          var dup = values.some(function (v) { return v.stable_id === ref.stable_id && v.version === ref.version && v.kind === ref.kind; });
          if (options.exclude && ref.stable_id === options.exclude.stable_id && ref.version === options.exclude.version) {
            row.remove();
            return;
          }
          if (!dup) { values.push(ref); emit(); }
          row.remove();
          render();
        });
      });
    }
    function emit() { if (options.onChange) options.onChange(values.slice()); }
    render();
    return { el: root, getValue: function () { return values.slice(); } };
  }

  window.ECMC = window.ECMC || {};
  window.ECMC.catalog = {
    KIND_DISPLAY: KIND_DISPLAY,
    fakeAdapter: fakeAdapter,
    enableFake: function () { return catalogState.enableFake(); },
    getAdapter: function () { return catalogState.getAdapter(); },
    setAdapter: function (a) { catalogState.adapter = a; },
    Picker: mountPicker,
    refInput: refInput,
    multiRefInput: multiRefInput,
    validateExactVersion: validateExactVersion,
    refFromStructured: refFromStructured,
    setRequestHandler: function (fn) { requestHandler = fn; },
  };
})();
