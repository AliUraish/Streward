"""The automatic Tool Forge (Oct 18): a request with a prepared draft is validated, tested, reviewed by the site manager in a
short chat, approved and published with no manual call; a task with no prepared draft is drafted live by Claude (stubbed
here) and goes the same way; a failing Claude draft is revised once and then rejected; a tool that writes stops at tested
for the Operations Director; the drafting switch and caps leave the request waiting with the reason. Nothing leaves the
process: Claude is a fake, the chats play their templates."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.main import create_app

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
PUMP_TASK = "Which pumps went over their pressure spec more than three times in the last 7 days, and who is responsible for each?"
ROUTE_TASK = "List every asset on the visitor route with an open issue or an overdue obligation, the regulation involved, and who must act."
UNBOOKED_TASK = "Which obligations fall due in the next 14 days with no maintenance booked, and who owns each?"


def arg(name, value):
    return dict(name=name, value=value)


# What Claude returns for the Tomioka task: the structured draft of forge_drafter.draft_schema().
UNBOOKED = dict(
    name="unbooked_due_obligations",
    description="Lists the obligations that fall due within 14 days with no open maintenance window booked, and who owns each. Read-only, "
                "a few store reads; next: book the work with schedule_maintenance or ask the site manager.",
    gap="list_obligations and list_maintenance are separate tools and neither names the owner",
    consideredTools=[dict(name="list_obligations", whyNot="no maintenance join"), dict(name="list_maintenance", whyNot="windows only")],
    inputs=[],
    steps=[
        dict(id="obl", op="obligations.list", args=[]),
        dict(id="due", op="filter", args=[arg("from", "{{steps.obl}}"), arg("where", "status == 'due_soon'")]),
        dict(id="win", op="maintenance.list", args=[]),
        dict(id="open", op="filter", args=[arg("from", "{{steps.win}}"), arg("where", "status != 'done'")]),
        dict(id="joined", op="join_on", args=[arg("left", "{{steps.due}}"), arg("right", "{{steps.open}}"), arg("on", "id=obligationId"),
                                              arg("as", "window"), arg("mode", "left")]),
        dict(id="unbooked", op="filter", args=[arg("from", "{{steps.joined}}"), arg("where", "window missing")]),
        dict(id="crew", op="crew.list", args=[]),
        dict(id="owned", op="join_on", args=[arg("left", "{{steps.unbooked}}"), arg("right", "{{steps.crew}}"), arg("on", "ownerId=id"),
                                             arg("as", "owner"), arg("mode", "left")]),
        dict(id="rows", op="map", args=[arg("from", "{{steps.owned}}"), arg("obligationId", "{{item.id}}"), arg("assetTag", "{{item.assetTag}}"),
                                        arg("title", "{{item.title}}"), arg("dueAt", "{{item.dueAt}}"), arg("owner", "{{item.owner.name}}"),
                                        arg("ownerRole", "{{item.owner.role}}"), arg("regulation", "{{item.regulation}}")]),
    ],
    outputShape="list",
    outputFields=[dict(name="obligationId", type="string"), dict(name="assetTag", type="string_or_null"), dict(name="title", type="string"),
                  dict(name="dueAt", type="string_or_null"), dict(name="owner", type="string_or_null"), dict(name="ownerRole", type="string_or_null"),
                  dict(name="regulation", type="string_or_null")],
    rowFields=[],
    outputTemplate="{{steps.rows}}",
    testInput=[],
)
BROKEN = dict(UNBOOKED, steps=[dict(id="obl", op="obligations.list", args=[arg("status", "{{input.state}}")])], outputTemplate="{{steps.obl}}")


class FakeClaude:
    def __init__(self, *drafts):
        self.drafts, self.requests = list(drafts), []
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        draft = self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(draft))], stop_reason="end_turn", model="claude-opus-5-5",
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=900))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    monkeypatch.setenv("STEWARD_CHAT_CLAUDE", "false")  # the review chat plays its template
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def ask(client, site, task, agent=None, draft=None):
    body = dict(siteId=site, task=task, **({"agentId": agent} if agent else {}), **({"draft": draft, "generator": "claude-opus-5-5"} if draft else {}))
    response = client.post("/api/tools/requests", json=body)
    assert response.status_code in (201, 202), response.text
    return response.json()


def test_prepared_drafts_are_published_with_no_manual_call(client):
    for site, agent, task, name, manager in ((MY, "myer-engineer", PUMP_TASK, "pump_spec_breaches", "myer-manager"),
                                             (BR, "bristol-compliance", ROUTE_TASK, "visitor_route_readiness", "bristol-manager")):
        tool = ask(client, site, task, agent)["tool"]
        assert tool["name"] == name and tool["status"] == "published", (tool["status"], tool.get("validation"), tool.get("test"))
        assert tool["approvedBy"] == manager and tool["generator"] == "hand-seed" and tool["test"]["passed"] is True
        review = svc(client).conversations.get(tool["reviewConversationId"])
        assert review["kind"] == "call" and len(review["transcript"]) == 4 and set(review["participants"]) == {agent, manager}
        assert review["summary"]["headline"]
        called = client.post(f"/api/tools/{tool['id']}/call", json={"args": {}})
        assert called.status_code == 200 and "output" in called.json()
        # A manual step after the pipeline is a no-op, so the dashboard's step-by-step run can overlap it.
        assert client.post(f"/api/tools/{tool['id']}/validate").json()["status"] == "published"
        assert client.post(f"/api/tools/{tool['id']}/publish").json()["status"] == "published"
    steps = [c["step"] for c in svc(client).store.all("change", MY) if c["type"] == "tool" and c.get("step")]
    assert {"draft", "validate", "test", "approve", "publish"} <= set(steps)


def test_a_task_with_no_prepared_draft_is_drafted_by_claude_and_published(client):
    claude = FakeClaude(UNBOOKED)
    svc(client).forge.drafter.client = claude
    result = ask(client, TM, UNBOOKED_TASK, "tomioka-compliance")
    tool, request = result["tool"], result["request"]
    assert tool["status"] == "published" and tool["generator"] == "claude-opus-5-5" and tool["approvedBy"] == "tomioka-manager"
    assert request["status"] == "drafted" and request["toolId"] == tool["id"]
    body = claude.requests[0]
    assert body["model"] == "claude-opus-5-5" and body["output_config"]["effort"] == "medium" and body["fallbacks"] == "default"
    assert body["betas"] == ["server-side-fallback-2026-07-01"] and "Which obligations fall due" in body["messages"][0]["content"]
    rows = tool["test"]["output"]
    assert rows and all(r["obligationId"] and r["owner"] for r in rows), rows  # seeded: HS-301's humidity watch, nothing booked
    called = client.post(f"/api/tools/{tool['id']}/call", json={"args": {}}).json()["output"]
    assert called == rows
    usage = svc(client).forge.drafter.usage()
    assert usage["calls"] == 1 and usage["usd"] > 0


def test_a_failing_claude_draft_is_revised_once_then_rejected(client):
    claude = FakeClaude(BROKEN, BROKEN)
    svc(client).forge.drafter.client = claude
    tool = ask(client, TM, UNBOOKED_TASK, "tomioka-compliance")["tool"]
    assert tool["status"] == "rejected" and tool["revisions"] == 1 and len(claude.requests) == 2
    assert "validation failed" in tool["rejection"]["reason"] and "Steward's checks failed" in claude.requests[1]["messages"][0]["content"]
    fixed = FakeClaude(BROKEN, UNBOOKED)
    svc(client).forge.drafter.client = fixed
    revised = ask(client, TM, UNBOOKED_TASK + " Again, please.", "tomioka-compliance")["tool"]
    assert revised["status"] == "published" and revised["revisions"] == 1 and len(fixed.requests) == 2


def test_a_tool_that_writes_stops_at_tested_for_the_director(client):
    writer = dict(name="flag_hot_supply", description="Raises a low issue on TS-801 when asked; it writes, so the Director approves it. Next: get_issue.",
                  why=dict(gap="no tool raises this issue", consideredTools=[]), inputSchema=dict(type="object", properties={}, required=[], additionalProperties=False),
                  steps=[dict(id="s1", op="issues.raise", args={"kind": "eye_observation", "severity": "low", "summary": "Forge probe: check TS-801.",
                                                             "assetTag": "TS-801"})],
                  output=dict(template="{{steps.s1}}", schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": [], "additionalProperties": False}),
                  test=dict(input={}))
    before = len(svc(client).store.all("issue", MY))
    tool = ask(client, MY, "Raise a low issue on TS-801 when the supply runs hot, please.", "myer-engineer", draft=writer)["tool"]
    assert tool["status"] == "tested" and tool["readOnly"] is False and tool["approvedBy"] is None
    assert len(svc(client).store.all("issue", MY)) == before  # the test previewed the write, nothing ran
    lines = [line["text"] for line in svc(client).conversations.get(tool["conversationId"])["transcript"]]
    assert any("waits for the Operations Director" in text for text in lines)
    approved = client.post(f"/api/tools/{tool['id']}/approve", json={"approve": True}, headers={"X-Steward-Actor": "director"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"


def test_the_switch_the_key_and_the_caps_leave_the_request_waiting(client, monkeypatch):
    nothing = ask(client, TM, "Which looms ran hot twice this week and who checked them?", "tomioka-engineer")
    assert nothing["tool"] is None and nothing["request"]["status"] == "awaiting_draft" and "ANTHROPIC_API_KEY" in nothing["request"]["draftError"]
    svc(client).forge.drafter.client = FakeClaude(UNBOOKED)
    monkeypatch.setenv("STEWARD_FORGE_CLAUDE", "false")
    off = ask(client, TM, "Which looms ran hot twice this week and who checked them, again?", "tomioka-engineer")
    assert off["request"]["status"] == "awaiting_draft" and "STEWARD_FORGE_CLAUDE=false" in off["request"]["draftError"]
    monkeypatch.setenv("STEWARD_FORGE_CLAUDE", "true")
    monkeypatch.setenv("STEWARD_FORGE_CLAUDE_MAX_CALLS_PER_DAY", "0")
    capped = ask(client, TM, "Which looms ran hot twice this week and who checked them, once more?", "tomioka-engineer")
    assert capped["request"]["status"] == "awaiting_draft" and "daily drafting cap" in capped["request"]["draftError"]
    monkeypatch.setenv("STEWARD_FORGE_AUTO", "false")
    manual = ask(client, MY, PUMP_TASK, "myer-engineer")["tool"]
    assert manual["status"] == "draft"  # the lifecycle by hand, as before
