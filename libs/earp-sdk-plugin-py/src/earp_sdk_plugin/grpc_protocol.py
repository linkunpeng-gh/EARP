"""Plugin gRPC communication protocol — Security Spec §7.2 Phase 3.

Upgrades SandboxManager from JSON stdin/stdout to gRPC for:
- Streaming responses (LLM token-by-token)
- Bidirectional communication
- Better performance (binary protocol)

Phase 2: JSON stdin/stdout (current default)
Phase 3: gRPC (this module)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


# ── gRPC Protocol Definition (protobuf) ──
# This is a Python representation of the protobuf schema.
# For production use, compile from plugin.proto using grpcio-tools.

PLUGIN_PROTO_SCHEMA = """
syntax = "proto3";

package earp.plugin;

service PluginExecutor {
  // Execute a plugin method synchronously (request → response)
  rpc Execute(ExecuteRequest) returns (ExecuteResponse);

  // Execute with streaming output (for LLM token streaming)
  rpc ExecuteStream(ExecuteRequest) returns (stream ExecuteChunk);
}

message ExecuteRequest {
  string plugin_class_source = 1;  // Plugin class source code
  string method_name = 2;          // Method to invoke
  bytes params_json = 3;           // JSON-serialized kwargs
  int32 timeout_seconds = 4;       // Execution timeout
}

message ExecuteResponse {
  string status = 1;              // "ok" | "error" | "timeout"
  bytes result_json = 2;          // JSON-serialized result
  string error = 3;               // Error message (if status != "ok")
}

message ExecuteChunk {
  string status = 1;              // "streaming" | "complete" | "error"
  bytes data = 2;                 // JSON-serialized chunk data
  string error = 3;               // Error message (if status == "error")
}
"""


# ── Protocol Selection ──

class PluginProtocol:
    """Protocol constants for SandboxManager communication."""

    JSON_STDIO = "json_stdio"    # Phase 2: JSON via stdin/stdout (default)
    GRPC = "grpc"                # Phase 3: gRPC (requires grpcio)


# Phase 3 upgrade: protocol field already added to SandboxConfig in sandbox.py.
# To enable gRPC: config = SandboxConfig(protocol="grpc")

SANDBOX_CONFIG_UPGRADE = """
from earp_sdk_plugin.sandbox import SandboxConfig

# Phase 2 (default): JSON stdin/stdout
config = SandboxConfig(timeout_seconds=5, protocol="json_stdio")

# Phase 3 (requires grpcio): gRPC
# config = SandboxConfig(timeout_seconds=5, protocol="grpc", grpc_port=50051)
"""
