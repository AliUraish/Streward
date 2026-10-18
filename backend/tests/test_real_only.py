"""Owner, Oct 18: a memory page, and real calls and texts only.

Seed records (conversations, memories, notifications loaded from backend/seed that never happened in this running
system) are backfilled once with `origin: "seed"` and hidden by default, visible with ?include=all; records written by
a scenario run or a workflow stay visible; a dispatch the provider really accepted (and an inbound Inkbox reply) is
listed as a real text, a dry run is not; GET /api/memory aggregates, filters and searches every agent's memories.
Every provider is stubbed: Inkbox's client raises if anything tries to reach it, Supermemory is never live.
"""
import itertools
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.providers import InkboxAdapter
from src.real_only import ORIGIN_META, ORIGIN_VERSION
from src.service import PropertyService
from src.synthetic import by_id
from src.verify import iso

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
USER_PHONE = "+15550000001"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def start_scenario(client, scenario_id):
    response = client.post(f"/api/scenarios/{scenario_id}/start", json={"speed": 0})
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["state"] == "completed", run
    return run


def ids(response):
    assert response.status_code == 200, response.text
    body = response.json()
    return [record["id"] for record in (body["items"] if isinstance(body, dict) else body)]


def no_real_inkbox(monkeypatch):
    def refuse():
        raise AssertionError("tests never reach Inkbox")
    monkeypatch.setattr(InkboxAdapter, "client", staticmethod(refuse))


def seed_records(store):
    """What a seed loader would have inserted: the scripted meeting from backend/seed/synthetic/conversations.json as a
    record, memories and a notification stamped by the loader, plus records from runs and workflows written before
    `origin` existed."""
    script = by_id("conversations")["cv-my-overpressure"]
    store.put("conversation", dict(id=script["id"], kind="meeting", topic=script["topic"], convener=script["convener"], participants=script["participants"],
                                   siteIds=[MY], transport="local", providerTaskIds=[], a2aTaskIds=[], contextId="ctx-seed",
                                   transcript=[dict(speaker=t["speaker"], text=str(t["text"]), at="2026-10-17T00:00:00Z") for t in script["turns"]],
                                   summary=script["summary"], summaryBy="hand-seed", startedAt="2026-10-17T00:00:00Z", endedAt="2026-10-17T00:05:00Z",
                                   status="ended", synthetic=True, generator=script["generator"], scenarioId=script["scenarioId"],
                                   issueKind=script["issueKind"], issueId="iss-seeded"), "")
    store.put("conversation", dict(id="conv-oldrun", kind="call", topic="HS-301 humidity after the typhoon", convener="tomioka-engineer",
                                   participants=["tomioka-engineer", "tomioka-manager"], siteIds=[TM], transport="local", providerTaskIds=[],
                                   a2aTaskIds=["a2a-oldrun"], contextId="ctx-oldrun", transcript=[], summary=None, summaryBy=None,
                                   startedAt="2026-10-18T01:00:00Z", endedAt="2026-10-18T01:01:00Z", status="ended", synthetic=True,
                                   scenarioId="tm-humidity", runId="srun-old"), "")
    store.put("conversation", dict(id="conv-oldfix", kind="call", topic="Fix: HS-301 humidity high", convener="tomioka-engineer",
                                   participants=["tomioka-engineer", "tomioka-manager"], siteIds=[TM], transport="local", providerTaskIds=[],
                                   a2aTaskIds=["a2a-oldfix"], contextId="ctx-oldfix", transcript=[], summary=None, summaryBy=None,
                                   startedAt="2026-10-18T01:02:00Z", endedAt="2026-10-18T01:03:00Z", status="ended", synthetic=True,
                                   workflowId="fix-old"), "")
    store.put("agent_memory", dict(id="mem-seeded-1", agentId="myer-manager", container="steward-myer-manager", kind="note",
                                   content="Seeded: PG-601 overpressure briefing", siteId=MY, refs={}, at="2026-10-17T00:00:00Z", synthetic=True,
                                   generator="hand-seed"), "")
    store.put("agent_memory", dict(id="amem-seedmeeting", agentId="myer-engineer", container="steward-myer-engineer", kind="note",
                                   content="Meeting on PG-601 overpressure: isolate at V-501", siteId=MY, refs={"conversationId": "cv-my-overpressure"},
                                   at="2026-10-17T00:06:00Z", synthetic=True), "")
    store.put("agent_memory", dict(id="amem-oldrun", agentId="director", container="steward-director", kind="scenario_outcome",
                                   content="Scenario outcome: HS-301 humidity handled", siteId=TM, refs={"scenarioId": "tm-humidity", "runId": "srun-old"},
                                   at="2026-10-18T01:05:00Z", synthetic=True), "")
    store.put("agent_memory", dict(id="amem-oldcall", agentId="tomioka-manager", container="steward-tomioka-manager", kind="note",
                                   content="Call on HS-301 humidity", siteId=TM, refs={"conversationId": "conv-oldrun"}, at="2026-10-18T01:01:30Z",
                                   synthetic=True), "")
    store.put("notification", dict(id="seed-ntf-1", siteId=MY, sender="myer-manager", toKind="crew", to="crew-my-duty-engineer",
                                   toName="Duty engineer (you)", channel="sms", text="Seeded notification", mode="sent", synthetic=True,
                                   generator="hand-seed", at="2026-10-17T00:00:00Z"), MY)


def test_seed_records_are_backfilled_once_hidden_by_default_and_kept_for_include_all(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "origins"
    first = PropertyService(directory, start_workers=False)
    assert first.store.meta(ORIGIN_META) == ORIGIN_VERSION
    seed_records(first.store)
    first.close()
    with sqlite3.connect(directory / "steward.sqlite3") as db:  # an existing database from before the origin field
        db.execute("DELETE FROM meta WHERE key=?", (ORIGIN_META,))
    upgraded = PropertyService(directory, start_workers=False)
    store = upgraded.store
    assert upgraded.conversations.origin_backfill == dict(conversations=3, memories=4)
    origin = lambda kind, record_id: store.get(kind, record_id, "")["origin"]
    assert origin("conversation", "cv-my-overpressure") == "seed"
    assert origin("conversation", "conv-oldrun") == "run" and origin("conversation", "conv-oldfix") == "workflow"
    assert origin("agent_memory", "mem-seeded-1") == "seed" and origin("agent_memory", "amem-seedmeeting") == "seed"
    assert origin("agent_memory", "amem-oldrun") == "run" and origin("agent_memory", "amem-oldcall") == "run"
    # Idempotent and never overwrites: an origin already set survives a re-run of the backfill.
    store.put("conversation", dict(store.get("conversation", "conv-oldfix", ""), origin="inkbox"), "")
    upgraded.close()
    with sqlite3.connect(directory / "steward.sqlite3") as db:
        db.execute("DELETE FROM meta WHERE key=?", (ORIGIN_META,))
    again = PropertyService(directory, start_workers=False)
    assert again.conversations.origin_backfill == dict(conversations=0, memories=0)
    assert again.store.get("conversation", "conv-oldfix", "")["origin"] == "inkbox"
    assert len(again.store.all("conversation", "")) == 3 and len(again.store.all("agent_memory", "")) == 4  # nothing deleted
    again.close()

    with TestClient(create_app(directory, start_workers=False)) as client:
        shown = ids(client.get("/api/conversations"))
        assert "cv-my-overpressure" not in shown and {"conv-oldrun", "conv-oldfix"} <= set(shown)
        everything = client.get("/api/conversations?include=all").json()
        assert next(c for c in everything if c["id"] == "cv-my-overpressure")["origin"] == "seed"
        assert client.get("/api/conversations/cv-my-overpressure").status_code == 404
        assert client.get("/api/conversations/cv-my-overpressure?include=all").json()["origin"] == "seed"
        assert client.get("/api/conversations/conv-oldrun").json()["origin"] == "run"
        assert ids(client.get("/api/conversations?origin=seed")) == ["cv-my-overpressure"]
        assert ids(client.get("/api/conversations?origin=run,workflow")) == ["conv-oldrun"]  # conv-oldfix was set to inkbox above
        # Board meetings are derived from conversations and follow the same rule.
        assert client.get(f"/api/board-meetings?siteId={MY}").json() == []
        assert [m["id"] for m in client.get(f"/api/board-meetings?siteId={MY}&include=all").json()] == ["cv-my-overpressure"]
        assert client.get("/api/board-meetings/cv-my-overpressure").status_code == 404
        assert client.get("/api/board-meetings?issueId=iss-seeded").status_code == 404
        assert client.get("/api/board-meetings?issueId=iss-seeded&include=all").json()[0]["id"] == "cv-my-overpressure"
        # Memories: the per-agent endpoint and the memory page hide seed memories unless include=all.
        assert ids(client.get("/api/memory?agentId=myer-manager")) == []
        assert client.get("/api/agents/myer-manager/memory").json()["local"] == []
        assert [m["id"] for m in client.get("/api/agents/myer-manager/memory?include=all").json()["local"]] == ["mem-seeded-1"]
        page = client.get("/api/memory").json()
        assert page["hidden"] == 2 and page["include"] == "real" and {"amem-oldrun", "amem-oldcall"} <= {m["id"] for m in page["items"]}
        assert not {"mem-seeded-1", "amem-seedmeeting"} & {m["id"] for m in page["items"]}
        everything = client.get("/api/memory?include=all").json()
        assert everything["hidden"] == 0 and {"mem-seeded-1", "amem-seedmeeting"} <= {m["id"] for m in everything["items"]}
        assert next(m for m in everything["items"] if m["id"] == "mem-seeded-1")["origin"] == "seed"
        # Notifications loaded from a seed file are hidden the same way.
        assert "seed-ntf-1" not in ids(client.get("/api/notifications"))
        assert "seed-ntf-1" in ids(client.get("/api/notifications?include=all"))


def test_run_and_workflow_records_are_real_and_carry_origin(client):
    run = start_scenario(client, "tm-humidity")
    call_id = run["conversationIds"]["cv-tm-humidity"]
    workflow = client.get(f"/api/fix-workflows/{run['context']['fixWorkflowId']}").json()
    shown = {c["id"]: c for c in client.get(f"/api/conversations?siteId={TM}").json()}
    assert shown[call_id]["origin"] == "run" and shown[call_id]["runId"] == run["id"]
    assert shown[workflow["conversationId"]]["origin"] == "workflow"
    assert all(c["origin"] in ("run", "workflow", "inkbox") for c in shown.values())
    assert client.get(f"/api/conversations/{call_id}").json()["origin"] == "run"
    store = svc(client).store
    assert store.get("conversation", call_id, "")["origin"] == "run"  # written where it is created
    memories = client.get(f"/api/memory?siteId={TM}").json()["items"]
    from_call = [m for m in memories if m["refs"].get("conversationId") == call_id]
    assert from_call and all(m["origin"] == "run" and m["source"] == {"kind": "conversation", "id": call_id} for m in from_call)
    outcome = next(m for m in memories if m["kind"] == "scenario_outcome" and m["agentId"] == "director")
    assert outcome["origin"] == "run" and outcome["source"] == {"kind": "scenario_run", "id": run["id"]} and outcome["agentName"] == "Operations Director"
    assert any(m["origin"] == "workflow" and m["refs"].get("conversationId") == workflow["conversationId"] for m in memories)
    # The eval suites read run-created meetings by issue (factory-workflow: get_board_meeting(issueId)); still found by default.
    overpressure = start_scenario(client, "my-overpressure")
    issue_id = next(iter(overpressure["issueIds"].values()))
    meeting = client.get(f"/api/board-meetings?issueId={issue_id}").json()[0]
    assert meeting["origin"] == "run" and meeting["status"] == "resolved" and meeting["resolution"]


def test_a_really_sent_dispatch_is_a_real_text_and_a_dry_run_is_not(client, monkeypatch):
    no_real_inkbox(monkeypatch)
    dry = client.post(f"/api/properties/{MY}/resolve", json={"assetTag": "P-101", "attribute": "pressure_bar", "budget": 5}).json()
    assert client.get(f"/api/work-items/{dry['workItemId']}").json()["dispatches"][0]["providerRef"] is None
    texts = lambda: [c for c in client.get("/api/conversations?kind=message").json() if c.get("real")]
    assert texts() == []  # a local / dry-run dispatch is never a real text
    # Live gates on, the provider stubbed: the SMS is accepted with a provider receipt.
    monkeypatch.setenv("INKBOX_API_KEY", "test-only")
    monkeypatch.setenv("INKBOX_IDENTITY_MYER_TECHNICIAN", "steward-myer-technician")
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    monkeypatch.setenv("INKBOX_CONTRACTOR_PHONE", USER_PHONE)
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", USER_PHONE)
    counter = itertools.count(1)
    sent = []

    def send_sms(property_id, to, body, conversation_id=None, idempotency_key=None):
        sent.append((property_id, to, body))
        return {"id": f"txt-real-{next(counter)}", "conversationId": "thread-real-1"}

    monkeypatch.setattr(svc(client).reality.comms, "send_sms", send_sms)
    live = client.post(f"/api/properties/{MY}/resolve", json={"assetTag": "P-102", "attribute": "pressure_bar", "budget": 5}).json()
    assert len(sent) == 1 and sent[0][1] == USER_PHONE
    [text] = texts()
    assert text["id"].startswith("conv-msg-dispatch-") and text["kind"] == "message" and text["origin"] == "inkbox" and text["synthetic"] is False
    assert (text["channel"], text["direction"], text["providerRef"], text["workItemId"]) == ("sms", "outbound", "txt-real-1", live["workItemId"])
    assert text["participants"] == ["myer-technician", "Duty engineer (you)"] and text["siteIds"] == [MY]
    assert text["person"]["kind"] == "crew" and text["person"]["address"] == "••• ••• 0001" and USER_PHONE not in str(text)
    assert text["transcript"][0]["text"].startswith("Myer Plant Room") and live["reference"] in text["text"] and text["at"]
    assert client.get(f"/api/conversations/{text['id']}").json()["providerRef"] == "txt-real-1"
    assert text["id"] in ids(client.get(f"/api/conversations?siteId={MY}&agentId=myer-technician"))
    assert not any(c.get("workItemId") == dry["workItemId"] for c in texts())
    # An inbound Inkbox reply is a real text too; the accepted verdict goes back on the same thread for real.
    monkeypatch.setenv("STEWARD_INBOUND_SECRET", "s3cret")
    stamp = iso(datetime.now(timezone.utc))
    payload = {"id": "evt_real_1", "event_type": "text.received", "timestamp": stamp, "data": {
        "text_message": {"id": "txt_in_1", "direction": "inbound", "local_phone_number": "+15550000009", "remote_phone_number": USER_PHONE,
                         "text": f"{live['reference']} P-102 reads 2.4 bar", "type": "sms", "media": None, "conversation_id": "thread-real-1", "created_at": stamp},
        "agent_identities": [{"id": "x", "agent_handle": "steward-myer-technician"}], "recipient_phone_number": "+15550000009"}}
    routed = client.post("/api/inbound/inkbox", json=payload, headers={"X-Steward-Inbound-Secret": "s3cret"}).json()
    assert routed["routed"] is True and routed["verdict"] == "accepted"
    real = {(c["direction"], c["providerRef"]): c for c in texts()}
    inbound = real[("inbound", "txt_in_1")]
    assert inbound["participants"] == ["Duty engineer (you)", "myer-technician"] and inbound["channel"] == "sms" and "2.4 bar" in inbound["text"]
    assert inbound["verdict"] == "accepted" and inbound["transcript"][0]["speaker"] == "Duty engineer (you)"
    assert ("outbound", "txt-real-2") in real and real[("outbound", "txt-real-2")]["text"].startswith("Accepted.")
    # A local reply (no provider) is still not a real text.
    client.post("/api/inbound/local", json={"reference": dry["reference"], "body": "P-101 reads 2.5 bar", "sender": "tech-1"})
    assert len(texts()) == 3
    assert sorted(ids(client.get("/api/conversations?origin=inkbox"))) == sorted(c["id"] for c in texts())  # real traffic only


def test_notices_document_email_and_owner_alerts_sent_for_real_become_texts(client):
    store = svc(client).store
    at = "2026-10-18T09:00:00Z"
    store.put("notice", dict(id="ntc-real", siteId=BR, noticeKind="contact", sender="bristol-manager", via="bristol-technician", line="dispatch",
                             toCrewId="crew-br-duty-engineer", toName="Duty engineer (you)", toRole="Duty engineer", channel="sms",
                             text="SU-201 sump at 96 %: attend.", mode="sent", reason="sent by Runner's number", providerRef="txt-notice-1",
                             issueId="iss-1", at=at, synthetic=True), BR)
    store.put("notice", dict(id="ntc-dry", siteId=BR, noticeKind="contact", sender="bristol-manager", via="bristol-technician", toName="Duty engineer (you)",
                             channel="sms", text="dry", mode="dry_run", providerRef=None, at=at, synthetic=True), BR)
    store.put("document_email", dict(id="dem-real", sender="myer-compliance", recipient="myer-engineer", siteId=MY, documentId="doc-1",
                                     subject="[Steward] Service report", bodyText="Please file it.", attachment=dict(filename="doc-1.pdf"),
                                     mode="sent", providerMessageId="em-1", at=at, synthetic=True), MY)
    store.put("document_email", dict(id="dem-dry", sender="myer-compliance", recipient="myer-engineer", siteId=MY, subject="dry", bodyText="",
                                     attachment={}, mode="dry_run", providerMessageId=None, at=at), MY)
    # The shape compliance_alerts.py stores: owner addresses masked, the sender agent, the text that lists the attachments.
    store.put("owner_alert", dict(id="oal-1", siteId=BR, title="PV-301 examination overdue", issueId="iss-2", at=at,
                                  email=dict(mode="sent", to="o•••@example.com", fromAgent="bristol-compliance", subject="[Bristol] Compliance: PV-301 examination (overdue by 6 days)",
                                             text="PV-301: examination overdue\n\nAttached: evidence-oal-1.txt", html="<p>PV-301</p>",
                                             attachments=[dict(filename="evidence-oal-1.txt", contentType="text/plain", size=120)], providerRef="em-alert-1", at=at),
                                  call=dict(mode="sent", to="••• ••• 0002", **{"from": "Steward Dispatch Line"}, brief="This is the Steward Dispatch Line for Bristol.",
                                            providerRef="call-1", at=at)), BR)
    store.put("owner_alert", dict(id="oal-2", siteId=BR, title="held", at=at, email=dict(mode="dry_run", subject="x", providerRef=None),
                                  call=dict(mode="capped", brief="y", providerRef=None)), BR)
    real = {c["id"]: c for c in client.get("/api/conversations?kind=message").json() if c.get("real")}
    assert set(real) == {"conv-msg-notice-ntc-real", "conv-msg-email-dem-real", "conv-msg-alert-oal-1-email", "conv-msg-alert-oal-1-call"}
    notice = real["conv-msg-notice-ntc-real"]
    assert notice["participants"] == ["bristol-technician", "Duty engineer (you)"] and notice["onBehalfOf"] == "bristol-manager"
    assert real["conv-msg-email-dem-real"]["direction"] == "internal" and real["conv-msg-email-dem-real"]["participants"] == ["myer-compliance", "myer-engineer"]
    email, call = real["conv-msg-alert-oal-1-email"], real["conv-msg-alert-oal-1-call"]
    assert email["participants"] == ["bristol-compliance", "owner"] and email["channel"] == "email" and email["text"].count("Attached: evidence-oal-1.txt") == 1
    assert email["person"] == dict(id="owner", name="Owner", kind="owner", address="o•••@example.com") and email["alertId"] == "oal-1"
    assert call["participants"] == ["dispatch", "owner"] and call["channel"] == "call" and call["providerRef"] == "call-1"
    assert call["person"]["address"] == "••• ••• 0002" and call["transcript"][0]["text"].startswith("This is the Steward Dispatch Line")
    assert {c["id"] for c in client.get(f"/api/conversations?siteId={BR}&agentId=owner").json()} == {email["id"], call["id"]}


def test_memory_page_aggregates_filters_and_searches(client, monkeypatch):
    service = svc(client)
    monkeypatch.setattr(service.memory.client, "search", lambda *a, **k: pytest.fail("Supermemory is not live; no search"))
    memory = service.memory
    first = memory.write("myer-engineer", "Isolated at V-501 after PG-601 read 4.1 bar", "decision", {"issueId": "iss-a"}, MY)
    second = memory.write("bristol-compliance", "PV-301 examination certificate expired; examiner booked", "decision", {"issueId": "iss-b"}, BR)
    third = memory.write("director", "Scenario outcome: HS-301 humidity back under 65 %", "scenario_outcome", {"scenarioId": "tm-humidity", "runId": "srun-x"}, TM)
    service.store.put("agent_memory", dict(id="mem-seeded-2", agentId="myer-engineer", container="steward-myer-engineer", kind="note",
                                           content="Seeded note about PG-601", siteId=MY, refs={}, at="2030-01-01T00:00:00Z", generator="hand-seed"), "")
    page = client.get("/api/memory").json()
    assert [m["id"] for m in page["items"]] == [third["id"], second["id"], first["id"]]  # newest first, the seed memory hidden
    assert page["total"] == 3 and page["hidden"] == 1 and page["source"] == "local" and page["supermemory"]["live"] is False
    item = page["items"][2]
    assert {k: item[k] for k in ("agentId", "agentName", "siteId", "kind", "text", "origin")} == dict(
        agentId="myer-engineer", agentName="Site Engineer · Myer", siteId=MY, kind="decision", text=first["content"], origin="workflow")
    assert item["refs"] == {"issueId": "iss-a"} and item["source"] == {"kind": "issue", "id": "iss-a"} and item["at"] == first["at"]
    assert page["items"][0]["origin"] == "run" and page["items"][0]["source"] == {"kind": "scenario_run", "id": "srun-x"}
    assert ids(client.get(f"/api/memory?siteId={BR}")) == [second["id"]]
    assert ids(client.get("/api/memory?agentId=myer-engineer")) == [first["id"]]
    assert ids(client.get("/api/memory?query=pg-601 V-501")) == [first["id"]]  # every word must match
    assert ids(client.get("/api/memory?query=examiner")) == [second["id"]]
    assert ids(client.get("/api/memory?query=Compliance Officer")) == [second["id"]]  # the agent's name is searchable
    assert ids(client.get("/api/memory?query=PG-601 humidity")) == []
    assert ids(client.get(f"/api/memory?query=pg-601&include=all&siteId={MY}")) == ["mem-seeded-2", first["id"]]
    limited = client.get("/api/memory?limit=1").json()
    assert [m["id"] for m in limited["items"]] == [third["id"]] and limited["total"] == 3
    assert client.get("/api/memory?agentId=nobody").status_code == 404
    assert client.get("/api/memory?siteId=nowhere").status_code == 404
    # The per-agent endpoint keeps working.
    assert [m["id"] for m in client.get("/api/agents/myer-engineer/memory").json()["local"]] == [first["id"]]
