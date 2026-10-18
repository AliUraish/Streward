"""Per-agent transcripts assembled from persisted records: A2A task messages, dispatches (sms/email/imessage/call) and
inbound replies (the site's Field Technician), owner decisions (the Operations Director), Owner's-agent calls (`mcp`
entries), mission steps (`system`), meeting statements (`board`), document email, notices, notifications, scenario
narration and reconfigurations.

Nothing here is generated; every entry points at a stored record through `refs`. Call entries carry the Inkbox
transcript text and `audioUrl` when the provider reported a recording URL.
"""
from __future__ import annotations

import hashlib
import json

from .agents import DIRECTOR, OPERATOR, all_agent_ids, display_name, is_known, kind_of, site_of, site_team
from .errors import RealityError

CHANNEL_KINDS = {"sms": "sms", "email": "email", "imessage": "imessage", "call": "call", "local": "sms"}


def _entry(agent_id, at, kind, direction, counterpart, text, refs, parts=None, audio_url=None, simulated=False, seed=""):
    entry = dict(id="tr-" + hashlib.sha256(f"{agent_id}:{kind}:{direction}:{at}:{seed}:{text[:80]}".encode()).hexdigest()[:14], agentId=agent_id, at=at,
                 kind=kind, direction=direction, counterpart=counterpart, text=text[:4000], refs={k: v for k, v in refs.items() if v})
    if parts is not None:
        entry["parts"] = parts
    if audio_url:
        entry["audioUrl"] = audio_url
    if simulated:
        entry["simulated"] = True
    return entry


def compact_args(args: dict) -> str:
    """Compact, bounded, secret-free rendering of endpoint arguments."""
    cleaned = {}
    for key, value in (args or {}).items():
        if key in ("file", "fileBytes", "authorization", "token", "secret", "apiKey") or key.startswith("_"):
            continue
        if isinstance(value, (bytes, bytearray)):
            cleaned[key] = f"<{len(value)} bytes>"
        elif isinstance(value, str):
            cleaned[key] = value[:120]
        else:
            cleaned[key] = value
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))[:600]


def transcript(service, agent_id: str, since: int = 0, limit: int = 200) -> list[dict]:
    if not is_known(agent_id) or agent_id == "owner":
        raise RealityError(f"Unknown agent '{agent_id[:40]}'.", "NOT_FOUND", "Use one of: " + ", ".join(all_agent_ids()) + ".", 404)
    store = service.store
    entries: list[dict] = []
    for task in store.all("a2a_task"):
        if agent_id not in (task["caller"], task["target"]):
            continue
        other = task["target"] if task["caller"] == agent_id else task["caller"]
        steward = task.get("steward") or {}
        for message in task["messages"]:
            text = " ".join(str(p.get("text")) for p in message["parts"] if isinstance(p, dict) and p.get("text")).strip()
            from_me = (message["role"] == "caller") == (task["caller"] == agent_id)
            data = next((p.get("data", {}).get("steward", {}) for p in message["parts"] if isinstance(p, dict) and isinstance(p.get("data"), dict)), {})
            refs = dict(missionId=steward.get("missionId"), taskId=task["id"], workItemId=data.get("workItemId") or steward.get("workItemId"),
                        attestationId=data.get("attestationId"))
            label = f"[{message.get('intent')}] " if message.get("intent") else ""
            entries.append(_entry(agent_id, message["at"], "a2a", "out" if from_me else "in", other, label + text, refs, parts=message["parts"],
                                  simulated=bool(task.get("simulated")), seed=message.get("id") or task["id"]))
    technician_site = site_of(agent_id) if kind_of(agent_id) == "technician" else None
    if technician_site:
        for dispatch in store.all("dispatch", technician_site):
            kind = CHANNEL_KINDS.get(dispatch["channel"], "sms")
            counterpart = dispatch.get("to") or "local task card"
            entries.append(_entry(agent_id, dispatch["sentAt"], kind, "out", counterpart, dispatch["body"],
                                  dict(workItemId=dispatch.get("workItemId")), simulated=bool(dispatch.get("simulated")), seed=dispatch["id"]))
        for inbound in store.all("inbound_message", technician_site):
            kind = CHANNEL_KINDS.get(inbound["channel"], "sms")
            text = inbound["body"] or inbound.get("subject") or ""
            if inbound["channel"] == "call" and inbound.get("transcriptUrl"):
                text = (text + f"\n(transcript: {inbound['transcriptUrl']})").strip()
            entries.append(_entry(agent_id, inbound["receivedAt"], kind, "in", inbound.get("sender") or "unknown", text,
                                  dict(workItemId=inbound["workItemId"], attestationId=inbound.get("attestationId")), audio_url=inbound.get("audioUrl"),
                                  simulated=bool(inbound.get("simulated")), seed=inbound["id"]))
    if agent_id == DIRECTOR:
        for item in store.all("work_item"):
            decision = item.get("ownerDecision")
            if decision:
                text = f"Owner decided '{decision['decision']}' on {item['reference']} ({item['assetTag']}.{item['attribute']})" + (f": {decision['note']}" if decision.get("note") else "")
                entries.append(_entry(agent_id, decision["at"], "decision", "in", "owner", text, dict(workItemId=item["id"], attestationId=item.get("attestationId")),
                                      simulated=bool(item.get("simulated")), seed=item["id"]))
    if agent_id == OPERATOR:
        for call in store.all("operator_call", ""):
            entries.append(_entry(agent_id, call["at"], "mcp", "out", "steward", f"{call['endpoint']} {call['args']}",
                                  dict(missionId=call.get("missionId"), workItemId=call.get("workItemId")), seed=call["id"]))
    for mission in store.all("mission"):
        for step in mission.get("steps", []):
            if step["agentId"] != agent_id:
                continue
            entries.append(_entry(agent_id, step["at"], "system", "out", "mission", step["summary"],
                                  dict(missionId=mission["id"], taskId=step.get("taskId"), workItemId=step.get("workItemId"), attestationId=step.get("attestationId")),
                                  seed=step["id"]))
    # Contract 3: board statements Atlas made in the room, document email, notices, scenario narration, reconfigurations.
    for conversation in store.all("conversation", ""):
        for line in conversation.get("transcript", []):
            if line.get("speaker") == agent_id and not line.get("taskId"):
                entries.append(_entry(agent_id, line["at"], "board", "out", f"{conversation['kind']}:{conversation['id']}", line["text"],
                                      dict(conversationId=conversation["id"], issueId=conversation.get("issueId")), seed=f"{conversation['id']}:{line['seq']}"))
    for email in store.all("document_email"):
        prefix = "" if email["mode"] == "sent" else f"[{email['mode']}] "
        text = f"{prefix}{email['subject']}\n{email['bodyText']}\n(attachment {email['attachment']['filename']}, {email['attachment']['size']} bytes)"
        refs = dict(documentId=email["documentId"], taskId=email.get("a2aTaskId"), emailId=email["id"])
        if agent_id == email["sender"]:
            entries.append(_entry(agent_id, email["at"], "email", "out", email["recipient"], text, refs, seed=email["id"]))
        elif agent_id == email["recipient"]:
            entries.append(_entry(agent_id, email["at"], "email", "in", email["sender"], text, refs, seed=email["id"]))
    for notice in store.all("notice"):
        channel_kind = {"sms": "sms", "email": "email"}.get(notice.get("channel") or "", "system")
        text = ("" if notice["mode"] == "sent" else f"[{notice['mode']}] ") + notice["text"]
        refs = dict(noticeId=notice["id"], issueId=notice.get("issueId"), obligationId=notice.get("obligationId"))
        if agent_id == notice.get("via"):
            entries.append(_entry(agent_id, notice["at"], channel_kind, "out", notice.get("toName") or "nobody", text, refs, seed=notice["id"]))
        elif agent_id == notice.get("sender"):
            entries.append(_entry(agent_id, notice["at"], "system", "out", notice.get("via") or "technician",
                                  f"Notice for {notice.get('toName') or 'nobody'} handed to {display_name(notice.get('via') or '')}: {notice['text']}",
                                  refs, seed=notice["id"]))
    for notification in store.all("notification"):
        if agent_id == notification.get("sender"):
            entries.append(_entry(agent_id, notification["at"], "system", "out", notification.get("toName") or notification.get("to") or "",
                               f"[{notification['mode']}] {notification['text']}", dict(notificationId=notification["id"], issueId=notification.get("issueId")),
                               seed=notification["id"]))
    for run in store.all("scenario_run", ""):
        for line in run.get("log", []):
            if line.get("agentId") == agent_id and line["type"] in ("narrate", "findings", "review_document", "reconfigure", "memory"):
                entries.append(_entry(agent_id, line["at"], "system", "out", f"scenario:{run['scenarioId']}", line["summary"],
                                      dict(scenarioRunId=run["id"]), simulated=False, seed=f"{run['id']}:{line['index']}"))
    for config in store.all("agent_config", ""):
        for change in config.get("history", []):
            if agent_id == change.get("by") or agent_id == config["agentId"]:
                direction = "out" if agent_id == change.get("by") else "in"
                text = f"{display_name(change['by'])} set {display_name(config['agentId'])} " + ", ".join(f"{k}={v}" for k, v in change["change"].items()) + \
                       (f": {change['reason']}" if change.get("reason") else "")
                entries.append(_entry(agent_id, change["at"], "decision", direction, config["agentId"] if direction == "out" else change["by"], text,
                                      dict(configVersion=str(change["version"])), seed=f"{config['id']}:{change['version']}"))
    entries.sort(key=lambda e: e["at"])
    return entries[since:since + limit]


def agent_ids_for_site(site_id: str) -> list[str]:
    return [OPERATOR, DIRECTOR, *site_team(site_id)]
