"""Idempotent Steward rename migrations; identifiers and uploaded originals stay intact."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, TextStringObject

LEGACY_DATABASE = "phylax.sqlite3"
LEGACY_HEADER = "PHYLAX / PROJECT EVIDENCE"
LEGACY_AUTHOR = "Phylax local demonstration"
BRAND_VERSION = "1"
AGENT_NAMES = {"portfolio": "Steward Coordinator", "agent-cedar": "Steward Cedar",
               "agent-harbor": "Steward Harbor", "agent-juniper": "Steward Juniper"}
PROTECTED_FIELDS = {"id", "propertyId", "componentId", "requirementId", "sourceId", "jobId", "filename", "url",
                    "sessionId", "eventId", "createdAt", "updatedAt", "uploadedAt", "position", "rotation"}


def prepare_database(directory: Path) -> Path:
    destination = directory / "steward.sqlite3"
    legacy = directory / LEGACY_DATABASE
    if destination.exists() or not legacy.exists():
        return destination
    backups = directory / ".migration-backups"
    backups.mkdir(mode=0o700, exist_ok=True)
    backup = backups / "pre-steward.sqlite3"
    if backup.exists():
        backup = backups / f"pre-steward-{uuid4().hex[:8]}.sqlite3"
    # SQLite's backup API includes committed WAL contents; copying only the main file would lose them.
    source = sqlite3.connect(legacy, timeout=30)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    temporary = directory / f".steward-{uuid4().hex}.sqlite3.tmp"
    shutil.copy2(backup, temporary)
    temporary.replace(destination)
    # Keep the original source and sidecars as a recovery copy, without leaving an active legacy filename.
    archived = backups / f"legacy-source-{uuid4().hex[:8]}.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        old = Path(str(legacy) + suffix)
        if old.exists():
            old.replace(Path(str(archived) + suffix))
    return destination


def brand_text(value: str) -> str:
    value = value.replace("PHYLAX", "STEWARD").replace("Phylax", "Steward").replace("phylax", "steward")
    for old, new in (("Atlas", "Steward Coordinator"), ("Mira", "Steward Cedar"),
                     ("Orion", "Steward Harbor"), ("Sage", "Steward Juniper")):
        value = re.sub(r"\b" + old + r"\b", new, value)
    return value


def brand_values(value, field=""):
    if field in PROTECTED_FIELDS or field.startswith("_"):
        return value
    if isinstance(value, dict):
        return {key: brand_values(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [brand_values(item) for item in value]
    if isinstance(value, str):
        if field == "identity" and not value.startswith("local://"):
            return value  # An assigned external mailbox address is not a display brand.
        if field == "source" and value.startswith(("job:", "chat:", "evidence:")):
            return value
        return brand_text(value)
    return value


def migrate_records(store):
    if store.meta("steward_brand_version") == BRAND_VERSION:
        return
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT kind,id,property_id,body FROM records").fetchall():
            original = json.loads(row["body"])
            body = brand_values(original)
            # Uploaded source text remains verbatim; only original seed PDFs are rebranded below.
            if row["kind"] == "document" and "extractedText" in original:
                body["extractedText"] = original["extractedText"]
            if row["kind"] == "agent" and row["id"] in AGENT_NAMES:
                body["name"] = AGENT_NAMES[row["id"]]
                if row["id"] == "portfolio":
                    body["role"] = "Steward portfolio coordinator"
            if body != original:
                db.execute("UPDATE records SET body=? WHERE kind=? AND id=? AND property_id=?",
                           (json.dumps(body), row["kind"], row["id"], row["property_id"]))
        for row in db.execute("SELECT id,body FROM events").fetchall():
            body = brand_values(json.loads(row["body"]))
            db.execute("UPDATE events SET body=? WHERE id=?", (json.dumps(body), row["id"]))
        for row in db.execute("SELECT key,value FROM meta").fetchall():
            try:
                value = json.dumps(brand_values(json.loads(row["value"])))
            except (ValueError, TypeError):
                value = brand_text(row["value"])
            # Preserve opaque keys, including webhook deduplication identifiers.
            db.execute("UPDATE meta SET value=? WHERE key=?", (value, row["key"]))
        db.execute("INSERT INTO meta(key,value) VALUES ('steward_brand_version',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (BRAND_VERSION,))


def rebrand_seed_pdfs(store):
    if store.meta("steward_seed_pdf_brand_version") == BRAND_VERSION:
        return
    for property_id in ("cedar", "harbor", "juniper"):
        for suffix in ("spec", "register", "observations"):
            identifier = f"{property_id}-{suffix}"
            document = store.get("document", identifier, property_id)
            expected = f"{identifier}.pdf"
            if not document or document.get("_path") != expected:
                continue
            path = store.directory / "files" / expected
            if not path.exists():
                continue
            reader = PdfReader(path)
            if str((reader.metadata or {}).get("/Author", "")) != LEGACY_AUTHOR:
                continue
            writer = PdfWriter()
            for page in reader.pages:
                content = ContentStream(page.get_contents(), reader)
                for operands, operator in content.operations:
                    if operator == b"Tj" and str(operands[0]) == LEGACY_HEADER:
                        operands[0] = TextStringObject("STEWARD / PROJECT EVIDENCE")
                    elif operator == b"TJ":
                        for index, operand in enumerate(operands[0]):
                            if str(operand) == LEGACY_HEADER:
                                operands[0][index] = TextStringObject("STEWARD / PROJECT EVIDENCE")
                page.replace_contents(content)
                writer.add_page(page)
            metadata = {key: str(value) for key, value in (reader.metadata or {}).items()}
            metadata["/Author"] = "Steward local demonstration"
            writer.add_metadata(metadata)
            temporary = path.with_suffix(".steward.tmp")
            with temporary.open("wb") as file:
                writer.write(file)
            temporary.replace(path)
            updated = PdfReader(path)
            document.update(size=path.stat().st_size,
                            extractedText="\n\f\n".join(page.extract_text() or "" for page in updated.pages))
            store.put("document", document, property_id)
    store.meta("steward_seed_pdf_brand_version", BRAND_VERSION)
