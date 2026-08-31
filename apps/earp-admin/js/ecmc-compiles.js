/* ECMC N01B — 编译与激活页（ecmc-compiles.js）
 * 设计: FE-ECMC-2026-0830 §4.1 编译与激活、§11.4 编译、§11.5 激活
 * 数据源：hydration（模型详情含 versions）+ 每个已发布 Version 的最新 governance。
 * 注意：N01A governance 只返回每个 Version 最新一条 compile_record，无法提供完整
 *   Attempt 历史 / retry 链；分页 attempts 接口未签署前，本页命名为「最新编译状态」，
 *   不冒充 Attempts 历史（FE-ECMC-2026-0830 §20.1/§21）。
 * running 展示进度，不展示伪 Artifact；failed 允许 retry（retry_of_compile_id 链路）。
 */
(function () {
  'use strict';
  var api = window.ECMC.api;
  var common = window.ECMC.common;
  var esc = common.esc;

  var state = { view: 'attempts', rows: [] };

  function rowHtml(item) {
    var cr = item.governance.compile_record;
    var actions = '';
    if (state.view === 'artifacts' && cr && cr.status === 'success') {
      actions = '<button class="row-action" data-act="artifact">查看 Artifact</button>'
        + '<button class="row-action" data-act="activate">激活</button>';
    }
    if (state.view === 'attempts' && cr && cr.status === 'failed') {
      actions = '<button class="row-action" data-act="retry">重试编译</button>';
    }
    if (state.view === 'attempts' && item.version.status === 'published' && !cr) {
      actions += '<button class="row-action" data-act="compile">发起编译</button>';
    }
    if (state.view === 'active' && item.active) {
      actions = '<button class="row-action" data-act="open">查看模型</button>';
    }
    return '<tr data-model="' + esc(item.model.model_id) + '" data-version="' + esc(item.version.model_version_id) + '">'
      + '<td><div class="cell-primary">' + esc(item.model.name) + '</div><div class="cell-id">' + esc(item.model.model_id) + '</div></td>'
      + '<td><span class="cell-mono">v' + esc(item.version.version) + '</span> <div class="cell-id">' + esc(item.version.model_version_id) + '</div>'
      + (cr && cr.retry_of_compile_id ? '<div class="cell-id">retry_of: ' + esc(cr.retry_of_compile_id) + '</div>' : '') + '</td>'
      + '<td>' + (cr ? common.compileBadge(cr.status) + ' <div class="cell-id">' + esc(cr.compile_record_id) + '</div>' : '<span class="cell-id">未编译</span>') + '</td>'
      + '<td class="cell-mono">' + (cr && cr.compiled_artifact_hash ? esc(common.fmtHash(cr.compiled_artifact_hash)) : '—')
      + (cr && cr.artifact_schema_version ? ' <span class="cell-id">' + esc(cr.artifact_schema_version) + '</span>' : '') + '</td>'
      + '<td>' + common.readinessBadge(item.governance.runtime_readiness) + '</td>'
      + '<td class="cell-actions">' + actions + '</td>'
      + '</tr>';
  }

  function render() {
    var body = document.getElementById('ecmc-compile-rows');
    var empty = document.getElementById('ecmc-compile-empty');
    var emptyText = document.getElementById('ecmc-compile-empty-text');
    var rows = state.rows.filter(function (r) { return r.view === state.view; });
    if (!rows.length) {
      body.innerHTML = '';
      empty.style.display = 'block';
      if (state.view === 'attempts') emptyText.textContent = '暂无编译状态（published 版本编译后出现在这里）。';
      else if (state.view === 'artifacts') emptyText.textContent = '暂无成功 Candidate Artifact。';
      else emptyText.textContent = '暂无 Active Version（激活由显式 CAS 事务完成）。';
      return;
    }
    empty.style.display = 'none';
    body.innerHTML = rows.map(rowHtml).join('');
    Array.prototype.forEach.call(body.querySelectorAll('tr[data-model]'), function (tr) {
      tr.addEventListener('click', function (e) {
        var act = e.target.closest('[data-act]');
        if (act) { e.stopPropagation(); handleAction(act.dataset.act, tr); return; }
        location.href = common.editorUrl(tr.dataset.model, tr.dataset.version);
      });
    });
  }

  async function handleAction(act, tr) {
    var modelId = tr.dataset.model, versionId = tr.dataset.version;
    var item = state.rows.find(function (r) { return r.model.model_id === modelId && r.version.model_version_id === versionId; });
    if (act === 'open') { location.href = common.editorUrl(modelId, versionId); return; }
    if (act === 'artifact' && item && item.governance.compile_record) {
      try {
        var art = await ECMC.governance.fetchArtifact(item.model, item.version, item.governance.compile_record.compile_record_id);
        var d = common.dialog(
          '<div class="ecmc-dialog-head"><h3>Candidate Artifact（只读）</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
          + '<div class="ecmc-dialog-body"><div class="kv"><dt>schema</dt><dd class="mono">' + esc(art.artifact_schema_version) + '</dd>'
          + '<dt>hash</dt><dd class="mono">' + esc(art.compiled_artifact_hash) + '</dd></div>'
          + '<pre style="max-height:340px;overflow:auto;font-size:0.7rem">' + esc(JSON.stringify(art.compiled_artifact, null, 2)) + '</pre></div>'
          + '<div class="ecmc-dialog-foot"><button class="btn" data-close2>关闭</button></div>'
        );
        d.on('[data-close]', 'click', function () { d.close(); });
        d.on('[data-close2]', 'click', function () { d.close(); });
      } catch (e) { common.errorBar(document.getElementById('ecmc-errorbar'), e); }
      return;
    }
    if ((act === 'compile' || act === 'retry') && item) {
      var retryId = act === 'retry' && item.governance.compile_record ? item.governance.compile_record.compile_record_id : null;
      try {
        var res = await ECMC.governance.requestCompile(null, item.model, item.version, retryId);
        var cr = res.compile_record || res;
        common.toast('已请求编译：' + (cr.compile_record_id || '') + (retryId ? '（retry_of ' + retryId + '）' : ''), 'success');
        await load();
      } catch (e) { common.errorBar(document.getElementById('ecmc-errorbar'), e); }
      return;
    }
    if (act === 'activate' && item) {
      var g = item.governance;
      var client = new api.VersionClient(item.model.model_id, item.version.model_version_id, item.version.revision || 0, function () {});
      ECMC.governance.activateConfirm(item.model, item.version, g.compile_record, g, async function (body) {
        try {
          var res = await client.mutate('POST', '/causal-models/' + encodeURIComponent(item.model.model_id) + '/activate', body, {});
          await load();
          return res;
        } catch (e) {
          common.errorBar(document.getElementById('ecmc-errorbar'), e);
          throw e;
        }
      }, async function () {
        // ACTIVE_VERSION_CHANGED：重新读取 governance（含最新 active pointer）
        try {
          var gr = await api.get(ECMC.governance.vUrl(item.model.model_id, item.version.model_version_id) + '/governance');
          item.governance = gr.body;
          return item.governance;
        } catch (_) { return null; }
      });
      return;
    }
  }

  async function load() {
    try {
      var res = await api.get('/causal-models');
      var hydrated = await common.hydrateModels(res.body || []);
      state.rows = [];
      var pending = [];
      hydrated.forEach(function (h) {
        var versions = h.versions.filter(function (v) { return v.status === 'published' || (h.model.active_pointer || {}).model_version_id === v.model_version_id; });
        versions.forEach(function (v) {
          pending.push((async function () {
            var governance = { compile_record: null, runtime_readiness: 'not_activated', active_pointer: h.model.active_pointer };
            try {
              var g = await api.get(ECMC.governance.vUrl(h.model.model_id, v.model_version_id) + '/governance');
              governance = g.body;
            } catch (_) {}
            var active = (h.model.active_pointer || {}).model_version_id === v.model_version_id;
            state.rows.push({ view: 'attempts', model: h.model, version: v, governance: governance, active: active });
            state.rows.push({ view: 'artifacts', model: h.model, version: v, governance: governance, active: active });
            state.rows.push({ view: 'active', model: h.model, version: v, governance: governance, active: active });
          })());
        });
      });
      await Promise.all(pending);
      render();
    } catch (e) {
      common.errorBar(document.getElementById('ecmc-errorbar'), e);
    }
  }

  function boot() {
    var q = new URLSearchParams(location.search);
    state.view = q.get('view') === 'artifacts' ? 'artifacts' : (q.get('view') === 'active' ? 'active' : 'attempts');
    Array.prototype.forEach.call(document.querySelectorAll('.ecmc-tab[data-view]'), function (tab) {
      if (tab.dataset.view === state.view) tab.classList.add('active');
      tab.addEventListener('click', function () {
        var sub = tab.dataset.view === 'attempts' ? 'ecmc-compiles' : (tab.dataset.view === 'artifacts' ? 'ecmc-artifacts' : 'ecmc-active');
        location.href = common.withCatalogParam('ecmc-compiles.html?view=' + tab.dataset.view + '&sub=' + sub);
      });
    });
    load();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
