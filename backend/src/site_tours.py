"""Site tours (owner, Oct 18 2026: "a site inspector can give an MCP agent a site tour and then send it pics of what is wrong to
show it to the agent"): any agent, or an MCP client acting as the owner's agent, asks the Site Inspector to walk a site with the
agent eye; at each stop the inspector looks at the asset, judges it from the records (an overdue or blocked obligation, an open
issue or an out-of-band reading makes it look bad, with the reasons citing them) and adds the latest walk label's observation
when Claude made one; at the end it hands over the pictures of what is wrong.

- `POST /api/site-tours {siteId, focus?: [assetTag], maxStops?: 1..8 (5), requester?: "mcp:<client name>"}` → 202 with the tour;
  a tour already running at the site is returned instead of a second one.
- `GET /api/site-tours?siteId=&limit=`, `GET /api/site-tours/{id}`.
- Record (store kind `site_tour`): {id, siteId, siteName, requester, requesterName, actor, guide: "site-inspector", guideName,
  state: running|completed|failed, focus, maxStops, route, stops: [{n, assetTag, assetName, verdict: good|bad, color: green|blue,
  title, reasons, observation, frameId, frameUrl, eyeNote, at}], findings: [the bad stops], summary, startedAt, finishedAt, error}.
- Changes of type `site_tour` (`{tourId, status: started|stop|completed|failed, stop, assetTag, verdict}`); when a Steward agent
  (not the owner's agent, whose MCP client gets the pictures in the tool result) asked, the inspector also messages it over A2A
  with the findings and the frame URLs in the data part.

The tour plays on its own thread when the backend runs its workers and inline otherwise (tests). An eye failure leaves the stop
without a frame and never fails the tour.
"""
from __future__ import annotations

import threading

from .agents import INSPECTOR, OPERATOR, display_name, is_known, parse_actor
from .compliance_alerts import BAD_STATUSES, place_of, plural, query, short_site
from .errors import RealityError
from .inspections import finding_score
from .store import now, uid

KIND = "site_tour"
DEFAULT_STOPS = 5
MAX_STOPS = 8


def requester_words(label: str | None, actor: str) -> tuple[str, str]:
    """(requester, requesterName): an MCP client's label ("mcp:Claude Desktop" → "Claude Desktop over MCP") or the acting agent."""
    value = " ".join(str(label or "").split())[:80]
    if value:
        name = f"{value[4:].strip() or 'an MCP client'} over MCP" if value.lower().startswith("mcp:") else value
        return value, name
    return actor, display_name(actor)


class SiteTourService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self.threads: dict[str, threading.Thread] = {}
        if getattr(service, "start_workers", False):
            self.recover()

    def recover(self) -> int:
        """A tour left running by an earlier backend process has no thread any more: it is failed, so the site can be toured again."""
        count = 0
        for tour in query(self.store, KIND, "json_extract(body, '$.state') = 'running'"):
            tour.update(state="failed", error="Interrupted by a backend restart; ask for the tour again.", finishedAt=now())
            self._save(tour)
            count += 1
        return count

    def close(self) -> None:
        self._stop.set()
        for thread in list(self.threads.values()):
            if thread.is_alive():
                thread.join(timeout=2)

    # ---- records -------------------------------------------------------------------------------------------------

    def get(self, tour_id: str) -> dict:
        record = self.store.get(KIND, tour_id)
        if not record:
            raise RealityError("Site tour not found.", "NOT_FOUND", "List tours with GET /api/site-tours?siteId=, or ask for one with POST /api/site-tours.", 404)
        return record

    def list(self, site_id: str | None = None, limit: int = 20) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        return query(self.store, KIND, order="json_extract(body, '$.startedAt') DESC", limit=max(1, int(limit)), property_id=site_id or None)

    def running(self, site_id: str) -> dict | None:
        rows = query(self.store, KIND, "json_extract(body, '$.state') = 'running'", property_id=site_id)
        return rows[0] if rows else None

    def _save(self, tour: dict) -> dict:
        tour["updatedAt"] = now()
        self.store.put(KIND, tour, tour["siteId"])
        return tour

    def _change(self, tour: dict, summary: str, status: str, **extra) -> None:
        fields = dict(tourId=tour["id"], status=status, **{k: v for k, v in extra.items() if v is not None})
        self.service.reality.emit_change(tour["siteId"], KIND, tour["id"], summary[:480], extra.get("assetTag"), extra=fields, fields=fields)

    # ---- start ---------------------------------------------------------------------------------------------------

    def route(self, site_id: str, focus: list[str] | None = None, max_stops: int = DEFAULT_STOPS) -> list[str]:
        """Focus assets first, then blocked and overdue obligations (most important first), open issues, out-of-band readings,
        obligations falling due, and the site's usual walk route; at most `max_stops` assets."""
        reality, patrols = self.service.reality, self.service.patrols
        tags = [reality.component_by_tag(site_id, str(tag))["tag"] for tag in focus or []]  # an unknown tag is a 404 UNKNOWN_ASSET
        obligations = self.service.people.obligations(site_id)
        issues = patrols.open_issues(site_id)
        readings = patrols.readings(site_id)
        bad = sorted([o for o in obligations if o.get("assetTag") and o.get("status") in BAD_STATUSES], key=finding_score, reverse=True)
        tags += [o["assetTag"] for o in bad]
        tags += [i["assetTag"] for i in issues if i.get("assetTag")]
        tags += [r["assetTag"] for r in readings if r.get("assetTag") and r.get("state") in ("high", "low")]
        tags += [o["assetTag"] for o in obligations if o.get("assetTag") and o.get("status") == "due_soon"]
        try:
            tags += patrols.default_route(site_id)
        except RealityError:
            pass
        known = {c["tag"] for c in reality.components(site_id)}
        return [t for t in dict.fromkeys(tags) if t in known][:max_stops]

    def start(self, site_id: str, actor: str | None = None, requester: str | None = None, focus: list[str] | None = None,
              max_stops: int | None = None, realtime: bool | None = None) -> dict:
        """Ask the Site Inspector for a tour of the site, or get the one already running there."""
        actor = parse_actor(actor or OPERATOR)  # unknown actors are refused (403)
        site = self.service.require_property(site_id)
        try:
            stops = DEFAULT_STOPS if max_stops is None else int(max_stops)
        except (TypeError, ValueError):
            raise RealityError("maxStops must be a whole number from 1 to 8.", "INVALID_REQUEST", "Send maxStops between 1 and 8, or omit it.")
        if not 1 <= stops <= MAX_STOPS:
            raise RealityError("maxStops must be from 1 to 8.", "INVALID_REQUEST", "Send maxStops between 1 and 8, or omit it.")
        if focus is not None and (not isinstance(focus, list) or len(focus) > MAX_STOPS):
            raise RealityError("focus takes at most 8 asset tags.", "INVALID_REQUEST", "Send focus: [assetTag, ...] or omit it.")
        realtime = bool(getattr(self.service, "start_workers", False)) if realtime is None else realtime
        label, name = requester_words(requester, actor)
        with self.lock:
            existing = self.running(site_id)
            if existing:
                return existing
            route = self.route(site_id, focus, stops)
            if not route:
                raise RealityError("There is nothing at this site to tour.", "INVALID_REQUEST", "Pass focus: [assetTag, ...] with registered tags.")
            tour = dict(id=uid("tour"), siteId=site_id, siteName=site.get("name"), requester=label, requesterName=name, actor=actor, guide=INSPECTOR,
                        guideName=display_name(INSPECTOR), state="running", focus=list(focus or []), maxStops=stops, route=route, stops=[], findings=[],
                        summary=None, error=None, startedAt=now(), finishedAt=None)
            self._save(tour)
        self._change(tour, f"{tour['guideName']} started a tour of {place_of(site_id)} at {short_site(site_id)} for {name}: "
                           f"{plural(len(route), 'stop')} ({', '.join(route)}).", "started", stops=len(route))
        if realtime:
            thread = threading.Thread(target=self.run, args=(tour["id"],), name=f"steward-site-tour-{site_id}", daemon=True)
            self.threads[site_id] = thread
            thread.start()
            return tour
        return self.run(tour["id"])

    # ---- the tour ------------------------------------------------------------------------------------------------

    def run(self, tour_id: str) -> dict:
        tour = self.get(tour_id)
        site = tour["siteId"]
        patrols = self.service.patrols
        try:
            self.service.ops.note(INSPECTOR, f"Touring {short_site(site)} for {tour['requesterName']}", why="A site tour someone asked for")
        except Exception:
            pass
        try:
            obligations = self.service.people.obligations(site)
            issues = patrols.open_issues(site)
            readings = patrols.readings(site)
            walk_labels = {label["assetTag"]: label for label in patrols.labels(site)}
            for index, tag in enumerate(tour["route"]):
                if self._stop.is_set():
                    break
                component = self.service.reality.component_by_tag(site, tag)
                try:
                    frame_id, frame_url, note = patrols.look(site, tag, INSPECTOR)
                except Exception as error:  # the eye never fails the tour
                    frame_id, frame_url, note = None, None, f"eye unavailable ({type(error).__name__})"
                assessment = patrols.assess(site, component, obligations, issues, readings)
                label = walk_labels.get(tag) or {}
                observation = label.get("observation") if label.get("assessedBy") not in (None, "rules") else None
                bad = assessment["verdict"] == "bad"
                stop = dict(n=index + 1, assetTag=tag, assetName=component.get("name"), verdict="bad" if bad else "good", color="blue" if bad else "green",
                            title="Looks bad" if bad else "Looks good", reasons=list(assessment["reasons"])[:4], observation=observation,
                            frameId=frame_id, frameUrl=frame_url if frame_id else None, eyeNote=note, at=now())
                with self.lock:
                    tour = self.get(tour_id)
                    tour["stops"].append(stop)
                    self._save(tour)
                try:
                    self.service.telemetry.record(INSPECTOR, "tool", "tour_stop", tokens=40, site_id=site, synthetic=True,
                                                  detail=(f"{tag}: {stop['title']}" + (f": {stop['reasons'][0]}" if stop["reasons"] else ""))[:200])
                except Exception:
                    pass
                self._change(tour, f"{tour['guideName']} at {tag} ({stop['assetName'] or tag}), stop {index + 1} of {len(tour['route'])}: {stop['title']}"
                                   + (f": {stop['reasons'][0]}" if bad and stop["reasons"] else "") + ".", "stop", stop=index + 1, assetTag=tag, verdict=stop["verdict"])
            return self.finish(tour_id)
        except Exception as error:
            detail = error.detail if isinstance(error, RealityError) else f"{type(error).__name__}: {str(error)[:200]}"
            with self.lock:
                tour = self.get(tour_id)
                tour.update(state="failed", error=detail[:300], finishedAt=now())
                self._save(tour)
            self._change(tour, f"The tour of {short_site(site)} stopped: {detail}", "failed")
            return tour
        finally:
            try:
                self.service.ops.note(INSPECTOR, None)
            except Exception:
                pass

    def finish(self, tour_id: str) -> dict:
        with self.lock:
            tour = self.get(tour_id)
            findings = [s for s in tour["stops"] if s["verdict"] == "bad"]
            pictures = sum(1 for s in findings if s.get("frameUrl"))
            site = tour["siteId"]
            if findings:
                listed = "; ".join(f"{s['assetTag']} ({s['reasons'][0]})" if s["reasons"] else s["assetTag"] for s in findings[:4])
                text = (f"{tour['guideName']} toured {place_of(site)} at {short_site(site)} for {tour['requesterName']}: "
                        f"{plural(len(tour['stops']), 'stop')}, {len(findings)} look bad: {listed}. "
                        + (f"{plural(pictures, 'picture')} of what is wrong." if pictures else "No pictures: the eye did not answer."))
            else:
                text = (f"{tour['guideName']} toured {place_of(site)} at {short_site(site)} for {tour['requesterName']}: "
                        f"{plural(len(tour['stops']), 'stop')}, all look good.")
            tour.update(state="completed", findings=findings, summary=text, finishedAt=now())
            self._save(tour)
        self._change(tour, text, "completed", stops=len(tour["stops"]), findings=len(findings))
        self.tell(tour)
        return self.get(tour_id)

    def tell(self, tour: dict) -> None:
        """A Steward agent that asked gets the findings over A2A (the frame URLs in the data part). The owner's agent asks through
        its MCP client, which gets the pictures in the tool result."""
        actor = tour.get("actor")
        if not actor or actor in (OPERATOR, INSPECTOR) or not is_known(actor):
            return
        frames = [dict(assetTag=s["assetTag"], frameUrl=s["frameUrl"], reasons=s["reasons"][:2]) for s in tour["findings"] if s.get("frameUrl")]
        try:
            conversation = self.service.conversations.message(INSPECTOR, actor, f"Site tour of {place_of(tour['siteId'])}", tour["summary"],
                                                              site_ids=[tour["siteId"]],
                                                              data=dict(tourId=tour["id"], findings=len(tour["findings"]), frames=frames))
            self.service.conversations.answer(conversation["id"], actor, "Received the tour and the pictures.")
            with self.lock:
                record = self.get(tour["id"])
                record["conversationId"] = conversation["id"]
                self._save(record)
        except Exception:  # the message is a courtesy; it never undoes a finished tour
            pass
