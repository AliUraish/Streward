"""HTTP routes for site tours (site_tours.py); installed by main.create_app.

- POST /api/site-tours {siteId, focus?, maxStops?, requester?}   202 with the tour (the one running at the site when there is one);
                                                                any Steward agent may ask (X-Steward-Actor, default the owner's agent)
- GET  /api/site-tours?siteId=&limit=                           newest first
- GET  /api/site-tours/{id}                                     one tour with its stops, findings and pictures (frame URLs)
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .agents import parse_actor
from .service import public

router = APIRouter(tags=["site-tours"])


class TourRequest(BaseModel):
    siteId: str = Field(min_length=1, max_length=80)
    focus: list[str] | None = Field(default=None, max_length=8)
    maxStops: int | None = Field(default=None, ge=1, le=8)
    requester: str | None = Field(default=None, max_length=80)


@router.post("/api/site-tours", status_code=202)
async def start_tour(body: TourRequest, request: Request):
    actor = parse_actor(request.headers.get("x-steward-actor"))
    service = request.app.state.service
    return public(await run_in_threadpool(service.site_tours.start, body.siteId, actor, body.requester, body.focus, body.maxStops))


@router.get("/api/site-tours")
def list_tours(request: Request, siteId: str = Query(default="", max_length=80), limit: int = Query(default=20, ge=1, le=100)):
    return public(request.app.state.service.site_tours.list(siteId or None, limit))


@router.get("/api/site-tours/{tour_id}")
def get_tour(tour_id: str, request: Request):
    return public(request.app.state.service.site_tours.get(tour_id))
