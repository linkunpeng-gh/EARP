# PRD-2026-014 v1.2

## Closed-loop Agent/Workflow 深化

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-014 |
| **Feature** | 执行模型从线性开环升级为自适应闭环——RePlan/Human-in-Loop/Self-Healing |
| **优先级** | **P1** |
| **版本** | v1.2 |
| **日期** | 2026-07-15 |

> **v1.2 变更**：P0-1 依赖修正（SandboxManager→Observation Spec）；P0-2 AC-05 改为行为验证；P1-1 Workflow Spec 改为更新(→v1.1)；P1-2/P1-3 AC 强化。

---

## 1. 背景

当前 EARP 执行模型：用户请求 → Planner Plan → 执行 → 返回。没有失败后的自适应能力。

## 2. 范围

### 2.1 Phase 1（本 PRD）

| 模式 | 内容 | 涉及组件 |
|:-----|:-----|:---------|
| RePlan | 执行失败后 Runtime 自动生成修正 Plan（继承 session_id, 上限 3 次） | Runtime Spec (Execution 状态机 +REPLANNING)、Planner.replan() |
| Human-in-Loop | Workflow 节点暂停→审批回调→继续/拒绝→超时升级 | Workflow Spec v1.0→v1.1 (新增状态机+暂停/恢复/超时) |
| Self-Healing | 失败自动重试+退避+Fallback Capability | Capability Spec (+fallback_capability_id)、ConnectorRetryConfig |

### 2.2 Phase 2（后续）

- Feedback-Driven Planner、Multi-Agent 协作、Multi-turn 对话闭环

### 2.3 产出物

| 产出 | 操作 | 内容 |
|:-----|:----:|:-----|
| Workflow Spec | v1.0→v1.1 (更新) | 新增状态机（running/paused/approved/rejected/failed）+ 暂停/恢复/超时升级 MUST |
| Runtime Spec | v1.2→v1.3 (更新) | Execution 状态机增加 `REPLANNING`；触发条件/退出条件/上限 3 次 |
| Capability Spec | 更新 | Capability 增加 `fallback_capability_id` |
| ConnectorRetryConfig | SDK 更新 | 增加 `fallback_capability_id: str` |

## 3. 验收条件

| ID | 描述 |
|:--:|:-----|
| AC-01 | Workflow Spec v1.1 新增：状态机表（≥5 状态：running/paused/approved/rejected/failed）+ 暂停/恢复/超时升级 MUST（≥3） |
| AC-02 | Runtime Spec v1.3：Execution 状态机新增 REPLANNING（触发：Capability FAILED + 可重试；退出：→running 或 →failed；上限 3 次；在途并行 step 保持等待） |
| AC-03 | Capability Spec：新增 `fallback_capability_id: str \| None`，失败时自动切换 |
| AC-04 | `ConnectorRetryConfig` 增加 `fallback_capability_id: str` 字段 + 重试耗尽后调用 fallback |
| AC-05 | RePlan 行为验证：(a) 新 Execution 继承原 session_id (b) failure_context 作为 Planner.replan() 输入约束 (c) 新 plan_id ≠ 原 plan_id (d) 3 次上限后 →FAILED (e) 审计事件 REPLAN_TRIGGERED |

## 4. 依赖

| 依赖 | 状态 |
|------|:----:|
| Runtime Spec v1.2 | ✅ |
| Workflow Spec v1.0 | ✅（已存在，更新 v1.0→v1.1） |
| Capability Center Spec | ✅ |
| Policy Center Spec v1.0 | ✅ |
| Observation Spec v1.1 (SandboxManager 交叉引用) | ✅ |
| PRD-2026-008 (SandboxManager SDK) | ✅ |

## 5. 不做（Phase 2）

- Feedback-Driven Planner、Multi-Agent 子 Workflow、Multi-turn 闭环
- Workflow Engine SDK 实现（本 PRD 仅规范层）

## 6. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | Security Spec 不含 SandboxManager | 依赖改为 Observation Spec v1.1 + PRD-2026-008 |
| P0-2 | AC-05 不可测试（时序图=文档） | 改为 5 条行为验证 |
| P1-1 | Workflow Spec 标注为"新建" | 改为"更新 v1.0→v1.1" |
| P1-2 | AC-01 门槛无约束力 | 明确新增内容：状态机 + 暂停/恢复/超时 MUST |
| P1-3 | AC-02 缺触发/退出条件 | 补充：触发=Capability FAILED+可重试；退出=running/failed；上限 3 次；并行 step 保持等待 |
