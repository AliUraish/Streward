"""HTTP routes for contract 8 (long agent chats); installed by main.create_app. See REALITY-CONTRACT-8.md §4."""
from __future__ import annotations

from fastapi import APIRouter, Request

from .service import public

router = APIRouter(tags=["chats"])


@router.get("/api/chats/status")
def chats_status(request: Request):
    """The chat writer: the day's Claude usage against its caps, the per-source hourly counts, the chats running now, the last error."""
    return public(request.app.state.service.chats.status())
