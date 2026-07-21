# Dashboard 设计变体对比评审

> 两个变体: **Sidebar Dense** vs **Topnav Fluid**
> 打开方式: `open sketches/001-sidebar-dense/index.html` / `open sketches/001-topnav-fluid/index.html`

---

## 对比矩阵

| 维度 | Sidebar Dense | Topnav Fluid |
|:---|:---|:---|
| **导航模式** | 左侧固定 200px 侧边栏 | 顶部粘性导航栏 |
| **内容宽度** | 无限制（flex:1） | 最大 1200px 居中 |
| **信息密度** | 高 — 紧凑表格 + 双列 stat cards | 中 — 大尺寸数字 + 面板布局 |
| **导航容量** | 9 项无压力，可滚动 | 7 项适中，更多会折行 |
| **主 CTA 位置** | 内容区顶部按钮组 | 右侧 Quick Actions 卡片网格 |
| **视觉重心** | 左上品牌 → 左下数据 | 顶部横条 → 中央内容 → 下方面板 |
| **首屏可见信息** | 4 stat cards + 3 行表格 | 4 stat cards + 右侧 Quick Actions（需滚动） |
| **适合屏幕** | 桌面优先，侧边栏固定占用 | 响应式友好，移动端自然折叠 |
| **未来发展** | 侧边栏支持折叠子菜单、搜索框 | 顶部导航支持面包屑、全局搜索 |
| **类似产品** | Linear, VSCode, Supabase | Vercel, Stripe Dashboard, AWS Console |

---

## 我的判断

**Sidebar Dense 更适合 EARP**:

1. **多人开发场景** — EARP 的核心用户是开发者/运维，频繁在 Sessions ↔ Plan ↔ Audit 之间跳转。侧边栏的"常驻可见"模式减少导航认知成本。

2. **导航项数** — 当前 8 个页面 + 未来可能的更多管理页。侧边栏无限垂直空间，顶部导航 7+ 项就会折行或隐藏。

3. **一致性** — Linear、Supabase、Vercel 等开发者工具平台全部使用侧边栏。Topnav 更偏向企业 SaaS（Salesforce, Jira），用户预期不同。

4. **空间效率** — 200px 侧边栏换取全宽内容区，信息密度更高。Dashboard 的 stat cards + recent sessions 表格在 Sidebar 模式下首屏可见更多。

**如果选 Sidebar Dense**，现有的 9 个页面保持不变，只需微调：
- 侧边栏增加当前租户显示
- Dashboard 增加 Recent Sessions 表格（替代 Quick Actions 下方的空白）

**如果选 Topnav Fluid**，需要重构所有页面的导航和布局（约 1-2 天工作量）。

---

## 建议

选 **Sidebar Dense**，进入 Phase 2（串后端）。现有 mockup 已经是这个方向，改动量最小。
