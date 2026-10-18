"""Contract 4 agent-id migration, once per database, idempotent, after a SQLite backup.

`atlas` → `director`; `warden:myer-plant` → `myer-engineer`; `warden:bristol-pumps` → `bristol-engineer`;
`counsel` → `<site>-compliance` by the record's site (cross-site or site-less records → `bristol-compliance`);
`runner` → `<site>-technician` by site (site-less → `myer-technician`). Only fields that hold agent ids are
rewritten (caller, target, from, to, agentId, participants, requester prefixes, ...); free text such as Change
summaries stays as it was written. Records keyed by agent id (`agent_activity`, `agent_config`) are re-keyed, memory
containers are recomputed, events and the telemetry table follow. Signed attestations never contain agent ids.
"""
from __future__ import annotations

import json
import re

from .agents import OLD_AGENT_IDS, display_name, migrate_agent_id
from .sites import SITE_BY_ID, _backup

AGENT_FIELDS = {"caller", "target", "from", "to", "agentId", "convenedBy", "sender", "recipient", "reviewer", "detectedBy", "issuedBy",
                "startedBy", "createdBy", "by", "updatedBy", "speaker", "owner", "decidedBy", "requestedBy"}
LIST_FIELDS = {"participants", "usedBy"}
KEYED_KINDS = {"agent_activity", "agent_config"}
_REQUESTER_RE = re.compile(r"^(atlas|runner|counsel|warden:(?:myer-plant|bristol-pumps))(/.*)?$")
_OLD_LIKE = ('%"atlas"%', '%"runner"%', '%"counsel"%', '%warden:myer-plant%', '%warden:bristol-pumps%', '%"runner/%', '%"atlas/%')


def _site(body: dict, inherited: str | None) -> str | None:
    for key in ("siteId", "propertyId", "_propertyId"):
        value = body.get(key)
        if isinstance(value, str) and value in SITE_BY_ID:
            return value
    steward = body.get("steward")
    if isinstance(steward, dict) and steward.get("siteId") in SITE_BY_ID:
        return steward["siteId"]
    return inherited


def _walk(value, site: str | None, field: str = ""):
    if isinstance(value, dict):
        local = _site(value, site)
        out = {}
        for key, item in value.items():
            out[key] = _walk(item, local, key)
        if out.get("agentId") != value.get("agentId") and "name" in out and isinstance(out.get("agentId"), str):
            out["name"] = display_name(out["agentId"])
        if out.get("issuedBy") != value.get("issuedBy") and "issuedByName" in out:
            out["issuedByName"] = display_name(out["issuedBy"])
        if "container" in out and isinstance(out.get("agentId"), str) and str(out["container"]).startswith("steward-"):
            out["container"] = f"steward-{out['agentId']}"
        return out
    if isinstance(value, list):
        if field in LIST_FIELDS:
            return [migrate_agent_id(item, site) if isinstance(item, str) else _walk(item, site) for item in value]
        return [_walk(item, site, field) for item in value]
    if isinstance(value, str):
        if field in AGENT_FIELDS and value in OLD_AGENT_IDS:
            return migrate_agent_id(value, site)
        if field == "requester":
            match = _REQUESTER_RE.match(value)
            if match:
                return migrate_agent_id(match.group(1), site) + (match.group(2) or "")
    return value


def migrate_agent_ids(store) -> dict:
    if store.meta("steward_agent_ids_version") == "4":
        return {}
    with store.connect() as db:
        clause = " OR ".join("body LIKE ?" for _ in _OLD_LIKE)
        records = db.execute(f"SELECT COUNT(*) FROM records WHERE kind NOT LIKE 'archived:%' AND ({clause})", _OLD_LIKE).fetchone()[0]
        events = db.execute(f"SELECT COUNT(*) FROM events WHERE {clause}", _OLD_LIKE).fetchone()[0]
        has_telemetry = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry'").fetchone() is not None
        telemetry = db.execute("SELECT COUNT(*) FROM telemetry WHERE agent_id IN (?,?,?,?,?)", tuple(OLD_AGENT_IDS)).fetchone()[0] if has_telemetry else 0
    if not records and not events and not telemetry:
        store.meta("steward_agent_ids_version", "4")
        return {}
    backup = _backup(store, "pre-agent-ids")
    counts = dict(records=0, rekeyed=0, events=0, telemetry=0, backup=backup.name)
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT rowid, kind, id, property_id, body FROM records WHERE kind NOT LIKE 'archived:%'").fetchall():
            original = json.loads(row["body"])
            site = row["property_id"] if row["property_id"] in SITE_BY_ID else None
            body = _walk(original, site)
            new_id = row["id"]
            if row["kind"] in KEYED_KINDS and row["id"] in OLD_AGENT_IDS:
                new_id = migrate_agent_id(row["id"], _site(original, site))
                body["id"] = new_id
                if row["kind"] == "agent_config":
                    body["agentId"] = new_id
                exists = db.execute("SELECT 1 FROM records WHERE kind=? AND id=? AND property_id=?", (row["kind"], new_id, row["property_id"])).fetchone()
                if exists:
                    db.execute("DELETE FROM records WHERE rowid=?", (row["rowid"],))  # the new-id record already wins
                    counts["rekeyed"] += 1
                    continue
                counts["rekeyed"] += 1
            if body != original or new_id != row["id"]:
                db.execute("UPDATE records SET id=?, body=? WHERE rowid=?", (new_id, json.dumps(body), row["rowid"]))
                counts["records"] += 1
        for row in db.execute("SELECT id, property_id, body FROM events").fetchall():
            original = json.loads(row["body"])
            site = row["property_id"] if row["property_id"] in SITE_BY_ID else None
            body = _walk(original, site)
            if body != original:
                db.execute("UPDATE events SET body=? WHERE id=?", (json.dumps(body), row["id"]))
                counts["events"] += 1
        if has_telemetry:
            for row in db.execute("SELECT seq, agent_id, site_id FROM telemetry WHERE agent_id IN (?,?,?,?,?)", tuple(OLD_AGENT_IDS)).fetchall():
                db.execute("UPDATE telemetry SET agent_id=? WHERE seq=?", (migrate_agent_id(row["agent_id"], row["site_id"]), row["seq"]))
                counts["telemetry"] += 1
        db.execute("INSERT INTO meta(key,value) VALUES ('steward_agent_ids_version','4') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    return counts
