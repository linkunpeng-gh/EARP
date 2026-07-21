# 技术债务清理 — 代码评审

- **日期**: 2026-07-21
- **评审范围**: `git diff HEAD` vs HEAD
- **涉及文件**: 7 文件，+79/-17

---

## 评审摘要

| # | 改动 | 结论 | 严重度 |
|:--|:---|:---|:---|
| 1 | `step_runner.py: batch()` 废弃标注 | PASS | — |
| 2 | `ext_logging.py: CredentialMaskingFilter` 凭证日志脱敏 | **ISSUE** | **P0** |
| 3 | `ext/__init__.py: install()` 挂载点 | PASS | — |
| 4 | `infra/db.py: tenant_session()` 推荐模式文档化 | PASS | — |
| 5 | `tenant_service.py: SET LOCAL → tenant_session()` 示范迁移 | PASS | — |
| 6 | `tech-debt.md` 3 项标记已清偿 | PASS | — |
| 7 | `test_m1_walking_skeleton.py: match 更新` | PASS | — |

---

## ISSUE P0 — CredentialMaskingFilter 第 5 条正则替换会运行时崩溃

**位置**: `apps/earp-server/src/earp_server/infra/ext/ext_logging.py:43`

**问题**: `_SENSITIVE_PATTERNS[4]`（索引 4，即第 5 条规则）使用非捕获分组 `(?:...)` 但替换字符串里引用了 `\1`：

```python
(r'(?i)"(?:api_key|secret|apikey)"\s*:\s*"[^"]*"', r'"\1": "***"'),
```

非捕获分组不产生编号捕获，`\1` 不存在。`re.sub` 在遇到不存在的组引用时抛出 `re.error: invalid group reference 1`。

**触发条件**: 任何入站请求的日志消息在 `logging.Filter.filter()` 处理时，只要消息正文包含 `"api_key":`, `"secret":`, 或 `"apikey":` 任意一种，就会在刷日志的线程里原地崩溃。对生产环境而言这等于一次带日志的文件描述符泄漏和服务降级。

**修复方案**: 将非捕获分组改为捕获分组：

```python
(r'(?i)"(api_key|secret|apikey)"\s*:\s*"[^"]*"', r'"\1": "***"'),
```

如果是刻意不需要保留组引用（即替换为固定字符串），也可以直接写：

```python
(r'(?i)"(?:api_key|secret|apikey)"\s*:\s*"[^"]*"', '"key": "***"'),
```

**验证**: 修复后在目标文件上做一条手工断言即可：

```python
import re
pat = r'(?i)"(api_key|secret|apikey)"\s*:\s*"[^"]*"'
assert re.sub(pat, r'"\1": "***"', '"api_key": "sk-12345"') == '"api_key": "***"'
```

---

## 其余改动逐个 PASS（无 ISSUE）

### `step_runner.py: batch()` 废弃标注（原 #1 技术债务）

- `docstring` 从 `"M7+: parallel batch execution (M5 uses for-loop)"` 改为明确的 `"DEPRECATED since M5"`，指向 `MultiStepExecutor.execute()`。
- `NotImplementedError` 文案同步更新。
- 检测范围验证：`rg '\.batch\('` 返回零条调用点（仅测试里有 `pytest.raises` 的 match 更新），确认接口无隐式消费者。
- 标记 P3 → 已清偿合理。

### `ext/__init__.py: install()` 挂载点

- `init_all()` 末尾调用 `ext_logging.install()`，时序正确：`basicConfig` 先完成根 logger handlers 初始化，之后 filter 挂到 root + `earp_server` logger 上。
- filter 挂两个 logger 是合理的安全设计——即使某个 handler 设置了 `propagate=False`，`earp_server` logger 自身也带 filter。

### `infra/db.py: tenant_session()` 推荐模式文档化

- 模块 docstring 增加了使用范例和为何推荐的理由（"guarantees GUC is set without relying on developer memory"），并诚实标注旧模式仍有效。文档风格与现有代码一致（L3 设计引用、契约约定）。

### `tenant_service.py: SET LOCAL → tenant_session()` 示范迁移

- `add_account_join`: 旧代码使用 `engine.connect()` + f-string `SET LOCAL` + 显式 `conn.commit()`，新代码使用 `tenant_session()` 一把包裹。参数化 GUC set 还修复了一个 SQL 注入风险（旧代码里 `tenant_id` 直接嵌入 SQL 字面量）。
- `get_user_tenants`: 两条路径——有 tenant 上下文时走 `tenant_session()`，无上下文时走 `engine.connect()` 做跨租户管理查询。行为与迁移前完全一致。

### `tech-debt.md` 3 项已清偿标记

- 原 #1（`step_runner.py: batch()`）、#7（`ext_logging.py` 凭证脱敏）、#8（`db.py` + `tenant_service.py` 示范迁移）全部标记为 ✅ 已清偿。
- 附带清理了原第 4/5/6 行的“触发条件”列（对 P3 低优条目来说列值就是原本的"对应功能需求触发时"——这类冗余垂直空间已移除）。

### `test_m1_walking_skeleton.py: match 更新`

- `pytest.raises(NotImplementedError, match=...)` 随 `batch()` 文案同步更新。无其他变更。

---

**最终裁决**: 7 项改动，6 项 PASS。1 项 **P0 阻塞**——要求在 `ext_logging.py` 落地到生产环境前修复，否则 `CredentialMaskingFilter` 会在日志包含 `api_key`/`secret`/`apikey` 的请求路径上崩掉整个 logger 链。
