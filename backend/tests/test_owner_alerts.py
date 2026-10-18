"""Compliance alert workflow (contract 7 §2): issue, teammate call, cross-site call, manager decision, owner email with
the file and the evidence, owner call, and the owner_alert record. Contract 8: by default the owner hears through the Site
Inspector's inspection, so the walk's owner email is kept on file (`skipped`) and no call is placed; with
STEWARD_WALK_OWNER_ALERTS=true the email goes to the outbox and the call to the phone-call service (fakes here), after the
alert's own gates, the daily cap and one alert per obligation per 24 h. Victorian PDFs are never attached. Nothing leaves
the process."""
import base64
import hashlib
import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.agents import display_name
from src.compliance_alerts import SKIPPED_REASON, STEPS
from src.main import create_app
from src.providers import InkboxAdapter, ProviderNotConfigured
from src.regulations import PDF_ROOT
from src.store import now
from src.verify import iso

from contract8_fakes import install_fakes

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
PREFIX = {MY: "MYER", BR: "BRISTOL", TM: "TOMIOKA"}


def jpeg_bytes() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (60, 70, 80)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = jpeg_bytes()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY", "STEWARD_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
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
    """Stubbed Inkbox sends. The adapter's own gate still has to pass: the owner channel's (STEWARD_ALLOW_OWNER_ALERTS, the
    owner's own allowlisted address or phone) for owner alerts, the general one (external-messages flag) otherwise."""
    sent = dict(emails=[], calls=[])

    def send_email(self, property_id, to, subject, body, reference, in_reply_to=None, html=None, attachments=None, sender_handle=None,
                   api_key=None, idempotency_key=None, owner_channel=False):
        (InkboxAdapter._owner_gate(to, "email") if owner_channel else InkboxAdapter._gate(to))
        sent["emails"].append(dict(property_id=property_id, to=to, subject=subject, body=body, html=html, attachments=list(attachments or []),
                                   sender_handle=sender_handle, idempotency_key=idempotency_key, owner_channel=owner_channel))
        return {"id": f"msg-{len(sent['emails'])}", "threadId": None, "messageId": None, "raw": {}}

    def place_call(self, property_id, to, script, owner_channel=False):
        (InkboxAdapter._owner_gate(to, "call") if owner_channel else InkboxAdapter._gate(to))
        sent["calls"].append(dict(property_id=property_id, to=to, script=script, owner_channel=owner_channel))
        return {"id": f"call-{len(sent['calls'])}", "status": "queued", "raw": {}}

    monkeypatch.setattr(InkboxAdapter, "send_email", send_email)
    monkeypatch.setattr(InkboxAdapter, "place_call", place_call)
    return sent


@pytest.fixture
def owner_live(client, monkeypatch):
    """STEWARD_WALK_OWNER_ALERTS=true with the contract-8 outbox and phone calls faked: the alert hands its email and call over."""
    monkeypatch.setenv("STEWARD_WALK_OWNER_ALERTS", "true")
    return install_fakes(svc(client))


def emails(fakes):
    return [item for item in fakes.outbox.items if item["channel"] == "email"]


def live(monkeypatch, *sites):
    """Every gate on (tests only; the provider is stubbed)."""
    monkeypatch.setenv("INKBOX_API_KEY", "fixture-key")
    for site in sites:
        monkeypatch.setenv(f"INKBOX_IDENTITY_{PREFIX[site]}_COMPLIANCE", f"steward-{PREFIX[site].lower()}-compliance")
    monkeypatch.setenv("INKBOX_IDENTITY_DISPATCH", "steward-dispatch")
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("INKBOX_OWNER_PHONE", "+15550000001")
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "owner@example.com,+15550000001")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")


def overdue(service, obligation_id, days=6):
    record = service.store.get("obligation", obligation_id)
    record.update(dueAt=iso(datetime.now(timezone.utc) - timedelta(days=days, hours=2)), status="overdue", blockedBy=None, blockedReason=None)
    service.store.put("obligation", record, record["siteId"])


def blocked(service, obligation_id, reason):
    record = service.store.get("obligation", obligation_id)
    record.update(status="blocked", blockedReason=reason)
    service.store.put("obligation", record, record["siteId"])


def walk(client, site, route):
    response = client.post("/api/patrols", json=dict(siteId=site, route=route))
    assert response.status_code == 202, response.text
    return response.json()


def alerts_for(client, patrol):
    return [client.get(f"/api/owner-alerts/{alert_id}").json() for alert_id in patrol["alertIds"]]


def test_alert_workflow_steps_conversations_and_owner_contact_through_the_inspection_by_default(client, eye, provider):
    service = svc(client)
    overdue(service, "ob-br-pv301-exam", days=9)
    patrol = walk(client, BR, ["PV-301", "V-505"])
    [alert] = alerts_for(client, patrol)
    label = next(l for l in client.get(f"/api/properties/{BR}/labels").json() if l["assetTag"] == "PV-301")
    assert alert["state"] == "completed" and alert["severity"] == "high" and alert["title"] == "PV-301: Pressure vessel examination overdue by 9 days"
    assert [step["name"] for step in alert["steps"]] == list(STEPS) == ["issue", "teammate_call", "cross_site_call", "manager_decision", "owner_email", "owner_call"]
    assert (alert["obligationId"], alert["labelId"], alert["patrolId"], alert["siteId"]) == ("ob-br-pv301-exam", label["id"], patrol["id"], BR)

    issue = service.store.get("issue", alert["issueId"], BR)
    assert issue["kind"] == "compliance_overdue" and issue["severity"] == "high" and issue["status"] == "open" and issue["obligationId"] == "ob-br-pv301-exam"
    assert "eng-pssr-2000-reg-9-6" in issue["regulationIds"] and issue["evidenceFrameIds"] == [label["frameId"]]
    assert issue["assigneeId"] == "crew-br-restoration-lead"  # the manager assigned the crew owner

    teammate, cross, manager = (service.conversations.get(cid) for cid in alert["conversationIds"])
    assert teammate["kind"] == "call" and set(teammate["participants"]) == {"bristol-engineer", "bristol-compliance"} and teammate["siteIds"] == [BR]
    assert 4 <= len(teammate["transcript"]) <= 6 and teammate["transcript"][0]["speaker"] == "bristol-engineer"
    said = " ".join(line["text"] for line in teammate["transcript"])
    assert "the Pressure Systems Safety Regulations 2000, regulation 9(6)-(7)" in said and "Alasdair Pennock" in said and "overdue by 9 days" in said
    assert teammate["summaryBy"] == "hand-seed" and teammate["summary"]["headline"].startswith("PV-301")
    assert set(cross["participants"]) == {"bristol-compliance", "myer-compliance"} and set(cross["siteIds"]) == {BR, MY}
    assert 3 <= len(cross["transcript"]) <= 4 and cross["transcript"][-1]["speaker"] == "myer-compliance"
    assert set(manager["participants"]) == {"bristol-compliance", "bristol-manager"} and manager["siteIds"] == [BR] and 2 <= len(manager["transcript"]) <= 3
    assert any(line["speaker"] == "bristol-manager" and line["text"].startswith("Approved: tell the owner now.") for line in manager["transcript"])
    assert alert["decision"]["by"] == "bristol-manager" and alert["decision"]["assignedTo"] == "crew-br-restoration-lead"

    email = alert["email"]  # kept on file: the inspection chain is what reaches the owner
    assert email["mode"] == "skipped" and email["reason"] == SKIPPED_REASON and email["to"] is None and email["outboxId"] is None
    assert email["subject"] == "[Bristol Dock Pump House] Compliance: Steam receiver PV-301 written-scheme thorough examination certificate (overdue by 9 days)"
    assert "cid:evidence-1-" in email["html"] and "https://www.legislation.gov.uk/uksi/2000/128/regulation/9" in email["html"]
    assert "Shall we book the competent-person examiner for" in email["html"] and email["fromAgent"] == "bristol-compliance"
    assert "Open Government Licence v3.0" in email["html"] and "Shall we book" in email["text"]
    files = {a["filename"]: a for a in email["attachments"]}
    assert files["evidence-pv-301-1.jpg"] == dict(filename="evidence-pv-301-1.jpg", contentType="image/jpeg", size=len(JPEG), inline=True, kind="frame")
    assert files["uksi_2000_128.pdf"]["size"] == (PDF_ROOT / "regulations" / "uksi_2000_128.pdf").stat().st_size and not files["uksi_2000_128.pdf"]["inline"]
    assert files[f"evidence-{alert['id']}.txt"]["contentType"] == "text/plain"
    call = alert["call"]
    assert call["mode"] == "skipped" and call["reason"] == SKIPPED_REASON and call["callId"] is None and len(call["brief"]) <= 1000
    assert call["goal"].startswith("Get the owner's decision on PV-301") and [o["id"] for o in call["options"]] == ["yes", "not-yet"]
    for words in ("Bristol Dock Pump House", "Pressure Systems Safety Regulations 2000", "emailed the owner the file and the evidence",
                  "shall we book the competent-person examiner"):
        assert words in call["brief"]
    assert not call["brief"].startswith("Hello")  # a task for a conversation, never a speech
    assert [s["summary"] for s in alert["steps"][-2:]][1] == "Owner contact goes through the inspection; no call from the walkthrough."
    assert provider == dict(emails=[], calls=[])  # the walk never sends to the owner itself

    listed = client.get(f"/api/owner-alerts?siteId={BR}&limit=5").json()
    assert [a["id"] for a in listed] == [alert["id"]] and client.get("/api/owner-alerts/oal-missing").status_code == 404
    changes = [c for c in service.store.all("change", BR) if c["type"] == "compliance_alert" and c["refId"] == alert["id"]]
    assert [c["status"] for c in changes] == ["queued", "started"] + ["step"] * len(STEPS) + ["completed"]
    assert [c["step"] for c in changes if c["status"] == "step"] == list(STEPS) and all(c["alertId"] == alert["id"] for c in changes)


def test_with_owner_contact_through_the_inspection_a_later_walk_reuses_the_alert_even_when_live(client, eye, provider, monkeypatch):
    """Contract 8: no fresh alert (and no fresh round of calls) on every walk once live messaging is on."""
    service = svc(client)
    overdue(service, "ob-br-pv301-exam", days=3)
    first = walk(client, BR, ["PV-301"])
    live(monkeypatch, BR)
    second = walk(client, BR, ["PV-301"])
    assert second["alertIds"] == first["alertIds"] and len(service.store.all("owner_alert", BR)) == 1 and provider == dict(emails=[], calls=[])


def test_owner_alert_hands_its_email_and_call_over_only_when_every_gate_holds(client, eye, provider, owner_live, monkeypatch):
    service = svc(client)
    live(monkeypatch, BR, MY, TM)
    overdue(service, "ob-br-pv301-exam", days=4)
    [bristol] = alerts_for(client, walk(client, BR, ["PV-301"]))
    assert bristol["email"]["mode"] == "queued" and bristol["email"]["outboxId"] and bristol["email"]["to"] == "o•••@example.com"
    assert bristol["call"]["mode"] == "queued" and bristol["call"]["callId"] and bristol["call"]["to"] == "••• ••• 0001"
    [item] = emails(owner_live)
    assert (item["siteId"], item["toRole"], item["sender"], item["purpose"]) == (BR, "owner", "bristol-compliance", "owner_alert")
    assert item["subject"] == bristol["email"]["subject"] and item["html"] == bristol["email"]["html"] and bristol["id"] in item["dedupeKey"]
    by_name = {a["filename"]: a for a in item["attachments"]}
    frame = by_name["evidence-pv-301-1.jpg"]
    assert frame["content_type"] == "image/jpeg" and frame["content_id"] and f"cid:{frame['content_id']}" in item["html"]
    assert base64.b64decode(frame["content_base64"]) == JPEG
    assert base64.b64decode(by_name["uksi_2000_128.pdf"]["content_base64"])[:4] == b"%PDF"
    assert base64.b64decode(by_name[f"evidence-{bristol['id']}.txt"]["content_base64"]).decode().startswith(f"Steward compliance evidence {bristol['id']}")
    [call] = owner_live.voice_calls.calls
    assert (call["purpose"], call["caller"], call["calleeRole"], call["siteId"]) == ("owner_compliance", "bristol-compliance", "owner", BR)
    assert call["goal"] == bristol["call"]["goal"] and "shall we book the competent-person examiner" in call["goal"]
    assert [o["id"] for o in call["options"]] == ["yes", "not-yet"] and set(call["canDo"]) == {"email_file", "note", "callback"}
    assert call["file"]["subject"] == bristol["email"]["subject"] and call["refs"]["alertId"] == bristol["id"]

    overdue(service, "ob-my-fe1001-monthly", days=2)
    [myer] = alerts_for(client, walk(client, MY, ["FE-1001"]))
    assert myer["email"]["mode"] == "queued" and emails(owner_live)[1]["sender"] == "myer-compliance"
    assert not [a for a in emails(owner_live)[1]["attachments"] if a["content_type"] == "application/pdf"]  # Victorian texts are link-only
    assert "https://www.legislation.vic.gov.au/" in myer["email"]["html"] and "link only" in myer["email"]["html"]

    blocked(service, "ob-tm-bw251-permit", "Work order TM-WO-2026-117 proposes drilling into BW-251; no permission to alter its current state is on file.")
    [mill] = alerts_for(client, walk(client, TM, ["BW-251"]))
    assert mill["email"]["mode"] == "queued" and mill["title"] == "BW-251: Alteration permission blocked" and mill["obligationStatus"] == "blocked"
    pdfs = [a["filename"] for a in emails(owner_live)[2]["attachments"] if a["content_type"] == "application/pdf"]
    assert pdfs == ["jp_act_1950_214_cultural_properties_r20250601.pdf"] and "出典" in mill["email"]["html"]
    assert service.store.get("issue", mill["issueId"], TM)["kind"] in ("compliance_blocked", "alteration_permit")
    every = [a["filename"] for e in emails(owner_live) for a in e["attachments"]]
    assert not [name for name in every if name.lower().startswith(("vic_", "vba_"))] and len(owner_live.voice_calls.calls) == 3
    assert provider == dict(emails=[], calls=[])  # nothing goes to Inkbox directly: the outbox paces it


def test_daily_cap_and_one_alert_per_obligation_per_day(client, eye, provider, owner_live, monkeypatch):
    service = svc(client)
    live(monkeypatch, BR)
    monkeypatch.setenv("STEWARD_OWNER_ALERTS_PER_DAY", "1")
    overdue(service, "ob-br-pv301-exam", days=3)
    overdue(service, "ob-br-v505-lift", days=2)
    first = walk(client, BR, ["PV-301", "V-505"])
    sent, capped = alerts_for(client, first)
    assert sent["email"]["mode"] == "queued" and sent["call"]["mode"] == "queued"
    assert capped["email"]["mode"] == "capped" and capped["call"]["mode"] == "capped"
    assert "STEWARD_OWNER_ALERTS_PER_DAY=1" in capped["email"]["reason"] and capped["call"]["reason"] == capped["email"]["reason"]
    assert capped["email"]["subject"].startswith("[Bristol Dock Pump House] Compliance: Receiver safety valve V-505") and "cid:" in capped["email"]["html"]
    assert {a["filename"] for a in capped["email"]["attachments"]} >= {"evidence-v-505-1.jpg", "uksi_2000_128.pdf", f"evidence-{capped['id']}.txt"}
    assert "safety valve lift test for V-505" in capped["call"]["brief"] and (len(emails(owner_live)), len(owner_live.voice_calls.calls)) == (1, 1)

    second = walk(client, BR, ["PV-301", "V-505"])  # within 24 h: the walk reuses the alerts, nothing new is raised or sent
    assert second["alertIds"] == first["alertIds"] and len(service.store.all("owner_alert", BR)) == 2
    assert (len(emails(owner_live)), len(owner_live.voice_calls.calls)) == (1, 1)

    monkeypatch.setenv("STEWARD_OWNER_ALERTS_PER_DAY", "10")
    label = next(l for l in service.store.all("patrol_label", BR) if l["assetTag"] == "PV-301")
    obligation = next(o for o in service.people.obligations(BR) if o["id"] == "ob-br-pv301-exam")
    again, reused = service.patrols.alerts.open(BR, label, obligation, None, "bristol-engineer", "manual", reuse=False)
    assert reused is False
    again = service.patrols.alerts.run(again["id"])
    assert again["email"]["mode"] == "capped" and "already alerted about this obligation in the last 24 h" in again["email"]["reason"]
    assert (len(emails(owner_live)), len(owner_live.voice_calls.calls)) == (1, 1)


def test_autoplayed_walkthroughs_send_on_the_owner_channel_like_manual_ones(client, eye, provider, owner_live, monkeypatch):
    """Owner, Oct 18: owner-facing sends are capped, deduplicated and reach only the owner, so an autoplayed (continuous) walk's
    alert emails and calls the owner like one started by hand; STEWARD_SCENARIO_AUTOPLAY_LIVE is not needed."""
    service = svc(client)
    live(monkeypatch, BR)
    overdue(service, "ob-br-pv301-exam", days=3)
    patrol = service.patrols.start(BR, "operator", route=["PV-301"], origin="autoplay")
    [alert] = alerts_for(client, patrol)
    assert patrol["origin"] == "autoplay" and alert["origin"] == "autoplay"
    assert alert["email"]["mode"] == "queued" and alert["call"]["mode"] == "queued" and alert["email"]["reason"] is None
    assert [e["toRole"] for e in emails(owner_live)] == ["owner"] and [c["calleeRole"] for c in owner_live.voice_calls.calls] == ["owner"]
    second = walk(client, BR, ["PV-301"])  # the next walk reuses the alert: one per obligation per 24 h
    assert second["alertIds"] == [alert["id"]] and (len(emails(owner_live)), len(owner_live.voice_calls.calls)) == (1, 1)


def test_the_owner_channel_sends_without_external_messages_and_only_to_the_owner(client, eye, provider, owner_live, monkeypatch):
    service = svc(client)
    live(monkeypatch, BR)
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "false")  # contractor dispatch, notices and escalations stay off
    overdue(service, "ob-br-pv301-exam", days=3)
    [alert] = alerts_for(client, walk(client, BR, ["PV-301"]))
    assert alert["email"]["mode"] == "queued" and alert["call"]["mode"] == "queued"
    assert emails(owner_live)[0]["toRole"] == "owner" and owner_live.voice_calls.calls[0]["calleeRole"] == "owner"
    with pytest.raises(ProviderNotConfigured):
        InkboxAdapter._gate("owner@example.com")  # every other outbound message still needs STEWARD_ALLOW_EXTERNAL_MESSAGES
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "owner@example.com,+15550000001,contractor@example.com")
    for recipient, channel in (("contractor@example.com", "email"), ("+15550000002", "call"), ("owner@example.com", "call")):
        with pytest.raises(ValueError):
            InkboxAdapter._owner_gate(recipient, channel)
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "false")
    overdue(service, "ob-br-v505-lift", days=2)
    [held] = alerts_for(client, walk(client, BR, ["V-505"]))
    assert held["email"]["mode"] == "dry_run" and held["email"]["reason"] == "STEWARD_ALLOW_OWNER_ALERTS is not true" and len(emails(owner_live)) == 1


def test_missing_recipient_or_allowlist_stays_dry_run(client, eye, provider, owner_live, monkeypatch):
    service = svc(client)
    live(monkeypatch, BR)
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "someone-else@example.com")
    monkeypatch.setenv("INKBOX_OWNER_PHONE", "# not set")
    overdue(service, "ob-br-pv301-exam", days=3)
    [alert] = alerts_for(client, walk(client, BR, ["PV-301"]))
    assert alert["email"]["mode"] == "dry_run" and alert["email"]["reason"] == "INKBOX_OWNER_EMAIL is not in INKBOX_ALLOWED_RECIPIENTS"
    assert alert["call"]["mode"] == "dry_run" and "INKBOX_OWNER_PHONE is not set" in alert["call"]["reason"]
    assert provider == dict(emails=[], calls=[]) and alert["liveAt"] is None and owner_live.outbox.items == [] and owner_live.voice_calls.calls == []


def test_an_outbox_or_call_failure_is_recorded_and_the_workflow_finishes(client, eye, owner_live, monkeypatch):
    service = svc(client)
    live(monkeypatch, BR)

    def broken(*args, **kwargs):
        raise RuntimeError("queue down")

    monkeypatch.setattr(owner_live.outbox, "email", broken)
    monkeypatch.setattr(owner_live.voice_calls, "request", broken)
    overdue(service, "ob-br-pv301-exam", days=3)
    [alert] = alerts_for(client, walk(client, BR, ["PV-301"]))
    assert alert["state"] == "completed" and alert["email"]["mode"] == "failed" and alert["call"]["mode"] == "failed"
    assert alert["email"]["reason"] == "The outbox did not take the email (RuntimeError); nothing reported as delivered." and alert["email"]["providerRef"] is None
    assert alert["call"]["reason"] == "The call could not be queued (RuntimeError); nothing reported as delivered."


def test_inkbox_send_email_carries_html_and_attachments_through_the_gate(monkeypatch):
    adapter = InkboxAdapter()
    attachment = dict(filename="evidence.jpg", content_type="image/jpeg", content_base64=base64.b64encode(JPEG).decode(), content_id="frame-1", size=len(JPEG))
    with pytest.raises(ProviderNotConfigured):
        adapter.send_email(BR, "owner@example.com", "Subject", "Text", "", html="<p>x</p>", attachments=[attachment])
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "owner@example.com")
    sent = []

    class Message:
        id, thread_id, message_id = "msg-1", None, "<msg-1@inkbox>"

    class Identity:
        agent_handle, email_address = "steward-bristol-compliance", "steward-bristol-compliance@inkboxmail.com"

        def send_email(self, **kwargs):
            sent.append(kwargs)
            return Message()

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_identity(self, handle):
            assert handle == "steward-bristol-compliance"
            return Identity()

    keys = []
    monkeypatch.setattr(adapter, "client_with", lambda key: keys.append(key) or FakeClient())
    with pytest.raises(ValueError):
        adapter.send_email(BR, "stranger@example.com", "Subject", "Text", "")
    result = adapter.send_email(BR, "owner@example.com", "Subject", "Text", "", html="<p>x</p>", attachments=[attachment],
                                sender_handle="steward-bristol-compliance", api_key="agent-key", idempotency_key="steward-oal-1-email")
    assert result["id"] == "msg-1" and keys == ["agent-key"]
    assert sent == [dict(to=["owner@example.com"], subject="Subject", body_text="Text", in_reply_to_message_id=None, body_html="<p>x</p>",
                         attachments=[dict(filename="evidence.jpg", content_type="image/jpeg", content_base64=attachment["content_base64"], content_id="frame-1")],
                         idempotency_key="steward-oal-1-email")]
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", "owner@example.com")
    assert InkboxAdapter.owner_email() == "owner@example.com"
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", "# the owner's address")
    assert InkboxAdapter.owner_email() == ""
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", "not-an-address")
    assert InkboxAdapter.owner_email() == ""


def test_a_dry_run_alert_gives_way_once_live_messaging_is_switched_on(client, eye, provider, owner_live, monkeypatch):
    service = svc(client)
    overdue(service, "ob-br-pv301-exam", days=3)
    [dry] = alerts_for(client, walk(client, BR, ["PV-301"]))
    assert dry["email"]["mode"] == "dry_run"
    calls_before = len(service.store.all("conversation", ""))
    assert walk(client, BR, ["PV-301"])["alertIds"] == [dry["id"]]  # live messaging still off: the alert is reused, no new calls
    assert len(service.store.all("conversation", "")) == calls_before + 1  # only the walker's summary message to the manager
    live(monkeypatch, BR)
    [real] = alerts_for(client, walk(client, BR, ["PV-301"]))
    assert real["id"] != dry["id"] and real["email"]["mode"] == "queued" and real["call"]["mode"] == "queued" and len(emails(owner_live)) == 1
    assert walk(client, BR, ["PV-301"])["alertIds"] == [real["id"]] and len(emails(owner_live)) == 1  # it reached the owner: reused
    service.store.put("owner_alert", dict(real, state="failed"), BR)
    retried = walk(client, BR, ["PV-301"])["alertIds"]  # a failed alert is not reused, and the obligation's live send is not repeated
    assert retried != [real["id"]] and alerts_for(client, dict(alertIds=retried))[0]["email"]["mode"] == "capped"
    assert len(emails(owner_live)) == 1


