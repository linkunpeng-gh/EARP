"""WebSocket Gateway — M6: push execution events to connected clients.

Endpoint: /ws/events/{session_id}
"""

from __future__ import annotations

import asyncio
import logging

import jwt
from fastapi import WebSocket, WebSocketDisconnect

from earp_server.infra.eventbus import CloudEvent

logger = logging.getLogger(__name__)

# session_id -> set of WebSocket connections
_connections: dict[str, set[WebSocket]] = {}


async def ws_endpoint(websocket: WebSocket, session_id: str, token: str = "") -> None:
    """WebSocket streaming endpoint with optional JWT auth via query param."""
    # M6 Phase 1: JWT validation via ?token=<jwt> query parameter
    if token:
        from earp_server.gateway.auth import JWTMiddleware

        try:
            _ = jwt.decode(token, JWTMiddleware.DEV_SECRET, algorithms=["HS256"])
        except Exception:
            await websocket.close(code=4001, reason="invalid token")
            return
    await websocket.accept()
    _connections.setdefault(session_id, set()).add(websocket)
    logger.info("ws: client connected to session %s", session_id)
    try:
        while True:
            # keep-alive: wait for client pong or disconnect
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _connections[session_id].discard(websocket)
        if not _connections[session_id]:
            del _connections[session_id]


def push_event(session_id: str, event: CloudEvent) -> None:
    """Push event to all WebSocket clients watching this session."""
    if session_id not in _connections:
        return
    payload = {
        "type": event.type,
        "source": event.source,
        "data": event.data,
        "time": event.time,
    }
    dead: list[WebSocket] = []
    for ws in _connections[session_id]:
        try:
            asyncio.create_task(ws.send_json(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections[session_id].discard(ws)
