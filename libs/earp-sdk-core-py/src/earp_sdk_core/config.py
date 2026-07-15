from dataclasses import dataclass, field

@dataclass
class AuthConfig:
    type: str = ""
    token: str = ""
    username: str = ""
    password: str = ""

@dataclass
class ConnectorRetryConfig:
    max_attempts: int = 3
    backoff: str = "exponential"

@dataclass
class ConnectorConfig:
    type: str = "rest"
    base_url: str = ""
    dsn: str = ""
    pool_size: int = 5
    timeout_ms: int = 5000
    auth: AuthConfig = field(default_factory=AuthConfig)
    retry: ConnectorRetryConfig = field(default_factory=ConnectorRetryConfig)
