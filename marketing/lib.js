/**
 * lib.js — EARP 宣讲 PPT 主题与布局辅助库
 */
const ICONS = require('./icons.json');

// ---------- 主题 ----------
const T = {
  W: 13.333, H: 7.5,
  FONT: 'Source Han Sans SC',
  NAVY: '0E2A5C',      // 深海军蓝（封面/结尾）
  NAVY2: '133A78',     // 次级深蓝
  BLUE: '0047AB',      // 主色 钴蓝
  BLUE2: '2563EB',     // 辅助 亮蓝
  ORANGE: 'E67E22',    // 点缀 暖橙
  INK: '14223B',       // 正文深色
  BODY: '3E4D68',      // 正文
  MUTED: '64748F',     // 弱化
  TINT: 'F2F6FC',      // 浅蓝底
  TINT2: 'E7EFFB',     // 稍深浅蓝底
  OTINT: 'FDF3E8',     // 浅橙底
  LINE: 'D8E2F1',      // 描边
  WHITE: 'FFFFFF',
  ICE: 'C9D8F2',       // 深底上的浅蓝文字
  ORANGE_D: 'C2550F',  // 深橙文字
};

const M = 0.55;          // 页边距
const CW = T.W - M * 2;  // 内容宽度 12.233

function isCJK(ch) {
  const o = ch.codePointAt(0);
  return (o >= 0x4E00 && o <= 0x9FFF) || (o >= 0x3000 && o <= 0x303F) || (o >= 0xFF00 && o <= 0xFFEF) || o > 0x2000;
}

// ---------- 通用 ----------
function shadow(o) {
  return { type: 'outer', color: '1B2C52', opacity: 0.13, blur: 8, offset: 3, angle: 90, ...o };
}
function ic(key, color) {
  const c = { blue2: 'light', lightblue: 'light' }[color] || color;
  const v = ICONS[`${key}_${c}`];
  if (!v) throw new Error(`missing icon ${key}_${c}`);
  return v;
}

// ---------- 形状/文本 ----------
function card(slide, o) {
  slide.addShape('roundRect', {
    x: o.x, y: o.y, w: o.w, h: o.h,
    fill: { color: o.fill || T.WHITE },
    line: o.line ? { color: o.line, width: o.lineW || 1 } : { color: T.WHITE, width: 0 },
    rectRadius: o.radius ?? 0.045,
    shadow: o.shadow === false ? undefined : shadow(o.shadowOpts),
    ...o.shapeOpts,
  });
}

function txt(slide, text, o) {
  const opts = {
    x: o.x, y: o.y, w: o.w, h: o.h,
    fontFace: o.font || T.FONT,
    fontSize: o.size || 14,
    bold: o.bold || false,
    italic: o.italic || false,
    color: o.color || T.INK,
    align: o.align || 'left',
    valign: o.valign || 'top',
    margin: o.margin ?? 0,
    charSpacing: o.charSpacing ?? 0,
    lineSpacingMultiple: o.lineSpacing ?? 1.15,
    paraSpaceAfter: o.paraSpaceAfter ?? 0,
    breakLine: o.breakLine ?? false,
    bullet: o.bullet ?? false,
    ...o.extra,
  };
  if (o.wrap === false) opts.wrap = false;
  slide.addText(text, opts);
}

function chip(slide, o) {
  // 宽度估算：中文全角 ≈ 0.95em，ASCII ≈ 0.55em，内边距 0.5"
  let est = 0.0;
  for (const ch of o.text) {
    const w = isCJK(ch) ? 0.95 : 0.55;
    est += (o.size || 12) * w / 72;
  }
  const w = o.w || est + 0.5;
  const h = o.h || 0.34;
  slide.addShape('roundRect', {
    x: o.x, y: o.y, w, h,
    fill: { color: o.fill || T.TINT },
    line: { color: o.line || T.TINT, width: 1 },
    rectRadius: h / 2,
    shadow: false,
  });
  txt(slide, o.text, {
    x: o.x, y: o.y, w, h,
    align: 'center', valign: 'middle',
    size: o.size || 12, bold: o.bold ?? true, color: o.color || T.BLUE,
    charSpacing: o.charSpacing ?? 0.5,
  });
  return w;
}

/** 图标（可选彩色圆底） */
function iconCircle(slide, o) {
  if (o.fill) {
    slide.addShape('ellipse', {
      x: o.x, y: o.y, w: o.d, h: o.d,
      fill: { color: o.fill },
      line: { color: o.fill, width: 0 },
      shadow: o.shadow === false ? undefined : shadow({ opacity: 0.12, blur: 6, offset: 2 }),
    });
  }
  const pad = o.d * 0.22;
  slide.addImage({ data: ic(o.key, o.color || 'blue'), x: o.x + pad, y: o.y + pad, w: o.d - pad * 2, h: o.d - pad * 2 });
}

/** 内容页页头：chip 序号 + 价值结论标题 + 副标题 */
function header(slide, o) {
  chip(slide, { x: M, y: 0.42, text: o.kicker, fill: T.TINT, color: T.BLUE, size: 11.5, h: 0.32 });
  txt(slide, o.title, {
    x: M, y: 0.84, w: CW, h: 0.9,
    size: o.titleSize || 27, bold: true, color: T.INK, lineSpacing: 1.08, valign: 'top',
  });
  if (o.sub) {
    txt(slide, o.sub, {
      x: M, y: o.titleSize ? 0.84 + 0.95 : 1.66, w: CW, h: 0.42,
      size: 13.5, color: T.MUTED, valign: 'top',
    });
  }
  return { titleBottom: (o.titleSize ? 0.84 + 0.95 : 1.66) + (o.sub ? 0.5 : 0.12) };
}

/** 内容页页脚 */
function footer(slide, n, total = 32, dark = false) {
  txt(slide, 'EARP · 企业级 AI 操作系统', {
    x: M, y: T.H - 0.42, w: 4, h: 0.3, size: 9.5, color: dark ? T.ICE : T.MUTED, valign: 'middle',
  });
  txt(slide, `${String(n).padStart(2, '0')} / ${total}`, {
    x: T.W - M - 1.2, y: T.H - 0.42, w: 1.2, h: 0.3, size: 9.5, color: dark ? T.ICE : T.MUTED,
    align: 'right', valign: 'middle',
  });
}

/** 数值大卡（价值结论） */
function stat(slide, o) {
  card(slide, { x: o.x, y: o.y, w: o.w, h: o.h, fill: o.fill || T.WHITE, line: o.line ?? T.LINE, shadow: false });
  if (o.icon) iconCircle(slide, { key: o.icon, color: o.iconColor || 'blue', x: o.x + 0.2, y: o.y + 0.18, d: 0.42, fill: o.iconFill || T.TINT, shadow: false });
  txt(slide, o.num, { x: o.x + 0.2, y: o.y + (o.icon ? 0.72 : 0.24), w: o.w - 0.4, h: o.h - (o.icon ? 0.9 : 0.45), size: o.numSize || 26, bold: true, color: o.numColor || T.BLUE, valign: 'middle', lineSpacing: 1 });
  txt(slide, o.label, { x: o.x + 0.2, y: o.y + o.h - 0.5, w: o.w - 0.4, h: 0.4, size: 11.5, color: T.MUTED, valign: 'middle', lineSpacing: 1.1 });
}

/** 箭头（chevron） */
function arrow(slide, o) {
  slide.addShape('chevron', {
    x: o.x, y: o.y, w: o.w, h: o.h,
    fill: { color: o.fill || T.TINT2 },
    line: { color: o.fill || T.TINT2, width: 0 },
    adj1: 0.42,
    shadow: false,
  });
}

/** 五要素中「痛点对比」双卡：传统 vs EARP */
function painCard(slide, o) {
  card(slide, { x: o.x, y: o.y, w: o.w, h: o.h, fill: o.fill || T.WHITE, line: T.LINE, shadow: false });
  txt(slide, o.beforeTitle || '传统模式', {
    x: o.x + 0.22, y: o.y + 0.16, w: o.w - 0.44, h: 0.32,
    size: 12.5, bold: true, color: o.beforeColor || T.MUTED,
  });
  txt(slide, o.before, {
    x: o.x + 0.22, y: o.y + 0.5, w: o.w - 0.44, h: o.h - 0.66,
    size: 12, color: o.beforeColor || T.MUTED, lineSpacing: 1.3, valign: 'top',
  });
  txt(slide, o.afterTitle || 'EARP 模式', {
    x: o.x + 0.22, y: o.y + o.h / 2 + 0.1, w: o.w - 0.44, h: 0.32,
    size: 12.5, bold: true, color: o.afterColor || T.BLUE,
  });
  txt(slide, o.after, {
    x: o.x + 0.22, y: o.y + o.h / 2 + 0.44, w: o.w - 0.44, h: o.h / 2 - 0.56,
    size: 12, color: o.afterColor || T.INK, lineSpacing: 1.3, valign: 'top',
  });
}

/** 小卡片（图标+标题+正文），常用于 grid */
function miniCard(slide, o) {
  card(slide, { x: o.x, y: o.y, w: o.w, h: o.h, fill: o.fill || T.WHITE, line: o.line ?? T.LINE, shadow: o.shadow !== false });
  if (o.icon) iconCircle(slide, { key: o.icon, color: o.iconColor || 'blue', x: o.x + 0.24, y: o.y + 0.22, d: 0.46, fill: o.iconFill || T.TINT, shadow: false });
  const top = o.icon ? o.y + 0.8 : o.y + 0.2;
  txt(slide, o.title, {
    x: o.x + 0.24, y: top, w: o.w - 0.48, h: 0.6,
    size: o.titleSize || 15.5, bold: true, color: T.INK, lineSpacing: 1.1, valign: 'top',
  });
  txt(slide, o.body, {
    x: o.x + 0.24, y: top + (o.titleSize ? 0.72 : 0.64), w: o.w - 0.48, h: o.h - (top + (o.titleSize ? 0.72 : 0.64) - o.y) - 0.22,
    size: o.bodySize || 12, color: T.BODY, lineSpacing: 1.32, valign: 'top',
  });
  if (o.tag) chip(slide, { x: o.x + 0.24, y: o.y + o.h - 0.46, text: o.tag, fill: o.tagFill || T.OTINT, color: o.tagColor || T.ORANGE_D, size: 10.5, h: 0.3 });
}

module.exports = { T, M, CW, shadow, ic, card, txt, chip, iconCircle, header, footer, stat, arrow, painCard, miniCard };
