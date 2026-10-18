"""HTTP routes for contract 8 §2-§3 (the outbox and phone calls); installed by main.create_app. Read-only for people: the outbox
decides when things go out, nobody pushes a button. Addresses appear only masked.

- GET /api/outbox?status=&channel=&siteId=&limit=    queued and settled items, newest first
- GET /api/outbox/status                             pacing, caps, the line, the person channel
- GET /api/phone-calls?siteId=&active=&purpose=&limit=   phone calls, newest first (with transcripts and outcomes)
- GET /api/phone-calls/{id}                          one call
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from .service import public

router = APIRouter(tags=["outbox"])


def _service(request: Request):
    return request.app.state.service


@router.get("/api/outbox")
def outbox_list(request: Request, status: str = Query(default="", max_length=120), channel: str = Query(default="", max_length=30),
                siteId: str = Query(default="", max_length=60), limit: int = Query(default=50, ge=1, le=500)):
    service = _service(request)
    if siteId:
        service.require_property(siteId)
    return public(service.outbox.list(status=status or None, channel=channel or None, site_id=siteId or None, limit=limit))


@router.get("/api/outbox/status")
def outbox_status(request: Request):
    service = _service(request)
    return public(dict(service.outbox.status(), calls=service.voice_calls.status()))


@router.get("/api/phone-calls")
def phone_calls(request: Request, siteId: str = Query(default="", max_length=60), active: bool | None = Query(default=None),
                purpose: str = Query(default="", max_length=40), limit: int = Query(default=50, ge=1, le=200)):
    service = _service(request)
    if siteId:
        service.require_property(siteId)
    return public(service.voice_calls.list(site_id=siteId or None, active=active, purpose=purpose or None, limit=limit))


@router.get("/api/phone-calls/{call_id}")
def phone_call(call_id: str, request: Request):
    return public(_service(request).voice_calls.get(call_id))
