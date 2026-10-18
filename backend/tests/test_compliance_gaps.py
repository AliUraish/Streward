"""Contract 7 §6: compliance is never 100 %. Every site carries seeded gaps (Myer one overdue, Bristol and Tomioka one
overdue and one blocked) on real assets, owned by the site's crew, citing the site's own regulation pack, past due, with
an open compliance issue each; the versioned seed migration brings them to existing databases once; and the drift lets the
next obligation fall due when the agents have closed every gap at a site, at most once per site per two hours. Every
external transport is off; nothing leaves the machine."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.service import PropertyService

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
JURISDICTION = {MY: "VIC-AU", BR: "ENG-UK", TM: "JP"}
EXPECTED = {MY: {"overdue": 1, "blocked": 0}, BR: {"overdue": 1, "blocked": 1}, TM: {"overdue": 1, "blocked": 1}}
GAP_IDS = {"ob-my-l901-esm", "ob-br-sp102-pipework", "ob-br-v504-gland", "ob-tm-exit-drill", "ob-tm-tr202-strap"}
GAP_KINDS = ("compliance_overdue", "compliance_blocked")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def obligations(client, site):
    return {o["id"]: o for o in client.get(f"/api/properties/{site}/obligations").json()}


def gap_issues(client, site, status="open"):
    return [i for i in client.get(f"/api/properties/{site}/issues?status={status}").json() if i["kind"] in GAP_KINDS]


def test_every_site_carries_real_gaps_with_open_compliance_issues(client):
    regulations = {r["id"]: r for r in client.get("/api/regulations?include=comparison").json()}
    moment = datetime.now(timezone.utc)
    for site, expected in EXPECTED.items():
        records = obligations(client, site)
        crew = {c["id"] for c in client.get(f"/api/properties/{site}/crew").json()}
        tags = {c["tag"] for c in client.get(f"/api/properties/{site}/components").json()}
        gaps = [o for o in records.values() if o["status"] in ("overdue", "blocked")]
        assert {status: sum(o["status"] == status for o in gaps) for status in ("overdue", "blocked")} == expected
        issues = {i["obligationId"]: i for i in gap_issues(client, site)}
        assert set(issues) == {o["id"] for o in gaps} <= GAP_IDS
        for obligation in gaps:
            assert obligation["assetTag"] in tags and obligation["ownerId"] in crew and obligation["synthetic"] is True
            assert obligation["title"] and obligation["frequency"] and "DEMO-RP" in obligation["ruleRef"]
            cited = obligation["regulationIds"]
            assert cited and not obligation.get("unresolvedRegulationIds") and obligation["regulationPending"] is False
            assert all(regulations[r]["jurisdiction"] == JURISDICTION[site] and regulations[r]["binding"] is True for r in cited)  # never US-CA
            days = (moment - parse(obligation["dueAt"])).days
            assert days >= 6
            if obligation["status"] == "blocked":
                assert obligation["blockedBy"] and obligation["blockedReason"]
            issue = issues[obligation["id"]]
            assert issue["status"] == "open" and issue["kind"] == ("compliance_blocked" if obligation["status"] == "blocked" else "compliance_overdue")
            assert issue["severity"] == ("high" if days > 7 else "medium") and issue["source"] == "agent" and issue["synthetic"] is True
            assert issue["assetTag"] == obligation["assetTag"] and issue["regulationIds"] == cited and issue["ownerId"] == obligation["ownerId"]
            assert issue["id"] == f"iss-{site[:2]}-compliance-{obligation['id']}"  # the id the walkthrough's alert workflow reuses
            assert "synthetic" not in issue["summary"].lower() and "demo" not in issue["summary"].lower()
    blocked = obligations(client, BR)["ob-br-v504-gland"]
    assert blocked["blockedBy"].startswith("Contractor slot") and "three weeks" in blocked["blockedReason"]
    assert obligations(client, TM)["ob-tm-tr202-strap"]["blockedBy"].startswith("Heritage consent")
    summary = client.get("/api/metrics/summary").json()["sites"]
    assert [s["siteId"] for s in summary] == [MY, BR, TM] and all(s["compliancePct"] < 100 for s in summary)
    drift = client.get("/api/compliance/drift").json()
    assert drift["version"] == "1" and all(s["compliancePct"] < 100 and s["gaps"] for s in drift["sites"])


def test_the_seed_migration_reaches_an_existing_database_once(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "before-gaps"
    first = PropertyService(directory, start_workers=False)
    assert first.compliance_gaps.migration["added"] == []  # a fresh database loads the gaps with the other obligations
    assert len(first.compliance_gaps.migration["issues"]) == 5
    first.close()
    with sqlite3.connect(directory / "steward.sqlite3") as db:  # the database as it was before the gaps existed
        for obligation_id in GAP_IDS:
            db.execute("DELETE FROM records WHERE kind='obligation' AND id=?", (obligation_id,))
        db.execute("DELETE FROM records WHERE kind='issue' AND (body LIKE '%compliance_overdue%' OR body LIKE '%compliance_blocked%')")
        db.execute("DELETE FROM meta WHERE key='steward_compliance_gaps_version'")
    upgraded = PropertyService(directory, start_workers=False)
    store = upgraded.store
    assert sorted(upgraded.compliance_gaps.migration["added"]) == sorted(GAP_IDS) and len(upgraded.compliance_gaps.migration["issues"]) == 5
    statuses = {o["id"]: o["status"] for site in (MY, BR, TM) for o in store.all("obligation", site) if o["id"] in GAP_IDS}
    assert statuses == {"ob-my-l901-esm": "overdue", "ob-br-sp102-pipework": "overdue", "ob-br-v504-gland": "blocked",
                        "ob-tm-exit-drill": "overdue", "ob-tm-tr202-strap": "blocked"}
    moment = datetime.now(timezone.utc)
    l901 = store.get("obligation", "ob-my-l901-esm", MY)
    assert timedelta(days=8, hours=23) < moment - parse(l901["dueAt"]) < timedelta(days=9, hours=1)  # relative to the migration
    counts = {site: len(store.all("obligation", site)) for site in (MY, BR, TM)}
    assert counts == {MY: 6, BR: 7, TM: 7}
    issues = [i for i in store.all("issue") if i["kind"] in GAP_KINDS]
    history = {i["id"]: len(i["history"]) for i in issues}
    assert len(issues) == 5 and all(i["status"] == "open" for i in issues)
    upgraded.close()
    again = PropertyService(directory, start_workers=False)
    assert again.compliance_gaps.migration == {}
    assert {site: len(again.store.all("obligation", site)) for site in (MY, BR, TM)} == counts
    assert {i["id"]: len(i["history"]) for i in again.store.all("issue") if i["kind"] in GAP_KINDS} == history  # nothing raised twice
    again.close()


def test_the_drift_reopens_a_gap_when_the_agents_close_them_all_at_most_every_two_hours(client):
    service = svc(client)
    gaps = service.compliance_gaps
    assert gaps.tick() == []  # every site still has a gap
    service.people.complete_obligation("ob-my-l901-esm", "myer-compliance", note="Discharge test passed; logbook signed.")
    remaining = obligations(client, MY)
    assert all(o["status"] in ("ok", "due_soon") for o in remaining.values())
    upcoming = sorted(remaining.values(), key=lambda o: o["dueAt"])[0]
    start = datetime.now(timezone.utc)
    drifted = gaps.tick(start)
    assert [d["siteId"] for d in drifted] == [MY] and drifted[0]["obligationId"] == upcoming["id"]
    closed = client.get("/api/issues/iss-my-compliance-ob-my-l901-esm").json()
    assert closed["status"] == "resolved"  # the closed gap's issue is resolved by the same pass
    record = obligations(client, MY)[upcoming["id"]]
    assert record["status"] == "overdue" and drifted[0]["reason"] in record["note"]
    assert record["driftReason"] == drifted[0]["reason"] and record["previousDueAt"] == upcoming["dueAt"]
    assert timedelta(minutes=55) < datetime.now(timezone.utc) - parse(record["dueAt"]) < timedelta(minutes=65)
    assert drifted[0]["reason"] in ("the permit renewal was not filed in time", "the monthly check sheet was not signed off",
                                    "the contractor's service report is late", "the contractor's visit slipped", "the inspection report is late")
    issue = next(i for i in gap_issues(client, MY) if i["obligationId"] == upcoming["id"])
    assert issue["kind"] == "compliance_overdue" and issue["severity"] == "medium" and issue["complianceGap"]["origin"] == "drift"
    assert drifted[0]["reason"] in issue["summary"]
    changes = client.get(f"/api/properties/{MY}/changes?limit=1000").json()["changes"]
    assert any(c["type"] == "obligation" and c["refId"] == upcoming["id"] and "fell due" in c["summary"] for c in changes)
    assert [s for s in (BR, TM) if any(d["siteId"] == s for d in drifted)] == []  # the other sites still had gaps
    service.people.complete_obligation(upcoming["id"], "myer-compliance", note="Closed again by the agents.")
    assert gaps.tick(start + timedelta(minutes=30)) == []  # paced: once per site per two hours
    assert not gap_issues(client, MY) and all(o["status"] in ("ok", "due_soon") for o in obligations(client, MY).values())
    later = gaps.tick(start + timedelta(hours=2, minutes=1))
    assert [d["siteId"] for d in later] == [MY]
    assert any(o["status"] == "overdue" for o in obligations(client, MY).values()) and len(gap_issues(client, MY)) == 1
    status = client.get("/api/compliance/drift").json()
    myer = next(s for s in status["sites"] if s["siteId"] == MY)
    assert myer["lastDriftAt"] and myer["compliancePct"] < 100 and status["recent"][0]["siteId"] == MY
