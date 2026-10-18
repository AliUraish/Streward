"""Agent calls and meetings (contract 4 §4). Every agent-to-agent exchange is a `conversation`:

`{id, kind: call | meeting | message, topic, participants, siteIds, convener, transport: inkbox | local,
providerTaskIds, a2aTaskIds, contextId, transcript: [{speaker, name, text, at, taskId?, transport?}], summary:
{headline, points, decisions, actions: [{owner, task, due}]} | null, summaryBy: claude-opus-5-5 | hand-seed | null,
startedAt, endedAt, synthetic, scenarioId?, runId?, issueId?, issueKind?, resolution?, contact?}`.

- A **meeting** is convened by a manager or the director: the convener asks each participant over A2A and the
  participant's reply is its statement; the convener states the resolution and the contact is decided from the
  crew ownership table.
- A **call** is an Inkbox A2A conversation presented as a call: each turn is a message on a task between the two
  speakers (send, follow-up `message`, or `progress` reply), closed with `complete` at the end. Voice comes from
  the browser's text-to-speech and the UI says so; there are no phone calls between agents on the current plan.
- Every other A2A exchange (missions, document deliveries, notifications) is shown as a derived **message**
  conversation grouped by A2A context, so nothing agent-to-agent is invisible.

The bus picks the transport per message (Inkbox A2A when both identities and keys exist, local otherwise) and
enforces the cross-site rule. Scripted conversations carry hand-seeded summaries; `scripts/synth/summarise.py`
(Claude, dry-run default) writes Claude summaries through `POST /api/conversations/{id}/summary`.
"""
from __future__ import annotations

from .agents import DIRECTOR, OPERATOR, display_name, is_known, kind_of, site_of
from .errors import RealityError
from .store import now, uid

VOICE_NOTE = "Voice is the browser's text-to-speech reading the transcript; agents talk over Inkbox A2A, not phone calls."
SUMMARY_KEYS = ("headline", "points", "decisions", "actions")


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fill(text, context: dict):
    if isinstance(text, str):
        return text.format_map(SafeDict({k: v for k, v in context.items() if v is not None}))
    if isinstance(text, list):
        return [fill(item, context) for item in text]
    if isinstance(text, dict):
        return {key: fill(value, context) for key, value in text.items()}
    return text


def validate_summary(summary: dict) -> dict:
    if not isinstance(summary, dict) or not isinstance(summary.get("headline"), str) or not summary["headline"].strip():
        raise RealityError("summary needs a headline.", "INVALID_REQUEST", "Send {headline, points, decisions, actions}.")
    points = [str(p)[:300] for p in (summary.get("points") or [])][:8]
    decisions = [str(d)[:300] for d in (summary.get("decisions") or [])][:8]
    actions = []
    for action in (summary.get("actions") or [])[:8]:
        if isinstance(action, dict) and action.get("task"):
            actions.append(dict(owner=str(action.get("owner") or "")[:60], task=str(action["task"])[:300], due=str(action.get("due") or "")[:40]))
    return dict(headline=summary["headline"].strip()[:200], points=points, decisions=decisions, actions=actions)


class ConversationService:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    # ---- records ------------------------------------------------------------------------------------------

    def _save(self, conversation: dict) -> dict:
        tasks = [self.service.bus.task(task_id) for task_id in conversation.get("a2aTaskIds", []) if self.store.get("a2a_task", task_id)]
        conversation["providerTaskIds"] = [t["providerTaskId"] for t in tasks if t.get("providerTaskId")]
        conversation["transport"] = "inkbox" if any(t["transport"] == "inkbox" for t in tasks) else "local"
        self.store.put("conversation", conversation, "")
        self.service.reality.mirror.put("conversation", conversation, conversation["siteIds"][0] if conversation["siteIds"] else "")
        return conversation

    def _change(self, conversation: dict, summary: str, status: str) -> None:
        for site in conversation["siteIds"]:
            self.service.reality.emit_change(site, "conversation", conversation["id"], summary[:480],
                                             extra=dict(conversationId=conversation["id"], kind=conversation["kind"], status=status,
                                                        issueId=conversation.get("issueId"), scenarioId=conversation.get("scenarioId"),
                                                        runId=conversation.get("runId"), meetingId=conversation["id"] if conversation["kind"] == "meeting" else None))

    def _new(self, kind: str, convener: str, participants: list[str], site_ids: list[str], topic: str, **extra) -> dict:
        for agent in participants:
            if not is_known(agent) or agent == "owner":
                raise RealityError(f"{agent} cannot take part in a conversation.", "INVALID_REQUEST", "Participants are Steward agents.")
        sites = list(dict.fromkeys([s for s in site_ids if s] + [site_of(a) for a in participants if site_of(a)]))
        conversation = dict(id=uid("conv"), kind=kind, topic=topic[:200], convener=convener, participants=list(dict.fromkeys(participants)),
                            siteIds=sites, transport="local", providerTaskIds=[], a2aTaskIds=[], contextId=uid("ctx"), transcript=[],
                            summary=None, summaryBy=None, startedAt=now(), endedAt=None, status="live", voiceNote=VOICE_NOTE,
                            synthetic=bool(extra.pop("synthetic", True)), **{k: v for k, v in extra.items() if v is not None})
        self._save(conversation)
        self._change(conversation, f"{display_name(convener)} started a {kind}: {topic[:160]}", "started")
        return conversation

    def _line(self, conversation: dict, speaker: str, text: str, task: dict | None = None, kind: str | None = None) -> None:
        entry = dict(seq=len(conversation["transcript"]) + 1, speaker=speaker, agentId=speaker, name=display_name(speaker), text=text[:1500], at=now())
        if task:
            entry.update(taskId=task["id"], transport=task["transport"])
            if task["id"] not in conversation["a2aTaskIds"]:
                conversation["a2aTaskIds"].append(task["id"])
        if kind:
            entry["kind"] = kind
        conversation["transcript"].append(entry)
        self._save(conversation)

    def _site_for(self, conversation: dict, a: str, b: str) -> str:
        return site_of(a) or site_of(b) or (conversation["siteIds"][0] if conversation["siteIds"] else "")

    def _finish(self, conversation: dict, summary: dict | None, summary_by: str | None, headline: str) -> dict:
        conversation.update(endedAt=now(), status="ended")
        if summary:
            conversation.update(summary=validate_summary(summary), summaryBy=summary_by or "hand-seed")
        self._save(conversation)
        self._change(conversation, headline, "ended")
        for agent in conversation["participants"]:
            if agent != OPERATOR:
                self.service.memory.write(agent, f"{conversation['kind'].title()} on {conversation['topic'][:120]}: "
                                                 f"{(conversation.get('resolution') or (conversation.get('summary') or {}).get('headline') or headline)[:300]}",
                                          "conversation", dict(conversationId=conversation["id"], issueId=conversation.get("issueId")),
                                          conversation["siteIds"][0] if conversation["siteIds"] else None, synthetic=conversation["synthetic"])
        return conversation

    # ---- meetings and calls -----------------------------------------------------------------------------------

    def meeting(self, convener: str, topic: str, participants: list[str], turns: list[dict], resolution: str | None = None,
                site_ids: list[str] | None = None, issue_kind: str | None = None, issue_id: str | None = None, scenario_id: str | None = None,
                run_id: str | None = None, context: dict | None = None, summary: dict | None = None, summary_by: str = "hand-seed",
                contact_site: str | None = None, synthetic: bool = True) -> dict:
        participants = list(dict.fromkeys([convener] + [p for p in participants if p != convener]))
        site_ids = site_ids or [s for s in (site_of(p) for p in participants) if s]
        context = dict(context or {})
        contact = None
        if issue_kind:
            responsible = self.service.people.who_is_responsible(contact_site or site_ids[0], issue_kind)
            owner, plan = responsible.get("owner"), responsible.get("contactPlan") or {}
            context.update(contactName=(owner or {}).get("name") or "nobody", contactRole=(owner or {}).get("role") or "no owner",
                           contactChannel=plan.get("channel") or "no channel")
            if owner:
                contact = dict(crewMemberId=owner["id"], name=owner["name"], role=owner["role"], contactable=owner["contactable"],
                               channel=plan.get("channel"), via=plan.get("via"), reason=plan.get("reason"), fallback=responsible.get("fallback", False))
        conversation = self._new("meeting", convener, participants, site_ids, topic, issueKind=issue_kind, issueId=issue_id, scenarioId=scenario_id,
                                 runId=run_id, synthetic=synthetic)
        bus = self.service.bus
        for turn in turns:
            speaker = turn["speaker"]
            text = fill(turn["text"], context)
            if speaker == convener:
                self.service.telemetry.record(speaker, "meeting", "meeting_statement", text=text, site_id=conversation["siteIds"][0] if conversation["siteIds"] else None,
                                              scenario_id=scenario_id, run_id=run_id)
                self._line(conversation, speaker, text)
                continue
            site = self._site_for(conversation, convener, speaker)
            ask = bus.send(convener, speaker, f"{topic[:120]}: your view, {display_name(speaker)}.",
                           dict(kind="board_meeting", conversationId=conversation["id"], meetingId=conversation["id"], issueId=issue_id, scenarioId=scenario_id),
                           site, context_id=conversation["contextId"], deliver=False)
            task = bus.reply(speaker, ask["id"], "complete", text, dict(kind="meeting_statement", conversationId=conversation["id"]), deliver=False)
            self._line(conversation, speaker, text, task)
        resolution_text = fill(resolution, context) if resolution else None
        if resolution_text:
            self._line(conversation, convener, f"Resolution: {resolution_text}", kind="resolution")
            self.service.telemetry.record(convener, "meeting", "meeting_resolution", text=resolution_text,
                                          site_id=conversation["siteIds"][0] if conversation["siteIds"] else None, scenario_id=scenario_id, run_id=run_id)
        conversation.update(resolution=resolution_text, contact=contact)
        headline = f"Meeting resolved: {(resolution_text or topic)[:200]}" + (f" Contact: {contact['name']} ({contact['role']})." if contact else "")
        return self._finish(conversation, fill(summary, context) if summary else None, summary_by, headline)

    def call(self, caller: str, callee: str, topic: str, turns: list[dict], participants: list[str] | None = None, site_ids: list[str] | None = None,
             issue_id: str | None = None, issue_kind: str | None = None, scenario_id: str | None = None, run_id: str | None = None,
             context: dict | None = None, summary: dict | None = None, summary_by: str = "hand-seed", synthetic: bool = True,
             workflow_id: str | None = None) -> dict:
        """A multi-turn A2A conversation between `caller` and `callee` (others may join with `to` set)."""
        everyone = list(dict.fromkeys([caller, callee] + list(participants or []) + [t["speaker"] for t in turns]))
        context = dict(context or {})
        conversation = self._new("call", caller, everyone, site_ids or [], topic, issueId=issue_id, issueKind=issue_kind, scenarioId=scenario_id,
                                 runId=run_id, workflowId=workflow_id, synthetic=synthetic)
        bus = self.service.bus
        open_tasks: dict[frozenset, str] = {}
        for turn in turns:
            speaker = turn["speaker"]
            listener = turn.get("to") or (callee if speaker != callee else caller)
            text = fill(turn["text"], context)
            pair = frozenset((speaker, listener))
            task_id = open_tasks.get(pair)
            if task_id is None:
                task = bus.send(speaker, listener, text, dict(kind="call", conversationId=conversation["id"], issueId=issue_id, scenarioId=scenario_id),
                                self._site_for(conversation, speaker, listener), context_id=conversation["contextId"], deliver=False)
                open_tasks[pair] = task["id"]
            else:
                current = bus.task(task_id)
                if current["caller"] == speaker:
                    task = bus.message(speaker, task_id, text, dict(kind="call", conversationId=conversation["id"]), deliver=False)
                else:
                    task = bus.reply(speaker, task_id, "progress", text, dict(kind="call", conversationId=conversation["id"]), deliver=False)
            self._line(conversation, speaker, text, task)
        for pair, task_id in open_tasks.items():
            task = bus.task(task_id)
            if task["state"] not in ("completed", "failed", "canceled"):
                bus.reply(task["target"], task_id, "complete", "(end of call)", dict(kind="call_end", conversationId=conversation["id"]), deliver=False)
        headline = f"Call ended: {topic[:200]}"
        return self._finish(conversation, fill(summary, context) if summary else None, summary_by, headline)

    # ---- reading --------------------------------------------------------------------------------------------

    def _derived(self) -> list[dict]:
        covered = {task_id for c in self.store.all("conversation", "") for task_id in c.get("a2aTaskIds", [])}
        summaries = {s["id"]: s for s in self.store.all("conversation_summary", "")}
        groups: dict[str, list[dict]] = {}
        for task in self.store.all("a2a_task"):
            if task["id"] in covered:
                continue
            groups.setdefault(task["contextId"], []).append(task)
        derived = []
        for context_id, tasks in groups.items():
            tasks.sort(key=lambda t: t["createdAt"])
            transcript = []
            for task in tasks:
                for message in task["messages"]:
                    speaker = task["caller"] if message["role"] == "caller" else task["target"]
                    text = " ".join(str(p.get("text")) for p in message["parts"] if isinstance(p, dict) and p.get("text")).strip()
                    transcript.append(dict(speaker=speaker, agentId=speaker, name=display_name(speaker), text=text[:1500], at=message["at"], taskId=task["id"],
                                           transport=task["transport"]))
            transcript.sort(key=lambda line: line["at"])
            participants = list(dict.fromkeys(a for t in tasks for a in (t["caller"], t["target"])))
            identifier = f"conv-ctx-{context_id}"
            summary = summaries.get(identifier)
            closed = all(t["state"] in ("completed", "failed", "canceled") for t in tasks)
            derived.append(dict(id=identifier, kind="message", topic=(transcript[0]["text"][:120] if transcript else "A2A exchange"), convener=tasks[0]["caller"],
                                participants=participants, siteIds=list(dict.fromkeys(t.get("siteId") for t in tasks if t.get("siteId"))),
                                transport="inkbox" if any(t["transport"] == "inkbox" for t in tasks) else "local",
                                providerTaskIds=[t["providerTaskId"] for t in tasks if t.get("providerTaskId")], a2aTaskIds=[t["id"] for t in tasks],
                                contextId=context_id, transcript=transcript, summary=(summary or {}).get("summary"), summaryBy=(summary or {}).get("summaryBy"),
                                startedAt=tasks[0]["createdAt"], endedAt=max(t["updatedAt"] for t in tasks) if closed else None,
                                status="ended" if closed else "live", synthetic=any(t.get("simulated") for t in tasks), derived=True,
                                missionId=next(((t.get("steward") or {}).get("missionId") for t in tasks if (t.get("steward") or {}).get("missionId")), None),
                                voiceNote=VOICE_NOTE))
        return derived

    def list(self, site_id: str | None = None, agent_id: str | None = None, kind: str | None = None, limit: int = 100) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        records = self.store.all("conversation", "") + self._derived()
        if site_id:
            records = [c for c in records if site_id in c["siteIds"]]
        if agent_id:
            records = [c for c in records if agent_id in c["participants"]]
        if kind:
            records = [c for c in records if c["kind"] == kind]
        records.sort(key=lambda c: c["startedAt"], reverse=True)
        return records[:limit]

    def get(self, conversation_id: str) -> dict:
        record = self.store.get("conversation", conversation_id, "")
        if record:
            return record
        if conversation_id.startswith("conv-ctx-"):
            match = next((c for c in self._derived() if c["id"] == conversation_id), None)
            if match:
                return match
        raise RealityError("Conversation not found.", "NOT_FOUND", "List conversations with GET /api/conversations.", 404)

    def set_summary(self, conversation_id: str, summary: dict, summary_by: str) -> dict:
        if summary_by not in ("claude-opus-5-5", "hand-seed"):
            raise RealityError("summaryBy must be claude-opus-5-5 or hand-seed.", "INVALID_REQUEST", "Label who wrote the summary.")
        clean = validate_summary(summary)
        record = self.store.get("conversation", conversation_id, "")
        if record:
            record.update(summary=clean, summaryBy=summary_by, summarizedAt=now())
            return self._save(record)
        conversation = self.get(conversation_id)
        self.store.put("conversation_summary", dict(id=conversation_id, summary=clean, summaryBy=summary_by, at=now()), "")
        return {**conversation, "summary": clean, "summaryBy": summary_by}

    # ---- contract-3 board meeting views ----------------------------------------------------------------------

    @staticmethod
    def as_board_meeting(conversation: dict) -> dict:
        return dict(conversation, convenedBy=conversation["convener"], siteId=conversation["siteIds"][0] if conversation["siteIds"] else None,
                    resolvedAt=conversation.get("endedAt"), status="resolved" if conversation["status"] == "ended" else "convened")

    def board_meetings(self, site_id: str | None = None) -> list[dict]:
        return [self.as_board_meeting(c) for c in self.list(site_id, kind="meeting", limit=200)]

    def board_meeting(self, meeting_id: str | None = None, issue_id: str | None = None) -> dict:
        if meeting_id:
            record = self.store.get("conversation", meeting_id, "")
            if record and record["kind"] == "meeting":
                return self.as_board_meeting(record)
        if issue_id:
            matches = [c for c in self.store.all("conversation", "") if c["kind"] == "meeting" and c.get("issueId") == issue_id]
            if matches:
                return self.as_board_meeting(sorted(matches, key=lambda c: c["startedAt"])[-1])
        raise RealityError("Board meeting not found.", "NOT_FOUND", "List meetings with GET /api/board-meetings?siteId=.", 404)
