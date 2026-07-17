# PRD-2026-013 v1.1

## Observation Spec Replay — 观测数据回放能力

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-013 |
| **Feature** | Observation Spec v1.0 → v1.1：新增第六章 Replay（沙箱回放/决策链追溯/差异对比/调试） |
| **优先级** | **P1** |
| **版本** | v1.2 |
| **日期** | 2026-07-15 |

---

## 1. 背景

Observation Spec v1.0 定位中声明了 Replay，但正文缺失。当前 Execution.payload、AuditLog、CapabilityCall 已具备数据基础，缺统一 Replay 规范。

## 2. 范围

### 2.1 新增章节：第六章 Replay

| 能力 | 描述 | 数据来源 |
|:-----|:-----|:---------|
| 沙箱回放 | 在隔离沙箱中用历史 params+context 重跑 Capability 调用，任何副作用（写 DB/调 API）不触及生产 | Execution.payload, Execution.context, SandboxManager |
| 决策链追溯 | 按 AuditLog 事件时间线重放执行顺序，输出结构化时间线 | AuditLog (event_type, timestamp, entity_id) |
| 差异对比 | 对比 replay 结果与原始结果：Plan DAG 差异、Capability 返回值差异、耗时差异 | Execution.result vs replay output |
| LLM 调试 | 回放 Planner 的 Prompt+Response，定位幻觉/注入来源 | AuditLog.detail (LLM Prompt+Response) |

### 2.2 覆盖的机制细节

- 触发方式：通过 Execution ID 触发 Replay
- 存储格式：Replay 结果以 JSON 存储，包含 `replay_id`, `execution_id`, `timestamp`, `diff`（与原始结果的差异）
- 隔离保证：Replay 使用 `SandboxManager` 隔离执行（复用 Phase 4 Plugin 沙箱），被重放的 Capability 产生的所有写操作不触及生产环境
- 副作用策略：Replay **仅适用于无副作用或沙箱可截获副作用的 Capability**（idempotent Query 天然安全；Command 需沙箱保护；网络调用若沙箱无法截获则直接拒绝 Replay）。Replay 基础设施本身 read-only
- 租户隔离：Replay 不能跨租户访问数据（复用 Tenant Spec RLS + Auth）
- 保留策略：Replay 结果保留 7 天

### 2.3 不做

- Replay UI/可视化工具
- 自动化回归测试框架（独立 PRD）
- SDK 实现代码（本 PRD 仅规范层）

## 3. 验收条件

| ID | 描述 |
|:--:|:-----|
| AC-01 | Observation Spec 新增 §6 Replay 章节，定义 4 个核心能力 + 数据来源映射 + 机制细节（触发方式/存储格式/隔离保证/保留策略） |
| AC-02 | 每条 Replay 能力 ≥1 MUST：沙箱隔离(≥1)、决策链追溯(≥1)、差异对比(≥1)、LLM 调试(≥1)，共计 ≥5 MUST |
| AC-03 | 与 Audit Spec v1.1（AuditLog 字段）、Runtime Spec v1.2（Execution.payload）、Security Spec v1.1（SandboxManager）交叉引用一致 |
| AC-04 | Replay 基础设施声明 read-only；沙箱回放声明副作用隔离（不触及生产环境） |
| AC-05 | 声明租户隔离约束：Replay 不可跨 tenant_id 访问数据 |
| AC-06 | 差异对比格式：Plan diff（DAG 节点增删改）、Result diff（RFC 6902 JSON Patch）、Timing diff（`abs(replay - original) / original × 100%`） |

## 4. 依赖

| 依赖 | 状态 | 备注 |
|------|:----:|:-----|
| Observation Spec v1.0 | ✅ | 当前版本 |
| Audit Spec v1.1 | ✅ | AuditLog 字段定义 |
| Runtime Spec v1.2 | ✅ | Execution.payload 结构 |
| Security Spec v1.1 | ✅ | SandboxManager 沙箱执行 |

## 5. 产出物 + 级联更新

| 产出物 | 变更 |
|:-----|:-----|
| `arch/L2/05-governance/observation-specification.md` | v1.0 → v1.1：新增 §6 Replay + 版本号 + Changelog |
| Security Spec §1.1 依赖声明 | Observation Spec 版本 v1.0 → v1.1（4 处引用更新） |
| Audit Spec 依赖列表 | 新增 Observation Spec v1.1 反向引用 |

## 6. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | 输入回放副作用未定义 | §2.1 改为"沙箱回放"（SandboxManager 隔离），§2.2 副作用策略明确 |
| P0-2 | 缺少隔离执行要求 | AC-04 补充沙箱隔离声明；AC-05 新增租户隔离约束 |
| S3 | 机制细节缺失 | §2.2 新增触发方式/存储格式/隔离保证/保留策略 |
| S4 | 缺保留策略 | §2.2 保留策略：Replay 结果 7 天 |
| — | AC-03 主观 | 拆解为具体检查项（AuditLog 字段/Execution.payload/SandboxManager） |
| — | 缺差异对比格式 | 新增 AC-06：Plan diff/Result diff/Timing diff |
| — | 交叉引用缺口 | §5 产出物增加 Security Spec + Audit Spec 级联更新 |
