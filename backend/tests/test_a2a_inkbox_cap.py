"""Agent-to-agent messages over Inkbox (STEWARD_A2A_TRANSPORT=inkbox): they only connect Steward's own identities, so they are
not a live switch; the bus bounds them instead. At most STEWARD_A2A_INKBOX_MAX_PER_HOUR Inkbox-carried messages (sends,
replies, follow-ups) per rolling hour, counted in the store (a restart keeps the count); over the cap a message stays local
with transportReason "hourly Inkbox cap". Machine chatter (the simulator's status checks, keep-alives, bare acknowledgements)
never goes over Inkbox. Traffic with an outside party is counted but never held. The Inkbox send and reply are stubbed on
the bus and building a real Inkbox client fails the test: nothing leaves the process."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from src.a2a import A2ABus, CAP_REASON, CHATTER_REASON, INKBOX_SENT_META
from src.main import create_app

MY = "myer-plant"
IDENTITIES = {"INKBOX_API_KEY": "fixture-key", "INKBOX_IDENTITY_DIRECTOR": "steward-ops-director",
              "INKBOX_IDENTITY_MYER_MANAGER": "steward-myer-manager", "INKBOX_IDENTITY_MYER_ENGINEER": "steward-myer-engineer",
              "INKBOX_IDENTITY_MYER_COMPLIANCE": "steward-myer-compliance", "INKBOX_IDENTITY_MYER_TECHNICIAN": "steward-myer-technician"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY", "STEWARD_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


@pytest.fixture
def inkbox(client, monkeypatch):
    """Inkbox A2A on, with every Inkbox call stubbed: `sent` and `replied` record what would have gone over the wire."""
    for name, value in IDENTITIES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "inkbox")
    bus = client.app.state.service.bus

    def refuse(*args, **kwargs):
        raise AssertionError("a real Inkbox client was created")

    monkeypatch.setattr(A2ABus, "_client", staticmethod(refuse))
    calls = dict(sent=[], replied=[])

    def send(caller, target, parts, message_id, context_id=None, task_id=None):
        calls["sent"].append(dict(caller=caller, target=target, text=parts[0]["text"], taskId=task_id))
        return dict(taskId=task_id or f"prov-{len(calls['sent'])}", contextId="prov-ctx", state="submitted")

    def reply(agent, provider_task_id, intent, parts):
        calls["replied"].append(dict(agent=agent, taskId=provider_task_id, intent=intent, text=parts[0]["text"]))

    monkeypatch.setattr(bus, "_inkbox_send", send)
    monkeypatch.setattr(bus, "_inkbox_reply", reply)
    return calls


def bus_of(client):
    return client.app.state.service.bus


def test_inkbox_carries_agent_messages_up_to_the_hourly_cap(client, inkbox, monkeypatch):
    bus = bus_of(client)
    monkeypatch.setenv("STEWARD_A2A_INKBOX_MAX_PER_HOUR", "3")
    tasks = [bus.send("director", "myer-manager", f"Plan the shutdown window {n}.", dict(kind="decision_request"), MY, deliver=False) for n in range(4)]
    assert [t["transport"] for t in tasks] == ["inkbox", "inkbox", "inkbox", "local"] and len(inkbox["sent"]) == 3
    assert tasks[3]["transportReason"] == CAP_REASON and "providerError" not in tasks[3] and tasks[3]["providerTaskId"] is None
    assert all(t.get("transportReason") is None and t["providerTaskId"] for t in tasks[:3])
    status = client.get("/api/a2a/transport").json()
    assert status == dict(status, mode="inkbox", inkboxAvailable=True, maxPerHour=3, sentLastHour=3, capReached=True)
    assert A2ABus(client.app.state.service).inkbox_sent_last_hour() == 3  # counted in the store: a restart keeps the count
    store = client.app.state.service.store
    store.meta(INKBOX_SENT_META, json.dumps([time.time() - 3700] * 3 + [time.time()]))  # older than an hour: no longer counted
    assert bus.inkbox_sent_last_hour() == 1
    assert bus.send("director", "myer-manager", "Plan the shutdown window 5.", dict(kind="decision_request"), MY, deliver=False)["transport"] == "inkbox"


def test_replies_and_follow_ups_count_and_stay_local_over_the_cap(client, inkbox, monkeypatch):
    bus = bus_of(client)
    monkeypatch.setenv("STEWARD_A2A_INKBOX_MAX_PER_HOUR", "2")
    task = bus.send("myer-manager", "myer-engineer", "Can you isolate P-101 at 14:00?", dict(kind="call"), MY, deliver=False)
    task = bus.reply("myer-engineer", task["id"], "progress", "Yes, after the duty pump takes over.", dict(kind="call"), deliver=False)
    task = bus.message("myer-manager", task["id"], "Good. Tag it out and tell compliance.", dict(kind="call"), deliver=False)
    assert task["transport"] == "inkbox" and len(inkbox["sent"]) == 1 and len(inkbox["replied"]) == 1  # the follow-up hit the cap
    last = task["messages"][-1]
    assert last["transport"] == "local" and last["transportReason"] == CAP_REASON
    assert "transport" not in task["messages"][1] and bus.inkbox_sent_last_hour() == 2


def test_machine_chatter_never_goes_over_inkbox(client, inkbox):
    bus = bus_of(client)
    status = bus.send("director", "myer-engineer", "Status check: anything blocking at Myer Plant Room?", dict(kind="status_check", simulated=True),
                      MY, simulated=True, deliver=False)
    ping = bus.send("director", "myer-engineer", "Are you there?", dict(kind="keepalive"), MY, deliver=False)
    ack = bus.send("myer-engineer", "myer-manager", "Noted.", dict(kind="notification"), MY, deliver=False)
    assert all(t["transport"] == "local" and t["transportReason"] == CHATTER_REASON for t in (status, ping, ack))
    replied = bus.reply("myer-engineer", status["id"], "complete", "Myer Plant Room: 0 open work item(s).", dict(simulated=True), deliver=False)
    assert replied["state"] == "completed" and inkbox == dict(sent=[], replied=[]) and bus.inkbox_sent_last_hour() == 0
    call = client.app.state.service.conversations.call(
        "myer-manager", "myer-compliance", "PV-301 examination", [dict(speaker="myer-manager", text="The examination is overdue."),
                                                                  dict(speaker="myer-compliance", text="I'll book the examiner for Tuesday.")])
    tasks = [bus.task(t) for t in call["a2aTaskIds"]]
    assert [t["transport"] for t in tasks] == ["inkbox"] and len(inkbox["sent"]) == 1 and len(inkbox["replied"]) == 1  # the two turns
    closing = tasks[0]["messages"][-1]
    assert closing["parts"][0]["text"] == "(end of call)" and closing["transportReason"] == CHATTER_REASON  # the bare closing stays local
    assert bus.inkbox_sent_last_hour() == 2


def test_an_outside_party_is_counted_but_never_held(client, inkbox, monkeypatch):
    bus = bus_of(client)
    monkeypatch.setenv("STEWARD_A2A_INKBOX_MAX_PER_HOUR", "0")
    assert bus.own_pair("director", "myer-manager") and not bus.own_pair("external:auditor", "myer-manager") and not bus.own_pair("operator", "director")
    assert bus._inkbox_gate("myer-engineer", "external:auditor", "ok", "status_check", False) is None  # answered over Inkbox as before
    assert bus.inkbox_sent_last_hour() == 1
    assert bus._inkbox_gate("director", "myer-manager", "Plan the window.", "decision_request", False) == CAP_REASON


def test_a_call_transcript_says_which_lines_went_over_inkbox(client, inkbox, monkeypatch):
    monkeypatch.setenv("STEWARD_A2A_INKBOX_MAX_PER_HOUR", "1")
    call = client.app.state.service.conversations.call(
        "myer-manager", "myer-compliance", "PV-301 examination", [dict(speaker="myer-manager", text="The examination is overdue."),
                                                                  dict(speaker="myer-compliance", text="I'll book the examiner for Tuesday.")])
    assert [line["transport"] for line in call["transcript"]] == ["inkbox", "local"]  # the second turn hit the hourly cap
    assert call["transport"] == "inkbox" and len(inkbox["sent"]) == 1 and inkbox["replied"] == []
