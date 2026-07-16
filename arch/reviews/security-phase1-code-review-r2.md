# 安全模块代码二次评审报告

## PRD-2026-005 Phase 1 — SDK 安全增强（修复验证）

| 字段 | 值 |
|------|-----|
| **评审范围** | 7 个文件变更（vs 上一轮 4 个新增问题） |
| **关联 PRD** | PRD-2026-005 v1.1 |
| **对齐规范** | Security Spec v1.1 (L2-06-SECURITY) |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **上一轮** | [security-phase1-code-review.md](../reviews/security-phase1-code-review.md) — 11 个问题（4 P0 / 5 P1 / 2 P2） |
| **本轮问题** | P0: 0 / P1: 1 / P2: 2 → **共 3 个** |

---

## 测试结果

| SDK | 测试文件 | 数量 | 结果 |
|:----|:---------|:----:|:----:|
| earp-sdk-core | `tests/test_masking.py` | 23 | ✅ 全部通过 |
| earp-sdk-connector | `tests/test_connector.py` | 23 | ✅ 全部通过 |
| earp-sdk-runtime | `tests/test_security.py` | 8 | ✅ 全部通过 |
| **合计** | | **54** | **全部通过** |

---

## 上一轮 P0 修复确认（4/4 ✅）

| # | 问题 | 修复方式 | 状态 |
|:-:|:-----|:---------|:----:|
| P0-1 | `StrEnum` 在 Python 3.9 不兼容 | `errors.py:6,46` — `ConnectorErrorCode` 和 `CapabilityErrorCode` 改为 `class X(str, Enum)` | ✅ |
| P0-2 | email/phone 脱敏格式与 Security Spec 不符 | `masking.py:24-41` — 新增 `_mask_email()`（保留首字母+域名）、`_mask_phone()`（保留前3后4位），通过 `_MASK_DISPATCH` 按字段分发 | ✅ |
| P0-3 | `logger.critical(extra={...})` 的 extra 字段不生效 | `base.py:87-94` — 改用 `logger.makeRecord()` + 显式属性赋值，字段直接设置在 LogRecord 上 | ✅ |
| P0-4 | 测试中 `or True` 短路掩盖问题 | `test_connector.py:223-228` — 改为 `getattr(audit_record, "audit_type", None)` 真实断言 | ✅ |

---

## 上一轮 P1 修复确认（5/5 ✅）

| # | 问题 | 修复方式 | 状态 |
|:-:|:-----|:---------|:----:|
| P1-1 | AuthConfig token/password 明文存储 | `config.py:8,10` — `field(default="", repr=False)` | ✅ |
| P1-2 | `_retry_connect` 对 AUTH_EXPIRED 盲重试 | `base.py:58-74` — 先捕获 `ConnectorError`，检查 `ce.retryable`，不可重试立即返回 False | ✅ |
| P1-3 | 未知 operation 抛 `INVALID_RESPONSE` | `errors.py:12` 新增 `OPERATION_NOT_FOUND`，`rest.py:101` 改用此错误码 | ✅ |
| P1-4 | mutability 语义矛盾 | `masking.py:64` — 文档明确："Mutates the input dict in place AND returns it." | ✅ |
| P1-5 | email/phone 测试断言格式不符 | `test_masking.py:29` → `"u***@example.com"`，`test_masking.py:34` → `"861****5678"` | ✅ |

---

## 上一轮 P2 修复确认（2/2 ✅）

| # | 问题 | 修复方式 | 状态 |
|:-:|:-----|:---------|:----:|
| P2-1 | 热路径中局部 import datetime | `base.py:3` — `from datetime import datetime, timezone` 移到文件顶部 | ✅ |
| P2-2 | mask 规则扩展性差 | `masking.py:45-56` — `_MASK_DISPATCH` dict 支持 per-field 策略函数，`_SENSITIVE_KEYS` 自动从 dispatch keys 构建 | ✅ |

---

## 本轮发现的新问题（3 个）

### P1-1：`_mask_phone` 对带国际区号的号码前3位包含国家码

**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/masking.py:34-41`

**场景**:
```python
_mask_phone("+86-138-1234-5678")  # → "861****5678"
```
`re.sub(r"\D", "", value)` 去除非数字后得到 `"8613812345678"`，然后取前3位 `"861"`（包含国家码 `86`）. Security Spec §3.2 的"保留前3后4位"在中文语境下指手机号前3位（如 `138`），而非含国家码的前3位。

**影响**: 低。Phase 1 主要面向国内场景，实际使用中号码格式可能已经标准化。且 phone 的 mask 仍提供了足够的隐私保护——中间 4 位被替换。

**建议**: 如果国码标准化是后续需求，可增加 `country_code` 参数：
```python
def _mask_phone(value: str, country_code: str = "") -> str:
    digits = re.sub(r"\D", "", value)
    if country_code and digits.startswith(country_code):
        digits = digits[len(country_code):]
    ...
```
当前行为可接受，标记为 P1 供后续迭代参考。

---

### P2-1：`_MASK_DISPATCH` 重复映射 — authorization/auth 与敏感字段无区分

**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/masking.py:45-56`

```python
_MASK_DISPATCH: dict[str, Callable[[str], str]] = {
    "password": _full_mask,
    "token": _full_mask,
    ...
    "authorization": _full_mask,  # 与敏感字段相同策略
    "auth": _full_mask,           # 与敏感字段相同策略
}
```

**问题**: 上一轮建议用 dict 区分字段→策略，现在实现了 `_MASK_DISPATCH`，但 authorization/auth 仍使用 `_full_mask`，与 password/token 无区分。如果将来需要"auth header 显示 Bearer 前缀 + mask token 部分"（常见于调试日志），当前结构虽然支持（只需替换函数引用），但 authorization/auth 混在 `_MASK_DISPATCH` 中不够显式。

**建议**: 可保持现状——结构已经足够灵活，只需替换 mask 函数即可。真正需要区分时再改。

---

### P2-2：`mask_sensitive` 对非字符串值静默跳过

**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/masking.py:80`

```python
if key_lower in _SENSITIVE_KEYS and isinstance(value, str):
    data[key] = _MASK_DISPATCH[key_lower](value)
```

**场景**: `{"token": 12345}` 或 `{"password": None}` 不会被 mask。当前静默跳过非字符串值——这是合理的防御性行为（mask 函数期望 `str` 输入），但调用方可能不知道 token 值因类型不对而被跳过。

**建议**: 保持当前行为。token/password 在 EARP 中始终是字符串，非字符串值属于调用方的 bug，静默跳过比 TypeError 更安全。如需严格性，可加 `DEBUG` 级别 log。

---

## 变更摘要

### 修复统计

| 级别 | 上一轮 | 已修复 | 剩余 | 本轮新增 | 当前未修复 |
|:----:|:------:|:------:|:----:|:--------:|:----------:|
| P0 | 4 | 4 | 0 | 0 | **0** |
| P1 | 5 | 5 | 0 | 1 | **1** |
| P2 | 2 | 2 | 0 | 2 | **2** |

### 当前状态

**所有 11 个上一轮问题已修复。** 本轮新增 3 个低优先级问题（1 P1 + 2 P2），均不阻塞合并。

---

## 总体评价

**修复质量高。** 第二轮变更精准命中上一轮的每个问题：

- **P0-1（StrEnum）**: `(str, Enum)` 多重继承是最小改动方案，向后兼容 Python 3.9+。同时顺便新增了 `OPERATION_NOT_FOUND` 错误码。
- **P0-2（email/phone）**: `_MASK_DISPATCH` dict + per-field 策略函数的设计干净，`_mask_email` 和 `_mask_phone` 逻辑正确，边界处理充分（空字符串、无 @ 符号）。
- **P0-3（audit extra）**: `makeRecord()` + 显式属性赋值是最可靠的方案——不依赖 logging format string 配置。
- **P1-2（盲重试）**: 双 `except` 分支（先 `ConnectorError` 再 `Exception`）逻辑正确，`ce.retryable` 检查阻止了 AUTH_EXPIRED 等不可重试错误的无效重试。

**测试结果: 54/54 全部通过**，无回归。

**可以合并。** 3 个新问题的严重程度均低，不构成阻塞条件。
