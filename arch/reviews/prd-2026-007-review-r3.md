# PRD-2026-007 三次评审报告

## Security Phase 3 — InputGuard + OutputFilter（LLM 安全）

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-007 |
| **版本** | v1.2 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **上一轮** | [prd-2026-007-review-r2.md](../reviews/prd-2026-007-review-r2.md) — 2 个问题（1 P1 / 1 P2） |
| **本轮** | P0: 0 / P1: 0 / P2: 3 → **共 3 个** |

---

## 总体评价

**上一轮的 2 个问题全部修复。** v1.2 质量高，可以进入 Gate 0。

本轮新增 3 个 P2，均为 L3 设计时可处理的细节问题，不阻塞。

---

## 上一轮问题修复确认（2/2 ✅）

### P1-1（R2）：OutputFilter 审计事件缺 AC ✅

**修复**：新增 2 条 AC——

| AC | 触发条件 | event_type |
|:--:|:---------|:-----------|
| AC-09 | `OutputFilter.check()` → blocked（system prompt 泄露） | `SYSTEM_PROMPT_LEAK` |
| AC-10 | `OutputFilter.check()` → filtered（危险代码） | `DANGEROUS_CODE` |

与 AC-07（InputGuard 注入检测审计）一起构成完整的审计 AC 覆盖。✅

---

### P2-1（R2）：sanitize 分隔符与注入检测重叠 ✅

**修复**：§8 US-02 新增实现说明——

```
sanitize 后的输入传给 guard.check() 不会被误检测
（InputGuard 识别 sanitize 标记并跳过注入检测）
实现方式：sanitize 前缀标记作为"安全区"信号，
check() 内部检测到 --- USER INPUT --- 起始行时跳过该段
```

实现方案明确：check() 识别 `--- USER INPUT ---` 作为"安全区起始"，跳过其后的用户内容。注入检测仅扫描安全区外的区域。✅

---

## 本轮发现的新问题（3 个 P2）

### P2-1：§8 缺少 US-01（注入检测）和 US-04（审批标记）的预期行为

当前 §8 覆盖：
- US-02：输入净化 ✅
- US-03：输出过滤 ✅
- US-05：审计集成 ✅

US-01（注入检测）的行为在 §3 模式表和 §7.1 接口预览中已有充分描述，但未在 §8 独立成段。US-04（`require_approval()`）是一个直白的纯标记函数，也不在 §8。

**建议**：可在 §8 补充简短段落，也可保持现状——§3 模式表 + §7 接口预览的内容已经足够。

---

### P2-2：审计事件中 `tenant_id`/`user_id`/`action` 未指定

AC-07/AC-09/AC-10 要求调用 `publish_audit_event`，但 `AuditEvent` 的 MUST 字段 `tenant_id`/`user_id`/`action` 在 PRD 中未指定值。InputGuard/OutputFilter 是 stateless 检测工具，不具备租户/用户上下文。

Phase 2 代码评审中 `base.py:93` 出现过同类问题：`tenant_id=""` 始终为空。Phase 3 面临同样的情况——Suggestion：在 L3 设计中沿用与 Phase 2 一致的策略：`tenant_id=""`、`user_id=""`（系统事件）、`action` 由检测类型派生（如 `"prompt_injection_detected"`）。

**建议**：在 §8 US-05 中加一句说明，或在 L3 设计中处理。

---

### P2-3：AC-03 "复用 mask_sensitive" 的实现模型需在 L3 设计中澄清

AC-03 原文：
```
PII 检测复用 Phase 1 mask_sensitive 的 _SENSITIVE_KEYS 字段集合和 _MASK_DISPATCH
```

`mask_sensitive` 在 dict 上操作（按 key 名匹配），而 `OutputFilter.check()` 接收 free-text 字符串。不能直接复用函数调用，需要提取 `_SENSITIVE_KEYS` 中的字段名（如 `email`、`phone`）作为 regex 搜索关键词，在 free-text 中扫描匹配。

复用策略需要在 L3 设计中明确：
- 复用 `_SENSITIVE_KEYS` 的字段名 → 作为 PII 类型标签
- 复用 `_MASK_DISPATCH` 中的 `_mask_email`/`_mask_phone` → 作为提取后脱敏的函数
- regex 匹配逻辑 → OutputFilter 自行实现

**建议**：在 L3 设计中补充这段说明，或 AC-03 改为"复用 mask_sensitive 的敏感字段**识别逻辑**"。

---

## 变更摘要

### 修复统计

| 级别 | R1 | R1→R2 | R2 新增 | R2→R3 | R3 新增 | 未修复 |
|:----:|:--:|:-----:|:------:|:-----:|:------:|:------:|
| P0 | 2 | 2 | 0 | — | 0 | **0** |
| P1 | 3 | 3 | 1 | 1 | 0 | **0** |
| P2 | 2 | 2 | 1 | 1 | 3 | **3** |

### 版本演进

| 版本 | 核心变更 |
|:----:|:---------|
| v1.0 | 初版，6 US + 8 AC |
| v1.1 | +GuardResult dataclass, +注入模式表, require_approval, +预期行为 |
| v1.2 | +AC-09/AC-10（OutputFilter 审计）, +sanitize 实现方式 |

---

## 评审总结

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| P0 | **0** | — |
| P1 | **0** | — |
| P2 | **3** | §8 缺 US-01/04 预期行为；审计 tenant_id/user_id/action 未指定；PII 复用的实现模型需澄清 |

**v1.2 可以进入 Gate 0。** 3 个 P2 均为 L3 设计阶段可处理的细节。
