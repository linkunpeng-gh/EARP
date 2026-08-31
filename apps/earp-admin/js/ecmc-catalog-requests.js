/* ECMC N01B — 目录扩展申请页（ecmc-catalog-requests.js）
 * 设计: FE-ECMC-2026-0830 §9.2 缺项流程、§11 审核发布、§6 状态机
 * 命令：submit（draft）· approve/reject（submitted，reject 必须 reason）· cancel（draft/submitted，仅申请人）
 *      · retry-fulfillment（fulfillment_failed）
 * 批准只把申请置为 approved_pending_fulfillment；权威目录服务履约成功后才 fulfilled，
 * 此前目录查询不得返回它、模型不得引用它。
 */
(function () {
  'use strict';
  var api = window.ECMC.api;
  var common = window.ECMC.common;
  var esc = common.esc;

  var state = { requests: [], q: '', status: '' };

  function cardHtml(r) {
    var def = r.proposed_definition || {};
    var actions = '';
    var id = r.request_id;
    if (r.status === 'draft') {
      actions = '<button class="btn-sm" data-act="submit" data-id="' + esc(id) + '">提交申请</button>'
        + '<button class="btn-sm secondary" data-act="cancel" data-id="' + esc(id) + '">取消</button>';
    } else if (r.status === 'submitted') {
      actions = '<button class="btn-sm btn-approve" data-act="approve" data-id="' + esc(id) + '">批准</button>'
        + '<button class="btn-sm secondary" data-act="reject" data-id="' + esc(id) + '">驳回</button>'
        + '<button class="btn-sm secondary" data-act="cancel" data-id="' + esc(id) + '">取消</button>';
    } else if (r.status === 'fulfillment_failed') {
      actions = '<button class="btn-sm" data-act="retry" data-id="' + esc(id) + '">重试履约</button>';
    }
    return '<div class="ecmc-request-card" data-id="' + esc(id) + '">'
      + '<div class="rc-top">' + common.requestStatusBadge(r.status)
      + '<span class="rc-title">' + esc(def.display_name || r.request_type) + '</span>'
      + '<span class="ecmc-type-badge causal" style="background:var(--bg-surface);color:var(--text-tertiary)">' + esc(r.request_type) + '</span></div>'
      + '<div class="rc-desc">' + esc(def.semantic_definition || '') + '</div>'
      + '<div class="rc-meta">'
      + '<span>数据域：' + esc((r.target_data_domain_ref && r.target_data_domain_ref.stable_id) || '—') + '</span>'
      + '<span>理由：' + esc(r.rationale || '—') + '</span>'
      + (r.resolved_ref ? '<span>resolved：' + esc(r.resolved_ref.stable_id + ' · ' + r.resolved_ref.version) + '</span>' : '')
      + '<span>revision ' + esc(r.revision) + '</span>'
      + '<span class="cell-id">' + esc(id) + '</span></div>'
      + (r.fulfillment_error ? '<div class="rc-error">' + esc(JSON.stringify(r.fulfillment_error)) + '</div>' : '')
      + (actions ? '<div class="rc-actions">' + actions + '</div>' : '')
      + '</div>';
  }

  function filtered() {
    return state.requests.filter(function (r) {
      var def = r.proposed_definition || {};
      var q = state.q.toLowerCase();
      if (state.status && r.status !== state.status) return false;
      if (q && (def.display_name || '').toLowerCase().indexOf(q) === -1 && (r.request_type || '').toLowerCase().indexOf(q) === -1 && (r.request_id || '').toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
  }

  function render() {
    var list = document.getElementById('ecmc-request-list');
    var empty = document.getElementById('ecmc-req-empty');
    var rows = filtered();
    document.getElementById('ecmc-req-count').textContent = '(' + rows.length + ')';
    if (!rows.length) { list.innerHTML = ''; empty.style.display = 'block'; return; }
    empty.style.display = 'none';
    list.innerHTML = rows.map(cardHtml).join('');
    Array.prototype.forEach.call(list.querySelectorAll('[data-act]'), function (btn) {
      btn.addEventListener('click', function () { command(btn.dataset.act, btn.dataset.id); });
    });
  }

  async function command(act, id) {
    try {
      var url = '/catalog-change-requests/' + encodeURIComponent(id);
      if (act === 'submit') {
        var ok = await common.confirmDialog('提交申请', '提交后进入 submitted，将由目录管理员审核。', '提交');
        if (!ok) return;
        await api.post(url + '/submit', null, { idempotencyKey: api.idempotencyKey() });
      } else if (act === 'approve') {
        var ok2 = await common.confirmDialog('批准申请', '批准只把申请置为 approved_pending_fulfillment，由权威目录服务履约；履约完成前模型不可引用。', '批准', { approve: true });
        if (!ok2) return;
        await api.post(url + '/approve', null, { idempotencyKey: api.idempotencyKey() });
      } else if (act === 'reject') {
        var reason = await promptRejectReason();
        if (reason === null) return;
        await api.post(url + '/reject', { reason: reason }, { idempotencyKey: api.idempotencyKey() });
      } else if (act === 'cancel') {
        var ok3 = await common.confirmDialog('取消申请', '仅申请人可取消自己的 draft/submitted 申请。', '取消', { danger: true });
        if (!ok3) return;
        await api.post(url + '/cancel', null, { idempotencyKey: api.idempotencyKey() });
      } else if (act === 'retry') {
        await api.post(url + '/retry-fulfillment', null, { idempotencyKey: api.idempotencyKey() });
      }
      common.toast('操作成功', 'success');
      await load();
    } catch (e) {
      common.errorBar(document.getElementById('ecmc-errorbar'), e);
    }
  }

  function promptRejectReason() {
    return new Promise(function (resolve) {
      var d = common.dialog(
        '<div class="ecmc-dialog-head"><h3>驳回申请</h3><button class="ecmc-dialog-close" data-close>×</button></div>'
        + '<div class="ecmc-dialog-body"><div class="ecmc-field"><label>驳回原因（必填）</label>'
        + '<textarea id="req-reason" rows="3"></textarea><div class="field-error" id="req-reason-err" style="display:none;color:var(--red);font-size:0.74rem">请填写驳回原因。</div></div></div>'
        + '<div class="ecmc-dialog-foot"><button class="btn secondary" data-cancel>取消</button><button class="btn btn-danger" data-ok>驳回</button></div>'
      );
      d.on('[data-ok]', 'click', function () {
        var reason = d.el.querySelector('#req-reason').value.trim();
        if (!reason) { d.el.querySelector('#req-reason-err').style.display = 'block'; return; }
        d.close();
        resolve(reason);
      });
      d.on('[data-cancel]', 'click', function () { d.close(); resolve(null); });
      d.on('[data-close]', 'click', function () { d.close(); resolve(null); });
    });
  }

  async function load() {
    try {
      var res = await api.get('/catalog-change-requests');
      state.requests = res.body || [];
      render();
    } catch (e) {
      common.errorBar(document.getElementById('ecmc-errorbar'), e);
    }
  }

  function boot() {
    var q = new URLSearchParams(location.search);
    var kindParam = q.get('kind') || '';
    // test-only 目录适配器：仅显式 ?catalog=fake 开启（§9.3 / §21）
    if (q.get('catalog') === 'fake') ECMC.catalog.enableFake();
    document.getElementById('ecmc-req-search').addEventListener('input', function (e) { state.q = e.target.value; render(); });
    document.getElementById('ecmc-req-status').addEventListener('change', function (e) { state.status = e.target.value; render(); });
    document.getElementById('ecmc-new-request').addEventListener('click', function () {
      ECMC.governance.catalogRequestDrawer(document.body, { prefill: { kind: kindParam || undefined }, onCreated: load });
    });
    load();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
