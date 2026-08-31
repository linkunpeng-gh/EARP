/* ECMC N01B — 概览页（ecmc-overview.js）
 * 设计: FE-ECMC-2026-0830 §6 概览页（进入工作，不承担深度分析）
 * 状态卡片必须可点击进入带筛选条件的列表；工作队列展示最近编辑/待审核/编译失败/待处理申请；
 * 决策/任务模型只显示规划说明，不展示虚构数量。
 */
(function () {
  'use strict';
  var api = window.ECMC.api;
  var common = window.ECMC.common;
  var esc = common.esc;

  function stat(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function card(id, href) {
    var el = document.getElementById(id);
    if (el && href) {
      el.closest('.ecmc-stat-card').style.cursor = 'pointer';
      el.closest('.ecmc-stat-card').addEventListener('click', function () { location.href = href; });
    }
  }

  async function load() {
    try {
      var res = await ECMC.common.hydrateModels((await api.get('/causal-models')).body || []);
      var models = res;
      var drafts = 0, published = 0, active = 0, failed = 0, inReview = 0;
      models.forEach(function (h) {
        if (h.model.active_pointer && h.model.active_pointer.model_version_id) active++;
        var latest = h.latestVersion;
        if (!latest) return;
        if (latest.status === 'draft') drafts++;
        if (latest.status === 'in_review') inReview++;
        if (latest.status === 'published') published++;
      });
      stat('st-total', models.length);
      stat('st-draft', drafts);
      stat('st-review', inReview);
      stat('st-active', active);
      stat('st-compile-failed', '—');

      card('st-total', common.withCatalogParam('ecmc-models.html'));
      card('st-draft', common.withCatalogParam('ecmc-models.html?type=causal'));
      card('st-active', common.withCatalogParam('ecmc-models.html?type=causal'));

      renderQueue(models);
    } catch (e) {
      common.errorBar(document.getElementById('ecmc-errorbar'), e);
      document.getElementById('ecmc-queue').innerHTML = '<div class="ecmc-queue-empty">后端未连接，无法加载工作队列。</div>';
    }
  }

  function queueItem(title, meta, href, badge) {
    return '<div class="ecmc-queue-item" onclick="location.href=\'' + esc(href) + '\'">'
      + '<div class="qi-main"><div class="qi-title">' + title + '</div><div class="qi-meta">' + meta + '</div></div>'
      + (badge || '') + '</div>';
  }

  function renderQueue(models) {
    var box = document.getElementById('ecmc-queue');
    var html = '';
    var recent = models.slice(0, 5);
    html += '<h3 style="margin-top:0.5rem;font-size:0.75rem">最近编辑的模型</h3>';
    if (!recent.length) html += '<div class="ecmc-queue-empty">暂无模型。点击右上角「新建因果模型」创建第一个草稿。</div>';
    recent.forEach(function (h) {
      var m = h.model;
      var latest = h.latestVersion;
      html += queueItem(
        esc(m.name || m.model_id),
        esc((latest ? 'v' + latest.version + ' · ' + (common.GOVERNANCE_LABELS[latest.status] || latest.status) : '') + ' · ' + common.fmtTime((h.latestDetail && h.latestDetail.updated_at) || m.updated_at || m.created_at)),
        common.editorUrl(m.model_id, latest && latest.model_version_id),
        latest ? common.governanceBadge(latest.status) : ''
      );
    });
    var review = models.filter(function (h) { var v = h.latestVersion; return v && v.status === 'in_review'; });
    html += '<h3 style="margin-top:0.5rem;font-size:0.75rem">待审核</h3>';
    if (!review.length) html += '<div class="ecmc-queue-empty">当前没有 in_review 版本待审核。</div>';
    review.forEach(function (h) {
      var latest = h.latestVersion;
      html += queueItem(
        esc(h.model.name || h.model.model_id) + ' · v' + esc(latest.version),
        esc('提交后内容锁定，可查看/驳回/发布'),
        common.editorUrl(h.model.model_id, latest.model_version_id),
        '<span class="ecmc-badge in_review">待审核</span>'
      );
    });
    html += '<h3 style="margin-top:0.5rem;font-size:0.75rem">待处理目录扩展申请</h3>';
    html += '<div class="ecmc-queue-empty"><a href="' + esc(common.withCatalogParam('ecmc-catalog-requests.html')) + '" style="color:var(--accent-text)">前往目录扩展申请 →</a></div>';
    box.innerHTML = html;
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
  else load();
})();
