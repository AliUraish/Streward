"""Live metrics (contract 7 §5): every series' current 5-second reading with the one before it, the direction and the
band state, per-kind KPIs per site and across sites; scenario facts apply (the overpressure ramp reads high)."""
import pytest
from fastapi.testclient import TestClient

from src.main import create_app

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "STEWARD_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def test_live_readings_and_kpis_for_every_site(client):
    live = client.get("/api/metrics/live").json()
    assert live["intervalSeconds"] == 5 and [s["siteId"] for s in live["sites"]] == [MY, BR, TM]
    for site in live["sites"]:
        assert site["readings"] and "checkedIn" in site["kpis"]
        for reading in site["readings"]:
            assert reading["trend"] in ("up", "down", "flat") and reading["state"] in ("high", "low", "normal")
            assert {"key", "label", "assetTag", "unit", "value", "previous", "delta", "spec"} <= set(reading)
        checked = site["kpis"]["checkedIn"]
        assert checked["value"] == int(checked["value"]) and checked["unit"] == "people"
    kinds = {s["siteId"]: set(s["kpis"]) for s in live["sites"]}
    assert {"pressure", "flow"} <= kinds[MY] and {"pressure", "flow"} <= kinds[BR] and "humidity" in kinds[TM] and "pressure" not in kinds[TM]
    assert {"pressure", "flow", "humidity", "checkedIn"} <= set(live["average"])
    one = client.get(f"/api/metrics/live?siteId={TM}").json()
    assert [s["siteId"] for s in one["sites"]] == [TM] and one["average"] == {}
    assert client.get("/api/metrics/live?siteId=nowhere").status_code == 404


def test_live_reading_follows_the_scenario_ramp(client):
    assert client.post("/api/scenarios/my-overpressure/start", json={"speed": 0}).status_code == 202
    site = client.get(f"/api/metrics/live?siteId={MY}").json()["sites"][0]
    gauge = next(r for r in site["readings"] if r["key"] == "pressure_bar:PG-601")
    assert gauge["value"] > 3.5 and gauge["state"] == "high"
    assert site["kpis"]["pressure"]["state"] == "high" and "PG-601" in site["kpis"]["pressure"]["outOfBand"]
    summary = client.get("/api/metrics/summary").json()
    assert all(s["employeesCheckedIn"] >= 1 for s in summary["sites"]) and "visitorsToday" not in summary["totals"]
