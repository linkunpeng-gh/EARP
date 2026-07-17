Permission allow rule (.claude/settings.local.json): Write(/Users/linkunpeng/work/adp2/**) is not matched by file permission checks — only Edit(path) rules are. Use Edit(/Users/linkunpeng/work/adp2/**) instead (Edit rules cover all file-editing tools).
## 审查结论：无 P0

逐一核对 AC-01~04，均满足。下面是细节：

### AC-01 ✅ 6图完整
图1-6覆盖全部6条交互链，组件角色、消息方向清晰标注。

### AC-02 ✅ 核心执行流完整
图1串联了 JWT→Session→Plan→Capability→Connector→External→返回 全链路。

### AC-03 ✅ 每图≥1审计点
文档自检表准确。图2的 SESSION_CREATED/CLOSED 算运营审计事件，如果严格按 PRD 括号里的"Audit Spec §6.2 安全事件"抠字眼可能有争议，但实际不构成问题。

### AC-04 ✅ 规范一致性
图3对齐 Security §5.1，图4对齐 Security §4，图5对齐 Security §7，图6对齐 Audit §6。

---

### P1 建议（2处）

**1. 图4 第155行发送方歧义**

```
│              │                   │──check(output)▶│              │          │
```

从列位置看，`check(output)` 的箭头起点落在 LLM Provider 列（第3列），像是 LLM Provider 直接调 OutputFilter，这不合理——应该是 Gateway 收到 response 后转发给 OutputFilter。实际是 ASCII 排版偏移，建议把 `check(output)` 的文字向左移动，让箭头起点对齐 Gateway 列。

**2. 图3 JWT 验证箭头方向**

```
│          │─验证签名──────────▶│                 │
```

Gateway → Runtime 画成跨组件消息，如果 Gateway 独立持有 RS256 公钥完成验证（Security Spec 的设计），这个应该是自箭头或本地标注。图1也有同样画法。建议统一为 Gateway 内部自循环箭头，避免误读为"Gateway 不做验证，透传给 Runtime 验证"。

### P2（nice to have）

- 图1只有 happy path，Policy 返回 deny 后的 403 分支没有画出来（图3补充了这部分，但图1作为"核心执行流"缺少分支）。
- 图4 OutputFilter → Capability 之间缺少 Gateway/Runtime 的"确认安全后放行"决策环节，直接画成了 OutputFilter 调 Capability。
