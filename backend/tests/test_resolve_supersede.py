"""Superseded facts never make a conflict: a sensor's own rising series is a time series, and an accepted reading for a
dispatched work item (including the clarification a conflict asked for) settles everything observed before it. The
receipt's dispatchedVia is a channel or absent, never null (the MCP contract rejects null)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.verify import iso


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    for key in ("STEWARD_API_TOKEN", "INKBOX_API_KEY", "INKBOX_IDENTITY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "STEWARD_INBOUND_SECRET"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def reality(client):
    return client.app.state.service.reality


def resolve(client, tag, attribute, **extra):
    response = client.post("/api/properties/myer-plant/resolve", json={"assetTag": tag, "attribute": attribute, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_sensor_series_is_not_a_conflict(client):
    service = reality(client)
    gauge = service.component_by_tag("myer-plant", "PG-601")
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    for index, value in enumerate([3.1, 3.6, 4.1]):
        service.write_fact("myer-plant", gauge, "pressure_bar", "reading", value, "bar", iso(start + timedelta(minutes=index)),
                           {"kind": "sensor", "ref": "scenario:test"}, [], [str(index) * 64])
    known = resolve(client, "PG-601", "pressure_bar")
    assert known["status"] == "known" and known["value"] == 4.1 and "dispatchedVia" not in known


def test_two_sources_that_disagree_still_conflict_and_the_receipt_has_no_null_channel(client):
    service = reality(client)
    gauge = service.component_by_tag("myer-plant", "PG-601")
    moment = datetime.now(timezone.utc)
    service.write_fact("myer-plant", gauge, "pressure_bar", "reading", 2.2, "bar", iso(moment - timedelta(minutes=4)), {"kind": "sensor", "ref": "bms"}, [], ["a" * 64])
    service.write_fact("myer-plant", gauge, "pressure_bar", "reading", 3.9, "bar", iso(moment - timedelta(minutes=2)), {"kind": "human", "ref": "sms:1"}, [], ["b" * 64])
    conflict = resolve(client, "PG-601", "pressure_bar")
    assert conflict["status"] == "conflict" and len(conflict["conflicts"]) == 2 and conflict["workState"] == "needs_clarification"
    assert "dispatchedVia" not in conflict  # nothing was dispatched for a clarification item


def test_an_accepted_clarification_ends_the_conflict_it_asked_for(client):
    service = reality(client)
    valve = service.component_by_tag("myer-plant", "V-501")
    service.write_fact("myer-plant", valve, "position", "reading", "closed", None, iso(datetime.now(timezone.utc) - timedelta(minutes=10)),
                       {"kind": "agent", "ref": "test"}, [], ["0" * 64])
    conflict = resolve(client, "V-501", "position")
    assert conflict["status"] == "conflict"
    answer = client.post("/api/properties/myer-plant/attest", json={
        "assetTag": "V-501", "attribute": "position", "value": "open", "statedTag": "V-501",
        "source": {"kind": "human", "ref": "sms:clarify"}, "workItemId": conflict["workItemId"]}).json()
    assert answer["verdict"] == "accepted", answer
    assert client.get(f"/api/work-items/{conflict['workItemId']}").json()["state"] == "resolved"
    settled = resolve(client, "V-501", "position")
    assert settled["status"] == "known" and settled["value"] == "open" and settled["attestationId"] == answer["attestationId"]
    # a disagreeing reading from another source after the clarification is a new conflict again
    service.write_fact("myer-plant", valve, "position", "reading", "closed", None, iso(datetime.now(timezone.utc) + timedelta(seconds=30)),
                       {"kind": "agent", "ref": "later"}, [], ["9" * 64])
    assert resolve(client, "V-501", "position")["status"] == "conflict"
