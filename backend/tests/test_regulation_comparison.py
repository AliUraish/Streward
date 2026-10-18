"""Binding law and comparison records: a US-CA record (`binding: false`, `comparisonFor`) is listed only on request and is
shown beside an issue's reasons, never as the reason the issue is a breach."""
import json

import pytest
from fastapi.testclient import TestClient

from src.main import create_app

BR = "bristol-pumps"
BINDING = {"id": "eng-whswr-1992-reg-12", "jurisdiction": "ENG-UK", "siteIds": [BR], "instrument": "Workplace (Health, Safety and Welfare) Regulations 1992",
           "provision": "reg. 12", "title": "Condition of floors and traffic routes", "officialUrl": "https://www.legislation.gov.uk/uksi/1992/3004/regulation/12",
           "servePdf": False, "licence": "Open Government Licence v3.0", "summary": "Keep traffic routes free of slip hazards.",
           "appliesTo": ["br-sump", "sump_overflow"], "synthetic": False}
COMPARISON = {"id": "us-ca-ccr-8-3273", "jurisdiction": "US-CA", "binding": False, "comparisonFor": [BR], "siteIds": [BR],
              "instrument": "California Code of Regulations, Title 8", "provision": "§ 3273", "title": "Working areas (comparison)",
              "officialUrl": "https://www.dir.ca.gov/title8/3273.html", "servePdf": False, "licence": "Public domain (comparison only)",
              "summary": "California's equivalent duty to keep walking surfaces free of hazards.", "appliesTo": ["br-sump", "sump_overflow"],
              "comparesTo": ["eng-whswr-1992-reg-12"], "synthetic": False}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    path = tmp_path / "regulations.json"
    path.write_text(json.dumps([BINDING, COMPARISON, {**BINDING, "id": "unbound-default", "appliesTo": []}]))
    monkeypatch.setenv("STEWARD_REGULATIONS_FILE", str(path))
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def test_comparison_records_never_become_the_reason_for_a_breach(client):
    assert [r["id"] for r in client.get(f"/api/regulations?siteId={BR}").json()] == ["eng-whswr-1992-reg-12", "unbound-default"]
    both = client.get(f"/api/regulations?siteId={BR}&include=comparison").json()
    assert [r["id"] for r in both] == ["eng-whswr-1992-reg-12", "us-ca-ccr-8-3273", "unbound-default"]
    comparison = next(r for r in both if r["id"] == "us-ca-ccr-8-3273")
    assert comparison["binding"] is False and comparison["comparisonFor"] == [BR] and comparison["siteIds"] == [] and "never the reason" in comparison["comparisonNote"]
    assert all(r["binding"] is True for r in client.get("/api/regulations").json())  # a record without `binding` is binding
    response = client.post("/api/scenarios/br-sump/start", json={"speed": 0})
    assert response.status_code == 202 and response.json()["state"] == "completed"
    issue = next(i for i in client.get(f"/api/properties/{BR}/issues").json() if i["kind"] == "sump_overflow")
    page = client.get(f"/api/issues/{issue['id']}").json()
    assert page["regulationIds"] == ["eng-whswr-1992-reg-12"] and [w["regulationId"] for w in page["why"]] == ["eng-whswr-1992-reg-12"]
    assert page["comparisonRegulationIds"] == ["us-ca-ccr-8-3273"] and page["comparison"][0]["binding"] is False
    service = client.app.state.service
    assert "us-ca-ccr-8-3273" not in service.regulations.for_issue(issue)
    assert service.regulations.why(["us-ca-ccr-8-3273"]) == []  # never rendered as a reason, even when asked directly
    # An obligation that lists the comparison id cites only the binding one and shows the comparison beside it.
    obligation = service.store.get("obligation", "ob-br-walkway-check", BR)
    obligation["regulationIds"] = ["eng-whswr-1992-reg-12", "us-ca-ccr-8-3273"]
    service.store.put("obligation", obligation, BR)
    view = {o["id"]: o for o in client.get(f"/api/properties/{BR}/obligations").json()}["ob-br-walkway-check"]
    assert view["regulationIds"] == ["eng-whswr-1992-reg-12"] and view["comparisonRegulationIds"] == ["us-ca-ccr-8-3273"]
    assert view["regulationPending"] is False and not view.get("unresolvedRegulationIds")
    workflow = client.post(f"/api/issues/{issue['id']}/fix", json={"speed": 0}).json()
    assert workflow["state"] == "completed" and "us-ca-ccr-8-3273" not in workflow["regulationIds"]
    call = client.get(f"/api/conversations/{workflow['conversationId']}").json()
    assert not any("California" in line["text"] for line in call["transcript"])
