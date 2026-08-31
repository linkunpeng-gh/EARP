/* ECMC N01B — 审核发布页（ecmc-reviews.js）
 * 设计: FE-ECMC-2026-0830 §4.1 审核发布（待审核/发布记录/驳回记录）、§5.3 只读审核页
 * 数据源：hydration（模型详情含 versions）+ 治理状态。当前 API 无审核分配信息，
 * 「待审核」展示全部 in_review 版本；驳回记录需要审核历史 API
 * （N01A 未暴露 causal_model_reviews 读接口）——按 §21 开放项诚实展示为空，不伪造数据。
 */
(function () {
  'use strict';
  var api = window.ECMC.api;
  var common = window.ECMC.common;
  var esc = common.esc;

  var state = { filter: 'mine', rows: [] };

  function rowHtml(item) {
    var actions = '<button class="row-action" data-act="open">' + (state.filter === 'mine' ? '审核' : '查看') + '</button>';
    if (item.version.status === 'in_review') {
      actions += '<button class="row-action" data-act="approve">通过并发布</button>';
    }
    if (state.filter === 'mine' && item.version.status === 'in_review') {
      actions += '<button class="row-action" data-act="reject">驳回</button>';
    }
    return '<tr data-model="' + esc(item.model.model_id) + '" data-version="' + esc(item.version.model_version_id) + '">'
      + '<td><div class="cell-primary">' + esc(item.model.name) + '</div><div class="cell-id">' + esc(item.model.model_id) + '</div></td>'
      + '<td><span class="cell-mono">v' + esc(item.version.version) + '</span> <div class="cell-id">' + esc(item.version.model_version_id) + '</div></td>'
      + '<td>' + common.governanceBadge(item.version.status) + '</td>'
      + '<td>' + (item.active ? '<span class="ecmc-badge active">ACTIVE</span>' : '<span class="cell-id">未激活</span>') + '</td>'
      + '<td>' + esc(common.fmtTime(item.version.updated_at || item.model.updated_at)) + '</td>'
      + '<td class="cell-actions">' + actions + '</td>'
      + '</tr>';
  }

  function render() {
    var body = document.getElementById('ecmc-review-rows');
    var empty = document.getElementById('ecmc-review-empty');
    var emptyText = document.getElementById('ecmc-review-empty-text');
    var rows = state.rows.filter(function (r) { return r.filter === state.filter; });
    if (!rows.length) {
      body.innerHTML = '';
      empty.style.display = 'block';
      if (state.filter === 'rejected') emptyText.textContent = '驳回记录需要审核历史 API（N01A 未暴露 causal_model_reviews 读接口）；当前无数据源，不伪造。';
      else if (state.filter === 'published') emptyText.textContent = '暂无发布记录（版本进入 published 后出现在这里）。';
      else emptyText.textContent = '暂无待审核版本（in_review）。当前 API 无审核分配信息，展示全部 in_review 版本（FE-ECMC-2026-0830 §11）。';
      return;
    }
    empty.style.display = 'none';
    body.innerHTML = rows.map(rowHtml).join('');
    Array.prototype.forEach.call(body.querySelectorAll('tr[data-model]'), function (tr) {
      tr.addEventListener('click', function (e) {
        var act = e.target.closest('[data-act]');
        var modelId = tr.dataset.model, versionId = tr.dataset.version;
        if (act) { e.stopPropagation(); handleAction(act.dataset.act, modelId, versionId); return; }
        location.href = common.editorUrl(modelId, versionId);
      });
    });
  }

  function handleAction(act, modelId, versionId) {
    if (act === 'open') {
      location.href = common.editorUrl(modelId, versionId);
      return;
    }
    // 通过并发布 / 驳回：进入编辑器（只读审核视图，操作在命令栏）
    if (act === 'approve' || act === 'reject') {
      location.href = common.editorUrl(modelId, versionId);
    }
  }

  async function load() {
    try {
      var res = await api.get('/causal-models');
      var hydrated = await common.hydrateModels(res.body || []);
      state.rows = [];
      hydrated.forEach(function (h) {
        var m = h.model;
        (h.versions || []).forEach(function (v) {
          var filters = [];
          if (v.status === 'in_review') filters.push('mine');
          if (v.status === 'published') filters.push('published');
          filters.forEach(function (f) {
            state.rows.push({ filter: f, model: m, version: v, active: (m.active_pointer || {}).model_version_id === v.model_version_id });
          });
        });
      });
      render();
    } catch (e) {
      common.errorBar(document.getElementById('ecmc-errorbar'), e);
    }
  }

  function boot() {
    var q = new URLSearchParams(location.search);
    state.filter = q.get('filter') === 'published' ? 'published' : (q.get('filter') === 'rejected' ? 'rejected' : 'mine');
    Array.prototype.forEach.call(document.querySelectorAll('.ecmc-tab[data-filter]'), function (tab) {
      if (tab.dataset.filter === state.filter) tab.classList.add('active');
      tab.addEventListener('click', function () {
        location.href = common.withCatalogParam('ecmc-reviews.html?filter=' + tab.dataset.filter + '&sub=ecmc-reviews-' + (tab.dataset.filter === 'mine' ? 'mine' : tab.dataset.filter));
      });
    });
    load();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
