"""Contract 6: Tool Forge. The op runner (allow-list only, the creating agent's authority, never the other site, write ops
need the Director), the lifecycle (request, draft, validate, test, approve or refuse, publish, call, retire, versions), the
Changes, waits, conversation lines and telemetry, and the two hand-seeded demo tools on seeded data. Nothing leaves the
machine; no model is called."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.main import create_app

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
PUMP_TASK = "Which pumps went over their pressure spec more than three times in the last 7 days, and who is responsible for each?"
ROUTE_TASK = "List every asset on the visitor route that has an open issue or an overdue obligation, the regulation involved, and who must act."
ROW = lambda props: {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def scenario(client, scenario_id):
    run = client.post(f"/api/scenarios/{scenario_id}/start", json={"speed": 0}).json()
    assert run["state"] == "completed", run
    return run


def draft(name="probe_tool", steps=None, schema=None, template="{{steps.s1}}", inputs=None, description="Lists the latest facts at the site; read-only; next: resolve one."):
    return dict(name=name, description=description, why=dict(gap="no tool lists what this probe needs", consideredTools=[dict(name="get_facts", whyNot="one asset")]),
                inputSchema=dict(type="object", properties=inputs or {}, required=[], additionalProperties=False),
                steps=steps or [dict(id="s1", op="facts.list", args={})],
                output=dict(template=template, schema=schema or {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {}}}),
                test=dict(input={}))


def build(client, site, agent, definition, actor="operator", task="A task no existing tool answers, for the test."):
    response = client.post("/api/tools/requests", json=dict(siteId=site, agentId=agent, task=task, draft=definition, generator="claude-opus-5-5"),
                           headers={"X-Steward-Actor": actor})
    assert response.status_code == 201, response.text
    return response.json()["tool"]


def lifecycle(client, tool, approver):
    validated = client.post(f"/api/tools/{tool['id']}/validate").json()
    assert validated["status"] == "validated", validated["validation"]
    tested = client.post(f"/api/tools/{tool['id']}/test").json()
    assert tested["status"] == "tested", tested["test"]
    approved = client.post(f"/api/tools/{tool['id']}/approve", json={"approve": True}, headers={"X-Steward-Actor": approver})
    assert approved.status_code == 200, approved.text
    published = client.post(f"/api/tools/{tool['id']}/publish").json()
    assert published["status"] == "published"
    return published


# ---- the op runner ----------------------------------------------------------------------------------------------------------

def test_ops_outside_the_allow_list_are_refused(client):
    tool = build(client, MY, "myer-engineer", draft(steps=[dict(id="s1", op="shell.exec", args={"cmd": "ls"}), dict(id="s2", op="facts.list", args={})],
                                                   template="{{steps.s2}}"))
    validated = client.post(f"/api/tools/{tool['id']}/validate").json()
    assert validated["status"] == "draft" and any("not on the allow-list" in e for e in validated["validation"]["errors"])
    assert client.post(f"/api/tools/{tool['id']}/test").json()["code"] == "INVALID_REQUEST"  # never runs unvalidated
    with pytest.raises(Exception) as raised:
        svc(client).forge.execute(svc(client).forge.get(tool["id"]), {}, dry_run=True)
    assert "not on the allow-list" in str(raised.value.detail)
    bad_args = build(client, MY, "myer-engineer", draft(name="probe_args", steps=[dict(id="s1", op="facts.list", args={"command": "x"})]))
    assert any("does not take 'command'" in e for e in client.post(f"/api/tools/{bad_args['id']}/validate").json()["validation"]["errors"])
    unresolved = build(client, MY, "myer-engineer", draft(name="probe_templates", steps=[dict(id="s1", op="facts.list", args={"assetTag": "{{input.tag}}"}),
                                                                                         dict(id="s2", op="take", args={"from": "{{steps.s9}}", "count": "3"})],
                                                         template="{{steps.s2}}"))
    errors = client.post(f"/api/tools/{unresolved['id']}/validate").json()["validation"]["errors"]
    assert any("input the schema does not declare" in e for e in errors) and any("step that has not run yet" in e for e in errors)
    open_schema = build(client, MY, "myer-engineer", draft(name="probe_open", schema={"type": "array", "items": {"type": "object", "properties": {}}}))
    assert any("additionalProperties false" in e for e in client.post(f"/api/tools/{open_schema['id']}/validate").json()["validation"]["errors"])
    catalog = client.get("/api/tools/catalog").json()
    assert {o["op"] for o in catalog["ops"]} >= {"facts.list", "metrics.series", "issues.list", "obligations.list", "crew.responsible", "eye.go_to", "resolve"}
    assert {t["op"] for t in catalog["transforms"]} == {"filter", "map", "group_count", "sort", "take", "join_on", "concat"}


def test_a_tool_can_never_read_the_other_site(client):
    # Naming another site, or choosing a site at all, fails validation.
    named = build(client, MY, "myer-engineer", draft(name="probe_named", steps=[dict(id="s1", op="facts.list", args={"assetTag": "bristol-pumps"})]))
    assert any(e.startswith("scope:") for e in client.post(f"/api/tools/{named['id']}/validate").json()["validation"]["errors"])
    chooser = build(client, MY, "myer-engineer", draft(name="probe_site", steps=[dict(id="s1", op="facts.list", args={"siteId": "myer-plant"})]))
    assert any("may not choose a site" in e for e in client.post(f"/api/tools/{chooser['id']}/validate").json()["validation"]["errors"])
    # Building for another site is refused; so is asking another site's engineer across the cross-site rule.
    denied = client.post("/api/tools/requests", json=dict(siteId=BR, agentId="myer-engineer", task="Read Bristol's sump from Myer, please.", draft=draft()))
    assert denied.status_code == 403 and denied.json()["code"] == "AUTHORITY_DENIED"
    cross = client.post("/api/tools/requests", json=dict(siteId=BR, agentId="bristol-engineer", task="Build me a Bristol tool from Myer.", draft=draft()),
                        headers={"X-Steward-Actor": "myer-engineer"})
    assert cross.status_code == 403 and "across sites" in cross.json()["detail"]
    # At run time every op is pinned to the tool's own site: a Bristol tag finds nothing at Myer.
    tool = lifecycle(client, build(client, MY, "myer-engineer", draft(name="sump_probe", steps=[dict(id="s1", op="facts.list", args={"assetTag": "{{input.tag}}"})],
                                                                     inputs={"tag": {"type": "string", "default": "SU-201"}})), "myer-manager")
    assert client.post(f"/api/tools/{tool['id']}/call", json={"args": {"tag": "SU-201"}}).json()["output"] == []
    assert client.post(f"/api/tools/{tool['id']}/call", json={"args": {"tag": "P-101"}}).json()["output"]  # Myer's own asset has facts
    other = client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}, headers={"X-Steward-Actor": "bristol-manager"})
    assert other.status_code == 403 and other.json()["code"] == "AUTHORITY_DENIED"


def test_write_ops_need_the_director_and_run_with_the_creators_authority(client):
    writer = draft(name="flag_hot_supply", description="Raises a low issue on TS-801 when asked; it writes, so the Director approves it. Next: get_issue.",
                   steps=[dict(id="s1", op="issues.raise", args={"kind": "eye_observation", "severity": "low", "summary": "Forge probe: check TS-801 lagging.",
                                                              "assetTag": "TS-801"})],
                   schema={"type": "object", "properties": {}, "additionalProperties": True}, template="{{steps.s1}}")
    writer["output"]["schema"] = {"type": "object", "properties": {"id": {"type": "string"}}, "required": [], "additionalProperties": False}
    tool = build(client, MY, "myer-engineer", writer)
    validated = client.post(f"/api/tools/{tool['id']}/validate").json()
    assert validated["readOnly"] is False and validated["validation"]["readOnly"] is False
    issues_before = len(svc(client).store.all("issue", MY))
    tested = client.post(f"/api/tools/{tool['id']}/test").json()
    assert "previewed, not executed" in " ".join(tested["test"]["notes"]) and len(svc(client).store.all("issue", MY)) == issues_before
    # The test output is the preview, which the closed output schema rejects, so retest with a permissive schema for the write.
    record = svc(client).forge.get(tool["id"])
    record["output"]["schema"] = {"type": "object", "properties": {"id": {"type": "string"}, "preview": {"type": "boolean"}, "op": {"type": "string"},
                                                                    "args": {"type": "object", "properties": {}, "additionalProperties": True}},
                                  "required": [], "additionalProperties": True}
    svc(client).store.put("forged_tool", record, MY)
    assert client.post(f"/api/tools/{tool['id']}/test").json()["status"] == "tested"
    manager = client.post(f"/api/tools/{tool['id']}/approve", json={"approve": True}, headers={"X-Steward-Actor": "myer-manager"})
    assert manager.status_code == 403 and "needs the Operations Director" in manager.json()["detail"]
    assert client.post(f"/api/tools/{tool['id']}/approve", json={"approve": True}).status_code == 403  # the Owner's agent does not approve
    director = client.post(f"/api/tools/{tool['id']}/approve", json={"approve": True}, headers={"X-Steward-Actor": "director"}).json()
    assert director["status"] == "approved" and director["approvedBy"] == "director"
    client.post(f"/api/tools/{tool['id']}/publish", headers={"X-Steward-Actor": "director"})
    called = client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}).json()
    raised = svc(client).store.get("issue", called["output"]["id"], MY)
    assert raised["forgedToolId"] == tool["id"] and raised["history"][-1]["by"] == "myer-engineer" and called["ranAs"] == "myer-engineer"
    # A step the creator may not perform fails at run time, whoever calls: compliance cannot drive the eye.
    eye_tool = build(client, MY, "myer-compliance", draft(name="compliance_eye", steps=[dict(id="s1", op="eye.look", args={})],
                                                          schema={"type": "object", "properties": {}, "required": [], "additionalProperties": True}))
    record = svc(client).forge.get(eye_tool["id"])
    record.update(status="published", readOnly=False)
    svc(client).store.put("forged_tool", record, MY)
    failed = client.post(f"/api/tools/{eye_tool['id']}/call", json={"args": {}}, headers={"X-Steward-Actor": "director"})
    assert failed.status_code == 403 and "Compliance Officer · Myer may not drive the agent eye" in failed.json()["detail"]


# ---- the lifecycle ----------------------------------------------------------------------------------------------------------

def test_lifecycle_changes_waits_transcripts_usage_refusal_and_versions(client):
    wait = client.post("/api/waits", json={"event": "tool.published", "siteId": MY}).json()["id"]
    requested = client.post("/api/tools/requests", json={"agentId": "myer-engineer", "siteId": MY, "task": PUMP_TASK})
    assert requested.status_code == 201
    body = requested.json()
    tool, request = body["tool"], body["request"]
    assert tool["generator"] == "hand-seed" and tool["synthetic"] is True and tool["status"] == "draft" and tool["mcpName"] == "forge_pump_spec_breaches"
    assert tool["why"]["task"] == PUMP_TASK and tool["why"]["requestedBy"] == "operator" and "breaches per asset" in tool["why"]["gap"]
    assert {c["name"] for c in tool["why"]["consideredTools"]} >= {"get_metrics", "who_is_responsible"} and request["status"] == "drafted"
    assert tool["mcpDescription"].startswith("Built by Site Engineer · Myer on ") and "because get_metrics returns raw series" in tool["mcpDescription"]
    assert client.post(f"/api/tools/{tool['id']}/publish").json()["code"] == "INVALID_REQUEST"  # nothing skips a step
    published = lifecycle(client, tool, "myer-manager")
    assert published["approvedBy"] == "myer-manager" and published["test"]["passed"] is True and published["readOnly"] is True
    assert client.get(f"/api/waits/{wait}?timeout=0").json()["status"] == "fired"
    steps = [c for c in client.get(f"/api/properties/{MY}/changes?limit=1000").json()["changes"] if c["type"] == "tool"]
    assert len(steps) == 5 and all(c["refId"] == tool["id"] and c["toolId"] == tool["id"] for c in steps)  # draft, validate, test, approve, publish
    assert [c["status"] for c in sorted(steps, key=lambda c: c["version"])] == ["draft", "validated", "tested", "approved", "published"]
    conversation = client.get(f"/api/conversations/{tool['conversationId']}").json()
    lines = [(line["speaker"], line["text"]) for line in conversation["transcript"]]
    assert lines[0] == ("operator", PUMP_TASK) and lines[1][1].startswith("I don't have a tool for this; drafting forge_pump_spec_breaches")
    assert [s for s, _ in lines] == ["operator", "myer-engineer", "myer-engineer", "myer-engineer", "myer-manager", "myer-engineer"]
    transcript = client.get("/api/agents/myer-engineer/transcript").json()
    assert any("drafting forge_pump_spec_breaches" in e["text"] for e in transcript) and any("Approved forge_pump_spec_breaches" in e["text"] for e in transcript)
    assert any("forge_pump_spec_breaches" in e["text"] for e in client.get("/api/agents/myer-manager/transcript").json())
    listed = client.get(f"/api/tools?siteId={MY}&status=published").json()
    assert [t["id"] for t in listed] == [tool["id"]] and client.get(f"/api/tools?agentId=myer-engineer").json()[0]["id"] == tool["id"]
    first = client.post(f"/api/tools/{tool['id']}/call", json={"args": {"days": 7, "minBreaches": 3}}).json()
    second = client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}, headers={"X-Steward-Actor": "myer-manager"}).json()
    assert second["usage"]["calls"] == 2 and second["usage"]["tokensSavedEstimate"] >= first["tokensSavedEstimate"] > 0
    rows = [r for r in svc(client).telemetry.rows(limit=10000) if r["tool"] == "forge_pump_spec_breaches"]
    assert {r["agentId"] for r in rows} == {"operator", "myer-manager"} and all(r["siteId"] == MY for r in rows)
    bad = client.post(f"/api/tools/{tool['id']}/call", json={"args": {"days": "seven"}})
    assert bad.status_code == 400 and "input schema" in bad.json()["detail"]
    # A new version keeps the usage history and supersedes the old one when published.
    again = client.post("/api/tools/requests", json={"agentId": "myer-engineer", "siteId": MY, "task": PUMP_TASK}).json()["tool"]
    assert again["version"] == 2 and again["previousVersionId"] == tool["id"] and again["usage"]["calls"] == 2
    assert again["usage"]["history"][0] == {"version": 1, "toolId": tool["id"], "calls": 2, "tokensSavedEstimate": second["usage"]["tokensSavedEstimate"]}
    lifecycle(client, again, "director")
    old = client.get(f"/api/tools/{tool['id']}").json()
    assert old["status"] == "retired" and old["supersededBy"] == again["id"]
    assert client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}).json()["code"] == "TOOL_NOT_PUBLISHED"
    retired = client.post(f"/api/tools/{again['id']}/retire", json={"reason": "demo over"}, headers={"X-Steward-Actor": "myer-manager"}).json()
    assert retired["status"] == "retired" and retired["retireReason"] == "demo over"
    # A refusal is recorded with its reason; one without a reason is refused.
    refused = client.post("/api/tools/requests", json={"agentId": "bristol-compliance", "siteId": BR, "task": ROUTE_TASK},
                          headers={"X-Steward-Actor": "bristol-manager"}).json()["tool"]
    client.post(f"/api/tools/{refused['id']}/validate")
    client.post(f"/api/tools/{refused['id']}/test")
    assert client.post(f"/api/tools/{refused['id']}/approve", json={"approve": False}, headers={"X-Steward-Actor": "bristol-manager"}).status_code == 400
    assert client.post(f"/api/tools/{refused['id']}/approve", json={"approve": True}, headers={"X-Steward-Actor": "myer-manager"}).status_code == 403
    rejected = client.post(f"/api/tools/{refused['id']}/approve", json={"approve": False, "reason": "use the opening checklist this week"},
                           headers={"X-Steward-Actor": "bristol-manager"}).json()
    assert rejected["status"] == "rejected" and rejected["rejection"]["reason"] == "use the opening checklist this week" and rejected["rejection"]["by"] == "bristol-manager"
    # A task with no prepared draft records the gap and waits for scripts/synth/forge.py.
    gap = client.post("/api/tools/requests", json={"siteId": BR, "task": "How many visitors crossed W-1201 during the last open day?"})
    assert gap.status_code == 202 and gap.json()["tool"] is None and gap.json()["request"]["status"] == "awaiting_draft"
    assert gap.json()["request"]["agentId"] == "bristol-engineer"  # routed to the site team by the task's words (data → the engineer)
    drafted = client.post("/api/tools/requests", json={"siteId": BR, "requestId": gap.json()["request"]["id"], "generator": "claude-opus-5-5",
                                                       "draft": draft(name="open_day_visitors")}).json()
    assert drafted["tool"]["generator"] == "claude-opus-5-5" and drafted["tool"]["createdBy"] == "bristol-engineer" and drafted["request"]["status"] == "drafted"
    permit = client.post("/api/tools/requests", json={"siteId": BR, "task": "Which permits and certificates expire before the open day?"}).json()
    assert permit["request"]["agentId"] == "bristol-compliance"  # compliance words → the Compliance Officer


# ---- the demo tools on seeded data -------------------------------------------------------------------------------------------

def test_pump_spec_breaches_counts_breaches_and_owners_on_seeded_data(client):
    tool = client.post("/api/tools/requests", json={"agentId": "myer-engineer", "siteId": MY, "task": PUMP_TASK}).json()["tool"]
    tool = lifecycle(client, tool, "myer-manager")
    assert client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}).json()["output"] == []  # the seeded week has no breach
    scenario(client, "my-overpressure")
    output = client.post(f"/api/tools/{tool['id']}/call", json={"args": {"days": 7, "minBreaches": 3}}).json()["output"]
    # The same answer computed independently from the metrics API and the crew table.
    start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    series = client.get(f"/api/properties/{MY}/metrics", params={"series": "pressure_bar", "from": start}).json()["series"]
    owner = client.get(f"/api/properties/{MY}/responsible?issueKind=overpressure").json()["owner"]["name"]
    expected = []
    for entry in series:
        over = [v for _, v in entry["points"] if v > entry["spec"]["max"]]
        if len(over) > 3:
            expected.append(dict(assetTag=entry["assetTag"], breaches=len(over), worstValue=max(over), unit=entry["unit"], owner=owner))
    assert output == sorted(expected, key=lambda r: -r["breaches"]) and output[0] == {"assetTag": "PG-601", "breaches": 5, "worstValue": 4.1, "unit": "bar",
                                                                                     "owner": "Duty engineer (you)"}
    assert client.post(f"/api/tools/{tool['id']}/call", json={"args": {"minBreaches": 5}}).json()["output"] == []


def test_visitor_route_readiness_on_seeded_data(client):
    tool = client.post("/api/tools/requests", json={"agentId": "bristol-compliance", "siteId": BR, "task": ROUTE_TASK},
                       headers={"X-Steward-Actor": "bristol-manager"}).json()["tool"]
    assert tool["name"] == "visitor_route_readiness" and tool["why"]["requestedBy"] == "bristol-manager"
    tool = lifecycle(client, tool, "bristol-manager")
    assert client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}).json()["output"] == {"items": [], "ready": True}
    scenario(client, "br-sump")
    svc(client).people.update_obligation("ob-br-fe1001-monthly", None, due_in_days=-2)
    output = client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}, headers={"X-Steward-Actor": "bristol-manager"}).json()["output"]
    components = client.get(f"/api/properties/{BR}/components").json()
    route = {c["tag"] for c in components if c["subsystem"] == "Visitor route" or "walkway" in c["description"].lower() or "visitor route" in c["description"].lower()}
    assert route == {"SU-201", "FE-1001", "D-1101", "W-1201", "L-901"}
    issues = {(i["assetTag"], "issue") for i in client.get(f"/api/properties/{BR}/issues").json() if i.get("assetTag") in route}
    overdue = {(o["assetTag"], "obligation") for o in client.get(f"/api/properties/{BR}/obligations?status=overdue").json() if o.get("assetTag") in route}
    assert {(r["assetTag"], r["kind"]) for r in output["items"]} == issues | overdue == {("SU-201", "issue"), ("FE-1001", "obligation")}
    sump = next(r for r in output["items"] if r["assetTag"] == "SU-201")
    assert sump["blocking"] is True and sump["owner"] == "Duty engineer (you)" and sump["issueOrObligation"].startswith("sump_overflow: SU-201")
    regulations = {r["id"] for r in client.get(f"/api/regulations?siteId={BR}").json()}
    if "eng-whswr-1992-reg-12" in regulations:
        assert sump["regulation"].startswith("Workplace (Health, Safety and Welfare) Regulations 1992") and "reg. 12" in sump["regulation"]
    extinguisher = next(r for r in output["items"] if r["assetTag"] == "FE-1001")
    assert extinguisher["blocking"] is True and extinguisher["owner"] == "Alasdair Pennock" and output["ready"] is False


def test_the_forge_works_at_the_mill(client):
    humidity = draft(name="humidity_over_limit",
                     description="Counts, per humidity sensor at the mill, the readings above the preservation maximum today. Read-only. Next: start a fix.",
                     steps=[dict(id="s1", op="metrics.samples", args={"series": "humidity_pct", "days": "1"}),
                            dict(id="s2", op="filter", args={"from": "{{steps.s1}}", "where": "value > item.max"}),
                            dict(id="s3", op="group_count", args={"from": "{{steps.s2}}", "by": "assetTag", "max": "value"}),
                            dict(id="s4", op="map", args={"from": "{{steps.s3}}", "assetTag": "{{item.assetTag}}", "readings": "{{item.count}}", "peak": "{{item.max}}"})],
                     schema={"type": "array", "items": ROW({"assetTag": {"type": "string"}, "readings": {"type": "integer"}, "peak": {"type": "number"}})},
                     template="{{steps.s4}}")
    tool = lifecycle(client, build(client, TM, "tomioka-engineer", humidity), "tomioka-manager")
    assert tool["mcpDescription"].startswith("Built by Conservation Engineer · Tomioka")
    scenario(client, "tm-humidity")
    output = client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}, headers={"X-Steward-Actor": "tomioka-compliance"}).json()["output"]
    assert output == [{"assetTag": "HS-301", "readings": 7, "peak": 88.6}]
    assert client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}, headers={"X-Steward-Actor": "bristol-compliance"}).status_code == 403
    assert client.post(f"/api/tools/{tool['id']}/approve", json={"approve": True}, headers={"X-Steward-Actor": "tomioka-manager"}).json()["code"] == "INVALID_REQUEST"
    assert any(c["type"] == "tool" for c in client.get(f"/api/properties/{TM}/changes?limit=1000").json()["changes"])
