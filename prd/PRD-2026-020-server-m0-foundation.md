# PRD-2026-020 v1.1

## M0 — 服务端脚手架 + DDL 基线 + procrastinate spike

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-020 |
| **Feature** | 服务端里程碑 M0：apps/earp-server 工程脚手架（一镜像多进程）、Alembic 基线 DDL（8 数据域 + checkpoints 3 表 + RLS）、procrastinate spike、工具链落地、openapi.yaml 契约初版、ADR-007 |
| **对齐规范** | Tenant Spec v1.2 §5.1（RLS 兜底）+ §5.4（role_id 三层防线，**role_id 的规范权威来源**）；Runtime Spec v1.3 §6.3（Session 基础字段）；Audit Spec v1.1/v1.2 变更（audit_logs.detail 含 role_id/user_roles）；Knowledge Base Spec v1.0 §2.2（Document/Chunk 已锁定列）；Concept Model v2.1 §5.8（Data Domain）；data-architecture v1.0（8 域实体/索引/迁移策略）；RBAC 设计 v1.1 §3.1（Role 实体）+ §3.2（RLS SQL 模式）+ §4.3（DDL 清单）；Policy Center Spec v1.2 §5.1（Data Domain 授权） |
| **决策依据** | server-side-development-plan v1.4（M0 定义 + D1-D9）；tech-stack-analysis v1.1（评审关闭，P0=0） |
| **优先级** | **P0**（服务端一切后续里程碑的地基） |
| **版本** | v1.1（Gate A r1 修复稿） |
| **日期** | 2026-07-18 |

---

## 1. 背景

服务端代码量为 0。M1（最小闭环）开工的前置条件是：工程骨架存在、数据库基线可迁移、任务队列选型经 spike 定案、CI 能跑服务端测试。本 PRD 一次性交付这些地基，并把技术栈终选固化为 ADR-007。

范围克制：**不含任何业务端点**（sessions API 属 M1）——M0 只交付"能启动、能迁移、能跑测试的空壳 + 已定案的技术决策"。

进程模型说明（P1-6）：三个 entrypoint（`earp_server.entrypoints.{api,worker,scheduler}`）实现 plan v1.4 §5.1 规则 #5 的一镜像多进程——api 启动 uvicorn，worker 启动 procrastinate worker，scheduler 启动调度循环（M0 为空转骨架）。

## 2. 用户故事

| US | 描述 | 类型 |
|:--:|:-----|:----:|
| US-01 | 作为开发者，克隆仓库后执行 `make dev`（内部串起 docker compose up -d → alembic upgrade head → uvicorn 启动），得到可访问 /health 的服务端骨架 | 基础设施 |
| US-02 | 作为开发者，我需要 8 数据域的基线表结构一次性建好（含 role_id 列与 RLS 策略），M1-M7 仅做非破坏性 ADD COLUMN/索引追加，不做破坏性重建 | 数据 |
| US-03 | 作为架构决策者，我需要 procrastinate 按判定矩阵完成 spike，D6 从"建议"变为"定案"（或有据回退 Celery） | 决策 |
| US-04 | 作为开发者，模块边界（模块间禁止 import 内部实现）由 CI 自动强制，而不是靠自觉 | 工程纪律 |
| US-05 | 作为 SDK 维护者，服务端的 API 契约以 openapi.yaml 固化入库，与 runtime-py 客户端的端点定义可自动比对（校验规则 R5 预留） | 契约 |
| US-06 | 作为异常路径：迁移在脏库/半迁移状态下重复执行不产生副作用（幂等），降级路径 alembic downgrade -1 可回退 | 数据/异常 |

**边界条件声明**：M0 开发与测试硬依赖本机 Docker（testcontainers/docker-compose）；无 Docker 环境不在支持范围（documented limitation）。/health 与 /ready 均无认证（K8s 探针语义，部署架构 §2.2）。

## 3. 核心数据结构（DDL 基线清单）

> 完整列定义在 L3 设计给出；本节锁定表清单与关键列，防止 AC 碎片化。
> **RLS 决策声明（P1-1）**：M0 对下表全部租户域表启用 RLS tenant 隔离策略——将 Tenant Spec v1.2 §5.1 的 SHOULD 提升为本项目 MUST 实现，在最早里程碑建立数据库层兜底防线（RBAC 设计 §3.2：RLS 仅做 tenant 隔离，data_scope 应用层过滤属 M2）。
> **命名约定（P1-3）**：用户表名定为 `users`（对齐 data-architecture v1.0 实体名 User；Dify 的 accounts 命名不采用）。

| 域 | 表 | 关键列（本 PRD 锁定项） | 规范来源 |
|:---|:---|:------------------------|:---------|
| Workspace | tenants / org_units / users / roles / service_accounts / tenant_account_joins | roles.data_scope VARCHAR（self/department/org/all）+ roles.permissions TEXT[] + roles.knowledge_tags TEXT[] + roles.data_domain_access JSONB；tenant_account_joins.role_ids TEXT[]、current_role_id VARCHAR | Role 实体：RBAC §3.1；关联表：RBAC §4.3 |
| Runtime | sessions / executions | 均含 role_id VARCHAR、status、created_at；(tenant_id, session_id)、(tenant_id, status) 索引 | role_id：Tenant Spec v1.2 §5.4 + RBAC §4.3；基础字段：Runtime Spec v1.3 §6.3；索引：data-arch §1.1 |
| Runtime-Checkpoint | checkpoints / checkpoint_blobs / checkpoint_writes | LangGraph PostgresSaver 3 表模型；**三表均冗余 tenant_id 列**（租户隔离不依赖跨表 JOIN，P1-5 定案）；大小值分离；checkpoint_writes.task_path 预留 | langgraph-earp-mapping v1.1 §2.5（blobs/writes 的 EARP 版完整 DDL 在 L3 设计补全） |
| Capability | business_capabilities / capability_calls / connector_bindings | business_capabilities.embedding vector（**M0 仅建列不建索引**，HNSW 属 M4）、visible_roles TEXT[] | Capability Spec v1.4；RBAC §3.3 |
| Governance | policies / policy_bindings / audit_logs | audit_logs.detail JSONB（role_id/user_roles 字段约定） | Audit Spec v1.1 + v1.2 变更 |
| Security | encrypted_credentials / api_keys | **tenant_id（凭证租户隔离 MUST，密钥按 tenant 派生）**、密文列 BYTEA + key_version | Security Spec v1.1；Tenant Spec §4.2.1 |
| Data Domain | data_domains / business_domain_data_domain_map | data_domains.data_classification VARCHAR(16) CHECK（public/internal/confidential/restricted）；bddm 表维护 BD↔DD 的 N:M 映射 | Concept Model v2.1；Policy Center Spec v1.2
| Knowledge | knowledge_bases / documents / chunks | knowledge_bases.data_domain_id FK REFERENCES data_domains（v2.1 新增）；documents.accessible_roles TEXT[]（默认封闭）+ documents.data_classification VARCHAR(16)（v2.1 新增）；chunks 按 KB Spec v1.0 §1.1 已锁定列建表（chunk_id/doc_id/tenant_id/content/embedding/metadata），**M0 仅建列不建向量索引** | KB Spec v1.0；RBAC §3.4；Concept Model v2.1 |
| Conversation | conversations / messages | (conversation_id, seq) 唯一 | Conversation Spec v1.0；data-arch §1.1 |
| Integration | connector_configs | tenant_id + 加密配置列 | Security Spec v1.1 |

> **P0-2 决议**：chunks 表的 content_hash / source_updated_at 列**不在 M0 建**——该字段属 M4 增量索引，KB Spec v1.0 尚未定义。M4 时先升 KB Spec v1.0→v1.1（plan v1.4 里程碑-规范映射表已有预算），再以 Alembic ADD COLUMN 非破坏性加入（data-arch §6.3：PG 11+ 在线 DDL 不锁表，与 US-02 不矛盾）。

## 4. 验收条件

| ID | 描述 | 验证方式 |
|:--:|:-----|:---------|
| AC-01 | `apps/earp-server` 脚手架：`uv run uvicorn earp_server.main:app` 启动，`GET /health` 返回 200，`GET /ready` 反映 DB 连接状态；两端点均无认证 | 集成测试（testcontainers PG） |
| AC-02 | 一镜像多进程：`python -m earp_server.entrypoints.api` / `.worker` / `.scheduler` 三个 entrypoint 均可启动并优雅退出（SIGTERM） | 进程启动测试 |
| AC-03 | `alembic upgrade head` 在空 PG16+pgvector 上创建 §3 全部表；重复执行幂等；`alembic downgrade -1` 可回退 | testcontainers 迁移测试 |
| AC-04 | RLS：§3 全部租户域表启用 tenant 隔离策略（策略存在性全表断言）；其中 sessions/executions/audit_logs/documents 4 表做数据级验证——`SET LOCAL earp.tenant_id='t1'` 后查询不到 t2 数据 | RLS 集成测试 |
| AC-05 | procrastinate spike 按判定矩阵（tech-stack-analysis v1.1 §4.4）四项全过：并发稳定性 / 重试语义 / async session 共存 / 事务性入队回滚；结论写入 ADR-007。任一项不过 → 记录失败证据并回退 Celery（以"结论定案且有测试证据"为通过标准，不预设方向） | spike 脚本 + 证据输出 |
| AC-06 | import-linter 契约：`earp_server.{gateway,runtime,capability,policy,planner,knowledge,conversation,schedule,audit}` 模块独立（planner 等 M0 空壳包一并纳入）；模块对外仅暴露各自 `service.py` 公开函数与 `infra.*`（P2-4 约定）；CI 违规即红 | CI lint 步骤 |
| AC-07 | 工具链：uv lock 可复现安装；ruff + pyright 零报错基线；squawk 对迁移文件无 danger 级告警；CI 新增 server job（ruff/pyright/pytest/import-linter/squawk） | CI 全绿 |
| AC-08 | `openapi.yaml` 由导出脚本 `uv run python -m earp_server.export_openapi > apps/earp-server/openapi.yaml` 生成并入库（含 /health、/ready 与 sessions 域占位 schema——POST /v1/sessions 请求/响应模型对齐 runtime-py client.py 字段：user_id/tenant_id/role_id/metadata；role_id 规范来源 Tenant Spec v1.2 §5.4）；重复导出 git diff 稳定 | 导出脚本 + diff 检查 |
| AC-09 | ADR-007 文档产出：单体先行（含与部署架构偏差声明）+ 技术栈终选表 + spike 结论；引用 plan v1.4 与 tech-stack v1.1 | 文档评审 |
| AC-10 | 现有 SDK 4 包 CI 无回归（317 测试全绿，monorepo 改造不破坏 libs/） | CI 全量 |

## 5. 依赖

| 依赖 | 状态 |
|------|:----:|
| tech-stack-analysis v1.1（评审关闭 P0=0） | ✅ |
| server-side-development-plan v1.4 | ✅ |
| RBAC 设计 v1.1（§3.1 Role 实体 + §4.3 DDL 清单） | ✅ |
| data-architecture v1.0（实体/索引/迁移策略） | ✅ |
| langgraph-earp-mapping v1.1（checkpoints 3 表模型） | ✅ |
| 本机 Docker（testcontainers/docker-compose，硬依赖见 §2 边界声明） | ✅ |
| PyPI：fastapi / sqlalchemy[asyncio] / psycopg[binary,pool]（D7：全线 psycopg3，**不引 asyncpg**）/ alembic / procrastinate / tenacity / pgvector | ⏳ M0 安装 |
| langchain-text-splitters | ⏳ **M4 才添加**（本 PRD 不装） |

## 6. 不做（后续里程碑）

- 任何业务端点与状态机逻辑（POST /v1/sessions 的实现属 M1——本 PRD 仅 openapi 占位 schema）
- JWT 认证中间件、InputGuard（M1）
- 应用层 data_scope 过滤、Policy/RBAC 评估逻辑（M2——本 PRD 只建列和 RLS 兜底）
- EventBus 接口与实现（M1）
- chunks.content_hash / source_updated_at 列（M4，先升 KB Spec v1.1 再 ADD COLUMN，见 §3 P0-2 决议）
- pgvector 检索逻辑与向量索引（M4——M0 仅建 embedding 列；空表建 HNSW 无意义）
- K8s/Helm、Istio、独立镜像仓库（Phase 2+，部署架构为 prod 目标态）
- Redis 接入（M2 限流才需要；docker-compose 预置服务但代码不连接）
- pgbouncer（M0 直连 PG；procrastinate LISTEN 需专用长连接，若未来引入 pgbouncer 需按 tech-stack v1.1 §4.5 配置 prepare_threshold=None 且 LISTEN 连接绕行直连） |

## 7. 接口预览（调用方视角）

```bash
# US-01 一键入口
make dev            # = docker compose up -d && alembic upgrade head && uvicorn earp_server.main:app
curl localhost:8000/health   # {"status":"ok"}
curl localhost:8000/ready    # {"db":"ok"}

# US-03 spike（判定矩阵四项，证据落盘）
uv run python spikes/procrastinate_spike.py --workers 2 --tasks 100
# 输出：并发/重试/共存/事务回滚 四项 PASS|FAIL + 证据（耗时/重试轨迹/连接数）

# AC-08 契约导出
uv run python -m earp_server.export_openapi > apps/earp-server/openapi.yaml
```

```toml
# AC-06 模块边界（importlinter 契约示意）
[[tool.importlinter.contracts]]
name = "domain modules are independent"
type = "independence"
modules = ["earp_server.gateway", "earp_server.runtime", "earp_server.capability",
           "earp_server.policy", "earp_server.planner", "earp_server.knowledge",
           "earp_server.conversation", "earp_server.schedule", "earp_server.audit"]
```

## 8. 验收总结表

| # | 检查项 | 状态 |
|:-:|--------|:----:|
| 1 | US 完整（正常 + 异常 US-06 + 决策 US-03 + 边界声明） | ✅ 6 US + 边界条款 |
| 2 | AC 可测试 | ✅ 10 条（9 自动化 + AC-09 文档评审） |
| 3 | 依赖完整（含 D7 psycopg3-only、text-splitters 延后声明） | ✅ 8 项 |
| 4 | P0 合理 | ✅ 地基性质 |
| 5 | 与冻结规范无矛盾（P0-2 已按 KB Spec v1.0 收敛） | ✅ |

## 9. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | role_id 交叉引用错挂 Runtime Spec §6.3 | 对齐表改为 Tenant Spec v1.2 §5.4 权威来源；§3/AC-08 补规范来源列 |
| P0-2 | chunks.content_hash/source_updated_at 不在 KB Spec v1.0 | 采纳方案 A：M0 不建该列，M4 先升 KB Spec v1.1 再 ADD COLUMN（§3 决议 + §6 排除项）；plan v1.4 M0 行同步修订 |
| P0-3 | roles 表完整列在 RBAC §4.3 清单缺失 | §3 Workspace 行展开 roles.data_scope/permissions/knowledge_tags 并标注 RBAC §3.1 来源 |
| P1-1 | RLS SHOULD→MUST 无决策声明、AC-04 范围窄 | §3 增加 RLS 决策声明；AC-04 改为全表策略断言 + 4 表数据级验证 |
| P1-2 | import-linter 缺 planner | AC-06 模块集扩至 9 模块（含 gateway/planner 空壳） |
| P1-3 | accounts vs users 命名 | 定名 users，§3 命名约定声明 |
| P1-4 | Security 域 tenant_id 未显式 | §3 Security 行显式 tenant_id MUST |
| P1-5 | blobs/writes 表 tenant_id 方案不明 | 定案三表冗余 tenant_id；完整 DDL 留 L3 设计 |
| P1-6 | entrypoints 路径无出处 | §1 补进程模型说明 |
| P1-7 | US-01"一条命令"歧义 | 改为 make dev 一键入口 |
| P2-1~5 | LISTEN 直连注/导出命令/向量索引时机/service.py 约定/roles.permissions | 分别落 §6 / AC-08 / §3+§6 / AC-06 / §3 |
