"""Metrics (contract 4 §3, contract 5 §3): synthetic, labelled time series per site, a three-site summary and eval metrics.

Series: `pressure_bar` per pump circuit, `flow_m3h`, `temperature_c`, `level_pct` (Myer expansion tank TK-201,
Bristol sump SU-201), `vibration_mms`, `power_kw`; for the Tomioka Silk Mill `humidity_pct` (HS-301..HS-303),
`temperature_c`, `vibration_mms` (reeling machine rows), `crack_width_mm` (the east brick wall BW-251) and `power_kw`;
on every site `checked_in` (employees checked in at the badge readers, following the site's day shift). A deterministic
generator (a seeded mean-reverting random walk per
series and day, plus a daily cycle) covers the last 7 days at 5-minute resolution. Facts written for the same asset
and attribute (scenario overlays such as the PG-601 overpressure ramp and the SU-201 sump rise, and the simulated
sensor feed) are merged in as overlay points, and while the simulation is on the series continue with a live point
every 5 s up to now. Every response says `synthetic: true`.

`GET /api/metrics/live[?siteId=]` (contract 7 §5) gives the current 5-second reading of every series with the previous
one, the direction (`trend` up/down/flat) and the band state (`state` high/low/normal), plus per-kind site KPIs.

`GET /api/properties/{id}/metrics?series=&from=&to=&step=` → `{series: [{key, unit, assetTag?, label, points:
[[isoTime, value]], spec?: {min, max}}], synthetic, generator}`; `series` takes full keys (`pressure_bar:PG-601`) or
base names (`pressure_bar`). `GET /api/metrics/summary` and `GET /api/evals/metrics` aggregate across sites.
"""
from __future__ import annotations

import bisect
import math
import random
import statistics
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .agents import site_of
from .env import env
from .errors import RealityError
from .telemetry import SOURCE_LABEL
from .verify import iso, parse_time

STEP_SECONDS = 300
LIVE_STEP_SECONDS = 5
HISTORY_DAYS = 7
MAX_POINTS = 5000
GENERATOR = "steward-metrics/1 (seeded random walk + daily cycle)"


def _s(key, unit, label, asset, base, amp, noise, spec=None, phase=6.0, floor=None, outage=0, hours=None, digits=3):
    """`outage`: minutes per day the pump is stopped (a seeded window per day), which drives the uptime figure.
    `hours`: (open, close, utc offset) local opening hours; the value is 0 outside them and follows a midday peak inside."""
    return dict(key=key, unit=unit, label=label, assetTag=asset, base=base, amp=amp, noise=noise, spec=spec, phase=phase, floor=floor, outage=outage,
                hours=hours, digits=digits)


SERIES: dict[str, list[dict]] = {
    "myer-plant": [
        _s("pressure_bar:PG-601", "bar", "Primary circuit pressure (PG-601)", "PG-601", 2.6, 0.15, 0.03, dict(min=1.5, max=3.5)),
        _s("pressure_bar:PG-602", "bar", "Secondary circuit pressure (PG-602)", "PG-602", 2.4, 0.12, 0.03, dict(min=1.5, max=3.5)),
        _s("pressure_bar:PG-603", "bar", "Standby circuit pressure (PG-603)", "PG-603", 1.7, 0.03, 0.02, dict(min=1.5, max=3.5)),
        _s("flow_m3h:P-101", "m³/h", "Primary pump flow (P-101)", "P-101", 42, 6, 0.8, dict(min=20, max=60), floor=0, outage=15),
        _s("flow_m3h:P-102", "m³/h", "Secondary pump flow (P-102)", "P-102", 35, 5, 0.7, dict(min=15, max=55), floor=0),
        _s("temperature_c:TS-801", "°C", "Supply temperature (TS-801)", "TS-801", 21.5, 1.2, 0.15, dict(min=5, max=40)),
        _s("temperature_c:TS-802", "°C", "Return temperature (TS-802)", "TS-802", 20.0, 1.0, 0.15, dict(min=5, max=40)),
        _s("level_pct:TK-201", "%", "Expansion tank level (TK-201)", "TK-201", 55, 3, 0.4, dict(min=10, max=95), floor=0),
        _s("vibration_mms:P-101", "mm/s", "Primary pump vibration (P-101)", "P-101", 2.1, 0.2, 0.08, dict(min=0, max=4.5), floor=0),
        _s("vibration_mms:P-102", "mm/s", "Secondary pump vibration (P-102)", "P-102", 1.8, 0.2, 0.07, dict(min=0, max=4.5), floor=0),
        _s("power_kw:DB-401", "kW", "Plant room power (DB-401)", "DB-401", 68, 18, 1.5, dict(min=0, max=120), floor=0),
        _s("checked_in:SITE", "people", "Employees checked in (badge readers)", "SITE", 10, 5, 0.4, dict(min=2, max=24), phase=19.0, floor=2, digits=0),
    ],
    "bristol-pumps": [
        _s("pressure_bar:PG-602", "bar", "Drainage delivery main pressure (PG-602)", "PG-602", 1.1, 0.1, 0.03, dict(min=0.5, max=2.5)),
        _s("pressure_bar:PG-601", "bar", "Steam receiver pressure (PG-601)", "PG-601", 0.3, 0.05, 0.02, dict(min=0, max=6), floor=0),
        _s("flow_m3h:P-103", "m³/h", "Drainage pump flow (P-103)", "P-103", 18, 4, 0.6, dict(min=5, max=40), floor=0, outage=40),
        _s("temperature_c:TS-801", "°C", "Engine house temperature (TS-801)", "TS-801", 14.0, 2.0, 0.2, dict(min=5, max=40)),
        _s("temperature_c:TS-802", "°C", "Boiler-side temperature (TS-802)", "TS-802", 16.0, 1.6, 0.2, dict(min=5, max=40)),
        _s("level_pct:SU-201", "%", "Sump level (SU-201)", "SU-201", 48, 10, 0.8, dict(min=0, max=85), phase=2.0, floor=0),
        _s("vibration_mms:P-103", "mm/s", "Drainage pump vibration (P-103)", "P-103", 2.6, 0.25, 0.1, dict(min=0, max=4.5), floor=0),
        _s("vibration_mms:SP-102", "mm/s", "No. 2 engine vibration (SP-102)", "SP-102", 0.4, 0.05, 0.03, dict(min=0, max=4.5), floor=0),
        _s("power_kw:DB-401", "kW", "Pump house power (DB-401)", "DB-401", 22, 6, 0.8, dict(min=0, max=60), floor=0),
        _s("checked_in:SITE", "people", "Employees checked in (badge readers)", "SITE", 6, 3, 0.3, dict(min=1, max=16), phase=5.0, floor=1, digits=0),
    ],
    # Contract 5 §3. Humidity peaks before dawn JST (phase 14 UTC), the hall is warmest mid-afternoon JST.
    "tomioka-mill": [
        _s("humidity_pct:HS-301", "%", "Relative humidity, north (HS-301)", "HS-301", 57, 4, 0.5, dict(min=40, max=65), phase=14.0, floor=0),
        _s("humidity_pct:HS-302", "%", "Relative humidity, centre (HS-302)", "HS-302", 55, 3.5, 0.5, dict(min=40, max=65), phase=14.0, floor=0),
        _s("humidity_pct:HS-303", "%", "Relative humidity, south (HS-303)", "HS-303", 54, 3.5, 0.5, dict(min=40, max=65), phase=14.0, floor=0),
        _s("temperature_c:HS-302", "°C", "Hall temperature, centre (HS-302)", "HS-302", 18.0, 3.0, 0.2, dict(min=5, max=30), phase=23.0),
        _s("vibration_mms:RM-101", "mm/s", "Reeling machine row 1 vibration (RM-101)", "RM-101", 0.35, 0.15, 0.04, dict(min=0, max=4.5), phase=23.0, floor=0),
        _s("vibration_mms:RM-104", "mm/s", "Reeling machine row 4 vibration (RM-104)", "RM-104", 0.4, 0.18, 0.04, dict(min=0, max=4.5), phase=23.0, floor=0),
        _s("crack_width_mm:BW-251", "mm", "East brick wall crack width (BW-251)", "BW-251", 0.12, 0.01, 0.002, dict(min=0, max=0.3), phase=23.0, floor=0),
        _s("power_kw:EP-901", "kW", "Mill power (EP-901)", "EP-901", 14, 6, 0.6, dict(min=0, max=40), phase=23.0, floor=0),
        _s("checked_in:SITE", "people", "Employees checked in (badge readers)", "SITE", 9, 4, 0.4, dict(min=2, max=20), phase=21.0, floor=2, digits=0),
    ],
}
BASES = ("pressure_bar", "flow_m3h", "temperature_c", "level_pct", "vibration_mms", "power_kw", "humidity_pct", "checked_in", "crack_width_mm")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def floor_time(moment: datetime, seconds: int) -> datetime:
    epoch = int(moment.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


@lru_cache(maxsize=512)
def _day_walk(site: str, key: str, day: int, noise: float) -> tuple[float, ...]:
    """Mean-reverting walk for one UTC day at 5-minute resolution, seeded by (site, series, day)."""
    rng = random.Random(f"{site}|{key}|{day}")
    value, out = 0.0, []
    theta = 0.08
    for _ in range(86400 // STEP_SECONDS):
        value += -theta * value + noise * rng.gauss(0, 1)
        out.append(value)
    return tuple(out)


@lru_cache(maxsize=512)
def _outage_start(site: str, key: str, day: int, slots: int) -> int:
    return random.Random(f"{site}|{key}|{day}|outage").randrange(0, 86400 // STEP_SECONDS - slots)


def base_value(site: str, spec: dict, moment: datetime) -> float:
    day = int(moment.timestamp() // 86400)
    slot = int((moment.timestamp() % 86400) // STEP_SECONDS)
    if spec.get("outage"):
        slots = max(1, spec["outage"] * 60 // STEP_SECONDS)
        start = _outage_start(site, spec["key"], day, slots)
        if start <= slot < start + slots:
            return float(spec.get("floor") or 0)
    walk = _day_walk(site, spec["key"], day, spec["noise"])[slot]
    hours = (moment.timestamp() % 86400) / 3600.0
    if spec.get("hours"):
        opens, closes, offset = spec["hours"]
        local = (hours + offset) % 24
        if not opens <= local < closes:
            return 0.0
        value = spec["base"] + spec["amp"] * math.sin(math.pi * (local - opens) / (closes - opens)) + walk
        return float(round(max(spec.get("floor") or 0, value), spec.get("digits", 3)))
    cycle = math.sin(2 * math.pi * (hours - spec["phase"]) / 24.0)
    value = spec["base"] + spec["amp"] * cycle + walk
    if spec.get("floor") is not None:
        value = max(spec["floor"], value)
    return round(value, spec.get("digits", 3)) if spec.get("digits", 3) else float(round(value))


def live_value(site: str, spec: dict, moment: datetime) -> float:
    """5-second points between grid points: interpolate the walk and add a small hashed jitter."""
    left = floor_time(moment, STEP_SECONDS)
    right = left + timedelta(seconds=STEP_SECONDS)
    fraction = (moment - left).total_seconds() / STEP_SECONDS
    if spec.get("hours") and (base_value(site, spec, left) == 0 or base_value(site, spec, right) == 0):
        return base_value(site, spec, left)  # closed (or opening/closing): no jitter around zero visitors
    value = base_value(site, spec, left) * (1 - fraction) + base_value(site, spec, right) * fraction
    jitter = (random.Random(f"{site}|{spec['key']}|{int(moment.timestamp())}").random() - 0.5) * spec["noise"] * 0.6
    value += jitter
    if spec.get("floor") is not None:
        value = max(spec["floor"], value)
    return round(value, spec.get("digits", 3)) if spec.get("digits", 3) else float(round(value))


LIVE_KPIS = {"pressure_bar": "pressure", "flow_m3h": "flow", "humidity_pct": "humidity", "checked_in": "checkedIn", "crack_width_mm": "crackWidth",
             "temperature_c": "temperature", "vibration_mms": "vibration", "power_kw": "power", "level_pct": "level"}


def _trend(value: float, previous: float, spec: dict) -> str:
    """up / down / flat; flat when the change is below a tenth of the series' own noise (or a whole person for counts)."""
    threshold = 0.5 if spec.get("digits") == 0 else max(1e-6, (spec.get("noise") or 0) * 0.1)
    if value - previous > threshold:
        return "up"
    if previous - value > threshold:
        return "down"
    return "flat"


def _state(value: float, band: dict) -> str:
    if band.get("max") is not None and value > band["max"]:
        return "high"
    if band.get("min") is not None and value < band["min"]:
        return "low"
    return "normal"


def _kpi(group: list[dict]) -> dict:
    """A site KPI from its readings of one kind: the mean now and before; high/low when any reading is out of its band."""
    value = statistics.fmean(r["value"] for r in group)
    previous = statistics.fmean(r["previous"] for r in group)
    states = {r["state"] for r in group}
    state = "high" if "high" in states else "low" if "low" in states else "normal"
    ups, downs = sum(r["trend"] == "up" for r in group), sum(r["trend"] == "down" for r in group)
    trend = "up" if value > previous and ups >= downs else "down" if value < previous and downs >= ups else "flat"
    digits = 0 if group[0]["key"].startswith("checked_in") else 3
    shown = (lambda v: float(round(v)) if digits == 0 else round(v, 3))
    return dict(value=shown(value), previous=shown(previous), delta=round(value - previous, 3), trend=trend, state=state, unit=group[0]["unit"],
                count=len(group), outOfBand=[r["assetTag"] for r in group if r["state"] != "normal"])


class MetricsService:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def specs(self, site_id: str) -> list[dict]:
        self.service.require_property(site_id)
        return SERIES.get(site_id, [])

    def _select(self, site_id: str, series: str | None) -> list[dict]:
        specs = self.specs(site_id)
        if not series:
            return specs
        wanted = [s.strip() for s in series.split(",") if s.strip()]
        chosen = [spec for spec in specs if spec["key"] in wanted or spec["key"].split(":")[0] in wanted]
        if not chosen:
            raise RealityError(f"No series match {series[:80]}.", "INVALID_REQUEST", "Use " + ", ".join(BASES) + " or full keys like pressure_bar:PG-601.")
        return chosen

    def _overlays(self, site_id: str, start: datetime, end: datetime) -> dict[tuple[str, str], list[tuple[datetime, float]]]:
        """Numeric facts in range grouped by (assetTag, attribute), read once per request."""
        grouped: dict[tuple[str, str], list[tuple[datetime, float]]] = {}
        for fact in self.store.all("fact", site_id):
            value = fact.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            moment = parse_time(fact.get("observedAt"))
            if moment and start <= moment <= end:
                grouped.setdefault((fact.get("assetTag"), fact.get("attribute")), []).append((moment, float(value)))
        return grouped

    def series(self, site_id: str, series: str | None = None, start: str | None = None, end: str | None = None, step: int | None = None) -> dict:
        moment = utcnow()
        end_at = parse_time(end) if end else moment
        start_at = parse_time(start) if start else end_at - timedelta(days=1)
        if not end_at or not start_at:
            raise RealityError("from and to must be ISO-8601 times.", "INVALID_REQUEST", "Example: from=2026-10-17T00:00:00Z.")
        earliest = floor_time(moment, 86400) - timedelta(days=HISTORY_DAYS - 1)
        start_at, end_at = max(start_at, earliest), min(end_at, moment)
        if start_at >= end_at:
            raise RealityError("from must be before to (within the last 7 days).", "INVALID_REQUEST", "Pick a range in the last 7 days.")
        step = int(step or STEP_SECONDS)
        if step < LIVE_STEP_SECONDS or step > 86400:
            raise RealityError("step must be between 5 and 86400 seconds.", "INVALID_REQUEST", "Use step=300 for 5-minute points.")
        while (end_at - start_at).total_seconds() / step > MAX_POINTS:
            step *= 2
        live = bool(getattr(self.service, "simulator", None) and self.service.simulator.enabled)
        overlays = self._overlays(site_id, start_at, end_at)
        out = []
        for spec in self._select(site_id, series):
            raw: list[tuple[datetime, float]] = []
            cursor = floor_time(start_at, STEP_SECONDS)
            if cursor < start_at:
                cursor += timedelta(seconds=STEP_SECONDS)
            grid_end = floor_time(end_at, STEP_SECONDS)
            while cursor <= grid_end:
                raw.append((cursor, base_value(site_id, spec, cursor)))
                cursor += timedelta(seconds=STEP_SECONDS)
            if live and step < STEP_SECONDS:
                tick = floor_time(end_at, LIVE_STEP_SECONDS)
                live_cursor = max(grid_end + timedelta(seconds=LIVE_STEP_SECONDS), start_at)
                while live_cursor <= tick:
                    raw.append((live_cursor, live_value(site_id, spec, live_cursor)))
                    live_cursor += timedelta(seconds=LIVE_STEP_SECONDS)
            overlay = overlays.get((spec["assetTag"], spec["key"].split(":")[0]), [])
            if overlay:
                raw = self._merge(site_id, spec, raw, overlay)
            raw.sort(key=lambda pair: pair[0])
            points = self._resample(raw, step) if step > STEP_SECONDS else [[iso(t), round(v, 3)] for t, v in raw]
            entry = dict(key=spec["key"], unit=spec["unit"], label=spec["label"], assetTag=spec["assetTag"], points=points, spec=spec.get("spec"),
                         overlayPoints=len(overlay), synthetic=True)
            out.append(entry)
        return {"siteId": site_id, "series": out, "from": iso(start_at), "to": iso(end_at), "step": step, "live": live, "synthetic": True,
                "generator": GENERATOR, "note": "Synthetic demonstration series; scenario and simulated-sensor facts are merged in as overlay points."}

    @staticmethod
    def _merge(site_id: str, spec: dict, raw: list, overlay: list) -> list:
        """Overlay facts replace nearby grid points; after the last fact the series keeps that fact's offset from the
        generator (an overpressure stays high until a later fact, such as the verified fix, brings it back)."""
        overlay = sorted(overlay, key=lambda pair: pair[0])
        times = [t.timestamp() for t, _ in overlay]
        half = STEP_SECONDS / 2
        last_t, last_v = overlay[-1]
        offset = last_v - base_value(site_id, spec, floor_time(last_t, STEP_SECONDS))
        kept = []
        for moment, value in raw:
            stamp = moment.timestamp()
            index = bisect.bisect_left(times, stamp)
            near = any(0 <= i < len(times) and abs(times[i] - stamp) <= half for i in (index - 1, index))
            if near:
                continue
            kept.append((moment, round(value + offset, 3) if moment > last_t else value))
        return kept + overlay

    @staticmethod
    def _resample(raw: list[tuple[datetime, float]], step: int) -> list[list]:
        buckets: dict[int, list[float]] = {}
        for moment, value in raw:
            buckets.setdefault(int(moment.timestamp()) // step, []).append(value)
        return [[iso(datetime.fromtimestamp(bucket * step, tz=timezone.utc)), round(sum(values) / len(values), 3)] for bucket, values in sorted(buckets.items())]

    # ---- summary ------------------------------------------------------------------------------------------

    def _day_values(self, site_id: str, base: str) -> list[float]:
        """Last-24-hour values of every series with this base at the site; empty when the site has none (the mill has no
        pressure or flow, the plants no humidity)."""
        if not any(spec["key"].split(":")[0] == base for spec in self.specs(site_id)):
            return []
        values = []
        for entry in self.series(site_id, base)["series"]:
            values += [v for _, v in entry["points"]]
        return values

    def site_summary(self, site_id: str) -> dict:
        pressure = self._day_values(site_id, "pressure_bar")
        flow = self._day_values(site_id, "flow_m3h")
        duty = next((s for s in self.specs(site_id) if s["key"].startswith("flow_m3h")), None)
        uptime = None
        if duty:
            points = self.series(site_id, duty["key"])["series"][0]["points"]
            running = sum(1 for _, v in points if v >= (duty["spec"] or {}).get("min", 0))
            uptime = round(100.0 * running / len(points), 1) if points else None
        obligations = self.service.people.obligations(site_id)
        compliant = sum(1 for o in obligations if o["status"] in ("ok", "due_soon"))
        midnight = iso(floor_time(utcnow(), 86400))
        actions = sum(1 for row in self.service.telemetry.rows(since=midnight, limit=100000)
                      if row.get("siteId") == site_id or site_of(row["agentId"]) == site_id)
        crew = self.store.all("crew_member", site_id)
        # Contract 5: the mill reports humidity and the brick wall's crack width instead of pressure and flow; contract 7:
        # every site reports its employees checked in now (not visitors).
        humidity = self._day_values(site_id, "humidity_pct")
        cracks = self._day_values(site_id, "crack_width_mm")
        checked = next((s for s in self.specs(site_id) if s["key"].startswith("checked_in")), None)
        checked_in = int(live_value(site_id, checked, floor_time(utcnow(), LIVE_STEP_SECONDS))) if checked else None
        return dict(siteId=site_id, avgPressureBar=round(statistics.fmean(pressure), 2) if pressure else None,
                    avgFlowM3h=round(statistics.fmean(flow), 1) if flow else None, uptimePct=uptime,
                    avgHumidityPct=round(statistics.fmean(humidity), 1) if humidity else None,
                    employeesCheckedIn=checked_in,
                    maxCrackWidthMm=round(max(cracks), 3) if cracks else None,
                    openIssues=len(self.service.issues.list(site_id, "open")),
                    compliancePct=round(100.0 * compliant / len(obligations), 1) if obligations else None,
                    crewOnShift=sum(1 for c in crew if c.get("onShift")), agentActionsToday=actions)

    def summary(self) -> dict:
        sites = [self.site_summary(p["id"]) for p in self.store.all("property")]
        average = {}
        for key in ("avgPressureBar", "avgFlowM3h", "uptimePct", "compliancePct", "avgHumidityPct", "maxCrackWidthMm"):
            values = [s[key] for s in sites if s.get(key) is not None]
            average[key] = round(statistics.fmean(values), 2) if values else None
        for key in ("openIssues", "crewOnShift", "agentActionsToday"):
            average[key] = round(statistics.fmean([s[key] for s in sites]), 1) if sites else None
        totals = {key: sum(s[key] for s in sites) for key in ("openIssues", "crewOnShift", "agentActionsToday")}
        totals["employeesCheckedIn"] = sum(s["employeesCheckedIn"] or 0 for s in sites)
        return dict(sites=sites, average=average, totals=totals, window="last 24 h", synthetic=True, generator=GENERATOR, at=iso(utcnow()))

    # ---- live (contract 7 §5) --------------------------------------------------------------------------------

    def live_readings(self, site_id: str, moment: datetime | None = None) -> list[dict]:
        """The current 5-second reading of every series at the site and the one before it, with direction and band state.
        Scenario and sensor facts apply exactly as in `series` (a ramp stays high until a later fact brings it back)."""
        moment = floor_time(moment or utcnow(), LIVE_STEP_SECONDS)
        before = moment - timedelta(seconds=LIVE_STEP_SECONDS)
        overlays = self._overlays(site_id, moment - timedelta(hours=6), moment + timedelta(seconds=LIVE_STEP_SECONDS))
        out = []
        for spec in self.specs(site_id):
            raw = [(before, live_value(site_id, spec, before)), (moment, live_value(site_id, spec, moment))]
            overlay = overlays.get((spec["assetTag"], spec["key"].split(":")[0]), [])
            if overlay:
                raw = sorted(self._merge(site_id, spec, raw, overlay), key=lambda pair: pair[0])
            horizon = moment + timedelta(seconds=LIVE_STEP_SECONDS)  # facts written inside the current 5 s window count
            raw = [pair for pair in raw if pair[0] < horizon][-2:]
            previous, value = (raw[0][1], raw[-1][1]) if len(raw) > 1 else (raw[-1][1], raw[-1][1])
            band = spec.get("spec") or {}
            out.append(dict(key=spec["key"], label=spec["label"], assetTag=spec["assetTag"], unit=spec["unit"], value=value, previous=previous,
                            delta=round(value - previous, 3), trend=_trend(value, previous, spec), state=_state(value, band), spec=band or None))
        return out

    def live(self, site_id: str | None = None) -> dict:
        moment = floor_time(utcnow(), LIVE_STEP_SECONDS)
        site_ids = [site_id] if site_id else [p["id"] for p in self.store.all("property")]
        sites, pooled = [], {}
        for sid in site_ids:
            self.service.require_property(sid)
            readings = self.live_readings(sid, moment)
            kpis = {}
            for base, name in LIVE_KPIS.items():
                group = [r for r in readings if r["key"].split(":")[0] == base]
                if not group:
                    continue
                kpis[name] = _kpi(group)
                pooled.setdefault(name, []).extend(group)
            sites.append(dict(siteId=sid, kpis=kpis, readings=readings))
        average = {name: _kpi(group) for name, group in pooled.items()} if len(site_ids) > 1 else {}
        return dict(at=iso(moment), intervalSeconds=LIVE_STEP_SECONDS, sites=sites, average=average, synthetic=True, generator=GENERATOR)

    # ---- eval metrics ---------------------------------------------------------------------------------------

    def eval_metrics(self) -> dict:
        runs = self.store.all("eval_run", "")
        suites: dict[str, dict] = {}
        for run in runs:
            entry = suites.setdefault(run["suite"], dict(suite=run["suite"], runs=0, passedRuns=0, passedSteps=0, failedSteps=0, lastRunAt=None))
            entry["runs"] += 1
            entry["passedSteps"] += int(run.get("passed") or 0)
            entry["failedSteps"] += int(run.get("failed") or 0)
            entry["passedRuns"] += 1 if run.get("state") == "finished" and not run.get("failed") else 0
            entry["lastRunAt"] = max(filter(None, [entry["lastRunAt"], run.get("finishedAt") or run.get("startedAt")]), default=None)
        for entry in suites.values():
            steps = entry["passedSteps"] + entry["failedSteps"]
            entry["stepPassRate"] = round(entry["passedSteps"] / steps, 3) if steps else None
            entry["runPassRate"] = round(entry["passedRuns"] / entry["runs"], 3) if entry["runs"] else None
        telemetry = self.service.telemetry
        missions = telemetry.per_mission()
        per_agent: dict[str, list[dict]] = {}
        for mission in missions.values():
            per_agent.setdefault(mission["agentId"], []).append(mission)
        tokens_per_agent = {agent: round(statistics.fmean(m["tokens"] for m in items)) for agent, items in per_agent.items()}
        calls_per_mission = {agent: round(statistics.fmean(m["calls"] for m in items), 1) for agent, items in per_agent.items()}
        all_calls = [m["calls"] for m in missions.values()]
        held, avoided, fired, waiting = 0.0, 0, 0, 0
        moment = utcnow()
        for wait in self.store.all("wait", ""):
            created = parse_time(wait["createdAt"])
            ended = parse_time(wait.get("firedAt")) if wait.get("firedAt") else min(moment, parse_time(wait.get("expiresAt")) or moment)
            if created and ended:
                seconds = max(0.0, (ended - created).total_seconds())
                held += seconds
                avoided += math.ceil(seconds / 30) * 350
            fired += wait["status"] == "fired"
            waiting += wait["status"] == "waiting"
        receipts = [w.get("receipt") for w in self.store.all("work_item") if w.get("receipt")]
        avoided += sum(int(r.get("estimatedPollingTokens") or 0) for r in receipts)
        held += sum(float(r.get("waitedSeconds") or 0) for r in receipts)
        latencies = sorted(r["ms"] for r in telemetry.rows(limit=100000) if isinstance(r.get("ms"), int))
        p50 = latencies[len(latencies) // 2] if latencies else None
        p95 = latencies[min(len(latencies) - 1, int(math.ceil(0.95 * len(latencies))) - 1)] if latencies else None
        week = iso(floor_time(moment, 86400) - timedelta(days=6))
        per_day: dict[str, int] = {}
        total_tokens = 0
        for row in telemetry.rows(since=week, limit=200000):
            total_tokens += int(row["tokens"] or 0)
            if row["kind"] == "a2a":
                per_day[row["at"][:10]] = per_day.get(row["at"][:10], 0) + 1
        rate = float(env("STEWARD_TOKEN_PRICE_USD_PER_MTOK", "7.2") or 7.2)
        return dict(source=SOURCE_LABEL, suites=sorted(suites.values(), key=lambda s: s["suite"]), tokensPerAgentPerMission=tokens_per_agent,
                    toolCallsPerMission=dict(overall=round(statistics.fmean(all_calls), 1) if all_calls else None, byAgent=calls_per_mission),
                    waitFor=dict(heldSeconds=round(held), tokensAvoided=avoided, fired=fired, waiting=waiting,
                                 note="Tokens avoided = polling every 30 s at ~350 tokens a poll, the same estimate as work-item receipts."),
                    latencyMs=dict(p50=p50, p95=p95, samples=len(latencies)), a2aMessagesPerDay=[dict(date=d, messages=n) for d, n in sorted(per_day.items())],
                    estimatedCost=dict(tokens=total_tokens, usd=round(total_tokens * rate / 1_000_000, 4), rateUsdPerMTok=rate, window="last 7 days",
                                       note="Estimated tokens (characters/4) at a blended rate; not billed usage."),
                    at=iso(moment))
