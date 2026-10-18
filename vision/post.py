#!/usr/bin/env python3
"""POST vision/results/<site>.json to the backend's ingest route.

    vision/.venv/bin/python vision/post.py <site> [--backend http://127.0.0.1:8001]

POST /api/properties/<site>/inspections/vision (BACKEND stream, REALITY-CONTRACT-3 §3.4) turns
the results file into finding records and issues. Sent with X-Steward-Actor: the results'
inspectedBy (the site engineer, REALITY-CONTRACT-4 §1). Exit 3 when the route does not exist yet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import DEFAULT_BACKEND, RESULTS_DIR, VisionError, engineer_for, fail, http_json, rel


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site")
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--results", type=Path)
    a = ap.parse_args(argv)
    path = a.results or RESULTS_DIR / f"{a.site}.json"
    url = f"{a.backend.rstrip('/')}/api/properties/{a.site}/inspections/vision"
    try:
        if not path.is_file():
            raise VisionError(f"{rel(path)} not found; run jepa.py {a.site} first.")
        body = json.loads(path.read_text())
        actor = body.get("inspectedBy") or engineer_for(a.site)  # contract 4: the site engineer runs inspections
        status, resp = http_json("POST", url, body, timeout=60, headers={"X-Steward-Actor": actor})
    except VisionError as exc:
        fail(exc)
    if status in (404, 405):
        print(f"[post] {url} -> HTTP {status}: the backend ingest route is not there yet "
              f"(BACKEND stream). Results stay in {rel(path)}.", file=sys.stderr)
        sys.exit(3)
    if status >= 300:
        print(f"[post] {url} -> HTTP {status}: {json.dumps(resp)[:500]}", file=sys.stderr)
        sys.exit(1)
    print(f"[post] {url} as {actor} -> HTTP {status}")
    print(json.dumps(resp, indent=2)[:2000])


if __name__ == "__main__":
    main()
