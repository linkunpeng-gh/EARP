# Server M0 — 架构影响分析

## PRD-2026-020 v1.1

| 字段 | 值 |
|------|-----|
| **影响范围** | 新增 apps/earp-server（全新代码，0 存量修改）；仓库级：CI workflow + 根目录布局 |
| **架构决策** | ADR-007（模块化单体 + 技术栈终选）——本 PRD 产出物之一 |
| **Breaking Change** | 否——libs/ 5 个 SDK 包零修改（AC-10 回归保护） |
| **新增依赖** | fastapi / sqlalchemy[asyncio] / psycopg[binary,pool] / alembic / procrastinate / tenacity / pgvector / uvicorn；dev: ruff / pyright / pytest-asyncio / testcontainers / import-linter / squawk |
| **分析人** | Arch Agent |
| **日期** | 2026-07-18 |

---

## 1. 影响范围

### 1.1 仓库级影响（唯一的存量触碰点）

| 位置 | 影响类型 | 说明 |
|:-----|:--------|:-----|
| `apps/earp-server/` | **全新** | 服务端全部代码，与 libs/ 平行 |
| `.github/workflows/test.yml` | **修改** | 新增 server job（ruff/pyright/pytest/import-linter/squawk）；既有 4 SDK matrix job 不动 |
| 根目录 | **新增文件** | 可能新增顶层 Makefile 或 apps/earp-server/Makefile（US-01 make dev，L3 定） |
| `libs/*` | **零修改** | AC-10 显式保护；uv workspace 若纳管 libs/ 需验证不改变其安装行为（PRD AC-07） |
| `scripts/validate-cross-refs.py` | 无影响（R5 预留不在 M0 实现） | openapi.yaml 仅入库 |

### 1.2 PRD AC → 交付物映射

| AC | 交付物 | 层 |
|:--:|:-------|:---|
| AC-01/02 | earp_server 包骨架 + entrypoints ×3 | 代码 |
| AC-03/04 | migrations/versions/0001_baseline.py + RLS 策略 | DDL |
| AC-05 | spikes/procrastinate_spike.py + 证据 | spike |
| AC-06/07 | importlinter 契约 + CI job + 工具链配置 | 工程 |
| AC-08 | export_openapi + apps/earp-server/openapi.yaml | 契约 |
| AC-09 | ADR-007 文档 | 文档 |
| AC-10 | CI 全量回归 | 验证 |

## 2. 跨域依赖与风险

| # | 风险 | 缓解 |
|:-:|:-----|:-----|
| 1 | uv workspace 纳管 libs/ 可能改变 SDK CI 安装路径 | 分两步：M0 workspace 仅纳管 apps/earp-server；libs/ 保持现有 per-package pip 安装（tech-stack v1.1 §4.9 已预警 uv workspace 成熟度） |
| 2 | DDL 基线一次建 23+ 表，L3 若列定义有误则返工成本高 | L3 设计逐表给全列 + Gate B 评审把关；squawk lint |
| 3 | spike 失败路径（回退 Celery）影响 entrypoints.worker 实现 | worker entrypoint 经 TaskQueue 薄抽象（tech-stack v1.1 §4.4 迁移路径）——spike 结论只影响实现类 |
| 4 | pgvector 扩展在 CI 容器可用性 | 镜像用 pgvector/pgvector:pg16（官方镜像，含扩展） |

## 3. L2 规范影响

无规范升级需求（P0-2 决议已把 KB Spec v1.1 推迟到 M4；plan v1.4 里程碑-规范映射表 M0 行本就为空）。RLS SHOULD→MUST 是实现层加严，不改规范文本。

## 4. 结论

绿灯进入 Phase 2（L3 设计）。影响面收敛于新增目录 + CI 一个 job，存量风险仅 uv workspace 纳管方式（已定分两步策略）。
