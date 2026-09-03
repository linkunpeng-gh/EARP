"""Catalog Phase 1 source-sync and governance negative vectors."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from earp_server.catalog.governance import (
    CatalogAuthorizationError,
    assert_approval_separation,
    assert_break_glass,
    assert_pack_export_allowed,
)
from earp_server.catalog.source import missing_status, webhook_signature_valid


def test_pull_missing_never_implicitly_deactivates_lkg_reference() -> None:
    assert missing_status(prior_status="active", consecutive_misses=1, tombstone=False) == "suspected_missing"
    assert missing_status(prior_status="deprecated", consecutive_misses=3, tombstone=False) == "suspected_missing"
    assert missing_status(prior_status="active", consecutive_misses=1, tombstone=True) == "inactive"


def test_webhook_signature_is_verified_in_constant_time() -> None:
    body = b'{"event":"published"}'
    signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert webhook_signature_valid(b"secret", body, signature) is True
    assert webhook_signature_valid(b"secret", body, "") is False


def test_sod_break_glass_and_export_are_not_bypassable() -> None:
    with pytest.raises(CatalogAuthorizationError):
        assert_approval_separation(requester_id="u1", approver_id="u1")
    with pytest.raises(CatalogAuthorizationError):
        assert_break_glass(requester_id="u1", confirmer_id="u2", reason="")
    with pytest.raises(CatalogAuthorizationError):
        assert_pack_export_allowed(owner_role="owner", actor_role="reader", is_platform_admin=False)
    assert_pack_export_allowed(owner_role="owner", actor_role="owner", is_platform_admin=False)
    assert_pack_export_allowed(owner_role="owner", actor_role="reader", is_platform_admin=True)
