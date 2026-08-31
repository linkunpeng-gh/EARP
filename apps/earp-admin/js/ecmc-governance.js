/* ════════════════════════════════════════════════════════════════════════
 * ECMC N01B — 治理操作（ecmc-governance.js）
 *
 * 设计: FE-ECMC-2026-0830 §11 审核/发布/编译/激活、§13 PublishDialog/ActivationDialog/
 *       CatalogRequestDrawer/VersionConflictDialog
 * 合同: api/2026-08-30-n01a-causal-model-management-api-contract.md
 * 约束：
 *   - 提交审核与发布使用不同文案/权限（不得用含混的“提交发布”）
 *   - 前端不预计算 canonical hash；发布成功后展示服务端返回的 Snapshot ID/hash
 *   - 激活同时携带 Candidate If-Match 与 active-pointer CAS；
 *     409 ACTIVE_VERSION_CHANGED 后刷新 active pointer，不自动重试、不选择其他 Artifact
 *   - 驳回必须填写原因
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var api = window.ECMC.api;
  var common = window.ECMC.common;
  var esc = common.esc;

  function vUrl(modelId, versionId) { return '/causal-models/' + encodeURIComponent(modelId) + '/versions/' + encodeURIComponent(versionId); }

  /* ── 提交审核：先运行 full 校验；阻断则展开校验面板并禁用 ──
   * ValidateRequest 冻结模式仅 incremental|full（API 合同 §4.3）；发布门禁由
   * submit-review 服务端最终校验决定，前端不传自定义模式。 */
  async function submitReview(client, model, version, onValidation) {
    var vpath = vUrl(model.id || model.model_id, version.model_version_id);
    var result = await api.post(vpath + '/validate', { mode: 'full' }, { idempotencyKey: api.idempotencyKey() });
    var summary = ECMC.validation.summarize(result.body);
    if (onValidation) onValidation(result.body);
    if (summary.errors > 0) {
      throw Object.assign(api.EcmcApiError(422, 'MODEL_VALIDATION_FAILED', '存在阻断发布的问题，请先修复。', ''), { validationResult: result.body });
    }
    var res = await client.mutate('POST', vpath + '/submit-review', null, {});
    common.toast('已提交审核（in_review），内容已锁定', 'success');
    return res.body;
  }

  /* ── 驳回：必须填写原因 ── */
  function rejectReview(client, model, version) {
    return new Promise(function (resolve) {
      var d = common.dialog(
        '<div class="ecmc-dialog-head"><h3>驳回版本</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
        + '<div class="ecmc-dialog-body">'
        + '<div class="info-box">驳回后版本将回到 <b>draft</b>，内容保留，revision 递增；驳回必须填写原因。</div>'
        + '<div class="ecmc-field"><label>驳回原因（必填）<span class="required">*</span></label>'
        + '<textarea id="ecmc-reject-reason" rows="4" placeholder="说明需要修改的内容…"></textarea>'
        + '<div class="field-error" id="ecmc-reject-err" style="display:none">请填写驳回原因。</div></div>'
        + '</div>'
        + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button>'
        + '<button class="btn btn-danger" data-ok>驳回</button></div>'
      );
      d.on('[data-ok]', 'click', async function () {
        var reason = d.el.querySelector('#ecmc-reject-reason').value.trim();
        if (!reason) {
          d.el.querySelector('#ecmc-reject-err').style.display = 'block';
          return;
        }
        try {
          var res = await client.mutate('POST', vUrl(model.model_id, version.model_version_id) + '/reject', { reason: reason }, {});
          d.close();
          common.toast('已驳回，版本回到 draft', 'success');
          resolve(res.body);
        } catch (e) {
          d.el.querySelector('#ecmc-reject-err').textContent = e.message;
          d.el.querySelector('#ecmc-reject-err').style.display = 'block';
        }
      });
      d.on('[data-cancel]', 'click', function () { d.close(); resolve(null); });
      d.on('[data-close]', 'click', function () { d.close(); resolve(null); });
    });
  }

  /* ── 发布确认：展示模型/Version/DiagnosticTarget signature/校验结果/Snapshot 说明 ── */
  function publishConfirm(model, version, validationResult) {
    var target = version.diagnostic_target || {};
    var sum = validationResult ? ECMC.validation.summarize(validationResult) : null;
    return new Promise(function (resolve) {
      var d = common.dialog(
        '<div class="ecmc-dialog-head"><h3>治理发布确认</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
        + '<div class="ecmc-dialog-body">'
        + '<div class="kv"><dt>模型</dt><dd>' + esc(model.name) + ' <span class="cell-id">' + esc(model.model_id) + '</span></dd>'
        + '<dt>Version</dt><dd class="mono">' + esc(version.version) + ' · ' + esc(version.model_version_id) + ' · revision ' + esc(version.revision) + '</dd>'
        + '<dt>诊断目标</dt><dd class="mono">' + esc(target.objective || 'diagnose') + ' · entry=' + esc(target.entry_point) + ' · direction=' + esc(target.direction || '') + '</dd>'
        + '<dt>数据域</dt><dd class="mono">' + esc((model.data_domain_ref && model.data_domain_ref.stable_id) || model.data_domain_id || '—') + '</dd>'
        + (sum ? '<dt>校验结果</dt><dd>' + (sum.errors ? '<span class="ecmc-badge failed">阻断 ' + sum.errors + '</span>' : '<span class="ecmc-badge success">通过</span>') + (sum.warnings ? ' <span class="ecmc-badge warning" style="background:var(--amber-bg);color:var(--amber)">警告 ' + sum.warnings + '</span>' : '') + '</dd>' : '')
        + '</div>'
        + '<div class="info-box">发布将生成 <b>不可变 Snapshot</b>（canonical hash 由服务端计算），版本进入 <b>published + inactive</b>；'
        + '发布不改变当前 active 模型，不自动编译、不激活。已发布内容不可修改。</div>'
        + '</div>'
        + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button>'
        + '<button class="btn btn-approve" data-ok>确认发布</button></div>'
      );
      d.on('[data-ok]', 'click', function () { d.close(); resolve(true); });
      d.on('[data-cancel]', 'click', function () { d.close(); resolve(false); });
      d.on('[data-close]', 'click', function () { d.close(); resolve(false); });
    });
  }

  /* ── 编译 ── */
  async function requestCompile(client, model, version, retryOfCompileId) {
    var body = retryOfCompileId ? { retry_of_compile_id: retryOfCompileId } : {};
    var res = await api.post(vUrl(model.model_id, version.model_version_id) + '/compile', body, { idempotencyKey: api.idempotencyKey() });
    return res.body; // { compile_record: {...} }
  }

  async function fetchArtifact(model, version, compileRecordId) {
    var res = await api.get(vUrl(model.model_id, version.model_version_id) + '/compile-records/' + encodeURIComponent(compileRecordId) + '/artifact');
    return res.body;
  }

  async function fetchGovernance(model, version) {
    var res = await api.get(vUrl(model.model_id, version.model_version_id) + '/governance');
    return res.body;
  }

  /* ── 激活确认：Candidate If-Match + active-pointer CAS ──
   * 409 ACTIVE_VERSION_CHANGED：先重新读取 governance（刷新 active pointer），
   * 再以最新 expected pointers 重新打开确认；不自动重试、不选择其他 Artifact。 */
  function activateConfirm(model, candidateVersion, compileRecord, governance, onActivate, onRefreshGovernance) {
    var activePointer = governance.active_pointer || {};
    var currentVersion = activePointer.model_version_id || null;
    var currentSnapshot = activePointer.snapshot_id || null;
    var d = common.dialog(
      '<div class="ecmc-dialog-head"><h3>激活确认</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="kv">'
      + '<dt>候选 Version</dt><dd class="mono">' + esc(candidateVersion.model_version_id) + ' · revision ' + esc(candidateVersion.revision) + '</dd>'
      + '<dt>Compile Attempt</dt><dd class="mono">' + esc(compileRecord.compile_record_id) + ' · ' + esc(compileRecord.status) + '</dd>'
      + '<dt>Artifact hash</dt><dd class="mono">' + esc(compileRecord.compiled_artifact_hash || '—') + '</dd>'
      + '<dt>当前 active pointer</dt><dd class="mono">' + esc(currentVersion || '无') + ' / ' + esc(currentSnapshot || '无') + '</dd>'
      + '<dt>expected pointer</dt><dd class="mono">' + esc(currentVersion || 'null') + ' / ' + esc(currentSnapshot || 'null') + '</dd>'
      + '</div>'
      + '<div class="info-box">激活只物化指定的 success Artifact（不重新编译、不自动选择其他 Attempt），并携带当前 active pointer 的 CAS。'
      + '若期间 active 已变化，将返回 <b>ACTIVE_VERSION_CHANGED</b>，不会切换、不会写审计；刷新指针后需重新确认。</div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button>'
      + '<button class="btn btn-approve" data-ok>确认激活</button></div>'
    );
    d.on('[data-ok]', 'click', async function () {
      try {
        var body = {
          model_version_id: candidateVersion.model_version_id,
          compile_record_id: compileRecord.compile_record_id,
          expected_active_model_version_id: currentVersion,
          expected_active_snapshot_id: currentSnapshot,
        };
        var res = await onActivate(body);
        d.close();
        common.toast('激活成功，active pointer 已切换', 'success');
        return res;
      } catch (e) {
        if (e.code === 'ACTIVE_VERSION_CHANGED') {
          d.close();
          common.toast('ACTIVE_VERSION_CHANGED：active 指针已被他人更新，正在刷新当前指针…', 'warn', 3600);
          var fresh = governance;
          if (onRefreshGovernance) {
            try { fresh = await onRefreshGovernance(); } catch (_) { /* 刷新失败则沿用旧指针重开，由用户决定 */ }
          }
          if (fresh && fresh !== governance) {
            // 以刷新后的 expected pointers 重新打开确认，用户显式重试（不自动激活）
            activateConfirm(model, candidateVersion, compileRecord, fresh, onActivate, onRefreshGovernance);
          } else {
            common.errorBar(document.getElementById('ecmc-errorbar'), e);
          }
        } else {
          common.toast('激活失败：' + e.message, 'error', 4200);
        }
      }
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  /* ── 归档 ── */
  async function archiveVersion(client, model, version) {
    var ok = await common.confirmDialog(
      '归档 Version',
      '归档后该版本只读保留（active 版本归档会同时清空 active pointer 并 withdraw 对应 Blueprint）。是否继续？',
      '归档', { danger: true }
    );
    if (!ok) return null;
    var res = await client.mutate('POST', vUrl(model.model_id, version.model_version_id) + '/archive', null, {});
    common.toast('已归档', 'success');
    return res.body;
  }

  /* ── 目录扩展申请：抽屉式创建（按 kind 构造 typed contract）──
   * 每种 request_type 使用对应 contract builder（schemas.py ProposedCatalogDefinition）；
   * target_data_domain_ref 使用受控 DataDomain 引用；ref 字段用受控选择器/结构化构建器。 */
  function catalogRequestDrawer(container, options) {
    options = options || {};
    var prefill = options.prefill || {};

    /* contract 字段定义：simple = 文本/选择；ref = 单个受控引用；refList = 受控引用多选 */
    var KIND_CONTRACT = {
      data_domain: { fields: [{ name: 'domain_code', label: '数据域编码', type: 'text' }] },
      entity_type: { fields: [{ name: 'semantic_class', label: '语义类别', type: 'text' }] },
      relation_type: { refLists: [{ name: 'source_entity_type_refs', label: '源实体类型', kind: 'entity_type' }, { name: 'target_entity_type_refs', label: '目标实体类型', kind: 'entity_type' }] },
      metric: {
        fields: [
          { name: 'value_type', label: '值类型', type: 'select', options: ['decimal', 'integer', 'string', 'boolean'] },
          { name: 'time_semantics', label: '时间语义', type: 'text' },
        ],
        refLists: [{ name: 'allowed_unit_refs', label: '允许单位', kind: 'unit' }, { name: 'allowed_aggregation_refs', label: '允许聚合', kind: 'aggregation' }],
      },
      unit: { fields: [{ name: 'quantity_kind', label: '量纲种类', type: 'text' }, { name: 'symbol', label: '符号', type: 'text' }] },
      aggregation: { fields: [{ name: 'operator', label: '操作符', type: 'text' }] },
      time_window_schema: { refs: [{ name: 'input_schema_ref', label: '输入 Schema 引用' }] },
      binding_template: {
        fields: [{ name: 'resolver_identity', label: '解析器标识', type: 'text' }],
        refs: [{ name: 'params_schema_ref', label: '参数 Schema 引用' }],
        refLists: [{ name: 'source_entity_type_refs', label: '源实体类型', kind: 'entity_type' }, { name: 'target_entity_type_refs', label: '目标实体类型', kind: 'entity_type' }],
      },
      capability_contract: { refs: [{ name: 'input_schema_ref', label: '输入 Schema 引用' }, { name: 'output_schema_ref', label: '输出 Schema 引用' }], fixed: { read_only: true } },
      rule_schema: { fields: [{ name: 'rule_kind', label: '规则类型', type: 'select', options: ['predicate', 'threshold', 'direction_rule'] }], refs: [{ name: 'spec_schema_ref', label: 'Spec Schema 引用' }] },
    };

    var overlay = document.createElement('div');
    overlay.className = 'run-drawer-overlay open';
    overlay.style.display = 'flex';
    overlay.style.justifyContent = 'flex-end';
    overlay.innerHTML =
      '<div class="run-drawer" style="width:600px;max-width:94vw">'
      + '<div class="run-drawer-header"><h3>目录扩展申请</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="run-drawer-msgs" style="overflow-y:auto">'
      + '<div class="ecmc-field"><label>申请类型（request_type）</label><select id="ccr-type">'
      + Object.keys(ECMC.catalog.KIND_DISPLAY || {}).map(function (k) {
        return '<option value="' + esc(k) + '"' + (k === (prefill.kind || 'metric') ? ' selected' : '') + '>' + esc(ECMC.catalog.KIND_DISPLAY[k]) + '</option>';
      }).join('') + '</select></div>'
      + '<div class="ecmc-field"><label>目标数据域（受控 DataDomain）</label><div id="ccr-domain"></div></div>'
      + '<div class="ecmc-field"><label>业务名称（display_name）</label><input id="ccr-name" placeholder="例如：运输周期"></div>'
      + '<div class="ecmc-field"><label>语义定义（semantic_definition）</label><textarea id="ccr-def" rows="3" placeholder="候选条目的业务语义…"></textarea></div>'
      + '<div id="ccr-contract"></div>'
      + '<div class="ecmc-field"><label>申请理由（rationale）</label><textarea id="ccr-rationale" rows="2" placeholder="为什么需要该目录项…"></textarea></div>'
      + '<div class="info-box">申请只描述候选业务语义；禁止提交 SQL、URL、endpoint、Provider 参数或执行代码。'
      + '批准后由权威目录服务履约，<b>履约完成前模型不可引用</b>。</div>'
      + '<div class="ecmc-field-error" id="ccr-error" style="color:var(--red);font-size:0.76rem;display:none"></div>'
      + '</div>'
      + '<div class="run-drawer-input" style="border-top:1px solid var(--border-subtle)"><button class="btn secondary" data-cancel style="flex:1">取消</button>'
      + '<button class="btn" data-submit style="flex:1">创建申请</button></div>'
      + '</div>';
    container.appendChild(overlay);

    var domainInput = ECMC.catalog.refInput(overlay.querySelector('#ccr-domain'), {
      kind: 'data_domain',
      emptyLabel: '选择目标数据域',
      value: prefill.domainRef || null,
      onChange: function () {},
    });

    // 生产 Catalog 合同未签署：目标数据域等目录项无法选择，禁用提交并说明
    var submitBtn = overlay.querySelector('[data-submit]');
    if (!ECMC.catalog.getAdapter()) {
      submitBtn.disabled = true;
      submitBtn.title = '受控目录 browse API 未签署：无法选择目标数据域等目录项';
      submitBtn.textContent = '生产 Catalog 合同签署后可提交';
      overlay.querySelector('.run-drawer-msgs').innerHTML += '<div class="info-box" style="font-size:0.74rem;margin-top:0.5rem">受控目录 browse API 未签署（§21）：当前无法选择目标数据域，申请暂不可提交；使用 <code>?catalog=fake</code> 可进行 test-only 合成。</div>';
    }

    /* 按 kind 渲染 contract 表单 */
    function renderContract(kind) {
      var box = overlay.querySelector('#ccr-contract');
      var def = KIND_CONTRACT[kind] || {};
      var html = '<div class="ecmc-field"><label>contract（' + esc(kind) + '）</label></div>';
      if (def.fixed) {
        html += '<div class="ecmc-field"><label>read_only</label><input readonly value="true"></div>';
      }
      (def.fields || []).forEach(function (f) {
        if (f.type === 'select') {
          html += '<div class="ecmc-field"><label>' + esc(f.label) + '</label><select data-contract-field="' + esc(f.name) + '">'
            + f.options.map(function (o) { return '<option value="' + esc(o) + '">' + esc(o) + '</option>'; }).join('') + '</select></div>';
        } else {
          html += '<div class="ecmc-field"><label>' + esc(f.label) + '</label><input data-contract-field="' + esc(f.name) + '" placeholder="' + esc(f.name) + '"></div>';
        }
      });
      (def.refs || []).forEach(function (r) {
        html += '<div class="ecmc-field"><label>' + esc(r.label) + '（受控引用）</label><div data-contract-ref="' + esc(r.name) + '"></div></div>';
      });
      (def.refLists || []).forEach(function (r) {
        html += '<div class="ecmc-field"><label>' + esc(r.label) + '（受控引用多选）</label><div data-contract-reflist="' + esc(r.name) + '"></div></div>';
      });
      box.innerHTML = html || '<div class="ecmc-field"><label>contract</label><div class="info-box">该类型无额外 contract 字段。</div></div>';
      box._inputs = {};
      Array.prototype.forEach.call(box.querySelectorAll('[data-contract-field]'), function (el) { box._inputs[el.dataset.contractField] = el; });
      box._refs = {};
      Array.prototype.forEach.call(box.querySelectorAll('[data-contract-ref]'), function (el) {
        box._refs[el.dataset.contractRef] = ECMC.catalog.refInput(el, { emptyLabel: '选择引用', onChange: function () {} });
      });
      box._refLists = {};
      Array.prototype.forEach.call(box.querySelectorAll('[data-contract-reflist]'), function (el) {
        var r = (def.refLists || []).filter(function (x) { return x.name === el.dataset.contractReflist; })[0];
        box._refLists[el.dataset.contractReflist] = ECMC.catalog.multiRefInput(el, { kind: r.kind, emptyLabel: '选择 ' + (ECMC.catalog.KIND_DISPLAY[r.kind] || r.kind), onChange: function () {} });
      });
    }
    renderContract(overlay.querySelector('#ccr-type').value);
    overlay.querySelector('#ccr-type').addEventListener('change', function () { renderContract(this.value); });

    function close() { overlay.remove(); }
    overlay.querySelector('[data-close]').addEventListener('click', close);
    overlay.querySelector('[data-cancel]').addEventListener('click', close);
    overlay.querySelector('[data-submit]').addEventListener('click', async function () {
      var requestType = overlay.querySelector('#ccr-type').value;
      var domainRef = domainInput.getValue();
      var displayName = overlay.querySelector('#ccr-name').value.trim();
      var semantic = overlay.querySelector('#ccr-def').value.trim();
      var rationale = overlay.querySelector('#ccr-rationale').value.trim();
      var errEl = overlay.querySelector('#ccr-error');
      if (!domainRef || !displayName || !semantic || !rationale) {
        errEl.textContent = '请填写全部字段（类型/数据域/名称/语义定义/理由）。';
        errEl.style.display = 'block';
        return;
      }
      /* 构造 typed contract */
      var box = overlay.querySelector('#ccr-contract');
      var contract = {};
      var def = KIND_CONTRACT[requestType] || {};
      if (def.fixed) Object.assign(contract, def.fixed);
      Object.keys(box._inputs || {}).forEach(function (name) {
        var el = box._inputs[name];
        var val = el.value.trim();
        if (el.tagName === 'SELECT' && el.dataset.contractField === 'value_type') { contract[name] = val; return; }
        contract[name] = val;
      });
      Object.keys(box._refs || {}).forEach(function (name) {
        var ref = box._refs[name].getValue();
        if (ref) contract[name] = ref;
      });
      Object.keys(box._refLists || {}).forEach(function (name) {
        contract[name] = box._refLists[name].getValue();
      });
      if (requestType === 'capability_contract') contract.read_only = true;
      var body = {
        request_type: requestType,
        target_data_domain_ref: domainRef,
        rationale: rationale,
        proposed_definition: {
          schema_version: 'catalog-change-request/v1',
          kind: requestType,
          display_name: displayName,
          semantic_definition: semantic,
          contract: contract,
        },
      };
      try {
        await api.post('/catalog-change-requests', body, { idempotencyKey: api.idempotencyKey() });
        close();
        common.toast('目录扩展申请已创建（draft）', 'success');
        if (options.onCreated) options.onCreated();
      } catch (e) {
        errEl.textContent = e.message;
        errEl.style.display = 'block';
      }
    });
    return { el: overlay, close: close };
  }

  window.ECMC = window.ECMC || {};
  window.ECMC.governance = {
    submitReview: submitReview,
    rejectReview: rejectReview,
    publishConfirm: publishConfirm,
    requestCompile: requestCompile,
    fetchArtifact: fetchArtifact,
    fetchGovernance: fetchGovernance,
    activateConfirm: activateConfirm,
    archiveVersion: archiveVersion,
    catalogRequestDrawer: catalogRequestDrawer,
    vUrl: vUrl,
  };
})();
