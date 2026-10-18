#!/usr/bin/env python3
"""Get a 16-frame orbit around every pinned valve of a site and store it for jepa.py.

    vision/.venv/bin/python vision/capture.py <site> [--defect TAG=kind ...] [--source capture|eye]
                                              [--base http://127.0.0.1:3000] [--backend http://127.0.0.1:8001]

1. Loads the asset register from the backend (GET /api/properties/<site>/scene, else /components)
   and keeps assets of kind 'valve' with a 3-D pin {x, y, z}.
2. Frame source (one source per run, so the valves stay comparable):
   - capture (default): launches headless Chrome (SwiftShader WebGL), opens
     <base>/capture?site=<site>&asset=<tag>&frames=16&defect=<kind>&pos=<x,y,z> per valve, waits for
     window.__done === true and reads window.__frames (data URLs) and window.__capture.
   - eye: the site engineer's own agent eye (REALITY-CONTRACT-4 §2):
     POST <backend>/api/eye/<site>/act {action: 'orbit', params: {assetTag, frames: 16}} with header
     X-Steward-Actor: <site engineer>, then downloads the returned frames. If the eye endpoint
     answers 404 on the first valve, the whole run falls back to the capture route.
3. Writes vision/frames/<site>/<tag>/f00.jpg..f15.jpg + meta.json, and frames/<site>/manifest.json.

--defect TAG=kind (kind: leak | corrosion | missing-handwheel) asks the source to apply a labelled
synthetic edit near that valve's pin. Such clips are always recorded as synthetic: true;
defectConfirmed says whether the source echoed the edit back.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

from PIL import Image

from cdp import DEFAULT_CHROME, GPU_FLAGS, SWIFTSHADER_FLAGS, CDPClosed, CDPError, Chrome, Session
from common import (DEFAULT_BACKEND, DEFAULT_FRONTEND, DEFECT_KINDS, FRAMES_DIR, FRAMES_PER_CLIP, VisionError,
                    asset_list, engineer_for, fail, fetch_site_assets, http_bytes, http_json, normalise_asset,
                    now_iso, read_meta, rel, valves_with_pins, write_json)

STATE_JS = """(() => ({
  done: window.__done === true,
  n: Array.isArray(window.__frames) ? window.__frames.length : -1,
  error: window.__error ? String(window.__error) : null,
  href: location.href,
  status: (document.querySelector('[data-testid="capture-status"]') || {}).textContent || null
}))()"""


class EyeUnavailable(VisionError):
    """The agent-eye endpoint is not there (HTTP 404)."""


def parse_defects(items: list[str]) -> dict[str, str]:
    out = {}
    for item in items or []:
        tag, sep, kind = item.partition("=")
        if not sep or not tag or kind not in DEFECT_KINDS:
            raise VisionError(f"bad --defect {item!r}; expected TAG=kind with kind in {', '.join(DEFECT_KINDS)}")
        out[tag] = kind
    return out


def _short(obj, n: int = 300) -> str:
    return (obj if isinstance(obj, str) else json.dumps(obj))[:n]


# ---------------------------------------------------------------- source: /capture route (Chrome over CDP)

def capture_url(base: str, site: str, tag: str, defect: str, frames: int, pin: dict | None = None) -> str:
    q = {"site": site, "asset": tag, "frames": frames, "defect": defect}
    if pin:  # the route prefers the backend's own 3-D pin and falls back to pos=x,y,z
        q["pos"] = f"{pin['x']:.4f},{pin['y']:.4f},{pin['z']:.4f}"
    return f"{base.rstrip('/')}/capture?{urllib.parse.urlencode(q)}"


def check_route(base: str, site: str, tag: str) -> None:
    url = capture_url(base, site, tag, "none", FRAMES_PER_CLIP)
    status, _ = http_json("GET", url, timeout=90)
    if status == 404:
        raise VisionError(f"the capture route is not there yet: GET {url} -> 404. The VIEWER stream builds "
                          "frontend/src/app/capture (REALITY-CONTRACT-3 §2); re-run once it lands.")
    if status >= 500:
        raise VisionError(f"the capture route errored: GET {url} -> HTTP {status}")


def decode_data_url(data_url: str) -> Image.Image:
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        raise VisionError(f"window.__frames entry is not an image data URL: {str(data_url)[:60]!r}")
    _, b64 = data_url.split(",", 1)
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


async def grab(session: Session, url: str, frames: int, timeout: float) -> tuple[list[Image.Image], dict]:
    await session.send("Page.navigate", {"url": url})
    t0 = time.monotonic()
    state: dict = {}
    last_n, last_log = -2, 0.0
    while time.monotonic() - t0 < timeout:
        await asyncio.sleep(0.5)
        try:
            left = timeout - (time.monotonic() - t0)
            state = await session.evaluate(STATE_JS, timeout=min(60.0, max(5.0, left))) or {}
        except CDPClosed:
            raise
        except CDPError:
            continue  # page mid-navigation or main thread busy rendering
        if state.get("error"):
            raise VisionError(f"capture route reported window.__error: {state['error']}")
        if state.get("done"):
            break
        now = time.monotonic()
        if state.get("n") != last_n or now - last_log > 30:
            last_n, last_log = state.get("n"), now
            print(f"[capture]   {now - t0:5.0f}s frames={state.get('n')} {state.get('status') or ''}",
                  file=sys.stderr, flush=True)
    else:
        hint = "; ".join(session.console[-5:]) or "no console errors"
        raise VisionError(f"window.__done not set within {timeout:.0f}s at {url} (last state {state}; {hint}). "
                          "Is the VIEWER stream's /capture route rendering?")
    data = await session.evaluate("window.__frames", timeout=120)
    route = await session.evaluate("window.__capture ? JSON.parse(JSON.stringify(window.__capture)) : null",
                                   timeout=30)
    if not isinstance(data, list) or len(data) < frames:
        raise VisionError(f"window.__frames has {len(data) if isinstance(data, list) else 'no'} frames, "
                          f"expected {frames}")
    return [decode_data_url(d) for d in data[:frames]], {
        "seconds": round(time.monotonic() - t0, 2), "consoleTail": session.console[-5:], "route": route}


GL_RENDERER_JS = """(() => {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl2') || c.getContext('webgl');
  if (!gl) return null;
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
})()"""


async def _gl_renderer(session: Session) -> str | None:
    try:
        return await session.evaluate(GL_RENDERER_JS, timeout=30)
    except CDPError:
        return None


async def capture_route_all(site, valves, defects, base, chrome_path, frames, timeout, renderer, headful, store):
    """renderer: 'auto' tries the GPU (ANGLE Metal) and falls back to SwiftShader when WebGL is missing."""
    order = {"auto": ["gpu", "swiftshader"], "gpu": ["gpu"], "swiftshader": ["swiftshader"]}[renderer]
    for attempt, mode in enumerate(order):
        flags = GPU_FLAGS if mode == "gpu" else SWIFTSHADER_FLAGS
        with Chrome(chrome_path, headless=not headful, gl_flags=flags) as chrome:
            browser = chrome.version.get("Browser", "Chrome")
            async with Session(chrome.page_ws_url()) as session:
                await session.send("Page.enable")
                await session.send("Runtime.enable")
                gl = await _gl_renderer(session)
                print(f"[capture] {browser} on CDP port {chrome.port} ({mode}; WebGL: {gl or 'unavailable'})",
                      file=sys.stderr)
                if not gl:
                    if attempt + 1 < len(order):
                        print(f"[capture] no WebGL with {mode} flags; retrying with {order[attempt + 1]}",
                              file=sys.stderr)
                        continue
                    raise VisionError(f"headless Chrome has no WebGL with the {mode} flags")
                await _capture_valves(session, site, valves, defects, base, frames, timeout, browser, mode, gl,
                                      store)
                return


async def _capture_valves(session, site, valves, defects, base, frames, timeout, browser, mode, gl, store):
    for v in valves:
        defect = defects.get(v["tag"], "none")
        url = capture_url(base, site, v["tag"], defect, frames, v["pin"])
        print(f"[capture] {v['tag']} defect={defect} via /capture ...", file=sys.stderr, flush=True)
        imgs, info = await grab(session, url, frames, timeout)
        route = info["route"] or {}
        store(v, defect, imgs, {
            "source": "capture-route", "url": url, "browser": browser, "renderer": mode, "glRenderer": gl,
            "renderSeconds": info["seconds"],
            "route": info["route"],  # window.__capture: pin used, arc, radius, elev, fov, probe, timings
            "defectConfirmed": (route.get("defect") == defect) if defect != "none" and route else None,
            "note": "frames rendered from the hosted third-party capture; defect edits are synthetic",
        })


# ---------------------------------------------------------------- source: the engineer's agent eye

def eye_frame_image(backend: str, item: dict) -> Image.Image:
    if isinstance(item.get("jpegBase64"), str):
        data = base64.b64decode(item["jpegBase64"].split(",", 1)[-1])
    else:
        url = item.get("frameUrl") or item.get("url")
        if not url and item.get("frameId"):
            url = f"/api/eye/frames/{item['frameId']}.jpg"
        if not url:
            raise VisionError(f"eye frame has no frameUrl, frameId or jpegBase64: {_short(item)}")
        data = http_bytes(urllib.parse.urljoin(backend.rstrip("/") + "/", url))
    return Image.open(io.BytesIO(data)).convert("RGB")


def eye_orbit(backend: str, site: str, tag: str, frames: int, actor: str, defect: str, timeout: float):
    url = f"{backend.rstrip('/')}/api/eye/{site}/act"
    params = {"assetTag": tag, "frames": frames}
    if defect != "none":
        params["defect"] = defect
    t0 = time.monotonic()
    status, resp = http_json("POST", url, {"action": "orbit", "params": params}, timeout=timeout,
                             headers={"X-Steward-Actor": actor})
    if status == 404:
        raise EyeUnavailable(f"POST {url} -> 404 ({_short(resp, 160)})")
    if status >= 300:
        raise VisionError(f"POST {url} as {actor} -> HTTP {status}: {_short(resp)}")
    items = resp if isinstance(resp, list) else None
    if items is None and isinstance(resp, dict):
        items = next((resp[k] for k in ("frames", "items", "results", "orbit") if isinstance(resp.get(k), list)), None)
    if not items or len(items) < frames:
        raise VisionError(f"eye orbit for {tag} returned {len(items or [])} frame(s), expected {frames}: {_short(resp)}")
    items = [it for it in items[:frames] if isinstance(it, dict)]
    imgs = [eye_frame_image(backend, it) for it in items]
    echoed = [it.get("defect") for it in items] + ([resp.get("defect")] if isinstance(resp, dict) else [])
    return imgs, {
        "seconds": round(time.monotonic() - t0, 2),
        "actor": next((it.get("actor") for it in items if it.get("actor")), actor),
        "frames": [{"frameId": it.get("frameId"), "frameUrl": it.get("frameUrl"), "camera": it.get("camera"),
                    "visiblePins": it.get("visiblePins"), "at": it.get("at")} for it in items],
        "defectConfirmed": (defect in echoed) if defect != "none" else None,
    }


def eye_all(site, valves, defects, backend, frames, timeout, actor, store) -> bool:
    """Orbit every valve with the agent eye. False if the eye is not there (404 on the first valve)."""
    for i, v in enumerate(valves):
        defect = defects.get(v["tag"], "none")
        print(f"[capture] {v['tag']} defect={defect} via agent eye as {actor} ...", file=sys.stderr, flush=True)
        try:
            imgs, info = eye_orbit(backend, site, v["tag"], frames, actor, defect, timeout)
        except EyeUnavailable as exc:
            if i == 0:
                print(f"[capture] agent eye unavailable ({exc}); falling back to the /capture route",
                      file=sys.stderr)
                return False
            raise VisionError(f"agent eye 404'd for {v['tag']} after earlier valves succeeded ({exc}); refusing "
                              "to mix frame sources at one site. Re-run with --source capture.") from exc
        store(v, defect, imgs, {
            "source": "eye", "actor": info["actor"], "eyeEndpoint": f"{backend.rstrip('/')}/api/eye/{site}/act",
            "renderSeconds": info["seconds"], "eyeFrames": info["frames"], "defectConfirmed": info["defectConfirmed"],
            "note": "frames from the site engineer's agent eye on the hosted third-party capture; defect edits are "
                    "synthetic",
        })
    return True


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site")
    ap.add_argument("--defect", action="append", default=[], metavar="TAG=kind")
    ap.add_argument("--source", choices=["capture", "eye"], default="capture",
                    help="capture: the /capture route in our own headless Chrome (default); eye: the site "
                         "engineer's agent eye via POST /api/eye/<site>/act, falling back to capture on 404")
    ap.add_argument("--actor", help="X-Steward-Actor for the eye (default: the site engineer, e.g. myer-engineer)")
    ap.add_argument("--base", default=DEFAULT_FRONTEND, help="frontend origin serving /capture")
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--chrome", default=DEFAULT_CHROME)
    ap.add_argument("--renderer", choices=["auto", "gpu", "swiftshader"], default="auto",
                    help="WebGL for our Chrome: auto = GPU (ANGLE Metal) first, SwiftShader if WebGL is missing "
                         "(default); gpu; swiftshader (--use-angle=swiftshader --enable-unsafe-swiftshader)")
    ap.add_argument("--frames", type=int, default=FRAMES_PER_CLIP)
    ap.add_argument("--timeout", type=float, default=300.0, help="seconds per valve")
    ap.add_argument("--only", help="comma-separated valve tags to capture (default: all pinned valves)")
    ap.add_argument("--headful", action="store_true", help="show the browser window (debugging)")
    ap.add_argument("--out-root", type=Path, help="default vision/frames/<site>")
    ap.add_argument("--assets-file", type=Path,
                    help="offline override: JSON asset list ({assets:[...]} or [...]) used instead of the backend")
    a = ap.parse_args(argv)
    actor = a.actor or engineer_for(a.site)
    out_root = a.out_root or FRAMES_DIR / a.site
    written: list[dict] = []
    try:
        if a.frames != FRAMES_PER_CLIP:
            raise VisionError(f"jepa.py expects {FRAMES_PER_CLIP} frames per clip")
        defects = parse_defects(a.defect)
        if a.assets_file:
            assets = [normalise_asset(x) for x in asset_list(json.loads(a.assets_file.read_text()))]
            asset_source = f"file:{rel(a.assets_file)}"
        else:
            assets, asset_source = fetch_site_assets(a.site, a.backend)
        valves = valves_with_pins(assets, a.site)
        if a.only:
            wanted = {t.strip() for t in a.only.split(",") if t.strip()}
            valves = [v for v in valves if v["tag"] in wanted]
        unknown = set(defects) - {v["tag"] for v in valves}
        if unknown:
            raise VisionError(f"--defect names valve(s) not in the pinned set: {', '.join(sorted(unknown))}")
        if not valves:
            raise VisionError("no valves left to capture")
        print(f"[capture] {len(valves)} valve(s) from {asset_source}: {', '.join(v['tag'] for v in valves)}",
              file=sys.stderr)

        def store(v: dict, defect: str, imgs: list[Image.Image], extra: dict) -> None:
            d = out_root / v["tag"]
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            for i, im in enumerate(imgs):
                im.save(d / f"f{i:02d}.jpg", quality=92)
            meta = {
                "site": a.site, "tag": v["tag"], "pin": v["pin"], "pinSource": v.get("pinSource"),
                "defect": defect, "synthetic": defect != "none",
                "capturedAt": now_iso(), "frames": len(imgs), "size": list(imgs[0].size),
                "requestedBy": actor, "assetSource": asset_source, **extra,
                "asset": {k: v.get(k) for k in ("id", "name", "kind", "system", "subsystem", "description",
                                                "status", "spec")},
            }
            write_json(d / "meta.json", meta)
            written.append(meta)
            print(f"[capture] {v['tag']}: {len(imgs)} frames {imgs[0].size} in {extra.get('renderSeconds')}s "
                  f"-> {rel(d)}", file=sys.stderr)

        used = a.source
        if a.source == "eye" and not eye_all(a.site, valves, defects, a.backend, a.frames, a.timeout, actor, store):
            used = "capture"
        if used == "capture":
            check_route(a.base, a.site, valves[0]["tag"])
            asyncio.run(capture_route_all(a.site, valves, defects, a.base, a.chrome, a.frames, a.timeout,
                                          a.renderer, a.headful, store))
        tags = [m["tag"] for m in written]
        if a.only:  # partial re-capture: keep the other valves from the previous manifest
            prev = out_root / "manifest.json"
            if prev.is_file():
                tags = sorted(set(tags) | set(json.loads(prev.read_text()).get("tags") or []))
        metas = {t: read_meta(out_root / t) for t in tags}
        write_json(out_root / "manifest.json", {
            "site": a.site, "capturedAt": now_iso(), "tags": tags,
            "defects": {t: m.get("defect") for t, m in metas.items() if m.get("defect", "none") != "none"},
            "frameSource": sorted({m.get("source", "capture-route") for m in metas.values()}),
            "requestedSource": a.source, "requestedBy": actor, "assetSource": asset_source,
            "base": a.base if used == "capture" else None, "backend": a.backend,
        })
    except (VisionError, CDPError) as exc:
        fail(exc)
    print(f"captured {len(written)} valve clip(s) via {used} -> {rel(out_root)}")


if __name__ == "__main__":
    main()
