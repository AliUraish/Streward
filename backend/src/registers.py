"""Per-site 24-asset registers (contract 3 §1).

Each site keeps its own register, plausible for what its scan shows:

- `myer-plant`: a modern plant room (circulation pumps, handwheel isolation valves, pressure gauges, expansion and
  buffer vessels, heat exchangers, distribution and control panels). The tags and register coordinates match the
  earlier shared register, so references, task cards and geometry checks keep working.
- `bristol-pumps`: a 1907 dock pump house under restoration (two steam pumping engines, electric drainage pumps,
  the pump sump, a steam receiver pressure vessel, valves, gauges, the dock-side egress door and the visitor walkway).
- `tomioka-mill` (contract 5 §3): a section of the 1872 Silk Reeling Mill (six preserved automatic reeling machine
  rows, four king-post roof trusses, the east brick wall that is National Treasure fabric, humidity/temperature and
  seismic sensors, extinguishers, an indoor hydrant, two visitor emergency exits, the visitor walkway, the electrical
  panel, a conservation CCTV camera and a mobile dehumidifier). Its sensors keep kind `sensor` with a `specKind`
  (`sensor:humidity`, `sensor:seismic`) that selects their attribute table in specs.py.

`position` is the register layout in metres on the room frame (+x east, -z north, y up) and drives the reality
layer's geometry checks, task cards and clearance queries. `pin` is a 3-D point in the scan's world coordinates
for the PlayCanvas viewer. Seeded pins are **estimated**: a scaled copy of the register layout scattered within a
few metres of the scan origin, marked `pinSource: "estimated"` until an operator places them on the capture.
Tomioka's capture is far from its origin, so its frame adds an offset: the layout is centred about 2.5 m beyond the
initial camera target along the initial view (viewer frame, the scan rotated 180 degrees about Z), inside the occupied
volume read from the capture's LOD octree (dense leaves around x -38..-28, z -51..-39, the floor near y -2.6).
"""
from __future__ import annotations

import hashlib

ROOMS = {
    "myer-plant": {"width": 13, "depth": 12, "height": 4.6},
    "bristol-pumps": {"width": 17, "depth": 13, "height": 7.5},
    "tomioka-mill": {"width": 22, "depth": 14, "height": 9},
}

# Estimated-pin projection: register metres → scan metres around the origin (scale, y offset, jitter); x/z offsets
# move the frame for captures whose occupied volume is far from the origin (Tomioka).
PIN_FRAME = {
    "myer-plant": dict(scale=0.34, y_scale=0.42, y_offset=-0.9, jitter=0.12),
    "bristol-pumps": dict(scale=0.30, y_scale=0.36, y_offset=0.4, jitter=0.12),
    "tomioka-mill": dict(scale=0.34, y_scale=0.62, y_offset=-2.6, x_offset=-34.9, z_offset=-46.2, jitter=0.12),
}


def _c(cid, tag, name, kind, system, subsystem, status, position, description):
    return dict(id=cid, tag=tag, name=name, kind=kind, system=system, subsystem=subsystem, status=status,
                position=list(position), description=description, confidence=0.94, requirementCount=4,
                verifiedCount=4 if status == "verified" else 2)


MYER = [
    _c("pump-01", "P-101", "Primary circulation pump", "pump", "Mechanical", "Hydronic distribution", "pending", (-3.1, 0, -0.6),
       "End-suction primary circulation pump on the heating water loop; inline motor, tag plate on the volute."),
    _c("pump-02", "P-102", "Secondary circulation pump", "pump", "Mechanical", "Hydronic distribution", "verified", (-1.2, 0, -0.6),
       "Secondary circulation pump serving the building risers; duty/assist pair with P-101."),
    _c("pump-03", "P-103", "Standby circulation pump", "pump", "Mechanical", "Hydronic distribution", "issue", (0.7, 0, -0.6),
       "Standby circulation pump, auto-changeover on duty pump failure."),
    _c("tank-01", "TK-201", "Expansion vessel", "tank", "Mechanical", "Pressure management", "verified", (4.1, 0, -3.6),
       "Membrane expansion vessel holding the closed loop's static pressure; charge valve on the base."),
    _c("tank-02", "TK-202", "Thermal buffer vessel", "tank", "Mechanical", "Thermal storage", "pending", (4.1, 0, -0.7),
       "Insulated buffer vessel decoupling the boiler and building loops."),
    _c("exchanger-01", "HX-301", "Plate heat exchanger", "exchanger", "Mechanical", "Heat exchange", "verified", (-0.7, 0, -4.7),
       "Gasketed plate heat exchanger between the district supply and the building loop."),
    _c("exchanger-02", "HX-302", "Domestic heat exchanger", "exchanger", "Mechanical", "Heat exchange", "pending", (1.8, 0, -4.7),
       "Domestic hot water plate exchanger with its own isolating valves."),
    _c("panel-01", "DB-401", "Main distribution panel", "panel", "Electrical", "Power distribution", "verified", (-5.8, 0.7, -3.6),
       "Main low-voltage distribution board for the plant room."),
    _c("panel-02", "CP-402", "Pump control cabinet", "panel", "Electrical", "Controls", "pending", (-5.8, 0.7, -1.5),
       "Pump control cabinet with VSDs and the BMS outstation."),
    _c("valve-01", "V-501", "Primary isolation valve", "valve", "Mechanical", "Hydronic distribution", "verified", (-3.1, 2.45, -0.6),
       "Gate isolation valve with a red handwheel above P-101."),
    _c("valve-02", "V-502", "Secondary isolation valve", "valve", "Mechanical", "Hydronic distribution", "verified", (-1.2, 2.45, -0.6),
       "Gate isolation valve with a handwheel above P-102."),
    _c("valve-03", "V-503", "Standby isolation valve", "valve", "Mechanical", "Hydronic distribution", "pending", (0.7, 2.45, -0.6),
       "Gate isolation valve with a handwheel above the standby pump."),
    _c("valve-04", "V-504", "Supply manifold valve", "valve", "Mechanical", "Hydronic distribution", "issue", (2.3, 3.0, -0.6),
       "Butterfly valve with a gear-operated handwheel on the supply manifold."),
    _c("valve-05", "V-505", "Return manifold valve", "valve", "Mechanical", "Hydronic distribution", "verified", (2.3, 3.0, 1.0),
       "Butterfly valve with a gear-operated handwheel on the return manifold."),
    _c("gauge-01", "PG-601", "Primary pressure gauge", "gauge", "Mechanical", "Instrumentation", "verified", (-3.1, 1.75, -0.1),
       "Dial pressure gauge on the primary circuit, rated 3.5 bar working pressure."),
    _c("gauge-02", "PG-602", "Secondary pressure gauge", "gauge", "Mechanical", "Instrumentation", "verified", (-1.2, 1.75, -0.1),
       "Dial pressure gauge on the secondary circuit."),
    _c("gauge-03", "PG-603", "Standby pressure gauge", "gauge", "Mechanical", "Instrumentation", "pending", (0.7, 1.75, -0.1),
       "Dial pressure gauge on the standby pump discharge."),
    _c("duct-01", "AHU-701", "Supply air duct", "duct", "Mechanical", "Ventilation", "verified", (-2.0, 3.75, -3.7),
       "Supply air duct from the plant room air handling unit."),
    _c("duct-02", "AHU-702", "Extract air duct", "duct", "Mechanical", "Ventilation", "pending", (2.0, 3.75, -3.7),
       "Extract air duct with fire damper at the wall."),
    _c("sensor-01", "TS-801", "Supply temperature sensor", "sensor", "Mechanical", "Instrumentation", "verified", (-4.1, 2.85, -0.6),
       "Immersion temperature sensor on the flow header."),
    _c("sensor-02", "TS-802", "Return temperature sensor", "sensor", "Mechanical", "Instrumentation", "verified", (-4.1, 2.85, 1.0),
       "Immersion temperature sensor on the return header."),
    _c("light-01", "L-901", "Emergency luminaire", "light", "Electrical", "Lighting", "pending", (-5.5, 3.3, 3.9),
       "Maintained emergency luminaire over the exit route."),
    _c("fire-01", "FE-1001", "Fire extinguisher", "fire", "Fire protection", "Portable equipment", "verified", (5.6, 0.6, 3.6),
       "CO2 extinguisher on a wall bracket by the panels; monthly visual inspection tag."),
    _c("door-01", "D-1101", "Plant room access door", "door", "Architectural", "Access and egress", "verified", (0, 0, 5.2),
       "Fire-rated plant room access door with closer."),
]

BRISTOL = [
    _c("engine-01", "SP-101", "No. 1 steam pumping engine (1907)", "pump", "Mechanical", "Steam plant", "issue", (-4.5, 0, -2.0),
       "1907 compound steam pumping engine driving the No. 1 plunger pump; under restoration."),
    _c("engine-02", "SP-102", "No. 2 steam pumping engine (1907)", "pump", "Mechanical", "Steam plant", "pending", (-1.0, 0, -2.0),
       "Sister engine to SP-101; runs for the public steam demonstration days."),
    _c("pump-03", "P-103", "Electric drainage pump (duty)", "pump", "Mechanical", "Drainage", "verified", (3.5, 0, 2.8),
       "Submersible electric drainage pump, duty, discharging the sump to the dock."),
    _c("pump-04", "P-104", "Electric drainage pump (standby)", "pump", "Mechanical", "Drainage", "pending", (5.0, 0, 2.8),
       "Standby drainage pump, manual start at CP-402."),
    _c("sump-01", "SU-201", "Main pump sump", "sump", "Mechanical", "Drainage", "pending", (4.2, 0, 4.2),
       "Brick-lined sump under the engine floor; its lip sits beside the visitor walkway."),
    _c("vessel-01", "PV-301", "Steam receiver pressure vessel", "vessel", "Mechanical", "Steam plant", "pending", (-6.5, 0, 1.5),
       "Riveted steam receiver feeding both engines; needs a current written-scheme examination certificate before steaming."),
    _c("tank-01", "TK-202", "Feedwater tank", "tank", "Mechanical", "Steam plant", "verified", (6.5, 2.5, -4.5),
       "Raised feedwater tank on the north gallery."),
    _c("exchanger-01", "HX-302", "Feedwater heater", "exchanger", "Mechanical", "Steam plant", "pending", (-6.5, 0, -4.5),
       "Exhaust-steam feedwater heater beside the boiler connection."),
    _c("valve-01", "V-501", "Main steam stop valve", "valve", "Mechanical", "Steam plant", "verified", (-5.5, 2.2, 1.5),
       "Bronze main steam stop valve with a large handwheel on the receiver outlet."),
    _c("valve-02", "V-502", "No. 1 engine delivery valve", "valve", "Mechanical", "Steam plant", "pending", (-4.5, 1.2, -0.8),
       "Delivery valve on the No. 1 engine's pump main."),
    _c("valve-03", "V-503", "No. 2 engine delivery valve", "valve", "Mechanical", "Steam plant", "pending", (-1.0, 1.2, -0.8),
       "Delivery valve on the No. 2 engine's pump main."),
    _c("valve-04", "V-504", "Sump suction valve", "valve", "Mechanical", "Drainage", "verified", (3.5, 0.6, 3.8),
       "Handwheel suction valve between the sump and the drainage pumps."),
    _c("valve-05", "V-505", "Receiver safety valve", "valve", "Mechanical", "Steam plant", "issue", (-6.5, 2.6, 1.5),
       "Spring safety valve on the steam receiver; lift test due with the vessel examination."),
    _c("gauge-01", "PG-601", "Steam receiver pressure gauge", "gauge", "Mechanical", "Instrumentation", "verified", (-6.0, 1.6, 2.2),
       "Brass dial gauge on the steam receiver."),
    _c("gauge-02", "PG-602", "Delivery main pressure gauge", "gauge", "Mechanical", "Instrumentation", "pending", (1.5, 1.6, -0.8),
       "Delivery main gauge shared by both engines."),
    _c("sensor-01", "TS-801", "Engine house temperature sensor", "sensor", "Mechanical", "Instrumentation", "verified", (-7.5, 2.8, 0.0),
       "Wall temperature sensor added during the restoration."),
    _c("sensor-02", "TS-802", "Boiler-side temperature sensor", "sensor", "Mechanical", "Instrumentation", "verified", (-7.5, 2.8, -4.0),
       "Temperature sensor near the boiler connection."),
    _c("panel-01", "DB-401", "Restoration distribution board", "panel", "Electrical", "Power distribution", "verified", (7.6, 0.8, -1.5),
       "Modern distribution board installed for the restoration works."),
    _c("panel-02", "CP-402", "Drainage pump control panel", "panel", "Electrical", "Controls", "pending", (7.6, 0.8, 1.5),
       "Control panel for P-103/P-104 with float-switch inputs from SU-201."),
    _c("light-01", "L-901", "Walkway emergency luminaire", "light", "Electrical", "Lighting", "pending", (0.0, 3.4, 4.6),
       "Emergency luminaire over the visitor walkway."),
    _c("fire-01", "FE-1001", "Engine floor fire extinguisher", "fire", "Fire protection", "Portable equipment", "verified", (2.0, 0.5, 5.6),
       "Water-mist extinguisher at the walkway end."),
    _c("door-01", "D-1101", "Dock-side egress door", "door", "Architectural", "Access and egress", "verified", (7.8, 0, 4.8),
       "Outward-opening dock-side egress door on the visitor route."),
    _c("walkway-01", "W-1201", "Visitor walkway", "walkway", "Architectural", "Visitor route", "verified", (0.0, 0.3, 4.8),
       "Raised timber visitor walkway along the south wall, past the sump lip to the egress door."),
    _c("duct-01", "AHU-701", "Engine house ventilation louvre", "duct", "Mechanical", "Ventilation", "pending", (0.0, 5.5, -5.8),
       "High-level ventilation louvre and extract fan in the north gable."),
]

def _s(cid, tag, name, spec_kind, system, subsystem, status, position, description):
    """A Tomioka sensor: kind `sensor` (as the contract's register table says) with its own attribute table."""
    return dict(_c(cid, tag, name, "sensor", system, subsystem, status, position, description), specKind=spec_kind)


TOMIOKA = [
    _c("machine-01", "RM-101", "Automatic silk reeling machine, row 1", "machine", "Heritage machinery", "Silk reeling", "verified", (-7.5, 0.8, -1.0),
       "Preserved automatic silk reeling machine line, row 1 of 6, kept in place in the Silk Reeling Mill and run only for conservation checks."),
    _c("machine-02", "RM-102", "Automatic silk reeling machine, row 2", "machine", "Heritage machinery", "Silk reeling", "verified", (-4.5, 0.8, -1.0),
       "Preserved automatic silk reeling machine line, row 2 of 6; reeling basins and traverse gear under dust covers."),
    _c("machine-03", "RM-103", "Automatic silk reeling machine, row 3", "machine", "Heritage machinery", "Silk reeling", "pending", (-1.5, 0.8, -1.0),
       "Preserved automatic silk reeling machine line, row 3 of 6; the conservator's monthly check covers its drive belts."),
    _c("machine-04", "RM-104", "Automatic silk reeling machine, row 4", "machine", "Heritage machinery", "Silk reeling", "verified", (1.5, 0.8, -1.0),
       "Preserved automatic silk reeling machine line, row 4 of 6, nearest the visitor walkway viewing point."),
    _c("machine-05", "RM-105", "Automatic silk reeling machine, row 5", "machine", "Heritage machinery", "Silk reeling", "pending", (4.5, 0.8, -1.0),
       "Preserved automatic silk reeling machine line, row 5 of 6; cast-iron frames and bobbin racks."),
    _c("machine-06", "RM-106", "Automatic silk reeling machine, row 6", "machine", "Heritage machinery", "Silk reeling", "verified", (7.5, 0.8, -1.0),
       "Preserved automatic silk reeling machine line, row 6 of 6, beside the east brick wall."),
    _c("truss-01", "TR-201", "Wooden king-post roof truss, bay 1", "structure", "Structure", "Roof", "verified", (-8.25, 7.5, 0.0),
       "King-post timber roof truss over bay 1 of the open hall; mould risk to the timber above 65 % relative humidity."),
    _c("truss-02", "TR-202", "Wooden king-post roof truss, bay 2", "structure", "Structure", "Roof", "pending", (-2.75, 7.5, 0.0),
       "King-post timber roof truss over bay 2; spans the hall without intermediate columns."),
    _c("truss-03", "TR-203", "Wooden king-post roof truss, bay 3", "structure", "Structure", "Roof", "verified", (2.75, 7.5, 0.0),
       "King-post timber roof truss over bay 3; its tie beam carries the lighting runs."),
    _c("truss-04", "TR-204", "Wooden king-post roof truss, bay 4", "structure", "Structure", "Roof", "pending", (8.25, 7.5, 0.0),
       "King-post timber roof truss over bay 4, nearest the east brick wall."),
    _c("wall-01", "BW-251", "Brick wall, east elevation (National Treasure fabric)", "structure", "Structure", "National Treasure fabric", "verified", (11.0, 2.0, 0.0),
       "Original brick infill in the timber frame of the east elevation; National Treasure fabric, never drilled or fixed into without permission to alter its current state."),
    _s("sensor-01", "HS-301", "Humidity and temperature sensor, north", "sensor:humidity", "Conservation", "Environmental monitoring", "verified", (0.0, 2.2, -6.2),
       "Relative-humidity and temperature sensor on a free-standing post by the north windows; preservation band 40-65 % RH."),
    _s("sensor-02", "HS-302", "Humidity and temperature sensor, centre", "sensor:humidity", "Conservation", "Environmental monitoring", "verified", (0.0, 2.2, 0.8),
       "Relative-humidity and temperature sensor on a free-standing post in the centre aisle between the machine rows."),
    _s("sensor-03", "HS-303", "Humidity and temperature sensor, south", "sensor:humidity", "Conservation", "Environmental monitoring", "pending", (0.0, 2.2, 6.2),
       "Relative-humidity and temperature sensor on a free-standing post by the visitor walkway on the south side."),
    _s("sensor-04", "VS-401", "Seismic and vibration sensor", "sensor:seismic", "Conservation", "Structural monitoring", "verified", (-10.4, 0.1, 4.0),
       "Triaxial accelerometer on the floor slab at the west end; reports ground acceleration in gal after earthquakes and heavy traffic."),
    _c("fire-01", "FE-501", "Portable fire extinguisher, west end", "fire", "Fire protection", "Portable equipment", "verified", (-10.6, 0.5, -5.5),
       "Portable powder extinguisher on a floor stand at the west end, clear of the timber frame."),
    _c("fire-02", "FE-502", "Portable fire extinguisher, east end", "fire", "Fire protection", "Portable equipment", "verified", (10.6, 0.5, -5.5),
       "Portable powder extinguisher on a floor stand at the east end beside the electrical access route."),
    _c("fire-03", "FE-503", "Portable fire extinguisher, visitor walkway", "fire", "Fire protection", "Portable equipment", "pending", (0.0, 0.5, 6.8),
       "Portable powder extinguisher at the middle of the visitor walkway, inside the barrier."),
    _c("hydrant-01", "FH-601", "Indoor fire hydrant", "hydrant", "Fire protection", "Indoor hydrant", "pending", (10.6, 1.0, 3.0),
       "Indoor fire hydrant cabinet with hose by the east wall; free-standing, not fixed into the brick."),
    _c("door-01", "D-701", "Visitor emergency exit, west", "door", "Architectural", "Access and egress", "verified", (-11.0, 0.0, 5.8),
       "Outward-opening visitor emergency exit at the west end of the walkway."),
    _c("door-02", "D-702", "Visitor emergency exit, east", "door", "Architectural", "Access and egress", "verified", (11.0, 0.0, 5.8),
       "Outward-opening visitor emergency exit at the east end of the walkway."),
    _c("walkway-01", "W-801", "Visitor walkway and barrier", "walkway", "Architectural", "Visitor route", "verified", (0.0, 0.2, 4.8),
       "Raised timber visitor walkway along the south side with a rope barrier that keeps visitors off the machine rows."),
    _c("panel-01", "EP-901", "Electrical distribution panel", "panel", "Electrical", "Power distribution", "verified", (-10.7, 1.2, -2.5),
       "Modern distribution panel for lighting, sensors and the dehumidifiers, in a free-standing steel cabinet off the historic fabric."),
    _c("camera-01", "CC-1001", "Conservation CCTV camera", "camera", "Security", "Conservation CCTV", "pending", (-10.8, 4.5, -6.8),
       "Camera on a free-standing mast at the north-west corner watching the machine rows for visitor safety and conservation."),
    _c("dehumidifier-01", "DH-1101", "Mobile dehumidifier", "dehumidifier", "Conservation", "Climate control", "pending", (-3.0, 0.0, -5.2),
       "Wheeled compressor dehumidifier staged by the north windows for humid spells; started by the conservator."),
]

REGISTERS: dict[str, list[dict]] = {"myer-plant": MYER, "bristol-pumps": BRISTOL, "tomioka-mill": TOMIOKA}
# Contract 5 §3 heads its table "24" but lists 25 tags (RM x6, TR x4, BW, HS x3, VS, FE x3, FH, D x2, W, EP, CC, DH);
# every listed tag is registered, so Tomioka has 25 assets (see DEVIATIONS.md).
REGISTER_SIZES = {"myer-plant": 24, "bristol-pumps": 24, "tomioka-mill": 25}
assert all(len(items) == REGISTER_SIZES[site] for site, items in REGISTERS.items())
assert all(len({c["tag"] for c in items}) == len(items) and len({c["id"] for c in items}) == len(items) for items in REGISTERS.values())


def room_for(site_id: str) -> dict:
    return ROOMS.get(site_id, {"width": 13, "depth": 12, "height": 4.6})


def estimated_pin(site_id: str, component: dict) -> dict:
    """Scan-frame point within a few metres of the origin, derived from the register layout plus a deterministic
    per-asset jitter. Never measured on the capture; `pinSource` says `estimated`."""
    frame = PIN_FRAME.get(site_id, PIN_FRAME["myer-plant"])
    x, y, z = (float(v) for v in component["position"])
    digest = hashlib.sha256(f"{site_id}:{component['tag']}:pin".encode()).digest()
    jitter = [(digest[i] / 255 - 0.5) * 2 * frame["jitter"] for i in range(3)]
    return dict(x=round(x * frame["scale"] + frame.get("x_offset", 0.0) + jitter[0], 3),
                y=round(y * frame["y_scale"] + frame["y_offset"] + jitter[1], 3),
                z=round(z * frame["scale"] + frame.get("z_offset", 0.0) + jitter[2], 3))


def register_for(site_id: str) -> list[dict]:
    """Fresh copies of the site's register with estimated 3-D pins."""
    out = []
    for template in REGISTERS.get(site_id, []):
        component = {**template, "position": list(template["position"])}
        component["pin"] = estimated_pin(site_id, component)
        component["pinSource"] = "estimated"
        out.append(component)
    return out
