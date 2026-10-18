"""The Supabase inbox: the Edge Function's signature check agrees with the Inkbox SDK, and the drainer replays queued
webhooks through POST /api/inbound/inkbox (signature verified again) before archiving them."""
import base64
import hashlib
import hmac
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from inkbox.signing_keys import verify_webhook

from src.main import create_app
from src.store import Store
from src.supa_budget import Budget
from src.supa_client import Supa
from src.supa_inbox import POISON_READS, InboxDrainer

ROOT = Path(__file__).resolve().parents[2]
FUNCTION = ROOT / "supabase" / "functions" / "inkbox-inbox"
NODE = shutil.which("node")


def sign(key: str, request_id: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(key.removeprefix("whsec_").encode(), f"{request_id}.{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def run_case(case: dict) -> dict:
    result = subprocess.run([NODE, str(FUNCTION / "verify_test.ts"), json.dumps(case)], capture_output=True, text=True, timeout=60, cwd=str(FUNCTION))
    assert result.returncode in (0, 1), result.stderr
    return dict(json.loads(result.stdout.strip().splitlines()[-1]), exit=result.returncode)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_edge_function_signature_check_matches_the_inkbox_sdk():
    body = json.dumps({"id": "evt-123", "event_type": "text.received", "data": {"text_message": {"text": "P-101 reads 3.2 bar"}}})
    headers = {"x-inkbox-request-id": "req-1", "x-inkbox-timestamp": "1760000000"}
    headers["x-inkbox-signature"] = sign("whsec_second-key", "req-1", "1760000000", body.encode())
    assert verify_webhook(payload=body.encode(), headers=headers, secret="whsec_second-key")  # the SDK agrees with our signer
    secrets = {"INKBOX_WEBHOOK_SIGNING_KEY": "first-key", "INKBOX_WEBHOOK_SIGNING_KEY_MYER_TECHNICIAN": "whsec_second-key", "OTHER": "ignored"}
    good = run_case(dict(body=body, secrets=secrets, headers=headers, expect=True, envelope="evt-123"))
    assert good["exit"] == 0 and good["verified"] and good["envelope"] == {"envelopeId": "evt-123", "eventType": "text.received"}
    tampered = run_case(dict(body=body.replace("3.2", "9.9"), secrets=secrets, headers=headers, expect=False, envelope=""))
    assert tampered["exit"] == 0 and tampered["verified"] is False
    unsigned = run_case(dict(body=body, secrets=secrets, headers={"x-inkbox-request-id": "req-1"}, expect=False, envelope=""))
    assert unsigned["exit"] == 0 and unsigned["verified"] is False
    wrong_key = run_case(dict(body=body, secrets={"INKBOX_WEBHOOK_SIGNING_KEY": "someone-else"}, headers=headers, expect=False, envelope=""))
    assert wrong_key["exit"] == 0
    stale = run_case(dict(body=body, secrets=secrets, headers=headers, expect=False, envelope="evt-123", tolerance=300, nowMs=1760000000 * 1000 + 3_600_000))
    assert stale["fresh"] is False


class FakeQueue:
    def __init__(self, messages):
        self.messages = {m["msg_id"]: m for m in messages}
        self.archived = []

    def __call__(self, request: httpx.Request):
        name = request.url.path.rsplit("/", 1)[-1]
        args = json.loads(request.content or b"{}")
        if name == "inkbox_inbox_read":
            rows = []
            for message in self.messages.values():
                message["read_ct"] += 1
                rows.append(dict(message))
            return httpx.Response(200, json=rows)
        if name == "inkbox_inbox_archive":
            self.archived.append(args["p_msg_id"])
            self.messages.pop(args["p_msg_id"], None)
            return httpx.Response(200, json=True)
        if name == "inkbox_inbox_stats":
            return httpx.Response(200, json=dict(queued=len(self.messages), archived=len(self.archived), callsToday=3, day="2026-10-18"))
        return httpx.Response(404)


def queued(msg_id: int, body: bytes, signature: str, request_id="req-9", timestamp="1760000000") -> dict:
    return dict(msg_id=msg_id, read_ct=0, enqueued_at="2026-10-18T00:00:00Z",
                message=dict(rawB64=base64.b64encode(body).decode(), headers={"x-inkbox-signature": signature, "x-inkbox-request-id": request_id,
                                                                               "x-inkbox-timestamp": timestamp, "content-type": "application/json"}))


def test_drainer_replays_through_the_inkbox_route_and_archives(tmp_path, monkeypatch):
    monkeypatch.setenv("INKBOX_WEBHOOK_SIGNING_KEY_MYER_ENGINEER", "whsec_drain-key")
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    body = json.dumps({"id": "evt-drain-1", "event_type": "steward.selftest", "data": {}}).encode()
    good = queued(1, body, sign("whsec_drain-key", "req-9", "1760000000", body))
    forged = queued(2, body, sign("whsec_not-ours", "req-9", "1760000000", body))
    fake = FakeQueue([good, forged])
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        budget = Budget(Store(tmp_path / "budget"))
        drainer = InboxDrainer(Supa("https://example.supabase.co", "sb_secret_test", "", httpx.MockTransport(fake)), client.app, budget)
        assert drainer.drain() == 1
        assert fake.archived == [1] and 2 in fake.messages  # the forged one got 401 and stays for retry
        events = client.get("/api/properties/myer-plant/events").json()
        assert any(e["type"] == "inkbox.event" and "steward.selftest" in e["title"] for e in events)
        for _ in range(POISON_READS):
            drainer.drain()
        assert fake.archived == [1, 2] and drainer.poisoned == 1  # archived as poison after five 401s, and announced
        assert drainer.refresh_stats(force=True)["callsToday"] == 3 and budget.counter("edge_calls", "day") in (0, 3)


def test_duplicate_deliveries_are_absorbed_by_the_route(tmp_path, monkeypatch):
    monkeypatch.setenv("INKBOX_WEBHOOK_SIGNING_KEY", "dup-key")
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    body = json.dumps({"id": "evt-dup", "event_type": "a2a.task.message", "data": {}}).encode()
    messages = [queued(10, body, sign("dup-key", "req-a", "1", body), "req-a", "1"), queued(11, body, sign("dup-key", "req-b", "2", body), "req-b", "2")]
    fake = FakeQueue(messages)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        drainer = InboxDrainer(Supa("https://example.supabase.co", "sb_secret_test", "", httpx.MockTransport(fake)), client.app,
                               Budget(Store(tmp_path / "budget")))
        drainer.drain()
        assert sorted(fake.archived) == [10, 11]  # the second delivery of the same envelope is a duplicate, still archived


def test_inbox_switch_plan_adds_the_function_before_removing_the_tunnel():
    import importlib.util
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("inkbox_use_supabase_inbox", ROOT / "scripts" / "inkbox_use_supabase_inbox.py")
    switch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(switch)
    supabase, tunnel = "https://ref.supabase.co", "https://abc.inkboxwire.com"
    subs = [dict(id="s1", url=f"{tunnel}/api/inbound/inkbox?agent=steward-myer-engineer"), dict(id="s2", url="https://elsewhere.example/hook")]
    todo = switch.plan(subs, "steward-myer-engineer", supabase, tunnel)
    assert todo == dict(create=f"{supabase}/functions/v1/inkbox-inbox?agent=steward-myer-engineer", delete=["s1"])  # never the unrelated hook
    assert switch.plan(subs, "steward-myer-engineer", supabase, tunnel, keep_tunnel=True)["delete"] == []
    done = subs + [dict(id="s3", url=todo["create"])]
    assert switch.plan(done, "steward-myer-engineer", supabase, tunnel) == dict(create=None, delete=["s1"])  # idempotent
    back = switch.plan([dict(id="s3", url=todo["create"])], "steward-myer-engineer", supabase, tunnel, revert=True)
    assert back == dict(create=f"{tunnel}/api/inbound/inkbox?agent=steward-myer-engineer", delete=["s3"])
