# 技术债务清理 r2 — P0 正则修复验证

- **日期**: 2026-07-21
- **验证范围**: `git diff HEAD` vs HEAD — P0 regex 修复单项回归检查

---

## P0 修复 — 确认 RESOLVED

**技术债务清理 r1 发现**: `ext_logging.py:43` 使用非捕获分组 `(?:...)` 但替换引用了 `\1`，导致 `re.sub` 运行时崩溃。

**修复**（当前工作树）: 非捕获分组改为捕获分组，`\1` 引用正确。

| 版本 | 正则 | 替换 | 运行结果 |
|:---|:---|:---|:---|
| r1（未修复） | `(?i)"(?:api_key\|secret\|apikey)"...` | `r'"\1": "***"'` | `re.error: invalid group reference 1` |
| **r2（已修复）** | `(?i)"(api_key\|secret\|apikey)"...` | `r'"\1": "***"'` | ✅ 正常替换 |

**手工验证**（Python 3 runtime）:

| 输入 | 输出 | 结果 |
|:---|:---|:---|
| `"api_key": "sk-12345"` | `"api_key": "***"` | ✅ |
| `"secret": "my-secret-value"` | `"secret": "***"` | ✅ |
| `"apikey": "abc123def"` | `"apikey": "***"` | ✅ |
| `"API_KEY": "SHOULD-MASK"` | `"API_KEY": "***"` | ✅（大小写不敏感）|
| `"token": "should-not-match"` | `"token": "should-not-match"` | ✅（负向匹配正确）|

**文件位置**: `apps/earp-server/src/earp_server/infra/ext/ext_logging.py:28`

**源码行**:
```python
(r'(?i)"(api_key|secret|apikey)"\s*:\s*"[^"]*"', r'"\1": "***"'),
```

---

## 其余 6 项改动再确认

以下项目在 r1 评审中为 **PASS**，本次 r2 仅做简要二次确认，无新增 ISSUE:

| # | 位置 | 性质 | 确认状态 |
|:--|:---|:---|:---|
| 1 | `step_runner.py: batch()` 废弃标注 | docstring + exception 文案更新 | ✅ PASS |
| 2 | `ext/__init__.py: install()` 挂载点 | 时序正确，root + earp_server logger 双挂 | ✅ PASS |
| 3 | `infra/db.py: tenant_session()` 推荐模式文档化 | 使用范例 + 理由 + 诚实标注旧模式可用 | ✅ PASS |
| 4 | `tenant_service.py: SET LOCAL → tenant_session()` | 安全参数化 GUC set，修复隐式 SQL 注入 | ✅ PASS |
| 5 | `tech-debt.md` 3 项已清偿标记 | 原 #1/#7/#8 标记正确 | ✅ PASS |
| 6 | `test_m1_walking_skeleton.py: match 更新` | pytest 文案随 batch() 同步 | ✅ PASS |

---

## 最终裁决

| 项目 | 结论 |
|:---|:---|
| P0 正则修复 `(?:…)→(…)` | **RESOLVED** ✅ |
| 其余 6 项 | **PASS** ✅ |
| 合计 7 项 | **7/7 PASS — 无阻塞项** |
