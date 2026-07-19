# 后续开发计划——优先级建议

> 2026-07-19，基于 M0→M7 全闭环 + P1+P2 全清理后的状态。

---

## 一、即刻（本周，0 外部依赖）

| # | 项 | 理由 | 估时 |
|:--|:---|:-----|:---:|
| 1 | SDK runtime-py 流式 + WebSocket client | M6 WebSocket 已有服务端，客户端零覆盖。SDK 集成是 M1 AC-09 的自然延伸 | 2h |
| 2 | 端到端集成测试（testcontainers PG + API + SDK） | 当前 24 测试全是单元级，缺一条 `create_session → plan → invoke → check audit` 全链路 | 2h |
| 3 | Makefile 加 `make e2e` 目标 + 本地 `docker compose up e2e` 一键启动 | 降低后续开发门槛 | 1h |

---

## 二、短期（1-2 周，需简单外部设置）

| # | 项 | 外部依赖 | 理由 |
|:--|:---|:-----|:-----|
| 4 | Workflow Engine DSL 编译（M5 遗留 #13） | 无 | 多步编排的最核心缺失——缺 DSL 则 M5 仅能 for-loop，无法表示 condition/branch/parallel |
| 5 | tenant_account_joins 多租户账号（跨域 #30） | 无 | RBAC 设计已定，表已建，仅缺业务逻辑——30 min |
| 6 | policies + policy_bindings 表启用（M7+ #21/22） | 无 | M2 PolicyLayer 目前硬编码 role.permissions 检查，启用 policy 表后策略可动态配置 |

---

## 三、中期（Phase 2，需 API Key 或自建服务）

| # | 项 | 外部依赖 | 理由 |
|:--|:---|:-----|:-----|
| 7 | 真实 embedding 模型（OpenAI ada-002 或 local） | API Key 或 Ollama | M4 伪随机向量导致同 query 不同结果——RAG 场景硬伤 |
| 8 | LLMConnector.with_structured_output | API Key | M3 plan_structured() placeholder——Plan 校验的正确性依赖 structured output |
| 9 | LLMConnector._cache | 无（redis 已有） | 调用 LLM 前先查缓存——降成本 |

---

## 四、远期（Phase 3+，需架构决策或重设计）

| # | 项 | 原因 |
|:--|:---|:-----|
| 10 | Audit Service 拆独立进程 | 当前 fire-and-forget EventBus——独立进程需 broker 选型确认（M6 已用 Redis Streams） |
| 11 | LLM Planner 真实调用 | 依赖 #7 + #8 完成后才有意义 |
| 12 | 完整 Saga/TCC | 需要先有 #4 Workflow DSL 表达补偿链 |
| 13 | 剩余 DDL 表（org_units/service_accounts/connector_bindings 等） | 按需启用——不要一次性全部建逻辑 |
| 14 | Plugin gRPC Daemon / Connector Daemon 独立化 | 运维复杂度高，单人团队收益小 |
| 15 | LiteLLM / Langfuse / Evaluation Center | 有 LLM 调用后再考虑不迟 |

---

## 建议执行顺序

```
本周:
  1. e2e 全链路测试 (优先——验证 7 里程碑真实可用)
  2. Makefile 一键启动

下周起:
  3. Workflow DSL（M5 剩余）
  4. policy 表启用（M2 增强）
  5. tenant_account_joins（跨域）
  
Phase 2（需 API Key 时）:
  6. 真实 embedding
  7. LLM structured output
  8. LLM cache

Phase 3 以后（等前序完成）:
  9. Audit Service 独立 → LLM Planner → Saga 完整
```

---

## 核心原则

1. **先验证，后堆功能**——7 里程碑代码量已大，先确认真实可用（e2e 测试）
2. **无外部依赖优先**——DSL/Policy 表/多租户账号都只需要写代码
3. **嵌入 → 结构化输出 → LLM 调用**是顺序依赖链，不要跳跃
4. **DDL 表按需启用**，不要预留表一次性全建逻辑
5. **单人团队不做重运维**——Audit 拆分、Plugin Daemon 等搁置到真正需要时
