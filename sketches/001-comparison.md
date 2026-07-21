# Dashboard 设计变体对比评审 — 三轮

> **Variant A**: Sidebar Dense (暗色) — `open sketches/001-sidebar-dense/index.html`
> **Variant B**: Topnav Fluid (暗色) — `open sketches/001-topnav-fluid/index.html`
> **Variant C**: Topnav Light (亮色) — `open sketches/002-topnav-light/index.html`

---

## 三向对比

| 维度 | A: Sidebar Dark | B: Topnav Dark | C: Topnav Light |
|:---|:---|:---|:---|
| **导航** | 左侧固定 200px | 顶部粘性 56px | 顶部粘性 56px |
| **内容宽度** | flex:1 全宽 | 1200px 居中 | 1200px 居中 |
| **色系** | 暗色 #08090a | 暗色 #08090a | 亮色 #fafbfc |
| **面板背景** | rgba 半透明 | solid dark | solid white + shadow |
| **信息密度** | 高 | 中 | 中 |
| **CTA 位置** | 内容区顶部按钮 | 右侧 Quick Actions | 标题右侧按钮组 |
| **视觉风格** | IDE/工具感 | 暗色 SaaS | 亮色 SaaS (Stripe-like) |
| **空间效率** | 高（sidebar常驻） | 中（header占56px） | 中 |
| **导航容量** | 无限（可滚动） | 7-8项（再多折行） | 7-8项 |
| **屏幕适配** | 桌面优先 | 响应式友好 | 响应式友好 |
| **品牌辨识度** | 高（暗色记忆点） | 中 | 中（较通用） |
| **现有 mockup 兼容** | ✅ 全兼容 | ❌ 需重构 9 页 | ❌ 需重构 9 页 |

---

## 判断

**如果选 C (Topnav Light)**，需要将 9 个页面全部从侧边栏布局改为顶部导航布局，配色从暗色改为亮色。工作量约 1-2 天。

**如果选 A (Sidebar Dark)**，现有 9 页 mockup 可直接进入开发，零重构。

---

## 建议

等用户查看 C 变体后决策。
