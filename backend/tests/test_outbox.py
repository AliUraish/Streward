"""The outbox (contract 8 §2): one paced queue for everything that reaches a person. One email and one call per 2 minutes, never
two calls at once (the gap counts from the end of the previous call), nothing in the first 3 minutes after a restart, daily caps
that hold items back as `capped`, dry runs with the full content when a gate fails, dedupe, CC rules, the producer's record kept
in step, and the read-only routes with masked addresses. The provider is stubbed; nothing leaves the process."""
import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.agents import COUNSEL, env_suffix
from src.main import create_app
from src.outbox import Outbox, stamp
from src.providers import InkboxAdapter

MY, BR = "myer-plant", "bristol-pumps"
OWNER_EMAIL, CONTRACTOR_EMAIL, PHONE = "owner@example.com", "contractor@example.com", "+15550000001"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def channel(monkeypatch, *agents):
    """The person channel on (tests only; the provider is stubbed): identities for the named agents and the dispatch line, the
    owner's and the contractor's addresses and the phone allowlisted, STEWARD_ALLOW_OWNER_ALERTS=true."""
    monkeypatch.setenv("INKBOX_API_KEY", "fixture-key")
    for agent in agents:
        suffix = env_suffix(agent)
        monkeypatch.setenv(f"INKBOX_IDENTITY_{suffix}", f"steward-{agent}")
        monkeypatch.setenv(f"INKBOX_AGENT_KEY_{suffix}", f"key-{agent}")
    monkeypatch.setenv("INKBOX_IDENTITY_DISPATCH", "steward-dispatch")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("INKBOX_OWNER_PHONE", PHONE)
    monkeypatch.setenv("INKBOX_CONTRACTOR_EMAIL", CONTRACTOR_EMAIL)
    monkeypatch.setenv("INKBOX_CONTRACTOR_PHONE", PHONE)
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", f"{OWNER_EMAIL},{CONTRACTOR_EMAIL},{PHONE}")


@pytest.fixture
def provider(monkeypatch):
    """Stubbed Inkbox sends that still run the adapter's own gates."""
    sent = dict(emails=[], sms=[], calls=[])

    def send_email(self, property_id, to, subject, body, reference, in_reply_to=None, html=None, attachments=None, sender_handle=None,
                   api_key=None, idempotency_key=None, owner_channel=False, cc=None, person_role=None, internal=False):
        if owner_channel:
            InkboxAdapter._owner_gate(to, "email")
        elif person_role:
            InkboxAdapter._person_gate(to, "email", person_role)
        elif internal:
            InkboxAdapter._internal_gate(to)
        else:
            InkboxAdapter._gate(to)
        copies = InkboxAdapter._cc_gate(cc or [])
        sent["emails"].append(dict(to=to, subject=subject, body=body, html=html, attachments=list(attachments or []), sender_handle=sender_handle,
                                   api_key=api_key, idempotency_key=idempotency_key, owner_channel=owner_channel, cc=copies, person_role=person_role,
                                   internal=internal))
        return {"id": f"msg-{len(sent['emails'])}", "threadId": None, "messageId": None, "raw": {}}

    def send_sms(self, property_id, to, body, conversation_id=None, idempotency_key=None, person_role=None):
        InkboxAdapter._person_gate(to, "sms", person_role) if person_role else InkboxAdapter._gate(to)
        sent["sms"].append(dict(to=to, body=body, person_role=person_role))
        return {"id": f"sms-{len(sent['sms'])}", "conversationId": None, "raw": {}}

    monkeypatch.setattr(InkboxAdapter, "send_email", send_email)
    monkeypatch.setattr(InkboxAdapter, "send_sms", send_sms)
    return sent


def paced(monkeypatch, grace=0):
    monkeypatch.setenv("STEWARD_OUTBOX_PACE_INLINE", "true")
    monkeypatch.setenv("STEWARD_OUTBOX_BOOT_GRACE_SECONDS", str(grace))


def mail(service, n=1, **extra):
    fields = dict(sender="bristol-manager", to_role="owner", subject=f"Subject {n}", text=f"Body {n}", site_id=BR, purpose="test")
    fields.update(extra)
    return service.outbox.email(**fields)


# ---- pacing ------------------------------------------------------------------------------------------------------------------

def test_two_person_emails_go_out_two_minutes_apart_in_priority_order(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager", "director")
    paced(monkeypatch)
    later = mail(service, 1, priority=7)
    first = mail(service, 2, sender="director", priority=3)
    assert later["status"] == first["status"] == "queued" and provider["emails"] == []
    t0 = datetime.now(timezone.utc)
    service.outbox.tick(t0)
    assert [e["subject"] for e in provider["emails"]] == ["Subject 2"], "the higher priority goes first"
    service.outbox.tick(t0 + timedelta(seconds=60))
    waiting = service.outbox.get(later["id"])
    assert waiting["status"] == "queued" and waiting["earliestAt"] == stamp(t0 + timedelta(seconds=120)) and len(provider["emails"]) == 1
    service.outbox.tick(t0 + timedelta(seconds=121))
    assert service.outbox.get(later["id"])["status"] == "sent" and len(provider["emails"]) == 2
    sent = service.outbox.get(first["id"])
    assert sent["providerRef"] == "msg-1" and sent["sentAt"] == stamp(t0) and provider["emails"][0]["owner_channel"] is True


def test_nothing_person_facing_goes_out_during_the_boot_grace(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    paced(monkeypatch, grace=180)
    item = mail(service)
    booted = service.outbox.booted_at
    service.outbox.tick(booted + timedelta(seconds=60))
    assert service.outbox.get(item["id"])["earliestAt"] == stamp(booted + timedelta(seconds=180)) and provider["emails"] == []
    assert service.outbox.status(booted + timedelta(seconds=60))["bootGraceUntil"] == stamp(booted + timedelta(seconds=180))
    service.outbox.tick(booted + timedelta(seconds=181))
    assert service.outbox.get(item["id"])["status"] == "sent"


def test_unpaced_with_the_workers_off_sends_at_enqueue(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    first, second = mail(service, 1), mail(service, 2)
    assert first["status"] == second["status"] == "sent" and len(provider["emails"]) == 2


def test_the_daily_cap_holds_items_back_as_capped(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    monkeypatch.setenv("STEWARD_OUTBOX_EMAILS_PER_DAY", "2")
    items = [mail(service, n) for n in range(3)]
    assert [i["status"] for i in items] == ["sent", "sent", "capped"]
    assert "STEWARD_OUTBOX_EMAILS_PER_DAY=2" in items[2]["reason"] and len(provider["emails"]) == 2


def test_a_gate_that_fails_makes_a_dry_run_with_the_full_content(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "false")
    item = mail(service, html="<p>Body</p>")
    assert item["status"] == "dry_run" and "STEWARD_ALLOW_OWNER_ALERTS is not true" in item["reason"] and provider["emails"] == []
    payload = service.store.get("outbox_payload", item["id"], "")
    assert payload["text"] == "Body 1" and payload["html"] == "<p>Body</p>" and item["subject"] == "Subject 1"
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", CONTRACTOR_EMAIL)
    refused = mail(service, 2)
    assert refused["status"] == "dry_run" and "INKBOX_OWNER_EMAIL is not in INKBOX_ALLOWED_RECIPIENTS" in refused["reason"]
    no_identity = mail(service, 3, sender="tomioka-manager")
    assert no_identity["status"] == "dry_run" and "no Inkbox identity" in no_identity["reason"]


def test_dedupe_returns_the_existing_item(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    first = mail(service, 1, dedupe_key="digest:odg-1")
    again = mail(service, 2, dedupe_key="digest:odg-1")
    assert again["id"] == first["id"] and len(provider["emails"]) == 1


# ---- recipients and copies -----------------------------------------------------------------------------------------------------

def test_cc_names_agents_and_roles_and_a_random_address_is_refused(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager", COUNSEL)
    item = mail(service, to_role="contractor", cc=[COUNSEL, "bristol-manager", "owner", "contractor"])
    assert item["status"] == "sent" and [c["id"] for c in item["cc"]] == [COUNSEL, "bristol-manager", "owner"]
    [email] = provider["emails"]
    assert email["to"] == CONTRACTOR_EMAIL and email["person_role"] == "contractor" and email["owner_channel"] is False
    assert email["cc"] == ["steward-compliance-counsel@inkboxmail.com", "steward-bristol-manager@inkboxmail.com", OWNER_EMAIL]
    for bad in ("someone@example.com", "operator", "nobody"):
        with pytest.raises(ValueError):
            mail(service, cc=[bad])
    with pytest.raises(ValueError):
        InkboxAdapter._cc_gate(["someone@example.com"])
    with pytest.raises(ValueError):
        mail(service, to_role="lawyer")


def test_each_role_reaches_only_its_own_address(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    employee = mail(service, to_role="employee")
    assert employee["status"] == "sent" and provider["emails"][-1]["to"] == OWNER_EMAIL, "the employee falls back to the owner's own address"
    with pytest.raises(ValueError):
        InkboxAdapter._person_gate(OWNER_EMAIL, "email", "contractor")
    with pytest.raises(ValueError):
        InkboxAdapter._person_gate("someone@example.com", "email", "employee")
    assert InkboxAdapter._person_gate(CONTRACTOR_EMAIL, "email", "contractor") is None


def test_the_producer_record_follows_the_item(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    paced(monkeypatch)
    service.store.put("test_record", dict(id="rec-1", email=dict(subject="S")), BR)
    item = mail(service, refs=dict(record=dict(kind="test_record", id="rec-1", propertyId=BR, field="email")))
    t0 = datetime.now(timezone.utc)
    service.outbox.tick(t0)
    record = service.store.get("test_record", "rec-1", BR)
    assert record["email"] == dict(subject="S", mode="sent", providerRef="msg-1", reason=None, outboxId=item["id"], at=stamp(t0))


def test_attachments_go_with_the_email_and_only_their_metadata_is_listed(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    data = base64.b64encode(b"%PDF-1.4 test").decode("ascii")
    item = mail(service, attachments=[dict(filename="a.pdf", content_type="application/pdf", content_base64=data)])
    assert item["attachments"] == [dict(filename="a.pdf", contentType="application/pdf", size=13, inline=False)]
    assert provider["emails"][0]["attachments"] == [dict(filename="a.pdf", content_type="application/pdf", content_base64=data)]
    with pytest.raises(ValueError):
        mail(service, attachments=[dict(filename="b.pdf", content_type="application/pdf")])


def test_internal_mail_is_not_paced_but_capped_per_hour(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-compliance", "bristol-manager")
    paced(monkeypatch, grace=600)
    monkeypatch.setenv("STEWARD_ALLOW_AGENT_EMAIL", "true")
    monkeypatch.setenv("STEWARD_OUTBOX_INTERNAL_EMAILS_PER_HOUR", "1")
    args = dict(sender="bristol-compliance", to_agent="bristol-manager", subject="Evidence", text="Frames attached.", site_id=BR, purpose="evidence")
    first, second = service.outbox.internal_email(**args), service.outbox.internal_email(**args)
    service.outbox.tick()
    assert service.outbox.get(first["id"])["status"] == "sent" and service.outbox.get(second["id"])["status"] == "capped"
    [email] = provider["emails"]
    assert email["internal"] is True and email["to"] == "steward-bristol-manager@inkboxmail.com"
    with pytest.raises(ValueError):
        service.outbox.internal_email(**dict(args, cc=["owner"]))


def test_texts_are_paced_and_the_external_gate_still_applies(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-technician")
    sms = service.outbox.sms(sender="bristol-technician", to_role="contractor", text="Notice", site_id=BR, purpose="notice", gate="external")
    assert sms["status"] == "dry_run" and "STEWARD_ALLOW_EXTERNAL_MESSAGES is not true" in sms["reason"]
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    sms = service.outbox.sms(sender="bristol-technician", to_role="contractor", text="Notice", site_id=BR, purpose="notice", gate="external")
    assert sms["status"] == "sent" and provider["sms"][-1] == dict(to=PHONE, body="Notice", person_role=None)
    person = service.outbox.sms(sender="dispatch", to_role="owner", text="Hello", site_id=BR, purpose="test")
    assert person["status"] == "sent" and provider["sms"][-1]["person_role"] == "owner"


def test_a_restart_puts_sending_items_back_in_the_queue(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    paced(monkeypatch)
    item = mail(service)
    record = service.store.get("outbox_item", item["id"], "")
    record["status"] = "sending"
    service.store.put("outbox_item", record, "")
    Outbox(service)
    assert service.outbox.get(item["id"])["status"] == "queued"


# ---- routes ------------------------------------------------------------------------------------------------------------------

def test_routes_list_status_and_mask_every_address(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    mail(service, 1)
    mail(service, 2, to_role="contractor", cc=["owner"])
    listed = client.get("/api/outbox", params=dict(channel="email", siteId=BR)).json()
    assert [i["subject"] for i in listed] == ["Subject 2", "Subject 1"] and listed[0]["to"] == "c•••@example.com"
    status = client.get("/api/outbox/status").json()
    assert status["lanes"]["email"]["gapSeconds"] == 120 and status["lanes"]["call"]["perDay"] == 8 and status["roles"]["contractor"]["email"] is True
    assert "calls" in status and status["calls"]["retries"] == 1
    for text in (client.get("/api/outbox").text, client.get("/api/outbox/status").text):
        assert OWNER_EMAIL not in text and CONTRACTOR_EMAIL not in text and PHONE not in text
    assert client.get("/api/outbox", params=dict(status="nope")).status_code == 400
    assert client.get("/api/outbox/obx-missing").status_code in (404, 405)


# ---- the old person-facing texts go through the outbox (§7) --------------------------------------------------------------------

def test_notices_and_decision_texts_go_through_the_outbox(client, provider, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-technician")
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    monkeypatch.setenv("STEWARD_ALLOW_NOTICE_SMS", "true")
    notice = service.people.send_notice(BR, "bristol-compliance", "PV-301 examination is due.", crew_member_id="crew-br-duty-engineer")
    assert notice["mode"] == "sent" and notice["outboxId"] and provider["sms"][-1]["to"] == PHONE
    item = service.outbox.get(notice["outboxId"])
    assert item["channel"] == "sms" and item["purpose"] == "notice" and item["gate"] == "external" and item["status"] == "sent"
    issue = service.issues.raise_issue(BR, "overpressure", "high", "PG-301 reads 3.9 bar.", asset_tag="PV-301", issue_id="iss-br-outbox")
    service.people.decide(issue, "Shut the pump down?", ["yes", "no"], "operator")
    owner_note = next(n for n in service.store.all("notification", BR) if n.get("toKind") == "owner")
    assert owner_note["mode"] == "sent" and owner_note["outboxId"] and provider["sms"][-1]["body"].startswith("Steward: Decision needed on PV-301")
    feed = client.get("/api/owner/notifications", params=dict(kind="decision_request,notice")).json()["items"]
    assert {i["kind"] for i in feed} == {"decision_request", "notice"} and all(i["mode"] == "sent" for i in feed)
