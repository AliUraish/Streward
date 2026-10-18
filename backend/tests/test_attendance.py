"""Employee logs and the People Officer (contract 8 §5): the badge log per employee (deterministic 14-day backfill, today's
entry once its check-in has passed), the late-twice rule (one case per employee per 7 days, one in progress per site, the
backfill never opens one, the seeded Myer shift technician's pair does), the People Officer's chat with the site manager and
call to the employee, every outcome of that call, and the routes. The outbox, phone calls and chat writer are the contract-8
fakes; nothing leaves the process."""
import json
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from contract8_fakes import install_fakes
from src.attendance import PURPOSE, parse_shift
from src.main import create_app

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
TECH, SAFETY = "crew-my-shift-tech", "crew-my-safety-lead"
TZ = {MY: "Australia/Melbourne", BR: "Europe/London", TM: "Asia/Tokyo"}
# Sunday 18 Oct 2026: 23:00 in Melbourne, 13:00 in London, 21:00 in Tokyo.
M = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def entries(service, site, crew=None):
    return service.attendance.entries(site, crew)


def recaps(fakes):
    return [i for i in fakes.outbox.items if i.get("purpose") == "attendance_recap"]


def open_seeded_case(client):
    service = svc(client)
    fakes = install_fakes(service)
    result = service.attendance.check(M)
    assert len(result["opened"]) == 1
    case = service.attendance.case(result["opened"][0])
    return service, fakes, case


def set_late(service, site, crew, day, minutes):
    entry = service.store.get("attendance_entry", f"att-{crew}-{day}", site)
    assert entry, day
    entry.update(status="late", lateMinutes=minutes, checkIn="07:" + str(minutes).zfill(2), onSite=False)
    service.store.put("attendance_entry", entry, site)


# ---- roster ---------------------------------------------------------------------------------------------------------


def test_the_roster_takes_people_with_a_named_shift_only(client):
    service = svc(client)
    assert {e["crewId"] for e in service.attendance.roster(MY)} == {"crew-my-safety-lead", TECH, "crew-my-facilities-manager"}
    assert {e["crewId"] for e in service.attendance.roster(BR)} == {"crew-br-restoration-lead", "crew-br-visitor-lead"}
    assert len(service.attendance.roster(TM)) == 6  # every Tomioka crew member but the duty engineer
    myer = {e["crewId"]: e for e in service.attendance.roster(MY)}
    assert myer["crew-my-facilities-manager"]["shiftStart"] == "08:30" and myer["crew-my-facilities-manager"]["workingDays"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    bristol = {e["crewId"]: e for e in service.attendance.roster(BR)}
    assert bristol["crew-br-visitor-lead"]["workingDays"] == ["Sat", "Sun"]  # "open days": the pump house's open weekend
    assert bristol["crew-br-restoration-lead"]["workingDays"] == ["Tue", "Wed", "Thu", "Fri", "Sat"]


@pytest.mark.parametrize("text,site,expected", [
    ("days 07:00-15:00", MY, ((0, 1, 2, 3, 4), "07:00", "15:00", False)),
    ("Tue-Sat 08:00-16:00", BR, ((1, 2, 3, 4, 5), "08:00", "16:00", False)),
    ("Mon-Fri 08:30-17:15", TM, ((0, 1, 2, 3, 4), "08:30", "17:15", False)),
    ("Tue-Sun 08:30-17:00", TM, ((1, 2, 3, 4, 5, 6), "08:30", "17:00", False)),
    ("opening days 08:30-17:30", TM, ((1, 2, 3, 4, 5, 6), "08:30", "17:30", False)),
    ("opening hours 09:00-17:00", TM, ((1, 2, 3, 4, 5, 6), "09:00", "17:00", False)),
    ("open days 10:00-17:00", BR, ((5, 6), "10:00", "17:00", False)),
    ("office hours", MY, ((0, 1, 2, 3, 4), "09:00", "17:00", False)),
    ("days 08:00-16:30, rest day today", TM, ((0, 1, 2, 3, 4), "08:00", "16:30", True)),
    ("something else", MY, ((0, 1, 2, 3, 4), "09:00", "17:00", False)),
])
def test_shift_text_is_parsed(text, site, expected):
    shift = parse_shift(text, site)
    assert (shift["days"], shift["start"], shift["end"], shift["restToday"]) == expected


@pytest.mark.parametrize("text", ["on call, 24 h this week", "call-out, 4 h response", "by appointment, next visit booked in 3 weeks",
                                  "steam days only, alternate Sundays"])
def test_people_without_a_shift_are_not_on_the_badge_log(text):
    assert parse_shift(text, BR) is None


# ---- the badge log ------------------------------------------------------------------------------------------------


def test_the_backfill_is_deterministic_written_once_and_on_working_days_only(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    logs = []
    for name in ("a", "b"):
        with TestClient(create_app(tmp_path / name, start_workers=False)) as client:
            service = svc(client)
            assert service.attendance.generate(M) > 0
            assert service.attendance.generate(M) == 0  # written once
            rows = [(e["id"], e["status"], e["checkIn"], e["checkOut"], e["lateMinutes"]) for site in (MY, BR, TM) for e in entries(service, site)]
            logs.append(sorted(rows))
            for site in (MY, BR, TM):
                roster = {e["crewId"]: e for e in service.attendance.roster(site)}
                today = M.astimezone(ZoneInfo(TZ[site])).date()
                for entry in entries(service, site):
                    day = date.fromisoformat(entry["date"])
                    assert today - timedelta(days=14) <= day <= today
                    assert entry["weekday"] in roster[entry["crewId"]]["workingDays"]
                    assert entry["status"] in ("on_time", "late", "absent", "rest_day")
                    if entry["status"] == "late":
                        assert entry["lateMinutes"] > 10 and entry["checkIn"]
    assert logs[0] == logs[1] and len(logs[0]) > 60


def test_todays_entry_appears_after_check_in_and_gets_its_check_out_later(client):
    service = svc(client)
    service.attendance.generate(M)  # 13:00 on Sunday in Bristol: the visitor lead's 10:00-17:00 Sunday shift is under way
    today = next((e for e in entries(service, BR, "crew-br-visitor-lead") if e["date"] == "2026-10-18"), None)
    assert today is not None
    if today["status"] != "absent":
        assert today["onSite"] is True and today["checkIn"] and today["checkOut"] is None
        service.attendance.generate(M + timedelta(hours=6))  # 19:00 in Bristol
        today = next(e for e in entries(service, BR, "crew-br-visitor-lead") if e["date"] == "2026-10-18")
        assert today["onSite"] is False and today["checkOut"]
    # Myer's Monday shift has not started at 23:00 on Sunday: no entry for Monday yet.
    assert not [e for e in entries(service, MY) if e["date"] == "2026-10-19"]


def test_rest_day_today_marks_the_first_working_day_the_log_sees(client):
    service = svc(client)
    service.attendance.generate(M)  # Sunday 21:00 in Tokyo: the fire officer's first working day is Monday 19 October
    service.attendance.generate(M + timedelta(hours=12))  # Monday 09:00 in Tokyo
    monday = next(e for e in entries(service, TM, "crew-tm-fire-officer") if e["date"] == "2026-10-19")
    assert monday["status"] == "rest_day" and monday["checkIn"] is None


# ---- the rule -------------------------------------------------------------------------------------------------------


def test_the_seeded_case_fires_once_on_the_first_check(client):
    service, fakes, case = open_seeded_case(client)
    assert case["crewId"] == TECH and case["siteId"] == MY and case["status"] == "calling"
    assert [(d["date"], d["checkIn"], d["lateMinutes"]) for d in case["days"]] == [("2026-10-15", "07:38", 38), ("2026-10-16", "07:52", 52)]
    assert case["nextShift"]["date"] == "2026-10-19" and case["nextShift"]["start"] == "07:00"
    assert len(service.attendance.cases()) == 1  # the backfill itself never opens a case
    again = service.attendance.check(M + timedelta(minutes=15))
    assert again["opened"] == [] and len(service.attendance.cases()) == 1
    fakes.voice_calls.finish(case["callId"], result="agreed", chosen_option_id="keep-reminder")
    assert service.attendance.check(M + timedelta(hours=1))["opened"] == []  # one case per employee per 7 days
    changes = [c for c in service.store.all("change", MY) if c["type"] == "attendance" and c["refId"] == case["id"]]
    assert len(changes) >= 3  # opened, calling, resolved


def test_one_case_per_employee_per_seven_days_and_one_in_progress_per_site(client):
    service, fakes, case = open_seeded_case(client)
    # The safety lead is late on the same two days while the technician's case is in progress: it waits.
    for day, minutes in (("2026-10-15", 25), ("2026-10-16", 31)):
        set_late(service, MY, SAFETY, day, minutes)
        entry = service.store.get("attendance_entry", f"att-{SAFETY}-{day}", MY)
        entry["seeded"] = True
        service.store.put("attendance_entry", entry, MY)
    assert service.attendance.rule(M + timedelta(minutes=5)) == []
    fakes.voice_calls.finish(case["callId"], result="agreed", chosen_option_id="start-0730")
    second = service.attendance.rule(M + timedelta(minutes=10))
    assert [c["crewId"] for c in second] == [SAFETY]
    service.attendance.dispatch(second[0]["id"])  # inline without workers: the chat, then the call
    fakes.voice_calls.finish(service.attendance.case(second[0]["id"])["callId"], result="declined")
    assert service.attendance.case(second[0]["id"])["status"] == "resolved"
    # The technician is late again within the week: no second case until 7 days have passed.
    tuesday = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)  # Wednesday 00:00 in Melbourne
    service.attendance.generate(tuesday)
    for day in ("2026-10-19", "2026-10-20"):
        set_late(service, MY, TECH, day, 44)
    assert all(c["crewId"] != TECH for c in service.attendance.rule(tuesday))
    later = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)  # Wednesday 28 Oct 00:00 in Melbourne
    service.attendance.generate(later)
    for entry in entries(service, MY):  # only the technician is late in the last week (a late run can carry on for others)
        if entry["crewId"] != TECH and entry["date"] >= "2026-10-21" and entry["status"] == "late":
            entry.update(status="on_time", lateMinutes=0)
            service.store.put("attendance_entry", entry, MY)
    for day in ("2026-10-26", "2026-10-27"):
        set_late(service, MY, TECH, day, 40)
    opened = service.attendance.rule(later)
    assert [c["crewId"] for c in opened] == [TECH]


# ---- the People Officer -----------------------------------------------------------------------------------------


def test_the_chat_and_the_call_are_requested_with_the_contract_fields(client):
    service, fakes, case = open_seeded_case(client)
    run = fakes.chats.runs[-1]
    assert run["convener"] == "people-officer" and run["participants"] == ["people-officer", "myer-manager"] and run["siteIds"] == [MY]
    assert (run["minTurns"], run["maxTurns"]) == (6, 8) and set(run["briefs"]) == {"people-officer", "myer-manager"}
    assert "07:38" in run["shared"] and "07:52" in run["shared"] and run["refs"]["caseId"] == case["id"]
    assert case["conversationIds"] and service.conversations.get(case["conversationIds"][0])["kind"] == "call"
    call = fakes.voice_calls.calls[-1]
    assert call["id"] == case["callId"] and call["purpose"] == PURPOSE and call["caller"] == "people-officer"
    assert call["calleeRole"] == "employee" and call["calleeName"] == case["name"] and call["siteId"] == MY
    assert [o["id"] for o in call["options"]] == ["start-0730", "swap-late", "keep-reminder"]
    assert call["canDo"] == ["note", "email_file"] and call["dedupeKey"] == f"attendance:{case['id']}"
    assert call["refs"]["caseId"] == case["id"] and call["file"]["cc"] == ["myer-manager"]
    assert "Monday 19 October" in call["goal"] and "not a disciplinary call" in " ".join(call["facts"])
    text = json.dumps(call)
    assert not re.search(r"synthetic|demo|simulat|scenario|\bAI\b", text, re.I)


@pytest.mark.parametrize("result,option,status,adjustment", [
    ("agreed", "start-0730", "resolved", ("later_start", "07:30")),
    ("agreed", "swap-late", "resolved", ("late_shift", "15:30")),
    ("agreed", "keep-reminder", "resolved", None),
    ("agreed", None, "resolved", None),  # no option picked: undecided
    ("declined", None, "resolved", None),
    ("undecided", None, "resolved", None),
    ("failed", None, "unreachable", None),
])
def test_every_outcome_updates_the_case_tells_the_manager_and_queues_the_recap_once(client, result, option, status, adjustment):
    service, fakes, case = open_seeded_case(client)
    handled = fakes.voice_calls.finish(case["callId"], result=result, chosen_option_id=option, summary="The bus timetable changed")
    case = service.attendance.case(case["id"])
    assert case["status"] == status and handled["handled"] == ["email_file"]
    expected = "undecided" if (result == "agreed" and option is None) else result
    assert case["outcome"]["result"] == expected
    if adjustment:
        assert (case["outcome"]["adjustment"]["kind"], case["outcome"]["adjustment"]["start"]) == adjustment
    else:
        assert case["outcome"]["adjustment"] is None
    items = recaps(fakes)
    assert len(items) == 1 and items[0]["toRole"] == "employee" and items[0]["cc"] == ["myer-manager"] and items[0]["sender"] == "people-officer"
    assert items[0]["dedupeKey"] == f"attendance-recap:{case['id']}" and case["recapOutboxId"] == items[0]["id"]
    manager = service.conversations.get(case["managerConversationId"])
    assert [line["agentId"] for line in manager["transcript"]] == ["people-officer", "myer-manager"] and manager["summary"]
    for day in case["dayDates"]:
        entry = service.store.get("attendance_entry", f"att-{TECH}-{day}", MY)
        assert entry["caseId"] == case["id"] and entry["note"]
    # The handler runs once: a second delivery changes nothing.
    service.attendance.on_call(fakes.voice_calls.get(case["callId"]))
    assert len(recaps(fakes)) == 1


def test_voicemail_is_retried_before_the_case_is_unreachable(client):
    service, fakes, case = open_seeded_case(client)
    fakes.voice_calls.finish(case["callId"], result="voicemail")
    assert service.attendance.case(case["id"])["status"] == "calling" and recaps(fakes) == []
    retry = fakes.voice_calls.request(purpose=PURPOSE, caller="people-officer", callee_role="employee", callee_name=case["name"], site_id=MY,
                                      goal="again", facts=[], refs={})
    retry.update(retryOf=case["callId"], attempt=2)
    fakes.voice_calls.finish(retry["id"], result="voicemail")
    case = service.attendance.case(case["id"])
    assert case["status"] == "unreachable" and case["callId"] == retry["id"] and len(recaps(fakes)) == 1
    assert recaps(fakes)[0]["subject"] == "I tried to call you about your start times"


@pytest.mark.parametrize("held", ["dry_run", "capped"])
def test_a_held_call_still_tells_the_manager_and_sends_the_email(client, held):
    service = svc(client)
    fakes = install_fakes(service)
    original = fakes.voice_calls.request

    def request(**kwargs):
        record = original(**kwargs)
        record.update(status=held, reason="Calls to people are switched off" if held == "dry_run" else "The daily call limit is reached")
        return record

    fakes.voice_calls.request = request
    opened = service.attendance.check(M)["opened"]
    case = service.attendance.case(opened[0])
    assert case["status"] == "held" and case["outcome"]["result"] == "held" and case["outcome"]["reason"]
    assert len(recaps(fakes)) == 1 and recaps(fakes)[0]["subject"] == "About your start times last week"
    assert case["managerConversationId"]
    service.attendance.on_call(fakes.voice_calls.get(case["callId"]))  # a later handler call for the held call changes nothing
    assert len(recaps(fakes)) == 1 and service.attendance.case(case["id"])["status"] == "held"


def test_an_email_follow_up_already_sent_is_not_sent_again(client):
    service, fakes, case = open_seeded_case(client)
    call = fakes.voice_calls.get(case["callId"])
    call.update(status="ended", outcome=dict(result="agreed", decision="", summary="", chosenOptionId="keep-reminder", interpretedBy="rules",
                                             followUps=[dict(type="email_file", cc=["myer-manager"], status="done", ref="obx-sent")]))
    handled = service.attendance.on_call(call)
    case = service.attendance.case(case["id"])
    assert handled["handled"] == [] and recaps(fakes) == [] and case["recapOutboxId"] == "obx-sent" and case["status"] == "resolved"


def test_an_agreed_later_start_moves_the_expected_start(client):
    service, fakes, case = open_seeded_case(client)
    fakes.voice_calls.finish(case["callId"], result="agreed", chosen_option_id="start-0730")
    monday = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)  # 12:00 on Monday in Melbourne
    service.attendance.generate(monday)
    entry = next(e for e in entries(service, MY, TECH) if e["date"] == "2026-10-19")
    assert entry["shiftStart"] == "07:30" and entry["shiftEnd"] == "16:00"


def test_the_chat_writer_failing_falls_back_to_the_template_chat(client):
    service = svc(client)
    fakes = install_fakes(service)

    def broken(**kwargs):
        raise RuntimeError("writer down")

    fakes.chats.run = broken
    case = service.attendance.case(service.attendance.check(M)["opened"][0])
    conversation = service.conversations.get(case["conversationIds"][0])
    assert len(conversation["transcript"]) == 6 and case["status"] == "calling"


# ---- routes ---------------------------------------------------------------------------------------------------------


def test_routes_are_read_only_for_people_and_the_check_is_for_the_owners_agent(client):
    service, fakes, case = open_seeded_case(client)
    log = client.get(f"/api/attendance?siteId={MY}&days=14")
    assert log.status_code == 200
    body = log.json()
    assert body["siteId"] == MY and len(body["employees"]) == 3 and body["timeZone"] == "Australia/Melbourne" and len(body["days"]) == 14
    tech = next(e for e in body["employees"] if e["crewId"] == TECH)
    assert tech["entries"] and tech["latestCase"]["id"] == case["id"] and any("People Officer" in f for f in tech["flags"])
    everything = client.get("/api/attendance").json()
    assert [s["siteId"] for s in everything["sites"]] == [MY, BR, TM] and "state" in everything["status"]
    cases = client.get(f"/api/attendance/cases?siteId={MY}").json()
    assert [c["id"] for c in cases] == [case["id"]]
    assert client.get(f"/api/attendance/cases/{case['id']}").json()["crewId"] == TECH
    assert client.get("/api/attendance/cases/attc-missing").status_code == 404
    text = log.text + json.dumps(everything) + json.dumps(cases)
    assert not re.search(r"synthetic|generator|seeded|demo|simulat|scenario", text, re.I)
    assert "@" not in text and not re.search(r"\+\d{7,}", text)  # no address or phone number anywhere
    assert not re.search(r'"(phone|email|to)"\s*:', text)
    assert client.post("/api/attendance/check", headers={"x-steward-actor": "myer-manager"}).status_code == 403
    assert client.post("/api/attendance/check", headers={"x-steward-actor": "people-officer"}).status_code == 403
    ran = client.post("/api/attendance/check", headers={"x-steward-actor": "operator"})
    assert ran.status_code == 200 and "opened" in ran.json()


def test_the_operator_can_seed_a_late_pair_for_the_live_check(client):
    service, fakes, case = open_seeded_case(client)
    fakes.voice_calls.finish(case["callId"], result="agreed", chosen_option_id="keep-reminder")
    seeded = service.attendance.check(M + timedelta(minutes=30), seed=True, crew_id=SAFETY)
    assert seeded["seeded"]["crewId"] == SAFETY and len(seeded["seeded"]["dates"]) == 2
    assert [service.attendance.case(c)["crewId"] for c in seeded["opened"]] == [SAFETY]
    with pytest.raises(Exception):
        service.attendance.check(M + timedelta(minutes=40), seed=True, crew_id=TECH)  # a case in progress at Myer


def test_the_loop_runs_only_with_the_workers_and_the_switch(client, monkeypatch):
    from types import SimpleNamespace
    from src.attendance import AttendanceService
    stub = SimpleNamespace(start_workers=True, store=svc(client).store)
    monkeypatch.setenv("STEWARD_ATTENDANCE", "false")
    service = AttendanceService(stub)
    service.start()
    assert service.status()["state"] == "off" and service._thread is None
    monkeypatch.setenv("STEWARD_ATTENDANCE", "true")
    monkeypatch.setenv("STEWARD_ATTENDANCE_FIRST_DELAY_SECONDS", "3600")
    service.start()
    assert service.status()["state"] == "running" and service._thread.is_alive() and service.status()["nextCheckAt"]
    service.close()
    assert service.status()["state"] == "stopped" and not service._thread.is_alive()
    assert svc(client).attendance.status()["state"] == "idle"  # the test app runs without workers: nothing was started
