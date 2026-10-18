"""Synthetic data families (contract 3 §9) loaded from `backend/seed/synthetic/<family>.json`.

The repository ships a deterministic hand-written seed with the same shapes that `scripts/synth/generate.py`
produces with Claude. Every record is labelled `synthetic: true` and `generator: "hand-seed"` (or
`"claude-opus-5-5"` for generated files). A record that is not labelled synthetic is rejected at load time, so
nothing synthetic can be mistaken for an observed record.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .env import env

SYNTH_DIR = Path(__file__).resolve().parents[1] / "seed" / "synthetic"
FAMILIES = ("crews", "obligations", "documents", "sensor_history", "scenarios", "conversations", "maintenance", "armature_traces")


def synth_dir() -> Path:
    override = env("STEWARD_SYNTHETIC_DIR", "")
    return Path(override) if override else SYNTH_DIR


@lru_cache(maxsize=32)
def _load(directory: str, family: str) -> tuple:
    path = Path(directory) / f"{family}.json"
    if not path.exists():
        return ()
    payload = json.loads(path.read_text())
    generator = payload.get("generator") or "hand-seed"
    records = []
    for record in payload.get("records", []):
        if record.get("synthetic") is False:
            raise ValueError(f"{path.name}: record {record.get('id')} is not labelled synthetic")
        records.append({**record, "synthetic": True, "generator": record.get("generator") or generator})
    return tuple(records)


def load_family(family: str) -> list[dict]:
    if family not in FAMILIES:
        raise KeyError(f"Unknown synthetic family {family}")
    return [json.loads(json.dumps(record)) for record in _load(str(synth_dir()), family)]


def by_id(family: str) -> dict[str, dict]:
    return {record["id"]: record for record in load_family(family)}


def clear_cache() -> None:
    _load.cache_clear()
