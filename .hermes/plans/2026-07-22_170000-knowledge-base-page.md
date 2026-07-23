# Knowledge Base 页面实施计划

> **For Hermes:** 按任务顺序执行，Phase 1 用模拟数据验证交互。

**Goal:** 重写 Knowledge Base 主页面为主从布局 + 新建 Test Retrieval 独立子页。

**Architecture:** 纯静态 HTML/CSS/JS。主页面用 CSS grid 两栏布局，KB CRUD + 文档管理用模拟数据。Test Retrieval 为独立页面带 scope 参数。

**Tech Stack:** HTML + CSS (admin.css) + vanilla JS

---

## 受影响文件

| 文件 | 变更 |
|---|---|
| `apps/earp-admin/pages/knowledge.html` | 完全重写（主从布局） |
| `apps/earp-admin/pages/test-retrieval.html` | 新建 |
| `apps/earp-admin/css/admin.css` | 新增 KB 布局样式 |

---

### Task 1: CSS — KB 主从布局样式

**Files:**
- Modify: `apps/earp-admin/css/admin.css`（末尾追加）

```css
/* ── Knowledge Base: Master-detail layout ── */
.kb-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 1.5rem;
  align-items: start;
}
@media (max-width: 768px) {
  .kb-layout { grid-template-columns: 1fr; }
}

/* ── KB List Panel ── */
.kb-list-panel {
  background: var(--bg-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 1rem;
  box-shadow: var(--shadow-card);
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  position: sticky;
  top: 72px;
}
.kb-list-panel h3 {
  font-size: 0.81rem; font-weight: 600; color: var(--text-tertiary);
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-bottom: 0.5rem;
}
.kb-list-filter {
  margin-bottom: 0.75rem;
}
.kb-list-filter select {
  width: 100%; font-size: 0.75rem; padding: 0.3rem 0.5rem;
}
.kb-list-item {
  display: flex; align-items: center; gap: 0.4rem;
  padding: 0.45rem 0.5rem; border-radius: var(--radius-md);
  cursor: pointer; margin-bottom: 0.2rem;
  transition: background 0.1s; border: 1px solid transparent;
  font-size: 0.81rem;
}
.kb-list-item:hover { background: var(--bg-surface); }
.kb-list-item.active {
  background: var(--accent-light); border-color: var(--accent);
}
.kb-list-item .kb-name {
  flex: 1; font-weight: 500; color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace; font-size: 0.78rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.kb-list-item .kb-count {
  font-size: 0.69rem; color: var(--text-quaternary); flex-shrink: 0;
}
.kb-list-item .kb-actions {
  display: none; gap: 2px; flex-shrink: 0;
}
.kb-list-item:hover .kb-actions { display: flex; }
.kb-list-item .kb-act-btn {
  background: none; border: none; cursor: pointer; padding: 2px 4px;
  font-size: 0.75rem; color: var(--text-quaternary); border-radius: 3px;
}
.kb-list-item .kb-act-btn:hover { color: var(--text-primary); background: var(--bg-surface); }
.kb-list-item .kb-act-btn.del:hover { color: var(--red); }
.kb-list-new {
  display: block; width: 100%; margin-top: 0.5rem; padding: 0.35rem;
  font-size: 0.75rem; text-align: center;
  border: 1px dashed var(--border-standard); border-radius: var(--radius-md);
  background: transparent; color: var(--text-tertiary); cursor: pointer;
}
.kb-list-new:hover { border-color: var(--accent); color: var(--accent); }

/* ── KB Workspace ── */
.kb-info-bar {
  display: flex; flex-wrap: wrap; gap: 0.75rem 1.5rem; align-items: center;
  padding: 0.6rem 0.9rem; margin-bottom: 1rem;
  background: var(--bg-panel); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md); font-size: 0.81rem;
}
.kb-info-bar .kb-info-name { font-weight: 600; color: var(--text-primary); }
.kb-info-bar .kb-info-meta { font-size: 0.75rem; color: var(--text-tertiary); }
.upload-bar {
  display: flex; gap: 6px; align-items: flex-end; margin-bottom: 1rem;
  padding: 0.75rem; background: var(--bg-surface);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
  flex-wrap: wrap;
}
.upload-bar input, .upload-bar textarea, .upload-bar select {
  font-size: 0.81rem;
}
.upload-bar textarea { resize: vertical; min-height: 44px; }

/* ── Modal (reuse from existing, ensure consistent) ── */
.modal-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.4); z-index: 100;
  display: flex; align-items: center; justify-content: center;
}
.modal {
  background: var(--bg-panel); border-radius: 10px; padding: 1.5rem;
  min-width: 460px; max-width: 560px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.15);
  max-height: 90vh; overflow-y: auto;
}
.modal h4 { margin: 0 0 1rem; font-size: 0.94rem; }
.form-row {
  display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem;
}
.form-row label {
  min-width: 100px; font-size: 0.81rem; font-weight: 500;
  color: var(--text-secondary);
}
.form-row input, .form-row select, .form-row textarea {
  flex: 1;
}
.form-section {
  border: 1px solid var(--border-subtle); border-radius: 6px;
  padding: 0.75rem; margin-bottom: 0.75rem;
  background: var(--bg-surface);
}
.form-section-title {
  font-size: 0.75rem; font-weight: 600; color: var(--text-tertiary);
  text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.5rem;
}
.form-actions {
  display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem;
}

/* ── Empty state ── */
.kb-empty {
  text-align: center; padding: 3rem 1rem;
  color: var(--text-quaternary); font-size: 0.81rem;
}
```

---

### Task 2: knowledge.html — HTML 结构重写

**Files:**
- Modify: `apps/earp-admin/pages/knowledge.html`

**HTML 结构**（保留 `<head>` + `<header>` 导航不变）：

```html
<main>

<div class="kb-layout">

  <!-- Left: KB List -->
  <aside class="kb-list-panel">
    <h3>Knowledge Bases</h3>
    <div class="kb-list-filter">
      <select id="dd-filter" onchange="renderKBList()">
        <option value="">All Data Domains</option>
        <option value="equipment_data">Equipment Data</option>
        <option value="hr_data">HR Policies</option>
        <option value="corporate_data">Corporate Standards</option>
      </select>
    </div>
    <div id="kb-list"></div>
    <button class="kb-list-new" onclick="showKBModal()">+ New KB</button>
  </aside>

  <!-- Right: Workspace -->
  <div id="kb-workspace">
    <p class="kb-empty" id="kb-empty">Select a Knowledge Base from the left panel.</p>
    <div id="kb-workspace-content" style="display:none">

      <!-- KB info bar -->
      <div class="kb-info-bar" id="kb-info-bar">
        <span class="kb-info-name" id="kb-info-name">—</span>
        <span class="kb-info-meta" id="kb-info-meta">—</span>
      </div>

      <!-- Upload bar -->
      <div class="upload-bar">
        <input id="upload-title" placeholder="Document title" style="flex:2">
        <select id="upload-class" style="width:auto">
          <option value="internal">internal</option>
          <option value="confidential">confidential</option>
          <option value="restricted">restricted</option>
        </select>
        <textarea id="upload-content" placeholder="Document content" rows="2" style="flex:3"></textarea>
        <button class="primary" onclick="uploadDoc()">Upload</button>
      </div>

      <!-- Doc table -->
      <table id="doc-table">
        <thead><tr><th>Doc ID</th><th>Title</th><th>Classification</th><th>Chunks</th><th>Status</th><th></th></tr></thead>
        <tbody id="doc-tbody"></tbody>
      </table>

      <!-- Test Retrieval link -->
      <div style="margin-top:1rem">
        <button class="secondary" onclick="goTestRetrieval()">Test Retrieval →</button>
      </div>

    </div>
  </div>
</div>

</main>
```

---

### Task 3: knowledge.html — JS 模拟数据 + CRUD 逻辑

```html
<script src="../js/app.js"></script>
<script>
// ── Demo data ──
var kbData = {
  'kb-eq-manuals': {
    name: 'Equipment Manuals', dd: 'equipment_data',
    chunk_size: 1000, overlap: 200, model: 'bge-m3',
    mode: 'vector', top_k: 5, threshold: 0.0, index: 'high_quality',
    docs: [
      {id:'doc-001',title:'CNC Operation Manual v3',cls:'internal',chunks:24,status:'indexed'},
      {id:'doc-002',title:'Maintenance Schedule 2026',cls:'internal',chunks:15,status:'indexed'},
      {id:'doc-003',title:'Safety Guidelines',cls:'confidential',chunks:8,status:'indexed'},
    ]
  },
  'kb-eq-alarms': {
    name: 'Alarm Thresholds', dd: 'equipment_data',
    chunk_size: 1000, overlap: 200, model: 'bge-m3',
    mode: 'hybrid', top_k: 10, threshold: 0.0, index: 'high_quality',
    docs: [
      {id:'doc-004',title:'Temperature Threshold Guide',cls:'internal',chunks:12,status:'indexed'},
      {id:'doc-005',title:'Pressure Alarm Settings',cls:'internal',chunks:10,status:'indexed'},
    ]
  },
  'kb-hr-policies': {
    name: 'Company Policies', dd: 'hr_data',
    chunk_size: 1500, overlap: 300, model: 'text-embedding-3-small',
    mode: 'vector', top_k: 5, threshold: 0.0, index: 'high_quality',
    docs: [
      {id:'doc-006',title:'Leave Policy 2026',cls:'internal',chunks:18,status:'indexed'},
      {id:'doc-007',title:'Employee Handbook',cls:'confidential',chunks:42,status:'indexed'},
    ]
  },
};

var state = {
  selectedKB: null,
};

// ── Init ──
document.addEventListener('DOMContentLoaded', function() {
  renderKBList();
});

// ── KB List ──
function renderKBList() {
  var dd = document.getElementById('dd-filter').value;
  var list = document.getElementById('kb-list');
  var items = [];
  for (var id in kbData) {
    var kb = kbData[id];
    if (dd && kb.dd !== dd) continue;
    items.push({id: id, kb: kb});
  }
  if (items.length === 0) {
    list.innerHTML = '<p style="font-size:0.75rem;color:var(--text-quaternary);padding:0.5rem">No KB found.</p>';
    return;
  }
  list.innerHTML = items.map(function(item) {
    var active = state.selectedKB === item.id ? ' active' : '';
    var docCount = item.kb.docs.length;
    return '<div class="kb-list-item' + active + '" onclick="selectKB(\'' + item.id + '\')">'
      + '<span class="kb-name">' + item.id + '</span>'
      + '<span class="kb-count">' + docCount + ' docs</span>'
      + '<span class="kb-actions">'
        + '<button class="kb-act-btn" onclick="event.stopPropagation();editKB(\'' + item.id + '\')" title="Config">⚙️</button>'
        + '<button class="kb-act-btn del" onclick="event.stopPropagation();deleteKB(\'' + item.id + '\')" title="Delete">🗑</button>'
      + '</span>'
      + '</div>';
  }).join('');
}

function selectKB(id) {
  state.selectedKB = id;
  renderKBList();
  showWorkspace(id);
}

function showWorkspace(id) {
  var kb = kbData[id];
  if (!kb) {
    document.getElementById('kb-empty').style.display = 'block';
    document.getElementById('kb-workspace-content').style.display = 'none';
    return;
  }
  document.getElementById('kb-empty').style.display = 'none';
  document.getElementById('kb-workspace-content').style.display = '';

  document.getElementById('kb-info-name').textContent = kb.name;
  var totalChunks = kb.docs.reduce(function(s,d){return s+d.chunks;},0);
  document.getElementById('kb-info-meta').innerHTML =
    '<span class="tag tag-accent">' + kb.dd + '</span> · '
    + kb.docs.length + ' docs · ' + totalChunks + ' chunks';

  renderDocTable(kb);
}

function renderDocTable(kb) {
  var tbody = document.getElementById('doc-tbody');
  if (kb.docs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-quaternary);padding:2rem">No documents yet. Upload one above.</td></tr>';
    return;
  }
  tbody.innerHTML = kb.docs.map(function(d) {
    var clsOpts = ['public','internal','confidential','restricted'].map(function(c){
      return '<option value="' + c + '"' + (d.cls===c?' selected':'') + '>' + c + '</option>';
    }).join('');
    return '<tr>'
      + '<td><code>' + d.id + '</code></td>'
      + '<td>' + d.title + '</td>'
      + '<td><select class="cls-editor" onchange="changeCls(this,\'' + d.id + '\')">' + clsOpts + '</select></td>'
      + '<td>' + d.chunks + '</td>'
      + '<td>' + (d.status==='indexed'?'✅ indexed':'⏳ processing') + '</td>'
      + '<td>'
        + '<a href="doc-config.html?doc=' + d.id + '" class="btn-sm" title="Chunk config" style="text-decoration:none">⚙️</a>'
      + '</td>'
      + '</tr>';
  }).join('');
}

// ── KB CRUD ──
function showKBModal(editId) {
  var modal = document.getElementById('kb-modal');
  var title = document.getElementById('kb-modal-title');
  if (!modal) {
    // Create modal dynamically
    createKBModal();
    modal = document.getElementById('kb-modal');
    title = document.getElementById('kb-modal-title');
  }
  if (editId) {
    title.textContent = 'Edit KB: ' + kbData[editId].name;
    document.getElementById('kb-modal-id').value = editId;
    var kb = kbData[editId];
    document.getElementById('kb-name').value = kb.name;
    document.getElementById('kb-dd').value = kb.dd;
    document.getElementById('kb-chunk-size').value = kb.chunk_size;
    document.getElementById('kb-overlap').value = kb.overlap;
    document.getElementById('kb-model').value = kb.model;
    document.getElementById('kb-mode').value = kb.mode;
    document.getElementById('kb-topk').value = kb.top_k;
    document.getElementById('kb-threshold').value = kb.threshold;
    document.getElementById('kb-index').value = kb.index;
  } else {
    title.textContent = 'Create Knowledge Base';
    document.getElementById('kb-modal-id').value = '';
    document.getElementById('kb-name').value = '';
    document.getElementById('kb-dd').value = '';
    document.getElementById('kb-chunk-size').value = '1000';
    document.getElementById('kb-overlap').value = '200';
    document.getElementById('kb-model').value = 'bge-m3';
    document.getElementById('kb-mode').value = 'vector';
    document.getElementById('kb-topk').value = '5';
    document.getElementById('kb-threshold').value = '0.0';
    document.getElementById('kb-index').value = 'high_quality';
  }
  modal.style.display = 'flex';
}

function hideKBModal() {
  document.getElementById('kb-modal').style.display = 'none';
}

function saveKB() {
  var name = document.getElementById('kb-name').value.trim();
  if (!name) { alert('Name required'); return; }
  var editId = document.getElementById('kb-modal-id').value;
  var kb = {
    name: name,
    dd: document.getElementById('kb-dd').value,
    chunk_size: parseInt(document.getElementById('kb-chunk-size').value),
    overlap: parseInt(document.getElementById('kb-overlap').value),
    model: document.getElementById('kb-model').value,
    mode: document.getElementById('kb-mode').value,
    top_k: parseInt(document.getElementById('kb-topk').value),
    threshold: parseFloat(document.getElementById('kb-threshold').value),
    index: document.getElementById('kb-index').value,
    docs: editId ? (kbData[editId] ? kbData[editId].docs : []) : [],
  };
  var id = editId || ('kb-' + name.toLowerCase().replace(/[^a-z0-9]+/g,'-').substring(0,20));
  kbData[id] = kb;
  if (!editId) state.selectedKB = id;
  hideKBModal();
  renderKBList();
  showWorkspace(state.selectedKB);
}

function editKB(id) { showKBModal(id); }

function deleteKB(id) {
  if (!confirm('Delete KB "' + kbData[id].name + '" and all its documents? This cannot be undone.')) return;
  delete kbData[id];
  if (state.selectedKB === id) state.selectedKB = null;
  renderKBList();
  showWorkspace(null);
}

function createKBModal() {
  var html = '<div id="kb-modal" class="modal-overlay" style="display:none" onclick="if(event.target===this)hideKBModal()">'
    + '<div class="modal">'
    + '<h4 id="kb-modal-title">Create Knowledge Base</h4>'
    + '<input type="hidden" id="kb-modal-id">'
    + '<div class="form-row"><label>Name</label><input id="kb-name" placeholder="KB name"></div>'
    + '<div class="form-row"><label>Data Domain</label><select id="kb-dd"><option value="">Select...</option><option value="equipment_data">Equipment Data</option><option value="hr_data">HR Policies</option><option value="corporate_data">Corporate Standards</option></select></div>'
    + '<div class="form-section"><div class="form-section-title">Chunking</div>'
    + '<div class="form-row"><label>Chunk Size</label><select id="kb-chunk-size"><option value="500">500</option><option value="1000" selected>1000</option><option value="1500">1500</option><option value="2000">2000</option></select><span style="font-size:0.75rem;color:var(--text-tertiary)">chars</span></div>'
    + '<div class="form-row"><label>Overlap</label><select id="kb-overlap"><option value="100">100</option><option value="200" selected>200</option><option value="300">300</option></select><span style="font-size:0.75rem;color:var(--text-tertiary)">chars</span></div>'
    + '<div class="form-row"><label>Model</label><select id="kb-model"><option value="bge-m3" selected>bge-m3 (1024d)</option><option value="text-embedding-3-small">OpenAI text-embedding-3 (1536d)</option></select></div>'
    + '</div>'
    + '<div class="form-section"><div class="form-section-title">Retrieval Defaults</div>'
    + '<div class="form-row"><label>Mode</label><select id="kb-mode"><option value="vector" selected>Vector Search</option><option value="hybrid">Hybrid</option></select></div>'
    + '<div class="form-row"><label>Top-K</label><select id="kb-topk"><option value="3">3</option><option value="5" selected>5</option><option value="10">10</option><option value="20">20</option></select></div>'
    + '<div class="form-row"><label>Threshold</label><input id="kb-threshold" type="number" min="0" max="1" step="0.05" value="0.0" style="width:80px"><span style="font-size:0.75rem;color:var(--text-tertiary)">0.0 = no filter</span></div>'
    + '<div class="form-row"><label>Index</label><select id="kb-index"><option value="high_quality" selected>High Quality</option><option value="economy">Economy</option></select></div>'
    + '</div>'
    + '<div class="form-actions"><button class="primary" onclick="saveKB()">Save</button><button class="btn-sm" onclick="hideKBModal()">Cancel</button></div>'
    + '</div></div>';
  document.body.insertAdjacentHTML('beforeend', html);
}

// ── Upload ──
function uploadDoc() {
  var title = document.getElementById('upload-title').value.trim();
  var content = document.getElementById('upload-content').value.trim();
  if (!title) { alert('Title required'); return; }
  if (!state.selectedKB) { alert('Select a KB first'); return; }
  var cls = document.getElementById('upload-class').value;
  var docId = 'doc-' + Date.now().toString(36);
  kbData[state.selectedKB].docs.push({
    id: docId, title: title, cls: cls,
    chunks: Math.floor(content.length / 500) || 1, status: 'indexed'
  });
  document.getElementById('upload-title').value = '';
  document.getElementById('upload-content').value = '';
  renderDocTable(kbData[state.selectedKB]);
}

function changeCls(sel, docId) {
  if (!confirm('Change classification to ' + sel.value + '?')) return;
  var kb = kbData[state.selectedKB];
  if (!kb) return;
  var doc = kb.docs.find(function(d){return d.id===docId;});
  if (doc) doc.cls = sel.value;
}

// ── Test Retrieval ──
function goTestRetrieval() {
  var url = 'test-retrieval.html';
  if (state.selectedKB) url += '?kb=' + state.selectedKB;
  else if (document.getElementById('dd-filter').value) url += '?dd=' + document.getElementById('dd-filter').value;
  window.location.href = url;
}
</script>
```

---

### Task 4: test-retrieval.html — 新建独立页面

**Files:**
- Create: `apps/earp-admin/pages/test-retrieval.html`

完整代码见独立文件。核心结构：
- 顶部导航（与其他页面一致的 L2 分组导航，「知识」组高亮）
- Scope 选择器：从 URL 参数 `?kb=xxx` 或 `?dd=xxx` 预填
- Query 输入 + Search 按钮
- Settings 行（显示当前检索参数）
- Results 表（# / Chunk ID / Content / Score）
- JS 模拟搜索结果

---

### Task 5: 验证

- [ ] KB 列表默认显示 3 个 KB，按 DD 过滤正常
- [ ] 点击 KB → 右侧显示信息栏 + 文档列表
- [ ] ⚙️ Config 按钮 → 打开编辑模态框，预填当前值
- [ ] 🗑 Delete 按钮 → 确认后删除
- [ ] + New KB → 创建模态框，保存后出现在列表
- [ ] Upload → 文档出现在表格中
- [ ] Classification 下拉修改
- [ ] Test Retrieval 按钮 → 跳转 test-retrieval.html（带 kb 参数）
- [ ] test-retrieval.html 独立页面可正常运行
