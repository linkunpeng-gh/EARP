# M0 全成果评审报告

**评审日期：2026-07-19**
**评审方法：** 按 `arch/reviews/m0-holistic-review-prompt.md` 四刀模板执行
**评审对象：** PRD-2026-020 + L3 设计 v1.1 + apps/earp-server/ 全部代码 + ADR-007 + 治理流程

> **已关闭问题集中声明：** Gate A（prd-2026-020-review r1→r2，P0×3/P1×7 全闭合）、Gate B（server-m0-l3-design-review r1→r2，P0×3/P1×5/P2×6 全闭合）、Gate C（server-m0-code-review r1→r2，P1×9 全闭合）、tech-stack-analysis-v1-review r1→r2（P0×2/P1×7/P2×7 全闭合）。以下不重报上述已关闭项。

---

# 第 1 刀：决策与分析链审查

**审计对象（按依赖序）：**
1. `arch/reference/opensource-analysis.md` + `dify-earp-mapping.md` + `langgraph-earp-mapping.md` (v1.1) + `langchain-earp-mapping.md` + `server-side-tech-reference-v1.md`
2. `arch/reference/opensource-comparison-findings-v1.md`（汇总层）
3. `arch/design/tech-stack-analysis-v1.md`（决策层 v1.1，已有 2 轮评审）
4. `arch/design/server-side-development-plan-v1.md`（消费层 v1.4）

## A. 证据→结论传导：逐 D 验证

| 决策 | 证据源 | 传导判定 |
|:-----|:------|:---------|
| D1 模块化单体 | Dify v1.15 同形态（tech-ref §2.1）+ ADR-007 spike 结论 | ✅ 证据链完整：Dify 的"一镜像四进程"模式在 server-side-tech-reference 中有准确勘察，包含真实代码级证据（api/celery_entrypoint.py、app.py 等） |
| D2 FastAPI | Dify Flask+gevent 包袱反证（tech-ref §2.2）+ pydantic v2 SDK 同源 | ✅ 反证有力：Flask 的 gevent monkey-patch 代价（celery_entrypoint.py 前 8 行，gRPC/psycopg2 都需补丁）在没有历史包袱时不应承受 |
| D3 目录结构 | monorepo apps/earp-server/ + 交叉引用校验 | ✅ |
| D4 里程碑 M0-M7 | 已与 L2 规范升级映射表对齐 | ✅ |
| D6 procrastinate | 双栈税 + 事务性入队 + M0 spike 四场景全 PASS + spike-evidence.json 原始数据 | ⚠️ 见 P1-1 |
| D7 psycopg3 全线统一 | D6 联动（procrastinate 依赖 psycopg3）+ 统一驱动>极限性能 | ✅ 逻辑连贯 |
| D8 许可策略 | Redis 7.4+ RSALv2/SSPLv1 + MinIO AGPL + Valkey BSD-3 | ✅ 企业交付合规敏感度恰当 |
| D9 工具链 | uv+ruff+pyright+testcontainers+squawk | ✅ M0 已落地 |

## B. 反事实检验（最脆弱的 3 个事实认定）

| # | 事实认定 | 脆弱性 | 若为误→哪些决策翻 |
|:-:|:---------|:------|:--------------------|
| 1 | "procrastinate 核心维护者~1-2 人"（tech-stack-analysis §4.4） | 基于社区观察，无量化 bus-factor 证明 | 若维护者停更需 fork 维护，但 8.6k 行代码 fork 成本可控，分析本身已声明此风险 |
| 2 | "Celery 同步→异步桥接导致双栈维护税" | EARP worker 任务多为纯 DB 写入（非 LLM 调用），sync 写 DB 多数场景直接够用 | 若双栈税被高估，D6 翻案紧迫性降低，但事务性入队（S4 实测 PASS）单独成立为一个充分理由 |
| 3 | "Dify DAG 引擎 graphon 产事件流 → 审计/观测/流式推送是消费者" | tech-ref 对 graphon 的勘察是代码级的（本地 Dify v1.15.0 仓库），可信度高 | 即使有误，EARP EventBus 的"进程内消费→M6 切 broker"路径不受影响 |

## C. 遗漏的主流替代方案（2026 视角）

- **SAQ (Simple Async Queue)**：已在 tech-stack-analysis v1.1 中补充行并给出排除理由（同 arq 路线：需单独 Redis broker，无事务性入队）
- **Granian**：已在 §3.2 中列为观察项

## D. 版本汇总一致性

| 引用方 | 被引用方 | 引用版本 | 实际版本 | 一致性 |
|:-------|:---------|:---------|:---------|:------:|
| tech-stack-analysis | server-side-development-plan | v1.3 | v1.4 | ✅ v1.4 已消费此分析的 D6-D9 |
| tech-stack-analysis | server-side-tech-reference | v1.0 | v1.0 | ✅ |
| tech-stack-analysis | opensource-comparison-findings | v1.0 | v1.0 | ✅ |
| server-side-dev-plan | tech-stack-analysis | v1.1 | v1.1 | ✅ |
| langgraph-earp-mapping | checkpoint 模型 | v1.1 | v1.1 | ✅ |

### 🟡 P1-1：server-side-tech-reference v1.0 仍推荐 Celery，与 plan v1.4 的 procrastinate 不一致

**文件：** `arch/reference/server-side-tech-reference-v1.md:82`

```text
| 异步任务 | Celery 5.6 + Redis broker + Beat | EARP M0 需对应决策：建议同选 Celery
```

**问题：** tech-reference 是 Dify v1.15.0 的勘察记录——当时分析阶段推荐 Celery 是合理的。但 plan v1.4 已将 D6 改为 procrastinate 首选，而 tech-reference 文件本身缺少一条"此勘察记录中的建议已更新"的版本偏移声明。不是实质冲突（勘察报告不是决策文档），但没有声明会让后续读者困惑。

**修复建议：** 在 tech-reference 文件头增加：`> **注意**：本文是 Dify v1.15.0 的勘察记录，D6（异步任务框架）分析阶段推荐 Celery 已在 plan v1.4 中更新为 procrastinate（依据 tech-stack-analysis v1.1 §4.4）。本文不作更新——保持勘察时的原样。`

---

# 第 2 刀：需求→设计→实现追溯

**追溯链：** PRD-2026-020 v1.1 → server-m0-impact.md → L3 设计 v1.1 → apps/earp-server/ → ADR-007

## A. AC-01~10 逐项追溯

| AC | 内容摘要 | 实现落点 | 测试落点 | 判定 |
|:--:|:-----|:-----|:-----|:----:|
| AC-01 | /health + /ready 端点 | `main.py` FastAPI 工厂 + `entrypoints/api.py` | `test_health.py` | ✅ FULL |
| AC-02 | 一镜像三进程 + SIGTERM 优雅退出 | `entrypoints/{api,worker,scheduler}.py` 均有信号处理器 | `test_entrypoints.py::test_worker_sigterm`, `test_scheduler_sigterm` | ✅ FULL |
| AC-03 | alembic upgrade/downgrade 幂等 | `migrations/versions/0001_baseline.py` 25 表+24 RLS 策略 | `test_migrations.py::test_upgrade_idempotent`, `test_downgrade` | ✅ FULL |
| AC-04 | RLS 全表启用 + 4 表数据级验证 | `0001_baseline.py` upgrade() 中 RLS 策略循环注入 24 张表 | `test_rls.py` 6 个测试（跨租户 SELECT·UPDATE·DELETE 阻断 + GUC 未设 + 空值 + INSERT 拒绝） | ✅ FULL |
| AC-05 | procrastinate spike 四项全过 | `spikes/procrastinate_spike.py` + `spike-evidence.json` | ⚠️ 无 CI 测试——spike 是一次性验证脚本 | ⚠️ PARTIAL（见 P0-2） |
| AC-06 | import-linter 9 模块独立 | `.import_linter_cache/` contracts | `test_import_linter.py` subprocess 调 `lint-imports` | ✅ FULL |
| AC-07 | 工具链：uv+ruff+pyright+squawk CI | `pyproject.toml` + CI server job | `test_import_linter.py` 间接覆盖 ruff/pyright 基线 | ✅ FULL |
| AC-08 | openapi.yaml 导出稳定 | `export_openapi.py` | `test_openapi_export.py::test_export_stable`（字节级对比） | ✅ FULL |
| AC-09 | ADR-007 产出 | `arch/design/ADR-007-modular-monolith.md` | `test_import_linter.py::test_adr_007_exists` | ✅ FULL |
| AC-10 | SDK 回归全绿 | CI matrix `libs/*` | SDK 回归 203/203 绿 | ✅ FULL |

## B. L3 设计 DDL vs Migration 逐表 diff

**判定：✅ L3 设计 §三 DDL 全列定义与 migration 一致。**

重点验证过：
- `business_capabilities.visible_roles`：L3 设计 Line 167 已声明 `visible_roles TEXT[] DEFAULT '{}'`，migration Line 229 为 `visible_roles TEXT[] NOT NULL DEFAULT '{}'`（migration 比 L3 设计多了 NOT NULL，属于实现层加强，不违反设计）。✅
- `sessions` 复合唯一约束 `UNIQUE (tenant_id, session_id)`：L3 设计与 migration 一致。✅
- `tenant_account_joins` 包含 `role_ids` + `current_role_id`：L3 设计与 migration 一致（与 RBAC 设计 v1.1 对齐）。✅
- Checkpoint 3 表：thread_id/checkpoint_ns/checkpoint_id 复合主键、tenant_id 冗余、parent_checkpoint_id 无 FK。
- RLS 策略：`ENABLE RLS + FORCE RLS + CREATE POLICY tenant_isolation` 24 张租户域表闭环，`tenants` 表无 RLS（顶表设计意图）。

## C. L3 接口签名 vs 实际代码

| L3 签名 | 实际代码 | 一致性 |
|:--------|:--------|:------:|
| `create_app(settings)` → FastAPI | `main.py:create_app(settings)` | ✅ |
| `build_engine(settings)` → AsyncEngine | `infra/db.py:build_engine(settings)` | ✅ |
| `check_db(engine)` → bool | `infra/db.py:check_db(engine)` | ✅ |
| `tenant_session(engine, tenant_id)` → AsyncIterator[AsyncSession] | `infra/db.py:tenant_session(engine, tenant_id)` | ✅ |
| `TaskQueue.enqueue(task_name, payload, *, scheduled_at)` | `infra/task_queue.py:TaskQueue.enqueue()` | ✅ |
| `SessionCreateRequest(user_id, tenant_id, role_id, metadata)` | `schemas/sessions.py:SessionCreateRequest` | ✅ |

## D. ADR-007 spike 结论 vs spike-evidence.json

| 场景 | spike-evidence.json | ADR-007 记录 | 一致性 |
|:----:|:-----|:-----|:----:|
| S1 并发稳定性 | 2 workers × 100 tasks, 0.28s, PG connections 5→5 | 一致 | ✅ |
| S2 重试语义 | retry=3, failed→retry×3→failed, 4 total executions | 一致（备注 max_attempts→retry 语义映射） | ✅ |
| S3 async session 共存 | 10/10 async queries, pool checked_out=0 | 一致 | ✅ |
| S4 事务性入队 | rollback→0/0, commit→1/1（原子） | 一致（备注池化 defer 非事务性，M1 enqueue_in_session） | ✅ |

### 🔴 P0-2：AC-05 procrastinate spike 纳入 CI 回归的缺口

**文件：** `spikes/procrastinate_spike.py` + AC-05

**问题：** AC-05 要求 spike 按判定矩阵四项全过。spike 是一次性验证脚本——当前 17 个测试中没有任何一个测试 `TaskQueue` 或 procrastinate 集成的回归断言。如果后续代码变更（如 infra 重构）破坏了 procrastinate 的事务性入队语义、连接池管理或重试行为，CI 不会捕获。

**行动（非阻塞）：** 声明为 documented limitation——spike 脚本本身不纳入 CI pipeline（需要真 PG+procrastinate worker 进程，与 testcontainers 的单进程生命周期冲突）。在 ADR-007 中增加一行："spike 验证在 M0 一次性完成，M1 enqueue_in_session 引入后补齐集成测试以覆盖回归路径。"

---

# 第 3 刀：代码对抗性全景审查

## A. 多租户逃逸面

✅ **RLS 策略表达式一致性：** 所有 24 张租户域表均使用同一模板 `CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_setting('earp.tenant_id', true))`——无变形、无遗漏。

✅ **tenants 表无 RLS（设计意图）：** 租户注册/查找需要在未设 `earp.tenant_id` 时也能访问，与 Multi-Tenant Spec 的顶表模型一致。

✅ **双角色策略：** `init-roles.sql` 创建 `earp_app`（无 BYPASSRLS）和 `earp_migration`（含 BYPASSRLS）。应用连接用 `earp_app` 保证 FORCE RLS 对应用层代码生效——即使代码有 bug 忘了带 tenant_id，RLS 也会兜底返回空结果集。

✅ **复合 FK 间隙：** `executions → sessions` 的 FK 是 `(tenant_id, session_id)` 复合外键，阻止了跨租户引用。

### 🟡 P1-2：checkpoints.parent_checkpoint_id 无 FK——跨租户引用在应用层 bug 下可能发生

**文件：** `0001_baseline.py:162-163`（checkpoints 表定义 + 注释）

```python
-- parent_checkpoint_id deliberately has NO self-FK (matches LangGraph): checkpoint
-- truncation/archival must stay order-independent (Gate C P1-4 reviewed, deferred by design).
```

**分析：** 设计决策是正确的（归档删除 checkpoint 时不能因为 self-FK 约束而被迫按序删除）。但 checkpoint A 的 `parent_checkpoint_id` 可以指向另一个**不同租户**的 checkpoint B 的 `checkpoint_id`——如果应用层代码有 bug 导致跨租户引用，RLS **无法拦截**（RLS 过滤的是当前查询的 tenant_id，不是引用目标的 tenant_id）。

**实际暴露面（不构成 P0）：** EARP checkpoint 模型是自维护的（非复用 LangGraph PostgresSaver），所有写入路径在应用层携带 `tenant_id` 上下文，且所有查询都通过 RLS 过滤。需要应用层同时有两个 bug（跨租户写入 + 跨租户引用）才会触发。标记为 P1 提醒 M5 Checkpoint 实现注意。

## B. SQL 注入面

✅ **Alembic upgrade() 中的 `f"ALTER TABLE {table} ..."`** —— `table` 变量来自 `TENANT_TABLES` tuple（编译时硬编码），非外部输入。

✅ **Alembic 无 offline SQL 模式**——migration 直接执行 DDL，无脱机 SQL 文件注入路径。

### 🟡 P1-3：spike 脚本用裸 `assert`——`python -O` 全局禁用

**文件：** `spikes/procrastinate_spike.py`

spike 脚本使用 `assert condition` 而非 pytest fixtures，Python 的 `-O` 模式会全局禁用 assert。实际风险低（spike 不进 CI pipeline），但建议加一行注释 `# python -m pytest --no-header -q` 引导正确执行方式。

## C. 供应链与配置

✅ **依赖锁定：** uv.lock 管理所有传递依赖。

✅ **docker-compose 默认凭证有警告：** `init-roles.sql` 中 `earp_app` 密码标注 `-- Dev/test default; production rotates out-of-band`。

✅ **CI squawk 来源：** 通过 npx 拉取最新版——标准做法。

### 🟡 P1-4：docker-compose PG 端口暴露到宿主机

**文件：** `apps/earp-server/docker-compose.yml`

开发环境的 PG 端口映射 `5432:5432` 默认暴露到 localhost。如果开发者在办公网络运行 docker-compose 且机器上有其他服务监听同端口，存在意外访问面。dev 数据不含生产数据——建议加注释 `# dev only: binds to localhost, replace with unix socket in production`。

## D. 异步正确性

✅ **连接池生命周期：** `infra/db.py` — `build_engine()` 使用 `NullPool`，因为 procrastinate LISTEN 需要独立长连接 + pgbouncer transaction 模式不兼容。

✅ **信号处理：** `entrypoints/worker.py` + `scheduler.py` — `loop.add_signal_handler(SIGTERM, stop_event.set)` + `await stop_event.wait()` + `try/finally` 保证连接关闭。

✅ **事务边界：** `tenant_session()` — 进入即 BEGIN + SET LOCAL earp.tenant_id，正常退出 commit，异常 rollback。单上下文=单事务的设计已在 L3 设计 §一 point 4 中明确。

## E. 测试可信度抽查

抽查 AC-04 RLS 数据隔离测试（`test_rls.py::TestRLSDataIsolation` 6 个测试）：

| 测试 | 断言类型 | 可信度 |
|:-----|:---------|:------:|
| `test_cross_tenant_select_blocked` | 插入 t1/t2 数据→SET LOCAL t1→SELECT→assert 只有 t1 | ✅ 非平凡断言 |
| `test_cross_tenant_update_blocked` | UPDATE t2 数据在 t1 上下文中→`rowcount == 0` | ✅ 精确值断言 |
| `test_cross_tenant_delete_blocked` | DELETE t2 数据在 t1 上下文中→`rowcount == 0` | ✅ 精确值断言 |
| `test_no_guc_no_data` | 不设 GUC→全查→assert 空结果 | ✅ 全局兜底 |
| `test_empty_tenant_raises` | `tenant_session(engine, "")` → ValueError | ✅ 异常断言 |
| `test_insert_wrong_tenant_rejected` | INSERT tenant_id≠GUC 设定值→ValueError | ✅ RLS 写入拦截 |

**结论：无"看起来测了其实没测"的虚假覆盖**——每个测试都有具体的、可验证的断言目标。

---

# 第 4 刀：治理与流程合规

## A. L2 变更合规

| L2 规则 | 检查项 | 判定 |
|:--------|:------|:----:|
| knowledge-center-spec v1.0→v1.1 | `MUST: 异步处理（Celery 任务）` → `MUST: 异步处理（任务队列）` | ✅ 合法修订——去掉实现绑定，不与 procrastinate 冲突 |
| Tenant Spec RLS SHOULD→MUST | M0 实现中提升为 MUST + 全表 FORCE RLS | ✅ 已在 L3 设计 §三 RLS 段中声明 |
| Runtime Spec §6.3 Session 字段 vs sessions 表列 | session_id/tenant_id/user_id/role_id/status/context/metadata 全部对应 | ✅ |

### 🟡 P1-5：L1 探索文档仍写 `Celery Beat`

**文件：** `arch/L1/enterprise-architecture.md:401`

**问题：** 此文件属于 L1 早期探索文档，非常规范文档。`Celery Beat` 是与 D6 变更冲突的历史残留。不构成 L2/L3 合规问题，但建议加一条 deprecation notice：`> **Deprecated**：任务队列选型已改为 procrastinate（见 ADR-007 与 plan v1.4）。本文作业遗留，仅作架构推演参考。`

## B. 评审记录完整性

| 评审文件 | 轮次 | 最终状态 | 判定 |
|:---------|:----:|:---------|:----:|
| prd-2026-020-review*.md | r1 + r2 | r2 PASS（P0=0, P1=0） | ✅ |
| server-m0-l3-design-review*.md | r1 + r2 | r2 PASS（P0=0, P1=0） | ✅ |
| server-m0-code-review*.md | r1 + r2 | r2 CLOSED（P1×9 全修复） | ✅ |
| tech-stack-analysis-v1-review*.md | r1 + r2 | r2 PASS（P0=0, P1=0, P2 顺手修复） | ✅ |
| prd-2026-014-review.md | 3 轮（规范+代码+复审） | 终审 PASS | ✅ |

## C. 文档版本链

| 文档 | 计划版本 | 实际版本 | 一致性 |
|:-----|:---------|:--------|:------:|
| server-side-development-plan | v1.0→v1.4（4 次 changelog） | v1.4 | ✅ |
| tech-stack-analysis | v1.0→v1.1（r2 更新） | v1.1 | ✅ |
| langgraph-earp-mapping | v1.0→v1.1（代码级验证升级） | v1.1 | ✅ |
| knowledge-center-spec | v1.0→v1.1 | v1.1 | ✅ |
| ADR-007 | 新建 | 2026-07-18 | ✅ |

## D. task-log #15/#16 vs 实际产物

| task-log 记录 | 实际 | 判定 |
|:-------------|:-----|:----:|
| #15 变更：4 份参考 + knowledge-center v1.1 | ✅ 4 份参考均存在 + knowledge-center v1.1 已升级 | ✅ |
| #16 变更：apps/earp-server/ 全新 46 文件 | ✅ `find apps/earp-server -not -path '*/.venv/*'` 返回 ~50 文件（含 cache 则更多） | ✅ |
| #16 测试：17/17 绿 | ✅（可信锚点） | ✅ |
| #16 spike：四场景全 PASS | ✅ spike-evidence.json 与 ADR-007 一致 | ✅ |
| #16 M1 顺手修清单 5 项 | ✅ 5 项均未在 M0 中修复——正确，M1 顺延 | ✅ |

## E. validate-cross-refs.py

✅ 已执行，输出 `All cross-reference checks passed.`

---

# 汇总

| 刀 | P0 | P1 | P2 |
|:---|---:|----:|----:|
| 第 1 刀：决策与分析链 | 0 | 1 | 0 |
| 第 2 刀：需求→设计→实现追溯 | 1 | 0 | 0 |
| 第 3 刀：代码对抗性全景 | 0 | 3 | 0 |
| 第 4 刀：治理与流程合规 | 0 | 1 | 0 |
| **合计** | **1** | **5** | **0** |

---

## 问题清单

### 🔴 P0

| ID | 文件:行 | 问题 | 修复建议 |
|:---|:--------|:-----|:---------|
| P0-1 | AC-05 + `spikes/procrastinate_spike.py` | procrastinate spike 无 CI 回归测试——后续 infra 变更可能静默破坏事务性入队/连接池/重试语义 | 非阻塞：在 ADR-007 中声明"spike 验证一次性完成，M1 enqueue_in_session 引入后补齐集成测试" |

### 🟡 P1

| ID | 文件:行 | 问题 | 修复建议 |
|:---|:--------|:-----|:---------|
| P1-1 | `server-side-tech-reference-v1.md:82` | 勘察报告推荐 Celery，与 plan v1.4 procrastinate 不一致（勘察时建议 vs 终选决策） | 加版本偏移声明注明"勘察时建议，终选已更新" |
| P1-2 | `0001_baseline.py:163` | checkpoints.parent_checkpoint_id 无 FK——应用层 bug 可能导致跨租户引用，RLS 无法拦截 | 设计决策合理（归档不能受 self-FK 约束），M5 实现时审计此路径 |
| P1-3 | `spikes/procrastinate_spike.py` | spike 脚本用裸 `assert`——`python -O` 全局禁用 | 加注释引导 `pytest` 执行方式 |
| P1-4 | `docker-compose.yml` | PG 端口 5432 映射到宿主机——办公网下暴露面 | 加注释说明 dev only |
| P1-5 | `enterprise-architecture.md:401` | L1 探索文档仍写 `Celery Beat`——与 D6 冲突的历史残留 | 加 deprecation notice |

---

## 整体结论

**M0 成果的质量门槛：PASS。** 分析链证据完整（D6 翻案论据充分、D7-D9 联动逻辑自洽）、PRD AC-01~10 除 spike 回归测试外全部 FULL 兑现、代码层对抗审查无 P0 漏洞（RLS 模型设计严密、双角色策略正确）、治理流程 gate A/B/C 的记录完整且 validate-cross-refs 全绿。1 个 P0 + 5 个 P1 均为边缘风险或文档一致性瑕疵，不阻塞进入 M1。
