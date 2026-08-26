/* Chatflow 运行历史（tech-debt #17 Task 4，D6）。
 *
 * 应用维度入口：chatflow 列表页卡片「📜 运行历史」→ 模态列出该应用每次执行
 * （时间/状态/attempts/耗时），选中展开 trace 只读表格（node/status/branch/
 * input/output/error/error_code/latency）。数据来自 GET /chat_apps/{id}/runs。
 * 权限与后端一致（非 admin 按 chat_app 可见性过滤，不可见 → 404 由 fetch 抛错）。
 */
var EARPRunHistory = (function () {
  var MODAL_ID = 'run-history-modal';

  function open(appId, appName) {
    var modal = document.getElementById(MODAL_ID);
    if (!modal) modal = buildModal();
    modal.dataset.appId = appId || '';
    document.getElementById('rh-title').textContent = '运行历史 — ' + (appName || appId || '');
    modal.style.display = 'flex';
    loadRuns();
  }

  function close() {
    var m = document.getElementById(MODAL_ID);
    if (m) m.style.display = 'none';
  }

  function buildModal() {
    var overlay = document.createElement('div');
    overlay.id = MODAL_ID;
    overlay.className = 'modal-overlay';
    overlay.style.display = 'none';
    overlay.onclick = function (ev) { if (ev.target === overlay) close(); };
    overlay.innerHTML =
      '<div class="modal" style="width:720px;max-width:94vw;">' +
        '<h3 id="rh-title" style="margin:0 0 0.25rem;">运行历史</h3>' +
        '<p class="page-subtitle" style="margin:0 0 0.75rem;">每次流程执行的完整轨迹（成功/失败/驳回/超时）——刷新页面不丢，用于回看与排查。</p>' +
        '<div id="rh-body" style="max-height:60vh;overflow-y:auto;">' +
          '<p style="color:var(--text-quaternary);font-size:0.8rem;padding:0.5rem 0;">加载中…</p>' +
        '</div>' +
        '<div style="display:flex;justify-content:flex-end;margin-top:0.75rem;">' +
          '<button class="btn-sm btn-outline" onclick="EARPRunHistory.close()">关闭</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);
    return overlay;
  }

  function currentAppId() {
    var m = document.getElementById(MODAL_ID);
    return m ? m.dataset.appId : '';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmt(dt) {
    if (!dt) return '—';
    var d = new Date(dt);
    if (isNaN(d.getTime())) return String(dt);
    var p = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  function statusTag(s) {
    var map = {
      completed: ['已完成', 'tag-green'], failed: ['失败', ''], rejected: ['已驳回', ''],
      timeout: ['超时', ''], waiting_human: ['等待确认', ''], running: ['执行中', 'tag-accent'],
    };
    var m = map[s] || [s || '未知', ''];
    return '<span class="tag' + (m[1] ? ' ' + m[1] : '') + '" style="' + (m[1] ? '' : 'background:var(--bg-surface);color:var(--text-tertiary);') + '">' + esc(m[0]) + '</span>';
  }

  function fmtJson(v) {
    if (v == null) return '—';
    var s = typeof v === 'string' ? v : JSON.stringify(v);
    return s.length > 120 ? s.slice(0, 120) + '…' : s;
  }

  function traceTable(run) {
    var trace = run.trace;
    if (!trace || !trace.length) {
      return '<p style="color:var(--text-quaternary);font-size:0.78rem;margin:0.4rem 0;">本 run 无轨迹（存量数据或挂起即终态）。</p>';
    }
    return '<div style="margin:0.4rem 0;">' +
      trace.map(function (t) {
        var st = t.status === 'completed' ? '<span class="tag tag-green">ok</span>'
          : t.status === 'failed' ? '<span class="tag" style="background:rgba(220,38,38,.15);color:#dc2626;">err</span>'
          : '<span class="tag" style="background:var(--bg-surface);color:var(--text-tertiary);">' + esc(t.status) + '</span>';
        var branch = t.branch ? '<span style="color:var(--text-tertiary);font-size:0.72rem;margin-left:0.3rem;">→ ' + esc(t.branch) + '</span>' : '';
        var err = t.error ? '<div style="color:#dc2626;font-size:0.72rem;margin-top:2px;">' + esc(t.error) + (t.error_code ? ' [' + esc(t.error_code) + ']' : '') + '</div>' : '';
        return '<div class="run-node" style="font-size:0.72rem;margin:3px 0;padding:0.3rem 0.45rem;background:var(--bg-surface);border-radius:4px;">' +
          st + ' <b>' + esc(t.node_id) + '</b>' + branch +
          '<span style="color:var(--text-tertiary);font-size:0.66rem;margin-left:0.4rem;">' + (t.latency_ms != null ? t.latency_ms + 'ms' : '') + '</span>' + err +
          '<div class="run-json" style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:0.64rem;color:var(--text-secondary);margin:3px 0 0 14px;word-break:break-all;">' +
            '<span class="run-k" style="color:var(--text-tertiary);">in: </span>' + esc(fmtJson(t.input)) +
            '<br><span class="run-k" style="color:var(--text-tertiary);">out: </span>' + esc(fmtJson(t.output)) +
          '</div></div>';
      }).join('') + '</div>';
  }

  async function loadRuns() {
    var appId = currentAppId();
    if (!appId) return;
    var body = document.getElementById('rh-body');
    try {
      var runs = await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(appId) + '/runs');
      if (!runs.length) {
        body.innerHTML = '<p style="color:var(--text-quaternary);font-size:0.8rem;padding:0.5rem 0;">该应用暂无运行记录——跑一次流程（▶ 运行或对话）后这里会留下完整轨迹。</p>';
        return;
      }
      body.innerHTML = runs.map(function (r) {
        var dur = '';
        if (r.finished_at && r.created_at) {
          var ms = new Date(r.finished_at) - new Date(r.created_at);
          if (!isNaN(ms)) dur = '<span style="color:var(--text-tertiary);font-size:0.7rem;">' + Math.round(ms) + 'ms</span>';
        }
        return '<div class="rh-run" style="border:1px solid var(--border-standard);border-radius:var(--radius-md);margin:0.4rem 0;overflow:hidden;">' +
          '<div class="rh-run-head" style="display:flex;align-items:center;gap:0.6rem;padding:0.45rem 0.6rem;cursor:pointer;font-size:0.8rem;" ' +
              'onclick="EARPRunHistory.toggle(\'' + r.execution_id + '\')">' +
            statusTag(r.status) +
            '<span style="color:var(--text-secondary);">' + fmt(r.created_at) + '</span>' +
            '<span style="color:var(--text-tertiary);font-size:0.72rem;">attempts ' + (r.attempts || 1) + '</span>' +
            '<span class="spacer" style="flex:1;"></span>' + dur +
          '</div>' +
          '<div id="rh-trace-' + r.execution_id + '" style="display:none;padding:0.2rem 0.6rem 0.5rem;border-top:1px solid var(--border-standard);">' +
            traceTable(r) + '</div>' +
        '</div>';
      }).join('');
    } catch (e) {
      body.innerHTML = '<p style="color:#dc2626;font-size:0.8rem;padding:0.5rem 0;">加载失败：' + esc(e.message) + '</p>';
    }
  }

  function toggle(execId) {
    var el = document.getElementById('rh-trace-' + execId);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
  }

  return { open: open, close: close, toggle: toggle, loadRuns: loadRuns };
})();
