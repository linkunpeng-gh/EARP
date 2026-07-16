# Security Phase 3 — 代码评审报告

## PRD-2026-007 v1.2 — InputGuard + OutputFilter（LLM 安全）

| 字段 | 值 |
|------|-----|
| **评审范围** | 2 个文件变更 + 1 个新模块 + 1 个新测试文件 |
| **关联 PRD** | PRD-2026-007 v1.2 |
| **对齐规范** | Security Spec v1.1 §4 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **问题统计** | P0: 0 / P1: 2 / P2: 4 → **共 6 个** |

---

## 测试结果

| 文件 | 数量 | 结果 |
|:-----|:----:|:----:|
| `test_guard.py` | 37 | ✅ 全部通过 |
| `test_masking.py` (P1 reg) | 23 | ✅ |
| `test_credential.py` (P2 reg) | 21 | ✅ |
| `test_key_source.py` (P2 reg) | 8 | ✅ |
| `test_audit.py` (P2 reg) | 8 | ✅ |
| `test_connector.py` (P1+P2 reg) | 25 | ✅ |
| **合计** | **122** | **全部通过** |

---

## 总体评价

**实现质量高，代码简洁清晰。** 单文件 `guard.py`（235 行）覆盖了 InputGuard 和 OutputFilter 的全部功能，`GuardResult` dataclass 精确对齐 PRD。37 个新测试覆盖充分——包括注入检测、净化、摘要、PII/泄露/代码检测、审计发布、sanitize 标记的 false positive 专门测试。Phase 1/2 零回归（85 个存量测试全部通过）。

无 P0 阻塞问题。2 个 P1 为安全相关，4 个 P2 为代码优化。

---

## P0 — 必须修复（0 个）

无。

---

## P1 — 建议修改（2 个）

### P1-1：`_PII_RE` 正则在长文本中存在性能隐患

**文件**：`guard.py:31-35`

```python
_PII_RE = re.compile(
    r'([\w.+-]+@[\w-]+\.[\w.-]+)'
    r'|(\+?\d[\d\-()\s]{6,}\d)',
    re.IGNORECASE,
)
```

**问题**：这是一个包含交替（`|`）的复杂正则，且不含锚点。当扫描长 LLM 输出（数千字符）时，每个位置都可能触发回溯。更关键的是，`[\d\-()\s]{6,}` 是一个贪婪量词，在非电话号码的纯数字序列上可能产生大量回溯。

**影响**：典型 LLM 输出大约几百字，当前正则没有实际性能问题。风险在于：如果 LLM 输出包含长 JSON 块或代码块（数千字符无标点），回溯可能显著增加检查时间。

**建议**：对 phone 部分增加边界锚点：

```python
_PII_RE = re.compile(
    r'([\w.+-]+@[\w-]+\.[\w.-]+)'
    r'|(\+?\d[\d\-()\s]{6,}\d)',
    re.IGNORECASE,
)
```

如果实在不放心，可以拆成两个独立的简单正则分别匹配 email 和 phone，消除交替回溯：

```python
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_PHONE_RE = re.compile(r'\+?\d[\d\-()\s]{6,}\d')
```

当前影响极低，标记为 P1 供后续优化。

---

### P1-2：sanitize 标记替换逻辑不完整

**文件**：`guard.py:98-102`

```python
text_to_check = text
header_stripped = _SANITIZE_HEADER.strip()
footer_stripped = _SANITIZE_FOOTER.strip()
if header_stripped in text_to_check:
    text_to_check = text_to_check.replace(_SANITIZE_HEADER, "")
    text_to_check = text_to_check.replace(_SANITIZE_FOOTER, "")
```

**问题**：用 `.strip()` 后的值做 `in` 检查，但 `.replace()` 用的是原始值（带 `\n`）。这导致：

- 如果文本以 `--- USER INPUT ---`（无前导 `\n`）开头，`header_stripped in text` 为 True，但 `text.replace(_SANITIZE_HEADER, "")` 不匹配（`_SANITIZE_HEADER` 以 `\n` 开头）
- 结果：标记未移除，注入检测可能误报

**场景**：
```python
guard = InputGuard()
sanitized = guard.sanitize("hello")
# → "\n--- USER INPUT ---\nhello\n--- END USER INPUT ---\n"

guard.check(sanitized)
# header_stripped = "--- USER INPUT ---" → in sanitized → True
# replace("\n--- USER INPUT ---\n", "") → 匹配成功（sanitize 生成的有 \n）

# 但如果别人直接传 "--- USER INPUT ---\nhello"（无前导 \n）
# → header_stripped = "--- USER INPUT ---" → in text → True
# → replace("\n--- USER INPUT ---\n", "") → 不匹配！标记未移除

# 同时，直接的 "--- USER INPUT ---" 本身会触发分隔符覆盖检测
```

**实际影响**：极低。sanitize 生成的输出总是带前导 `\n`，正常调用路径不会触发此问题。

**建议**：统一检查逻辑——检查前先一次性替换原始标记：

```python
# Strip both header and footer regardless of leading newline presence
text_to_check = text
text_to_check = text_to_check.replace(_SANITIZE_HEADER.strip(), "")
text_to_check = text_to_check.replace(_SANITIZE_FOOTER.strip(), "")
```

---

## P2 — 优化建议（4 个）

### P2-1：`_SENSITIVE_KEYS` 已 import 但未使用

**文件**：`guard.py:10`

```python
from earp_sdk_core.masking import _SENSITIVE_KEYS
```

`_SENSITIVE_KEYS` 导入了但 `guard.py` 中没有直接使用——PII 检测用的是自己的 `_PII_RE`，不是 `_SENSITIVE_KEYS`。

PRD AC-03 要求"复用 Phase 1 mask_sensitive 的 `_SENSITIVE_KEYS` 字段集合和 `_MASK_DISPATCH`"，但这是说**概念层面**共享敏感字段定义——email、phone、password、token 等等。实际运行时 guard 使用独立的 regex，masking 使用 key-lookup。

当前代码的 import 似乎是占位符，但未实际使用。要么用它（例如遍历 `_SENSITIVE_KEYS` 参与 PII 类型的标签生成），要么移除避免 dead import 被 linter 标记。

**建议**：如果没有计划在 guard 中直接使用，移除这行 import，在 docstring 中加注释说明复⽤关系。

---

### P2-2：PII 检测的 `_PII_RE` 与 `mask_sensitive` 的敏感字段定义不同步

**文件**：`guard.py:31-35` vs `masking.py:45-56`

| | `_PII_RE` | `mask_sensitive._MASK_DISPATCH` |
|:--|:---------|:-----------------------------|
| email | ✅ `\w+@\w+\.\w+` | ✅ `email` key |
| phone | ✅ `\d[\d\-()\s]{6,}\d` | ✅ `phone` key |
| password | ❌ 无 | ✅ `password` key |
| token | ❌ 无 | ✅ `token` key |
| secret | ❌ 无 | ✅ `secret` key |
| api_key | ❌ 无 | ✅ `api_key` key |
| id_card | ❌ 无 | ✅ `id_card` key |
| ssn | ❌ 无 | ✅ `ssn` key |

**分析**：`_PII_RE` 只能检测 email 和 phone 两类 PII（因为它们有可识别的 pattern）。password/token/secret/api_key/id_card/ssn 没有普适的正则模式——它们依赖上下文中的 key 名（如 `{"password": "xxx"}`），这正是 `mask_sensitive` 的工作方式。

这种差异是合理的：`OutputFilter.check()` 处理 free-text LLM 输出，只能检测有 pattern 的 PII；`mask_sensitive` 处理结构化 dict，按 key 名匹配。两者的交集只有 email 和 phone。

**建议**：在 `OutputFilter` docstring 中注明这一限制：

```
PII detection currently covers email and phone (regex-matchable patterns).
Password, token, secret, api_key, id_card, ssn are detected by
mask_sensitive() on structured data; they have no reliable free-text pattern.
```

---

### P2-3：`test_guard.py:152-159` 测试 phone PII 用 `+86-138-1234-5678`，但 `_PII_RE` phone 部分可能匹配不完整

**验证**：`+86-138-1234-5678` 去除非数字字符后为 `"8613812345678"`  — 12 位数字。`_PII_RE` 的 phone 部分 `\+?\d[\d\-()\s]{6,}\d` 匹配：

```
+?    → 匹配 "+"
\d    → 匹配 "8"
[\d\-()\s]{6,}  → 匹配 "6-138-1234-567"（15 个字符）
\d    → 匹配 "8"
```

整个 phone 号码被匹配——正确。测试通过了，没问题。

但测试 `test_pii_phone_detected` 只断言 `status == "filtered"`——它没有断言 phone 号码本身被提取到 `pii_detected` 中。建议补一条更严格的断言：

```python
def test_pii_phone_detected(self):
    r = self.filter.check("Call +86-138-1234-5678 now")
    assert r.status == "filtered"
    assert any("138" in item for item in r.detail.get("pii_detected", []))
```

---

### P2-4：审计事件重复代码——InputGuard 和 OutputFilter 各自独立构造 AuditEvent

**文件**：`guard.py:113-119`、`guard.py:181-190`、`guard.py:200-208`

三处审计发布代码结构和错误处理完全一致，只有参数不同：
- 注入检测：`event_type="PROMPT_INJECTION_DETECTED", action="input_guard_check"`
- 泄露检测：`event_type="SYSTEM_PROMPT_LEAK", action="output_filter_check"`
- 代码检测：`event_type="DANGEROUS_CODE", action="output_filter_check"`

**建议**：提取 `_publish_security_audit(event_type, action, result, detail)` 辅助函数减少重复。P2 级别，不阻塞合并。

---

## 与 PRD AC 对齐检查

| AC | 描述 | 实现位置 | 测试 | 状态 |
|:--:|:-----|:---------|:----:|:----:|
| AC-01 | InputGuard.check → blocked + detail | `guard.py:87-124` | `test_guard.py:35-83` | ✅ |
| AC-02 | InputGuard.sanitize 分隔符包裹 | `guard.py:126-133` | `test_guard.py:87-114` | ✅ |
| AC-03 | OutputFilter PII → filtered + pii_detected | `guard.py:211-222` | `test_guard.py:152-159` | ✅ |
| AC-04 | OutputFilter system prompt → blocked | `guard.py:173-190` | `test_guard.py:161-168` | ✅ |
| AC-05 | OutputFilter 危险代码 → filtered | `guard.py:192-209` | `test_guard.py:170-181` | ✅ |
| AC-06 | OutputFilter.require_approval | `guard.py:226-234` | `test_guard.py:198-205` | ✅ |
| AC-07 | InputGuard blocked → publish_audit_event | `guard.py:113-119` | `test_guard.py:213-221` | ✅ |
| AC-08 | InputGuard.summarize 截断+标注 | `guard.py:135-145` | `test_guard.py:118-141` | ✅ |
| AC-09 | OutputFilter blocked (泄露) → audit | `guard.py:181-190` | `test_guard.py:223-230` | ✅ |
| AC-10 | OutputFilter filtered (代码) → audit | `guard.py:200-208` | `test_guard.py:232-239` | ✅ |

**AC 10/10 全部覆盖。** ✅

---

## 与 Security Spec 的对齐

| Security Spec §4 要求 | 实现 | 状态 |
|:----------------------|:-----|:----:|
| §4.1 InputGuard 实体定义 | `class InputGuard` | ✅ |
| §4.1 OutputFilter 实体定义 | `class OutputFilter` | ✅ |
| §4.2 MUST: 用户输入通过 InputGuard | `InputGuard.check()` | ✅ |
| §4.2 MUST: 分隔符隔离系统 Prompt | `InputGuard.sanitize()` | ✅ |
| §4.2 MUST: 外部数据源摘要/过滤 | `InputGuard.summarize()` | ✅ |
| §4.2 直接注入：（指令覆盖/角色翻转/分隔符覆盖/Prompt窃取） | `_INJECTION_PATTERNS` 7个正则 | ✅ |
| §4.2 间接注入：（Phase 3 截断代替 LLM 摘要） | `summarize()` 截断+标注 | ✅ |
| §4.2 泄露系统 Prompt | `OutputFilter.check()` 短语匹配 | ✅ |
| §4.3 MUST: LLM 输出经过 OutputFilter | `OutputFilter.check()` | ✅ |
| §4.3 MUST: Command 参数人工审核 | `OutputFilter.require_approval()` | ✅ |
| §4.2 SHOULD: 注入检测审计 | AC-07/09/10 → `publish_audit_event` | ✅ |

---

## 代码质量观察

### 好的方面

- **单文件简洁实现** — `guard.py` 235 行覆盖全部功能，`GuardResult` 支持统一返回类型，调用方无需区分 Input/Output 的返回值
- **sanitize 标记处理正确** — check() 在注入检测前剥离自己的 sanitize 标记，`test_sanitized_input_not_false_positive` 和 `test_sanitized_input_with_injection_still_blocked` 两条测试专门覆盖
- **审计降级与 P1/P2 一致** — `try/except Exception: pass` + `publish_audit_event` 的 fallback 模式与 Phase 2 `_on_error` 一致
- **注入模式表 7 个正则覆盖 4 类攻击** — 对齐 Security Spec §4.2 和 PRD §3 模式表
- **`require_approval()` 无参纯标记** — 正确的设计决策，Security Spec §4.3 的审批判断权在 Policy Center
- **测试覆盖全面** — 37 个测试覆盖了所有 10 条 AC + false positive 专门测试 + empty/unicode/边界测试
- **Phase 1+2 零回归** — 122 个测试全部通过

---

## 评审总结

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| ❌ P0 | 0 | — |
| ⚠️ P1 | 2 | _PII_RE 性能（交替+回溯）；sanitize 标记替换逻辑中 strip() 与 replace() 不一致 |
| 💡 P2 | 4 | _SENSITIVE_KEYS import 未使用；PII 检测覆盖与 mask_sensitive 不同步；phone 测试断言不够严格；audit 重复代码 |

### 结论

**可以合并。** 实现简洁清晰，10/10 AC 全部覆盖，37 个新测试充分，Phase 1/2 零回归。2 个 P1 影响极低，4 个 P2 为代码优化建议。
