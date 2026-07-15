from dataclasses import dataclass, field
from typing import Any

@dataclass
class ConnectorResult:
    status: str = "ok"
    data: Any = None
    error: str | None = None

@dataclass
class ConnectorCapability:
    capability_id: str
    name: str = ""
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
