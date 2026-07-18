"""Conversation management — Conversation Spec v1.0.

Data models: Conversation, Message
Management: ConversationStore (create, add_message, archive, list)
Context: ContextBuilder (LLM context window construction)
Summarization: summarize_history (multi-turn overflow)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Awaitable


# ── Data Models ──

class ConversationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass
class Message:
    """Single message within a conversation. Role: user|assistant|system|tool."""
    message_id: str = ""
    conversation_id: str = ""
    role: str = "user"
    content: str = ""
    seq: int = 0
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Conversation:
    """Multi-turn conversation container. Conversation Spec §2.1."""
    conversation_id: str = ""
    tenant_id: str = ""
    user_id: str = ""
    title: str = ""
    status: ConversationStatus = ConversationStatus.ACTIVE
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""

    @property
    def message_count(self) -> int:
        return len(self.messages)


# ── Conversation Store ──

class ConversationStore:
    """In-memory conversation store. Replace with DB-backed impl in production."""

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}

    def create(self, conv_id: str, tenant_id: str, user_id: str, title: str = "") -> Conversation:
        conv = Conversation(conversation_id=conv_id, tenant_id=tenant_id, user_id=user_id, title=title)
        self._conversations[conv_id] = conv
        return conv

    def get(self, conv_id: str) -> Conversation | None:
        return self._conversations.get(conv_id)

    def add_message(self, conv_id: str, role: str, content: str, **meta) -> Message | None:
        conv = self._conversations.get(conv_id)
        if not conv or conv.status != ConversationStatus.ACTIVE:
            return None
        msg = Message(
            message_id=f"{conv_id}-msg-{conv.message_count + 1}",
            conversation_id=conv_id,
            role=role,
            content=content,
            seq=conv.message_count + 1,
            metadata=meta,
        )
        conv.messages.append(msg)
        conv.updated_at = msg.created_at
        return msg

    def archive(self, conv_id: str) -> bool:
        conv = self._conversations.get(conv_id)
        if conv:
            conv.status = ConversationStatus.ARCHIVED
            return True
        return False

    def list_active(self, tenant_id: str) -> list[Conversation]:
        return [c for c in self._conversations.values()
                if c.tenant_id == tenant_id and c.status == ConversationStatus.ACTIVE]


# ── Context Builder ──

class ContextBuilder:
    """Build LLM context window from conversation history. Conversation Spec §3.1."""

    def __init__(self, max_messages: int = 20, max_tokens: int = 8000):
        self.max_messages = max_messages
        self.max_tokens = max_tokens

    def build(self, conversation: Conversation, system_prompt: str = "",
              variables: dict[str, str] | None = None) -> list[dict]:
        """Build context messages for LLM call, respecting max_tokens limit."""
        messages: list[dict] = []
        token_budget = self.max_tokens

        if system_prompt:
            # Variable substitution: {{user_name}}, {{tenant_name}}, {{current_time}}
            if variables:
                for key, val in variables.items():
                    system_prompt = system_prompt.replace(f"{{{{{key}}}}}", str(val))
            sys_tokens = self._estimate_tokens(system_prompt)
            messages.append({"role": "system", "content": system_prompt})
            token_budget -= sys_tokens

        # Take messages from newest to oldest until token budget exhausted
        recent = list(reversed(conversation.messages[-self.max_messages:]))
        for msg in recent:
            est = self._estimate_tokens(msg.content)
            if est > token_budget:
                break
            messages.insert(1, {"role": msg.role, "content": msg.content})  # after system
            token_budget -= est

        return messages

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation: ~4 chars/token for English, ~1.5 for CJK."""
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        ascii_chars = len(text) - cjk
        return ascii_chars // 4 + int(cjk * 1.5)

    def build_with_summary(
        self,
        conversation: Conversation,
        summary: str | None,
        system_prompt: str = "",
    ) -> list[dict]:
        """Build context with summary prefix for truncated history."""
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if summary:
            messages.append({"role": "system", "content": summary})
        recent = conversation.messages[-self.max_messages:]
        for msg in recent:
            messages.append({"role": msg.role, "content": msg.content})
        return messages


# ── Summarization ──

async def summarize_history(
    messages: list[dict],
    llm_summarize: Callable[[str], Awaitable[str]],
    *,
    max_messages: int = 20,
    keep_last: int = 5,
) -> str | None:
    """Summarize older conversation messages when history is long."""
    if len(messages) <= max_messages:
        return None
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
