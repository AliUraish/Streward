"""The maintenance planner (owner, Oct 18 2026): nobody asks the agents to schedule maintenance. Each site's Manager books a
window on its own for every obligation that is overdue or due within 14 days, in the site's local working hours; before
booking it checks the other sites' windows of the same kind within ±7 days and, when there is one, the two Managers hold a
cross-site A2A call and link the visits; the team is told over A2A; the change is emitted. Paced (one new window per site
per 10 minutes) and idempotent. Every external transport is off; nothing leaves the machine."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.maintenance_planner import choose_slot

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
TZ = {MY: "Australia/Melbourne", BR: "Europe/London", TM: "Asia/Tokyo"}
PREFIX = {MY: "myer", BR: "bristol", TM: "tomioka"}
FIRST = {MY: "ob-my-l901-esm", BR: "ob-br-sp102-pipework", TM: "ob-tm-exit-drill"}


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


def windows(client, site):
    return {w["id"]: w for w in client.get(f"/api/maintenance?siteId={site}").json()}


def planner_windows(client, site):
    return [w for w in windows(client, site).values() if w.get("origin") == "planner"]


def test_the_planner_books_due_obligations_in_each_sites_working_hours(client):
    service = svc(client)
    moment = datetime.now(timezone.utc)
    booked = service.maintenance_planner.tick(moment)
    assert {w["siteIds"][0]: w["obligationId"] for w in booked} == FIRST  # the overdue gaps first, one per site
    for window in booked:
        site = window["siteIds"][0]
        obligation = next(o for o in client.get(f"/api/properties/{site}/obligations").json() if o["id"] == window["obligationId"])
        manager = f"{PREFIX[site]}-manager"
        assert window["status"] == "approved" and window["origin"] == "planner" and window["proposedBy"] == window["approvedBy"] == manager
        assert window["synthetic"] is True and window["timeZone"] == TZ[site] and window["assetTags"] == [obligation["assetTag"]]
        assert window["ownerId"] == obligation["ownerId"] and window["regulationIds"] == obligation["regulationIds"] and window["regulationIds"]
        start, end = parse(window["startAt"]).astimezone(ZoneInfo(TZ[site])), parse(window["endAt"]).astimezone(ZoneInfo(TZ[site]))
        assert start.weekday() < 5 and 8 <= start.hour and end.hour <= 17 and end > start and window["date"] == start.date().isoformat()
        assert start - moment >= timedelta(hours=12)  # a contractor needs notice
        assert window["localStart"].endswith(start.strftime("%H:%M")) and window["examiner"]
        text = f"{window['scope']} {window['examiner']}".lower()
        assert "synthetic" not in text and "demo" not in text
        assert window["id"] in windows(client, site)  # the same windows the maintenance API lists
        changes = client.get(f"/api/properties/{site}/changes?limit=1000").json()["changes"]
        change = next(c for c in changes if c["type"] == "maintenance" and c["refId"] == window["id"])
        assert change["assetTag"] == obligation["assetTag"] and "booked" in change["summary"]
        team = [client.get(f"/api/conversations/{cid}").json() for cid in window["teamConversationIds"]]
        assert [c["participants"] for c in team] == [[manager, f"{PREFIX[site]}-{role}"] for role in ("compliance", "engineer", "technician")]
        assert all(c["kind"] == "message" and c["status"] == "ended" and len(c["transcript"]) == 2 and c["synthetic"] is True for c in team)
        assert all(line.get("taskId") for c in team for line in c["transcript"])  # over the A2A bus
        issue = client.get(f"/api/issues/iss-{site[:2]}-compliance-{obligation['id']}").json()
        assert issue["maintenanceWindowId"] == window["id"] and issue["status"] == "open"  # booked, not yet done
        assert obligation["status"] == "overdue"  # booking does not close the gap
    queues = {s["siteId"]: {q["obligationId"]: q for q in s["queue"]} for s in client.get("/api/maintenance-planner").json()["sites"]}
    assert queues[BR]["ob-br-v504-gland"]["action"] == queues[TM]["ob-tm-tr202-strap"]["action"] == "waiting"  # blocked: not booked
    assert queues[BR]["ob-br-walkway-check"]["action"] == queues[TM]["ob-tm-humidity-watch"]["action"] == "round"
    assert queues[MY]["ob-my-hotwork-permit"]["action"] == "paperwork"
    assert all(queues[s][FIRST[s]]["action"] == "covered" for s in FIRST)


def test_the_planner_coordinates_with_another_sites_window_of_the_same_kind(client):
    service = svc(client)
    moment = datetime.now(timezone.utc)
    # Myer's seeded TK-201 examiner visit, two days after the slot Bristol's overdue pipework examination will take.
    slot, _ = choose_slot(BR, "pressure", moment, None, True)
    exam = service.store.get("maintenance_window", "mw-my-tk201-exam", "")
    exam["date"] = (slot.astimezone(ZoneInfo(TZ[BR])).date() + timedelta(days=2)).isoformat()
    service.maintenance._put(exam)
    booked = {w["obligationId"]: w for w in service.maintenance_planner.tick(moment)}
    bristol, myer, tomioka = booked["ob-br-sp102-pipework"], booked["ob-my-l901-esm"], booked["ob-tm-exit-drill"]

    assert bristol["linkedWindowIds"] == ["mw-my-tk201-exam"] and bristol["coordination"]["mode"] == "linked"
    assert bristol["coordination"]["siteId"] == MY and bristol["coordination"]["sharedContractor"] is True
    assert bristol["coordination"]["relation"] == "2 days before yours" and bristol["examiner"].startswith("Northgate Engineering Inspection")
    call = client.get(f"/api/conversations/{bristol['conversationId']}").json()
    assert call["kind"] == "call" and call["participants"] == ["bristol-manager", "myer-manager"] and call["siteIds"] == [BR, MY]
    assert len(call["transcript"]) == 5 and all(line.get("taskId") and line["transport"] == "local" for line in call["transcript"])
    assert [line["speaker"] for line in call["transcript"]] == ["bristol-manager", "myer-manager"] * 2 + ["bristol-manager"]
    assert "SP-102" in call["transcript"][0]["text"] and "TK-201" in call["transcript"][0]["text"] and "6 days overdue" in call["transcript"][0]["text"]
    assert "same examining body" in call["transcript"][2]["text"] and "London time" in call["transcript"][2]["text"]
    assert call["summary"]["headline"].startswith("Bristol booked SP-102") and call["maintenanceWindowId"] == bristol["id"]
    assert call["issueId"] == "iss-br-compliance-ob-br-sp102-pipework" and call["status"] == "ended"
    assert "mw-plan-br-sp102" in windows(client, MY)["mw-my-tk201-exam"]["linkedWindowIds"][0]  # the back link on Myer's window
    assert any(c["type"] == "maintenance" and c["refId"] == "mw-my-tk201-exam" and "linked" in c["summary"]
               for c in client.get(f"/api/properties/{MY}/changes?limit=1000").json()["changes"])

    # Tomioka's overdue exit drill is fire-safety work; Myer booked its L-901 fire-safety check in the same pass.
    assert tomioka["linkedWindowIds"] == [myer["id"]] and tomioka["coordination"]["siteId"] == MY
    assert windows(client, MY)[myer["id"]]["linkedWindowIds"] == [tomioka["id"]]
    talk = client.get(f"/api/conversations/{tomioka['conversationId']}").json()
    assert talk["participants"] == ["tomioka-manager", "myer-manager"] and "D-701" in talk["transcript"][0]["text"] and "L-901" in talk["transcript"][0]["text"]
    assert myer["conversationId"] is None and myer["coordination"] is None  # nothing of its kind elsewhere when Myer booked
    for conversation in (call, talk):
        text = " ".join(line["text"] for line in conversation["transcript"]).lower()
        assert "synthetic" not in text and "demo" not in text and "{" not in text


def test_the_planner_is_paced_and_idempotent(client):
    service = svc(client)
    planner = service.maintenance_planner
    start = datetime.now(timezone.utc)
    assert len(planner.tick(start)) == 3
    assert planner.tick(start) == [] and planner.tick(start + timedelta(minutes=9)) == []  # one new window per site per 10 minutes
    assert planner.book(MY, "ob-my-l901-esm", start) is None  # the same cycle is never booked twice
    second = planner.tick(start + timedelta(minutes=11))
    assert [w["obligationId"] for w in second] == ["ob-my-fe1001-monthly"]  # Myer's next due obligation; nothing else is due elsewhere
    extinguisher = second[0]
    due = parse(next(o for o in client.get(f"/api/properties/{MY}/obligations").json() if o["id"] == "ob-my-fe1001-monthly")["dueAt"])
    assert parse(extinguisher["startAt"]) <= due - timedelta(days=1) and extinguisher["dueStatus"] == "due_soon"
    assert extinguisher["examiner"] == "Meera Vasquez-Lin (site safety lead, in-house)"  # a monthly check is done in-house
    assert planner.tick(start + timedelta(minutes=22)) == [] and planner.tick(start + timedelta(minutes=40)) == []
    per_obligation = {}
    for site in (MY, BR, TM):
        for window in planner_windows(client, site):
            per_obligation[window["obligationId"]] = per_obligation.get(window["obligationId"], 0) + 1
    assert per_obligation == {"ob-my-l901-esm": 1, "ob-br-sp102-pipework": 1, "ob-tm-exit-drill": 1, "ob-my-fe1001-monthly": 1}
    status = client.get("/api/maintenance-planner").json()
    assert status["paceSeconds"] == 600 and status["state"] == "idle" and len(status["recent"]) == 4
    assert {s["siteId"]: s["timeZone"] for s in status["sites"]} == TZ


def test_a_planner_window_is_done_once_its_obligation_closes(client):
    service = svc(client)
    start = datetime.now(timezone.utc)
    window = next(w for w in service.maintenance_planner.tick(start) if w["obligationId"] == "ob-my-l901-esm")
    service.people.complete_obligation("ob-my-l901-esm", "myer-compliance", note="Discharge test passed.")
    service.maintenance_planner.tick(start + timedelta(minutes=11))
    done = windows(client, MY)[window["id"]]
    assert done["status"] == "done" and "closed" in done["closedReason"]
    assert any(c["type"] == "maintenance" and c["refId"] == window["id"] and "done" in c["summary"]
               for c in client.get(f"/api/properties/{MY}/changes?limit=1000").json()["changes"])


class LiveMemory:
    """A Supermemory client stub with the live switch on; it never leaves the process."""
    live = configured = True

    def add(self, *args, **kwargs):
        return {}

    def search(self, *args, **kwargs):
        return {"results": []}


def test_the_planner_pauses_while_a_live_path_is_on(client, monkeypatch):
    service = svc(client)
    monkeypatch.setattr(service.bus, "inkbox_available", lambda: True)  # A2A over Inkbox only connects Steward's own identities
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")  # the owner channel is capped on its own
    assert service.maintenance_planner.live_switches() == []  # neither pauses the planner
    original = service.memory.client
    monkeypatch.setattr(service.memory, "client", LiveMemory())  # live Supermemory still does
    assert service.maintenance_planner.tick() == []
    status = client.get("/api/maintenance-planner").json()
    assert status["state"] == "paused" and status["liveSwitches"] == ["STEWARD_SUPERMEMORY_LIVE"] and "Inkbox" not in status["reason"]
    assert not any(planner_windows(client, site) for site in (MY, BR, TM))
    monkeypatch.setattr(service.memory, "client", original)
    booked = service.maintenance_planner.tick()  # Inkbox A2A still "available": the planner books and tells the teams
    assert booked and client.get("/api/maintenance-planner").json()["state"] == "booked"
    assert all(t["transport"] == "local" for t in client.get("/api/a2a/tasks").json())  # no identities configured: nothing left the process


def test_people_can_still_propose_and_approve_by_hand(client):
    svc(client).maintenance_planner.tick()
    proposal = client.post("/api/maintenance", json={"siteIds": [MY], "date": "2026-11-04", "scope": "Pump seals"}, headers={"X-Steward-Actor": "myer-manager"})
    assert proposal.status_code == 201 and proposal.json()["status"] == "proposed"
    approved = client.post(f"/api/maintenance/{proposal.json()['id']}/approve", headers={"X-Steward-Actor": "myer-manager"}).json()
    assert approved["status"] == "approved" and approved.get("origin") is None
