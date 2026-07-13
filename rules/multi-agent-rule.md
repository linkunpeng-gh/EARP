# Multi-Agent Rule — 多 Agent 团队协作规则

> 配合 `loop-engineering.md` 的三层循环架构和 `task-rules.md` 的状态机使用。

---

## 1. 团队模式的约束

- 主 Agent（Orchestrator）可派发多个子 Agent 同步开发
- 一个模块前后端各 1 个 Agent
- 子 Agent 的角色固定为：Impl Agent、Test Agent、Review Agent 等，不可跨角色
- Orchestrator 负责心跳和状态驱动，不参与具体实现

---

## 2. 上下文管理

### 2.1 上下文隔离原则

```
父 Agent 分派任务时，生成的任务上下文必须严格限定：
  ├── 只包含该 Task 需要的 PRD 章节（不要传整份 PRD）
  ├── 只包含该 Task 影响的 L2 规范 MUST 子集
  ├── 只包含该 Task 依赖的接口定义（data contract）
  ├── 包含该 Task 的 acceptance_criteria 原文
  └── 不包含任何其他 Task 的上下文
```

### 2.2 上下文容量约束

- 单次分派上下文不超过 15,000 tokens（含必须的任务模版开销）
- 如果 PRD 章节较大，Orchestrator 需要先做摘要再分派
- 子 Agent 完成后的工作报告须包含：做了什么、修改了哪些文件、测试结果、遗留问题

---

## 3. 任务间通信

### 3.1 通信原则

```
✅ 允许的通信方式：
  - 任务文档（每个 Agent 单独，含 id + status + 工作内容）
  - 接口定义文档（data contract / API spec）
  - 工作报告（子 Agent → Orchestrator）
  - 测试报告（Test Agent → 其他 Agent）
  - 审查报告（Review Agent → Impl Agent）

❌ 禁止的通信方式：
  - 两个 Agent 共同修改同一套代码（代码物理隔离）
  - 直接调用对方的内存/上下文
  - 通过代码注释传递业务信息
```

### 3.2 依赖通知

当 Task A 依赖 Task B 的产出时：
1. Task A 的 `status` 设为 `blocked`，备注依赖 `task-B`
2. Orchestrator 检测到 Task B 状态变 `done` 后，自动将 Task A 恢复为 `backlog` 或 `active`
3. 同时将 Task B 的输出摘要注入 Task A 的上下文

---

## 4. 心跳与进度驱动

### 4.1 Orchestrator 心跳规则

```
每 5 分钟执行一次（规则来自 loop-engineering.md §2.1）：
  1. 读取全部活跃 Task 的状态文档
  2. 逐 Task 检查当前状态 vs 期望状态
  3. 驱动状态机流转（触发对应 Agent 执行下一阶段）
  4. 检查是否有 Task 超时（active > 60min / testing > 30min / review > 60min）
  5. 超时 Task 触发告警，记录到 session-record.md
```

### 4.2 心跳日志格式

```json
{
  "heartbeat_at": "2026-07-12T10:05:00Z",
  "active_tasks": 3,
  "task_states": {
    "TASK-001": "testing",
    "TASK-002": "active",
    "TASK-003": "backlog"
  },
  "alerts": [],
  "next_drive_action": "TASK-002 停留 active 已 45min，无异常"
}
```

---

## 5. Agent 角色与工具解耦

### 5.1 规则层（What）

本规则定义 Agent **职责**，不绑定具体工具：

| Agent | 职责 | 可用的工具类型（示例，非绑定） |
|-------|------|-----------------------------|
| Impl Agent | 写代码、跑测试、修复缺陷 | 编码 CLI / IDE / 测试框架 |
| Test Agent | 执行 MUST 合规测试、UT 覆盖检查 | 测试框架 / 静态分析 |
| Review Agent | 代码审查、安全审查、质量评分 | 审查 CLI / Linter / SAST |
| Docs Agent | 生成文档、更新 CHANGELOG | 文档生成工具 |
| Inte Agent | 跨域回归、接口一致性检查 | 契约测试 / E2E 框架 |
| Arch Agent | 架构影响分析、ADR 起草 | 架构建模工具 |

### 5.2 配置层（How）

具体使用什么工具，在 `rules/` 目录下通过一个工具映射配置文件声明（当前版本不强制，但建议逐步迁移）：

```
rules/tool-mapping.md（可选）
  ├── coding_tool: claude-code / opencode / codex / ...
  ├── review_tool: codex / hermes-review / ...
  ├── test_tool: pytest / vitest / ...
  └── ...
```

---

## 6. 代码合入策略

### 6.1 合入流程

```
1. 子 Agent 完成任务 → commit 到 feature 分支
2. Inte Agent 做跨域回归（如有依赖关系）
3. Review Agent 做最终集成审查
4. Orchestrator 确认所有相关 Task 为 done
5. Gate 1 ✅ → 合入主干（merge / squash）
6. Gate 1 ❌ → 标记相关 Task 回退
```

### 6.2 分支策略

- 每个 Feature 一个 feature 分支
- 每个子 Agent 基于 feature 分支创建子分支（`feature/xxx/agent-impl`）
- 合入顺序：子分支 → feature 分支 → 主干（仅在 Gate 1 ✅ 后）

---

## 7. 异常处理

| 异常场景 | 处理方式 |
|---------|---------|
| Agent A 卡住超过超时阈值 | Orchestrator 告警，尝试重新分派 |
| 两个 Agent 代码冲突 | 升级到 Arch Agent 裁决 |
| 连续 3 次中循环回退 | 升级人工介入 |
| 依赖的 Task 被取消 | 通知依赖方，Task 状态改为 `cancelled` |
| 工具调用失败 | 重试 1 次，失败则切换工具（按 tool-mapping 的备选） |
