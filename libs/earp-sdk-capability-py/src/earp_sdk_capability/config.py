"""Configuration module — loads capability.yaml with environment variable interpolation.

Priority (highest → lowest):
  1. CLI arguments (passed at runtime)
  2. Environment variables ($KEY or ${KEY})
  3. capability.yaml file values
  4. Default values (hardcoded)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")

# ── Config data classes ──


@dataclass
class RegistryConfig:
    """Capability Center Registry connection settings."""

    api_url: str = "http://localhost:8080"
    auto_register: bool = False
    timeout_seconds: int = 30


@dataclass
class RuntimeConfig:
    """Local runtime defaults."""

    default_timeout_ms: int = 30000
    max_retries: int = 0


@dataclass
class ConnectorAuthConfig:
    """Connector authentication settings."""

    type: str = ""
    token: str = ""
    username: str = ""
    password: str = ""


@dataclass
class ConnectorRetryConfig:
    """Connector retry policy."""

    max_attempts: int = 0
    backoff: str = "exponential"


@dataclass
class ConnectorConfig:
    """A single Connector configuration."""

    type: str = "rest"
    base_url: str = ""
    dsn: str = ""
    pool_size: int = 5
    auth: ConnectorAuthConfig = field(default_factory=ConnectorAuthConfig)
    timeout_ms: int = 5000
    retry: ConnectorRetryConfig = field(default_factory=ConnectorRetryConfig)


@dataclass
class EarpConfig:
    """Root EARP configuration.

    Loaded from capability.yaml, overridable via env vars and CLI args.
    """

    registry: RegistryConfig = field(default_factory=RegistryConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)


@dataclass
class Config:
    """Complete SDK configuration."""

    earp: EarpConfig = field(default_factory=EarpConfig)
    connectors: dict[str, ConnectorConfig] = field(default_factory=dict)


# ── Env var interpolation ──


def _interpolate(value: Any, env: dict[str, str] | None = None) -> Any:
    """Recursively replace ${VAR} and $VAR placeholders with env var values.

    Args:
        value: The value to interpolate (str, list, dict, or scalar).
        env: Environment variable dict. Defaults to os.environ.

    Returns:
        Interpolated value. Non-string types pass through unchanged.
    """
    if env is None:
        env = os.environ

    if isinstance(value, str):

        def _replace(m: re.Match) -> str:
            name = m.group(1)
            if name is None:
                return m.group(0)
            val = env.get(name)
            if val is None:
                raise ConfigError(
                    f"Environment variable '{name}' is not set. "
                    f"Set it or provide a fallback in capability.yaml."
                )
            return val

        return _ENV_VAR_RE.sub(_replace, value)
    elif isinstance(value, dict):
        return {k: _interpolate(v, env) for k, v in value.items()}
    elif isinstance(value, list):
        return [_interpolate(item, env) for item in value]
    return value


# ── Loading ──


def _dict_to_dataclass(dcls: type, data: dict[str, Any]) -> Any:
    """Convert a nested dict into a dataclass tree."""
    from dataclasses import fields

    field_map = {f.name: f.type for f in fields(dcls)}
    init_kwargs: dict[str, Any] = {}

    for key, value in data.items():
        if key in field_map:
            field_type = field_map[key]
            # If the field is itself a dataclass, recurse
            if hasattr(field_type, "__dataclass_fields__") and isinstance(value, dict):
                init_kwargs[key] = _dict_to_dataclass(field_type, value)
            elif (
                hasattr(field_type, "__origin__")
                and hasattr(field_type, "__args__")
                and isinstance(value, dict)
            ):
                # Generic types like dict[str, ConnectorConfig]
                # Just keep as dict for now
                init_kwargs[key] = value
            else:
                init_kwargs[key] = value
        else:
            init_kwargs[key] = value

    return dcls(**init_kwargs)


def _build_connectors(data: dict[str, Any] | None) -> dict[str, ConnectorConfig]:
    """Build connector config dict from raw yaml data."""
    result: dict[str, ConnectorConfig] = {}
    if not data:
        return result
    for name, cfg in data.items():
        auth_data = cfg.get("auth", {}) or {}
        retry_data = cfg.get("retry", {}) or {}
        # Remove consumed keys so they don't end up in ConnectorConfig kwargs
        for key in ("auth", "retry"):
            cfg.pop(key, None)
        result[name] = ConnectorConfig(
            **cfg,
            auth=ConnectorAuthConfig(**auth_data),
            retry=ConnectorRetryConfig(**retry_data),
        )
    return result


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from a capability.yaml file.

    Args:
        path: Path to capability.yaml. If None, searches cwd and parent dirs.

    Returns:
        A fully populated Config dataclass with env vars interpolated.

    Raises:
        ConfigError: If a required env var is missing.
        FileNotFoundError: If the specified path does not exist.
    """
    if path is None:
        path = _find_config()

    if path is None or not Path(path).exists():
        return Config()

    path = Path(path)
    raw_text = path.read_text(encoding="utf-8")
    raw: dict[str, Any] = yaml.safe_load(raw_text) or {}

    # Interpolate env vars on the raw dict
    interpolated = _interpolate(raw)

    # Build Config from interpolated data
    earp_data = interpolated.get("earp", {})
    connectors_data = interpolated.get("connectors", {})

    return Config(
        earp=EarpConfig(
            registry=RegistryConfig(**earp_data.get("registry", {})),
            runtime=RuntimeConfig(**earp_data.get("runtime", {})),
        ),
        connectors=_build_connectors(connectors_data if isinstance(connectors_data, dict) else None),
    )


def _find_config() -> Path | None:
    """Search for capability.yaml in cwd and parent directories."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / "capability.yaml"
        if candidate.exists():
            return candidate
    return None


# ── Error ──


class ConfigError(Exception):
    """Raised when configuration loading fails."""
