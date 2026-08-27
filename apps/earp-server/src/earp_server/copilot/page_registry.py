"""Page context registry — each admin config page registers its schema here.

The registry provides field metadata so the Copilot context builder can
assemble a focused prompt without sending raw DOM to the LLM.

IMPORTANT: When adding/modifying fields in admin pages, update this registry!
The Copilot uses these descriptions to explain parameters to users.
See docs/copilot-tasks.md for maintenance guidelines.
"""

from __future__ import annotations

from typing import Any

PAGE_SCHEMAS: dict[str, dict[str, Any]] = {
    "models": {
        "description": "LLM 和 Embedding 模型配置页面。管理模型提供商、凭证、默认模型选择。",
        "fields": {
            "provider": {
                "type": "select",
                "label": "模型提供商 (Provider)",
                "options": ["ollama", "openai", "deepseek", "zhipu", "moonshot"],
                "description": "选择 LLM 服务提供商。Ollama 为本地部署，其他为云端 API。",
            },
            "model_type": {
                "type": "select",
                "label": "模型类型 (Type)",
                "options": ["llm", "embedding", "rerank"],
                "description": "LLM=推理/对话；Embedding=向量化；Rerank=重排序。",
            },
            "model_name": {
                "type": "text",
                "label": "模型名称",
                "description": "具体模型标识，如 qwen3.5:35b、gpt-4o、bge-m3:latest。",
            },
            "api_key": {
                "type": "password",
                "label": "API Key",
                "sensitive": True,
                "description": "云端 API 密钥。本地 Ollama 不需要。",
            },
            "base_url": {
                "type": "text",
                "label": "API Base URL",
                "description": "API 地址。Ollama 默认 http://localhost:11434。",
            },
            "default_llm": {
                "type": "select",
                "label": "默认推理模型",
                "description": "系统默认使用的 LLM。所有 AI 功能（知识库、编排器等）优先使用此模型。",
            },
            "default_embedding": {
                "type": "select",
                "label": "默认嵌入模型",
                "description": "用于知识库向量化的模型。修改后需要重新索引知识库。",
            },
            "default_rerank": {
                "type": "select",
                "label": "默认重排序模型",
                "description": "可选。用于搜索结果重排序，提升检索精度。",
            },
            "qu_prompt_template": {
                "type": "textarea",
                "label": "QU 升级模板",
                "description": (
                    "Query Understanding 升级提示词模板。留空使用内置默认。"
                    "占位符：{query} {missing} {relation_candidates} {context}。"
                ),
            },
        },
        "common_questions": [
            "如何选择 LLM 模型？",
            "Ollama 和 OpenAI 的配置有什么区别？",
            "嵌入模型的作用是什么？",
            "如何测试模型连接是否正常？",
            "QU 升级模板是什么？我需要修改吗？",
        ],
    },
    "knowledge": {
        "description": "知识库管理页面。创建知识库、上传文档、配置分块和检索策略。",
        "fields": {
            "kb_name": {
                "type": "text",
                "label": "知识库名称",
                "description": "知识库的显示名称。",
            },
            "data_domain_id": {
                "type": "select",
                "label": "所属数据域",
                "description": "知识库归属的数据域，用于权限隔离和语义路由。",
            },
            "description": {
                "type": "textarea",
                "label": "描述",
                "description": "知识库的用途说明。",
            },
            "summary_text": {
                "type": "textarea",
                "label": "检索摘要",
                "description": "用于语义路由匹配的摘要。留空则自动聚合文档标题。",
            },
            "indexing_technique": {
                "type": "select",
                "label": "索引技术",
                "options": ["high_quality", "economy"],
                "description": "high_quality=精确分块+向量化；economy=快速索引。",
            },
            "chunk_size": {
                "type": "number",
                "label": "分块大小 (tokens)",
                "description": "每个文本块的最大 token 数。过小丢失上下文，过大降低精度。建议 500-1500。",
            },
            "chunk_overlap": {
                "type": "number",
                "label": "分块重叠 (tokens)",
                "description": "相邻块的重叠 token 数。防止语义断裂。建议为分块大小的 10%-20%。",
            },
            "separator": {
                "type": "text",
                "label": "分隔符",
                "description": "文本分割的优先分隔符。默认 \\n\\n（段落分隔）。",
            },
            "retrieval_mode": {
                "type": "select",
                "label": "检索模式",
                "options": ["vector", "hybrid"],
                "description": "vector=纯向量搜索；hybrid=向量+全文混合（推荐）。",
            },
            "top_k": {
                "type": "number",
                "label": "Top K",
                "description": "返回最相似的 K 个文本块。建议 3-10。",
            },
            "score_threshold": {
                "type": "number",
                "label": "相似度阈值",
                "description": "低于此分数的结果会被过滤。0-1 之间，建议 0.3-0.5。",
            },
        },
        "common_questions": [
            "分块大小和重叠怎么设置？",
            "向量搜索和混合搜索的区别？",
            "如何选择合适的相似度阈值？",
            "知识库和数据域的关系是什么？",
            "上传文档后如何验证检索效果？",
        ],
    },
    "chat-edit": {
        "description": "AI 应用（Chat App）配置页面。配置系统提示词、知识库范围、检索参数、生成参数。",
        "fields": {
            "app_name": {
                "type": "text",
                "label": "应用名称",
                "description": "AI 应用的显示名称。",
            },
            "system_prompt": {
                "type": "textarea",
                "label": "系统提示词",
                "description": "定义 AI 的角色和行为规范。好的提示词应包含：角色、任务、约束、输出格式。",
            },
            "kb_scope": {
                "type": "multi-select",
                "label": "知识库范围",
                "description": "限定 AI 可检索的知识库。不选则自动路由到相关知识库。",
            },
            "retrieval_top_k": {
                "type": "number",
                "label": "检索 Top K",
                "description": "每次对话检索的文本块数量。过多增加延迟，过少可能遗漏。",
            },
            "retrieval_threshold": {
                "type": "number",
                "label": "检索阈值",
                "description": "过滤低相关性结果。过高导致无结果，过低引入噪声。",
            },
            "retrieval_mode": {
                "type": "select",
                "label": "检索模式",
                "options": ["vector", "hybrid"],
                "description": "推荐 hybrid 模式，兼顾语义和关键词匹配。",
            },
            "temperature": {
                "type": "number",
                "label": "温度 (Temperature)",
                "description": "控制生成的随机性。0=确定性，1=创造性。配置类任务建议 0.3。",
            },
            "top_p": {
                "type": "number",
                "label": "Top P",
                "description": "核采样参数。0.9 表示从累积概率 90% 的词中采样。",
            },
            "max_tokens": {
                "type": "number",
                "label": "最大输出长度",
                "description": "单次回复的最大 token 数。根据预期回答长度设置。",
            },
            "context_turns": {
                "type": "number",
                "label": "上下文轮数",
                "description": "保留最近 N 轮对话历史。过多消耗 token，过少丢失上下文。建议 3-5。",
            },
            "model_config_id": {
                "type": "select",
                "label": "模型配置",
                "description": "覆盖默认模型。留空使用系统默认 LLM。",
            },
            "orchestration": {
                "type": "select",
                "label": "编排模式",
                "options": ["auto", "flow"],
                "description": "auto=自动 RAG；flow=可视化工作流编排。",
            },
        },
        "common_questions": [
            "系统提示词怎么写效果好？",
            "温度参数对回答质量有什么影响？",
            "知识库范围怎么选择？",
            "检索参数如何调优？",
            "上下文轮数设多少合适？",
        ],
    },
    "data-domains": {
        "description": "数据域管理页面。定义数据治理边界，配置访问权限和路由描述。",
        "fields": {
            "name": {
                "type": "text",
                "label": "数据域名称",
                "description": "数据域的显示名称，如「客服知识」「产品文档」。",
            },
            "description": {
                "type": "textarea",
                "label": "描述",
                "description": "数据域的用途说明。",
            },
            "data_classification": {
                "type": "select",
                "label": "数据分类",
                "options": ["public", "internal", "confidential", "restricted"],
                "description": "数据安全等级。影响访问权限控制。",
            },
            "owner": {
                "type": "text",
                "label": "负责人",
                "description": "数据域的负责人或团队。",
            },
            "routing_description": {
                "type": "textarea",
                "label": "路由描述",
                "description": "用于语义路由的检索描述（50-150字）。会被向量化后与用户查询匹配。留空可让 AI 自动生成。",
            },
        },
        "common_questions": [
            "数据域的作用是什么？",
            "数据分类等级如何选择？",
            "路由描述怎么写？",
            "数据域和知识库的关系是什么？",
        ],
    },
    "roles": {
        "description": "角色与权限管理页面。创建角色、配置 RBAC 权限和数据域访问范围。",
        "fields": {
            "role_name": {
                "type": "text",
                "label": "角色名称",
                "description": "角色的显示名称。",
            },
            "permissions": {
                "type": "multi-select",
                "label": "权限",
                "description": "角色拥有的操作权限，如 session.create、capability.invoke。",
            },
            "data_domains": {
                "type": "multi-select",
                "label": "数据域访问范围",
                "description": "角色可以访问的数据域。决定了用户能看到哪些知识库。",
            },
        },
        "common_questions": [
            "如何设计合理的角色权限体系？",
            "数据域访问范围的作用是什么？",
            "内置角色有哪些？可以修改吗？",
        ],
    },
    "doc-seg": {
        "description": "文档分段设置页面。配置文档的分段标识符、分段大小、重叠长度等参数，控制文档如何被切分为文本块。",
        "fields": {
            "separators": {
                "type": "text",
                "label": "分段标识符",
                "description": "多个用逗号分隔，按优先级排列，最多5个。如 \\n\\n, \\n, 。 → 先按段落切，切不动降级按行/句号。常见标识符：\\n\\n（段落）、\\n（行）、。（句号）、；（分号）、. （英文句号）。",  # noqa: E501 — 长中文说明
            },
            "max_tokens": {
                "type": "number",
                "label": "分段最大长度（tokens）",
                "description": "每个文本块的最大 token 数。中文约1字符=1token。过小丢失上下文，过大降低检索精度。推荐 500-1500，技术文档可适当增大。",  # noqa: E501 — 长中文说明
            },
            "chunk_overlap": {
                "type": "number",
                "label": "分段重叠长度（tokens）",
                "description": "相邻块的重叠 token 数，防止语义断裂。建议为分段最大长度的 10%-20%。如 max_tokens=1000 时推荐 overlap=100~200。",  # noqa: E501 — 长中文说明
            },
            "remove_extra_spaces": {
                "type": "checkbox",
                "label": "去除多余空格",
                "description": "预处理规则：去除文本中连续多个空格。建议开启，减少噪音。",
            },
        },
        "common_questions": [
            "分段标识符怎么选择？不同文档类型有什么推荐？",
            "分段大小和重叠怎么设置效果最好？",
            "技术文档和普通文档的分段策略有什么区别？",
            "分段后如何验证切块质量？",
            "如何根据文档结构自动推荐分隔符？",
        ],
    },
    "chatflow-edit": {
        "description": "Chatflow 流程编排页面。使用画布式拖拽编排 LLM、知识检索、条件分支、能力调用等节点，构建对话型工作流。",  # noqa: E501 — 长中文说明
        "fields": {
            "app_name": {
                "type": "text",
                "label": "应用名称",
                "description": "Chatflow 智能体的显示名称。",
            },
            "orchestration": {
                "type": "select",
                "label": "编排模式",
                "options": ["flow"],
                "description": "当前为 flow（可视化画布编排）模式。",
            },
            "flow_nodes": {
                "type": "text",
                "label": "流程节点",
                "description": "画布中已添加的节点列表。节点类型：开始、LLM 生成、知识检索、QU 理解、能力调用、工具取数、对话历史、条件分支、人工确认、回答、结束。",  # noqa: E501 — 长中文说明
            },
            "system_prompt": {
                "type": "textarea",
                "label": "系统提示词（LLM 节点）",
                "description": "LLM 节点的系统提示词，定义 AI 角色和行为。可用变量：{{query}}、{{knowledge}}、{{history}} 等。",  # noqa: E501 — 长中文说明
            },
            "knowledge_scope": {
                "type": "multi-select",
                "label": "知识检索范围",
                "description": "知识检索节点可检索的知识库。不选则自动路由。",
            },
            "retrieval_top_k": {
                "type": "number",
                "label": "检索 Top K",
                "description": "知识检索节点每次返回的文本块数量。",
            },
            "temperature": {
                "type": "number",
                "label": "温度（Temperature）",
                "description": "LLM 节点的生成随机性。0=确定性，1=创造性。配置类任务建议 0.3。",
            },
            "max_tokens": {
                "type": "number",
                "label": "最大输出长度",
                "description": "LLM 节点单次回复的最大 token 数。",
            },
        },
        "common_questions": [
            "Chatflow 和普通 Chat 应用有什么区别？",
            "如何设计一个合理的多节点工作流？",
            "条件分支节点怎么配置？",
            "QU 理解节点的作用是什么？什么时候需要用？",
            "LLM 节点的变量 {{query}} {{knowledge}} 怎么用？",
            "人工确认节点在什么场景下使用？",
            "如何调试和测试 Chatflow？",
        ],
    },
}


def get_page_schema(page_id: str) -> dict[str, Any] | None:
    """Return the page schema dict for *page_id*, or None if not registered."""
    return PAGE_SCHEMAS.get(page_id)


def list_pages() -> list[dict[str, Any]]:
    """Return a summary list of all registered pages with common questions."""
    return [
        {
            "page_id": pid,
            "description": schema["description"],
            "common_questions": schema.get("common_questions", []),
        }
        for pid, schema in PAGE_SCHEMAS.items()
    ]
