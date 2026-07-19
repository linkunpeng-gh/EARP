## Gate B 复核：DESIGN-SERVER-M0-L3 v1.1

### 一、Round-1 问题逐项复核

| 编号 | 问题 | 判定 | 证据 |
|:-----|:-----|:-----|:-----|
| P0-1 | checkpoint 自维护声明 | **RESOLVED** | §三 Runtime-Checkpoint 段首含完整声明块：不引 langgraph/langgraph-checkpoint、不用 setup()/migration/AsyncPostgresSaver、Alembic 全权维护 DDL、LangGraph 仅为表模型参考、tenant_id NOT NULL 附写入路径始终携带租户上下文的理由 |
| P0-2 | 双角色策略 | **RESOLVED** | §三 RLS 段末尾「双角色策略（P0-2）」：earp_migration=BYPASSRLS、earp_app=受限角色、docker-compose 初始化创建两角色、Settings.database_url 与 alembic.ini url 分离；§六 test_migrations 行明确「BYPASSRLS 路径：seed 一行 + 回退」 |
| P0-3 | spike 场景3 独立 engine | **RESOLVED** | §四「独立性（P0-3）：spike 不 import earp_server 包」+ 场景3 描述为「脚本内直接以 DATABASE_URL 构建独立的 AsyncEngine + async_sessionmaker（与 app 无共享代码）」 |
| P1-1 | env.py async 模式 | **RESOLVED** | §一 point 5 含完整代码片段：`async_engine_from_config` + `asyncio.run(_run(connectable))` + `conn.run_sync(_do_run_migrations)` |
| P1-2 | tenant_session 事务契约 | **RESOLVED** | §一 point 4 明确「事务契约=方案 A（P1-2 定案）」：进入即 BEGIN + SET LOCAL、正常退出 commit、异常 rollback、单上下文=单事务、多事务需多次进入；test_rls 按此模式书写 |
| P1-3 | openapi 排序与基线 diff | **RESOLVED** | §二 export_openapi 签名 `json.dumps(..., sort_keys=True)`；§六 基线机制：「导出实现为 json.dumps(app.openapi(), sort_keys=True, indent=2) 转 YAML，info.title/version 固定常量（version "0.1.0"），仓库内 openapi.yaml 即基线，test_openapi_export 重新导出与基线逐字节比对」 |
| P1-4 | 测试覆盖 AC-06/AC-09 | **RESOLVED** | §一 point 7 增补 test_import_linter.py（subprocess `lint-imports` 断言 exit 0）；§六 表格含 test_import_linter（AC-06）+ ADR 存在性（AC-09：CI 步骤断言 `arch/design/ADR-007-*.md` 存在且含"spike 结论"章节） |
| P1-5 | testcontainers 生命周期 | **RESOLVED** | §六：PG 容器 fixture `scope="session"`、启动超时 60s、测试串行（不启用 pytest-xdist）、每个测试函数独立事务 + teardown rollback（function 级 fixture 包装）、RLS 数据级测试自建/自清理租户数据 |
| P2-1 | 复合 FK executions→sessions | **RESOLVED** | §三 executions 表定义含 `FOREIGN KEY(tenant_id, session_id) REFERENCES sessions(tenant_id, session_id)`；sessions 补 `UNIQUE(tenant_id, session_id)`（与 data-arch 索引重合）；§三 引用完整性段确认 |
| P2-2 | SIGTERM 优雅退出 | **RESOLVED** | §一 point 6：`loop.add_signal_handler(SIGTERM, stop_event.set)` + `await stop_event.wait()`，收到信号后取消在途 task 并 `sys.exit(0)`；test_entrypoints 断言 <5s |
| P2-3 | service_account_id 命名 | **RESOLVED** | §三 service_accounts 表主键列为 `service_account_id PK`（非 account_id）；§三 引用完整性段重复确认 |
| P2-4 | credentials owner 列 | **RESOLVED** | §三 encrypted_credentials 列含 `owner_type VARCHAR(24) NULL, owner_id VARCHAR(64) NULL`；§三 引用完整性段注明「凭据归属实体，P2-4；M2 启用校验」 |
| P2-5 | export 签名 | **RESOLVED** | §二 `def export_openapi() -> str`，注释含 `json.dumps(create_app().openapi(), sort_keys=True) → YAML 字符串`，`__main__: print(export_openapi())`，固定 `info.title="EARP Server", info.version="0.1.0"` |
| P2-6 | sessions user_id/role_id 无 FK | **RESOLVED** | §三 引用完整性段：「sessions.user_id / role_id：**不建 FK**——多租户下的权威校验属 M2 应用层（Policy），M0 由 RLS + 应用层保证；documented limitation」 |

### 二、新问题扫描

对文档进行完整 P0/P1 扫描：

- **DDL 完整性**：所有表、列、约束、索引、RLS 策略均有定义；shorthand 风格一致（name/domain/status 等常规列省略类型，属规范文档惯例，实际 migration 文件中补齐）
- **引用完整性**：已声明的 FK（executions→sessions 复合 FK、chunks.doc_id→documents、documents.kb_id→knowledge_bases、connector_bindings 两列→各自表、service_accounts.api_key_id→api_keys）与故意不建 FK 的列（sessions.user_id/role_id、capability_calls 各引用列、policy_bindings 多态引用）均有说明
- **Checkpoint 段头标注 "P1-5：三表冗余 tenant_id"**：此 P1-5 编号疑似来自更早轮次评审（本轮的 P1-5 为 testcontainers），属标注笔误，不影响设计正确性——建议顺手修正为独立说明
- **无新增 P0/P1 设计缺陷**

### 三、最终裁定

**VERDICT: PASS** — 0 个 P0，0 个 P1（含本轮新扫描）。

13 项 round-1 问题全部 RESOLVED，无新 P0/P1 发现。仅有 1 处可顺手修正的标注笔误（Checkpoint 段头 "P1-5" 编号与实际 issue 编号不一致），不影响 Gate B 通过。
