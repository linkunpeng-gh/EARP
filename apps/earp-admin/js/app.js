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
