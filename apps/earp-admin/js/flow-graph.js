/* EARP Chatflow F5a — flow_schema JSON 校验 + SVG 流程图渲染（纯 vanilla，file:// 直开）。
 *
 * - validateFlowSchema(graph) → 错误数组（移植 orchestrator/workflow_dsl.validate_workflow
 *   的核心规则：节点白名单 / 恰一 start·end / 边引用 / 自环 / 重复边 / condition 恰 2 出边
 *   true·false / 非 condition 出边 ≤1 / 无环(DAG)）。注意：前端只做「即时提示」，
 *   后端门禁（PATCH /chat_apps 422）是权威。
 * - renderFlowGraph(schema, container) → 拓扑分层布局的 SVG（start 左 → end 右）。
 * - flowExampleSchema(kind) → 示例模板（simple 顺序 / full 全节点含 human_approval）。
 */

(function () {
  'use strict';

  var FLOW_TYPES = ['start', 'end', 'step', 'condition', 'capability', 'llm', 'knowledge',
    'qu', 'chat_history', 'human_approval', 'tool', 'mcp', 'note', 'answer'];

  var NODE_META = {
    start: { color: '#16a34a', label: '开始' },
    end: { color: '#64748b', label: '结束' },
    llm: { color: '#7c3aed', label: 'LLM' },
    note: { color: '#94a3b8', label: '注释' },
    knowledge: { color: '#2563eb', label: '知识检索' },
    qu: { color: '#ea580c', label: 'QU 理解' },
    capability: { color: '#dc2626', label: '能力调用' },
    tool: { color: '#0891b2', label: '工具取数' },
    chat_history: { color: '#475569', label: '历史' },
    condition: { color: '#ca8a04', label: '条件分支' },
    human_approval: { color: '#db2777', label: '人工确认' },
    step: { color: '#6b7280', label: '步骤' },
    mcp: { color: '#9333ea', label: 'MCP' },
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ── 校验（移植 validate_workflow）───────────────────────────────────────────

  function validateFlowSchema(graph) {
    var errors = [];
    if (!graph || typeof graph !== 'object' || !Array.isArray(graph.nodes)) {
      return ['flow_schema 必须是 { nodes: [...], edges: [...] } 结构'];
    }
    var nodes = graph.nodes;
    var edges = Array.isArray(graph.edges) ? graph.edges : [];
    var ids = {};
    var byId = {};
    nodes.forEach(function (n, i) {
      if (!n.id) { errors.push('第 ' + (i + 1) + ' 个节点缺 id'); return; }
      if (ids[n.id]) errors.push('节点 id 重复: ' + n.id);
      ids[n.id] = true;
      byId[n.id] = n;
      if (FLOW_TYPES.indexOf(n.type) < 0) {
        errors.push('节点 ' + n.id + ': 未知类型 ' + n.type + '（允许: ' + FLOW_TYPES.join(', ') + '）');
      }
    });
    var starts = nodes.filter(function (n) { return n.type === 'start'; });
    var ends = nodes.filter(function (n) { return n.type === 'end'; });
    var answers = nodes.filter(function (n) { return n.type === 'answer'; });
    if (starts.length !== 1) errors.push('必须有且仅有一个 start 节点（当前 ' + starts.length + ' 个）');
    if (ends.length > 1) errors.push('end 节点最多一个（当前 ' + ends.length + ' 个）');
    if (!ends.length && !answers.length) errors.push('流程需要至少一个终点节点（end 或回答）');

    var incoming = {};
    var outgoing = {};
    nodes.forEach(function (n) { incoming[n.id] = []; outgoing[n.id] = []; });
    var edgeKeys = {};
    edges.forEach(function (e, i) {
      if (!byId[e.source]) errors.push('边 ' + (i + 1) + ': 起点节点 ' + e.source + ' 不存在');
      if (!byId[e.target]) errors.push('边 ' + (i + 1) + ': 终点节点 ' + e.target + ' 不存在');
      if (e.source === e.target) errors.push('边 ' + e.source + '->' + e.target + ': 自环');
      var key = e.source + '|' + e.target + '|' + (e.sourceHandle || '');
      if (edgeKeys[key]) errors.push('重复边: ' + key);
      edgeKeys[key] = true;
      if (byId[e.source] && byId[e.target]) {
        incoming[e.target].push(e);
        outgoing[e.source].push(e);
      }
    });
    if (starts[0] && byId[starts[0].id]) {
      if (incoming[starts[0].id].length) errors.push('start 节点不能有入边');
      if (!outgoing[starts[0].id].length && nodes.length > 1) errors.push('start 节点必须有出边');
    }
    if (ends[0] && byId[ends[0].id]) {
      if (outgoing[ends[0].id].length) errors.push('end 节点不能有出边');
    }
    nodes.forEach(function (n) {
      if (n.type === 'answer') {
        if ((outgoing[n.id] || []).length) errors.push('answer ' + n.id + ': 回答节点是终点，不允许出边');
        if (!n.data || !String(n.data.text || '').trim()) errors.push('answer ' + n.id + ': 回答内容（text 模板）必填');
      }
    });
    nodes.forEach(function (n) {
      var outs = outgoing[n.id] || [];
      if (n.type === 'condition') {
        var handles = outs.map(function (e) { return e.sourceHandle || ''; }).slice().sort();
        if (outs.length !== 2 || handles.join(',') !== 'false,true') {
          errors.push('condition ' + n.id + ': 需要恰好 2 条出边（sourceHandle true/false 各一）');
        }
      } else if (n.type === 'note') {
        if ((incoming[n.id] || []).length || outs.length) {
          errors.push('note ' + n.id + ': 注释节点不可连线（纯标注）');
        }
      } else {
        // 可执行节点：成功/失败双分支——出边 ≤2；2 条必须 ''（成功）+ 'error'（失败）；1 条必须 ''
        var handles = outs.map(function (e) { return e.sourceHandle || ''; }).slice().sort();
        if (outs.length > 2) {
          errors.push(n.type + ' ' + n.id + ': 最多 2 条出边（成功/失败分支各一）');
        } else if (outs.length === 2 && handles.join(',') !== ',error') {
          errors.push(n.type + ' ' + n.id + ': 双分支出边必须 sourceHandle ""(成功) + error(失败)');
        } else if (outs.length === 1 && handles[0] === 'error') {
          errors.push(n.type + ' ' + n.id + ': 只有失败分支边（缺少成功边）');
        }
      }
    });

    // 无环（Kahn）——仅当无结构错误时判，避免连环报错
    if (!errors.length) {
      var indeg = {};
      nodes.forEach(function (n) { indeg[n.id] = (incoming[n.id] || []).length; });
      var q = nodes.filter(function (n) { return indeg[n.id] === 0; }).map(function (n) { return n.id; });
      var seen = 0;
      while (q.length) {
        var cur = q.shift();
        seen++;
        (outgoing[cur] || []).forEach(function (e) {
          indeg[e.target]--;
          if (!indeg[e.target]) q.push(e.target);
        });
      }
      if (seen !== nodes.length) errors.push('图中存在环（flow 仅支持 DAG）');
    }
    return errors;
  }

  // ── SVG 渲染（拓扑分层布局）───────────────────────────────────────────────

  function renderFlowGraph(schema, container) {
    container.innerHTML = '';
    var errors = validateFlowSchema(schema);
    if (errors.length || !schema || !schema.nodes.length) return errors;

    var nodes = schema.nodes;
    var edges = schema.edges || [];
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    var incoming = {};
    var outgoing = {};
    nodes.forEach(function (n) { incoming[n.id] = []; outgoing[n.id] = []; });
    edges.forEach(function (e) {
      if (byId[e.source] && byId[e.target]) {
        incoming[e.target].push(e);
        outgoing[e.source].push(e);
      }
    });

    // 拓扑序（Kahn）
    var indeg = {};
    nodes.forEach(function (n) { indeg[n.id] = (incoming[n.id] || []).length; });
    var q = nodes.filter(function (n) { return indeg[n.id] === 0; }).map(function (n) { return n.id; });
    var topo = [];
    while (q.length) {
      var cur = q.shift();
      topo.push(cur);
      (outgoing[cur] || []).forEach(function (e) {
        indeg[e.target]--;
        if (!indeg[e.target]) q.push(e.target);
      });
    }

    // 分层 = 最长路径深度（start 层 0 → end 最右）
    var layerOf = {};
    nodes.forEach(function (n) { layerOf[n.id] = 0; });
    topo.forEach(function (id) {
      (outgoing[id] || []).forEach(function (e) {
        layerOf[e.target] = Math.max(layerOf[e.target], layerOf[id] + 1);
      });
    });
    var maxLayer = 0;
    nodes.forEach(function (n) { maxLayer = Math.max(maxLayer, layerOf[n.id]); });
    var layers = [];
    for (var i = 0; i <= maxLayer; i++) {
      layers.push(nodes.filter(function (n) { return layerOf[n.id] === i; }));
    }

    var W = 150;
    var H = 48;
    var GX = 46;
    var GY = 36;
    var PAD = 24;
    var width = maxLayer * (W + GX) + W + PAD * 2;
    var height = Math.max.apply(null, layers.map(function (l) { return l.length; })) * (H + GY) + GY;
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.setAttribute('style', 'display:block;min-width:100%');

    // 箭头 defs
    var defs = document.createElementNS(ns, 'defs');
    var marker = document.createElementNS(ns, 'marker');
    marker.setAttribute('id', 'flow-arrow');
    marker.setAttribute('viewBox', '0 0 10 10');
    marker.setAttribute('refX', 9);
    marker.setAttribute('refY', 5);
    marker.setAttribute('markerWidth', 7);
    marker.setAttribute('markerHeight', 7);
    marker.setAttribute('orient', 'auto-start-reverse');
    var path = document.createElementNS(ns, 'path');
    path.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
    path.setAttribute('fill', '#94a3b8');
    marker.appendChild(path);
    defs.appendChild(marker);
    svg.appendChild(defs);

    function el(tag, attrs, text) {
      var node = document.createElementNS(ns, tag);
      Object.keys(attrs || {}).forEach(function (k) {
        if (k === 'class') node.setAttribute('class', attrs[k]);
        else node.setAttribute(k, attrs[k]);
      });
      if (text != null) node.textContent = text;
      return node;
    }

    var pos = {};
    layers.forEach(function (layer, li) {
      layer.forEach(function (n, ni) {
        var x = PAD + li * (W + GX);
        var y = PAD + ni * (H + GY);
        pos[n.id] = { x: x, y: y, w: W, h: H };
        var meta = NODE_META[n.type] || { color: '#6b7280', label: n.type };
        var g = el('g');
        var rect = el('rect', {
          x: x, y: y, width: W, height: H, rx: 10,
          fill: n.type === 'condition' ? '#fef3c7' : '#f8fafc',
          stroke: meta.color, 'stroke-width': 2,
        });
        var badge = el('rect', {
          x: x + 8, y: y + 8, width: 8, height: 8, rx: 2, fill: meta.color,
        });
        var idText = el('text', {
          x: x + 24, y: y + 21, 'font-size': 13, 'font-weight': 600, fill: '#0f172a',
        }, n.id);
        var typeText = el('text', {
          x: x + 24, y: y + 38, 'font-size': 11, fill: meta.color,
        }, meta.label);
        g.appendChild(rect);
        g.appendChild(badge);
        g.appendChild(idText);
        g.appendChild(typeText);
        svg.appendChild(g);
      });
    });

    // 边：从 source 右侧 → target 左侧；condition 边带 true/false 标签
    edges.forEach(function (e) {
      var s = pos[e.source];
      var t = pos[e.target];
      if (!s || !t) return;
      var x1 = s.x + s.w;
      var y1 = s.y + s.h / 2;
      var x2 = t.x;
      var y2 = t.y + t.h / 2;
      var midX = (x1 + x2) / 2;
      var d = 'M ' + x1 + ' ' + y1 + ' C ' + midX + ' ' + y1 + ', ' + midX + ' ' + y2 + ', ' + x2 + ' ' + y2;
      var line = el('path', {
        d: d, fill: 'none', stroke: '#94a3b8', 'stroke-width': 1.6,
        'marker-end': 'url(#flow-arrow)',
      });
      svg.appendChild(line);
      if (e.sourceHandle) {
        var isGood = (e.sourceHandle === 'true' || e.sourceHandle === 'success' || e.sourceHandle === '');
        var isCond = byId[e.source] && byId[e.source].type === 'condition';
        var labelText = isCond ? (e.sourceHandle === 'true' ? '✓ 是' : '✗ 否')
          : (e.sourceHandle === 'error' ? '✗ 失败' : '✓ 成功');
        var label = el('text', {
          x: midX + 4, y: (y1 + y2) / 2 - 4, 'font-size': 10,
          fill: isGood ? '#16a34a' : '#dc2626',
          'font-weight': 600,
        }, labelText);
        svg.appendChild(label);
      }
    });

    container.appendChild(svg);
    return [];
  }

  // ── 示例模板 ──────────────────────────────────────────────────────────────

  function flowExampleSchema(kind) {
    if (kind === 'full') {
      return {
        nodes: [
          { id: 'start', type: 'start', data: {} },
          { id: 'q1', type: 'qu', data: {} },
          { id: 'c1', type: 'capability', data: { capability_call: { capability_id: 'cap-demo-echo', input: { msg: '{{query}}' } } } },
          { id: 't1', type: 'tool', data: { connector_id: 'cn-xxx', params: { region: '{{query}}' } } },
          {
            id: 'cond1', type: 'condition',
            data: { condition: { left: 'c1.output.echo.msg', op: 'contains', right: '故障' } },
          },
          { id: 'h1', type: 'human_approval', data: { question: '确认处理？' } },
          { id: 'l1', type: 'llm', data: { prompt: '答复：{{#h1.output.reply#}}，总结：{{query}}' } },
          { id: 'l2', type: 'llm', data: { prompt: '设备正常：{{query}}' } },
          { id: 'end', type: 'end', data: {} },
        ],
        edges: [
          { source: 'start', target: 'q1' },
          { source: 'q1', target: 'c1' },
          { source: 'c1', target: 't1' },
          { source: 't1', target: 'cond1' },
          { source: 'cond1', target: 'h1', sourceHandle: 'true' },
          { source: 'cond1', target: 'l2', sourceHandle: 'false' },
          { source: 'h1', target: 'l1' },
          { source: 'l1', target: 'end' },
          { source: 'l2', target: 'end' },
        ],
      };
    }
    return {
      nodes: [
        { id: 'start', type: 'start', data: {} },
        { id: 'l1', type: 'llm', data: { prompt: '请回答用户问题：{{query}}' } },
        { id: 'end', type: 'end', data: {} },
      ],
      edges: [
        { source: 'start', target: 'l1' },
        { source: 'l1', target: 'end' },
      ],
    };
  }

  window.FlowGraph = {
    validate: validateFlowSchema,
    render: renderFlowGraph,
    example: flowExampleSchema,
    meta: NODE_META,
    esc: esc,
  };
})();
