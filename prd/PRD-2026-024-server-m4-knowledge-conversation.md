# PRD-2026-024 v1.0

## M4 — Knowledge Base + Conversation

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-024 |
| **Feature** | Knowledge Base: Document/Chunk 入库 + pgvector 检索 + Data Domain 过滤 + accessible_roles RAG 过滤 + RecordManager 增量索引; Conversation: 会话消息/摘要 |
| **里程碑** | M4 (依赖 M2 PolicyLayer + M0 DDL) |
| **上游设计** | RBAC v1.1 §3.4; langchain-earp-mapping §2.5(RecordManager) §2.6(text-splitters) |
| **PRD 链** | ← PRD-2026-023(M3) |

---

## 1. 范围表

| # | 域 | 功能 |
|:--|:---|:-----|
| 1 | KB | Document 入库: POST /knowledge/documents（创建文档，含 data_classification 字段）
- `PUT /knowledge/documents/{doc_id}`（更新文档信息，含 data_classification——需验证 ≤ 所属域天花板。降级操作写入审计事件） — 创建 document 行(knowledge_base_id/content/data_classification)。
  classification 约束：document.data_classification ≤ data_domain.data_classification（文档等级不能超过所属域的天花板）。违反时返回 422 |
| 2 | KB | Chunk 分块: langchain-text-splitters(MIT依赖), RecursiveCharacterTextSplitter, chunk_size=1000/overlap=200 |
| 3 | KB | Chunk 嵌入: pgvector embedding(1536d), INSERT chunks 行(embedding+document_id+content) |
| 4 | KB | pgvector 检索: POST /knowledge/search — text→embedding→cosine_similarity→top_k=5
  + Data Domain 过滤（WHERE knowledge_bases.data_domain_id IN ? OR knowledge_bases.data_domain_id IS NULL——未分配 DD 的 KB 仍可检索）
  + 文档级 data_classification ≤ 角色 max_classification（max_classification 从 Role.data_domain_access 中该域的字段取值）
  + accessible_roles 过滤（向后兼容）|
| 5 | KB | RecordManager 增量索引: content_hash 去重(MD5), 旧 chunk 清理(incremental 模式) |
| 6 | KB | RETRIEVAL_FAILED 事件(检索异常→stderr+audit) |
| 7 | Conv | Conversation: POST /conversations — 创建 messages 行(role/content/created_at), 摘要生成 |
| 8 | Conv | 消息管理: GET /conversations/{id}/messages — 分页, 租户+角色隔离 |

---

## 2. US

| US | 描述 |
|:--:|:-----|
| US-01 | 上传文档(kb_id+"hello world")→document 行→chunk 分块→embedding→chunks 行 3 条写入 |
| US-02 | 同文档二次上传→content_hash 匹配→跳过(RecordManager 去重) |
| US-03 | text="用户查询"→embedding→cosine_similarity→top_k chunks, 角色无权限的 kb 被过滤 |
| US-04 | 检索异常(embedding 服务不可用)→RETRIEVAL_FAILED 事件+stderr |
| US-05 | 创建 conversation→POST messages(role=user, content="hello")→201 |
| US-06 | GET /conversations/{id}/messages→按创建时间顺序返回, RLS 隔离 |
| US-07 | 上传文档时 data_classification 超过所属域天花板→422 拒绝 |
| US-08 | 修改文档 classification（如 confidential → internal）→ PUT 200 + 审计事件记录降级操作。修改后角色 max_classification="internal" 的用户可以看到该文档 |, 不写入 documents 表 |

---

## 3. AC

| AC | 内容 | 验证 |
|:--:|:-----|:----|
| AC-01 | 文档上传→document+chunks 行写入, chunk_count = ceil(len(content)/chunk_size) | pytest |
| AC-02 | 重复上传→content_hash 匹配→0 新 chunk 写入 | pytest |
| AC-03 | 嵌入检索→top_k chunks 返回, accessible_roles 过滤生效 | pytest |
| AC-04 | RETRIEVAL_FAILED 事件含 error message | pytest |
| AC-05 | 创建 conversation→POST message→201; GET→按序返回 | pytest |
| AC-06 | 跨租户消息不可见(RLS) | pytest |
| AC-09 | 修改文档 classification 后重新检索→新等级下的角色可见性生效（如: internal→confidential 后 max=internal 的角色不再返回该文档） | pytest |
| AC-08 | 文档 classification 过滤：设备工程师角色对 equipment_data 域的 max_classification="internal" → 搜索时只返回该域下 internal(含)以下的文档, confidential 文档被静默过滤 | pytest |
| AC-07 | Data Domain 过滤生效：角色 R1 只对 equipment_data 域有权限 → 跨域查询时只返回该域的 chunks（未分配 DD 的 KB 不受影响） | pytest |

---

## 4. 依赖

| 依赖 | 来源 | M4 引用 |
|:-----|:-----|:------|
| langchain-text-splitters | MIT, 33KB, PyPI | chunk 分块 |
| pgvector | M0 DDL 已建 extension | embedding 存储+检索 |
| knowledge_bases/documents/chunks 表 | M0 DDL | CRUD |
| conversations/messages 表 | M0 DDL | CRUD |
| accessible_roles 字段 | RBAC v1.1 §3.4 | RAG 过滤 |

---

## 5. 对齐

| 规范 | 条款 | 对齐 |
|:-----|:-----|:----:|
| RBAC v1.1 §3.4 | accessible_roles RAG 过滤 | ✅ |
| langchain-earp-mapping §2.5 | RecordManager 增量索引(content_hash+incremental) | ✅ |
| langchain-earp-mapping §2.6 | text-splitters MIT 依赖 | ✅ |
| EventBus Spec v1.1 | RETRIEVAL_FAILED 事件类型 | ✅ |

---

## 6. Gate

| # | 检查项 | 状态 |
|:--|:-----|:----:|
| 1 | 依赖明确 | ✅ 5 项 |
| 2 | AC 可测试 | ✅ 6 条 |
| 3 | M0/M1/M2/M3 遗留 0 | ✅ |
| 4 | 与冻结规范无矛盾 | ✅ |
