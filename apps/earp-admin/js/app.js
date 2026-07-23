/* EARP Admin Dashboard — Vue app shell (petite-vue) */
const EARP = {
  apiBase: '/',
  token: localStorage.getItem('earp_token') || '',
  tenantId: 'tenant-demo',

  headers() {
    const h = { 'Content-Type': 'application/json' };
    if (this.token) h['Authorization'] = 'Bearer ' + this.token;
    return h;
  },

  async fetchJSON(url, opts = {}) {
    const res = await fetch(this.apiBase + url, { headers: this.headers(), ...opts });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  },

  // SSE streaming helper
  async streamSSE(url, body, onToken) {
    const res = await fetch(this.apiBase + url, {
      method: 'POST', headers: this.headers(), body: JSON.stringify(body),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') { onToken({ token: '[DONE]', index: -1 }); return; }
        try { onToken(JSON.parse(data)); } catch {}
      }
    }
  },
};

// ── Navigation active state ──
EARP.setActiveNav = function() {
  const path = location.pathname;
  const nav = document.querySelector('header nav');
  if (!nav) return;
  // Top-level group links
  const groups = nav.querySelectorAll('.nav-group > a[data-nav]');
  groups.forEach(a => {
    const group = a.getAttribute('data-nav');
    if (path.includes('/' + group)) a.classList.add('active');
  });
  // Special: stream → 推理
  if (path.includes('/stream')) {
    const reasoning = nav.querySelector('.nav-group > a[data-nav="plan"]');
    if (reasoning) reasoning.classList.add('active');
  }
  // Special: data-domains / doc-config → 知识
  if (path.includes('/data-domains') || path.includes('/doc-config')) {
    const knowledge = nav.querySelector('.nav-group > a[data-nav="knowledge"]');
    if (knowledge) knowledge.classList.add('active');
  }
  // Dropdown items
  const dropdownItems = nav.querySelectorAll('.dropdown-menu a[data-nav]');
  dropdownItems.forEach(a => {
    const group = a.getAttribute('data-nav');
    if (path.includes('/' + group)) a.classList.add('active');
  });
};
document.addEventListener('DOMContentLoaded', function() {
  EARP.setActiveNav();
});
