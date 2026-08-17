/**
 * slides_c.js — Part 4/5：平台核心能力（19-23）+ 开放生态（24-26）
 */
module.exports = function buildC(pptx, H) {
  const S = [];
  const { T, M, CW, card, txt, chip, iconCircle, header, footer, arrow, miniCard } = H;

  // ========== S19 知识资产中心 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '平台核心 · 知识资产中心', title: '让 AI 基于企业自己的知识作答：答案有出处、可溯源', sub: '是什么：企业文档 + 业务实体图谱 双知识体系，三层检索融合，回答可引用溯源' });
    // 左：双知识体系
    card(s, { x: M, y: 2.3, w: 6.2, h: 2.2, fill: T.WHITE, line: T.LINE });
    txt(s, '双知识体系', { x: M + 0.26, y: 2.52, w: 3, h: 0.4, size: 14.5, bold: true, color: T.INK });
    card(s, { x: M + 0.26, y: 3.0, w: 2.75, h: 1.3, fill: T.TINT, line: T.TINT, shadow: false });
    iconCircle(s, { key: 'book', color: 'blue', x: M + 0.42, y: 3.16, d: 0.4, fill: T.WHITE, shadow: false });
    txt(s, '文档知识', { x: M + 0.9, y: 3.18, w: 2, h: 0.3, size: 12.5, bold: true, color: T.BLUE });
    txt(s, '制度 / 手册 / 流程 / 报告', { x: M + 0.42, y: 3.55, w: 2.45, h: 0.65, size: 10.5, color: T.BODY, lineSpacing: 1.2 });
    card(s, { x: M + 3.19, y: 3.0, w: 2.75, h: 1.3, fill: T.OTINT, line: T.OTINT, shadow: false });
    iconCircle(s, { key: 'network', color: 'orange', x: M + 3.35, y: 3.16, d: 0.4, fill: T.WHITE, shadow: false });
    txt(s, '实体图谱', { x: M + 3.83, y: 3.18, w: 2, h: 0.3, size: 12.5, bold: true, color: T.ORANGE_D });
    txt(s, '设备 / 供应商 / 客户 / 关系', { x: M + 3.35, y: 3.55, w: 2.45, h: 0.65, size: 10.5, color: T.BODY, lineSpacing: 1.2 });
    // 三层检索
    card(s, { x: M, y: 4.72, w: 6.2, h: 2.15, fill: T.TINT2, line: T.TINT2, shadow: false });
    txt(s, '三层检索 · 融合回答', { x: M + 0.26, y: 4.94, w: 4, h: 0.35, size: 14.5, bold: true, color: T.INK });
    const layers = [
      { icon: 'userCheck', t: '实体档案', d: '快速命中事实摘要' },
      { icon: 'network', t: '关系图谱', d: '多跳展开业务关系' },
      { icon: 'fileText', t: '文档原文', d: '标准流程与细则' },
    ];
    layers.forEach((l, i) => {
      const x = M + 0.26 + i * 1.95;
      card(s, { x, y: 5.42, w: 1.8, h: 1.25, fill: T.WHITE, line: T.WHITE, shadow: false });
      iconCircle(s, { key: l.icon, color: 'blue', x: x + 0.12, y: 5.55, d: 0.36, fill: T.TINT, shadow: false });
      txt(s, l.t, { x: x + 0.12, y: 5.98, w: 1.56, h: 0.28, size: 11, bold: true, color: T.INK, align: 'center' });
      txt(s, l.d, { x: x + 0.12, y: 6.26, w: 1.56, h: 0.35, size: 9, color: T.MUTED, align: 'center', lineSpacing: 1.1 });
    });
    // 右：案例
    const rx = M + 6.5, rw = 5.73;
    card(s, { x: rx, y: 2.3, w: rw, h: 4.57, fill: T.WHITE, line: T.LINE });
    chip(s, { x: rx + 0.26, y: 2.54, text: '客户实践 · 设备维护知识问答', fill: T.TINT2, color: T.BLUE, size: 11, h: 0.32 });
    card(s, { x: rx + 0.26, y: 3.04, w: rw - 0.52, h: 0.6, fill: T.TINT, line: T.TINT, shadow: false });
    txt(s, 'Q  新员工：CNC 设备报警后应该怎么处理？', { x: rx + 0.42, y: 3.04, w: rw - 0.84, h: 0.6, size: 12, bold: true, color: T.INK, valign: 'middle' });
    card(s, { x: rx + 0.26, y: 3.76, w: rw - 0.52, h: 1.75, fill: T.OTINT, line: T.OTINT, shadow: false });
    txt(s, 'A  返回：标准处理流程（停机 → 报警代码识别 → 联系供应商 → 记录）＋ 该设备档案（型号 / 维保记录）＋ 原文出处（《设备运维手册》第 4 章）', {
      x: rx + 0.42, y: 3.9, w: rw - 0.84, h: 1.5, size: 11.5, color: T.INK, lineSpacing: 1.35,
    });
    txt(s, [
      { text: '回答有出处：每条结论可回溯到原文', options: { bullet: true, breakLine: true, paraSpaceAfter: 7 } },
      { text: '知识不流失：老师傅经验沉淀为资产', options: { bullet: true, breakLine: true, paraSpaceAfter: 7 } },
      { text: '权限贯穿：无权限域的文档/实体不可见', options: { bullet: true } },
    ], { x: rx + 0.26, y: 5.7, w: rw - 0.52, h: 1.05, size: 12, color: T.BODY, lineSpacing: 1.3 });
    footer(s, 19);
  }

  // ========== S20 智能体编排 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '平台核心 · 智能体编排', title: '复杂任务自动拆解、可靠执行：断点续跑、失败重试、事务补偿', sub: '是什么：一句话任务自动规划为多步执行，可靠性由运行时统一保障' });
    // 左：可靠四卡
    const cards = [
      { icon: 'refresh', t: '断点续跑', d: '执行中断后从检查点恢复，不重头再来' },
      { icon: 'refreshCw', t: '自动重试', d: '网络抖动等瞬时故障自动重试，无需人工介入' },
      { icon: 'clock', t: '超时熔断', d: '单步超时或异常自动熔断，避免任务挂死' },
      { icon: 'route', t: '事务补偿', d: '多步失败自动回滚已执行动作，不留脏数据' },
    ];
    cards.forEach((c, i) => {
      const x = M + (i % 2) * (6.2 + 0.33), y = 2.35 + Math.floor(i / 2) * (1.5 + 0.26);
      card(s, { x, y, w: 6.2, h: 1.5, fill: T.WHITE, line: T.LINE, shadow: false });
      iconCircle(s, { key: c.icon, color: 'blue', x: x + 0.22, y: y + 0.2, d: 0.44, fill: T.TINT, shadow: false });
      txt(s, c.t, { x: x + 0.8, y: y + 0.18, w: 2.4, h: 0.32, size: 14, bold: true, color: T.INK });
      txt(s, c.d, { x: x + 0.8, y: y + 0.52, w: 5.2, h: 0.85, size: 11.5, color: T.BODY, lineSpacing: 1.3 });
    });
    // 右：案例
    const rx = M + 6.5, rw = 5.73;
    card(s, { x: rx, y: 2.35, w: rw, h: 3.26, fill: T.TINT2, line: T.TINT2, shadow: false });
    chip(s, { x: rx + 0.26, y: 2.58, text: '客户实践 · 多系统对账', fill: T.WHITE, color: T.BLUE, size: 11, h: 0.32 });
    txt(s, '一句话：完成本月订单、库存、财务三方对账', { x: rx + 0.26, y: 3.05, w: rw - 0.52, h: 0.4, size: 13, bold: true, color: T.INK });
    const flow = ['① 拉取订单数据', '② 核对库存记录', '③ 比对财务凭证'];
    let fx = rx + 0.26;
    flow.forEach((f, i) => {
      chip(s, { x: fx, y: 3.55, text: f, fill: T.WHITE, color: T.BLUE, size: 10.5, h: 0.34, w: 1.55 });
      fx += 1.6 + 0.12;
    });
    txt(s, '任一步失败 → 自动重试 → 仍失败则补偿回滚，对账结论不留半成品；人工核对 3 天 → 系统 30 分钟出差异清单', {
      x: rx + 0.26, y: 4.1, w: rw - 0.52, h: 1.4, size: 12, color: T.BODY, lineSpacing: 1.35,
    });
    // 底部价值
    card(s, { x: M, y: 5.95, w: CW, h: 1.15, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, '长任务不用盯 · 失败不重跑 · 账务不出错', { x: M + 0.4, y: 6.08, w: 6, h: 0.4, size: 15.5, bold: true, color: T.WHITE });
    txt(s, '多步任务全自动推进，可靠性由平台兜底 —— 交付给业务的是「结果」，不是「流程」', { x: M + 0.4, y: 6.52, w: 11.4, h: 0.4, size: 12, color: T.ICE });
    footer(s, 20);
  }

  // ========== S21 多模型接入 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '平台核心 · 多模型接入', title: '按场景自由选模型：一套平台调度所有模型，不被单一厂商绑定', sub: '是什么：统一接入多家大模型，按任务类型智能路由，模型升级不影响业务' });
    const cards = [
      { icon: 'messageText', t: '对话问答', d: '通用对话、客服问答 —— 选均衡型模型，成本与效果兼顾' },
      { icon: 'workflow', t: '结构化规划', d: '任务拆解、意图识别 —— 选推理型模型，输出需稳定可控' },
      { icon: 'book', t: '长文档理解', d: '合同、手册、报告分析 —— 选长上下文模型，支持大文档' },
      { icon: 'terminal', t: '代码与工具调用', d: '生成查询、调用接口 —— 选工具调用能力强的模型' },
    ];
    cards.forEach((c, i) => {
      const x = M + (i % 2) * (6.2 + 0.33), y = 2.35 + Math.floor(i / 2) * (1.72 + 0.26);
      card(s, { x, y, w: 6.2, h: 1.72, fill: T.WHITE, line: T.LINE });
      iconCircle(s, { key: c.icon, color: 'blue', x: x + 0.24, y: y + 0.24, d: 0.48, fill: T.TINT, shadow: false });
      txt(s, c.t, { x: x + 0.9, y: y + 0.24, w: 3, h: 0.36, size: 14.5, bold: true, color: T.INK });
      txt(s, c.d, { x: x + 0.9, y: y + 0.64, w: 5.1, h: 0.95, size: 11.5, color: T.BODY, lineSpacing: 1.3 });
    });
    // 底部价值
    card(s, { x: M, y: 6.1, w: CW, h: 0.95, fill: T.TINT2, line: T.TINT2, shadow: false });
    txt(s, [
      { text: '模型升级不重构业务：切换模型只动配置', options: { breakLine: true, paraSpaceAfter: 5 } },
      { text: '成本按场景优化：简单任务不浪费大模型算力', options: { breakLine: true, paraSpaceAfter: 5 } },
      { text: '支持私有化部署：数据不出企业边界', options: {} },
    ], { x: M + 0.35, y: 6.22, w: 8.5, h: 0.85, size: 12, color: T.BODY, lineSpacing: 1.28 });
    chip(s, { x: M + 9.3, y: 6.3, text: '兼容 Ollama / 云端 API / 私有化', fill: T.WHITE, color: T.BLUE, size: 11, h: 0.38 });
    footer(s, 21);
  }

  // ========== S22 安全治理 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '平台核心 · 安全治理', title: '企业级安全合规：租户隔离、分级权限、全链路审计、数据脱敏', sub: '是什么：安全不是功能插件，而是内建于运行时的默认能力' });
    const cards = [
      { icon: 'building', t: '租户级隔离', d: '数据在存储层强隔离：A 部门看不到 B 部门的数据，多租户互不越界。', tag: '数据不出界' },
      { icon: 'userCheck', t: '分级权限', d: '按角色与数据范围控制「能看什么、能做什么」：查询只读、命令必经审批。', tag: '权限精细化' },
      { icon: 'clipboard', t: '全链路审计', d: '每一次 AI 执行自动留痕：谁、何时、问了什么、做了什么，可追溯可复盘。', tag: '过程可追溯' },
      { icon: 'lock', t: '数据安全', d: '凭证加密存储、输出脱敏处理、敏感信息自动保护，防止数据外泄。', tag: '信息不外泄' },
    ];
    cards.forEach((c, i) => {
      const x = M + (i % 2) * (6.2 + 0.33), y = 2.35 + Math.floor(i / 2) * (2.05 + 0.26);
      card(s, { x, y, w: 6.2, h: 2.05, fill: T.WHITE, line: T.LINE });
      iconCircle(s, { key: c.icon, color: 'blue', x: x + 0.26, y: y + 0.24, d: 0.5, fill: T.TINT, shadow: false });
      txt(s, c.t, { x: x + 0.95, y: y + 0.26, w: 3.4, h: 0.36, size: 15, bold: true, color: T.INK });
      txt(s, c.d, { x: x + 0.26, y: y + 0.86, w: 5.7, h: 0.85, size: 12, color: T.BODY, lineSpacing: 1.35 });
      chip(s, { x: x + 0.26, y: y + 1.62, text: c.tag, fill: T.TINT2, color: T.BLUE, size: 10.5, h: 0.3 });
    });
    card(s, { x: M, y: 6.6, w: CW, h: 0.55, fill: T.OTINT, line: T.OTINT, shadow: false });
    txt(s, '满足等保、内审与监管留痕要求 —— 业务敢用，审计敢放行', {
      x: M, y: 6.6, w: CW, h: 0.55, align: 'center', valign: 'middle', size: 13, bold: true, color: T.ORANGE_D,
    });
    footer(s, 22);
  }

  // ========== S23 自动化调度 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '平台核心 · 自动化调度', title: '定时任务与事件触发：让 AI 7×24 小时自动运转', sub: '是什么：把重复性分析固化为自动任务，从「人找 AI」到「AI 找人」' });
    // 左：两种触发
    const left = [
      { icon: 'calendar', t: '定时调度', d: '每日经营日报 / 每周库存预警 / 每月分析报告，到点自动执行并推送', fill: T.TINT, ic: 'blue' },
      { icon: 'zap', t: '事件驱动', d: '系统报警、数据异常、审批回调 —— 事件一发生，自动归因并通知责任人', fill: T.OTINT, ic: 'orange' },
    ];
    left.forEach((l, i) => {
      const x = M, y = 2.35 + i * 1.95;
      card(s, { x, y, w: 6.2, h: 1.78, fill: T.WHITE, line: T.LINE, shadow: false });
      iconCircle(s, { key: l.icon, color: l.ic, x: x + 0.26, y: y + 0.24, d: 0.5, fill: l.fill, shadow: false });
      txt(s, l.t, { x: x + 0.95, y: y + 0.26, w: 3, h: 0.36, size: 15, bold: true, color: T.INK });
      txt(s, l.d, { x: x + 0.26, y: y + 0.82, w: 5.7, h: 0.85, size: 12, color: T.BODY, lineSpacing: 1.3 });
    });
    // 右：案例
    const rx = M + 6.5, rw = 5.73;
    card(s, { x: rx, y: 2.35, w: rw, h: 3.68, fill: T.TINT2, line: T.TINT2, shadow: false });
    chip(s, { x: rx + 0.26, y: 2.58, text: '客户实践 · 自动化运营', fill: T.WHITE, color: T.BLUE, size: 11, h: 0.32 });
    txt(s, [
      { text: '每天 08:00：自动生成前一日经营日报，推送给管理层', options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
      { text: '库存低于安全阈值：自动触发补货建议并通知采购', options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
      { text: '设备报警：自动归因 → 关联知识库 → 生成处置建议', options: { bullet: true } },
    ], { x: rx + 0.26, y: 3.1, w: rw - 0.52, h: 2.4, size: 12.5, color: T.BODY, lineSpacing: 1.4 });
    txt(s, '报表不再「等人要」，异常不再「等发现」', { x: rx + 0.26, y: 5.5, w: rw - 0.52, h: 0.4, size: 13, bold: true, color: T.BLUE });
    footer(s, 23);
  }

  // ========== S24 五大 SDK ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '开放生态 · 开发者能力', title: '五大 SDK + 能力即插即用：伙伴三天开发一个新能力', sub: '是什么：面向开发者与伙伴的标准开发套件，能力封装、注册、上线全流程开放' });
    const sdks = [
      { en: 'Capability', t: '能力开发 SDK', d: '把业务逻辑封装为标准「能力」，注册即用', icon: 'puzzle' },
      { en: 'Connector', t: '连接器 SDK', d: '对接 REST / 数据库 / MCP 等存量系统', icon: 'link' },
      { en: 'Runtime', t: '运行时 SDK', d: '让应用快速接入运行时，拿到执行能力', icon: 'zap' },
      { en: 'Plugin', t: '插件 SDK', d: '沙箱化插件，安全隔离、独立发布', icon: 'pkg' },
      { en: 'Core', t: '公共能力 SDK', d: '审计 / 脱敏 / 配置等公共件开箱即用', icon: 'box' },
    ];
    const cw2 = 2.28, gap = 0.18;
    sdks.forEach((sd, i) => {
      const x = M + i * (cw2 + gap);
      card(s, { x, y: 2.35, w: cw2, h: 2.6, fill: T.WHITE, line: T.LINE });
      iconCircle(s, { key: sd.icon, color: i === 2 ? 'orange' : 'blue', x: x + cw2 / 2 - 0.3, y: 2.62, d: 0.6, fill: i === 2 ? T.OTINT : T.TINT, shadow: false });
      txt(s, sd.en, { x: x + 0.1, y: 3.4, w: cw2 - 0.2, h: 0.3, size: 10.5, bold: true, color: T.BLUE, align: 'center', charSpacing: 0.5 });
      txt(s, sd.t, { x: x + 0.12, y: 3.72, w: cw2 - 0.24, h: 0.36, size: 13, bold: true, color: T.INK, align: 'center' });
      txt(s, sd.d, { x: x + 0.16, y: 4.12, w: cw2 - 0.32, h: 0.75, size: 10, color: T.MUTED, align: 'center', lineSpacing: 1.25 });
    });
    // 生态价值
    card(s, { x: M, y: 5.3, w: CW, h: 1.75, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, '伙伴生态的价值', { x: M + 0.35, y: 5.52, w: 3.5, h: 0.35, size: 13.5, bold: true, color: T.ICE });
    txt(s, [
      { text: '行业伙伴把自身能力封装为「能力包」，注册即上架，全平台复用', options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: '三天一个能力：模板 + 示例 + 测试工具，开箱即开发', options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: '能力即资产：一次开发，多客户复用，边际成本趋近于零', options: { bullet: true } },
    ], { x: M + 0.35, y: 5.92, w: 11.6, h: 1.0, size: 12.5, color: T.WHITE, lineSpacing: 1.3 });
    footer(s, 24);
  }

  // ========== S25 插件与 MCP ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '开放生态 · 系统集成', title: '无缝对接企业存量系统：ERP、MES、政务系统一次接通', sub: '是什么：标准连接器 + MCP 协议 + 插件沙箱，不推倒重来，存量系统即插即用' });
    // 中心
    card(s, { x: M + 3.4, y: 2.4, w: 4.0, h: 1.7, fill: T.BLUE, line: T.BLUE, shadow: false });
    iconCircle(s, { key: 'zap', color: 'white', x: M + 3.7, y: 2.68, d: 0.52, fill: T.BLUE2, shadow: false });
    txt(s, 'EARP 运行时', { x: M + 4.35, y: 2.7, w: 2.6, h: 0.36, size: 15, bold: true, color: T.WHITE });
    txt(s, '统一接入 · 统一治理 · 统一审计', { x: M + 3.6, y: 3.3, w: 3.6, h: 0.6, size: 10.5, color: T.ICE, align: 'center', lineSpacing: 1.25 });
    // 四类连接方式
    const ways = [
      { icon: 'plug', t: 'REST 连接器', d: '对接 API 类系统' },
      { icon: 'database', t: '数据库连接器', d: '直连业务库表' },
      { icon: 'link', t: 'MCP 协议', d: 'MCP 生态即插即用' },
      { icon: 'pkg', t: '插件沙箱', d: '隔离执行第三方插件' },
    ];
    ways.forEach((w2, i) => {
      const x = M + (i % 2) * (6.2 + 0.33), y = 4.35 + Math.floor(i / 2) * (1.32 + 0.22);
      card(s, { x, y, w: 6.2, h: 1.32, fill: T.WHITE, line: T.LINE, shadow: false });
      iconCircle(s, { key: w2.icon, color: 'blue', x: x + 0.24, y: y + 0.2, d: 0.44, fill: T.TINT, shadow: false });
      txt(s, w2.t, { x: x + 0.82, y: y + 0.18, w: 2.6, h: 0.32, size: 13.5, bold: true, color: T.INK });
      txt(s, w2.d, { x: x + 0.82, y: y + 0.52, w: 5.2, h: 0.7, size: 11, color: T.MUTED, lineSpacing: 1.25 });
    });
    // 底部
    card(s, { x: M, y: 6.32, w: CW, h: 0.72, fill: T.TINT2, line: T.TINT2, shadow: false });
    txt(s, '典型接入对象：ERP / SAP / MES / 数据库 / 政务平台 / 各类 SaaS —— 一次接通，长期复用', {
      x: M, y: 6.32, w: CW, h: 0.72, align: 'center', valign: 'middle', size: 12.5, bold: true, color: T.BLUE,
    });
    footer(s, 25);
  }

  // ========== S26 可观测闭环 ==========
  {
    const s = pptx.addSlide(); S.push(s);
    header(s, { kicker: '开放生态 · 持续进化', title: '全程可观测 + 反馈学习：系统越用越懂你的业务', sub: '是什么：每次执行全程留痕，结果反馈进入学习机制，闭环驱动能力进化' });
    // 左侧：观测三要素
    card(s, { x: M, y: 2.35, w: 6.2, h: 3.3, fill: T.WHITE, line: T.LINE, shadow: false });
    txt(s, '全程可观测', { x: M + 0.28, y: 2.6, w: 3, h: 0.4, size: 15, bold: true, color: T.INK });
    const obs = [
      { icon: 'eye', t: 'Trace 链路', d: '一次任务的每一步执行路径全程可见' },
      { icon: 'activity', t: '指标与日志', d: '执行耗时、成功率、失败原因自动采集' },
      { icon: 'clipboard', t: '行为留痕', d: 'AI 做了什么、为什么这么做，可解释可复盘' },
    ];
    obs.forEach((o, i) => {
      const y = 3.15 + i * 0.78;
      iconCircle(s, { key: o.icon, color: 'blue', x: M + 0.28, y, d: 0.42, fill: T.TINT, shadow: false });
      txt(s, o.t, { x: M + 0.85, y, w: 2.2, h: 0.3, size: 12.5, bold: true, color: T.INK });
      txt(s, o.d, { x: M + 0.85, y: y + 0.3, w: 5.1, h: 0.4, size: 10.5, color: T.MUTED, lineSpacing: 1.2 });
    });
    // 右侧：学习闭环
    card(s, { x: M + 6.5, y: 2.35, w: 5.73, h: 3.3, fill: T.TINT2, line: T.TINT2, shadow: false });
    txt(s, '反馈学习闭环', { x: M + 6.78, y: 2.6, w: 3, h: 0.4, size: 15, bold: true, color: T.INK });
    const loop = [
      { icon: 'zap', t: '执行', d: '任务完成并产出结果' },
      { icon: 'star', t: '反馈', d: '用户评价 + 结果质量' },
      { icon: 'activity', t: '评估', d: '自动评估效果好坏' },
      { icon: 'layers', t: '沉淀', d: '经验写入记忆与知识' },
    ];
    loop.forEach((l, i) => {
      const x = M + 6.78 + (i % 2) * 2.75, y = 3.15 + Math.floor(i / 2) * 1.15;
      card(s, { x, y, w: 2.6, h: 1.0, fill: T.WHITE, line: T.WHITE, shadow: false });
      iconCircle(s, { key: l.icon, color: 'orange', x: x + 0.14, y: y + 0.12, d: 0.38, fill: T.OTINT, shadow: false });
      txt(s, l.t, { x: x + 0.6, y: y + 0.12, w: 1.9, h: 0.3, size: 12, bold: true, color: T.INK });
      txt(s, l.d, { x: x + 0.14, y: y + 0.52, w: 2.35, h: 0.42, size: 9.5, color: T.MUTED, lineSpacing: 1.15 });
      if (i === 1 || i === 3) arrow(s, { x: x + 2.6 - 0.02, y: y + 0.32, w: 0.3, h: 0.2, fill: T.TINT2 });
      if (i === 2) arrow(s, { x: x + 0.02, y: y - 0.26, w: 0.3, h: 0.2, fill: T.TINT2 });
    });
    txt(s, '第 100 次执行，比第 1 次更懂你的业务', { x: M + 6.78, y: 5.5, w: 5.0, h: 0.35, size: 13, bold: true, color: T.BLUE });
    // 底部
    card(s, { x: M, y: 6.0, w: CW, h: 1.05, fill: T.BLUE, line: T.BLUE, shadow: false });
    txt(s, '每一次执行都在沉淀：从「能用」到「好用」，从「通用」到「懂你」', {
      x: M, y: 6.0, w: CW, h: 1.05, align: 'center', valign: 'middle', size: 15, bold: true, color: T.WHITE,
    });
    footer(s, 26);
  }
  return S;
};
