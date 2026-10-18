"""Real records only (owner, Oct 18 2026): seed records are hidden by default; real Inkbox traffic is shown as texts.

A record is **seed** when it was inserted at seed time and never happened in this running system: a conversation,
message, memory or notification loaded from `backend/seed` instead of being produced by a scenario run, a fix
workflow, a walkthrough, a compliance alert, the maintenance planner, a mission, an eval, an agent's tool call or
real Inkbox traffic. Conversations and agent memories carry `origin`:

- `seed`: loaded from `backend/seed`: the record carries the seed loader's `generator` stamp or a seed-family id, or
  (conversations) it has no run or workflow provenance and never went over the A2A bus;
- `run`: written by a scenario run (`runId`);
- `workflow`: written while the system runs by a fix workflow, walkthrough, compliance alert, maintenance planner,
  mission, eval, decision or tool request, the simulator, or any other agent action;
- `inkbox`: real external traffic carried by Inkbox (A2A over Inkbox, email, SMS and calls with a provider reference).

New records get `origin` where they are created (`ConversationService._new`, `MemoryStore.write`); records written
earlier are backfilled once (`migrate_origins`, meta `steward_origin_version`). An origin that is already set is never
overwritten and nothing is deleted: read endpoints hide `seed` by default and `?include=all` returns everything.

**Real texts** (`real_texts`): every email, SMS, iMessage and call actually sent or received through Inkbox becomes a
read-only conversation of kind `message` (`id: conv-msg-<source>-<recordId>`, `origin: "inkbox"`, `channel`,
`direction: outbound | inbound | internal`, `providerRef`, `person`, `participants`, the text and its time): work-item
dispatches with a provider receipt, notices and owner SMS sent for real, agent-to-agent document email sent for real,
owner alerts whose email or call was sent, and inbound messages received through the Inkbox webhook (directly or
replayed from the Supabase inbox queue). Dry-run, capped, failed, local and simulated records never appear.
"""
from __future__ import annotations

import re

from .agents import DIRECTOR, DISPATCH, OWNER, compliance_id, display_name, is_known, technician_id
from .providers import EMAIL_RE, clean_env
from .sites import SITE_BY_ID

ORIGINS = ("seed", "run", "workflow", "inkbox")
ORIGIN_META = "steward_origin_version"
ORIGIN_VERSION = "1"
INCLUDE_ALL = "all"
# Fields that mark a conversation (or notification) as produced by a workflow while the system runs.
WORKFLOW_KEYS = ("workflowId", "patrolId", "alertId", "ownerAlertId", "missionId", "toolRequestId", "maintenanceId", "maintenanceWindowId",
                 "evalRunId", "evalId", "decisionRequestId", "planId")
OUT_CHANNELS = ("sms", "imessage", "email", "call")
CHANNEL_LABEL = {"sms": "SMS", "imessage": "iMessage", "email": "Email", "call": "Call", "a2a": "A2A"}
TEXT_PREFIX = "conv-msg-"


def include_all(include: str | None) -> bool:
    return str(include or "").strip().casefold() == INCLUDE_ALL


def _seed_conversation_ids() -> frozenset:
    """Ids of the conversation scripts in backend/seed/synthetic (scenario steps reference them by id)."""
    try:
        from .synthetic import by_id
        return frozenset(by_id("conversations"))
    except Exception:
        return frozenset()


# ---- origin -------------------------------------------------------------------------------------------------------

def creation_origin(fields: dict, default: str = "workflow") -> str:
    """The origin of a record created while the system runs: an explicit valid origin, `run` for a scenario run,
    otherwise `default` (a workflow or agent action)."""
    explicit = fields.get("origin")
    if explicit in ORIGINS:
        return explicit
    if fields.get("runId"):
        return "run"
    return default


def memory_creation_origin(refs: dict | None, origin: str | None = None) -> str:
    refs = refs or {}
    return creation_origin(dict(origin=origin, runId=refs.get("runId") or refs.get("scenarioId")))


def conversation_origin(record: dict) -> str:
    """Classify a stored conversation (backfill and records written without `origin`). An explicit origin wins."""
    explicit = record.get("origin")
    if explicit in ORIGINS:
        return explicit
    if record.get("runId"):
        return "run"
    if any(record.get(key) for key in WORKFLOW_KEYS):
        return "workflow"
    if record.get("generator") or record.get("id") in _seed_conversation_ids():
        return "seed"
    if not record.get("a2aTaskIds"):
        return "seed"  # never went over the bus: it did not happen in this running system
    if record.get("transport") == "inkbox" and record.get("providerTaskIds"):
        return "inkbox"
    return "workflow"


def memory_origin(record: dict, conversation_origins: dict | None = None) -> str:
    """Classify an agent memory (backfill and records written without `origin`). An explicit origin wins."""
    explicit = record.get("origin")
    if explicit in ORIGINS:
        return explicit
    refs = record.get("refs") or {}
    if refs.get("runId") or refs.get("scenarioId"):
        return "run"
    conversation_id = refs.get("conversationId")
    if conversation_id and conversation_origins and conversation_id in conversation_origins:
        return conversation_origins[conversation_id]
    if record.get("generator") or not str(record.get("id") or "").startswith("amem-"):
        return "seed"  # not written by MemoryStore.write: loaded from a seed file
    if conversation_id and conversation_id in _seed_conversation_ids():
        return "seed"
    return "workflow"


def notification_origin(record: dict) -> str:
    explicit = record.get("origin")
    if explicit in ORIGINS:
        return explicit
    if record.get("runId"):
        return "run"
    if any(record.get(key) for key in WORKFLOW_KEYS):
        return "workflow"
    if record.get("generator") or not str(record.get("id") or "").startswith("ntf-"):
        return "seed"
    return "workflow"


def conversation_origins(store) -> dict:
    return {c["id"]: conversation_origin(c) for c in store.all("conversation", "")}


def migrate_origins(store) -> dict:
    """Backfill `origin` on conversations and agent memories once (meta `steward_origin_version`). Idempotent: an
    origin already set is kept, nothing is deleted, and a re-run classifies the same records the same way."""
    if store.meta(ORIGIN_META) == ORIGIN_VERSION:
        return {}
    counts = dict(conversations=0, memories=0)
    origins = {}
    for record in store.all("conversation", ""):
        origin = conversation_origin(record)
        origins[record["id"]] = origin
        if record.get("origin") != origin:
            store.put("conversation", dict(record, origin=origin), "")
            counts["conversations"] += 1
    for record in store.all("agent_memory", ""):
        if record.get("origin") in ORIGINS:
            continue
        store.put("agent_memory", dict(record, origin=memory_origin(record, origins)), "")
        counts["memories"] += 1
    store.meta(ORIGIN_META, ORIGIN_VERSION)
    return counts


# ---- real texts ---------------------------------------------------------------------------------------------------

class _People:
    """Who is at the far end of a real text: the owner, the site's crew member who is the user, or a masked address."""

    def __init__(self, store):
        from .people import mask_email, mask_phone, user_email, user_phone
        from .providers import InkboxAdapter
        self.store = store
        self._mask_email, self._mask_phone = mask_email, mask_phone
        owner_email = clean_env("INKBOX_OWNER_EMAIL")
        self.owner = {v.casefold() for v in (InkboxAdapter.owner_phone(), owner_email if EMAIL_RE.match(owner_email) else "") if v}
        self.user = {v.casefold() for v in (user_phone(), user_email()) if v}
        self._crew: dict = {}

    def mask(self, address: str | None) -> str | None:
        if not address:
            return None
        if "•" in address:
            return address  # stored masked already (owner alerts)
        return self._mask_email(address) if "@" in address else self._mask_phone(address)

    def _user_crew(self, site: str | None) -> dict | None:
        if site not in self._crew:
            records = self.store.all("crew_member", site) if site else []
            self._crew[site] = next((c for c in records if c.get("contact") == "user"), None)
        return self._crew[site]

    def owner_entry(self, address: str | None = None) -> dict:
        return dict(id=OWNER, name="Owner", kind="owner", address=self.mask(address))

    def resolve(self, site: str | None, address: str | None, name: str | None = None, role: str | None = None, crew_id: str | None = None) -> dict:
        key = (address or "").strip().casefold()
        if key and key in self.owner:
            return self.owner_entry(address)
        if name:
            return dict(id=name, name=name, role=role, crewMemberId=crew_id, kind="crew", address=self.mask(address))
        if key and key in self.user:
            crew = self._user_crew(site)
            if crew:
                return dict(id=crew["name"], name=crew["name"], role=crew.get("role"), crewMemberId=crew["id"], kind="crew", address=self.mask(address))
            return dict(id="Contractor", name="Contractor", kind="contractor", address=self.mask(address))
        masked = self.mask(address) or "unknown sender"
        return dict(id=masked, name=masked, kind="external", address=masked if address else None)


def _team_member(site: str | None, build) -> str:
    try:
        return build(site) if site in SITE_BY_ID else DIRECTOR
    except Exception:
        return DIRECTOR


def _name(participant: str, person: dict) -> str:
    return person["name"] if participant == person["id"] else display_name(participant)


def _call_lines(body: str, ours: str, person: dict, at: str, provider_ref: str | None) -> list[dict]:
    """`Call outcome: completed. local: ...\\nremote: ...` (Inkbox call.ended) as speaker lines."""
    text = re.sub(r"^Call outcome: [^.]*\.\s*", "", body or "")
    lines = []
    for raw in text.split("\n"):
        party, sep, said = raw.partition(":")
        if not sep or party.strip().casefold() not in ("local", "remote", "agent", "user", "caller", "callee"):
            party, said = "", raw
        said = said.strip()
        if not said:
            continue
        speaker = ours if party.strip().casefold() in ("local", "agent") else person["id"]
        lines.append(dict(seq=len(lines) + 1, speaker=speaker, agentId=speaker if is_known(speaker) or speaker == DISPATCH else None,
                          name=_name(speaker, person), text=said[:1500], at=at, channel="call", direction="inbound", providerRef=provider_ref))
    return lines


def _entry(source: str, record_id: str, *, site: str | None, channel: str, direction: str, sender: str, recipient: str, text: str, at: str,
           provider_ref: str | None, person: dict, topic: str, refs: dict | None = None, lines: list[dict] | None = None, suffix: str = "",
           summaries: dict | None = None) -> dict:
    identifier = f"{TEXT_PREFIX}{source}-{record_id}{suffix}"
    text = (text or "").strip()[:4000]
    line = dict(seq=1, speaker=sender, agentId=sender if sender != person["id"] else None, name=_name(sender, person), text=text[:1500], at=at,
                channel=channel, direction=direction, providerRef=provider_ref, transport="inkbox")
    stored = (summaries or {}).get(identifier) or {}
    entry = dict(id=identifier, kind="message", origin="inkbox", real=True, derived=True, channel=channel, direction=direction,
                 providerRef=provider_ref, provider="inkbox", topic=topic[:200], convener=sender, participants=list(dict.fromkeys([sender, recipient])),
                 person=person, siteIds=[site] if site else [], transport="inkbox", providerTaskIds=[], a2aTaskIds=[], contextId=None,
                 transcript=lines or [line], text=text, at=at, summary=stored.get("summary"), summaryBy=stored.get("summaryBy"), startedAt=at, endedAt=at,
                 status="ended", delivery="received" if direction == "inbound" else "sent", synthetic=False, voiceNote=None,
                 source=dict(kind=source, id=record_id))
    entry.update({k: v for k, v in (refs or {}).items() if v})
    return entry


def real_texts(service, summaries: dict | None = None) -> list[dict]:
    """Every email, SMS, iMessage and call actually sent or received through Inkbox, as `message` conversations,
    deduplicated by (channel, providerRef). Built from the stored records on every read; nothing is written."""
    store = service.store
    people = _People(store)
    entries: list[dict] = []

    # Owner alerts (contract 7 §2): the owner email from the site's Compliance Officer and the Dispatch Line's call.
    for alert in store.all("owner_alert"):
        site = alert.get("siteId")
        refs = dict(alertId=alert.get("id"), issueId=alert.get("issueId"), obligationId=alert.get("obligationId"), patrolId=alert.get("patrolId"))
        email = alert.get("email") if isinstance(alert.get("email"), dict) else {}
        if email.get("mode") == "sent" and email.get("providerRef"):
            sender = email.get("fromAgent") if is_known(str(email.get("fromAgent") or "")) else _team_member(site, compliance_id)
            files = ", ".join(str(a.get("filename")) for a in email.get("attachments") or [] if isinstance(a, dict) and a.get("filename"))
            body = str(email.get("text") or email.get("bodyText") or email.get("body") or alert.get("title") or "")
            text = "\n".join(part for part in (email.get("subject"), body, f"Attached: {files}" if files and "Attached:" not in body else "") if part)
            entries.append(_entry("alert", alert["id"], site=site, channel="email", direction="outbound", sender=sender, recipient=OWNER, text=text,
                                  at=email.get("at") or alert.get("at") or "", provider_ref=str(email["providerRef"]), person=people.owner_entry(email.get("to")),
                                  topic=email.get("subject") or f"Email to the owner: {alert.get('title') or 'compliance alert'}", refs=refs,
                                  suffix="-email", summaries=summaries))
        call = alert.get("call") if isinstance(alert.get("call"), dict) else {}
        if call.get("mode") == "sent" and call.get("providerRef"):
            text = call.get("brief") or call.get("script") or alert.get("title") or ""
            entries.append(_entry("alert", alert["id"], site=site, channel="call", direction="outbound", sender=DISPATCH, recipient=OWNER, text=str(text),
                                  at=call.get("at") or alert.get("at") or "", provider_ref=str(call["providerRef"]), person=people.owner_entry(call.get("to")),
                                  topic=f"Call to the owner: {alert.get('title') or 'compliance alert'}", refs=refs, suffix="-call", summaries=summaries))

    # Notices delivered for real by the site's Field Technician (SMS through the dispatch line, or email).
    for notice in store.all("notice"):
        if notice.get("mode") != "sent" or not notice.get("providerRef") or notice.get("simulated"):
            continue
        channel = notice.get("channel") if notice.get("channel") in OUT_CHANNELS else "sms"
        site = notice.get("siteId")
        sender = notice.get("via") or _team_member(site, technician_id)
        person = people.resolve(site, None, notice.get("toName"), notice.get("toRole"), notice.get("toCrewId"))
        entries.append(_entry("notice", notice["id"], site=site, channel=channel, direction="outbound", sender=sender, recipient=person["id"],
                              text=notice.get("text") or "", at=notice.get("at") or "", provider_ref=str(notice["providerRef"]), person=person,
                              topic=f"{CHANNEL_LABEL[channel]} to {person['name']}: {str(notice.get('noticeKind') or 'notice').replace('_', ' ')} notice",
                              refs=dict(noticeId=notice["id"], onBehalfOf=notice.get("sender"), issueId=notice.get("issueId"),
                                        obligationId=notice.get("obligationId"), scenarioId=notice.get("scenarioId"), runId=notice.get("runId")),
                              summaries=summaries))

    # Notifications sent for real outside a notice or an owner alert (the owner's copy of a decision request).
    for note in store.all("notification"):
        if note.get("mode") != "sent" or not note.get("providerRef") or note.get("channel") not in OUT_CHANNELS:
            continue
        if note.get("noticeId") or note.get("alertId") or note.get("ownerAlertId") or note.get("simulated"):
            continue  # shown through its notice or owner alert
        site = note.get("siteId")
        sender = note.get("sender") or _team_member(site, technician_id)
        person = people.owner_entry() if note.get("toKind") == "owner" or note.get("to") == OWNER else people.resolve(site, None, note.get("toName") or note.get("to"))
        entries.append(_entry("notification", note["id"], site=site, channel=note["channel"], direction="outbound", sender=sender, recipient=person["id"],
                              text=note.get("text") or "", at=note.get("at") or "", provider_ref=str(note["providerRef"]), person=person,
                              topic=f"{CHANNEL_LABEL[note['channel']]} to {person['name']}", summaries=summaries,
                              refs=dict(notificationId=note["id"], issueId=note.get("issueId"), decisionRequestId=note.get("decisionRequestId"),
                                        workflowId=note.get("workflowId"))))

    # Agent-to-agent document email sent for real between two Inkbox identities.
    for email in store.all("document_email"):
        if email.get("mode") != "sent" or not email.get("providerMessageId"):
            continue
        attachment = email.get("attachment") or {}
        text = "\n".join(part for part in (email.get("subject"), email.get("bodyText"),
                                           f"Attached: {attachment.get('filename')}" if attachment.get("filename") else "") if part)
        sender, recipient = email.get("sender") or DIRECTOR, email.get("recipient") or DIRECTOR
        person = dict(id=recipient, name=display_name(recipient), kind="agent", address=None)
        entries.append(_entry("email", email["id"], site=email.get("siteId"), channel="email", direction="internal", sender=sender, recipient=recipient,
                              text=text, at=email.get("at") or "", provider_ref=str(email["providerMessageId"]), person=person,
                              topic=email.get("subject") or "Document email", summaries=summaries,
                              refs=dict(emailId=email["id"], documentId=email.get("documentId"), scenarioId=email.get("scenarioId"), runId=email.get("runId"))))

    # Work-item task cards, reminders, escalations and verdict replies the provider accepted (a provider receipt).
    for dispatch in store.all("dispatch"):
        channel = dispatch.get("channel")
        if channel not in OUT_CHANNELS or not dispatch.get("providerRef") or dispatch.get("simulated"):
            continue
        site = dispatch.get("propertyId") or dispatch.get("_propertyId")
        sender = _team_member(site, technician_id)
        person = people.resolve(site, dispatch.get("to"))
        entries.append(_entry("dispatch", dispatch["id"], site=site, channel=channel, direction="outbound", sender=sender, recipient=person["id"],
                              text=dispatch.get("body") or "", at=dispatch.get("sentAt") or "", provider_ref=str(dispatch["providerRef"]), person=person,
                              topic=f"{CHANNEL_LABEL[channel]} to {person['name']}: {dispatch.get('reference') or 'task card'}", summaries=summaries,
                              refs=dict(workItemId=dispatch.get("workItemId") or dispatch.get("_workItemId"), reference=dispatch.get("reference"),
                                        via=DISPATCH if channel in ("sms", "call") else None)))

    # Messages received through the Inkbox webhook (direct or replayed from the Supabase inbox queue).
    for kind in ("inbound_message", "inbound_unrouted"):
        for message in store.all(kind):
            if message.get("provider") != "inkbox" or message.get("simulated"):
                continue
            channel = message.get("channel") if message.get("channel") in OUT_CHANNELS else "sms"
            site = message.get("propertyId") or _site_of_handles(message)
            # The site's Field Technician reads replies; with no site, the dispatch line (phone) or the director (email).
            ours = _team_member(site, technician_id) if site in SITE_BY_ID else (DIRECTOR if channel == "email" else DISPATCH)
            person = people.resolve(site, message.get("sender"))
            at = message.get("receivedAt") or message.get("at") or message.get("storedAt") or ""
            provider_ref = str(message.get("providerMessageId") or "") or None
            body = message.get("body") or ""
            text = "\n".join(part for part in (message.get("subject") if channel == "email" else "", body) if part)
            lines = _call_lines(body, ours, person, at, provider_ref) if channel == "call" else None
            label = "Call transcript" if channel == "call" else CHANNEL_LABEL[channel]
            entries.append(_entry("inbound", message["id"], site=site, channel=channel, direction="inbound", sender=person["id"], recipient=ours,
                                  text=text, at=at, provider_ref=provider_ref, person=person, lines=lines or None, summaries=summaries,
                                  topic=f"{label} from {person['name']}" + (f": {message['reference']}" if message.get("reference") else ""),
                                  refs=dict(workItemId=message.get("workItemId"), reference=message.get("reference"), verdict=message.get("verdict"),
                                            attestationId=message.get("attestationId"), threadRef=message.get("threadRef"),
                                            audioUrl=message.get("audioUrl") or message.get("recordingUrl"), transcriptUrl=message.get("transcriptUrl"),
                                            unrouted=kind == "inbound_unrouted")))

    seen, unique = set(), []
    for entry in entries:
        key = (entry["channel"], entry["direction"], entry["providerRef"])
        if entry["providerRef"] and key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _site_of_handles(message: dict) -> str | None:
    from .providers import InkboxAdapter
    for handle in list(message.get("identityHandles") or []) + [message.get("localAddress")]:
        site = InkboxAdapter.site_for_handle(handle) if handle else None
        if site:
            return site
    return None
