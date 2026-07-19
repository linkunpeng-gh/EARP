"""API process: uvicorn serving the FastAPI factory."""

from __future__ import annotations

import uvicorn

from earp_server.config import Settings


def main() -> int:
    settings = Settings()
    uvicorn.run(
        "earp_server.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
