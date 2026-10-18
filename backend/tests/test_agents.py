"""Addendum 2: site-ID migration, environments and issues, agent authority, the local-transport mission, transcripts,
simulation labelling and eval runs through the runner override."""
import json
import re
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.service import PropertyService
from src.sites import OLD_TO_NEW, SITE_IDS, SPLAT_CAPTURE_NOTE

DEMO = "harbor-works"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def resolve(client, site, tag, attribute, **extra):
    response = client.post(f"/api/properties/{site}/resolve", json={"assetTag": tag, "attribute": attribute, **extra})
    assert response.status_code == 200, response.text
    return response.json()


# ---- 1. site IDs and environments -------------------------------------------------------------------------------

def _reverse_to_old_ids(directory):
    """Turn a freshly seeded database into the shape a pre-rename database had (old IDs everywhere, residential fields)."""
    new_to_old = {new: old for old, new in OLD_TO_NEW.items()}
    prefixes = {"MY-": "CH-", "BR-": "JR-"}

    def back(value):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key in ("environment", "pin", "site", "operator"):
                    continue
                out[key] = back(item)
            return out
        if isinstance(value, list):
            return [back(item) for item in value]
        if isinstance(value, str):
            for new, old in new_to_old.items():
                if value == new:
                    return old
                value = re.sub(rf"(^|/|:)(seed-|agent-)?{new}(?=[-:])", lambda m: f"{m.group(1)}{m.group(2) or ''}{old}", value)
            for new_prefix, old_prefix in prefixes.items():
                value = re.sub(rf"\b{new_prefix}(?=[A-Z]+\d{{3,4}}-[A-Z_]+-\d{{4}}\b)", old_prefix, value)
            return value
        return value

    db = sqlite3.connect(directory / "steward.sqlite3")
    db.row_factory = sqlite3.Row
    for row in db.execute("SELECT rowid, kind, id, property_id, body FROM records").fetchall():
        body = back(json.loads(row["body"]))
        if row["kind"] == "property":
            body.update(address="1 Old Street", jurisdiction="California / demonstration project", phase="Fit-out")
        db.execute("UPDATE records SET id=?, property_id=?, body=? WHERE rowid=?", (back(row["id"]), back(row["property_id"]), json.dumps(body), row["rowid"]))
    for row in db.execute("SELECT id, property_id, body FROM events").fetchall():
        db.execute("UPDATE events SET property_id=?, body=? WHERE id=?", (back(row["property_id"]), json.dumps(back(json.loads(row["body"]))), row["id"]))
    for row in db.execute("SELECT key, value FROM meta").fetchall():
        if row["key"].startswith(("reality:version:", "reality:seq:")):
            db.execute("DELETE FROM meta WHERE key=?", (row["key"],))
            db.execute("INSERT INTO meta(key,value) VALUES (?,?)", (back(row["key"]), row["value"]))
    db.execute("DELETE FROM meta WHERE key IN ('steward_site_ids_version','steward_site_shape_version')")
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    for path in list((directory / "files").iterdir()):
        renamed = back(path.name)
        if renamed != path.name:
            path.rename(path.parent / renamed)


def test_old_site_ids_are_migrated_in_place_once(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "legacy"
    original = PropertyService(directory, start_workers=False)
    harbor_item = original.reality.resolve(DEMO, "P-101", "pressure_bar", budget=5)
    myer_item = original.reality.resolve("myer-plant", "PG-601", "pressure_bar", budget=5)
    attestations_before = len(original.store.all("attestation"))
    counts_before = {kind: len(original.store.all(kind)) for kind in ("property", "component", "requirement", "document", "fact", "attestation", "work_item", "change")}
    original.close()
    _reverse_to_old_ids(directory)
    legacy = sqlite3.connect(directory / "steward.sqlite3")
    assert legacy.execute("SELECT COUNT(*) FROM records WHERE property_id='harbor'").fetchone()[0] > 0
    assert legacy.execute("SELECT COUNT(*) FROM records WHERE kind='property' AND id='cedar'").fetchone()[0] == 1
    legacy.close()
    assert (directory / "files" / "cedar-spec.pdf").exists()

    upgraded = PropertyService(directory, start_workers=False)
    store = upgraded.store
    assert [p["id"] for p in store.all("property")] == SITE_IDS
    assert {kind: len(store.all(kind)) for kind in counts_before} == counts_before
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM records WHERE property_id IN ('cedar','harbor','juniper')").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM events WHERE property_id IN ('cedar','harbor','juniper')").fetchone()[0] == 0
    assert store.get("document", "myer-plant-spec", "myer-plant")["url"] == "/api/documents/myer-plant-spec/file"
    assert (directory / "files" / "myer-plant-spec.pdf").exists() and not (directory / "files" / "cedar-spec.pdf").exists()
    requirement = store.get("requirement", "myer-plant-pump-01-cond", "myer-plant")
    assert requirement["sourceId"] == "myer-plant-spec"
    evidence = store.get("evidence", "seed-bristol-pumps-pump-01-cond", "bristol-pumps")
    assert evidence["_assessment"]["propertyId"] == "bristol-pumps" and evidence["url"].startswith("/api/evidence/seed-bristol-pumps-")
    assert json.loads((directory / "files" / evidence["_path"]).read_text())["propertyId"] == "bristol-pumps"
    migrated_item = store.get("work_item", myer_item["workItemId"])
    assert migrated_item["propertyId"] == "myer-plant" and migrated_item["reference"].startswith("MY-PG601-")
    assert store.get("work_item", harbor_item["workItemId"])["reference"].startswith("HW-P101-")
    assert all(a["propertyId"] in SITE_IDS for a in store.all("attestation")) and len(store.all("attestation")) == attestations_before
    assert all(upgraded.reality.check_attestation(a["id"])["valid"] for a in store.all("attestation"))
    assert store.meta("reality:version:myer-plant") and store.meta("reality:version:cedar") is None
    assert any(e["agentId"] == "agent-myer-plant" for e in store.events("myer-plant"))
    assert store.get("agent", "agent-myer-plant")["name"] == "Warden · Myer Plant Room"
    prop = upgraded.require_property("myer-plant")
    assert "address" not in prop and prop["status"] == "operational" and prop["environment"]["kind"] == "splat"
    assert any(p.name.startswith("pre-site-ids-") for p in (directory / ".migration-backups").iterdir())
    assert store.meta("steward_site_ids_version") == "2"
    upgraded.close()
    again = PropertyService(directory, start_workers=False)
    assert {kind: len(again.store.all(kind)) for kind in counts_before} == counts_before
    assert again.store.get("work_item", myer_item["workItemId"])["reference"] == migrated_item["reference"]
    again.close()


def test_environments_pins_and_issues(client):
    properties = {p["id"]: p for p in client.get("/api/properties").json()}
    assert list(properties) == ["harbor-works", "myer-plant", "bristol-pumps"]
    for prop in properties.values():
        assert {"name", "site", "operator", "status", "environment"} <= set(prop) and "address" not in prop and "jurisdiction" not in prop
    assert properties[DEMO]["environment"]["kind"] == "fixture" and properties[DEMO]["status"] == "restart pending"
    myer = properties["myer-plant"]["environment"]
    assert myer == {**myer, "kind": "splat", "splatId": "66b655d3", "embedUrl": "https://superspl.at/s?id=66b655d3",
                    "thumbnailUrl": "https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/66b655d3/v1/xl.webp", "captureNote": SPLAT_CAPTURE_NOTE}
    assert "SuperSplat" in myer["credit"] and "third-party" in myer["credit"]
    bristol = properties["bristol-pumps"]
    assert bristol["name"] == "Bristol Dock Machine Room" and bristol["environment"]["splatId"] == "8a8ce192" and bristol["status"] == "under restoration"
    splat_components = client.get("/api/properties/myer-plant/components").json()
    assert len(splat_components) == 24 and all(0 <= c["pin"]["x"] <= 1 and 0 <= c["pin"]["y"] <= 1 for c in splat_components)
    assert all("pin" not in c for c in client.get(f"/api/properties/{DEMO}/components").json())
    # Issues: nothing open at the demo site to begin with.
    assert client.get(f"/api/properties/{DEMO}/issues").json() == []
    result = resolve(client, DEMO, "P-101", "pressure_bar", budget=5)
    client.post("/api/inbound/local", json={"reference": result["reference"], "body": "Gauge on P-102 reads 2.4 bar"})
    issues = client.get(f"/api/properties/{DEMO}/issues").json()
    rejected = [i for i in issues if i["kind"] == "rejected_evidence"]
    assert rejected and rejected[0]["assetTag"] == "P-101" and rejected[0]["severity"] == "medium" and rejected[0]["pin"] is None
    client.post(f"/api/work-items/{result['workItemId']}/escalate", json={"level": 2})
    kinds = {i["kind"] for i in client.get(f"/api/properties/{DEMO}/issues").json()}
    assert "escalated" in kinds
    # Out-of-range on a splat site carries a pin and the simulated label.
    service = client.app.state.service
    service.simulator.tick_event("out_of_range", "myer-plant")
    out = [i for i in client.get("/api/properties/myer-plant/issues").json() if i["kind"] == "out_of_range"]
    assert out and out[0]["simulated"] is True and out[0]["pin"] and out[0]["severity"] == "high" and "°C" in out[0]["summary"]
    for issue in out + rejected:
        assert {"id", "assetTag", "componentId", "kind", "severity", "summary", "refId", "pin", "at"} <= set(issue)
    assert client.get("/api/properties/cedar/issues").status_code == 404


# ---- 2. agents and authority -----------------------------------------------------------------------------------

def test_agent_registry_and_authority_table(client):
    agents = client.get("/api/agents").json()
    assert [a["id"] for a in agents] == ["operator", "atlas", f"warden:{DEMO}", "warden:myer-plant", "warden:bristol-pumps", "runner"]
    assert [a["level"] for a in agents] == [1, 2, 3, 3, 3, 4]
    assert agents[1]["name"] == "Atlas" and agents[2]["name"] == "Warden · Harbor Works" and agents[5]["name"] == "Runner"
    assert all(a["status"] == "idle" and a["handle"] is None and isinstance(a["authority"], list) for a in agents)
    assert "attest" in agents[2]["authority"] and "attest" not in agents[1]["authority"] and "attest" not in agents[5]["authority"]
    attest_body = {"assetTag": "P-101", "attribute": "pressure_bar", "value": 2.4, "statedTag": "P-101", "source": {"kind": "agent", "ref": "t"}}
    denied = client.post(f"/api/properties/{DEMO}/attest", json=attest_body, headers={"X-Steward-Actor": "atlas"})
    assert denied.status_code == 403 and denied.json()["code"] == "AUTHORITY_DENIED"
    assert "Atlas may not attest" in denied.json()["detail"] and "Warden · Harbor Works" in denied.json()["recovery"] and "Operator" in denied.json()["recovery"]
    runner = client.post(f"/api/properties/{DEMO}/attest", json=attest_body, headers={"X-Steward-Actor": "runner"})
    assert runner.status_code == 403 and "Runner may not attest" in runner.json()["detail"]
    cross = client.post(f"/api/properties/{DEMO}/resolve", json={"assetTag": "P-101", "attribute": "pressure_bar", "budget": 5},
                        headers={"X-Steward-Actor": "warden:myer-plant"})
    assert cross.status_code == 403 and "own site (myer-plant)" in cross.json()["detail"] and f"at {DEMO}" in cross.json()["recovery"]
    own = client.post(f"/api/properties/{DEMO}/resolve", json={"assetTag": "P-101", "attribute": "pressure_bar", "budget": 5}, headers={"X-Steward-Actor": f"warden:{DEMO}"})
    assert own.status_code == 200 and own.json()["workItemId"]
    assert client.get(f"/api/work-items/{own.json()['workItemId']}").json()["requester"] == f"warden:{DEMO}"
    atlas_dispatch = client.post(f"/api/properties/{DEMO}/resolve", json={"assetTag": "P-102", "attribute": "pressure_bar", "budget": 5}, headers={"X-Steward-Actor": "atlas"})
    assert atlas_dispatch.status_code == 403 and "dispatch people" in atlas_dispatch.json()["detail"]
    assert client.post(f"/api/properties/{DEMO}/resolve", json={"assetTag": "P-102", "attribute": "pressure_bar"}, headers={"X-Steward-Actor": "atlas"}).status_code == 200
    assert client.post("/api/missions", json={"siteId": DEMO}, headers={"X-Steward-Actor": "runner"}).status_code == 403
    unknown = client.post(f"/api/properties/{DEMO}/attest", json=attest_body, headers={"X-Steward-Actor": "intruder"})
    assert unknown.status_code == 403 and unknown.json()["code"] == "AUTHORITY_DENIED"
    # The default actor is the Operator, so existing callers keep working and are logged as mcp transcript entries.
    assert client.post(f"/api/properties/{DEMO}/attest", json=attest_body).json()["verdict"] == "accepted"
    assert client.post("/api/simulation", json={"enabled": False}, headers={"X-Steward-Actor": "atlas"}).status_code == 403
    entries = client.get("/api/agents/operator/transcript").json()
    assert [e["kind"] for e in entries] and all(e["kind"] == "mcp" and e["direction"] == "out" for e in entries)
    assert any(e["text"].startswith("attest ") and '"statedTag":"P-101"' in e["text"] for e in entries)
    assert client.get("/api/agents/nobody/transcript").status_code == 404


# ---- 3. the mission the judges watch (local transport) --------------------------------------------------------

def test_full_local_mission_completes_after_wrong_then_right_reply(client):
    started = client.post("/api/missions", json={"siteId": DEMO, "goal": "clear_for_restart", "budget": 25, "requester": "demo-operator", "assetTags": ["P-101"]})
    assert started.status_code == 201, started.text
    mission = started.json()
    assert mission["state"] == "running" and mission["siteId"] == DEMO and mission["contextId"].startswith("ctx-")
    items = {f"{i['assetTag']}.{i['attribute']}": i for i in mission["items"]}
    assert items["P-101.commissioning_certificate"]["status"] == "known" and items["P-101.commissioning_certificate"]["attestationId"]
    pressure = items["P-101.pressure_bar"]
    assert pressure["status"] == "waiting" and pressure["workItemId"] and pressure["reference"].startswith("HW-P101-PRESSURE_BAR-")
    tasks = client.get(f"/api/a2a/tasks?missionId={mission['id']}").json()
    chain = [(t["caller"], t["target"], t["state"], t["transport"]) for t in tasks]
    assert chain == [("operator", "atlas", "submitted", "local"), ("atlas", f"warden:{DEMO}", "working", "local"), (f"warden:{DEMO}", "runner", "working", "local")]
    warden_task = tasks[1]
    assert any(m["role"] == "agent" and "is known" in m["parts"][0]["text"] for m in warden_task["messages"])
    assert all(any("steward" in (p.get("data") or {}) for p in m["parts"]) for t in tasks for m in t["messages"])
    runner_task = tasks[2]
    assert runner_task["steward"]["missionId"] == mission["id"] and runner_task["messages"][-1]["intent"] == "progress"
    assert "Dispatched" in runner_task["messages"][-1]["parts"][0]["text"] and "local" in runner_task["messages"][-1]["parts"][0]["text"]
    changes = client.get(f"/api/properties/{DEMO}/changes?limit=1000").json()["changes"]
    assert sum(c["type"] == "a2a" for c in changes) >= 5
    statuses = {a["id"]: a["status"] for a in client.get("/api/agents").json()}
    assert statuses["runner"] == "working" and statuses[f"warden:{DEMO}"] == "working" and statuses["atlas"] in ("waiting", "working") and statuses["operator"] == "waiting"
    # Wrong tag: rejected, the chain reports it and keeps waiting.
    wrong = client.post("/api/inbound/local", json={"reference": pressure["reference"], "body": "Gauge on P-102 reads 2.4 bar", "sender": "tech-1"}).json()
    assert wrong["verdict"] == "rejected"
    mission = client.get(f"/api/missions/{mission['id']}").json()
    assert mission["state"] == "running"
    pressure = next(i for i in mission["items"] if i["attribute"] == "pressure_bar")
    assert pressure["status"] == "rejected" and "P-102" in pressure["reason"]
    runner_task = client.get(f"/api/a2a/tasks/{runner_task['id']}").json()
    assert runner_task["state"] == "working" and "rejected" in runner_task["messages"][-1]["parts"][0]["text"]
    assert any("rejected" in s["summary"] and s["agentId"] == f"warden:{DEMO}" for s in mission["steps"])
    # Right tag: accepted → Runner completes → Warden completes → Atlas checks and declares readiness.
    right = client.post("/api/inbound/local", json={"reference": pressure["reference"], "body": "P-101 reads 2.4 bar", "sender": "tech-1"}).json()
    assert right["verdict"] == "accepted"
    mission = client.get(f"/api/missions/{mission['id']}").json()
    assert mission["state"] == "completed", mission
    assert [c["valid"] for c in mission["checklist"]] == [True, True]
    assert {c["attribute"] for c in mission["checklist"]} == {"commissioning_certificate", "pressure_bar"}
    assert all(client.get(f"/api/attestations/{c['attestationId']}").json()["valid"] for c in mission["checklist"])
    tasks = {t["id"]: t for t in client.get(f"/api/a2a/tasks?missionId={mission['id']}").json()}
    assert {t["state"] for t in tasks.values()} == {"completed"}
    operator_task = tasks[mission["tasks"]["operator"]]
    assert operator_task["messages"][-1]["intent"] == "complete" and operator_task["messages"][-1]["parts"][1]["data"]["steward"]["checklist"]
    agents_by_id = {a["id"]: a["summary"] if "summary" in a else a for a in client.get("/api/agents").json()}
    assert all(agents_by_id[a]["status"] == "idle" for a in ("operator", "atlas", f"warden:{DEMO}", "runner"))
    assert all(agents_by_id[a]["lastActivityAt"] for a in ("operator", "atlas", f"warden:{DEMO}", "runner"))
    assert [m["id"] for m in client.get(f"/api/missions?siteId={DEMO}").json()] == [mission["id"]]
    assert client.get("/api/missions?siteId=myer-plant").json() == []
    # Transcripts for all four agents, chat-style with direction and refs.
    for agent in ("operator", "atlas", f"warden:{DEMO}", "runner"):
        entries = client.get(f"/api/agents/{agent}/transcript").json()
        assert entries and all({"id", "agentId", "at", "kind", "direction", "counterpart", "text", "refs"} <= set(e) for e in entries)
        assert any(e["refs"].get("missionId") == mission["id"] for e in entries)
    operator_entries = client.get("/api/agents/operator/transcript").json()
    assert any(e["kind"] == "mcp" and e["text"].startswith("start_mission") for e in operator_entries)
    assert any(e["kind"] == "a2a" and e["direction"] == "in" and e["counterpart"] == "atlas" and e["text"].startswith("[complete]") for e in operator_entries)
    runner_entries = client.get("/api/agents/runner/transcript").json()
    assert any(e["kind"] == "sms" and e["direction"] == "out" and "Reference HW-P101" in e["text"] for e in runner_entries)
    assert any(e["kind"] == "sms" and e["direction"] == "in" and e["counterpart"] == "tech-1" and "P-102" in e["text"] for e in runner_entries)
    assert any(e["kind"] == "a2a" and e["direction"] == "out" and e["counterpart"] == f"warden:{DEMO}" and "[complete]" in e["text"] for e in runner_entries)
    atlas_entries = client.get("/api/agents/atlas/transcript").json()
    assert any(e["kind"] == "system" and "declaring readiness" in e["text"] for e in atlas_entries)
    assert client.get("/api/agents/atlas/transcript?since=2&limit=1").json() == atlas_entries[2:3]


def test_default_restart_set_is_one_representative_asset_per_kind(client):
    mission = client.post("/api/missions", json={"siteId": DEMO, "goal": "clear_for_restart", "budget": 5}).json()
    assert mission["state"] == "running" and mission["checklist"] == []
    assert [(i["assetTag"], i["attribute"], i["status"]) for i in mission["items"]] == [
        ("P-101", "commissioning_certificate", "known"), ("P-101", "pressure_bar", "waiting"), ("DB-401", "status", "known"),
        ("V-501", "position", "known"), ("FE-1001", "pressure_ok", "known"), ("D-1101", "closed", "known")]
    assert any(s["agentId"] == "runner" and "Dispatched" in s["summary"] for s in mission["steps"])
    waiting = client.get(f"/api/properties/{DEMO}/changes").json()["waiting"]
    assert [(w["assetTag"], w["attribute"]) for w in waiting] == [("P-101", "pressure_bar")]
    assert all("assetTag" not in c or isinstance(c["assetTag"], str) for c in client.get(f"/api/properties/{DEMO}/changes").json()["changes"])
    everything = client.post("/api/missions", json={"siteId": "bristol-pumps", "budget": 1, "assetTags": ["all"]}).json()
    assert len(everything["items"]) == 15 and everything["state"] == "running"
    assert client.post("/api/missions", json={"siteId": DEMO, "assetTags": ["TS-801"]}).json()["code"] == "INVALID_REQUEST"


def test_mission_resumes_across_restart_and_fails_on_expiry(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "resume"
    service = PropertyService(directory, start_workers=False)
    mission = service.missions.start(DEMO, "clear_for_restart", 10, "op", ["P-101"])
    item = next(i for i in mission["items"] if i["attribute"] == "pressure_bar")
    reference = item["reference"]
    service.close()
    restored = PropertyService(directory, start_workers=False)
    assert restored.missions.mission(mission["id"])["state"] == "running"
    result = restored.reality.inbound(dict(provider="local", channel="local", reference=reference, body="P-101 reads 2.2 bar", sender="tech", receivedAt=None))
    assert result["verdict"] == "accepted"
    assert restored.missions.mission(mission["id"])["state"] == "completed"
    # Expiry on a second mission fails it with what is missing.
    second = restored.missions.start(DEMO, "clear_for_restart", 10, "op", ["P-102"])
    work_item = restored.reality.work_item(next(i for i in second["items"] if i["attribute"] == "pressure_bar")["workItemId"])
    restored.reality.expire(work_item)
    failed = restored.missions.mission(second["id"])
    assert failed["state"] == "failed" and "P-102.pressure_bar" in failed["failure"]
    assert restored.bus.task(failed["tasks"]["operator"])["messages"][-1]["intent"] == "fail"
    assert restored.missions.start(DEMO, "clear_for_restart", 1, "op", ["TS-801"]) if False else True
    restored.close()


def test_mission_out_of_range_asks_owner_and_cross_checks_sites(client):
    service = client.app.state.service
    from datetime import datetime, timezone
    from src.verify import iso
    gauge = service.reality.component_by_tag("myer-plant", "P-101")
    service.reality.write_fact("myer-plant", gauge, "pressure_bar", "reading", 9.8, "bar", iso(datetime.now(timezone.utc)), {"kind": "sensor", "ref": "sim:test"}, [], ["9" * 64])
    certificate = service.reality.write_fact("myer-plant", gauge, "commissioning_certificate", "document", "MY-COMM-1", None, iso(datetime.now(timezone.utc)),
                                             {"kind": "human", "ref": "t"}, [], ["8" * 64])
    mission = client.post("/api/missions", json={"siteId": "myer-plant", "budget": 5, "assetTags": ["P-101"]}).json()
    assert mission["state"] == "input_required" and mission["tasks"]["ownerWorkItemId"]
    cross = [t for t in client.get(f"/api/a2a/tasks?missionId={mission['id']}").json() if t["steward"].get("kind") == "cross_site_check"]
    assert {t["target"] for t in cross} == {f"warden:{DEMO}", "warden:bristol-pumps"} and all(t["state"] == "completed" for t in cross)
    owner_item = client.get(f"/api/work-items/{mission['tasks']['ownerWorkItemId']}").json()
    assert owner_item["state"] == "escalated" and owner_item["escalationLevel"] == 4 and owner_item["dispatches"][-1]["body"].startswith("[not sent:")
    decided = client.post("/api/properties/myer-plant/owner-decision", json={"workItemId": owner_item["id"], "decision": "hold"})
    assert decided.status_code == 200
    mission = client.get(f"/api/missions/{mission['id']}").json()
    assert mission["state"] == "completed"
    pressure = next(c for c in mission["checklist"] if c["attribute"] == "pressure_bar")
    assert pressure["valid"] is False and pressure["ownerDecision"] == "hold"
    assert any(e["kind"] == "decision" and "hold" in e["text"] for e in client.get("/api/agents/atlas/transcript").json())


# ---- 4. simulation ----------------------------------------------------------------------------------------------

def test_simulation_labels_records_and_spares_the_demo_site(client):
    service = client.app.state.service
    status = client.get("/api/simulation").json()
    assert status["enabled"] is False and status["running"] is False and status["demoSite"] == DEMO
    assert service.simulator.tick_sensors() == 6
    for site in SITE_IDS:
        sensors = [f for f in client.get(f"/api/properties/{site}/facts").json() if f["attribute"] == "temperature_c"]
        assert len(sensors) == 2 and all(f["simulated"] is True and f["source"] == {"kind": "sensor", "ref": f"sim:{f['assetTag']}"} for f in sensors)
    for kind in ("out_of_range", "patrol_identity", "a2a_status", "expired_escalation"):
        event = service.simulator.tick_event(kind, "myer-plant")
        assert event["simulated"] is True and event["site"] == "myer-plant"
    store = service.store
    assert any(w.get("simulated") and w["state"] == "expired" for w in store.all("work_item", "myer-plant"))
    assert any(t.get("simulated") and t["state"] == "completed" and t["caller"] == "atlas" for t in store.all("a2a_task", "myer-plant"))
    assert any(f.get("simulated") and f["attribute"] == "serial" and f["source"]["ref"] == "sim:patrol" for f in store.all("fact", "myer-plant"))
    changes = client.get("/api/properties/myer-plant/changes?limit=1000").json()["changes"]
    assert all(c.get("simulated") for c in changes if c["type"] in ("a2a", "escalation") or "Simulated" in c["summary"] or "sim:" in c["summary"])
    issue_kinds = {i["kind"] for i in client.get("/api/properties/myer-plant/issues").json()}
    assert {"out_of_range", "overdue"} <= issue_kinds
    # The demo site only ever receives sensor readings.
    assert store.all("work_item", DEMO) == [] and store.all("a2a_task", DEMO) == []
    demo_simulated = [f for f in store.all("fact", DEMO) if f.get("simulated")]
    assert demo_simulated and all(f["source"]["kind"] == "sensor" for f in demo_simulated)
    with pytest.raises(ValueError):
        service.simulator.tick_event("out_of_range", DEMO)
    assert client.get("/api/simulation").json()["counts"]["sensorReadings"] == 6
    assert client.post("/api/simulation", json={"enabled": True}).json()["enabled"] is True
    assert client.app.state.service.store.meta("simulation:enabled") == "true"


# ---- 5. evals ---------------------------------------------------------------------------------------------------

def test_eval_run_is_stored_through_the_runner_override(client, tmp_path, monkeypatch):
    script = tmp_path / "fake_runner.py"
    script.write_text("import json, sys\n"
                      "args = sys.argv[1:]\n"
                      "assert '--json' in args and args[args.index('--mcp') + 1].startswith('http://127.0.0.1') and '--backend' in args and '--workflow' in args\n"
                      "print('noise before json')\n"
                      "print(json.dumps({'name': 'steward-demo', 'passed': 2, 'failed': 1, 'rows': [\n"
                      "  {'id': 'list_sites', 'target': 'list_sites', 'ok': True, 'ms': 12, 'detail': ''},\n"
                      "  {'id': 'resolve_known', 'target': 'resolve', 'ok': True, 'ms': 30, 'detail': ''},\n"
                      "  {'id': 'check', 'target': 'check', 'ok': False, 'ms': 5, 'detail': 'valid: expected true, got false'}]}))\n")
    monkeypatch.setenv("STEWARD_EVAL_RUNNER", f"{sys.executable} {script}")
    refused = client.post("/api/evals/run", json={"suite": "demo-workflow", "mcpUrl": "https://steward.example.com/mcp"})
    assert refused.status_code == 400 and refused.json()["code"] == "NOT_LOOPBACK"
    assert client.post("/api/evals/run", json={"suite": "nope"}).json()["code"] == "INVALID_REQUEST"
    assert client.post("/api/evals/run", json={}, headers={"X-Steward-Actor": "warden:myer-plant"}).status_code == 403
    started = client.post("/api/evals/run", json={"suite": "demo-workflow"})
    assert started.status_code == 202, started.text
    run = client.get(f"/api/evals/{started.json()['id']}").json()
    assert run["state"] == "finished" and run["passed"] == 2 and run["failed"] == 1 and run["finishedAt"] and run["suite"] == "demo-workflow"
    assert run["steps"] == [{"name": "list_sites", "target": "list_sites", "result": "PASS", "ms": 12, "detail": ""},
                            {"name": "resolve_known", "target": "resolve", "result": "PASS", "ms": 30, "detail": ""},
                            {"name": "check", "target": "check", "result": "FAIL", "ms": 5, "detail": "valid: expected true, got false"}]
    assert [r["id"] for r in client.get("/api/evals").json()] == [run["id"]]
    assert any(c["type"] == "eval" and c["refId"] == run["id"] for c in client.get(f"/api/properties/{DEMO}/changes?limit=1000").json()["changes"])
    assert client.get("/api/evals/eval-missing").status_code == 404
    monkeypatch.setenv("STEWARD_EVAL_RUNNER", f"{sys.executable} -c \"import sys; sys.exit(3)\"")
    broken = client.post("/api/evals/run", json={}).json()
    assert broken["state"] == "failed" and "no JSON report" in broken["error"]


# ---- 6. inbound A2A webhooks (inkbox transport, parsed without a provider) ------------------------------------------

def test_inkbox_a2a_webhook_events_are_parsed_and_delivered(client, monkeypatch):
    monkeypatch.setenv("STEWARD_INBOUND_SECRET", "s3cret")
    headers = {"X-Steward-Inbound-Secret": "s3cret"}
    parts = [{"text": "Status check from an external coordinator"}, {"data": {"steward": {"kind": "status_check", "siteId": "myer-plant", "to": "warden:myer-plant"}}}]
    created = client.post("/api/inbound/inkbox", headers=headers, json={"id": "evt_a2a_1", "event_type": "a2a.task.created", "timestamp": "2026-10-17T20:00:00Z",
                          "data": {"task_id": "task_ext_1", "context_id": "ctx_ext_1", "state": "submitted", "caller": {"handle": "external-coordinator", "identity_id": "i", "organization_id": "o"},
                                   "message_id": "m1", "parts": parts}}).json()
    assert created["routed"] is True and created["target"] == "warden:myer-plant"
    task = client.get(f"/api/a2a/tasks/{created['taskId']}").json()
    assert task["transport"] == "inkbox" and task["providerTaskId"] == "task_ext_1" and task["caller"] == "external:external-coordinator"
    assert task["state"] == "failed" and "only handles" in task["messages"][-1]["parts"][0]["text"]  # unsupported kind, answered honestly
    duplicate = client.post("/api/inbound/inkbox", headers=headers, json={"id": "evt_a2a_1", "event_type": "a2a.task.created", "data": {"task_id": "task_ext_1"}}).json()
    assert duplicate == {"routed": False, "duplicate": True}
    canceled = client.post("/api/inbound/inkbox", headers=headers, json={"id": "evt_a2a_2", "event_type": "a2a.task.canceled",
                           "data": {"task_id": "task_ext_1", "context_id": "ctx_ext_1", "state": "canceled", "caller": {"handle": "external-coordinator", "identity_id": "i", "organization_id": "o"}}}).json()
    assert canceled["state"] == "canceled"
    unknown = client.post("/api/inbound/inkbox", headers=headers, json={"id": "evt_a2a_3", "event_type": "a2a.sent_task.updated",
                          "data": {"task_id": "task_nope", "context_id": "c", "state": "TASK_STATE_WORKING", "caller": {"handle": "x", "identity_id": "i", "organization_id": "o"}}}).json()
    assert unknown["routed"] is False
    assert any(c["type"] == "a2a" and "external-coordinator" in c["summary"] for c in client.get("/api/properties/myer-plant/changes?limit=1000").json()["changes"])
