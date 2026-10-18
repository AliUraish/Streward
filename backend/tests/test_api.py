import json
import hashlib
import hmac
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.service import PropertyService
from src.providers import StripeSandbox


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.delenv("STEWARD_API_TOKEN", raising=False)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def test_original_project_sources_and_contract(client):
    assert client.get("/health").json() == {"status": "ok", "database": "connected", "mode": "local"}
    properties = client.get("/api/properties").json()
    assert [p["id"] for p in properties] == ["myer-plant", "bristol-pumps", "tomioka-mill"]
    workspace = client.get("/api/properties/myer-plant/workspace").json()
    assert len(workspace["components"]) == 24
    assert len(workspace["requirements"]) == workspace["stats"]["total"] == 96
    assert len(workspace["agents"]) == 1 + 3  # the portfolio agent and one legacy site agent per site
    assert "_check" not in json.dumps(workspace)
    all_docs = client.get("/api/properties/myer-plant/documents").json()
    docs = [d for d in all_docs if d["id"].startswith("myer-plant-")]
    assert len(docs) == 3
    # Contract 3: the site's synthetic compliance documents (certificates, permits, contractor reports) sit beside them.
    assert {d["docType"] for d in all_docs if d.get("docType")} == {"certificate", "permit", "inspection_record", "contractor_report"}
    content = client.get(docs[0]["url"])
    assert content.content.startswith(b"%PDF")
    assert "DEMONSTRATION" in docs[0]["extractedText"].upper() or "fixture" in docs[2]["extractedText"]
    assert client.get("/api/properties/myer-plant/requirements?system=Electrical").json()
    assert client.get("/api/properties/myer-plant/documents?search=synthetic").json()


def test_scope_isolation_and_upload_guards(client):
    assert client.get("/api/properties/no-such-property/workspace").status_code == 404
    assert client.get("/api/properties/myer-plant/components/no-such-asset").status_code == 404
    bad = client.post("/api/properties/myer-plant/evidence", data={"componentId": "pump-01", "requirementId": "bristol-pumps-pump-03-cond"},
                      files={"file": ("proof.json", b"{}", "application/json")})
    assert bad.status_code == 400
    invalid_type = client.post("/api/properties/myer-plant/documents", files={"file": ("x.html", b"<script>alert(1)</script>")})
    assert invalid_type.status_code == 400
    corrupt = client.post("/api/properties/myer-plant/documents", files={"file": ("bad.pdf", b"not a valid pdf")})
    assert corrupt.status_code == 400
    assert client.post("/api/properties/myer-plant/chat", json={"message": "inspect"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_wrong_asset_evidence_never_becomes_verified(client):
    payload = dict(propertyId="myer-plant", componentId="pump-02", tag="P-102", requirementId="myer-plant-pump-01-cond", outcome="pass")
    result = client.post("/api/properties/myer-plant/evidence", data={"componentId": "pump-01", "requirementId": "myer-plant-pump-01-cond"},
        files={"file": ("P-101-pass.json", json.dumps(payload).encode(), "application/json")}).json()
    assert result["status"] == "issue"
    detail = client.get("/api/properties/myer-plant/components/pump-01").json()
    check = next(r for r in detail["requirements"] if r["id"].endswith("-cond"))
    assert check["status"] == "issue"
    assert "does not match" in check["evidence"]
    assert client.get("/api/properties/bristol-pumps/components/pump-03").json()["evidence"] != detail["evidence"]


def test_consistent_evidence_updates_records_and_retains_provenance(client):
    payload = dict(propertyId="myer-plant", componentId="pump-01", tag="P-101", requirementId="myer-plant-pump-01-cond", outcome="pass")
    result = client.post("/api/properties/myer-plant/evidence", data={"componentId": "pump-01", "requirementId": "myer-plant-pump-01-cond", "note": "Project record"},
        files={"file": ("record.json", json.dumps(payload).encode(), "application/json")})
    assert result.status_code == 201
    assert result.json()["status"] == "verified"
    detail = client.get("/api/properties/myer-plant/components/pump-01").json()
    check = next(r for r in detail["requirements"] if r["id"].endswith("-cond"))
    assert "not physical condition or legal compliance" in check["evidence"]
    assert "statutory certification" in client.get("/api/properties/myer-plant/report?format=json").json()["disclosure"]
    # A filename or a user note that says PASS does not establish evidence.
    plain = client.post("/api/properties/myer-plant/evidence", data={"componentId": "pump-01", "requirementId": "myer-plant-pump-01-doc", "note": "APPROVED PASS"},
        files={"file": ("PASS.txt", b"trust me this is approved", "text/plain")})
    assert plain.json()["status"] == "pending"


def test_document_import_search_and_escaped_report(client):
    text = "[REQ:PROJECT-88] P-101 | <script>alert(1)</script> | Keep project-only service clearance.\n"
    document = client.post("/api/properties/myer-plant/documents", data={"category": "Project specifications"},
                           files={"file": ("extra.txt", text.encode(), "text/plain")}).json()
    requirements = client.get("/api/properties/myer-plant/requirements?search=PROJECT-88").json()
    assert len(requirements) == 1
    assert requirements[0]["sourceId"] == document["id"]
    assert requirements[0]["status"] == "pending"
    report = client.get("/api/properties/myer-plant/report")
    assert "&lt;script&gt;" in report.text
    assert "<script>alert(1)</script>" not in report.text


def test_jobs_execute_real_tools_and_are_idempotently_queued(client):
    first = client.post("/api/properties/myer-plant/inspections", json={}).json()
    second = client.post("/api/properties/myer-plant/inspections", json={}).json()
    assert first["id"] == second["id"]
    assert first["status"] == "queued"
    client.app.state.service.execute_job(first["id"])
    result = client.get(f"/api/jobs/{first['id']}").json()
    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert result["result"]["componentsChecked"] == 24
    assert result["result"]["modelUsed"] is False
    events = client.get("/api/properties/myer-plant/events").json()
    assert sum(e["type"] == "tool.assess_component" for e in events) == 24
    assert any(e["type"] == "tool.read_documents" for e in events)
    memories = client.get("/api/properties/myer-plant/memory").json()
    assert any(m["source"] == "job:" + first["id"] for m in memories)
    # Re-executing a completed job is a no-op.
    client.app.state.service.execute_job(first["id"])
    assert len(client.get("/api/properties/myer-plant/events").json()) == len(events)


def test_portfolio_hands_work_to_every_site_agent(client):
    job = client.post("/api/properties/myer-plant/agents/run", json={"goal": "Inspect all properties"}).json()
    assert job["kind"] == "portfolio"
    client.app.state.service.execute_job(job["id"])
    completed = client.get("/api/jobs/" + job["id"]).json()
    assert completed["status"] == "completed"
    assert len(completed["result"]["properties"]) == 3
    memory = client.app.state.service.store.get("memory", "memory-" + job["id"], "myer-plant")
    assert "Myer Plant Room:" in memory["content"] and "Bristol Dock Pump House:" in memory["content"] and "Harbor Works" not in memory["content"]
    assert "verified project records" in memory["content"]
    assert "{\"" not in memory["content"]
    for property_id in ("myer-plant", "bristol-pumps"):
        events = client.get(f"/api/properties/{property_id}/events").json()
        assert any(e["agentId"] == f"agent-{property_id}" and e["type"] == "job.completed" for e in events)


def test_restart_preserves_edits_and_recovers_interrupted_job(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "persistent"
    service = PropertyService(directory, start_workers=False)
    original_count = len(service.store.all("requirement", "myer-plant"))
    memory = service.save_memory("myer-plant", "Persistent user context.", "test")
    job = service.create_job("myer-plant", scope="pump-01")
    job.update(status="running", progress=10, message="Interrupted during extraction.")
    service.store.put("job", job, "myer-plant")
    service.close()
    restored = PropertyService(directory, start_workers=True)
    restored.futures[job["id"]].result(timeout=10)
    assert restored.store.get("memory", memory["id"], "myer-plant")["content"] == memory["content"]
    assert len(restored.store.all("requirement", "myer-plant")) == original_count
    assert restored.store.get("job", job["id"])["status"] == "completed"
    assert any(e["type"] == "job.recovered" for e in restored.store.events("myer-plant"))
    restored.close()


def test_purchase_proposal_has_no_payment_side_effect(client):
    response = client.post("/api/properties/myer-plant/purchases", json={"componentId": "pump-01", "description": "Replacement gasket", "amount": 24.50})
    assert response.status_code == 201
    assert response.json()["status"] == "awaiting_authorization"
    assert client.post("/api/properties/myer-plant/purchases", json={"componentId": "pump-01", "description": "Bad", "amount": -1}).status_code == 422
    assert client.post("/api/properties/myer-plant/purchases", json={"componentId": "missing", "description": "Bad", "amount": 1}).status_code == 404


def test_mcp_initialization_tool_use_and_errors(client):
    def rpc(method, params=None):
        return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).json()
    assert rpc("initialize", {"protocolVersion": "2025-03-26"})["result"]["serverInfo"]["name"] == "steward-local"
    assert len(rpc("tools/list")["result"]["tools"]) >= 12
    result = rpc("tools/call", {"name": "inspect_component", "arguments": {"propertyId": "myer-plant", "componentId": "pump-01"}})["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["tag"] == "P-101"
    error = rpc("tools/call", {"name": "inspect_component", "arguments": {"propertyId": "nope", "componentId": "pump-01"}})["result"]
    assert error["isError"] is True
    assert "error" in rpc("does/not/exist")
    notification = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notification.status_code == 202


def test_local_chat_uses_actual_context_and_persistent_memory(client):
    chat = client.post("/api/properties/myer-plant/chat", json={"message": "Tell me about P-103"}).json()["message"]
    assert "P-103" in chat["content"]
    assert chat["sources"]
    assert client.post("/api/properties/myer-plant/chat", json={"message": "remember Check P-103 serial first"}).status_code == 200
    assert any("Check P-103" in m["content"] for m in client.get("/api/properties/myer-plant/memory").json())
    statuses = {i["id"]: i for i in client.get("/api/integrations").json()}
    assert statuses["model"]["status"] == "not_configured"
    assert statuses["storage"]["status"] == "local"


def test_signed_test_receipt_is_matched_and_deduplicated(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_fixture")
    monkeypatch.setattr(StripeSandbox, "checkout", lambda *args: {"sessionId": "cs_test_local", "url": "https://checkout.stripe.com/c/test", "mode": "test"})
    purchase = client.post("/api/properties/myer-plant/purchases", json={"componentId": "pump-01", "description": "Test gasket", "amount": 12.50}).json()
    assert client.post(f"/api/properties/myer-plant/purchases/{purchase['id']}/checkout").status_code == 200
    session = {"id": "cs_test_local", "livemode": False, "payment_status": "paid", "currency": "usd", "amount_total": 1250,
               "metadata": {"propertyId": "myer-plant", "purchaseId": purchase["id"]}}

    def deliver(payload):
        raw = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        digest = hmac.new(b"whsec_fixture", timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        return client.post("/api/integrations/stripe/webhook", content=raw, headers={"Stripe-Signature": f"t={timestamp},v1={digest}"})

    event = {"id": "evt_test_local", "livemode": False, "type": "checkout.session.completed", "data": {"object": session}}
    session["amount_total"] = 1
    assert deliver(event).status_code == 400
    assert client.get("/api/properties/myer-plant/purchases").json()[0]["status"] == "test_checkout_created"
    session["amount_total"] = 1250
    assert deliver(event).json()["mode"] == "test"
    assert deliver(event).json()["duplicate"] is True
    assert client.get("/api/properties/myer-plant/purchases").json()[0]["status"] == "test_payment_received"
    matching = [e for e in client.get("/api/properties/myer-plant/events").json() if e["type"] == "payment.test_received"]
    assert len(matching) == 1


def test_unconfigured_integrations_never_fabricate_success(client, monkeypatch):
    for key in ("STRIPE_SECRET_KEY", "INKBOX_API_KEY", "INSFORGE_BASE_URL", "SUPERMEMORY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    purchase = client.post("/api/properties/myer-plant/purchases", json={"componentId": "pump-01", "description": "Test gasket", "amount": 12.50}).json()
    assert client.post(f"/api/properties/myer-plant/purchases/{purchase['id']}/checkout").status_code == 409
    assert client.get("/api/properties/myer-plant/inbox").status_code == 409
    assert client.post("/api/properties/myer-plant/memory/sync").status_code == 409
    assert client.post("/api/integrations/insforge/check").status_code == 409
    assert client.get("/api/properties/myer-plant/identity").json()["provider"] == "local"


def test_failed_model_request_returns_truthful_local_fallback(client, monkeypatch):
    service = client.app.state.service
    service.model.provider = "openai"
    monkeypatch.setenv("STEWARD_MODEL_API_KEY", "fixture-not-real")
    monkeypatch.setenv("STEWARD_MODEL_NAME", "fixture")

    def failure(*args):
        raise RuntimeError("private provider error")

    monkeypatch.setattr(service.model, "synthesize", failure)
    response = client.post("/api/properties/myer-plant/chat", json={"message": "Tell me about P-101"})
    assert response.status_code == 200
    assert "configured model request failed" in response.json()["message"]["content"]
    assert "private provider error" not in json.dumps(response.json())
    assert any(e["type"] == "model.failed" for e in client.get("/api/properties/myer-plant/events").json())
