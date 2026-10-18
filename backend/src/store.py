"""Small durable store. Each mutation is a transaction; JSON preserves the API contract."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .branding import prepare_database, migrate_records
from .sites import migrate_site_ids, retire_sites
from .agent_migration import migrate_agent_ids


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


class Store:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "files").mkdir(exist_ok=True)
        self.path = prepare_database(self.directory)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, property_id TEXT NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(kind,id,property_id));
                CREATE INDEX IF NOT EXISTS records_property ON records(kind, property_id);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, property_id TEXT NOT NULL,
                    body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_property ON events(property_id,id);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            """)
        migrate_records(self)
        migrate_site_ids(self)
        retire_sites(self)
        migrate_agent_ids(self)

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def put(self, kind: str, body: dict, property_id: str = "") -> dict:
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO records(kind,id,property_id,body) VALUES (?,?,?,?) "
                       "ON CONFLICT(kind,id,property_id) DO UPDATE SET body=excluded.body",
                       (kind, body["id"], property_id, json.dumps(body)))
        return body

    def get(self, kind: str, identifier: str, property_id: str | None = None) -> dict | None:
        with self.connect() as db:
            if property_id is None:
                row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, identifier)).fetchone()
            else:
                row = db.execute("SELECT body FROM records WHERE kind=? AND id=? AND property_id=?",
                                 (kind, identifier, property_id)).fetchone()
        return json.loads(row["body"]) if row else None

    def all(self, kind: str, property_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if property_id is None:
                rows = db.execute("SELECT body FROM records WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
            else:
                rows = db.execute("SELECT body FROM records WHERE kind=? AND property_id=? ORDER BY rowid",
                                  (kind, property_id)).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def event(self, property_id: str, agent_id: str, event_type: str, title: str,
              detail: str, component_id: str | None = None) -> dict:
        body = dict(propertyId=property_id, agentId=agent_id, type=event_type, title=title,
                    detail=detail, componentId=component_id, createdAt=now())
        with self.lock, self.connect() as db:
            cursor = db.execute("INSERT INTO events(property_id,body) VALUES (?,?)", (property_id, json.dumps(body)))
            body["id"] = cursor.lastrowid
        return body

    def events(self, property_id: str, after: int = 0, limit: int = 300) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,body FROM events WHERE property_id=? AND id>? ORDER BY id LIMIT ?",
                              (property_id, after, limit)).fetchall()
        return [{**json.loads(row["body"]), "id": row["id"]} for row in rows]

    def meta(self, key: str, value: str | None = None) -> str | None:
        with self.lock, self.connect() as db:
            if value is not None:
                db.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
                return value
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def claim_job(self, identifier: str) -> dict | None:
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body,property_id FROM records WHERE kind='job' AND id=?", (identifier,)).fetchone()
            if not row:
                return None
            job = json.loads(row["body"])
            if job["status"] != "queued":
                return None
            job.update(status="running", updatedAt=now())
            db.execute("UPDATE records SET body=? WHERE kind='job' AND id=?", (json.dumps(job), identifier))
            return job

    def mark_once(self, key: str, value: str = "1") -> bool:
        """Atomically deduplicate externally delivered events."""
        with self.lock, self.connect() as db:
            result = db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES (?,?)", (key, value))
            return result.rowcount == 1

    def put_with_event_once(self, dedupe_key: str, kind: str, body: dict, property_id: str,
                            agent_id: str, event_type: str, title: str, detail: str, component_id=None) -> bool:
        """Receipt deduplication, domain update and event are committed together."""
        event = dict(propertyId=property_id, agentId=agent_id, type=event_type, title=title,
                     detail=detail, componentId=component_id, createdAt=now())
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES (?,?)", (dedupe_key, now()))
            if inserted.rowcount != 1:
                return False
            db.execute("INSERT INTO records(kind,id,property_id,body) VALUES (?,?,?,?) "
                       "ON CONFLICT(kind,id,property_id) DO UPDATE SET body=excluded.body",
                       (kind, body["id"], property_id, json.dumps(body)))
            db.execute("INSERT INTO events(property_id,body) VALUES (?,?)", (property_id, json.dumps(event)))
            return True
