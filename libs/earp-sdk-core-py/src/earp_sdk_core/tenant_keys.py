"""Multi-tenant LLM API key management — Security Spec §4.4.

Per-tenant API key isolation ensures one tenant's LLM usage
does not consume another's quota or expose their credentials.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class TenantKeyStore:
    """Resolve LLM API keys by tenant_id.

    Key sources (highest priority first):
      1. Explicit key map passed to constructor
      2. Environment variables: EARP_LLM_KEY_{TENANT_ID_UPPER}
      3. Fallback: default_key (shared key, for non-production)

    Usage:
        store = TenantKeyStore(default_key="sk-default")
        store.add_key("t1", "sk-tenant-1")
        key = store.resolve("t1")  # → "sk-tenant-1"
        key = store.resolve("t2")  # → "sk-default" (fallback)
    """

    def __init__(self, default_key: str = "") -> None:
        self._keys: dict[str, str] = {}
        self._default_key = default_key

    def add_key(self, tenant_id: str, api_key: str) -> None:
        self._keys[tenant_id] = api_key

    def resolve(self, tenant_id: str) -> str:
        if not tenant_id:
            logger.warning("TenantKeyStore.resolve() called with empty tenant_id — using default key")
            return self._default_key

        # 1. Explicit key map
        if tenant_id in self._keys:
            return self._keys[tenant_id]

        # 2. Environment variable (EARP_LLM_KEY_T1 → sk-xxx)
        env_key = os.environ.get(f"EARP_LLM_KEY_{tenant_id.upper()}")
        if env_key:
            return env_key

        # 3. Fallback to default
        return self._default_key

    def has_tenant_key(self, tenant_id: str) -> bool:
        return tenant_id in self._keys or f"EARP_LLM_KEY_{tenant_id.upper()}" in os.environ


@dataclass
class PerTenantAuthConfig:
    """Connector auth config with per-tenant key support.

    When tenant_id is set on the connector, resolve() returns
    the tenant-specific key if available, otherwise the default.
    """

    default_token: str = field(default="", repr=False)
    tenant_keys: TenantKeyStore = field(default_factory=TenantKeyStore)

    def resolve(self, tenant_id: str) -> str:
        if not tenant_id:
            return self.default_token
        tenant_key = self.tenant_keys.resolve(tenant_id)
        return tenant_key if tenant_key else self.default_token
