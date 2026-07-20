"""Tests for RuntimeClient.stream_invoke() and plan() — M8/M11 SDK coverage."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from earp_sdk_runtime.client import RuntimeClient


def _make_client(handler) -> RuntimeClient:
    """Create a RuntimeClient backed by httpx.MockTransport."""
    client = RuntimeClient(endpoint="http://test", token="test-token")
    # replace internal client with mocked one
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test-token"},
    )
    return client


class TestStreamInvoke:
    """M8: RuntimeClient.stream_invoke() — SSE streaming."""

    async def test_stream_tokens(self) -> None:
        """stream_invoke yields tokens from SSE response."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/stream/invoke"
            body = json.loads(request.content)
            assert body["prompt"] == "Hello"
            return httpx.Response(
                200,
                content=(
                    b'data: {"token": "Hello", "index": 0}\n\n'
                    b'data: {"token": " world", "index": 1}\n\n'
                    b"data: [DONE]\n\n"
                ),
                headers={"content-type": "text/event-stream"},
            )

        client = _make_client(handler)
        tokens = []
        async for event in client.stream_invoke("Hello"):
            tokens.append(event)

        assert len(tokens) == 3
        assert tokens[0] == {"token": "Hello", "index": 0}
        assert tokens[1] == {"token": " world", "index": 1}
        assert tokens[2] == {"token": "[DONE]", "index": -1}


class TestPlan:
    """M11: RuntimeClient.plan() — intent → steps."""

    async def test_plan_intent(self) -> None:
        """plan() calls POST /plan and returns steps."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/plan"
            body = json.loads(request.content)
            assert body["intent"] == "echo hello"
            return httpx.Response(
                200,
                json={
                    "intent": "echo hello",
                    "steps": [
                        {
                            "capability_id": "cap-demo-echo",
                            "adapter_type": "demo.echo",
                            "input": {"message": "hello"},
                        }
                    ],
                },
            )

        client = _make_client(handler)
        steps = await client.plan("echo hello")

        assert len(steps) == 1
        assert steps[0]["capability_id"] == "cap-demo-echo"
        assert steps[0]["adapter_type"] == "demo.echo"


class TestStreamError:
    """Stream error handling."""

    async def test_stream_error_event(self) -> None:
        """SSE error event is yielded as dict."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b'data: {"error": "Ollama unavailable"}\n\n',
                headers={"content-type": "text/event-stream"},
            )

        client = _make_client(handler)
        events = []
        async for event in client.stream_invoke("test"):
            events.append(event)

        assert len(events) == 1
        assert events[0]["error"] == "Ollama unavailable"
