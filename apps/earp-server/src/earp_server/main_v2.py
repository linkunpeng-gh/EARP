"""FastAPI app with M1 routes: sessions CRUD, invoke, capability registry.

MERGE INSTRUCTIONS for main.py (T13 step):
 1. Add imports from session_service, invoke_router, registry, eventbus, audit consumer
 2. In lifespan: create EventBus + subscribe audit handler
 3. Add session CRUD endpoints (POST/GET/close)
 4. include_router(invoke_router)
 5. Add capability register/discover endpoints
"""

from __future__ import annotations

# Reference — actual merge target is src/earp_server/main.py.
# This file exists to avoid merge-conflict during the T2-T13 batch write session.
# At T13, the content below is merged into main.py.

# ---- IMPORTS to ADD ----
# from earp_server.runtime.session_service import create_session, get_session, close_session
# from earp_server.runtime.invoke import router as invoke_router
# from earp_server.capability.registry import register_demo, discover
# from earp_server.infra.eventbus import EventBus
# from earp_server.audit.consumer import audit_handler_factory

# ---- LIFESPAN ADDITION ----
# app.state.eventbus = EventBus()
# app.state.eventbus.subscribe("earp.execution.*", audit_handler_factory(app.state.engine))

# ---- ROUTES ----
# @app.post("/v1/sessions", status_code=201)
# async def create_session_endpoint(request: SessionCreateRequest, req: Request):
#     return await create_session(req.app.state.engine, req.state.tenant_id, req.state.user_id, req.state.role_id,
#                                  metadata=request.metadata)
# @app.get("/v1/sessions/{session_id}")
# ...
# @app.post("/v1/sessions/{session_id}/close", status_code=200)
# ...
# app.include_router(invoke_router)
# @app.post("/capabilities", status_code=201)
# @app.get("/capabilities")
