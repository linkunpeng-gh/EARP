评审报告已生成，但写入文件需要授权。以下是完整的 Gate A 评审结论：

---

## Gate A 结论：⚠️ 有条件通过（4 P1，修复后升 Gate B）

### P1（必须修复）

**P1-1: close 端点缺失** — AC-08 要求 `POST /v1/sessions/{id}/close` 验收，但 §3.1 范围表和 §2 US 均无 close 端点。状态机有 `active→close→closed` 路径却无功能条目对应。→ 补充范围行+US。

**P1-2: checkpoint 3 表 vs PRD 2 表** — M0 DDL 实际是 checkpoints + checkpoint_blobs + **checkpoint_writes** 三表（LangGraph PostgresSaver 模型）。PRD 全文只提前两张表，未解释 checkpoint_writes 为何 M1 不写入。→ 明确说明：writes 表已建但 M1 单步无需写入，M5 多步恢复时启用。

**P1-3: SDK 测试数 27→37** — PRD 写 runtime-py 有 27 测试，地面真值统计 37 个（test_mock_runtime 16 + test_invoker_http 12 + test_security 9）。→ 更正数字。

**P1-4: US-02 混合两个端点** — GET session + POST invoke 合并为一个 US，降低可追溯性。→ 拆分。

### P2（建议不阻塞）

- **P2-1**: Capability SDK 测试数 114 vs 实际 90
- **P2-2**: InputGuard（AC-11）缺对应 US
- **P2-3**: `stream()` 返回类型签名需在 §4.3 锁定
- **P2-4**: executions 行写入应在 §3.1 显式列出

### 对齐检查：通过

Runtime v1.3 / EventBus v1.1 / Audit v1.2 / Capability v1.4 / Security v1.1 / Tenant v1.2 — 全部关键条款对齐。M0 DDL 的 sessions/executions 已有 role_id 列，无需新增迁移。CloudEvents specversion="1.0" 正确。

### M0 顺手修 5 项：全部验证通过

F1-F5 在地面真值中均确认问题真实存在，描述准确。

---

评审详情已准备好写入 `arch/reviews/prd-2026-021-review.md`，是否需要我写入该文件？
