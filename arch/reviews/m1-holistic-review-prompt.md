# M1 全成果评审 Prompt

> 用法：建议四刀分审。每刀一条命令在仓库根目录执行，结果写 `arch/reviews/m1-holistic-review.md`。
> 修复后重评：r2 prompt 用逐项 RESOLVED/NOT-RESOLVED 表格 + 新 P0/P1 扫描。

---

## 第 1 刀：PRD→实现追溯（AC 逐条兑现判定）

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M1 walking skeleton 追溯审计。PRD-2026-021 v1.1 (11 US, 12 AC) → L3 设计 v1.1 → 实际代码。

评审对象：
- prd/PRD-2026-021-server-m1-walking-skeleton.md (v1.1)
- arch/design/server-m1-l3-design-v1.md (v1.1)
- apps/earp-server/src/earp_server/ 全部模块（特别是 main.py, runtime/session_service.py, runtime/invoke.py, orchestrator/types.py, orchestrator/step_runner.py, orchestrator/layers.py, gateway/auth.py, infra/eventbus.py, infra/checkpoint.py, audit/consumer.py, connector.py, capability/registry.py）
- apps/earp-server/tests/ 全部测试
- libs/earp-sdk-core-py/pyproject.toml (F1 version fix)
- libs/earp-sdk-runtime-py/src/earp_sdk_runtime/session.py (F3 utcnow fix)
- .github/workflows/test.yml (F2 CI fix)

已验证事实（可信任，不用复验）：17/17 测试绿(含5新增RLS全表+F5幂等)；37/37 runtime-py SDK集成绿；ruff/import-linter净；openapi基线已更新；交叉引用全绿。

逐 AC 判定（12 条）：每条给出 实现落点(file:line) + 测试落点 + FULL/PARTIAL/MISSING 判定。
特别关注 AC-04 (audit含checkpoint_id→EventBus→DB)、AC-09 (SDK集成路径——37测试如何覆盖真实服务端)。

反事实抽查：任选 2 条 AC，说明你如何从代码确认其被真实测试覆盖（不看测试名，看断言语义）。

输出：追溯矩阵 + P0/P1/P2 + 发现。中文，表格。" | tee arch/reviews/m1-holistic-r1-trace.md | tail -5
```

## 第 2 刀：架构决策与设计折衷审查

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M1 架构审计。焦点：M1 的三个'接口一次到位'决策是否正确落地，实现折衷是否被诚实记录。

审查维度：
A. Step Runner 三形态锁定 —— invoke 实现 vs stream/batch 抛 NotImplemented(含AsyncGenerator返回类型)。检查 step_runner.py 接口签名是否不可变。M5/M6 的真扩展成本（只加实现不碰接口？）。

B. Layer 拦截器链 —— AuditLayer.before_step/after_step 是否正确订阅EventBus？PolicyLayer 占位是否真实存在（不只是注释）？layers.py 和 types.py 的接口稳定性。

C. Checkpoint 最小落盘 —— checkpoints+blobs 双写 vs writes 表 M1 不写（设计文档声明 vs 实际代码）。checkpoint_id 是否真实回传到 InvokeResponse。

D. EventBus fire-and-forget 语义 —— publish() 是否用 asyncio.create_task？audit_handler 失败后是否仅 stderr 日志不抛回 invoke？

E. 实现中发现的 5 个折衷是否被文档化：
   ① SET LOCAL 用 f-string 直接插值（非 SQLAlchemy 参数化）
   ② psycopg3 dict→JSONB 需显式 json.dumps
   ③ orchestrator 循环导入→types.py 解耦（检查 layers.py 和 step_runner.py 是否零相互 import）
   ④ import-linter ignore 模式要求精确匹配（当前 ignore_imports 清单是否最小化）
   ⑤ JWT dev secret 硬编码（documented limitation）

F. M0 承诺的 5 项顺手修复（F1-F5）是否全部落地。

输出：逐项 PASS/ISSUE/PARTIAL + 证据 + P0/P1/P2。中文，简洁。" | tee arch/reviews/m1-holistic-r2-arch.md | tail -5
```

## 第 3 刀：代码对抗性审查（安全+异步+数据完整性）

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M1 代码安全审查。焦点：M1 首次引入认证和外部输入面。

对抗视角：
A. JWT 安全性 —— auth.py 的 decode 路径（alg=none 攻击面、exp 校验是否真实生效、HS256 dev secret 半径）。token payload 注入 tenant_id/role_id 到 request.state 后，下游是否有'信任state但未校验'的盲点。

B. SQL 注入 —— SET LOCAL f-string 插值（tenant_id 来自 JWT payload——是否总可信任？）。invoke 端点中字符串拼接（session_id/execution_id UUID 随机——安全但需标注理由）。

C. RLS 逃逸 —— tenant_session 和 connect()+SET LOCAL 两种模式的使用场景是否正确（何时该用哪个？）。是否有模块绕过了 SET LOCAL（直接用裸 engine.connect()而不设租户上下文）。

D. 异步安全 —— EventBus publish() 的 asyncio.create_task 是否会导致无序 audit 事件（先发生的 invoke 后入库）。CheckpointStore write 是否在 transaction commit 前完成（crash 时 checkpoint 丢失 vs 脏 checkpoint）。invoke 端点的事务边界——sessions 查询、execution 创建、StepRunner 执行、execution 更新是否在同一事务（当前不是——这是 M1 documented limitation 还是 bug？）。

E. tenacity 重试正确性 —— connector.py 的 @retry 装饰器在 async 方法上是否正确工作（有实测证据：spike S2 验证过 procrastinate 的 retry 语义——Connector 的 tenacity retry 是否被 M1 集成测试覆盖？）。

输出：P0/P1/P2 + file:line + 可复现攻击/失败场景。中文。" | tee arch/reviews/m1-holistic-r3-security.md | tail -5
```

## 第 4 刀：实现忠实度与文档同步审查（短刀，快速）

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M1 实现忠实度快速扫描。不读代码细节——对比 L3 设计 v1.1 的接口签名列表 vs 实际代码文件存在性+导出符号。

检查项（每项 1 行判定）：
1. 目录结构：L3 §一 列出的 10 个文件是否全部存在（含 orchestrator/__init__.py、types.py）
2. 接口签名映射：L3 §二 的接口表（Session CRUD/JWT中间件/EventBus/Audit/StepRunner/Checkpoint/Connector/Capability）vs 实际导出符号
3. Checkpoint 3 表语义：L3 §三 的 writes 表"不写入"声明 vs 实际代码
4. JWT 令牌管理：L3 §四 dev HS256 硬编码 vs prod RS256 预留
5. AC-09 SDK 集成策略：L3 §五 3 组分组的实际执行结果（37 全绿 vs skip 标记——实际 skip 了多少？）
6. M0 F4 (enqueue_in_session) 是否在 TaskQueue Protocol 中加了口子（不是只加注释）
7. M0 F3 (utcnow) 是否在两处都修了（core + runtime session.py）
8. import-linter ignore_imports：当前清单是否最小化（没有 orphan 'no matches' warning）

输出：逐项 PASS/FAIL + 一行证据。中文，表格。" | tee arch/reviews/m1-holistic-r4-fidelity.md | tail -5
```

---

## r2 重评模板

```bash
codex exec "Round-2 复核。r1 报告：arch/reviews/<r1文件>.md。已修复清单：<逐条列出>。逐项 RESOLVED/NOT-RESOLVED + 一行证据；新 P0/P1 扫描；verdict CLOSED 或列余项。中文，表格。" | tee arch/reviews/<r1文件>-r2.md | tail -5
```
