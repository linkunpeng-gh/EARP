# M0 全成果评审 Prompt 包（可复用模板）

> 用法：每刀一条命令，在仓库根目录执行。全景审查让 Claude Code 自己 Read 文件（不用 --append-system-prompt-file，那个只适合单文档），所以 --max-turns 给足、超时 600s。
> 修复后重评：把 r1 报告路径和修复清单塞进 r2 prompt，要求逐项 RESOLVED/NOT-RESOLVED + 新问题扫描。

---

## 第 1 刀：决策与分析链审查

```bash
cd /Users/linkunpeng/work/EARP && claude -p "你是独立架构评审员，做'决策链审计'——检验从开源分析到技术选型到开发计划的推理链是否经得起推敲。

评审对象（按依赖序）：
1. arch/reference/opensource-analysis.md + dify-earp-mapping.md + langgraph-earp-mapping.md(v1.1) + langchain-earp-mapping.md + server-side-tech-reference-v1.md
2. arch/reference/opensource-comparison-findings-v1.md（汇总层）
3. arch/design/tech-stack-analysis-v1.md（v1.1，决策层，已有 2 轮评审关闭：arch/reviews/tech-stack-analysis-v1-review*.md）
4. arch/design/server-side-development-plan-v1.md（v1.4，消费层）

审查维度：
A. 证据→结论传导：每个 D1-D9 决策的证据是否真实存在于上游分析？有无'结论先行、证据后补'的痕迹？
B. 反事实检验：若 Dify/LangGraph 的关键事实认定有误（列出你认为最脆弱的 3 个事实认定），哪些决策会翻？
C. 遗漏的主流替代方案（2026 视角）
D. 版本汇总一致性：五份文档间相互引用的版本号/结论是否一致
E. 已声明的延期决策（EventBus broker M6、LiteLLM M3 前）的触发条件是否可执行

已关闭问题不要重报（见两轮评审文件）。输出：P0/P1/P2 + 文档:章节定位 + 修复建议 + 决策链健康度总评。中文。" --max-turns 12 --output-format text 2>&1 | tee arch/reviews/m0-holistic-r1-decision-chain.md | tail -5
```

## 第 2 刀：需求→设计→实现追溯审查

```bash
cd /Users/linkunpeng/work/EARP && claude -p "你是独立评审员，做'追溯性审计'——PRD 的每条承诺是否真实兑现到代码，设计与实现有无静默偏离。

追溯链：prd/PRD-2026-020-server-m0-foundation.md(v1.1) → arch/impact/server-m0-impact.md → arch/design/server-m0-l3-design-v1.md(v1.1) → apps/earp-server/（实现）→ arch/design/ADR-007-modular-monolith.md。

裁判标准：以 PRD AC 和 L2 规范为准（Tenant Spec v1.2 §5.1/§5.4、Runtime Spec v1.3 §6.3、KB Spec v1.0 §1.1、RBAC 设计 v1.1 §3/§4.3）；分析类文档不作为实现正确性的依据（防循环论证）。

逐项检查：
A. AC-01~AC-10 : 每条给出实现落点(file:line) + 测试落点(test:case) + 兑现判定(FULL/PARTIAL/MISSING)；PARTIAL 必须说明缺口
B. L3 设计 §三 DDL 全列定义 vs migrations/versions/0001_baseline.py 逐表 diff（列/约束/索引/RLS，任何未声明的偏离都要列出）
C. L3 §二 接口签名 vs 实际代码签名 diff
D. ADR-007 的 spike 结论 vs spikes/spike-evidence.json 原始数据是否一致（含 S4 事务性入队的语义限定是否如实）
E. 声明的验证事实抽查：任选 2 条 AC，说明你如何从测试代码确认其真实被覆盖

可信锚点（不必重新执行，但可质疑方法）：pytest 17/17 绿、spike 4/4 PASS、squawk 0、pyright strict 0、SDK 回归 203/203。
已关闭问题清单在 arch/reviews/prd-2026-020-review*.md 与 server-m0-l3-design-review*.md，不要重报。
输出：追溯矩阵表(AC×落点×判定) + P0/P1/P2 + verdict。中文。" --max-turns 15 --output-format text 2>&1 | tee arch/reviews/m0-holistic-r2-traceability.md | tail -5
```

## 第 3 刀：代码对抗性全景审查

```bash
cd /Users/linkunpeng/work/EARP && claude -p "你是攻击性安全评审员（fresh eyes，假设此前评审都可能漏），全景审查 apps/earp-server/ 全部代码（src/ migrations/ tests/ spikes/ pyproject.toml Makefile docker-compose.yml）与 .github/workflows/test.yml 的 server job。

对抗视角优先级：
A. 多租户逃逸：RLS 策略表达式、GUC 注入面、BYPASSRLS 角色触达面、FORCE RLS 例外（tenants 表无 RLS 的实际暴露面）、复合 FK 是否留了跨租户引用缝隙
B. SQL 注入面：f-string 拼接的表名循环、alembic offline SQL、spike 脚本
C. 供应链与配置：依赖锁定策略、docker-compose 默认凭证的暴露半径、CI 中 npx 拉取 squawk 的完整性风险
D. 异步正确性：连接池生命周期、信号处理竞态、事务边界（tenant_session 方案 A 的误用面）
E. 测试可信度：17 个测试里有没有'看起来测了其实没测'的（断言过宽/fixture 掩盖/顺序依赖）

已知已修（Gate C 两轮，arch/reviews/server-m0-code-review*.md）：worker try/finally、tenant_session 空值自卫、TOCTOU 移除、5 处 FK/PK、+3 RLS 测试、S4 语义澄清。已声明 M1 顺延：任务名注册校验、enqueue_in_session、RLS 全表矩阵。这些不要重报，但可以质疑'顺延是否合理'。
输出：P0/P1/P2 + file:line + 可复现的攻击/失败场景描述 + 修复建议。中文。" --max-turns 15 --output-format text 2>&1 | tee arch/reviews/m0-holistic-r3-adversarial.md | tail -5
```

## 第 4 刀：治理与流程合规审查

```bash
cd /Users/linkunpeng/work/EARP && claude -p "你是流程审计员，检查 M0 全过程是否符合项目自己定义的治理规则。

治理规则来源：L0-L3 四层治理（L3 不得违背 L2、L2 不得违背 L1）、流水线 v2.0（PRD→Gate A→影响分析→L3→Gate B→任务清单人工确认→编码→门禁→Gate C）、scripts/validate-cross-refs.py 四规则。

检查项：
A. L2 变更合规：knowledge-center-specification v1.0→v1.1 的变更（Celery→任务队列）是否属于'去实现绑定'的合法修订？有无其他 L2 条款被实现静默违背（重点：Tenant Spec RLS SHOULD→MUST 提升的声明是否充分、Runtime Spec §6.3 Session 字段 vs sessions 表列）
B. 评审记录完整性：6 份评审文件（prd*2/l3*2/code*2）+ 2 份 tech-stack 评审，每轮的 P0/P1 是否都有对应修复证据或显式延期声明
C. 文档版本链：plan v1.0→v1.4 的 4 次 changelog 与实际 diff 是否相符；被依赖文档的版本引用是否最新
D. .hermes/task-log.md #15/#16 记录 vs 实际产物核对
E. 跑 python3 scripts/validate-cross-refs.py 确认全绿
F. 流程偏差清单：哪些环节偏离了流水线定义（如有），偏差是否已记录

输出：合规检查表(项×判定×证据) + P0/P1/P2 + 流程改进建议(最多 3 条，避免过程膨胀)。中文。" --max-turns 12 --output-format text 2>&1 | tee arch/reviews/m0-holistic-r4-governance.md | tail -5
```

---

## r2 重评模板（任何一刀发现 P0/P1 修复后用）

```bash
claude -p "Round-2 复核。r1 报告：arch/reviews/<r1文件>.md。已修复清单：<逐条列出修复动作与落点>。逐项给出 RESOLVED/NOT-RESOLVED + 一行证据；扫描修复是否引入新 P0/P1；verdict 行：CLOSED 或列出余项。中文，表格。" --max-turns 8 --output-format text 2>&1 | tee arch/reviews/<r1文件>-r2.md | tail -5
```

## Prompt 写法备忘（为什么这么写）

1. **清单不给感觉**——精确路径+版本，防评审者自选范围
2. **锚定已验证事实**——声明可信锚点省轮次，但保留"质疑方法"的口子
3. **已修/已延期声明**——防重报已关闭项（r2 靠这个把噪音砍半）
4. **独立性指令**——以规范为裁判，分析文档不得自证（防循环论证）
5. **输出结构强约束**——P0/P1/P2 + file:line + verdict，否则无法进修复循环
6. **分刀**——决策链/追溯链/对抗代码/治理四个注意力焦点，一刀一命令
