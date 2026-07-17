Permission allow rule (.claude/settings.local.json): Write(/Users/linkunpeng/work/adp2/**) is not matched by file permission checks — only Edit(path) rules are. Use Edit(/Users/linkunpeng/work/adp2/**) instead (Edit rules cover all file-editing tools).
## PRD-2026-013 评审

### 1. 范围（Scope）

**清晰点：**
- 4 个能力定义明确，数据来源映射完整
- "不做"边界清晰（SDK/UI/自动化回归）

**问题：**

| # | 问题 | 严重度 |
|---|------|:------:|
| S1 | **输入回放未处理副作用问题**。用历史 params+context "重跑 Capability 调用"，但 Capability 可能有写 DB、调外部 API 等副作用。AC-04 的 read-only 仅约束 Replay 基础设施，不约束被重放的 Capability 本身 | **P0** |
| S2 | **缺少沙箱/隔离要求**。Replay 应在隔离环境中执行，防止污染生产数据。PRD 未提及 | **P0** |
| S3 | 规范层到底输出什么不明确——PRD 只定义了能力名称和数据来源，缺少对 Replay 机制（触发方式、存储格式、回放协议）的最低要求 | P1 |
| S4 | 缺少 Replay 数据的保留策略和性能考量（如：一次 Replay 最多追溯多久的历史？） | P2 |

---

### 2. AC 可测试性

| AC | 可测试？ | 备注 |
|:--:|:--------:|------|
| AC-01 | ✅ | 检查 §6 是否存在，4 能力+数据映射是否定义 |
| AC-02 | ✅ | 计数 MUST 条款。注意：每能力 ≥3 条 MUST → 至少 12 条，量不小 |
| AC-03 | ⚠️ | "交叉引用一致"主观。建议拆解为具体检查项：如"§6 中引用的 AuditLog 字段与 Audit Spec v1.1 一致" |
| AC-04 | ✅ | 可验证规范中是否声明 read-only |

**缺失的 AC：**
- 未验证 Replay 规范与 Security Spec 的租户隔离要求一致（多租户下 Replay 不能跨租户访问数据）
- 未验证 Replay 输出的差异对比格式定义

---

### 3. 依赖完整性

| 依赖 | PRD 声明 | 实际版本 | 状态 |
|------|:--------:|:--------:|:----:|
| Observation Spec | v1.0 | v1.0 | ✅ |
| Audit Spec | v1.1 | v1.1 | ✅ |
| Runtime Spec | v1.2 | v1.2 | ✅ |
| Security Spec | v1.1 | v1.1 | ✅ |

版本号全部匹配。

**但存在交叉引用缺口：**
- **Audit Spec v1.1 未引用 Observation Spec**。Replay 的"决策链追溯"依赖 AuditLog 结构（event_type, timestamp, entity_id），但 Audit Spec 依赖列表中没有 Observation Spec。更新 Observation Spec 至 v1.1 后，需确认 Audit Spec 是否需要反向引用。
- **Security Spec v1.1 引用了 Observation Spec v1.0**（4 处）。PRD 产出物将 Observation Spec 升至 v1.1 后，Security Spec 的依赖声明需同步更新。
- **Runtime Spec v1.2 未引用 Observation Spec**。Replay 的"输入回放"依赖 Execution.payload，同样缺少交叉引用。

---

### 4. P0 总结

| ID | 描述 | 建议 |
|:--:|------|------|
| **P0-1** | 输入回放的副作用未定义 | 增加 MUST 条款：Replay 必须在沙箱环境中执行，或明确 Replay 仅适用于无副作用（idempotent）的 Capability |
| **P0-2** | 缺少隔离执行要求 | AC 中增加：Replay 执行环境与生产环境隔离，不得修改任何持久化数据（包括被重放的 Capability 产生的副作用） |

**建议：** 在 PRD 的"不做"中补充说明副作用处理策略（是 sandbox 还是仅限无副作用能力），否则实施时会有重大设计返工。
