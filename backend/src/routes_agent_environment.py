"""HTTP route for the agent environment (agent_environment.py); installed by main.create_app.

- GET /api/agent-environment/{siteId}             the site as an agent sees it (JSON, with the same content as markdown)
- GET /api/agent-environment/{siteId}?format=md   the markdown alone (text/markdown), what the MCP's get_environment returns
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from .service import public

router = APIRouter(tags=["agent-environment"])


@router.get("/api/agent-environment/{site_id}")
async def agent_environment(site_id: str, request: Request, format: str = Query(default="json", pattern="^(json|md)$")):
    view = await run_in_threadpool(request.app.state.service.agent_environment.view, site_id)
    if format == "md":
        return PlainTextResponse(view["markdown"], media_type="text/markdown; charset=utf-8")
    return public(view)
