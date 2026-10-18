"""HTTP surface for the Supabase features, installed into the app by main.create_app (two lines there).

- GET  /api/supabase/usage            every budget counter against its cap and the plan limits, plus mirror/HUD/storage/inbox state
- POST /api/supabase/viewers          viewer heartbeat {siteId, viewerId, role?, leave?}: no fresh viewer, no HUD broadcasts
- POST /api/supabase/authority-check  {agentId, table, action, siteId?}: Postgres's own answer to that agent's write
- GET  /api/supabase/ledger           verify_ledger() (incremental from the local anchor; ?full=true for the whole chain)
- GET  /api/supabase/evidence/{sha}   307 to a signed Storage URL for an uploaded evidence file

install() also tags each request with its acting agent (X-Steward-Actor, default operator) for the mirror, and wraps
the app lifespan so the Storage/HUD/inbox/usage services start after the service and stop before it closes.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .agents import OPERATOR
from .errors import RealityError
from .sites import SITE_IDS
from .store import now
from .supa_authority import AGENT_IDS, MATRIX, SITES, acting_as, agent_site, display_name, permitted, role_of
from .supa_auth import decode_claims
from .supa_budget import CAPS

router = APIRouter(prefix="/api/supabase", tags=["supabase"])


class ViewerHeartbeat(BaseModel):
    siteId: str = Field(min_length=3, max_length=40)
    viewerId: str = Field(min_length=6, max_length=80)
    role: str = Field(default="viewer", max_length=20)
    leave: bool = False


class AuthorityCheck(BaseModel):
    agentId: str = Field(min_length=3, max_length=40)
    table: str = Field(min_length=3, max_length=40)
    action: str = Field(default="insert", max_length=10)
    siteId: str | None = Field(default=None, max_length=40)


def mirror_of(request: Request):
    return request.app.state.service.reality.mirror


def services_of(request: Request):
    return mirror_of(request).services


# ---- helpers main.py calls ------------------------------------------------------------------------------------------

def signed_frame_url(request: Request, frame_id: str) -> str | None:
    """The signed Storage URL for an uploaded eye frame when a browser asks, or None: not uploaded, Supabase off, the
    egress budget spent, `?local=1`, or an agent asking (X-Steward-Actor: the MCP eye tools need the bytes and refuse
    redirects)."""
    try:
        if request.headers.get("x-steward-actor") or request.query_params.get("local"):
            return None
        services = services_of(request)
        return services.storage.frame_url(frame_id) if services is not None else None
    except Exception:
        return None


def decorate_feed(request: Request, feed: dict) -> dict:
    """Frames in Storage get `url`/`signedUrl` (signed, 15 minutes) and `thumbUrl`, keeping `localUrl`; the rest stay local."""
    try:
        services = services_of(request)
        if services is None:
            return feed
        copies = 1
        for frame in feed.get("frames") or []:
            frame.setdefault("storage", "local")
            if not services.storage.find("eye_frame", frame.get("id") or ""):
                continue
            signed = services.storage.frame_url(frame["id"], copies=copies)
            if not signed:
                continue
            frame.update(localUrl=frame.get("url"), url=signed, signedUrl=signed, storage="supabase",
                         thumbUrl=services.storage.thumb_url(frame["id"], frame.get("siteId"), services.frames_dir, copies=copies))
    except Exception:
        return feed
    return feed


# ---- routes ---------------------------------------------------------------------------------------------------------

@router.get("/usage")
def usage(request: Request):
    mirror = mirror_of(request)
    services = mirror.services
    budget = mirror.budget.usage()
    return dict(configured=mirror.configured, plan=budget["plan"], budget=budget, mirror=mirror.stats(),
                services=services.status() if services is not None else None,
                mau=dict(agents=len(AGENT_IDS), note=f"one Supabase Auth user per agent; monthly active users stay at {len(AGENT_IDS)}"),
                caps=[dict(key=c.key, env=c.env, unit=c.unit, period=c.period, defaults=c.defaults) for c in CAPS], at=now())


@router.post("/viewers")
def viewers(body: ViewerHeartbeat, request: Request):
    if body.siteId not in SITES:
        raise RealityError(f"Unknown site {body.siteId}.", "NOT_FOUND", "Sites: " + ", ".join(SITES) + ".", 404)
    services = services_of(request)
    if services is None:
        return dict(realtime=False, reason="Supabase Realtime is off in this backend (not configured or workers not running); keep polling.",
                    heartbeatSeconds=30)
    if body.leave:
        return services.hud.leave(body.siteId, body.viewerId)
    return services.hud.heartbeat(body.siteId, body.viewerId, body.role)


@router.post("/authority-check")
async def authority_check(body: AuthorityCheck, request: Request):
    mirror = mirror_of(request)
    agent = body.agentId.strip().casefold()
    if agent not in AGENT_IDS:
        raise RealityError(f"Unknown agent {agent[:40]}.", "NOT_FOUND", "Agents: " + ", ".join(AGENT_IDS) + ".", 404)
    if body.table not in MATRIX:
        raise RealityError(f"Unknown table {body.table[:40]}.", "NOT_FOUND", "Tables: " + ", ".join(sorted(MATRIX)) + ".", 404)
    if body.action not in ("insert", "update", "delete"):
        raise RealityError("action must be insert, update or delete.", "INVALID_REQUEST", "Pick insert, update or delete.")
    if not mirror.configured or not mirror.tokens.enabled:
        return JSONResponse(dict(attempted=False, reason="Supabase agent sign-in is not configured (SUPABASE_URL, the publishable key and "
                                                       "STEWARD_AGENT_PASSWORD_* are required)."), status_code=503)
    site = body.siteId or agent_site(agent) or SITES[0]
    spec = MATRIX[body.table]
    sample = {spec["site_col"]: [site] if spec["site_kind"] == "many" else site} if spec["site_col"] else {}
    if spec["bind"]:
        sample[spec["bind"]] = agent
    if body.table == "attestations":
        sample["signed_payload"] = None  # the probe row carries no backend signature
    expected_allowed = body.action == "insert" and permitted(agent, body.table, sample)

    def run():
        token = mirror.tokens.token(agent)
        if not token:
            return None, {}
        result = mirror.supa.rpc("steward_authority_probe", {"p_table": body.table, "p_action": body.action, "p_site": site}, token=token)
        return result, decode_claims(token)

    try:
        result, claims = await run_in_threadpool(run)
    except Exception as error:
        return JSONResponse(dict(attempted=False, reason=f"probe request failed: {type(error).__name__}: {str(error)[:200]}"), status_code=502)
    if result is None:
        return JSONResponse(dict(attempted=False, reason=f"could not sign {agent} in to Supabase Auth"), status_code=502)
    return dict(agentId=agent, agentName=display_name(agent), role=role_of(agent), table=body.table, action=body.action, siteId=site,
                claims={k: claims.get(k) for k in ("agent_id", "agent_level", "site_id", "agent_role", "role", "sub", "email") if k in claims},
                localAuthoritySays="allowed" if expected_allowed else "refused", postgres=result,
                agreement=(bool(result.get("allowed")) == expected_allowed) if isinstance(result, dict) and "allowed" in result else None,
                via="PostgREST RPC public.steward_authority_probe as this agent (role authenticated, RLS applied); always rolled back",
                at=now())


@router.get("/ledger")
async def ledger(request: Request, full: bool = Query(default=False)):
    mirror = mirror_of(request)
    if not mirror.configured:
        return JSONResponse(dict(ok=None, reason="Supabase is not configured."), status_code=503)
    store = mirror.store
    anchor = json.loads(store.meta("supa:ledger:anchor") or "null")

    def run():
        args = {"p_from_seq": 1, "p_expected_prev": None}
        if anchor and not full:
            args = {"p_from_seq": int(anchor["chainSeq"]) + 1, "p_expected_prev": anchor["rowHash"]}
        result = mirror.supa.rpc("verify_ledger", args, timeout=60)
        anchored = None
        if anchor:
            # The anchored link must still be where we left it: a rewritten chain moves it.
            rows = mirror.supa.select("attestations", {"select": "chain_seq,row_hash", "chain_seq": f"eq.{int(anchor['chainSeq'])}"})
            found = rows[0]["row_hash"] if isinstance(rows, list) and rows else None
            anchored = dict(chainSeq=anchor["chainSeq"], rowHash=anchor["rowHash"], at=anchor.get("at"), stillMatches=found == anchor["rowHash"])
        return result, anchored

    try:
        result, anchored = await run_in_threadpool(run)
    except Exception as error:
        return JSONResponse(dict(ok=None, reason=f"verify_ledger failed: {type(error).__name__}: {str(error)[:200]}"), status_code=502)
    ok = bool(isinstance(result, dict) and result.get("ok")) and (anchored is None or anchored["stillMatches"])
    if ok and isinstance(result, dict) and result.get("head"):
        head = result["head"]
        store.meta("supa:ledger:anchor", json.dumps(dict(chainSeq=head["chainSeq"], rowHash=head["rowHash"], at=now())))
    return dict(ok=ok, mode="full" if full or not anchor else "incremental from the local anchor", ledger=result, anchor=anchored,
                note="Append-only (UPDATE/DELETE/TRUNCATE refused for every role), hash-chained (sha256 over prev_hash and the canonical row), "
                     "Ed25519 signatures checked in Postgres with pgsodium.", at=now())


@router.get("/evidence/{digest}")
def evidence(digest: str, request: Request):
    services = services_of(request)
    url = services.storage.evidence_url(digest) if services is not None and len(digest) == 64 else None
    if not url:
        raise RealityError("Evidence is not in Supabase Storage.", "NOT_FOUND", "Use the local evidence file route.", 404)
    return RedirectResponse(url, status_code=307)


# ---- install -----------------------------------------------------------------------------------------------------------

def install(app, start_workers: bool = True):
    app.include_router(router)

    @app.middleware("http")
    async def supabase_actor(request: Request, call_next):
        actor = (request.headers.get("x-steward-actor") or OPERATOR).strip().casefold()
        with acting_as(actor if actor in AGENT_IDS else None):
            return await call_next(request)

    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_):
        async with original(app_) as state:
            started = None
            if start_workers:
                try:
                    from .supa_services import SupaServices
                    mirror = app_.state.service.reality.mirror
                    if mirror.configured:
                        mirror.services = started = SupaServices(mirror, app_.state.service, app_)
                except Exception as error:  # Supabase must never stop the backend from starting
                    app_.state.service.store.event(SITE_IDS[0], "director", "supabase.service", "Supabase services did not start", type(error).__name__)
            try:
                yield state
            finally:
                if started is not None:
                    try:
                        mirror = app_.state.service.reality.mirror
                        mirror.services = None
                        started.close()
                    except Exception:
                        pass

    app.router.lifespan_context = lifespan
    return app
