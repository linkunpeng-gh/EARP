/* ════════════════════════════════════════════════════════════════════════
 * ECMC N01B — 全屏因果模型编辑器（ecmc-causal-editor.js）
 *
 * 设计: FE-ECMC-2026-0830 §5.2 全屏编辑器、§8 因果模型编辑器、§10 校验面板
 *   - 顶部命令栏 52px / 左侧结构面板 220–240px / 中央画布 ≥720px / 右侧属性 320–360px /
 *     底部校验抽屉 收起 40px 展开 240–320px
 *   - 状态化操作（§8.1）：draft→校验/提交审核；in_review→通过并发布/驳回；
 *     published→复制草稿/编译/查看 Artifact；superseded→查看/复制草稿/归档；archived→查看
 *   - 已发布内容只读（§3.3）；Catalog 可执行字段只能由 CatalogRefPicker 产生（§9）
 *   - 画布位置属视图数据，不进入 canonical hash：本地 localStorage 保存个人视图（§8.3），
 *     首版采用确定性自动布局
 *   - 409 VERSION_CONFLICT → 停止写队列 + 冲突对话框 + 重新加载（§8.5）
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var api = window.ECMC.api;
  var common = window.ECMC.common;
  var esc = common.esc;

  var S = {
    model: null, version: null, governance: null,
    client: null, selected: null, validation: null,
    editing: false, readOnly: false,
  };

  var $ = function (id) { return document.getElementById(id); };

  /* ── 视图数据（localStorage，仅个人视图，不上送 API）── */
  function viewKey() {
    var m = (S.model && S.model.model_id) || '';
    var v = (S.version && S.version.model_version_id) || '';
    return 'ecmc:view:' + m + ':' + v;
  }
  function loadView() {
    try { return JSON.parse(localStorage.getItem(viewKey())) || null; } catch (_) { return null; }
  }
  function saveView() {
    if (!S.canvas) return;
    var pos = S.canvas.getPositions();
    localStorage.setItem(viewKey(), JSON.stringify({ nodes: pos, zoom: S.canvas.zoom, pan: S.canvas.pan }));
  }

  /* ═══════════════ 命令栏 ═══════════════ */
  function renderCommandBar() {
    var model = S.model, version = S.version;
    $('cb-name').textContent = model.name;
    $('cb-name').title = model.model_id;

    var vs = model.versions || [];
    var sel = $('cb-version');
    sel.innerHTML = vs.map(function (v) {
      return '<option value="' + esc(v.model_version_id) + '"' + (v.model_version_id === version.model_version_id ? ' selected' : '') + '>v' + esc(v.version) + ' · ' + esc(v.status) + '</option>';
    }).join('');

    $('cb-status').innerHTML = common.governanceBadge(version.status);
    var ap = model.active_pointer || {};
    $('cb-active').innerHTML = ap.model_version_id === version.model_version_id ? '<span class="ecmc-badge active">ACTIVE</span>' : '';
    $('cb-revision').textContent = 'revision ' + version.revision;

    renderActions();
  }

  function renderActions() {
    var box = $('cb-actions');
    var v = S.version;
    var editable = v.status === 'draft';
    S.readOnly = !editable;
    var html = '';
    if (v.status === 'draft') {
      html = '<button class="btn secondary btn-sm" data-act="validate">校验</button>'
        + '<button class="btn btn-sm" data-act="submit">提交审核</button>'
        + '<button class="btn secondary btn-sm" data-act="more">更多 ▾</button>';
    } else if (v.status === 'in_review') {
      html = '<button class="btn btn-sm btn-approve" data-act="approve">通过并发布</button>'
        + '<button class="btn secondary btn-sm" data-act="reject">驳回</button>';
    } else if (v.status === 'published') {
      html = '<button class="btn secondary btn-sm" data-act="clone">复制为新草稿</button>'
        + '<button class="btn btn-sm" data-act="compile">编译</button>'
        + '<button class="btn secondary btn-sm" data-act="artifact">查看 Artifact</button>'
        + (S.governance && S.governance.compile_record && S.governance.compile_record.status === 'success'
          ? '<button class="btn btn-sm btn-approve" data-act="activate">激活</button>'
          : '')
        + '<button class="btn secondary btn-sm" data-act="more2">更多 ▾</button>';
    } else if (v.status === 'superseded') {
      html = '<button class="btn secondary btn-sm" data-act="clone">复制为新草稿</button>'
        + '<button class="btn secondary btn-sm" data-act="archive">归档</button>';
    } else { // archived
      html = '';
    }
    box.innerHTML = html;
    Array.prototype.forEach.call(box.querySelectorAll('[data-act]'), function (b) {
      b.addEventListener('click', function () { handleAction(b.dataset.act); });
    });
  }

  function setSaveState(text, cls) {
    var el = $('cb-save-state');
    el.textContent = text;
    el.className = 'cb-save-state ' + (cls || '');
  }

  /* ═══════════════ 数据加载 ═══════════════ */
  async function load() {
    var q = new URLSearchParams(location.search);
    var modelId = q.get('model_id');
    if (q.get('catalog') === 'fake') ECMC.catalog.enableFake();
    if (!modelId) { location.href = common.withCatalogParam('ecmc-models.html'); return; }
    try {
      var mr = await api.get('/causal-models/' + encodeURIComponent(modelId));
      S.model = mr.body;
      var versionId = q.get('version_id') || (S.model.versions && S.model.versions[0] && S.model.versions[0].model_version_id);
      var vr = await api.get('/causal-models/' + encodeURIComponent(modelId) + '/versions/' + encodeURIComponent(versionId));
      S.version = vr.body;
      S.client = new api.VersionClient(modelId, versionId, S.version.revision, onVersionConflict);
      renderCommandBar();
      renderStruct();
      renderCanvas();
      renderInspector(null);
      renderValidationSummary();
      try { var g = await api.get(ECMC.governance.vUrl(modelId, versionId) + '/governance'); S.governance = g.body; renderReadOnlyPanel(); } catch (_) {}
    } catch (e) {
      common.errorBar($('ecmc-errorbar'), e);
      $('ecmc-loading').style.display = 'block';
      $('ecmc-loading').textContent = '加载失败：' + e.message;
    }
  }

  function onVersionConflict(err) {
    setSaveState('保存失败：版本冲突', 'error');
    var rev = common.currentRevisionFromError(err);
    var d = common.dialog(
      '<div class="ecmc-dialog-head"><h3>版本已被其他用户更新</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="ecmc-conflict-icon">!</div>'
      + '<div class="info-box">本页面基于旧 revision' + (S.version ? '（revision ' + esc(S.version.revision) + '）' : '') + '编辑。'
      + '该 Version 已在别处被更新' + (rev != null ? '（当前 revision ' + rev + '）' : '') + '。'
      + '<br><br><b>不会静默覆盖</b>：请重新加载最新内容后再编辑。</div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn" data-reload>重新加载</button>'
      + '<button class="btn secondary" data-close2>稍后</button></div>'
    );
    d.on('[data-reload]', 'click', function () { location.reload(); });
    d.on('[data-close]', 'click', function () { d.close(); });
    d.on('[data-close2]', 'click', function () { d.close(); });
  }

  async function reloadVersion() {
    if (!S.model || !S.version) return;
    try {
      var vr = await api.get('/causal-models/' + encodeURIComponent(S.model.model_id) + '/versions/' + encodeURIComponent(S.version.model_version_id));
      S.version = vr.body;
      S.client.refresh(S.version.revision);
      renderCommandBar();
      renderStruct();
      renderCanvas();
      renderValidationSummary();
    } catch (e) { common.toast('重新加载失败：' + e.message, 'error'); }
  }

  async function switchVersion(versionId) {
    location.href = common.editorUrl(S.model.model_id, versionId);
  }

  /* ═══════════════ 动作 ═══════════════ */
  async function handleAction(act) {
    var model = S.model, version = S.version;
    try {
      if (act === 'validate') return runValidate();
      if (act === 'submit') {
        var sub = await ECMC.governance.submitReview(S.client, model, version, function (result) {
          S.validation = result;
          renderValidation(result, true);
        });
        if (sub) await reloadVersion();
        return;
      }
      if (act === 'approve') {
        var ok = await ECMC.governance.publishConfirm(model, version, S.validation);
        if (!ok) return;
        var res = await S.client.mutate('POST', ECMC.governance.vUrl(model.model_id, version.model_version_id) + '/publish', null, {});
        common.toast('已发布 · Snapshot ' + (res.body.snapshot_id || '') + ' · hash ' + common.fmtHash(res.body.content_hash), 'success', 5000);
        await reloadVersion();
        return;
      }
      if (act === 'reject') {
        var rej = await ECMC.governance.rejectReview(S.client, model, version);
        if (rej) await reloadVersion();
        return;
      }
      if (act === 'clone') {
        var c = await api.post('/causal-models/' + encodeURIComponent(model.model_id) + '/versions', { clone_from_version_id: version.model_version_id }, { idempotencyKey: api.idempotencyKey() });
        location.href = common.editorUrl(model.model_id, c.body.model_version_id);
        return;
      }
      if (act === 'compile') {
        var rec = await ECMC.governance.requestCompile(S.client, model, version, null);
        var cr = rec.compile_record || rec;
        common.toast('已请求编译：' + cr.compile_record_id + '（' + (cr.status || 'running') + '）', 'success');
        await loadGovernance();
        return;
      }
      if (act === 'artifact') return viewArtifact();
      if (act === 'activate') return activateVersion();
      if (act === 'archive') {
        var ar = await ECMC.governance.archiveVersion(S.client, model, version);
        if (ar) await reloadVersion();
        return;
      }
      if (act === 'more') {
        common.toast('更多操作：复制为新草稿 / 归档。', 'warn');
        return;
      }
      if (act === 'more2') {
        common.toast('更多操作：复制为新草稿 / 归档；激活需先编译成功。', 'warn');
        return;
      }
    } catch (e) {
      var vresult = common.validationResultFromError(e);
      if (vresult) { S.validation = vresult; renderValidation(vresult, true); common.toast('存在阻断问题，请先修复', 'warn'); }
      else common.errorBar($('ecmc-errorbar'), e);
    }
  }

  async function loadGovernance() {
    try {
      var g = await api.get(ECMC.governance.vUrl(S.model.model_id, S.version.model_version_id) + '/governance');
      S.governance = g.body;
      renderReadOnlyPanel();
      renderActions();
    } catch (_) {}
  }

  /* 激活：Candidate If-Match + active-pointer CAS（§11.5） */
  function activateVersion() {
    var g = S.governance;
    if (!g || !g.compile_record || g.compile_record.status !== 'success') {
      common.toast('需要编译成功的 Attempt 才能激活', 'warn');
      return;
    }
    ECMC.governance.activateConfirm(S.model, S.version, g.compile_record, g, async function (body) {
      var res = await S.client.mutate('POST', '/causal-models/' + encodeURIComponent(S.model.model_id) + '/activate', body, {});
      await reloadVersion();
      await loadGovernance();
      return res;
    }, async function () {
      // ACTIVE_VERSION_CHANGED：重新读取 governance（含最新 active pointer），不自动重试
      try {
        var gr = await api.get(ECMC.governance.vUrl(S.model.model_id, S.version.model_version_id) + '/governance');
        S.governance = gr.body;
        renderReadOnlyPanel();
        renderActions();
        return S.governance;
      } catch (_) { return null; }
    });
  }

  async function viewArtifact() {
    if (!S.governance || !S.governance.compile_record || S.governance.compile_record.status !== 'success') {
      common.toast('没有可查看的成功 Artifact（需先编译成功）', 'warn');
      return;
    }
    try {
      var art = await ECMC.governance.fetchArtifact(S.model, S.version, S.governance.compile_record.compile_record_id);
      var d = common.dialog(
        '<div class="ecmc-dialog-head"><h3>Candidate Artifact（只读）</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
        + '<div class="ecmc-dialog-body">'
        + '<div class="kv"><dt>schema</dt><dd class="mono">' + esc(art.artifact_schema_version) + '</dd>'
        + '<dt>hash</dt><dd class="mono">' + esc(art.compiled_artifact_hash) + '</dd></div>'
        + '<pre style="max-height:340px;overflow:auto;font-size:0.7rem">' + esc(JSON.stringify(art.compiled_artifact, null, 2)) + '</pre>'
        + '</div>'
        + '<div class="ecmc-dialog-foot"><button class="btn" data-close2>关闭</button></div>'
      );
      d.on('[data-close]', 'click', function () { d.close(); });
      d.on('[data-close2]', 'click', function () { d.close(); });
    } catch (e) { common.errorBar($('ecmc-errorbar'), e); }
  }

  /* ═══════════════ 校验 ═══════════════ */
  async function runValidate() {
    setSaveState('校验中…', 'saving');
    try {
      var res = await api.post(ECMC.governance.vUrl(S.model.model_id, S.version.model_version_id) + '/validate', { mode: 'full' }, { idempotencyKey: api.idempotencyKey() });
      S.validation = res.body;
      renderValidation(res.body, true);
      var sum = ECMC.validation.summarize(res.body);
      setSaveState('已校验', 'saved');
      common.toast(sum.errors ? '校验：阻断 ' + sum.errors + ' · 警告 ' + sum.warnings : '校验通过', sum.errors ? 'warn' : 'success');
    } catch (e) {
      setSaveState('校验失败', 'error');
      common.errorBar($('ecmc-errorbar'), e);
    }
  }

  function renderValidationSummary() {
    var bar = $('vb-summary');
    var count = $('vb-count');
    if (!S.validation) {
      bar.textContent = '校验结果：尚未运行';
      count.innerHTML = '';
      return;
    }
    var sum = ECMC.validation.summarize(S.validation);
    bar.textContent = '校验结果：' + (S.validation.validation_run_id || '');
    count.innerHTML = '<span class="vb-count error">阻断 ' + sum.errors + '</span><span class="vb-count warning">警告 ' + sum.warnings + '</span>';
  }

  function renderValidation(result, open) {
    S.validation = result;
    ECMC.validation.render($('validation-list'), result);
    var drawer = $('validation-drawer');
    if (open) drawer.classList.add('open');
    renderValidationSummary();
  }

  /* ═══════════════ 只读审核面板（in_review 右侧默认展示治理信息）═══ */
  function renderReadOnlyPanel() {
    var box = $('review-panel');
    var g = S.governance;
    if (!g) { box.style.display = 'none'; return; }
    box.style.display = 'block';
    var cr = g.compile_record;
    box.innerHTML =
      '<h4>治理信息</h4>'
      + '<dl class="ecmc-review-kv">'
      + '<dt>治理状态</dt><dd>' + common.governanceBadge(g.governance_status) + '</dd>'
      + '<dt>激活状态</dt><dd>' + common.readinessBadge(g.runtime_readiness) + '</dd>'
      + '<dt>Compile</dt><dd>' + (cr ? cr.compile_record_id + ' · ' + common.compileBadge(cr.status) : '—') + '</dd>'
      + (cr && cr.compiled_artifact_hash ? '<dt>Artifact hash</dt><dd>' + esc(cr.compiled_artifact_hash) + '</dd>' : '')
      + '<dt>Active pointer</dt><dd class="mono">' + esc((g.active_pointer && g.active_pointer.model_version_id) || '无') + '</dd>'
      + '</dl>';
  }

  /* ═══════════════ 左侧结构面板 ═══════════════ */
  function renderStruct() {
    var v = S.version;
    var body = $('struct-body');
    var q = ($('struct-search') && $('struct-search').value || '').toLowerCase();

    var nodes = (v.nodes || []).filter(function (n) { return !q || (n.business_name || '').toLowerCase().indexOf(q) !== -1 || n.node_key.toLowerCase().indexOf(q) !== -1; });
    var edges = (v.edges || []).filter(function (e) { return !q || e.edge_key.toLowerCase().indexOf(q) !== -1; });
    var rules = (v.rules || []).filter(function (r) { return !q || r.rule_key.toLowerCase().indexOf(q) !== -1; });
    var evs = (v.evidence_requirements || []).filter(function (e) { return !q || e.requirement_key.toLowerCase().indexOf(q) !== -1; });

    var html = '';
    html += '<div class="ecmc-struct-group">图结构</div>';
    html += nodes.map(function (n) {
      var issues = nodeIssueCounts(n);
      return '<div class="ecmc-struct-item" data-sel="node:' + esc(n.node_key) + '">'
        + (n.entry_point ? '● ' : '• ') + esc(n.business_name || n.node_key)
        + (issues.error ? '<span class="si-badge ecmc-badge failed" style="background:var(--red-bg);color:var(--red)">' + issues.error + '</span>' : '')
        + (issues.warning ? '<span class="si-badge" style="background:var(--amber-bg);color:var(--amber)">' + issues.warning + '</span>' : '')
        + '</div>';
    }).join('') || '';
    html += '<div class="ecmc-struct-group">边</div>';
    html += edges.map(function (e) {
      return '<div class="ecmc-struct-item dim" data-sel="edge:' + esc(e.edge_key) + '">→ ' + esc(e.edge_key) + '</div>';
    }).join('') || '';
    html += '<div class="ecmc-struct-group">规则</div>';
    html += rules.map(function (r) {
      return '<div class="ecmc-struct-item dim" data-sel="rule:' + esc(r.rule_key) + '">⚖ ' + esc(r.rule_key) + '</div>';
    }).join('') || '';
    html += '<div class="ecmc-struct-group">证据需求</div>';
    html += evs.map(function (e) {
      return '<div class="ecmc-struct-item dim" data-sel="evidence:' + esc(e.node_key) + ':' + esc(e.requirement_key) + '">◈ ' + esc(e.requirement_key) + '</div>';
    }).join('') || '';

    body.innerHTML = html || '<div class="ecmc-empty-state"><p>暂无内容</p></div>';
    Array.prototype.forEach.call(body.querySelectorAll('[data-sel]'), function (el) {
      el.addEventListener('click', function () { selectResource(el.dataset.sel); });
    });
    $('struct-count').textContent = (v.nodes || []).length + ' 节点 / ' + (v.edges || []).length + ' 边';
  }

  function nodeIssueCounts(node) {
    var err = 0, warn = 0;
    (S.validation && S.validation.issues || []).forEach(function (i) {
      var loc = i.location || {};
      if (loc.node_key !== node.node_key) return;
      if (i.severity === 'error') err++; else if (i.severity === 'warning') warn++;
    });
    return { error: err, warning: warn };
  }

  /* ═══════════════ 画布 ═══════════════ */
  var NODE_W = 168, NODE_H = 74, GAP_X = 90, GAP_Y = 40;

  function renderCanvas() {
    var wrap = $('canvas-wrap');
    if (!S.canvas) {
      S.canvas = new GraphCanvas(wrap, {
        onSelect: function (sel) { selectResource(sel); },
        onMutate: saveView,
        onRequestEdge: requestCreateEdge,
        onRequestDelete: requestDeleteResource,
        getContent: function () { return S.version; },
      });
    }
    S.canvas.render(S.version, S.validation, loadView());
  }

  function layoutPositions(nodes, edges) {
    var W = NODE_W + GAP_X, H = NODE_H + GAP_Y;
    var keyTo = {}; nodes.forEach(function (n) { keyTo[n.node_key] = []; });
    edges.forEach(function (e) { if (keyTo[e.from_node_key]) keyTo[e.from_node_key].push(e.to_node_key); });
    var dist = {};
    nodes.forEach(function (n) { dist[n.node_key] = 0; });
    // 最长路径分层（因果边 cause→effect，入口 target 在最右）
    var changed = true;
    while (changed) {
      changed = false;
      nodes.forEach(function (n) {
        keyTo[n.node_key].forEach(function (t) {
          if (dist[t] < dist[n.node_key] + 1) { dist[t] = dist[n.node_key] + 1; changed = true; }
        });
      });
    }
    var layers = {};
    var order = {};
    nodes.forEach(function (n) {
      var l = dist[n.node_key] || 0;
      layers[l] = layers[l] || [];
      order[n.node_key] = l;
      layers[l].push(n.node_key);
    });
    var indexInLayer = {};
    Object.keys(layers).forEach(function (l) {
      layers[l].sort();
      layers[l].forEach(function (key, i) { indexInLayer[key] = i; });
    });
    var pos = {};
    nodes.forEach(function (n) {
      pos[n.node_key] = {
        x: 40 + (order[n.node_key] || 0) * W,
        y: 40 + (indexInLayer[n.node_key] || 0) * H,
      };
    });
    return pos;
  }

  /* GraphCanvas：视图层（节点 div + SVG 边）；位置仅本地视图 */
  function GraphCanvas(container, hooks) {
    this.container = container;
    this.hooks = hooks;
    this.zoom = 1;
    this.pan = { x: 0, y: 0 };
    this.positions = {};
    this.selected = null;
    this.version = null;
    this.validation = null;
    this._nodeDrag = null; // {key, sx, sy, ox, oy, el}
    this._portDrag = null; // {fromKey, port, ghost}
    this._panDrag = null;  // {sx, sy, ox, oy}

    this.viewport = document.createElement('div');
    this.viewport.className = 'ecmc-canvas-viewport';
    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.setAttribute('class', 'ecmc-canvas-edges');
    this.svg.style.overflow = 'visible';
    this.viewport.appendChild(this.svg);
    container.appendChild(this.viewport);

    this._bindDocumentDrag();
    this._bindPan();
  }

  // 文档级拖拽统一处理：节点移动 / 端口建边 / 背景平移（只注册一次，避免重渲染累积监听）
  GraphCanvas.prototype._bindDocumentDrag = function () {
    var self = this;
    document.addEventListener('mousemove', function (e) {
      if (self._nodeDrag) {
        var d = self._nodeDrag;
        d.pos.x = d.ox + (e.clientX - d.sx) / self.zoom;
        d.pos.y = d.oy + (e.clientY - d.sy) / self.zoom;
        d.el.style.left = d.pos.x + 'px';
        d.el.style.top = d.pos.y + 'px';
        self._renderEdges();
        return;
      }
      if (self._portDrag) {
        var p = self._screenToViewport(e.clientX, e.clientY);
        var from = self._portPos(self._portDrag.fromKey, self._portDrag.port);
        self._portDrag.ghost.setAttribute('x1', from.x);
        self._portDrag.ghost.setAttribute('y1', from.y);
        self._portDrag.ghost.setAttribute('x2', p.x);
        self._portDrag.ghost.setAttribute('y2', p.y);
        return;
      }
      if (self._panDrag) {
        self.pan.x = self._panDrag.ox + (e.clientX - self._panDrag.sx);
        self.pan.y = self._panDrag.oy + (e.clientY - self._panDrag.sy);
        self._applyTransform();
      }
    });
    document.addEventListener('mouseup', function (e) {
      if (self._nodeDrag) {
        self._nodeDrag = null;
        self.hooks.onMutate();
        return;
      }
      if (self._portDrag) {
        var target = document.elementFromPoint(e.clientX, e.clientY);
        var inPort = target && target.classList && target.classList.contains('ecmc-port') && target.dataset.port === 'in';
        if (inPort) {
          var nodeEl = target.closest('.ecmc-node');
          var toKey = nodeEl.querySelector('.ecmc-node-key').textContent;
          if (toKey !== self._portDrag.fromKey) self.hooks.onRequestEdge(self._portDrag.fromKey, toKey);
        }
        if (self._portDrag.ghost) { self._portDrag.ghost.remove(); }
        Array.prototype.forEach.call(self.viewport.querySelectorAll('.ecmc-port.dragging'), function (p) { p.classList.remove('dragging'); });
        self._portDrag = null;
        return;
      }
      self._panDrag = null;
    });
  };

  GraphCanvas.prototype.render = function (version, validation, view) {
    this.version = version;
    this.validation = validation;
    if (view && view.nodes) {
      // 已有视图：新出现的节点并入确定性布局，避免叠在一起
      var layout = layoutPositions(version.nodes || [], version.edges || []);
      this.positions = {};
      (version.nodes || []).forEach(function (n) {
        this.positions[n.node_key] = view.nodes[n.node_key] || layout[n.node_key] || { x: 40, y: 40 };
      }, this);
      if (view.zoom) this.zoom = view.zoom;
      if (view.pan) this.pan = view.pan;
    } else {
      this.positions = layoutPositions(version.nodes || [], version.edges || []);
      this.zoom = 0.9;
      this.pan = { x: 20, y: 20 };
    }
    this._renderNodes();
    this._renderEdges();
    this._applyTransform();
  };

  GraphCanvas.prototype.getPositions = function () { return this.positions; };

  GraphCanvas.prototype._nodeById = function (key) {
    return (this.version.nodes || []).find(function (n) { return n.node_key === key; });
  };
  GraphCanvas.prototype._edgeById = function (key) {
    return (this.version.edges || []).find(function (e) { return e.edge_key === key; });
  };

  GraphCanvas.prototype._renderNodes = function () {
    var self = this;
    // 移除旧节点
    Array.prototype.forEach.call(this.viewport.querySelectorAll('.ecmc-node'), function (el) { el.remove(); });
    var version = this.version;
    var required = {};
    (version.evidence_requirements || []).forEach(function (e) {
      if (e.required) required[e.node_key] = (required[e.node_key] || 0) + 1;
    });

    (version.nodes || []).forEach(function (n) {
      var pos = self.positions[n.node_key] || { x: 40, y: 40 };
      var issues = nodeIssueCounts(n);
      var el = document.createElement('div');
      el.className = 'ecmc-node'
        + (n.entry_point ? ' entry' : '')
        + (issues.error ? ' has-error' : (issues.warning ? ' has-warning' : ''))
        + (n.observability === 'latent_hypothesis' ? ' latent' : '');
      el.style.left = pos.x + 'px';
      el.style.top = pos.y + 'px';
      el.style.width = NODE_W + 'px';
      el.innerHTML =
        '<div class="ecmc-node-header"><span class="ecmc-node-name">' + esc(n.business_name || n.node_key) + '</span>'
        + (n.entry_point ? '<span class="ecmc-node-entry-mark">入口</span>' : '') + '</div>'
        + '<div class="ecmc-node-key">' + esc(n.node_key) + '</div>'
        + '<div class="ecmc-node-type">' + esc((n.entity_type_ref && n.entity_type_ref.stable_id) || '') + (n.observability ? ' · ' + esc(n.observability) : '') + '</div>'
        + '<div class="ecmc-node-foot">'
        + '<span class="ecmc-node-evidence ' + (required[n.node_key] ? 'complete' : 'missing') + '">'
        + (required[n.node_key] ? '✓ 证据 ' + required[n.node_key] : '缺证据') + '</span>'
        + '<span class="ecmc-node-issues">'
        + (issues.error ? '<span class="ecmc-node-issue error">' + issues.error + '</span>' : '')
        + (issues.warning ? '<span class="ecmc-node-issue warning">' + issues.warning + '</span>' : '')
        + '</span></div>'
        + '<span class="ecmc-port in" data-port="in" title="拖拽创建入边"></span>'
        + '<span class="ecmc-port out" data-port="out" title="拖拽创建出边"></span>';

      // 点击选中
      el.addEventListener('click', function (e) {
        if (e.target.classList.contains('ecmc-port')) return;
        self.select({ type: 'node', key: n.node_key });
      });
      // 拖拽移动（仅视图）：设置共享状态，由文档级监听驱动
      el.addEventListener('mousedown', function (e) {
        if (e.target.classList.contains('ecmc-port')) return;
        self._nodeDrag = { key: n.node_key, pos: pos, sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y, el: el };
        e.preventDefault();
      });
      this.viewport.appendChild(el);
    }, this);

    // 端口拖拽建边：仅设置共享状态
    Array.prototype.forEach.call(this.viewport.querySelectorAll('.ecmc-port'), function (port) {
      port.addEventListener('mousedown', function (e) {
        if (self.readOnly) return;
        e.stopPropagation();
        var nodeEl = port.closest('.ecmc-node');
        var key = nodeEl.querySelector('.ecmc-node-key').textContent;
        port.classList.add('dragging');
        var ghost = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        ghost.setAttribute('stroke', 'var(--accent)');
        ghost.setAttribute('stroke-width', '2');
        ghost.setAttribute('stroke-dasharray', '5,4');
        self.svg.appendChild(ghost);
        self._portDrag = { fromKey: key, port: port.dataset.port, ghost: ghost };
        e.preventDefault();
      });
    });
  };

  GraphCanvas.prototype._portPos = function (nodeKey, port) {
    var el = this.viewport.querySelector('.ecmc-node .ecmc-node-key');
    var nodeEl = null;
    Array.prototype.forEach.call(this.viewport.querySelectorAll('.ecmc-node'), function (n) {
      if (n.querySelector('.ecmc-node-key').textContent === nodeKey) nodeEl = n;
    });
    if (!nodeEl) return { x: 0, y: 0 };
    var pos = this.positions[nodeKey] || { x: 0, y: 0 };
    var y = pos.y + NODE_H / 2;
    return port === 'out' ? { x: pos.x + NODE_W, y: y } : { x: pos.x, y: y };
  };

  GraphCanvas.prototype._screenToViewport = function (sx, sy) {
    var rect = this.container.getBoundingClientRect();
    return {
      x: (sx - rect.left - this.pan.x) / this.zoom,
      y: (sy - rect.top - this.pan.y) / this.zoom,
    };
  };

  GraphCanvas.prototype._renderEdges = function () {
    var self = this;
    this.svg.innerHTML = '';
    this.svg.setAttribute('width', 4000);
    this.svg.setAttribute('height', 4000);
    (this.version.edges || []).forEach(function (e) {
      var from = self._portPos(e.from_node_key, 'out');
      var to = self._portPos(e.to_node_key, 'in');
      var dx = Math.max(70, (to.x - from.x) / 2);
      var d = 'M' + from.x + ',' + from.y + ' C' + (from.x + dx) + ',' + from.y + ' ' + (to.x - dx) + ',' + to.y + ' ' + to.x + ',' + to.y;
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', 'var(--border-standard)');
      path.setAttribute('stroke-width', '2');
      path.setAttribute('data-edge', e.edge_key);
      var selected = self.selected && self.selected.type === 'edge' && self.selected.key === e.edge_key;
      if (selected) path.setAttribute('stroke', 'var(--accent)');
      path.setAttribute('stroke-width', selected ? '2.5' : '2');
      // 箭头
      var marker = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      var ang = Math.atan2(to.y - from.y, to.x - from.x);
      var ax = to.x - 8, ay = to.y - 8 * Math.tan(ang) * 0;
      marker.setAttribute('d', 'M' + (to.x - 10) + ',' + (to.y - 5) + ' L' + to.x + ',' + to.y + ' L' + (to.x - 10) + ',' + (to.y + 5));
      marker.setAttribute('fill', selected ? 'var(--accent)' : 'var(--border-standard)');
      self.svg.appendChild(path);
      self.svg.appendChild(marker);
      // 标签 effect/strength/confidence/lag
      var midX = (from.x + to.x) / 2, midY = (from.y + to.y) / 2 - 8;
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      var text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      var label = (e.effect || '') + ' ' + (e.strength || '') + ' · c' + (e.confidence || '') + (e.lag && e.lag !== 'PT0S' ? ' · ' + e.lag : '');
      text.setAttribute('x', midX);
      text.setAttribute('y', midY);
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('class', 'ecmc-edge-label ' + (e.effect === '-' ? 'negative' : 'positive'));
      text.textContent = label;
      g.appendChild(text);
      g.addEventListener('click', function () { self.select({ type: 'edge', key: e.edge_key }); });
      self.svg.appendChild(g);
    });
  };

  GraphCanvas.prototype.select = function (sel) {
    this.selected = sel;
    Array.prototype.forEach.call(this.viewport.querySelectorAll('.ecmc-node'), function (el) { el.classList.remove('selected'); });
    if (sel && sel.type === 'node') {
      var keyEl = this.viewport.querySelector('.ecmc-node.selected');
      Array.prototype.forEach.call(this.viewport.querySelectorAll('.ecmc-node'), function (n) {
        if (n.querySelector('.ecmc-node-key').textContent === sel.key) n.classList.add('selected');
      });
    }
    this._renderEdges();
    if (this.hooks.onSelect) this.hooks.onSelect(sel);
  };

  GraphCanvas.prototype.centerOn = function (sel) {
    var pos = null;
    if (sel.type === 'node') pos = this.positions[sel.key];
    else if (sel.type === 'edge') {
      var e = this._edgeById(sel.key);
      if (e) {
        var a = this.positions[e.from_node_key], b = this.positions[e.to_node_key];
        if (a && b) pos = { x: (a.x + b.x) / 2 - NODE_W / 2, y: (a.y + b.y) / 2 - NODE_H / 2 };
      }
    }
    if (!pos) return;
    var rect = this.container.getBoundingClientRect();
    this.pan.x = rect.width / 2 - (pos.x + NODE_W / 2) * this.zoom;
    this.pan.y = rect.height / 2 - (pos.y + NODE_H / 2) * this.zoom;
    this._applyTransform();
  };

  GraphCanvas.prototype._applyTransform = function () {
    this.viewport.style.transform = 'translate(' + this.pan.x + 'px,' + this.pan.y + 'px) scale(' + this.zoom + ')';
    $('canvas-zoom-value').textContent = Math.round(this.zoom * 100) + '%';
  };

  GraphCanvas.prototype.zoomBy = function (factor) {
    this.zoom = Math.min(2.5, Math.max(0.3, this.zoom * factor));
    this._applyTransform();
  };

  GraphCanvas.prototype.fit = function () {
    var self = this;
    var keys = Object.keys(this.positions);
    if (!keys.length) return;
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    keys.forEach(function (k) {
      var p = self.positions[k];
      minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + NODE_W); maxY = Math.max(maxY, p.y + NODE_H);
    });
    var rect = this.container.getBoundingClientRect();
    var zoom = Math.min(1.2, Math.max(0.3, Math.min((rect.width - 60) / (maxX - minX + 1), (rect.height - 60) / (maxY - minY + 1))));
    this.zoom = zoom;
    this.pan.x = (rect.width - (maxX + minX) * zoom) / 2;
    this.pan.y = (rect.height - (maxY + minY) * zoom) / 2;
    this._applyTransform();
  };

  GraphCanvas.prototype._bindPan = function () {
    var self = this;
    this.container.addEventListener('mousedown', function (e) {
      if (e.target !== self.container && !e.target.classList.contains('ecmc-canvas')) return;
      self._panDrag = { sx: e.clientX, sy: e.clientY, ox: self.pan.x, oy: self.pan.y };
    });
    this.container.addEventListener('wheel', function (e) {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        self.zoomBy(e.deltaY > 0 ? 0.9 : 1.1);
      } else {
        self.pan.x -= e.deltaX;
        self.pan.y -= e.deltaY;
        self._applyTransform();
      }
    }, { passive: false });
  };

  /* ═══════════════ 资源选择与属性面板 ═══════════════ */
  function selectResource(sel) {
    if (typeof sel === 'string') {
      var parts = sel.split(':');
      if (parts[0] === 'evidence') sel = { type: 'evidence', nodeKey: parts[1], key: parts[2] };
      else sel = { type: parts[0], key: parts[1] };
    }
    S.selected = sel;
    if (S.canvas) S.canvas.select(sel);
    renderStructActive(sel);
    renderInspector(sel);
  }

  function renderStructActive(sel) {
    Array.prototype.forEach.call($('struct-body').querySelectorAll('.ecmc-struct-item'), function (el) {
      el.classList.remove('active');
    });
    if (!sel) return;
    var target = sel.type === 'evidence' ? 'evidence:' + sel.nodeKey + ':' + sel.key : sel.type + ':' + sel.key;
    var el = $('struct-body').querySelector('[data-sel="' + CSS.escape(target) + '"]');
    if (el) el.classList.add('active');
  }

  function renderInspector(sel) {
    var box = $('inspector-body');
    var head = $('inspector-head');
    if (!sel) {
      head.innerHTML = '<h4>属性</h4><span class="ih-type">未选中</span>';
      box.innerHTML = '<div class="ecmc-inspector-empty">点击画布节点、边或左侧大纲查看/编辑属性。<br>可执行字段只能从受控目录选择。</div>';
      return;
    }
    if (sel.type === 'node') renderNodeInspector(box, head, sel);
    else if (sel.type === 'edge') renderEdgeInspector(box, head, sel);
    else if (sel.type === 'evidence') renderEvidenceInspector(box, head, sel);
    else if (sel.type === 'rule') renderRuleInspector(box, head, sel);
  }

  function field(name, html) {
    return '<div class="ecmc-field' + (S.readOnly ? ' readonly' : '') + '"><label>' + name + '</label>' + html + '</div>';
  }

  /* binding_params 由 ECMC.common.paramsRowsComponent 提供（按 BindingTemplate
   * params schema 渲染固定字段；schema 未解析时只读）。 */

  function renderNodeInspector(box, head, sel) {
    var n = (S.version.nodes || []).find(function (x) { return x.node_key === sel.key; });
    if (!n) { box.innerHTML = '<div class="ecmc-inspector-empty">节点不存在</div>'; return; }
    head.innerHTML = '<h4>' + esc(n.business_name || n.node_key) + '</h4><span class="ih-type">NODE</span>';
    box.innerHTML =
      field('node key（创建后只读）', '<input readonly value="' + esc(n.node_key) + '">')
      + field('业务名称', '<input id="n-name" value="' + esc(n.business_name || '') + '">')
      + field('EntityType CatalogRef', '<div id="n-entity"></div>')
      + field('observability', '<select id="n-obs">'
        + ['observable', 'indirectly_observable', 'latent_hypothesis'].map(function (o) {
          return '<option value="' + o + '"' + (n.observability === o ? ' selected' : '') + '>' + o + '</option>';
        }).join('') + '</select>')
      + field('entry point', '<label style="display:flex;align-items:center;gap:0.4rem;font-weight:400"><input type="checkbox" id="n-entry" ' + (n.entry_point ? 'checked' : '') + '> 入口节点</label>')
      + field('notes', '<textarea id="n-notes" rows="3">' + esc(n.notes || '') + '</textarea>')
      + '<div class="ecmc-inspector-actions">'
      + (S.readOnly ? '' : '<button class="btn" id="n-save">应用</button>')
      + (S.readOnly ? '' : '<button class="btn secondary" id="n-del">删除节点</button>')
      + '<button class="btn secondary" id="n-ev">+ 证据需求</button>'
      + '</div>';

    var entityPicker = ECMC.catalog.Picker(box.querySelector('#n-entity'), {
      kind: 'entity_type', domain: S.model.data_domain_id, value: n.entity_type_ref, readOnly: S.readOnly, onChange: function () { box.querySelector('#n-save').disabled = false; },
    });

    var saveBtn = box.querySelector('#n-save');
    if (saveBtn) saveBtn.addEventListener('click', async function () {
      var body = {
        entity_type_ref: entityPicker.getValue() || n.entity_type_ref,
        observability: box.querySelector('#n-obs').value,
        entry_point: box.querySelector('#n-entry').checked,
        business_name: box.querySelector('#n-name').value.trim() || null,
        notes: box.querySelector('#n-notes').value.trim() || null,
      };
      await saveResource('PUT', '/nodes/' + encodeURIComponent(n.node_key), body);
    });

    var delBtn = box.querySelector('#n-del');
    if (delBtn) delBtn.addEventListener('click', function () { requestDeleteResource({ type: 'node', key: n.node_key }); });

    var evBtn = box.querySelector('#n-ev');
    if (evBtn) evBtn.addEventListener('click', function () { addEvidence(n.node_key); });
  }

  function renderEdgeInspector(box, head, sel) {
    var e = (S.version.edges || []).find(function (x) { return x.edge_key === sel.key; });
    if (!e) { box.innerHTML = '<div class="ecmc-inspector-empty">边不存在</div>'; return; }
    head.innerHTML = '<h4>' + esc(e.edge_key) + '</h4><span class="ih-type">EDGE</span>';
    box.innerHTML =
      field('edge key（创建后只读）', '<input readonly value="' + esc(e.edge_key) + '">')
      + field('source / target', '<input readonly value="' + esc(e.from_node_key) + ' → ' + esc(e.to_node_key) + '">')
      + field('RelationType CatalogRef', '<div id="e-relation"></div>')
      + field('effect', '<select id="e-effect"><option value="+"' + (e.effect === '+' ? ' selected' : '') + '>+ 正向</option><option value="-"' + (e.effect === '-' ? ' selected' : '') + '>- 负向</option></select>')
      + '<div class="ecmc-field-row">'
      + field('strength [0,1]', '<input id="e-strength" value="' + esc(e.strength || '0.80') + '">')
      + field('confidence [0,1]', '<input id="e-confidence" value="' + esc(e.confidence || '0.90') + '">')
      + '</div>'
      + field('lag（ISO-8601）', '<input id="e-lag" value="' + esc(e.lag || 'PT0S') + '" placeholder="PT0S">')
      + '<div class="ecmc-inspector-actions">'
      + (S.readOnly ? '' : '<button class="btn" id="e-save">应用</button>')
      + (S.readOnly ? '' : '<button class="btn secondary" id="e-del">删除边</button>')
      + '</div>';

    var relationPicker = ECMC.catalog.Picker(box.querySelector('#e-relation'), {
      kind: 'relation_type', domain: S.model.data_domain_id, value: e.relation_type_ref, readOnly: S.readOnly, onChange: function () {},
    });
    var saveBtn = box.querySelector('#e-save');
    if (saveBtn) saveBtn.addEventListener('click', async function () {
      var body = {
        from_node_key: e.from_node_key,
        to_node_key: e.to_node_key,
        relation_type_ref: relationPicker.getValue() || e.relation_type_ref,
        effect: box.querySelector('#e-effect').value,
        strength: box.querySelector('#e-strength').value.trim(),
        confidence: box.querySelector('#e-confidence').value.trim(),
        lag: box.querySelector('#e-lag').value.trim() || 'PT0S',
      };
      await saveResource('PUT', '/edges/' + encodeURIComponent(e.edge_key), body);
    });
    var delBtn = box.querySelector('#e-del');
    if (delBtn) delBtn.addEventListener('click', function () { requestDeleteResource({ type: 'edge', key: e.edge_key }); });
  }

  function renderEvidenceInspector(box, head, sel) {
    var ev = (S.version.evidence_requirements || []).find(function (x) { return x.node_key === sel.nodeKey && x.requirement_key === sel.key; });
    if (!ev) { box.innerHTML = '<div class="ecmc-inspector-empty">证据需求不存在</div>'; return; }
    head.innerHTML = '<h4>' + esc(ev.requirement_key) + '</h4><span class="ih-type">EVIDENCE</span>';
    box.innerHTML =
      field('requirement key（创建后只读）', '<input readonly value="' + esc(ev.requirement_key) + '">')
      + field('metric', '<div id="ev-metric"></div>')
      + '<div class="ecmc-field-row">'
      + field('unit', '<div id="ev-unit"></div>')
      + field('aggregation', '<div id="ev-agg"></div>')
      + '</div>'
      + field('time window', '<div id="ev-window"></div>')
      + field('binding template', '<div id="ev-binding"></div>')
      + field('binding params（按模板 schema 的受控键值）', '<div id="ev-params"></div>')
      + field('required', '<label style="display:flex;align-items:center;gap:0.4rem;font-weight:400"><input type="checkbox" id="ev-required" ' + (ev.required ? 'checked' : '') + '> 必需证据</label>')
      + field('primary Capability Contract', '<div id="ev-primary"></div>')
      + field('supporting contracts（受控目录多选）', '<div id="ev-supporting"></div>')
      + field('business_description', '<textarea id="ev-desc" rows="2">' + esc(ev.business_description || '') + '</textarea>')
      + '<div class="ecmc-inspector-actions">'
      + (S.readOnly ? '' : '<button class="btn" id="ev-save">应用</button>')
      + (S.readOnly ? '' : '<button class="btn secondary" id="ev-del">删除证据</button>')
      + '</div>';

    var domain = S.model.data_domain_id;
    // binding_params：先初始化（供模板变更时重建与保存时读取）
    var paramsRows = common.paramsRowsComponent(box.querySelector('#ev-params'), ev.binding_params || {}, ev.binding_template_ref, S.readOnly, S.model.data_domain_id);
    var pickers = {
      metric: ECMC.catalog.Picker(box.querySelector('#ev-metric'), { kind: 'metric', domain: domain, value: ev.metric_ref, readOnly: S.readOnly, onChange: function () {} }),
      unit: ECMC.catalog.Picker(box.querySelector('#ev-unit'), { kind: 'unit', domain: domain, value: ev.unit_ref, readOnly: S.readOnly, onChange: function () {} }),
      agg: ECMC.catalog.Picker(box.querySelector('#ev-agg'), { kind: 'aggregation', domain: domain, value: ev.aggregation_ref, readOnly: S.readOnly, onChange: function () {} }),
      window: ECMC.catalog.Picker(box.querySelector('#ev-window'), { kind: 'time_window_schema', domain: domain, value: ev.time_window_ref, readOnly: S.readOnly, onChange: function () {} }),
      binding: ECMC.catalog.Picker(box.querySelector('#ev-binding'), { kind: 'binding_template', domain: domain, value: ev.binding_template_ref, readOnly: S.readOnly, onChange: function (ref) {
        // 模板变化：按新模板 schema 重新渲染参数控件，清理不属于新 schema 的参数
        box.querySelector('#ev-params').innerHTML = '';
        paramsRows = common.paramsRowsComponent(box.querySelector('#ev-params'), paramsRows.collect(), ref, S.readOnly, domain);
      } }),
      primary: ECMC.catalog.Picker(box.querySelector('#ev-primary'), { kind: 'capability_contract', domain: domain, value: ev.primary_contract_ref, readOnly: S.readOnly, onChange: function () {} }),
    };
    // supporting contracts：受控多选，排除 primary、去重、精确版本
    var supporting = ECMC.catalog.multiRefInput(box.querySelector('#ev-supporting'), {
      kind: 'capability_contract', domain: domain, value: ev.supporting_contract_refs || [],
      exclude: ev.primary_contract_ref, readOnly: S.readOnly, onChange: function () {},
    });

    var saveBtn = box.querySelector('#ev-save');
    if (saveBtn) saveBtn.addEventListener('click', async function () {
      var body = {
        metric_ref: pickers.metric.getValue() || ev.metric_ref,
        unit_ref: pickers.unit.getValue() || ev.unit_ref,
        aggregation_ref: pickers.agg.getValue() || ev.aggregation_ref,
        time_window_ref: pickers.window.getValue() || ev.time_window_ref,
        binding_template_ref: pickers.binding.getValue() || ev.binding_template_ref,
        binding_params: paramsRows.collect(),
        required: box.querySelector('#ev-required').checked,
        primary_contract_ref: pickers.primary.getValue() || ev.primary_contract_ref,
        supporting_contract_refs: supporting.getValue(),
        business_description: box.querySelector('#ev-desc').value.trim() || null,
      };
      await saveResource('PUT', '/evidence-requirements/' + encodeURIComponent(ev.node_key) + '/' + encodeURIComponent(ev.requirement_key), body);
    });
    var delBtn = box.querySelector('#ev-del');
    if (delBtn) delBtn.addEventListener('click', function () { requestDeleteResource({ type: 'evidence', nodeKey: ev.node_key, key: ev.requirement_key }); });
  }

  function renderRuleInspector(box, head, sel) {
    var r = (S.version.rules || []).find(function (x) { return x.rule_key === sel.key; });
    if (!r) { box.innerHTML = '<div class="ecmc-inspector-empty">规则不存在</div>'; return; }
    head.innerHTML = '<h4>' + esc(r.rule_key) + '</h4><span class="ih-type">RULE</span>';
    box.innerHTML =
      field('rule key（创建后只读）', '<input readonly value="' + esc(r.rule_key) + '">')
      + field('RuleSchema CatalogRef', '<div id="r-schema"></div>')
      + field('rule spec（结构化 JSON）', '<textarea id="r-spec" rows="4">' + esc(JSON.stringify(r.rule_spec || {}, null, 2)) + '</textarea>')
      + field('rationale', '<textarea id="r-rationale" rows="2">' + esc(r.rationale || '') + '</textarea>')
      + '<div class="ecmc-inspector-actions">'
      + (S.readOnly ? '' : '<button class="btn" id="r-save">应用</button>')
      + (S.readOnly ? '' : '<button class="btn secondary" id="r-del">删除规则</button>')
      + '</div>';
    var schemaPicker = ECMC.catalog.Picker(box.querySelector('#r-schema'), {
      kind: 'rule_schema', domain: S.model.data_domain_id, value: r.rule_schema_ref, readOnly: S.readOnly, onChange: function () {},
    });
    var saveBtn = box.querySelector('#r-save');
    if (saveBtn) saveBtn.addEventListener('click', async function () {
      var body;
      try {
        body = {
          rule_schema_ref: schemaPicker.getValue() || r.rule_schema_ref,
          rule_spec: JSON.parse(box.querySelector('#r-spec').value || '{}'),
          rationale: box.querySelector('#r-rationale').value.trim() || null,
        };
      } catch (e) { common.toast('rule spec 必须是合法 JSON', 'warn'); return; }
      await saveResource('PUT', '/rules/' + encodeURIComponent(r.rule_key), body);
    });
    var delBtn = box.querySelector('#r-del');
    if (delBtn) delBtn.addEventListener('click', function () { requestDeleteResource({ type: 'rule', key: r.rule_key }); });
  }

  /* ── 保存资源：串行写队列 + If-Match + Idempotency-Key ── */
  async function saveResource(method, subPath, body) {
    if (S.readOnly) { common.toast('已发布内容只读，请复制为新草稿', 'warn'); return; }
    setSaveState('保存中…', 'saving');
    try {
      var res = await S.client.mutate(method, ECMC.governance.vUrl(S.model.model_id, S.version.model_version_id) + subPath, body, {});
      setSaveState('已保存 · revision ' + S.client.revision, 'saved');
      await reloadVersion();
      common.toast('已保存', 'success');
    } catch (e) {
      setSaveState('保存失败', 'error');
      var vresult = common.validationResultFromError(e);
      if (vresult) { S.validation = vresult; renderValidation(vresult, true); }
      else common.errorBar($('ecmc-errorbar'), e);
    }
  }

  /* ── 新建资源 ── */
  function newKey(prefix, existing) {
    var n = 1;
    var keys = {};
    existing.forEach(function (k) { keys[k] = true; });
    while (keys[prefix + n]) n++;
    return prefix + n;
  }

  /* 无可用 Catalog adapter 时禁止直接写目录引用（§9.3：不假设真实目录存在） */
  function catalogUnavailableDialog(field) {
    common.dialog(
      '<div class="ecmc-dialog-head"><h3>受控目录不可用</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="info-box">「' + esc(field || '可执行字段') + '」只能从受控目录选择。'
      + '生产 Catalog browse/search API 尚未签署（FE-ECMC-2026-0830 §21），当前无法提交该写入。</div>'
      + '<p style="font-size:0.78rem;color:var(--text-tertiary)">可选：<br>'
      + '1. 使用 <code>?catalog=fake</code> 的 test-only 适配器进行界面合成（不会进入生产目录）；<br>'
      + '2. 先到「目录扩展申请」提出缺项，履约后才能引用。</p>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>关闭</button>'
      + '<button class="btn" data-goto>前往目录申请</button></div>'
    ).on('[data-goto]', 'click', function () { location.href = common.withCatalogParam('ecmc-catalog-requests.html'); });
  }

  function addNode() {
    if (S.readOnly) { common.toast('已发布内容只读', 'warn'); return; }
    if (!ECMC.catalog.getAdapter()) { catalogUnavailableDialog('节点实体类型'); return; }
    var domain = S.model.data_domain_id;
    var d = common.dialog(
      '<div class="ecmc-dialog-head"><h3>新增节点</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="ecmc-field"><label>EntityType CatalogRef（受控选择）</label><div id="n-entity-pick"></div></div>'
      + '<div class="ecmc-field"><label>业务名称</label><input id="n-name2" placeholder="例如：运输系统"></div>'
      + '<div class="ecmc-field"><label>observability</label><select id="n-obs2">'
      + '<option value="observable">observable</option><option value="indirectly_observable">indirectly_observable</option><option value="latent_hypothesis">latent_hypothesis</option>'
      + '</select></div>'
      + '<div class="ecmc-field"><label>entry point</label><label style="display:flex;align-items:center;gap:0.4rem;font-weight:400"><input type="checkbox" id="n-entry2"> 入口节点（全模型仅一个）</label></div>'
      + '<div class="field-error" id="n-err2" style="color:var(--red);font-size:0.74rem;display:none"></div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button><button class="btn" data-ok>创建节点</button></div>'
    );
    var picker = ECMC.catalog.Picker(d.el.querySelector('#n-entity-pick'), {
      kind: 'entity_type', domain: domain, emptyLabel: '选择实体类型', onChange: function () {},
    });
    d.on('[data-ok]', 'click', async function () {
      var ref = picker.getValue();
      var errEl = d.el.querySelector('#n-err2');
      if (!ref) { errEl.textContent = '请先从受控目录选择实体类型。'; errEl.style.display = 'block'; return; }
      var key = newKey('n-', (S.version.nodes || []).map(function (n) { return n.node_key; }));
      var body = {
        entity_type_ref: ref,
        observability: d.el.querySelector('#n-obs2').value,
        entry_point: d.el.querySelector('#n-entry2').checked,
        business_name: d.el.querySelector('#n-name2').value.trim() || key,
        notes: null,
      };
      d.close();
      await saveResource('PUT', '/nodes/' + encodeURIComponent(key), body);
      selectResource({ type: 'node', key: key });
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  function addEdge() {
    if (S.readOnly) { common.toast('已发布内容只读', 'warn'); return; }
    if (!ECMC.catalog.getAdapter()) { catalogUnavailableDialog('关系类型'); return; }
    var nodes = S.version.nodes || [];
    if (nodes.length < 2) { common.toast('至少需要两个节点才能创建边', 'warn'); return; }
    var d = common.dialog(
      '<div class="ecmc-dialog-head"><h3>新增边</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="ecmc-field"><label>from（原因）</label><select id="e-from2">' + nodes.map(function (n) { return '<option value="' + esc(n.node_key) + '">' + esc(n.business_name || n.node_key) + '</option>'; }).join('') + '</select></div>'
      + '<div class="ecmc-field"><label>to（结果）</label><select id="e-to2">' + nodes.map(function (n) { return '<option value="' + esc(n.node_key) + '">' + esc(n.business_name || n.node_key) + '</option>'; }).join('') + '</select></div>'
      + '<div class="ecmc-field"><label>RelationType CatalogRef（受控选择）</label><div id="e-rel-pick"></div></div>'
      + '<div class="field-error" id="e-err2" style="color:var(--red);font-size:0.74rem;display:none"></div>'
      + '<div class="info-box">创建后可在右侧属性面板调整 effect / strength / confidence / lag。</div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button><button class="btn" data-ok>创建边</button></div>'
    );
    var picker = ECMC.catalog.Picker(d.el.querySelector('#e-rel-pick'), {
      kind: 'relation_type', domain: S.model.data_domain_id, emptyLabel: '选择关系类型', onChange: function () {},
    });
    d.on('[data-ok]', 'click', function () {
      var fromKey = d.el.querySelector('#e-from2').value;
      var toKey = d.el.querySelector('#e-to2').value;
      var ref = picker.getValue();
      var errEl = d.el.querySelector('#e-err2');
      if (fromKey === toKey) { errEl.textContent = '不允许自环边。'; errEl.style.display = 'block'; return; }
      if (!ref) { errEl.textContent = '请先从受控目录选择关系类型。'; errEl.style.display = 'block'; return; }
      if ((S.version.edges || []).some(function (e) { return e.from_node_key === fromKey && e.to_node_key === toKey; })) {
        errEl.textContent = '该边已存在。'; errEl.style.display = 'block'; return;
      }
      var key = newKey('e-', (S.version.edges || []).map(function (e) { return e.edge_key; }));
      var body = {
        from_node_key: fromKey, to_node_key: toKey,
        relation_type_ref: ref,
        effect: '+', strength: '0.80', confidence: '0.90', lag: 'PT0S',
      };
      d.close();
      saveResource('PUT', '/edges/' + encodeURIComponent(key), body);
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  function addEvidence(nodeKey) {
    if (S.readOnly) { common.toast('已发布内容只读', 'warn'); return; }
    if (!ECMC.catalog.getAdapter()) { catalogUnavailableDialog('证据需求目录项'); return; }
    var domain = S.model.data_domain_id;
    var d = common.dialog(
      '<div class="ecmc-dialog-head"><h3>添加证据需求</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="ecmc-field"><label>所属节点</label><select id="ev-node2">'
      + (S.version.nodes || []).map(function (n) { return '<option value="' + esc(n.node_key) + '"' + (n.node_key === nodeKey ? ' selected' : '') + '>' + esc(n.business_name || n.node_key) + '</option>'; }).join('')
      + '</select></div>'
      + '<div class="ecmc-field"><label>metric（受控）</label><div id="ev-metric-pick"></div></div>'
      + '<div class="ecmc-field"><label>unit（受控）</label><div id="ev-unit-pick"></div></div>'
      + '<div class="ecmc-field"><label>aggregation（受控）</label><div id="ev-agg-pick"></div></div>'
      + '<div class="ecmc-field"><label>time window（受控）</label><div id="ev-window-pick"></div></div>'
      + '<div class="ecmc-field"><label>binding template（受控）</label><div id="ev-binding-pick"></div></div>'
      + '<div id="ev-bindparams"></div>'
      + '<div class="ecmc-field"><label>primary Capability Contract（受控）</label><div id="ev-primary-pick"></div></div>'
      + '<div class="ecmc-field"><label>required</label><label style="display:flex;align-items:center;gap:0.4rem;font-weight:400"><input type="checkbox" id="ev-required2" checked> 必需证据</label></div>'
      + '<div class="field-error" id="ev-err2" style="color:var(--red);font-size:0.74rem;display:none"></div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button><button class="btn" data-ok>创建证据</button></div>'
    );
    var picks = {
      metric: ECMC.catalog.Picker(d.el.querySelector('#ev-metric-pick'), { kind: 'metric', domain: domain, emptyLabel: '选择指标', onChange: function () {} }),
      unit: ECMC.catalog.Picker(d.el.querySelector('#ev-unit-pick'), { kind: 'unit', domain: domain, emptyLabel: '选择单位', onChange: function () {} }),
      agg: ECMC.catalog.Picker(d.el.querySelector('#ev-agg-pick'), { kind: 'aggregation', domain: domain, emptyLabel: '选择聚合', onChange: function () {} }),
      window: ECMC.catalog.Picker(d.el.querySelector('#ev-window-pick'), { kind: 'time_window_schema', domain: domain, emptyLabel: '选择时间窗口', onChange: function () {} }),
      binding: ECMC.catalog.Picker(d.el.querySelector('#ev-binding-pick'), { kind: 'binding_template', domain: domain, emptyLabel: '选择绑定模板', onChange: function (ref) { renderBindParams(ref); } }),
      primary: ECMC.catalog.Picker(d.el.querySelector('#ev-primary-pick'), { kind: 'capability_contract', domain: domain, emptyLabel: '选择能力合同', onChange: function () {} }),
    };
    // binding_params：按所选模板 schema 渲染固定字段；未选模板/schema 未解析时只读提示
    var bindParamsBox = d.el.querySelector('#ev-bindparams');
    var bindParamsCtl = { collect: function () { return {}; } };
    function renderBindParams(ref) {
      bindParamsBox.innerHTML = '';
      if (ref) {
        bindParamsCtl = common.paramsRowsComponent(bindParamsBox, {}, ref, false, S.model.data_domain_id);
      } else {
        bindParamsBox.innerHTML = '<div class="info-box" style="font-size:0.72rem">选择绑定模板后按模板参数 schema 填写绑定参数。</div>';
        bindParamsCtl = { collect: function () { return {}; } };
      }
    }
    renderBindParams(null);
    d.on('[data-ok]', 'click', async function () {
      var errEl = d.el.querySelector('#ev-err2');
      var missing = ['metric', 'unit', 'agg', 'window', 'binding', 'primary'].filter(function (k) { return !picks[k].getValue(); });
      if (missing.length) {
        errEl.textContent = '请先从受控目录选择：' + missing.join('、') + '。';
        errEl.style.display = 'block';
        return;
      }
      var node = d.el.querySelector('#ev-node2').value;
      var reqKey = newKey(node + '_req_', (S.version.evidence_requirements || []).filter(function (e) { return e.node_key === node; }).map(function (e) { return e.requirement_key; }));
      var body = {
        metric_ref: picks.metric.getValue(),
        unit_ref: picks.unit.getValue(),
        aggregation_ref: picks.agg.getValue(),
        time_window_ref: picks.window.getValue(),
        binding_template_ref: picks.binding.getValue(),
        binding_params: bindParamsCtl.collect(),
        required: d.el.querySelector('#ev-required2').checked,
        primary_contract_ref: picks.primary.getValue(),
        supporting_contract_refs: [],
        business_description: null,
      };
      d.close();
      await saveResource('PUT', '/evidence-requirements/' + encodeURIComponent(node) + '/' + encodeURIComponent(reqKey), body);
      selectResource({ type: 'evidence', nodeKey: node, key: reqKey });
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  function addRule() {
    if (S.readOnly) { common.toast('已发布内容只读', 'warn'); return; }
    if (!ECMC.catalog.getAdapter()) { catalogUnavailableDialog('规则 Schema'); return; }
    var d = common.dialog(
      '<div class="ecmc-dialog-head"><h3>新增规则</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">'
      + '<div class="ecmc-field"><label>RuleSchema CatalogRef（受控选择）</label><div id="r-schema-pick"></div></div>'
      + '<div class="ecmc-field"><label>rule spec（结构化 JSON，由所选 Schema 校验）</label><textarea id="r-spec2" rows="4">' + esc(JSON.stringify({ operator: 'matches_direction', expected: 'down' }, null, 2)) + '</textarea></div>'
      + '<div class="ecmc-field"><label>rationale</label><textarea id="r-rat2" rows="2"></textarea></div>'
      + '<div class="field-error" id="r-err2" style="color:var(--red);font-size:0.74rem;display:none"></div>'
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button><button class="btn" data-ok>创建规则</button></div>'
    );
    var picker = ECMC.catalog.Picker(d.el.querySelector('#r-schema-pick'), {
      kind: 'rule_schema', domain: S.model.data_domain_id, emptyLabel: '选择规则 Schema', onChange: function () {},
    });
    d.on('[data-ok]', 'click', async function () {
      var errEl = d.el.querySelector('#r-err2');
      var ref = picker.getValue();
      if (!ref) { errEl.textContent = '请先从受控目录选择规则 Schema。'; errEl.style.display = 'block'; return; }
      var spec;
      try { spec = JSON.parse(d.el.querySelector('#r-spec2').value || '{}'); }
      catch (_) { errEl.textContent = 'rule spec 必须是合法 JSON。'; errEl.style.display = 'block'; return; }
      var key = newKey('r-', (S.version.rules || []).map(function (r) { return r.rule_key; }));
      var body = {
        rule_schema_ref: ref,
        rule_spec: spec,
        rationale: d.el.querySelector('#r-rat2').value.trim() || null,
      };
      d.close();
      await saveResource('PUT', '/rules/' + encodeURIComponent(key), body);
      selectResource({ type: 'rule', key: key });
    });
    d.on('[data-cancel]', 'click', function () { d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
  }

  function requestDeleteResource(sel) {
    if (S.readOnly) { common.toast('已发布内容只读，请复制为新草稿', 'warn'); return; }
    var deps = [];
    var label = '';
    var path = '';
    if (sel.type === 'node') {
      label = '节点 ' + sel.key;
      path = '/nodes/' + encodeURIComponent(sel.key);
      (S.version.edges || []).forEach(function (e) {
        if (e.from_node_key === sel.key || e.to_node_key === sel.key) deps.push({ kind: '边', id: e.edge_key });
      });
      (S.version.evidence_requirements || []).forEach(function (e) {
        if (e.node_key === sel.key) deps.push({ kind: '证据需求', id: e.requirement_key });
      });
    } else if (sel.type === 'edge') {
      label = '边 ' + sel.key;
      path = '/edges/' + encodeURIComponent(sel.key);
    } else if (sel.type === 'evidence') {
      label = '证据 ' + sel.key;
      path = '/evidence-requirements/' + encodeURIComponent(sel.nodeKey) + '/' + encodeURIComponent(sel.key);
    } else if (sel.type === 'rule') {
      label = '规则 ' + sel.key;
      path = '/rules/' + encodeURIComponent(sel.key);
    }
    var depsHtml = deps.length
      ? '<div class="info-box">该资源仍有依赖，需先删除：<ul class="ecmc-deps">'
        + deps.map(function (d) { return '<li><span class="deps-kind">' + esc(d.kind) + '</span>' + esc(d.id) + '</li>'; }).join('')
        + '</ul></div>'
      : '';
    var d = common.dialog(
      '<div class="ecmc-dialog-head"><h3>删除' + esc(label) + '</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
      + '<div class="ecmc-dialog-body">' + depsHtml
      + (deps.length
        ? '<div class="info-box">请先在画布/大纲中删除上述依赖，再删除本资源。</div>'
        : '<div class="info-box">删除后不可恢复（仅 draft 可删；删除会递增 revision）。</div>')
      + '</div>'
      + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-close2>关闭</button>'
      + (deps.length ? '' : '<button class="btn btn-danger" data-ok>删除</button>') + '</div>'
    );
    d.on('[data-ok]', 'click', function () { saveResource('DELETE', path, undefined); d.close(); });
    d.on('[data-close]', 'click', function () { d.close(); });
    d.on('[data-close2]', 'click', function () { d.close(); });
  }

  /* 画布端口拖拽建边：打开受控表单（关系类型只能从目录选择） */
  function requestCreateEdge(fromKey, toKey) {
    addEdge(fromKey, toKey);
  }

  /* ═══════════════ 定位（校验 → 画布/面板）══════════════ */
  function onLocate(e) {
    var loc = (e.detail && e.detail.issue && e.detail.issue.location) || {};
    if (loc.node_key && (loc.resource_type === 'node' || loc.resource_type === 'evidence')) {
      S.canvas.select({ type: 'node', key: loc.node_key });
      S.canvas.centerOn({ type: 'node', key: loc.node_key });
      if (loc.resource_type === 'evidence' && loc.requirement_key) {
        selectResource({ type: 'evidence', nodeKey: loc.node_key, key: loc.requirement_key });
      } else {
        renderInspector({ type: 'node', key: loc.node_key });
        renderStructActive({ type: 'node', key: loc.node_key });
      }
    } else if (loc.edge_key) {
      S.canvas.select({ type: 'edge', key: loc.edge_key });
      S.canvas.centerOn({ type: 'edge', key: loc.edge_key });
      renderInspector({ type: 'edge', key: loc.edge_key });
      renderStructActive({ type: 'edge', key: loc.edge_key });
    } else if (loc.rule_key) {
      renderInspector({ type: 'rule', key: loc.rule_key });
      renderStructActive({ type: 'rule', key: loc.rule_key });
    } else {
      common.toast('该问题定位到版本/目标级别，请在右侧查看', 'warn');
    }
  }

  /* ═══════════════ 事件绑定 ═══════════════ */
  function bindEvents() {
    $('cb-back').addEventListener('click', function () { location.href = common.withCatalogParam('ecmc-models.html'); });
    $('cb-version').addEventListener('change', function () { switchVersion(this.value); });

    // 左/右面板折叠
    $('cb-toggle-left').addEventListener('click', function () { document.body.classList.toggle('ecmc-editor-body-collapsed-left'); $('ecmc-editor-body').classList.toggle('collapsed-left'); });
    $('cb-toggle-right').addEventListener('click', function () { $('ecmc-editor-body').classList.toggle('collapsed-right'); });

    // 结构面板 Tab
    Array.prototype.forEach.call(document.querySelectorAll('.ecmc-struct-tab'), function (tab) {
      tab.addEventListener('click', function () {
        Array.prototype.forEach.call(document.querySelectorAll('.ecmc-struct-tab'), function (t) { t.classList.remove('active'); });
        tab.classList.add('active');
        var mode = tab.dataset.mode;
        $('struct-outline').style.display = mode === 'outline' ? '' : 'none';
        $('struct-components').style.display = mode === 'components' ? '' : 'none';
      });
    });
    $('struct-search').addEventListener('input', renderStruct);

    // 组件 Tab 动作
    $('add-node').addEventListener('click', addNode);
    $('add-edge').addEventListener('click', addEdge);
    $('add-rule').addEventListener('click', addRule);
    $('add-evidence').addEventListener('click', function () {
      var nodes = S.version.nodes || [];
      if (!nodes.length) { common.toast('请先添加节点', 'warn'); return; }
      var nodeKey = nodes[0].node_key;
      var d = common.dialog(
        '<div class="ecmc-dialog-head"><h3>添加证据需求</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
        + '<div class="ecmc-dialog-body"><div class="ecmc-field"><label>所属节点</label><select id="ev-node">'
        + nodes.map(function (n) { return '<option value="' + esc(n.node_key) + '">' + esc(n.business_name || n.node_key) + '</option>'; }).join('')
        + '</select></div></div>'
        + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button><button class="btn" data-ok>创建</button></div>'
      );
      d.on('[data-ok]', 'click', function () { addEvidence(d.el.querySelector('#ev-node').value); d.close(); });
      d.on('[data-cancel]', 'click', function () { d.close(); });
      d.on('[data-close]', 'click', function () { d.close(); });
    });

    // 校验抽屉
    $('validation-bar').addEventListener('click', function () { $('validation-drawer').classList.toggle('open'); });

    // 画布工具
    $('canvas-zoom-in').addEventListener('click', function () { S.canvas.zoomBy(1.15); });
    $('canvas-zoom-out').addEventListener('click', function () { S.canvas.zoomBy(0.87); });
    $('canvas-fit').addEventListener('click', function () { S.canvas.fit(); });
    $('canvas-layout').addEventListener('click', function () {
      S.canvas.positions = layoutPositions(S.version.nodes || [], S.version.edges || []);
      S.canvas.render(S.version, S.validation, { nodes: S.canvas.positions, zoom: S.canvas.zoom, pan: S.canvas.pan });
      saveView();
    });

    // 定位事件
    document.addEventListener('ecmc:locate', onLocate);

    // Ctrl/Cmd+S 保存当前资源（不得绕过表单校验 → 仅当存在可保存表单时触发应用）
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        var saveBtn = document.querySelector('.ecmc-inspector-actions .btn[data-save]') || document.querySelector('#n-save, #e-save, #ev-save, #r-save');
        if (saveBtn) saveBtn.click();
        else common.toast('当前没有可保存的资源', 'warn');
      }
    });

    // 响应式：<1024 只读查看提示；1280 以下自动折叠左侧结构面板
    var applyResponsive = function () {
      var body = $('ecmc-editor-body');
      var w = window.innerWidth;
      if (w < 1024) {
        body.classList.add('collapsed-left');
        body.classList.add('collapsed-right');
      } else if (w < 1280) {
        body.classList.add('collapsed-left');
        body.classList.remove('collapsed-right');
      } else {
        body.classList.remove('collapsed-left');
        body.classList.remove('collapsed-right');
      }
    };
    applyResponsive();
    window.addEventListener('resize', applyResponsive);
  }

  /* ═══════════════ boot ═══════════════ */
  function boot() {
    bindEvents();
    // 目录选择器「申请新增目录项」→ 抽屉内创建申请
    ECMC.catalog.setRequestHandler(function (kind, domain) {
      ECMC.governance.catalogRequestDrawer(document.body, { prefill: { kind: kind, domain: domain } });
    });
    load();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
