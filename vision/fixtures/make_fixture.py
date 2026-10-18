#!/usr/bin/env python3
"""Generate the 6-clip synthetic fixture used to test scoring without a browser or backend.

    vision/.venv/bin/python vision/fixtures/make_fixture.py [--out vision/fixtures/clips]

FX-01..FX-05: solid-colour frames (similar steel-grey/blue tones, a slow brightness drift) plus
low-amplitude gaussian noise, i.e. five "peer valves" that look alike.
FX-06: the deliberate outlier, full-range uniform RGB noise re-drawn every frame.
Deterministic (seeded). 16 frames, 256x256 JPEG, same layout as capture.py output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SIZE = 256
FRAMES = 16
OUTLIER = "FX-06"
BASE_COLOURS = {  # RGB, close to one another on purpose
    "FX-01": (118, 124, 132),
    "FX-02": (112, 120, 130),
    "FX-03": (122, 126, 128),
    "FX-04": (115, 122, 136),
    "FX-05": (120, 121, 126),
}


def normal_clip(rgb, rng) -> np.ndarray:
    frames = []
    for t in range(FRAMES):
        drift = 6.0 * np.sin(2 * np.pi * t / FRAMES)
        f = np.empty((SIZE, SIZE, 3), dtype=np.float64)
        f[:] = np.array(rgb, dtype=np.float64) + drift
        f += rng.normal(0.0, 4.0, size=f.shape)
        frames.append(np.clip(f, 0, 255).astype(np.uint8))
    return np.stack(frames)


def outlier_clip(rng) -> np.ndarray:
    return rng.integers(0, 256, size=(FRAMES, SIZE, SIZE, 3), dtype=np.uint8)


def write_clip(out_dir: Path, tag: str, clip: np.ndarray, kind: str) -> None:
    d = out_dir / tag
    d.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(clip):
        Image.fromarray(f).save(d / f"f{i:02d}.jpg", quality=92)
    (d / "meta.json").write_text(json.dumps({
        "site": "fixture", "tag": tag, "pin": None, "defect": "none", "source": "fixture",
        "synthetic": True, "fixture": kind, "expectedOutlier": tag == OUTLIER,
        "capturedAt": None, "note": "numpy-generated test clip, not a render of any site",
    }, indent=2) + "\n")


def make(out_dir: Path) -> list[str]:
    rng = np.random.default_rng(20261017)
    for tag, rgb in BASE_COLOURS.items():
        write_clip(out_dir, tag, normal_clip(rgb, rng), "solid-colour + low noise")
    write_clip(out_dir, OUTLIER, outlier_clip(rng), "full-range uniform noise (outlier)")
    tags = [*BASE_COLOURS, OUTLIER]
    (out_dir / "manifest.json").write_text(json.dumps({"site": "fixture", "tags": tags}, indent=2) + "\n")
    return tags


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "clips")
    a = ap.parse_args()
    print("wrote", make(a.out), "to", a.out)
