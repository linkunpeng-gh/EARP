/* Catalog Phase 1 pages: explicit empty/readiness states until source APIs are wired. */
(function () {
  'use strict';
  var common = window.ECMC && window.ECMC.common;
  var page = document.body.dataset.catalogPage;
  var labels = {
    admin: 'Catalog browse / ref / Pack / Manifest list APIs',
    profiles: 'Catalog Profile CRUD API',
    metrics: 'Metrics authoritative-source API',
    basics: 'Basic-config authoritative-source API',
    bindings: 'Binding-template authoritative-source API'
  };
  function esc(value) {
    return common && common.esc ? common.esc(value) : String(value).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }
  function boot() {
    var name = labels[page] || 'Catalog API';
    var bar = document.getElementById('catalog-readiness');
    if (bar) bar.innerHTML = '<strong>当前状态：readiness HOLD</strong> · ' + esc(name) + ' 尚未接入真实源系统或列表 API；页面不展示编造数据。';
    document.querySelectorAll('[data-catalog-disabled]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (common && common.toast) common.toast('依赖的 Catalog API 尚未就绪', 'warning');
      });
    });
    var form = document.getElementById('catalog-register-form');
    if (form) form.addEventListener('submit', registerRef);
    var packForm = document.getElementById('catalog-pack-create-form');
    if (packForm) packForm.addEventListener('submit', createPackDraft);
    var entryForm = document.getElementById('catalog-pack-entry-form');
    if (entryForm) entryForm.addEventListener('submit', addPackEntry);
    var previewForm = document.getElementById('catalog-manifest-preview-form');
    if (previewForm) previewForm.addEventListener('submit', previewManifest);
    var activateForm = document.getElementById('catalog-manifest-activate-form');
    if (activateForm) activateForm.addEventListener('submit', activateManifest);
    var profileForm = document.getElementById('catalog-profile-create-form');
    if (profileForm) profileForm.addEventListener('submit', createProfile);
    document.querySelectorAll('[data-catalog-tab]').forEach(function (tab) {
      tab.addEventListener('click', function () {
        document.querySelectorAll('[data-catalog-tab]').forEach(function (item) { item.classList.remove('active'); });
        document.querySelectorAll('[data-catalog-panel]').forEach(function (panel) { panel.hidden = true; });
        tab.classList.add('active');
        var panel = document.querySelector('[data-catalog-panel="' + tab.dataset.catalogTab + '"]');
        if (panel) panel.hidden = false;
      });
    });
    if (page === 'admin' || page === 'profiles' || page === 'metrics') loadData();
  }
  async function loadData() {
    if (!window.ECMC || !ECMC.catalogApi) return;
    try {
      if (page === 'admin') {
        var results = await Promise.all([
          ECMC.catalogApi.get('/refs'), ECMC.catalogApi.get('/packs'), ECMC.catalogApi.get('/manifests'),
          ECMC.catalogApi.get('/approvals'), ECMC.api.get('/catalog-change-requests')
        ]);
        renderAdmin(results);
      } else if (page === 'profiles') {
        var profiles = await ECMC.catalogApi.get('/profiles');
        renderProfiles(profiles.body && profiles.body.items || []);
      } else if (page === 'metrics') {
        var metrics = await ECMC.catalogApi.get('/metrics');
        renderMetrics(metrics.body || {});
      }
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>列表加载失败：' + esc(error.message || 'API unavailable') + '</span>';
    }
  }
  async function registerRef(event) {
    event.preventDefault();
    var form = event.currentTarget;
    try {
      await ECMC.catalogApi.post('/refs/register', {
        source_system: form.elements.source_system.value.trim(),
        kind: form.elements.kind.value,
        stable_id: form.elements.stable_id.value.trim(),
        version: form.elements.version.value.trim()
      }, { idempotencyKey: ECMC.catalogApi.idempotencyKey() });
      if (common && common.toast) common.toast('引用注册成功', 'success');
      form.reset();
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>引用注册失败：' + esc(error.message || 'request failed') + '</span>';
    }
  }
  async function createPackDraft(event) {
    event.preventDefault();
    var form = event.currentTarget;
    try {
      await ECMC.catalogApi.post('/packs', {
        pack_id: form.elements.pack_id.value.trim(),
        layer: form.elements.layer.value,
        name: form.elements.name.value.trim(),
        owner_role: form.elements.owner_role.value.trim(),
        version: form.elements.version.value.trim()
      }, { idempotencyKey: ECMC.catalogApi.idempotencyKey() });
      if (common && common.toast) common.toast('Pack 草稿创建成功', 'success');
      form.reset();
      form.elements.version.value = '1.0.0';
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>Pack 草稿创建失败：' + esc(error.message || 'request failed') + '</span>';
    }
  }
  async function addPackEntry(event) {
    event.preventDefault();
    var form = event.currentTarget;
    var pack = JSON.parse(decodeURIComponent(form.elements.pack.value));
    var ref = JSON.parse(decodeURIComponent(form.elements.ref.value));
    try {
      await ECMC.catalogApi.post('/packs/entries', {
        pack_id: pack[0],
        pack_version: pack[1],
        kind: ref[0],
        stable_id: ref[1],
        ref_version: ref[2]
      }, { idempotencyKey: ECMC.catalogApi.idempotencyKey() });
      if (common && common.toast) common.toast('引用已加入 Pack 草稿', 'success');
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>加入 Pack 失败：' + esc(error.message || 'request failed') + '</span>';
    }
  }
  function renderPackSelectors(packs, refs) {
    var packSelect = document.querySelector('#catalog-pack-entry-form select[name="pack"]');
    var refSelect = document.querySelector('#catalog-pack-entry-form select[name="ref"]');
    if (packSelect) {
      var drafts = packs.filter(function (item) { return item.status === 'draft'; });
      packSelect.innerHTML = drafts.length ? drafts.map(function (item) {
        var value = esc(encodeURIComponent(JSON.stringify([item.pack_id, item.version])));
        return '<option value="' + value + '">' + esc(item.pack_id) + '@' + esc(item.version) + '</option>';
      }).join('') : '<option value="">暂无 Pack 草稿</option>';
    }
    if (refSelect) {
      refSelect.innerHTML = refs.length ? refs.filter(function (item) { return item.status !== 'inactive'; }).map(function (item) {
        var value = esc(encodeURIComponent(JSON.stringify([item.kind, item.stable_id, item.version])));
        return '<option value="' + value + '">' + esc(item.kind) + ' · ' + esc(item.stable_id) + '@' + esc(item.version) + '</option>';
      }).join('') : '<option value="">暂无已注册引用</option>';
    }
  }
  function renderAdmin(results) {
    var refs = results[0].body && results[0].body.items || [];
    var packs = results[1].body && results[1].body.items || [];
    var manifests = results[2].body && results[2].body.items || [];
    var approvals = results[3].body && results[3].body.items || [];
    var requests = results[4].body || [];
    renderPackSelectors(packs, refs);
    var summary = document.getElementById('catalog-summary');
    if (summary) summary.textContent = '引用 ' + refs.length + ' · Pack ' + packs.length + ' · Manifest ' + manifests.length + ' · 变更单 ' + requests.length;
    var list = document.getElementById('catalog-browse-list');
    if (list && refs.length) list.innerHTML = refs.map(function (item) {
      return '<div class="ecmc-request-card"><strong>' + esc(item.stable_id) + '</strong> · ' + esc(item.kind)
        + ' · v' + esc(item.version) + ' · ' + esc(item.status) + ' · hash ' + esc(String(item.content_hash).slice(0, 12)) + '…'
        + ' <button type="button" class="btn-sm secondary" data-ref-refresh data-source-system="' + esc(item.source_system)
        + '" data-kind="' + esc(item.kind) + '" data-stable-id="' + esc(item.stable_id)
        + '" data-version="' + esc(item.version) + '">刷新状态</button>'
        + (item.status !== 'inactive' ? ' <button type="button" class="btn-sm secondary" data-ref-revoke data-source-system="' + esc(item.source_system)
          + '" data-kind="' + esc(item.kind) + '" data-stable-id="' + esc(item.stable_id)
          + '" data-version="' + esc(item.version) + '">撤销引用</button>' : '') + '</div>';
    }).join('');
    var empty = document.getElementById('catalog-empty');
    if (empty) empty.style.display = refs.length ? 'none' : 'block';
    renderCollection('catalog-packs-list', 'catalog-packs-empty', packs, function (item) {
      return '<div class="ecmc-request-card"><strong>' + esc(item.pack_id) + '@' + esc(item.version) + '</strong> · '
        + esc(item.layer) + ' · ' + esc(item.status) + ' · entries ' + esc(item.entry_count)
        + (item.status === 'draft' ? ' <button type="button" class="btn-sm secondary" data-pack-publish="'
          + esc(item.pack_id) + '" data-pack-version="' + esc(item.version) + '">提交发布申请</button>' : '') + '</div>';
    });
    document.querySelectorAll('[data-pack-publish]').forEach(function (button) {
      button.addEventListener('click', requestPackPublish);
    });
    document.querySelectorAll('[data-ref-refresh]').forEach(function (button) {
      button.addEventListener('click', refreshRef);
    });
    document.querySelectorAll('[data-ref-revoke]').forEach(function (button) {
      button.addEventListener('click', revokeRef);
    });
    renderCollection('catalog-manifests-list', 'catalog-manifests-empty', manifests, function (item) {
      return '<div class="ecmc-request-card"><strong>' + esc(item.manifest_id) + '</strong> · revision '
        + esc(item.manifest_revision) + ' · ' + esc(item.status) + (item.is_active ? ' · active' : '') + '</div>';
    });
    var approvalItems = requests.length ? requests : approvals;
    renderCollection('catalog-approvals-list', 'catalog-approvals-empty', approvalItems, function (item) {
      if (item.request_type) {
        var action = item.status === 'draft' ? 'submit' : item.status === 'submitted' ? 'approve'
          : item.request_type === 'pack_publish' && item.status === 'approved_pending_fulfillment'
            && item.fulfillment_attempt_id ? 'fulfill' : '';
        return '<div class="ecmc-request-card"><strong>' + esc(item.request_id) + '</strong> · '
          + esc(item.request_type) + ' · ' + esc(item.status)
          + (item.resource_id ? ' · ' + esc(item.resource_id) : '')
          + (action ? ' <button type="button" class="btn-sm secondary" data-catalog-request-action="'
            + action + '" data-catalog-request-id="' + esc(item.request_id) + '">'
            + (action === 'submit' ? '提交审批' : action === 'approve' ? '批准' : '执行发布') + '</button>' : '') + '</div>';
      }
      return '<div class="ecmc-request-card"><strong>' + esc(item.request_id) + '</strong> · '
        + esc(item.decision) + ' · approver ' + esc(item.approver_id) + '</div>';
    });
    document.querySelectorAll('[data-catalog-request-action]').forEach(function (button) {
      button.addEventListener('click', transitionCatalogRequest);
    });
  }
  function renderProfiles(items) {
    var summary = document.getElementById('profile-summary');
    if (summary) summary.textContent = items.length ? '已加载 ' + items.length + ' 个 Profile' : '暂无 Profile';
    var list = document.getElementById('profile-list');
    if (list && items.length) list.innerHTML = items.map(function (item) {
      return '<div class="ecmc-request-card"><strong>' + esc(item.profile_id) + '</strong> · '
        + esc(item.data_domain_id) + ' · ' + esc(item.status) + ' · roles ' + esc(item.role_count) + '</div>';
    }).join('');
    var empty = document.getElementById('profile-empty');
    if (empty) empty.style.display = items.length ? 'none' : 'block';
  }
  async function createProfile(event) {
    event.preventDefault();
    var form = event.currentTarget;
    try {
      await ECMC.catalogApi.post('/profiles', {
        profile_id: form.elements.profile_id.value.trim(),
        catalog_profile_id: form.elements.catalog_profile_id.value.trim(),
        industry_scope: form.elements.industry_scope.value.trim(),
        enterprise_scope: form.elements.enterprise_scope.value.trim(),
        data_domain_id: form.elements.data_domain_id.value.trim(),
        roles: JSON.parse(form.elements.roles.value),
        backup_approver: form.elements.backup_approver.value.trim()
      }, { idempotencyKey: ECMC.catalogApi.idempotencyKey() });
      if (common && common.toast) common.toast('Profile 草稿已创建', 'success');
      form.reset();
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>Profile 创建失败：' + esc(error.message || '请检查 roles JSON') + '</span>';
    }
  }
  function renderMetrics(metrics) {
    var summary = document.getElementById('catalog-metrics-summary');
    if (summary) summary.textContent = 'Refs ' + JSON.stringify(metrics.refs_by_status || {})
      + ' · Packs ' + JSON.stringify(metrics.packs_by_status || {})
      + ' · 审批积压 ' + esc(metrics.approval_backlog || 0)
      + ' · Hash 漂移 ' + esc(metrics.hash_drift_count || 0);
    var runs = document.getElementById('catalog-sync-runs');
    if (runs) runs.textContent = JSON.stringify(metrics.recent_sync_runs || [], null, 2);
    var runtime = document.getElementById('catalog-runtime-metrics');
    if (runtime) runtime.textContent = JSON.stringify(metrics.runtime || {}, null, 2);
  }
  async function refreshRef(event) {
    var button = event.currentTarget;
    try {
      await ECMC.catalogApi.post('/refs/refresh', {
        source_system: button.dataset.sourceSystem,
        kind: button.dataset.kind,
        stable_id: button.dataset.stableId,
        version: button.dataset.version
      });
      if (common && common.toast) common.toast('已从权威源刷新引用状态', 'success');
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>引用刷新失败：' + esc(error.message || 'request failed') + '</span>';
    }
  }
  async function revokeRef(event) {
    var button = event.currentTarget;
    var reason = window.prompt('请输入引用撤销原因');
    if (!reason || !reason.trim()) return;
    try {
      await ECMC.catalogApi.post('/refs/revoke', {
        source_system: button.dataset.sourceSystem,
        kind: button.dataset.kind,
        stable_id: button.dataset.stableId,
        version: button.dataset.version,
        reason: reason.trim()
      }, { idempotencyKey: ECMC.catalogApi.idempotencyKey() });
      if (common && common.toast) common.toast('引用已撤销', 'success');
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>引用撤销失败：' + esc(error.message || 'request failed') + '</span>';
    }
  }
  async function requestPackPublish(event) {
    var button = event.currentTarget;
    var rationale = window.prompt('请输入 Pack 发布原因');
    if (!rationale || !rationale.trim()) return;
    try {
      await ECMC.catalogApi.post('/packs/publish-requests', {
        pack_id: button.dataset.packPublish,
        version: button.dataset.packVersion,
        rationale: rationale.trim()
      }, { idempotencyKey: ECMC.catalogApi.idempotencyKey() });
      if (common && common.toast) common.toast('发布申请已提交，等待 Pack owner 审批', 'success');
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>提交 Pack 发布申请失败：' + esc(error.message || 'request failed') + '</span>';
    }
  }
  function manifestPackSelections(form) {
    return form.elements.packs.value.split(',').map(function (value) {
      var parts = value.trim().split('@');
      if (parts.length !== 2 || !parts[0] || !parts[1]) throw new Error('Pack 选择格式应为 pack_id@version');
      return { pack_id: parts[0], version: parts[1] };
    });
  }
  function manifestPayload(form) {
    return {
      profile_id: form.elements.profile_id.value.trim(),
      manifest_id: form.elements.manifest_id.value.trim(),
      manifest_revision: Number(form.elements.manifest_revision.value),
      packs: manifestPackSelections(form)
    };
  }
  async function previewManifest(event) {
    event.preventDefault();
    var form = event.currentTarget;
    try {
      var result = await ECMC.catalogApi.post('/manifests/preview', manifestPayload(form));
      var output = document.getElementById('catalog-manifest-preview');
      if (output) output.textContent = JSON.stringify(result.body, null, 2);
      if (common && common.toast) common.toast('Manifest 预览已生成', 'success');
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>Manifest 预览失败：' + esc(error.message || 'request failed') + '</span>';
    }
  }
  async function activateManifest(event) {
    event.preventDefault();
    var form = event.currentTarget;
    try {
      var payload = manifestPayload(form);
      payload.expected_active_revision = form.elements.expected_active_revision.value ? Number(form.elements.expected_active_revision.value) : null;
      payload.attestation = JSON.parse(form.elements.attestation.value);
      await ECMC.catalogApi.post('/manifests/activate', payload, { idempotencyKey: ECMC.catalogApi.idempotencyKey() });
      if (common && common.toast) common.toast('Manifest 已激活', 'success');
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>Manifest 激活失败：' + esc(error.message || '请检查 attestation JSON') + '</span>';
    }
  }
  async function transitionCatalogRequest(event) {
    var button = event.currentTarget;
    var action = button.dataset.catalogRequestAction;
    var requestId = button.dataset.catalogRequestId;
    try {
      if (action === 'fulfill') {
        var items = (await ECMC.api.get('/catalog-change-requests')).body || [];
        var request = items.find(function (item) { return item.request_id === requestId; });
        if (!request || !request.fulfillment_attempt_id) throw new Error('未找到待履约 attempt');
        await ECMC.catalogApi.post('/packs/publish-requests/' + encodeURIComponent(requestId) + '/fulfill', {
          attempt_id: request.fulfillment_attempt_id
        }, { idempotencyKey: ECMC.catalogApi.idempotencyKey() });
      } else {
        await ECMC.api.post('/catalog-change-requests/' + encodeURIComponent(requestId) + '/' + action, null, {
          idempotencyKey: ECMC.api.idempotencyKey()
        });
      }
      if (common && common.toast) common.toast(action === 'approve' ? '变更单已批准'
        : action === 'fulfill' ? 'Pack 已完成发布' : '变更单已提交审批', 'success');
      await loadData();
    } catch (error) {
      var bar = document.getElementById('catalog-readiness');
      if (bar) bar.innerHTML += '<br><span>变更单操作失败：' + esc(error.message || 'request failed') + '</span>';
    }
  }
  function renderCollection(listId, emptyId, items, formatter) {
    var list = document.getElementById(listId);
    if (list) list.innerHTML = items.map(formatter).join('');
    var empty = document.getElementById(emptyId);
    if (empty) empty.style.display = items.length ? 'none' : 'block';
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
