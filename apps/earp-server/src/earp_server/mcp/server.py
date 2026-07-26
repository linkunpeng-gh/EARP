"""MCP Server — JSON-RPC 2.0 tools/list endpoint."""

from __future__ import annotations

from typing import Any

MCP_TOOLS = [
    {
        "name": "echo",
        "description": "Echo the input back",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
    },
]


def handle_mcp_request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if method == "tools/list":
        return {"jsonrpc": "2.0", "result": {"tools": MCP_TOOLS}, "id": params.get("id") if params else None}
    if method == "tools/call" and params:
        tool_name = params.get("name", "")
        if tool_name == "echo":
            msg = str(params.get("arguments", {}).get("message", ""))
            return {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": msg}]}, "id": params.get("id")}
    return {
        "jsonrpc": "2.0",
        "error": {"code": -32601, "message": f"Method not found: {method}"},
        "id": params.get("id") if params else None,
    }
