# 安全模块代码评审报告

## PRD-2026-005 Phase 1 — SDK 安全增强

| 字段 | 值 |
|------|-----|
| **评审范围** | 4 个文件变更 + 1 个新增模块（masking.py） |
| **关联 PRD** | PRD-2026-005 v1.1 |
| **对齐规范** | Security Spec v1.1 (L2-06-SECURITY) |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **评审等级** | high |
| **问题统计** | P0: 4 / P1: 5 / P2: 2 → **共 11 个** |

---

## 涉及文件

| 文件 | 状态 | 说明 |
|:-----|:----:|:-----|
| `libs/earp-sdk-core-py/src/earp_sdk_core/masking.py` | **新增** | 敏感字段脱敏工具（Security Spec §3.2） |
| `libs/earp-sdk-core-py/src/earp_sdk_core/__init__.py` | 修改 | 导出 `mask_sensitive` |
| `libs/earp-sdk-core-py/pyproject.toml` | 修改 | 新增 pytest 配置 |
| `libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py` | 修改 | AUTH_EXPIRED 结构化审计日志 |
| `libs/earp-sdk-connector-py/tests/test_connector.py` | 修改 | 新增 AC-02/AC-05 安全测试 |
| `libs/earp-sdk-core-py/tests/test_masking.py` | **新增** | mask_sensitive 单元测试（AC-03/AC-04） |
| `libs/earp-sdk-runtime-py/tests/test_security.py` | **新增** | JWT Bearer header 传播测试（AC-01） |

---

## 总体评价

**方向正确，覆盖面好。** 5 个 AC 均有对应的实现和测试——JWT 传递（AC-01）、token 脱敏（AC-02）、mask_sensitive 内置字段（AC-03）、全字段覆盖（AC-04）、结构化审计日志（AC-05）。跨 Core/Connector/Runtime 三个 SDK 的改动量合理，PRD 对齐度高。

但存在两个需要立即处理的 P0：**`enum.StrEnum` 在 Python 3.9 不兼容**导致所有 SDK 不可用、**审计日志 `extra` 字段不生效**使 AC-05 实际未达成。另外 `mask_sensitive` 对 email/phone 的脱敏格式与 Security Spec §3.2 不一致。

---

## P0 — 必须修复（4 个）

### P0-1：`errors.py:2` — `enum.StrEnum` 在 Python 3.9 下不可用

**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/errors.py:2`

**场景**: macOS 系统 Python 3.9.6 环境，import 时直接报错：

```
ImportError: cannot import name 'StrEnum' from 'enum'
```

**原因**: `StrEnum` 在 Python 3.11 才引入。项目 pyproject.toml 未声明 `requires-python` 下限，但 macOS 系统 Python 为 3.9.6，导致所有依赖 `earp_sdk_core` 的 SDK（Runtime/Connector）全部无法 import。

**影响链路**:
```
masking.py → __init__.py → errors.py → from enum import StrEnum → ImportError
```
这意味着即使不涉及 StrEnum 的 `mask_sensitive` 函数也无法使用。

**建议方案**:

```python
# 方案 A：多重继承（推荐，零依赖）
class ConnectorErrorCode(str, Enum):
    CONNECTION_FAILED = "CONNECTION_FAILED"
    ...

# 方案 B：使用 typing 兼容写法
import sys
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    class StrEnum(str, Enum):
        pass
```

---

### P0-2：`masking.py:12-13` — email/phone 脱敏格式与 Security Spec §3.2 不一致

**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/masking.py:12-13`

**Security Spec §3.2 原文**:

```
MUST: 以下字段在日志/审计/API 响应中自动脱敏：
  - email（保留 @ 前首字母，替换其余为 ***）
  - phone（保留前 3 后 4 位，中间替换为 ****）
  - id_card / ssn（替换全部为 ***）
```

**当前实现**: email、phone、id_card、ssn 全部替换为 `"***"`，丢失了规范要求的精确格式。

**对比**:

| 字段 | Security Spec 要求 | 当前实现 |
|:-----|:-------------------|:---------|
| email | `u***@example.com` | `***` |
| phone | `138****5678` | `***` |
| id_card | `***` | `***` ✅ |
| ssn | `***` | `***` ✅ |

**建议方案**:

```python
def _mask_email(value: str) -> str:
    """保留 @ 前首字母，其余替换为 ***"""
    if "@" in value:
        local, domain = value.split("@", 1)
        return local[0] + "***@" + domain if local else "***@" + domain
    return value[0] + "***" if value else "***"

def _mask_phone(value: str) -> str:
    """保留前 3 后 4 位，中间替换为 ****"""
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 7:
        return digits[:3] + "****" + digits[-4:]
    return "***"

# 在 mask_sensitive 中按字段类型分发
_MASK_DISPATCH = {
    "password": lambda v: "***",
    "token": lambda v: "***",
    "secret": lambda v: "***",
    "api_key": lambda v: "***",
    "email": _mask_email,
    "phone": _mask_phone,
    "id_card": lambda v: "***",
    "ssn": lambda v: "***",
}
```

---

### P0-3：`base.py:78` — `logger.critical` 的 `extra` 字段不会自动成为 LogRecord 属性

**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:78`

**场景**: AUTH_EXPIRED 发生时调用：

```python
logger.critical("Security audit: AUTH_EXPIRED", extra={
    "audit_type": "AUTH_EXPIRED",
    "connector_id": self.connector_id,
    "timestamp": datetime.now(timezone.utc).isoformat(),
})
```

**问题**: Python 标准库 `logging` 中，`extra` dict 的字段**只有当 format string 或 filter 中显式使用时才会注入到 LogRecord**。如果 format string 是 `"%(message)s"`（默认），extra 中的字段不会出现在 `LogRecord.__dict__` 中。

这意味着 `caplog` 抓取到的 `LogRecord` 上永远不会有 `audit_type`、`connector_id`、`timestamp` 这三个属性。AC-05（结构化审计日志）实际上不生效。

**建议方案**:

```python
# 方案 A：使用 logging.LoggerAdapter（推荐）
class AuditLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs

# 方案 B：显式设置 LogRecord 属性（简单直接）
record = logger.makeRecord(
    logger.name, logging.CRITICAL, "(unknown file)", 0,
    "Security audit: AUTH_EXPIRED", (), None
)
record.audit_type = "AUTH_EXPIRED"
record.connector_id = self.connector_id
record.timestamp = datetime.now(timezone.utc).isoformat()
logger.handle(record)
```

---

### P0-4：`test_connector.py:222` — `or True` 短路掩盖了 P0-3

**文件**: `libs/earp-sdk-connector-py/tests/test_connector.py:222`

```python
assert hasattr(audit_record, "audit_type") or "audit_type" in getattr(audit_record, "extra", {}) or True
```

**问题**: 最后一个 `or True` 短路了整条断言，使验证**永远通过**。结合 P0-3（extra 字段不会出现在 LogRecord 上），该断言根本无法捕获问题。

**建议**: 修复 P0-3 后，将测试改为直接验证 LogRecord 属性：

```python
extra = getattr(audit_record, "extra", {})
assert extra.get("audit_type") == "AUTH_EXPIRED"
assert extra.get("connector_id") == "audit-conn-1"
assert extra.get("timestamp") is not None
```

---

## P1 — 建议修改（5 个）

### P1-1：`config.py:17-18` — `AuthConfig.token` 和 `password` 明文存储

**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/config.py:15-18`

```python
@dataclass
class AuthConfig:
    type: str = ""
    token: str = ""       # 明文
    username: str = ""
    password: str = ""    # 明文
```

**问题**: Security Spec §2.2 MUST 要求"AES-256-GCM 加密存储"，当前以 `str` 明文存储在 dataclass 中。虽然 Phase 2 才实施加密存储，但当前无任何防护措施（如 `__repr__` 遮掩、属性访问控制），任何访问 `config.auth.token` 的代码都可直接读取明文。

**建议**: Phase 1 至少应做到：

```python
@dataclass
class AuthConfig:
    type: str = ""
    token: str = field(default="", repr=False)     # repr 不显示
    username: str = ""
    password: str = field(default="", repr=False)  # repr 不显示
```

---

### P1-2：`base.py:55` — `_retry_connect` 对 AUTH_EXPIRED 盲重试

**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:54-65`

```python
async def _retry_connect(self, max_attempts: int = 3) -> bool:
    for attempt in range(max_attempts):
        if self.status == ConnectorStatus.ACTIVE:
            return True
        try:
            await self.connect()
            return True
        except Exception:             # 裸 except
            if attempt == max_attempts - 1:
                return False
            await asyncio.sleep(2 ** attempt)
    return False
```

**问题**: 裸 `except Exception` 捕获一切——包括 `AUTH_EXPIRED`。对已过期的 token 重试连接无意义，3 次重试只会延长故障时间，且频繁认证失败可能触发外部安全告警。

**建议**: AUTH_EXPIRED 标记为不可重试：

```python
except ConnectorError as ce:
    if not ce.retryable:
        return False
    ...
```

---

### P1-3：`rest.py:101` — 未知 operation 的语义错误码

**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/rest.py:101`

```python
raise ConnectorError(ConnectorErrorCode.INVALID_RESPONSE,
    f"Operation '{operation}' not defined.")
```

**问题**: `INVALID_RESPONSE` 语义暗示"服务端返回了非法响应"，但这里实际是"调用方传入了未知操作"——属于客户端错误。使用 `INVALID_RESPONSE` 会误导日志/监控分析。

**建议**: 新增 `OPERATION_NOT_FOUND` 错误码，或使用 `CapabilityErrorCode.CAPABILITY_NOT_FOUND`：

```python
# 方案 A：扩展 ConnectorErrorCode
OPERATION_NOT_FOUND = "OPERATION_NOT_FOUND"

# 方案 B：直接复用 CapabilityError
raise CapabilityError(CapabilityErrorCode.CAPABILITY_NOT_FOUND,
    f"Operation '{operation}' not defined.")
```

---

### P1-4：`masking.py:19` — 函数 mutability 语义矛盾

**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/masking.py:19`

```python
def mask_sensitive(data: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    """Recursively mask sensitive fields in a dictionary.
    ...
    Returns:
        The same dict with sensitive values replaced.
    """
```

**文档说** "The same dict with sensitive values replaced"（原地修改+返回同一个对象），但嵌套 dict 的赋值 `data[key] = mask_sensitive(value)` 的行为取决于递归调用内部的实现。调用方可能误以为传入的 dict 不会被修改，导致意外的数据损坏。

**建议**: 明确选择一种行为并文档化：

```python
# 推荐：返回新 dict（函数式风格，更安全）
def mask_sensitive(data: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with sensitive values replaced.
    The original dict is not modified.
    """
    result = {}
    for key, value in data.items():
        ...
        result[key] = ...
    return result
```

---

### P1-5：`test_masking.py:28,33` — email/phone 测试断言与 Security Spec 精确格式不匹配

**文件**: `libs/earp-sdk-core-py/tests/test_masking.py:28-38`

```python
def test_email_masked(self):
    result = mask_sensitive({"email": "user@example.com"})
    assert result["email"] == "***"          # 应为 "u***@example.com"

def test_phone_masked(self):
    result = mask_sensitive({"phone": "+86-138-1234-5678"})
    assert result["phone"] == "***"          # 应为 "138****5678"
```

**问题**: 与 P0-2 关联。修复 P0-2 后，这两条测试也需要更新。

---

## P2 — 优化建议（2 个）

### P2-1：`base.py:77` — 热路径中的局部 import

**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:77`

```python
if ce.code == ConnectorErrorCode.AUTH_EXPIRED:
    from datetime import datetime, timezone     # 每次 AUTH_EXPIRED 都 import
    logger.critical(...)
```

**问题**: 每次 AUTH_EXPIRED 都执行 import——虽然 Python 有 import 缓存，但仍有 dict 查找开销。违反 PEP 8（import 应在文件顶部）。

**建议**: 移到文件顶部：
```python
from datetime import datetime, timezone
```

---

### P2-2：`masking.py:41` — Auth header 与敏感字段 mask 逻辑完全相同时的维护问题

**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/masking.py:16,41`

```python
_AUTH_HEADER_FIELDS = frozenset({"authorization", "auth"})
...
if key_lower in _SENSITIVE_FIELDS or key_lower in _AUTH_HEADER_FIELDS:
    data[key] = "***"
```

**问题**: auth header 字段与敏感字段的 mask 逻辑完全相同，都替换为 `"***"`。如果将来需要区分处理（如 `Authorization: Bearer eyJ***` 允许显示 token 前缀方便调试），当前结构不易扩展。

**建议**: 合并为一个字段集合，或使用 dict 映射字段→mask 策略：
```python
_MASK_RULES = {
    **{f: _full_mask for f in ("password","token","secret","api_key","email","phone","id_card","ssn")},
    **{f: _full_mask for f in ("authorization","auth")},
}
```

---

## 对齐检查表

### 与 PRD-2026-005 AC 的对齐

| AC | 描述 | 实现 | 测试 | 状态 |
|:--:|:-----|:-----|:----:|:----:|
| AC-01 | JWT Bearer header 在所有 HTTP 请求中传递 | `RuntimeClient.__init__` line 37 | `test_security.py` 8 条 | ✅ |
| AC-02 | `_ensure_auth_headers` 不将 token 写入日志 | `rest.py` line 105-113 | `test_connector.py` 2 条 | ✅ |
| AC-03 | `mask_sensitive(data)` 内置敏感字段列表 | `masking.py` line 11-14 | `test_masking.py` | ✅ |
| AC-04 | 覆盖 Security Spec §3.2 全部 8 个字段 | `masking.py` line 12-13 | `test_masking.py` (参数化) | ⚠️ P0-2 email/phone 格式不符 |
| AC-05 | AUTH_EXPIRED 结构化审计事件 | `base.py` line 76-82 | `test_connector.py` 2 条 | ❌ P0-3 extra 不生效 |

### 与 Security Spec v1.1 的对齐

| 规范要求 | 代码实现 | 状态 |
|:---------|:---------|:----:|
| §2.2 MUST: auth.token 不在日志中出现 | `_ensure_auth_headers` 无 log 调用 | ✅ |
| §2.2 MUST: 凭证 AES-256-GCM 加密存储 | 未实现（Phase 2） | ⏳ 合理延期 |
| §2.2 SHOULD: 凭证不在全局变量中长期持有 | `AuthConfig` dataclass 属性 | ⚠️ 明文，无访问控制 |
| §3.2 MUST: 敏感字段自动脱敏 | `mask_sensitive` 内置字段列表 | ⚠️ P0-2 格式不符 |
| §5.1 MUST: JWT 在每个请求上传递 | `RuntimeClient.__init__` headers | ✅ |
| §6.2 MUST: 认证失败写入审计 | `_on_error` AUTH_EXPIRED 分支 | ❌ P0-3 extra 不生效 |

---

## 评审总结

### 数据统计

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| ❌ P0（必须修复） | 4 | P0-1 Python 3.9 兼容性、P0-2 email/phone 格式、P0-3 audit extra 不生效、P0-4 测试短路 |
| ⚠️ P1（建议修改） | 5 | config 明文、盲重试、错误码语义、mutability 矛盾、测试断言 |
| 💡 P2（优化建议） | 2 | 局部 import、mask 规则扩展性 |

### P0 影响分析

| # | 问题 | 影响 | 修复复杂度 |
|:-:|:-----|:-----|:----------:|
| P0-1 | `StrEnum` 不兼容 Python 3.9 | **阻断性** — 所有 SDK 不可用 | 低（改 1 行） |
| P0-2 | email/phone 脱敏格式 | 不符合 Security Spec §3.2 | 中（新增 mask 函数） |
| P0-3 | audit extra 不生效 | AC-05 未实际达成 | 低（改用 makeRecord） |
| P0-4 | 测试 `or True` 短路 | 掩盖 P0-3 | 低（删掉 or True） |

### 好的方面

- **PRD 对齐度好** — 5 个 AC 均有对应实现和测试，US→AC→代码→测试的追踪链完整
- **`mask_sensitive` 设计合理** — `depth` 参数防止递归炸弹（max 10），大小写不敏感匹配
- **JWT 传递干净** — `RuntimeClient.__init__` 中统一设置一次 header，所有后续请求自动携带
- **`_ensure_auth_headers` 无日志** — token 不会通过 log 泄露，AC-02 达成
- **测试覆盖全面** — 参数化测试 + 递归嵌套 + 深度限制 + 大小写 + 列表嵌套，覆盖面广
- **PRD OOS（不做）明确** — Phase 2/3 的凭证加密、InputGuard/OutputFilter 延迟有记录
