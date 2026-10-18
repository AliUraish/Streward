#!/usr/bin/env python
"""Backfill every mirrored record (reality layer and contract-3 tables) from SQLite into Supabase through PostgREST.

Usage: backend/.venv/bin/python backend/scripts/supabase_sync.py [--data-dir backend/data]
Requires SUPABASE_URL and SUPABASE_SERVICE_KEY (loaded from backend/.env when present).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

from src.env import env  # noqa: E402
from src.mirror import COLUMNS, Mirror, TABLES, row_for  # noqa: E402
from src.store import Store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=env("STEWARD_DATA_DIR", str(ROOT / "data")))
    parser.add_argument("--batch", type=int, default=200)
    args = parser.parse_args()
    store = Store(Path(args.data_dir))
    mirror = Mirror(store)
    if not mirror.configured:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY are not set; nothing synced.")
        return 2
    total = 0
    for kind, table in TABLES.items():
        rows = []
        if kind == "telemetry":
            with store.connect() as db:
                exists = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry'").fetchone()
                records = [] if not exists else [dict(row) for row in db.execute("SELECT * FROM telemetry ORDER BY seq").fetchall()]
            for record in records:
                rows.append({column: (bool(record[column]) if column in ("ok", "synthetic") else record[column]) for column in COLUMNS[table]})
        for record in ([] if kind == "telemetry" else store.all(kind)):
            row = row_for(kind, record)
            property_id = row.get("property_id") or record.get("_propertyId") or ""
            if property_id and "property_id" in COLUMNS[table]:
                row["property_id"] = property_id
            rows.append(row)
        for start in range(0, len(rows), args.batch):
            chunk = rows[start:start + args.batch]
            mirror.upsert(table, chunk)
            total += len(chunk)
        print(f"{table}: {len(rows)} row(s) upserted")
    mirror.close()
    print(f"Done: {total} row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
