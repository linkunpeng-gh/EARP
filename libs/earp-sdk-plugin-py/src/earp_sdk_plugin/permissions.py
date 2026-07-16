from enum import Enum
from earp_sdk_core import PermissionDeniedError


class Permission(str, Enum):
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    LLM_CALL = "llm_call"


class PermissionEnforcer:
    """Check plugin permissions before executing operations.

    Phase 4 provides declaration-level enforcement — callers must
    explicitly call ensure() before performing restricted operations.
    System-call-level automatic enforcement (seccomp/WASM) is deferred to Phase 5+.
    """

    def __init__(self, plugin) -> None:
        self._plugin = plugin
        self._declared = set(plugin.permissions) if plugin.permissions else set()

    def ensure(self, permission: str) -> None:
        """Raise PermissionDeniedError if permission is not declared."""
        if permission not in self._declared:
            raise PermissionDeniedError(
                message=f"Plugin '{getattr(self._plugin, 'name', 'unknown')}' "
                        f"has not declared permission '{permission}'"
            )

    def ensure_all(self, permissions: list[str]) -> None:
        """Raise on first undeclared permission."""
        for perm in permissions:
            self.ensure(perm)
