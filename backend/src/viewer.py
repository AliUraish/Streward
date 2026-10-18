"""3-D scene, pins and the per-site viewer command stream (contract 3 §2).

- `PUT /api/properties/{id}/assets/{assetTag}/pin {x, y, z, source}` stores a pin in the scan's world coordinates;
  `source: "placed"` comes from the dashboard's operator pin tool, `"estimated"` resets to the seeded estimate.
- `POST /api/properties/{id}/viewer {action: focus|orbit|reset|highlight, assetTag?, issueId?}` appends a command;
  the dashboard viewer polls `GET /api/properties/{id}/viewer?since=<seq>` and executes it. This is how an MCP tool
  or an agent moves the 3-D view. Commands carry a per-site monotonic `seq` and the asset's pin.
- `GET /api/properties/{id}/scene` is the compact payload for `get_scene`: environment, SOG URL, credit, camera
  presets and every asset with its pin and open issues.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from .agents import display_name
from .errors import RealityError
from .registers import estimated_pin
from .store import now, uid

ACTIONS = ("focus", "orbit", "reset", "highlight")
ROOT = Path(__file__).resolve().parents[2]
FRAME_RE = re.compile(r"^f\d{2}\.(jpg|jpeg|png|webp)$")


class ViewerService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.frames_root = ROOT / "vision" / "frames"

    @property
    def reality(self):
        return self.service.reality

    def _seq(self, site_id: str) -> int:
        with self.store.lock:
            value = int(self.store.meta(f"viewer:seq:{site_id}") or 0) + 1
            self.store.meta(f"viewer:seq:{site_id}", str(value))
            return value

    def post(self, site_id: str, action: str, asset_tag: str | None, issue_id: str | None, actor: str) -> dict:
        self.service.require_property(site_id)
        if action not in ACTIONS:
            raise RealityError("action must be focus, orbit, reset or highlight.", "INVALID_REQUEST", "Pick one of focus, orbit, reset, highlight.")
        component = None
        if issue_id:
            issue = self.service.issues.get(issue_id)
            if issue.get("siteId") not in (None, site_id):
                raise RealityError("Issue belongs to another site.", "SCOPE", "Use the issue's own site.", 409)
            asset_tag = asset_tag or issue.get("assetTag")
        if asset_tag:
            component = self.reality.component_by_tag(site_id, asset_tag)
        elif action != "reset":
            raise RealityError(f"{action} needs an assetTag or an issueId.", "INVALID_REQUEST", "Pass assetTag or issueId, or use action reset.")
        command = dict(id=uid("vc"), seq=self._seq(site_id), siteId=site_id, action=action, assetTag=component["tag"] if component else None,
                       issueId=issue_id, pin=(component or {}).get("pin"), pinSource=(component or {}).get("pinSource"), issuedBy=actor,
                       issuedByName=display_name(actor), at=now())
        self.store.put("viewer_command", command, site_id)
        self.reality.mirror.put("viewer_command", command, site_id)
        self.service.telemetry.record(actor, "tool", "focus_view", tokens=60, site_id=site_id, detail=f"{action} {command['assetTag'] or ''}".strip())
        return command

    def commands(self, site_id: str, since: int = 0, limit: int = 50) -> dict:
        self.service.require_property(site_id)
        commands = sorted((c for c in self.store.all("viewer_command", site_id) if c["seq"] > since), key=lambda c: c["seq"])
        return dict(siteId=site_id, latest=int(self.store.meta(f"viewer:seq:{site_id}") or 0), commands=commands[:limit])

    def set_pin(self, site_id: str, asset_tag: str, x: float, y: float, z: float, source: str, actor: str) -> dict:
        component = self.reality.component_by_tag(site_id, asset_tag)
        if source not in ("placed", "estimated"):
            raise RealityError("source must be placed or estimated.", "INVALID_REQUEST", "Send source 'placed' from the pin tool.")
        if source == "estimated":
            pin = estimated_pin(site_id, component)
        else:
            values = [x, y, z]
            if any(v is None or not math.isfinite(float(v)) or abs(float(v)) > 1000 for v in values):
                raise RealityError("x, y and z must be finite numbers within ±1000 m of the scan origin.", "INVALID_REQUEST", "Pick the point again.")
            pin = dict(x=round(float(x), 4), y=round(float(y), 4), z=round(float(z), 4))
        component.update(pin=pin, pinSource=source, pinPlacedAt=now() if source == "placed" else None, pinPlacedBy=actor if source == "placed" else None)
        self.store.put("component", component, site_id)
        self.reality.emit_change(site_id, "pin", component["id"], f"{component['tag']} pin {'placed' if source == 'placed' else 'reset to estimate'} at "
                                 f"({pin['x']}, {pin['y']}, {pin['z']}).", component["tag"], extra=dict(assetTag=component["tag"], source=source))
        return component

    def scene(self, site_id: str) -> dict:
        prop = self.service.require_property(site_id)
        environment = prop.get("environment") or {}
        by_asset = self.service.issues.open_by_asset(site_id)
        severity_rank = {"high": 3, "medium": 2, "low": 1}
        assets = []
        for component in self.reality.components(site_id):
            issues = by_asset.get(component["tag"], [])
            top = max((i["severity"] for i in issues), key=lambda s: severity_rank.get(s, 0), default="none")
            assets.append(dict(assetTag=component["tag"], componentId=component["id"], name=component["name"], kind=component["kind"],
                               pin=component.get("pin"), pinSource=component.get("pinSource", "estimated"), severity=top,
                               issueIds=[i["id"] for i in issues]))
        return dict(siteId=site_id, name=prop["name"], environment=environment, sogMetaUrl=environment.get("sogMetaUrl"),
                    credit=environment.get("credit"), viewerUrl=environment.get("viewerUrl"), cameraPresets=environment.get("cameraPresets", []),
                    assets=assets, openIssues=sum(len(v) for v in by_asset.values()),
                    estimatedPins=sum(1 for a in assets if a["pinSource"] != "placed"),
                    pinNote="Estimated pins are scattered around the scan origin from the register layout until an operator places them.")

    def frames(self, site_id: str, asset_tag: str) -> dict:
        component = self.reality.component_by_tag(site_id, asset_tag)
        folder = self.frames_root / site_id / component["tag"]
        names = sorted(p.name for p in folder.iterdir() if FRAME_RE.match(p.name)) if folder.is_dir() else []
        return dict(siteId=site_id, assetTag=component["tag"], frames=[f"/api/vision/frames/{site_id}/{component['tag']}/{name}" for name in names],
                    caption="frames rendered from the hosted capture",
                    hint=None if names else "No capture frames yet: run the valve inspection (inspect_valves / vision/capture.py).")

    def frame_path(self, site_id: str, asset_tag: str, name: str) -> Path:
        component = self.reality.component_by_tag(site_id, asset_tag)
        if not FRAME_RE.match(name):
            raise RealityError("Frame not found.", "NOT_FOUND", "Use a frame name from the frames listing.", 404)
        path = self.frames_root / site_id / component["tag"] / name
        if not path.is_file():
            raise RealityError("Frame not found.", "NOT_FOUND", "Use a frame name from the frames listing.", 404)
        return path
