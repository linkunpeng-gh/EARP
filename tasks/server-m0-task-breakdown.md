# 任务清单 — Server M0（PRD-2026-020 v1.1）

**状态：待人工确认（Phase 3 → Phase 4 门禁）**
**依据：PRD-2026-020 v1.1（Gate A PASS）+ server-m0-l3-design v1.1（Gate B PASS）**
**日期：2026-07-18**

| # | Task | 关联 AC | 涉及文件 | 预估工作量 |
|:-:|:-----|:------:|:---------|:----------:|
| 1 | 工程骨架：pyproject/uv + ruff/pyright/importlinter 配置 + Makefile + docker-compose（pg16-pgvector 双角色初始化脚本 / valkey / minio）+ 9 域空壳包 + config.py | AC-06/07 | apps/earp-server/{pyproject.toml,Makefile,docker-compose.yml,src/earp_server/**} | 中 |
| 2 | main.py 工厂 + /health /ready + infra/db.py（build_engine/check_db/tenant_session 方案 A）+ ext_logging | AC-01 | src/earp_server/{main.py,infra/db.py,infra/ext/*} | 中 |
| 3 | entrypoints ×3（api/worker/scheduler，SIGTERM 优雅退出）+ infra/task_queue.py（TaskQueue Protocol + Procrastinate 实现骨架） | AC-02 | src/earp_server/entrypoints/*, infra/task_queue.py | 中 |
| 4 | Alembic：env.py async 桥接 + 0001_baseline（全部表 + 复合 FK + RLS 循环 + 双角色）| AC-03/04 | migrations/**, alembic.ini | 大 |
| 5 | procrastinate spike（4 场景独立脚本 + 证据 JSON）→ 结论定 D6 | AC-05 | spikes/procrastinate_spike.py | 中 |
| 6 | schemas/sessions.py + export_openapi.py + openapi.yaml 基线 | AC-08 | src/earp_server/{schemas/sessions.py,export_openapi.py}, openapi.yaml | 小 |
| 7 | 测试套件：conftest(testcontainers) + test_{health,entrypoints,migrations,rls,import_linter,openapi_export} | AC-01~04/06/08 | tests/** | 大 |
| 8 | CI：test.yml 新增 server job（lint/test/squawk/openapi-diff/ADR 存在性检查），保 SDK matrix 不动 | AC-07/10 | .github/workflows/test.yml | 小 |
| 9 | ADR-007 文档（单体先行 + 技术栈终选 + spike 结论） | AC-09 | arch/design/ADR-007-modular-monolith.md | 小 |
| 10 | Phase 5/6：全量回归 + validate-cross-refs + Gate C 评审修复循环 + task-log 记录 | AC-10 | — | 中 |

### 依赖关系
- Task 1 → 2 → 3（骨架先行）；Task 1 → 4（配置就绪才能跑 alembic）
- Task 5 仅依赖 Task 1 的 docker-compose（spike 不 import 包，可与 2-4 并行）
- Task 6 依赖 Task 2（app 工厂）；Task 7 依赖 2/3/4/6；Task 8 依赖 7；Task 9 依赖 5；Task 10 收尾
- 建议执行序：1 → (2,5 并行) → 3 → 4 → 6 → 7 → 8 → 9 → 10

### 风险提示
1. testcontainers 首次拉 pgvector/pg16 镜像较慢——CI 需缓存镜像层；本机先 docker pull 预热
2. spike 若 FAIL：Task 3 的 TaskQueue 实现类切 Celery 备选（接口不变，PRD AC-05 允许），Task 9 记录证据
3. FORCE RLS + 双角色：migration 与 app 连接串必须分开，环境变量易配错——Makefile 内显式两个 URL 变量
4. uv workspace 仅纳管 apps/earp-server（不动 libs/），防 SDK CI 回归（AC-10）

---
**确认后进入 Phase 4 编码。**
