/* 治理中心 · 应用权限矩阵（角色 × 已发布应用） */
(function () {
  var roles = [];      // 非 admin 角色
  var apps = [];       // 已发布应用
  var cells = {};      // appId -> Set(roleId)（本地编辑态）
  var dirty = {};      // appId -> true

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  async function load() {
    var status = document.getElementById('m-status');
    try {
      var [r, a] = await Promise.all([
        EARP.fetchJSON('/api/roles'),
        EARP.fetchJSON('/chat_apps'),
      ]);
      roles = r.filter(function (x) { return !x.is_admin; });
      apps = a.filter(function (x) { return x.status === 'published'; });
      // 初始化本地格：restricted 应用从后端拉授权角色
      cells = {};
      dirty = {};
      for (var i = 0; i < apps.length; i++) {
        var app = apps[i];
        cells[app.chat_app_id] = new Set();
        if (app.access_mode === 'restricted') {
          try {
            var acc = await EARP.fetchJSON('/api/app_access?chat_app_id=' + encodeURIComponent(app.chat_app_id));
            (acc.roles || []).forEach(function (r2) { cells[app.chat_app_id].add(r2.role_id); });
          } catch (e) { /* 保持空集 */ }
        }
      }
      render();
      status.textContent = '';
    } catch (e) {
      status.textContent = '加载失败: ' + e.message;
    }
  }

  function render() {
    var head = document.getElementById('m-head');
    head.innerHTML = '<tr><th>应用</th>' + roles.map(function (r) { return '<th>' + esc(r.name) + '</th>'; }).join('') + '<th>模式</th></tr>';
    var body = document.getElementById('m-body');
    if (!apps.length) { body.innerHTML = '<tr><td colspan="' + (roles.length + 2) + '" style="color:var(--text-quaternary);">暂无已发布应用</td></tr>'; return; }
    var kw = (document.getElementById('m-q').value || '').trim().toLowerCase();
    var filtered = kw ? apps.filter(function (a) { return (a.name || '').toLowerCase().indexOf(kw) >= 0; }) : apps;
    if (!filtered.length) { body.innerHTML = '<tr><td colspan="' + (roles.length + 2) + '" style="color:var(--text-quaternary);">无匹配应用</td></tr>'; return; }
    body.innerHTML = filtered.map(function (a) {
      var rng = roles.map(function (r, idx) {
        var checked = cells[a.chat_app_id].has(r.role_id) ? ' checked' : '';
        return '<td style="text-align:center;"><input type="checkbox" data-app="' + esc(a.chat_app_id) + '" data-role="' + esc(r.role_id) + '"' + checked + '></td>';
      }).join('');
      var mode = cells[a.chat_app_id].size > 0 ? 'restricted' : 'open';
      return '<tr><td>' + esc(a.name) + '<br><span style="font-size:0.68rem;color:var(--text-quaternary);">' + esc(a.chat_app_id) + '</span></td>'
        + rng + '<td class="mode-cell"><span class="mode-badge ' + mode + '">' + (mode === 'open' ? '开放' : '白名单') + '</span></td></tr>';
    }).join('');
    // 绑定 checkbox 事件（re-render 后重新挂）
    body.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
      cb.onchange = function () {
        var appId = cb.dataset.app, roleId = cb.dataset.role;
        if (cb.checked) cells[appId].add(roleId); else cells[appId].delete(roleId);
        dirty[appId] = true;
        updateModeBadge(appId);
      };
    });
  }

  function updateModeBadge(appId) {
    var rows = document.querySelectorAll('#m-body tr');
    rows.forEach(function (tr) {
      var firstTd = tr.querySelector('td');
      if (!firstTd) return;
      if (tr.querySelector('input[data-app="' + appId + '"]')) {
        var mode = cells[appId].size > 0 ? 'restricted' : 'open';
        var badge = tr.querySelector('.mode-cell .mode-badge');
        if (badge) { badge.className = 'mode-badge ' + mode; badge.textContent = mode === 'open' ? '开放' : '白名单'; }
      }
    });
  }

  async function save() {
    var status = document.getElementById('m-status');
    var appIds = Object.keys(dirty);
    if (!appIds.length) { status.textContent = '无变更'; return; }
    var errors = 0;
    for (var i = 0; i < appIds.length; i++) {
      var appId = appIds[i];
      var mode = cells[appId].size > 0 ? 'restricted' : 'open';
      try {
        await EARP.fetchJSON('/api/app_access/' + encodeURIComponent(appId), {
          method: 'PUT',
          body: JSON.stringify({ mode: mode, roles: Array.from(cells[appId]) }),
        });
      } catch (e) { errors++; status.textContent = '保存失败: ' + e.message; }
    }
    dirty = {};
    if (!errors) status.textContent = '✓ 已保存 ' + appIds.length + ' 个应用的权限';
  }

  document.addEventListener('DOMContentLoaded', function () {
    load();
    var q = document.getElementById('m-q');
    var t;
    q.addEventListener('input', function () { clearTimeout(t); t = setTimeout(render, 250); });
    document.getElementById('m-save').onclick = save;
  });
})();
