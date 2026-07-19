# PRD-2026-027 v1.0

## M7 — 隔离与生态

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-027 |
| **Feature** | Plugin 安装五段流程 + MCP Server 骨架 + 出口管控 |
| **里程碑** | M7（依赖 M6 EventBus） |
| **PRD 链** | ← PRD-2026-026(M6) |

---

## 1. 范围表

| # | 域 | 功能 |
|:--|:---|:-----|
| 1 | Plugin | 安装五段流程：download(URL→本地)/verify(sha256)/unpack(zip)/register(DB write)/health_check(HTTP 200) |
| 2 | Plugin | PluginManager：管理已安装 plugin 的生命周期 |
| 3 | MCP | MCP Server 骨架：POST /mcp/tools — JSON-RPC 2.0 protocol，echo tool |
| 4 | Egress | Egress 出口管控：connector 调用前检查 allowed_domains 白名单 |

---

## 2. AC

| AC | 内容 |
|:--:|:-----|
| AC-01 | Plugin 安装五段流程依次执行，任一段失败→rollback 已执行段 |
| AC-02 | MCP /mcp/tools 端点返回 tools/list JSON-RPC 格式 |
| AC-03 | Connector 调用前检查域名白名单，不在名单→拒绝 |

---

## 3. Gate

| # | 检查项 | 状态 |
|:--|:-----|:----:|
| 1 | 依赖明确 | ✅ |
| 2 | AC 可测试 | ✅ 3 条 |
