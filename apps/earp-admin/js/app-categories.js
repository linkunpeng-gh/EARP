/* 治理中心 · 应用分类词表 CRUD */
(function () {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var cats = [];
  var renaming = null;

  async function load() {
    var tbody = document.getElementById('cat-list');
    tbody.innerHTML = '<tr><td colspan="2" style="color:var(--text-quaternary);">加载中…</td></tr>';
    try {
      cats = await EARP.fetchJSON('/api/app_categories');
      if (!cats.length) { tbody.innerHTML = '<tr><td colspan="2" style="color:var(--text-quaternary);">暂无分类 — 新增或使用默认分类</td></tr>'; return; }
      tbody.innerHTML = cats.map(function (c) {
        return '<tr data-id="' + esc(c.category_id) + '">'
          + '<td>' + esc(c.name) + '</td>'
          + '<td style="white-space:nowrap;">'
          + '<button class="btn-sm btn-outline" data-act="rename">改名</button> '
          + '<button class="btn-sm btn-outline" data-act="del" style="color:var(--red);">删除</button>'
          + '</td></tr>';
      }).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="2" style="color:var(--red);">加载失败: ' + esc(e.message) + '</td></tr>';
    }
  }

  function openRename(c) {
    renaming = c;
    document.getElementById('rename-input').value = c.name;
    document.getElementById('rename-modal').style.display = 'flex';
    setTimeout(function () { document.getElementById('rename-input').focus(); }, 60);
  }

  document.addEventListener('DOMContentLoaded', function () {
    load();
    document.getElementById('cat-add').onclick = async function () {
      var name = document.getElementById('cat-name').value.trim();
      if (!name) { alert('请输入分类名称'); return; }
      try {
        await EARP.fetchJSON('/api/app_categories', { method: 'POST', body: JSON.stringify({ name: name }) });
        document.getElementById('cat-name').value = '';
        await load();
      } catch (e) { alert('新增失败: ' + e.message); }
    };
    document.getElementById('cat-list').addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-act]');
      if (!btn) return;
      var tr = ev.target.closest('tr');
      var cat = cats.find(function (c) { return c.category_id === tr.dataset.id; });
      if (!cat) return;
      if (btn.dataset.act === 'rename') openRename(cat);
      if (btn.dataset.act === 'del') {
        if (!confirm('删除分类「' + cat.name + '」？该分类下的应用分类将置空。')) return;
        EARP.fetchJSON('/api/app_categories/' + encodeURIComponent(cat.category_id), { method: 'DELETE' })
          .then(function (res) {
            if (res.affected_apps > 0) alert('已删除，' + res.affected_apps + ' 个应用的分类已置空。');
            load();
          }).catch(function (e) { alert('删除失败: ' + e.message); });
      }
    });
    document.getElementById('rename-ok').onclick = async function () {
      var name = document.getElementById('rename-input').value.trim();
      if (!renaming || !name) return;
      try {
        await EARP.fetchJSON('/api/app_categories/' + encodeURIComponent(renaming.category_id), {
          method: 'PATCH', body: JSON.stringify({ name: name }),
        });
        document.getElementById('rename-modal').style.display = 'none';
        await load();
      } catch (e) { alert('改名失败: ' + e.message); }
    };
    document.getElementById('rename-cancel').onclick = function () { document.getElementById('rename-modal').style.display = 'none'; };
  });
})();
