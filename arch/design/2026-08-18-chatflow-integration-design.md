# 设计稿（草案）— Chatflow 融入：确定性骨架 + 动态节点

**状态：讨论稿，待评审**
**依据**：Dify Chat vs Chatflow 对比分析（2026-08-18 会话）+ `arch/design/2026-08-18-chat-session-context-design.md`（会话上下文底座）+ EARP 既有编排能力盘点
**日期**：2026-08-18

## 1. 核心思想

**「确定性骨架 + 动态节点」两层模型**：
- **模板层（手工，= Dify Chatflow）**：流程合规/顺序/分支由人画死（复用 orchestrator workflow_dsl）
- **实例层（自动，= QU）**：图内节点可放置 QU（自动理解子问题）——骨架确定，节点动态

Chatflow 不是替代 QU，而是给 QU 套上一层**用户可掌控的确定性外壳**：
> 企业流程「查状态 → 开单 → 人工确认」的顺序是规范；「设备名是什么、查哪台」是 AI 判断。

## 2. 架构定位：chat app 增加编排模式

```
chat_apps.orchestration: 'auto' | 'flow'   （二期字段）
  auto = 现状：QU 理解 → select_plan 自动选策略（一键问答）
  flow = 图驱动：开发者声明的 DAG，逐节点执行（可含 QU/Plan 节点）
```

- 两种模式共用：conversations.context（会话上下文底座）、citations、SSE、审计
- 切换模式不影响历史对话（context 兼容）

## 3. 节点类型设计（对标 Dify + 复用 EARP 既有）

| 节点 | 职责 | 来源 |
|------|------|------|
| Start / End | 图边界 | 新增（轻量） |
| LLM | 生成/流式（chat_stream） | 复用 `connector` |
| Knowledge | 三层检索（软路由/限域） | 复用 `knowledge_search` |
| **QU** | 理解→select_plan→策略执行（plan_fact/relation/aggregation 内置子流程） | 包装 `execute_plan` |
| Capability | 能力调用（含审批/审计/补偿/Saga） | 复用 orchestrator + capability |
| Chat History | 历史注入（context_turns + conversations.context 指代消解） | 复用 `_recent_pairs` |
| Condition | 业务规则分支 | 复用 `workflow_dsl.Conditional` |
| Human Approval | 人工把关（挂起等待确认，SSE 通知） | **新增**（企业场景关键） |
| Tool / MCP | 外部工具 | 复用 `connector` / `mcp` |

## 4. 复用 vs 新增（改动面控制）

**⚠️ 现状核实（2026-08-18）：workflow 引擎是「半成品」**
- `MultiStepExecutor`（执行层：checkpoint/Saga/retry/状态机）✅ 真实可用——直接吃 **Step 列表**（invoke 端点手工拼）
- `workflow_dsl`（声明层：Sequential/Conditional/Parallel + compile_workflow）❌ **死代码**——无任何调用方（无 import/无测试）；Conditional flatten 时两个分支都编译进 Step 列表，运行时 skip 逻辑未实现
- 结论：**当前无「声明式 workflow → 执行」闭环**；Chatflow 前置 F0 真实化（见 §7）

**复用（零/低改动）**：
- `MultiStepExecutor`（checkpoint / Saga 补偿 / retry / 执行状态机）——执行层直接用
- capability 体系（required_permissions + 审批 + 审计 earp.capability.*）
- `connector`（LLM 流式 / json_complete）
- `knowledge_search`（三层检索）与 `execute_plan`（QU 链路）
- conversations.context + citations 落库

**新增（Phase 拆解）**：
- **F0 workflow 真实化**：声明式 JSON schema + compile 接线 MultiStepExecutor + Conditional 求值/分支选择 + 单测（1-2 天）
- flow 模式声明 + DAG schema（JSON，描述即文档）
- 对话节点适配层：Step → 对话节点（输入/输出为对话上下文，非 capability 输入）
- Human Approval 挂起语义（等待 + 恢复 + 超时）
- SSE 执行透传（token 流 + 节点级进度）
- 前端图编辑器（对标 Dify 画布，最小可用：节点拖拽 + 连线 + 配置面板 + 单节点调试）

## 5. 场景示例（企业）

**示例 A：设备维修单（确定性骨架 + QU 节点）**
```
Start → QU（解析「CNC-01 温度异常」→ plan_relation 找设备事实）
      → Capability: query_equipment_status（复用审批/审计）
      → Condition: status == 'faulty' ?
          ├─ yes → Capability: create_maintenance_order（Saga 补偿）
          │       → Human Approval（人工确认派单）
          │       → Capability: notify_owner
          └─ no  → LLM（生成"设备正常"答复）
      → End
```
顺序/审批/通知是规范（手工定死）；「CNC-01 是什么、状态怎么查」是 AI（QU 节点）。

**示例 B：客户投诉分流（规则分支）**
```
Start → Knowledge（查历史投诉）→ Condition: VIP? → 分支话术 → 记录归档
```

## 6. 与 QU / Phase F 的关系

| 层 | 谁设计 | EARP 现状 | 落点 |
|----|--------|-----------|------|
| Plan 模板池（3 策略） | 人 | ✅ 已有 | QU 内置 |
| Plan 实例（选哪个） | 机器 | ✅ 已有 | QU |
| **对话图模板（Chatflow）** | 人 | ❌ 无 | **本设计（F 系列）** |
| 图内节点实例化 | 机器 | — | QU 作为节点 |

- Phase F（通用 DAG）本质 = 把 flow 模式开放为用户可配 + 循环/复杂状态
- 本设计的 F1-F4 是 Phase F 的**确定性最小子集**（无循环、无并行语义，先线性+分支）

## 7. 落地路径（QU 二期后排期）

| Task | 内容 | 依赖 |
|------|------|------|
| **F0** | **workflow 真实化**（前置）：声明式 JSON schema（Sequential/Conditional）+ compile 接线 MultiStepExecutor + Conditional 运行时求值/分支选择 + 单测（顺序/分支/嵌套/空图） | — |
| F1 | migration：chat_apps.orchestration（auto\|flow）+ flow_schema JSONB + 校验（节点类型白名单） | F0 |
| F2 | flow 执行器：DAG JSON → workflow_dsl 编译 → 对话节点适配层（LLM/Knowledge/Chat History/Condition 最小集） | F1 |
| F3 | QU/Plan 节点化（execute_plan 包装为节点）+ Capability 节点（复用审批/审计） | F2 |
| F4 | Human Approval 节点（挂起/恢复/超时/SSE 通知） | F3 |
| F5a | 前端最小可用（**决策门前**）：flow_schema JSON 编辑（textarea + 校验：节点白名单/边可达/无环）+ SVG 只读渲染（复用 entity-graph 思路）+ 节点步进调试（逐节点输入/输出/token） | F2-F4 |
| **决策门** | FDE 真实使用 flow 模式（建 N 个 flow）后评估：拖拽编辑是否为刚需 | F5a |
| F5b | 前端拖拽编辑器（**决策门通过后**）：vendored **Drawflow**（UMD 单文件 ~11KB，DOM 节点内嵌配置表单，MIT）替换 JSON 编辑 + 节点配置面板（LLM prompt + 变量引用选择器 `{{#node.output#}}`、检索参数、条件）+ 拖拽/连线/校验/保存。file:// 直开，不引 React | 决策门 |
| F6 | 评估：flow 模式端到端验证（示例 A/B 场景）+ 会话上下文联动（指代消解在 flow 内生效） | F5 |

## 8. 不做什么（YAGNI）

- 不发明新编排语言——DAG JSON 描述（**图形状直接对齐 Dify/graphon 的 `{nodes:[{id,type,data}], edges:[{source,target}]}`**，ReactFlow 兼容——2026-08-18 决策：预留接口位，无论最终接 Drawflow 还是 ReactFlow，schema 不变）
- 一期无循环节点 / 并行执行 / 复杂会话状态机（Phase F 开放）
- 不把 QU 改手工——auto 模式保持，QU 是图内节点而非被替代
- 不做「图热编辑生效」——flow 修改需重新发布（对齐 chat_apps 发布评审，二期可见范围一并做）
- **一期不引 React/ReactFlow**（破坏 file:// 与 vanilla 栈）；拖拽编辑器候选 = vendored Drawflow（框架无关 UMD 单文件，决策门后）

## 9. 开放问题

1. flow 图与「chat 发布评审/可见范围」（chat 二期）的绑定：flow 变更是否也要审批？倾向：应用级发布评审覆盖 flow_schema 变更（复用 chat_apps 发布状态机）
2. Human Approval 的恢复语义：人工确认是异步回调（MQ/SSE）还是轮询？倾向 SSE 长连接 + 超时降级
3. flow 执行与 executions/checkpoint 的复用度：对话节点是否需要 checkpoint 恢复（跨进程）？倾向一期不接（对话轻量），Phase F 再接

---
**评审后并入 QU 二期 / Phase F 任务书。**
