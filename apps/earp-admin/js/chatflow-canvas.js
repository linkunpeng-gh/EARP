/* EARP Chatflow 画布编辑器 — 节点定义 + flow_schema ↔ Drawflow 转换 + 属性面板。
 *
 * Dify 式三栏编辑器的逻辑核心（纯 vanilla，配合 drawflow.min.js）：
 * - NODE_DEFS：10 种节点（端口数 / 颜色 / 字段 / 画布摘要）——字段驱动右属性面板
 * - nodeHtml(type, data)：画布节点 DOM（内嵌轻量摘要）
 * - toFlowSchema(editor)：Drawflow export → EARP flow_schema（ReactFlow 兼容形状）
 * - loadIntoDrawflow(editor, schema)：flow_schema → 画布（拓扑分层自动布局）
 * - renderPropsPanel(node, data, onChange)：右属性面板（选中节点字段表单）
 * - hashId：校验 / 最短 schema（关联 flow-graph.js 的 validate）
 */

(function () {
  'use strict';

  // 节点定义：type → { name/color/inputs/outputs/fields/简要摘要函数 }
  var NODE_DEFS = {
    start: { name: '开始', color: '#16a34a', inputs: 0, outputs: 1, fields: [],
      brief: () => '流程起点' },
    end: { name: '结束', color: '#64748b', inputs: 1, outputs: 0, fields: [],
      brief: () => '流程终点' },
    llm: { name: 'LLM', color: '#7c3aed', inputs: 1, outputs: 1,
      fields: [
        { key: 'prompt', label: '提示词（User）', type: 'textarea', default: '请回答：{{query}}' },
        { key: 'system', label: '系统提示词（角色/规则）', type: 'textarea', default: '' },
        { key: 'model_config_id', label: '模型', type: 'model-select', default: '' },
      ],
      brief: (d) => '生成回复' },
    knowledge: { name: '知识检索', color: '#2563eb', inputs: 1, outputs: 1,
      fields: [
        { key: 'query', label: '检索词', type: 'text', default: '{{query}}' },
        { key: 'top_k', label: 'TopK', type: 'number', default: 5 },
      ],
      brief: () => '知识库检索' },
    qu: { name: 'QU 理解', color: '#ea580c', inputs: 1, outputs: 1,
      fields: [
        { key: 'query', label: '理解问题', type: 'text', default: '{{query}}' },
        { key: 'use_llm', label: '启用 LLM 升级（低置信时智能补全）', type: 'checkbox', default: true },
      ],
      brief: (d) => '自动理解→检索' },
    capability: { name: '能力调用', color: '#dc2626', inputs: 1, outputs: 1,
      fields: [{ key: 'capability_id', label: '能力 ID', type: 'text', default: '' }],
      brief: (d) => '能力: ' + (d.capability_id || '未选') },
    tool: { name: '工具取数', color: '#0891b2', inputs: 1, outputs: 1,
      fields: [{ key: 'connector_id', label: '连接 ID', type: 'text', default: '' }],
      brief: (d) => '取数: ' + (d.connector_id || '未选') },
    chat_history: { name: '历史', color: '#475569', inputs: 1, outputs: 1,
      fields: [{ key: 'turns', label: '轮数', type: 'number', default: 6 }],
      brief: () => '最近对话' },
    condition: { name: '条件', color: '#ca8a04', inputs: 1, outputs: 2,
      fields: [
        { key: 'left', label: '左值（节点输出）', type: 'text', default: '' },
        { key: 'op', label: '操作符', type: 'select',
          options: ['==', '!=', '>', '>=', '<', '<=', 'contains', 'exists'] },
        { key: 'right', label: '右值', type: 'text', default: '' },
      ],
      brief: (d) => d.left + ' ' + (d.op || '==') + ' ' + d.right },
    human_approval: { name: '人工确认', color: '#db2777', inputs: 1, outputs: 1,
      fields: [{ key: 'question', label: '确认问题', type: 'text', default: '请确认是否继续' }],
      brief: (d) => '⏸ ' + (d.question || '人工确认') },
    note: { name: '注释', color: '#94a3b8', inputs: 0, outputs: 0,
      fields: [{ key: 'text', label: '注释内容', type: 'textarea', default: '' }],
      brief: (d) => d.text || '（空注释）' },
  };

  // ── 字段 ↔ flow_schema 的 data 映射 ────────────────────────────────────────
  // 普通节点 data 直接是字段键值；特殊节点有包裹结构（对齐 F1 定稿 schema 形状）
  function dataToFields(type, data) {
    if (type === 'capability') {
      var cc = (data && data.capability_call) || {};
      return { capability_id: cc.capability_id || '' };
    }
    if (type === 'tool') {
      return { connector_id: (data && data.connector_id) || '' };
    }
    if (type === 'condition') {
      var cond = (data && data.condition) || {};
      return { left: cond.left || '', op: cond.op || '==', right: cond.right != null ? String(cond.right) : '' };
    }
    var out = {};
    (NODE_DEFS[type] || { fields: [] }).fields.forEach(function (f) {
      var v = data && data[f.key];
      out[f.key] = v != null ? v : f.default;
    });
    return out;
  }

  function fieldsToData(type, fields) {
    if (type === 'capability') {
      return { capability_call: { capability_id: fields.capability_id || '', input: {} } };
    }
    if (type === 'tool') {
      return { connector_id: fields.connector_id || '', params: {} };
    }
    if (type === 'condition') {
      return { condition: { left: fields.left || '', op: fields.op || '==', right: fields.right || '' } };
    }
    var data = {};
    (NODE_DEFS[type] || { fields: [] }).fields.forEach(function (f) {
      var v = fields[f.key];
      data[f.key] = v == null || v === '' ? undefined : (f.type === 'number' ? Number(v) : v);
    });
    return data;
  }

  // ── 节点引用名（id）生成 ────────────────────────────────────────────────
  // 节点 id = 稳定语义引用名（如 qu1 / h1 / llm1），显示在节点上，并作为 flow_schema
  // 节点 id 供 `{{#id.output#}}` 跨节点取数与 edge 引用。
  var _usedIds = {};
  var _typeCounts = {};
  function resetIds() { _usedIds = {}; _typeCounts = {}; }
  function registerId(id) { if (id) _usedIds[id] = true; }
  function nextId(type) {
    _typeCounts[type] = (_typeCounts[type] || 0) + 1;
    var cand = type + _typeCounts[type];
    while (_usedIds[cand]) { _typeCounts[type]++; cand = type + _typeCounts[type]; }
    _usedIds[cand] = true;
    return cand;
  }

  // 画布节点 DOM（内嵌：引用名徽标 + 摘要；完整字段在右属性面板）
  function nodeHtml(type, data, id) {
    var d = NODE_DEFS[type] || { name: type, color: '#6b7280', brief: () => type };
    var dataFields = dataToFields(type, data);
    return '<div class="cf-node c-' + type + '" style="border-top:3px solid ' + d.color + '">'
      + (id ? '<div class="cf-node-id">' + esc(id) + '</div>' : '')
      + '<div class="cf-node-name">' + d.name + '</div>'
      + '<div class="cf-node-brief">' + esc(d.brief(dataFields)) + '</div>'
      + '</div>';
  }

  // ── Drawflow export → EARP flow_schema ────────────────────────────────────
  function toFlowSchema(editor) {
    var ex = editor.export();
    var data = (ex.drawflow && ex.drawflow.Home && ex.drawflow.Home.data) || {};
    var ids = Object.keys(data);
    // Drawflow 数字 id → 语义引用名 id（node.data.id 优先，缺省回退数字 id）
    var idMap = {};
    var nodes = ids.map(function (id) {
      var n = data[id];
      var type = (n.data && n.data.type) || 'unknown';
      var fields = dataToFields(type, n.data && n.data.data);
      var fid = (n.data && n.data.id) ? String(n.data.id) : String(n.id);
      idMap[String(n.id)] = fid;
      // 画布位置持久化（ReactFlow 兼容 position{x,y}）——Drawflow export 提供 pos_x/pos_y
      var pos = (typeof n.pos_x === 'number' && typeof n.pos_y === 'number')
        ? { x: n.pos_x, y: n.pos_y } : undefined;
      return { id: fid, type: type, data: fieldsToData(type, fields), position: pos };
    });
    var edges = [];
    ids.forEach(function (id) {
      var n = data[id];
      var type = (n.data && n.data.type) || 'unknown';
      var outCount = (NODE_DEFS[type] || { outputs: 1 }).outputs;
      Object.keys(n.outputs || {}).forEach(function (outIdx) {
        (n.outputs[outIdx].connections || []).forEach(function (c) {
          // 手柄对齐 flow_schema 规范：2 输出源（condition）output_1→true / output_2→false；
          // 1 输出节点源不留手柄（空串），校验/roundtrip 与 flow-graph.js 一致。
          var sh = '';
          if (outCount === 2) { sh = (outIdx === 'output_2') ? 'false' : 'true'; }
          edges.push({ source: idMap[String(n.id)], target: idMap[String(c.node)], sourceHandle: sh, targetHandle: String(c.output) });
        });
      });
    });
    return { nodes: nodes, edges: edges };
  }

  // ── flow_schema → Drawflow（拓扑分层自动布局）──────────────────────────────
  function loadIntoDrawflow(editor, schema) {
    var nodes = (schema && schema.nodes) || [];
    var edges = (schema && schema.edges) || [];
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });

    // 拓扑分层（最长路径）：start 层 0 → end 最右
    var incoming = {}, outgoing = {};
    nodes.forEach(function (n) { incoming[n.id] = []; outgoing[n.id] = []; });
    edges.forEach(function (e) {
      if (byId[e.source] && byId[e.target]) { incoming[e.target].push(e); outgoing[e.source].push(e); }
    });
    var indeg = {};
    nodes.forEach(function (n) { indeg[n.id] = (incoming[n.id] || []).length; });
    var q = nodes.filter(function (n) { return indeg[n.id] === 0; }).map(function (n) { return n.id; });
    var topo = [];
    while (q.length) { var cur = q.shift(); topo.push(cur); (outgoing[cur] || []).forEach(function (e) { indeg[e.target]--; if (!indeg[e.target]) q.push(e.target); }); }
    var layerOf = {};
    nodes.forEach(function (n) { layerOf[n.id] = 0; });
    topo.forEach(function (id) { (outgoing[id] || []).forEach(function (e) { layerOf[e.target] = Math.max(layerOf[e.target], layerOf[id] + 1); }); });
    // 每层节点纵排（行号 = 在层内数组的下标）
    var per = {};
    nodes.forEach(function (n) { (per[layerOf[n.id]] = per[layerOf[n.id]] || []).push(n.id); });
    var rowOf = {};
    Object.keys(per).forEach(function (L) {
      per[L].forEach(function (id, i) { rowOf[id] = i; });
    });

    var map = {};
    nodes.forEach(function (n) {
      var def = NODE_DEFS[n.type] || { name: n.type, inputs: 1, outputs: 1 };
      registerId(n.id);
      // 位置：优先用保存的 position{x,y}（重开不漂移），缺省回退拓扑分层自动布局
      var px = layerOf[n.id] * 250 + 40, py = rowOf[n.id] * 130 + 60;
      if (n.position && typeof n.position.x === 'number' && typeof n.position.y === 'number') {
        px = n.position.x; py = n.position.y;
      }
      var did = editor.addNode(def.name, def.inputs, def.outputs,
        px, py, 'c-' + n.type, { type: n.type, data: n.data, id: n.id }, nodeHtml(n.type, n.data, n.id));
      map[n.id] = did;
    });
    // 连接：condition 用 output_2 映射 true，否则 output_1
    edges.forEach(function (e) {
      var srcDef = NODE_DEFS[byId[e.source].type] || { outputs: 1 };
      var outIdx = 'output_1';
      if (srcDef.outputs === 2) { outIdx = (e.sourceHandle === 'false') ? 'output_2' : 'output_1'; }
      try { editor.addConnection(map[e.source], map[e.target], outIdx, 'input_1'); } catch (err) { /* 防重复/非法边 */ }
    });
    return map;
  }

  function rowCount(l) { return 1; }

  // 属性面板：渲染选中节点字段表单
  function renderPropsPanel(container, type, data, onChange) {
    container.innerHTML = '';
    var def = NODE_DEFS[type] || { fields: [] };
    var fields = dataToFields(type, data);
    var hint = '';
    if (type === 'capability') hint = '能力 ID 来自「能力中心」注册表';
    if (type === 'tool') hint = '连接 ID 来自「中台对接」连接器';
    if (type === 'llm') hint = '模型默认用应用配置；选择后该节点用所选模型执行（模型配置中心）';
    container.appendChild(el('div', { class: 'cf-panel-label' }, def.name + ' 配置'));
    if (hint) container.appendChild(el('div', { class: 'cf-panel-hint' }, hint));
    def.fields.forEach(function (f) {
      var label = el('label', { class: 'cf-panel-field' });
      label.appendChild(el('span', { class: 'cf-panel-k' }, f.label));
      var input;
      if (f.type === 'textarea') {
        input = el('textarea', { rows: 4, 'data-key': f.key });
        input.value = fields[f.key] != null ? fields[f.key] : '';
      } else if (f.type === 'checkbox') {
        input = el('input', { type: 'checkbox', 'data-key': f.key });
        input.checked = fields[f.key] !== false;  // 缺省启用
      } else if (f.type === 'model-select') {
        // 模型选择：选项来自模型配置中心（window.EARP_MODELS，页面加载时拉取）
        input = el('select', { 'data-key': f.key });
        var modelOpts = [{ value: '', label: '默认（应用配置）' }];
        (window.EARP_MODELS || []).forEach(function (m) {
          modelOpts.push({ value: m.config_id, label: m.model_name + '（' + m.provider + '）' });
        });
        modelOpts.forEach(function (o) {
          var opt = el('option', { value: o.value }, o.label);
          if (String(fields[f.key]) === String(o.value)) opt.selected = true;
          input.appendChild(opt);
        });
      } else if (f.type === 'select') {
        input = el('select', { 'data-key': f.key });
        f.options.forEach(function (o) {
          var opt = el('option', { value: o }, o);
          if (String(fields[f.key]) === String(o)) opt.selected = true;
          input.appendChild(opt);
        });
      } else if (f.type === 'number') {
        input = el('input', { type: 'number', 'data-key': f.key });
        input.value = fields[f.key] != null ? fields[f.key] : '';
      } else {
        input = el('input', { type: 'text', 'data-key': f.key });
        input.value = fields[f.key] != null ? fields[f.key] : '';
      }
      label.appendChild(input);
      container.appendChild(label);
    });
    // 输入变化 → 即时写回画布节点 data + 摘要（checkbox 读 .checked，其余读 .value）
    container.querySelectorAll('[data-key]').forEach(function (input) {
      var events = input.type === 'checkbox' ? ['change', 'input'] : ['input'];
      events.forEach(function (en) {
        input.addEventListener(en, function () {
          var fields2 = {};
          container.querySelectorAll('[data-key]').forEach(function (inp2) {
            fields2[inp2.getAttribute('data-key')] = inp2.type === 'checkbox' ? inp2.checked : inp2.value;
          });
          onChange(fields2);
        });
      });
    });
  }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text != null) node.textContent = text;
    return node;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  window.ChatflowCanvas = {
    NODE_DEFS: NODE_DEFS,
    nodeHtml: nodeHtml,
    toFlowSchema: toFlowSchema,
    loadIntoDrawflow: loadIntoDrawflow,
    renderPropsPanel: renderPropsPanel,
    dataToFields: dataToFields,
    fieldsToData: fieldsToData,
    nextId: nextId,
    resetIds: resetIds,
    esc: esc,
  };
})();
