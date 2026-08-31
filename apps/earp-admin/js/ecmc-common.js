/* ════════════════════════════════════════════════════════════════════════
 * ECMC N01B — 公共组件（ecmc-common.js）
 *
 * 设计: FE-ECMC-2026-0830 §13 公共组件契约
 * 提供：状态映射（GovernanceStatusBadge / ModelTypeBadge / CompileStatusBadge /
 *       runtime_readiness）、toast、对话框、全局错误条（系统错误与业务校验分离）、
 *       correlation_id 复制、时间格式化。公共逻辑禁止在多个页面复制。
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var GOVERNANCE_LABELS = {
    draft: '草稿', in_review: '审核中', published: '已发布', superseded: '已取代', archived: '已归档',
    testing: '测试', deprecated: '已弃用',
  };
  var COMPILE_LABELS = { running: '编译中', success: '成功', failed: '失败' };
  var READINESS_LABELS = {
    active: '运行中', compile_delivery_pending: '编译排队中', compiling: '编译中',
    compile_failed: '编译失败', ready_to_activate: '可激活', not_activated: '未激活',
  };
  var MODEL_TYPE_LABELS = { causal: '因果模型', decision: '决策模型', task: '任务模型' };
  var REQUEST_STATUS_LABELS = {
    draft: '草稿', submitted: '已提交', approved_pending_fulfillment: '履约中', fulfilled: '已履约',
    rejected: '已驳回', cancelled: '已取消', fulfillment_failed: '履约失败',
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmtTime(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return esc(String(iso));
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function fmtHash(hash) {
    if (!hash) return '—';
    return String(hash).length > 12 ? String(hash).slice(0, 6) + '…' + String(hash).slice(-6) : esc(String(hash));
  }

  /* ── 徽章 ── */
  function governanceBadge(status) {
    var s = status || '';
    return '<span class="ecmc-badge ' + esc(s) + '" title="governance status: ' + esc(s) + '"><span class="dot"></span>' + esc(GOVERNANCE_LABELS[s] || s) + '</span>';
  }
  function compileBadge(status) {
    var s = status || '';
    return '<span class="ecmc-badge ' + esc(s) + '">' + esc(COMPILE_LABELS[s] || s) + '</span>';
  }
  function readinessBadge(status) {
    var s = status || '';
    var cls = s === 'active' ? 'active' : (s === 'compile_failed' ? 'failed' : (s === 'compiling' || s === 'compile_delivery_pending' ? 'running' : 'neutral'));
    return '<span class="ecmc-badge ' + cls + '" title="runtime_readiness: ' + esc(s) + '">' + esc(READINESS_LABELS[s] || s) + '</span>';
  }
  function typeBadge(type, planned) {
    var s = type || '';
    if (planned) return '<span class="ecmc-type-badge ' + esc(s) + '">' + esc(MODEL_TYPE_LABELS[s] || s) + '</span><span class="planned-tag" style="font-size:0.62rem;color:var(--text-quaternary);border:1px dashed var(--border-standard);border-radius:3px;padding:0 5px;margin-left:4px">规划中</span>';
    return '<span class="ecmc-type-badge ' + esc(s) + '">' + esc(MODEL_TYPE_LABELS[s] || s) + '</span>';
  }
  function requestStatusBadge(status) {
    var s = status || '';
    var cls = s === 'fulfilled' ? 'success' : (s === 'rejected' || s === 'cancelled' || s === 'fulfillment_failed' ? 'failed' : (s === 'approved_pending_fulfillment' ? 'running' : 'neutral'));
    return '<span class="ecmc-badge ' + cls + '">' + esc(REQUEST_STATUS_LABELS[s] || s) + '</span>';
  }

  /* ── 目录引用展示（业务名称 · kind.stable_id · vX）── */
  function catalogRefText(ref, adapter) {
    if (!ref) return '未选择';
    var display = null;
    if (adapter && typeof adapter.lookup === 'function') {
      var found = adapter.lookup(ref);
      if (found) display = found.display_name;
    }
    var line = ref.kind + '.' + ref.stable_id + ' · ' + ref.version;
    if (display) return display + ' — ' + line;
    return line;
  }

  /* ── Toast ── */
  var toastRoot = null;
  function ensureToasts() {
    if (!toastRoot) {
      toastRoot = document.createElement('div');
      toastRoot.className = 'ecmc-toasts';
      document.body.appendChild(toastRoot);
    }
    return toastRoot;
  }
  function toast(message, type, timeout) {
    var el = document.createElement('div');
    el.className = 'ecmc-toast ' + (type || '');
    el.textContent = message;
    ensureToasts().appendChild(el);
    setTimeout(function () {
      el.style.opacity = '0';
      el.style.transition = 'opacity 0.25s';
      setTimeout(function () { el.remove(); }, 260);
    }, timeout || 2600);
  }

  /* ── 对话框（焦点锁定 + Escape 取消）── */
  function dialog(html, options) {
    options = options || {};
    var overlay = document.createElement('div');
    overlay.className = 'ecmc-dialog-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    var dlg = document.createElement('div');
    dlg.className = 'ecmc-dialog' + (options.wide ? ' wide' : '');
    dlg.innerHTML = html;
    overlay.appendChild(dlg);
    document.body.appendChild(overlay);

    var lastFocus = document.activeElement;
    var focusables = function () {
      return Array.prototype.slice.call(dlg.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')).filter(function (el) { return !el.disabled; });
    };
    function focusTrap(e) {
      var items = focusables();
      if (!items.length) return;
      var first = items[0], last = items[items.length - 1];
      if (e.key === 'Tab') {
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    function onKey(e) {
      if (e.key === 'Escape') close();
      if (e.key === 'Tab') focusTrap(e);
    }
    function close() {
      document.removeEventListener('keydown', onKey, true);
      overlay.remove();
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey, true);
    var first = focusables()[0];
    if (first) setTimeout(function () { first.focus(); }, 0);

    var api = {
      el: dlg,
      overlay: overlay,
      close: close,
      on: function (selector, event, fn) {
        var node = dlg.querySelector(selector);
        if (node) node.addEventListener(event, fn);
        return api;
      },
    };
    return api;
  }

  function confirmDialog(title, messageHtml, confirmLabel, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var d = dialog(
        '<div class="ecmc-dialog-head"><h3>' + esc(title) + '</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
        + '<div class="ecmc-dialog-body">' + messageHtml + '</div>'
        + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button>'
        + '<button class="btn ' + (opts.danger ? 'btn-danger' : (opts.approve ? 'btn-approve' : '')) + '" data-ok>' + esc(confirmLabel) + '</button></div>'
      );
      d.on('[data-ok]', 'click', function () { d.close(); resolve(true); });
      d.on('[data-cancel]', 'click', function () { d.close(); resolve(false); });
      d.on('[data-close]', 'click', function () { d.close(); resolve(false); });
    });
  }

  /* ── 全局错误条：系统错误（403/404/409/422 请求结构）不进校验面板 ── */
  function errorBar(el, error) {
    if (!el) return;
    var code = error && error.code ? error.code : 'HTTP_' + (error && error.status || '');
    var message = error && error.message ? error.message : String(error || '请求失败');
    var corr = error && error.correlationId ? error.correlationId : '';
    el.className = 'ecmc-errorbar visible';
    el.innerHTML = '<span class="eb-code">' + esc(code) + '</span><span class="eb-msg">' + esc(message) + '</span>'
      + (corr ? '<button class="eb-copy" title="复制 correlation_id">复制 correlation_id</button>' : '')
      + '<span class="eb-spacer"></span><button class="eb-dismiss">关闭</button>';
    var copyBtn = el.querySelector('.eb-copy');
    if (copyBtn) copyBtn.addEventListener('click', function () { copyText(corr); toast('correlation_id 已复制', 'success'); });
    el.querySelector('.eb-dismiss').addEventListener('click', function () { el.className = 'ecmc-errorbar'; });
  }
  function clearErrorBar(el) {
    if (el) el.className = 'ecmc-errorbar';
  }
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () {});
    } else {
      var ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (_) {}
      ta.remove();
    }
  }

  /* 稳定错误 → 是否应进入校验面板（只有 MODEL_VALIDATION_FAILED 携带 ValidationResult） */
  function validationResultFromError(error) {
    if (!error) return null;
    if (error.code === 'MODEL_VALIDATION_FAILED') {
      return (error.details && error.details.validation_result) || (error.payload && error.payload.details && error.payload.details.validation_result) || null;
    }
    return null;
  }

  /* 版本冲突详情 → 当前 revision */
  function currentRevisionFromError(error) {
    if (!error) return null;
    var d = error.details || {};
    if (typeof d.current_revision === 'number') return d.current_revision;
    if (error.payload && error.payload.error && error.payload.error.details) {
      var dd = error.payload.error.details;
      if (typeof dd.current_revision === 'number') return dd.current_revision;
    }
    return null;
  }

  /* ── 模型列表 hydration ──
   * GET /v1/ecmc/causal-models 只返回模型摘要（不含 versions）；统一补取模型详情
   * （含 versions）与最新 Version 内容（diagnostic_target / updated_at）。
   * 使用 Promise.all(map) 保持后端列表顺序（不按请求完成顺序输出）。 */
  async function hydrateModels(list) {
    var listArr = list || [];
    return Promise.all(listArr.map(async function (m) {
      var hydrated = { model: m, versions: [], latestVersion: null, latestDetail: null };
      try {
        var mr = await ECMC.api.get('/causal-models/' + encodeURIComponent(m.model_id));
        var detail = mr.body || {};
        hydrated.model = Object.assign({}, m, detail);
        hydrated.versions = detail.versions || [];
        hydrated.latestVersion = hydrated.versions[0] || null;
        if (hydrated.latestVersion) {
          try {
            var vr = await ECMC.api.get('/causal-models/' + encodeURIComponent(m.model_id) + '/versions/' + encodeURIComponent(hydrated.latestVersion.model_version_id));
            hydrated.latestDetail = vr.body || null;
          } catch (_) { hydrated.latestDetail = null; }
        }
      } catch (_) { /* 单模型详情失败时保留摘要，页面按不可见处理 */ }
      return hydrated;
    }));
  }

  /* ── binding_params：按 BindingTemplate params schema 渲染固定字段（§6.2 API 合同：
   * 只可含模板 schema 声明字段，不能携带任意参数/Provider/query）。
   * schema 未解析（无 adapter / 模板无 schema）时禁止新增或修改，仅展示已有值。
   * 每个标量字段使用独立工厂创建闭包，避免多字段共享同一 input。 */
  function scalarField(input) {
    return { getValue: function () { return input.value.trim() || null; } };
  }

  function paramsRowsComponent(container, params, templateRef, readOnly, domain) {
    var adapter = window.ECMC && window.ECMC.catalog ? window.ECMC.catalog.getAdapter() : null;
    var entry = adapter && templateRef ? adapter.lookup(templateRef) : null;
    var schema = entry && entry.params_schema ? entry.params_schema : null;
    var root = document.createElement('div');
    container.appendChild(root);

    if (schema && schema.properties && schema.properties.length) {
      var fields = {};
      schema.properties.forEach(function (p) {
        var row = document.createElement('div');
        row.className = 'ecmc-params-row';
        row.style.marginBottom = '0.5rem';
        var label = document.createElement('div');
        label.style.cssText = 'font-size:0.7rem;color:var(--text-tertiary);margin-bottom:0.2rem';
        label.textContent = (p.label || p.name) + '（' + p.name + '）';
        row.appendChild(label);
        var existing = params && params[p.name] !== undefined ? params[p.name] : null;
        if (p.type === 'ref' && p.kind) {
          var refVal = existing && typeof existing === 'object' ? existing : null;
          // 按 kind + 数据域 + active 过滤（§9.1），domain 由调用方（当前模型数据域）传入
          fields[p.name] = window.ECMC.catalog.refInput(row, { kind: p.kind, domain: domain, value: refVal, readOnly: !!readOnly, onChange: function () {} });
        } else {
          var input = document.createElement('input');
          input.className = 'ecmc-params-value';
          input.style.cssText = 'width:100%;font-size:0.76rem;padding:0.35rem 0.5rem;border:1px solid var(--border-standard);border-radius:var(--radius-md)';
          input.value = existing != null ? String(existing) : '';
          if (readOnly) input.readOnly = true;
          row.appendChild(input);
          // 独立闭包：每个字段绑定自己的 input（避免 var 共享）
          fields[p.name] = scalarField(input);
        }
        root.appendChild(row);
      });
      return {
        collect: function () {
          var out = {};
          Object.keys(fields).forEach(function (name) {
            var v = fields[name].getValue();
            if (v !== null && v !== undefined && v !== '') out[name] = v;
          });
          return out;
        },
      };
    }

    // schema 不可用：只读展示，禁止新增/修改
    var keys = Object.keys(params || {});
    var html = keys.length
      ? keys.map(function (k) {
          return '<div class="ecmc-multi-ref-chip" style="font-family:ui-monospace,monospace;font-size:0.7rem;border:1px solid var(--border-standard);border-radius:var(--radius-md);padding:0.3rem 0.5rem;margin-bottom:0.3rem">'
            + esc(k) + ': ' + esc(String(params[k])) + '</div>';
        }).join('')
      : '';
    html += '<div class="info-box" style="font-size:0.72rem">BindingTemplate 参数 schema 未解析：参数由模板 schema 声明，不可新增或修改；接入 Resolver 后按 schema 渲染固定字段。</div>';
    root.innerHTML = html;
    return { collect: function () { return params || {}; } };
  }

  /* ── test-only Catalog 模式透传（§9.3/§21）──
   * fake 模式判断：已启用的 test-only adapter（加载了 catalog-picker 的页面）
   * 或当前 URL 显式带 catalog=fake（概览/审核/编译页未加载 picker 也能透传）。
   * withCatalogParam 避免重复添加已有参数。 */
  function isFakeCatalog() {
    var a = window.ECMC && window.ECMC.catalog ? window.ECMC.catalog.getAdapter() : null;
    if (a && a.testOnly) return true;
    try {
      var loc = (typeof window !== 'undefined' && window.location) ? window.location
        : (typeof location !== 'undefined' ? location : { search: '' });
      return new URLSearchParams(loc.search).get('catalog') === 'fake';
    } catch (_) { return false; }
  }

  function withCatalogParam(url) {
    if (!isFakeCatalog()) return url;
    if (/[?&]catalog=fake(?:&|$)/.test(url)) return url; // 已有则不重复
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'catalog=fake';
  }

  function editorUrl(modelId, versionId) {
    var url = 'ecmc-causal-edit.html?model_id=' + encodeURIComponent(modelId);
    if (versionId) url += '&version_id=' + encodeURIComponent(versionId);
    return withCatalogParam(url);
  }

  window.ECMC = window.ECMC || {};
  window.ECMC.common = {
    esc: esc,
    fmtTime: fmtTime,
    fmtHash: fmtHash,
    governanceBadge: governanceBadge,
    compileBadge: compileBadge,
    readinessBadge: readinessBadge,
    typeBadge: typeBadge,
    requestStatusBadge: requestStatusBadge,
    catalogRefText: catalogRefText,
    toast: toast,
    dialog: dialog,
    confirmDialog: confirmDialog,
    errorBar: errorBar,
    clearErrorBar: clearErrorBar,
    copyText: copyText,
    validationResultFromError: validationResultFromError,
    currentRevisionFromError: currentRevisionFromError,
    hydrateModels: hydrateModels,
    paramsRowsComponent: paramsRowsComponent,
    isFakeCatalog: isFakeCatalog,
    withCatalogParam: withCatalogParam,
    editorUrl: editorUrl,
    GOVERNANCE_LABELS: GOVERNANCE_LABELS,
    READINESS_LABELS: READINESS_LABELS,
    REQUEST_STATUS_LABELS: REQUEST_STATUS_LABELS,
  };
})();
