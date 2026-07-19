# ADR-007：服务端工程形态——模块化单体先行 + 技术栈终选

| 字段 | 值 |
|------|-----|
| **状态** | Accepted（2026-07-18） |
| **决策层级** | L1 补充（工程形态；不修改部署架构目标态） |
| **依据** | server-side-development-plan v1.4（D1-D9）；tech-stack-analysis v1.1（评审关闭 P0=0）；opensource-comparison-findings v1.0（Dify v1.15 实证） |
| **实施** | PRD-2026-020（M0，Gate A/B PASS） |

---

## 1. 决策

1. **模块化单体先行**：服务端以单一 FastAPI 应用承载 9 个域模块（gateway/runtime/capability/policy/planner/knowledge/conversation/schedule/audit），模块边界 = 部署架构服务边界，import-linter independence 契约在 CI 强制（M0 起生效）。
2. **一镜像多进程**：同一代码库以不同 entrypoint 跑出 `api` / `worker` / `scheduler` 三进程角色（M6 增 `websocket`）；扩容拆进程不拆代码库；仅安全边界（Plugin Daemon/沙箱/出口代理）独立成服务（M7）。
3. **技术栈终选**：见 server-side-development-plan v1.4 §5.2 全表——Python 3.12 / FastAPI+uvicorn / SQLAlchemy 2 async / **psycopg3 全线（D7）** / **procrastinate（D6，见 §3 spike 结论）** / Redis 7.2 命令面+Valkey 双验证（D8a）/ S3 API only（D8b）/ uv+ruff+pyright+testcontainers+squawk（D9）。
4. **与部署架构的关系**：deployment-architecture v1.1 描述 **prod 目标态**（11 服务 + Istio + per-tenant namespace），本 ADR 不修改之；dev/MVP 阶段以单体承载同一套逻辑拓扑，拆分路径在模块边界处保留（Phase 2+ 按部署架构执行）。

## 2. 理由（摘要，证据见依据文档）

- Dify v1.15 以同形态服务生产级多租户 SaaS（一镜像四进程实证，tech-reference §2.1）；
- 单人开发直接微服务 = 11×(镜像+Helm+mTLS) 不可承受的运维负担；
- SDK 5 包已锁定 asyncio/httpx/pydantic 栈，FastAPI 同源，Flask+gevent 为反例；
- Celery 的 sync-first 与全异步服务端形成永久性"双栈维护税"，procrastinate 以 PG 为 broker 消除之并带来事务性入队（spike S4 实证）。

## 3. spike 结论（AC-05，2026-07-18 实测）

**判定：四场景全 PASS → D6 定案 procrastinate 3.6（MIT）。** 证据：`apps/earp-server/spikes/spike-evidence.json`。

| 场景 | 结果 | 关键数据 |
|:-----|:----:|:---------|
| S1 并发稳定 | PASS | 2 worker × 100 任务 0.28s 全完成；PG 连接数 5→5 无泄漏 |
| S2 重试语义 | PASS | retry=3 → 失败后重试 3 次（总执行 4 次）终态 failed |
| S3 async session 共存 | PASS | 任务内 SQLAlchemy async session 10/10 查询成功；pool checked_out=0 |
| S4 事务性入队 | PASS | 同一连接事务内业务行+job 行：回滚后 0/0，提交后 1/1（原子） |

**语义映射备忘（实现约束）**：
1. procrastinate `retry=N` = 首次执行后再重试 N 次（共 N+1 次执行）；EARP `ConnectorRetryConfig.max_attempts`（总次数，Temporal 惯例）→ 映射 `retry = max_attempts - 1`。
2. **事务性入队的准确语义（Gate C P1-9 澄清）**：S4 证明的是"job 行与业务行在同一连接事务内原子提交/回滚"（同事务插入模式）；procrastinate 的 `defer_async` 默认走自身连接池、**不**参与调用方事务。生产路径（M4 KB 索引等）采用同会话插入模式——M1 在 TaskQueue 增加 `enqueue_in_session(session, ...)` API，池化 `enqueue` 仅用于无事务耦合场景。
3. TaskQueue 薄抽象已封装上述差异（`infra/task_queue.py`），业务代码不感知 procrastinate。

**回退预案**：TaskQueue Protocol 保留 Celery 实现位（tech-stack v1.1 §4.4 远期迁移路径），若生产期吞吐成为瓶颈可换实现类，业务代码零改动。

**spike 回归覆盖声明**：spike 验证在 M0 一次性完成（四场景 PASS，证据 `spikes/spike-evidence.json`）。spike 脚本本身不纳入 CI pipeline（需真 PG + procrastinate worker 进程，与 testcontainers 单进程生命周期冲突）。M1 `enqueue_in_session` 引入后补齐 TaskQueue 集成测试覆盖回归路径（Gate C P1-9 承诺）。

## 4. 后果

**正面**：基础设施最小化（M4 前仅 PG+可选 Redis）；契约测试可用 SDK 测试双跑；模块拆分路径由 import-linter 契约保真。
**负面/接受的风险**：procrastinate 社区小（bus factor——8.6k 行实测，fork 成本可控）；单体形态下单点资源竞争（多进程缓解，拆分预案在）；uvicorn SIGTERM 退出码 143（K8s 正常终止语义，已文档化）。

## 5. 关联

- 冲突清单：tech-stack-analysis v1.1 附录 A（L2 knowledge-center-spec v1.1 已同步去 Celery 绑定）
- 实施验收：PRD-2026-020 AC-01~AC-10；测试 14/14 绿；squawk 0 issues
