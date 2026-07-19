"""JSON-ish stdlib logging (M0: no structlog dependency)."""

from __future__ import annotations

import logging

from earp_server.config import Settings

_FORMAT = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'


def init_app(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level.upper(), format=_FORMAT)
