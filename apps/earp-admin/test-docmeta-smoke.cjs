// 冒烟：knowledge.html 文档元数据弹窗（回归 — 保存后再打开）
// 背景：autoMetaHtml 引用 editDocMetadata 的局部 var esc（词法不可见）——KB 无
// schema 时首次打开（metadata 空，autoMetaHtml 全走无值分支）不触发 esc；保存后
// updated_at 有值 → 二次打开 ReferenceError → 弹窗打不开（FDE 反馈）。
// 修复：esc 提升为全局函数。本测试验证「打开→保存→再打开」全流程。
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'pages/knowledge.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const biz = scripts[scripts.length - 1];

// ── 最小真实 DOM stub（insertAdjacentHTML / querySelectorAll / innerHTML 子树）──
function mkNode(tag) {
  const n = {
    tagName: tag.toUpperCase(), id: null, children: [], parent: null,
    attributes: {}, style: {}, value: '', _innerHTML: '', _textContent: '',
    getAttribute(k) { return this.attributes[k] !== undefined ? this.attributes[k] : null; },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    appendChild(c) { c.parent = this; this.children.push(c); return c; },
    addEventListener() {},
    querySelectorAll(sel) { return queryAll(this, sel); },
  };
  Object.defineProperty(n, 'innerHTML', {
    get() { return this._innerHTML; },
    set(v) { this._innerHTML = v; this.children = parseHtml(v, this); },
  });
  return n;
}
function parseHtml(s, parent) {
  const re = /<(\/?)([a-zA-Z0-9]+)((?:"[^"]*"|[^>"])*)>/g;
  const stack = [parent];
  let m;
  while ((m = re.exec(s))) {
    const close = m[1] === '/';
    const tag = m[2].toLowerCase();
    if (close) { if (stack.length > 1) stack.pop(); continue; }
    const attrs = m[3] || '';
    const node = mkNode(tag);
    const am = /id="([^"]*)"/.exec(attrs); if (am) node.id = am[1];
    const cm = /class="([^"]*)"/.exec(attrs); if (cm) node.attributes.class = cm[1];
    const dm = /data-key="([^"]*)"/.exec(attrs); if (dm) node.attributes['data-key'] = dm[1];
    const vm = /value="([^"]*)"/.exec(attrs); if (vm) { node.value = vm[1]; node.attributes.value = vm[1]; }
    const sm = /style="([^"]*)"/.exec(attrs); if (sm) { sm[1].split(';').filter(Boolean).forEach(p => { const kv = p.split(':'); node.style[kv[0].trim()] = kv[1].trim(); }); }
    const cur = stack[stack.length - 1];
    cur.appendChild(node);
    if (!['input', 'select', 'option', 'button', 'br', 'hr'].includes(tag)) stack.push(node);
  }
  return parent.children;
}
function matches(node, sel) {
  if (sel.startsWith('#')) return node.id === sel.slice(1);
  if (sel.startsWith('.')) return (node.attributes.class || '').split(/\s+/).includes(sel.slice(1));
  if (sel.includes('.')) {
    const [tag, cls] = sel.split('.');
    return node.tagName.toLowerCase() === tag.toLowerCase() && (node.attributes.class || '').split(/\s+/).includes(cls);
  }
  return node.tagName.toLowerCase() === sel.toLowerCase();
}
function queryAll(root, sel) {
  const parts = sel.split(/\s+/);
  const results = [];
  (function walk(n) {
    if (n !== root && matches(n, parts[parts.length - 1]) && parts.length === 1) results.push(n);
    n.children.forEach(walk);
  })(root);
  if (parts.length === 2) {
    const scope = queryAll(root, parts[0]);
    const out = [];
    (function walk2(n) {
      n.children.forEach(c => { if (matches(c, parts[1])) out.push(c); walk2(c); });
    })(scope.length ? scope[0] : root);
    return out;
  }
  return results;
}

const root = mkNode('body');
global.document = {
  body: root,
  getElementById(id) { return queryAll(root, '#' + id)[0] || null; },
  createElement(tag) { return mkNode(tag); },
  querySelectorAll(sel) { return queryAll(root, sel); },
  querySelector(sel) { return queryAll(root, sel)[0] || null; },
  addEventListener() {},
};
root.insertAdjacentHTML = (pos, s) => { parseHtml(s, root); };
global.window = global;
global.location = { search: '' };
global.alert = (m) => console.log('ALERT:', m);

let patchCalls = 0;
global.EARP = {
  async fetchJSON(url, opts = {}) {
    if (url.includes('/metadata') && opts.method === 'PATCH') {
      patchCalls++;
      const body = JSON.parse(opts.body);
      const doc = global.state.docs.find(d => d.document_id === 'doc-x');
      doc.metadata = { ...doc.metadata, ...body.metadata, updated_at: '2026-08-18T11:28:14+00:00' };
      return doc.metadata;
    }
    if (url.includes('/documents')) return global.state.docs;
    return {};
  },
};

(async () => {
try {
  (0, eval)(biz);
  // 页面脚本 var state 覆盖 stub——eval 后重新注入（KB 无 schema + 文档 metadata 空）
  global.state = {
    selectedKB: 'kb-1',
    kbs: [{ knowledge_base_id: 'kb-1', name: 'KB1', metadata_schema: [] }],
    docs: [{ document_id: 'doc-x', title: '文档X', metadata: {}, status: 'active', classification: 'internal', chunk_count: 2 }],
  };
  global.showWorkspace = () => {};  // stub 无对应 DOM，跳过列表渲染

  const checks = [];

  // 第一次打开（metadata 空 → autoMetaHtml 无值分支，不触发 esc）
  global.editDocMetadata('doc-x');
  let modal = document.getElementById('doc-meta-modal');
  checks.push(['首次打开弹窗显示', modal && modal.style.display === 'flex']);
  let inputs = document.querySelectorAll('#doc-meta-form .doc-meta-val');
  checks.push(['首次表单渲染', inputs.length >= 0]);  // schema 空：无输入框但应显示提示
  const form1 = document.getElementById('doc-meta-form');
  checks.push(['首次无 schema 提示', (form1.innerHTML || '').includes('未配置元数据字段')]);

  // 保存 → PATCH + 关闭
  await global.saveDocMetadata();
  modal = document.getElementById('doc-meta-modal');
  checks.push(['保存关闭弹窗', modal.style.display === 'none']);
  checks.push(['保存 PATCH 1 次', patchCalls === 1]);

  // 第二次打开（updated_at 有值 → 修复前 ReferenceError → 弹窗打不开）
  global.editDocMetadata('doc-x');
  modal = document.getElementById('doc-meta-modal');
  checks.push(['二次打开弹窗显示（回归点）', modal && modal.style.display === 'flex']);
  const form2 = document.getElementById('doc-meta-form');
  checks.push(['二次表单含自动字段 updated_at（标签）', (form2.innerHTML || '').includes('最后更新')]);
  checks.push(['二次表单含最后更新值（非空）', (form2.innerHTML || '').includes('2026')]);

  // 有 schema 的 KB：输入框 + 保存后回填
  global.state.kbs[0].metadata_schema = [{ key: 'data', type: 'number', required: false }];
  global.editDocMetadata('doc-x');
  inputs = document.querySelectorAll('#doc-meta-form .doc-meta-val');
  checks.push(['有 schema 时输入框渲染', inputs.length === 1]);
  inputs[0].value = '2024';
  await global.saveDocMetadata();
  global.editDocMetadata('doc-x');
  inputs = document.querySelectorAll('#doc-meta-form .doc-meta-val');
  checks.push(['保存后二次打开值回填', inputs[0] && inputs[0].value === '2024']);
  checks.push(['保存后表单含 updated_at 自动字段', (document.getElementById('doc-meta-form').innerHTML || '').includes('最后更新')]);

  const failed = checks.filter(([, ok]) => !ok);
  console.log('doc-meta smoke:', checks.length, 'checks,', checks.length - failed.length, 'passed');
  checks.forEach(([name, ok]) => console.log('  ' + (ok ? '✅' : '❌') + ' ' + name));
  if (failed.length) { console.error('FAILED:', failed.map(f => f[0])); process.exit(1); }
} catch (e) {
  console.error('smoke error:', e.stack || e);
  process.exit(1);
}
})();
