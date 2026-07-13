# Task RULES

## 1. 强制任务模式

每次执行必须按照 `rules/executor.md` 的流程执行。
一次只允许执行一个 TASK。

**禁止**：
- 同时做多个任务
- 未读取 PRD 就写代码
- 未验证测试就标记完成
- 未经 Gate 0 就进入实现阶段
- 未经 Gate 1 就标记发布

---

## 2. 代码约束

- 必须符合 PRD
- 必须通过 test
- 必须遵循 L2 规范 MUST 条款
- 新代码单元测试覆盖率 ≥ 80%

---

## 3. 任务完成标准

任务完成必须满足**全部**：

| # | 条件 | 验证人 |
|---|------|--------|
| 1 | 单元测试通过 | Test Agent |
| 2 | MUST 合规测试通过 | Test Agent |
| 3 | Review 评分 ≥ 8 | Review Agent |
| 4 | PRD 对齐检查通过 | PM Agent (Gate 1) |
| 5 | 无未解决的安全问题 | Review Agent |

有一项不满足 → 任务不能标记 done，按中循环规则回退。

---

## 4. 任务状态机

状态流转规则（由 `loop-engineering.md` 定义的状态机强制约束）：

```
合法流转：
  backlog → active       (Orchestrator 分派)
  active  → testing      (Impl Agent 完成实现)
  testing → review       (Test Agent 全部通过)
  testing → active       (测试失败，回退修复)
  review  → done         (Review Agent 通过)
  review  → active       (Review 不通过，回退修复)

禁止流转：
  active  → done         (❌ 跳过测试和审查)
  active  → review       (❌ 跳过测试)
  backlog → testing      (❌ 跳过实现)
  backlog → done         (❌ 无任何执行)
```

---

## 5. 任务状态记录

每个 Agent 的任务执行状态记录在一个单独的 md 文档中，通过此文件可查看该 Agent 所做的所有 task。

```
约定：
  - 文件名：{agent-role}-tasks.md
  - 存放路径：docs/tasks/
  - 状态变更必须立即更新文件
  - 状态变更时间戳记录到毫秒
```

**任务记录格式**（JSON 严格格式，逗号不能缺）：

```json
[
  {
    "id": "001",
    "title": "用户登录接口",
    "sub_title": "登录接口前端开发",
    "status": "active",
    "input": "prd#section2.1",
    "acceptance_criteria": [
      "POST /login 返回 JWT",
      "密码加密存储",
      "错误码规范统一",
      "单元测试通过"
    ],
    "修改的文件": [
      "aaa",
      "bbb"
    ],
    "created_at": "2026-07-12T10:00:00Z",
    "updated_at": "2026-07-12T10:30:00Z"
  }
]
```

---

## 6. Gate 引用

本规则与 `rules/loop-engineering.md` 的循环架构配合使用：
- **Gate 0 之前**：任务保持 `backlog`，不进入 `active`
- **Gate 1 之前**：任务必须处于 `done` 状态，且所有 done 任务汇总后接受验收
