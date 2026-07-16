"""Tests for mask_sensitive() — Security Spec §3.2.

Covers:
  AC-03: mask_sensitive(data) uses built-in sensitive field list
  AC-04: All §3.2 fields: password, token, secret, api_key, email, phone, id_card, ssn
"""

import pytest
from earp_sdk_core.masking import mask_sensitive


class TestMaskSensitiveBasic:
    """AC-04: Verify all §3.2 sensitive fields are masked to '***'."""

    @pytest.mark.parametrize("field,value", [
        ("password", "my-secret-pw"),
        ("token", "jwt-token-12345"),
        ("secret", "shared-secret-xyz"),
        ("api_key", "sk-abc123def456"),
    ])
    def test_full_mask_fields(self, field, value):
        """password/token/secret/api_key → '***'."""
        result = mask_sensitive({field: value})
        assert result[field] == "***"

    def test_email_masked(self):
        """email field → 'u***@example.com' (retains first char + domain)."""
        result = mask_sensitive({"email": "user@example.com"})
        assert result["email"] == "u***@example.com"

    def test_phone_masked(self):
        """phone field → '861****5678' (strips non-digits, retains first 3 + last 4)."""
        result = mask_sensitive({"phone": "+86-138-1234-5678"})
        assert result["phone"] == "861****5678"

    def test_id_card_masked(self):
        """id_card field → '***'."""
        result = mask_sensitive({"id_card": "440101199001011234"})
        assert result["id_card"] == "***"

    def test_ssn_masked(self):
        """ssn field → '***'."""
        result = mask_sensitive({"ssn": "123-45-6789"})
        assert result["ssn"] == "***"


class TestMaskSensitiveAuthHeaders:
    """Authorization headers also masked."""

    def test_authorization_header_masked(self):
        result = mask_sensitive({"authorization": "Bearer secret-token-abc"})
        assert result["authorization"] == "***"

    def test_auth_header_masked(self):
        result = mask_sensitive({"auth": "Basic dXNlcjpwYXNz"})
        assert result["auth"] == "***"


class TestMaskSensitiveSafeFields:
    """Non-sensitive fields must pass through unchanged."""

    def test_safe_string_field(self):
        result = mask_sensitive({"username": "alice", "role": "admin"})
        assert result["username"] == "alice"
        assert result["role"] == "admin"

    def test_safe_numeric_field(self):
        result = mask_sensitive({"age": 25, "score": 98.5, "count": 0})
        assert result["age"] == 25
        assert result["score"] == 98.5
        assert result["count"] == 0

    def test_safe_boolean_field(self):
        result = mask_sensitive({"active": True, "verified": False})
        assert result["active"] is True
        assert result["verified"] is False

    def test_safe_null_field(self):
        result = mask_sensitive({"middle_name": None, "notes": ""})
        assert result["middle_name"] is None
        assert result["notes"] == ""

    def test_empty_dict(self):
        result = mask_sensitive({})
        assert result == {}


class TestMaskSensitiveRecursive:
    """Recursive masking into nested dicts and lists."""

    def test_nested_dict(self):
        data = {
            "user": {
                "name": "Alice",
                "credentials": {
                    "token": "nested-jwt-123",
                    "password": "nested-pw-456",
                }
            }
        }
        result = mask_sensitive(data)
        assert result["user"]["name"] == "Alice"
        assert result["user"]["credentials"]["token"] == "***"
        assert result["user"]["credentials"]["password"] == "***"

    def test_list_of_dicts(self):
        data = {
            "items": [
                {"id": 1, "token": "t1"},
                {"id": 2, "token": "t2"},
                {"id": 3, "secret": "s3"},
            ]
        }
        result = mask_sensitive(data)
        assert result["items"][0]["token"] == "***"
        assert result["items"][1]["token"] == "***"
        assert result["items"][2]["secret"] == "***"
        assert result["items"][0]["id"] == 1

    def test_deeply_nested(self):
        data = {"l1": {"l2": {"l3": {"l4": {"token": "deep"}}}}}
        result = mask_sensitive(data)
        assert result["l1"]["l2"]["l3"]["l4"]["token"] == "***"

    def test_depth_limit(self):
        """Recursion stops at depth 10, no infinite loop."""
        data = {}
        current = data
        for i in range(12):
            current["nested"] = {}
            current = current["nested"]
        current["token"] = "very-deep-token"
        result = mask_sensitive(data)
        # Beyond depth 10, returns as-is (token NOT masked)
        node = result
        for _ in range(12):
            node = node["nested"]
        assert node["token"] == "very-deep-token"

    def test_list_with_non_dict_items(self):
        data = {"tokens": ["t1", "t2", 42, None]}
        result = mask_sensitive(data)
        assert result["tokens"] == ["t1", "t2", 42, None]


class TestMaskSensitiveCaseInsensitive:
    """Field matching is case-insensitive."""

    def test_uppercase_field(self):
        result = mask_sensitive({"TOKEN": "my-token", "Password": "my-pw"})
        assert result["TOKEN"] == "***"
        assert result["Password"] == "***"

    def test_mixed_case_auth(self):
        result = mask_sensitive({"Authorization": "Bearer xyz"})
        assert result["Authorization"] == "***"


class TestMaskSensitiveNonDict:
    """Non-dict values in lists should pass through unchanged."""

    def test_list_of_primitives(self):
        result = mask_sensitive({"items": [1, "hello", True, None]})
        assert result["items"] == [1, "hello", True, None]
