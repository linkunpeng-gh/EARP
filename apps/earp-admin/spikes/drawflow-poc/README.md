# Drawflow POC — Chatflow 拖拽编辑器候选验证（F5b 前置）

**状态**：POC 完成（2026-08-18），已验证可行，待 F5b 决策门后正式集成
**验证结论**：Drawflow 0.0.60（框架无关 UMD 单文件）满足 EARP 约束——file:// 直开、vanilla 栈、DOM 节点内嵌配置表单、纯 CSS 换肤（亮/暗已做 demo）

## 文件

- `index.html` — 完整 demo（预载维修工单示例 7 节点 + 6 连线；亮/暗主题切换；导出 EARP schema）
- `drawflow.min.js` — vendored 0.0.60（46KB，版本写死）
- `drawflow.min.css` — 基础样式

## Drawflow 0.0.60 API 要点（踩坑记录，勿照旧文档）

1. **必须调 `editor.start()`**——构造函数不再建画布（precanvas null → addNode 崩）；旧文档无此步
2. **构造参数**：`new Drawflow(el)`（第二参是 `render`（Vue），非旧版的 `emit`；纯 JS 不传）
3. **`addNode(name, inputs, outputs, x, y, class, data, html, typenode)`**：
   - `typenode` **不传**（默认 false → 直接用 html 字符串渲染）
   - 传字符串类型名会走 Vue 组件路径（`noderegister[html].options`）——未 registerNode 直接抛错
4. **端口键**：`input_1/output_1/...`（非数字索引）——`addConnection(id_from, id_to, 'output_1', 'input_1')`；条件节点第二输出是 `'output_2'`
5. **导出结构**：`export() → {drawflow:{Home:{data:{<id>:{..., outputs:{'output_1':{connections:[{node, output}]}}}}}}}`（无 edges_out 字段）
6. **面板拖拽**：勿用 HTML5 `draggable`（与库冲突，元素弹回）；用 mousedown 幽灵图 + document mouseup 定位

## EARP schema 映射（已预留 ReactFlow 兼容形状）

```js
// Drawflow export → EARP flow_schema（F1 定稿形状）
{ nodes: [{id, type, data}], edges: [{source, target, sourceHandle, targetHandle}] }
```

无论 F5b 用 Drawflow 还是未来换 ReactFlow，schema 不变。

## 暗色主题

`body.dark` CSS 覆盖 + `toggleTheme()`——纯 CSS 换肤（~20 行），JS 零改动；F5b 集成时用 EARP admin.css 设计令牌替换即可平台统一。

## 已知限制

- 端口固定左右两侧、交互手感由库实现（深度定制需 fork）——编排场景可接受
- 无小地图/对齐线（LogicFlow 有）——如 FDE 反馈需要再评估
- 官方暗色主题文件不在 dist 中（自行 CSS）

## 下一步（F5b，决策门通过后）

1. vendored 进 `apps/earp-admin/vendor/`（版本号写死 + 校验和）
2. EARP 主题（设计令牌）+ 节点配置面板（变量引用选择器 `{{#node.output#}}`）
3. API 适配层 + 冒烟测试（覆盖上面 6 条踩坑点）
