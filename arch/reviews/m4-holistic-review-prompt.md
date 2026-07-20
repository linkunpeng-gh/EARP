# M4 成果评审 Prompt

> 两刀。M4 规模中等（8 新文件，2 域）。输出 `arch/reviews/m4-holistic-review.md`。

---

## 第 1 刀：核心链路追溯

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M4 Knowledge+Conversation 追溯审计。

评审对象：
- prd/PRD-2026-024-server-m4-knowledge-conversation.md (v1.0, 6 AC)
- apps/earp-server/src/earp_server/knowledge/document_service.py
- apps/earp-server/src/earp_server/knowledge/chunk_service.py
- apps/earp-server/src/earp_server/knowledge/embedding_service.py
- apps/earp-server/src/earp_server/knowledge/search_service.py
- apps/earp-server/src/earp_server/knowledge/record_manager.py
- apps/earp-server/src/earp_server/conversation/conversation_service.py
- apps/earp-server/src/earp_server/main.py (M4 路由段)

逐 AC 判定：
AC-01 '文档上传→document+chunks 写入' → upload_document 端点是否正确调用 create_document→create_chunks→embed_chunks 流水线？chunk_count 断言是否合理？
AC-02 '重复上传→content_hash 匹配→跳过' → is_unchanged 的 content_hash 比较逻辑是否正确？cleanup_old_chunks 是否在 unchanged 时被跳过？
AC-03 '嵌入检索→top_k + accessible_roles 过滤' → search_chunks 的 SQL 是否正确处理 accessible_roles IS NULL OR = '{}' OR role_id = ANY()？Cosine similarity operator <=> 是否正确？
AC-04 'RETRIEVAL_FAILED 事件' → search_chunks 的 except 块是否发布 earp.retrieval.failed CloudEvent？
AC-05 '创建 conversation + POST message → 201; GET → 按序返回' → conversation_service 的 add_message/get_messages 是否正确？
AC-06 '跨租户消息不可见(RLS)' → 所有 DB 操作是否携带 SET LOCAL earp.tenant_id？

架构检查：
- M4 嵌入使用伪随机 1536d（Phase 2 替换）——是否在 embedding_service.py 文件头声明为已知限制？
- langchain-text-splitters 依赖是否正确声明（pyproject.toml + PRD）？
- RecordManager pattern（content_hash MD5 + cleanup_old_chunks）是否对齐 langchain §2.5？

输出：AC 逐条 FULL/PARTIAL/MISSING + P0/P1/P2 + file:line。中文，表格。" > arch/reviews/m4-holistic-review.md 2>&1
```

---

## 第 2 刀：一致性与安全边界

```bash
cd /Users/linkunpeng/work/EARP && codex exec "M4 一致性+安全扫描。

检查项（每项 1 行判定）：

A. 文档上传流水线事务边界：
   - upload_document 是否为每个步骤单独 commit（而非一个事务）？中间失败是否有残留数据？
   - create_document→is_unchanged 在同一 connection 上执行，content_hash 比较是否可见刚 INSERT 的行？

B. SQL 注入面：
   - search_chunks 的 query_embedding 用 f-string 拼接 SQL 值——1621 个浮点数无用户输入，是否安全？
   - knowledge_base_id/document_id/conversation_id 等参数来自 URL path/uuid——是否全部不可注入？

C. accessible_roles RAG 过滤：
   - SQL 中 accessible_roles IS NULL OR = '{}' OR :rid = ANY(accessible_roles) 是否覆盖三种状态（未设/空数组/角色在列表中）？
   - 若 kb.accessible_roles 为 NULL，是否允许所有角色访问？（该行为是否与 RBAC v1.1 §3.4 一致？）

D. 嵌入服务正确性：
   - pseudo-random embedding 是否在每次 embed_query/embed_chunks 产生不同向量（导致相同查询不同结果）？
   - 这属于 M4 documented limitation 还是缺陷？（Phase 2 替换前的一致性影响）

E. Conversation RLS 完整性：
   - add_message 是否正确校验 conversation_id 属于当前 tenant？（RLS SET LOCAL 是否覆盖该路径？）
   - get_messages 的 ORDER BY created_at 是否保证确定顺序？

F. import-linter + main.py：
   - knowledge 和 conversation 模块是否加入 pyproject.toml 的 modules 列表？
   - main.py 从 knowledge 和 conversation 直接 import——这是 controller 层的合法 wire-up 还是违反域独立？

输出：逐项 PASS/ISSUE/NA + P0/P1/P2。中文，表格。" >> arch/reviews/m4-holistic-review.md 2>&1
```

---

## r2 重评模板

```bash
codex exec "Round-2 复核。r1：arch/reviews/m4-holistic-review.md。已修：...。逐项 RESOLVED/NOT-RESOLVED；新 P0/P1 扫描；verdict。中文。" >> arch/reviews/m4-holistic-review-r2.md 2>&1
```
