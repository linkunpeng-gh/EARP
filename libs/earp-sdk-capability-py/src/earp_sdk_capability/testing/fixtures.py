"""pytest fixtures for testing Capabilities.

Usage in a test file:

    from earp_sdk_capability.testing.fixtures import mock_runtime

    async def test_my_cap(mock_runtime):
        async with mock_runtime as rt:
            ...
"""

from __future__ import annotations

import pytest

from earp_sdk_capability.testing.mock_runtime import MockRuntime


@pytest.fixture
def mock_runtime() -> MockRuntime:
    """Create an empty MockRuntime for testing.

    Usage:
        async def test_foo(mock_runtime):
            async with mock_runtime as rt:
                rt.register(MyCap)
                result = await rt.execute("my_cap", {"key": "val"})
    """
    return MockRuntime()
