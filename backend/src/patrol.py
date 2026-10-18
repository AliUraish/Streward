"""Walkthroughs (contract 7 §1): the site's Engineer walks the 3D scan with the agent eye, stop by stop, and labels every
asset it looks at: green "Looks good" or blue "Looks bad".

- `POST /api/patrols {siteId, agentId?, route?, paceSeconds?}` (operator, director, the site's manager or engineer) starts a
  walkthrough, or returns the one already running at the site. The walker is the site's Engineer (`agentId` may name the
  site's manager or the director instead). Default route: up to 10 assets: placed pins first (`pinSource: placed` or a
  stored `viewPose`), any asset with a gap (overdue or blocked obligation, open issue, reading out of band) always in,
  then the most important others (assets with obligations or open issues, then monitored assets), ordered as a walking
  path (nearest neighbour from the scan's initial camera). Pace `paceSeconds` (default 8 s, `STEWARD_PATROL_PACE_SECONDS`)
  per stop while the backend runs its workers; inline with no sleeping otherwise.
- Each stop: `eye.act_sync(site, "go_to", {assetTag}, walker)` (cold-start aware; skipped with the reason when no
  renderer is open and the headless worker is off; an eye failure keeps the walk going with `frameId: null`), then a
  deterministic assessment and a `patrol_label` record. **Bad** when an obligation on the asset is overdue or blocked
  (`compliance: true`), an open stored issue sits on it, or a live reading is outside its band; **good** otherwise, with
  the evidence in words. No model is called.
- Changes of type `patrol`, extras `{patrolId, status: started|stop|completed|canceled|failed, assetTag, verdict, labelId,
  stop, stops}`. At the end the walker messages the Site Manager with the summary (an A2A message conversation, which the
  manager acknowledges) and every bad compliance label starts a compliance alert (`compliance_alerts.py`), once per
  obligation per 24 h; later walkthroughs reuse the alert.
- `GET /api/properties/{siteId}/labels` returns the latest label per asset.
"""
from __future__ import annotations

import math
import threading
import time

from .agents import DIRECTOR, OPERATOR, authorize, display_name, engineer_id, manager_id, parse_actor
from .compliance_alerts import (BAD_STATUSES, ComplianceAlertService, categorize, cite_short, due_in_days, place_of, plural, state_phrase)
from .env import env
from .errors import RealityError
from .sites import SITE_BY_ID
from .store import now, uid

DEFAULT_PACE_SECONDS = 8.0
MAX_DEFAULT_STOPS = 10
MAX_ROUTE = 24
LABEL_KEEP_PER_SITE = 400
EYE_FAILURES_BEFORE_SKIP = 2
COMPLIANCE_ISSUE_KINDS = {"inspection_overdue", "certificate_expired", "walkway_closure", "permit_blocked", "alteration_permit", "visitor_route",
                          "compliance_overdue", "compliance_blocked"}
MEASURES = {"pressure_bar": "Pressure", "flow_m3h": "Flow", "temperature_c": "Temperature", "level_pct": "Level", "vibration_mms": "Vibration",
            "power_kw": "Power", "humidity_pct": "Humidity", "crack_width_mm": "Crack width"}


def number(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def quantity(value, unit: str | None) -> str:
    unit = unit or ""
    return f"{number(value)}{unit}" if unit == "%" else f"{number(value)} {unit}".strip()


def reading_words(reading: dict) -> tuple[bool, str]:
    """(bad, words) for one live reading: "PG-601 4.1 bar, above the 3.5 bar limit" or "Pressure 2.61 bar, inside 1.5 to 3.5 bar"."""
    band = reading.get("spec") or {}
    unit, value = reading.get("unit"), reading.get("value")
    measure = MEASURES.get(str(reading.get("key", "")).split(":")[0], "Reading")
    if reading.get("state") == "high":
        limit = f"the {quantity(band['max'], unit)} limit" if band.get("max") is not None else "its band"
        return True, f"{reading['assetTag']} {quantity(value, unit)}, above {limit}"
    if reading.get("state") == "low":
        limit = f"the {quantity(band['min'], unit)} minimum" if band.get("min") is not None else "its band"
        return True, f"{reading['assetTag']} {quantity(value, unit)}, below {limit}"
    if band.get("min") is not None and band.get("max") is not None:
        return False, f"{measure} {quantity(value, unit)}, inside {number(band['min'])} to {quantity(band['max'], unit)}"
    if band.get("max") is not None:
        return False, f"{measure} {quantity(value, unit)}, under the {quantity(band['max'], unit)} limit"
    return False, f"{measure} {quantity(value, unit)}"


def pin_point(component: dict) -> tuple[float, float, float] | None:
    pin = component.get("pin")
    if isinstance(pin, dict) and all(isinstance(pin.get(k), (int, float)) and not isinstance(pin.get(k), bool) for k in ("x", "y", "z")):
        return float(pin["x"]), float(pin["y"]), float(pin["z"])
    return None


class PatrolService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self.threads: dict[str, threading.Thread] = {}
        self.alerts = ComplianceAlertService(service)
        if service.start_workers:
            self.recover()

    def recover(self) -> int:
        """A walkthrough left `running` by an earlier backend process has no thread any more: mark it failed, so the site can
        be walked again and the autoplayer does not wait on it. Its queued alerts are marked failed too."""
        count = 0
        for patrol in self.store.all("patrol"):
            if patrol.get("state") == "running":
                patrol.update(state="failed", finishedAt=now(), currentAssetTag=None, error="Interrupted by a backend restart; walk the site again.")
                self._save(patrol)
                count += 1
        return count + self.alerts.recover()

    def close(self) -> None:
        self._stop.set()
        self.alerts.close()
        for thread in list(self.threads.values()):
            if thread.is_alive():
                thread.join(timeout=2)

    # ---- records -----------------------------------------------------------------------------------------

    def get(self, patrol_id: str) -> dict:
        record = self.store.get("patrol", patrol_id)
        if not record:
            raise RealityError("Walkthrough not found.", "NOT_FOUND", "List walkthroughs with GET /api/patrols?siteId=.", 404)
        return record

    def list(self, site_id: str | None = None, limit: int = 50) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        records = self.store.all("patrol", site_id) if site_id else self.store.all("patrol")
        return sorted(records, key=lambda r: r["startedAt"], reverse=True)[:max(1, int(limit))]

    def running(self, site_id: str | None = None) -> list[dict]:
        records = self.store.all("patrol", site_id) if site_id else self.store.all("patrol")
        return sorted((r for r in records if r.get("state") == "running"), key=lambda r: r["startedAt"], reverse=True)

    def active(self, patrol: dict) -> bool:
        """The walkthrough, or one of the compliance alerts it started, is still playing."""
        if patrol.get("state") == "running":
            return True
        for alert_id in patrol.get("alertIds") or []:
            alert = self.store.get("owner_alert", alert_id)
            if alert and alert.get("state") in ("queued", "running"):
                return True
        return False

    def busy(self) -> str | None:
        """What is playing now (for the autoplayer): a running walkthrough, or a compliance alert still in its steps."""
        for patrol in self.running():
            return f"a walkthrough of {patrol['place']} is running" + ("" if patrol.get("origin") == "autoplay" else " (started by hand)")
        for alert in self.alerts.active():
            return f"the compliance alert for {alert.get('assetTag') or alert['obligationId']} is running"
        return None

    def _save(self, patrol: dict) -> dict:
        patrol["updatedAt"] = now()
        self.store.put("patrol", patrol, patrol["siteId"])
        return patrol

    def _change(self, patrol: dict, summary: str, status: str, **extra) -> None:
        fields = dict(patrolId=patrol["id"], status=status, **{k: v for k, v in extra.items() if v is not None})
        self.service.reality.emit_change(patrol["siteId"], "patrol", patrol["id"], summary[:480], extra.get("assetTag"), extra=fields, fields=fields)

    # ---- route -------------------------------------------------------------------------------------------

    def open_issues(self, site_id: str) -> list[dict]:
        return [i for i in self.store.all("issue", site_id) if i.get("status") == "open"]

    def readings(self, site_id: str) -> list[dict]:
        try:
            return list(self.service.metrics.live_readings(site_id))
        except Exception:  # a metrics failure must not stop the walk; the label says what it checked
            return []

    def default_route(self, site_id: str) -> list[str]:
        components = self.service.reality.components(site_id)
        obligations = self.service.people.obligations(site_id)
        issues = self.open_issues(site_id)
        readings = self.readings(site_id)
        with_obligation = {o["assetTag"] for o in obligations if o.get("assetTag")}
        with_issue = {i["assetTag"] for i in issues if i.get("assetTag")}
        monitored = {r["assetTag"] for r in readings if r.get("assetTag")}
        gaps = ({o["assetTag"] for o in obligations if o.get("assetTag") and o.get("status") in BAD_STATUSES} | with_issue
                | {r["assetTag"] for r in readings if r.get("assetTag") and r.get("state") in ("high", "low")})

        def tier(component: dict) -> int | None:
            tag = component["tag"]
            placed = component.get("pinSource") == "placed" or bool(component.get("viewPose"))
            important = tag in with_obligation or tag in with_issue
            if placed and (important or tag in gaps):
                return 0
            if tag in gaps:
                return 1
            if placed and tag in monitored:
                return 2
            if placed:
                return 3
            if important:
                return 4
            if tag in monitored:
                return 5
            return None

        ranked = sorted(((t, index) for index, c in enumerate(components) if (t := tier(c)) is not None))
        chosen = [components[index] for _, index in ranked[:MAX_DEFAULT_STOPS]]
        return [c["tag"] for c in self.walk_order(site_id, chosen)]

    @staticmethod
    def walk_order(site_id: str, components: list[dict]) -> list[dict]:
        """Nearest neighbour by pin position, starting nearest the scan's initial camera; assets without a pin go last."""
        pinned = [c for c in components if pin_point(c)]
        rest = [c for c in components if not pin_point(c)]
        try:
            here = tuple(float(v) for v in SITE_BY_ID[site_id]["environment"]["cameraPresets"][0]["position"])
            if len(here) != 3:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            here = pin_point(min(pinned, key=lambda c: pin_point(c)[0])) if pinned else (0.0, 0.0, 0.0)
        order = []
        while pinned:
            index = min(range(len(pinned)), key=lambda i: math.dist(here, pin_point(pinned[i])))
            nearest = pinned.pop(index)
            order.append(nearest)
            here = pin_point(nearest)
        return order + rest

    def route(self, site_id: str, route: list | None = None) -> list[str]:
        if not route:
            tags = self.default_route(site_id)
        else:
            if not isinstance(route, list) or len(route) > MAX_ROUTE:
                raise RealityError(f"route takes at most {MAX_ROUTE} asset tags.", "INVALID_REQUEST", "Send route: [assetTag, ...] or omit it.")
            tags = list(dict.fromkeys(self.service.reality.component_by_tag(site_id, str(tag))["tag"] for tag in route))
        if not tags:
            raise RealityError("No assets to walk at this site.", "INVALID_REQUEST", "Pass route: [assetTag, ...].")
        return tags

    @staticmethod
    def walker(site_id: str, agent_id: str | None = None) -> str:
        if not agent_id:
            return engineer_id(site_id)
        agent = parse_actor(agent_id)
        if agent not in (engineer_id(site_id), manager_id(site_id), DIRECTOR):
            raise RealityError(f"{display_name(agent)} cannot walk {site_id}.", "INVALID_REQUEST",
                               "agentId is the site's engineer (the default), its manager or the Operations Director.")
        return agent

    @staticmethod
    def pace(value: float | None = None) -> float:
        if value is None:
            try:
                configured = float(env("STEWARD_PATROL_PACE_SECONDS", str(DEFAULT_PACE_SECONDS)) or DEFAULT_PACE_SECONDS)
            except ValueError:
                configured = DEFAULT_PACE_SECONDS
            return min(max(configured, 0.0), 120.0) if math.isfinite(configured) else DEFAULT_PACE_SECONDS
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = -1.0
        if not math.isfinite(value) or not 0 <= value <= 120:
            raise RealityError("paceSeconds must be between 0 and 120.", "INVALID_REQUEST", "Send paceSeconds: 8 (the default) or omit it.")
        return value

    # ---- lifecycle -----------------------------------------------------------------------------------------

    def start(self, site_id: str, actor: str = OPERATOR, agent_id: str | None = None, route: list | None = None,
              pace_seconds: float | None = None, origin: str = "manual") -> dict:
        prop = self.service.require_property(site_id)
        actor = authorize(actor, "eye", site_id)
        walker = self.walker(site_id, agent_id)
        pace = self.pace(pace_seconds)
        origin = origin if origin in ("manual", "autoplay") else "manual"
        with self.lock:
            running = self.running(site_id)
            if running:
                return running[0]
            tags = self.route(site_id, route)
            name, place = display_name(walker), place_of(site_id)
            patrol = dict(id=uid("ptl"), siteId=site_id, siteName=prop["name"], agentId=walker, agentName=name, state="running", origin=origin,
                          startedBy="autoplay" if origin == "autoplay" else actor, route=tags, stopIndex=0, stops=[], currentAssetTag=None,
                          place=place, line=f"{name} is starting a walkthrough of {place}: {plural(len(tags), 'stop')}", paceSeconds=pace,
                          counts=dict(good=0, bad=0), startedAt=now(), finishedAt=None, summary=None, alertIds=[], conversationId=None, error=None,
                          synthetic=True)
            self._save(patrol)
        self._change(patrol, f"{name} started a walkthrough of {place}: {plural(len(tags), 'stop')} ({', '.join(tags[:5])}"
                             + (", ..." if len(tags) > 5 else "") + ").", "started", stops=len(tags))
        self.service.ops.note(walker, f"Walkthrough of {place}: {plural(len(tags), 'stop')}", why="Walking the scan with the agent eye, labelling each asset")
        if self.service.start_workers:
            thread = threading.Thread(target=self._guarded, args=(patrol["id"], True), name=f"steward-patrol-{patrol['id']}", daemon=True)
            self.threads[patrol["id"]] = thread
            thread.start()
        else:
            self.run(patrol["id"], realtime=False)
        return self.get(patrol["id"])

    def cancel(self, patrol_id: str, actor: str) -> dict:
        patrol = self.get(patrol_id)
        actor = authorize(actor, "eye", patrol["siteId"])
        with self.lock:
            patrol = self.get(patrol_id)
            if patrol["state"] != "running":
                return patrol
            done, total = patrol.get("stopIndex", 0), len(patrol["route"])
            patrol.update(state="canceled", finishedAt=now(), currentAssetTag=None, canceledBy=actor,
                          summary=f"Canceled after {done} of {plural(total, 'stop')}.", line=f"{patrol['agentName']} stopped walking {patrol['place']}")
            self._save(patrol)
        self._change(patrol, f"Walkthrough of {patrol['place']} canceled by {display_name(actor)} after {done} of {plural(total, 'stop')}.", "canceled",
                     stop=done, stops=total)
        self.service.ops.note(patrol["agentId"], None)
        return patrol

    def _guarded(self, patrol_id: str, realtime: bool) -> None:
        try:
            self.run(patrol_id, realtime)
        except Exception as error:  # never leave a walkthrough dangling
            failed = None
            with self.lock:
                patrol = self.store.get("patrol", patrol_id)
                if patrol and patrol["state"] == "running":
                    patrol.update(state="failed", error=f"{type(error).__name__}: {str(error)[:200]}", finishedAt=now(), currentAssetTag=None)
                    failed = self._save(patrol)
            if failed:
                self._change(failed, f"Walkthrough of {failed['place']} failed: {failed['error']}", "failed", stop=failed.get("stopIndex"),
                             stops=len(failed["route"]))
                self.service.ops.note(failed["agentId"], None)
        finally:
            self.threads.pop(patrol_id, None)

    def run(self, patrol_id: str, realtime: bool = False) -> dict:
        patrol = self.get(patrol_id)
        site, walker, route = patrol["siteId"], patrol["agentId"], list(patrol["route"])
        skip_eye, failures = None, 0
        for index, tag in enumerate(route):
            with self.lock:
                patrol = self.get(patrol_id)
                if patrol["state"] != "running":
                    return patrol
                patrol.update(currentAssetTag=tag, line=f"{patrol['agentName']} is walking {patrol['place']}: stop {index + 1} of {len(route)}, {tag}")
                self._save(patrol)
            self.service.ops.note(walker, f"Walkthrough of {patrol['place']}: stop {index + 1} of {len(route)}, {tag}", why="Labelling each asset it looks at")
            began = time.monotonic()
            if skip_eye:
                frame_id, frame_url, note = None, None, skip_eye
            else:
                frame_id, frame_url, note = self.look(site, tag, walker)
                failures = 0 if frame_id else failures + 1
                if failures >= EYE_FAILURES_BEFORE_SKIP:
                    skip_eye = note  # the eye is not answering: label the rest of the route without frames
            label = self.label(patrol, index, tag, frame_id, frame_url, note)
            with self.lock:
                patrol = self.get(patrol_id)
                if patrol["state"] != "running":
                    return patrol
                patrol["stops"].append(dict(assetTag=tag, labelId=label["id"], verdict=label["verdict"], frameId=frame_id, at=label["at"],
                                            reason=(label["reasons"] or [None])[0]))
                patrol["stopIndex"] = index + 1
                patrol.setdefault("counts", {})[label["verdict"]] = patrol.get("counts", {}).get(label["verdict"], 0) + 1
                self._save(patrol)
            self._change(patrol, f"{patrol['agentName']} at {tag} (stop {index + 1} of {len(route)}): {label['title']}"
                                 + (f": {label['reasons'][0]}" if label["reasons"] else "") + ".", "stop", assetTag=tag, verdict=label["verdict"],
                         labelId=label["id"], stop=index + 1, stops=len(route), frameId=frame_id)
            if realtime and index < len(route) - 1:
                remaining = float(patrol.get("paceSeconds") or 0) - (time.monotonic() - began)
                if remaining > 0 and self._stop.wait(remaining):
                    return self.get(patrol_id)
        return self.finish(patrol_id, realtime)

    def finish(self, patrol_id: str, realtime: bool = False) -> dict:
        queued: list[str] = []
        with self.lock:
            patrol = self.get(patrol_id)
            if patrol["state"] != "running":
                return patrol
            site = patrol["siteId"]
            labels = [l for l in (self.store.get("patrol_label", stop["labelId"], site) for stop in patrol["stops"]) if l]
            bad = [l for l in labels if l["verdict"] == "bad"]
            summary = (f"Walked {patrol['place']}: {len(labels)} checked, {len(labels) - len(bad)} look good, {len(bad)} look bad"
                       + ((": " + "; ".join(f"{l['assetTag']}: {l['reasons'][0]}" for l in bad[:4] if l["reasons"]) + ("; ..." if len(bad) > 4 else "") + ".")
                          if bad else "."))
            obligations = {o["id"]: o for o in self.service.people.obligations(site)}
            alert_ids = []
            for label in bad:
                if not label.get("compliance"):
                    continue
                for obligation_id in label.get("obligationIds") or []:
                    obligation = obligations.get(obligation_id)
                    if not obligation or obligation.get("status") not in BAD_STATUSES:
                        continue
                    alert, reused = self.alerts.open(site, label, obligation, patrol, patrol["agentId"], patrol.get("origin", "manual"))
                    alert_ids.append(alert["id"])
                    if not reused:
                        queued.append(alert["id"])
            patrol.update(state="completed", finishedAt=now(), summary=summary, alertIds=list(dict.fromkeys(alert_ids)), currentAssetTag=None,
                          line=f"{patrol['agentName']} walked {patrol['place']}: {len(labels)} checked, {len(bad)} look bad")
            self._save(patrol)
        self._change(patrol, f"Walkthrough completed. {summary}", "completed", stop=len(labels), stops=len(patrol["route"]),
                     alerts=len(patrol["alertIds"]) or None)
        self.report(patrol)
        self.service.ops.note(patrol["agentId"], None)
        self.prune_labels(site)
        for alert_id in queued:
            if self._stop.is_set():
                break
            self.alerts.run(alert_id, realtime)
        return self.get(patrol_id)

    def report(self, patrol: dict) -> dict | None:
        """The walker's message to the Site Manager (the director when the manager walked), acknowledged by the recipient."""
        site, walker = patrol["siteId"], patrol["agentId"]
        recipient = manager_id(site) if walker != manager_id(site) else DIRECTOR
        alerts = [a for a in (self.store.get("owner_alert", alert_id) for alert_id in patrol.get("alertIds") or []) if a]
        tags = sorted({a["assetTag"] for a in alerts if a.get("assetTag")})
        text = patrol["summary"] + (f" Compliance is taking {', '.join(tags)} to the owner." if tags else "")
        try:
            conversation = self.service.conversations.message(walker, recipient, f"Walkthrough of {patrol['place']}", text, site_ids=[site],
                                                              data=dict(patrolId=patrol["id"]), synthetic=True)
            self.service.conversations.answer(conversation["id"], recipient, "Thanks. I'll take the decision when Compliance calls." if tags else
                                              "Thanks. Nothing for the owner from this walk.")
        except RealityError:
            return None
        with self.lock:
            fresh = self.get(patrol["id"])
            fresh["conversationId"] = conversation["id"]
            self._save(fresh)
        return conversation

    # ---- stops ---------------------------------------------------------------------------------------------

    def look(self, site_id: str, tag: str, walker: str) -> tuple[str | None, str | None, str | None]:
        """(frameId, frameUrl, note): drive the eye to the asset, or say why there is no frame."""
        eye = self.service.eye
        if not eye.fresh(site_id) and not eye.worker.enabled:
            return None, None, "no renderer is open and the headless worker is off"
        try:
            timeout = float(env("STEWARD_PATROL_EYE_TIMEOUT", "20") or 20)
            looked = eye.act_sync(site_id, "go_to", dict(assetTag=tag), walker, timeout=timeout)
        except RealityError as error:
            return None, None, f"eye unavailable ({error.detail[:160]})"
        frame_id = (looked or {}).get("frameId")
        if not frame_id:
            return None, None, "the eye returned no frame"
        record = self.store.get("eye_frame", frame_id, site_id) or {}
        return frame_id, record.get("url") or looked.get("frameUrl") or f"/api/eye/frames/{frame_id}.jpg", None

    def label(self, patrol: dict, index: int, tag: str, frame_id: str | None, frame_url: str | None, note: str | None) -> dict:
        site = patrol["siteId"]
        component = self.service.reality.component_by_tag(site, tag)
        assessment = self.assess(site, component)
        reasons = list(assessment["reasons"])
        if not frame_id:
            reasons.append(f"No eye frame: {note or 'the eye did not answer'}")
        bad = assessment["verdict"] == "bad"
        point = pin_point(component)
        label = dict(id=uid("lbl"), patrolId=patrol["id"], siteId=site, assetTag=tag, assetName=component.get("name"), verdict=assessment["verdict"],
                     color="blue" if bad else "green", title="Looks bad" if bad else "Looks good", reasons=reasons, compliance=assessment["compliance"],
                     regulationIds=assessment["regulationIds"], obligationId=assessment["obligationId"], obligationIds=assessment["obligationIds"],
                     issueId=assessment["issueId"], frameId=frame_id, frameUrl=frame_url if frame_id else None,
                     world=dict(x=point[0], y=point[1], z=point[2]) if point else None, agentId=patrol["agentId"], agentName=patrol["agentName"],
                     stop=index + 1, at=now(), synthetic=True)
        self.store.put("patrol_label", label, site)
        self.service.telemetry.record(patrol["agentId"], "tool", "label_asset", tokens=40, site_id=site, synthetic=True,
                                      detail=(f"{tag}: {label['title']}" + (f": {reasons[0]}" if reasons else ""))[:200])
        return label

    def assess(self, site_id: str, component: dict, obligations: list[dict] | None = None, issues: list[dict] | None = None,
               readings: list[dict] | None = None) -> dict:
        """The deterministic verdict for one asset from its obligations, its open stored issues and its live readings."""
        tag = component["tag"]
        obligations = [o for o in (self.service.people.obligations(site_id) if obligations is None else obligations) if o.get("assetTag") == tag]
        issues = [i for i in (self.open_issues(site_id) if issues is None else issues) if i.get("assetTag") == tag]
        readings = [r for r in (self.readings(site_id) if readings is None else readings) if r.get("assetTag") == tag]
        known = self.service.regulations.by_id()
        obligation_bad, obligation_good, bad_obligations = [], [], []
        for obligation in obligations:
            _, noun = categorize(obligation)
            first = next((known[rid] for rid in obligation.get("regulationIds") or [] if rid in known), None)
            cite = cite_short(first) if first else (obligation.get("ruleRef") or "site rule pack")
            if obligation.get("status") in BAD_STATUSES:
                bad_obligations.append(obligation)
                if obligation["status"] == "blocked":
                    why = (obligation.get("blockedReason") or "").rstrip(". ")
                    obligation_bad.append(f"{noun} blocked" + (f": {why}" if why else "") + f" ({cite})")
                else:
                    obligation_bad.append(f"{noun} {state_phrase(obligation)} ({cite})")
            else:
                days = due_in_days(obligation)
                if days is None:
                    obligation_good.append(f"{noun} current")
                elif obligation.get("status") == "due_soon":
                    obligation_good.append(f"{noun} due " + ("today" if days == 0 else f"in {plural(days, 'day')}"))
                else:
                    obligation_good.append(f"{noun} current, next due in {plural(days, 'day')}")
        bad_ids = {o["id"] for o in bad_obligations}
        issue_bad, compliance = [], bool(bad_obligations)
        for issue in issues:
            if issue.get("obligationId") or issue.get("kind") in COMPLIANCE_ISSUE_KINDS:
                compliance = True
            if issue.get("obligationId") in bad_ids:
                continue  # the obligation reason already says it
            issue_bad.append(f"Open issue: {' '.join(str(issue.get('summary') or issue['kind']).split())[:160]}")
        reading_bad, reading_good = [], []
        for reading in readings:
            is_bad, words = reading_words(reading)
            (reading_bad if is_bad else reading_good).append(words)
        bad = obligation_bad + reading_bad + issue_bad
        good = reading_good + obligation_good + ([] if issues else ["No open issues"])
        if bad_obligations:
            regulation_ids = list(dict.fromkeys(rid for o in bad_obligations for rid in o.get("regulationIds") or []))
        elif issues:
            regulation_ids = list(dict.fromkeys(rid for i in issues for rid in self.service.regulations.for_issue(i)))
        else:
            regulation_ids = list(dict.fromkeys(rid for o in obligations for rid in o.get("regulationIds") or []))
        return dict(verdict="bad" if bad else "good", reasons=bad or good, compliance=compliance and bool(bad), regulationIds=regulation_ids,
                    obligationId=(bad_obligations or obligations or [{}])[0].get("id"), obligationIds=[o["id"] for o in bad_obligations],
                    issueId=issues[0]["id"] if issues else None)

    # ---- labels --------------------------------------------------------------------------------------------

    def labels(self, site_id: str) -> list[dict]:
        """The latest label per asset at the site, newest first."""
        self.service.require_property(site_id)
        latest: dict[str, dict] = {}
        for label in self.store.all("patrol_label", site_id):  # insertion order: a later row wins a tie
            current = latest.get(label["assetTag"])
            if current is None or label["at"] >= current["at"]:
                latest[label["assetTag"]] = label
        return sorted(latest.values(), key=lambda l: l["at"], reverse=True)

    def prune_labels(self, site_id: str, keep: int = LABEL_KEEP_PER_SITE) -> int:
        """Keep the newest `keep` labels and the latest one per asset; walkthroughs run all day under autoplay."""
        labels = self.store.all("patrol_label", site_id)
        if len(labels) <= keep:
            return 0
        latest = {}
        for label in labels:
            latest[label["assetTag"]] = label["id"]
        keep_ids = set(latest.values()) | {label["id"] for label in labels[-keep:]}
        drop = [(label["id"], site_id) for label in labels if label["id"] not in keep_ids]
        with self.store.lock, self.store.connect() as db:
            db.executemany("DELETE FROM records WHERE kind='patrol_label' AND id=? AND property_id=?", drop)
        return len(drop)
