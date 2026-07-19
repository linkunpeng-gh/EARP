现在我已经掌握了所有必要的上下文信息。以下是结构化的 Gate A 评审报告。

---

# PRD-2026-020 Gate A 评审报告

**评审对象**：`prd/PRD-2026-020-server-m0-foundation.md` v1.0
**评审日期**：2026-07-18
**评审人**：Claude Code（Gate A）
**依赖基线**：tech-stack-analysis v1.1（评审关闭 P0=0）、server-side-development-plan v1.4、RBAC 设计 v1.1、data-architecture v1.0、langgraph-earp-mapping v1.1、Tenant Spec v1.2、Runtime Spec v1.3、Audit Spec v1.2、KB Spec v1.0、Security Spec v1.1

---

## 一、评审总评

PRD 整体结构清晰，范围克制得当，US/AC 覆盖面好。发现 **3 个 P0**（阻塞合并）、**7 个 P1**（应修后合）、**5 个 P2**（建议改进）。核心问题集中在规范交叉引用精度、DDL 字段与 L2 规范的一致性和一处缺失的 DDL 实体。

---

## 二、P0 — 阻塞性问题（3 项）

### P0-1：对齐头中 Runtime Spec v1.3 §6.3 不包含 `role_id` 字段——交叉引用错误

**问题**：PRD 头部对齐表声称对齐 "Runtime Spec v1.3 §6.3（Session 字段）"。经核查，Runtime Spec v1.3 §6.3 的 Session MUST 字段清单为：`session_id, tenant_id, user_id, status, created_at, expires_at, context, metadata`——**不含 `role_id`**。`role_id` 的规范来源是 **Tenant Spec v1.2 §5.4**（v1.2 新增变更）和 **RBAC 设计 v1.1 §4.3**。

**影响**：若后续开发者按此交叉引用去 Runtime Spec 找 `role_id` 定义，会找不到。AC-08 同样引用 "runtime-py client.py 字段：user_id/tenant_id/role_id/metadata"——role_id 的规范权威来源不明确。

**修复建议**：
```markdown
# PRD 头部对齐表修改为：
| **对齐规范** | Tenant Spec v1.2 §5.4（role_id + RLS 三层防线）；Runtime Spec v1.3 §6.3（Session 基础字段）；
                Audit Spec v1.2（audit_logs.detail 含 role_id/user_roles）；
                Knowledge Base Spec v1.0 §2.2（Document/Chunk）；
                data-architecture v1.0（8 域实体/索引/迁移策略）；
                RBAC 设计 v1.1 §3.2（RLS SQL 模式）、§4.3（DDL 清单） |
```
同时，建议在 PRD §3 DDL 表中对 Runtime 域增加一列"规范来源"标注 `role_id` 来自 Tenant Spec v1.2 §5.4。

---

### P0-2：chunks 表的 `content_hash` 和 `source_updated_at` 在 KB Spec v1.0 中不存在——DDL 与 L2 规范不同步

**问题**：PRD §3 DDL 表 Knowledge 行列出 `chunks.embedding vector + content_hash + source_updated_at`，引用 "langchain-earp-mapping §2.5"。经核查：
- **KB Spec v1.0 §1.1** Chunk MUST 字段仅包含：`chunk_id, doc_id, tenant_id, content, embedding, metadata`——**无 `content_hash` 和 `source_updated_at`**。
- **langchain-earp-mapping.md** 是 LangChain 分析文档（§2.5 讨论 RecordManager 增量索引模式），不是 L2 规范。
- `content_hash` 和 `source_updated_at` 属于实现层的增量索引优化，其规范归属应在 KB Spec 中定义。

**影响**：M0 的 DDL 基线包含 L2 规范未定义的列——若后续 KB Spec 升级时字段名/类型/语义有变化，M0 DDL 需要破坏性迁移，违背 US-02 "M1-M7 不再做破坏性重建" 的承诺。

**修复方案（二选一）**：

**方案 A（推荐）**：M0 DDL 中 chunks 表先不加 `content_hash` / `source_updated_at`，仅建 KB Spec v1.0 已锁定的列。在 PRD §6 "不做" 中增加一条："chunks 表的 content_hash / source_updated_at 列（属 M4 增量索引，届时通过 Alembic 非破坏性 ADD COLUMN 加入，data-arch §6.3 确认 PG 11+ 在线 DDL 不锁表）"。

**方案 B**：在 M0 PRD 中先行升级 KB Spec v1.0→v1.1（参照 plan v1.4 里程碑-L2 映射表中 M4 的规范升级预算，提前执行 KB Spec 的字段新增部分）。需走 mini-Gate A 审 KB Spec 变更。

**建议选 A**，理由：M0 是地基，不应抢跑 M4 的规范升级；`ALTER TABLE ADD COLUMN` 对空表/新表是零成本操作，不存在 US-02 顾虑。

---

### P0-3：RBAC 设计 §4.3 DDL 清单中的 `roles` 表缺少 `data_scope` 列——PRD DDL 表未列出但关键列栏暗示存在

**问题**：PRD §3 DDL 表 Workspace 行关键列写 `roles.data_scope（self/department/org/all）`。RBAC 设计 v1.1 §4.3 DDL 变更清单列出了 5 张表的变更（sessions/executions/audit_logs/documents/tenant_account_joins），但 **未列出 `roles` 表的完整 DDL**——§3.1 在实体定义中说明 `Role.data_scope` 字段，但 §4.3 的 "数据层（DDL）" 清单仅覆盖了"需新增列"的表，roles 表作为新建表，其完整列清单（含 data_scope、permissions、knowledge_tags）未在 DDL 清单中显式出现。

**影响**：开发者仅看 §4.3 DDL 清单会遗漏 `roles.data_scope` 列的创建——PRD DDL 表已正确识别，但规范引用链有缺口。属于可修复的追溯性缺失。

**修复建议**：在 PRD §3 DDL 表中将 Workspace 行的关键列展开为：
```markdown
| Workspace | tenants / org_units / accounts / roles / service_accounts / tenant_account_joins | 
  roles.data_scope VARCHAR（self/department/org/all，RBAC §3.1）、roles.permissions TEXT[]；
  tenant_account_joins.role_ids TEXT[]、current_role_id VARCHAR（RBAC §4.3） |
```
并在 RBAC 设计文档的后续修订中补全 §4.3 的 roles 表完整 DDL。

---

## 三、P1 — 应修复（7 项）

### P1-1：AC-04 RLS 测试的表范围与 Tenant Spec 的 SHOULD/MUST 级别不对齐

**问题**：AC-04 要求对 `sessions/executions/audit_logs/documents` 4 张表测试 RLS tenant 隔离。但：
- Tenant Spec v1.2 §5.1 写的是 `SHOULD: 数据库层面使用 Row-Level Security (RLS) 作为第二道防线`（非 MUST），且 §5.1.1 实体清单覆盖了全部持久化实体，不仅仅是这 4 张表。
- RBAC 设计 v1.1 §3.2 将 RLS 定位为"第三层防线——仅做 tenant 隔离兜底"。

PRD 将 Tenant Spec 的 SHOULD 提升为 AC 的 MUST 验证——这本身可以是一个有意的架构决定（M0 就做实 RLS），但**缺乏显式的决策声明**。

**修复建议**：在 PRD §3 的注释区块增加一句："M0 决定对所有租户域表启用 RLS tenant 隔离策略（将 Tenant Spec §5.1 的 SHOULD 提升为 MUST 实现），以在最早里程碑建立数据库层兜底防线。" 同时扩展 AC-04 测试范围至少覆盖 §3 全部租户域表（不仅是 4 张），或显式声明其余表的 RLS 策略在后续 PRD 补测。

---

### P1-2：import-linter 契约缺少 `planner` 模块

**问题**：AC-06 的模块清单为 `{runtime,capability,policy,knowledge,conversation,schedule,audit}`。但 plan v1.4 §5.1 的目录结构中明确包含 `planner/` 模块。虽然 M0 中 planner 仅为空壳，import-linter 契约应覆盖完整模块集合，避免后续遗漏。

**修复建议**：将 AC-06 扩展为 `earp_server.{runtime,capability,policy,planner,knowledge,conversation,schedule,audit}`。对于 M0 尚未创建的模块（如 planner），import-linter 配置可以使用 `ignore_imports` 或在 contract 中注明 "planner 模块由 M3 创建，届时自动纳入 CI 检查"。

---

### P1-3：DDL 表名 `accounts` 与 data-architecture v1.0 实体名 `User` 不一致

**问题**：PRD §3 列出 `accounts` 表，data-architecture v1.0 §1.1 和 §2.1 ER 图使用 `User` 实体名。RBAC 设计 v1.1 和 plan v1.4 均使用 `User`（如 "User↔Role 关联"）。需要确认 `accounts` 是最终表名还是笔误。

**修复建议**：统一为 `users`（与 data-arch 对齐）或 `accounts`（如果这是有意选择，需在 PRD 中注明与 data-arch 的命名映射关系，并在 data-arch 后续修订中同步）。

---

### P1-4：Security 域表缺少显式 `tenant_id` 声明

**问题**：PRD §3 对 Security 域仅写了 `encrypted_credentials / api_keys | 密文列 BYTEA + key_version（Security Spec v1.1）`。虽然引语说了"所有租户域表含 tenant_id"，但 Security 域是跨租户安全的关键——加密密钥按 tenant_id 派生（Tenant Spec §4.2.1），凭证密文跨租户不可解密。缺少显式的 `tenant_id` 标注可能在实现时被遗漏。

**修复建议**：Security 行增加 `tenant_id` 显式标注：
```markdown
| Security | encrypted_credentials / api_keys | tenant_id（凭证隔离 MUST）、密文列 BYTEA + key_version（Security Spec v1.1 §2.2） |
```

---

### P1-5：checkpoint_blobs 和 checkpoint_writes 表增加 `tenant_id` 的具体方案不明确

**问题**：PRD §3 Runtime-Checkpoint 行写 "每表增加 tenant_id（langgraph-earp-mapping v1.1 §2.5）"。但 langgraph-earp-mapping v1.1 §2.5 中：
- `checkpoints` 表：EARP 改编 DDL（第 200-217 行）已含 `tenant_id UUID NOT NULL`
- `checkpoint_blobs` 和 `checkpoint_writes` 表：仅展示了 LangGraph 原始 DDL（无 tenant_id），**未提供带 tenant_id 的 EARP 改编版**

这两个表如何加 `tenant_id` 存在设计选择：是冗余存储 `tenant_id`（独立查询时无需 JOIN），还是通过 `checkpoint_id → checkpoints.tenant_id` 间接获取？需要明确定案。

**修复建议**：在 PRD §3 或 langgraph-earp-mapping 文档中补全 3 表的完整 EARP DDL（含 tenant_id 列 + 索引），PRD 引用具体行号。建议 checkpoint_blobs 和 checkpoint_writes 均冗余存储 `tenant_id`，与 checkpoints 表的 `(tenant_id, checkpoint_id)` 保持一致，避免跨表 JOIN 才能做租户隔离。

---

### P1-6：AC-02 的 entrypoint 路径未在 PRD 或 plan 中明确定义

**问题**：AC-02 要求 `python -m earp_server.entrypoints.api` / `.worker` / `.scheduler` 三个 entrypoint 可启动。但 plan v1.4 §5.1 目录结构中未出现 `entrypoints/` 包——目录结构以 `gateway/`, `runtime/` 等域模块组织。`entrypoints/` 的引入是一个新设计决策，应有一句说明。

**修复建议**：在 PRD §1 背景或 §7 接口预览中增加一句："三个 entrypoint（`earp_server.entrypoints.api/worker/scheduler`）遵循一镜像多进程模型（plan v1.4 §5.1 规则 #5），api 进程启动 uvicorn，worker 进程启动 procrastinate worker，scheduler 进程启动调度循环。"

---

### P1-7：US-01 描述中的 "一条命令" 与实际多步骤不匹配

**问题**：US-01 描述为 "克隆仓库后执行一条命令（docker-compose up + alembic upgrade head + uvicorn 启动）"。括号内实际是 3 条独立命令。这种表述会在验收时造成歧义——"一条命令"到底是指一个 shell 脚本/ Makefile target，还是手动依次执行？

**修复建议**：改为：
```markdown
| US-01 | 作为开发者，克隆仓库后按 README 步骤执行（docker compose up -d → alembic upgrade head → uvicorn 启动），得到可访问 /health 的服务端骨架 | 基础设施 |
```
或明确提供一个 `make dev` / `just dev` 一键入口。

---

## 四、P2 — 建议改进（5 项）

### P2-1：§6 "不做" 清单缺少 docker-compose 中 PG LISTEN 连接配置说明

procrastinate 依赖 PostgreSQL LISTEN/NOTIFY，需要独立长连接（不能走 pgbouncer transaction 模式）。tech-stack-analysis v1.1 §4.4 已注明此约束，但 PRD 未提及 docker-compose 中的 PG 连接配置策略。建议在 §6 或 §7 中加一句："docker-compose 中 PG 直连（不经过 pgbouncer），procrastinate worker 预留 1-2 个专用连接用于 LISTEN。"

### P2-2：AC-08 openapi.yaml 导出机制缺少具体步骤

AC-08 写 "由 FastAPI 导出并入库"，但未说明导出触发方式（启动时自动生成？独立脚本 `python -m earp_server.export_openapi`？）。建议在 AC-08 或 §7 中增加导出命令示例。

### P2-3：chunks.embedding 的索引类型未在 M0 DDL 中明确

tech-stack-analysis v1.1 §3.3 明确 M4 用 HNSW 索引。PRD §3 写 "chunks.embedding vector" 但未说明 M0 是否预建索引、建什么类型。建议明确：M0 仅建 embedding 列（类型 `vector(1536)` 或 `halfvec`），索引创建留给 M4（避免空表建 HNSW 无意义）。同理 `business_capabilities.embedding`。

### P2-4：AC-06 import-linter 的 `*.service` 公共接口约定缺少定义

AC-06 说 "仅允许经 `*.service` 公共接口与 `infra.*`"，但没有定义什么是 `*.service` 接口——是指每个模块下的 `service.py` 文件？还是 `__init__.py` 中 `__all__` 导出的符号？建议在 PRD 中引用 plan v1.4 §5.1 规则 #1 并补充一句具体约定（如 "每个域模块对外仅暴露 `service.py` 中的公开函数"）。

### P2-5：缺少 `roles` 表的 `permissions` 列在 DDL 表中的显式标注

PRD §3 Workspace 行关键列写了 `roles.data_scope` 但未写 `roles.permissions`（RBAC §3.1 定义 `permissions: list[str]`）。虽然 RBAC 执行面在 M2，但 `permissions` 是角色定义的基础列，M0 DDL 应一步建好。建议补充。

---

## 五、对齐检查表

| # | 检查项 | PRD 声明 | 实际 L2/设计文档 | 状态 |
|:-:|:-------|:---------|:----------------|:----:|
| 1 | Tenant Spec v1.2 §5.1 RLS | 对齐 | §5.1 RLS 为 SHOULD（非 MUST）；§5.4 含 role_id 三层防线 | ⚠️ P1-1 |
| 2 | Runtime Spec v1.3 §6.3 Session 字段 | 对齐 | §6.3 Session MUST 字段不含 role_id | 🔴 P0-1 |
| 3 | Audit Spec v1.2 | 对齐（audit_logs） | §2.1 detail JSONB 含 role_id + user_roles（v1.2 变更） | ✅ |
| 4 | KB Spec v1.0 §2.2 Document/Chunk | 对齐 | §1.1 Chunk 不含 content_hash/source_updated_at | 🔴 P0-2 |
| 5 | data-architecture v1.0 | 对齐 | §1.1 索引清单一致；实体名 `User` vs PRD 的 `accounts` | ⚠️ P1-3 |
| 6 | RBAC 设计 v1.1 §4.3 DDL 清单 | 对齐 | §4.3 5 表变更清单已覆盖 sessions/executions/audit_logs/documents/tenant_account_joins | ✅ |
| 7 | RBAC 设计 v1.1 §3.2 RLS SQL 模式 | 对齐 | RLS tenant 隔离策略模式一致（`SET LOCAL earp.tenant_id`） | ✅ |
| 8 | langgraph-earp-mapping v1.1 §2.5 | 对齐 | 3 表模型一致；blobs/writes 的 tenant_id 改编 DDL 未提供 | ⚠️ P1-5 |
| 9 | Security Spec v1.1 | 对齐 | §2.2 AES-256-GCM + key 管理；密文列 BYTEA 含 tenant_id | ⚠️ P1-4 |
| 10 | plan v1.4 M0 范围 | 一致 | M0 定义覆盖 PRD 全部条目 | ✅ |
| 11 | plan v1.4 §5.1 模块清单 | 一致 | import-linter 缺 planner | ⚠️ P1-2 |
| 12 | 与 tech-stack-analysis v1.1 无矛盾 | 一致 | procrastinate spike 判定矩阵完全对齐 §4.4 | ✅ |

---

## 六、US 完整性检查

| US | 覆盖维度 | 评估 |
|:--:|:---------|:-----|
| US-01 | 正常路径：脚手架启动 + /health | ✅ 清晰 |
| US-02 | 正常路径：基线 DDL 一次性建表 | ✅ 含 role_id + RLS |
| US-03 | 决策路径：spike 定案（含失败回退） | ✅ 双向覆盖 |
| US-04 | 工程纪律：模块边界 CI 强制 | ✅ |
| US-05 | 契约路径：openapi.yaml 固化 | ✅ |
| US-06 | 异常路径：迁移幂等 + 回退 | ✅ |

**缺失的 US 维度**：
- **边界条件**：未覆盖 "M0 脚手架在无 Docker 环境下的行为"（如本地开发仅有 PG 无 docker-compose）
- **安全边界**：未覆盖 "/health 无认证但 /ready 是否也无认证" 的明确声明（AC-01 暗示无需认证，但可以显式确认）

建议补充一个 US 或在 AC-01 中注明边界条件，但**不阻塞合并**（P2 级别）。

---

## 七、依赖完整性检查

| PRD §5 声明的依赖 | 验证结果 |
|:---|:-----|
| tech-stack-analysis v1.1（P0=0） | ✅ 评审关闭，v1.1 已修复全部 P0/P1 |
| server-side-development-plan v1.4 | ✅ 已消费 tech-stack 决策，M0 定义完备 |
| RBAC 设计 v1.1 | ✅ v1.1 已修复 P0-1/P0-2（见审查记录） |
| data-architecture v1.0 | ✅ 实体/索引/迁移策略完整 |
| langgraph-earp-mapping v1.1 | ✅ 3 表 DDL + 大小值分离 + task_path 已定案 |
| 本机 Docker | ✅ |
| PyPI 包清单 | ⚠️ 缺少 `asyncpg` 或确认只依赖 psycopg3（D7 已决策统一 psycopg3，确认无需列出 asyncpg 即可） |

**建议补充依赖**：`langchain-text-splitters`——虽然 M4 才启用，但若 M0 的 pyproject.toml 需要预声明所有依赖，应加入（或在 §6 注明 "M4 才添加"）。

---

## 八、评审结论

| 等级 | 数量 | 阻塞合并？ |
|:----:|:----:|:----------:|
| P0 | 3 | **是** |
| P1 | 7 | 建议修后合 |
| P2 | 5 | 可后修 |

**建议**：修复 P0-1（交叉引用）、P0-2（chunks 字段与 KB Spec 同步）、P0-3（roles.data_scope DDL 追溯）后进入 Gate B。P1 项建议在 Gate B 前修复，但可根据 PRD 作者判断部分延后至 L3 设计阶段处理。

PRD 的整体质量：**良好**。范围克制清晰（M0 vs M1/M2 边界无泄漏），US 覆盖正常/异常/决策三类路径，AC 均可测试化（10 条中 9 条可自动化），DDL 基线基本完整对齐 RBAC 设计 §4.3。主要改进点在规范交叉引用的精度和 DDL 字段与 L2 规范版本的严格同步。
