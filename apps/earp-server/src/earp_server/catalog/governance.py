"""Catalog Phase 1 authorization and separation-of-duties guards."""

from __future__ import annotations


class CatalogAuthorizationError(PermissionError):
    """A Catalog governance action is not permitted."""


def assert_approval_separation(*, requester_id: str, approver_id: str) -> None:
    """SoD is based on immutable user identity, never role/display name."""
    if requester_id == approver_id:
        raise CatalogAuthorizationError("requester cannot approve their own Catalog change")


def assert_pack_export_allowed(*, owner_role: str, actor_role: str, is_platform_admin: bool) -> None:
    """Pack export is restricted because canonical inputs can be sensitive."""
    if not is_platform_admin and actor_role != owner_role:
        raise CatalogAuthorizationError("only the Pack owner or a platform admin may export a Pack")


def assert_break_glass(*, requester_id: str, confirmer_id: str, reason: str) -> None:
    """Require a distinct confirmer and recorded reason for emergency approval."""
    if not reason.strip():
        raise CatalogAuthorizationError("break-glass approval requires a reason")
    assert_approval_separation(requester_id=requester_id, approver_id=confirmer_id)
