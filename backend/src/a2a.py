"""Agent-to-agent bus (Inkbox A2A 1.0) with two transports behind one interface.

Every task is persisted as kind `a2a_task` `{id, contextId, caller, target, state, messages: [{role, parts, at}],
transport, providerTaskId?, createdAt, updatedAt}` and every message emits a Change of type `a2a`. Parts carry a
text part a human can read plus a `data` part `{steward: {...}}`.

`local`: in-process delivery, same envelope, persisted identically. `inkbox`: the caller identity's agent-scoped
key sends the real A2A 1.0 JSON-RPC `SendMessage` through `identity.a2a_client().send(target_card, parts=...)`
(the SDK's client sets `A2A-Version: 1.0` and `X-API-Key`), the worker replies through
`identity.a2a_reply(task_id, intent=..., parts=...)`, and the webhook events `a2a.task.created`,
`a2a.task.message`, `a2a.task.canceled`, `a2a.sent_task.updated` arrive on `/api/inbound/inkbox`. Because both
ends of every task live in this process, a task sent over Inkbox is also delivered in-process immediately; the
webhook echo is deduplicated by provider task/message id. A provider failure never pretends success: the task
is persisted with `transport: "local"` and a bounded `providerError`, and an event is written.
"""
from __future__ import annotations

import os
import threading
from uuid import uuid4

from .agents import (DIRECTOR, SKILLS, agent_key, all_agent_ids, engineer_id, handle_for, is_known, kind_of, manager_id, migrate_agent_id,
                     require_message_allowed, site_of, technician_id)
from .env import env
from .errors import RealityError
from .providers import clean_env
from .sites import DEMO_SITE
from .store import now, uid

OPEN_TASK_STATES = ("submitted", "working", "input_required")
INTENT_STATE = {"progress": "working", "ask_caller": "input_required", "complete": "completed", "fail": "failed"}
WIRE_STATE = {"TASK_STATE_SUBMITTED": "submitted", "TASK_STATE_WORKING": "working", "TASK_STATE_COMPLETED": "completed",
              "TASK_STATE_FAILED": "failed", "TASK_STATE_CANCELED": "canceled", "TASK_STATE_INPUT_REQUIRED": "input_required",
              "TASK_STATE_REJECTED": "failed", "TASK_STATE_AUTH_REQUIRED": "input_required"}


def steward_data(parts: list[dict]) -> dict:
    for part in parts or []:
        data = part.get("data") if isinstance(part, dict) else None
        if isinstance(data, dict) and isinstance(data.get("steward"), dict):
            return data["steward"]
    return {}


def text_of(parts: list[dict]) -> str:
    return " ".join(str(part.get("text")) for part in parts or [] if isinstance(part, dict) and part.get("text")).strip()


class A2ABus:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.reality = service.reality
        self.handlers: dict[str, object] = {}
        self.lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()

    # ---- configuration --------------------------------------------------------------------------------

    @staticmethod
    def mode() -> str:
        """STEWARD_A2A_TRANSPORT: `local` never calls Inkbox A2A (sends, replies, follow-ups, startup recovery) even when
        keys exist; `inkbox` and `auto` (default) use Inkbox whenever both identities and the sender's key exist."""
        value = clean_env("STEWARD_A2A_TRANSPORT", "auto").strip().lower()
        return value if value in ("auto", "local", "inkbox") else "auto"

    @classmethod
    def inkbox_available(cls) -> bool:
        return cls.mode() != "local" and bool(clean_env("INKBOX_API_KEY"))

    def transport_for(self, agent_id: str, other: str | None = None) -> str:
        """`inkbox` when the transport mode allows it, INKBOX_API_KEY and both handles exist, else `local`. The Owner's agent
        has no identity."""
        if not self.inkbox_available():
            return "local"
        ends = [agent_id] + ([other] if other else [])
        if any(end == "operator" or not handle_for(end) for end in ends):
            return "local"
        return "inkbox"

    def register(self, agent_kind: str, handler) -> None:
        self.handlers[agent_kind] = handler

    def handler_for(self, agent_id: str):
        return self.handlers.get(kind_of(agent_id))

    # ---- records --------------------------------------------------------------------------------------

    def task(self, task_id: str) -> dict:
        record = self.store.get("a2a_task", task_id)
        if not record:
            raise RealityError("A2A task not found.", "NOT_FOUND", "List tasks with GET /api/a2a/tasks.", 404)
        return record

    def tasks(self, site: str | None = None, mission_id: str | None = None, agent: str | None = None) -> list[dict]:
        records = self.store.all("a2a_task", site) if site else self.store.all("a2a_task")
        if mission_id:
            records = [r for r in records if r.get("steward", {}).get("missionId") == mission_id]
        if agent:
            records = [r for r in records if agent in (r["caller"], r["target"])]
        return sorted(records, key=lambda r: r["createdAt"])

    def by_provider_task(self, provider_task_id: str) -> dict | None:
        if not provider_task_id:
            return None
        for record in self.store.all("a2a_task"):
            if record.get("providerTaskId") == provider_task_id:
                return record
        return None

    def save(self, record: dict) -> dict:
        record["updatedAt"] = now()
        self.store.put("a2a_task", record, record.get("siteId") or "")
        return record

    def touch(self, agent_id: str, current_task: str | None) -> None:
        if agent_id == "owner":
            return
        previous = self.store.get("agent_activity", agent_id, "") or {}
        record = dict(id=agent_id, lastActivityAt=now(), currentTask=(current_task or "")[:200] or None)
        if current_task and previous.get("why"):
            record["why"] = previous["why"]
        self.store.put("agent_activity", record, "")

    def _telemetry(self, agent: str, tool: str, text: str, record: dict) -> None:
        telemetry = getattr(self.service, "telemetry", None)
        if telemetry is None or agent == "operator" or str(agent).startswith("external:"):
            return
        steward = record.get("steward") or {}
        telemetry.record(agent, "a2a", tool, text=text, site_id=record.get("siteId"), mission_id=steward.get("missionId"),
                         scenario_id=steward.get("scenarioId"), run_id=steward.get("runId"), synthetic=bool(record.get("simulated")),
                         detail=f"{tool} {record['caller']}->{record['target']} ({record['transport']}): {text[:140]}")

    def status_for(self, agent_id: str) -> tuple[str, str | None]:
        """idle | working | waiting from the open tasks this agent is part of."""
        open_tasks = [t for t in self.store.all("a2a_task") if t["state"] in OPEN_TASK_STATES]
        mine = [t for t in open_tasks if t["target"] == agent_id and t["state"] in ("submitted", "working")]
        if mine:
            return "working", text_of(mine[-1]["messages"][0]["parts"])[:200]
        asked = [t for t in open_tasks if t["target"] == agent_id and t["state"] == "input_required"]
        waiting_on = [t for t in open_tasks if t["caller"] == agent_id]
        if asked or waiting_on:
            chosen = (asked or waiting_on)[-1]
            return "waiting", text_of(chosen["messages"][0]["parts"])[:200]
        return "idle", None

    def _emit(self, record: dict, role: str, parts: list[dict], intent: str | None = None):
        site = record.get("siteId") or DEMO_SITE
        speaker = record["caller"] if role == "caller" else record["target"]
        listener = record["target"] if role == "caller" else record["caller"]
        summary = f"A2A {speaker} → {listener}" + (f" [{intent}]" if intent else "") + f" ({record['transport']}): {text_of(parts)[:240]}"
        self.reality.emit_change(site, "a2a", record["id"], summary, steward_data(parts).get("assetTag") or record.get("steward", {}).get("assetTag"),
                                 simulated=bool(record.get("simulated")))

    # ---- outbound -------------------------------------------------------------------------------------

    def send(self, caller: str, target: str, text: str, data: dict | None, site: str, context_id: str | None = None,
             simulated: bool = False, deliver: bool = True) -> dict:
        """Open a task from `caller` to `target`. Returns the persisted record after in-process delivery.
        Cross-site messages obey the contract-4 rule (manager↔manager, compliance↔compliance, anyone↔director)."""
        if is_known(caller) and is_known(target):
            require_message_allowed(caller, target)
        task_id = uid("a2a")
        steward = dict(data or {})
        steward.setdefault("siteId", site)
        steward.update({"from": caller, "to": target, "messageId": task_id})
        parts = [{"text": text}, {"data": {"steward": steward}}]
        record = dict(id=task_id, contextId=context_id or uid("ctx"), caller=caller, target=target, state="submitted",
                      messages=[dict(role="caller", parts=parts, at=now())], transport=self.transport_for(caller, target),
                      providerTaskId=None, providerContextId=None, siteId=site, steward=steward, createdAt=now(), updatedAt=now())
        if simulated:
            record["simulated"] = True
        if record["transport"] == "inkbox" and self.inkbox_available():
            try:
                provider = self._inkbox_send(caller, target, parts, message_id=task_id, context_id=self._provider_context(context_id, site, caller, target))
                record.update(providerTaskId=provider["taskId"], providerContextId=provider.get("contextId"))
            except Exception as error:
                record["transport"] = "local"
                record["providerError"] = f"Inkbox A2A send failed ({type(error).__name__}): {str(error)[:200]}"
                self.store.event(site, caller, "a2a.inkbox_failed", f"A2A send to {target} fell back to local", record["providerError"])
        with self.lock:
            self.save(record)
        self._emit(record, "caller", parts)
        self._telemetry(caller, "a2a_send", text, record)
        self.touch(caller, f"waiting on {target}: {text}")
        self.touch(target, text)
        if deliver:
            handler = self.handler_for(target)
            if handler is not None and hasattr(handler, "on_task"):
                handler.on_task(self.task(task_id))
        return self.task(task_id)

    def reply(self, agent: str, task_id: str, intent: str, text: str, data: dict | None = None, deliver: bool = True) -> dict:
        """Worker reply on a task; `intent` is progress | ask_caller | complete | fail (Inkbox A2AReplyIntent)."""
        if intent not in INTENT_STATE:
            raise RealityError("intent must be progress, ask_caller, complete or fail.", "INVALID_REQUEST", "Use an Inkbox A2A reply intent.")
        with self.lock:
            record = self.task(task_id)
            if record["target"] != agent:
                raise RealityError(f"{agent} is not the worker on task {task_id}.", "AUTHORITY_DENIED", f"Only {record['target']} may reply.", 403)
            if record["state"] in ("completed", "failed", "canceled"):
                raise RealityError(f"Task {task_id} is {record['state']}.", "TASK_CLOSED", "Open a new task instead of replying.", 409)
            steward = dict(record.get("steward", {}), **(data or {}))
            message_id = uid("msg")
            steward.update({"from": agent, "to": record["caller"], "messageId": message_id})
            parts = [{"text": text}, {"data": {"steward": steward}}]
            record["messages"].append(dict(role="agent", parts=parts, at=now(), id=message_id, intent=intent))
            record["state"] = INTENT_STATE[intent]
            if record["transport"] == "inkbox" and record.get("providerTaskId") and not self.inkbox_available():
                record["providerError"] = "Reply kept local: STEWARD_A2A_TRANSPORT=local (or no INKBOX_API_KEY)."
            elif record["transport"] == "inkbox" and record.get("providerTaskId"):
                try:
                    self._inkbox_reply(agent, record["providerTaskId"], intent, parts)
                except Exception as error:
                    record["providerError"] = f"Inkbox A2A reply failed ({type(error).__name__}): {str(error)[:200]}"
                    self.store.event(record.get("siteId") or DEMO_SITE, agent, "a2a.inkbox_failed", "A2A reply not delivered to Inkbox", record["providerError"])
            self.save(record)
        self._emit(record, "agent", parts, intent)
        self._telemetry(agent, "a2a_reply", text, record)
        self.touch(agent, None if intent in ("complete", "fail") else text)
        self.touch(record["caller"], text if intent != "complete" else None)
        if deliver:
            handler = self.handler_for(record["caller"])
            if handler is not None and hasattr(handler, "on_reply"):
                handler.on_reply(self.task(task_id), record["messages"][-1], intent)
        return self.task(task_id)

    def message(self, caller: str, task_id: str, text: str, data: dict | None = None, deliver: bool = True) -> dict:
        """Caller follow-up on an open task (answers an `input_required`)."""
        with self.lock:
            record = self.task(task_id)
            if record["caller"] != caller:
                raise RealityError(f"{caller} is not the caller on task {task_id}.", "AUTHORITY_DENIED", f"Only {record['caller']} may add messages.", 403)
            steward = dict(record.get("steward", {}), **(data or {}))
            message_id = uid("msg")
            steward.update({"from": caller, "to": record["target"], "messageId": message_id})
            parts = [{"text": text}, {"data": {"steward": steward}}]
            record["messages"].append(dict(role="caller", parts=parts, at=now(), id=message_id))
            record["state"] = "working"
            self._telemetry(caller, "a2a_message", text, record)
            if record["transport"] == "inkbox" and record.get("providerTaskId") and not self.inkbox_available():
                record["providerError"] = "Follow-up kept local: STEWARD_A2A_TRANSPORT=local (or no INKBOX_API_KEY)."
            elif record["transport"] == "inkbox" and record.get("providerTaskId"):
                try:
                    self._inkbox_send(caller, record["target"], parts, message_id=message_id, context_id=record.get("providerContextId"),
                                      task_id=record["providerTaskId"])
                except Exception as error:
                    record["providerError"] = f"Inkbox A2A message failed ({type(error).__name__}): {str(error)[:200]}"
            self.save(record)
        self._emit(record, "caller", parts)
        if deliver:
            handler = self.handler_for(record["target"])
            if handler is not None and hasattr(handler, "on_message"):
                handler.on_message(self.task(task_id), record["messages"][-1])
        return self.task(task_id)

    def cancel(self, task_id: str, reason: str = "canceled") -> dict:
        with self.lock:
            record = self.task(task_id)
            if record["state"] in ("completed", "failed", "canceled"):
                return record
            record["state"] = "canceled"
            record["messages"].append(dict(role="caller", parts=[{"text": reason}, {"data": {"steward": dict(record.get("steward", {}), canceled=True)}}], at=now()))
            self.save(record)
        self._emit(record, "caller", record["messages"][-1]["parts"], "cancel")
        return record

    # ---- Inkbox transport -----------------------------------------------------------------------------

    def _provider_context(self, context_id: str | None, site: str, caller: str, target: str) -> str | None:
        """Reuse the provider context of an earlier task between the same two identities in the same local context.
        Inkbox rejects a context id reused by a different caller/worker pair (`-32602 contextId is invalid`)."""
        if not context_id:
            return None
        for record in self.store.all("a2a_task", site):
            if record["contextId"] == context_id and record.get("providerContextId") and record["caller"] == caller and record["target"] == target:
                return record["providerContextId"]
        return None

    @staticmethod
    def _client(api_key: str):
        from inkbox import Inkbox
        from .providers import inkbox_base_url
        return Inkbox(api_key=api_key, base_url=inkbox_base_url())

    def _card_url(self, identity, target_handle: str) -> str:
        explicit = clean_env(f"INKBOX_A2A_CARD_URL_{target_handle.upper().replace('-', '_')}")
        if explicit:
            return explicit
        own = identity.a2a_settings().card_url
        if identity.agent_handle in own:
            return own.replace(identity.agent_handle, target_handle)
        from .providers import inkbox_base_url
        base = inkbox_base_url().rstrip("/")
        return f"{base}/a2a/{target_handle}/card"

    def _inkbox_send(self, caller: str, target: str, parts: list[dict], message_id: str, context_id: str | None = None,
                     task_id: str | None = None) -> dict:
        key = agent_key(caller)
        if not key:
            raise RealityError(f"Outbound A2A from {caller} needs its identity-scoped key in {self._key_name(caller)}.", "PROVIDER_NOT_CONFIGURED",
                               "Create an agent-scoped (claimed) API key for the identity and set the variable.")
        handle, target_handle = handle_for(caller), handle_for(target)
        with self._client(key) as client:
            identity = client.get_identity(handle)
            a2a = identity.a2a_client()
            try:
                card = a2a.fetch_card(self._card_url(identity, target_handle))
                result = a2a.send(card, parts=parts, message_id=message_id, context_id=context_id, task_id=task_id)
            finally:
                a2a.close()
        if result.kind == "task" and result.task is not None:
            raw = result.task.raw
            return dict(taskId=str(raw.get("id")), contextId=str(raw.get("contextId") or "") or None, state=WIRE_STATE.get(str((raw.get("status") or {}).get("state")), "submitted"))
        raw = result.message.raw if result.message is not None else {}
        return dict(taskId=str(raw.get("taskId") or task_id or ""), contextId=str(raw.get("contextId") or "") or None, state="submitted")

    @staticmethod
    def _key_name(agent_id: str) -> str:
        from .agents import key_env_name
        return key_env_name(agent_id) or "INKBOX_AGENT_KEY"

    def _inkbox_reply(self, agent: str, provider_task_id: str, intent: str, parts: list[dict]) -> None:
        key = agent_key(agent) or clean_env("INKBOX_API_KEY")
        with self._client(key) as client:
            identity = client.get_identity(handle_for(agent))
            identity.a2a_reply(provider_task_id, intent=intent, parts=parts)

    # ---- inbound webhooks (a2a.*) --------------------------------------------------------------------

    def _agent_for_handle(self, handle: str | None) -> str | None:
        if not handle:
            return None
        needle = handle.strip().casefold()
        for agent_id in all_agent_ids():
            own = (handle_for(agent_id) or "").casefold()
            if own and own == needle:
                return agent_id
        return None

    def handle_inkbox_event(self, payload: dict) -> dict:
        event_type = str(payload.get("event_type", ""))
        data = payload.get("data") or {}
        provider_task_id = str(data.get("task_id") or "")
        parts = data.get("parts") or []
        steward = steward_data(parts)
        caller_handle = (data.get("caller") or {}).get("handle") if isinstance(data.get("caller"), dict) else None
        sender_handle = (data.get("sender") or {}).get("handle") if isinstance(data.get("sender"), dict) else None
        existing = self.by_provider_task(provider_task_id)
        site = steward.get("siteId") or (existing or {}).get("siteId") or DEMO_SITE
        if event_type == "a2a.task.created":
            if existing:
                return dict(routed=True, duplicate=True, taskId=existing["id"], detail="Echo of a task this process sent.")
            caller = steward.get("from") or self._agent_for_handle(caller_handle) or f"external:{caller_handle or 'unknown'}"
            caller = migrate_agent_id(caller, site)
            target = migrate_agent_id(steward.get("to") or "", site) or self._default_target(caller, site)
            record = dict(id=uid("a2a"), contextId=uid("ctx"), caller=caller, target=target, state="submitted",
                          messages=[dict(role="caller", parts=parts or [{"text": ""}], at=payload.get("timestamp") or now(), id=data.get("message_id"))],
                          transport="inkbox", providerTaskId=provider_task_id or None, providerContextId=str(data.get("context_id") or "") or None,
                          siteId=site, steward=dict(steward, **{"from": caller, "to": target}), createdAt=now(), updatedAt=now())
            with self.lock:
                self.save(record)
            self._emit(record, "caller", record["messages"][0]["parts"])
            self.touch(target, text_of(parts))
            handler = self.handler_for(target)
            if handler is not None and hasattr(handler, "on_task"):
                handler.on_task(self.task(record["id"]))
            return dict(routed=True, taskId=record["id"], target=target)
        if existing is None:
            self.store.event(site, DIRECTOR, "a2a.unmatched", f"Inkbox {event_type} for an unknown task", f"provider task {provider_task_id[:40]} has no local record.")
            return dict(routed=False, detail="No local task matches this provider task id.", eventType=event_type)
        if event_type == "a2a.task.message":
            if self._known_message(existing, data.get("message_id"), steward.get("messageId")):
                return dict(routed=True, duplicate=True, taskId=existing["id"])
            with self.lock:
                existing["messages"].append(dict(role="caller", parts=parts, at=payload.get("timestamp") or now(), id=data.get("message_id")))
                existing["state"] = "working"
                self.save(existing)
            self._emit(existing, "caller", parts)
            handler = self.handler_for(existing["target"])
            if handler is not None and hasattr(handler, "on_message"):
                handler.on_message(self.task(existing["id"]), existing["messages"][-1])
            return dict(routed=True, taskId=existing["id"])
        if event_type == "a2a.task.canceled":
            with self.lock:
                existing["state"] = "canceled"
                self.save(existing)
            self._emit(existing, "caller", [{"text": "canceled by caller"}], "cancel")
            handler = self.handler_for(existing["target"])
            if handler is not None and hasattr(handler, "on_cancel"):
                handler.on_cancel(self.task(existing["id"]))
            return dict(routed=True, taskId=existing["id"], state="canceled")
        if event_type == "a2a.sent_task.updated":
            state = str(data.get("state") or "")
            local_state = WIRE_STATE.get(state, state if state in INTENT_STATE.values() or state in ("submitted", "canceled") else existing["state"])
            if self._known_message(existing, data.get("message_id"), steward.get("messageId")) or not parts:
                with self.lock:
                    if local_state and local_state != existing["state"] and existing["state"] in OPEN_TASK_STATES:
                        existing["state"] = local_state
                        self.save(existing)
                return dict(routed=True, duplicate=bool(parts), taskId=existing["id"], state=existing["state"])
            intent = {"working": "progress", "input_required": "ask_caller", "completed": "complete", "failed": "fail"}.get(local_state, "progress")
            with self.lock:
                existing["messages"].append(dict(role="agent", parts=parts, at=payload.get("timestamp") or now(), id=data.get("message_id"), intent=intent))
                existing["state"] = local_state or existing["state"]
                self.save(existing)
            self._emit(existing, "agent", parts, intent)
            handler = self.handler_for(existing["caller"])
            if handler is not None and hasattr(handler, "on_reply"):
                handler.on_reply(self.task(existing["id"]), existing["messages"][-1], intent)
            return dict(routed=True, taskId=existing["id"], state=existing["state"])
        return dict(routed=False, ignored=True, eventType=event_type)

    @staticmethod
    def _known_message(record: dict, provider_message_id, steward_message_id) -> bool:
        for message in record["messages"]:
            if provider_message_id and message.get("id") == provider_message_id:
                return True
            if steward_message_id and steward_data(message["parts"]).get("messageId") == steward_message_id:
                return True
        return False

    @staticmethod
    def _default_target(caller: str, site: str) -> str:
        """Down the chain of command: director → manager → engineer → technician; anyone else → director."""
        try:
            if caller == DIRECTOR:
                return manager_id(site)
            if kind_of(caller) == "manager":
                return engineer_id(site)
            if kind_of(caller) == "engineer":
                return technician_id(site)
        except RealityError:
            pass
        return DIRECTOR

    # ---- startup: skills and recovery --------------------------------------------------------------------

    def start(self) -> None:
        if not self.inkbox_available():
            return
        self._thread = threading.Thread(target=self._startup, name="steward-a2a-startup", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _startup(self) -> None:
        """Recover submitted tasks and, only with STEWARD_A2A_SET_SKILLS=true, (re)advertise skills on the Agent Cards
        (contract 4: the role skills are already on the cards). Never raises; every failure is an event."""
        from .agents import OPERATOR
        set_skills = env("STEWARD_A2A_SET_SKILLS", "false").strip().lower() == "true"
        for agent_id in all_agent_ids():
            if agent_id == OPERATOR or not handle_for(agent_id) or self._stop.is_set():
                continue
            key = agent_key(agent_id) or clean_env("INKBOX_API_KEY")
            try:
                from inkbox.a2a.types import A2ASkill
                with self._client(key) as client:
                    identity = client.get_identity(handle_for(agent_id))
                    if set_skills:
                        skills = [A2ASkill(id=sid, name=name, description=desc, tags=["steward", kind_of(agent_id)]) for sid, name, desc in SKILLS[kind_of(agent_id)]]
                        identity.a2a_set_skills(skills)
                        self.store.event(site_of(agent_id) or DEMO_SITE, agent_id, "a2a.skills", "Agent Card skills set", ", ".join(s.id for s in skills))
                    recovered = 0
                    for task in identity.a2a_tasks(state="submitted").items:
                        if self.by_provider_task(str(task.id)):
                            continue
                        parts = task.messages[0].parts if task.messages else []
                        payload = dict(id=f"recover-{task.id}", event_type="a2a.task.created", timestamp=now(),
                                       data=dict(task_id=str(task.id), context_id=str(task.context_id), state="submitted",
                                                 caller=dict(handle=task.caller.handle, identity_id=task.caller.identity_id, organization_id=task.caller.organization_id),
                                                 message_id=task.messages[0].message_id if task.messages else None, parts=parts))
                        self.handle_inkbox_event(payload)
                        recovered += 1
                    if recovered:
                        self.store.event(site_of(agent_id) or DEMO_SITE, agent_id, "a2a.recovered", "Submitted A2A tasks recovered", f"{recovered} task(s)")
            except Exception as error:
                self.store.event(site_of(agent_id) or DEMO_SITE, agent_id, "a2a.startup_failed", "A2A startup step failed",
                                 f"{type(error).__name__} ({str(error)[:160]}): skills/recovery skipped for {agent_id}; sends still work when keys are valid.")
