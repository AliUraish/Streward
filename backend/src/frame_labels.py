"""Labelled eye frames (owner, Oct 18: "the image provided to MCP can also be labelled so it's known what the issue is").

`GET /api/eye/frames/{frameId}/labelled.jpg` returns the frame with its labels burned in, so an agent that only gets the
picture still knows what it shows:
- every visible, unoccluded asset pin as a small tag at its point;
- every judgement of an asset in this frame (a walk label, a site-tour stop) as a ring at the asset in the label's colour
  (green "looks good", blue "looks bad", as on the dashboard) with a tag "V-504 · Looks bad: <what>";
- a caption bar over the top with the worst judgement and its first reason (the regulation, the reading against its band);
- a footer with who looked, the site and the time.
The point is the label's own mark (x, y as fractions of the frame), else the asset's visible pin. Nothing is stored; the
original frame is never changed.
"""
from __future__ import annotations

import io
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .sites import SITE_BY_ID, SITE_IDS

GREEN, BLUE = (34, 197, 94), (59, 130, 246)
WHITE, BLACK = (255, 255, 255), (0, 0, 0)
FONT_FILES = ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
BOLD_FILES = ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") + FONT_FILES


@lru_cache(maxsize=32)
def font(size: int, bold: bool = False):
    for path in BOLD_FILES if bold else FONT_FILES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _point(value) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    x, y = value.get("x"), value.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    return float(x), float(y)


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _wrap(draw: ImageDraw.ImageDraw, text: str, face, width: int, lines: int) -> list[str]:
    out, line = [], ""
    for word in str(text or "").split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=face) <= width:
            line = trial
            continue
        if line:
            out.append(line)
        line = word
        if len(out) == lines:
            break
    if line and len(out) < lines:
        out.append(line)
    if len(out) == lines and " ".join(out) != " ".join(str(text or "").split()):
        while out[-1] and draw.textlength(out[-1] + "…", font=face) > width:
            out[-1] = out[-1][:-1]
        out[-1] = out[-1].rstrip() + "…"
    return out


def find_frame(store, frame_id: str) -> tuple[dict | None, str | None]:
    for site in SITE_IDS:
        record = store.get("eye_frame", frame_id, site)
        if record:
            return record, site
    return None, None


def judgements(store, site: str, frame: dict) -> list[dict]:
    """Every judgement made on this frame: walk labels and site-tour stops that name it, newest first per asset."""
    frame_id = frame["id"]
    found: dict[str, dict] = {}
    rows = [dict(r, _source="walk") for r in store.all("patrol_label", site) if r.get("frameId") == frame_id]
    for tour in store.all("site_tour", site):
        for stop in tour.get("stops") or []:
            if stop.get("frameId") == frame_id:
                rows.append(dict(stop, _source="tour", agentName=tour.get("guideName") or "Site Inspector", at=stop.get("at") or tour.get("startedAt")))
    for inspection in store.all("inspection", site):
        for stop in inspection.get("stops") or []:
            if stop.get("frameId") == frame_id and stop.get("verdict"):
                rows.append(dict(stop, _source="inspection", agentName=inspection.get("inspectorName") or "Site Inspector", at=stop.get("at") or inspection.get("startedAt")))
    for row in sorted(rows, key=lambda r: str(r.get("at") or "")):
        tag = row.get("assetTag")
        if tag:
            found[tag] = row
    pins = {p.get("assetTag"): p for p in frame.get("visiblePins") or [] if isinstance(p, dict)}
    out = []
    for tag, row in found.items():
        point = _point(row.get("mark")) or _point(pins.get(tag))
        reasons = [r for r in row.get("reasons") or [] if r]
        out.append(dict(assetTag=tag, assetName=row.get("assetName"), bad=row.get("verdict") == "bad", title=row.get("title") or ("Looks bad" if row.get("verdict") == "bad" else "Looks good"),
                        reason=reasons[0] if reasons else row.get("observation") or "", point=point, agentName=row.get("agentName"), at=row.get("at")))
    out.sort(key=lambda j: (not j["bad"], j["assetTag"]))
    return out


def render(data: bytes, frame: dict, site: str, found: list[dict]) -> bytes:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    width, height = image.size
    unit = max(0.72, width / 1280)  # small frames (640 px) keep readable text without the caption taking the picture
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    small, tag_face, cap_face, cap_bold = font(round(15 * unit)), font(round(17 * unit), True), font(round(19 * unit)), font(round(20 * unit), True)
    judged = {j["assetTag"] for j in found}

    def tag_box(x: float, y: float, text: str, fill, face, ink=WHITE, pad: int = round(6 * unit)):
        box = draw.textbbox((0, 0), text, font=face)
        w, h = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
        left = min(max(0, x), width - w)
        top = min(max(0, y), height - h)
        draw.rectangle((left, top, left + w, top + h), fill=fill)
        draw.text((left + pad - box[0], top + pad - box[1]), text, font=face, fill=ink)

    # Every visible asset the agent did not judge here: its tag at its point, small and quiet.
    for pin in frame.get("visiblePins") or []:
        point = _point(pin)
        if not point or pin.get("occluded") or pin.get("assetTag") in judged:
            continue
        px, py = point[0] * width, point[1] * height
        draw.ellipse((px - 4 * unit, py - 4 * unit, px + 4 * unit, py + 4 * unit), fill=(255, 255, 255, 230))
        tag_box(px + 8 * unit, py - 12 * unit, str(pin.get("assetTag")), (0, 0, 0, 170), small)
    # Every judgement: a ring in its colour and the verdict next to it.
    for j in found:
        colour = BLUE if j["bad"] else GREEN
        if j["point"]:
            px, py = j["point"][0] * width, j["point"][1] * height
            r = 26 * unit
            draw.ellipse((px - r, py - r, px + r, py + r), outline=colour + (255,), width=max(3, round(5 * unit)))
            draw.ellipse((px - 5 * unit, py - 5 * unit, px + 5 * unit, py + 5 * unit), fill=colour + (255,))
            tag_box(px + r + 6 * unit, py - 16 * unit, _short(f"{j['assetTag']} · {j['title']}", 58), colour + (235,), tag_face)
    # The caption: the worst judgement and why.
    if found:
        top = found[0]
        colour = BLUE if top["bad"] else GREEN
        verdict = "LOOKS BAD" if top["bad"] else "LOOKS GOOD"
        head = f"{verdict}  {top['assetTag']}{' ' + top['assetName'] if top.get('assetName') else ''}"
        lines = _wrap(draw, top.get("reason") or top["title"], cap_face, width - round(48 * unit), 2)
        bar = round((20 + 30 + 26 * len(lines)) * unit)
        draw.rectangle((0, 0, width, bar), fill=(0, 0, 0, 200))
        draw.rectangle((0, 0, round(8 * unit), bar), fill=colour + (255,))
        draw.text((round(24 * unit), round(12 * unit)), head, font=cap_bold, fill=WHITE)
        for k, line in enumerate(lines):
            draw.text((round(24 * unit), round((44 + 26 * k) * unit)), line, font=cap_face, fill=(230, 230, 230))
        if len(found) > 1:
            more = f"+{len(found) - 1} more marked in this view"
            w = draw.textlength(more, font=small)
            draw.text((width - w - round(16 * unit), round(14 * unit)), more, font=small, fill=(200, 200, 200))
    # The footer: who looked, where, when.
    who = next((j.get("agentName") for j in found if j.get("agentName")), None) or frame.get("actorName") or "Agent eye"
    when = frame.get("at") or ""
    try:
        when = datetime.fromisoformat(str(when).replace("Z", "+00:00")).strftime("%d %b %H:%M UTC")
    except ValueError:
        pass
    footer = f"{who} · {SITE_BY_ID.get(site, {}).get('name', site)} · {when}"
    fw = draw.textlength(footer, font=small)
    fh = round(28 * unit)
    draw.rectangle((0, height - fh, fw + round(24 * unit), height), fill=(0, 0, 0, 180))
    draw.text((round(12 * unit), height - fh + round(6 * unit)), footer, font=small, fill=(230, 230, 230))
    out = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    buffer = io.BytesIO()
    out.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def labelled_bytes(service, frame_id: str, extra: list[dict] | None = None) -> bytes:
    """The frame for an email or a report, labelled like the MCP copy (owner, Oct 18: "the pics aren't marked"). `extra` adds
    judgements made for this message (e.g. a reading above its band) that win over stored ones for their assets: {assetTag,
    assetName?, bad, title, reason, agentName?, at?}. Raises like the frame file when the frame is missing; any labelling
    problem gives the plain frame."""
    data = service.eye.frame_path(frame_id).read_bytes()
    try:
        frame, site = find_frame(service.store, frame_id)
        if not frame:
            return data
        found = judgements(service.store, site, frame)
        if extra:
            pins = {p.get("assetTag"): p for p in frame.get("visiblePins") or [] if isinstance(p, dict)}
            own = [dict(j, point=j.get("point") or _point(pins.get(j["assetTag"]))) for j in extra if j.get("assetTag")]
            tags = {j["assetTag"] for j in own}
            found = sorted(own + [j for j in found if j["assetTag"] not in tags], key=lambda j: (not j["bad"], j["assetTag"]))
        return render(data, frame, site, found)
    except Exception:  # a label must never cost the message its picture
        return data


def labelled(service, frame_id: str) -> tuple[bytes, int]:
    """The frame with its labels burned in, and how many judgements it carries. Raises RealityError (404) like the frame file."""
    path = service.eye.frame_path(frame_id)
    frame, site = find_frame(service.store, frame_id)
    if not frame:
        return path.read_bytes(), 0
    found = judgements(service.store, site, frame)
    return render(path.read_bytes(), frame, site, found), len(found)
