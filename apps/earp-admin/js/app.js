/* EARP Admin Dashboard — Vue app shell (petite-vue) */
const EARP = {
  // file:// pages can't resolve relative URLs against the API — use the
  // absolute dev origin (server CORS allows this). Same-origin deployments
  // (http://127.0.0.1:8000/admin/...) keep the relative base. A previously
  // discovered base (from auto-probe) is preferred.
  apiBase: (function() {
    const saved = localStorage.getItem('earp_api_base');
    if (saved) return saved;
    if (location.protocol === 'file:') return 'http://127.0.0.1:8000';
    return '/';
  })(),
  token: localStorage.getItem('earp_token') || '',
  tenantId: 'tenant-demo',

  headers() {
    const h = { 'Content-Type': 'application/json' };
    if (this.token) h['Authorization'] = 'Bearer ' + this.token;
    return h;
  },

  async fetchJSON(url, opts = {}) {
    const attempt = async (base) => {
      const res = await fetch(base + url, { headers: this.headers(), ...opts });
      if (!res.ok) {
        const err = new Error(res.status === 401 ? '401 未授权 — 请先通过 pages/login.html 登录获取 token' : `${res.status} ${res.statusText}`);
        err.status = res.status;
        throw err;
      }
      return res.json();
    };
    try {
      return await attempt(this.apiBase);
    } catch (e) {
      // Network-level failure (Failed to fetch / DNS error): the page may be
      // opened from a host that isn't the API server — probe the standard dev
      // origin once and retry. This makes the dashboard work regardless of how
      // it's served (file://, http://api/..., any static server port).
      if (!e.status && this.apiBase !== 'http://127.0.0.1:8000') {
        try {
          const probe = await fetch('http://127.0.0.1:8000/health', { method: 'GET' });
          if (probe.ok) {
            this.apiBase = 'http://127.0.0.1:8000';
            localStorage.setItem('earp_api_base', this.apiBase);
            return await attempt(this.apiBase);
          }
        } catch (_) { /* probe failed — keep original error */ }
      }
      throw e;
    }
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
  // Special: data-domains / doc-config / test-retrieval / doc-seg → 知识
  if (
    path.includes('/data-domains') ||
    path.includes('/doc-config') ||
    path.includes('/test-retrieval') ||
    path.includes('/doc-seg')
  ) {
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
