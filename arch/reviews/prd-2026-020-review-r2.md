# Gate A Round-2 复查 · PRD-2026-020 v1.1

## Round-1 问题逐项复查

| # | 问题 | 判定 | 证据（文档位置） |
|:-:|:-----|:----:|:----------------|
| P0-1 | role_id 规范来源 | **RESOLVED** | 对齐规范行 `§5.4（role_id 三层防线，**role_id 的规范权威来源**）`；§3 Runtime 行 `role_id：Tenant Spec v1.2 §5.4`；AC-08 同 |
| P0-2 | chunks 多余列移除 | **RESOLVED** | §3 底部 P0-2 决议段落完整声明 M4 延期策略；§6 排除项 `chunks.content_hash / source_updated_at 列（M4，先升 KB Spec v1.1 再 ADD COLUMN）` |
| P0-3 | roles 列补齐 | **RESOLVED** | §3 Workspace 行 `roles.data_scope VARCHAR（self/department/org/all）+ roles.permissions TEXT[] + roles.knowledge_tags TEXT[]`，来源标注 `RBAC §3.1` |
| P1-1 | RLS 决策声明 + AC-04 全表断言 | **RESOLVED** | §3 RLS 决策声明（P1-1 标签）明确 `SHOULD→MUST`；AC-04 `§3 全部租户域表启用 tenant 隔离策略（策略存在性全表断言）+ 4 表数据级验证` |
| P1-2 | import-linter 9 模块 | **RESOLVED** | AC-06 模块集 `gateway,runtime,capability,policy,planner,knowledge,conversation,schedule,audit` 共 9 个；§7 toml 契约一致 |
| P1-3 | users 命名 | **RESOLVED** | §3 命名约定 `用户表名定为 users（对齐 data-architecture v1.0 实体名 User；Dify 的 accounts 命名不采用）` |
| P1-4 | Security tenant_id 显式 | **RESOLVED** | §3 Security 行 `**tenant_id（凭证租户隔离 MUST，密钥按 tenant 派生）**` |
| P1-5 | checkpoint 3 表 tenant_id 冗余 | **RESOLVED** | §3 Runtime-Checkpoint 行 `**三表均冗余 tenant_id 列**（租户隔离不依赖跨表 JOIN，P1-5 定案）` |
| P1-6 | entrypoints 说明 | **RESOLVED** | §1 进程模型说明 `三个 entrypoint（earp_server.entrypoints.{api,worker,scheduler}）实现 plan v1.4 §5.1 规则 #5` |
| P1-7 | make dev 一键入口 | **RESOLVED** | US-01 `make dev（内部串起 docker compose up -d → alembic upgrade head → uvicorn 启动）`；§7 接口预览同样 |

## 新增 P0/P1 扫描

| 级别 | 发现 |
|:----:|:-----|
| P0 | **无** — 文档内部逻辑一致，与引用规范对齐 |
| P1 | **无** — AC-08 与 §7 中 openapi.yaml 导出路径略有差异（`> openapi.yaml` vs `> apps/earp-server/openapi.yaml`），属 P2 级书写不一致，不影响实现 |

## 判定

**VERDICT: PASS** — 0 P0/P1 remaining，Round-1 全部 10 项修复已落定，无新增阻塞项。
