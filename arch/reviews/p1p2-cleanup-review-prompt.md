# P1+P2 清理评审 Prompt

> 一刀即可。改动集中在 6 个文件。输出 `arch/reviews/p1p2-cleanup-review.md`。

```bash
cd /Users/linkunpeng/work/EARP && claude -p "P1+P2 优先级清理代码评审。

评审对象（自上次全链路评审后的增量）：
- apps/earp-server/src/earp_server/orchestrator/layers.py (data_scope=department+org)
- apps/earp-server/src/earp_server/capability/registry.py (pgvector semantic discovery)
- apps/earp-server/src/earp_server/orchestrator/step_runner.py (stream()实现 + batch废弃)
- apps/earp-server/src/earp_server/orchestrator/multi_step.py (REPLANNING+interrupt)
- apps/earp-server/src/earp_server/infra/checkpoint.py (write_writes方法)
- apps/earp-server/src/earp_server/gateway/websocket_gateway.py (JWT 鉴权)
- apps/earp-server/migrations/versions/0002_add_org_unit_id.py
- apps/earp-server/migrations/versions/0003_add_capability_embedding.py

已验证事实：24/24 测试绿，ruff/import-linter 净。

逐项检查：

1. layers.py data_scope=department+org:
   - _get_descendant_orgs 仅 1 层深度（无递归 CTE）——这属于 M5 已知限制还是缺陷？
   - _get_user_org_unit 返回 None 时 after_step 是否正确退避？
   - org scope 过滤逻辑是否正确（self + descendants）？

2. registry.py pgvector discovery:
   - discover() 三分支（query+role / query only / no query）是否无死代码？
   - 无 query 时 role 过滤是否保留原有 behavior？
   - embed_query 使用 M4 伪随机——文档化了吗？

3. step_runner.py stream():
   - stream() 现在生成 event 但不触发 layers(AuditLayer/PolicyLayer)——这是 M6 Phase 1 by design 还是缺陷？
   - InvokeContext 用空字符串创建——tenant_id/execution_id 缺失是否合理？

4. step_runner.py batch():
   - NotImplementedError 消息改为 'M7+'——与全景评审 P2-2 结论一致？

5. multi_step.py REPLANNING+interrupt:
   - interrupt() 方法线程安全吗？
   - INTERRUPTED 状态写入 checkpoint 后 caller 如何恢复？
   - resume() 方法是否被任何调用方使用？

6. checkpoint.py write_writes:
   - checkpoint_writes 表 1 年内未被使用——现在启用是否对齐 PRD-2026-025？
   - value 参数类型为 bytes——调用方是否正确传入？

7. websocket_gateway.py JWT:
   - token 参数是否必须（当前默认 ''）？不可信客户端能否绕过？
   - 与 JWTMiddleware 共享 DEV_SECRET 是否正确？

8. 迁移 0002/0003:
   - ADD COLUMN IF NOT EXISTS 在 prod 环境中幂等吗？
   - downgrade 的 DROP COLUMN 是否可逆？

输出：逐项 PASS/ISSUE/WARN + P0/P1/P2 + file:line。中文，表格。" --max-turns 8 --output-format text > arch/reviews/p1p2-cleanup-review.md 2>&1
```
