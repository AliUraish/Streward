"""Shared paths, HTTP helpers and asset/clip loading for the vision pipeline.

Standalone: imported only by the scripts in vision/, never by the backend.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VISION_DIR = Path(__file__).resolve().parent
ROOT = VISION_DIR.parent
FRAMES_DIR = VISION_DIR / "frames"
RESULTS_DIR = VISION_DIR / "results"
REQUESTS_DIR = RESULTS_DIR / "_requests"
REFERENCE_DIR = VISION_DIR / "reference"

DEFAULT_BACKEND = os.environ.get("STEWARD_BACKEND", "http://127.0.0.1:8001")
DEFAULT_FRONTEND = os.environ.get("STEWARD_FRONTEND", "http://127.0.0.1:3000")
FRAMES_PER_CLIP = 16
DEFECT_KINDS = ("none", "leak", "corrosion", "missing-handwheel")

# REALITY-CONTRACT-4 §1: valve inspections are run by the site engineer agent of each factory.
ENGINEER_BY_SITE = {"myer-plant": "myer-engineer", "bristol-pumps": "bristol-engineer"}


def engineer_for(site: str) -> str:
    """Agent id of the site engineer who owns inspections at `site` (X-Steward-Actor, inspectedBy)."""
    return ENGINEER_BY_SITE.get(site) or f"{site.split('-')[0]}-engineer"


HONESTY_NOTE = (
    "Status comes from an embedding anomaly score: each valve's V-JEPA 2 clip embedding is compared "
    "with the leave-one-out median of the other valves at the same site (plus an optional labelled "
    "reference set). It is not a trained defect classifier, it does not certify equipment and it "
    "replaces no engineer's sign-off. Frames are rendered from a third-party Gaussian-splat capture; "
    "any defect marked synthetic was injected on purpose for the demo."
)


class VisionError(RuntimeError):
    """A failure with a message meant for the operator (printed without a traceback)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel(path: Path) -> str:
    """Path relative to the repo root, with forward slashes (what the backend and MCP see)."""
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def http_json(method: str, url: str, body: object | None = None, timeout: float = 15.0,
              headers: dict | None = None):
    """Tiny JSON-over-HTTP helper (stdlib only). Returns (status, parsed_json_or_text)."""
    data = None
    hdrs = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise VisionError(f"cannot reach {url}: {exc}") from exc
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def http_bytes(url: str, timeout: float = 30.0, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise VisionError(f"GET {url} -> HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise VisionError(f"cannot reach {url}: {exc}") from exc


# ---------------------------------------------------------------- assets

def _pin3(record: dict):
    """Return (x, y, z) floats if the record carries a 3-D world pin, else None.

    Accepts `pin: {x, y, z}` (REALITY-CONTRACT-3 §1) or `pin: [x, y, z]`. A 2-D pin {x, y}
    (the legacy floor-plan pin) is not a world pin and returns None.
    """
    pin = record.get("pin")
    if isinstance(pin, dict) and all(isinstance(pin.get(k), (int, float)) for k in ("x", "y", "z")):
        return float(pin["x"]), float(pin["y"]), float(pin["z"])
    if isinstance(pin, (list, tuple)) and len(pin) == 3 and all(isinstance(v, (int, float)) for v in pin):
        return float(pin[0]), float(pin[1]), float(pin[2])
    return None


def asset_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if isinstance(payload, dict):
        for key in ("assets", "components", "items", "data"):
            if isinstance(payload.get(key), list):
                return [a for a in payload[key] if isinstance(a, dict)]
    return []


def normalise_asset(record: dict) -> dict:
    tag = record.get("tag") or record.get("assetTag") or record.get("id")
    pin = _pin3(record)
    return {
        "tag": tag,
        "id": record.get("id"),
        "name": record.get("name"),
        "kind": (record.get("kind") or "").lower(),
        "system": record.get("system"),
        "subsystem": record.get("subsystem"),
        "description": record.get("description"),
        "status": record.get("status"),
        "pin": {"x": pin[0], "y": pin[1], "z": pin[2]} if pin else None,
        "pinSource": record.get("pinSource"),
        "spec": record.get("spec") or record.get("specs") or record.get("specification"),
        "raw": record,
    }


def fetch_site_assets(site: str, backend: str = DEFAULT_BACKEND) -> tuple[list[dict], str]:
    """Fetch the site's asset register: try GET /scene (contract-3) first, then /components."""
    errors = []
    for path in ("scene", "components"):
        url = f"{backend.rstrip('/')}/api/properties/{site}/{path}"
        try:
            status, payload = http_json("GET", url)
        except VisionError as exc:
            errors.append(str(exc))
            continue
        if status == 200:
            assets = asset_list(payload)
            if assets:
                return [normalise_asset(a) for a in assets], url
            errors.append(f"{url} returned 200 but no asset list")
        else:
            errors.append(f"{url} -> HTTP {status}")
    raise VisionError("could not load the asset register for site "
                      f"'{site}':\n  " + "\n  ".join(errors))


def valves_with_pins(assets: list[dict], site: str) -> list[dict]:
    valves = [a for a in assets if a["kind"] == "valve"]
    if not valves:
        raise VisionError(f"site '{site}' has no assets of kind 'valve' in its register.")
    pinned = [a for a in valves if a["pin"]]
    if not pinned:
        sample = valves[0]["raw"].get("pin")
        raise VisionError(
            f"site '{site}' has {len(valves)} valve(s) but none carries a 3-D world pin {{x, y, z}} "
            f"(first valve's pin is {json.dumps(sample)}). The BACKEND stream adds 3-D pins and "
            "GET /api/properties/<site>/scene per REALITY-CONTRACT-3 §1-2; re-run once that lands.")
    missing = [a["tag"] for a in valves if not a["pin"]]
    if missing:
        print(f"[vision] skipping valves without a 3-D pin: {', '.join(missing)}", file=sys.stderr)
    return pinned


# ---------------------------------------------------------------- clips

def clip_dirs(frames_root: Path) -> list[Path]:
    """Every <frames_root>/<tag>/ holding f00.jpg..f15.jpg, sorted by tag."""
    if not frames_root.is_dir():
        return []
    out = []
    for d in sorted(p for p in frames_root.iterdir() if p.is_dir()):
        if all((d / f"f{i:02d}.jpg").is_file() for i in range(FRAMES_PER_CLIP)):
            out.append(d)
    return out


def frame_paths(clip_dir: Path) -> list[Path]:
    return [clip_dir / f"f{i:02d}.jpg" for i in range(FRAMES_PER_CLIP)]


def read_meta(clip_dir: Path) -> dict:
    p = clip_dir / "meta.json"
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


# The capture route stamps "synthetic defect: <kind>" in a 19 px box at the bottom-left of defected
# frames. Left in, the model would score the label, not the defect, and Claude would read the
# answer. Every frame of every clip gets the same bottom strip blacked out before embedding or
# sending, so clips stay comparable; the frames on disk keep the label for people.
LABEL_STRIP_PX = 20


def mask_label_strip(frame, px: int = LABEL_STRIP_PX):
    import numpy as np

    out = np.array(frame, copy=True)
    if px > 0:
        out[-px:, :, :] = 0
    return out


def load_clip(clip_dir: Path, mask_px: int = LABEL_STRIP_PX):
    """Load the 16 frames as a uint8 array (T, H, W, 3), bottom label strip masked."""
    import numpy as np
    from PIL import Image

    frames = [mask_label_strip(np.asarray(Image.open(p).convert("RGB")), mask_px) for p in frame_paths(clip_dir)]
    shapes = {f.shape for f in frames}
    if len(shapes) != 1:
        raise VisionError(f"{clip_dir}: frames differ in size {shapes}")
    return np.stack(frames)


def load_dotenv(path: Path = ROOT / ".env") -> dict:
    """Parse KEY=VALUE lines without exporting anything or printing values."""
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key] = value
    return out


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def fail(exc: Exception, code: int = 2):
    print(f"[vision] error: {exc}", file=sys.stderr)
    sys.exit(code)
