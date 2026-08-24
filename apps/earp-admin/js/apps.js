/* 应用中心 · 智能体页（data-page=apps 全量 | my-apps 我的应用收藏）*/
(function () {
  var IS_MINE = (document.body && document.body.getAttribute('data-page') === 'my-apps')
    || new URLSearchParams(location.search).get('fav') === '1';
  var state = {
    tab: IS_MINE ? 'mine' : 'all',        // all=智能体页 | mine=我的应用页
    q: '',
    category: '',
    type: '',
    sort: 'latest',
    apps: [],
    categories: [],
    drawer: null,      // 当前打开的抽屉 app
    convId: null,      // 抽屉当前会话
    streaming: false,
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  async function loadCategories() {
    try { state.categories = await EARP.fetchJSON('/api/app_categories'); }
    catch (e) { state.categories = []; }
  }

  async function loadApps() {
    var grid = document.getElementById('app-grid');
    grid.innerHTML = '<p class="kb-empty">加载中…</p>';
    var params = new URLSearchParams({ sort: state.sort });
    if (state.q) params.set('q', state.q);
    if (state.category) params.set('category', state.category);
    if (state.type) params.set('type', state.type);
    if (state.tab === 'mine') params.set('fav', '1');
    try {
      state.apps = await EARP.fetchJSON('/chat_apps?' + params.toString());
      renderApps();
    } catch (err) {
      grid.innerHTML = '<p class="kb-empty">加载失败: ' + esc(err.message) + '</p>';
    }
  }

  function renderApps() {
    var grid = document.getElementById('app-grid');
    if (!state.apps.length) {
      grid.innerHTML = '<p class="kb-empty">' + (state.tab === 'mine' ? '还没有收藏的智能体 — 在「全部智能体」中点 ⭐ 收藏' : '暂无已发布智能体 — 请先在「工作台 → chat / chatflow」创建并发布。') + '</p>';
      return;
    }
    grid.innerHTML = state.apps.map(function (a) {
      var typeCls = a.orchestration === 'flow' ? 'flow' : 'chat';
      var typeLabel = a.orchestration === 'flow' ? 'chatflow' : 'chat';
      var tags = (a.tags || []).map(function (t) { return '<span class="ac-tag">' + esc(t) + '</span>'; }).join('');
      return '<div class="app-card" data-id="' + esc(a.chat_app_id) + '">'
        + '<div class="ac-top"><span class="ac-name" title="' + esc(a.name) + '">' + esc(a.name) + '</span>'
        + '<span class="ac-type ' + typeCls + '">' + typeLabel + '</span>'
        + '<button class="ac-fav' + (a.favorite ? ' on' : '') + '" data-fav="' + esc(a.chat_app_id) + '" title="收藏">' + (a.favorite ? '★' : '☆') + '</button></div>'
        + '<div class="ac-desc">' + esc(a.description || '暂无描述') + '</div>'
        + '<div class="ac-meta">'
        + (a.category ? '<span class="ac-cat">' + esc(a.category) + '</span>' : '')
        + '<span class="ac-tags">' + tags + '</span>'
        + '<span>👤 ' + esc(a.created_by || '—') + '</span>'
        + '<span>★ ' + (a.favorite_count || 0) + '</span>'
        + '</div></div>';
    }).join('');
  }

  async function toggleFavorite(id, btn) {
    var favorited = btn.classList.contains('on');
    try {
      if (favorited) await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(id) + '/favorite', { method: 'DELETE' });
      else await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(id) + '/favorite', { method: 'POST' });
      await loadApps(); // 刷新（含计数与我的应用联动）
    } catch (err) { alert('收藏操作失败: ' + err.message); }
  }

  /* ── 运行抽屉 ── */
  function openDrawer(app) {
    state.drawer = app;
    state.convId = null;
    document.getElementById('rd-name').textContent = app.name;
    document.getElementById('rd-sub').textContent = (app.orchestration === 'flow' ? 'chatflow · ' : 'chat · ') + (app.category || '未分类');
    document.getElementById('rd-fav').textContent = app.favorite ? '★ 已收藏' : '☆ 收藏';
    document.getElementById('rd-fav').classList.toggle('on', !!app.favorite);
    document.getElementById('rd-msgs').innerHTML = '';
    document.getElementById('rd-input').disabled = false;
    document.getElementById('rd-send').disabled = false;
    document.getElementById('run-drawer').classList.add('open');
    setTimeout(function () { document.getElementById('rd-input').focus(); }, 80);
  }
  function closeDrawer() {
    if (state.streaming) { try { state.abort && state.abort.abort(); } catch (e) {} }
    document.getElementById('run-drawer').classList.remove('open');
  }

  function addMsg(role, text, cls) {
    var box = document.getElementById('rd-msgs');
    var el = document.createElement('div');
    el.className = 'rd-msg ' + (role === 'user' ? 'user' : (cls || 'assistant'));
    el.textContent = text;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }

  async function sendDrawerMsg() {
    if (state.streaming) return;
    var input = document.getElementById('rd-input');
    var query = input.value.trim();
    if (!query || !state.drawer) return;
    input.value = '';
    addMsg('user', query);
    var answerEl = addMsg('assistant', '');
    var flowEl = null;
    state.streaming = true;
    document.getElementById('rd-send').disabled = true;

    try {
      if (state.drawer.orchestration === 'flow') {
        answerEl.textContent = '⏳ 执行中…';
        var nodeMap = {};
        flowEl = addFlowPanel();
        await EARP.streamFlowSSE('/chat_apps/' + encodeURIComponent(state.drawer.chat_app_id) + '/chat/stream',
          { query: query, conversation_id: state.convId },
          function (ev, data) {
            if (ev === 'node_start') { flowNode(flowEl, nodeMap, data.node_id, data.node_type, 'running'); }
            else if (ev === 'token') { appendTokens(flowEl, data.text); }
            else if (ev === 'node_end') { flowNode(flowEl, nodeMap, data.node_id, null, data.status, data); }
            else if (ev === 'branch') { addBranch(flowEl, data.branch_id, data.side); }
            else if (ev === 'human_approval') { showHABar(data); }
            else if (ev === 'done') {
              state.convId = data.conversation_id;
              answerEl.textContent = data.answer || '(无输出)';
              flowEl.querySelector('.fp-title').textContent = '执行完成 (' + (data.status || 'completed') + ')';
            }
            else if (ev === 'error') {
              answerEl.className = 'rd-msg error';
              answerEl.textContent = data.message || '执行失败';
            }
          }, state.abort);
      } else {
        await EARP.streamSSE('/chat_apps/' + encodeURIComponent(state.drawer.chat_app_id) + '/chat',
          { query: query, conversation_id: state.convId },
          function (d) {
            if (d.token === '[DONE]') return;
            if (d.type === 'token') { answerEl.textContent += d.content; }
            else if (d.type === 'done') { state.convId = d.conversation_id; answerEl.textContent += ''; }
            else if (d.type === 'error') { answerEl.className = 'rd-msg error'; answerEl.textContent = d.message; }
          }, state.abort);
      }
    } catch (err) {
      answerEl.className = 'rd-msg error';
      answerEl.textContent = '请求失败: ' + (err.message || err);
    } finally {
      state.streaming = false;
      document.getElementById('rd-send').disabled = false;
      hideHABar();
    }
  }

  function addFlowPanel() {
    var box = document.getElementById('rd-msgs');
    var el = document.createElement('details');
    el.className = 'flow-progress';
    el.open = true;
    el.innerHTML = '<summary class="fp-title">节点执行过程</summary><div class="fp-body"></div>';
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }
  function flowNode(panel, nodeMap, nodeId, nodeType, status, meta) {
    var body = panel.querySelector('.fp-body');
    var row = nodeMap[nodeId];
    if (!row) {
      row = document.createElement('div');
      row.className = 'fp-node ' + (status || 'running');
      row.innerHTML = '<span class="fp-status"></span><span class="fp-label">' + esc(nodeId) + (nodeType ? ' <em>(' + esc(nodeType) + ')</em>' : '') + '</span><span class="fp-lat"></span>';
      body.appendChild(row);
      nodeMap[nodeId] = row;
    }
    row.className = 'fp-node ' + (status || 'running');
    if (meta && meta.latency_ms != null) row.querySelector('.fp-lat').textContent = (meta.latency_ms) + 'ms';
    if (meta && meta.error) {
      var err = document.createElement('div');
      err.className = 'fp-tokens';
      err.style.color = 'var(--red)';
      err.textContent = '✗ ' + meta.error;
      row.appendChild(err);
    }
  }
  function appendTokens(panel, text) {
    var body = panel.querySelector('.fp-body');
    var t = body.querySelector(':scope > .fp-tokens:last-child');
    if (!t) { t = document.createElement('div'); t.className = 'fp-tokens'; body.appendChild(t); }
    t.textContent += text;
  }
  function addBranch(panel, branchId, side) {
    var body = panel.querySelector('.fp-body');
    var el = document.createElement('div');
    el.className = 'fp-branch';
    el.textContent = '→ 分支 ' + branchId + ': ' + side;
    body.appendChild(el);
  }
  function showHABar(data) {
    var bar = document.getElementById('rd-ha');
    bar.innerHTML = '⏸ 等待确认：' + esc(data.question || '请确认是否继续')
      + ' <button class="btn-sm btn-primary" id="rd-ha-ok">确认</button>'
      + ' <button class="btn-sm btn-outline" id="rd-ha-no">拒绝</button>';
    bar.style.display = 'flex';
    document.getElementById('rd-ha-ok').onclick = function () { sendReplyAfterHA('确认'); };
    document.getElementById('rd-ha-no').onclick = function () { sendReplyAfterHA('拒绝'); };
  }
  function hideHABar() {
    var bar = document.getElementById('rd-ha');
    bar.style.display = 'none';
  }
  function sendReplyAfterHA(reply) {
    hideHABar();
    var input = document.getElementById('rd-input');
    input.value = reply;
    sendDrawerMsg();
  }

  /* ── 事件绑定 ── */
  function bind() {
    document.addEventListener('click', function (ev) {
      var favBtn = ev.target.closest('[data-fav]');
      if (favBtn) { ev.stopPropagation(); toggleFavorite(favBtn.dataset.fav, favBtn); return; }
      var card = ev.target.closest('.app-card');
      if (card) {
        var app = state.apps.find(function (a) { return a.chat_app_id === card.dataset.id; });
        if (app) openDrawer(app);
      }
      if (ev.target.id === 'rd-close' || ev.target.id === 'run-drawer' || ev.target.closest('.run-drawer-overlay') && ev.target.id === 'run-drawer') closeDrawer();
    });
    document.getElementById('rd-send').onclick = sendDrawerMsg;
    document.getElementById('rd-input').addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); sendDrawerMsg(); }
    });
    document.getElementById('rd-full').onclick = function () {
      if (state.drawer) location.href = 'run.html?app=' + encodeURIComponent(state.drawer.chat_app_id);
    };
    document.getElementById('rd-fav').onclick = async function () {
      if (!state.drawer) return;
      await toggleFavorite(state.drawer.chat_app_id, document.getElementById('rd-fav'));
      var app = await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(state.drawer.chat_app_id));
      state.drawer.favorite = app.favorite;
      document.getElementById('rd-fav').textContent = app.favorite ? '★ 已收藏' : '☆ 收藏';
    };
    document.getElementById('f-cat').onchange = function () { state.category = this.value; loadApps(); };
    document.getElementById('f-type').onchange = function () { state.type = this.value; loadApps(); };
    document.getElementById('f-sort').onchange = function () { state.sort = this.value; loadApps(); };
    var qInput = document.getElementById('f-q');
    var debounce;
    qInput.addEventListener('input', function () {
      clearTimeout(debounce);
      debounce = setTimeout(function () { state.q = qInput.value; loadApps(); }, 300);
    });
  }
  function renderCats() {
    var sel = document.getElementById('f-cat');
    sel.innerHTML = '<option value="">全部分类</option>' + state.categories.map(function (c) {
      return '<option value="' + esc(c.name) + '">' + esc(c.name) + '</option>';
    }).join('');
  }

  document.addEventListener('DOMContentLoaded', async function () {
    bind();
    await loadCategories();
    renderCats();
    await loadApps();
  });
})();
