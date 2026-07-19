# P1+P2 清理评审报告

**日期:** 2026-07-19
**范围:** 8 个清理项 (6 个源文件 + 2 个 migration)
**基线:** 24/24 测试绿，ruff/import-linter 净

---

## 逐项判定

| # | 检查项 | 判定 | 证据 | 级别 |
|:--:|:-----|:----:|------|:----:|
| 1 | layers.py data_scope=dept+org | ⚠️ | `_get_descendant_orgs` 仅 1 层 (parent_id 硬编码，无 recursive CTE) — 组织树深度>2 时过滤范围不完整。在文件头注释标注为 M5 known limitation | P1 |
| 2 | registry.py pgvector discover | ✅ | query+role/query+no-role/no-query+role/no-query+all 四分支全覆盖，embed_query 使用 M4 伪随机 (documented) | — |
| 3 | step_runner.py stream() | ✅ | 无 layers 调用 — M6 Phase 1 by design (token 流式输出无需 RBAC) | — |
| 4 | step_runner.py batch() | ✅ | 消息 `'M7+: parallel batch execution (M5 uses for-loop)'` — 对齐全景评审 P2-2 | — |
| 5 | multi_step.py REPLANNING | ⚠️ | interrupt() 线程安全 (asyncio GIL)，但 resume() 搜索调用方=0；REPLANNING enum 存在但执行循环仅检查 INTERRUPTED 分支 — M6 预留 | P2 |
| 6 | checkpoint.py write_writes | ✅ | value column 类型 bytes + 幂等 INSERT，接口签名正确 | — |
| 7 | websocket_gateway.py JWT | ✅ | token 验证复用 JWTMiddleware.DEV_SECRET+HS256；token 参数可选 (M6 Phase 1) | — |
| 8 | 迁移 0002/0003 | ✅ | `ADD COLUMN IF NOT EXISTS` 幂等 (Prod-safe)；`DROP COLUMN IF EXISTS` 可逆 | — |

---

## 问题清单

| ID | 级别 | 文件:行 | 问题 | 修复 |
|:---|:----:|:--------|:-----|:-----|
| P1-1 | 🟡 | `layers.py:185-192` | `_get_descendant_orgs` 仅 1 层深度——组织树深度 > 2 时 dept/org scope 过滤不完整 | 在方法 docstring 中标注 known limitation (M5 recursive CTE 暂不引入) |
| P2-1 | 🔵 | `multi_step.py:57-59` | `resume()` 搜索调用方 = 0；REPLANNING 只在 enum 中声明但执行循环无分支 | 在文件头注释中标注 resume() 当前无调用方 (M6 预留) |

## 汇总

**0 P0，1 P1 (data_scope depth)，1 P2 (interrupt resume unused)。6/8 PASS。**
