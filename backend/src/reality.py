"""Reality layer: facts, attestations, work items, dispatches, changes and subscriptions.

Composed into PropertyService and sharing its Store. Resolver policy, dispatch, escalation, inbound
routing and the simulated sensor feed live here. Nothing here pretends a provider succeeded: a dispatch
without a provider receipt carries `providerRef: null` and says why in its body.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .env import env
from .errors import RealityError
from .mirror import Mirror
from .providers import InkboxAdapter, ProviderNotConfigured, external_messages_allowed
from .signing import VERIFIER_VERSION, Signer, verify as verify_signature
from .sites import DEMO_SITE, SITE2, SITE_BY_ID, SITE_BY_PREFIX
from .specs import DEFAULT_FOOTPRINT_RADIUS_M, FOOTPRINT_RADIUS_M, SPECS, spec_for, spec_kind, spec_table, specs_of, ttl_for_class
from .store import now, uid
from .verify import Observation, REFERENCE_RE, TAG_RE, iso, parse_time, relative_position, verify_observation

OPEN_STATES = ("open", "dispatched", "waiting", "needs_clarification", "escalated")
CLOSED_STATES = ("resolved", "rejected", "expired")
ESCALATION_THRESHOLDS = ((1, 0.5), (2, 0.7), (3, 0.85), (4, 0.95))
NUMBER_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(bar|°\s?c|c\b|%|percent|psi|deg)?", re.IGNORECASE)
SCHEDULER_INTERVAL_SECONDS = 30
SENSOR_PERIOD_SECONDS = 600
# Seeded demo conditions at the demo site so the mission's restart set has exactly one unknown (P-101.pressure_bar).
DEMO_CONDITION_SEEDS = (("DB-401", "status", "normal"), ("FE-1001", "pressure_ok", "yes"), ("D-1101", "closed", "yes"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def age_seconds(observed_at: str, reference: datetime | None = None) -> float:
    observed = parse_time(observed_at)
    if observed is None:
        return float("inf")
    return max(0.0, ((reference or utcnow()) - observed).total_seconds())


def public_value(value):
    """Facts carry str | number | bool. Normalise enum text to lower case and numeric strings to numbers."""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            number = float(text)
            return int(number) if number.is_integer() and "." not in text else number
        return text
    return value


def simulated_temperature(tag: str, moment: datetime | None = None) -> float:
    """Deterministic drift around 21 °C: a slow sine per sensor tag, resolved to the minute."""
    moment = moment or utcnow()
    minutes = int(moment.timestamp() // 60)
    phase = int(hashlib.sha256(tag.encode()).hexdigest()[:4], 16) % 360
    return round(21.0 + 1.5 * math.sin(math.radians(phase) + minutes * 2 * math.pi / SENSOR_PERIOD_SECONDS * 60), 1)


def simulated_reading(tag: str, attribute: str, moment: datetime | None = None) -> float:
    """Deterministic drift for the simulated sensor feed: temperature around 21 °C (as before), relative humidity
    around 56 % (inside Tomioka's 40-65 % preservation band) and ground acceleration around 0.6 gal."""
    if attribute == "temperature_c":
        return simulated_temperature(tag, moment)
    moment = moment or utcnow()
    minutes = int(moment.timestamp() // 60)
    phase = int(hashlib.sha256(f"{tag}:{attribute}".encode()).hexdigest()[:4], 16) % 360
    wave = math.sin(math.radians(phase) + minutes * 2 * math.pi / SENSOR_PERIOD_SECONDS * 60)
    if attribute == "humidity_pct":
        return round(56.0 + 3.0 * wave, 1)
    if attribute == "seismic_gal":
        return round(0.6 + 0.4 * wave, 2)
    return round(1.0 + 0.5 * wave, 2)


def identity_serial(property_id: str, tag: str) -> str:
    digest = hashlib.sha256(f"{property_id}:{tag}".encode()).hexdigest()[:6].upper()
    return f"{SITE2.get(property_id, property_id[:2].upper())}-{tag.replace('-', '')}-SN{digest}"


class RealityService:
    def __init__(self, service, start_workers: bool = True):
        self.service = service
        self.store = service.store
        self.signer = Signer(self.store.directory)
        self.mirror = Mirror(self.store)
        self.comms = InkboxAdapter()
        self.start_workers = start_workers
        self.lock = threading.RLock()
        self.delivery = ThreadPoolExecutor(max_workers=4, thread_name_prefix="steward-callback")
        self._stop = threading.Event()
        self._scheduler = None
        self.listeners: list = []  # callables (event: str, work_item: dict, extra: dict) → None; see missions.py
        self.change_listeners: list = []  # callables (change: dict, work_item: dict | None, extra: dict) → None; see waits.py
        self.seed_facts()
        if start_workers:
            self._scheduler = threading.Thread(target=self._scheduler_loop, name="steward-reality-scheduler", daemon=True)
            self._scheduler.start()

    def close(self):
        self._stop.set()
        if self._scheduler and self._scheduler.is_alive():
            self._scheduler.join(timeout=2)
        self.delivery.shutdown(wait=True)
        self.mirror.close()

    # ---- scene helpers --------------------------------------------------------------------------------

    def components(self, property_id: str) -> list[dict]:
        return self.store.all("component", property_id)

    def component_by_tag(self, property_id: str, asset_tag: str) -> dict:
        self.service.require_property(property_id)
        tag = (asset_tag or "").strip().upper()
        for component in self.components(property_id):
            if component["tag"] == tag:
                return component
        raise RealityError(f"Asset {asset_tag} is not registered at property {property_id}.", "UNKNOWN_ASSET",
                           "Call list_components to find the registered tags.", 404)

    def put(self, kind: str, body: dict, property_id: str = ""):
        self.store.put(kind, body, property_id)
        self.mirror.put(kind, body, property_id)
        return body

    def next_version(self, property_id: str) -> int:
        with self.lock:
            current = int(self.store.meta(f"reality:version:{property_id}") or 0) + 1
            self.store.meta(f"reality:version:{property_id}", str(current))
            return current

    def version(self, property_id: str) -> int:
        return int(self.store.meta(f"reality:version:{property_id}") or 0)

    def next_sequence(self, property_id: str) -> int:
        with self.lock:
            current = int(self.store.meta(f"reality:seq:{property_id}") or 0) + 1
            self.store.meta(f"reality:seq:{property_id}", str(current))
            return current

    # ---- changes and subscriptions ----------------------------------------------------------------------

    def notify(self, event: str, work_item: dict | None, extra: dict | None = None):
        """Tell mission/A2A listeners about a work-item event. Listener failures become events, never exceptions."""
        for listener in list(self.listeners):
            try:
                listener(event, work_item, extra or {})
            except Exception as error:
                site = (work_item or {}).get("propertyId") or DEMO_SITE
                self.store.event(site, "atlas", "listener.failed", f"Listener failed on {event}", type(error).__name__)

    def emit_change(self, property_id: str, change_type: str, ref_id: str, summary: str, asset_tag: str | None = None,
                    work_item: dict | None = None, simulated: bool = False, extra: dict | None = None, fields: dict | None = None) -> dict:
        """`extra` goes to the change listeners (waits, the live HUD); `fields` are also stored on the Change itself
        (Tool Forge Changes carry toolId and status for the MCP and the dashboard)."""
        version = self.next_version(property_id)
        change = dict(id=f"{property_id}:{version}", version=version, type=change_type, propertyId=property_id,
                      refId=ref_id, summary=summary[:500], at=now())
        for key, value in (fields or {}).items():
            if key not in change and value is not None:
                change[key] = value
        if asset_tag:
            change["assetTag"] = asset_tag  # optional in the contract; clients reject an explicit null
        if simulated:
            change["simulated"] = True
        self.put("change", change, property_id)
        self.store.event(property_id, f"agent-{property_id}", "reality.change", f"{change_type} v{version}", summary[:500])
        for listener in list(self.change_listeners):
            try:
                listener(change, work_item, extra or {})
            except Exception as error:  # a waiter must never break the write path
                self.store.event(property_id, "atlas", "listener.failed", f"Change listener failed on {change_type}", type(error).__name__)
        # Callback subscribers are ordinary agents: a scenario's own step rows are not delivered (see changes()).
        subscriptions = self.store.all("subscription", property_id) if change_type != "scenario" else []
        if subscriptions:
            payload = {"event": "steward.change", "change": change}
            if work_item is not None:
                payload["workItem"] = self.service_public(work_item)
            for subscription in subscriptions:
                try:
                    self.delivery.submit(self._deliver, subscription, payload)
                except RuntimeError:
                    pass
        return change

    @staticmethod
    def service_public(value):
        from .service import public
        return public(value)

    def _deliver(self, subscription: dict, payload: dict):
        property_id = subscription["propertyId"]
        for attempt in range(1, 4):
            try:
                response = httpx.post(subscription["callbackUrl"], json=payload, timeout=5.0)
                if response.status_code < 400:
                    self.store.event(property_id, f"agent-{property_id}", "subscription.delivered", "Callback delivered",
                                     f"{subscription['callbackUrl']} accepted change v{payload['change']['version']} (attempt {attempt}).")
                    return
                reason = f"HTTP {response.status_code}"
            except Exception as error:
                reason = type(error).__name__
            if attempt < 3:
                self._stop.wait(0.5 * attempt)
        self.store.event(property_id, f"agent-{property_id}", "subscription.failed", "Callback failed",
                         f"{subscription['callbackUrl']} did not accept change v{payload['change']['version']} after 3 attempts ({reason}).")

    def subscribe(self, property_id: str, callback_url: str, requester: str) -> dict:
        self.service.require_property(property_id)
        parsed = urlparse(callback_url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise RealityError("callbackUrl must be an http(s) URL.", "INVALID_CALLBACK", "Provide an http:// or https:// URL that accepts POST.")
        for existing in self.store.all("subscription", property_id):
            if existing["callbackUrl"] == callback_url and existing["requester"] == requester:
                return existing
        subscription = dict(id=uid("sub"), propertyId=property_id, callbackUrl=callback_url, requester=requester or "mcp-client", createdAt=now())
        self.put("subscription", subscription, property_id)
        self.store.event(property_id, f"agent-{property_id}", "subscription.created", "Subscription created", f"{requester} → {callback_url}")
        return subscription

    def changes(self, property_id: str, since: int = 0, limit: int = 100, include_scenario: bool = False, latest: bool = False) -> dict:
        """Changes after `since`. A scenario's own step rows (type `scenario`) are left out unless `include_scenario`: each
        step's issue, fact and conversation Changes already say what happened, and the eval harness waits on the step rows
        through the WaitHub, which sees every Change. `version` stays the site's latest, scenario rows included."""
        self.service.require_property(property_id)
        items = [{k: v for k, v in c.items() if not (k == "assetTag" and v is None)} for c in self.store.all("change", property_id)
                 if c["version"] > since and (include_scenario or c["type"] != "scenario")]
        items.sort(key=lambda c: c["version"])
        waiting = [w for w in self.store.all("work_item", property_id) if w["state"] in OPEN_STATES]
        # `latest`: the newest `limit` changes after `since` (still oldest first), for "what just happened" views.
        return dict(version=self.version(property_id), changes=items[-limit:] if latest else items[:limit], waiting=waiting)

    # ---- facts ------------------------------------------------------------------------------------------

    def fact_status(self, fact: dict, reference: datetime | None = None) -> str:
        if fact.get("expiresAt") is None:
            return "known"
        expires = parse_time(fact["expiresAt"])
        return "known" if expires and expires > (reference or utcnow()) else "stale"

    def facts_for(self, property_id: str, asset_tag: str, attribute: str) -> list[dict]:
        matching = [f for f in self.store.all("fact", property_id) if f["assetTag"] == asset_tag and f["attribute"] == attribute]
        matching.sort(key=lambda f: (f["observedAt"], f["version"]), reverse=True)
        return matching

    def latest_facts(self, property_id: str, asset_tag: str | None = None, attribute: str | None = None) -> list[dict]:
        self.service.require_property(property_id)
        latest: dict[tuple, dict] = {}
        for fact in sorted(self.store.all("fact", property_id), key=lambda f: (f["observedAt"], f["version"])):
            if asset_tag and fact["assetTag"] != asset_tag.upper():
                continue
            if attribute and fact["attribute"] != attribute:
                continue
            latest[(fact["assetTag"], fact["attribute"])] = fact
        return [dict(**fact, status=self.fact_status(fact)) for fact in latest.values()]

    def sign_attestation(self, record: dict) -> dict:
        payload = {key: value for key, value in record.items() if key != "signature" and not key.startswith("_")}
        signature, public_key = self.signer.sign({**payload, "publicKey": self.signer.public_key_b64})
        return {**payload, "publicKey": public_key, "signature": signature}

    def check_attestation(self, attestation_id: str) -> dict:
        record = self.store.get("attestation", attestation_id)
        if not record:
            raise RealityError("Attestation not found.", "NOT_FOUND", "Call get_changes or facts to find current attestation IDs.", 404)
        payload = {key: value for key, value in record.items() if key != "signature" and not key.startswith("_")}
        return {**record, "valid": verify_signature(payload, record["signature"], record["publicKey"])}

    def write_fact(self, property_id: str, component: dict, attribute: str, attribute_class: str, value, unit, observed_at: str,
                   source: dict, checks: list[dict], evidence_hashes: list[str], verdict: str = "accepted",
                   work_item: dict | None = None, summary: str | None = None, attestation: dict | None = None,
                   simulated: bool = False, extra: dict | None = None) -> tuple[dict, dict]:
        """Sign an attestation (unless one is supplied), write the fact, update the component and emit Changes.
        `extra` labels (e.g. `{synthetic: True, scenarioId}`) are stored on the fact and inside the signed attestation."""
        ttl = ttl_for_class(attribute_class)
        expires_at = iso(parse_time(observed_at) + timedelta(seconds=ttl)) if ttl else None
        flag = {"simulated": True} if simulated else {}
        flag.update({k: v for k, v in (extra or {}).items() if k in ("synthetic", "scenarioId", "generator")})
        if attestation is None:
            attestation = self.sign_attestation(dict(
                id=uid("att"), propertyId=property_id, assetTag=component["tag"], componentId=component["id"], attribute=attribute,
                value=value, unit=unit, observedAt=observed_at, evidenceHashes=evidence_hashes, checks=checks, verdict=verdict,
                source=source, verifierVersion=VERIFIER_VERSION, signedAt=now(), **flag))
            self.put("attestation", attestation, property_id)
        for digest in evidence_hashes:
            if not self.store.get("evidence_hash", digest, ""):
                self.store.put("evidence_hash", dict(id=digest, propertyId=property_id, attestationId=attestation["id"],
                                                     workItemId=work_item["id"] if work_item else None, at=now()), "")
        version = self.next_version(property_id)
        fact = dict(id=uid("fact"), propertyId=property_id, assetTag=component["tag"], componentId=component["id"], attribute=attribute,
                    attributeClass=attribute_class, value=value, unit=unit, observedAt=observed_at, ttlSeconds=ttl, expiresAt=expires_at,
                    source=source, attestationId=attestation["id"], version=version, createdAt=now(), **flag)
        self.put("fact", fact, property_id)
        stored = self.store.get("component", component["id"], property_id)
        if stored:
            stored["lastFactAt"] = fact["createdAt"]
            stored["factStatus"] = "known"
            if stored.get("status") != "issue":
                stored["status"] = "verified"
            self.store.put("component", stored, property_id)
        text = summary or f"{component['tag']}.{attribute} = {value}{(' ' + unit) if unit else ''} ({source['kind']}:{source['ref']})"
        self.emit_change(property_id, "fact", fact["id"], text, component["tag"], work_item, simulated=simulated)
        self.emit_change(property_id, "attestation", attestation["id"], f"Signed attestation for {component['tag']}.{attribute} ({verdict}).",
                         component["tag"], work_item, simulated=simulated)
        return fact, attestation

    def seed_facts(self):
        """Seed demo facts once per seed version, writing only what is missing: every serial-kind asset on every site gets an
        identity fact, and the demo site gets the contract's demo observations (cert, valve position, sensors, conditions)."""
        # Version 4 (contract 5): re-run once so a site added to an existing database gets its identity facts; the pass
        # only writes what is missing, so existing sites are untouched.
        if self.store.meta("reality_seed_version") == "4":
            self.refresh_demo_seeds()
            return
        with self.lock:
            if self.store.meta("reality_seed_version") == "4":
                return
            moment = utcnow()
            for prop in self.store.all("property"):
                property_id = prop["id"]
                components = {c["tag"]: c for c in self.components(property_id)}
                identified = {f["assetTag"] for f in self.store.all("fact", property_id) if f["attribute"] == "serial"}
                for component in components.values():
                    if "serial" in specs_of(component) and component["tag"] not in identified:
                        self._seeded_fact(property_id, component, "serial", "identity", identity_serial(property_id, component["tag"]), None,
                                          iso(moment - timedelta(days=30)), dict(kind="patrol", ref="seed:initial"))
                if property_id != DEMO_SITE:
                    continue
                prefix = SITE2.get(DEMO_SITE, "MY")
                seeds = [("P-101", "commissioning_certificate", "document", f"{prefix}-COMM-2026-0611", None, moment - timedelta(days=122),
                          dict(kind="human", ref=f"document:{DEMO_SITE}-observations")),
                         ("V-501", "position", "reading", "open", None, moment - timedelta(minutes=40), dict(kind="patrol", ref="seed:patrol-initial"))]
                seeds += [(tag, "temperature_c", "reading", simulated_temperature(tag, moment - timedelta(minutes=2)), "°C", moment - timedelta(minutes=2),
                           dict(kind="sensor", ref=f"sim:{tag}")) for tag in ("TS-801", "TS-802")]
                seeds += [(tag, attribute, "condition", value, None, moment - timedelta(minutes=30), dict(kind="patrol", ref="seed:patrol-initial"))
                          for tag, attribute, value in DEMO_CONDITION_SEEDS]
                for tag, attribute, attribute_class, value, unit, observed, source in seeds:
                    if tag in components and not self.facts_for(property_id, tag, attribute):
                        self._seeded_fact(property_id, components[tag], attribute, attribute_class, value, unit, iso(observed), source)
            self.store.meta("reality_seed_version", "4")
        self.refresh_demo_seeds()

    def refresh_demo_seeds(self):
        """Keep the demo mission reproducible: when a seeded demo observation at the demo site has passed its TTL and nothing
        but seeds was ever written for that attribute, write a fresh seeded patrol observation (ref `seed:patrol-refresh`).
        Real facts are never overwritten; see DEVIATIONS.md."""
        components = {c["tag"]: c for c in self.components(DEMO_SITE)} if self.store.get("property", DEMO_SITE) else {}
        if not components:
            return
        moment = utcnow()
        for tag, attribute, value in (("V-501", "position", "open"), *DEMO_CONDITION_SEEDS):
            facts = self.facts_for(DEMO_SITE, tag, attribute)
            if not facts or any(not str(f["source"].get("ref", "")).startswith("seed:") for f in facts):
                continue
            if self.fact_status(facts[0], moment) == "known":
                continue
            spec = spec_for(spec_kind(components[tag]), attribute)
            self._seeded_fact(DEMO_SITE, components[tag], attribute, spec["attributeClass"], value, None,
                              iso(moment - timedelta(minutes=2)), dict(kind="patrol", ref="seed:patrol-refresh"))

    def _seeded_fact(self, property_id, component, attribute, attribute_class, value, unit, observed_at, source):
        digest = hashlib.sha256(f"seed:{property_id}:{component['tag']}:{attribute}:{value}:{observed_at}".encode()).hexdigest()
        checks = [dict(name="scope", passed=True, reason=f"Seeded demonstration fact for registered asset {component['tag']} at {property_id}."),
                  dict(name="integrity", passed=True, reason=f"SHA-256 of the seeded record: {digest}.")]
        self.write_fact(property_id, component, attribute, attribute_class, value, unit, observed_at, source, checks, [digest],
                        summary=f"Seeded {component['tag']}.{attribute} = {value}{(' ' + unit) if unit else ''} ({source['kind']}:{source['ref']}).")

    # ---- work items and dispatch -----------------------------------------------------------------------

    def work_item(self, work_item_id: str) -> dict:
        item = self.store.get("work_item", work_item_id)
        if not item:
            raise RealityError("Work item not found.", "NOT_FOUND", "Call get_changes for the current waiting work items.", 404)
        return item

    def current_facts(self, property_id: str, asset_tag: str, attribute: str, facts: list[dict]) -> list[dict]:
        """The facts that still speak for (tag, attribute), newest first; superseded ones never make a conflict.

        - One source is one series: a sensor feed's newest reading supersedes its earlier ones (a rising humidity trace
          is a time series, not a disagreement).
        - A reading that resolved a dispatched work item (a fresh reading, or the clarification a conflict asked for)
          supersedes everything observed before it; otherwise an accepted clarification could never end the conflict
          that requested it."""
        attested = {f["attestationId"] for f in facts}
        anchors = [parse_time(f["observedAt"]) for item in self.store.all("work_item", property_id)
                   if item["assetTag"] == asset_tag and item["attribute"] == attribute and item.get("state") == "resolved"
                   and item.get("attestationId") in attested
                   for f in facts if f["attestationId"] == item.get("attestationId")]
        anchor = max((a for a in anchors if a), default=None)
        current, sources = [], set()
        for fact in facts:
            observed = parse_time(fact["observedAt"])
            if anchor and observed and observed < anchor:
                continue
            source = fact.get("source") or {}
            key = (source.get("kind"), source.get("ref"))
            if key in sources:
                continue
            sources.add(key)
            current.append(fact)
        return current

    def open_work_item_for(self, property_id: str, asset_tag: str, attribute: str) -> dict | None:
        for item in self.store.all("work_item", property_id):
            if item["assetTag"] == asset_tag and item["attribute"] == attribute and item["state"] in OPEN_STATES:
                return item
        return None

    def save_work_item(self, item: dict):
        item["updatedAt"] = now()
        self.put("work_item", item, item["propertyId"])
        return item

    def create_work_item(self, property_id: str, component: dict, attribute: str, spec: dict, requester: str, budget: float,
                         state: str = "open", simulated: bool = False, deadline_seconds: int | None = None) -> dict:
        sequence = self.next_sequence(property_id)
        reference = f"{SITE2.get(property_id, property_id[:2].upper())}-{component['tag'].replace('-', '')}-{attribute.upper()}-{sequence:04d}"
        deadline_seconds = deadline_seconds if deadline_seconds is not None else int(env("STEWARD_WORK_DEADLINE_SECONDS", "7200"))
        item = dict(id=uid("wi"), propertyId=property_id, assetTag=component["tag"], componentId=component["id"], attribute=attribute,
                    attributeClass=spec["attributeClass"], reference=reference, state=state, requester=requester or "mcp-client",
                    budget=float(budget or 0), deadlineAt=iso(utcnow() + timedelta(seconds=deadline_seconds)), dispatches=[], verdicts=[],
                    factId=None, attestationId=None, receipt=None, escalationLevel=0, createdAt=now(), updatedAt=now())
        if simulated:
            item["simulated"] = True
        self.put("work_item", item, property_id)
        self.emit_change(property_id, "work_item", item["id"], f"Work item {reference} opened ({state}) for {component['tag']}.{attribute} by {item['requester']}.",
                         component["tag"], item, simulated=simulated)
        return item

    def task_card(self, item: dict, level: int = 0) -> str:
        property_id = item["propertyId"]
        prop = self.service.require_property(property_id)
        components = self.components(property_id)
        component = next(c for c in components if c["id"] == item["componentId"])
        spec = spec_for(spec_kind(component), item["attribute"])
        x, y, z = component["position"]
        wall = "north wall" if z < 0 else "south wall" if z > 0 else "centre of the room"  # wall by sign of z
        neighbours = sorted((c for c in components if c["id"] != component["id"]),
                            key=lambda c: math.dist(c["position"], component["position"]))[:2]
        near = "; ".join(f"{c['tag']} ({c['name'].lower()}) {relative_position(c, component)}" for c in neighbours)
        if spec.get("enum"):
            need = f"state of {item['attribute'].replace('_', ' ')}: one of {', '.join(spec['enum'])}"
            expected = f"Expected one of {', '.join(spec['enum'])}."
        elif spec.get("min") is not None:
            need = f"{item['attribute'].replace('_', ' ')} reading in {spec['unit']}"
            expected = f"Expected range {spec['min']:g} to {spec['max']:g} {spec['unit']}."
        else:
            need = f"{spec['attributeClass']} record for {item['attribute'].replace('_', ' ')}"
            expected = "Reply with the document reference or photograph it."
        prefix = f"REMINDER {level}: " if level else ""
        area = (SITE_BY_ID.get(property_id) or {}).get("area") or "plant room"
        return (f"{prefix}{prop['name']}, {area}, {wall}.\n"
                f"Asset {component['tag']}, {component['name'].lower()}, tag plate on the housing. Nearby: {near}.\n"
                f"Need: {need}. Photograph it with the tag plate visible, or reply with the tag and value.\n"
                f"{expected} Reply to this thread. Pays on verified proof only.\n"
                f"Reference {item['reference']}")

    def record_dispatch(self, item: dict, channel: str, to: str, body: str, provider_ref: str | None, thread_ref: str | None = None,
                        note: str | None = None) -> dict:
        simulated = bool(item.get("simulated"))
        dispatch = dict(id=uid("dsp"), channel=channel, to=to or "", reference=item["reference"], sentAt=now(), providerRef=provider_ref,
                        body=body, _threadRef=thread_ref, _workItemId=item["id"], _propertyId=item["propertyId"])
        if simulated:
            dispatch["simulated"] = True
        item.setdefault("dispatches", []).append(dispatch)
        self.save_work_item(item)
        if note:
            dispatch["note"] = note[:200]
        self.put("dispatch", dict(dispatch, workItemId=item["id"], propertyId=item["propertyId"]), item["propertyId"])
        summary = f"{channel} dispatch for {item['reference']} to {to or 'local card'}" + (f" ({note})" if note else "") + \
                  (" delivered to provider" if provider_ref else " recorded locally; no provider receipt")
        self.emit_change(item["propertyId"], "dispatch", dispatch["id"], summary, item["assetTag"], item, simulated=simulated)
        return dispatch

    def choose_channel(self, property_id: str) -> tuple[str, str]:
        channel, to, _ = self.comms.dispatch_target(property_id)
        return channel, to

    def send(self, item: dict, channel: str, to: str, body: str, thread_ref: str | None = None, reply_to: str | None = None,
             reason: str | None = None) -> dict:
        """Send through the configured provider; on any failure record a local dispatch that says why. Never raises."""
        property_id = item["propertyId"]
        subject = f"{item['reference']}: {item['assetTag']} {item['attribute'].replace('_', ' ')} needed at {self.service.require_property(property_id)['name']}"
        try:
            if channel == "sms":
                result = self.comms.send_sms(property_id, to, body, conversation_id=thread_ref, idempotency_key=f"{item['id']}-{len(item['dispatches'])}")
                return self.record_dispatch(item, "sms", to, body, result["id"], result.get("conversationId") or result["id"])
            if channel == "imessage":
                result = self.comms.send_imessage(property_id, to, body, conversation_id=thread_ref)
                return self.record_dispatch(item, "imessage", to, body, result["id"], result.get("conversationId") or result["id"])
            if channel == "email":
                result = self.comms.send_email(property_id, to, subject, body, item["reference"], in_reply_to=reply_to)
                return self.record_dispatch(item, "email", to, body, result["id"], result.get("threadId") or result["id"])
            if channel == "call":
                result = self.comms.place_call(property_id, to, body)
                return self.record_dispatch(item, "call", to, body, result["id"], result["id"])
        except ProviderNotConfigured as error:
            reason = str(error)
        except ValueError as error:
            reason = str(error)
        except Exception as error:
            reason = f"provider request failed ({type(error).__name__})"
            self.store.event(property_id, f"agent-{property_id}", "dispatch.failed", f"{channel} dispatch failed", reason)
        if channel == "local":
            return self.record_dispatch(item, "local", "", body, None, None, "card stored for /api/inbound/local" + (f"; {reason}" if reason else ""))
        label = "dry-run, " if not external_messages_allowed() else ""
        return self.record_dispatch(item, channel, to, f"[not sent: {label}{reason}]\n{body}", None, None, f"not sent: {label}{reason[:150]}")

    def dispatch(self, item: dict) -> dict:
        channel, to, reason = self.comms.dispatch_target(item["propertyId"])
        body = self.task_card(item)
        dispatch = self.send(item, channel, to, body, reason=reason if channel == "local" else None)
        item = self.work_item(item["id"])
        item["state"] = "dispatched" if dispatch["providerRef"] else "waiting"
        self.save_work_item(item)
        self.emit_change(item["propertyId"], "work_item", item["id"], f"Work item {item['reference']} is {item['state']} via {dispatch['channel']}.",
                         item["assetTag"], item)
        return item

    def escalate(self, work_item_id: str, level: int, note: str | None = None, automatic: bool = False) -> dict:
        item = self.work_item(work_item_id)
        if level not in (1, 2, 3, 4):
            raise RealityError("Escalation level must be 1, 2, 3 or 4.", "INVALID_LEVEL", "1 re-send, 2 email, 3 call, 4 owner SMS.")
        if item["state"] in CLOSED_STATES:
            raise RealityError(f"Work item {item['reference']} is {item['state']} and cannot be escalated.", "WORK_ITEM_CLOSED",
                               "Call resolve again to open a new work item.", 409)
        property_id = item["propertyId"]
        card = self.task_card(item, level)
        if note:
            card += f"\nNote: {note[:300]}"
        last = next((d for d in reversed(item["dispatches"]) if d["channel"] != "call"), None)
        if level == 1:
            channel = last["channel"] if last else self.choose_channel(property_id)[0]
            to = last["to"] if last else self.choose_channel(property_id)[1]
            self.send(item, channel, to, card, thread_ref=last.get("_threadRef") if last else None)
        elif level == 2:
            to = self.comms.contractor_email()
            self.send(item, "email", to, card) if to and self.comms.configured(property_id) else \
                self.record_dispatch(item, "email", to, f"[not sent: {'dry-run, ' if not external_messages_allowed() else ''}INKBOX_CONTRACTOR_EMAIL or Inkbox identity not configured]\n{card}", None, None, "not sent: email not configured")
        elif level == 3:
            to = self.comms.contractor_phone()
            script = (f"This is Steward for {self.service.require_property(property_id)['name']}. We need the {item['attribute'].replace('_', ' ')} "
                      f"for asset {item['assetTag']}. Reference {item['reference']}. Please reply by text with the tag plate and the value.")
            self.send(item, "call", to, script) if to and self.comms.configured(property_id) else \
                self.record_dispatch(item, "call", to, f"[not sent: {'dry-run, ' if not external_messages_allowed() else ''}Inkbox voice not configured]\n{script}", None, None, "not sent: voice not configured")
        else:
            to = self.comms.owner_phone()
            question = (f"Owner decision needed for {item['reference']}: {item['assetTag']} {item['attribute'].replace('_', ' ')} is still unverified"
                        f" after {len(item['dispatches'])} dispatch(es). Reply PROCEED or HOLD, or use the owner-decision control.")
            self.send(item, "sms", to, question) if to and self.comms.configured(property_id) else \
                self.record_dispatch(item, "sms", to, f"[not sent: {'dry-run, ' if not external_messages_allowed() else ''}INKBOX_OWNER_PHONE or Inkbox identity not configured]\n{question}", None, None, "not sent: owner SMS not configured")
        item = self.work_item(work_item_id)
        item["state"] = "escalated"
        item["escalationLevel"] = max(int(item.get("escalationLevel", 0)), level)
        self.save_work_item(item)
        how = "automatic" if automatic else "manual"
        self.emit_change(property_id, "escalation", item["id"], f"Work item {item['reference']} escalated to level {level} ({how}).", item["assetTag"], item,
                         simulated=bool(item.get("simulated")))
        self.notify("escalated", item, dict(level=level))
        return item

    def expire(self, item: dict) -> dict:
        item["state"] = "expired"
        self.save_work_item(item)
        self.emit_change(item["propertyId"], "work_item", item["id"], f"Work item {item['reference']} expired at its deadline with no accepted fact.",
                         item["assetTag"], item, simulated=bool(item.get("simulated")))
        self.notify("expired", item)
        return item

    def tick(self, moment: datetime | None = None) -> dict:
        """One scheduler pass: expire past-deadline items and auto-escalate along the ladder."""
        moment = moment or utcnow()
        expired, escalated = 0, 0
        for prop in self.store.all("property"):
            for item in self.store.all("work_item", prop["id"]):
                if item["state"] not in OPEN_STATES or item["state"] == "needs_clarification" and not item["dispatches"]:
                    continue
                deadline = parse_time(item.get("deadlineAt"))
                created = parse_time(item["createdAt"])
                if not deadline or not created:
                    continue
                if moment >= deadline:
                    self.expire(item)
                    expired += 1
                    continue
                fraction = (moment - created).total_seconds() / max((deadline - created).total_seconds(), 1)
                due = max((level for level, threshold in ESCALATION_THRESHOLDS if fraction >= threshold), default=0)
                if due > int(item.get("escalationLevel", 0)):
                    try:
                        self.escalate(item["id"], due, automatic=True)
                        escalated += 1
                    except RealityError:
                        pass
        return dict(expired=expired, escalated=escalated)

    def _scheduler_loop(self):
        while not self._stop.wait(SCHEDULER_INTERVAL_SECONDS):
            try:
                self.tick()
            except Exception as error:
                self.store.event(DEMO_SITE, "atlas", "scheduler.failed", "Reality scheduler pass failed", type(error).__name__)

    def receipt(self, item: dict, accepted_at: datetime) -> dict:
        waited = max(0, int((accepted_at - parse_time(item["createdAt"])).total_seconds()))
        return dict(waitedSeconds=waited, tokensWhileWaiting=0, estimatedPollingTokens=math.ceil(waited / 30) * 350,
                    dispatches=len(item.get("dispatches", [])), cost=0, currency="USD")

    # ---- resolve ----------------------------------------------------------------------------------------

    def resolve(self, property_id: str, asset_tag: str, attribute: str, max_age_hours: float | None = None, budget: float = 0,
                requester: str = "mcp-client", callback_url: str | None = None) -> dict:
        component = self.component_by_tag(property_id, asset_tag)
        spec = spec_for(spec_kind(component), attribute)
        tag = component["tag"]
        if callback_url:
            self.subscribe(property_id, callback_url, requester)
        base = dict(propertyId=property_id, assetTag=tag, attribute=attribute)
        facts = self.facts_for(property_id, tag, attribute)
        ttl = spec["ttlSeconds"]
        moment = utcnow()
        existing = self.open_work_item_for(property_id, tag, attribute)

        def with_item(result, item):
            out = {**result, "workItemId": item["id"], "workState": item["state"], "reference": item["reference"], "cost": 0}
            if item["dispatches"]:  # the contract's dispatchedVia is a Channel or absent, never null
                out["dispatchedVia"] = item["dispatches"][-1]["channel"]
            return out

        if facts:
            latest = facts[0]
            current = self.current_facts(property_id, tag, attribute, facts)
            fresh_disagreeing = [f for f in current[1:] if (ttl is None or age_seconds(f["observedAt"], moment) <= ttl) and f["value"] != latest["value"]]
            if fresh_disagreeing and (ttl is None or age_seconds(latest["observedAt"], moment) <= ttl):
                item = existing or self.create_work_item(property_id, component, attribute, spec, requester, budget, state="needs_clarification")
                conflicts = [dict(attestationId=f["attestationId"], value=f["value"], observedAt=f["observedAt"]) for f in [latest, *fresh_disagreeing]]
                return with_item({**base, "status": "conflict", "conflicts": conflicts,
                                  "nextStep": f"attest a fresh {attribute} reading for {tag} or escalate work item {item['id']}"}, item)
            age = age_seconds(latest["observedAt"], moment)
            bounds = [bound for bound in (ttl, max_age_hours * 3600 if max_age_hours else None) if bound is not None]
            limit = min(bounds) if bounds else None
            known = dict(base, value=latest["value"], unit=latest.get("unit"), observedAt=latest["observedAt"], ageSeconds=int(age),
                         attestationId=latest["attestationId"], expiresAt=latest.get("expiresAt"))
            if limit is None or age <= limit:
                return {**known, "status": "known", "nextStep": f"cite attestation {latest['attestationId']}; no dispatch needed"}
            if existing:
                return with_item({**known, "status": "stale", "nextStep": f"work item {existing['reference']} is already {existing['state']}; poll get_changes or wait for the callback"}, existing)
            if budget and budget > 0:
                item = self.dispatch(self.create_work_item(property_id, component, attribute, spec, requester, budget))
                return with_item({**known, "status": "stale", "nextStep": f"wait for work item {item['reference']} via get_changes or the callback; the stale value is cited above"}, item)
            return {**known, "status": "stale", "nextStep": "call resolve again with budget > 0 to dispatch a fresh reading"}
        if existing:
            return with_item({**base, "status": "unknown", "nextStep": f"work item {existing['reference']} is already {existing['state']}; poll get_changes or wait for the callback"}, existing)
        if budget and budget > 0:
            item = self.dispatch(self.create_work_item(property_id, component, attribute, spec, requester, budget))
            return with_item({**base, "status": "unknown", "nextStep": f"wait for work item {item['reference']} via get_changes or the callback; do not guess the value"}, item)
        return {**base, "status": "unknown", "nextStep": "call resolve again with budget > 0 to dispatch"}

    # ---- attest -----------------------------------------------------------------------------------------

    def hash_owner(self, digest: str) -> dict | None:
        return self.store.get("evidence_hash", digest, "")

    def attest(self, property_id: str, asset_tag: str, attribute: str, value=None, unit=None, observed_at: str | None = None,
               source: dict | None = None, stated_tag: str | None = None, work_item_id: str | None = None, body: str = "",
               filename: str | None = None, file_bytes: bytes | None = None, received_at: str | None = None) -> dict:
        self.service.require_property(property_id)
        component = self.component_by_tag(property_id, asset_tag)
        spec = spec_for(spec_kind(component), attribute)
        item = self.work_item(work_item_id) if work_item_id else None
        source = source if isinstance(source, dict) and source.get("kind") else {"kind": "human", "ref": "attest"}
        source = {"kind": str(source["kind"]), "ref": str(source.get("ref") or "attest")[:200]}
        if file_bytes and len(file_bytes) > 10 * 1024 * 1024:
            raise RealityError("Evidence file must be at most 10 MB.", "FILE_TOO_LARGE", "Resize the photo and resubmit.")
        observation = Observation(property_id=property_id, asset_tag=component["tag"], attribute=attribute, value=value, observed_at=observed_at,
                                  stated_tag=stated_tag, body=body or "", filename=filename, file_bytes=file_bytes, source=source, received_at=received_at)
        result = verify_observation(observation, component, spec, self.components(property_id), item, self.hash_owner)
        verdict = result["verdict"]
        stored_value = public_value(value)
        if spec.get("enum") and isinstance(stored_value, str):
            stored_value = stored_value.casefold()
        digest = result["evidenceHashes"][0]
        if file_bytes:
            suffix = Path(filename or "evidence.bin").suffix.lower()[:8] or ".bin"
            (self.store.directory / "files" / f"{digest}{suffix}").write_bytes(file_bytes)
        attestation = self.sign_attestation(dict(
            id=uid("att"), propertyId=property_id, assetTag=component["tag"], componentId=component["id"], attribute=attribute,
            value=stored_value, unit=unit or spec.get("unit"), observedAt=result["observedAt"], evidenceHashes=result["evidenceHashes"],
            checks=result["checks"], verdict=verdict, source=source, verifierVersion=VERIFIER_VERSION, signedAt=now()))
        self.put("attestation", attestation, property_id)
        if not self.hash_owner(digest):
            self.store.put("evidence_hash", dict(id=digest, propertyId=property_id, attestationId=attestation["id"],
                                                 workItemId=item["id"] if item else None, at=now()), "")
        response = dict(verdict=verdict, reasons=result["reasons"], checks=result["checks"], attestationId=attestation["id"])
        if verdict == "accepted":
            fact, _ = self.write_fact(property_id, component, attribute, spec["attributeClass"], stored_value, unit or spec.get("unit"),
                                      result["observedAt"], source, result["checks"], result["evidenceHashes"], "accepted", item,
                                      attestation=attestation)
            response["factId"] = fact["id"]
            response["nextStep"] = f"cite attestation {attestation['id']}"
        elif verdict == "needs_clarification":
            response["nextStep"] = "answer the clarification: " + "; ".join(result["reasons"])[:300]
        else:
            response["nextStep"] = "resubmit evidence for the right asset: " + "; ".join(result["reasons"])[:300]
        if item:
            item = self.work_item(item["id"])
            item["verdicts"].append(dict(attestationId=attestation["id"], verdict=verdict, reasons=result["reasons"], at=now()))
            if verdict == "accepted":
                accepted_at = utcnow()
                item.update(state="resolved", factId=response["factId"], attestationId=attestation["id"], receipt=self.receipt(item, accepted_at))
            elif verdict == "needs_clarification":
                item["state"] = "needs_clarification"
            self.save_work_item(item)
            self.emit_change(property_id, "work_item", item["id"], f"Work item {item['reference']} verdict {verdict}: " + ("; ".join(result["reasons"]) or "all checks passed")[:300],
                             component["tag"], item)
            response["workItemId"] = item["id"]
        else:
            self.emit_change(property_id, "attestation", attestation["id"], f"Attestation {verdict} for {component['tag']}.{attribute}: " + ("; ".join(result["reasons"]) or "all checks passed")[:300], component["tag"])
        return response

    # ---- inbound routing ---------------------------------------------------------------------------------

    def route(self, message: dict) -> dict | None:
        """Thread/providerRef → reference → sender + open items (scoped to the receiving identity's site when known)."""
        thread = (message.get("threadRef") or "").strip()
        if thread:
            for item in self.store.all("work_item"):
                if item["state"] in OPEN_STATES and any((d.get("_threadRef") == thread or d.get("providerRef") == thread) for d in item["dispatches"]):
                    return item
        text = " ".join(str(message.get(key) or "") for key in ("reference", "subject", "body")).upper()
        match = REFERENCE_RE.search(text)
        if match:
            reference = match.group(0)
            for item in self.store.all("work_item"):
                if item["reference"] == reference:
                    return item
        sender = (message.get("sender") or "").strip().casefold()
        site = None
        for handle in message.get("identityHandles") or []:
            site = site or self.comms.site_for_handle(handle)
        site = site or self.comms.site_for_handle(message.get("localAddress"))
        if sender:
            candidates = [item for item in self.store.all("work_item", site) if item["state"] in OPEN_STATES
                          and any(d.get("to", "").casefold() == sender for d in item["dispatches"])]
            if candidates:
                return sorted(candidates, key=lambda i: i["updatedAt"])[-1]
        return None

    def extract_value(self, body: str, spec: dict):
        text = REFERENCE_RE.sub(" ", TAG_RE.sub(" ", body or ""))
        if spec.get("enum"):
            words = re.findall(r"[a-z]+", text.casefold())
            for word in words:
                if word in spec["enum"]:
                    return word
            return None
        if spec.get("min") is not None:
            matches = list(NUMBER_RE.finditer(text))
            with_unit = [m for m in matches if m.group(2)]
            chosen = with_unit[0] if with_unit else (matches[0] if matches else None)
            return float(chosen.group(1)) if chosen else None
        stripped = text.strip()
        return stripped[:120] or None

    def inbound(self, message: dict, file: tuple[str, bytes] | None = None) -> dict:
        """Route an inbound message to a work item and verify it. Unrouted messages are stored and announced."""
        item = self.route(message)
        if item is None:
            record = {"id": uid("inb"), **{k: v for k, v in message.items() if k != "media"}, "storedAt": now()}
            record.setdefault("receivedAt", now())
            site = self.comms.site_for_handle((message.get("identityHandles") or [None])[0]) or DEMO_SITE
            self.store.put("inbound_unrouted", record, site)
            self.emit_change(site, "dispatch", record["id"], f"Unrouted inbound {message.get('channel', 'local')} message from {message.get('sender') or 'unknown'}: "
                             f"{(message.get('body') or '')[:120]}")
            return dict(routed=False, unroutedId=record["id"], detail="No work item matched by thread, reference or sender.")
        if item["state"] in CLOSED_STATES:
            self.store.event(item["propertyId"], f"agent-{item['propertyId']}", "inbound.ignored", f"Reply after {item['state']}",
                             f"{item['reference']} is {item['state']}; the reply was recorded but not verified.")
            self.record_inbound(item, message, None)
            return dict(routed=True, workItemId=item["id"], verdict=None, detail=f"Work item is {item['state']}.")
        if message.get("channel") == "call" and message.get("provider") == "inkbox":
            # Hosted-agent call ended: keep the transcript on the work item; a value in the transcript is verified like a text.
            self.store.event(item["propertyId"], f"agent-{item['propertyId']}", "call.ended", f"Call ended for {item['reference']}",
                             f"outcome={message.get('callOutcome')}; transcript={message.get('transcriptUrl')}")
            component = self.store.get("component", item["componentId"], item["propertyId"])
            spec = spec_for(spec_kind(component), item["attribute"])
            if self.extract_value(message.get("body") or "", spec) is None:
                item.setdefault("verdicts", [])
                self.save_work_item(item)
                self.record_inbound(item, message, None)
                self.emit_change(item["propertyId"], "dispatch", message.get("providerMessageId") or item["id"],
                                 f"Call for {item['reference']} ended ({message.get('callOutcome') or 'no outcome'}); no reading in the transcript.", item["assetTag"], item)
                return dict(routed=True, workItemId=item["id"], verdict=None, detail="Call transcript recorded; no value to verify.")
        component = self.store.get("component", item["componentId"], item["propertyId"])
        spec = spec_for(spec_kind(component), item["attribute"])
        value = message.get("value")
        if value in (None, ""):
            value = self.extract_value(message.get("body") or "", spec)
        filename, data = file if file else (None, None)
        source = dict(kind="human", ref=f"{message.get('channel', 'local')}:{message.get('providerMessageId') or message.get('sender') or 'reply'}"[:200])
        result = self.attest(item["propertyId"], item["assetTag"], item["attribute"], value=value, observed_at=message.get("observedAt"),
                             source=source, stated_tag=message.get("statedTag"), work_item_id=item["id"], body=message.get("body") or "",
                             filename=filename, file_bytes=data, received_at=message.get("receivedAt"))
        self.reply(item["id"], message, result)
        self.record_inbound(item, message, result)
        self.notify("verdict", self.work_item(item["id"]), dict(result=result, message={k: v for k, v in message.items() if k != "media"}))
        return dict(routed=True, workItemId=item["id"], verdict=result["verdict"], reasons=result["reasons"], attestationId=result.get("attestationId"),
                    factId=result.get("factId"))

    def record_inbound(self, item: dict, message: dict, result: dict | None) -> dict:
        """Persist the inbound message itself (for transcripts); secrets never appear in these payloads."""
        record = dict(id=uid("inm"), workItemId=item["id"], propertyId=item["propertyId"], assetTag=item["assetTag"], reference=item["reference"],
                      channel=message.get("channel") or "local", provider=message.get("provider") or "local", sender=message.get("sender") or "",
                      body=(message.get("body") or "")[:4000], subject=message.get("subject") or "", receivedAt=message.get("receivedAt") or now(),
                      providerMessageId=message.get("providerMessageId"), threadRef=message.get("threadRef"), audioUrl=message.get("recordingUrl"),
                      transcriptUrl=message.get("transcriptUrl"), verdict=(result or {}).get("verdict"), attestationId=(result or {}).get("attestationId"),
                      reasons=(result or {}).get("reasons") or [], at=now())
        if item.get("simulated"):
            record["simulated"] = True
        self.store.put("inbound_message", record, item["propertyId"])
        self.emit_change(item["propertyId"], "reply", record["id"], f"Reply received on {item['reference']} via {record['channel']} from "
                         f"{record['sender'] or 'unknown'}" + (f": {record['verdict']}" if record.get("verdict") else ""), item["assetTag"], item,
                         simulated=bool(item.get("simulated")),
                         extra=dict(workItemId=item["id"], reference=item["reference"], verdict=record.get("verdict"), channel=record["channel"]))
        return record

    def reply(self, work_item_id: str, message: dict, result: dict):
        """Answer on the same thread with the verdict; recorded as a dispatch (local when no provider)."""
        item = self.work_item(work_item_id)
        verdict = result["verdict"]
        if verdict == "accepted":
            text = f"Accepted. {item['assetTag']} {item['attribute'].replace('_', ' ')} recorded. Thank you. Reference {item['reference']}."
        else:
            text = f"{'Rejected' if verdict == 'rejected' else 'Needs clarification'}: " + "; ".join(result["reasons"])[:600] + f" Reference {item['reference']}."
        channel = message.get("channel") or "local"
        if channel in ("sms", "imessage", "email") and message.get("provider") == "inkbox":
            self.send(item, channel, message.get("sender", ""), text, thread_ref=message.get("threadRef"), reply_to=message.get("rfcMessageId"))
        else:
            self.record_dispatch(item, "local", message.get("sender", ""), text, None, None, "reply stored locally")

    # ---- owner decision, patrol, clearance, context ----------------------------------------------------

    def owner_decision(self, property_id: str, work_item_id: str, decision: str, note: str | None = None) -> dict:
        self.service.require_property(property_id)
        item = self.work_item(work_item_id)
        if item["propertyId"] != property_id:
            raise RealityError("Work item belongs to another property.", "SCOPE", "Use the work item's own property ID.", 409)
        if item["state"] in CLOSED_STATES:
            raise RealityError(f"Work item {item['reference']} is already {item['state']}.", "WORK_ITEM_CLOSED", "Nothing further to decide.", 409)
        decision_text = (decision or "").strip()[:80]
        if not decision_text:
            raise RealityError("decision is required.", "INVALID_REQUEST", "Provide a decision such as proceed or hold.")
        component = self.store.get("component", item["componentId"], property_id)
        source = dict(kind="owner", ref=f"work_item:{item['id']}")
        digest = hashlib.sha256(f"owner:{item['id']}:{decision_text}:{now()}".encode()).hexdigest()
        checks = [dict(name="scope", passed=True, reason=f"Owner decision on {item['reference']} for {component['tag']}."),
                  dict(name="integrity", passed=True, reason=f"SHA-256 of the decision record: {digest}.")]
        summary = f"Owner decided '{decision_text}' on {item['reference']} ({component['tag']}.{item['attribute']})" + (f": {note[:200]}" if note else "")
        fact, attestation = self.write_fact(property_id, component, "owner_decision", "condition", decision_text, None, now(), source, checks, [digest],
                                            "accepted", item, summary)
        item = self.work_item(work_item_id)
        item.update(state="resolved", factId=fact["id"], attestationId=attestation["id"], receipt=self.receipt(item, utcnow()))
        item["verdicts"].append(dict(attestationId=attestation["id"], verdict="accepted", reasons=[f"owner decision: {decision_text}"], at=now()))
        item["ownerDecision"] = dict(decision=decision_text, note=(note or "")[:1000], at=now())
        self.save_work_item(item)
        self.emit_change(property_id, "owner_decision", item["id"], summary, component["tag"], item)
        self.notify("owner_decision", item, dict(decision=decision_text, note=note))
        return item

    def patrol(self, property_id: str, scope: str = "all") -> dict:
        """Queue the existing inspection job and write patrol identity facts plus simulated sensor readings now."""
        self.service.require_property(property_id)
        components = self.components(property_id)
        if scope and scope.lower() not in ("all", "full", "plant room"):
            components = [c for c in components if scope.casefold() in f"{c['id']} {c['tag']} {c['system']} {c['subsystem']}".casefold()]
            if not components:
                raise RealityError("Unknown patrol scope.", "UNKNOWN_SCOPE", "Use all, an asset tag, a system or a subsystem name.")
        job = self.service.create_job(property_id, scope=scope or "all", goal=f"Patrol: {scope or 'all'}")
        moment = utcnow()
        written = 0
        for component in components:
            if "serial" in specs_of(component):
                digest = hashlib.sha256(f"patrol:{job['id']}:{component['tag']}:serial".encode()).hexdigest()
                checks = [dict(name="scope", passed=True, reason=f"Patrol {job['id']} checked registered asset {component['tag']}."),
                          dict(name="identity", passed=True, reason=f"Asset register tag {component['tag']} confirmed by patrol."),
                          dict(name="integrity", passed=True, reason=f"SHA-256 of the patrol record: {digest}.")]
                self.write_fact(property_id, component, "serial", "identity", identity_serial(property_id, component["tag"]), None, iso(moment),
                                dict(kind="patrol", ref=job["id"]), checks, [digest])
                written += 1
            if component["kind"] == "sensor":
                written += len(self.sensor_readings(property_id, component, moment))
        self.store.event(property_id, f"agent-{property_id}", "patrol.facts", "Patrol facts written",
                         f"{written} fact(s) written for {len(components)} asset(s); sensor readings are from the labelled simulated feed.")
        return dict(job, patrolFacts=written)

    def clearance(self, property_id: str, start: list[float], end: list[float], width_m: float) -> dict:
        self.service.require_property(property_id)
        if width_m <= 0 or width_m > 10:
            raise RealityError("widthM must be between 0 and 10 metres.", "INVALID_REQUEST", "Pass the corridor width in metres.")
        ax, az = float(start[0]), float(start[1])
        bx, bz = float(end[0]), float(end[1])
        length_sq = (bx - ax) ** 2 + (bz - az) ** 2
        hits = []
        for component in self.components(property_id):
            radius = FOOTPRINT_RADIUS_M.get(component["kind"], DEFAULT_FOOTPRINT_RADIUS_M)
            if radius <= 0:
                continue
            px, pz = float(component["position"][0]), float(component["position"][2])
            t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * (bx - ax) + (pz - az) * (bz - az)) / length_sq))
            distance = math.hypot(px - (ax + t * (bx - ax)), pz - (az + t * (bz - az)))
            if distance <= radius + width_m / 2:
                hits.append((t, component))
        hits.sort(key=lambda hit: hit[0])
        first = hits[0][1] if hits else None
        return dict(clear=not hits, widthM=width_m, blockingAssetTag=first["tag"] if first else None,
                    blockingComponentId=first["id"] if first else None, path=[[ax, az], [bx, bz]])

    def context_min(self, property_id: str) -> dict:
        prop = self.service.require_property(property_id)
        components = self.components(property_id)
        latest = self.latest_facts(property_id)
        known = sum(f["status"] == "known" for f in latest)
        stale = sum(f["status"] == "stale" for f in latest)
        slots = sum(len(specs_of(c)) for c in components)
        waiting = [w for w in self.store.all("work_item", property_id) if w["state"] in OPEN_STATES]
        blockers = [dict(assetTag=w["assetTag"], attribute=w["attribute"], state=w["state"], reference=w["reference"]) for w in waiting[:6]]
        sensors = [dict(assetTag=f["assetTag"], attribute=f["attribute"], value=f["value"], ageSeconds=int(age_seconds(f["observedAt"])))
                   for f in latest if f["source"]["kind"] == "sensor"][:4]
        return dict(propertyId=property_id, name=prop["name"], version=self.version(property_id), assets=len(components),
                    facts=dict(known=known, stale=stale, unknown=max(slots - known - stale, 0)), blockers=blockers, sensors=sensors)

    def sensor_reading(self, property_id: str, component: dict, moment: datetime | None = None, value: float | None = None,
                       simulated: bool = False, attribute: str | None = None) -> tuple[dict, dict]:
        """Write one labelled sensor reading (source `sensor`, ref `sim:<tag>`); `value` overrides the drift for simulation.
        The attribute defaults to `temperature_c` (every sensor table has it except Tomioka's seismic sensor, which reads
        `seismic_gal`); the plausibility line uses the component's own spec range."""
        moment = moment or utcnow()
        table = specs_of(component)
        if attribute is None:
            attribute = "temperature_c" if "temperature_c" in table else next((a for a, spec in table.items() if spec["attributeClass"] == "reading"), None)
        if attribute not in table:
            raise RealityError(f"{component['tag']} has no reading attribute {attribute}.", "UNSUPPORTED_ATTRIBUTE", "Use a sensor reading attribute.")
        spec = table[attribute]
        reading = simulated_reading(component["tag"], attribute, moment) if value is None else value
        unit = spec.get("unit") or ""
        digest = hashlib.sha256(f"sim:{component['tag']}:{attribute}:{iso(moment)}:{reading}".encode()).hexdigest() if attribute != "temperature_c" else \
            hashlib.sha256(f"sim:{component['tag']}:{iso(moment)}:{reading}".encode()).hexdigest()
        checks = [dict(name="scope", passed=True, reason=f"Simulated sensor feed for {component['tag']} (sim:{component['tag']}); not a physical instrument."),
                  dict(name="plausibility", passed=spec["min"] <= reading <= spec["max"], reason=f"{reading} {unit} against the {spec['min']:g}–{spec['max']:g} {unit} spec."),
                  dict(name="integrity", passed=True, reason=f"SHA-256 of the sample: {digest}.")]
        return self.write_fact(property_id, component, attribute, "reading", reading, unit or None, iso(moment),
                               dict(kind="sensor", ref=f"sim:{component['tag']}"), checks, [digest], simulated=simulated)

    def sensor_readings(self, property_id: str, component: dict, moment: datetime | None = None, simulated: bool = False,
                        hold_seconds: float = 0) -> list[tuple[dict, dict]]:
        """One simulated reading for every reading attribute of a sensor (Tomioka's humidity sensors report humidity and
        temperature; every other sensor reports its single reading, as before). With `hold_seconds`, an attribute whose
        latest fact is a scenario sample, a site event's reading (ref `feed:events`, events.py) or a person's verified reading
        younger than that is left alone, so the feed never overwrites a scenario or event ramp or a fix (the mill's humidity headline)."""
        table = specs_of(component)
        moment = moment or utcnow()
        out = []
        for attribute in [a for a, spec in table.items() if spec["attributeClass"] == "reading"]:
            if hold_seconds:
                latest = self.latest_facts(property_id, component["tag"], attribute)
                source = (latest[0].get("source") or {}) if latest else {}
                held = latest and not latest[0].get("simulated") and (source.get("kind") == "human"
                                                                      or str(source.get("ref", "")).startswith(("scenario:", "feed:events")))
                if held and age_seconds(latest[0]["observedAt"], moment) < hold_seconds:
                    continue
            out.append(self.sensor_reading(property_id, component, moment, simulated=simulated, attribute=attribute))
        return out

    def issues(self, property_id: str) -> list[dict]:
        """Issue[] for the environment view: open clarification/escalated/expired items, out-of-range latest facts,
        rejected verdicts in the last 24 h and assets without an identity fact."""
        self.service.require_property(property_id)
        components = {c["id"]: c for c in self.components(property_id)}
        by_tag = {c["tag"]: c for c in components.values()}
        issues: list[dict] = []
        moment = utcnow()

        def add(kind, severity, component, summary, ref_id, at, simulated=False):
            issue = dict(id=f"iss-{hashlib.sha256(f'{kind}:{ref_id}:{component['tag']}'.encode()).hexdigest()[:12]}", assetTag=component["tag"],
                         componentId=component["id"], kind=kind, severity=severity, summary=summary[:300], refId=ref_id,
                         pin=component.get("pin"), pinSource=component.get("pinSource", "estimated"), at=at)
            if simulated:
                issue["simulated"] = True
            issues.append(issue)

        items = self.store.all("work_item", property_id)
        # One overdue issue per (asset, attribute): the latest expiry in the last 24 h, unless a later fact or a resolved
        # item for the same attribute superseded it (the simulation expires a fresh card every few minutes).
        latest_expired: dict[tuple, dict] = {}
        superseded_at: dict[tuple, str] = {}
        for item in items:
            key = (item["assetTag"], item["attribute"])
            if item["state"] == "expired" and age_seconds(item["updatedAt"], moment) <= 86400:
                if key not in latest_expired or item["updatedAt"] > latest_expired[key]["updatedAt"]:
                    latest_expired[key] = item
            elif item["state"] == "resolved":
                superseded_at[key] = max(superseded_at.get(key, ""), item["updatedAt"])
        for fact in self.store.all("fact", property_id):
            key = (fact["assetTag"], fact["attribute"])
            superseded_at[key] = max(superseded_at.get(key, ""), fact["createdAt"])
        for item in items:
            component = components.get(item["componentId"])
            if not component:
                continue
            simulated = bool(item.get("simulated"))
            if item["state"] == "expired":
                key = (item["assetTag"], item["attribute"])
                if latest_expired.get(key) is not item or superseded_at.get(key, "") > item["updatedAt"]:
                    continue
            if item["state"] == "escalated":
                add("escalated", "high", component, f"{item['reference']} escalated to level {item.get('escalationLevel', 0)} for {item['assetTag']}.{item['attribute']}.",
                    item["id"], item["updatedAt"], simulated)
            elif item["state"] == "expired":
                add("overdue", "high", component, f"{item['reference']} expired with no accepted fact for {item['assetTag']}.{item['attribute']}.",
                    item["id"], item["updatedAt"], simulated)
            elif item["state"] == "needs_clarification":
                reasons = (item["verdicts"][-1]["reasons"] if item.get("verdicts") else []) or ["awaiting clarification"]
                add("rejected_evidence", "medium", component, f"{item['reference']} needs clarification: {'; '.join(reasons)[:200]}", item["id"], item["updatedAt"], simulated)
            for verdict in item.get("verdicts", []):
                if verdict["verdict"] == "rejected" and age_seconds(verdict["at"], moment) <= 86400:
                    add("rejected_evidence", "medium", component, f"Evidence rejected for {item['reference']}: {'; '.join(verdict['reasons'])[:200]}",
                        verdict["attestationId"], verdict["at"], simulated)
        latest = self.latest_facts(property_id)
        for fact in latest:
            component = by_tag.get(fact["assetTag"])
            spec = specs_of(component).get(fact["attribute"]) if component else None
            if not spec:
                continue
            value = fact["value"]
            out = False
            if spec.get("min") is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
                out = not (spec["min"] <= value <= spec["max"])
            elif spec.get("enum") and isinstance(value, str) and fact["attribute"] == "status" and value in ("tripped", "alarm", "fault"):
                out = True
            elif spec.get("enum") and isinstance(value, str) and fact["attribute"] == "condition" and value == "defect":
                out = True
            if out:
                add("out_of_range", "high", component, f"{fact['assetTag']}.{fact['attribute']} = {value}{(' ' + fact['unit']) if fact.get('unit') else ''} is outside spec"
                    + (f" {spec['min']:g}–{spec['max']:g} {spec['unit']}" if spec.get("min") is not None else "") + f" ({fact['source']['kind']}:{fact['source']['ref']}).",
                    fact["attestationId"], fact["observedAt"], bool(fact.get("simulated")))
        identified = {f["assetTag"] for f in latest if f["attribute"] == "serial"}
        for component in components.values():
            if "serial" in specs_of(component) and component["tag"] not in identified:
                add("unknown_identity", "low", component, f"No identity fact for {component['tag']}; run a patrol or attest its serial.", component["id"], now())
        issues.sort(key=lambda i: ({"high": 0, "medium": 1, "low": 2}[i["severity"]], i["at"]), reverse=False)
        return issues

    def specs(self, property_id: str) -> dict:
        self.service.require_property(property_id)
        return dict(propertyId=property_id, **spec_table(),
                    assets=[dict(assetTag=c["tag"], componentId=c["id"], kind=c["kind"], specKind=spec_kind(c), attributes=sorted(specs_of(c)))
                            for c in self.components(property_id)])
