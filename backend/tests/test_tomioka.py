"""Contract 5: the third site, the Tomioka Silk Mill (tomioka-mill, TM, JP). Registry, register and pins, the team and the
authority rules, crew and obligations (Japanese regulations, tolerated while pending), the three scenarios through the
fix workflow, the shared window with Bristol, metrics and the three-site summaries, and the migration of an existing
two-site database. Every external transport is off; nothing leaves the machine."""
import base64
import io
import json
import sqlite3
import threading
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.service import PropertyService

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
LOD = "https://d28zzqy0iyovbz.cloudfront.net/849bce2a/v1/lod-meta.json"
TARGET = (-33.558, 0.001, -44.495)
TAGS = (["RM-101", "RM-102", "RM-103", "RM-104", "RM-105", "RM-106", "TR-201", "TR-202", "TR-203", "TR-204", "BW-251", "HS-301", "HS-302", "HS-303",
         "VS-401", "FE-501", "FE-502", "FE-503", "FH-601", "D-701", "D-702", "W-801", "EP-901", "CC-1001", "DH-1101"])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def start(client, scenario_id):
    response = client.post(f"/api/scenarios/{scenario_id}/start", json={"speed": 0})
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["state"] == "completed", run
    return run


def fix(client, issue_id):
    response = client.post(f"/api/issues/{issue_id}/fix", json={"speed": 0})
    assert response.status_code == 202, response.text
    workflow = response.json()
    assert workflow["state"] == "completed", workflow
    return workflow


def jpeg() -> str:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (80, 80, 80)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


class Renderer(threading.Thread):
    """A renderer in eye mode for one site: long-polls commands, records their params, posts one JPEG per expected frame.
    `mark` frames carry the renderer's real body: `mark: {x, y, world: [x, y, z], hit, note}`."""

    def __init__(self, client, site, renderer_id="tm-test"):
        super().__init__(daemon=True)
        self.client, self.site, self.renderer_id = client, site, renderer_id
        self.stop = threading.Event()
        self.since = 0
        self.frame = jpeg()
        self.commands = []

    def run(self):
        while not self.stop.is_set():
            listing = self.client.get(f"/api/eye/{self.site}/commands", params={"rendererId": self.renderer_id, "since": self.since, "timeout": 1}).json()
            for command in listing.get("commands", []):
                self.since = max(self.since, command["seq"])
                self.commands.append(command)
                for index in range(command["expectedFrames"]):
                    payload = {"commandId": command["id"], "jpegBase64": "data:image/jpeg;base64," + self.frame, "rendererId": self.renderer_id, "index": index,
                               "camera": {"position": [-32.4, 0.3, -43.4], "target": list(TARGET), "fov": 75},
                               "visiblePins": [{"assetTag": "HS-301", "x": 0.5, "y": 0.5, "distance": 2.0, "occluded": False}]}
                    if command["action"] == "mark":
                        payload["mark"] = {"x": 0.5, "y": 0.5, "world": [-35.41, -1.14, -48.69], "hit": True, "note": command["params"].get("note")}
                    self.client.post(f"/api/eye/{self.site}/frames", json=payload)


# ---- 1. the site ------------------------------------------------------------------------------------------------------------

def test_tomioka_is_the_third_site_with_every_contract_field(client):
    properties = {p["id"]: p for p in client.get("/api/properties").json()}
    assert list(properties) == [MY, BR, TM]
    mill = properties[TM]
    assert mill["name"] == "Tomioka Silk Mill" and mill["site"].startswith("富岡製糸場, Tomioka, Gunma Prefecture, Japan")
    assert "UNESCO World Heritage" in mill["site"] and "National Treasures" in mill["site"]
    assert mill["status"] == "open to visitors" and mill["jurisdiction"] == "JP" and mill["prefix"] == "TM"
    assert "not the site's real operator" in mill["operator"] and mill["siteKind"].startswith("heritage industrial site; an 1872 silk reeling mill")
    environment = mill["environment"]
    assert environment["kind"] == "splat" and environment["format"] == "lod" and environment["splatId"] == "849bce2a"
    assert environment["sogUrl"] == environment["sogMetaUrl"] == environment["lodMetaUrl"] == environment["contentUrl"] == LOD
    assert environment["lod"] == {"version": 1, "levels": 5, "chunkFiles": 44, "count": 23564860, "octree": "tree"}
    assert environment["embedUrl"] == "https://superspl.at/s?id=849bce2a"
    assert environment["thumbnailUrl"] == "https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/849bce2a/v1/xl.webp"
    assert "富岡製糸場" in environment["credit"] and "by acrylagitt on SuperSplat" in environment["credit"] and "third-party" in environment["credit"]
    assert environment["captureNote"] == properties[MY]["environment"]["captureNote"]
    preset = environment["cameraPresets"][0]
    assert preset == {"id": "initial", "label": "Initial view", "fov": 75, "position": [-32.414, 0.287, -43.351], "target": [-33.558, 0.001, -44.495]}
    scene = client.get(f"/api/properties/{TM}/scene").json()
    assert scene["sogUrl"] == scene["contentUrl"] == scene["lodMetaUrl"] == LOD and scene["scanFormat"] == "lod" and len(scene["assets"]) == 25
    assert environment["scanFormat"] == "lod" and properties[MY]["environment"]["scanFormat"] == "sog"
    assert client.get(f"/api/properties/{MY}/scene").json()["scanFormat"] == "sog"
    assert client.get(f"/api/properties/{TM}/scene").json()["estimatedPins"] == 25


def test_register_specs_pins_and_references(client):
    components = client.get(f"/api/properties/{TM}/components").json()
    assert [c["tag"] for c in components] == TAGS  # §3's table lists 25 tags (its heading says 24); all are registered
    kinds = {c["tag"]: c["kind"] for c in components}
    assert {kinds[t] for t in ("RM-101", "RM-106")} == {"machine"} and kinds["BW-251"] == kinds["TR-203"] == "structure"
    assert {kinds[t] for t in ("HS-301", "VS-401")} == {"sensor"} and kinds["FH-601"] == "hydrant" and kinds["CC-1001"] == "camera"
    assert kinds["DH-1101"] == "dehumidifier" and kinds["W-801"] == "walkway" and kinds["EP-901"] == "panel" and kinds["D-702"] == "door"
    by_tag = {c["tag"]: c for c in components}
    assert by_tag["HS-302"]["specKind"] == "sensor:humidity" and by_tag["VS-401"]["specKind"] == "sensor:seismic"
    for component in components:  # estimated, inside the occupied volume around the initial camera target
        pin = component["pin"]
        assert component["pinSource"] == "estimated" and abs(pin["x"] - TARGET[0]) < 8 and abs(pin["z"] - TARGET[2]) < 8 and -3.5 < pin["y"] < 3.5
    specs = client.get(f"/api/properties/{TM}/specs").json()
    table = specs["kinds"]
    assert table["machine"]["vibration_mms"]["max"] == 4.5 and table["machine"]["status"]["enum"] == ["running", "stopped", "fault"]
    assert table["structure"]["crack_width_mm"]["max"] == 0.3 and table["structure"]["condition"]["enum"] == ["sound", "watch", "defect"]
    assert (table["sensor:humidity"]["humidity_pct"]["min"], table["sensor:humidity"]["humidity_pct"]["max"]) == (40, 65)
    assert (table["sensor:humidity"]["temperature_c"]["min"], table["sensor:humidity"]["temperature_c"]["max"]) == (5, 30)
    assert table["sensor:seismic"]["seismic_gal"]["max"] == 80 and table["hydrant"]["pressure_ok"]["enum"] == ["yes", "no"]
    assert table["camera"]["working"]["enum"] == ["yes", "no"] and table["dehumidifier"]["running"]["enum"] == ["yes", "no"]
    assert table["sensor"]["temperature_c"]["max"] == 40  # the existing sensor kind keeps its spec
    asset = next(a for a in specs["assets"] if a["assetTag"] == "HS-301")
    assert asset["kind"] == "sensor" and asset["specKind"] == "sensor:humidity" and asset["attributes"] == ["humidity_pct", "serial", "temperature_c"]
    # A dispatch for the mill carries the TM reference prefix and the spec range of its own table.
    result = client.post(f"/api/properties/{TM}/resolve", json={"assetTag": "HS-302", "attribute": "humidity_pct", "budget": 5}).json()
    assert result["reference"].startswith("TM-HS302-HUMIDITY_PCT-")
    item = client.get(f"/api/work-items/{result['workItemId']}").json()
    card = item["dispatches"][0]["body"]
    assert "Tomioka Silk Mill, Silk Reeling Mill" in card and "Expected range 40 to 65 %" in card
    bad = client.post(f"/api/properties/{TM}/resolve", json={"assetTag": "HS-302", "attribute": "pressure_bar"})
    assert bad.status_code == 400 and bad.json()["code"] == "UNSUPPORTED_ATTRIBUTE"
    reply = client.post("/api/inbound/local", json={"reference": result["reference"], "body": "HS-302 reads 57 %"}).json()
    assert reply["verdict"] == "accepted"
    context = client.get(f"/api/properties/{TM}/context.min")
    assert context.status_code == 200 and len(context.text) < 1600 and context.json()["assets"] == 25


# ---- 2. the team and authority -------------------------------------------------------------------------------------------------

def test_team_identities_titles_and_authority(client, monkeypatch):
    for role in ("MANAGER", "ENGINEER", "COMPLIANCE", "TECHNICIAN"):
        monkeypatch.setenv(f"INKBOX_IDENTITY_TOMIOKA_{role}", f"steward-tomioka-{role.lower()}")
        monkeypatch.setenv(f"INKBOX_AGENT_KEY_TOMIOKA_{role}", f"key-{role.lower()}")
    agents = {a["id"]: a for a in client.get("/api/agents").json()}
    assert [a for a in agents if a.startswith("tomioka-")] == ["tomioka-manager", "tomioka-engineer", "tomioka-compliance", "tomioka-technician"]
    assert agents["tomioka-manager"]["name"] == "Site Manager · Tomioka" and agents["tomioka-manager"]["level"] == 3
    assert agents["tomioka-engineer"]["name"] == "Conservation Engineer · Tomioka" and agents["tomioka-engineer"]["level"] == 4
    assert agents["tomioka-compliance"]["name"] == "Compliance Officer · Tomioka" and agents["tomioka-technician"]["level"] == 5
    assert agents["tomioka-engineer"]["handle"] == "steward-tomioka-engineer" and agents["tomioka-compliance"]["email"] == "steward-tomioka-compliance@inkboxmail.com"
    assert agents["tomioka-technician"]["siteId"] == TM and "tomioka-technician" in agents["dispatch"]["usedBy"]
    assert agents["director"]["role"].startswith("all three sites")
    from src.agents import agent_key
    assert agent_key("tomioka-manager") == "key-manager"
    # The mill's technician never attests; the engineer does.
    body = {"assetTag": "HS-301", "attribute": "humidity_pct", "value": 58, "statedTag": "HS-301", "source": {"kind": "agent", "ref": "t"}}
    denied = client.post(f"/api/properties/{TM}/attest", json=body, headers={"X-Steward-Actor": "tomioka-technician"})
    assert denied.status_code == 403 and "Field Technician · Tomioka may not attest" in denied.json()["detail"]
    assert "Conservation Engineer · Tomioka" in denied.json()["recovery"]
    assert client.post(f"/api/properties/{TM}/attest", json=body, headers={"X-Steward-Actor": "tomioka-engineer"}).json()["verdict"] == "accepted"
    # Bristol's manager cannot write the mill's records.
    for response in (
        client.post(f"/api/properties/{TM}/resolve", json={"assetTag": "HS-301", "attribute": "humidity_pct", "budget": 5}, headers={"X-Steward-Actor": "bristol-manager"}),
        client.post("/api/maintenance", json={"siteIds": [TM], "date": "2026-11-02", "scope": "Not Bristol's"}, headers={"X-Steward-Actor": "bristol-manager"}),
        client.post(f"/api/properties/{TM}/viewer", json={"action": "focus", "assetTag": "HS-301"}, headers={"X-Steward-Actor": "bristol-manager"}),
        client.post(f"/api/eye/{TM}/act", json={"action": "look"}, headers={"X-Steward-Actor": "bristol-manager"}),
    ):
        assert response.status_code == 403 and response.json()["code"] == "AUTHORITY_DENIED", response.text
    issue = svc(client).issues.raise_issue(TM, "humidity_high", "medium", "test", asset_tag="HS-301")
    assert client.post(f"/api/issues/{issue['id']}/assign", json={"crewMemberId": "crew-tm-conservator"},
                       headers={"X-Steward-Actor": "bristol-manager"}).status_code == 403
    assert client.post(f"/api/issues/{issue['id']}/assign", json={"crewMemberId": "crew-tm-conservator"},
                       headers={"X-Steward-Actor": "tomioka-manager"}).json()["assigneeId"] == "crew-tm-conservator"
    # Cross-site rule: compliance to compliance and manager to manager, anyone to or from the director.
    bus = svc(client).bus
    assert bus.send("tomioka-compliance", "bristol-compliance", "How do you mount sensors?", {}, TM, deliver=False)["target"] == "bristol-compliance"
    assert bus.send("tomioka-manager", "myer-manager", "hello", {}, TM, deliver=False)["caller"] == "tomioka-manager"
    assert bus.send("director", "tomioka-technician", "status?", {}, TM, deliver=False)["target"] == "tomioka-technician"
    from src.errors import RealityError
    with pytest.raises(RealityError):
        bus.send("tomioka-engineer", "bristol-manager", "hello", {}, TM, deliver=False)
    # The director's scope covers the mill.
    assert client.post(f"/api/properties/{TM}/resolve", json={"assetTag": "EP-901", "attribute": "status"},
                       headers={"X-Steward-Actor": "director"}).status_code == 200


# ---- 3. crew, obligations, regulations ---------------------------------------------------------------------------------------

def test_crew_obligations_and_japanese_regulations(client, monkeypatch, tmp_path):
    monkeypatch.setenv("INKBOX_CONTRACTOR_PHONE", "+15550001234")
    crew = {c["id"]: c for c in client.get(f"/api/properties/{TM}/crew").json()}
    assert set(crew) == {"crew-tm-duty-engineer", "crew-tm-site-manager", "crew-tm-conservation-architect", "crew-tm-conservator",
                         "crew-tm-visitor-safety-lead", "crew-tm-fire-officer", "crew-tm-guide-supervisor"}
    duty = crew["crew-tm-duty-engineer"]
    assert duty["name"] == "Duty engineer (you)" and duty["contactable"] is True and duty["phone"] == "••• ••• 1234"
    assert all(not c["contactable"] and c["phone"] is None and c["email"] is None and c["synthetic"] for k, c in crew.items() if k != "crew-tm-duty-engineer")
    owners = {kind: client.get(f"/api/properties/{TM}/responsible?issueKind={kind}").json() for kind in ("humidity_high", "alteration_permit", "visitor_route", "out_of_range")}
    assert owners["humidity_high"]["owner"]["id"] == owners["alteration_permit"]["owner"]["id"] == "crew-tm-conservation-architect"
    assert owners["visitor_route"]["owner"]["id"] == "crew-tm-visitor-safety-lead" and owners["out_of_range"]["owner"]["id"] == "crew-tm-duty-engineer"
    assert owners["humidity_high"]["agent"] == "tomioka-engineer" and owners["alteration_permit"]["agent"] == "tomioka-compliance"
    assert owners["visitor_route"]["agent"] == "tomioka-compliance" and owners["humidity_high"]["contactPlan"]["reachable"] is False
    obligations = {o["id"]: o for o in client.get(f"/api/properties/{TM}/obligations").json()}
    assert set(obligations) == {"ob-tm-humidity-watch", "ob-tm-bw251-permit", "ob-tm-fe-inspection", "ob-tm-fh601-inspection", "ob-tm-heritage-mounting",
                                "ob-tm-exit-drill", "ob-tm-tr202-strap"}  # the last two are the seeded compliance gaps (contract 7 §6)
    regulations = {r["id"]: r for r in client.get(f"/api/regulations?siteId={TM}").json()}
    if "jp-cpa-1950-art-43" in regulations:  # the regulations stream's Japanese pack is present
        assert all(r["jurisdiction"] == "JP" for r in regulations.values())
        permit = obligations["ob-tm-bw251-permit"]
        assert permit["regulationPending"] is False and "jp-cpa-1950-art-43" in permit["regulationIds"]
        assert obligations["ob-tm-humidity-watch"]["regulationIds"][0] == "jp-cpa-1950-art-31"
        assert permit.get("why") and permit["trackedBy"] == "tomioka-compliance"  # the REGULATIONS stream's suggestion attaches
        record = regulations["jp-cpa-1950-art-43"]
        if record["servePdf"] and record["cached"]:
            pdf = client.get("/api/regulations/jp-cpa-1950-art-43/file")
            assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
            assert pdf.headers["x-steward-attribution"] == "Source: e-Gov Law Search (Digital Agency, Japan), PDL1.0."
            assert "Open Government Licence" not in pdf.headers["x-steward-attribution"] and record["attribution"].startswith("出典")
    # Without the Japanese records the obligations say the regulations are pending instead of failing.
    empty = tmp_path / "regs.json"
    empty.write_text(json.dumps([]))
    monkeypatch.setenv("STEWARD_REGULATIONS_FILE", str(empty))
    pending = {o["id"]: o for o in client.get(f"/api/properties/{TM}/obligations").json()}["ob-tm-bw251-permit"]
    assert pending["regulationPending"] is True and pending["regulationIds"] == [] and "jp-cpa-1950-art-43" in pending["unresolvedRegulationIds"]


# ---- 4. scenarios through the fix workflow -------------------------------------------------------------------------------------

def test_tm_humidity_raises_calls_contacts_and_the_fix_verifies_under_65(client):
    scenarios = {s["id"]: s for s in client.get("/api/scenarios").json()}
    assert scenarios["tm-humidity"]["headline"] is True and scenarios["tm-humidity"]["siteIds"] == [TM]
    # Nothing fires until started; only the seeded compliance gaps are open (contract 7 §6).
    assert sorted(i["kind"] for i in client.get(f"/api/properties/{TM}/issues").json()) == ["compliance_blocked", "compliance_overdue"]
    run = start(client, "tm-humidity")
    readings = [f for f in svc(client).store.all("fact", TM) if f["source"] == {"kind": "sensor", "ref": "scenario:tm-humidity"}]
    assert [f["value"] for f in readings] == [79.6, 81.8, 83.9, 85.6, 86.9, 88.0, 88.6] and all(f["synthetic"] is True for f in readings)
    issues = [i for i in client.get(f"/api/properties/{TM}/issues?status=all").json() if i.get("scenarioId") == "tm-humidity"]
    assert len(issues) == 1 and issues[0]["kind"] == "humidity_high" and issues[0]["severity"] == "high" and issues[0]["assetTag"] == "HS-301"
    issue = issues[0]
    assert issue["ownerId"] == "crew-tm-conservation-architect" and issue["synthetic"] is True and issue["pinSource"] == "estimated"
    assert issue["history"][0]["severity"] == "medium" and issue["history"][1]["severity"] == "high"
    call = client.get(f"/api/conversations/{run['conversationIds']['cv-tm-humidity']}").json()
    assert call["kind"] == "call" and call["siteIds"] == [TM] and call["summaryBy"] == "hand-seed" and call["synthetic"] is True
    assert [line["speaker"] for line in call["transcript"]] == ["tomioka-engineer", "tomioka-manager", "tomioka-compliance", "tomioka-manager", "tomioka-technician"]
    assert "第31条" in call["transcript"][2]["text"] and call["summary"]["headline"].startswith("HS-301 at 88.0 % RH")
    notices = {n["noticeKind"]: n for n in client.get(f"/api/properties/{TM}/notices").json()}
    assert notices["contact"]["toCrewId"] == "crew-tm-conservator" and notices["contact"]["mode"] == "not_contactable"
    assert notices["compliance"]["toCrewId"] == "crew-tm-conservation-architect" and "DH-1101" in notices["contact"]["text"]
    page = client.get(f"/api/issues/{issue['id']}").json()
    assert page["responsible"]["owner"]["id"] == "crew-tm-conservation-architect"
    if page["regulationIds"]:
        assert page["regulationIds"][0] == "jp-cpa-1950-art-31" and page["why"][0]["instrument"].startswith("Act on Protection of Cultural Properties")
    # The scenario ends with the contract-4 fix workflow: the conservator's fix is verified and signed.
    assert run["log"][-1]["type"] == "fix" and page["fix"]["available"] is False and page["fix"]["latest"]["id"] == run["context"]["fixWorkflowId"]
    workflow = client.get(f"/api/fix-workflows/{run['context']['fixWorkflowId']}").json()
    assert workflow["state"] == "completed" and [s["name"] for s in workflow["steps"]] == ["evidence", "call", "contact", "fix", "verify", "inform"]
    assert workflow["reply"]["simulated"] is True and "DH-1101" in workflow["reply"]["body"]
    assert client.get(f"/api/issues/{issue['id']}").json()["status"] == "resolved"
    attestation = client.get(f"/api/attestations/{workflow['attestationId']}").json()
    assert attestation["valid"] is True and attestation["verdict"] == "accepted" and attestation["value"] <= 65
    assert client.get(f"/api/properties/{TM}/facts?assetTag=HS-301&attribute=humidity_pct").json()[0]["value"] == 58
    assert client.post(f"/api/issues/{issue['id']}/fix", json={"speed": 0}).json()["code"] == "ISSUE_CLOSED"
    humidity = client.get(f"/api/properties/{TM}/metrics?series=humidity_pct:HS-301").json()["series"][0]
    assert humidity["points"][-1][1] == 58 and humidity["overlayPoints"] >= 8 and humidity["spec"] == {"min": 40, "max": 65}
    notifications = client.get(f"/api/notifications?siteId={TM}").json()
    assert len([n for n in notifications if n["toKind"] == "crew"]) == 7
    assert {n["to"] for n in notifications if n["toKind"] == "agent"} == {"tomioka-engineer", "tomioka-compliance", "tomioka-technician", "director"}
    assert {o["id"]: o for o in client.get(f"/api/properties/{TM}/obligations").json()}["ob-tm-humidity-watch"]["status"] in ("ok", "due_soon")


def test_tm_alteration_permit_blocks_the_drilling_and_files_the_permit(client):
    run = start(client, "tm-alteration-permit")
    log = [line["type"] for line in run["log"]]
    assert log.count("obligation") == 2 and "send_document" in log and "regenerate_document" in log
    issue = next(i for i in client.get(f"/api/properties/{TM}/issues").json() if i["kind"] == "alteration_permit")
    assert issue["assetTag"] == "BW-251" and issue["severity"] == "high" and issue["documentId"] == "doc-tm-contractor-wo"
    meeting = client.get(f"/api/conversations/{run['conversationIds']['cv-tm-alteration']}").json()
    assert meeting["kind"] == "meeting" and meeting["convener"] == "tomioka-manager" and meeting["contact"]["crewMemberId"] == "crew-tm-conservation-architect"
    assert "clamp mounts" in meeting["resolution"] and "Takahashi Kenji" in meeting["resolution"] and meeting["summaryBy"] == "hand-seed"
    assert "第43条" in meeting["transcript"][1]["text"]
    email = next(e for e in client.get(f"/api/document-emails?siteId={TM}").json() if e["documentId"] == "doc-tm-contractor-wo")
    assert email["sender"] == "tomioka-compliance" and email["recipient"] == "tomioka-manager" and email["mode"] == "dry_run"
    document = client.get("/api/documents/doc-tm-contractor-wo").json()
    assert "BW-251" in document["text"] and document["flagged"] is False
    permit = {o["id"]: o for o in client.get(f"/api/properties/{TM}/obligations").json()}["ob-tm-bw251-permit"]
    assert permit["status"] != "blocked" and "TM-PERMIT-2026-03" in permit["note"]
    changes = [c for c in client.get(f"/api/properties/{TM}/changes?limit=1000").json()["changes"] if c["type"] == "obligation"]
    assert any("blocked" in c["summary"] for c in changes)
    workflow = fix(client, issue["id"])
    item = client.get(f"/api/work-items/{workflow['workItemId']}").json()
    assert item["attribute"] == "condition" and item["state"] == "resolved"
    assert client.get(f"/api/properties/{TM}/facts?assetTag=BW-251&attribute=condition").json()[0]["value"] == "sound"
    assert client.get(f"/api/issues/{issue['id']}").json()["status"] == "resolved"


def test_x_heritage_agrees_the_shared_window_on_both_sites(client):
    run = start(client, "x-heritage")
    assert run["siteIds"] == [TM, BR]
    shared = [w for w in client.get(f"/api/maintenance?siteId={TM}").json() if len(w["siteIds"]) == 2]
    assert len(shared) == 1 and shared[0] in client.get(f"/api/maintenance?siteId={BR}").json()
    window = shared[0]
    assert window["siteIds"] == [TM, BR] and window["status"] == "approved" and window["approvedBy"] == "director" and window["proposedBy"] == "tomioka-manager"
    assert window["scope"].startswith("Heritage-safe sensor installation") and window["date"] == run["context"]["windowDate"] and window["synthetic"] is True
    assert window["conversationId"] == run["conversationIds"]["cv-xh-managers"]
    compliance = client.get(f"/api/conversations/{run['conversationIds']['cv-xh-compliance']}").json()
    assert set(compliance["siteIds"]) == {TM, BR} and compliance["participants"] == ["tomioka-compliance", "bristol-compliance"]
    assert compliance["summaryBy"] == "hand-seed" and any("reg 12" in line["text"] for line in compliance["transcript"])
    managers = client.get(f"/api/conversations/{run['conversationIds']['cv-xh-managers']}").json()
    assert managers["participants"] == ["tomioka-manager", "bristol-manager"] and set(managers["siteIds"]) == {TM, BR}
    approval = client.get(f"/api/conversations/{run['conversationIds']['cv-xh-approval']}").json()
    assert approval["participants"] == ["tomioka-manager", "director"]
    assert {c["id"] for c in client.get(f"/api/conversations?siteId={BR}").json()} >= {compliance["id"], managers["id"]}
    email = next(e for e in client.get(f"/api/document-emails?siteId={BR}").json() if e["documentId"] == "doc-br-heritage-methods")
    assert email["sender"] == "bristol-compliance" and email["recipient"] == "tomioka-compliance" and email["a2aTaskId"]  # compliance to compliance
    issue = next(i for i in client.get(f"/api/properties/{TM}/issues").json() if i["kind"] == "visitor_route")
    assert issue["assetTag"] == "W-801" and issue["scenarioId"] == "x-heritage"
    heritage = {o["id"]: o for o in client.get(f"/api/properties/{TM}/obligations").json()}["ob-tm-heritage-mounting"]
    assert heritage["status"] == "overdue" and run["context"]["windowDate"] in heritage["note"]
    workflow = fix(client, issue["id"])
    assert client.get(f"/api/issues/{issue['id']}").json()["status"] == "resolved" and workflow["crewMemberId"] == "crew-tm-visitor-safety-lead"
    assert {o["id"]: o for o in client.get(f"/api/properties/{TM}/obligations").json()}["ob-tm-heritage-mounting"]["status"] in ("ok", "due_soon")
    # The scenario's own step rows reach only the eval harness (includeScenario=true); people and agents get the step's records.
    assert any(c["type"] == "scenario" for c in client.get(f"/api/properties/{BR}/changes?limit=1000&includeScenario=true").json()["changes"])
    assert not any(c["type"] == "scenario" for c in client.get(f"/api/properties/{BR}/changes?limit=1000").json()["changes"])


# ---- 5. metrics, overview, summaries, eye -------------------------------------------------------------------------------------

def test_metrics_overview_and_three_site_summaries(client):
    for base in ("humidity_pct", "temperature_c", "checked_in", "vibration_mms", "crack_width_mm", "power_kw"):
        data = client.get(f"/api/properties/{TM}/metrics?series={base}").json()
        assert data["series"] and data["synthetic"] is True, base
    checked = client.get(f"/api/properties/{TM}/metrics?series=checked_in").json()["series"][0]
    assert checked["assetTag"] == "SITE" and checked["unit"] == "people"
    assert all(value == int(value) and value >= 2 for _, value in checked["points"])  # whole people, never an empty mill
    by_hour = {}
    for at, value in checked["points"]:
        hour = (datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(timezone.utc).hour + 9) % 24
        by_hour.setdefault(hour, []).append(value)
    if 12 in by_hour and 0 in by_hour:
        assert sum(by_hour[12]) / len(by_hour[12]) > sum(by_hour[0]) / len(by_hour[0])  # the day shift is bigger than the night
    summary = client.get("/api/metrics/summary").json()
    sites = {s["siteId"]: s for s in summary["sites"]}
    assert list(sites) == [MY, BR, TM]
    mill = sites[TM]
    assert 40 < mill["avgHumidityPct"] < 65 and mill["employeesCheckedIn"] >= 2 and 0 < mill["maxCrackWidthMm"] < 0.3 and "visitorsToday" not in mill
    assert mill["avgPressureBar"] is None and mill["avgFlowM3h"] is None and mill["crewOnShift"] == 6
    assert summary["average"]["avgHumidityPct"] == mill["avgHumidityPct"]
    assert summary["totals"]["employeesCheckedIn"] == sum(s["employeesCheckedIn"] for s in sites.values())
    assert summary["average"]["avgPressureBar"] == round((sites[MY]["avgPressureBar"] + sites[BR]["avgPressureBar"]) / 2, 2)
    overview = client.get("/api/overview").json()
    assert [s["id"] for s in overview["sites"]] == [MY, BR, TM] and len(overview["agents"]) == 14
    assert len(json.dumps(overview, separators=(",", ":"))) <= 2400
    assert {"ok", "due_soon", "overdue", "blocked"} == set(overview["sites"][2]["compliance"])


def test_eye_endpoints_work_for_the_mill(client):
    client.post(f"/api/eye/{TM}/renderers", json={"rendererId": "tm-test"})
    renderer = Renderer(client, TM)
    renderer.start()
    try:
        look = client.post(f"/api/eye/{TM}/act", json={"action": "go_to", "params": {"assetTag": "HS-301"}}, headers={"X-Steward-Actor": "tomioka-engineer"})
        assert look.status_code == 200, look.text
        assert look.json()["actor"] == "tomioka-engineer" and look.json()["params"]["target"] == client.get(f"/api/properties/{TM}/components/sensor-01").json()["pin"]
        mark = client.post(f"/api/eye/{TM}/act", json={"action": "mark", "params": {"x": 0.5, "y": 0.5, "note": "condensation on the sash"}},
                           headers={"X-Steward-Actor": "tomioka-engineer"}).json()
        assert mark["world"] == {"x": -35.41, "y": -1.14, "z": -48.69} and mark["hit"] is True and mark["annotation"]["nearestAssetTag"] == "HS-301"
    finally:
        renderer.stop.set()
        renderer.join(timeout=5)
    feed = client.get(f"/api/eye/{TM}/feed").json()
    assert len(feed["frames"]) == 2 and feed["operating"]["actor"] == "tomioka-engineer"
    assert client.post(f"/api/eye/{TM}/act", json={"action": "look"}, headers={"X-Steward-Actor": "tomioka-compliance"}).status_code == 403


# ---- 6. migration of an existing two-site database --------------------------------------------------------------------------

def test_an_existing_two_site_database_gains_the_mill_once_with_a_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "two-sites"
    first = PropertyService(directory, start_workers=False)
    before = {kind: len([r for r in first.store.all(kind) if (r.get("siteId") or r.get("propertyId") or r.get("_propertyId")) != TM])
              for kind in ("component", "fact", "obligation", "crew_member")}
    first.close()
    with sqlite3.connect(directory / "steward.sqlite3") as db:  # the database as it was before contract 5
        db.execute("DELETE FROM records WHERE property_id=? OR (kind='property' AND id=?) OR (kind='agent' AND id=?)", (TM, TM, f"agent-{TM}"))
        db.execute("DELETE FROM events WHERE property_id=?", (TM,))
        db.execute("DELETE FROM meta WHERE key IN ('steward_sites_version')")
        db.execute("UPDATE meta SET value='1' WHERE key IN ('steward_people_version','steward_maintenance_version')")
        db.execute("UPDATE meta SET value='3' WHERE key IN ('reality_seed_version','steward_site_shape_version')")
        db.execute("DELETE FROM records WHERE kind='maintenance_window' AND body LIKE '%tomioka-mill%'")
    upgraded = PropertyService(directory, start_workers=False)
    store = upgraded.store
    assert [p["id"] for p in store.all("property")] == [MY, BR, TM] and upgraded.site_additions["added"] == [TM]
    assert len(store.all("component", TM)) == 25 and len(store.all("requirement", TM)) == 100
    assert len(store.all("crew_member", TM)) == 7 and len(store.all("obligation", TM)) == 7  # 5 plus the 2 seeded compliance gaps
    assert any(f["attribute"] == "serial" for f in store.all("fact", TM))  # identity facts seeded for the new site
    assert {w["id"] for w in upgraded.maintenance.list(TM)} >= {"mw-tm-dh1101-service", "mw-tm-fire-inspection"}
    assert store.get("property", MY)["jurisdiction"] == "VIC-AU" and store.get("property", TM)["environment"]["format"] == "lod"
    after = {kind: len([r for r in store.all(kind) if (r.get("siteId") or r.get("propertyId") or r.get("_propertyId")) != TM])
             for kind in ("component", "fact", "obligation", "crew_member")}
    assert after == before  # the plants are untouched
    backups = [p.name for p in (directory / ".migration-backups").iterdir() if p.name.startswith("pre-third-site-")]
    assert len(backups) == 1
    upgraded.close()
    again = PropertyService(directory, start_workers=False)
    assert again.site_additions == {} and len(again.store.all("component", TM)) == 25
    assert len([p for p in (directory / ".migration-backups").iterdir() if p.name.startswith("pre-third-site-")]) == 1
    again.close()


def test_the_simulated_feed_never_overwrites_the_scenario_ramp(client):
    start(client, "tm-humidity")
    service = svc(client)
    before = service.reality.latest_facts(TM, "HS-301", "humidity_pct")[0]
    assert before["value"] == 58 and before["source"]["kind"] == "human"  # the verified fix
    service.simulator.tick_sensors()
    after = service.reality.latest_facts(TM, "HS-301", "humidity_pct")[0]
    assert after["id"] == before["id"]  # held for 30 minutes
    assert service.reality.latest_facts(TM, "HS-302", "humidity_pct")[0]["simulated"] is True  # the other sensors keep reporting
