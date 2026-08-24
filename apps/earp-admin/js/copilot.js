/* EARP AI Assist Panel — Copilot for configuration pages.
 *
 * Usage: include this script after app.js, then call:
 *   EARPCopilot.init({ pageId: 'models', getFormState: fn })
 *
 * The panel provides:
 * - Side panel with streaming AI responses
 * - Quick prompt buttons
 * - Multi-turn conversation
 * - KB-backed context (server-side)
 */

var EARPCopilot = (function() {
  var _pageId = '';
  var _getFormState = function() { return {}; };
  var _conversationId = null;
  var _isOpen = false;
  var _isStreaming = false;

  function _escapeHtml(text) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(text));
    return d.innerHTML;
  }

  function _renderMarkdown(text) {
    var html = _escapeHtml(text);
    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Lists
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    // Numbered lists
    html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    return html;
  }

  function _ensurePanel() {
    if (document.getElementById('ai-panel-overlay')) return;
    var overlay = document.createElement('div');
    overlay.id = 'ai-panel-overlay';
    overlay.className = 'ai-panel-overlay';
    overlay.onclick = function(e) {
      if (e.target === overlay) close();
    };
    var panel = document.createElement('div');
    panel.className = 'ai-panel';

    var header = document.createElement('div');
    header.className = 'ai-panel-header';
    var h3 = document.createElement('h3');
    h3.innerHTML = '<span class="ai-dot"></span> AI 配置助手';
    header.appendChild(h3);
    var closeBtn = document.createElement('button');
    closeBtn.className = 'ai-panel-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.onclick = function() { close(); };
    header.appendChild(closeBtn);
    panel.appendChild(header);

    var quickDiv = document.createElement('div');
    quickDiv.id = 'ai-quick-prompts';
    quickDiv.className = 'ai-quick-prompts';
    panel.appendChild(quickDiv);

    var msgDiv = document.createElement('div');
    msgDiv.id = 'ai-messages';
    msgDiv.className = 'ai-messages';
    var emptyDiv = document.createElement('div');
    emptyDiv.id = 'ai-empty';
    emptyDiv.className = 'ai-empty';
    emptyDiv.innerHTML = '<p><strong>\u914D\u7F6E\u52A9\u624B</strong></p><p>\u6211\u53EF\u4EE5\u5E2E\u4F60\u7406\u89E3\u53C2\u6570\u542B\u4E49\u3001\u8BCA\u65AD\u914D\u7F6E\u95EE\u9898\u3001\u5EFA\u8BAE\u6700\u4F73\u5B9E\u8DF5\u3002</p>';
    msgDiv.appendChild(emptyDiv);
    panel.appendChild(msgDiv);

    var inputDiv = document.createElement('div');
    inputDiv.className = 'ai-panel-input';
    var input = document.createElement('input');
    input.id = 'ai-input';
    input.placeholder = '\u8F93\u5165\u5173\u4E8E\u5F53\u524D\u914D\u7F6E\u7684\u95EE\u9898...';
    input.onkeydown = function(e) { if (e.key === 'Enter') send(); };
    inputDiv.appendChild(input);
    var sendBtn = document.createElement('button');
    sendBtn.textContent = '\u53D1\u9001';
    sendBtn.onclick = function() { send(); };
    inputDiv.appendChild(sendBtn);
    panel.appendChild(inputDiv);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);
  }

  function _renderQuickPrompts(prompts) {
    var container = document.getElementById('ai-quick-prompts');
    if (!container || !prompts || !prompts.length) return;
    container.innerHTML = prompts.map(function(p) {
      return '<button class="ai-quick-btn" onclick="EARPCopilot.quickAsk(\'' + _escapeHtml(p).replace(/'/g, "\\'") + '\')">' + _escapeHtml(p) + '</button>';
    }).join('');
  }

  function _addMessage(role, content, sources) {
    var container = document.getElementById('ai-messages');
    var empty = document.getElementById('ai-empty');
    if (empty) empty.style.display = 'none';

    var div = document.createElement('div');
    div.className = 'ai-msg ' + role;
    if (role === 'assistant') {
      div.innerHTML = _renderMarkdown(content);
      if (sources && sources.length) {
        var srcDiv = document.createElement('div');
        srcDiv.className = 'ai-msg-sources';
        sources.forEach(function(s) {
          var tag = document.createElement('span');
          tag.className = 'ai-msg-source-tag';
          tag.textContent = s.knowledge_base_name || s.title || '来源';
          tag.title = s.title + '\n' + (s.content || '').substring(0, 100);
          srcDiv.appendChild(tag);
        });
        div.appendChild(srcDiv);
      }
    } else {
      div.textContent = content;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
  }

  function _showTyping() {
    var container = document.getElementById('ai-messages');
    var div = document.createElement('div');
    div.className = 'ai-typing';
    div.id = 'ai-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function _removeTyping() {
    var el = document.getElementById('ai-typing');
    if (el) el.remove();
  }

  function _collectFormState() {
    try {
      return _getFormState();
    } catch (e) {
      return {};
    }
  }

  // ── Public API ──

  function init(opts) {
    _pageId = opts.pageId || '';
    _getFormState = opts.getFormState || function() { return {}; };
    _conversationId = null;

    // Find or create trigger button
    if (opts.triggerSelector) {
      var trigger = document.querySelector(opts.triggerSelector);
      if (trigger) {
        trigger.onclick = function() { toggle(); };
      }
    }
  }

  function toggle() {
    if (_isOpen) close();
    else open();
  }

  function open() {
    _ensurePanel();
    _isOpen = true;
    var overlay = document.getElementById('ai-panel-overlay');
    if (!overlay) return;
    overlay.classList.add('open');
    var input = document.getElementById('ai-input');
    if (input) input.focus();

    // Load quick prompts
    _renderQuickPrompts([
      '\u89E3\u91CA\u5F53\u524D\u9875\u9762\u6240\u6709\u53C2\u6570',
      '\u68C0\u67E5\u6211\u7684\u914D\u7F6E\u662F\u5426\u6B63\u786E',
      '\u6839\u636E\u6700\u4F73\u5B9E\u8DF5\u4F18\u5316\u914D\u7F6E',
    ]);
  }

  function close() {
    _isOpen = false;
    var overlay = document.getElementById('ai-panel-overlay');
    if (overlay) overlay.classList.remove('open');
  }

  function quickAsk(question) {
    document.getElementById('ai-input').value = question;
    send();
  }

  async function send() {
    var input = document.getElementById('ai-input');
    var query = input.value.trim();
    if (!query || _isStreaming) return;

    input.value = '';
    _addMessage('user', query);
    _showTyping();
    _isStreaming = true;

    // Determine intent from query
    var intent = 'explain';
    if (/检查|诊断|问题|错误|不对|不正确|验证/.test(query)) intent = 'diagnose';
    else if (/优化|建议|改进|最佳|推荐|怎么配/.test(query)) intent = 'suggest';

    var formState = _collectFormState();

    try {
      var responseText = '';
      var sources = [];

      await EARP.streamSSE('/copilot/assist', {
        page_id: _pageId,
        intent: intent,
        query: query,
        form_state: formState,
        conversation_id: _conversationId,
      }, function(ev) {
        if (ev.type === 'token') {
          responseText += ev.content;
          // Update the assistant message in-place
          _updateStreamingMessage(responseText, sources);
        } else if (ev.type === 'sources') {
          sources = ev.items || [];
        } else if (ev.type === 'done') {
          if (ev.conversation_id) _conversationId = ev.conversation_id;
        } else if (ev.type === 'error') {
          responseText = ev.message || 'AI 助手出错';
          _updateStreamingMessage(responseText, []);
        }
      });

      // Finalize: remove streaming indicator, show final message
      _removeTyping();
      if (!responseText) {
        _addMessage('assistant', 'AI 助手未返回内容，请重试。', []);
      }
    } catch (e) {
      _removeTyping();
      _addMessage('assistant', '请求失败: ' + e.message, []);
    } finally {
      _isStreaming = false;
    }
  }

  function _updateStreamingMessage(text, sources) {
    var container = document.getElementById('ai-messages');
    var existing = container.querySelector('.ai-msg.assistant:last-child');
    if (!existing || existing.dataset.streaming !== 'true') {
      _removeTyping();
      existing = _addMessage('assistant', '', sources);
      existing.dataset.streaming = 'true';
    }
    existing.innerHTML = _renderMarkdown(text);
    if (sources && sources.length) {
      var srcDiv = document.createElement('div');
      srcDiv.className = 'ai-msg-sources';
      sources.forEach(function(s) {
        var tag = document.createElement('span');
        tag.className = 'ai-msg-source-tag';
        tag.textContent = s.knowledge_base_name || s.title || '来源';
        tag.title = s.title + '\n' + (s.content || '').substring(0, 100);
        srcDiv.appendChild(tag);
      });
      existing.appendChild(srcDiv);
    }
    container.scrollTop = container.scrollHeight;
  }

  return {
    init: init,
    open: open,
    close: close,
    toggle: toggle,
    send: send,
    quickAsk: quickAsk,
  };
})();

// Ensure global access
if (typeof window !== 'undefined') window.EARPCopilot = EARPCopilot;
