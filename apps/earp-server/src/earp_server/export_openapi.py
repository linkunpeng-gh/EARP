"""Export the OpenAPI contract deterministically (AC-08).

Usage: uv run python -m earp_server.export_openapi > openapi.yaml
Byte-stable across runs: keys sorted, fixed title/version, no timestamps.
"""

from __future__ import annotations

import json
import sys

import yaml

from earp_server.main import create_app


def export_openapi() -> str:
    spec = create_app().openapi()
    ordered = json.loads(json.dumps(spec, sort_keys=True))
    return yaml.safe_dump(ordered, sort_keys=True, allow_unicode=True)


if __name__ == "__main__":
    sys.stdout.write(export_openapi())
