"""Multi-turn conversation context summarization — Conversation Spec §3.1.

When conversation history exceeds the LLM context window, summarize
older messages to preserve conversation coherence while staying within
token limits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Awaitable

if TYPE_CHECKING:
    pass  # dataclass types only


async def summarize_history(
    messages: list[dict],
    llm_summarize: Callable[[str], Awaitable[str]],
    *,
    max_messages: int = 20,
    keep_last: int = 5,
) -> str | None:
    """Summarize older conversation messages when history is long.

    Strategy:
      1. If total messages ≤ max_messages, no summarization needed
      2. Otherwise: summarize messages [0 : -keep_last]
      3. Return the summary string (or None if no summarization needed)

    Args:
        messages: List of {"role": "user"|"assistant", "content": "..."} dicts.
        llm_summarize: Async callback(text) → summary string.
        max_messages: Threshold — summarize if > this many messages.
        keep_last: Keep the most recent N messages unsummarized.

    Returns:
        Summary string, or None if history is short enough.
    """
    if len(messages) <= max_messages:
        return None

    # Build context from older messages
    older = messages[:-keep_last]
    context = "\n".join(
        f"[{m.get('role', 'user')}]: {m.get('content', '')}" for m in older
    )

    try:
        prompt = (
            "Summarize the following conversation history in 2-3 sentences. "
            "Preserve key facts, decisions, and unresolved questions:\n\n"
            f"{context}"
        )
        summary = await llm_summarize(prompt)
        return f"[Conversation summary ({len(older)} messages)]: {summary}"
    except Exception:
        return None
