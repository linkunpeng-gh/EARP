/* 应用详情「API 访问」— 密钥管理（tech-debt #18 Task 5）。
 *
 * 与 Dify API Access 对标：生成（明文仅展示一次 + 复制）/ 吊销 / 列表（name/状态/最后使用）。
 * 仅已发布应用可被密钥调用（后端 404 门禁）；生产密钥管理须知见 arch/guides/earp-fde-user-guide.md。
 * 明文仅由后端返回一次——刷新/重开后不再可得，需吊销重建。
 */
var EARPApiAccess = (function () {
  var MODAL_ID = 'api-access-modal';

  function open(appId) {
    var modal = document.getElementById(MODAL_ID);
    if (!modal) modal = buildModal();
    modal.dataset.appId = appId || '';
    modal.style.display = 'flex';
    loadKeys();
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
      '<div class="modal" style="width:640px;max-width:92vw;">' +
        '<h3 style="margin:0 0 0.25rem;">API 访问</h3>' +
        '<p class="page-subtitle" style="margin:0 0 0.75rem;">对外服务密钥：外部系统用 <code style="background:var(--bg-surface);padding:0.1rem 0.35rem;border-radius:4px;">Bearer app-&lt;key&gt;</code> 调用已发布应用（<code>POST /api/v1/chat-apps/{id}/chat</code>）。仅已发布应用可调用；密钥吊销即时生效。</p>' +
        '<div class="cfg-field">' +
          '<label class="cfg-label">新密钥名称（生产/测试隔离建议：prod-key / dev-key）</label>' +
          '<div style="display:flex;gap:0.5rem;">' +
            '<input type="text" id="api-key-name" placeholder="如 prod-报销助手" style="flex:1;padding:0.35rem 0.6rem;font-size:0.81rem;border:1px solid var(--border-standard);border-radius:var(--radius-md);">' +
            '<button class="primary btn-sm" onclick="EARPApiAccess.create()">生成密钥</button>' +
          '</div>' +
          '<span id="api-key-err" style="font-size:0.75rem;color:#dc2626;"></span>' +
        '</div>' +
        '<div id="api-key-created" style="display:none;margin:0.6rem 0;padding:0.6rem;background:rgba(22,163,74,.08);border:1px solid rgba(22,163,74,.35);border-radius:var(--radius-md);">' +
          '<p style="margin:0 0 0.35rem;font-size:0.78rem;color:#16a34a;font-weight:600;">密钥已生成 — 明文仅显示这一次，关闭后不可恢复，请立即复制保存</p>' +
          '<div style="display:flex;gap:0.5rem;align-items:center;">' +
            '<code id="api-key-plain" style="flex:1;word-break:break-all;font-size:0.8rem;background:var(--bg-surface);padding:0.35rem 0.5rem;border-radius:4px;"></code>' +
            '<button class="btn-sm secondary" onclick="EARPApiAccess.copyPlain()">复制</button>' +
          '</div>' +
        '</div>' +
        '<table style="width:100%;border-collapse:collapse;font-size:0.8rem;">' +
          '<thead><tr style="text-align:left;color:var(--text-tertiary);font-size:0.72rem;">' +
            '<th style="padding:0.35rem 0.25rem;">名称</th><th>状态</th><th>创建时间</th><th>最后使用</th><th></th>' +
          '</tr></thead>' +
          '<tbody id="api-key-rows"><tr><td colspan="5" style="color:var(--text-quaternary);padding:0.75rem 0.25rem;">加载中…</td></tr></tbody>' +
        '</table>' +
        '<div style="display:flex;justify-content:flex-end;margin-top:0.75rem;">' +
          '<button class="btn-sm btn-outline" onclick="EARPApiAccess.close()">关闭</button>' +
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
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  async function loadKeys() {
    var appId = currentAppId();
    if (!appId) return;
    var rows = document.getElementById('api-key-rows');
    var err = document.getElementById('api-key-err');
    if (err) err.textContent = '';
    try {
      var list = await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(appId) + '/api-keys');
      if (!rows) return;
      if (!list.length) {
        rows.innerHTML = '<tr><td colspan="5" style="color:var(--text-quaternary);padding:0.75rem 0.25rem;">暂无密钥 — 生成后即可被外部系统调用（应用需已发布）。</td></tr>';
        return;
      }
      rows.innerHTML = list.map(function (k) {
        var statusTag = k.status === 'active'
          ? '<span class="tag tag-green">有效</span>'
          : '<span class="tag" style="background:var(--bg-surface);color:var(--text-tertiary);">已吊销</span>';
        var revokeBtn = k.status === 'active'
          ? '<button class="btn-sm btn-outline" type="button" style="color:#dc2626;border-color:rgba(220,38,38,.4);" data-key-action="revoke" data-key-id="' + esc(k.api_key_id) + '">吊销</button>'
          : '';
        return '<tr>' +
          '<td style="padding:0.35rem 0.25rem;">' + esc(k.name) + '</td>' +
          '<td>' + statusTag + '</td>' +
          '<td style="color:var(--text-secondary);">' + fmt(k.created_at) + '</td>' +
          '<td style="color:var(--text-secondary);">' + fmt(k.last_used_at) + '</td>' +
          '<td style="text-align:right;">' + revokeBtn + '</td>' +
        '</tr>';
      }).join('');
    } catch (e) {
      rows.innerHTML = '<tr><td colspan="5" style="color:#dc2626;padding:0.75rem 0.25rem;">加载失败：' + esc(e.message) + '</td></tr>';
    }
  }

  async function create() {
    var appId = currentAppId();
    var nameInput = document.getElementById('api-key-name');
    var err = document.getElementById('api-key-err');
    var name = (nameInput ? nameInput.value : '').trim();
    if (err) err.textContent = '';
    if (!name) { if (err) err.textContent = '请输入密钥名称'; return; }
    var btn = document.querySelector('#api-access-modal .primary');
    if (btn) { btn.disabled = true; }
    try {
      var created = await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(appId) + '/api-keys', {
        method: 'POST', body: JSON.stringify({ name: name }),
      });
      var box = document.getElementById('api-key-created');
      box.style.display = 'block';
      document.getElementById('api-key-plain').textContent = created.plaintext;
      if (nameInput) nameInput.value = '';
      await loadKeys();
    } catch (e) {
      if (err) err.textContent = '生成失败：' + e.message;
    } finally {
      if (btn) { btn.disabled = false; }
    }
  }

  async function revoke(keyId) {
    if (!confirm('吊销后该密钥立即失效（已发出的调用不受影响，新调用将 401）。确定吊销？')) return;
    var appId = currentAppId();
    try {
      await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(appId) + '/api-keys/' + encodeURIComponent(keyId) + '/revoke', {
        method: 'POST',
      });
      await loadKeys();
    } catch (e) { alert('吊销失败：' + e.message); }
  }

  function copyPlain() {
    var el = document.getElementById('api-key-plain');
    if (!el || !el.textContent) return;
    navigator.clipboard.writeText(el.textContent).then(function () {
      var b = document.querySelector('#api-access-modal .secondary');
      if (b) { var old = b.textContent; b.textContent = '已复制'; setTimeout(function () { b.textContent = old; }, 1200); }
    }).catch(function () { /* clipboard 不可用（file:// 等）——用户可手动选中复制 */ });
  }

  // 行内动作委托（安全修复）：api_key_id 不再裸拼进 inline onclick 的 JS 字符串
  // 字面量（esc 的 HTML 实体会被属性解析还原，构成双上下文注入面）。
  document.addEventListener('click', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('[data-key-action]') : null;
    if (el && el.getAttribute('data-key-action') === 'revoke') revoke(el.getAttribute('data-key-id') || '');
  });

  return { open: open, close: close, create: create, revoke: revoke, copyPlain: copyPlain, loadKeys: loadKeys };
})();
