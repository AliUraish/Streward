"""HTTP routes for contract 8 (inspections); installed by main.create_app. See REALITY-CONTRACT-8.md §6.

- GET  /api/inspections?siteId=&limit=   newest first
- GET  /api/inspections/{id}             one inspection with its stops, findings and chain steps
- POST /api/inspections {siteId}         the owner's agent (operator) starts one now; 202 with the record (the one in progress at
                                         the site when there is one)
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .agents import OPERATOR, parse_actor
from .errors import RealityError
from .service import public

router = APIRouter(tags=["inspections"])


class InspectionRequest(BaseModel):
    siteId: str = Field(min_length=1, max_length=80)


def inspections(request: Request):
    return request.app.state.service.inspections


@router.get("/api/inspections")
def list_inspections(request: Request, siteId: str = Query(default="", max_length=80), limit: int = Query(default=20, ge=1, le=100)):
    return public(inspections(request).list(siteId or None, limit))


@router.get("/api/inspections/{inspection_id}")
def get_inspection(inspection_id: str, request: Request):
    return public(inspections(request).get(inspection_id))


@router.post("/api/inspections", status_code=202)
async def start_inspection(body: InspectionRequest, request: Request):
    actor = parse_actor(request.headers.get("x-steward-actor"))
    if actor != OPERATOR:
        raise RealityError("Only the owner's agent may start an inspection by hand.", "AUTHORITY_DENIED",
                           "Inspections run on their own every hour; send X-Steward-Actor: operator to start one now.", 403)
    service = request.app.state.service
    service.require_property(body.siteId)
    return public(await run_in_threadpool(service.inspections.start_now, body.siteId, actor))
