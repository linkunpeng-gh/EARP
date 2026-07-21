"""Extension assembly (Dify ext_* pattern): each module exposes init_app(settings)."""

from __future__ import annotations

from earp_server.config import Settings
from earp_server.infra.ext import ext_logging, ext_otel


def init_all(settings: Settings) -> None:
    ext_logging.init_app(settings)
    ext_otel.init_app(settings)
    ext_logging.install()  # enable credential masking filter
