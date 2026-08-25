"""Context builder — assembles LLM prompt context from page schema + form state + KB retrieval.

The context builder is the security boundary: it decides what the LLM can see.
Sensitive fields are stripped, tenant scoping is enforced, and the prompt is
structured to keep the model focused on configuration assistance.
"""

from __future__ import annotations

import logging
from typing import Any

from earp_server.copilot.page_registry import get_page_schema

logger = logging.getLogger(__name__)

# ── System prompts ──

_SYSTEM_EXPLAIN = (
    "你是 EARP 平台的配置助手。你的任务是帮助管理员理解配置页面上的参数含义、"
    "取值范围和最佳实践。\n\n"
    "规则：\n"
    "1. 用简洁的中文回答，直接解释参数用途\n"
    "2. 结合知识库中的平台文档给出具体建议\n"
    "3. 如果知识库中有相关配置示例，给出推荐值\n"
    "4. 不要编造不确定的信息，如果不确定就说不确定\n"
    "5. 输出格式：直接回答，不要前缀"
)

_SYSTEM_DIAGNOSE = (
    "你是 EARP 平台的配置诊断专家。你的任务是分析管理员当前的配置状态，"
    "指出潜在问题并给出修复建议。\n\n"
    "规则：\n"
    "1. 逐项检查配置参数，指出不合理的值\n"
    "2. 检查配置项之间的兼容性（如模型类型与用途是否匹配）\n"
    "3. 给出具体的修复建议和推荐值\n"
    "4. 如果配置没有问题，明确告知「当前配置合理」\n"
    "5. 输出格式：用编号列出检查项，每项包含【状态】和【建议】"
)

_SYSTEM_SUGGEST = (
    "你是 EARP 平台的配置优化顾问。你的任务是根据管理员的描述和当前配置，"
    "给出优化建议。\n\n"
    "规则：\n"
    "1. 结合知识库中的最佳实践给出建议\n"
    "2. 说明每项优化的原因和预期效果\n"
    "3. 如果当前配置已经是最佳状态，明确告知\n"
    "4. 输出格式：用编号列出建议，每项包含【建议】【原因】【预期效果】"
)

_SYSTEM_AUTOFILL = (
    "你是 EARP 平台的智能配置填充助手。你的任务是根据当前页面上下文和用户描述，"
    "为表单字段生成推荐值。\n\n"
    "规则：\n"
    "1. 仔细分析当前已填写的字段，保持合理的已有配置\n"
    "2. 为每个需要填写或优化的字段给出推荐值\n"
    "3. 每个建议必须包含置信度（0-1）和简短理由\n"
    "4. 不要修改用户已明确设置的字段，除非明显错误\n"
    "5. 敏感字段（如 api_key）不要给出具体值，仅提示需要填写\n"
    "6. 输出格式：严格输出 JSON 数组，不要包含任何其他文本\n\n"
    "JSON 格式：\n"
    '[{"field": "字段名", "value": "推荐值", "confidence": 0.9, "reason": "推荐理由"}]\n\n'
    "字段名必须与页面参数说明中的字段名一致。"
)

_SYSTEM_APPLY = (
    "你是 EARP 平台的一键配置助手。根据管理员的场景描述，为当前页面的所有字段生成完整配置方案。\n\n"
    "规则：\n"
    "1. 必须为页面中的每个字段都给出值，不要遗漏任何字段\n"
    "2. 敏感字段（如 api_key）用 placeholder 代替，不要给出真实值\n"
    "3. 根据场景需求合理设置每个参数，参考知识库中的最佳实践\n"
    "4. 保持当前已填写的合理配置，不要无故修改\n"
    "5. 输出格式：严格输出 JSON 对象，不要包含任何其他文本\n\n"
    "JSON 格式：\n"
    '{"fields": {"字段名": "值", ...}, "explanation": "配置方案说明"}\n\n'
    'fields 必须包含页面参数说明中的所有字段（敏感字段值填 "__PLACEHOLDER__"）。'
    "explanation 用 2-3 句话说明整体配置思路。"
)

_INTENT_SYSTEM_PROMPTS = {
    "explain": _SYSTEM_EXPLAIN,
    "diagnose": _SYSTEM_DIAGNOSE,
    "suggest": _SYSTEM_SUGGEST,
    "autofill": _SYSTEM_AUTOFILL,
    "apply": _SYSTEM_APPLY,
}


def _sensitive_fields(schema: dict[str, Any]) -> set[str]:
    """Return field names marked as sensitive (should not be sent to LLM)."""
    return {fname for fname, meta in schema.get("fields", {}).items() if meta.get("sensitive")}


def build_copilot_context(
    page_id: str,
    form_state: dict[str, Any],
    query: str,
    intent: str,
    kb_context: str = "",
) -> dict[str, Any]:
    """Build the full context dict for the copilot LLM call.

    Returns:
        {
            "system_prompt": str,
            "user_prompt": str,
            "page_description": str,
        }
    """
    schema = get_page_schema(page_id)
    if schema is None:
        logger.warning("build_copilot_context: unknown page_id=%r", page_id)
        return {
            "system_prompt": _INTENT_SYSTEM_PROMPTS.get(intent, _SYSTEM_EXPLAIN),
            "user_prompt": query,
            "page_description": f"未知页面: {page_id}",
        }

    # Strip sensitive fields from form_state before including in prompt
    sensitive = _sensitive_fields(schema)
    safe_form_state = {k: v for k, v in form_state.items() if k not in sensitive and v is not None and v != ""}

    # Build field descriptions for the prompt
    field_desc_lines: list[str] = []
    for fname, fmeta in schema["fields"].items():
        if fname in sensitive:
            continue
        desc = fmeta.get("description", "")
        ftype = fmeta.get("type", "")
        label = fmeta.get("label", fname)
        opts = fmeta.get("options")
        line = f"- {label} ({fname}, {ftype}): {desc}"
        if opts:
            line += f" 可选值: {', '.join(str(o) for o in opts)}"
        field_desc_lines.append(line)

    field_desc = "\n".join(field_desc_lines)

    # Format current values
    if safe_form_state:
        current_values = "\n".join(f"  {k}: {v}" for k, v in safe_form_state.items())
        current_values_block = f"\n当前配置值：\n{current_values}"
    else:
        current_values_block = "\n当前配置值：（表单为空，可能处于新建状态）"

    # Knowledge base context
    kb_block = ""
    if kb_context:
        kb_block = f"\n\n相关知识库参考：\n{kb_context}"

    # Assemble user prompt — for autofill/apply, include all fields for comprehensive suggestions
    if intent == "autofill":
        user_prompt = (
            f"页面：{schema['description']}\n\n"
            f"页面参数说明：\n{field_desc}"
            f"{current_values_block}"
            f"{kb_block}\n\n"
            f"用户请求：{query}\n\n"
            f"请为上述字段生成推荐值，输出严格 JSON 数组格式。"
        )
    elif intent == "apply":
        user_prompt = (
            f"页面：{schema['description']}\n\n"
            f"页面参数说明：\n{field_desc}"
            f"{current_values_block}"
            f"{kb_block}\n\n"
            f"用户场景：{query}\n\n"
            f"请为上述所有字段生成完整配置方案，输出严格 JSON 对象格式。"
            f'注意：必须为每个字段都给出值，不要遗漏。敏感字段值填 "__PLACEHOLDER__"。'
        )
    else:
        user_prompt = (
            f"页面：{schema['description']}\n\n"
            f"页面参数说明：\n{field_desc}"
            f"{current_values_block}"
            f"{kb_block}\n\n"
            f"用户问题：{query}"
        )

    system_prompt = _INTENT_SYSTEM_PROMPTS.get(intent, _SYSTEM_EXPLAIN)

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "page_description": schema["description"],
    }


def format_kb_results(results: list[dict[str, Any]]) -> str:
    """Format knowledge base search results into a readable string for the prompt."""
    if not results:
        return ""

    parts: list[str] = []
    for i, r in enumerate(results[:5], 1):  # limit to top 5
        title = r.get("title", "")
        content = r.get("content", "")
        # Truncate long content
        if len(content) > 500:
            content = content[:500] + "..."
        kb_name = r.get("knowledge_base_name", "")
        source = f" [{kb_name}]" if kb_name else ""
        parts.append(f"{i}. {title}{source}\n   {content}")

    return "\n\n".join(parts)
