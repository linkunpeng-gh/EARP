# M3 成果评审 Prompt

> 两刀，M3 规模小（1 PRD，5 新文件）。输出写 `arch/reviews/m3-holistic-review.md`。

---

## 第 1 刀：核心链路追溯（PRD→代码 AC 覆盖）

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M3 Reasoning 追溯审计。

评审对象（5 个文件）：
- prd/PRD-2026-023-server-m3-reasoning.md (v1.0, 6 US, 6 AC)
- apps/earp-server/src/earp_server/planner/business_dictionary.py
- apps/earp-server/src/earp_server/planner/task_planner.py
- apps/earp-server/src/earp_server/planner/validation.py
- apps/earp-server/src/earp_server/connector.py (LLMConnector 部分)
- apps/earp-server/src/earp_server/main.py (/plan + /intents 端点)

逐 AC 判定（6 条）：
AC-01 'Rule Planner: query users → Plan 含 1 Step' → business_dictionary.py _BUSINESS_DICTIONARY 是否含 'query users' 条目？RuleIntentPlanner.resolve 是否正确返回 IntentMatch？
AC-02 'Rule Planner: unknown intent → error' → resolve 返回 None 后 task_planner 是否抛出 PlanError？
AC-03 'Simple Task Planner: prompt → Plan(Steps[])' → SimpleTaskPlanner.plan 是否正确委托给 RuleIntentPlanner？
AC-04 'Plan Validation: 缺少 capability_id → reject' → validation.py validate_plan 是否检查 capability_call.get('capability_id')？
AC-05 'Plan depth > 5 → reject' → MAX_PLAN_DEPTH=5 是否正确检查？
AC-06 'LLMConnector.plan() 返回合法 Plan schema' → LLMConnector.plan 的 M3 fallback 是否正确委托给 RuleIntentPlanner？降级路径是否对齐 L1 §8.5？

架构检查：
- LLMConnector 五挂点（rate_limiter/cache/bind_tools/with_structured_output/stream）是否在构造函数中声明？（M3 只实现 rate_limiter，其余留 Phase 2/3——接口定稿=签名+注释存在）
- PlanRequest(BaseModel) 是否定义在模块顶层（非 create_app 内部）？
- /plan 端点 400→PlanError 的异常链是否用 from e 保留根因？

输出：AC 逐条 FULL/PARTIAL/MISSING + P0/P1/P2 + file:line。中文，表格。" > arch/reviews/m3-holistic-review.md 2>&1
```

---

## 第 2 刀：一致性与边界（短刀）

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M3 一致性与边界扫描。

检查项（每项 1 行判定）：

A. Business Dictionary 覆盖度：
   - _BUSINESS_DICTIONARY 当前 4 条目（query users/create alarm/query alarms/echo）——是否与 PRD US-01/02 的验收场景对应？
   - intent 匹配是否大小写不敏感（intent.lower().strip()）？

B. Plan→Step 映射正确性：
   - SimpleTaskPlanner.plan 产出的 Step.capability_call 的 adapter_type 字段格式是否正确（cap-query-users → query.users）？
   - Step.step_id 是否唯一（f\"step-{capability_id}\" 在单步场景下不碰撞）？

C. Plan Validation 健壮性：
   - validate_plan 空列表 → PlanValidationError？depth=0 的边界是否处理？
   - MAX_PLAN_DEPTH=5 的硬上限是否与 L1 §8 对齐？

D. LLMConnector 接口定稿验证：
   - 五挂点在 __init__ 中是否全部声明（rate_limiter 已实现，cache/bind_tools/with_structured_output/stream 留 None 或注释）？
   - plan() vs plan_structured() 的职责区分是否清晰（前者 M3 降级路径，后者 Phase 3 结构化输出）？
   - 降级路径是否对齐 PRD §1.6 'LLM 不可用→Rule Planner 兜底'？

E. main.py 集成：
   - app.state.planner 在 lifespan 中是否创建？
   - /plan 和 /intents 端点的 JWT 鉴权状态——当前无鉴权（M2 只有 invoke 有 JWT）。这属于 M3 scope 省略还是缺陷？

F. import-linter:
   - earp_server.planner 是否已加入 pyproject.toml 的 modules 列表？
   - planner 模块的 imports 是否违反独立契约？

输出：逐项 PASS/ISSUE/NA + 一行证据 + P0/P1/P2。中文，表格。" >> arch/reviews/m3-holistic-review.md 2>&1
```

---

## r2 重评模板

```bash
codex exec "Round-2 复核。r1 报告：arch/reviews/m3-holistic-review.md。已修复清单：...。逐项 RESOLVED/NOT-RESOLVED；新 P0/P1 扫描；verdict CLOSED。中文。" >> arch/reviews/m3-holistic-review-r2.md 2>&1
```
