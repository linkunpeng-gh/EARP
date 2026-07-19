"""Rule Intent Planner — Business Dictionary exact-match intent resolution.

M3 minimal: a static dictionary of intent→capability mappings.
M4+ extends with embeddings-based semantic matching (pgvector).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Business Dictionary ───────────────────────────────────────────────────────
# Intent → Capability mapping. Extensible at runtime (M4+ via API).
_BUSINESS_DICTIONARY: dict[str, dict[str, Any]] = {
    "query users": {
        "capability_id": "cap-query-users",
        "description": "Query user list",
        "input_template": {"action": "list", "entity": "users"},
    },
    "create alarm": {
        "capability_id": "cap-create-alarm",
        "description": "Create a new alarm",
        "input_template": {"action": "create", "entity": "alarm"},
    },
    "query alarms": {
        "capability_id": "cap-query-alarms",
        "description": "Query alarm list",
        "input_template": {"action": "list", "entity": "alarms"},
    },
    "echo": {
        "capability_id": "cap-demo-echo",
        "description": "Echo demo capability",
        "input_template": {"message": "hello"},
    },
}


@dataclass
class IntentMatch:
    intent: str
    capability_id: str
    input: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # exact match = 1.0; M4+ supports fuzzy


class RuleIntentPlanner:
    """Resolve user intent to a capability call via Business Dictionary exact match."""

    def resolve(self, intent: str) -> IntentMatch | None:
        entry = _BUSINESS_DICTIONARY.get(intent.lower().strip())
        if entry is None:
            return None
        return IntentMatch(
            intent=intent,
            capability_id=entry["capability_id"],
            input=dict(entry.get("input_template", {})),
        )

    def list_intents(self) -> list[str]:
        return list(_BUSINESS_DICTIONARY.keys())
