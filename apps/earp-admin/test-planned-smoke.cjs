/* Runtime test for pages/planned.html inline rendering logic. */
const fs = require('fs');
const path = require('path');

function makeEl(tag, id) {
  return {
    tagName: tag, id: id || '', children: [], className: '', innerHTML: '',
    textContent: '', style: {},
    dataset: {},
    classList: { add() {}, remove() {} },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    insertBefore(c, ref) { const i = this.children.indexOf(ref); if (i < 0) this.children.push(c); else this.children.splice(i, 0, c); c.parentNode = this; return c; },
    closest() { return null; },
  };
}

function pageElements(ids) {
  const el = {};
  ids.forEach((id) => { el[id] = makeEl('div', id); });
  return el;
}

function runPlanned(url, bodyDataset) {
  global.location = { search: url, pathname: '/pages/planned.html' };
  global.window = {};
  global.URLSearchParams = URLSearchParams;
  const ids = ['p-title', 'p-sub', 'pb-title', 'pb-desc', 'pb-phase', 'p-hint', 'p-grid', 'p-implemented-title', 'p-implemented'];
  const els = pageElements(ids);
  const main = makeEl('main');
  Object.values(els).forEach((e) => main.appendChild(e));

  global.document = {
    readyState: 'loading',
    listeners: {},
    body: Object.assign(makeEl('body'), { dataset: bodyDataset }),
    createElement(t) { return makeEl(t); },
    addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    querySelector(sel) { return sel === 'main' ? main : (sel === 'header' ? makeEl('header') : null); },
    getElementById(id) {
      if (els[id]) return els[id];
      const walk = (el) => { if (el.id === id) return el; for (const c of el.children || []) { const r = walk(c); if (r) return r; } return null; };
      return walk(this.body);
    },
  };
  document.body.appendChild(main);

  // load nav.js then planned inline script
  const navSrc = fs.readFileSync(path.join(__dirname, 'js', 'nav.js'), 'utf8');
  eval(navSrc);
  const plannedSrc = fs.readFileSync(path.join(__dirname, 'pages', 'planned.html'), 'utf8');
  const inline = [...plannedSrc.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((b) => b[1]).join('\n');
  eval(inline); // inline script runs synchronously (uses nav.js + getElementById)

  // nav.js boot
  (document.listeners['DOMContentLoaded'] || []).forEach((fn) => fn());

  return { els, nav: global.window.EARP_NAV };
}

let ok = true;
const fail = (m) => { ok = false; console.error('  ✗ ' + m); };

// 1) item view: ?section=workspace&item=workflow（chat 已实现，用 workflow 验证占位页）
let r = runPlanned('?section=workspace&item=workflow', { base: '..' });
if (!r.els['p-title'].textContent.includes('workflow')) fail('item title wrong: ' + r.els['p-title'].textContent);
if (!r.els['pb-phase'].textContent.includes('第三期')) fail('phase/priority missing: ' + r.els['pb-phase'].textContent);
if (!r.els['p-grid'].innerHTML.includes('可视化对话编排')) fail('roadmap card missing workflow desc');
if (r.els['p-hint'].style.display !== 'none') fail('hint not hidden');

// 2) section overview: ?section=workspace (no item)
r = runPlanned('?section=workspace', { base: '..' });
const grid = r.els['p-grid'].innerHTML;
if (!grid.includes('workflow') || !grid.includes('Agent') || !grid.includes('Skills')) fail('workspace overview missing planned items');
if (grid.includes('pages/chat.html')) fail('chat should NOT appear in planned overview');
if (!grid.includes('planned.html?section=workspace&item=workflow')) fail('overview card link wrong');

// 3) mixed section: ?section=capability (connector planned + implemented items)
r = runPlanned('?section=capability', { base: '..' });
if (!r.els['p-grid'].innerHTML.includes('连接器')) fail('capability overview missing connector');
if (!r.els['p-implemented'].innerHTML.includes('capabilities.html')) fail('implemented links missing');

// 4) governance item: ?section=governance&item=roles
r = runPlanned('?section=governance&item=roles', { base: '..' });
if (!r.els['pb-phase'].textContent.includes('P8')) fail('roles priority missing P8');
if (!r.els['p-sub'].textContent.includes('治理中心')) fail('subtitle section wrong');

console.log(ok ? '✓ planned.html rendering OK' : '✗ planned.html rendering FAILED');
process.exit(ok ? 0 : 1);
