"""A wait that names one specific run fires at once when that run already finished (lost wake-up guard)."""
from types import SimpleNamespace

from src.store import Store
from src.waits import WaitHub


def hub(tmp_path):
    store = Store(tmp_path / "data")
    service = SimpleNamespace(store=store, require_property=lambda site_id: None)
    return WaitHub(service)


def scenario_change(run_id: str, status: str, version: int = 1) -> tuple[dict, dict]:
    change = dict(version=version, type="scenario", propertyId="myer-plant", refId=run_id, summary="step", at="2026-10-18T07:48:25Z")
    extra = dict(scenarioId="my-overpressure", runId=run_id, status=status)
    return change, extra


def test_wait_created_after_the_event_fires_immediately(tmp_path):
    h = hub(tmp_path)
    change, extra = scenario_change("srun-1", "completed")
    h.on_change(change, None, extra)
    wait = h.create("scenario.step", None, {"scenarioId": "my-overpressure", "runId": "srun-1", "status": "completed"})
    assert wait["status"] == "fired"
    assert wait["firedEvent"]["replayed"] is True
    assert h.result(wait)["status"] == "fired"


def test_wait_without_a_specific_id_does_not_replay_old_events(tmp_path):
    h = hub(tmp_path)
    change, extra = scenario_change("srun-1", "completed")
    h.on_change(change, None, extra)
    wait = h.create("scenario.step", None, {"scenarioId": "my-overpressure", "status": "completed"})
    assert wait["status"] == "waiting"


def test_replay_never_matches_a_different_run(tmp_path):
    h = hub(tmp_path)
    change, extra = scenario_change("srun-1", "completed")
    h.on_change(change, None, extra)
    wait = h.create("scenario.step", None, {"runId": "srun-2", "status": "completed"})
    assert wait["status"] == "waiting"
    later, later_extra = scenario_change("srun-2", "completed", version=2)
    h.on_change(later, None, later_extra)
    assert h.get(wait["id"])["status"] == "fired"


def test_any_skips_scenario_step_rows_unless_the_filter_asks_for_them(tmp_path):
    """An agent's `any` wait fires on the issue, fact or conversation Change a step emits, never on the step row itself;
    the eval harness asks for step rows with filter type "scenario"."""
    h = hub(tmp_path)
    agent = h.create("any", "myer-plant", {})
    harness = h.create("any", None, {"type": "scenario", "runId": "srun-1"})
    change, extra = scenario_change("srun-1", "step")
    h.on_change(change, None, extra)
    assert h.get(agent["id"])["status"] == "waiting"
    assert h.get(harness["id"])["status"] == "fired" and h.get(harness["id"])["firedEvent"]["name"] == "scenario.step"
    issue = dict(version=2, type="issue", propertyId="myer-plant", refId="iss-1", summary="PG-601 above its circuit limit", at="2026-10-18T07:48:26Z")
    h.on_change(issue, None, dict(issueId="iss-1", status="open"))
    fired = h.get(agent["id"])
    assert fired["status"] == "fired" and fired["firedEvent"]["change"]["type"] == "issue"
    # the replay guard follows the same rule
    assert h.create("any", None, {"runId": "srun-1"})["status"] == "waiting"
    assert h.create("any", None, {"type": "scenario", "runId": "srun-1"})["status"] == "fired"
