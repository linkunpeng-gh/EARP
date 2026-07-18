# P6 SDK 变更评审

**评审日期：2026-07-17**
**变更文件（6 个模块）：**
| 模块 | 文件 | 新增内容 |
|------|------|----------|
| key_source | `libs/earp-sdk-core-py/.../key_source.py` | VaultSource, FileSource, `_decode` 重构为 @staticmethod |
| feedback | `libs/earp-sdk-core-py/.../feedback.py` | CapabilityFeedback, PlannerFeedback |
| tenant_keys | `libs/earp-sdk-core-py/.../tenant_keys.py` | TenantKeyStore, PerTenantAuthConfig |
| guard | `libs/earp-sdk-core-py/.../guard.py` | summarize_with_llm() |
| conversation | `libs/earp-sdk-core-py/.../conversation.py` | summarize_history() |
| sandbox+grpc_protocol | `libs/earp-sdk-plugin-py/.../` | SandboxConfig.protocol 字段, PluginProtocol, PLUGIN_PROTO_SCHEMA |

---

## P1

### 1. CapabilityFeedback.health_score 偏向未测试 Capability

**文件：** `libs/earp-sdk-core-py/src/earp_sdk_core/feedback.py:34`

**失败场景：**
- 默认值：`success_rate=1.0`，`total_calls=0`，`avg_latency_ms=0.0` → `health_score = 0.7×1.0 + 0.3×1.0 = 1.0`
- 调用 1 次，耗时 1000ms：`health_score = 0.7×1.0 + 0.3×0.5 = 0.85`

**结果：未测试的 Capability（score=1.0）排名高于已测试的 Capability（score=0.85），Planner 会优先选择从未调用过的能力。** 这不合理——从未验证过的 Capability 不应获得完美健康分。

**修复建议：** 默认 `total_calls=0` 时 `health_score` 应低于任何已验证的 Capability，例如设为 `0.0` 或 `None` 由调用方另行处理。

### 2. summarize_history 未导出

**文件：** `libs/earp-sdk-core-py/src/earp_sdk_core/__init__.py`

`conversation.py` 定义的 `summarize_history()` 是一个完整的 pubic API（有 docstring、类型注解），但 `__init__.py` 既不 import 也未加入 `__all__`。其他 5 个模块的新 API 全部正确导出，唯独此函数遗漏，外部 `from earp_sdk_core import summarize_history` 会报 `ImportError`。

### 3. CapabilityFeedback._update_latency 的 p99/p95 跟踪有缺陷

**文件：** `libs/earp-sdk-core-py/src/earp_sdk_core/feedback.py:52-57`

```python
def _update_latency(self, latency_ms: int) -> None:
    ...
    if latency_ms > self.p99_latency_ms:
        self.p99_latency_ms = latency_ms
```

两个问题：
1. **p99 只涨不跌**：首个调用若因冷启动耗时 5000ms，`p99` 永久锁定在 5000ms，后续 10000 次调用都是 10ms 也降不下来。
2. **p95 从未更新**：`p95_latency_ms` 无任何赋值逻辑，永远为 `0.0`，PlannerFeedback 中引用它会产生误导数据。

---

## P2

### 4. SandboxConfig.protocol 字段有定义无消费

**文件：** `libs/earp-sdk-plugin-py/src/earp_sdk_plugin/sandbox.py:43`

`SandboxConfig` 新增 `protocol: str = "json_stdio"`，但 `SandboxManager.run()` **从未读取此字段**。用户设置 `protocol="grpc"` 后沙箱仍走 JSON stdio——无报错无告警，形成静默降级。

### 5. grpc_protocol.py 注释已过时

**文件：** `libs/earp-sdk-plugin-py/src/earp_sdk_plugin/grpc_protocol.py:67-68`

```python
# Extend SandboxConfig with protocol choice
# (Note: modify SandboxConfig in sandbox.py to add `protocol: str = PluginProtocol.JSON_STDIO`)
```

该注释提示"需要修改 SandboxConfig"，但实际上 `sandbox.py` 中 `protocol` 字段已加入。注释应更新为指向已完成的工作。

### 6. TenantKeyStore.resolve("") 静默返回 default key

**文件：** `libs/earp-sdk-core-py/src/earp_sdk_core/tenant_keys.py:36-37`

```python
def resolve(self, tenant_id: str) -> str:
    if not tenant_id:
        return self._default_key  # 静默降级
```

所有 falsy tenant_id（`None`、`""`）静默返回默认 key。多租户环境下若调用方传错参数，会**跨租户使用共享 key**，且无任何告警。建议至少 `logger.warning` 一条安全审计事件。

---

## P3 / 观察

### 7. CapabilityFeedback 的 latency 平均算法有精度丢失

**文件：** `libs/earp-sdk-core-py/src/earp_sdk_core/feedback.py:54`

```python
self.avg_latency_ms = (self.avg_latency_ms * (n - 1) + latency_ms) / n
```

公式正确（Welford 变体），但多线程环境下 `_update_latency` 和 `_recalc` 分开调用且无锁，存在竞态。不过 Python GIL 下对 float 的单次赋值是原子的，生产风险低。标记为 P3。

### 8. VaultSource 每次 get_key() 都新建 hvac.Client

**文件：** `libs/earp-sdk-core-py/src/earp_sdk_core/key_source.py:90`

每次调用 `get_key()` 都执行 `hvac.Client(url=addr, token=token)` 和 `client.is_authenticated()`，高频率访问时会重复建连/认证。实际使用频率低（只在密钥轮换时调用），标记为 P3。

---

## 安全性总评

| 维度 | 结论 |
|------|------|
| 密钥管理 | ✅ VaultSource/FileSource 复用 `_decode()`，32 字节校验一致 |
| 提示注入 | ✅ summarize_with_llm 剥离了 sanitize 包裹后再检查 |
| 多租户 | ⚠️ 空 tenant_id 静默降级为共享 key（P2-6） |
| 审计 | ✅ VaultSource、summarize_with_llm 异常路径有审计事件 |
| 输出过滤 | ✅ OutputFilter 未变更，保持不变 |

---

## 总结

| 级别 | 数量 | 关键项 |
|:----:|:----:|:------|
| P1 | 3 | health_score 偏向未测试 cap、summarize_history 未导出、p99 单调不降 + p95 从未更新 |
| P2 | 4 | protocol 字段未消费、grpc_protocol 注释过时、TenantKeyStore 空 tenant 静默降级、latency 算法精度 |
| P3 | 2 | 竞态风险、VaultSource 重用优化 |

**建议：** 3 个 P1 均影响核心功能正确性（feedback 误导 Planner、API 不可发现、p95 返回错误数据），建议修复后再合入。
