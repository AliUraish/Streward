"""The owner's notifications page (owner, Oct 18 2026): the feed of what was sent or prepared for the owner and what
happened, the compliance snapshot (JSON and a black-and-white PDF), the Operations Director's digest with the PDF attached,
the agents' play reports from their own identities, and the owner channel: real only with STEWARD_ALLOW_OWNER_ALERTS=true and
the owner's own allowlisted address or phone, without STEWARD_ALLOW_EXTERNAL_MESSAGES. The provider is stubbed; nothing
leaves the process."""
import base64
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from src.agents import display_name
from src.main import create_app
from src.providers import InkboxAdapter, ProviderNotConfigured
from src.store import now
from src.verify import iso

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
PREFIX = {MY: "MYER", BR: "BRISTOL", TM: "TOMIOKA"}
OWNER_EMAIL, OWNER_PHONE, USER_PHONE = "owner@example.com", "+15550000001", "+15550000002"
REQUIRED = {"id", "at", "kind", "channel", "mode", "title", "summary", "siteId", "links", "attachments"}
LINKS = {"issueId", "conversationId", "alertId", "windowId", "patrolId"}


def jpeg_bytes() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (60, 70, 80)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = jpeg_bytes()

def same_picture(data: bytes) -> bool:
    """The attached frame is the labelled copy of the frame (labels are drawn on a copy): a JPEG of the same size."""
    from PIL import Image
    return data[:2] == b"\xff\xd8" and Image.open(io.BytesIO(data)).size == Image.open(io.BytesIO(JPEG)).size



@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


@pytest.fixture
def eye(client, monkeypatch):
    service = svc(client)

    def act_sync(site_id, action, params, actor, timeout=None):
        frame_id = f"eyf-{uuid4().hex[:16]}"
        (service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(JPEG)
        service.store.put("eye_frame", dict(id=frame_id, seq=1, siteId=site_id, commandId="eyc-test", action=action, params=params, actor=actor,
                                            actorName=display_name(actor), camera=None, visiblePins=[], index=0, rendererId="test", size=len(JPEG),
                                            sha256=hashlib.sha256(JPEG).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now()), site_id)
        return dict(frameId=frame_id, frameUrl=f"/api/eye/frames/{frame_id}.jpg")

    monkeypatch.setattr(service.eye, "act_sync", act_sync)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])


@pytest.fixture
def provider(monkeypatch):
    """Stubbed Inkbox sends; the adapter's own gates (the owner channel or the general one) still have to pass."""
    sent = dict(emails=[], calls=[])

    def send_email(self, property_id, to, subject, body, reference, in_reply_to=None, html=None, attachments=None, sender_handle=None,
                   api_key=None, idempotency_key=None, owner_channel=False):
        (InkboxAdapter._owner_gate(to, "email") if owner_channel else InkboxAdapter._gate(to))
        sent["emails"].append(dict(property_id=property_id, to=to, subject=subject, body=body, html=html, attachments=list(attachments or []),
                                   sender_handle=sender_handle, api_key=api_key, idempotency_key=idempotency_key, owner_channel=owner_channel))
        return {"id": f"msg-{len(sent['emails'])}", "threadId": None, "messageId": None, "raw": {}}

    def place_call(self, property_id, to, script, owner_channel=False):
        (InkboxAdapter._owner_gate(to, "call") if owner_channel else InkboxAdapter._gate(to))
        sent["calls"].append(dict(property_id=property_id, to=to, script=script, owner_channel=owner_channel))
        return {"id": f"call-{len(sent['calls'])}", "status": "queued", "raw": {}}

    monkeypatch.setattr(InkboxAdapter, "send_email", send_email)
    monkeypatch.setattr(InkboxAdapter, "place_call", place_call)
    return sent


def owner_channel(monkeypatch, *agents, external=False):
    """The owner channel on (tests only; the provider is stubbed): identities for the named agents, the owner's own address and
    phone allowlisted, STEWARD_ALLOW_OWNER_ALERTS=true. STEWARD_ALLOW_EXTERNAL_MESSAGES stays off unless `external`."""
    monkeypatch.setenv("INKBOX_API_KEY", "fixture-key")
    for agent in agents:
        suffix = "DIRECTOR" if agent == "director" else agent.upper().replace("-", "_")
        monkeypatch.setenv(f"INKBOX_IDENTITY_{suffix}", f"steward-{agent}")
        monkeypatch.setenv(f"INKBOX_AGENT_KEY_{suffix}", f"key-{agent}")
    monkeypatch.setenv("INKBOX_IDENTITY_DISPATCH", "steward-dispatch")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("INKBOX_OWNER_PHONE", OWNER_PHONE)
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", f"{OWNER_EMAIL},{OWNER_PHONE},contractor@example.com")
    if external:
        monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    else:
        monkeypatch.delenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", raising=False)


def overdue(service, obligation_id, days=6):
    record = service.store.get("obligation", obligation_id)
    record.update(dueAt=iso(datetime.now(timezone.utc) - timedelta(days=days, hours=2)), status="overdue", blockedBy=None, blockedReason=None)
    service.store.put("obligation", record, record["siteId"])


def shift_issue(service, issue_id, moment):
    """Move an issue's timestamps (creation and history) to a simulated moment, for the scheduler's clock."""
    record = service.store.get("issue", issue_id)
    stamp = iso(moment)
    record["at"] = stamp
    record["history"] = [dict(entry, at=stamp) for entry in record.get("history") or []]
    if record.get("resolvedAt"):
        record["resolvedAt"] = stamp
    service.store.put("issue", record, record["siteId"])


def walk(client, site, route):
    response = client.post("/api/patrols", json=dict(siteId=site, route=route))
    assert response.status_code == 202, response.text
    return response.json()


def feed(client, **params):
    response = client.get("/api/owner/notifications", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def at(item) -> datetime:
    return datetime.fromisoformat(item["at"].replace("Z", "+00:00"))


def pdf_text(data: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)


# ---- the feed ---------------------------------------------------------------------------------------------------------------

def test_the_feed_lists_what_the_owner_got_and_what_happened_newest_first_masked(client, eye, provider, monkeypatch):
    service = svc(client)
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("INKBOX_OWNER_PHONE", OWNER_PHONE)
    monkeypatch.setenv("INKBOX_CONTRACTOR_PHONE", USER_PHONE)
    overdue(service, "ob-br-pv301-exam", days=9)
    patrol = walk(client, BR, ["PV-301", "V-505"])
    [alert_id] = patrol["alertIds"]
    alert = client.get(f"/api/owner-alerts/{alert_id}").json()
    decided = client.post(f"/api/issues/{alert['issueId']}/decide", json=dict(question="Book the examiner for Tuesday?", options=["Yes", "No"]))
    assert decided.status_code == 201, decided.text
    service.people.send_notice(BR, "bristol-manager", "Compliance notice (synthetic demo): keep visitors off the walkway.",
                               crew_member_id="crew-br-duty-engineer", notice_kind="compliance")
    service.issues.raise_issue(MY, "overpressure", "high", "PG-601 reads 4.1 bar on a 3.5 bar circuit.", asset_tag="PG-601", issue_id="iss-my-feed-overpressure")
    service.issues.resolve_issue("iss-my-feed-overpressure", "Fixed and verified: PG-601 back to 2.6 bar.", "myer-engineer")
    booked = service.maintenance_planner.tick(datetime.now(timezone.utc))
    assert booked
    digest = client.post("/api/owner/digest", json={}).json()

    body = feed(client, limit=200)
    items = body["items"]
    kinds = {item["kind"] for item in items}
    assert {"owner_alert", "owner_digest", "decision_request", "notice", "issue", "compliance_gap", "maintenance", "walkthrough"} <= kinds
    assert body["total"] == len(items) and body["latestAt"] == items[0]["at"]
    assert [at(i) for i in items] == sorted((at(i) for i in items), reverse=True), "newest first"
    for item in items:
        assert REQUIRED <= set(item) and LINKS <= set(item["links"]) and item["channel"] in ("email", "call", "sms", "dashboard")
        assert item["mode"] in ("sent", "dry_run", "capped", "failed", "event") and (item["mode"] == "event") == (item["kind"] in ("issue", "compliance_gap", "maintenance", "walkthrough"))
        assert not re.search(r"synthetic|simulat|scenario", item["title"] + " " + item["summary"], re.I), item
        assert all({"filename", "contentType", "size", "url"} <= set(a) for a in item["attachments"])
    text = json.dumps(body, ensure_ascii=False)
    for secret in (OWNER_EMAIL, OWNER_PHONE, USER_PHONE, "15550000001", "15550000002"):
        assert secret not in text, secret
    assert "o•••@example.com" in text

    email = next(i for i in items if i["id"] == f"alert:{alert_id}:email")
    call = next(i for i in items if i["id"] == f"alert:{alert_id}:call")
    assert email["channel"] == "email" and email["mode"] == "dry_run" and email["title"].startswith("[Bristol Dock Pump House] Compliance:")
    assert email["links"]["alertId"] == alert_id and email["links"]["issueId"] == alert["issueId"] and email["links"]["patrolId"] == patrol["id"]
    assert email["from"] == "Compliance Officer · Bristol" and email["to"] == "o•••@example.com" and "Prepared, not sent" in email["summary"]
    frames = [a for a in email["attachments"] if a["contentType"] == "image/jpeg"]
    assert frames and frames[0]["url"].startswith("/api/eye/frames/eyf-")
    assert any(a["url"] == "/api/regulations/eng-pssr-2000-reg-9-6/file" or (a["url"] or "").startswith("/api/regulations/") for a in email["attachments"])
    assert call["channel"] == "call" and call["to"] == "••• ••• 0001" and call["from"] == "Steward Dispatch Line"
    sms = next(i for i in items if i["kind"] == "decision_request")
    assert sms["channel"] == "sms" and sms["mode"] == "dry_run" and sms["links"]["decisionRequestId"] and "Awaiting your answer" in sms["summary"]
    notice = next(i for i in items if i["kind"] == "notice")
    assert notice["to"] == "••• ••• 0002" and "keep visitors off the walkway" in notice["summary"] and "(you)" not in notice["title"].replace("(duty engineer", "")
    assert notice["summary"].startswith("Compliance notice: keep visitors off")
    opened = next(i for i in items if i["id"] == "issue:iss-my-feed-overpressure:opened")
    resolved = next(i for i in items if i["id"] == "issue:iss-my-feed-overpressure:resolved")
    assert opened["title"] == "High-severity issue opened: PG-601: overpressure" and opened["severity"] == "high" and at(resolved) >= at(opened)
    gap = next(i for i in items if i["kind"] == "compliance_gap" and i["links"]["issueId"] == alert["issueId"])
    assert gap["title"].startswith("Compliance gap raised: PV-301") and gap["siteId"] == BR
    walked = next(i for i in items if i["kind"] == "walkthrough")
    assert walked["links"]["patrolId"] == patrol["id"] and walked["title"].startswith("Walkthrough at Bristol: ") and walked["attachments"][0]["url"].startswith("/api/eye/frames/")
    window = next(i for i in items if i["kind"] == "maintenance")
    assert window["links"]["windowId"] in {w["id"] for w in booked} and window["title"].startswith("Maintenance booked at ")
    digest_item = next(i for i in items if i["kind"] == "owner_digest")
    assert digest_item["id"] == f"digest:{digest['id']}" and digest_item["siteId"] is None and digest_item["from"] == "Operations Director"
    assert digest_item["attachments"] == [dict(filename=digest["pdf"]["filename"], contentType="application/pdf", size=digest["pdf"]["size"],
                                               url=f"/api/owner/digests/{digest['id']}.pdf")]
    # seeded gaps were raised at seed time, not in this running system: their raise is not news
    seeded = [i for i in items if i["kind"] == "compliance_gap" and i["links"]["obligationId"] in ("ob-my-l901-esm", "ob-br-v504-gland", "ob-tm-tr202-strap")]
    assert not seeded
    assert provider == dict(emails=[], calls=[])


def test_filters_single_items_markdown_and_closing_a_seeded_gap(client, eye, monkeypatch):
    service = svc(client)
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", OWNER_EMAIL)
    overdue(service, "ob-br-pv301-exam", days=3)
    patrol = walk(client, BR, ["PV-301"])
    service.issues.raise_issue(MY, "overpressure", "high", "PG-601 reads 4.1 bar.", asset_tag="PG-601", issue_id="iss-my-md-overpressure")
    everything = feed(client)
    assert {i["siteId"] for i in feed(client, siteId=BR)["items"]} == {BR}
    assert {i["kind"] for i in feed(client, kind="owner_alert")["items"]} == {"owner_alert"}
    assert {i["kind"] for i in feed(client, kind="events")["items"]} <= {"issue", "compliance_gap", "maintenance", "walkthrough"}
    assert len(feed(client, limit=1)["items"]) == 1 and feed(client, limit=1)["total"] == everything["total"]
    newest = everything["items"][0]
    assert feed(client, since=newest["at"])["items"] == []
    assert client.get("/api/owner/notifications", params=dict(kind="gossip")).status_code == 400
    assert client.get("/api/owner/notifications", params=dict(since="yesterday")).status_code == 400
    assert client.get("/api/owner/notifications", params=dict(siteId="harbor-works")).status_code == 404
    one = client.get(f"/api/owner/notifications/{newest['id']}")
    assert one.status_code == 200 and one.json() == newest
    assert client.get("/api/owner/notifications/alert:oal-missing:email").status_code == 404

    md = client.get("/api/owner/notifications", params=dict(format="md"))
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith("# Owner notifications") and newest["title"] in md.text and f"id `{newest['id']}`" in md.text
    assert OWNER_EMAIL not in md.text and not re.search(r"synthetic|simulat", md.text, re.I)
    assert client.get("/api/owner/notifications", params=dict(format="xml")).status_code == 400

    # closing a seeded gap is news even though its seeded raise is not
    service.people.complete_obligation("ob-br-v504-gland")
    service.compliance_gaps.sync_issues()
    closed = [i for i in feed(client, kind="compliance_gap")["items"] if i["links"]["obligationId"] == "ob-br-v504-gland"]
    assert [i["id"].split(":")[-1] for i in closed] == ["closed"] and closed[0]["title"] == "Compliance gap closed: V-504: valve repair"
    assert patrol["id"] in {i["links"]["patrolId"] for i in everything["items"] if i["kind"] == "walkthrough"}


def test_repeated_walks_with_the_same_findings_are_not_news_for_six_hours(client, eye):
    service = svc(client)
    overdue(service, "ob-br-pv301-exam", days=3)
    first = walk(client, BR, ["PV-301"])
    second = walk(client, BR, ["PV-301"])
    walks = [i for i in feed(client, kind="walkthrough")["items"] if i["siteId"] == BR]
    assert [i["links"]["patrolId"] for i in walks] == [first["id"]], "the same findings again within 6 h are not news"
    overdue(service, "ob-br-v505-lift", days=2)
    third = walk(client, BR, ["PV-301", "V-505"])
    walks = [i for i in feed(client, kind="walkthrough")["items"] if i["siteId"] == BR]
    assert [i["links"]["patrolId"] for i in walks] == [third["id"], first["id"]] and second["id"] != third["id"]


# ---- the snapshot ---------------------------------------------------------------------------------------------------------

def test_snapshot_pdf_is_a_valid_report_with_every_site_and_its_percent(client, eye):
    service = svc(client)
    walk(client, BR, ["SP-102", "V-504"])
    response = client.get("/api/compliance/snapshot.pdf")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf" and response.content[:5] == b"%PDF-"
    assert "inline" in response.headers["content-disposition"] and ".pdf" in response.headers["content-disposition"]
    text, pages = pdf_text(response.content)
    flat = " ".join(text.split())
    for name in ("Myer Plant Room", "Bristol Dock Pump House", "Tomioka Silk Mill"):
        assert name in flat, name
    assert "83 %" in flat and "71 %" in flat and pages <= 4, pages
    for words in ("Needs your decision", "What changed since the last snapshot", "Obligations needing attention", "Agent activity", "Upcoming maintenance",
                  "Sources and licences", "Open Government Licence v3.0", "出典", "SP-102", "V-504", "Latest walkthrough"):
        assert words in flat, words
    assert not re.search(r"synthetic|simulat|scenario", flat, re.I)
    vic = service.regulations.get("vic-br-2018-reg-223")
    assert vic["summary"][:40] not in flat, "Victorian text is never reproduced"
    one, _ = pdf_text(client.get("/api/compliance/snapshot.pdf", params=dict(siteId=TM)).content)
    assert "Tomioka Silk Mill" in one and "Bristol Dock Pump House" not in one and "出典" in one
    assert client.get("/api/compliance/snapshot.pdf", params=dict(siteId="harbor-works")).status_code == 404


def test_snapshot_json_carries_the_obligations_regulations_agents_and_pdf_url(client, eye):
    walk(client, TM, ["TR-202"])
    snap = client.get("/api/compliance/snapshot").json()
    sites = {s["siteId"]: s for s in snap["sites"]}
    assert list(sites) == [MY, BR, TM] and snap["pdfUrl"] == "/api/compliance/snapshot.pdf"
    assert (sites[MY]["compliancePct"], sites[BR]["compliancePct"], sites[TM]["compliancePct"]) == (83.3, 71.4, 71.4)
    assert snap["complianceLine"] == "Myer 83 %, Bristol 71 %, Tomioka 71 %"
    blocked = sites[BR]["blocked"][0]
    assert blocked["obligationId"] == "ob-br-v504-gland" and blocked["blockedReason"] and blocked["owner"]["name"] and blocked["dueDate"]
    overdue_item = sites[MY]["overdue"][0]
    assert overdue_item["obligationId"] == "ob-my-l901-esm" and overdue_item["daysOverdue"] >= 8
    assert overdue_item["regulations"] and all(r["linkOnly"] and r["jurisdiction"] == "VIC-AU" and r["url"].startswith("https://") for r in overdue_item["regulations"])
    assert sites[TM]["walkthrough"]["bad"][0]["assetTag"] == "TR-202" and sites[TM]["walkthrough"]["bad"][0]["reasons"]
    assert [a["agentId"] for a in sites[BR]["agents"]] == ["bristol-manager", "bristol-engineer", "bristol-compliance", "bristol-technician"]
    assert any("Open Government Licence" in line for line in snap["attributions"]) and any("出典" in line for line in snap["attributions"])
    assert len(snap["decisions"]) >= 5 and all(d["text"] for d in snap["decisions"])
    assert client.get("/api/compliance/snapshot", params=dict(siteId=f"{BR},{TM}")).json()["siteIds"] == [BR, TM]


# ---- the digest -----------------------------------------------------------------------------------------------------------

def test_a_digest_is_a_dry_run_by_default_with_its_pdf_stored(client, provider):
    response = client.post("/api/owner/digest", json=dict(note="Before the board meeting"))
    assert response.status_code == 201, response.text
    digest = response.json()
    assert digest["email"]["mode"] == "dry_run" and "STEWARD_ALLOW_OWNER_ALERTS is not true" in digest["email"]["reason"]
    assert digest["subject"].startswith("Steward compliance snapshot · ") and digest["subject"].endswith(" · Myer 83 %, Bristol 71 %, Tomioka 71 %")
    assert digest["trigger"] == "manual" and digest["requestedBy"] == "operator" and digest["email"]["fromAgent"] == "director"
    pdf = client.get(digest["pdf"]["url"])
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    assert len(pdf.content) == digest["pdf"]["size"] and hashlib.sha256(pdf.content).hexdigest() == digest["pdf"]["sha256"]
    assert client.get("/api/owner/digests/odg-missing.pdf").status_code == 404
    assert client.post("/api/owner/digest", json={}, headers={"X-Steward-Actor": "bristol-manager"}).status_code == 403
    assert client.post("/api/owner/digest", json={}, headers={"X-Steward-Actor": "director"}).status_code == 201
    view = client.get("/api/owner/digests").json()
    assert view["schedule"]["live"] is False and view["schedule"]["digest"]["perDay"] == 3 and len(view["digests"]) == 2
    assert provider == dict(emails=[], calls=[])


def test_a_real_digest_goes_from_the_directors_identity_with_the_pdf_attached(client, provider, monkeypatch):
    owner_channel(monkeypatch, "director")
    digest = client.post("/api/owner/digest", json={}).json()
    assert digest["email"]["mode"] == "sent" and digest["email"]["providerRef"] == "msg-1" and digest["email"]["to"] == "o•••@example.com"
    [email] = provider["emails"]
    assert email["owner_channel"] is True and email["to"] == OWNER_EMAIL and email["sender_handle"] == "steward-director" and email["api_key"] == "key-director"
    assert email["subject"] == digest["subject"] and "Myer 83 %, Bristol 71 %, Tomioka 71 %" in email["subject"] and digest["id"] in email["idempotency_key"]
    [attachment] = email["attachments"]
    assert attachment["content_type"] == "application/pdf" and attachment["filename"] == digest["pdf"]["filename"]
    data = base64.b64decode(attachment["content_base64"])
    assert data[:5] == b"%PDF-" and hashlib.sha256(data).hexdigest() == digest["pdf"]["sha256"]
    assert "What needs your decision" in email["html"] and "What changed" in email["html"] and "synthetic" not in email["html"].lower()
    item = client.get(f"/api/owner/notifications/digest:{digest['id']}").json()
    assert item["mode"] == "sent" and item["fromAddress"] == "steward-director@inkboxmail.com"
    texts = client.get("/api/conversations", params=dict(kind="message", origin="inkbox")).json()
    real = next(c for c in texts if c["id"] == f"conv-msg-digest-{digest['id']}-email")  # a real email is a real text (real_only.py)
    assert real["channel"] == "email" and real["person"]["kind"] == "owner" and real["participants"] == ["director", "owner"]


def test_the_digest_scheduler_cadence_and_daily_cap(client, provider, monkeypatch):
    service = svc(client)
    owner_channel(monkeypatch, "director")
    monkeypatch.setenv("STEWARD_OWNER_DIGESTS_PER_DAY", "2")
    monkeypatch.setenv("STEWARD_AGENT_REPORTS", "false")
    owner = service.owner
    t0 = datetime.now(timezone.utc)
    first = owner.tick(t0)
    assert first["kind"] == "owner_digest" and first["mode"] == "sent"
    assert owner.tick(t0 + timedelta(minutes=10)) is None  # nothing important, not yet 4 h
    service.issues.raise_issue(MY, "overpressure", "high", "PG-601 reads 4.1 bar.", asset_tag="PG-601", issue_id="iss-my-cadence")
    assert owner.tick(t0 + timedelta(minutes=30)) is None, "an important change waits for the minimum gap (60 min)"
    second = owner.tick(t0 + timedelta(minutes=61))
    assert second["mode"] == "sent" and service.store.get("owner_digest", second["id"], "")["trigger"] == "change"
    service.issues.raise_issue(BR, "overpressure", "high", "PG-301 reads 3.9 bar.", asset_tag="PV-301", issue_id="iss-br-cadence")
    shift_issue(service, "iss-br-cadence", t0 + timedelta(minutes=100))
    third = owner.tick(t0 + timedelta(minutes=125))
    assert third["mode"] == "capped" and "STEWARD_OWNER_DIGESTS_PER_DAY=2" in service.store.get("owner_digest", third["id"], "")["email"]["reason"]
    assert owner.tick(t0 + timedelta(minutes=150)) is None, "a capped digest counts for the cadence too"
    assert len(provider["emails"]) == 2
    # four hours after the last one the scheduled digest comes only when something changed
    assert owner.tick(t0 + timedelta(hours=6, minutes=10)) is None
    service.issues.resolve_issue("iss-br-cadence", "Fixed and verified.", "bristol-engineer")
    record = service.store.get("issue", "iss-br-cadence")
    record["history"][-1]["at"] = record["resolvedAt"] = iso(t0 + timedelta(hours=6, minutes=15))
    service.store.put("issue", record, BR)
    later = owner.tick(t0 + timedelta(hours=6, minutes=20))
    assert later["mode"] == "capped"  # still two real digests in the rolling 24 h
    fresh = owner.tick(t0 + timedelta(hours=30))
    assert fresh is None or fresh["mode"] in ("sent", "capped")


def test_digests_are_dry_runs_without_the_owner_channel_and_paced_the_same_way(client, provider, monkeypatch):
    service = svc(client)
    monkeypatch.setenv("STEWARD_AGENT_REPORTS", "false")
    owner = service.owner
    t0 = datetime.now(timezone.utc)
    assert owner.tick(t0)["mode"] == "dry_run"
    assert owner.tick(t0 + timedelta(minutes=5)) is None
    owner_channel(monkeypatch, "director")
    sent = owner.tick(t0 + timedelta(minutes=6))
    assert sent["mode"] == "sent", "the live track starts at once when the owner channel is switched on"
    assert len(provider["emails"]) == 1


# ---- the owner channel ----------------------------------------------------------------------------------------------------

def test_the_owner_channel_needs_no_external_messages_and_reaches_only_the_owner(client, eye, provider, monkeypatch):
    service = svc(client)
    owner_channel(monkeypatch, "bristol-compliance")
    assert InkboxAdapter._owner_gate(OWNER_EMAIL, "email") is None and InkboxAdapter._owner_gate(OWNER_PHONE, "call") is None
    for recipient, channel in (("contractor@example.com", "email"), ("someone@example.com", "email"), ("+15550000009", "call"), (OWNER_EMAIL, "call")):
        with pytest.raises(ValueError):
            InkboxAdapter._owner_gate(recipient, channel)
    with pytest.raises(ProviderNotConfigured):
        InkboxAdapter._gate(OWNER_EMAIL)  # every other send still needs STEWARD_ALLOW_EXTERNAL_MESSAGES
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "contractor@example.com")
    with pytest.raises(ValueError):
        InkboxAdapter._owner_gate(OWNER_EMAIL, "email")  # the owner's address must be allowlisted too
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", f"{OWNER_EMAIL},{OWNER_PHONE}")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "false")
    with pytest.raises(ProviderNotConfigured):
        InkboxAdapter._owner_gate(OWNER_EMAIL, "email")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")

    overdue(service, "ob-br-pv301-exam", days=4)
    [alert_id] = service.patrols.start(BR, "operator", route=["PV-301"], origin="autoplay")["alertIds"]
    alert = client.get(f"/api/owner-alerts/{alert_id}").json()
    # contract 8: a walk's alert no longer contacts the owner itself (STEWARD_WALK_OWNER_ALERTS is off); the inspection chain does
    assert alert["origin"] == "autoplay" and alert["email"]["mode"] == "skipped" and alert["call"]["mode"] == "skipped"
    assert provider["emails"] == [] and provider["calls"] == []

    # the real adapter refuses any other recipient on the owner channel before it touches the network
    adapter = InkboxAdapter.__new__(InkboxAdapter)
    monkeypatch.undo()  # drop the stubs and the env; set only what this check needs
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", f"{OWNER_EMAIL},contractor@example.com")
    monkeypatch.setattr(InkboxAdapter, "client_with", lambda key: (_ for _ in ()).throw(AssertionError("no network")))
    with pytest.raises(ValueError):
        adapter.send_email(BR, "contractor@example.com", "Subject", "Text", "", owner_channel=True, api_key="k")
    with pytest.raises(ProviderNotConfigured):
        adapter.send_email(BR, OWNER_EMAIL, "Subject", "Text", "", api_key="k")  # the general gate: external messages are off


# ---- agent play reports ---------------------------------------------------------------------------------------------------

def test_agents_report_from_their_own_identities_only_with_news_and_inside_the_caps(client, eye, provider, monkeypatch):
    service = svc(client)
    agents = [f"{p}-{r}" for p in ("myer", "bristol", "tomioka") for r in ("manager", "engineer", "compliance", "technician")]
    owner_channel(monkeypatch, "director", *agents)
    monkeypatch.setenv("STEWARD_OWNER_DIGEST", "false")
    owner = service.owner
    t0 = datetime.now(timezone.utc)
    assert owner.tick(t0) is None, "nothing new: no report"
    overdue(service, "ob-br-pv301-exam", days=6)
    walk(client, BR, ["PV-301", "V-505"])
    t1 = datetime.now(timezone.utc) + timedelta(seconds=1)
    first = owner.tick(t1)
    assert first["kind"] == "agent_report" and first["agentId"] == "bristol-compliance" and first["mode"] == "sent"
    report = service.store.get("agent_report", first["id"], BR)
    email = provider["emails"][-1]
    assert email["sender_handle"] == "steward-bristol-compliance" and email["api_key"] == "key-bristol-compliance" and email["owner_channel"] is True
    assert email["subject"].startswith("[Bristol Dock Pump House] Compliance Officer: PV-301 pressure vessel examination 6 days overdue")
    assert [a["content_type"] for a in email["attachments"]] == ["application/pdf"] and base64.b64decode(email["attachments"][0]["content_base64"])[:5] == b"%PDF-"
    for words in ("What I did", "What I found", "What's next", "What I need from you"):
        assert words in email["html"]
    pdf = client.get(report["pdf"]["url"])
    assert pdf.status_code == 200 and "Bristol Dock Pump House" in pdf_text(pdf.content)[0] and "Myer Plant Room" not in pdf_text(pdf.content)[0]
    assert owner.tick(t1 + timedelta(minutes=20)) is None, "45 minutes between any two reports"
    second = owner.tick(t1 + timedelta(minutes=50))
    assert second["agentId"] == "bristol-engineer"
    engineer = provider["emails"][-1]
    assert engineer["sender_handle"] == "steward-bristol-engineer" and engineer["subject"] == ("[Bristol Dock Pump House] Site Engineer: walked the pump house: 1 of 2 look bad "
                                                                                                    "(PV-301: pressure vessel examination overdue by 6 days)")
    frames = [a for a in engineer["attachments"] if a["content_type"] == "image/jpeg"]
    assert frames and all(a.get("content_id") and f"cid:{a['content_id']}" in engineer["html"] for a in frames)
    assert same_picture(base64.b64decode(frames[0]["content_base64"]))
    # the same agents have nothing new, and the walk again is capped for the engineer today (1 a day)
    walk(client, BR, ["PV-301"])
    third = owner.tick(t1 + timedelta(minutes=100))
    assert third is None or third["agentId"] not in ("bristol-engineer", "bristol-compliance")
    items = feed(client, kind="agent_report")["items"]
    assert {i["from"] for i in items} >= {"Compliance Officer · Bristol", "Site Engineer · Bristol"}
    assert {i["fromAddress"] for i in items} >= {"steward-bristol-compliance@inkboxmail.com", "steward-bristol-engineer@inkboxmail.com"}
    assert all(i["mode"] == "sent" and i["channel"] == "email" for i in items)


def test_the_total_cap_holds_reports_back_and_dry_runs_need_no_identity(client, eye, provider, monkeypatch):
    service = svc(client)
    monkeypatch.setenv("STEWARD_OWNER_DIGEST", "false")
    monkeypatch.setenv("STEWARD_AGENT_REPORTS_PER_DAY", "1")
    monkeypatch.setenv("STEWARD_AGENT_REPORT_MIN_GAP_MINUTES", "0")
    owner = service.owner
    overdue(service, "ob-br-pv301-exam", days=6)
    walk(client, BR, ["PV-301"])
    t1 = datetime.now(timezone.utc) + timedelta(seconds=1)
    first = owner.tick(t1)
    assert first["mode"] == "dry_run"
    record = service.store.get("agent_report", first["id"], BR)
    assert record["email"]["fromAddress"] is None and "STEWARD_ALLOW_OWNER_ALERTS is not true" in record["email"]["reason"]
    assert owner.tick(t1 + timedelta(minutes=5)) is None, "STEWARD_AGENT_REPORTS_PER_DAY=1 holds the next one back"
    monkeypatch.setenv("STEWARD_AGENT_REPORTS_PER_DAY", "8")
    assert owner.tick(t1 + timedelta(minutes=6))["agentId"] != first["agentId"]
    assert provider == dict(emails=[], calls=[])


def test_manager_and_technician_reports_carry_bookings_coordination_and_dispatch_line_work(client, provider, monkeypatch):
    service = svc(client)
    owner_channel(monkeypatch, "bristol-manager", "bristol-technician", "myer-manager")
    owner = service.owner
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert owner.report_content("bristol-manager", since, datetime.now(timezone.utc)) is None, "nothing booked yet: nothing to report"
    booked = service.maintenance_planner.tick(datetime.now(timezone.utc))
    assert any(w["siteIds"] == [BR] for w in booked)
    service.people.send_notice(BR, "bristol-manager", "Please keep the walkway W-1201 closed until the check is signed.", crew_member_id="crew-br-duty-engineer",
                               notice_kind="compliance")
    moment = datetime.now(timezone.utc) + timedelta(seconds=1)
    manager = owner.prepare_report("bristol-manager", since, moment)
    assert manager["email"]["mode"] == "sent" and manager["subject"].startswith("[Bristol Dock Pump House] Plant Manager: booked ")
    assert manager["sections"]["found"] and manager["links"]["windowId"] and provider["emails"][-1]["sender_handle"] == "steward-bristol-manager"
    technician = owner.prepare_report("bristol-technician", since, moment)
    assert technician["subject"] == "[Bristol Dock Pump House] Field Technician: 1 message through the Steward Dispatch Line".replace("the Steward Dispatch Line", "the dispatch line")
    assert any("you" in line for line in technician["sections"]["found"]) and technician["email"]["fromAddress"] == "steward-bristol-technician@inkboxmail.com"
    assert technician["sections"]["need"][0].startswith("A reply to the dispatch line")
