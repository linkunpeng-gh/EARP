"""JWT middleware: decode + inject tenant_id/role_id/user_id into request.state.

Dev: HS256 with hardcoded secret. Prod: RS256 with EARP_JWT_PUBLIC_KEY env.
"""

from __future__ import annotations

import logging
import os
import time

import jwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

DEV_SECRET = "earp-dev-secret-change-in-production"
SECRET_ENV = "EARP_JWT_SECRET"
PUBLIC_KEY_ENV = "EARP_JWT_PUBLIC_KEY"

EXEMPT_PATHS = ("/health", "/ready", "/admin", "/auth")  # /admin: static dashboard assets (API calls still require JWT)
logger = logging.getLogger(__name__)


def create_token(*, sub: str, tenant_id: str, role_id: str, expires_in: int = 7 * 24 * 3600) -> str:
    """Issue an HS256 JWT using the same key selection as JWTMiddleware._decode.

    Dev/test login endpoint only — prod auth uses a real IdP (RS256 via
    EARP_JWT_PUBLIC_KEY), so this function must not be reachable in prod
    (main.py guards /auth/login with app_env check).
    """
    now = int(time.time())
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role_id": role_id,
        "iat": now,
        "exp": now + expires_in,
    }
    secret = os.environ.get(SECRET_ENV, DEV_SECRET)
    return jwt.encode(payload, secret, algorithm="HS256")


class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # CORS preflight (OPTIONS) carries no auth — let CORSMiddleware answer it.
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path.startswith(EXEMPT_PATHS):
            return await call_next(request)

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"error": "Missing Authorization header"})

        try:
            payload = self._decode(token)
        except jwt.ExpiredSignatureError:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"error": "Token expired"})
        except jwt.InvalidTokenError:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"error": "Invalid token"})

        if not payload.get("tenant_id") or not payload.get("role_id"):
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=403, content={"error": "Missing tenant/role in token"})

        request.state.user_id = payload.get("sub")
        request.state.tenant_id = payload["tenant_id"]
        request.state.role_id = payload["role_id"]
        return await call_next(request)

    @staticmethod
    def _decode(token: str) -> dict:
        if PUBLIC_KEY_ENV in os.environ:
            key = os.environ[PUBLIC_KEY_ENV]
            return jwt.decode(token, key, algorithms=["RS256"])
        if SECRET_ENV in os.environ:
            return jwt.decode(token, os.environ[SECRET_ENV], algorithms=["HS256"])
        return jwt.decode(token, DEV_SECRET, algorithms=["HS256"])
