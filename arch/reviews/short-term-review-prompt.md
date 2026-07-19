# 短期清理评审 Prompt

> 一刀。改动 3 个新文件。输出 `arch/reviews/short-term-review.md`。

```bash
cd /Users/linkunpeng/work/EARP && claude -p "短期清理代码评审。

评审对象：
- apps/earp-server/src/earp_server/orchestrator/workflow_dsl.py (78行，DSL编译)
- apps/earp-server/src/earp_server/policy/policy_service.py (76行，policy表CRUD)
- apps/earp-server/src/earp_server/runtime/tenant_service.py (37行，多租户账号)

检查项：

1. workflow_dsl.py：
   - Sequential/Conditional/Parallel/StepNode 四节点覆盖度——是否缺循环(loop)节点？
   - Conditional.flatten() 同时展开两个分支——M5 运行时如何选支？（iflattener 返回全量 Step，依赖 executor 跳过不可达分支——这个设计是否合理？）
   - Parallel.flatten() 当前退化为 Sequential——文档化了吗？
   - compile_workflow() 是否被任何调用方使用？（搜索项目内引用）

2. policy_service.py：
   - create_policy 的 conditions 字段用 str 存 JSON——与 M0 DDL 的 JSONB 列类型匹配吗？
   - get_policies_for_role 的 JOIN 查询是否被 M2 PolicyLayer 替换使用？（当前 PolicyLayer 仍用 role.permissions——新旧路径未对接）
   - ON CONFLICT 语句——policy_id 是单列主键吗？（搜索 DDL）

3. tenant_service.py：
   - add_account_join 的 ON CONFLICT (tenant_id, user_id) ——是否有对应该组合的唯一约束？
   - get_user_tenants 无 tenant_id 过滤——跨租户查询是否安全？（RLS 在 DB 层生效吗？）

输出：PASS/ISSUE + P0/P1/P2 + file:line。中文。" --max-turns 5 --output-format text > arch/reviews/short-term-review.md 2>&1
```
