#!/usr/bin/env python
"""Backfill every mirrored record from SQLite into Supabase, within the budget caps. Safe to re-run.

Usage: backend/.venv/bin/python backend/scripts/supabase_sync.py [--data-dir backend/data] [--batch 200] [--no-storage] [--dry-run]

- Rows go through the same author-aware path as the live mirror (src/mirror.py): an agent's rows with that agent's own
  access token (RLS decides), system rows (machine readings, seeds, the change feed) with the secret key. Attestations go
  first, in creation order, so the ledger chain follows history and every fact can cite its attestation.
- The database cap is checked before every table (pg_database_size through public.steward_db_size()).
- Eye frames, their 320 px thumbnails and evidence files already stored locally are uploaded to the private buckets
  (eye-frames, evidence), each asking the budget guard first (per-object and storage caps).
Requires SUPABASE_URL and SUPABASE_SERVICE_KEY (root .env); agent passwords and the publishable key for agent rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env", override=True)

from src.env import env, sanitize_environment  # noqa: E402

sanitize_environment()

from src.mirror import Mirror, TABLES, build_row, is_machine  # noqa: E402
from src.store import Store  # noqa: E402
from src.supa_authority import author_for  # noqa: E402
from src.supa_budget import MB  # noqa: E402
from src.supa_storage import ObjectStore  # noqa: E402

ORDER = ["attestation", "fact"] + [kind for kind in TABLES if kind not in ("attestation", "fact")]


def telemetry_records(store: Store) -> list[dict]:
    with store.connect() as db:
        if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry'").fetchone():
            return []
        rows = [dict(row) for row in db.execute("SELECT * FROM telemetry ORDER BY seq").fetchall()]
    out = []
    for r in rows:
        out.append(dict(id=r["id"], at=r["at"], agentId=r["agent_id"], siteId=r["site_id"], kind=r["kind"], tool=r["tool"], tokens=r["tokens"],
                        ms=r["ms"], ok=bool(r["ok"]), missionId=r["mission_id"], scenarioId=r["scenario_id"], runId=r["run_id"], source=r["source"],
                        synthetic=bool(r["synthetic"]), detail=r["detail"]))
    return out


def records(store: Store, kind: str) -> list[tuple[dict, str]]:
    if kind == "telemetry":
        return [(record, record.get("siteId") or "") for record in telemetry_records(store)]
    with store.connect() as db:
        rows = db.execute("SELECT body, property_id FROM records WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
    return [(json.loads(row["body"]), row["property_id"]) for row in rows]


def poll_db(mirror: Mirror) -> int | None:
    try:
        size = mirror.supa.rpc("steward_db_size")
        mirror.budget.set_db_bytes(int(size))
        return int(size)
    except Exception as error:
        print(f"  (database size unavailable: {type(error).__name__})")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=env("STEWARD_DATA_DIR", str(ROOT / "data")))
    parser.add_argument("--batch", type=int, default=200)
    parser.add_argument("--no-storage", action="store_true", help="rows only; skip eye frames and evidence files")
    parser.add_argument("--dry-run", action="store_true", help="count what would be sent; send nothing")
    parser.add_argument("--storage-only", action="store_true", help="skip rows; upload eye frames and evidence only")
    args = parser.parse_args()
    store = Store(Path(args.data_dir))
    mirror = Mirror(store)
    if not mirror.configured:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY are not set; nothing synced.")
        return 2
    agent_auth = mirror.tokens.enabled
    print(f"plan {mirror.budget.plan}; agent rows written with agent tokens: {agent_auth}; database cap {mirror.budget.cap('db_mb')} MB")
    if not args.dry_run:
        size = poll_db(mirror)
        print(f"database before: {size / MB:.1f} MB" if size else "database size unknown")
    totals = Counter()
    for kind in ([] if args.storage_only else ORDER):
        table = TABLES[kind]
        if not args.dry_run:
            state = mirror.budget.db_state()
            if state == "full":
                print(f"{table}: skipped, the database is at its cap")
                continue
        groups: OrderedDict[str | None, list[dict]] = OrderedDict()
        shed = 0
        for record, property_id in records(store, kind):
            row = build_row(kind, record, property_id)
            if not args.dry_run and mirror.budget.db_state() == "shed" and is_machine(table, record):
                shed += 1
                continue
            author = author_for(table, row, record, None) if agent_auth else None
            groups.setdefault(author, []).append(row)
        sent = Counter()
        for author, rows in groups.items():
            for start in range(0, len(rows), args.batch):
                chunk = rows[start:start + args.batch]
                if args.dry_run:
                    sent["written"] += len(chunk)
                    continue
                result = mirror.write_now(table, chunk, author)
                for key, value in result.items():
                    sent[key] += value
        writers = ", ".join(f"{author or 'service_role'}={len(rows)}" for author, rows in groups.items()) or "none"
        print(f"{table}: {sum(len(r) for r in groups.values())} row(s); written {sent['written']}, refused {sent['refused']}, "
              f"failed {sent['failed']}, shed {shed}; writers {writers}")
        totals.update(sent)
        if not args.dry_run and table in ("attestations", "facts", "changes", "telemetry"):
            poll_db(mirror)
    if mirror.last_refusal:
        print("last refusal:", json.dumps(mirror.last_refusal)[:300])
    uploads = dict(frames=0, evidence=0)
    if not args.no_storage and not args.dry_run:
        objects = ObjectStore(mirror.supa, mirror.budget, store)
        frames_dir = store.directory / "eye" / "frames"
        for frame in store.all("eye_frame"):
            if objects.upload_frame(frame, frames_dir):
                uploads["frames"] += 1
        files_dir = store.directory / "files"
        for attestation in store.all("attestation"):
            if attestation.get("evidenceHashes"):
                uploads["evidence"] += objects.upload_evidence(attestation, files_dir)
        for evidence in store.all("evidence"):
            if objects.upload_evidence_record(evidence, files_dir):
                uploads["evidence"] += 1
        try:
            usage = mirror.supa.rpc("steward_storage_usage")
            mirror.budget.set_storage_bytes(sum(int((b or {}).get("bytes") or 0) for b in usage.values()))
            print("storage:", json.dumps(usage))
        except Exception as error:
            print(f"storage usage unavailable: {type(error).__name__}")
        print(f"uploaded {uploads['frames']} eye frame(s) (+ thumbnails) and {uploads['evidence']} evidence file(s); "
              f"storage {mirror.budget.storage_bytes() / MB:.2f} MB of {mirror.budget.cap('storage_mb')} MB")
    if not args.dry_run:
        size = poll_db(mirror)
        print(f"database after: {size / MB:.1f} MB of a {mirror.budget.cap('db_mb')} MB cap" if size else "")
    mirror.close()
    print(f"Done: written {totals['written']}, refused {totals['refused']}, failed {totals['failed']}.")
    return 0 if not totals["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
