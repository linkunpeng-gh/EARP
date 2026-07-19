"""Session API schemas - aligned with runtime-py client.py (AC-08).

role_id authority: Tenant Spec v1.2 section 5.4 (+ RBAC design v1.1).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    role_id: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    status: str = "active"
