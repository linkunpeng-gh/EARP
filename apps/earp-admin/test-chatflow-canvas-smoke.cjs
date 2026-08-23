// 冒烟：chatflow 独立后的画布编辑器核心（F5b/Dify 式）
// 验证：flow-graph.validate、chatflow-canvas 的 dataToFields/fieldsToData（各节点包裹结构）、
//       toFlowSchema（Drawflow export → flow_schema）、loadIntoDrawflow↔toFlowSchema roundtrip
const fs = require('fs');
const path = require('path');

// ── 加载 flow-graph.js + chatflow-canvas.js ────────────────────────────────
global.window = {};
const flowGraphSrc = fs.readFileSync(path.join(__dirname, 'js/flow-graph.js'), 'utf8');
const FlowGraph = new Function(flowGraphSrc + '; return window.FlowGraph;')();
global.FlowGraph = FlowGraph;
const canvasSrc = fs.readFileSync(path.join(__dirname, 'js/chatflow-canvas.js'), 'utf8');
const Canvas = new Function(canvasSrc + '; return window.ChatflowCanvas;')();

// ── DOM mock（ChatflowCanvas.renderPropsPanel 用 document）──────────────────
function mkEl() {
  return { children: [], innerHTML: '', value: '', selected: undefined, style: {}, appendChild(c) { this.children.push(c); return c; }, addEventListener() {}, setAttribute() {}, querySelectorAll() { return []; }, append(a) { this.children.push({}); } };
}
global.document = {
  createElement(tag) { const e = mkEl(); e.tagName = tag; return e; },
  querySelectorAll() { return []; },
  getElementById() { return mkEl(); },
};

// ── mock Drawflow（记录 addNode/connections）───────────────────────────────
function mkDrawflow() {
  const nodes = {};
  let nextId = 1;
  return {
    start() {}, reroute: false, reroute_fix_curvature: false,
    addNode(name, inputs, outputs, x, y, cls, data, html) {
      const id = nextId++;
      nodes[id] = { id: id, name: name, data: data, inputs: inputs, outputs: outputs, x: x, y: y, cls: cls, html: html };
      (nodes[id].outs = []);
      return id;
    },
    addConnection(from, to, out, inp) {
      if (nodes[from]) (nodes[from]._c = nodes[from]._c || []).push({ from, to, out, inp });
    },
    // 镜像 Drawflow 语义：getNodeFromId 返回深拷贝（克隆写不生效）
    getNodeFromId(id) { return JSON.parse(JSON.stringify(nodes[id])); },
    updateNodeDataFromId(id, t) { if (nodes[id]) nodes[id].data = t; },
    export() {
      const data = {};
      Object.keys(nodes).forEach(function (id) {
        const n = nodes[id];
        const outputs = {};
        for (let i = 1; i <= n.outputs; i++) {
          outputs['output_' + i] = { connections: (n._c || []).filter(c => c.from === n.id && c.out === 'output_' + i).map(c => ({ node: c.to, output: c.inp })) };
        }
        data[id] = { id: id, name: n.name, data: n.data, outputs: outputs };
      });
      return { drawflow: { Home: { data: data } } };
    },
    nodes,
  };
}

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error('✗ FAIL:', msg); process.exitCode = 1; } else { passed++; console.log('✓', msg); } }

// ── 1. dataToFields / fieldsToData 节点形状 ─────────────────────────────────
const capFields = Canvas.dataToFields('capability', { capability_call: { capability_id: 'cap-x', input: {} } });
assert(capFields.capability_id === 'cap-x', 'dataToFields capability 解包');
const capData = Canvas.fieldsToData('capability', { capability_id: 'cap-x' });
assert(capData.capability_call.capability_id === 'cap-x', 'fieldsToData capability 包裹');

const condFields = Canvas.dataToFields('condition', { condition: { left: 'a.output.x', op: '==', right: '1' } });
assert(condFields.op === '==', 'dataToFields condition 解包 op');
const condData = Canvas.fieldsToData('condition', { left: 'a.output.x', op: 'contains', right: '故障' });
assert(condData.condition.op === 'contains' && condData.condition.left === 'a.output.x', 'fieldsToData condition 包裹');

const toolData = Canvas.fieldsToData('tool', { connector_id: 'cn-1' });
assert(toolData.connector_id === 'cn-1', 'fieldsToData tool 包裹');

const llmData = Canvas.fieldsToData('llm', { prompt: 'hi' });
assert(llmData.prompt === 'hi', 'fieldsToData llm 普通字段');

// ── 2. toFlowSchema（Drawflow export → flow_schema）────────────────────────
const editor = mkDrawflow();
const idStart = editor.addNode('开始', 0, 1, 0, 0, 'c-start', { type: 'start', data: {} }, '');
const idLlm = editor.addNode('LLM', 1, 1, 0, 0, 'c-llm', { type: 'llm', data: { prompt: 'p' } }, '');
const idEnd = editor.addNode('结束', 1, 0, 0, 0, 'c-end', { type: 'end', data: {} }, '');
editor.addConnection(idStart, idLlm, 'output_1', 'input_1');
editor.addConnection(idLlm, idEnd, 'output_1', 'input_1');
const schema = Canvas.toFlowSchema(editor);
assert(schema.nodes.length === 3, 'toFlowSchema: 3 节点');
assert(schema.nodes[1].type === 'llm' && schema.nodes[1].data.prompt === 'p', 'toFlowSchema: llm data 保留');
assert(schema.edges.length === 2 && schema.edges[0].source === String(idStart) && schema.edges[0].target === String(idLlm), 'toFlowSchema: 边映射');

// condition 第二输出 → 源 export 需 output_2
const ed2 = mkDrawflow();
const cStart = ed2.addNode('开始', 0, 1, 0, 0, 'c-start', { type: 'start', data: {} }, '');
const cCond = ed2.addNode('条件', 1, 2, 0, 0, 'c-condition', { type: 'condition', data: { condition: { left: 'a', op: '==', right: 'b' } } }, '');
const cEnd = ed2.addNode('结束', 1, 0, 0, 0, 'c-end', { type: 'end', data: {} }, '');
ed2.addConnection(cCond, cEnd, 'output_2', 'input_1'); // ✗否分支
const schema2 = Canvas.toFlowSchema(ed2);
assert(schema2.edges[0].sourceHandle === 'false', 'toFlowSchema: condition 第二输出 sourceHandle 应为 false（对齐 flow_schema 规范）');

// ── 3. loadIntoDrawflow ↔ toFlowSchema roundtrip ───────────────────────────
const full = FlowGraph.example('full');
assert(FlowGraph.validate(full).length === 0, 'flow-graph: 全节点示例图校验合法');
const ed3 = mkDrawflow();
Canvas.loadIntoDrawflow(ed3, full);
const roundtrip = Canvas.toFlowSchema(ed3);
// 节点：start/end/llm/... 应全保留（同数量、同类型集合）
assert(roundtrip.nodes.length === full.nodes.length, 'roundtrip: 节点数一致 (' + roundtrip.nodes.length + '/' + full.nodes.length + ')');
const typeSetFull = full.nodes.map(n => n.type).sort().join(',');
const typeSetR = roundtrip.nodes.map(n => n.type).sort().join(',');
assert(typeSetFull === typeSetR, 'roundtrip: 节点类型一致');
assert(roundtrip.edges.length === full.edges.length, 'roundtrip: 边数一致');
assert(roundtrip.nodes.some(n => n.id === 'q1') && roundtrip.nodes.some(n => n.id === 'h1'), 'roundtrip: 语义引用名 id 保留（q1/h1）');
assert(FlowGraph.validate(roundtrip).length === 0, 'roundtrip: 往返后 flow_schema 仍校验合法（condition 手柄 true/false 保留）');

// ── 4. 编辑持久化契约：toFlowSchema 读内部存储 → 修改必须写内部（updateNodeDataFromId）──
const ed4 = mkDrawflow();
const idS4 = ed4.addNode('开始', 0, 1, 0, 0, 'c-start', { type: 'start', data: {} }, '');
const idL4 = ed4.addNode('LLM', 1, 1, 0, 0, 'c-llm', { type: 'llm', data: { prompt: '旧提示词' }, id: 'l1' }, '');
const idE4 = ed4.addNode('结束', 1, 0, 0, 0, 'c-end', { type: 'end', data: {} }, '');
ed4.addConnection(idS4, idL4, 'output_1', 'input_1');
ed4.addConnection(idL4, idE4, 'output_1', 'input_1');
const clone4 = ed4.getNodeFromId(idL4);  // 页面旧逻辑：改克隆
clone4.data.data = Canvas.fieldsToData('llm', { prompt: '克隆改', system: 'S', model_config_id: 'mc-x' });
const out4a = Canvas.toFlowSchema(ed4);
assert(out4a.nodes.find(n => n.id === 'l1').data.prompt === '旧提示词', '持久化契约: 改克隆不生效（getNodeFromId 深拷贝 → 必须写内部）');
ed4.updateNodeDataFromId(idL4, { type: 'llm', data: Canvas.fieldsToData('llm', { prompt: '新提示词', system: '你是助手', model_config_id: 'mc-x' }), id: 'l1' });
const out4b = Canvas.toFlowSchema(ed4);
const l4d = out4b.nodes.find(n => n.id === 'l1').data;
assert(l4d.prompt === '新提示词' && l4d.system === '你是助手' && l4d.model_config_id === 'mc-x', '持久化契约: updateNodeDataFromId 写内部 → 导出含编辑（prompt/system/model）');
assert(FlowGraph.validate(out4b).length === 0, '持久化契约: 编辑后图仍合法');


// ── 5. note（注释）节点：纯标注、不连线即可通过校验、不参与 roundtrip 执行 ──
const noteSchema = {
  nodes: [
    { id: 'start', type: 'start', data: {} },
    { id: 'nt1', type: 'note', data: { text: '此处需人工确认后通知负责人' } },
    { id: 'l1', type: 'llm', data: { prompt: 'p' } },
    { id: 'end', type: 'end', data: {} },
  ],
  edges: [{ source: 'start', target: 'l1' }, { source: 'l1', target: 'end' }],
};
assert(FlowGraph.validate(noteSchema).length === 0, 'note: 断开注释节点图校验合法（可达性豁免）');
const badNote = JSON.parse(JSON.stringify(noteSchema));
badNote.edges.push({ source: 'l1', target: 'nt1' });
assert(FlowGraph.validate(badNote).some(e => e.indexOf('注释节点不可连线') >= 0), 'note: 注释节点连线被拒');
const ed5 = mkDrawflow();
Canvas.loadIntoDrawflow(ed5, noteSchema);
const round5 = Canvas.toFlowSchema(ed5);
assert(round5.nodes.some(n => n.id === 'nt1' && n.type === 'note'), 'note: roundtrip 保留注释节点');
assert(FlowGraph.validate(round5).length === 0, 'note: roundtrip 后仍合法');

console.log('\n' + passed + ' 断言全部通过（chatflow 画布核心冒烟）');
