# M2 成果评审 Prompt

> 用法：两条命令在仓库根目录执行。M2 规模小（1 PRD，核心改动 6 文件），两刀够用。
> 输出写 `arch/reviews/m2-holistic-review.md`。

---

## 第 1 刀：核心链路追溯（决策→设计→代码）

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M2 Policy Center 追溯审计。PRD→代码完整性判定。

评审对象（6 个核心文件）：
- prd/PRD-2026-022-server-m2-policy-rbac.md (v1.1, 6 US, 6 AC)
- apps/earp-server/src/earp_server/orchestrator/layers.py (PolicyLayer 完整实现)
- apps/earp-server/src/earp_server/capability/registry.py (discover 角色过滤 + Redis 限流)
- apps/earp-server/src/earp_server/orchestrator/types.py (InvokeContext.role_id)
- apps/earp-server/src/earp_server/runtime/invoke.py (PolicyLayer 接入)
- apps/earp-server/src/earp_server/main.py (rate_limiter + PolicyLayer wire-up)

已验证事实（可信任）：23/24 M1 回归绿；ruff 净。

逐 AC 判定（6 条）：
AC-01 '有权限→invoke 200；无权限→403 + PERMISSION_DENIED' → 检查 layers.py PolicyLayer.before_step 是否正确查 DB role.permissions、判子集、拒绝发布 CloudEvent
AC-02 'data_scope=self 过滤非本人数据' → 检查 layers.py after_step 过滤逻辑
AC-03 '令牌桶 10rps→第 11 次 429' → 检查 registry.py TokenBucketRateLimiter（INCR+EXPIRE pattern、pass-through fallback）
AC-04 'Capability discover 只返回角色可用' → 检查 registry.py discover() 的 required_permissions <@ role.permissions JOIN
AC-05 'audit COMPLETED/PERMISSION_DENIED 含 role_id' → 检查 layers.py AuditLayer CloudEvent 是否含 role_id + PolicyLayer PERMISSION_DENIED 事件
AC-06 'RBAC v1.1 §六 两个场景可执行' → 检查 tests/test_rbac_scenarios.py 的测试函数语义是否匹配 PRD 中的具体断言描述

反事实抽查（任选 1 条 AC）：说明你从代码确认该 AC 被真实覆盖的路径（不看测试数量，看断言语义）。

输出：AC 逐条 FULL/PARTIAL/MISSING + P0/P1/P2 + file:line 证据。中文，表格。" > arch/reviews/m2-holistic-review.md 2>&1
```

---

## 第 2 刀：架构一致性 + RBAC 测试缺口（短刀）

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M2 架构一致性快速扫描。

检查项（2-3 轮，每项 1 行判定）：

A. PolicyLayer 拦截器链正确性：
   - 是否作为 M1 Layer Protocol 的实现（before_step/after_step 签名不变）？
   - before_step 拒绝是否通过 HTTPException(403) 终止链（不执行后续 layer/step）？
   - PolicyLayer.__init__ 是否接受 engine+bus（与其他 Layer 的注入模式一致）？

B. Capability 角色过滤边界：
   - discover() 无 role_id 时是否走无过滤路径（兼容 M1 现有调用）？
   - <@ 操作符是否正确使用 text[] 数组包含语义？
   - 无角色时返回空列表 vs 全量——当前行为是否符合 PRD？

C. Redis 限流集成：
   - TokenBucketRateLimiter 是否正确处理 Redis 不可达（pass-through 非阻塞）？
   - 当前是否接入 invoke 路径（main.py 创建但 invoke.py 未调用 is_allowed）？

D. InvokeContext.role_id 链路完整性：
   - types.py 新增字段 → invoke.py 传递 ctx.role_id → layers.py 消费
   - M1 既有代码（test_m1_walking_skeleton.py）是否因新增字段而 break？

E. RBAC 场景测试（test_rbac_scenarios.py）：
   - 种子数据 INSERT 使用 f-string（非参数化），属于 documented limitation（psycopg ':' 占位符冲突）
   - 4 个测试函数语义是否完整覆盖 PRD AC-01/04/05/06？

F. 与 RBAC 设计 v1.1 的一致性：
   - Role.permissions (list[str] domain:action) 是否正确映射到 $3.1？
   - data_scope 四层过滤是否与 $3.2 一致（M2 实现了 self/all，department/org 留 M3）？
   - 能力可见性过滤是否对齐 $3.3？
   - Audit role_id 补充是否对齐 $3.5？（自查 RBAC v1.1 中是否定义了 $3.5 审计角色信息）

输出：逐项 PASS/ISSUE/NA + 一行证据 + P0/P1/P2。中文，表格。" >> arch/reviews/m2-holistic-review.md 2>&1
```

---

## r2 重评模板

```bash
codex exec "Round-2 复核。r1 报告：arch/reviews/m2-holistic-review.md。已修复清单：...。逐项 RESOLVED/NOT-RESOLVED + 一行证据；新 P0/P1 扫描；verdict CLOSED。中文，表格。" >> arch/reviews/m2-holistic-review-r2.md 2>&1
```

---

## 避坑备忘（本 session 实战验证）

1. **不用 `| tee`**——Claude 验证代理会吞输出。用 `> file 2>&1` 或 `>> file 2>&1`
2. **`--max-turns` 按规模定**：PRD 审 3-5，代码审 8-12，全景多文件 12-15
3. **`--append-system-prompt-file`** 单文档通道，比 pipe 可靠
4. **退出码 None** = 进程被信号杀（超时/内存），减轮次或缩范围
5. **第 2 刀用 `>>` 追加**，不覆盖第 1 刀结果
