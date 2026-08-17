/**
 * slides_b.js — Part 3：数据智能五件套（12-18）
 */
module.exports = function buildB(pptx, H) {
  const S = [];
  const { T, M, CW, card, txt, chip, iconCircle, header, footer, arrow, painCard } = H;

  /** 底部价值条：3 个橙色数字 + 说明 */
  function valueBand(s, items) {
    card(s, { x: M, y: 6.18, w: CW, h: 0.98, fill: T.TINT2, line: T.TINT2, shadow: false });
    const n = items.length;
    const cw2 = CW / n;
    items.forEach((it, i) => {
      const x = M + i * cw2;
      if (i > 0) s.addShape('line', { x, y: 6.4, w: 0, h: 0.55, line: { color: T.LINE, width: 1 } });
      txt(s, it.num, { x: x + 0.3, y: 6.32, w: cw2 - 0.6, h: 0.42, size: 20, bold: true, color: T.ORANGE, valign: 'middle', lineSpacing: 1 });
      txt(s, it.label, { x: x + 0.3, y: 6.74, w: cw2 - 0.6, h: 0.3, size: 11, color: T.BODY, valign: 'middle', lineSpacing: 1.1 });
    });
  }

  /** 场景 chips 行 */
  function sceneChips(s, list) {
    let x = M;
    list.forEach((t2) => {
      const w = chip(s, { x, y: 2.98, text: t2, fill: T.TINT, color: T.BLUE, size: 11, h: 0.34 });
      x += w + 0.18;
    });
  }

  /** 左栏「是什么」行 */
  function whatLine(s, icon, text) {
    iconCircle(s, { key: icon, color: 'blue', x: M, y: 2.28, d: 0.46, fill: T.TINT, shadow: false });
    txt(s, text, { x: M + 0.62, y: 2.28, w: 6.0, h: 0.55, size: 13.5, bold: true, color: T.INK, lineSpacing: 1.2, valign: 'middle' });
  }

  // ========== S12 双核驱动 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '数据智能 · 设计内核', title: '大模型 + BI 引擎双核驱动：企业问数的正确姿势', sub: '只靠大模型，结果不可控；只靠 BI，交互不自然 —— 双核协同才是企业场景的正解' });
    const cw2 = 5.95;
    // 左：大模型
    card(s, { x: M, y: 2.35, w: cw2, h: 3.1, fill: T.TINT, line: T.TINT });
    iconCircle(s, { key: 'brain', color: 'blue', x: M + 0.3, y: 2.6, d: 0.5, fill: T.WHITE, shadow: false });
    txt(s, '大模型引擎', { x: M + 0.95, y: 2.62, w: 3, h: 0.4, size: 16.5, bold: true, color: T.INK });
    chip(s, { x: M + cw2 - 1.85, y: 2.65, text: '负责理解与表达', fill: T.WHITE, color: T.BLUE, size: 10.5, h: 0.32 });
    txt(s, [
      { text: '听懂自然语言，回答流畅自然', options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } },
      { text: '理解业务语义与对话上下文', options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } },
      { text: '局限：自由生成不可控、算数不可靠、口径难统一', options: { bullet: true } },
    ], { x: M + 0.3, y: 3.3, w: cw2 - 0.6, h: 2.0, size: 13, color: T.BODY, lineSpacing: 1.25 });
    // 右：BI 引擎
    card(s, { x: M + cw2 + 0.33, y: 2.35, w: cw2, h: 3.1, fill: T.WHITE, line: T.BLUE, lineW: 1.5 });
    iconCircle(s, { key: 'database', color: 'orange', x: M + cw2 + 0.63, y: 2.6, d: 0.5, fill: T.OTINT, shadow: false });
    txt(s, 'BI 引擎', { x: M + cw2 + 1.28, y: 2.62, w: 2.5, h: 0.4, size: 16.5, bold: true, color: T.BLUE });
    chip(s, { x: M + cw2 + 0.33 + cw2 - 1.85, y: 2.65, text: '负责计算与校验', fill: T.TINT2, color: T.BLUE, size: 10.5, h: 0.32 });
    txt(s, [
      { text: '精确计算、口径一致、可审计', options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } },
      { text: '权限管控，数据不出域', options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } },
      { text: '局限：交互门槛高，业务人员难上手', options: { bullet: true } },
    ], { x: M + cw2 + 0.63, y: 3.3, w: cw2 - 0.6, h: 2.0, size: 13, color: T.INK, lineSpacing: 1.25 });
    // 中间融合条
    card(s, { x: M, y: 5.72, w: CW, h: 0.75, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, '双核协同 = 自然表达 × 精确计算 × 可信合规 —— 让业务人员放心提问，让数据结果经得起追问', {
      x: M, y: 5.72, w: CW, h: 0.75, align: 'center', valign: 'middle', size: 14.5, bold: true, color: T.WHITE,
    });
    txt(s, '例：问「上个月华东区退货率」→ 大模型听懂意图，BI 引擎按统一口径精确计算，大模型再组织成自然语言回答', {
      x: M, y: 6.62, w: CW, h: 0.4, size: 12, color: T.MUTED, align: 'center',
    });
    footer(s, 12);
  }

  // ========== S13 可信问数 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '数据智能五件套 · 01', title: '业务人员一句话查数：不用写 SQL，指标口径全公司一致', sub: '是什么：以日常语言提问，系统自动解析意图、生成查询、返回可信结果' });
    whatLine(s, 'search', '一句话查数 · 指标口径企业级统一');
    sceneChips(s, ['经营分析会', '销售复盘', '库存盘点', '财务月结']);
    painCard(s, {
      x: M, y: 3.55, w: 6.55, h: 2.4,
      before: '提需求 → 等 IT 排期 → 写 SQL → 各看各的口径，数字对不上（通常 2–3 天）',
      after: '业务人员直接提问，秒级出数；同一指标（如「收入」）财务与销售口径一致，同名不同义被根除',
    });
    // 右栏案例
    const rx = M + 6.85, rw = 5.38;
    card(s, { x: rx, y: 2.28, w: rw, h: 3.67, fill: T.WHITE, line: T.LINE });
    chip(s, { x: rx + 0.24, y: 2.5, text: '客户实践 · 某制造集团财务部', fill: T.TINT2, color: T.BLUE, size: 11, h: 0.32 });
    card(s, { x: rx + 0.24, y: 2.98, w: rw - 0.48, h: 0.62, fill: T.TINT, line: T.TINT, shadow: false });
    txt(s, 'Q  上个月华东区哪个品类的退货率最高？', { x: rx + 0.4, y: 2.98, w: rw - 0.8, h: 0.62, size: 12.5, bold: true, color: T.INK, valign: 'middle', lineSpacing: 1.1 });
    card(s, { x: rx + 0.24, y: 3.72, w: rw - 0.48, h: 1.05, fill: T.OTINT, line: T.OTINT, shadow: false });
    txt(s, 'A  自动识别统一口径（退货率 = 退货金额 ÷ 销售金额），秒级返回：家用电器 3.2%，居华东区首位', {
      x: rx + 0.4, y: 3.86, w: rw - 0.8, h: 0.8, size: 11.5, color: T.INK, lineSpacing: 1.3,
    });
    txt(s, [
      { text: '提数方式：找 IT → 自己问', options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: '口径：各查各的 → 全集团统一', options: { bullet: true } },
    ], { x: rx + 0.24, y: 4.95, w: rw - 0.48, h: 0.85, size: 11.5, color: T.BODY, lineSpacing: 1.25 });
    valueBand(s, [
      { num: '口径统一', label: '消除「同名不同义」' },
      { num: '无需排期', label: '随问随答，秒级出数' },
      { num: '数据授权', label: '只看权限范围内的数' },
    ]);
    footer(s, 13);
  }

  // ========== S14 智能归因 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '数据智能五件套 · 02', title: '销售额下降 12%：不只告诉你「跌了」，更告诉你「为什么」', sub: '是什么：自动定位指标波动的核心维度，量化每个因素的影响程度' });
    whatLine(s, 'sigma', '从「看到问题」到「理解原因」，一步完成');
    sceneChips(s, ['月度经营复盘', '销售波动分析', '成本异常排查']);
    painCard(s, {
      x: M, y: 3.55, w: 6.55, h: 2.4,
      before: '「为什么跌了？」开会各说各话：市场说大环境、销售说价格、财务说成本 —— 归因靠拍脑袋',
      after: '系统自动拆解：客户流失 -5.2%、促销效率 -3.8%、季节性 -2.1%…… 各因素影响度量化、可下钻验证',
    });
    // 右栏：归因分解
    const rx = M + 6.85, rw = 5.38;
    card(s, { x: rx, y: 2.28, w: rw, h: 3.67, fill: T.WHITE, line: T.LINE });
    chip(s, { x: rx + 0.24, y: 2.5, text: '指标波动 · 自动归因示例', fill: T.TINT2, color: T.BLUE, size: 11, h: 0.32 });
    txt(s, '销售额', { x: rx + 0.24, y: 3.0, w: 2, h: 0.35, size: 12, bold: true, color: T.MUTED });
    txt(s, '-12%', { x: rx + 0.24, y: 3.3, w: 2.5, h: 0.6, size: 30, bold: true, color: T.ORANGE });
    txt(s, '环比上月', { x: rx + 2.9, y: 3.5, w: 1.6, h: 0.3, size: 10.5, color: T.MUTED });
    // 分解条
    const segs = [
      { label: '客户流失', v: '-5.2%', w: 1.95, c: T.ORANGE },
      { label: '促销效率下滑', v: '-3.8%', w: 1.42, c: T.BLUE },
      { label: '季节性', v: '-2.1%', w: 0.79, c: T.BLUE2 },
      { label: '其他', v: '-0.9%', w: 0.34, c: T.MUTED },
    ];
    let sx = rx + 0.24;
    segs.forEach((g) => {
      s.addShape('rect', { x: sx, y: 4.18, w: g.w, h: 0.4, fill: { color: g.c }, line: { color: g.c, width: 0 }, shadow: false });
      sx += g.w + 0.06;
    });
    txt(s, segs.map((g, i) => ({ text: `${g.label} ${g.v}`, options: { bullet: false, breakLine: i < segs.length - 1, paraSpaceAfter: 4 } })),
      { x: rx + 0.24, y: 4.7, w: rw - 0.48, h: 1.0, size: 11.5, color: T.BODY, lineSpacing: 1.3 });
    txt(s, '案例：某零售集团月度复盘，1 天人工归因 → 10 分钟自动出结论', {
      x: rx + 0.24, y: 5.7, w: rw - 0.48, h: 0.3, size: 11, color: T.MUTED, lineSpacing: 1.2,
    });
    valueBand(s, [
      { num: '自动下钻', label: '定位波动的核心维度' },
      { num: '量化影响', label: '告别「拍脑袋」归因' },
      { num: '决策聚焦', label: '会议直接给结论' },
    ]);
    footer(s, 14);
  }

  // ========== S15 洞察预测 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '数据智能五件套 · 03', title: '提前三周预判「库存见底」：从被动响应到主动决策', sub: '是什么：基于历史数据的统计建模，输出可执行的前瞻判断 —— 不是玄学，是统计模型' });
    whatLine(s, 'trendUp', '基于历史数据的趋势预判，给决策留出提前量');
    sceneChips(s, ['库存预警', '销售预测', '产能规划']);
    painCard(s, {
      x: M, y: 3.55, w: 6.55, h: 2.4,
      before: '缺货了才补货、积压了才清仓 —— 每次都是紧急补救，损失已经发生',
      after: '提前预警：按当前消耗速度，华东仓 A 产品 21 天后将低于安全库存，今日即可触发补货流程',
    });
    // 右栏：预测曲线
    const rx = M + 6.85, rw = 5.38;
    card(s, { x: rx, y: 2.28, w: rw, h: 3.67, fill: T.WHITE, line: T.LINE });
    chip(s, { x: rx + 0.24, y: 2.5, text: '库存消耗 · 趋势预测', fill: T.TINT2, color: T.BLUE, size: 11, h: 0.32 });
    txt(s, '华东仓 · A 产品', { x: rx + 0.24, y: 2.98, w: 3, h: 0.35, size: 13.5, bold: true, color: T.INK });
    // 曲线区
    const cx = rx + 0.24, cy = 3.5, cw2 = rw - 0.48, ch2 = 1.5;
    // 安全线（虚线）
    s.addShape('line', { x: cx, y: cy + ch2 - 0.22, w: cw2, h: 0, line: { color: T.ORANGE, width: 1.2, dash: 'dash' } });
    txt(s, '安全库存线', { x: cx + cw2 - 1.25, y: cy + ch2 - 0.4, w: 1.25, h: 0.25, size: 8.5, color: T.ORANGE_D, align: 'right' });
    // 下降趋势（三段）
    const p = [
      { x: cx + 0.05, y: cy + 0.1 },
      { x: cx + cw2 * 0.38, y: cy + 0.62 },
      { x: cx + cw2 * 0.68, y: cy + 1.05 },
      { x: cx + cw2 - 0.05, y: cy + ch2 - 0.22 },
    ];
    for (let i = 0; i < p.length - 1; i++) {
      s.addShape('line', { x: p[i].x, y: p[i].y, w: p[i + 1].x - p[i].x, h: p[i + 1].y - p[i].y, line: { color: T.BLUE, width: 2.4 } });
    }
    // 数据点
    [[0, 0], [1, 0], [2, 0], [3, 0]].forEach((q, i) => {
      s.addShape('ellipse', { x: p[i].x - 0.045, y: p[i].y - 0.045, w: 0.09, h: 0.09, fill: { color: T.BLUE }, line: { color: T.WHITE, width: 1 }, shadow: false });
    });
    txt(s, '今日', { x: cx, y: cy + ch2 + 0.06, w: 1.0, h: 0.25, size: 9, color: T.MUTED });
    txt(s, '21 天后', { x: cx + cw2 * 0.68 - 0.35, y: cy + ch2 + 0.06, w: 1.0, h: 0.25, size: 9, bold: true, color: T.ORANGE_D });
    txt(s, '低于安全库存，建议今日触发补货流程', {
      x: rx + 0.24, y: 5.62, w: rw - 0.48, h: 0.3, size: 11.5, bold: true, color: T.BLUE,
    });
    valueBand(s, [
      { num: '提前 21 天', label: '预警，留出决策窗口' },
      { num: '主动决策', label: '从「救火」到「预防」' },
      { num: '减少损失', label: '缺货与积压双降' },
    ]);
    footer(s, 15);
  }

  // ========== S16 一言成报 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '数据智能五件套 · 04', title: '输入一句话，输出一份结构完整的经营分析报告', sub: '是什么：自动提取数据、生成图表、撰写分析结论 —— 从「零」到「成品」' });
    // 顶部流水线
    const steps = [
      { icon: 'mic', t: '一句话需求', d: '“生成上月经营分析报告”' },
      { icon: 'database', t: '自动取数', d: '按指标口径精准取数' },
      { icon: 'barChart', t: '生成图表', d: '趋势、对比、结构图' },
      { icon: 'pen', t: '撰写结论', d: '异常预警 + 经营建议' },
      { icon: 'fileText', t: '成品报告', d: '结构完整、可溯源' },
    ];
    const nw = 2.05, aw = 0.4, gap = 0.1;
    let x = M + (CW - (nw * 5 + (aw + gap) * 4)) / 2;
    steps.forEach((st, i) => {
      card(s, { x, y: 2.3, w: nw, h: 1.85, fill: T.WHITE, line: T.LINE, shadow: false });
      iconCircle(s, { key: st.icon, color: i === 4 ? 'orange' : 'blue', x: x + nw / 2 - 0.26, y: 2.5, d: 0.52, fill: i === 4 ? T.OTINT : T.TINT, shadow: false });
      txt(s, st.t, { x: x + 0.08, y: 3.14, w: nw - 0.16, h: 0.3, size: 11.5, bold: true, color: T.INK, align: 'center' });
      txt(s, st.d, { x: x + 0.1, y: 3.46, w: nw - 0.2, h: 0.6, size: 9, color: T.MUTED, align: 'center', lineSpacing: 1.15 });
      if (i < steps.length - 1) arrow(s, { x: x + nw + 0.04, y: 2.3 + 0.85, w: aw, h: 0.22, fill: T.TINT2 });
      x = x + nw + aw + gap;
    });
    // 案例卡
    card(s, { x: M, y: 4.5, w: CW, h: 1.5, fill: T.TINT, line: T.TINT, shadow: false });
    chip(s, { x: M + 0.28, y: 4.72, text: '客户实践 · 月度经营分析会', fill: T.TINT2, color: T.BLUE, size: 11, h: 0.32 });
    txt(s, [
      { text: '需求：「帮我生成上月经营分析报告」', options: { breakLine: true, paraSpaceAfter: 4 } },
      { text: '结果：10 分钟输出完整报告 —— 收入 / 成本 / 毛利、区域与品类对比、异常预警与经营建议', options: { breakLine: true, paraSpaceAfter: 4 } },
      { text: '不是模板填空，是从数据到结论的自动成文', options: {} },
    ], { x: M + 0.28, y: 5.16, w: CW - 0.56, h: 0.85, size: 12, color: T.BODY, lineSpacing: 1.28 });
    valueBand(s, [
      { num: '1-2 天 → 10 分钟', label: '报告产出效率跃升' },
      { num: '格式统一', label: '结构规范、口径一致' },
      { num: '结论可溯源', label: '每句话都有数据出处' },
    ]);
    footer(s, 16);
  }

  // ========== S17 智策看板 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '数据智能五件套 · 05', title: '会对话、可追问的「活看板」：让数据与决策直接对话', sub: '是什么：智能构建核心指标看板，动态更新、自动解读、可追问下钻' });
    // 左：对比
    card(s, { x: M, y: 2.35, w: 6.55, h: 3.6, fill: T.WHITE, line: T.LINE, shadow: false });
    txt(s, '传统 BI 看板', { x: M + 0.28, y: 2.6, w: 2.8, h: 0.4, size: 15, bold: true, color: T.MUTED });
    txt(s, [
      { text: '静态图表，只能看不能问', options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: '异常要靠人肉发现', options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: '解读靠开会猜，结论难统一', options: { bullet: true } },
    ], { x: M + 0.28, y: 3.1, w: 6.0, h: 1.4, size: 13, color: T.BODY, lineSpacing: 1.3 });
    s.addShape('line', { x: M + 0.28, y: 4.7, w: 6.0, h: 0, line: { color: T.LINE, width: 1 } });
    txt(s, '智策看板', { x: M + 0.28, y: 4.85, w: 2.8, h: 0.4, size: 15, bold: true, color: T.BLUE });
    txt(s, [
      { text: '指标动态更新，随时可追问', options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: '异常自动解读，不用人找', options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: '对话式下钻：问到原因那一层', options: { bullet: true } },
    ], { x: M + 0.28, y: 5.28, w: 6.0, h: 1.2, size: 13, color: T.INK, lineSpacing: 1.3 });
    // 右：对话
    const rx = M + 6.85, rw = 5.38;
    card(s, { x: rx, y: 2.35, w: rw, h: 3.6, fill: T.TINT2, line: T.TINT2, shadow: false });
    chip(s, { x: rx + 0.24, y: 2.58, text: '看板追问 · 对话示例', fill: T.WHITE, color: T.BLUE, size: 11, h: 0.32 });
    card(s, { x: rx + 0.24, y: 3.06, w: rw - 0.48, h: 0.62, fill: T.WHITE, line: T.WHITE, shadow: false });
    txt(s, 'Q  为什么华东区毛利率环比下滑？', { x: rx + 0.4, y: 3.06, w: rw - 0.8, h: 0.62, size: 12.5, bold: true, color: T.INK, valign: 'middle' });
    card(s, { x: rx + 0.24, y: 3.8, w: rw - 0.48, h: 1.5, fill: T.OTINT, line: T.OTINT, shadow: false });
    txt(s, 'A  主要受促销占比提升影响，其中 A 品类促销拉低约 1.2 个百分点；剔除促销影响后环比基本持平。建议关注 A 品类促销力度与毛利平衡。', {
      x: rx + 0.4, y: 3.94, w: rw - 0.8, h: 1.25, size: 11.5, color: T.INK, lineSpacing: 1.35,
    });
    txt(s, '看板从「展示工具」变成「决策助手」', { x: rx + 0.24, y: 5.45, w: rw - 0.48, h: 0.35, size: 11.5, bold: true, color: T.BLUE });
    valueBand(s, [
      { num: '从展示到决策', label: '看板会说话、可追问' },
      { num: '异常秒级解读', label: '不等开会才发现' },
      { num: '追问式下钻', label: '一路问到原因层' },
    ]);
    footer(s, 17);
  }

  // ========== S18 五件套小结 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '数据智能五件套 · 全景串联', title: '五件套串起完整链路：从「问数」到「决策」再到「行动」', sub: '不是五个孤立功能，而是一条贯穿经营决策的业务闭环' });
    const nodes = [
      { icon: 'search', t: '可信问数', d: '快速看清现状' },
      { icon: 'sigma', t: '智能归因', d: '理解波动原因' },
      { icon: 'trendUp', t: '洞察预测', d: '预判风险机会' },
      { icon: 'fileText', t: '一言成报', d: '形成决策材料' },
      { icon: 'dashboard', t: '智策看板', d: '持续追踪验证' },
    ];
    const nw = 2.12, aw = 0.42, gap = 0.1;
    let x = M + (CW - (nw * 5 + (aw + gap) * 4)) / 2;
    nodes.forEach((nd, i) => {
      card(s, { x, y: 2.45, w: nw, h: 1.95, fill: T.WHITE, line: i === 4 ? T.ORANGE : T.LINE, shadow: false });
      iconCircle(s, { key: nd.icon, color: i === 4 ? 'orange' : 'blue', x: x + nw / 2 - 0.28, y: 2.68, d: 0.56, fill: i === 4 ? T.OTINT : T.TINT, shadow: false });
      txt(s, nd.t, { x: x + 0.08, y: 3.38, w: nw - 0.16, h: 0.32, size: 13, bold: true, color: T.INK, align: 'center' });
      txt(s, nd.d, { x: x + 0.1, y: 3.72, w: nw - 0.2, h: 0.55, size: 10, color: T.MUTED, align: 'center', lineSpacing: 1.15 });
      if (i < nodes.length - 1) arrow(s, { x: x + nw + 0.04, y: 2.45 + 0.9, w: aw, h: 0.24, fill: T.TINT2 });
      x = x + nw + aw + gap;
    });
    // 场景串联
    card(s, { x: M, y: 4.85, w: CW, h: 1.5, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, '一个真实工作日的经营闭环', { x: M + 0.35, y: 5.08, w: 4, h: 0.35, size: 13.5, bold: true, color: T.ICE });
    txt(s, '晨会问数 → 归因定位 → 预判风险 → 一键成报 → 看板持续追踪：一条链走完「发现问题 → 理解原因 → 提前应对 → 形成决策 → 验证效果」', {
      x: M + 0.35, y: 5.46, w: 11.6, h: 0.75, size: 13.5, color: T.WHITE, lineSpacing: 1.4,
    });
    card(s, { x: M, y: 6.6, w: CW, h: 0.55, fill: T.OTINT, line: T.OTINT, shadow: false });
    txt(s, '五件套叠加在既有数据底座 / BI 之上 —— 对企业现有投入是「升级」，不是「推倒重来」', {
      x: M, y: 6.6, w: CW, h: 0.55, align: 'center', valign: 'middle', size: 12.5, bold: true, color: T.ORANGE_D,
    });
    footer(s, 18);
  }
  return S;
};
