# Loop Engineering — EARP 自动开发循环机制

> **定位**：定义 EARP 开发流水线的循环架构，包括外循环（Feature Pipeline）、内循环（质量反馈）、心跳机制和状态机。
> **版本**：v1.0
> **设计参考**：OODA Loop（Observe-Orient-Decide-Act）、PDCA（Plan-Do-Check-Act）、Agentic Reflection Loop、DevOps Continuous Delivery Loop

---

## 1. 核心概念：三层循环架构

```
┌─────────────────────────────────────────────────────────────┐
│                    外循环（Outer Loop）                       │
│  Phase 0 → Gate 0 → Phase 1-5 → Gate 1 → Phase 6 → (反馈)  │
│                                                             │
│   ┌─────────────────────────┐   ┌─────────────────────────┐ │
│   │    中循环（Mid Loop）     │   │    中循环（Mid Loop）     │ │
│   │  Phase 3 → Phase 4      │   │  Phase 4 → Phase 3      │ │
│   │  (Implement → Test)     │   │  (Review → Fix)         │ │
│   │        ↓         ↑      │   │        ↓         ↑      │ │
│   │   ┌───────────┐         │   │   ┌───────────┐         │ │
│   │   │ 内循环     │         │   │   │ 内循环     │         │ │
│   │   │ 写-测-修   │         │   │   │ 审-修-再审 │         │ │
│   │   └───────────┘         │   │   └───────────┘         │ │
│   └─────────────────────────┘   └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 外循环（Outer Loop）— Feature 级生命周期

| 循环阶段 | 负责 Agent | 产出 | 门禁 |
|----------|-----------|------|------|
| Phase 0 | PM Agent | PRD + 验收条件 | — |
| **Gate 0** | PM + 架构师 + 域主程 | ✅ PRD 验收签名 | **硬门禁** |
| Phase 1 | Arch Agent | 影响范围报告 / ADR | — |
| Phase 2 | Spec Agent | L2 规范更新 + MUST | — |
| Phase 3 | Impl Agent | 代码 + UT | — |
| Phase 4 | Test + Review Agent | 测试报告 + 审查报告 | 质量评分 ≥ 8 |
| Phase 5 | Inte + Docs Agent | 集成报告 + 文档 | — |
| **Gate 1** | PM + 测试 | ✅ 发布验收签名 | **硬门禁** |
| Phase 6 | 全部 Agent | 指标 + 反馈 | — |

**外循环触发条件**：
- Gate 0 ✅ → 自动进入 Phase 1
- Phase N 完成 → 自动进入 Phase N+1
- Phase 4 不达标 → 自动退回 Phase 3（中循环降级到内循环）
- Gate 1 ❌ → 自动退回 Phase 3
- Phase 6 完成 → 反馈数据进入 Knowledge Center，循环结束

### 1.2 中循环（Mid Loop）— 质量反馈回退

```
Phase 3 (Implement)
   │
   ▼
Phase 4 (Test + Review)
   │                  │
   ▼                  ▼
  ✅ 通过           ❌ 不达标
   │                 │
   ▼                 ▼
Phase 5           退回 Phase 3 (Fix)
   │                 │
   │                 ▼
   │            重新进入 Phase 4
   │                 │
   └─────────────────┘ (最多 3 次，超限升级人工)
```

**回退计数**：每个 Feature 在 Phase 3→4 中循环最多 3 次。第 4 次仍然不达标 → 升级到人工干预。

### 1.3 内循环（Inner Loop）— 写-测-修微循环

```
Impl Agent 级别的最小循环：

┌──────────────────────────────────────┐
│  1. 读取 Task + PRD 对应章节          │
│  2. 设计实现方案（理解 acceptance）     │
│  3. 写代码                           │
│  4. 运行单元测试                      │
│     ├── ✅ 通过 → 标记 testing        │
│     └── ❌ 失败 → 修复 → 回到 3       │
│  5. 代码 Review                      │
│     ├── ✅ 通过 → 标记 review          │
│     └── ❌ 有意见 → fix → 回到 3      │
│  6. 标记 done → commit               │
└──────────────────────────────────────┘

循环条件：内循环自身最多迭代 10 次
超过 10 次仍未通过 → 升级到中循环（Arch Agent 介入审查设计方案）
```

---

## 2. 心跳机制（Heartbeat）

### 2.1 Orchestrator Agent 心跳

```
频率：每 5 分钟（配置项，可在 task 中覆盖）
动作：
  1. 读取所有活跃 Task 的状态文档
  2. 对于每个 Task：
     a. 当前状态 = 文档中 status 字段
     b. 期望状态 = 状态机定义的下一个状态
     c. 如果当前状态 = 期望状态 → 无事可做
     d. 如果当前状态 ≠ 期望状态 → 检查是否需要驱动下一步
  3. 对于状态停滞超过 30 分钟（可配置）的 Task → 触发告警
  4. 输出心跳日志到 session-record.md
```

### 2.2 状态超时阈值

| 状态 | 最大停留时间 | 超时动作 |
|------|-------------|---------|
| `backlog` | 无限制 | — |
| `active` | 60 分钟 | 告警 + 检查是否卡住 |
| `testing` | 30 分钟 | 自动检查测试输出 |
| `review` | 60 分钟 | 检查 Review Agent 是否完成 |
| `done` | — | 驱动下一 Task |

---

## 3. 状态机（任务级别）

```
                  ┌─────────────────┐
                  │    backlog      │
                  └────────┬────────┘
                           │ Orchestrator 分派
                           ▼
                  ┌─────────────────┐
         ┌───────│    active       │◄────────────┐
         │       └────────┬────────┘              │
         │                │ Impl Agent 标记        │
         │                ▼                       │
         │       ┌─────────────────┐              │
         │       │    testing      │──────────────┤
         │       └────────┬────────┘  Test 失败    │
         │                │ Test 通过               │
         │                ▼                       │
         │       ┌─────────────────┐              │
         │       │    review       │──────────────┤
         │       └────────┬────────┘  Review 不通过 │
         │                │ Review 通过             │
         │                ▼                       │
         │       ┌─────────────────┐              │
         │       │     done        │              │
         │       └─────────────────┘              │
         │                                        │
         └────────────────────────────────────────┘
         退回规则：review → active（需重新实现）
                    testing → active（需修复代码）
```

### 3.1 非法流转禁止

| 流转 | 禁止原因 |
|------|---------|
| `active → done` | 跳过测试和审查 |
| `active → review` | 跳过测试 |
| `backlog → testing` | 跳过实现 |
| `backlog → done` | 无任何执行 |

---

## 4. OODA 映射（设计原理）

每个 Agent 在执行任务时遵循 OODA 微循环：

| OODA | Agent 操作 | 对应步骤 |
|------|-----------|---------|
| **Observe** | 读取 PRD + Task + 上下文 | 读入阶段 |
| **Orient** | 理解 acceptance criteria + 设计约束 | 理解阶段 |
| **Decide** | 确定实现方案 | 设计阶段 |
| **Act** | 写代码/运行测试/提交审查 | 执行阶段 |

执行完成后，Observe 结果（测试输出/审查意见）驱动下一轮 OODA，形成持续闭环。

---

## 5. Agent 角色与循环职责

| Agent | 参与循环 | 职责定位 |
|-------|---------|---------|
| **Orchestrator** | 全部 | 心跳、状态驱动、任务分派、超时告警 |
| **PM** | Phase 0 / Gate 0 / Gate 1 | 外循环驱动 |
| **Arch** | Phase 1 / 升级介入 | 外循环 + 异常处理 |
| **Spec** | Phase 2 | 外循环 |
| **Impl** | Phase 3 / Phase 4 回退 | 内循环 + 中循环 |
| **Test** | Phase 4 | 中循环质量门禁 |
| **Review** | Phase 4 | 中循环质量门禁 |
| **Inte** | Phase 5 | 外循环集成 |
| **Docs** | Phase 5 | 外循环文档 |
| **全部** | Phase 6 | 外循环反馈 |

---

## 6. 循环终止条件

一个 Feature 的外循环在以下条件之一终止：

1. **正常完成**：Gate 1 ✅ → Phase 6 ✅ → 指标入库
2. **人工终止**：Feature 标记为 cancelled / postponed
3. **升级终止**：内循环 10 次 + 中循环 3 次均失败 → 升级人工 → 人工决定终止或重设计
4. **依赖阻塞**：依赖的 Feature 或 Capability 未完成 → 状态设为 `blocked`，等待依赖完成后再恢复

---

## 7. 与其他规则文件的关系

```
rules/
├── loop-engineering.md     ← 本文：循环架构总纲
├── task-rules.md           ← 任务状态管理规则（被 loop 引用）
├── multi-agent-rule.md     ← 多 Agent 协作规则（被 loop 引用）
└── executor.md             ← 单个 Agent 的执行规则（被 task-rules 引用）
```
