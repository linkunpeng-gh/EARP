/**
 * slides_a.js — Part 0/1/2：开篇（1-4）、理念定位（5-9）、能力全景（10-11）
 */
module.exports = function buildA(pptx, H) {
  const S = [];
  const { T, M, CW, card, txt, chip, iconCircle, header, footer, stat, arrow, painCard, miniCard } = H;

  // ========== S1 封面（深蓝底） ==========
  {
    const s = pptx.addSlide(); S.push(s);
    s.background = { color: T.NAVY };
    // 装饰圆（大留白下的一点层次）
    s.addShape('ellipse', { x: 9.6, y: -2.2, w: 6.4, h: 6.4, fill: { color: T.BLUE, transparency: 88 }, line: { color: T.BLUE, width: 0 }, shadow: false });
    s.addShape('ellipse', { x: 10.8, y: 3.6, w: 3.4, h: 3.4, fill: { color: T.BLUE2, transparency: 90 }, line: { color: T.BLUE2, width: 0 }, shadow: false });
    s.addShape('ellipse', { x: -1.4, y: 5.4, w: 3.0, h: 3.0, fill: { color: T.BLUE2, transparency: 92 }, line: { color: T.BLUE2, width: 0 }, shadow: false });

    txt(s, 'EARP', { x: M, y: 0.55, w: 3, h: 0.5, size: 22, bold: true, color: T.WHITE, charSpacing: 3 });
    txt(s, 'ENTERPRISE AI RUNTIME PLATFORM', { x: M, y: 1.02, w: 6, h: 0.3, size: 9.5, color: T.ICE, charSpacing: 1.8 });

    // 中间主视觉
    s.addShape('roundRect', {
      x: M, y: 2.42, w: 3.05, h: 0.44, rectRadius: 0.22,
      fill: { color: T.NAVY2 }, line: { color: '3E63A8', width: 1 }, shadow: false,
    });
    txt(s, '企业级 AI 操作系统', { x: M, y: 2.42, w: 3.05, h: 0.44, align: 'center', valign: 'middle', size: 12.5, bold: true, color: T.ICE, charSpacing: 1 });

    txt(s, '让企业 AI 可信、可控、可落地', {
      x: M, y: 3.02, w: 12.2, h: 1.1, size: 38, bold: true, color: T.WHITE, lineSpacing: 1.12, valign: 'top',
    });
    txt(s, '面向企业场景的智能体开发、调度与运行底座 —— 把大模型真正变成业务生产力', {
      x: M, y: 4.32, w: 11.4, h: 0.5, size: 15, color: T.ICE, valign: 'top',
    });

    // 底部能力点
    const tags = ['多模型编排', '业务能力中心', '知识资产', '安全合规治理'];
    let tx = M;
    tags.forEach((t, i) => {
      txt(s, t, { x: tx, y: 5.55, w: 2.1, h: 0.4, size: 12.5, color: T.WHITE, bold: true });
      if (i < tags.length - 1) {
        s.addShape('ellipse', { x: tx + 2.14, y: 5.71, w: 0.08, h: 0.08, fill: { color: T.ORANGE }, line: { color: T.ORANGE, width: 0 }, shadow: false });
      }
      tx += 2.35;
    });

    txt(s, '产品介绍 · 商务宣讲版   2026', { x: M, y: 6.62, w: 5, h: 0.3, size: 10.5, color: T.ICE });
    txt(s, '01', { x: T.W - M - 0.8, y: 0.55, w: 0.8, h: 0.4, size: 11, color: T.ICE, align: 'right' });
  }

  // ========== S2 目录 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: 'CONTENTS · 内容导览', title: '本次分享，五个部分', sub: '从理念到落地，30 分钟看懂 EARP 能为你解决什么' });
    const items = [
      { n: '01', t: '重新认识 AI 平台', d: '理念与定位：企业 AI 难在 80% 的“模型之外”', icon: 'compass' },
      { n: '02', t: '一张图看懂 EARP', d: '能力全景：核心刚需 + 增值赋能', icon: 'grid' },
      { n: '03', t: '数据智能五件套', d: '从问数到决策：五个立即可用的业务场景', icon: 'zap' },
      { n: '04', t: '平台核心能力', d: '可信、可控、可落地：知识与执行的安全底座', icon: 'shield' },
      { n: '05', t: '行业落地与合作', d: '客户实践与示例场景，以及三种合作方式', icon: 'handshake' },
    ];
    const cw = 3.87, ch = 1.78, gap = 0.31;
    const xs = [M, M + cw + gap, M + 2 * (cw + gap)];
    items.forEach((it, i) => {
      const x = xs[i % 3], y = 2.35 + Math.floor(i / 3) * (ch + 0.32);
      card(s, { x, y, w: cw, h: ch });
      iconCircle(s, { key: it.icon, color: i === 3 ? 'orange' : 'blue', x: x + 0.24, y: y + 0.22, d: 0.5, fill: i === 3 ? T.OTINT : T.TINT, shadow: false });
      txt(s, it.n, { x: x + cw - 0.75, y: y + 0.18, w: 0.55, h: 0.4, size: 20, bold: true, color: T.ORANGE, align: 'right' });
      txt(s, it.t, { x: x + 0.24, y: y + 0.85, w: cw - 0.48, h: 0.4, size: 15.5, bold: true, color: T.INK });
      txt(s, it.d, { x: x + 0.24, y: y + 1.22, w: cw - 0.48, h: 0.5, size: 11.5, color: T.MUTED, lineSpacing: 1.2 });
    });
    // 第六格：你将收获
    const x = xs[2], y = 2.35 + ch + 0.32;
    card(s, { x, y, w: cw, h: ch, fill: T.OTINT, line: T.OTINT });
    txt(s, '你将收获', { x: x + 0.24, y: y + 0.2, w: cw - 0.48, h: 0.4, size: 15.5, bold: true, color: T.ORANGE_D });
    txt(s, [
      { text: '一套可复制的 AI 落地方法论', options: { bullet: true, breakLine: true, paraSpaceAfter: 5 } },
      { text: '五种立即可用的数据智能场景', options: { bullet: true, breakLine: true, paraSpaceAfter: 5 } },
      { text: '三种与 EARP 合作共赢的方式', options: { bullet: true } },
    ], { x: x + 0.24, y: y + 0.68, w: cw - 0.48, h: 1.0, size: 12, color: T.BODY, lineSpacing: 1.25 });
    txt(s, '本材料案例均已标注：■ 客户实践  ■ 示例场景', {
      x: M, y: 6.45, w: CW, h: 0.35, size: 11.5, color: T.MUTED,
    });
    footer(s, 2);
  }

  // ========== S3 痛点 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '开场 · 直面现实', title: '企业 AI 落地的三大现实：80% 的精力，消耗在模型之外', sub: '大模型本身不是瓶颈 —— 集成、编排、治理、审计，才是企业真正要翻的墙' });
    const cards = [
      { icon: 'link', iconC: 'blue', t: '接不通', d: '模型多、系统杂：每个应用都要重复对接大模型与企业系统，项目迟迟跑不起来。' },
      { icon: 'shield', iconC: 'orange', t: '不敢信', d: '答非所问、无权限管控、无审计留痕，业务部门不敢把真业务交给 AI。' },
      { icon: 'refreshCw', iconC: 'blue', t: '不闭环', d: '问完就完、结果不沉淀，AI 没有沉淀成可复用的业务能力。' },
    ];
    cards.forEach((c, i) => {
      const x = M + i * (3.87 + 0.31);
      card(s, { x, y: 2.35, w: 3.87, h: 2.75 });
      iconCircle(s, { key: c.icon, color: c.iconC, x: x + 0.24, y: 2.6, d: 0.54, fill: c.iconC === 'orange' ? T.OTINT : T.TINT, shadow: false });
      txt(s, c.t, { x: x + 0.24, y: 3.28, w: 3.4, h: 0.5, size: 18, bold: true, color: T.INK });
      txt(s, c.d, { x: x + 0.24, y: 3.82, w: 3.4, h: 1.15, size: 12.5, color: T.BODY, lineSpacing: 1.35 });
    });
    // 数据条
    card(s, { x: M, y: 5.5, w: CW, h: 1.25, fill: T.TINT2, line: T.TINT2, shadow: false });
    txt(s, '20%', { x: M + 0.35, y: 5.68, w: 1.6, h: 0.9, size: 34, bold: true, color: T.ORANGE, valign: 'middle' });
    txt(s, 'LLM 在企业场景只占 20% 的工作量', { x: M + 1.95, y: 5.75, w: 5.6, h: 0.4, size: 15.5, bold: true, color: T.INK });
    txt(s, '其余 80% 是集成、编排、治理与审计 —— 这正是 EARP 的价值所在', { x: M + 1.95, y: 6.2, w: 9.6, h: 0.4, size: 12.5, color: T.BODY });
    footer(s, 3);
  }

  // ========== S4 破题 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '开场 · 破题', title: 'AI 平台的分水岭：以模型为中心，还是以业务能力为中心？', sub: '模型会换、会升级；业务能力，才是企业长期沉淀的资产' });
    const cw2 = 5.95;
    // 左：通用平台
    card(s, { x: M, y: 2.35, w: cw2, h: 3.15, fill: T.TINT, line: T.TINT });
    txt(s, '通用 AI 平台', { x: M + 0.3, y: 2.6, w: 3, h: 0.45, size: 17, bold: true, color: T.BODY });
    chip(s, { x: M + cw2 - 2.4, y: 2.63, text: '以 LLM 为中心', fill: T.WHITE, color: T.MUTED, size: 11, h: 0.32 });
    txt(s, [
      { text: '对话思维，难以直达业务结果', options: { bullet: true, breakLine: true, paraSpaceAfter: 7 } },
      { text: '工具零散接入，能力不可治理', options: { bullet: true, breakLine: true, paraSpaceAfter: 7 } },
      { text: '权限与审计事后补丁，合规存疑', options: { bullet: true, breakLine: true, paraSpaceAfter: 7 } },
      { text: '与企业系统集成浅，落地隔层纱', options: { bullet: true } },
    ], { x: M + 0.3, y: 3.2, w: cw2 - 0.6, h: 2.15, size: 13.5, color: T.BODY, lineSpacing: 1.25 });
    // 右：EARP
    card(s, { x: M + cw2 + 0.33, y: 2.35, w: cw2, h: 3.15, fill: T.WHITE, line: T.BLUE, lineW: 1.5 });
    txt(s, 'EARP', { x: M + cw2 + 0.63, y: 2.6, w: 2.2, h: 0.45, size: 17, bold: true, color: T.BLUE });
    chip(s, { x: M + cw2 + 0.33 + cw2 - 2.75, y: 2.63, text: '以业务能力为中心', fill: T.TINT2, color: T.BLUE, size: 11, h: 0.32 });
    txt(s, [
      { text: '先懂业务领域，再调用业务能力', options: { bullet: true, breakLine: true, paraSpaceAfter: 7 } },
      { text: '能力统一注册、统一治理、可复用', options: { bullet: true, breakLine: true, paraSpaceAfter: 7 } },
      { text: '权限与审计内建于运行时，天然合规', options: { bullet: true, breakLine: true, paraSpaceAfter: 7 } },
      { text: '与 ERP / MES / 政务系统原生对接', options: { bullet: true } },
    ], { x: M + cw2 + 0.63, y: 3.2, w: cw2 - 0.6, h: 2.15, size: 13.5, color: T.INK, lineSpacing: 1.25 });
    // 底部结论
    card(s, { x: M, y: 5.85, w: CW, h: 0.9, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, '以业务能力为中心，AI 才能真正嵌入企业经营 —— 而不是停留在演示 Demo', {
      x: M, y: 5.85, w: CW, h: 0.9, align: 'center', valign: 'middle', size: 16, bold: true, color: T.WHITE,
    });
    footer(s, 4);
  }

  // ========== S5 定位 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '理念 · 定位', title: '像操作系统管理硬件一样，EARP 管理企业 AI 的执行', sub: '操作系统不生产硬件，却让一切软件跑起来 —— EARP 在企业 AI 中的角色正是如此' });
    const rows = [
      { icon: 'server', n: 'Linux 内核', d: '管理硬件资源，为应用软件提供运行环境' },
      { icon: 'cpu', n: 'Java 虚拟机（JVM）', d: '管理字节码执行，为 Java 程序提供运行时' },
      { icon: 'zap', n: 'EARP AI 运行时', d: '管理企业 AI 执行，为 AI 应用提供运行时', hot: true },
    ];
    rows.forEach((r, i) => {
      const y = 2.35 + i * 1.12;
      card(s, { x: M, y, w: CW, h: 0.97, fill: r.hot ? T.TINT2 : T.WHITE, line: r.hot ? T.BLUE : T.LINE });
      iconCircle(s, { key: r.icon, color: r.hot ? 'orange' : 'blue', x: M + 0.24, y: y + 0.26, d: 0.46, fill: r.hot ? T.OTINT : T.TINT, shadow: false });
      txt(s, r.n, { x: M + 0.95, y: y + 0.14, w: 3.6, h: 0.4, size: 16, bold: true, color: r.hot ? T.BLUE : T.INK });
      txt(s, r.d, { x: M + 0.95, y: y + 0.52, w: 9.6, h: 0.35, size: 12.5, color: T.BODY });
      if (r.hot) txt(s, '→ 这就是 EARP', { x: M + CW - 2.2, y: y + 0.28, w: 1.9, h: 0.4, size: 13, bold: true, color: T.ORANGE, align: 'right' });
    });
    // 一句话定义
    card(s, { x: M, y: 5.85, w: CW, h: 1.25, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, 'EARP = Enterprise AI Runtime Platform', { x: M + 0.35, y: 6.02, w: 9, h: 0.4, size: 16, bold: true, color: T.WHITE });
    txt(s, '面向企业场景的 AI 运行时底座：理解任务 → 规划任务 → 决策 → 执行 → 反馈 → 学习，形成持续进化的业务闭环', {
      x: M + 0.35, y: 6.44, w: 11.6, h: 0.55, size: 13, color: T.ICE, lineSpacing: 1.25,
    });
    footer(s, 5);
  }

  // ========== S6 初衷 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '理念 · 研发初衷', title: 'EARP 从企业真实工作流出发，而不是从大模型出发', sub: '四类角色的共同痛点，催生了这个平台' });
    const items = [
      { icon: 'users', iconC: 'blue', t: '业务人员', d: '想用自然语言问数、要结果 —— 不想写 SQL，不想等 IT 排期。' },
      { icon: 'database', iconC: 'orange', t: '数据部门', d: '指标口径必须统一、可审计 —— “同名不同义”是问数第一坑。' },
      { icon: 'gauge', iconC: 'blue', t: '运营团队', d: '告警要自动归因、自动闭环 —— 从看到问题到解决问题一条链。' },
      { icon: 'lock', iconC: 'blue2', t: 'IT 部门', d: '要可控、可管、可审计 —— 权限隔离，不被单一模型绑定。' },
    ];
    const cw2 = 5.95, ch2 = 1.72;
    items.forEach((it, i) => {
      const x = M + (i % 2) * (cw2 + 0.33), y = 2.35 + Math.floor(i / 2) * (ch2 + 0.3);
      card(s, { x, y, w: cw2, h: ch2 });
      iconCircle(s, { key: it.icon, color: it.iconC, x: x + 0.24, y: y + 0.22, d: 0.5, fill: it.iconC === 'orange' ? T.OTINT : T.TINT, shadow: false });
      txt(s, it.t, { x: x + 0.95, y: y + 0.24, w: 3, h: 0.4, size: 15.5, bold: true, color: T.INK });
      txt(s, it.d, { x: x + 0.95, y: y + 0.66, w: cw2 - 1.2, h: 0.95, size: 12.5, color: T.BODY, lineSpacing: 1.3 });
    });
    card(s, { x: M, y: 5.85, w: CW, h: 0.9, fill: T.OTINT, line: T.OTINT, shadow: false });
    txt(s, '2024–2025 市场上不缺 AI 平台，缺的是把 AI 融进企业业务流程的运行时 —— 这就是 EARP 的起点', {
      x: M, y: 5.85, w: CW, h: 0.9, align: 'center', valign: 'middle', size: 15, bold: true, color: T.ORANGE_D,
    });
    footer(s, 6);
  }

  // ========== S7 三大原则 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '理念 · 设计原则', title: '三大设计原则，回答「AI 凭什么可信、可控」', sub: '平台规范先行，能力来自规则而非运气' });
    const items = [
      { icon: 'layers', t: '统一执行入口', en: 'Runtime First', d: '所有 AI 执行都走同一个运行时：权限、审计、重试、补偿自动生效，应用不再各造轮子。' },
      { icon: 'compass', t: '先懂业务再调能力', en: 'Domain First', d: 'AI 先理解业务领域，再在领域内调用能力：检索准确率从 60% 提升到 95% 以上。' },
      { icon: 'zap', t: '推理与执行分离', en: 'Reason-Act', d: '规划可以聪明试错、持续升级；执行必须稳定可靠，两者互不拖累。' },
    ];
    items.forEach((it, i) => {
      const x = M + i * (3.87 + 0.31);
      card(s, { x, y: 2.35, w: 3.87, h: 3.3 });
      iconCircle(s, { key: it.icon, color: 'blue', x: x + 0.24, y: 2.6, d: 0.56, fill: T.TINT, shadow: false });
      txt(s, it.t, { x: x + 0.24, y: 3.32, w: 3.4, h: 0.45, size: 16.5, bold: true, color: T.INK });
      txt(s, it.en, { x: x + 0.24, y: 3.74, w: 3.4, h: 0.32, size: 11.5, bold: true, color: T.BLUE, charSpacing: 0.5 });
      txt(s, it.d, { x: x + 0.24, y: 4.14, w: 3.4, h: 1.4, size: 12.5, color: T.BODY, lineSpacing: 1.35 });
    });
    txt(s, '还有六项原则：企业级 CQRS（查询只读 / 命令必经审批） · 闭环学习 · 工作流即执行模式 · 多租户隔离 · 全链路审计 · 开放平台规范', {
      x: M, y: 5.95, w: CW, h: 0.5, size: 12, color: T.MUTED, align: 'center',
    });
    footer(s, 7);
  }

  // ========== S8 差异化对比 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '理念 · 差异化', title: '为什么不是「企业版 Dify」：六个维度，本质不同', sub: '通用 AI 平台解决「能不能做」，EARP 解决「企业敢不敢用、能不能持续用」' });
    const cols = [
      { t: '维度', x: M, w: 2.1 },
      { t: '通用 AI 平台（Dify / Coze 等）', x: M + 2.2, w: 4.9 },
      { t: 'EARP', x: M + 7.2, w: 5.03 },
    ];
    const rows = [
      ['设计起点', '以 LLM 为中心', '以业务能力为中心'],
      ['核心抽象', 'App → Workflow → Tool → LLM', 'Request → 领域 → 能力 → 企业系统'],
      ['权限与审计', '事后补丁，合规存疑', '内建于运行时，全链路留痕'],
      ['系统集成', '插件零散对接', '标准连接器 + MCP，一次接通'],
      ['知识资产', '文档问答为主', '文档 RAG + 业务实体图谱双体系'],
      ['执行可靠性', '单步调用为主', '断点续跑 · 重试 · 事务补偿'],
    ];
    // 表头
    cols.forEach((c) => {
      card(s, { x: c.x, y: 2.28, w: c.w, h: 0.52, fill: c.t === 'EARP' ? T.BLUE : T.TINT2, line: 'transparent' === '' ? undefined : (c.t === 'EARP' ? T.BLUE : T.TINT2), shadow: false, lineW: 0 });
      txt(s, c.t, { x: c.x, y: 2.28, w: c.w, h: 0.52, align: 'center', valign: 'middle', size: 13, bold: true, color: c.t === 'EARP' ? T.WHITE : T.BODY });
    });
    rows.forEach((r, i) => {
      const y = 2.88 + i * 0.64;
      const rowFill = i % 2 === 0 ? T.WHITE : T.TINT;
      card(s, { x: M, y, w: 2.1, h: 0.56, fill: rowFill, line: T.LINE, lineW: 0.5, shadow: false });
      txt(s, r[0], { x: M, y, w: 2.1, h: 0.56, align: 'center', valign: 'middle', size: 12, bold: true, color: T.INK });
      card(s, { x: M + 2.2, y, w: 4.9, h: 0.56, fill: rowFill, line: T.LINE, lineW: 0.5, shadow: false });
      txt(s, r[1], { x: M + 2.2 + 0.15, y, w: 4.6, h: 0.56, valign: 'middle', size: 11.5, color: T.MUTED });
      card(s, { x: M + 7.2, y, w: 5.03, h: 0.56, fill: i % 2 === 0 ? T.TINT2 : T.WHITE, line: T.LINE, lineW: 0.5, shadow: false });
      txt(s, r[2], { x: M + 7.2 + 0.15, y, w: 4.73, h: 0.56, valign: 'middle', size: 12, bold: true, color: T.BLUE });
    });
    txt(s, 'EARP 兼容主流大模型与工具生态 —— 与通用平台不是替代关系，而是企业落地的下一层。', {
      x: M, y: 6.62, w: CW, h: 0.35, size: 11.5, color: T.MUTED, align: 'center',
    });
    footer(s, 8);
  }

  // ========== S9 赋能承诺 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '理念 · 赋能', title: '一套平台，三方共赢：我们为谁解决什么问题', sub: '价值不是口号，而是三个群体都能算得清的收益' });
    const items = [
      { icon: 'users', iconC: 'blue', t: '企业客户', d: '让 AI 真正进入日常经营', items: ['落地门槛低：业务人员直接使用', '结果可信合规：口径统一、有据可查', '见效快：2–4 周试点出价值'] },
      { icon: 'store', iconC: 'orange', t: '渠道与集成商', d: '让交付变成可复制的生意', items: ['标准产品 + 开放 SDK，交付可复制', '行业方案叠加，客单价提升', '持续的服务与扩展收入'] },
      { icon: 'award', iconC: 'blue', t: '生态伙伴', d: '让能力变成共享的资产', items: ['能力即插即用，快速封装上线', '联合方案进市场，共享收益', '技术认证与市场支持'] },
    ];
    items.forEach((it, i) => {
      const x = M + i * (3.87 + 0.31);
      card(s, { x, y: 2.35, w: 3.87, h: 3.5 });
      iconCircle(s, { key: it.icon, color: it.iconC, x: x + 0.24, y: 2.6, d: 0.54, fill: it.iconC === 'orange' ? T.OTINT : T.TINT, shadow: false });
      txt(s, it.t, { x: x + 0.24, y: 3.28, w: 3.4, h: 0.4, size: 16.5, bold: true, color: T.INK });
      txt(s, it.d, { x: x + 0.24, y: 3.68, w: 3.4, h: 0.35, size: 11.5, bold: true, color: T.BLUE });
      txt(s, it.items.map((t2, j) => ({ text: t2, options: { bullet: true, breakLine: j < it.items.length - 1, paraSpaceAfter: 7 } })),
        { x: x + 0.24, y: 4.14, w: 3.45, h: 1.6, size: 12.5, color: T.BODY, lineSpacing: 1.25 });
    });
    card(s, { x: M, y: 6.1, w: CW, h: 0.75, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, '把复杂留给自己，把简单交付给伙伴', { x: M, y: 6.1, w: CW, h: 0.75, align: 'center', valign: 'middle', size: 16, bold: true, color: T.WHITE });
    footer(s, 9);
  }

  // ========== S10 能力全景 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '全景 · 一张图', title: '一张图看懂 EARP：核心刚需 + 增值赋能', sub: '三大层次、十三个模块，覆盖从问数到治理的完整闭环' });
    const bands = [
      {
        label: '数据智能层', sub: '核心刚需 · 业务直接使用', icon: 'zap', labelC: T.BLUE,
        cards: [
          { t: '可信问数', icon: 'search', d: '一句话查数，口径一致' },
          { t: '智能归因', icon: 'sigma', d: '指标波动自动拆解' },
          { t: '洞察预测', icon: 'trendUp', d: '趋势预判，提前决策' },
          { t: '一言成报', icon: 'fileText', d: '一句话生成分析报告' },
          { t: '智策看板', icon: 'dashboard', d: '可追问的活看板' },
        ],
      },
      {
        label: '平台核心层', sub: '核心刚需 · 可信可控底座', icon: 'shield', labelC: T.BLUE2,
        cards: [
          { t: '知识资产中心', icon: 'book', d: '文档 + 实体图谱' },
          { t: '智能体编排', icon: 'workflow', d: '断点续跑 / 补偿' },
          { t: '多模型接入', icon: 'server', d: '不绑定单一厂商' },
          { t: '安全治理', icon: 'lock', d: '隔离 / 权限 / 审计' },
          { t: '自动化调度', icon: 'clock', d: '定时 + 事件触发' },
        ],
      },
      {
        label: '开放生态层', sub: '增值赋能 · 伙伴共建', icon: 'puzzle', labelC: T.ORANGE,
        cards: [
          { t: '五大 SDK', icon: 'code', d: '能力三天封装上线' },
          { t: '插件与 MCP', icon: 'plug', d: '对接存量系统' },
          { t: '可观测闭环', icon: 'activity', d: '全程留痕、越用越聪明' },
        ],
      },
    ];
    bands.forEach((b, bi) => {
      const y = 2.2 + bi * 1.66;
      // 左标签
      card(s, { x: M, y, w: 1.6, h: 1.5, fill: bi === 2 ? T.OTINT : T.TINT2, line: bi === 2 ? T.OTINT : T.TINT2, shadow: false });
      iconCircle(s, { key: b.icon, color: bi === 2 ? 'orange' : 'blue', x: M + 0.16, y: y + 0.14, d: 0.4, fill: T.WHITE, shadow: false });
      txt(s, b.label, { x: M + 0.12, y: y + 0.62, w: 1.36, h: 0.35, size: 13, bold: true, color: T.INK, align: 'center' });
      txt(s, b.sub, { x: M + 0.12, y: y + 0.98, w: 1.36, h: 0.45, size: 9.5, color: T.MUTED, align: 'center', lineSpacing: 1.15 });
      // 能力卡
      const n = b.cards.length;
      const gap = 0.22, avail = CW - 1.6 - 0.25 - (n - 1) * gap;
      const cw3 = avail / n;
      b.cards.forEach((c, i) => {
        const x = M + 1.85 + i * (cw3 + gap);
        card(s, { x, y, w: cw3, h: 1.5, fill: T.WHITE, line: T.LINE, shadow: false });
        iconCircle(s, { key: c.icon, color: 'blue', x: x + 0.14, y: y + 0.13, d: 0.38, fill: T.TINT, shadow: false });
        txt(s, c.t, { x: x + 0.14, y: y + 0.58, w: cw3 - 0.28, h: 0.32, size: 11.5, bold: true, color: T.INK });
        txt(s, c.d, { x: x + 0.14, y: y + 0.92, w: cw3 - 0.28, h: 0.5, size: 9.5, color: T.MUTED, lineSpacing: 1.15 });
      });
    });
    txt(s, '数据智能层叠加在既有数据底座 / BI 之上 —— 对企业现有投入是「升级」，不是「推倒重来」', {
      x: M, y: 7.02, w: CW, h: 0.32, size: 11, color: T.MUTED, align: 'center',
    });
    footer(s, 10);
  }

  // ========== S11 执行闭环 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '全景 · 执行闭环', title: '从一句话到结果：AI 执行全链路闭环，且越用越聪明', sub: '六个环节环环相扣 —— 每一次执行，都在让系统更懂你的业务' });
    const nodes = [
      { icon: 'brain', t: '理解意图', d: '听懂业务语言，识别实体与约束' },
      { icon: 'workflow', t: '规划任务', d: '把目标拆解为可执行步骤' },
      { icon: 'compass', t: '决策选择', d: '按业务规则选择最优路径' },
      { icon: 'zap', t: '执行调用', d: '调用业务能力，稳定执行' },
      { icon: 'activity', t: '反馈评估', d: '结果质量自动评估' },
      { icon: 'layers', t: '学习沉淀', d: '经验入库，越用越聪明' },
    ];
    const nw = 1.52, aw = 0.42, gap = 0.12;
    const totalW = nw * 6 + (aw + gap) * 5;
    let x = M + (CW - totalW) / 2;
    nodes.forEach((nd, i) => {
      const nx = x;
      card(s, { x: nx, y: 2.4, w: nw, h: 2.5, fill: i === 5 ? T.OTINT : T.WHITE, line: i === 5 ? T.ORANGE : T.LINE });
      iconCircle(s, { key: nd.icon, color: i === 5 ? 'orange' : 'blue', x: nx + nw / 2 - 0.34, y: 2.66, d: 0.68, fill: i === 5 ? T.OTINT : T.TINT, shadow: false });
      txt(s, nd.t, { x: nx + 0.06, y: 3.5, w: nw - 0.12, h: 0.36, size: 12.5, bold: true, color: T.INK, align: 'center' });
      txt(s, nd.d, { x: nx + 0.1, y: 3.88, w: nw - 0.2, h: 0.9, size: 9.5, color: T.MUTED, align: 'center', lineSpacing: 1.2 });
      if (i < nodes.length - 1) arrow(s, { x: nx + nw + 0.06, y: 2.4 + 1.14, w: aw, h: 0.26, fill: T.TINT2 });
      x = nx + nw + aw + gap;
    });
    // 回环
    card(s, { x: M + 1.6, y: 5.25, w: CW - 3.2, h: 0.6, fill: T.TINT, line: T.TINT, shadow: false });
    txt(s, '学习沉淀  →  下一次执行更懂你的业务（反馈闭环）', {
      x: M + 1.6, y: 5.25, w: CW - 3.2, h: 0.6, align: 'center', valign: 'middle', size: 12.5, bold: true, color: T.BLUE,
    });
    // 底部三卡
    const bottom = [
      { icon: 'shield', t: '统一治理', d: '权限、策略、审计在所有执行上自动生效' },
      { icon: 'eye', t: '统一可观测', d: 'Trace / 指标 / 日志覆盖每一次执行' },
      { icon: 'refresh', t: '统一补偿', d: '失败重试、回滚由运行时统一保证' },
    ];
    bottom.forEach((b, i) => {
      const bx = M + i * (3.87 + 0.31);
      card(s, { x: bx, y: 6.08, w: 3.87, h: 1.0, fill: T.WHITE, line: T.LINE, shadow: false });
      iconCircle(s, { key: b.icon, color: 'blue', x: bx + 0.16, y: 6.26, d: 0.42, fill: T.TINT, shadow: false });
      txt(s, b.t, { x: bx + 0.7, y: 6.22, w: 1.6, h: 0.3, size: 13, bold: true, color: T.INK });
      txt(s, b.d, { x: bx + 0.7, y: 6.52, w: 3.05, h: 0.5, size: 10, color: T.MUTED, lineSpacing: 1.2 });
    });
    footer(s, 11);
  }
  return S;
};
