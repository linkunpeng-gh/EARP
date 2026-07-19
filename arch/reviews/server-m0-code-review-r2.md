我已逐一核对 5 个文件中的每项修复，以下是逐条验证结果：

## 修复验证表

| 编号 | 修复内容 | 文件 | 状态 | 备注 |
|------|---------|------|------|------|
| P1-1 | worker try/finally 包裹 open/run/close | `entrypoints/worker.py:29-47` | ✅ 正确 | finally 块确保 close 必定执行；CancelledError 被 suppress |
| P1-2 | tenant_session 拒绝空 tenant_id | `infra/db.py:30-33` | ✅ 正确 | 空白字符串和纯空格均被 `strip()` 拦截 |
| P1-3 | ensure_schema → assert_schema（只读检查，无 DDL） | `infra/task_queue.py:51-63` | ✅ 正确 | 用 `to_regclass` 探测，缺失时抛 RuntimeError；worker.py 在 open 之后调用 |
| P1-4 | 自引用 FK：org_units.parent_id + business_capabilities.fallback | `migrations/.../0001_baseline.py` L62, L139 | ✅ 正确 | checkpoints.parent_checkpoint_id 刻意不加 FK，注释已说明 LangGraph 归档灵活性理由 |
| P1-5 | chunks.kb_id FK + conversations.user_id FK | `migrations/.../0001_baseline.py` L214, L226 | ✅ 正确 | `REFERENCES knowledge_bases (kb_id)` 和 `REFERENCES users (user_id)` 均已添加 |
| P1-6 | policy_bindings PK 纳入 tenant_id | `migrations/.../0001_baseline.py` L175 | ✅ 正确 | `PRIMARY KEY (policy_id, entity_type, entity_id, tenant_id)` |
| P1-7 | task-name 注册校验延后至 M1 | `infra/task_queue.py:67-70` | ✅ 正确 | NOTE 注释清晰记录了延期理由和 M1 路径 |
| P1-8 | +3 RLS 测试 + row.level 正则 | `tests/test_rls.py:68-98` | ✅ 正确 | UPDATE/DELETE 跨租户阻断、GUC 未设置时不可见、空 tenant_id ValueError、INSERT 租户不匹配拒绝 — 4 个测试均覆盖 |
| P1-9 | 非事务性入队文档化 | `infra/task_queue.py:71-76` | ✅ 正确 | NOTE 标注了 pool-defer 不与调用方事务绑定的限制，给出 M1 `enqueue_in_session` 路径 |

## 新问题扫描

**未发现 NEW P0 或 P1。** 逐一检查了：

- **正确性**：`assert_schema` 在 `open()` 之后调用，connector 已就绪；downgrade 的 DROP TABLE 顺序遵循 FK 依赖逆序（如 `capability_calls` 先于 `executions`，`connector_bindings` 先于 `business_capabilities`/`connector_configs`）
- **异常安全**：`pytest.raises` 包裹 `tenant_session` 上下文管理器时，内层 `session.begin()` 的 `__aexit__` 会正确 rollback 已中止的事务
- **无回归**：17/17 测试绿色，squawk 0 告警，pyright/ruff/import-linter 干净

**VERDICT: CLOSED** — 全部 9 项 P1 修复正确落地，无新增 P0/P1。
