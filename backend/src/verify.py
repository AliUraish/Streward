"""Verification engine: six deterministic checks over a submitted observation.

No vision model is used. Identity comes from a stated tag (JSON `tag`/`statedTag`, message body, or filename).
Time prefers EXIF DateTimeOriginal in JPEG bytes, then the explicit observedAt, then the provider receipt
time, then the submission time. Integrity hashes file bytes or the canonical JSON of the observation.
"""
from __future__ import annotations

import hashlib
import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .signing import VERIFIER_VERSION, canonical_json

TAG_RE = re.compile(r"\b[A-Z]{1,3}-\d{3,4}\b")
REFERENCE_RE = re.compile(r"\b[A-Z]{2}-[A-Z]+\d{3,4}-[A-Z_]+-\d{4}\b")
SIBLING_RADIUS_M = 3.0
WINDOW_BEFORE = timedelta(minutes=5)
WINDOW_AFTER = timedelta(minutes=2)
PASS, CLARIFY, REJECT = "pass", "needs_clarification", "rejected"


@dataclass
class Observation:
    property_id: str
    asset_tag: str
    attribute: str
    value: Any = None
    observed_at: str | None = None
    stated_tag: str | None = None
    body: str = ""
    filename: str | None = None
    file_bytes: bytes | None = None
    source: dict = field(default_factory=lambda: {"kind": "human", "ref": "unknown"})
    received_at: str | None = None


def parse_time(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def exif_datetime_original(data: bytes | None) -> tuple[datetime | None, str]:
    """DateTimeOriginal from JPEG EXIF via Pillow when installed; returns (datetime, explanation)."""
    if not data or data[:3] != b"\xff\xd8\xff":
        return None, "no JPEG EXIF available"
    try:
        from PIL import Image  # Pillow is a transitive dependency of reportlab; guarded anyway.
    except ImportError:
        return None, "Pillow is not installed, so EXIF was not read"
    try:
        image = Image.open(io.BytesIO(data))
        exif = image.getexif()
        ifd = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
        raw = ifd.get(36867) or exif.get(36867) or exif.get(306)
        offset = ifd.get(36881)
    except Exception:
        return None, "JPEG EXIF could not be parsed"
    if not raw or not isinstance(raw, str):
        return None, "JPEG carries no EXIF DateTimeOriginal"
    try:
        parsed = datetime.strptime(raw.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, "EXIF DateTimeOriginal is malformed"
    if isinstance(offset, str) and re.fullmatch(r"[+-]\d{2}:\d{2}", offset.strip()):
        sign = 1 if offset[0] == "+" else -1
        hours, minutes = int(offset[1:3]), int(offset[4:6])
        parsed = parsed.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))
        return parsed.astimezone(timezone.utc), "EXIF DateTimeOriginal with OffsetTimeOriginal"
    return parsed.replace(tzinfo=timezone.utc), "EXIF DateTimeOriginal (no offset; treated as UTC)"


def relative_position(target: dict, origin: dict) -> str:
    """'1.9 m west' describing where `target` lies relative to `origin` on the floor plane (x east, z south)."""
    dx = float(target["position"][0]) - float(origin["position"][0])
    dz = float(target["position"][2]) - float(origin["position"][2])
    distance = math.hypot(dx, dz)
    east_west = "east" if dx > 0 else "west"
    north_south = "south" if dz > 0 else "north"
    if distance < 0.05:
        return "at the same position"
    if abs(dx) >= 2 * abs(dz):
        direction = east_west
    elif abs(dz) >= 2 * abs(dx):
        direction = north_south
    else:
        direction = f"{north_south}-{east_west}"
    return f"{distance:.1f} m {direction}"


def distance_3d(a: dict, b: dict) -> float:
    return math.sqrt(sum((float(p) - float(q)) ** 2 for p, q in zip(a["position"], b["position"])))


def stated_tag_from(observation: Observation) -> tuple[str | None, str]:
    if observation.stated_tag:
        return observation.stated_tag.strip().upper(), "stated tag"
    body = REFERENCE_RE.sub(" ", observation.body or "")
    match = TAG_RE.search(body)
    if match:
        return match.group(0), "message body"
    if observation.filename:
        match = TAG_RE.search(observation.filename.upper().replace("_", "-"))
        if match:
            return match.group(0), "filename"
    return None, "none"


def to_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match and re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*[^\d]*", value):
            return float(match.group(0))
    return None


def integrity_hash(observation: Observation) -> tuple[str, str]:
    if observation.file_bytes:
        return hashlib.sha256(observation.file_bytes).hexdigest(), f"SHA-256 of {len(observation.file_bytes):,} file bytes"
    payload = dict(propertyId=observation.property_id, assetTag=observation.asset_tag, attribute=observation.attribute,
                   value=observation.value, observedAt=observation.observed_at, statedTag=observation.stated_tag,
                   source=observation.source, body=observation.body or "")
    return hashlib.sha256(canonical_json(payload)).hexdigest(), "SHA-256 of the canonical JSON observation (no file)"


def verify_observation(observation: Observation, component: dict, spec: dict, components: list[dict],
                       work_item: dict | None, hash_owner: Callable[[str], dict | None], now: datetime | None = None) -> dict:
    """Run the six checks. Returns checks, verdict, reasons, evidenceHashes, the effective observedAt and statedTag."""
    now = now or datetime.now(timezone.utc)
    outcomes: list[tuple[str, str, str]] = []
    by_tag = {c["tag"]: c for c in components}
    expected_tag = component["tag"]

    # 1. scope
    if work_item is not None and work_item.get("propertyId") != observation.property_id:
        outcomes.append(("scope", REJECT, f"Work item {work_item.get('reference', work_item.get('id'))} belongs to property "
                                          f"{work_item.get('propertyId')}, submission is for {observation.property_id}."))
    elif work_item is not None and work_item.get("assetTag") != observation.asset_tag:
        outcomes.append(("scope", REJECT, f"Work item {work_item.get('reference')} concerns {work_item.get('assetTag')}, "
                                          f"submission names {observation.asset_tag}."))
    elif observation.asset_tag not in by_tag:
        outcomes.append(("scope", REJECT, f"{observation.asset_tag} is not registered at property {observation.property_id}."))
    else:
        suffix = f" and work item {work_item['reference']}" if work_item else ""
        outcomes.append(("scope", PASS, f"Property {observation.property_id} matches the asset register{suffix}."))

    # 2. identity
    stated, origin = stated_tag_from(observation)
    if stated is None:
        outcomes.append(("identity", CLARIFY, f"No tag plate stated for {expected_tag}; reply with the tag plate text "
                                              "or include the tag in the JSON `statedTag` or the photo filename."))
    elif stated == expected_tag:
        outcomes.append(("identity", PASS, f"Tag plate reads {stated} (from {origin}), matching expected {expected_tag}."))
    elif stated in by_tag:
        where = relative_position(component, by_tag[stated])
        outcomes.append(("identity", REJECT, f"tag plate reads {stated}, expected {expected_tag}, {expected_tag} is {where} of {stated}"))
    else:
        outcomes.append(("identity", REJECT, f"tag plate reads {stated}, which is not a registered asset; expected {expected_tag}."))

    # 3. geometry
    probe = by_tag.get(stated or expected_tag) or component
    siblings = [c for c in components if c["kind"] == component["kind"] and c["id"] != component["id"]
                and distance_3d(c, component) <= SIBLING_RADIUS_M]
    sibling_note = ("; sibling of the same kind within 3 m: " + ", ".join(
        f"{c['tag']} ({c['name']}, {relative_position(c, component)})" for c in siblings)) if siblings else ""
    x, y, z = component["position"]
    if probe["id"] == component["id"]:
        outcomes.append(("geometry", PASS, f"{expected_tag} is registered as {component['id']} at ({x}, {y}, {z}){sibling_note}."))
    else:
        outcomes.append(("geometry", REJECT, f"{probe['tag']} is {probe['id']} at ({probe['position'][0]}, {probe['position'][1]}, "
                                             f"{probe['position'][2]}), not the expected {component['id']}{sibling_note}."))

    # 4. plausibility
    unit = spec.get("unit") or ""
    if spec.get("enum"):
        text = str(observation.value).strip().casefold() if observation.value is not None else ""
        if not text:
            outcomes.append(("plausibility", CLARIFY, f"No value stated; reply with one of {', '.join(spec['enum'])}."))
        elif text in spec["enum"]:
            outcomes.append(("plausibility", PASS, f"'{text}' is a permitted value for {observation.attribute}."))
        else:
            outcomes.append(("plausibility", REJECT, f"'{observation.value}' is not one of {', '.join(spec['enum'])} for {observation.attribute}."))
    elif spec.get("min") is not None:
        number = to_number(observation.value)
        if number is None:
            outcomes.append(("plausibility", CLARIFY, f"No numeric value stated for {observation.attribute}; reply with a number in {unit}."))
        elif number > spec["max"]:
            outcomes.append(("plausibility", CLARIFY, f"{number:g} {unit} exceeds {spec['max']:g} {unit} spec; confirm with a second reading"))
        elif number < spec["min"]:
            outcomes.append(("plausibility", CLARIFY, f"{number:g} {unit} is below {spec['min']:g} {unit} spec; confirm with a second reading"))
        else:
            outcomes.append(("plausibility", PASS, f"{number:g} {unit} is inside the {spec['min']:g}–{spec['max']:g} {unit} spec range."))
    else:
        if observation.value in (None, ""):
            outcomes.append(("plausibility", CLARIFY, f"No value stated for the {spec['attributeClass']} attribute {observation.attribute}."))
        else:
            outcomes.append(("plausibility", PASS, f"{spec['attributeClass'].title()} value recorded: {str(observation.value)[:80]}."))

    # 5. time
    exif_time, exif_note = exif_datetime_original(observation.file_bytes)
    explicit = parse_time(observation.observed_at)
    receipt = parse_time(observation.received_at)
    if exif_time:
        observed, basis = exif_time, exif_note
    elif explicit:
        observed, basis = explicit, f"submitted observedAt ({exif_note})"
    elif receipt:
        observed, basis = receipt, f"provider receipt time ({exif_note})"
    else:
        observed, basis = now, f"submission time ({exif_note})"
    upper = now + WINDOW_AFTER
    lower = None
    if work_item is not None and parse_time(work_item.get("createdAt")):
        lower = parse_time(work_item["createdAt"]) - WINDOW_BEFORE
    elif spec.get("ttlSeconds"):
        lower = now - timedelta(seconds=spec["ttlSeconds"])
    if observed > upper:
        outcomes.append(("time", REJECT, f"observedAt {iso(observed)} ({basis}) is more than 2 minutes in the future."))
    elif lower is not None and observed < lower:
        outcomes.append(("time", REJECT, f"observedAt {iso(observed)} ({basis}) is before the accepted window starting {iso(lower)}."))
    else:
        outcomes.append(("time", PASS, f"observedAt {iso(observed)} ({basis}) is inside the accepted window."))

    # 6. integrity
    digest, how = integrity_hash(observation)
    owner = hash_owner(digest)
    current_item = work_item["id"] if work_item else None
    if owner and (owner.get("workItemId") or None) != current_item:
        previous = owner.get("workItemId") or owner.get("attestationId") or "an earlier submission"
        outcomes.append(("integrity", REJECT, f"evidence reused from {previous} ({how}: {digest[:16]}…)."))
    else:
        outcomes.append(("integrity", PASS, f"{how}: {digest}."))

    verdict = "accepted"
    if any(outcome == REJECT for _, outcome, _ in outcomes):
        verdict = "rejected"
    elif any(outcome == CLARIFY for _, outcome, _ in outcomes):
        verdict = "needs_clarification"
    checks = [dict(name=name, passed=outcome == PASS, reason=reason) for name, outcome, reason in outcomes]
    reasons = [reason for name, outcome, reason in outcomes if outcome != PASS]
    return dict(checks=checks, verdict=verdict, reasons=reasons, evidenceHashes=[digest], observedAt=iso(observed),
                statedTag=stated, verifierVersion=VERIFIER_VERSION)
