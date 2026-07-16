# Security Phase 4 — code-review skill 评审报告

## 评审工具：/code-review (high effort, 8 angles, ≤10 findings)

| 字段 | 值 |
|------|-----|
| **评审范围** | 10 个文件变更（4 个 Phase 交叉） |
| **评审角度** | 8 个 finder angles (A–H) |
| **方法** | Phase 0: diff gather → Phase 1: 8-angle scan → Phase 2: dedup |
| **评审人** | code-review skill (high effort) |
| **日期** | 2026-07-15 |
| **发现问题** | 7 个 (0 P0 / 2 高 / 5 低) |

---

## 评审结果

| # | 类别 | 严重度 | 文件:行 | 发现 |
|:--|:-----|:----:|:--------|:-----|
| 1 | correctness | 高 | `base.py:84` | 错误日志去掉了 `ce.message`，丢失诊断上下文——只显示错误码不显示原因文本 |
| 2 | correctness | 高 | `base.py:93` | AUTH_EXPIRED 审计事件中 `tenant_id` 始终为空——`BaseConnector` 无此属性 |
| 3 | simplification | 中 | `sandbox.py:99` | `required_permissions_for_run` 是未在 `Plugin` 基类中定义的隐式约定——不可发现且无测试覆盖 |
| 4 | efficiency | 低 | `guard.py:192` | `text.lower()` 在 system prompt 泄露检测循环中被重复调用 |
| 5 | simplification | 低 | `manager.py:39` | `load_all` 和 `unload_all` 中的审计发布逻辑大量重复——未来变更需同步两处 |
| 6 | simplification | 低 | `base.py:109` | `makeRecord` 使用魔术字符串 `"(unknown file)"` 和 `0` |
| 7 | simplification | 低 | `base.py:65` | `_retry_connect` 中 `ConnectorError` 和通用 `Exception` 两个分支有重复的重试逻辑 |

---

## 各 Finding 详情

### #1 — 错误日志丢失 ce.message（诊断信息缺失）

**严重度**: correctness  
**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:84`  
**角度**: Angle B — removed-behavior auditor

旧日志格式：
```python
logger.error("Non-retryable connector error [%s]: %s (connector=%s)",
              ce.code.value, ce.message, self.connector_id)
```

新日志格式：
```python
logger.error("Non-retryable error [%s] (connector=%s)", ce.code.value, self.connector_id)
```

**问题分析**：

| 信息 | 旧格式 | 新格式 |
|:-----|:-----:|:-----:|
| 错误码 (AUTH_EXPIRED) | ✅ `[AUTH_EXPIRED]` | ✅ `[AUTH_EXPIRED]` |
| 原因文本 (Auth expired) | ✅ `: Auth expired` | ❌ **丢失** |
| Connector ID | ✅ `(connector=xxx)` | ✅ `(connector=xxx)` |

结果：日志中只能看到 `"Non-retryable error [AUTH_EXPIRED] (connector=my-conn)"`，看不到具体的错误原因文本（如 `"Auth expired"` / `"Invalid response"` / `"Token expired"`）。在故障排查时少了一个关键的诊断维度。

---

### #2 — AUTH_EXPIRED 审计事件的 tenant_id 始终为空

**严重度**: correctness  
**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:93`  
**角度**: Angle C — cross-file tracer

```python
publish_audit_event(AuditEvent(
    ...
    tenant_id=getattr(self, "tenant_id", ""),
    ...
))
```

`BaseConnector` 类的属性列表：`connector_id`, `name`, `protocol`, `version`, `status`, `config` — **没有 `tenant_id`**。`getattr(self, "tenant_id", "")` 始终返回 `""`。

**影响**：Audit Spec v1.1 §2.1 要求 `tenant_id` 为 **MUST** 字段。所有 AUTH_EXPIRED 审计事件的 `tenant_id` 永远为空，无法按租户过滤/聚合认证失败事件。

---

### #3 — required_permissions_for_run 隐式约定不可发现

**严重度**: simplification  
**文件**: `libs/earp-sdk-plugin-py/src/earp_sdk_plugin/sandbox.py:99`  
**角度**: Angle C — cross-file tracer

```python
required = getattr(plugin, "required_permissions_for_run", [])
```

- **Plugin 基类**未定义此属性
- **_sandbox_plugins.py** 中所有测试 plugin 也未定义
- 结果：权限预检代码路径**永远不触发**（`getattr` 返回空列表）
- `SandboxManager.run()` 的 AC-05 "权限预检"**无测试覆盖**

---

### #4 — text.lower() 在循环中重复计算

**严重度**: efficiency  
**文件**: `libs/earp-sdk-core-py/src/earp_sdk_core/guard.py:192`  
**角度**: Angle F — efficiency

```python
for phrase in self._prompt_phrases:
    if phrase.lower() in text.lower():  # text.lower() 每次循环重复计算
```

默认 4 个短语，每次 `check()` 调用多做 3 次冗余 `lower()`。建议在循环前计算一次：
```python
text_lower = text.lower()
for phrase in self._prompt_phrases:
    if phrase.lower() in text_lower:
```

---

### #5 — load_all / unload_all 审计逻辑重复

**严重度**: simplification  
**文件**: `libs/earp-sdk-plugin-py/src/earp_sdk_plugin/manager.py:39,62`  
**角度**: Angle E — simplification

`load_all()` 和 `unload_all()` 的成功+失败审计发布逻辑高度相似（仅 `event_type`、`action` 和错误日志格式不同）。如果将来审计事件格式变更，需要同步修改两处，容易遗漏。

---

### #6 — makeRecord 魔术字符串

**严重度**: simplification  
**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:109`  
**角度**: Angle E — simplification

```python
record = logger.makeRecord(
    logger.name, logging.CRITICAL, "(unknown file)", 0,
    "Security audit: AUTH_EXPIRED", (), None,
)
```

`"(unknown file)"` 和 `0` 是硬编码的占位值。日志聚合工具（Sentry、ELK）解析 `fn` 和 `lno` 字段时会显示错误的源码位置，AUTH_EXPIRED 审计 fallback 日志无法定位到真正的触发代码。

---

### #7 — _retry_connect 重试逻辑重复

**严重度**: simplification  
**文件**: `libs/earp-sdk-connector-py/src/earp_sdk_connector/base.py:65`  
**角度**: Angle E — simplification

```python
except ConnectorError as ce:
    if not ce.retryable:
        return False
    if attempt == max_attempts - 1:
        return False
    await asyncio.sleep(2 ** attempt)
except Exception:
    if attempt == max_attempts - 1:
        return False
    await asyncio.sleep(2 ** attempt)
```

两个分支的 `attempt == max_attempts - 1` 和 `asyncio.sleep` 完全一致。抽取统一的 `_should_retry` / `_wait_for_retry` 方法可消除重复。

---

## 与之前手动 review 的对比

| 发现 | 手动 review 已发现? | 说明 |
|:----|:------------------:|:-----|
| #1 ce.message 丢失 | ❌ **新发现** | Angle B (removed-behavior) 发现的遗漏问题 |
| #2 tenant_id 始终为空 | ✅ P1-1 | 手动 review 的 Phase 2 P1-1 |
| #3 required_permissions_for_run | ✅ P2-2 | 手动 review 的 Phase 4 P2-2 |
| #4 text.lower() 重复 | ❌ **新发现** | Angle F (efficiency) 发现的遗漏问题 |
| #5 load/unload 重复 | ❌ **新发现** | Angle E (simplification) 发现的遗漏问题 |
| #6 makeRecord 魔术字符串 | ❌ **新发现** | Angle E (simplification) 发现的遗漏问题 |
| #7 _retry_connect 重复 | ❌ **新发现** | Angle E (simplification) 发现的遗漏问题 |

**对比结论**：code-review skill (8-angle scan) 发现了 **5 个我手动 review 遗漏的问题**（#1, #4, #5, #6, #7），均为 simplification/efficiency 类别。手动 review 发现的 2 个 P1（sanitize 标记替换不一致、stderr 无限制）和 2 个 P2（_SENSITIVE_KEYS import 未使用、PII 覆盖率文档化）skill 未报告——因为 skill 只扫描 git diff 中的已追踪文件，而新模块（guard.py, sandbox.py, credential.py, masking.py）是 untracked 文件。
