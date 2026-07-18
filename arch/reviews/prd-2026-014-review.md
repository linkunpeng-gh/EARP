# PRD-2026-014 闭环变更复审

**评审日期：2026-07-17（第 2 轮）**
**评审范围：** 上一轮 2 P0 + 5 P1 修复情况

---

## P0 修复验证

| 编号 | 问题 | 状态 | 证据 |
|:----:|:-----|:----:|------|
| P0-1 | Capability SDK 缺少 fallback_capability_id（2 处副本） | ✅ 已修复 | `libs/earp-sdk-capability-py` 和 `earp-sdk-capability-py` 均已新增 `fallback_capability_id: str = ""`，与 Core SDK 一致 |
| P0-2 | Runtime Spec header 版本号 v1.2 未更新 | ✅ 已修复 | `版本：v1.3` + changelog 摘要 |

## P1 修复验证

| 编号 | 问题 | 状态 | 证据 |
|:----:|:-----|:----:|------|
| P1-1 | REPLANNING 缺"在途 step 等待"声明 | ✅ 已修复 | 转换规则新增：`进入 Replanning 时同 Execution 内其他在途并行 Step 保持等待，不取消`；v1.2→v1.3 changelog 同步记录 |
| P1-2 | REPLAN_TRIGGERED 未入 Runtime 事件表 | ✅ 已修复 | §5.2 事件表新增 `runtime.execution.replan_triggered`，data 含 `{execution_id, session_id, failure_capability_id, replan_count}` |
| P1-3 | Spec `null` vs SDK `""` 语义不一致 | ⚠️ 维持 | 设计取舍：Spec 用 `string \| null` 表意，SDK 用 `""` 降级为 falsy。无功能影响，可后续统一 |
| P1-4 | Runtime Spec 缺 v1.2→v1.3 changelog | ✅ 已修复 | 新增附录 B：v1.2→v1.3 变更记录，含 6 项变更 |
| P1-5 | fallback_capability_id 规范级别 SHOULD→MUST | ✅ 已修复 | `（MUST，v1.3 新增）` |

---

## 逐 AC 终判

| AC | 状态 | 备注 |
|:--:|:----:|------|
| AC-01 | ✅ | Workflow Spec §7.1-7.3：7 状态 + 6 MUST（≥5/≥3 要求） |
| AC-02 | ✅ | Runtime Spec §4.1-4.2：REPLANNING 状态 + 触发/退出 + 上限 3 + 在途并行保持 |
| AC-03 | ✅ | Capability Spec §2.2：`fallback_capability_id: string \| null`，MUST 级别 |
| AC-04 | ✅ | Core SDK + Capability SDK（3 处）同步新增 `fallback_capability_id: str` |
| AC-05 | ✅ | (a)-(e) 5 条行为全部在 Workflow Spec §7.5 时序图中可溯源 + REPLAN_TRIGGERED 已入 Runtime 事件表 |

---

## 结论

**无新增 P0。上一轮 2 P0 + 4 P1 已修复，1 P1（null vs ""）维持现状不影响功能。AC-01~05 全部通过。**

---

## 代码级评审（2026-07-17）

### 🔴 Bug：test_security.py:212 引用未定义变量 `body`

**文件：** `libs/earp-sdk-runtime-py/tests/test_security.py`，line 212

**方法：** `TestJWTNoTokenNoAuthHeader.test_no_auth_header_without_token`

```python
# line 188-212
async def test_no_auth_header_without_token(self):
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))   # ← 只捕获 headers
        return httpx.Response(200, json={...})
    ...
    assert "authorization" not in ...  # ← 这是正确的
    assert body.get("tenant_id") == "tenant-from-setter"  # ← body 从未定义！
```

**失败场景：** `pytest test_security.py` 运行时抛出 `NameError: name 'body' is not defined`。内联 handler 仅将 `request.headers` 写入 `captured`，从未读取 `request.body` 或解析 JSON body。该行疑似从 `test_set_tenant_id_persists` 误粘贴——但即便在那里 handler 也未提取 body。

**修复建议：** 删除 line 212，或在 handler 中增加 `nonlocal body; body = json.loads(await request.aread())` 并声明变量。
