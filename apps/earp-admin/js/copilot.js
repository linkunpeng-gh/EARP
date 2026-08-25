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
  var _abortController = null;
  var _suggestions = [];
  var _ghostElements = {};
  var _applyPlan = null;
  var _commonQuestions = [];

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
    emptyDiv.innerHTML = '<p><strong>\u914D\u7F6E\u52A9\u624B</strong></p><p>\u6211\u53EF\u4EE5\u5E2E\u4F60\u7406\u89E3\u53C2\u6570\u542B\u4E49\u3001\u8BCA\u65AD\u914D\u7F6E\u95EE\u9898\u3001\u5EFA\u8BAE\u6700\u4F73\u5B9E\u8DF5\u3001\u667A\u80FD\u586B\u5145\u3002</p>';
    msgDiv.appendChild(emptyDiv);
    panel.appendChild(msgDiv);

    // Suggestions action bar
    var suggestionsBar = document.createElement('div');
    suggestionsBar.id = 'ai-suggestions-bar';
    suggestionsBar.className = 'ai-suggestions-bar';
    suggestionsBar.style.display = 'none';
    var countSpan = document.createElement('span');
    countSpan.className = 'ai-suggestions-count';
    countSpan.textContent = '0 个建议';
    suggestionsBar.appendChild(countSpan);
    var acceptAllBtn = document.createElement('button');
    acceptAllBtn.className = 'ai-suggestions-btn';
    acceptAllBtn.textContent = '接受全部';
    acceptAllBtn.onclick = function() { acceptAllSuggestions(); };
    suggestionsBar.appendChild(acceptAllBtn);
    var rejectAllBtn = document.createElement('button');
    rejectAllBtn.className = 'ai-suggestions-btn secondary';
    rejectAllBtn.textContent = '清除全部';
    rejectAllBtn.onclick = function() { rejectAllSuggestions(); };
    suggestionsBar.appendChild(rejectAllBtn);
    panel.appendChild(suggestionsBar);

    var inputDiv = document.createElement('div');
    inputDiv.className = 'ai-panel-input';
    var input = document.createElement('input');
    input.id = 'ai-input';
    input.placeholder = '\u8F93\u5165\u5173\u4E8E\u5F53\u524D\u914D\u7F6E\u7684\u95EE\u9898...';
    input.onkeydown = function(e) { if (e.key === 'Enter') send(); };
    inputDiv.appendChild(input);
    var sendBtn = document.createElement('button');
    sendBtn.id = 'ai-send-btn';
    sendBtn.className = 'ai-send-btn';
    sendBtn.textContent = '\u53D1\u9001';
    sendBtn.onclick = function() { send(); };
    inputDiv.appendChild(sendBtn);
    var stopBtn = document.createElement('button');
    stopBtn.id = 'ai-stop-btn';
    stopBtn.className = 'ai-stop-btn';
    stopBtn.style.display = 'none';
    stopBtn.innerHTML = '\u25A0 \u505C\u6B62';
    stopBtn.onclick = function() { stop(); };
    inputDiv.appendChild(stopBtn);
    panel.appendChild(inputDiv);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);
  }

  function _renderQuickPrompts(prompts) {
    var container = document.getElementById('ai-quick-prompts');
    if (!container) return;
    container.innerHTML = '';
    if (!prompts || !prompts.length) return;
    prompts.forEach(function(p) {
      var btn = document.createElement('button');
      btn.className = 'ai-quick-btn';
      btn.textContent = p;
      btn.onclick = function() { EARPCopilot.quickAsk(p); };
      container.appendChild(btn);
    });
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

  function _toggleButtons(streaming) {
    var sendBtn = document.getElementById('ai-send-btn');
    var stopBtn = document.getElementById('ai-stop-btn');
    var input = document.getElementById('ai-input');
    if (sendBtn) sendBtn.style.display = streaming ? 'none' : '';
    if (stopBtn) stopBtn.style.display = streaming ? '' : 'none';
    if (input) input.disabled = streaming;
  }

  // ── Ghost Text & Suggestions ──

  function _clearAllGhostTexts() {
    Object.keys(_ghostElements).forEach(function(fieldId) {
      var el = _ghostElements[fieldId];
      if (el && el.parentNode) el.parentNode.removeChild(el);
    });
    _ghostElements = {};
  }

  function _renderGhostText(fieldId, suggestion) {
    // Find the input element by field ID
    var inputEl = document.getElementById(fieldId);
    if (!inputEl) {
      // Try common ID patterns
      var patterns = [
        'def-' + fieldId,
        'add-' + fieldId,
        fieldId.replace('_', '-'),
      ];
      for (var i = 0; i < patterns.length; i++) {
        inputEl = document.getElementById(patterns[i]);
        if (inputEl) break;
      }
    }
    if (!inputEl) return;

    // Remove existing ghost text for this field
    _removeGhostText(fieldId);

    // Create ghost text container
    var ghost = document.createElement('div');
    ghost.className = 'ai-ghost-text';
    ghost.dataset.field = fieldId;

    // Value display
    var valueSpan = document.createElement('span');
    valueSpan.className = 'ai-ghost-value';
    valueSpan.textContent = '建议: ' + suggestion.value;
    ghost.appendChild(valueSpan);

    // Confidence badge
    var confBadge = document.createElement('span');
    confBadge.className = 'ai-ghost-confidence';
    confBadge.textContent = Math.round(suggestion.confidence * 100) + '%';
    ghost.appendChild(confBadge);

    // Reason
    if (suggestion.reason) {
      var reasonSpan = document.createElement('span');
      reasonSpan.className = 'ai-ghost-reason';
      reasonSpan.textContent = suggestion.reason;
      ghost.appendChild(reasonSpan);
    }

    // Accept button
    var acceptBtn = document.createElement('button');
    acceptBtn.className = 'ai-ghost-btn accept';
    acceptBtn.textContent = '✓ 接受';
    acceptBtn.onclick = function(e) {
      e.stopPropagation();
      acceptSuggestion(fieldId);
    };
    ghost.appendChild(acceptBtn);

    // Reject button
    var rejectBtn = document.createElement('button');
    rejectBtn.className = 'ai-ghost-btn reject';
    rejectBtn.textContent = '✕ 跳过';
    rejectBtn.onclick = function(e) {
      e.stopPropagation();
      rejectSuggestion(fieldId);
    };
    ghost.appendChild(rejectBtn);

    // Insert ghost text after the input element
    inputEl.parentNode.insertBefore(ghost, inputEl.nextSibling);
    _ghostElements[fieldId] = ghost;

    // Tab key to accept
    inputEl.addEventListener('keydown', function handler(e) {
      if (e.key === 'Tab' && _ghostElements[fieldId]) {
        e.preventDefault();
        acceptSuggestion(fieldId);
        inputEl.removeEventListener('keydown', handler);
      }
    });
  }

  function _removeGhostText(fieldId) {
    var el = _ghostElements[fieldId];
    if (el && el.parentNode) {
      el.parentNode.removeChild(el);
    }
    delete _ghostElements[fieldId];
  }

  function acceptSuggestion(fieldId) {
    var suggestion = _suggestions.find(function(s) { return s.field === fieldId; });
    if (!suggestion) return;

    // Find input element and set value
    var inputEl = document.getElementById(fieldId);
    if (!inputEl) {
      var patterns = ['def-' + fieldId, 'add-' + fieldId, fieldId.replace('_', '-')];
      for (var i = 0; i < patterns.length; i++) {
        inputEl = document.getElementById(patterns[i]);
        if (inputEl) break;
      }
    }
    if (inputEl) {
      inputEl.value = suggestion.value;
      inputEl.dispatchEvent(new Event('change', { bubbles: true }));
    }

    _removeGhostText(fieldId);
    _suggestions = _suggestions.filter(function(s) { return s.field !== fieldId; });
    _updateSuggestionsBar();
  }

  function rejectSuggestion(fieldId) {
    _removeGhostText(fieldId);
    _suggestions = _suggestions.filter(function(s) { return s.field !== fieldId; });
    _updateSuggestionsBar();
  }

  function acceptAllSuggestions() {
    var fields = _suggestions.map(function(s) { return s.field; });
    fields.forEach(function(fieldId) {
      acceptSuggestion(fieldId);
    });
  }

  function rejectAllSuggestions() {
    var fields = _suggestions.map(function(s) { return s.field; });
    fields.forEach(function(fieldId) {
      rejectSuggestion(fieldId);
    });
  }

  function _updateSuggestionsBar() {
    var bar = document.getElementById('ai-suggestions-bar');
    if (!bar) return;
    if (_suggestions.length === 0) {
      bar.style.display = 'none';
      return;
    }
    bar.style.display = 'flex';
    bar.querySelector('.ai-suggestions-count').textContent = _suggestions.length + ' 个建议';
  }

  function _renderSuggestions(suggestions) {
    _suggestions = suggestions;
    _clearAllGhostTexts();

    if (suggestions.length === 0) {
      _addMessage('assistant', '没有找到需要建议的字段。', []);
      return;
    }

    // Render ghost text for each suggestion
    suggestions.forEach(function(s) {
      _renderGhostText(s.field, s);
    });

    // Show suggestions bar
    _updateSuggestionsBar();

    // Add summary message
    var summary = '已生成 ' + suggestions.length + ' 个配置建议：\n';
    suggestions.forEach(function(s, i) {
      var conf = Math.round(s.confidence * 100);
      summary += (i + 1) + '. **' + s.field + '** → ' + s.value + ' (' + conf + '%) ' + s.reason + '\n';
    });
    summary += '\n点击字段下方的「接受」或按 Tab 键采纳建议。';
    _addMessage('assistant', summary, []);
  }

  // ── Apply Plan (一键配置) ──

  function _renderApplyPlan(plan) {
    _applyPlan = plan;
    var fields = plan.fields || {};
    var explanation = plan.explanation || '';
    var formState = _collectFormState();

    if (Object.keys(fields).length === 0) {
      _addMessage('assistant', 'AI 未能生成配置方案，请重试。', []);
      return;
    }

    // Build diff rows
    var rows = '';
    Object.keys(fields).forEach(function(fieldId) {
      var newVal = fields[fieldId];
      var oldVal = formState[fieldId];
      var oldDisplay = (oldVal !== undefined && oldVal !== null && oldVal !== '') ? String(oldVal) : '(空)';
      var newDisplay = String(newVal);
      var isChanged = String(oldVal) !== String(newVal);
      var isPlaceholder = newVal === '__PLACEHOLDER__';
      var rowClass = isPlaceholder ? 'placeholder' : (isChanged ? 'changed' : 'same');
      rows += '<div class="ai-apply-row ' + rowClass + '">'
        + '<span class="ai-apply-field">' + _escapeHtml(fieldId) + '</span>'
        + '<span class="ai-apply-old">' + _escapeHtml(oldDisplay) + '</span>'
        + '<span class="ai-apply-arrow">→</span>'
        + '<span class="ai-apply-new">' + _escapeHtml(newDisplay) + '</span>'
        + '</div>';
    });

    var html = '<div class="ai-apply-plan">'
      + '<div class="ai-apply-header">配置方案预览</div>'
      + (explanation ? '<div class="ai-apply-explanation">' + _escapeHtml(explanation) + '</div>' : '')
      + '<div class="ai-apply-rows">' + rows + '</div>'
      + '<div class="ai-apply-actions">'
      + '<button class="ai-apply-btn primary" onclick="EARPCopilot.applyPlan()">应用配置</button>'
      + '<button class="ai-apply-btn secondary" onclick="EARPCopilot.cancelPlan()">取消</button>'
      + '</div>'
      + '</div>';

    _addMessage('assistant', html, []);
  }

  function applyPlan() {
    if (!_applyPlan || !_applyPlan.fields) return;
    var fields = _applyPlan.fields;
    var applied = 0;
    var skipped = 0;

    Object.keys(fields).forEach(function(fieldId) {
      var value = fields[fieldId];
      if (value === '__PLACEHOLDER__') { skipped++; return; }

      var inputEl = document.getElementById(fieldId);
      if (!inputEl) {
        var patterns = ['def-' + fieldId, 'add-' + fieldId, fieldId.replace('_', '-')];
        for (var i = 0; i < patterns.length; i++) {
          inputEl = document.getElementById(patterns[i]);
          if (inputEl) break;
        }
      }
      if (!inputEl) { skipped++; return; }

      inputEl.value = value;
      inputEl.dispatchEvent(new Event('change', { bubbles: true }));
      applied++;
    });

    var msg = '已应用 ' + applied + ' 个字段配置。';
    if (skipped > 0) msg += '\n' + skipped + ' 个敏感字段需手动填写。';
    msg += '\n请检查后点击页面上的「保存」按钮。';
    _addMessage('assistant', msg, []);
    _applyPlan = null;
  }

  function cancelPlan() {
    _applyPlan = null;
    _addMessage('assistant', '已取消配置方案。', []);
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

  async function open() {
    _ensurePanel();
    _isOpen = true;
    var overlay = document.getElementById('ai-panel-overlay');
    if (!overlay) return;
    overlay.classList.add('open');
    var input = document.getElementById('ai-input');
    if (input) input.focus();

    // Default prompts as fallback
    var defaultPrompts = [
      '解释当前页面所有参数',
      '检查我的配置是否正确',
    ];

    // Fetch page-specific common questions from API
    try {
      var pages = await EARP.fetchJSON('/copilot/pages');
      var page = pages.find(function(p) { return p.page_id === _pageId; });
      _commonQuestions = (page && page.common_questions) || [];
    } catch (e) {
      _commonQuestions = [];
    }

    // Render quick prompts — use page-specific questions, fallback to defaults
    var prompts = _commonQuestions.length > 0 ? _commonQuestions : defaultPrompts;
    _renderQuickPrompts(prompts);

    // Restore suggestions bar if there are pending suggestions
    _updateSuggestionsBar();
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

  function stop() {
    if (_abortController) {
      _abortController.abort();
      _abortController = null;
    }
  }

  function _toggleSendStop(streaming) {
    var sendBtn = document.getElementById('ai-send-btn');
    var stopBtn = document.getElementById('ai-stop-btn');
    if (sendBtn) sendBtn.style.display = streaming ? 'none' : '';
    if (stopBtn) stopBtn.style.display = streaming ? '' : 'none';
  }

  async function send() {
    var input = document.getElementById('ai-input');
    var query = input.value.trim();
    if (!query || _isStreaming) return;

    input.value = '';
    _addMessage('user', query);
    _showTyping();
    _isStreaming = true;
    _toggleSendStop(true);

    // Determine intent from query
    var intent = 'explain';
    if (/一键配置|完整配置|帮我配|帮我配置/.test(query)) intent = 'apply';
    else if (/自动填充|自动|填充|帮我自动配置/.test(query)) intent = 'autofill';
    else if (/检查|诊断|问题|错误|不对|不正确|验证/.test(query)) intent = 'diagnose';
    else if (/优化|建议|改进|最佳|推荐|怎么配/.test(query)) intent = 'suggest';

    var formState = _collectFormState();
    _abortController = new AbortController();

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
        } else if (ev.type === 'suggestions') {
          _renderSuggestions(ev.items || []);
        } else if (ev.type === 'apply_plan') {
          _renderApplyPlan(ev);
        } else if (ev.type === 'done') {
          if (ev.conversation_id) _conversationId = ev.conversation_id;
        } else if (ev.type === 'error') {
          responseText = ev.message || 'AI 助手出错';
          _updateStreamingMessage(responseText, []);
        }
      }, _abortController.signal);

      // Finalize: remove streaming indicator, show final message
      _removeTyping();
      if (!responseText) {
        _addMessage('assistant', 'AI 助手未返回内容，请重试。', []);
      }
    } catch (e) {
      _removeTyping();
      if (e.name === 'AbortError') {
        _addMessage('assistant', '已停止当前任务。', []);
      } else {
        _addMessage('assistant', '请求失败: ' + e.message, []);
      }
    } finally {
      _isStreaming = false;
      _abortController = null;
      _toggleSendStop(false);
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
    stop: stop,
    quickAsk: quickAsk,
    acceptSuggestion: acceptSuggestion,
    rejectSuggestion: rejectSuggestion,
    acceptAllSuggestions: acceptAllSuggestions,
    rejectAllSuggestions: rejectAllSuggestions,
    applyPlan: applyPlan,
    cancelPlan: cancelPlan,
  };
})();

// Ensure global access
if (typeof window !== 'undefined') window.EARPCopilot = EARPCopilot;
