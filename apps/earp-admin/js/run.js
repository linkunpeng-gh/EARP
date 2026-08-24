/* 智能体独立运行页 — 会话历史 + SSE 流式 + flow 节点执行面板 + human_approval */
(function () {
  var app = null;
  var convId = null;
  var streaming = false;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  async function init() {
    var params = new URLSearchParams(location.search);
    var appId = params.get('app');
    if (!appId) { document.getElementById('rp-name').textContent = '缺少 app 参数'; return; }
    try {
      app = await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(appId));
    } catch (e) {
      document.getElementById('rp-name').textContent = '加载失败: ' + e.message;
      return;
    }
    document.getElementById('rp-name').textContent = app.name;
    document.getElementById('rp-sub').textContent = (app.orchestration === 'flow' ? 'chatflow' : 'chat') + ' · ' + (app.category || '未分类') + ' · ' + esc(app.description || '');
    renderFav();
    await loadConvs();
    bind();
  }

  function renderFav() {
    var btn = document.getElementById('rp-fav');
    btn.textContent = app.favorite ? '★ 已收藏' : '☆ 收藏';
    btn.classList.toggle('on', !!app.favorite);
  }

  async function loadConvs() {
    var box = document.getElementById('conv-list');
    box.innerHTML = '<span style="color:var(--text-quaternary);font-size:0.75rem;">加载中…</span>';
    try {
      var convs = await EARP.fetchJSON('/conversations?chat_app_id=' + encodeURIComponent(app.chat_app_id));
      if (!convs.length) { box.innerHTML = '<span style="color:var(--text-quaternary);font-size:0.75rem;">暂无会话</span>'; return; }
      box.innerHTML = convs.map(function (c) {
        return '<div class="conv-item' + (c.conversation_id === convId ? ' active' : '') + '" data-cid="' + esc(c.conversation_id) + '" title="' + esc(c.title || '') + '">'
          + esc(c.title || '(无标题)') + '<br><span style="font-size:0.68rem;color:var(--text-quaternary);">' + (c.message_count || 0) + ' 条消息</span></div>';
      }).join('');
    } catch (e) {
      box.innerHTML = '<span style="color:var(--text-quaternary);font-size:0.75rem;">加载失败</span>';
    }
  }

  async function openConv(cid) {
    convId = cid;
    var box = document.getElementById('rm-msgs');
    box.innerHTML = '';
    if (!cid) return;
    try {
      var msgs = await EARP.fetchJSON('/conversations/' + encodeURIComponent(cid) + '/messages');
      msgs.forEach(function (m) {
        if (m.role === 'user') addBubble('user', m.content);
        else if (m.role === 'assistant') addBubble('assistant', m.content);
      });
    } catch (e) { addBubble('error', '加载消息失败: ' + e.message); }
    refreshConvActive();
  }

  function refreshConvActive() {
    document.querySelectorAll('.conv-item').forEach(function (el) {
      el.classList.toggle('active', el.dataset.cid === convId);
    });
  }

  function addBubble(role, text) {
    var box = document.getElementById('rm-msgs');
    var el = document.createElement('div');
    el.className = 'msg-bubble ' + (role === 'user' ? 'user' : role === 'error' ? 'assistant' : 'assistant');
    if (role === 'error') el.style.color = 'var(--red)';
    el.textContent = text;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }

  function addFlowPanel() {
    var box = document.getElementById('rm-msgs');
    var el = document.createElement('details');
    el.className = 'flow-progress';
    el.open = true;
    el.innerHTML = '<summary class="fp-title">节点执行过程</summary><div class="fp-body"></div>';
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }
  function flowNode(panel, map, nodeId, nodeType, status, meta) {
    var body = panel.querySelector('.fp-body');
    var row = map[nodeId];
    if (!row) {
      row = document.createElement('div');
      row.className = 'fp-node ' + (status || 'running');
      row.innerHTML = '<span class="fp-status"></span><span class="fp-label">' + esc(nodeId) + (nodeType ? ' <em>(' + esc(nodeType) + ')</em>' : '') + '</span><span class="fp-lat"></span>';
      body.appendChild(row);
      map[nodeId] = row;
    }
    row.className = 'fp-node ' + (status || 'running');
    if (meta && meta.latency_ms != null) row.querySelector('.fp-lat').textContent = meta.latency_ms + 'ms';
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

  async function send() {
    if (streaming) return;
    hideHA();  // 新消息发送：清理可能残留的人工确认条
    var input = document.getElementById('rm-input');
    var query = input.value.trim();
    if (!query) return;
    input.value = '';
    addBubble('user', query);
    var answerEl = addBubble('assistant', '');
    var flowEl = null;
    streaming = true;
    document.getElementById('rm-send').disabled = true;
    try {
      if (app.orchestration === 'flow') {
        answerEl.textContent = '⏳ 执行中…';
        flowEl = addFlowPanel();
        var nm = {};  // 每次消息独立节点状态表（恢复/多轮不串）
        await EARP.streamFlowSSE('/chat_apps/' + encodeURIComponent(app.chat_app_id) + '/chat/stream',
          { query: query, conversation_id: convId },
          function (ev, data) {
            if (ev === 'node_start') flowNode(flowEl, nm, data.node_id, data.node_type, 'running');
            else if (ev === 'token') appendTokens(flowEl, data.text);
            else if (ev === 'node_end') flowNode(flowEl, nm, data.node_id, null, data.status, data);
            else if (ev === 'branch') addBranch(flowEl, data.branch_id, data.side);
            else if (ev === 'human_approval') {
              convId = data.conversation_id;  // 恢复挂起需同一会话
              showHA(data);
            }
            else if (ev === 'done') {
              convId = data.conversation_id;
              answerEl.textContent = data.answer || '(无输出)';
              var title = flowEl.querySelector('.fp-title');
              if (title) title.textContent = '执行完成 (' + (data.status || 'completed') + ')';
              loadConvs();
            }
            else if (ev === 'error') {
              answerEl.className = 'msg-bubble assistant';
              answerEl.style.color = 'var(--red)';
              answerEl.textContent = data.message || '执行失败';
            }
          });
      } else {
        await EARP.streamSSE('/chat_apps/' + encodeURIComponent(app.chat_app_id) + '/chat',
          { query: query, conversation_id: convId },
          function (d) {
            if (d.token === '[DONE]') return;
            if (d.type === 'token') answerEl.textContent += d.content;
            else if (d.type === 'done') { convId = d.conversation_id; loadConvs(); }
            else if (d.type === 'error') { answerEl.style.color = 'var(--red)'; answerEl.textContent = d.message; }
          });
      }
    } catch (err) {
      answerEl.style.color = 'var(--red)';
      answerEl.textContent = '请求失败: ' + (err.message || err);
    } finally {
      streaming = false;
      document.getElementById('rm-send').disabled = false;
      // 注意：不在 finally 隐藏确认条——human_approval 后流正常结束，
      // 确认条必须保留供用户回复；由下一次 send 开头清理。
    }
  }

  function showHA(data) {
    var bar = document.getElementById('rp-ha');
    bar.innerHTML = '⏸ 等待确认：' + esc(data.question || '请确认是否继续')
      + ' <button class="btn-sm btn-primary" id="rp-ha-ok">确认</button>'
      + ' <button class="btn-sm btn-outline" id="rp-ha-no">拒绝</button>';
    bar.style.display = 'flex';
    document.getElementById('rp-ha-ok').onclick = function () { replyHA('确认'); };
    document.getElementById('rp-ha-no').onclick = function () { replyHA('拒绝'); };
  }
  function hideHA() {
    var bar = document.getElementById('rp-ha');
    bar.style.display = 'none';
  }
  function replyHA(reply) {
    hideHA();
    var input = document.getElementById('rm-input');
    input.value = reply;
    send();
  }

  function bind() {
    document.getElementById('rm-send').onclick = send;
    document.getElementById('rm-input').addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); send(); }
    });
    document.getElementById('rp-new').onclick = function () { openConv(null); };
    document.getElementById('rp-fav').onclick = async function () {
      if (app.favorite) await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(app.chat_app_id) + '/favorite', { method: 'DELETE' });
      else await EARP.fetchJSON('/chat_apps/' + encodeURIComponent(app.chat_app_id) + '/favorite', { method: 'POST' });
      app.favorite = !app.favorite;
      renderFav();
    };
    document.getElementById('conv-list').addEventListener('click', function (ev) {
      var item = ev.target.closest('.conv-item');
      if (item) openConv(item.dataset.cid);
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
