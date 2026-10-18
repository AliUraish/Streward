"""Simulation (addendum 2): a background thread that keeps the non-demo sites alive.

Every 20 s a sensor reading for each sensor-kind asset on every site (source `sensor`, ref `sim:<tag>`). Every
2 min one plausible event on a non-demo site, chosen in rotation from: a reading drifting out of range (creates an
`out_of_range` issue), a patrol identity fact, a short Director → Site Engineer A2A status task that completes by itself, and
an expired work item escalation. Every simulated record carries `simulated: true`. The demo site (`harbor-works`)
gets only the sensor readings, never fabricated work items or verdicts. Runs only with `start_workers` and
`STEWARD_SIMULATION=true` (the default in local dev); `POST /api/simulation {enabled}` toggles it at runtime.
"""
from __future__ import annotations

import json
import threading

from .agents import DIRECTOR as ATLAS, engineer_id as warden_id
from .env import env
from .reality import utcnow
from .sites import DEMO_SITE, SITE_BY_ID, SITE_IDS
from .specs import SPECS, spec_for, spec_kind, specs_of
from .store import now

SENSOR_INTERVAL_SECONDS = 20
SCENARIO_HOLD_SECONDS = 1800  # a scenario sample or a verified reading is not overwritten by the feed for 30 minutes
EVENT_INTERVAL_SECONDS = 120
EVENT_KINDS = ("out_of_range", "patrol_identity", "a2a_status", "expired_escalation")


class Simulator:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.reality = service.reality
        self.bus = service.bus
        self._stop = threading.Event()
        self._thread = None
        self._tick = 0
        stored = self.store.meta("simulation:enabled")
        self.enabled = (stored == "true") if stored is not None else env("STEWARD_SIMULATION", "true").lower() == "true"

    # ---- lifecycle ---------------------------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="steward-simulation", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def set_enabled(self, enabled: bool) -> dict:
        self.enabled = bool(enabled)
        self.store.meta("simulation:enabled", "true" if self.enabled else "false")
        self.store.event(DEMO_SITE, "operator", "simulation.toggled", "Simulation " + ("enabled" if self.enabled else "disabled"), "Toggled through POST /api/simulation.")
        return self.status()

    def status(self) -> dict:
        counts = json.loads(self.store.meta("simulation:counts") or "{}")
        return dict(enabled=self.enabled, running=bool(self._thread and self._thread.is_alive()), counts=counts,
                    sensorIntervalSeconds=SENSOR_INTERVAL_SECONDS, eventIntervalSeconds=EVENT_INTERVAL_SECONDS,
                    demoSite=DEMO_SITE, simulatedSites=[s for s in SITE_IDS if s != DEMO_SITE])

    def _count(self, key: str, amount: int = 1) -> None:
        with self.store.lock:
            counts = json.loads(self.store.meta("simulation:counts") or "{}")
            counts[key] = counts.get(key, 0) + amount
            counts["lastAt"] = now()
            self.store.meta("simulation:counts", json.dumps(counts))

    def _loop(self) -> None:
        while not self._stop.wait(SENSOR_INTERVAL_SECONDS):
            if not self.enabled:
                continue
            try:
                self.tick_sensors()
                self._tick += 1
                if self._tick % (EVENT_INTERVAL_SECONDS // SENSOR_INTERVAL_SECONDS) == 0:
                    self.tick_event()
            except Exception as error:
                self.store.event(DEMO_SITE, ATLAS, "simulation.failed", "Simulation pass failed", type(error).__name__)

    # ---- ticks (callable directly in tests) --------------------------------------------------------------

    def tick_sensors(self) -> int:
        written = 0
        moment = utcnow()
        for site in SITE_IDS:
            for component in self.reality.components(site):
                if component["kind"] == "sensor":
                    written += len(self.reality.sensor_readings(site, component, moment, simulated=True, hold_seconds=SCENARIO_HOLD_SECONDS))
        self._count("sensorReadings", written)
        return written

    def tick_event(self, kind: str | None = None, site: str | None = None) -> dict:
        """One plausible event on a non-demo site. Never touches the demo site."""
        sites = [s for s in SITE_IDS if s != DEMO_SITE]
        site = site or sites[self._tick % len(sites)]
        if site == DEMO_SITE:
            raise ValueError("The demo site is never simulated beyond sensor readings.")
        kind = kind or EVENT_KINDS[(self._tick // max(len(sites), 1)) % len(EVENT_KINDS)]
        components = self.reality.components(site)
        if kind == "out_of_range":
            sensor = next(c for c in components if c["kind"] == "sensor" and "temperature_c" in specs_of(c))
            spec = specs_of(sensor)["temperature_c"]
            fact, _ = self.reality.sensor_reading(site, sensor, value=round(spec["max"] + 1.5 + (self._tick % 5) * 0.7, 1), simulated=True)
            detail = f"{sensor['tag']} drifted to {fact['value']} °C (spec {spec['min']:g}–{spec['max']:g}); listed as an out_of_range issue."
            ref = fact["id"]
        elif kind == "patrol_identity":
            index = self._tick % len(components)
            component = next((c for c in components[index:] + components[:index] if "serial" in specs_of(c)), components[0])
            from .reality import identity_serial, iso
            import hashlib
            digest = hashlib.sha256(f"sim-patrol:{site}:{component['tag']}:{now()}".encode()).hexdigest()
            checks = [dict(name="scope", passed=True, reason=f"Simulated patrol pass checked registered asset {component['tag']}."),
                      dict(name="identity", passed=True, reason=f"Asset register tag {component['tag']} confirmed by the simulated patrol."),
                      dict(name="integrity", passed=True, reason=f"SHA-256 of the patrol record: {digest}.")]
            fact, _ = self.reality.write_fact(site, component, "serial", "identity", identity_serial(site, component["tag"]), None, iso(utcnow()),
                                              dict(kind="patrol", ref="sim:patrol"), checks, [digest], simulated=True)
            detail = f"Simulated patrol confirmed {component['tag']} identity."
            ref = fact["id"]
        elif kind == "a2a_status":
            task = self.bus.send(ATLAS, warden_id(site), f"Status check: anything blocking at {SITE_BY_ID[site]['name']}?",
                                 dict(kind="status_check", simulated=True), site, simulated=True, deliver=False)
            waiting = [w for w in self.store.all("work_item", site) if w["state"] in ("open", "dispatched", "waiting", "needs_clarification", "escalated")]
            self.bus.reply(warden_id(site), task["id"], "complete",
                           f"{SITE_BY_ID[site]['name']}: {len(waiting)} open work item(s); sensors reporting on the simulated feed.",
                           dict(openWorkItems=len(waiting), simulated=True), deliver=False)
            detail = f"Simulated Atlas → Warden status task {task['id']} completed."
            ref = task["id"]
        else:
            # A valve position where the site has valves; at the mill (no valves) the first asset with a state attribute (RM-101.status).
            valve = next((c for c in components if c["kind"] == "valve"), None)
            attribute = "position"
            if valve is None:
                valve = next(c for c in components if any(v.get("enum") and v["attributeClass"] in ("reading", "condition") for v in specs_of(c).values()))
                attribute = next(a for a, v in specs_of(valve).items() if v.get("enum") and v["attributeClass"] in ("reading", "condition"))
            spec = spec_for(spec_kind(valve), attribute)
            existing = self.reality.open_work_item_for(site, valve["tag"], attribute)
            if existing and existing.get("simulated"):
                item = existing
            else:
                item = self.reality.create_work_item(site, valve, attribute, spec, "simulation", 0, simulated=True, deadline_seconds=60)
                item = self.reality.work_item(item["id"])
                self.reality.record_dispatch(item, "local", "", self.reality.task_card(item), None, None, "simulated card; nobody was contacted")
                item = self.reality.work_item(item["id"])
                item["state"] = "waiting"
                self.reality.save_work_item(item)
            self.reality.expire(self.reality.work_item(item["id"]))
            detail = f"Simulated work item {item['reference']} expired (overdue issue); no person was contacted."
            ref = item["id"]
        self.store.event(site, ATLAS, "simulation.event", f"Simulated {kind}", detail)
        self._count("events")
        self._count(f"event:{kind}")
        return dict(kind=kind, site=site, refId=ref, detail=detail, simulated=True)
