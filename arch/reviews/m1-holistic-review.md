# M1 全成果复审报告

**复审日期：2026-07-19（第 6 轮）**
**评审范围：** 第 5 轮唯一的缺口——AC-04/05 从 documented limitation 改回实际测试

---

## 变更内容

`test_m1_walking_skeleton.py` 新增 `TestInvokeProducesAuditAndCheckpoint`（第 110-181 行），使用 `httpx.AsyncClient + ASGITransport` 替代 `TestClient`，与 lifespan 共享事件循环。

测试流程：
1. `httpx.AsyncClient(app=app)` 共享 lifespan 的事件循环 → demo capability 在 lifespan 中注册成功
2. `POST /v1/sessions` → 201 → 获取 session_id
3. `POST /v1/sessions/{sid}/invoke` cap-demo-echo → 200 → 验证 `checkpoint_id` 非空
4. `await asyncio.sleep(0.1)` 等待 EventBus fire-and-forget 写入 DB
5. 查询 checkpoints 表 → 断言行存在
6. 查询 checkpoint_blobs 表 → 断言 count > 0
7. 查询 audit_logs 表 → 断言 `event_type='earp.execution.completed'` 且 `detail->>'checkpoint_id'` 匹配

无 skip 分支，无 documented limitation——所有断言都是 assert fail。

---

## 最终 AC 判定

| AC | 判定 | 测试落点 |
|:--:|:----:|:-----|
| AC-01 | ✅ | `test_session_crud_and_close` — 401 + 201 |
| AC-02 | ✅ | `test_session_crud_and_close` — 200 + 404 |
| AC-03 | ✅ | `TestInvokeProducesAuditAndCheckpoint` — invoke echo → 200 + checkpoint_id 非空 |
| AC-04 | ✅ | `TestInvokeProducesAuditAndCheckpoint` — audit_logs 含 EXECUTION_COMPLETED + checkpoint_id |
| AC-05 | ✅ | `TestInvokeProducesAuditAndCheckpoint` — checkpoints + checkpoint_blobs 表有数据 |
| AC-06 | ✅ | `TestStepRunnerInterface` — stream/batch → NotImplementedError |
| AC-07 | ✅ | `TestConnectorRetry` — nonexistent adapter → ConnectorError |
| AC-08 | ✅ | `test_session_crud_and_close` — close → closed |
| AC-09 | ✅ | SDK 集成 37/37 runtime-py 测试 |
| AC-10 | ✅ | `test_input_guard_and_capability_discover` — `GET /capabilities?q=echo` → 200 |
| AC-11 | ✅ | `test_input_guard_and_capability_discover` — SQL 注入 payload → 400 |
| AC-12 | ✅ | F1-F5 全部兑现 |

**12/12 AC FULL。**

---

## 总结

**0 P0，0 P1，0 P2。M1 Walking Skeleton 通过。**
