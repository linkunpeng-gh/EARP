# 任务清单 — Chatflow F5a: 前端最小可用（JSON 编辑 + SVG 渲染 + 节点调试）

**状态：✅ 已完成（2026-08-21，JSON 编辑器 + SVG 只读渲染 + 节点调试交付；F5b 画布编辑器在决策门前已实现）
**依据**：`arch/design/2026-08-18-chatflow-integration-design.md` §7（F5a：flow_schema JSON 编辑 textarea + 校验 + SVG 只读渲染 + 节点步进调试；决策门前不引 React）
**依赖**：F0-F4 ✅（引擎 + 8 节点类型 + flow 执行 + human_approval 挂起/恢复/超时）
**日期**：2026-08-21

## 目标

1. **编排页 flow 模式**：`chat-edit.html` 加 orchestration 切换（auto/flow）——flow 模式显示流程配置区，FDE 不用写代码就能配置/保存流程图
2. **JSON 编辑 + 实时校验**：textarea 编辑 flow_schema，前端即时校验（节点白名单 / 恰一 start·end / 边引用 / 无环 / condition 分支边），保存时后端门禁兜底（F1 已有）
3. **SVG 只读渲染**：flow_schema → 流程图（纯 vanilla SVG，复用 entity-graph 的 `el()` 模式）——节点类型颜色区分、condition true/false 分支标注
4. **flow 调试对话**：右侧预览支持 flow 执行——发送 → 显示 answer + 逐节点 outputs；**202 waiting_human → 等待确认卡片 + 答复输入**（F4 语义）
5. 零回归：后端零改动（除可能的小端点）；auto 模式编排 UI 零回归

## 现状（已核实，2026-08-21）

- `apps/earp-admin/pages/chat-edit.html`（501 行）：左配置（名称/描述/模型/提示词/KB/检索/生成/轮数）右调试预览；**无 orchestration/flow_schema UI**（F1 前端零改动默认 auto）；`saveApp()` PATCH `/chat_apps/{id}`、`publishApp()` POST `/publish`、右侧 `send()` 流式 chat_sse
- `apps/earp-admin/pages/entity-graph.html`：纯 vanilla SVG 渲染先例（`el()` 建 SVG 节点 + defs 箭头）
- `apps/earp-admin/js/app.js`：`EARP.fetchJSON(url, opts)` API 封装（自动探测 base + JWT）
- `apps/earp-admin/js/nav.js`：workspace 抽屉 `workflow` 目前 `planned` 占位
- 后端（F0-F4 已交付）：`GET/PATCH /chat_apps/{id}` 往返 flow_schema；create/update/publish 均 `validate_flow_schema`（坏图 422）；`POST /chat_apps/{id}/chat` flow 分支非流式 JSON / **202 waiting_human**（F4）；`compile_flow_schema` 对 mcp 仍报未实现
- 基线：383 tests 全绿（F0-F4）

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 入口 | **chat-edit 编排页内 orchestration 切换**（auto/flow 下拉，flow 时展开流程配置区）——应用中心已有入口，不新开页面；workspace/workflow 抽屉保持 planned（独立 flow 管理页 F5b 范畴） |
| D2 | JSON 校验 | **前端 JS 实现** `validate_flow_schema` 移植（节点白名单 / 恰一 start·end / 边引用 / 自环 / 无环(Kahn) / condition 恰 2 出边 true·false / 非 condition 出边 ≤1）——即时反馈；保存时后端门禁兜底（F1 已有，坏图 422 提示） |
| D3 | SVG 渲染 | 纯 vanilla（复用 entity-graph `el()` 模式）：**拓扑分层布局**（start 最左 → end 最右，同层垂直排布），节点按类型着色 + 图标符号，condition 分支边标注 true/false，节点显示 id + 类型名 |
| D4 | 调试对话 | 复用右侧预览：flow 模式发送 → `POST /chat_apps/{id}/chat` → 显示 `answer` + 逐节点 `outputs`（折叠 JSON）；**202 → 等待确认卡片（question）+ 答复输入框**——发送即恢复（同 conversation_id，F4 语义）；手动切 auto 仍走原流式 |
| D5 | 一期不做 | 节点配置表单 / 拖拽连线（F5b 决策门后）；mcp 节点模板（编译仍报错）；SSE 节点级透传 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — orchestration 切换 + flow 配置区（0.5 天）
**文件**：`apps/earp-admin/pages/chat-edit.html`
- 左配置面板加「编排方式」select（auto 问答 / flow 流程）；flow 时显示流程配置区
- 流程配置区：JSON textarea（初始示例模板）+ 校验结果区 + 常用节点示例（LLM/QU/Capability/Tool/Human Approval/Condition 的 JSON 形状帮助）+ 「插入示例」快捷按钮
- `collectConfig()` 加 orchestration/flow_schema；`renderConfig()` 反向填充；`saveApp()` 保存
- 验证：auto→flow→auto 切换保留、坏 JSON 保存被后端 422 拦截提示

### Task 2 — SVG 渲染（0.5-1 天）
**文件**：`apps/earp-admin/js/flow-graph.js`（新）、chat-edit.html 引入
- `renderFlowGraph(schema, container)`：拓扑分层布局（Kahn 排序分 layer）、SVG 节点（类型着色 + 图标）、边（含 condition true/false 标注、箭头 defs）
- 校验通过即实时渲染；校验错误显示错误列表（不渲染或渲染局部）
- 验证：顺序图 / 分支图 / 含 human_approval 全节点图渲染正确

### Task 3 — flow 调试对话（0.5 天）
**文件**：`apps/earp-admin/pages/chat-edit.html`
- `send()` 分支：orchestration=flow → `POST /chat_apps/{id}/chat`（非流式）→ 渲染 answer + 节点 outputs（折叠卡：节点 id → JSON）
- **202 waiting_human** → 等待确认卡（question + 提示「输入内容即答复」）+ 输入框激活；下一轮发送带 `conversation_id` → 恢复 → completed 显示
- 清空对话重置 conversation_id；错误（422 flow 执行失败 / 403 权限）提示
- 验证：auto 流式零回归；flow 正常 / 挂起-恢复 / 坏图 422 / 403

### Task 4 — 保存/加载 + 发布（0.5 天）
**文件**：`apps/earp-admin/pages/chat-edit.html`
- loadApp → renderConfig 填充 orchestration/flow_schema（JSON 格式化展示）
- 保存：flow 模式必须合法 JSON + 通过前端校验；发布门禁（后端已强制重校验）
- 验证：保存→刷新→往返一致；已发布应用编辑 flow → 回 draft 提示（既有逻辑）

### Task 5 — 质量门 + dev 冒烟 + 收尾（0.5 天）
- 后端全量 pytest 零回归（383）+ 前端冒烟（现有 smoke 模式，新 flow 页面手工冒烟）
- dev 真 API：编排页建 flow 应用（qu→capability→tool→llm→human_approval）→ 保存 → 调试（挂起 202 → 答复 → 完成）
- FDE 指南补 F5a 页面说明；session-record 补记 + F5a 标 ✅

## 依赖关系

```
Task 1（编排切换+配置区）→ Task 2（SVG 渲染）→ Task 3（调试对话）→ Task 4（保存/加载）→ Task 5（收尾）
Task 2 依赖 Task 1 的配置区；Task 3 独立于 2 可并行
```

**建议执行序**：`1 → 2 → 3 → 4 → 5`（T2/T3 可并行）

## 验收标准

1. 编排页可切换 auto/flow；flow 模式可编辑 JSON + 实时校验错误提示 + SVG 流程图渲染
2. flow 调试：正常执行显示 answer + 节点 outputs；**human_approval 挂起显示等待卡 → 答复 → 完成**
3. 保存/刷新往返一致；坏 JSON/坏图被前端或后端拦截（不落库）
4. auto 模式编排（流式调试）零回归；后端全量 383 零回归
5. FDE 指南补说明；dev 真 API 冒烟通过

## 风险提示

1. **前端校验与后端一致性**：JS 移植 validate_flow_schema 可能漏项——前端只做「即时提示」，后端门禁是权威（保存 422 提示）；JS 校验过≠后端过
2. **SVG 布局复杂度**：分支图（condition）可能交叉——一期用分层布局 + 直边，不追求美观最优（F5b 拖拽才精细布局）
3. **202 的浏览器 fetch 处理**：fetch 默认 202 走 ok=false（res.ok 为 false 于 2xx？——不，res.ok 是 200-299 为 true）——202 是 2xx，res.ok=true，正常解析 JSON
4. **调试状态**：flow 调试的 conversation_id 在页面会话内维护（localStorage 或内存）——刷新后需重新开始（与 auto 调试一致）
5. **不引外部库**：校验/渲染/布局全 vanilla（file:// 直开约束）

---
**规划定稿，确认后开工。**
