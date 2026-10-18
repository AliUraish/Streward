"""HTTP routes for contract 8 §5 (the employees' badge log and the People Officer's cases); installed by main.create_app.

- GET  /api/attendance?siteId=&days=14   one site's roster with its badge entries, flags and cases (all sites without siteId)
- GET  /api/attendance/cases?siteId=&limit=   cases, newest first
- GET  /api/attendance/cases/{id}        one case
- POST /api/attendance/check {seed?, crewId?}   the Owner's agent only: run the late-twice rule now (optionally seeding a late pair)

Read-only for people; no phone number or email address appears (the employee is reached through the outbox's `employee` role).
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .agents import OPERATOR, display_name, parse_actor
from .errors import RealityError
from .service import public
from .sites import SITE_IDS

router = APIRouter(tags=["attendance"])


class AttendanceCheck(BaseModel):
    seed: bool = False
    crewId: str | None = Field(default=None, max_length=80)


@router.get("/api/attendance")
def attendance(request: Request, siteId: str | None = Query(default=None, max_length=40), days: int = Query(default=14, ge=1, le=31)):
    svc = request.app.state.service
    if siteId:
        return public(svc.attendance.log(siteId, days))
    return public(dict(sites=[svc.attendance.log(site, days) for site in SITE_IDS if svc.store.get("property", site)],
                       status=svc.attendance.status()))


@router.get("/api/attendance/cases")
def attendance_cases(request: Request, siteId: str | None = Query(default=None, max_length=40), limit: int = Query(default=50, ge=1, le=200)):
    return public(request.app.state.service.attendance.cases(siteId or None, limit))


@router.get("/api/attendance/cases/{case_id}")
def attendance_case(case_id: str, request: Request):
    return public(request.app.state.service.attendance.case(case_id))


@router.post("/api/attendance/check")
async def attendance_check(request: Request, body: AttendanceCheck | None = None):
    actor = parse_actor(request.headers.get("x-steward-actor"))
    if actor != OPERATOR:
        raise RealityError(f"{display_name(actor)} may not run the attendance check.", "AUTHORITY_DENIED",
                           "The Owner's agent runs it; the People Officer checks the badge log on its own every 15 minutes.", 403)
    body = body or AttendanceCheck()
    svc = request.app.state.service
    return public(await run_in_threadpool(svc.attendance.check, None, body.seed, body.crewId))
