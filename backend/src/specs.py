"""Attribute specifications per component kind: class, unit, numeric range or enum, and TTL by class.

The table mirrors REALITY-CONTRACT.md exactly. It is the only place plausibility ranges live.

Contract 5 (Tomioka Silk Mill) adds `machine`, `structure`, `hydrant`, `camera` and `dehumidifier`. Its sensors keep
the register kind `sensor` (icons, filters and the PINS stream key on it) and carry a `specKind` that selects their
own table: `sensor:humidity` (humidity_pct 40-65 % for preservation plus temperature_c 5-30 °C) and `sensor:seismic`
(seismic_gal 0-80). Every lookup goes through `spec_kind(component)`, so the existing `sensor` table (temperature_c
5-40 °C) and every other existing kind are unchanged.
"""
from __future__ import annotations

from .errors import RealityError

TTL_BY_CLASS: dict[str, int | None] = {"reading": 3600, "condition": 86400, "document": 31536000, "identity": None}


def _reading(unit, low, high):
    return dict(attributeClass="reading", unit=unit, min=low, max=high, enum=None)


def _enum(cls, *values):
    return dict(attributeClass=cls, unit=None, min=None, max=None, enum=list(values))


def _plain(cls):
    return dict(attributeClass=cls, unit=None, min=None, max=None, enum=None)


SPECS: dict[str, dict[str, dict]] = {
    "pump": {"pressure_bar": _reading("bar", 1.5, 3.5), "running": _enum("condition", "on", "off"),
             "commissioning_certificate": _plain("document"), "serial": _plain("identity")},
    "gauge": {"pressure_bar": _reading("bar", 0, 6), "serial": _plain("identity")},
    "valve": {"position": _enum("reading", "open", "closed", "partial"), "serial": _plain("identity")},
    "sensor": {"temperature_c": _reading("°C", 5, 40), "serial": _plain("identity")},
    "tank": {"level_pct": _reading("%", 10, 95), "serial": _plain("identity")},
    "exchanger": {"outlet_temperature_c": _reading("°C", 30, 80), "serial": _plain("identity")},
    "panel": {"status": _enum("condition", "normal", "tripped", "alarm"), "serial": _plain("identity")},
    "duct": {"airflow_ok": _enum("condition", "yes", "no"), "serial": _plain("identity")},
    "light": {"working": _enum("condition", "yes", "no")},
    "fire": {"inspection_tag_date": _plain("document"), "pressure_ok": _enum("condition", "yes", "no")},
    "door": {"closed": _enum("condition", "yes", "no")},
    # Contract 3 (Bristol pump house): the pump sump, the steam receiver pressure vessel and the visitor walkway.
    "sump": {"level_pct": _reading("%", 0, 85)},
    "vessel": {"pressure_bar": _reading("bar", 0, 7), "inspection_certificate": _plain("document"), "serial": _plain("identity")},
    "walkway": {"clear": _enum("condition", "yes", "no")},
    # Contract 5 (Tomioka Silk Mill): preserved reeling machines, the National Treasure fabric, conservation sensors.
    "machine": {"vibration_mms": _reading("mm/s", 0, 4.5), "status": _enum("condition", "running", "stopped", "fault"), "serial": _plain("identity")},
    "structure": {"crack_width_mm": _reading("mm", 0, 0.3), "condition": _enum("condition", "sound", "watch", "defect")},
    "sensor:humidity": {"humidity_pct": _reading("%", 40, 65), "temperature_c": _reading("°C", 5, 30), "serial": _plain("identity")},
    "sensor:seismic": {"seismic_gal": _reading("gal", 0, 80), "serial": _plain("identity")},
    "hydrant": {"pressure_ok": _enum("condition", "yes", "no")},
    "camera": {"working": _enum("condition", "yes", "no"), "serial": _plain("identity")},
    "dehumidifier": {"running": _enum("condition", "yes", "no"), "serial": _plain("identity")},
}

# Footprint radius on the x/z plane used by the clearance query (metres). Doors and ceiling luminaires
# are openings/overhead and get no footprint so a path to the door is not reported as blocked by the door.
FOOTPRINT_RADIUS_M: dict[str, float] = {"tank": 1.0, "exchanger": 0.9, "panel": 0.5, "pump": 0.6, "duct": 0.8, "door": 0.0, "light": 0.0,
                                        "sump": 1.2, "vessel": 0.8, "walkway": 0.0,
                                        # Contract 5: roof trusses are overhead and the wall is the room boundary; the CCTV camera is mast-mounted.
                                        "machine": 1.0, "structure": 0.0, "hydrant": 0.3, "camera": 0.0, "dehumidifier": 0.5}
DEFAULT_FOOTPRINT_RADIUS_M = 0.6


def spec_kind(component: dict) -> str:
    """The attribute table a component uses: its `specKind` when the register sets one (Tomioka's humidity and seismic
    sensors), else its `kind`."""
    return component.get("specKind") or component["kind"]


def specs_of(component: dict) -> dict[str, dict]:
    return SPECS.get(spec_kind(component), {})


def supported_attributes(kind: str) -> list[str]:
    return sorted(SPECS.get(kind, {}))


def spec_for(kind: str, attribute: str) -> dict:
    """Return the spec for (kind, attribute) or raise UNSUPPORTED_ATTRIBUTE listing supported attributes."""
    table = SPECS.get(kind)
    if table is None:
        raise RealityError(f"No attribute table exists for component kind '{kind}'.", "UNSUPPORTED_ATTRIBUTE",
                           "Use a registered component kind: " + ", ".join(sorted(SPECS)) + ".")
    spec = table.get(attribute)
    if spec is None:
        raise RealityError(f"Attribute '{attribute}' is not supported for kind '{kind}'. Supported: {', '.join(sorted(table))}.",
                           "UNSUPPORTED_ATTRIBUTE", f"Call resolve or attest with one of: {', '.join(sorted(table))}.")
    return {"kind": kind, "attribute": attribute, "ttlSeconds": TTL_BY_CLASS[spec["attributeClass"]], **spec}


def ttl_for_class(attribute_class: str) -> int | None:
    return TTL_BY_CLASS[attribute_class]


def spec_table() -> dict:
    """The exported spec table for GET /api/properties/{id}/specs."""
    return {
        "ttlSecondsByClass": TTL_BY_CLASS,
        "kinds": {kind: {attribute: {**spec, "ttlSeconds": TTL_BY_CLASS[spec["attributeClass"]]} for attribute, spec in table.items()}
                  for kind, table in SPECS.items()},
        "footprintRadiusM": {"byKind": FOOTPRINT_RADIUS_M, "default": DEFAULT_FOOTPRINT_RADIUS_M},
    }
