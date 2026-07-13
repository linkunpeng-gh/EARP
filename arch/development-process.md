# EARP 开发过程管理规范

**版本：v1.0**
**定位：本文定义 EARP 平台从需求到交付的完整开发流程标准，包括分工角色、阶段门禁、人工介入点和自动闭环机制。**
**适用对象：所有参与 EARP 开发的 PM、架构师、工程师（含 Agent 团队）**

---

# 第一章：概述

## 1.1 为什么需要这份规范

EARP 是一个多层架构（L0→L1→L2→L3）的大型企业平台，涉及 6 个开发域、9 个 Agent 角色、多次迭代版本。没有统一的开发流程管理，会面临：

- 需求不清晰就启动开发
- 架构决策无人记录
- 规范与实现脱节
- 评审意见提了但未解决
- 跨域接口不一致

本文定义了从 PRD 到交付的**标准化流水线**，确保每次开发都可追溯、可验收、可闭环。

## 1.2 核心原则

| # | 原则 | 含义 |
|---|------|------|
| 1 | **PRD 先行** | 没有验收通过的 PRD 不得进入架构影响分析 |
| 2 | **双闸口门禁** | Gate 0（PRD 验收）保需求质量，Gate 1（发布验收）保交付质量 |
| 3 | **规范即契约** | L2 规范的 MUST 条款是实现的法定约束，违反 MUST 不可发布 |
| 4 | **自动优先** | 70%+ 环节由 Agent 自动完成，人工聚焦决策和验收 |
| 5 | **闭环驱动** | 每次开发完成后收集指标，反馈到下一次迭代 |

---

# 第二章：组织架构

## 2.1 四层治理体系

```
层次        定位             负责                       典型产物
────        ────             ────                       ────
L0          设计哲学          原则委员会                 9 条核心理念
L1          系统架构          架构委员会                 architecture-v6.md + ADR
L2          平台规范          各域 Spec 团队             12-13 份规范、~145 条 MUST
L3          产品需求          PM 团队                    PRD 文档 + 验收条件
```

## 2.2 九大 Agent 角色

| 角色 | 数量 | 职责 | 输出 | 人工介入 |
|------|:----:|------|------|:--------:|
| **PM Agent** | 1-2 | PRD 设计、验收条件、优先级 | PRD 文档 | ✅ Gate 0 验收 |
| **Orchestrator Agent** | 1 | 需求拆解、任务分派、进度跟踪 | 任务状态看板 | ❌ |
| **Arch Agent** | 1 | 维护 L1 架构、起草 ADR | ADR + 架构图更新 | ✅ ADR 评审 |
| **Spec Agent** ×6 | 每域 1 | 维护 L2 规范、MUST 条款 | 规范文档更新 | ✅ MUST 变更 |
| **Impl Agent** ×6 | 每域 1 | 代码实现、单元测试 | 代码 + UT | ❌ |
| **Test Agent** | 1 | MUST 合规测试、集成测试 | 测试报告 | ❌ |
| **Review Agent** | 1 | 代码审查、安全审查、质量评分 | 审查报告 | ❌ (评分<8 打回) |
| **Inte Agent** | 1 | 跨域接口回归、一致性检查 | 集成报告 | ❌ |
| **Docs Agent** | 1 | CHANGELOG、API 文档、架构快照 | 文档更新 | ❌ |

## 2.3 六域划分

| 域 | L2 规范 | P0/P1/P2 |
|----|---------|:---------:|
| Runtime | Runtime Spec + EventBus Spec | P1 |
| Reasoning | Planner Spec + Decision Spec + Knowledge Spec | P1-P2 |
| Capability | Capability Center Spec | P1（已冻结） |
| Execution | Workflow Spec + Agent Spec + Scheduler Spec + Resource Spec | P2-P3 |
| Governance | Policy Spec + Audit Spec + Observation Spec | P2-P3 |
| SDK/API | SDK + Gateway + Plugin | P3-P4 |

---

# 第三章：开发流水线

## 3.1 流水线总览

一次完整的 Feature 开发经过 **7 个阶段、2 道人工门禁**：

```
用户需求 / 评审反馈 / 技术债 / 架构评审问题
    │
    ▼
┌──────────────────────────────────────────┐
│ Phase 0: PM Agent → PRD                  │
│   输出：PRD + 验收条件 + 依赖分析 + 优先级  │
└──────────────────┬───────────────────────┘
                   │
    ╔══════════════════════════════════════╗
    ║  🚧 Gate 0：PRD 人工验收              ║
    ║  ✅ 通过 → 继续                       ║
    ║  ❌ 退回 → PM Agent 修改 → 重新验收    ║
    ╚══════════════════════════════════════╝
                   │
                   ▼
┌──────────────────────────────────────────┐
│ Phase 1: Arch Agent → 架构影响分析        │
│   输出：影响范围报告（输入 → 输出 → 风险）  │
│   如果涉及架构变更 → ADR 起草 → 人工评审    │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ Phase 2: Spec Agent → 规范层更新          │
│   输出：L2 规范更新 + MUST 条款增删        │
│   自动检查：跨域引用、版本号、一致性        │
│   如果涉及 MUST 变更 → 人工评审            │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ Phase 3: Impl Agent → 代码实现            │
│   输出：代码 + 单元测试                    │
│   自动检查：每条 MUST 有对应测试            │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ Phase 4: Test + Review Agent → 质量门禁   │
│   Test Agent: MUST 合规测试（全绿才通过）  │
│   Review Agent: 代码+安全审查（评分≥8）   │
│   不达标 → 退回 Phase 3                   │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ Phase 5: Inte + Docs Agent → 集成与发布    │
│   Inte Agent: 跨域端到端回归              │
│   Docs Agent: CHANGELOG + 架构快照        │
│   如果 Breaking → 人工签批                │
└──────────────────┬───────────────────────┘
                   │
    ╔══════════════════════════════════════╗
    ║  🚧 Gate 1：发布验收                   ║
    ║  对照 PRD 验收条件逐条过               ║
    ║  ✅ 通过 → 发布                       ║
    ║  ❌ 退回 → Impl Agent 修复 → 重新验收  ║
    ╚══════════════════════════════════════╝
                   │
                   ▼
┌──────────────────────────────────────────┐
│ Phase 6: 反馈闭环                         │
│   收集：MUST 合规率、测试通过率、缺陷密度   │
│   反馈：PM Agent（PRD 偏差分析）          │
│         Spec Agent（规范质量报告）        │
│         Arch Agent（架构漂移趋势）        │
└──────────────────────────────────────────┘
```

## 3.2 Phase 0：PRD 设计

### 负责人

PM Agent

### 输入

- 用户需求（客户反馈/使用数据）
- 架构评审报告中的问题（CP 完整性类、Q 规范质量类）
- 技术债/已知产品缺陷
- 历史 PRD 的反馈闭环

### PRD 内容模板

```
PRD ID: PRD-{year}-{seq}
Feature: {Feature 名称}
影响域: {Runtime / Reasoning / Capability / Execution / Governance / SDK}
影响规范: {L2 规范列表}
优先级: P0（必须本期）/ P1（可选）/ P2（未来）

用户故事:
  - 场景 A（正常路径）: 作为{角色}，我希望{行动}，以便{价值}
  - 场景 B（异常路径）: 作为{角色}，当{异常}时，我希望{行动}
  - 场景 C（边界条件）: 作为{角色}，当{边界条件}时，我希望{行动}

验收条件（AC）:
  - AC-01: {描述}（可测试）
  - AC-02: {描述}（可测试）
  ...

依赖分析:
  - 依赖 Capability: {已存在/需新建}
  - 依赖外部系统: {无/列出}
  - 跨域接口: {涉及哪些域}

影响的 MUST:
  - {MUST 条款引用}
```

### 自动检查（由 Spec Agent 在 Gate 0 前执行）

```
1. 检查 PRD 中的用户故事是否覆盖：正常路径 + 异常路径 + 边界条件
2. 检查验收条件是否每条都可写为自动化测试用例
3. 检查 PRD 是否与现有 MUST 条款冲突
4. 检查依赖分析是否完整
```

## 3.3 Gate 0：PRD 人工验收

### 这是**不可跳过的硬门禁**

没有 Gate 0 ✅ 通过的 PRD，Orchestrator Agent 不得将其分派到 Phase 1。

### 验收人

PM（产品负责人）+ 架构师 + 相关域主程（至少 2 人）

### 验收标准

验收人对照以下 5 条逐条检查：

| # | 检查项 | 通过条件 |
|---|--------|---------|
| 1 | 用户故事完整性 | 覆盖正常路径 + 异常路径 + 边界条件 |
| 2 | 验收条件可测试性 | 每条 AC 可以写为一个自动化测试 |
| 3 | 依赖分析完整性 | 不遗漏跨域依赖，所依赖的模块/Capability 存在或已规划 |
| 4 | 优先级合理性 | P0/P1/P2 界定清晰，与版本规划一致 |
| 5 | 无矛盾需求 | PRD 内部无冲突，与已冻结的规范无矛盾 |

### 验收结果

```
✅ 通过 → PRD 标记为 APPROVED，进入 Phase 1
      → PM Agent 将 PRD 同步给 Orchestrator Agent

❌ 不通过 → 验收人给出 2-5 条具体验收意见（标注对应 PRD 段落）
          → PM Agent 逐条修改 PRD（每条意见标记 resolved/unresolved）
          → 重新提交回原验收人
          → 验收人仅复查上轮意见（5 分钟快速检查）
          → 循环直到 ✅ 或 Feature 被标记暂缓
```

### 禁止行为

- ❌ Gate 0 不通过但强行进入 Phase 1
- ❌ 修改了 PRD 但未通知验收人确认
- ❌ 验收意见只回复"已改"但未展示修改内容

## 3.4 Phase 1：架构影响分析

### 负责人

Arch Agent（主）+ Inte Agent（跨域依赖验证）

### 流程

```
1. Arch Agent 读取 PRD → 判断是否影响 L1 架构
   ├── 不影响 → 输出影响范围报告（自动，5 分钟）
   └── 影响 → 起草 ADR（2-3 个备选方案，10 分钟）
         → 架构委员会人工评审 ADR（≤ 1 周）
         → Arch Agent 更新 L1 架构文档
         → Inte Agent 验证新架构的跨域一致性
2. Spec Agent 并行检查：PRD 影响的 MUST 是否已定义
   ├── 已定义 → 影响范围报告中标注
   └── 未定义 → Phase 2 补充
```

## 3.5 Phase 2：规范层

### 负责人

Spec Agent（对应域）

### 内容

- 新增/修改 L2 规范的 MUST/SHOULD/MAY 条款
- 更新版本号
- 更新依赖关系表
- 自动检查：跨域引用正确、版本号语义化、与 L0 原则一致

### 特别注意

如果涉及 MUST 条款的增删或修改（语义变更），需要 **架构委员会人工签批**（可与 Gate 1 合并评审）。

## 3.6 Phase 3：实现层

### 负责人

Impl Agent（对应域）

### 前置条件

- Gate 0 ✅
- 影响范围报告已发布
- 涉及的 L2 规范 MUST 条款已定义或同步更新中

### 实现要求

```
MUST: 每条新增/修改的 MUST 条款对应至少一个自动化测试
MUST: 单元测试覆盖率 ≥ 80%（新代码）
MUST: 不引入循环依赖
SHOULD: 遵循各域 Spec Agent 的接口契约
SHOULD: 所有 public API 有文档注释
```

## 3.7 Phase 4：质量门禁

### 负责人

Test Agent + Review Agent

### 评估项

| 评估 | 负责人 | 标准 | 不达标后果 |
|------|--------|------|-----------|
| MUST 合规测试 | Test Agent | 所有 MUST 测试绿 | 退回 Phase 3 |
| 单元测试 | Test Agent | 覆盖率 ≥ 80%，全部通过 | 退回 Phase 3 |
| 代码审查 | Review Agent | 评分 ≥ 8/10 | 退回 Phase 3 |
| 安全审查 | Review Agent | 无高危漏洞 | 退回 Phase 3 |
| 规范一致性 | Review Agent | 实现与 MUST 条款一致 | 退回 Phase 3 |

### 质量门禁自动执行

```
Test Agent 执行:
  ├── MUST 合规测试套件（每条 MUST 对应的自动化测试）
  ├── 新代码 UT（覆盖率 + 通过率）
  ├── 回归测试（已有功能的 MUST 不受影响）
  └── 性能基准（对比上次基线，退化 > 10% 标记）

Review Agent 执行:
  ├── 代码风格检查
  ├── 循环依赖检测
  ├── 安全漏洞扫描
  ├── 跨域接口签名一致性
  └── 输出评分（0-10）

评分公式 = (MUST 通过率 × 0.4) + (UT 覆盖率 × 0.2)
         + (Review 评分 × 0.3) + (安全通过 × 0.1)

不达标（评分 < 8）：打回 Phase 3，Impl Agent 修复
达标签（评分 ≥ 8）：进入 Phase 5
```

## 3.8 Phase 5：集成与发布

### 负责人

Inte Agent + Docs Agent

### 集成检查

```
Inte Agent:
  ├── 跨域端到端回归（3 个关键场景）
  │   ├── Chat 场景："查询昨天的产线异常"
  │   ├── Workflow 场景："设备故障处理" 编译并执行
  │   └── Agent 场景："日报生成助手" 多轮迭代
  ├── API 契约测试（跨域接口签名一致）
  └── 部署测试（构建 + 启动 + 健康检查）

Docs Agent:
  ├── 更新 CHANGELOG（按 Keep a Changelog 格式）
  ├── 更新 API 文档（关联新增/修改的接口）
  └── 更新架构快照（受影响的 L1 图/字描述）
```

### Breaking 变更签批

如果本次发布涉及 Breaking Change（不兼容的 API 变更、MUST 语义变更、数据迁移），需要在 Gate 1 之前增加 **Release 签批**：

```
PM + 架构师 + 受影响域主程
  ├── 评审 Breaking 的影响范围和兼容性策略
  ├── 确定是否需要灰度发布
  └── 确定升级迁移方案
```

## 3.9 Gate 1：发布验收

### 这是**不可跳过的发布门禁**

所有 Phase 0→5 完成后，在发布前必须通过 Gate 1。

### 验收人

PM（产品负责人）+ 测试工程师

### 验收标准

验收人对照 Phase 0 PRD 中的验收条件（AC）**逐条执行**：

```
验收模板：

PRD ID: PRD-2026-001
Feature: Capability Health Dashboard

| AC ID | 验收条件 | 验收结果 | 备注 |
|-------|---------|:--------:|------|
| AC-01 | 用户查看所有 Capability 的健康状态列表 | ✅ / ❌ | |
| AC-02 | 当 Capability 健康分 < 0.6 时标红 | ✅ / ❌ | |
| AC-03 | 健康分每 30 秒刷新 | ✅ / ❌ | |
| ...   | ...                                   | ✅ / ❌ | |

验收结论：✅ 通过 / ❌ 不通过
补充说明：{可选}
```

### 验收结果

```
✅ 全部通过 → 触发发布
❌ 有失败项 → 退回 Phase 3（Impl Agent）
          → 修复失败项
          → 重新 Gate 1（仅复验失败项）
          → 循环直到 ✅
```

### 与 Gate 0 的区别

```
              Gate 0（PRD 验收）              Gate 1（发布验收）
             ──────────────────              ──────────────────
验收对象       PRD 文档本身                   实现产物 vs PRD
验收时机       Phase 0 完成后                 Phase 5 完成后
验收人         PM + 架构师 + 域主程           PM + 测试
核心问题       "这个 PRD 写得对吗？"           "实现符合 PRD 吗？"
失败处理       退回 Phase 0                  退回 Phase 3
验收耗时       15-30 分钟                    15-30 分钟
频率           每个 Feature 一次             每个 Feature 一次
```

## 3.10 Phase 6：反馈闭环

### 负责人

全部 Agent（各自收集本环节指标）+ Orchestrator Agent（汇总）

### 收集指标

| 指标 | 来源 | 用途 |
|------|------|------|
| MUST 合规率 | Test Agent | 规范质量、趋势 |
| 测试通过率 | Test Agent | 实现质量、趋势 |
| Review 缺陷密度 | Review Agent | 代码质量、趋势 |
| 跨域回归通过率 | Inte Agent | 跨域耦合度、趋势 |
| PRD 偏差标记 | PM Agent | 需求与实现的偏差统计 |
| 验收条件通过率 | PM Agent（Gate 1） | PRD 质量、趋势 |
| 评审修复周期 | Orchestrator Agent | 流程效率、瓶颈 |

### 反馈路径

```
Test Agent  → Spec Agent（规范质量报告：哪些 MUST 常出问题）
Review Agent → Impl Agent（代码质量趋势：常见缺陷类型）
Inte Agent  → Arch Agent（架构漂移趋势：跨域接口变化频率）
PM Agent    → Spec Agent（PRD 偏差分析：需求→MUST 的映射缺失）
Orchestrator → 所有 Agent（流水线瓶颈：哪个 Phase 耗时最长）
```

### 指标进入 Knowledge Center

所有指标持久化到 Knowledge Center，形成**基线**。每次发布后自动对比基线，偏差超过阈值的自动生成 Issue 进入下一轮 Feature 队列。

---

# 第四章：人工介入总表

| 介入点 | 时机 | 参与人 | 耗时 | 频率 |
|--------|------|--------|:----:|:----:|
| Gate 0 PRD 验收 | Phase 0 后 | PM + 架构师 + 域主程 | 15-30 min | 每个 Feature |
| ADR 评审 | Phase 1 中（涉及架构变更） | 架构委员会 | ≤ 1 周 | 按需 |
| MUST 变更签批 | Phase 2 中（MUST 语义变更） | 架构委员会 | 15-30 min | 按需 |
| Release 签批 | Phase 5 后（Breaking） | PM + 架构师 + 相关域主程 | 15-30 min | 按版本 |
| Gate 1 发布验收 | Phase 5 后 | PM + 测试 | 15-30 min | 每个 Feature |
| 总体占比 | — | — | **约 25-30%**（其余自动） | — |

---

# 第五章：Cycle Time 参考

场景：一个中等 Feature（影响 1-2 个域，新增 3-5 条 MUST）

```
阶段                    负责人         耗时            人工
────                    ──────         ────           ────
Phase 0  PRD           PM Agent       30-60 min       —
Gate 0   验收           PM + 架构师     15-30 min      ✅
Phase 1  影响分析       Arch Agent     5-10 min        —
Phase 2  规范层         Spec Agent     10-20 min       —
Phase 3  实现           Impl Agent     1-2 小时        —
Phase 4  质量门禁       Test+Review     5-10 min        —
Phase 5  集成发布       Inte+Docs      10-20 min        —
Gate 1   验收           PM + 测试      15-30 min       ✅
Phase 6  反馈闭环       全部 Agent      5 min            —

总时长：2.5-4.5 小时
其中人工：30-60 分钟（占比 ~20%）
其中自动：剩余全部（占比 ~75-80%）
```

---

# 第六章：异常处理

## 6.1 紧急修复（Hotfix）

紧急 Bug 修复可以**跳过 Gate 0**，但不可跳过 Gate 1。

```
Hotfix 流程：
  1. PM 口头确认优先级（替代 Gate 0）
  2. Impl Agent 直接修复代码
  3. Review Agent 加速审查（30 分钟）
  4. Inte Agent 仅运行受影响域的回归测试
  5. Gate 1 ✅ → 发布
  6. 补 PRD（发布后 24 小时内完成）
```

## 6.2 多次 Gate 不通过

```
同一 PRD 连续 3 次 Gate 0 ❌ → 升级到 L0 原则委员会仲裁
  → 可能结果：
    ├── Feature 暂缓（PM Agent 定期重审）
    ├── 重写 PRD（产品方向调整）
    └── 取消 Feature

同一实现连续 3 次 Gate 1 ❌ → 升级到架构委员会仲裁
  → 可能结果：
    ├── 修正验收条件（过于严格或不合理）
    ├── 替换 Impl Agent（代码质量问题）
    └── 取消 Feature
```

## 6.3 跨域冲突

当 Phase 5 集成时 Inte Agent 发现跨域接口不一致：

```
1. Inte Agent 标记冲突并通知相关 Spec Agent
2. 相关 Spec Agent 在 1 小时内确认问题
3. 如果是一方实现与规范不一致 → 退回 Phase 3（该域 Impl Agent 修复）
4. 如果是两方规范存在冲突 → Arch Agent 介入，起草 ADR
5. ADR 通过后，双方 Spec Agent 更新规范
6. 重新 Phase 5 验证
```

---

# 第七章：工具与基础设施

## 7.1 必备工具

| 工具 | 用途 |
|------|------|
| Git + GitHub | 版本管理、PR/MR、Code Review |
| MUST 合规测试框架 | 每条 MUST 对应一条自动化测试，纳入 CI |
| ADR 模板 + 管理系统 | ADR 起草、评审、归档 |
| PRD 模板 | 结构化 PRD 编写 |
| 质量门禁 Dashboard | 实时显示各域 MUST 合规率、测试通过率、Review 评分 |
| Orchestrator 看板 | Feature 的 Phase 状态追踪 |

## 7.2 MUST 合规测试框架

这是 EAR P 开发流程中**最重要的基础设施**——它把规范（L2）和实现（代码）连接起来。

```
每条 MUST 条款 → 一个合规测试用例

示例：
L2 规范：MUST: 每个 Capability 包含 capability_id (全局唯一)
合规测试：assert capability_registry.all_have_unique_ids() == True

测试位置：tests/compliance/{domain}/test_{spec_name}.py
CI 触发：每次 PR 合并前运行全量合规测试
失败后果：CI ❌ 禁止合并
```

---

# 附录 A：术语表

| 术语 | 含义 |
|------|------|
| L0 | 设计哲学层 — 9 条核心理念 |
| L1 | 系统架构层 — 架构图 + ADR |
| L2 | 平台规范层 — MUST/SHOULD/MAY 契约 |
| L3 | 产品需求层 — PRD + 验收条件 |
| MUST | RFC 2119 定义：违反即为不合规实现 |
| SHOULD | RFC 2119 定义：建议但不强制 |
| ADR | Architecture Decision Record — 架构决策记录 |
| Gate 0 | PRD 人工验收门禁 |
| Gate 1 | 发布人工验收门禁 |
| AC | Acceptance Criteria — PRD 中的验收条件 |
| Phase 0-6 | 开发流水线的 7 个阶段 |
| Agent | 自动化执行某个环节的 AI 角色 |

---

# 附录 B：文档索引

| 文档 | 位置 | 版本 |
|------|------|:----:|
| 设计哲学（L0） | arch/L0/design-philosophy.md | v1.0 |
| 系统架构（L1） | arch/L1/architecture-v6.md | v6.0 |
| 概念模型（L1.5） | arch/L1.5/concept-model-v2.0.md | v2.0 |
| 各域 L2 规范 | arch/L2/{domain}/*.md | 各 v1.x |
| 架构评审报告 | arch/reviews/architecture-review-v5.md | v5.0 |
| **开发流程规范** | **arch/development-process.md** | **v1.0 ← 本文** |
