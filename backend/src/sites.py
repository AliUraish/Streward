"""Site registry (contracts 3 and 5): IDs, display names, environments, scan pins and the in-place migrations.

Site == property: the API keeps the `/api/properties/{id}` prefix and `propertyId` field names. Three sites, all
third-party Gaussian-splat captures hosted on SuperSplat and loaded at runtime from the CloudFront origin (never
copied or rehosted): `myer-plant` (the demo site, MY), `bristol-pumps` (BR) and, from contract 5, `tomioka-mill` (TM),
the Tomioka Silk Mill, whose capture is a streamed level-of-detail octree (`lod-meta.json`, `environment.format: lod`)
rather than a single SOG `meta.json`. `harbor-works` and its Three.js fixture twin were retired; `retire_sites`
archives its records once, after a backup. A site added to an existing database is seeded by `seed.add_new_sites`
(once, after a backup `pre-third-site-<stamp>`).

Databases created before the first rename (`cedar` / `harbor` / `juniper`) are still migrated in place on startup,
once, idempotently (`migrate_site_ids`), before the retirement runs. Signed attestations whose body changed are
re-signed with the local key, because the backend is the signer and a stale signature would read as tampering.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEMO_SITE = "myer-plant"
SITE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,30}$")
OLD_TO_NEW = {"cedar": "myer-plant", "harbor": "harbor-works", "juniper": "bristol-pumps"}
OLD_PREFIX_TO_NEW = {"CH": "MY", "HW": "HW", "JR": "BR"}
# Contract 3: harbor-works and the hand-built Three.js twin left the product. Its records are archived in place
# (kind `archived:<kind>`, property `archived:harbor-works`) after a backup; see retire_sites().
RETIRED_SITES = {"harbor-works": "HW"}
SPLAT_CAPTURE_NOTE = "Scene rendered from a third-party capture hosted on SuperSplat; shown here as the site environment."
SOG_ORIGIN = "https://d28zzqy0iyovbz.cloudfront.net"
TOMIOKA_LOD_META = f"{SOG_ORIGIN}/849bce2a/v1/lod-meta.json"
# Scan facts from the SuperSplat scene pages and their meta.json (gaussian counts are meta.json `count`).
SITES: list[dict] = [
    dict(id="myer-plant", prefix="MY", name="Myer Plant Room", site="Myer Plant Room, basement plant room (demonstration site)",
         operator="Myer facilities team (demonstration)", status="operational", jurisdiction="VIC-AU", area="plant room",
         siteKind="modern building plant room",
         environment=dict(kind="splat", format="sog", scanFormat="sog", splatId="66b655d3", sogMetaUrl=f"{SOG_ORIGIN}/66b655d3/v1/meta.json",
                          sogUrl=f"{SOG_ORIGIN}/66b655d3/v1/meta.json", contentUrl=f"{SOG_ORIGIN}/66b655d3/v1/meta.json",
                          viewerUrl="https://superspl.at/scene/66b655d3", embedUrl="https://superspl.at/s?id=66b655d3",
                          thumbnailUrl="https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/66b655d3/v1/xl.webp",
                          sceneName="industrial plant room within Kenneth Myer building", author="azha007", gaussians=14158102,
                          captureDevice="Xgrids portal cam",
                          credit="\u201cindustrial plant room within Kenneth Myer building\u201d by azha007 on SuperSplat (https://superspl.at/scene/66b655d3); third-party capture, not ours",
                          captureNote=SPLAT_CAPTURE_NOTE,
                          cameraPresets=[dict(id="initial", label="Initial view", fov=75, position=[-8.4004, -0.4771, 0.5886],
                                              target=[88.5429, 2.1959, -82.384])])),
    dict(id="bristol-pumps", prefix="BR", name="Bristol Dock Pump House", site="Bristol Dock Pump House, 1907 pump house under restoration (demonstration site)",
         operator="Dock pump house restoration project (demonstration)", status="under restoration", jurisdiction="ENG-UK", area="engine house",
         siteKind="heritage pump house under restoration, open to visitors",
         environment=dict(kind="splat", format="sog", scanFormat="sog", splatId="8a8ce192", sogMetaUrl=f"{SOG_ORIGIN}/8a8ce192/v1/meta.json",
                          sogUrl=f"{SOG_ORIGIN}/8a8ce192/v1/meta.json", contentUrl=f"{SOG_ORIGIN}/8a8ce192/v1/meta.json",
                          viewerUrl="https://superspl.at/scene/8a8ce192", embedUrl="https://superspl.at/s?id=8a8ce192",
                          thumbnailUrl="https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/8a8ce192/v1/xl.webp",
                          sceneName="1907 pumps being restored", author="scanomatic_labs", gaussians=6934105, captureDevice="portal cam",
                          credit="\u201c1907 pumps being restored\u201d by scanomatic_labs on SuperSplat (https://superspl.at/scene/8a8ce192); third-party capture, not ours",
                          captureNote=SPLAT_CAPTURE_NOTE,
                          cameraPresets=[dict(id="initial", label="Initial view", fov=120, position=[-0.0713, 2.8039, -0.5236],
                                              target=[-0.0221, 2.7469, -0.6373])])),
    # Contract 5 §1. The operator is a demonstration operator: nothing here implies the real site operator uses Steward.
    # The capture streams by level of detail: lod-meta.json (LOD v1, 23,564,860 gaussians over 5 levels in 44 chunk
    # files, octree `tree`, CORS *). `sogMetaUrl`, `sogUrl`, `lodMetaUrl` and `contentUrl` all carry that URL so every
    # existing consumer finds it; `format: "lod"` tells a viewer to use the streamed loader (the v1/meta.json object 403s).
    dict(id="tomioka-mill", prefix="TM", name="Tomioka Silk Mill",
         site="\u5bcc\u5ca1\u88fd\u7cf8\u5834, Tomioka, Gunma Prefecture, Japan (UNESCO World Heritage; buildings designated National Treasures)",
         operator="Demonstration operator (fictional; not the site's real operator)", status="open to visitors", jurisdiction="JP",
         jurisdictionName="Japan (Gunma Prefecture)", area="Silk Reeling Mill",
         siteKind="heritage industrial site; an 1872 silk reeling mill preserved with its reeling machines",
         environment=dict(kind="splat", format="lod", scanFormat="lod", splatId="849bce2a", sogMetaUrl=TOMIOKA_LOD_META, sogUrl=TOMIOKA_LOD_META,
                          lodMetaUrl=TOMIOKA_LOD_META, contentUrl=TOMIOKA_LOD_META,
                          lod=dict(version=1, levels=5, chunkFiles=44, count=23564860, octree="tree"),
                          viewerUrl="https://superspl.at/scene/849bce2a", embedUrl="https://superspl.at/s?id=849bce2a",
                          thumbnailUrl="https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/849bce2a/v1/xl.webp",
                          sceneName="\u5bcc\u5ca1\u88fd\u7cf8\u5834", author="acrylagitt", gaussians=23564860, sizeMB=271.06,
                          credit="\u201c\u5bcc\u5ca1\u88fd\u7cf8\u5834\u201d by acrylagitt on SuperSplat (https://superspl.at/scene/849bce2a); third-party capture, not ours",
                          captureNote=SPLAT_CAPTURE_NOTE,
                          cameraPresets=[dict(id="initial", label="Initial view", fov=75, position=[-32.414, 0.287, -43.351],
                                              target=[-33.558, 0.001, -44.495])])),
]
SITE_IDS = [site["id"] for site in SITES]
SITE_BY_ID = {site["id"]: site for site in SITES}
SITE2 = {site["id"]: site["prefix"] for site in SITES}
SITE_BY_PREFIX = {prefix: site_id for site_id, prefix in SITE2.items()}
SITE_JURISDICTION = {site["id"]: site["jurisdiction"] for site in SITES}
_OLD_ID_RE = re.compile(r"^(cedar|harbor|juniper)([-:])")
_OLD_AGENT_RE = re.compile(r"^agent-(cedar|harbor|juniper)$")
_OLD_SEED_RE = re.compile(r"^seed-(cedar|harbor|juniper)-")
_OLD_REFERENCE_RE = re.compile(r"\b(CH|JR)-([A-Z]+\d{3,4}-[A-Z_]+-\d{4})\b")
_OLD_URL_RE = re.compile(r"^/api/(documents|evidence)/(seed-)?(cedar|harbor|juniper)-")
_ID_FIELDS = {"propertyId", "_propertyId", "siteId"}


def site_env_suffix(site_id: str) -> str:
    """`myer-plant` → `MYER_PLANT` for per-site environment variable names."""
    return site_id.upper().replace("-", "_")


SHAPE_KEYS = ("name", "site", "operator", "status", "jurisdiction", "jurisdictionName", "prefix", "siteKind")


def property_record(site: dict, component_count: int, updated_at: str) -> dict:
    return dict(id=site["id"], **{key: site[key] for key in SHAPE_KEYS if key in site}, environment=dict(site["environment"]),
                readiness=0, componentCount=component_count, openIssues=0, updatedAt=updated_at)


def pin_for(site_id: str, component: dict) -> dict | None:
    """Estimated 3-D scan pin for a registered asset (see registers.estimated_pin); None for unknown sites."""
    if site_id not in SITE_BY_ID:
        return None
    from .registers import estimated_pin
    return estimated_pin(site_id, component)


def _rename_prefixed(value: str) -> str:
    match = _OLD_ID_RE.match(value)
    if match:
        return OLD_TO_NEW[match.group(1)] + value[len(match.group(1)):]
    match = _OLD_AGENT_RE.match(value)
    if match:
        return "agent-" + OLD_TO_NEW[match.group(1)]
    match = _OLD_SEED_RE.match(value)
    if match:
        return "seed-" + OLD_TO_NEW[match.group(1)] + "-" + value[match.end():]
    return value


def _migrate_value(value, field: str = "", text_references: bool = True):
    if isinstance(value, dict):
        return {key: _migrate_value(item, key, text_references) for key, item in value.items()}
    if isinstance(value, list):
        return [_migrate_value(item, field, text_references) for item in value]
    if not isinstance(value, str):
        return value
    if field in _ID_FIELDS:
        return OLD_TO_NEW.get(value, value)
    if field in ("id", "sourceId", "requirementId", "componentId", "jobId", "evidenceId", "documentId", "agentId"):
        return _rename_prefixed(value)
    if field == "url":
        return _OLD_URL_RE.sub(lambda m: f"/api/{m.group(1)}/{m.group(2) or ''}{OLD_TO_NEW[m.group(3)]}-", value)
    if field in ("_path", "filename"):
        return _rename_prefixed(value)
    if field == "ref" and value.startswith("document:"):
        return "document:" + _rename_prefixed(value[len("document:"):])
    if field == "reference" or text_references:
        return _OLD_REFERENCE_RE.sub(lambda m: f"{OLD_PREFIX_TO_NEW[m.group(1)]}-{m.group(2)}", value)
    return value


def _backup(store, prefix: str = "pre-site-ids"):
    backups = store.directory / ".migration-backups"
    backups.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target_path = backups / f"{prefix}-{stamp}.sqlite3"
    source = sqlite3.connect(store.path, timeout=30)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return target_path


def migrate_site_ids(store) -> dict:
    """Rename old site IDs everywhere, once. Returns counts; a no-op on databases that never used the old IDs."""
    if store.meta("steward_site_ids_version") == "2":
        return {}
    with store.connect() as db:
        old_rows = db.execute("SELECT COUNT(*) FROM records WHERE property_id IN ('cedar','harbor','juniper')").fetchone()[0]
        old_props = db.execute("SELECT COUNT(*) FROM records WHERE kind='property' AND id IN ('cedar','harbor','juniper')").fetchone()[0]
    if not old_rows and not old_props:
        store.meta("steward_site_ids_version", "2")
        return {}
    _backup(store)
    from .signing import Signer
    signer = Signer(store.directory)
    counts = dict(records=0, events=0, meta=0, resigned=0, files=0)
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT rowid, kind, id, property_id, body FROM records").fetchall()
        for row in rows:
            original = json.loads(row["body"])
            kind = row["kind"]
            signed = kind == "attestation"
            body = _migrate_value(original, text_references=not signed and kind not in ("fact",))
            if signed and body != original:
                payload = {key: value for key, value in body.items() if key != "signature" and not key.startswith("_")}
                payload["publicKey"] = signer.public_key_b64
                signature, public_key = signer.sign(payload)
                body = {**payload, "publicKey": public_key, "signature": signature,
                        **{key: value for key, value in body.items() if key.startswith("_")}}
                body["_resignedFrom"] = original.get("propertyId")
                counts["resigned"] += 1
            if kind == "property" and row["id"] in OLD_TO_NEW:
                body["id"] = OLD_TO_NEW[row["id"]]
            new_id = body.get("id", row["id"])
            new_property = OLD_TO_NEW.get(row["property_id"], row["property_id"])
            if body != original or new_id != row["id"] or new_property != row["property_id"]:
                db.execute("UPDATE records SET id=?, property_id=?, body=? WHERE rowid=?",
                           (new_id, new_property, json.dumps(body), row["rowid"]))
                counts["records"] += 1
        for row in db.execute("SELECT id, property_id, body FROM events").fetchall():
            body = _migrate_value(json.loads(row["body"]))
            new_property = OLD_TO_NEW.get(row["property_id"], row["property_id"])
            db.execute("UPDATE events SET property_id=?, body=? WHERE id=?", (new_property, json.dumps(body), row["id"]))
            counts["events"] += 1
        for row in db.execute("SELECT key, value FROM meta").fetchall():
            key = row["key"]
            for prefix in ("reality:version:", "reality:seq:"):
                if key.startswith(prefix) and key[len(prefix):] in OLD_TO_NEW:
                    db.execute("DELETE FROM meta WHERE key=?", (key,))
                    db.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (prefix + OLD_TO_NEW[key[len(prefix):]], row["value"]))
                    counts["meta"] += 1
        db.execute("INSERT INTO meta(key,value) VALUES ('steward_site_ids_version','2') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    files = store.directory / "files"
    for path in list(files.iterdir()) if files.exists() else []:
        renamed = _rename_prefixed(path.name)
        if renamed != path.name:
            target = files / renamed
            if not target.exists():
                shutil.move(str(path), str(target))
                counts["files"] += 1
            path = target
        if path.name.startswith("seed-") and path.suffix == ".json":
            try:
                payload = json.loads(path.read_text())
                migrated = _migrate_value(payload)
                if migrated != payload:
                    path.write_text(json.dumps(migrated, indent=2))
            except (ValueError, OSError):
                pass
    return counts


def apply_site_shape(store) -> None:
    """Industrial property records with the registry's environments; idempotent and safe to re-run. Version 5 (contract
    5) also writes the registry's `jurisdiction` (VIC-AU, ENG-UK, JP; it replaces the first generation's free-text
    jurisdiction), the reference `prefix` and `siteKind`, and the environments' `format` / `sogUrl` / `contentUrl`."""
    if store.meta("steward_site_shape_version") == "5":
        return
    for site in SITES:
        prop = store.get("property", site["id"])
        if not prop:
            continue
        for stale_key in ("address", "jurisdiction", "phase"):
            prop.pop(stale_key, None)
        prop.update({key: site[key] for key in SHAPE_KEYS if key in site}, environment=dict(site["environment"]))
        store.put("property", prop)
        legacy = store.get("agent", f"agent-{site['id']}")
        if legacy:
            legacy.update(name=f"Warden · {site['name']}", role=f"{site['name']} site agent",
                          identity=legacy.get("identity") if not str(legacy.get("identity", "")).startswith("local://") else f"local://steward/agents/{site['id']}")
            store.put("agent", legacy)
    portfolio = store.get("agent", "portfolio")
    if portfolio:
        portfolio.update(name="Atlas", role="Portfolio coordinator")
        store.put("agent", portfolio)
    store.meta("steward_site_shape_version", "5")


def _mentions_retired(body: dict) -> str | None:
    for key in ("propertyId", "_propertyId", "siteId"):
        if body.get(key) in RETIRED_SITES:
            return body[key]
    identifier = str(body.get("id", ""))
    for site in RETIRED_SITES:
        if identifier in (f"agent-{site}", f"warden:{site}"):
            return site
    return None


def retire_sites(store) -> dict:
    """Archive every record of a retired site (contract 3: harbor-works), once, after a SQLite backup.

    Records keep their bodies (signatures stay valid) and move to kind `archived:<kind>` under property
    `archived:<site>`, so nothing in the application reads them again; events and per-site meta counters move the
    same way. Files stay on disk. Idempotent: a second run finds nothing and only re-sets the version marker."""
    if store.meta("steward_retired_sites_version") == "3":
        return {}
    retired = tuple(RETIRED_SITES)
    marks = ",".join("?" * len(retired))
    with store.connect() as db:
        rows = db.execute(f"SELECT COUNT(*) FROM records WHERE property_id IN ({marks}) OR (kind='property' AND id IN ({marks}))",
                          retired + retired).fetchone()[0]
        globals_ = [row for row in db.execute("SELECT kind, body FROM records WHERE property_id=''").fetchall()
                    if _mentions_retired(json.loads(row["body"]))]
        events = db.execute(f"SELECT COUNT(*) FROM events WHERE property_id IN ({marks})", retired).fetchone()[0]
    if not rows and not globals_ and not events:
        store.meta("steward_retired_sites_version", "3")
        return {}
    backup = _backup(store, "pre-two-sites")
    counts = dict(records=0, events=0, meta=0, backup=backup.name)
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT rowid, kind, id, property_id, body FROM records").fetchall():
            if row["kind"].startswith("archived:"):
                continue
            body = json.loads(row["body"])
            site = row["property_id"] if row["property_id"] in RETIRED_SITES else (
                row["id"] if row["kind"] == "property" and row["id"] in RETIRED_SITES else (
                    _mentions_retired(body) if row["property_id"] == "" else None))
            if not site:
                continue
            db.execute("UPDATE records SET kind=?, property_id=? WHERE rowid=?", (f"archived:{row['kind']}", f"archived:{site}", row["rowid"]))
            counts["records"] += 1
        for site in retired:
            counts["events"] += db.execute("UPDATE events SET property_id=? WHERE property_id=?", (f"archived:{site}", site)).rowcount
            for prefix in ("reality:version:", "reality:seq:"):
                row = db.execute("SELECT value FROM meta WHERE key=?", (prefix + site,)).fetchone()
                if row:
                    db.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (f"archived:{prefix}{site}", row["value"]))
                    db.execute("DELETE FROM meta WHERE key=?", (prefix + site,))
                    counts["meta"] += 1
        db.execute("INSERT INTO meta(key,value) VALUES ('steward_retired_sites_version','3') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    return counts
