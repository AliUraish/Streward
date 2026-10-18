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
