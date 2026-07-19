# PRD-2026-026 v1.0

## M6 — 事件与流式

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-026 |
| **Feature** | EventBus Redis Streams 实现 + WebSocket 执行事件推送 + 流式 token 事件 |
| **里程碑** | M6（依赖 M1 EventBus 抽象接口） |
| **PRD 链** | ← PRD-2026-025(M5) |

---

## 1. 范围表

| # | 域 | 功能 |
|:--|:---|:-----|
| 1 | EventBus | Redis Streams 实现：XADD 写流、XREADGROUP 消费者组。保持 M1 EventBus 接口不变，仅换实现类 |
| 2 | EventBus | 保留进程内 EventBus 作为 fallback（Redis 不可达时自动降级） |
| 3 | WebSocket | WebSocket Gateway：`/ws/events/{session_id}` — 推送执行事件（EXECUTION_STARTED/COMPLETED/FAILED/RETRIED/DENIED） |
| 4 | WebSocket | 流式 token 事件：`earp.llm.token` 类型入 EventBus 注册表 |

---

## 2. US

| US | 描述 |
|:--:|:-----|
| US-01 | invoke echo→事件 XADD 到 Redis Stream→消费者 XREADGROUP→audit_handler 写入 audit_logs（与进程内行为等价） |
| US-02 | Redis 不可达→自动降级为进程内 EventBus（不阻塞 invoke） |
| US-03 | 客户端连接 `/ws/events/{session_id}`→invoke 后收到 EXECUTION_STARTED→COMPLETED 事件 JSON 推送 |
| US-04 | WebSocket 断线重连（3 秒内自动重连） |

---

## 3. AC

| AC | 内容 | 验证 |
|:--:|:-----|:----|
| AC-01 | Redis Streams 模式：invoke→XADD→XREADGROUP→audit_logs 写入 | pytest |
| AC-02 | Redis 不可达→进程内 EventBus fallback→invoke 正常返回 | pytest |
| AC-03 | WebSocket 客户端收到 EXECUTION_STARTED+COMPLETED 事件 | pytest |
| AC-04 | 流式 token 事件类型在 EventBus 中可订阅 | pytest |

---

## 4. 依赖

| 依赖 | 来源 |
|:-----|:-----|
| EventBus Protocol | M1 |
| Redis（redis-py async） | M2 TokenBucketRateLimiter |
| WebSocket（FastAPI WebSocket） | M1 FastAPI |

---

## 5. Gate

| # | 检查项 | 状态 |
|:--|:-----|:----:|
| 1 | 依赖明确 | ✅ |
| 2 | AC 可测试 | ✅ 4 条 |
| 3 | 与冻结规范无矛盾 | ✅ |
