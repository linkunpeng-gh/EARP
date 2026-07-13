# Executor Agent

> **适用**：Impl Agent / Test Agent / Review Agent 等执行具体工作的 Agent。
> **配合**：`loop-engineering.md`（循环架构）、`task-rules.md`（状态机）、`multi-agent-rule.md`（多 Agent 协作）

---

## 1. 通用执行规则

1. 检查任务状态，找到第一个非 `done` 的 Task 依次执行
2. 一次只执行一个 TASK（由 Orchestrator 分派）
3. 必须先读取 PRD 对应章节 + Task 定义
4. 必须先检查 acceptance_criteria，理解验收标准
5. 每完成一步必须更新任务状态文档
6. 每一步出错必须记录错误原因，不可静默跳过

---

## 2. Impl Agent 执行流程

### 2.1 OODA 映射

| 步骤 | OODA | 操作 | 超时 |
|------|------|------|:----:|
| STEP 1 | Observe | 读取 Task 定义 + PRD 对应章节 | 2 min |
| STEP 2 | Orient | 理解 acceptance_criteria + 设计约束 | 2 min |
| STEP 3 | Decide | 设计实现方案（必要时输出设计草稿） | 5 min |
| STEP 4 | Act | 写代码 | — |
| STEP 5 | Act | 运行单元测试 | 5 min |
| STEP 6 | Observe | 检查测试结果 | — |
| STEP 7 | Act | 代码 Review | 5 min |
| STEP 8 | Act | Commit + 标记 done | 1 min |

### 2.2 详细流程

```
STEP 1: 读取 Task
  ├── 读取 task-rules.md 中当前 Task 的定义
  ├── 读取 PRD 中对应章节（非整份 PRD）
  └── 输出：确认理解（"我理解了这个 Task，涉及 PRD §X"）

STEP 2: 理解 acceptance_criteria
  ├── 逐条阅读 acceptance_criteria
  ├── 确认每条 AC 的可测试性
  └── 输出：AC 分析清单

STEP 3: 设计实现
  ├── 确定需要修改的文件
  ├── 确认是否影响其他模块（如有 → 标注 + 通知 Orchestrator）
  ├── 如果设计复杂（修改 > 5 文件 / 涉及架构变更）→ 输出设计草稿
  └── 输出：实现方案概要

STEP 4: 写代码
  ├── 将任务 status 更新为 active
  ├── 按照实现方案写代码
  ├── 每条新增 MUST 对应至少一个自动化测试
  ├── 新代码 UT 覆盖率 ≥ 80%
  ├── 遵循 L2 规范 MUST 条款
  └── 输出：代码 + 测试代码

STEP 5: 运行测试
  ├── 运行单元测试
  ├── ├── ✅ 全部通过 → 进入 STEP 6
  │   └── ❌ 有失败 → 修复 → 回到 STEP 4
  │         最多迭代 10 次（内循环约束）
  │         超过 10 次 → 升级到 Arch Agent
  ├── 将任务 status 更新为 testing
  └── 输出：测试结果

STEP 6: 代码 Review
  ├── 提交 Review（由 Review Agent 执行）
  ├── ├── ✅ Review 通过（评分 ≥ 8）→ 进入 STEP 7
  │   └── ❌ Review 不通过（评分 < 8）→ 修复 → 回到 STEP 4
  │         最多 3 次中循环回退
  │         超过 3 次 → 升级人工介入
  └── 输出：Review 结果

STEP 7: 标记完成 + Commit
  ├── 将任务 status 更新为 done
  ├── 运行 git add + git commit（含 Task id 在 commit message 中）
  └── 输出：commit SHA

STEP 8: 工作报告
  ├── 输出工作报告到 docs/tasks/ 目录
  ├── 内容：做了什么、修改了哪些文件、测试结果、遗留问题
  └── 更新 session-record.md
```

---

## 3. Test Agent 执行流程

```
STEP 1: 读取 affected MUST 列表（来自 Spec Agent）
STEP 2: 执行 MUST 合规测试套件
STEP 3: 执行新代码 UT（覆盖率 + 通过率）
STEP 4: 执行回归测试（已有功能的 MUST）
STEP 5: 执行性能基准（对比上次基线）
STEP 6: 输出测试报告
  ├── ✅ 全部通过 → 通知 Orchestrator 进入下一阶段
  └── ❌ 有失败 → 通知 Impl Agent 修复
```

---

## 4. Review Agent 执行流程

```
STEP 1: 读取代码变更（diff）
STEP 2: 检查代码风格和规范一致性
STEP 3: 检查循环依赖
STEP 4: 安全漏洞扫描
STEP 5: 跨域接口签名一致性检查
STEP 6: 输出评分（0-10）
  评分公式：
    Score = (MUST 通过率 × 0.4) + (UT 覆盖率 × 0.2)
          + (Review 评分 × 0.3) + (安全通过 × 0.1)
  ├── Score ≥ 8 → 通知 Orchestrator
  └── Score < 8 → 输出具体意见 → 退回 Impl Agent
```

---

## 5. 失败与回退

### 5.1 内循环失败（Impl Agent 级别）

```
STEP 5 测试失败 → 修复 → 重测
   最多 10 次迭代
   第 11 次 → 升级到 Arch Agent
   Arch Agent 决策：
     ├── 设计方案有问题 → 重做 STEP 3
     └── PRD 不明确 → 退回 PM Agent 修改 PRD
```

### 5.2 中循环失败（质量门禁级别）

```
Review 不通过 → 修复 → 重新提交 Review
   最多 3 次迭代
   第 4 次 → 升级人工介入
   PM + 架构师决策：
     ├── 放宽标准（非常规，需记录原因）
     ├── 重设计
     └── 特征暂缓
```

### 5.3 提交失败

```
git commit 失败 → 检查冲突 → 解决 → 重试（最多 2 次）
第 3 次 → 升级人工
```

---

## 6. 执行后检查清单

每个 Task completed 后，执行 Agent 自行检查：

```
□ 单元测试全部通过
□ MUST 合规测试全部通过（如适用）
□ 覆盖率 ≥ 80%（新代码）
□ Review 评分 ≥ 8
□ 无新增安全漏洞
□ 已更新任务状态文档
□ 已 commit 代码（commit message 含 Task id）
□ 已生成工作报告
□ 已通知 Orchestrator
```
