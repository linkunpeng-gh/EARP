# P6 Runtime SDK 修复复核报告（R2）

**评审范围**: `b7c6141..6a8c307`
**提交**: `6a8c307` — fix: P6 codex review — P1 复用 self._client + 分级 timeout
**评审日期**: 2026-07-20
**基线报告**: [p6-sdk-review.md](./p6-sdk-review.md)

---

## 1. stream_invoke(): 是否已复用 self._client？（r1 P1-1）

**结论：RESOLVED**

提交 `6a8c307` 将

```python
# 旧: 新建独立 AsyncClient，丢失 User-Agent，无法复用连接池
async with httpx.AsyncClient(timeout=300) as sse_client:
    async with sse_client.stream("POST", ..., headers=...) as response:
```

改为

```python
# 新: 复用 self._client，继承所有默认 headers 和连接池
async with self._client.stream("POST", ..., timeout=sse_timeout) as response:
```

关键变更验证：
- `self._client` 在 `__init__` 中已设置 `User-Agent` 和条件式 `Authorization` header，`self._client.stream()` 自动继承这些 headers，不再需要手动传 `headers` 参数。
- 旧代码中独立的 `AsyncClient` 每次 stream_invoke 调用都会被创建和销毁，新代码复用连接池，行为与 `create_session()`、`call()`、`plan()` 一致。
- 生命周期正确：stream 响应通过 `async with self._client.stream(...)` 管理，退出时关闭响应但不关闭 `self._client`（由 RuntimeClient 的 `close()` 控制）。

---

## 2. stream_invoke(): timeout 是否改为分级 httpx.Timeout？（r1 P1-2）

**结论：RESOLVED**

提交 `6a8c307` 将

```python
# 旧: 单值 300s，5 个阶段全用同一值
httpx.AsyncClient(timeout=300)
```

改为

```python
# 新: 分级 Timeout
httpx.Timeout(connect=10, read=300, write=10, pool=5)
```

| 阶段 | 旧值 | 新值 | 合理性 |
|------|------|------|--------|
| connect | 300s | 10s | 服务不可达时快速失败，防止 SDK 调用方被长时间阻塞 |
| read | 300s | 300s | SSE 流可能长时间无数据，保持宽松 |
| write | 300s | 10s | POST body 发送不应耗时过长 |
| pool | 300s | 5s | 连接池等待合理时间，避免死等 |

**注意**: r1 建议值（`connect=10, read=300, pool=10`）未含 `write`。修复中额外加入了 `write=10`，这是一个合理的补充，因为 POST body 的 write 阶段不会持续很久。

---

## 3. 修复是否引入新问题？

**结论：未引入新问题。** 变更到 `client.py` 的 diff 仅 25 行（+12/-13），改动范围精确，逻辑等价性可验证。

### 变更审计

| 审计项 | 旧行为 | 新行为 | 风险评估 |
|--------|--------|--------|----------|
| Authorization header | 条件式手动传 `headers=...` | 继承自 `self._client` 默认 headers | 等价的 — `__init__` 中 `self.token` 非空时已加入默认 headers |
| 空 token 场景 | `headers={}` → 无 Authorization | `self._client` headers 仅含 User-Agent | 等价的 |
| 响应生命周期 | 独立 client + stream 双重 context manager | stream 单一 context manager | 正确的 — 响应关闭后 `self._client` 保持打开 |
| 生成器提前退出 | 独立 client context manager 退出时关闭 client | stream context manager 退出时关闭响应 | 正确的 — `self._client` 不被关闭 |
| import json | 函数体内 | 函数体内（未移动） | 无风险（观察项，同 r1） |
| SSE 解析逻辑 | 全量 | 零改动 | 无风险 |
| plan() 方法 | 零改动 | 零改动 | 无风险 |
| 测试文件 | 零改动 | 零改动 | 无风险 |

### 未修复的遗留项（r1 P2，不在本次修复范围）

| 原 Issue | 级别 | 说明 |
|----------|------|------|
| ISSUE-3: error 事件后继续 yield | P2 | 未修复 |
| ISSUE-4: 事件类型过于宽松 | P2 | 未修复 |
| ISSUE-5: plan() steps 条目结构验证 | P2 | 未修复 |
| ISSUE-6: _make_client 缺 User-Agent | P2 | 未修复 |
| ISSUE-7: 缺失边缘 case 测试覆盖 | P2 | 未修复 |

以上均为优化级需求，不影响当前功能正确性，无需在当前修复中处理。

---

## 汇总

| 检查项 | 结论 |
|--------|------|
| 1. 复用 self._client | **RESOLVED** — 替换为 `self._client.stream()`，headers 和连接池一致 |
| 2. 分级 timeout | **RESOLVED** — 使用 `httpx.Timeout(connect=10, read=300, write=10, pool=5)` |
| 3. 引入新问题 | **无** — diff 范围精确，行为等价，无新风险 |

**新问题: P0: 0 | P1: 0 | P2: 0**

**结论: 修复正确，批准合并。** 两个 P1 问题均已关闭，变更无回归风险。
