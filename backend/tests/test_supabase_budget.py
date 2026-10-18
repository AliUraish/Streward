"""Supabase budget guard: every cap refuses at its limit, counts persist, refusals record one event, nothing raises."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.store import Store
from src.supa_budget import CAPS, MB, Budget


class Clock:
    def __init__(self, moment=datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)):
        self.moment = moment

    def __call__(self):
        return self.moment


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


def budget_events(store):
    return [e for e in store.events("myer-plant") if e["type"] == "supabase.budget"]


def test_free_defaults_are_the_brief_and_pro_defaults_are_larger(store, monkeypatch):
    budget = Budget(store)
    caps = {key: entry["value"] for key, entry in budget.resolved().items()}
    assert budget.plan == "free"
    assert caps == dict(realtime_msgs_day=40_000, realtime_msgs_month=1_000_000, realtime_viewers=20, storage_mb=600, upload_mb=5, edge_calls_day=5_000,
                        db_mb=300, egress_mb_day=500, egress_mb_month=4_000, transform_origins_month=0)
    monkeypatch.setenv("SUPABASE_PLAN", "pro")
    pro = {key: entry["value"] for key, entry in Budget(store).resolved().items()}
    assert pro == dict(realtime_msgs_day=100_000, realtime_msgs_month=3_000_000, realtime_viewers=50, storage_mb=5_120, upload_mb=10, edge_calls_day=20_000,
                       db_mb=2_048, egress_mb_day=3_072, egress_mb_month=90_000, transform_origins_month=80)
    for cap in CAPS:  # every default sits well inside what its plan includes
        for plan, default in cap.defaults.items():
            limit = cap.limits[plan]
            if limit is None:
                assert default == 0
            elif cap.period != "object":
                assert default <= 0.9 * limit[0], (cap.key, plan)


def test_env_overrides_lower_caps_and_are_clamped_below_the_plan(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_CAP_REALTIME_MSGS_DAY", "12 # comment")
    monkeypatch.setenv("SUPABASE_CAP_STORAGE_MB", "99999999")
    resolved = Budget(store).resolved()
    assert resolved["realtime_msgs_day"] == dict(value=12, source="env", default=40_000, ceiling=1_800_000)
    assert resolved["storage_mb"]["value"] == int(1024 * 0.9) and resolved["storage_mb"]["source"] == "clamped"
    monkeypatch.setenv("SUPABASE_CAP_TRANSFORM_ORIGINS_MONTH", "500")
    assert Budget(store).cap("transform_origins_month") == 0  # not available on free whatever env says


def test_realtime_day_and_month_caps_count_fan_out_and_persist(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_CAP_REALTIME_MSGS_DAY", "10")
    monkeypatch.setenv("SUPABASE_CAP_REALTIME_MSGS_MONTH", "25")
    clock = Clock()
    budget = Budget(store, clock)
    viewers = 3
    assert budget.spend_realtime(1 + viewers) and budget.spend_realtime(1 + viewers)  # 8 of 10
    assert not budget.spend_realtime(1 + viewers)  # 12 > 10: refused, nothing spent
    assert budget.counter("realtime_msgs", "day") == 8
    assert Budget(store, clock).counter("realtime_msgs", "day") == 8  # persistent across instances (restart)
    clock.moment += timedelta(days=1)
    assert budget.counter("realtime_msgs", "day") == 0 and budget.counter("realtime_msgs", "month") == 8
    assert budget.spend_realtime(10) and not budget.spend_realtime(10)  # month cap 25: 18 + 10 > 25
    clock.moment += timedelta(days=1)
    assert not budget.spend_realtime(8)  # 18 + 8 > 25 even on a fresh day
    assert budget.spend_realtime(5, force=True) and budget.counter("realtime_msgs", "month") == 23  # spend that already happened is recorded


def test_viewer_cap(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_CAP_REALTIME_VIEWERS", "2")
    budget = Budget(store)
    assert budget.viewers_ok(2) and not budget.viewers_ok(3)


def test_storage_and_per_object_caps(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_CAP_STORAGE_MB", "2")
    monkeypatch.setenv("SUPABASE_CAP_UPLOAD_MB", "1")
    budget = Budget(store)
    assert budget.allow_upload(MB // 2) == (True, "")
    assert budget.allow_upload(MB + 1) == (False, "upload_mb")
    budget.add_storage(int(1.8 * MB))
    assert budget.allow_upload(MB // 2) == (False, "storage_mb")
    assert round(budget.storage_fraction(), 2) == 0.9
    budget.add_storage(-10 * MB)
    assert budget.storage_bytes() == 0  # never negative


def test_database_cap_states(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_CAP_DB_MB", "100")
    budget = Budget(store)
    assert budget.db_state() == "ok"  # unknown size never blocks
    budget.set_db_bytes(79 * MB)
    assert budget.db_state() == "ok"
    budget.set_db_bytes(81 * MB)
    assert budget.db_state() == "shed"
    budget.set_db_bytes(100 * MB)
    assert budget.db_state() == "full"
    assert store.meta("supa:budget:db_checked_at")


def test_edge_call_cap(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_CAP_EDGE_CALLS_DAY", "3")
    clock = Clock()
    budget = Budget(store, clock)
    budget.set_edge_calls("2026-10-18", 2)
    assert budget.edge_ok()
    budget.set_edge_calls("2026-10-18", 3)
    assert not budget.edge_ok()
    clock.moment += timedelta(days=1)
    assert budget.edge_ok()


def test_egress_day_and_month_caps(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_CAP_EGRESS_MB_DAY", "1")
    monkeypatch.setenv("SUPABASE_CAP_EGRESS_MB_MONTH", "2")
    clock = Clock()
    budget = Budget(store, clock)
    assert budget.spend_egress(MB - 10)
    assert not budget.spend_egress(20)
    clock.moment += timedelta(days=1)
    assert budget.spend_egress(MB - 10)
    clock.moment += timedelta(days=1)
    assert not budget.spend_egress(100)  # month: ~2 MB spent


def test_transform_origins_are_pro_only_and_counted_once_per_image(store, monkeypatch):
    assert not Budget(store).allow_transform("site/eyf-1.jpg")
    monkeypatch.setenv("SUPABASE_PLAN", "pro")
    monkeypatch.setenv("SUPABASE_CAP_TRANSFORM_ORIGINS_MONTH", "2")
    clock = Clock()
    budget = Budget(store, clock)
    assert budget.allow_transform("a") and budget.allow_transform("a") and budget.allow_transform("b")
    assert not budget.allow_transform("c")
    assert budget.counter("transform_origins", "month") == 2
    clock.moment += timedelta(days=31)
    assert budget.allow_transform("c")


def test_refusal_records_one_event_per_cap_per_day(store):
    clock = Clock()
    budget = Budget(store, clock)
    for _ in range(5):
        budget.refuse("realtime_msgs_day", "HUD skipped")
    budget.refuse("storage_mb", "frame kept local")
    assert len(budget_events(store)) == 2
    assert budget.refusals_today("realtime_msgs_day") == 5
    clock.moment += timedelta(days=1)
    budget.refuse("realtime_msgs_day", "HUD skipped again")
    assert len(budget_events(store)) == 3


def test_usage_reports_every_counter_against_cap_and_free_limit(store, monkeypatch):
    monkeypatch.setenv("SUPABASE_PLAN", "pro")
    budget = Budget(store)
    budget.spend_realtime(7)
    report = budget.usage()
    assert report["plan"] == "pro" and {c["key"] for c in report["counters"]} == {c.key for c in CAPS}
    realtime = next(c for c in report["counters"] if c["key"] == "realtime_msgs_day")
    assert realtime["used"] == 7 and realtime["cap"] == 100_000 and realtime["planLimit"] == dict(amount=5_000_000, period="month")
    assert realtime["freeLimit"] == dict(amount=2_000_000, period="month")
    transforms = next(c for c in report["counters"] if c["key"] == "transform_origins_month")
    assert transforms["freeLimit"] is None and transforms["planLimit"] == dict(amount=100, period="month")


def test_broken_counter_refuses_instead_of_overspending(store, monkeypatch):
    budget = Budget(store)
    monkeypatch.setattr(store, "connect", lambda: (_ for _ in ()).throw(RuntimeError("disk")))
    assert budget.spend_realtime(1) is False
    budget.refuse("realtime_msgs_day", "never raises")  # swallowed


def test_hud_broadcast_cost_is_one_plus_viewers_and_stops_at_the_cap(store, monkeypatch):
    from src.supa_client import Supa
    from src.supa_realtime import Hud

    monkeypatch.setenv("SUPABASE_CAP_REALTIME_MSGS_DAY", "12")
    sent = []

    def handler(request: httpx.Request):
        sent.append(json.loads(request.content))
        return httpx.Response(202)

    budget = Budget(store)
    supa = Supa("https://example.supabase.co", "sb_secret_test", "sb_publishable_test", httpx.MockTransport(handler))
    hud = Hud(supa, budget, ["myer-plant", "bristol-pumps"])
    assert hud.push("myer-plant", dict(type="agent_action", text="nobody watching")) is False  # no viewers, nothing queued
    assert hud.heartbeat("myer-plant", "viewer-aaaaaa")["realtime"] is True  # join: 2 + 0
    assert hud.heartbeat("myer-plant", "viewer-bbbbbb")["realtime"] is True  # join: 2 + 1
    assert budget.counter("realtime_msgs", "day") == 5
    hud.push("myer-plant", dict(type="agent_action", text="call +14155550123 now"))
    hud.push("myer-plant", dict(type="issue_change", issueId="i1", status="open"))
    hud.push("myer-plant", dict(type="issue_change", issueId="i1", status="resolved"))  # coalesced per issue
    hud.tick()
    assert len(sent) == 1 and budget.counter("realtime_msgs", "day") == 8  # 1 sent + 2 viewers
    message = sent[0]["messages"][0]
    assert message["topic"] == "site:myer-plant:hud" and message["private"] is True and message["event"] == "hud"
    assert [e["type"] for e in message["payload"]["events"]] == ["agent_action", "issue_change"]
    assert message["payload"]["events"][1]["status"] == "resolved"
    hud.push("myer-plant", dict(type="agent_action", text="second"))
    hud.tick()  # within the 1 s window: not sent yet
    assert len(sent) == 1
    hud.last_sent["myer-plant"] = 0
    hud.tick()  # 8 + 3 = 11 <= 12
    assert len(sent) == 2
    hud.push("myer-plant", dict(type="agent_action", text="third"))
    hud.last_sent["myer-plant"] = 0
    hud.tick()  # 11 + 3 > 12: refused, nothing sent
    assert len(sent) == 2 and budget.refusals_today("realtime_msgs_day") >= 1
    assert hud.heartbeat("myer-plant", "viewer-aaaaaa")["realtime"] is False  # budget spent: viewers fall back to polling
