"""Contract 8 test doubles for the outbox, phone calls and the chat writer, with the contract's signatures
(REALITY-CONTRACT-8.md §2-§4). Agents B and C test against these; agents A and E test the real modules.

    fakes = install_fakes(service)        # replaces service.outbox / voice_calls / chats
    call = fakes.voice_calls.calls[-1]
    fakes.voice_calls.finish(call["id"], result="agreed", chosen_option_id="slot-1", follow_ups=[{"type": "email_file", "cc": ["compliance-counsel"]}])
"""
from __future__ import annotations

from itertools import count

_ids = count(1)


def _id(prefix: str) -> str:
    return f"{prefix}-fake{next(_ids):04d}"


class FakeOutbox:
    def __init__(self):
        self.items: list[dict] = []

    def _add(self, channel: str, **fields) -> dict:
        item = dict(id=_id("obx"), channel=channel, status="queued", reason=None, providerRef=None, **fields)
        self.items.append(item)
        return item

    def email(self, *, sender, to_role, subject, text, html=None, attachments=None, cc=None, site_id=None, purpose, refs=None,
              dedupe_key=None, priority=5, not_before=None):
        if dedupe_key:
            match = next((i for i in self.items if i.get("dedupeKey") == dedupe_key), None)
            if match:
                return match
        return self._add("email", sender=sender, toRole=to_role, subject=subject, text=text, html=html, attachments=attachments or [],
                         cc=list(cc or []), siteId=site_id, purpose=purpose, refs=refs or {}, dedupeKey=dedupe_key, priority=priority,
                         notBefore=not_before)

    def internal_email(self, *, sender, to_agent, subject, text, html=None, attachments=None, cc=None, site_id=None, purpose, refs=None):
        return self._add("internal_email", sender=sender, toAgent=to_agent, subject=subject, text=text, html=html, attachments=attachments or [],
                         cc=list(cc or []), siteId=site_id, purpose=purpose, refs=refs or {})

    def sms(self, *, sender, to_role, text, site_id=None, purpose, refs=None, dedupe_key=None, priority=5, not_before=None, gate="person",
            idempotency_key=None):
        return self._add("sms", sender=sender, toRole=to_role, text=text, siteId=site_id, purpose=purpose, refs=refs or {}, dedupeKey=dedupe_key,
                         priority=priority, notBefore=not_before, gate=gate)

    def call(self, *, phone_call_id, site_id, purpose, priority=5, not_before=None, dedupe_key=None):
        return self._add("call", phoneCallId=phone_call_id, siteId=site_id, purpose=purpose, priority=priority, notBefore=not_before,
                         dedupeKey=dedupe_key)

    def get(self, item_id):
        return next(i for i in self.items if i["id"] == item_id)

    def list(self, *, status=None, channel=None, site_id=None, limit=50):
        rows = [i for i in self.items if (not status or i["status"] == status) and (not channel or i["channel"] == channel)
                and (not site_id or i.get("siteId") == site_id)]
        return list(reversed(rows))[:limit]

    def status(self):
        return dict(state="fake", queued=len([i for i in self.items if i["status"] == "queued"]))

    def cancel(self, item_id, reason):
        item = self.get(item_id)
        item.update(status="canceled", reason=reason)
        return item

    def start(self):
        return None

    def close(self):
        return None

    def tick(self, moment=None):
        return []


class FakeVoiceCalls:
    def __init__(self):
        self.calls: list[dict] = []
        self.handlers: dict = {}

    def register(self, purpose, handler):
        self.handlers[purpose] = handler

    def request(self, *, purpose, caller, callee_role, callee_name, site_id, goal, facts, options=None, can_do=None, file=None,
                context=None, refs=None, priority=5, dedupe_key=None, not_before=None):
        if dedupe_key:
            match = next((c for c in self.calls if c.get("dedupeKey") == dedupe_key), None)
            if match:
                return match
        record = dict(id=_id("pcall"), purpose=purpose, caller=caller, calleeRole=callee_role, calleeName=callee_name, siteId=site_id,
                      goal=goal, facts=list(facts), options=list(options or []), canDo=list(can_do or []), file=file, context=context or {},
                      refs=refs or {}, priority=priority, dedupeKey=dedupe_key, notBefore=not_before, status="queued", transcript=[],
                      actionItems=[], outcome=None, attempt=1, retryOf=None)
        self.calls.append(record)
        return record

    def finish(self, call_id, result="agreed", chosen_option_id=None, follow_ups=None, decision="", summary="", transcript=None):
        """End a call the way VoiceCalls does after reading its outcome, then run the purpose's handler (returns its result)."""
        record = self.get(call_id)
        status = {"voicemail": "voicemail", "no_answer": "no_answer", "failed": "failed"}.get(result, "ended")
        record.update(status=status, transcript=list(transcript or []),
                      outcome=dict(result=result, decision=decision, summary=summary, chosenOptionId=chosen_option_id,
                                   followUps=[dict(cc=[], topic="", details="", status="queued", ref=None, **f) for f in (follow_ups or [])],
                                   interpretedBy="rules"))
        handler = self.handlers.get(record["purpose"])
        return handler(record) if handler else None

    def get(self, call_id):
        return next(c for c in self.calls if c["id"] == call_id)

    def list(self, *, site_id=None, active=None, purpose=None, limit=50):
        rows = [c for c in self.calls if (not site_id or c["siteId"] == site_id) and (not purpose or c["purpose"] == purpose)]
        if active is not None:
            rows = [c for c in rows if (c["status"] in ("queued", "dialing", "live")) == active]
        return list(reversed(rows))[:limit]

    def not_placed(self, call_id, status, reason):
        """The outbox could not place the call: settle it and run the handler with an undecided outcome."""
        record = self.get(call_id)
        record.update(status=status if status in ("dry_run", "capped", "failed", "canceled") else "failed",
                      outcome=dict(result="undecided", decision=f"Not placed: {reason}", summary="", chosenOptionId=None, followUps=[], interpretedBy="rules"))
        handler = self.handlers.get(record["purpose"])
        return handler(record) if handler else None

    def place(self, call_id):
        record = self.get(call_id)
        record.update(status="live", providerCallId="fake-provider-call")
        return dict(providerCallId="fake-provider-call", status="live")

    def start(self):
        return None

    def close(self):
        return None

    def tick(self, moment=None):
        return []


class FakeChatWriter:
    """Plays the `fallback` turns through the real ConversationService (so conversations, A2A tasks and memories exist), or
    records the run when no service is given."""

    def __init__(self, service=None):
        self.service = service
        self.runs: list[dict] = []

    def run(self, *, convener, participants, topic, site_ids, briefs, shared, goal, min_turns=6, max_turns=12, refs=None, issue_id=None,
            fallback=None, fallback_summary=None, realtime=True, origin=None):
        self.runs.append(dict(convener=convener, participants=list(participants), topic=topic, siteIds=list(site_ids), briefs=dict(briefs),
                              shared=shared, goal=goal, minTurns=min_turns, maxTurns=max_turns, refs=refs or {}, issueId=issue_id))
        others = [p for p in participants if p != convener] or [convener]
        turns = list(fallback or [dict(speaker=convener, text=f"{topic}."), dict(speaker=others[0], text="Understood.")])
        if self.service is None:
            return dict(id=_id("conv"), kind="call", topic=topic, participants=list(participants), siteIds=list(site_ids),
                        transcript=turns, summary=fallback_summary, summaryBy="hand-seed", status="ended")
        return self.service.conversations.call(convener, others[0], topic, turns, participants=list(participants), site_ids=list(site_ids),
                                               issue_id=issue_id, summary=fallback_summary or dict(headline=topic[:200], points=[], decisions=[], actions=[]),
                                               summary_by="hand-seed", origin=origin or "workflow")

    def status(self):
        return dict(state="fake", runs=len(self.runs))

    def close(self):
        return None


class Fakes:
    def __init__(self, outbox, voice_calls, chats):
        self.outbox, self.voice_calls, self.chats = outbox, voice_calls, chats


def install_fakes(service) -> Fakes:
    fakes = Fakes(FakeOutbox(), FakeVoiceCalls(), FakeChatWriter(service))
    service.outbox, service.voice_calls, service.chats = fakes.outbox, fakes.voice_calls, fakes.chats
    return fakes
