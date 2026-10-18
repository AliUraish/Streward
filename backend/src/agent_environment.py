"""The agent environment (owner, Oct 18 2026: "make these agent environments for MCPs, so MCP servers can see them, and add for
that agent how they are seeing the environment"): one cheap, read-only view of a site as an agent sees it, shared by the
dashboard's agent mode and the MCP's get_environment tool.

`GET /api/agent-environment/{siteId}` (`?format=md` for the markdown alone):

    {siteId, siteName, at,
     summary: {compliancePercent, openIssues, overdue, blocked, employeesCheckedIn, crewOnShift},
     walk: {state, agentId, agentName, stopIndex, stops, assetTag, assetName, moving, startedAt} | null,
     eye: {frames: [{id, url, assetTag, at, actorName, labels: [{assetTag, verdict, color, title, reasons, mark: {x, y, note} | null}]}]},
     labels: [{assetTag, assetName, verdict, color, title, reasons, regulationIds, frameUrl, at}],
     readings: [{key, label, assetTag, unit, value, previous, delta, trend, state, spec}],
     obligations: [{id, title, assetTag, status, dueAt, daysOverdue, dueInDays, blockedReason, regulationIds}],
     issues: [{id, kind, severity, assetTag, summary, at}],
     inspection: {id, state, primary, alsoNoted, steps, summary, startedAt, finishedAt} | null,
     tours: [{id, state, requesterName, stops, findings, summary, startedAt, finishedAt}],
     logs: [{at, type, summary}],
     tools: [{name, purpose}],
     markdown}

Everything comes from a few store reads (the latest eye frames, the labels, obligations, open issues, the live readings, the
latest inspection and tours, and the newest changes through SQLite's json_extract). Contact details never appear, and log
lines that describe machinery rather than the site are left out.
"""
from __future__ import annotations

import re

from .compliance_alerts import BAD_STATUSES, due_in_days, overdue_days, query
from .store import now

MAX_FRAMES = 3
MAX_LOGS = 20
MAX_TOURS = 3
# Changes that are bookkeeping or machinery, not news about the site: signed readings and their attestations, every eye
# command, the scenario's own step rows, each A2A message (the chats carry them), pin placement, agent settings and evals.
QUIET_TYPES = ("fact", "attestation", "eye", "scenario", "a2a", "pin", "agent_config", "eval")
MACHINERY = re.compile(r"synthetic|simulat|scenario|\bdemo\b|dry[_ ]run|harness", re.I)
CONTACT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\+?\d[\d\s().-]{7,}\d")
TOOLS = (
    ("get_environment", "This view: the site's state, the latest eye frames as images and what the agents see in them."),
    ("request_site_tour", "Ask the Site Inspector for a tour: it walks the site with the agent eye and sends back pictures of what is wrong."),
    ("get_site_tour", "Read a tour's stops, findings and pictures by tourId."),
    ("eye_go_to", "Fly the agent eye to a tagged asset and get the frame as an image."),
    ("eye_look", "Look through the agent eye from where it is now."),
    ("list_issues", "The site's open issues; get_issue for one, request_fix to have the agents fix it."),
    ("list_obligations", "Compliance obligations with due dates, owners and the regulations they cite."),
    ("get_metrics", "Live readings and their history."),
    ("wait_for", "Wait for the next change without spending tokens."),
)


def clean(text) -> str:
    """One line of text for an agent: collapsed whitespace, contact details masked."""
    return CONTACT.sub("[contact withheld]", " ".join(str(text or "").split()))


def short(text, limit: int) -> str:
    value = clean(text)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


class AgentEnvironment:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    # ---- parts -------------------------------------------------------------------------------------------------

    def walk(self, site_id: str) -> dict | None:
        rows = query(self.store, "patrol", order="json_extract(body, '$.startedAt') DESC", limit=1, property_id=site_id)
        patrol = rows[0] if rows else None
        if not patrol:
            return None
        walking = patrol.get("state") == "running"
        tag = patrol.get("currentAssetTag") if walking else None
        name = None
        if tag:
            try:
                name = self.service.reality.component_by_tag(site_id, tag).get("name")
            except Exception:  # an unregistered tag only loses its name
                name = None
        route = patrol.get("route") or []
        done = int(patrol.get("stopIndex") or 0)
        return dict(state=patrol.get("state"), agentId=patrol.get("agentId"), agentName=patrol.get("agentName"),
                    stopIndex=min(done + 1, len(route)) if walking else done, stops=len(route), assetTag=tag, assetName=name,
                    moving=walking, startedAt=patrol.get("startedAt"))

    def frames(self, site_id: str) -> list[dict]:
        rows = query(self.store, "eye_frame", order="json_extract(body, '$.at') DESC", limit=MAX_FRAMES, property_id=site_id)
        out = []
        for frame in rows:
            frame_id = frame["id"]
            labels = query(self.store, "patrol_label", "json_extract(body, '$.frameId') = ? OR json_extract(body, '$.mark.frameId') = ?",
                           (frame_id, frame_id), property_id=site_id)
            seen, marks = set(), []
            for label in labels:
                if label["assetTag"] in seen:
                    continue
                seen.add(label["assetTag"])
                mark = label.get("mark") if isinstance(label.get("mark"), dict) else None
                marks.append(dict(assetTag=label["assetTag"], verdict=label.get("verdict"), color=label.get("color"), title=label.get("title"),
                                  reasons=[short(r, 200) for r in (label.get("reasons") or [])[:4]],
                                  mark=dict(x=mark.get("x"), y=mark.get("y"), note=short(mark.get("note"), 120)) if mark and mark.get("x") is not None else None))
            params = frame.get("params") if isinstance(frame.get("params"), dict) else {}
            pins = [p.get("assetTag") for p in frame.get("visiblePins") or [] if isinstance(p, dict) and not p.get("occluded")]
            out.append(dict(id=frame_id, url=frame.get("url") or f"/api/eye/frames/{frame_id}.jpg", assetTag=params.get("assetTag") or (pins[0] if pins else None),
                            at=frame.get("at"), actorName=frame.get("actorName") or frame.get("actor"), labels=marks))
        return out

    def labels(self, site_id: str) -> list[dict]:
        return [dict(assetTag=label["assetTag"], assetName=label.get("assetName"), verdict=label.get("verdict"), color=label.get("color"),
                     title=label.get("title"), reasons=[short(r, 200) for r in (label.get("reasons") or [])[:4]],
                     regulationIds=list(label.get("regulationIds") or []), frameUrl=label.get("frameUrl"), at=label.get("at"))
                for label in self.service.patrols.labels(site_id)]

    def readings(self, site_id: str) -> list[dict]:
        keys = ("key", "label", "assetTag", "unit", "value", "previous", "delta", "trend", "state", "spec")
        return [{k: reading.get(k) for k in keys} for reading in self.service.patrols.readings(site_id)]

    @staticmethod
    def obligation(item: dict) -> dict:
        return dict(id=item["id"], title=short(item.get("title"), 200), assetTag=item.get("assetTag"), status=item.get("status"), dueAt=item.get("dueAt"),
                    daysOverdue=overdue_days(item) if item.get("status") == "overdue" else None, dueInDays=due_in_days(item),
                    blockedReason=short(item.get("blockedReason"), 200) or None, regulationIds=list(item.get("regulationIds") or []))

    def inspection(self, site_id: str) -> dict | None:
        rows = query(self.store, "inspection", order="json_extract(body, '$.startedAt') DESC", limit=1, property_id=site_id)
        record = rows[0] if rows else None
        if not record:
            return None
        primary = record.get("primary") or {}
        return dict(id=record["id"], state=record.get("state"), primary=primary.get("title"), alsoNoted=list(record.get("alsoNoted") or [])[:4],
                    steps=[s.get("name") for s in record.get("steps") or []], summary=short(record.get("summary"), 300) or None,
                    startedAt=record.get("startedAt"), finishedAt=record.get("finishedAt"))

    def tours(self, site_id: str) -> list[dict]:
        rows = query(self.store, "site_tour", order="json_extract(body, '$.startedAt') DESC", limit=MAX_TOURS, property_id=site_id)
        return [dict(id=t["id"], state=t.get("state"), requesterName=t.get("requesterName"), stops=len(t.get("stops") or []),
                     findings=len(t.get("findings") or []), summary=short(t.get("summary"), 300) or None, startedAt=t.get("startedAt"),
                     finishedAt=t.get("finishedAt")) for t in rows]

    def logs(self, site_id: str) -> list[dict]:
        marks = ",".join("?" for _ in QUIET_TYPES)
        rows = query(self.store, "change", f"json_extract(body, '$.type') NOT IN ({marks})", QUIET_TYPES,
                     order="json_extract(body, '$.version') DESC", limit=MAX_LOGS * 2, property_id=site_id)
        out = []
        for change in rows:
            text = clean(change.get("summary"))
            if not text or MACHINERY.search(text):
                continue
            out.append(dict(at=change.get("at"), type=change.get("type"), summary=short(text, 300)))
            if len(out) >= MAX_LOGS:
                break
        return out

    # ---- the view -----------------------------------------------------------------------------------------------

    def view(self, site_id: str) -> dict:
        site = self.service.require_property(site_id)
        obligations = self.service.people.obligations(site_id)
        issues = self.service.patrols.open_issues(site_id)
        readings = self.readings(site_id)
        crew = self.store.all("crew_member", site_id)
        compliant = sum(1 for o in obligations if o.get("status") in ("ok", "due_soon"))
        checked = next((r for r in readings if str(r.get("key") or "").startswith("checked_in")), None)
        checked_value = checked.get("value") if checked else None
        summary = dict(compliancePercent=round(100.0 * compliant / len(obligations), 1) if obligations else None, openIssues=len(issues),
                       overdue=sum(1 for o in obligations if o.get("status") == "overdue"),
                       blocked=sum(1 for o in obligations if o.get("status") == "blocked"),
                       employeesCheckedIn=int(round(checked_value)) if isinstance(checked_value, (int, float)) else None,
                       crewOnShift=sum(1 for c in crew if c.get("onShift")))
        flagged = [o for o in obligations if o.get("status") in BAD_STATUSES + ("due_soon",)]
        flagged.sort(key=lambda o: (0 if o.get("status") == "blocked" else 1 if o.get("status") == "overdue" else 2, o.get("dueAt") or ""))
        view = dict(siteId=site_id, siteName=site.get("name"), at=now(), summary=summary, walk=self.walk(site_id), eye=dict(frames=self.frames(site_id)),
                    labels=self.labels(site_id), readings=readings, obligations=[self.obligation(o) for o in flagged],
                    issues=[dict(id=i["id"], kind=i.get("kind"), severity=i.get("severity"), assetTag=i.get("assetTag"), summary=short(i.get("summary"), 300),
                                 at=i.get("at")) for i in sorted(issues, key=lambda i: i.get("at") or "", reverse=True)],
                    inspection=self.inspection(site_id), tours=self.tours(site_id), logs=self.logs(site_id),
                    tools=[dict(name=name, purpose=purpose) for name, purpose in TOOLS])
        view["markdown"] = self.markdown(view)
        return view

    # ---- markdown -------------------------------------------------------------------------------------------------

    @staticmethod
    def markdown(v: dict) -> str:
        s = v["summary"]
        lines = [f"# {v['siteName']} ({v['siteId']}): what the agents see", ""]
        parts = []
        if s["compliancePercent"] is not None:
            parts.append(f"compliance {s['compliancePercent']:g} % ({s['overdue']} overdue, {s['blocked']} blocked)")
        parts.append(f"{s['openIssues']} open issue{'s' if s['openIssues'] != 1 else ''}")
        if s["employeesCheckedIn"] is not None:
            parts.append(f"{s['employeesCheckedIn']} employees checked in")
        parts.append(f"{s['crewOnShift']} crew on shift")
        lines.append("Now: " + ", ".join(parts) + ".")
        walk = v["walk"]
        if walk and walk["moving"]:
            where = f" at {walk['assetTag']}" + (f" ({walk['assetName']})" if walk.get("assetName") else "") if walk.get("assetTag") else ""
            lines.append(f"Walking: {walk['agentName']}, stop {walk['stopIndex']} of {walk['stops']}{where}.")
        elif walk:
            lines.append(f"Last walk: {walk['agentName']}, {walk['stops']} stops ({walk['state']}).")
        lines += ["", "## What the eye sees (latest frames)"]
        if not v["eye"]["frames"]:
            lines.append("- No frames yet: eye_look or eye_go_to(assetTag) renders one.")
        for frame in v["eye"]["frames"]:
            seen = "; ".join(f"{l['assetTag']} {l['title'] or ''}".strip() + (f": {l['reasons'][0]}" if l["reasons"] and l["verdict"] == "bad" else "")
                             + (f" (marked at x {l['mark']['x']:.2f}, y {l['mark']['y']:.2f}: {l['mark']['note']})" if l.get("mark") else "")
                             for l in frame["labels"])
            lines.append(f"- {frame['id']} ({frame['url']}): {frame['assetTag'] or 'no asset'} by {frame['actorName'] or 'an agent'} at {frame['at'] or '?'}"
                         + (f". {seen}" if seen else ""))
        bad = [l for l in v["labels"] if l["verdict"] == "bad"]
        good = [l for l in v["labels"] if l["verdict"] != "bad"]
        lines += ["", f"## Labels: {len(bad)} look bad, {len(good)} look good"]
        for label in bad:
            lines.append(f"- BAD {label['assetTag']} {label['assetName'] or ''}: " + "; ".join(label["reasons"][:2]))
        if good:
            lines.append("- Good: " + ", ".join(label["assetTag"] for label in good))
        if v["obligations"]:
            lines += ["", "## Obligations blocked, overdue or due soon"]
            for o in v["obligations"]:
                state = ("blocked" + (f": {o['blockedReason']}" if o["blockedReason"] else "")) if o["status"] == "blocked" else (
                    f"overdue by {o['daysOverdue']} days" if o["status"] == "overdue" and o["daysOverdue"] is not None else
                    f"due in {o['dueInDays']} days" if o["dueInDays"] is not None else o["status"])
                lines.append(f"- {o['assetTag'] or '-'} {o['title']}: {state}" + (f" [{', '.join(o['regulationIds'][:2])}]" if o["regulationIds"] else ""))
        if v["issues"]:
            lines += ["", "## Open issues"]
            lines += [f"- {i['id']} ({i['severity']}, {i['assetTag'] or '-'}): {short(i['summary'], 160)}" for i in v["issues"][:8]]
        out_of_band = [r for r in v["readings"] if r.get("state") in ("high", "low")]
        lines += ["", f"## Readings: {len(v['readings'])} live" + (f", {len(out_of_band)} out of band" if out_of_band else ", all inside their bands")]
        for r in (out_of_band or v["readings"])[:8]:
            arrow = {"up": "↑", "down": "↓"}.get(r.get("trend"), "→")
            lines.append(f"- {r.get('assetTag') or '-'} {r.get('label') or r.get('key')}: {r.get('value')} {r.get('unit') or ''} {arrow} ({r.get('state') or 'normal'})".replace("  ", " "))
        if v["inspection"]:
            i = v["inspection"]
            lines += ["", f"## Latest inspection ({i['state']})", f"- {i['primary'] or 'nothing outstanding'}" + (f"; steps: {', '.join(i['steps'])}" if i["steps"] else "")]
        if v["tours"]:
            lines += ["", "## Site tours"]
            lines += [f"- {t['id']} for {t['requesterName']} ({t['state']}): {t['stops']} stops, {t['findings']} look bad" for t in v["tours"]]
        if v["logs"]:
            lines += ["", "## Recent log"]
            lines += [f"- {(l['at'] or '')[11:16]} {l['type']}: {short(l['summary'], 160)}" for l in v["logs"][:10]]
        lines += ["", "## Tools"]
        lines += [f"- {t['name']}: {t['purpose']}" for t in v["tools"]]
        return "\n".join(lines)
