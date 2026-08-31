/* ════════════════════════════════════════════════════════════════════════
 * ECMC N01B — 校验面板（ecmc-validation.js）
 *
 * 设计: FE-ECMC-2026-0830 §10 校验面板、§13 ValidationDrawer
 * 每条 ValidationIssue 展示 code/message/resource type/resource key/修复建议/“定位”；
 * 点击定位派发 ecmc:locate 事件，由编辑器消费（画布居中选中 / 打开属性 Tab）。
 * 权限、可见性、If-Match 冲突、active CAS 冲突、请求 schema 错误通过全局错误条
 * 展示，不混入校验列表（§10、§15.2）。
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var RESOURCE_LABELS = {
    node: '节点', edge: '边', rule: '规则', evidence: '证据需求',
    evidence_requirement: '证据需求', version: '版本', catalog_change_request: '目录申请',
  };

  function summarize(result) {
    var errors = 0, warnings = 0;
    (result && result.issues || []).forEach(function (i) {
      if (i.severity === 'error') errors++;
      else if (i.severity === 'warning') warnings++;
    });
    return { errors: errors, warnings: warnings, result: result };
  }

  function locateLabel(location) {
    if (!location) return '';
    var parts = [];
    if (location.resource_type) parts.push(RESOURCE_LABELS[location.resource_type] || location.resource_type);
    if (location.node_key) parts.push(location.node_key);
    if (location.edge_key) parts.push(location.edge_key);
    if (location.rule_key) parts.push(location.rule_key);
    if (location.requirement_key) parts.push(location.requirement_key);
    if (location.field) parts.push('@' + location.field);
    return parts.join(' / ');
  }

  function issueHtml(issue) {
    var loc = issue.location || {};
    var isError = issue.severity === 'error';
    var help = issue.suggested_action || (isError ? '修复阻断项后重新校验' : '复核后决定是否保留');
    return '<div class="ecmc-validation-item ' + (isError ? 'error' : 'warning') + '">'
      + '<span class="vi-code">' + ECMC.common.esc(issue.code) + '</span>'
      + '<div class="vi-main">'
      + '<div class="vi-msg">' + ECMC.common.esc(issue.message) + '</div>'
      + '<div class="vi-loc">' + ECMC.common.esc(locateLabel(loc)) + '</div>'
      + '<div class="vi-action">' + ECMC.common.esc(help) + '</div>'
      + '</div>'
      + '<button type="button" class="vi-locate" data-locate>定位</button>'
      + '</div>';
  }

  function render(container, result) {
    var issues = (result && result.issues) || [];
    var errors = issues.filter(function (i) { return i.severity === 'error'; });
    var warnings = issues.filter(function (i) { return i.severity === 'warning'; });
    if (!issues.length) {
      container.innerHTML = '<div class="ecmc-validation-empty">校验通过：未发现阻断项或警告。</div>';
      return;
    }
    var rendered = [];
    var html = '';
    if (errors.length) {
      html += '<div class="ecmc-validation-group"><div class="ecmc-validation-group-title error">阻断发布 · ' + errors.length + '</div>'
        + errors.map(function (i) { rendered.push(i); return issueHtml(i); }).join('') + '</div>';
    }
    if (warnings.length) {
      html += '<div class="ecmc-validation-group"><div class="ecmc-validation-group-title warning">警告 · ' + warnings.length + '</div>'
        + warnings.map(function (i) { rendered.push(i); return issueHtml(i); }).join('') + '</div>';
    }
    container.innerHTML = html;
    Array.prototype.forEach.call(container.querySelectorAll('[data-locate]'), function (btn, index) {
      btn.addEventListener('click', function () {
        document.dispatchEvent(new CustomEvent('ecmc:locate', { detail: { issue: rendered[index] } }));
      });
    });
  }

  window.ECMC = window.ECMC || {};
  window.ECMC.validation = {
    summarize: summarize,
    render: render,
    locateLabel: locateLabel,
  };
})();
