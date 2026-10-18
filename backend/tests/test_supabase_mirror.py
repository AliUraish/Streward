"""The Supabase mirror's authority, redaction, batching and budget behaviour (mock transports; no network)."""
import base64
import json
import re
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.mirror import Mirror, build_row, redact_text
from src.supa_authority import AGENT_IDS, MATRIX, author_for, permitted
from src.supa_budget import MB

ROOT = Path(__file__).resolve().parents[2]


def fake_jwt(claims: dict) -> str:
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{part({'alg': 'ES256'})}.{part(claims)}.c2ln"


class FakeSupabase:
    """PostgREST + Auth stand-in: records every request, signs agents in, and refuses what RLS would refuse."""

    def __init__(self, refuse: set[tuple[str, str]] | None = None):
        self.requests = []
        self.refuse = refuse or set()

    def __call__(self, request: httpx.Request):
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, dict(request.headers), body, dict(request.url.params)))
        if request.url.path == "/auth/v1/token":
            email = body["email"] if body and "email" in body else "agent+operator@steward.invalid"
            agent = email.split("+", 1)[1].split("@", 1)[0]
            return httpx.Response(200, json=dict(access_token=fake_jwt({"agent_id": agent, "role": "authenticated"}) + "." + agent,
                                                 refresh_token="r-" + agent, expires_in=3600, expires_at=time.time() + 3600))
        token = request.headers.get("authorization", "")
        writer = token.rsplit(".", 1)[-1] if token.count(".") >= 3 else "service_role"
        table = request.url.path.rsplit("/", 1)[-1]
        if (table, writer) in self.refuse:
            return httpx.Response(403, json=dict(code="42501", message=f'new row violates row-level security policy for table "{table}"'))
        return httpx.Response(201)

    def writes(self, table: str):
        return [(h, b) for m, p, h, b, _ in self.requests if p == f"/rest/v1/{table}"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def configure(monkeypatch, agents=True):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_test")
    if agents:
        monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_test")
        for agent in AGENT_IDS:
            monkeypatch.setenv("STEWARD_AGENT_PASSWORD_" + agent.upper().replace("-", "_"), "pw-" + agent)


def install(client, fake):
    reality = client.app.state.service.reality
    reality.mirror.close()
    reality.mirror = Mirror(reality.store, transport=httpx.MockTransport(fake))
    return reality.mirror


def test_python_matrix_matches_the_migration_text():
    sql = (ROOT / "supabase" / "migrations" / "0003_authority.sql").read_text()
    block = sql[sql.index("insert into steward.authority"):sql.index("on conflict (tbl) do update")]
    rows = re.findall(r"\('(\w+)',\s+(null|'\w+'),\s+'(\w+)',\s+array\[([^\]]*)\](?:::text\[\])?,\s+(null|'\w+'),\s+(true|false)\)", block)
    parsed = {t: dict(site_col=None if c == "null" else c.strip("'"), site_kind=k, writers=tuple(w.strip().strip("'") for w in ws.split(",") if w.strip()),
                      bind=None if b == "null" else b.strip("'"), append_only=a == "true") for t, c, k, ws, b, a in rows}
    assert parsed == MATRIX


def test_agent_rows_use_the_agents_token_and_system_rows_the_secret_key(client, monkeypatch):
    configure(monkeypatch)
    fake = FakeSupabase()
    mirror = install(client, fake)
    response = client.post("/api/properties/myer-plant/resolve", json={"assetTag": "P-101", "attribute": "pressure_bar", "budget": 5},
                           headers={"X-Steward-Actor": "myer-technician"})
    assert response.status_code == 200, response.text
    client.app.state.service.telemetry.record("bristol-engineer", "tool", "eye_look", tokens=5, site_id="bristol-pumps")
    mirror.executor.shutdown(wait=True)
    work = fake.writes("work_items")
    assert work and work[0][0]["authorization"].endswith(".myer-technician") and work[0][0]["apikey"] == "sb_publishable_test"
    changes = fake.writes("changes")
    assert changes and "authorization" not in changes[0][0] and changes[0][0]["apikey"] == "sb_secret_test"  # new keys: apikey header only
    telemetry = [h for h, b in fake.writes("telemetry") if any(r.get("agent_id") == "bristol-engineer" for r in b)]
    assert telemetry and telemetry[0]["authorization"].endswith(".bristol-engineer")
    dispatches = fake.writes("dispatches")
    assert dispatches and dispatches[0][0]["authorization"].endswith(".myer-technician")  # the acting technician dispatches
    assert mirror.stats()["rowsByWriter"]["myer-technician"] >= 2 and mirror.tokens.logins <= 3  # tokens cached, not one login per row


def test_rls_refusal_is_recorded_and_never_retried_with_the_secret_key(client, monkeypatch):
    configure(monkeypatch)
    fake = FakeSupabase(refuse={("telemetry", "myer-technician")})
    mirror = install(client, fake)
    client.app.state.service.telemetry.record("myer-technician", "tool", "contact", tokens=5, site_id="myer-plant")
    mirror.executor.shutdown(wait=True)
    attempts = [(h, b) for h, b in fake.writes("telemetry") if any(r.get("agent_id") == "myer-technician" for r in b)]
    assert len(attempts) == 1 and attempts[0][0]["authorization"].endswith(".myer-technician")
    assert mirror.refused >= 1 and mirror.last_refusal["code"] == "42501" and mirror.last_refusal["writer"] == "myer-technician"
    events = client.get("/api/properties/myer-plant/events").json()
    assert any(e["type"] == "mirror.refused" and "row-level security" in e["detail"] for e in events)


def test_without_agent_passwords_everything_uses_the_secret_key(client, monkeypatch):
    configure(monkeypatch, agents=False)
    fake = FakeSupabase()
    mirror = install(client, fake)
    client.app.state.service.telemetry.record("myer-engineer", "tool", "eye_look", tokens=5, site_id="myer-plant")
    mirror.executor.shutdown(wait=True)
    assert fake.requests and all("authorization" not in h for _, p, h, _, _ in fake.requests if p.startswith("/rest/"))
    assert not mirror.tokens.enabled


def test_contact_details_are_masked_but_signed_attestations_are_byte_exact(client, monkeypatch):
    assert redact_text("reply from +14155550123 and dana@example.com") == "reply from ••• ••• 0123 and d•••@example.com"
    row = build_row("change", {"id": "myer-plant:9", "version": 9, "type": "reply", "propertyId": "myer-plant",
                               "summary": "Reply received via sms from +14155550123", "at": "2026-10-18T00:00:00Z"})
    assert row["summary"] == "Reply received via sms from ••• ••• 0123" and row["id"] == "myer-plant:9"
    dispatch = build_row("dispatch", {"id": "d1", "to": "contractor@example.com", "body": "Call +447700900123", "workItemId": "wi-1"})
    assert dispatch["to"] == "c•••@example.com" and dispatch["body"] == "Call ••• ••• 0123" and dispatch["work_item_id"] == "wi-1"
    service = client.app.state.service
    result = client.post("/api/properties/myer-plant/attest", json={"assetTag": "P-101", "attribute": "pressure_bar", "value": 3.2,
                                                                    "source": {"kind": "human", "ref": "sms:+14155550123"}})
    attestation = service.store.get("attestation", result.json()["attestationId"])
    row = build_row("attestation", attestation)
    assert row["source"]["ref"] == "sms:+14155550123"  # signed content is never altered
    payload = json.loads(row["signed_payload"])
    assert "signature" not in payload and payload["publicKey"] == attestation["publicKey"] and payload["id"] == attestation["id"]
    forged = dict(attestation, value=99)
    assert build_row("attestation", forged)["signed_payload"] is None  # a body that no longer verifies carries no signed payload


def test_batches_coalesce_and_the_latest_version_wins(client, monkeypatch):
    configure(monkeypatch, agents=False)
    fake = FakeSupabase()
    mirror = install(client, fake)
    mirror.executor.submit(time.sleep, 0.3)  # hold the writer so the puts below queue up together
    for version in range(5):
        mirror.put("change", {"id": "myer-plant:x", "version": version, "type": "fact", "propertyId": "myer-plant", "summary": f"v{version}",
                              "at": "2026-10-18T00:00:00Z"}, "myer-plant")
    mirror.executor.shutdown(wait=True)
    writes = fake.writes("changes")
    assert len(writes) == 1 and writes[0][1] == [dict(id="myer-plant:x", version=4, type="fact", property_id="myer-plant", summary="v4",
                                                      at="2026-10-18T00:00:00Z")]


def test_database_cap_sheds_simulated_rows_then_everything(client, monkeypatch):
    configure(monkeypatch, agents=False)
    monkeypatch.setenv("SUPABASE_CAP_DB_MB", "100")
    fake = FakeSupabase()
    mirror = install(client, fake)
    mirror.budget.set_db_bytes(85 * MB)
    sim = {"id": "f-sim", "propertyId": "myer-plant", "simulated": True, "source": {"kind": "sensor", "ref": "sim"}}
    mirror.put("fact", sim, "myer-plant")
    mirror.put("issue", {"id": "iss-1", "siteId": "myer-plant", "summary": "kept"}, "myer-plant")
    mirror.budget.set_db_bytes(100 * MB)
    mirror.put("issue", {"id": "iss-2", "siteId": "myer-plant", "summary": "full"}, "myer-plant")
    mirror.executor.shutdown(wait=True)
    assert not fake.writes("facts")
    assert [b[0]["id"] for _, b in fake.writes("issues")] == ["iss-1"]
    assert mirror.shed == 2 and mirror.budget.refusals_today("db_mb") == 1


def test_author_rules_never_hand_a_technician_an_attestation():
    signed = {"property_id": "myer-plant", "source": {"kind": "human", "ref": "sms:1"}, "signed_payload": "{}"}
    assert author_for("attestations", signed, {}, actor="myer-technician") == "myer-engineer"
    assert author_for("attestations", dict(signed, source={"kind": "sensor", "ref": "sim"}), {"simulated": True}, actor="myer-engineer") is None
    assert author_for("obligations", {"site_id": "myer-plant"}, {}, actor="operator") == "myer-compliance"
    assert author_for("issues", {"site_id": "bristol-pumps"}, {"history": [{"by": "bristol-manager"}]}) == "bristol-manager"
    assert author_for("eye_frames", {"site_id": "myer-plant", "actor": "director"}, {}) == "director"
    assert not permitted("myer-engineer", "attestations", dict(signed, property_id="bristol-pumps"))  # cross-site
    assert permitted("director", "maintenance_windows", {"site_ids": ["myer-plant", "bristol-pumps"]})
    assert permitted("bristol-manager", "maintenance_windows", {"site_ids": ["myer-plant", "bristol-pumps"]})  # a participant site
    assert not permitted("bristol-manager", "maintenance_windows", {"site_ids": ["myer-plant"]})
