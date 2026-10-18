import gc
import hashlib
import json
import sqlite3

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from src.env import env
from src.integrations import ModelAdapter
from src.service import PropertyService


def test_canonical_environment_preserves_legacy_alias_and_precedence(monkeypatch):
    monkeypatch.delenv("STEWARD_MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("PHY_MODEL_PROVIDER", "openai")
    assert env("STEWARD_MODEL_PROVIDER", "local") == "openai"
    assert ModelAdapter().provider == "openai"
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    assert ModelAdapter().provider == "local"
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "")
    assert env("STEWARD_MODEL_PROVIDER", "local") == ""  # An explicit empty canonical value wins.


def test_legacy_database_upgrade_keeps_ids_uploads_jobs_and_rebrands_owned_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "legacy-upgrade"
    original = PropertyService(directory, start_workers=False)
    user_document = original.upload_document("myer-plant", "user-source.txt", b"Phylax is mentioned in this original uploaded source.", "User documents")
    user_path = directory / "files" / user_document["_path"]
    user_bytes = user_path.read_bytes()
    evidence_path = directory / "files" / original.store.all("evidence", "myer-plant")[0]["_path"]
    evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    purchase = original.propose_purchase("myer-plant", "pump-01", "Phylax gasket proposal", 25, "USD")
    job = original.create_job("myer-plant", scope="pump-01")
    original.store.put("chat", {"id": "phylax-stable-chat-id", "role": "assistant", "content": "Phylax: Mira checked the record.", "createdAt": "2026-10-17T00:00:00Z"}, "myer-plant")
    memory = original.save_memory("myer-plant", "PHYLAX: Atlas coordinated the portfolio.", "chat:phylax-stable-chat-id")
    event = original.store.event("myer-plant", "agent-myer-plant", "test", "Phylax observation", "Mira checked the supplied record.")
    original.store.meta("integration:example", json.dumps({"status": "local", "detail": "Phylax local context"}))
    agent = original.store.get("agent", "agent-myer-plant")
    agent.update(name="Mira", identity="local://phylax/agents/myer-plant")
    original.store.put("agent", agent)
    # Simulate the original owned fixture PDF. An unrelated uploaded original must remain untouched.
    seed_path = directory / "files" / "myer-plant-spec.pdf"
    pdf = canvas.Canvas(str(seed_path))
    pdf.setAuthor("Phylax local demonstration")
    pdf.drawString(42, 800, "PHYLAX / PROJECT EVIDENCE")
    pdf.drawString(42, 760, "Original fixture body and source data.")
    pdf.save()
    original.write_report("myer-plant")
    before_counts = {kind: len(original.store.all(kind)) for kind in ("property", "component", "requirement", "document", "evidence", "job", "purchase", "memory", "chat")}
    original.close()
    canonical = directory / "steward.sqlite3"
    with sqlite3.connect(canonical) as db:
        db.execute("DELETE FROM meta WHERE key LIKE 'steward_%'")
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    gc.collect()
    legacy = directory / "phylax.sqlite3"
    canonical.rename(legacy)
    for suffix in ("-wal", "-shm"):
        path = directory / ("steward.sqlite3" + suffix)
        if path.exists():
            path.rename(directory / ("phylax.sqlite3" + suffix))
    upgraded = PropertyService(directory, start_workers=False)
    assert upgraded.store.path.name == "steward.sqlite3"
    assert (directory / ".migration-backups" / "pre-steward.sqlite3").exists()
    assert not legacy.exists()
    assert {kind: len(upgraded.store.all(kind)) for kind in before_counts} == before_counts
    assert upgraded.store.get("job", job["id"])["status"] == "queued"
    assert upgraded.store.get("purchase", purchase["id"], "myer-plant")["description"] == "Steward gasket proposal"
    assert upgraded.store.get("chat", "phylax-stable-chat-id", "myer-plant")["content"] == "Steward: Steward Cedar checked the record."
    assert upgraded.store.get("memory", memory["id"], "myer-plant")["source"] == "chat:phylax-stable-chat-id"
    assert upgraded.store.get("agent", "agent-myer-plant")["name"] == "Warden · Myer Plant Room"
    assert upgraded.store.get("agent", "agent-myer-plant")["identity"] == "local://steward/agents/myer-plant"
    migrated_event = next(item for item in upgraded.store.events("myer-plant") if item["id"] == event["id"])
    assert migrated_event["title"] == "Steward observation"
    assert json.loads(upgraded.store.meta("integration:example"))["detail"] == "Steward local context"
    assert user_path.read_bytes() == user_bytes
    assert upgraded.store.get("document", user_document["id"], "myer-plant")["extractedText"] == user_bytes.decode()
    assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == evidence_hash
    reader = PdfReader(seed_path)
    assert "STEWARD / PROJECT EVIDENCE" in reader.pages[0].extract_text()
    assert "Original fixture body and source data." in reader.pages[0].extract_text()
    assert "PHYLAX" not in reader.pages[0].extract_text()
    assert reader.metadata.author == "Steward local demonstration"
    assert "STEWARD / Myer Plant Room" in (directory / "files" / "myer-plant-report.html").read_text()
    assert upgraded.require_property("myer-plant")["name"] == "Myer Plant Room"
    upgraded.close()
    # A second startup must not duplicate data, redo source migrations or change attachment bytes.
    again = PropertyService(directory, start_workers=False)
    assert {kind: len(again.store.all(kind)) for kind in before_counts} == before_counts
    assert user_path.read_bytes() == user_bytes
    again.close()
