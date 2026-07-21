# PRD-2026-018 v1.0

## Knowledge Base — 数据模型层

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-018 |
| **Feature** | KnowledgeBase/Document/Chunk 核心数据模型（对齐数据视图 Knowledge 域 + Dify rag/models/） |
| **优先级** | **P1** |
| **版本** | v1.0 |

---

## 1. 背景

数据视图已定义 Knowledge 域（KnowledgeBase → Document → Chunk 1:N:N），但 SDK 层无任何代码。Dify 的 `core/rag/models/` 提供可直接参考的数据模型。

## 2. 范围

| 模型 | 字段 | Dify 对应 |
|:-----|:-----|:---------|
| `KnowledgeBase` | kb_id, tenant_id, name, description, data_domain_id | `Dataset` |
| `Document` | doc_id, kb_id, title, format, status(processing/ready/error), chunk_count | `Document` |
| `Chunk` | chunk_id, doc_id, content, embedding(list[float]), metadata | `Segment` |
| `ChunkWithScore` | chunk: Chunk, score: float | (retrieval result) |

## 3. 验收条件

| ID | 描述 |
|:--:|:-----|
| AC-01 | 4 个 dataclass 创建在 `earp-sdk-core/src/earp_sdk_core/knowledge.py` |
| AC-02 | 对齐数据视图 entity 定义 + 含 tenant_id 字段 |
| AC-03 | `ChunkWithScore` 支持排序（score 降序） |
| AC-04 | 现有 104 tests 无回归 |
| AC-05 | `KnowledgeBase.data_domain_id` 字段存在，可为 None（未分配 DD 的 KB 仍可检索） |

## 4. 产出物

- `earp-sdk-core-py/src/earp_sdk_core/knowledge.py` (新建, ~50 行)
- `__init__.py` 导出
