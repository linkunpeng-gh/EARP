/**
 * slides_d.js — Part 6/7：行业落地（27-30）+ 合作共赢（31-32）
 */
module.exports = function buildD(pptx, H) {
  const S = [];
  const { T, M, CW, card, txt, chip, iconCircle, header, footer, arrow } = H;

  // ========== S27 工业制造 · 供应链（客户实践） ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '行业落地 · 工业制造 ①', title: '供应链三场景：把人工 Excel 拉锯战变成自动决策', sub: '客户实践 —— 面向制造业供应链的三大高频场景' });
    const items = [
      {
        icon: 'box', t: '库存调拨', scene: '多仓库存余量动态变化，人工协调调拨慢、靠经验拍脑袋。',
        story: '系统自动分析各仓余量、在途与需求，给出调拨建议并生成单据，决策从 1 天缩短到 10 分钟。',
        v: '调拨更快 · 缺货更少',
      },
      {
        icon: 'clipboard', t: '多系统对账', scene: '订单、库存、财务多系统核对靠人工 Excel，错漏难查。',
        story: '自动拉取三方数据比对差异，输出差异清单并自动归因，对账从 3 天缩短到 30 分钟。',
        v: '对账 3 天 → 30 分钟',
      },
      {
        icon: 'truck', t: '物流改派', scene: '运输异常（延迟 / 车辆故障）响应慢，客户体验受损。',
        story: '异常自动识别 → 智能推荐改派方案 → 自动通知客户，响应从小时级缩短到分钟级。',
        v: '响应小时级 → 分钟级',
      },
    ];
    items.forEach((it, i) => {
      const x = M + i * (3.87 + 0.31);
      card(s, { x, y: 2.3, w: 3.87, h: 4.35, fill: T.WHITE, line: T.LINE });
      iconCircle(s, { key: it.icon, color: 'blue', x: x + 0.24, y: 2.54, d: 0.52, fill: T.TINT, shadow: false });
      txt(s, it.t, { x: x + 0.24, y: 3.2, w: 3.4, h: 0.4, size: 16, bold: true, color: T.INK });
      txt(s, it.scene, { x: x + 0.24, y: 3.64, w: 3.42, h: 0.85, size: 11.5, color: T.MUTED, lineSpacing: 1.3 });
      card(s, { x: x + 0.24, y: 4.55, w: 3.4, h: 1.35, fill: T.TINT, line: T.TINT, shadow: false });
      txt(s, '客户实践', { x: x + 0.4, y: 4.7, w: 1.6, h: 0.28, size: 10.5, bold: true, color: T.BLUE });
      txt(s, it.story, { x: x + 0.4, y: 4.98, w: 3.06, h: 0.85, size: 10.5, color: T.BODY, lineSpacing: 1.28 });
      chip(s, { x: x + 0.24, y: 6.1, text: it.v, fill: T.OTINT, color: T.ORANGE_D, size: 10.5, h: 0.34 });
    });
    card(s, { x: M, y: 6.72, w: CW, h: 0.42, fill: T.NAVY, line: T.NAVY, shadow: false });
    txt(s, '把供应链里重复、易错、耗人的环节交给 AI，让人聚焦在异常与决策', {
      x: M, y: 6.72, w: CW, h: 0.42, align: 'center', valign: 'middle', size: 11.5, bold: true, color: T.WHITE,
    });
    footer(s, 27);
  }

  // ========== S28 工业制造 · 生产运营（客户实践） ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '行业落地 · 工业制造 ②', title: '预测性维护与产销协同：设备故障前预警，计划与销售同频', sub: '客户实践 —— 生产运营两大高价值场景' });
    const items = [
      {
        icon: 'gauge', t: '预测性维护', tag: '客户实践',
        scene: '设备非计划停机损失巨大，传统「坏了再修」只能被动救火。',
        story: '基于设备运行数据预测故障窗口，提前安排检修与备件准备，把非计划停机变成计划内检修。',
        v: '非计划停机显著减少 · 备件提前准备',
      },
      {
        icon: 'network', t: '产销协同', tag: '客户实践',
        scene: '销售预测与产能计划脱节：要么缺货丢单，要么积压压资金。',
        story: '销售预测与产能、物料计划自动联动，计划随市场变化动态调整，供需实时对齐。',
        v: '计划响应加快 · 库存周转提升',
      },
    ];
    items.forEach((it, i) => {
      const x = M + i * (6.2 + 0.33);
      card(s, { x, y: 2.3, w: 6.2, h: 4.3, fill: T.WHITE, line: T.LINE });
      iconCircle(s, { key: it.icon, color: 'blue', x: x + 0.26, y: 2.54, d: 0.54, fill: T.TINT, shadow: false });
      txt(s, it.t, { x: x + 0.95, y: 2.56, w: 3, h: 0.4, size: 17, bold: true, color: T.INK });
      chip(s, { x: x + 0.26, y: 3.3, text: it.tag, fill: T.TINT2, color: T.BLUE, size: 10.5, h: 0.3 });
      txt(s, it.scene, { x: x + 0.26, y: 3.72, w: 5.7, h: 0.75, size: 12, color: T.MUTED, lineSpacing: 1.35 });
      s.addShape('line', { x: x + 0.26, y: 4.62, w: 5.68, h: 0, line: { color: T.LINE, width: 1 } });
      txt(s, '落地效果', { x: x + 0.26, y: 4.78, w: 1.6, h: 0.3, size: 11.5, bold: true, color: T.BLUE });
      txt(s, it.story, { x: x + 0.26, y: 5.1, w: 5.7, h: 0.95, size: 12, color: T.BODY, lineSpacing: 1.35 });
      txt(s, '价值  ' + it.v, { x: x + 0.26, y: 6.12, w: 5.7, h: 0.4, size: 13, bold: true, color: T.ORANGE_D });
    });
    footer(s, 28);
  }

  // ========== S29 政务（示例场景） ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '行业落地 · 政务', title: '政务服务：让群众少跑腿，让材料少返工', sub: '示例场景 —— 基于平台能力构建，具体效果以实际项目为准' });
    const items = [
      {
        icon: 'messageText', t: '政策咨询秒答', scene: '政策文件多、更新快，群众高频问题重复咨询，窗口压力大。',
        story: '知识库承载政策原文，高频问题秒级自动答复，人工专注疑难件。',
        v: '应答及时率↑ · 窗口压力↓',
      },
      {
        icon: 'fileCheck', t: '公文与材料辅助', scene: '拟稿耗时、格式易错、要点难提炼，材料反复返工。',
        story: '辅助拟稿、自动格式校验、要点提取，材料质量与效率双提升。',
        v: '返工减少 · 拟稿提效',
      },
      {
        icon: 'listChecks', t: '热线工单智能分派', scene: '工单人工分类派单，语义复杂易派错，处置时效受影响。',
        story: '语义识别自动分类、匹配责任部门，工单直达处置人。',
        v: '派单准确率↑ · 处置更快',
      },
    ];
    items.forEach((it, i) => {
      const x = M + i * (3.87 + 0.31);
      card(s, { x, y: 2.35, w: 3.87, h: 3.9, fill: T.WHITE, line: T.LINE });
      iconCircle(s, { key: it.icon, color: 'blue', x: x + 0.24, y: 2.6, d: 0.52, fill: T.TINT, shadow: false });
      txt(s, it.t, { x: x + 0.24, y: 3.28, w: 3.4, h: 0.4, size: 16, bold: true, color: T.INK });
      txt(s, it.scene, { x: x + 0.24, y: 3.72, w: 3.42, h: 0.9, size: 11.5, color: T.MUTED, lineSpacing: 1.3 });
      txt(s, it.story, { x: x + 0.24, y: 4.66, w: 3.42, h: 1.05, size: 11.5, color: T.BODY, lineSpacing: 1.32 });
      chip(s, { x: x + 0.24, y: 5.78, text: it.v, fill: T.OTINT, color: T.ORANGE_D, size: 10.5, h: 0.34 });
    });
    card(s, { x: M, y: 6.55, w: CW, h: 0.6, fill: T.OTINT, line: T.OTINT, shadow: false });
    txt(s, '示例场景：以上场景基于平台通用能力构建，可按政务客户实际业务定制落地', {
      x: M, y: 6.55, w: CW, h: 0.6, align: 'center', valign: 'middle', size: 12, bold: true, color: T.ORANGE_D,
    });
    footer(s, 29);
  }

  // ========== S30 交通（示例场景） ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '行业落地 · 交通', title: '交通运营：路网监测、出行服务、运营分析一屏掌握', sub: '示例场景 —— 基于平台能力构建，具体效果以实际项目为准' });
    const items = [
      {
        icon: 'route', t: '路网运行监测问答', scene: '拥堵、事故信息分散，管理者难以及时掌握原因。',
        story: '实时路况问答 + 拥堵 / 事故自动归因，指挥调度有据可依。',
        v: '掌握更及时 · 调度更精准',
      },
      {
        icon: 'bus', t: '出行信息服务', scene: '公交地铁信息查询量大，人工客服压力大。',
        story: '实时班次、换乘方案自然语言问答，多渠道自动应答。',
        v: '服务 7×24 · 咨询自助化',
      },
      {
        icon: 'trendDown', t: '运营指标归因', scene: '客流波动原因难定位，运营决策靠经验。',
        story: '客流、准点率等指标自动归因，量化各因素影响程度。',
        v: '归因自动化 · 决策有依据',
      },
    ];
    items.forEach((it, i) => {
      const x = M + i * (3.87 + 0.31);
      card(s, { x, y: 2.35, w: 3.87, h: 3.9, fill: T.WHITE, line: T.LINE });
      iconCircle(s, { key: it.icon, color: 'blue', x: x + 0.24, y: 2.6, d: 0.52, fill: T.TINT, shadow: false });
      txt(s, it.t, { x: x + 0.24, y: 3.28, w: 3.4, h: 0.4, size: 16, bold: true, color: T.INK });
      txt(s, it.scene, { x: x + 0.24, y: 3.72, w: 3.42, h: 0.9, size: 11.5, color: T.MUTED, lineSpacing: 1.3 });
      txt(s, it.story, { x: x + 0.24, y: 4.66, w: 3.42, h: 1.05, size: 11.5, color: T.BODY, lineSpacing: 1.32 });
      chip(s, { x: x + 0.24, y: 5.78, text: it.v, fill: T.OTINT, color: T.ORANGE_D, size: 10.5, h: 0.34 });
    });
    card(s, { x: M, y: 6.55, w: CW, h: 0.6, fill: T.OTINT, line: T.OTINT, shadow: false });
    txt(s, '示例场景：以上场景基于平台通用能力构建，可按交通客户实际业务定制落地', {
      x: M, y: 6.55, w: CW, h: 0.6, align: 'center', valign: 'middle', size: 12, bold: true, color: T.ORANGE_D,
    });
    footer(s, 30);
  }

  // ========== S31 合作模式 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '合作共赢 · 伙伴模式', title: '三种合作方式：让伙伴赚到钱、学得会、卖得动', sub: '按资源禀赋选择合作方式，我们提供全流程支持' });
    const items = [
      {
        icon: 'store', t: '渠道代理', who: '适合：有客户资源、缺 AI 产品的伙伴', d: '产品转售 + 实施服务分成；提供标准产品、报价与售前支持。', tag: '转售与分成' },
      {
        icon: 'handshake', t: '联合方案', who: '适合：深耕行业、有交付能力的集成商', d: '行业解决方案共创、联合投标；平台能力 + 行业 Know-how。', tag: '联合投标' },
      {
        icon: 'puzzle', t: '能力共建', who: '适合：有行业经验的开发者 / ISV', d: '基于 SDK 开发行业能力包，注册上架、全平台复用、共享收益。', tag: '收益共享' },
    ];
    items.forEach((it, i) => {
      const x = M + i * (3.87 + 0.31);
      card(s, { x, y: 2.35, w: 3.87, h: 3.3, fill: T.WHITE, line: T.LINE });
      iconCircle(s, { key: it.icon, color: i === 1 ? 'orange' : 'blue', x: x + 0.24, y: 2.6, d: 0.52, fill: i === 1 ? T.OTINT : T.TINT, shadow: false });
      txt(s, it.t, { x: x + 0.24, y: 3.28, w: 3.4, h: 0.4, size: 16, bold: true, color: T.INK });
      txt(s, it.who, { x: x + 0.24, y: 3.7, w: 3.42, h: 0.4, size: 11, bold: true, color: T.BLUE, lineSpacing: 1.2 });
      txt(s, it.d, { x: x + 0.24, y: 4.18, w: 3.42, h: 1.0, size: 11.5, color: T.BODY, lineSpacing: 1.3 });
      chip(s, { x: x + 0.24, y: 5.24, text: it.tag, fill: T.TINT2, color: T.BLUE, size: 10.5, h: 0.32 });
    });
    // 伙伴支持
    card(s, { x: M, y: 5.9, w: CW, h: 1.15, fill: T.TINT2, line: T.TINT2, shadow: false });
    txt(s, '伙伴全流程支持', { x: M + 0.3, y: 6.06, w: 2.2, h: 0.32, size: 13, bold: true, color: T.INK });
    const sup = ['培训与认证', '样板案例与演示', '联合市场活动', '技术支持与升级'];
    sup.forEach((t2, i) => {
      const w = chip(s, { x: M + 0.3 + i * 2.75, y: 6.5, text: t2, fill: T.WHITE, color: T.BLUE, size: 11, h: 0.36 });
    });
    txt(s, '欢迎洽谈区域合作与联合方案', { x: M + CW - 3.1, y: 6.06, w: 2.8, h: 0.7, size: 13, bold: true, color: T.ORANGE_D, align: 'right', lineSpacing: 1.2 });
    footer(s, 31);
  }

  // ========== S32 结尾（深蓝底） ==========
  {
    const s = pptx.addSlide(); S.push(s);
    s.background = { color: T.NAVY };
    s.addShape('ellipse', { x: 10.2, y: -2.0, w: 5.6, h: 5.6, fill: { color: T.BLUE, transparency: 88 }, line: { color: T.BLUE, width: 0 }, shadow: false });
    s.addShape('ellipse', { x: -1.2, y: 5.6, w: 3.2, h: 3.2, fill: { color: T.BLUE2, transparency: 92 }, line: { color: T.BLUE2, width: 0 }, shadow: false });

    txt(s, '让每一家企业，都能把 AI 用起来', { x: M, y: 0.9, w: 12.2, h: 0.9, size: 34, bold: true, color: T.WHITE });
    txt(s, '可信 · 可控 · 可落地 —— EARP 企业级 AI 操作系统', { x: M, y: 1.85, w: 9, h: 0.4, size: 14.5, color: T.ICE });

    // 三步走
    const steps = [
      { n: '01', t: '试点验证', d: '2–4 周 POC：选定一个高价值场景，快速出结果' },
      { n: '02', t: '核心推广', d: '核心场景正式上线，沉淀标准交付方法' },
      { n: '03', t: '规模化复制', d: '全组织、多场景推广，AI 融入日常经营' },
    ];
    steps.forEach((st, i) => {
      const x = M + i * (4.05 + 0.28);
      card(s, { x, y: 2.6, w: 4.05, h: 1.75, fill: T.NAVY2, line: '3A5AA0', shadow: false });
      txt(s, st.n, { x: x + 0.26, y: 2.8, w: 1.2, h: 0.5, size: 22, bold: true, color: T.ORANGE });
      txt(s, st.t, { x: x + 0.26, y: 3.32, w: 3.5, h: 0.36, size: 15, bold: true, color: T.WHITE });
      txt(s, st.d, { x: x + 0.26, y: 3.72, w: 3.55, h: 0.55, size: 11, color: T.ICE, lineSpacing: 1.25 });
      if (i < 2) txt(s, '→', { x: x + 4.02, y: 3.05, w: 0.35, h: 0.5, size: 20, bold: true, color: T.ICE, align: 'center' });
    });

    // CTA
    card(s, { x: M, y: 4.85, w: CW, h: 1.6, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, '联系我们 · 开启企业 AI 之旅', { x: M + 0.35, y: 5.1, w: 8, h: 0.4, size: 17, bold: true, color: T.WHITE });
    const cta = ['联系电话：138-0000-0000（示例）', '邮箱：contact@earp.example.com（示例）', '官网：www.earp.example.com（示例）'];
    cta.forEach((c2, i) => {
      txt(s, c2, { x: M + 0.35, y: 5.62 + i * 0.26, w: 11, h: 0.26, size: 11.5, color: T.ICE });
    });
    txt(s, 'EARP · Enterprise AI Runtime Platform', { x: M, y: 6.75, w: 6, h: 0.3, size: 10.5, color: T.ICE, charSpacing: 1 });
    txt(s, '32', { x: T.W - M - 0.8, y: 0.55, w: 0.8, h: 0.4, size: 11, color: T.ICE, align: 'right' });
  }
  return S;
};
