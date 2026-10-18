#!/usr/bin/env python3
"""Embed each valve's 16-frame clip with V-JEPA 2 and score it against its peers.

    vision/.venv/bin/python vision/jepa.py <site> [--frames-root DIR] [--reference DIR] [--k 3.0]

Reads vision/frames/<site>/<tag>/f00.jpg..f15.jpg (+ meta.json from capture.py), writes
vision/results/<site>.json. See scoring.py for the score and threshold definitions.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

import scoring
from common import (FRAMES_DIR, HONESTY_NOTE, REFERENCE_DIR, RESULTS_DIR, VisionError, clip_dirs, engineer_for,
                    fail, frame_paths, load_clip, now_iso, read_meta, rel, write_json)
from embedders import MODEL_ID, MODEL_REVISION, make_embedder


def site_clips(frames_root: Path) -> list[Path]:
    """Clip dirs for the site; restricted to the latest capture manifest when one exists."""
    dirs = clip_dirs(frames_root)
    manifest = frames_root / "manifest.json"
    if manifest.is_file():
        try:
            tags = set(json.loads(manifest.read_text()).get("tags") or [])
        except json.JSONDecodeError:
            tags = set()
        if tags:
            dirs = [d for d in dirs if d.name in tags]
    return dirs


def reference_clips(ref_root: Path) -> dict[str, list[Path]]:
    """vision/reference/<label>/<clip>/f00..f15.jpg -> {label: [clip dirs]}."""
    out: dict[str, list[Path]] = {}
    if ref_root.is_dir():
        for label_dir in sorted(p for p in ref_root.iterdir() if p.is_dir()):
            clips = clip_dirs(label_dir)
            if clips:
                out[label_dir.name] = clips
    return out


def frame_source(meta: dict, clip_dir: Path) -> tuple[str, tuple[int, int]]:
    from PIL import Image

    size = meta.get("size")
    if not size:
        with Image.open(frame_paths(clip_dir)[0]) as im:
            size = list(im.size)
    return meta.get("source") or "capture-route", (int(size[0]), int(size[1]))


def run(site: str, frames_root: Path, out_path: Path, ref_root: Path, embedder_name: str = "vjepa2",
        device: str = "auto", region: str = "centre", k: float = scoring.K_DEFAULT,
        k_uncertain: float = scoring.K_UNCERTAIN_DEFAULT, model_id: str = MODEL_ID,
        revision: str | None = MODEL_REVISION, quiet: bool = False, inspected_by: str | None = None,
        allow_mixed: bool = False, mode: str = "auto") -> dict:
    log = (lambda *a: None) if quiet else (lambda *a: print("[jepa]", *a, file=sys.stderr))
    inspected_by = inspected_by or engineer_for(site)
    clips = site_clips(frames_root)
    if not clips:
        raise VisionError(f"no complete 16-frame clips under {frames_root}; run capture.py {site} first.")
    sources = {d.name: frame_source(read_meta(d), d) for d in clips}
    kinds = sorted({f"{src} {w}x{h}" for src, (w, h) in sources.values()})
    if len(kinds) > 1 and not allow_mixed:
        raise VisionError(f"clips at {site} come from different frame sources/sizes ({', '.join(kinds)}); a peer "
                          "comparison across them is meaningless. Re-capture every valve with one --source "
                          "(or pass --allow-mixed).")
    if (ref_root / site).is_dir():  # per-site references (vision/reference/<site>/<label>/<clip>/) win
        ref_root = ref_root / site
    refs = reference_clips(ref_root)
    log(f"{len(clips)} clip(s) at {rel(frames_root)}; reference labels at {rel(ref_root)}: "
        + (", ".join(f"{lb}={len(v)}" for lb, v in refs.items()) or "none"))
    # Baseline mode: an accepted-good clip of the same valve (dir named by its tag) under a normal label.
    baseline_dirs = {d.name: d for lb, dirs in refs.items() if lb.lower() in scoring.NORMAL_LABELS for d in dirs}
    missing = [d.name for d in clips if d.name not in baseline_dirs]
    if mode == "baseline" and missing:
        raise VisionError(f"--mode baseline needs a baseline clip for every valve; missing: {', '.join(missing)} "
                          f"(capture them with: capture.py {site} --out-root {rel(ref_root)}/fixed)")
    use_baseline = mode != "peer" and not missing and bool(baseline_dirs)
    if use_baseline:
        mismatched = [t for t in sources if frame_source(read_meta(baseline_dirs[t]), baseline_dirs[t]) != sources[t]]
        if mismatched:
            raise VisionError(f"baseline clips differ in frame source/size from the inspection clips: "
                              f"{', '.join(mismatched)}; re-capture the baselines with the same --source")
    elif mode == "auto" and baseline_dirs and missing:
        log(f"baselines exist for {len(baseline_dirs)} valve(s) but not for {', '.join(missing)}; using peer mode")
    log(f"mode: {'baseline (each valve vs its own accepted-good capture)' if use_baseline else 'peer (each valve vs the other valves)'}")

    emb_model = make_embedder(embedder_name, device=device, model_id=model_id, revision=revision)
    log(f"model {emb_model.model_id} on {emb_model.device} (load {emb_model.load_seconds:.1f}s)")

    def embed_dir(d: Path):
        clip = load_clip(d)
        t = time.perf_counter()
        pooled, tokens = emb_model.embed(clip)
        return pooled, tokens, time.perf_counter() - t

    pooled, maps, per_clip = [], [], []
    for d in clips:
        p, g, dt = embed_dir(d)
        pooled.append(p)
        maps.append(g)
        per_clip.append({"assetTag": d.name, "seconds": round(dt, 3)})
        log(f"  {d.name}: {dt:.2f}s")
    ref_cache: dict[Path, np.ndarray] = {}

    def ref_map(d: Path) -> np.ndarray:
        if d not in ref_cache:
            ref_cache[d] = embed_dir(d)[1]
        return ref_cache[d]

    ref_maps = {lb: np.stack([ref_map(d) for d in dirs]) for lb, dirs in refs.items()}
    baselines = np.stack([ref_map(baseline_dirs[d.name]) for d in clips]) if use_baseline else None

    results, thr = scoring.score_site(np.stack(maps), ref_maps, k=k, k_uncertain=k_uncertain, region=region,
                                      baselines=baselines)
    pooled = np.stack(pooled)
    pooled_loo = [float(1 - np.dot(pooled[i], scoring.l2n(np.median(np.delete(pooled, i, 0), 0))))
                  if len(pooled) > 1 else 0.0 for i in range(len(pooled))]

    valves, any_synthetic = [], False
    for i, (d, r) in enumerate(zip(clips, results)):
        meta = read_meta(d)
        defect = meta.get("defect") or "none"
        synthetic = bool(meta.get("synthetic", defect != "none"))
        any_synthetic |= synthetic
        valves.append({
            "assetTag": d.name,
            "status": r.status,
            "score": round(r.score, 6),
            "threshold": round(thr["value"], 6),
            "uncertainAbove": round(thr["uncertainAbove"], 6),
            "model": emb_model.model_id,
            "frames": [rel(p) for p in frame_paths(d)],
            "baseline": rel(baseline_dirs[d.name]) if use_baseline else None,
            "components": {"looPatchDistance": round(r.loo, 6), "referenceDistance": round(r.ref_term, 6),
                           "pooledLooDistance": round(pooled_loo[i], 6)},
            "anomalyPeak": scoring.peak_cell(r.grid),
            "anomalyGrid": np.round(r.grid, 4).tolist(),
            "reference": r.reference,
            "reason": r.reason,
            "defect": defect if defect != "none" else None,  # null, not "none": ingest treats any defect as synthetic
            "synthetic": synthetic,
            "pin": meta.get("pin"),
            "pinSource": meta.get("pinSource"),
            "capturedAt": meta.get("capturedAt"),
            "frameSource": sources[d.name][0],
            "inspectedBy": inspected_by,
            "explanation": None,
        })

    secs = [p["seconds"] for p in per_clip]
    warm = secs[1:] if len(secs) > 1 else secs
    out = {
        "siteId": site,
        "generatedAt": now_iso(),
        "kind": "valve-inspection",
        "inspectedBy": inspected_by,
        "frameSource": kinds[0] if len(kinds) == 1 else kinds,
        "model": {
            "id": emb_model.model_id,
            "revision": emb_model.revision,
            "library": getattr(emb_model, "library", None),
            "device": emb_model.device,
            "embedding": emb_model.pooling,
            "framesPerClip": 16,
        },
        "threshold": {k_: (round(v, 6) if isinstance(v, float) else v) for k_, v in thr.items()},
        "mode": thr["mode"],
        "scoreDefinition": (
            ("baseline mode: position-aligned cosine distance between the clip's V-JEPA 2 token map and the token "
             "map of the same valve's accepted-good baseline clip (centre-weighted mean over 8x16x16 tokens), i.e. "
             "how much the valve changed since it was last known good. ")
            if use_baseline else
            ("peer mode: position-aligned cosine distance between the clip's V-JEPA 2 token map and the "
             "leave-one-out median token map of the site's other valves (centre-weighted mean over 8x16x16 "
             "tokens), plus mean distance to the k nearest 'normal' reference clips when the reference set has a "
             "normal label. ")) + "anomalyGrid is that distance per 16x16 patch (row 0 = top of the 256 px centre "
                                 "crop), averaged over time.",
        "reference": {"used": bool(refs), "root": rel(ref_root), "labels": {lb: len(v) for lb, v in refs.items()}},
        "honesty": HONESTY_NOTE,
        "synthetic": any_synthetic,
        "timings": {
            "device": emb_model.device,
            "modelLoadSeconds": round(emb_model.load_seconds, 2),
            "perClip": per_clip,
            "firstClipSeconds": secs[0] if secs else None,
            "meanWarmClipSeconds": round(float(np.mean(warm)), 3) if warm else None,
        },
        "counts": {s: sum(v["status"] == s for v in valves) for s in ("fixed", "not_fixed", "uncertain")},
        "pinWarning": (None if not any(v.get("pinSource") == "estimated" for v in valves) else
                       "Some pins are estimated, not placed on the scan: their orbits may not show the valve, so "
                       "their scores compare whatever lies at the estimated point. Place pins in the dashboard "
                       "and re-run."),
        "valves": valves,
    }
    if embedder_name != "vjepa2":
        out["honesty"] = "TEST RUN with a pixel-statistics baseline, not V-JEPA 2. " + HONESTY_NOTE
    write_json(out_path, out)
    np.savez(out_path.with_suffix(".embeddings.npz"), tags=np.array([d.name for d in clips]), pooled=pooled)
    log(f"wrote {rel(out_path)}: {out['counts']} (threshold {thr['value']:.4f}, median {thr['median']:.4f}; "
        f"inspected by {inspected_by})")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site")
    ap.add_argument("--frames-root", type=Path, help="default vision/frames/<site>")
    ap.add_argument("--out", type=Path, help="default vision/results/<site>.json")
    ap.add_argument("--reference", type=Path, default=REFERENCE_DIR,
                    help="labelled reference root; <root>/<site>/ is used when it exists")
    ap.add_argument("--mode", choices=["auto", "peer", "baseline"], default="auto",
                    help="auto: baseline mode when every valve has a baseline under <reference>/<site>/fixed/<tag>/, "
                         "else peer mode")
    ap.add_argument("--k", type=float, default=scoring.K_DEFAULT, help="MADs above the median for not_fixed")
    ap.add_argument("--k-uncertain", type=float, default=scoring.K_UNCERTAIN_DEFAULT,
                    help="MADs above the median for uncertain")
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cpu"])
    ap.add_argument("--region", default="centre", choices=["centre", "full"],
                    help="centre: gaussian weight around the pin (default); full: every patch equally")
    ap.add_argument("--embedder", default="vjepa2", choices=["vjepa2", "pixel-stats"],
                    help="pixel-stats is a model-free test baseline")
    ap.add_argument("--model-id", default=MODEL_ID)
    ap.add_argument("--revision", default=MODEL_REVISION)
    ap.add_argument("--inspected-by", help="agent id stamped on the results (default: the site engineer)")
    ap.add_argument("--allow-mixed", action="store_true", help="score clips from different frame sources anyway")
    a = ap.parse_args(argv)
    frames_root = a.frames_root or FRAMES_DIR / a.site
    out = a.out or RESULTS_DIR / f"{a.site}.json"
    try:
        res = run(a.site, frames_root, out, a.reference, a.embedder, a.device, a.region, a.k, a.k_uncertain,
                  a.model_id, a.revision, inspected_by=a.inspected_by, allow_mixed=a.allow_mixed, mode=a.mode)
    except VisionError as exc:
        fail(exc)
    for v in res["valves"]:
        print(f"{v['assetTag']:>10}  {v['status']:<10} score={v['score']:.4f}  peak={v['anomalyPeak']['where']:<14}"
              f" defect={v['defect'] or 'none'}")


if __name__ == "__main__":
    main()
