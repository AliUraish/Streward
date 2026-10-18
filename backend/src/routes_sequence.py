"""HTTP routes for the live sequence (demo_sequence.py); installed by main.create_app."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .agents import OPERATOR, authorize
from .service import public

router = APIRouter(tags=["live-sequence"])


class LiveSequenceRequest(BaseModel):
    contractorSiteId: str = Field(default="myer-plant", max_length=40)
    employeeSiteId: str = Field(default="bristol-pumps", max_length=40)
    telemetrySiteId: str = Field(default="bristol-pumps", max_length=40)


@router.get("/api/live-sequence")
def live_sequence_status(request: Request, limit: int = Query(default=5, ge=1, le=50)):
    sequence = request.app.state.service.sequence
    return public(dict(sequence.status(), runs=sequence.list(limit)))


@router.post("/api/live-sequence", status_code=202)
async def live_sequence_start(request: Request, body: LiveSequenceRequest | None = None):
    """Start one run now (the Owner's agent only); returns the run record. One run at a time."""
    actor = authorize(request.headers.get("x-steward-actor") or OPERATOR, "read")
    if actor != OPERATOR:
        from .errors import RealityError
        raise RealityError("Only the Owner's agent starts the live sequence.", "AUTHORITY_DENIED", "Send X-Steward-Actor: operator.", 403)
    body = body or LiveSequenceRequest()
    sequence = request.app.state.service.sequence
    record = await run_in_threadpool(sequence.start_now, OPERATOR, body.contractorSiteId, body.employeeSiteId, body.telemetrySiteId)
    return public(record)
