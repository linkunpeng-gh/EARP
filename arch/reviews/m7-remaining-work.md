# EARP 服务端——待开发内容清单

> 基于 server-side-development-plan v1.4、DDL 表使用率矩阵（全景评审第 2 刀）、技术债务清单。

---

## 一、Phase 2 嵌入与 LLM 深化（M4→Phase 2）

| # | 内容 | 当前状态 |
|:--|:-----|:-----|
| 1 | 伪随机 embedding(1536d)→真实模型(OpenAI text-embedding-ada-002 或本地) | M4 embedding_service.py 预留 |
| 2 | LLMConnector._cache — LLM 响应缓存 | M3 connector.py 留 None |
| 3 | LLMConnector.bind_tools — Capability 候选作为 LLM tool | M3 声明留 Phase 3 |
| 4 | LLMConnector.with_structured_output — Pydantic Plan schema 校验 | M3 plan_structured() placeholder |
| 5 | Langfuse 可观测集成 | tech-reference §四 遗留分析 |

---

## 二、Phase 3 LLM + 完整 Saga

| # | 内容 | 当前状态 |
|:--|:-----|:-----|
| 6 | LLM Planner 真实调用（当前 M3 走 RuleIntentPlanner fallback） | M3 LLMConnector.plan() |
| 7 | 完整 Saga/TCC 补偿模式（当前 M5 最小版：register compensate + LIFO rollback） | plan §5 明确排除到 Phase 3 |
| 8 | LiteLLM 网关深度分析（M3 前遗留） | tech-reference §四 |
| 9 | Evaluation Center 闭环 | plan §排除 |

---

## 三、M5 未完成项

| # | 内容 | 当前状态 |
|:--|:-----|:-----|
| 10 | batch() 接口实现或被 M5 for-loop 替代 | step_runner.py:77 NotImplementedError |
| 11 | checkpoint_writes 表启用 | DDL 已建，M5 未写 |
| 12 | REPLANNING + interrupt(human_approval) 完整实现 | PRD-2026-025 定义但 M5 未实现 |
| 13 | Workflow Engine DSL 编译 | plan M5 列但未进入 PRD-2026-025 范围 |

---

## 四、M6 未完成项

| # | 内容 | 当前状态 |
|:--|:-----|:-----|
| 14 | stream() 接口实现 + WebSocket token streaming | step_runner.py:74 NotImplementedError |
| 15 | Audit Service 拆独立消费者进程 | plan M6 列但未实现 |
| 16 | WebSocket 端点 JWT 鉴权 | 全景评审 P2-1 |

---

## 五、M7 未完成项 + 11 张 DDL 预留表

| # | 表/功能 | 用途 |
|:--|:-----|:-----|
| 17 | org_units | 组织架构（M7+） |
| 18 | service_accounts | 服务账号（M7+） |
| 19 | capability_calls | 能力调用审计（M7+） |
| 20 | connector_bindings | 连接器绑定（M7+） |
| 21 | policies | Policy 实体管理（M7+，当前 M2 PolicyLayer 只用了 policy_bindings 概念但未写 policies 表） |
| 22 | policy_bindings | Policy 绑定实现（M7+） |
| 23 | encrypted_credentials | Vault/KMS 凭证加密（M7 Plugin gRPC Daemon） |
| 24 | api_keys | API Key 认证（M7+） |
| 25 | connector_configs | 连接器配置持久化（M7+） |
| 26 | Connector Daemon 独立化 | M7 plan 列但未实现 |
| 27 | Plugin gRPC Daemon（子进程沙箱） | M7 plan 列但 M7 只做了安装流程骨架 |

---

## 六、跨域增强

| # | 内容 | 当前状态 |
|:--|:-----|:-----|
| 28 | Capability 语义发现切 pgvector（当前 M1 用 LIKE 精确匹配） | plan M4 列但 M4 未实现 |
| 29 | RBAC data_scope=department/org 完整实现（M2 只实现了 self/all） | M2 PolicyLayer 预留 |
| 30 | tenant_account_joins 多租户账号关联 | RBAC 设计引用，未实现 |

---

## 总结

| 类别 | 数量 |
|:-----|:----:|
| Phase 2（嵌入+LLM深化） | 5 |
| Phase 3（LLM+Saga完整） | 4 |
| M5+M6 未完成 | 7 |
| M7+ DDL 预留表 | 11 |
| 跨域增强 | 3 |
| **合计** | **30** |

所有未完成项均有明确的文档锚点（PRD/技术债务清单/DDL 表名），可直接进入各自 Phase 的 PRD 流水线。
