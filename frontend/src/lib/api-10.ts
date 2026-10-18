/* Contract 8 (REALITY-CONTRACT-8.md): the phone calls that reach you (you are the owner, the contractor or an employee,
   on your one phone), the outbox that paces everything that reaches you, the employees' badge log with the People
   Officer's cases, and the Site Inspector's inspections. Field names follow the contract; obvious alternatives are
   accepted so a partial backend still renders. Every loader throws the ApiError of api.ts, so a 404 reads as "not
   available yet" through useRemote's readiness. Phone numbers and addresses are never kept for display: a person is
   named by role ("you (contractor)"), and numbers or addresses said on a call are masked in the transcript. */
import { request } from "./api";
import { list } from "./api-3";
import { AGENTS3, agentName, canonicalId, rn } from "./sites-3";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const obj = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? v as Raw : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => typeof v === "string" && v.trim() ? v.trim() : typeof v === "number" && Number.isFinite(v) ? String(v) : null;
const num = (v: unknown): number | null => typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)) ? Number(v) : null;
/* An ISO time, or epoch seconds or milliseconds turned into one. */
const isoOf = (v: unknown): string | null => typeof v === "number" && Number.isFinite(v) ? new Date(v < 1e12 ? v * 1000 : v).toISOString() : str(v);
const word = (v: string | null) => (v ?? "").toLowerCase().replace(/[\s-]+/g, "_");
const enc = encodeURIComponent;
const qs = (values: Record<string, string | number | boolean | undefined | null>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  return q.size ? `?${q}` : "";
};
const t = (iso: string | null | undefined) => { const x = iso ? Date.parse(iso) : NaN; return Number.isNaN(x) ? 0 : x; };
const newest = <T,>(at: (x: T) => string | null | undefined) => (a: T, b: T) => t(at(b)) - t(at(a));

/* ---- people: you, in a role ------------------------------------------------------------------------------- */
export type PersonRole = "owner" | "contractor" | "employee";
const ROLE_WORD: Record<string, string> = { owner: "you (owner)", contractor: "you (contractor)", employee: "you (employee)" };
const ROLE_NOUN: Record<string, string> = { owner: "the owner", contractor: "the contractor", employee: "the employee" };
export const isPersonRole = (r: string | null | undefined): r is PersonRole => r === "owner" || r === "contractor" || r === "employee";
/* "you (contractor)": how the dashboard names a person on a call or an email. */
export const roleWord = (r: string | null | undefined) => (r && ROLE_WORD[r]) || "you";
/* "the contractor": the same person in a sentence about the agent ("is calling the contractor"). */
export const roleNoun = (r: string | null | undefined) => (r && ROLE_NOUN[r]) || "you";
/* An agent from its own mailbox ("steward-bristol-manager@inkboxmail.com" is the Plant Manager · Bristol). */
export function agentOfAddress(v: string | null | undefined): string | null {
  const handle = (v ?? "").trim().toLowerCase().replace(/@.*$/, "");
  return handle ? AGENTS3.find(a => a.inbox === handle)?.id ?? null : null;
}
/* A recipient named in a record: a role reads as "you (role)", an agent by its name; addresses are never shown. */
export function recipientWord(v: unknown): string {
  const o = obj(v);
  const id = typeof v === "string" ? v : str(o.id ?? o.role ?? o.agentId);
  if (id && isPersonRole(id)) return roleWord(id);
  if (id && !id.includes("@")) return agentName(canonicalId(id));
  const mailbox = agentOfAddress(id ?? str(o.address));
  if (mailbox) return agentName(mailbox);
  const name = str(o.name);
  return name && !name.includes("@") ? rn(name) : "a recipient";
}

/* Numbers and addresses someone says on a call ("six two eight four eight eight…", "+1 628…", "me@example.com") are
   masked before anything shows them. */
const DIGIT_WORDS = "zero|oh|one|two|three|four|five|six|seven|eight|nine|double|triple";
const SPOKEN_NUMBER = new RegExp(`\\b(?:${DIGIT_WORDS})(?:[\\s,.-]+(?:${DIGIT_WORDS})){3,}\\b`, "gi");
export function scrub(text: string | null | undefined): string {
  if (!text) return "";
  return text
    .replace(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, "[address]")
    .replace(/\+?\d[\d\s().-]{5,}\d/g, m => (m.replace(/\D/g, "").length >= 7 ? "[number]" : m))
    .replace(SPOKEN_NUMBER, "[number]");
}

/* Clock time in the viewer's zone, 24-hour: "14:32". */
export function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso); if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}
/* "2 min 05 s" for a duration in seconds. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return "";
  const s = Math.round(seconds); const m = Math.floor(s / 60); const r = s % 60;
  return m ? `${m} min ${String(r).padStart(2, "0")} s` : `${r} s`;
}

/* ---- section 3: phone calls ------------------------------------------------------------------------------ */
export type CallStatus = "queued" | "dialing" | "live" | "ended" | "voicemail" | "no_answer" | "failed" | "dry_run" | "capped" | "canceled" | string;
const LIVE = new Set(["dialing", "ringing", "live", "connected", "in_progress", "answered"]);
const WAITING = new Set(["queued", "sending", "scheduled"]);
export const isLiveCall = (c: { status: string }) => LIVE.has(c.status);
export const isQueuedCall = (c: { status: string }) => WAITING.has(c.status);
export const isOverCall = (c: { status: string }) => !LIVE.has(c.status) && !WAITING.has(c.status);
export interface CallLine { seq: number; party: "agent" | "person"; speaker: string | null; name: string; text: string; at: string | null }
export interface CallOption { id: string; label: string }
export interface CallFollowUp { type: string; cc: string[]; topic: string | null; details: string | null; status: string; ref: string | null }
export interface CallOutcome { result: string; decision: string | null; summary: string | null; chosenOptionId: string | null; followUps: CallFollowUp[]; interpretedBy: string | null }
export interface PhoneCall {
  id: string; purpose: string; caller: string; callerName: string; calleeRole: string; calleeName: string | null; siteId: string | null;
  goal: string | null; facts: string[]; options: CallOption[]; status: CallStatus;
  transcript: CallLine[]; actionItems: { seq: number; action: string; details: string | null }[]; outcome: CallOutcome | null;
  attempt: number | null; retryOf: string | null; refs: Record<string, string>; outboxId: string | null;
  queuedAt: string | null; startedAt: string | null; endedAt: string | null; durationSeconds: number | null; hangupReason: string | null; at: string;
}
const PURPOSE_WORD: Record<string, string> = {
  owner_compliance: "Compliance", contractor_schedule: "Booking the work", employee_attendance: "Attendance",
  counsel_followup: "Legal follow-up", callback: "Call back",
};
export const purposeWord = (p: string | null | undefined) => (p && PURPOSE_WORD[p]) || (p ? p.replace(/_/g, " ").replace(/^./, c => c.toUpperCase()) : "Call");
const STATUS_WORD: Record<string, string> = {
  queued: "Waiting to call", sending: "Waiting to call", dialing: "Ringing", ringing: "Ringing", live: "On the line", connected: "On the line",
  in_progress: "On the line", answered: "On the line", ended: "Ended", completed: "Ended", voicemail: "Message left", no_answer: "No answer",
  failed: "Failed", dry_run: "Not placed: live calling is off", capped: "Held: today's call limit reached", canceled: "Canceled",
};
export const callStatusWord = (s: string) => STATUS_WORD[s] ?? s.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const RESULT_WORD: Record<string, string> = { agreed: "Agreed", declined: "Declined", undecided: "No decision yet", voicemail: "Message left", no_answer: "No answer", failed: "Failed" };
export const resultWord = (r: string | null | undefined) => (r && RESULT_WORD[r]) || (r ? r.replace(/_/g, " ").replace(/^./, c => c.toUpperCase()) : "");

function normaliseLine(raw: unknown, i: number, callerName: string, calleeRole: string): CallLine {
  const o = obj(raw);
  const p = word(str(o.party ?? o.role ?? o.side ?? o.speakerType));
  /* Inkbox calls our side "local" and the person "remote". */
  const party: CallLine["party"] = /^(person|remote|human|callee|user|customer|contact)$/.test(p) || isPersonRole(str(o.speaker)) ? "person" : "agent";
  const speaker = str(o.speaker ?? o.agentId);
  const name = party === "person" ? roleWord(calleeRole) : (speaker && !isPersonRole(speaker) && speaker !== "agent" ? agentName(canonicalId(speaker)) : callerName);
  return { seq: num(o.seq) ?? i + 1, party, speaker, name, text: scrub(rn(str(o.text ?? o.content ?? o.utterance)) ?? ""), at: isoOf(o.at ?? o.ts ?? o.createdAt) };
}
function normaliseOutcome(raw: unknown): CallOutcome | null {
  if (!raw) return null;
  const o = obj(raw);
  if (!Object.keys(o).length) return typeof raw === "string" ? { result: "", decision: null, summary: rn(raw), chosenOptionId: null, followUps: [], interpretedBy: null } : null;
  return {
    result: word(str(o.result ?? o.status ?? o.outcome)), decision: scrub(rn(str(o.decision))) || null, summary: scrub(rn(str(o.summary))) || null,
    chosenOptionId: str(o.chosenOptionId ?? o.optionId ?? o.chosen),
    followUps: arr(o.followUps ?? o.follow_ups ?? o.actions).map(f => { const x = obj(f); return {
      type: word(str(x.type ?? x.kind)) || "note", cc: arr(x.cc).map(c => str(c) ?? str(obj(c).id) ?? "").filter(Boolean),
      topic: scrub(rn(str(x.topic))) || null, details: scrub(rn(str(x.details ?? x.text))) || null,
      status: word(str(x.status)) || "queued", ref: str(x.ref ?? x.outboxId ?? x.callId ?? x.windowId),
    }; }),
    interpretedBy: str(o.interpretedBy),
  };
}
export function normalisePhoneCall(raw: unknown): PhoneCall {
  const c = obj(raw);
  const caller = canonicalId(str(c.caller ?? c.agentId ?? c.from) ?? "dispatch");
  const callerName = rn(str(c.callerName)) ?? agentName(caller);
  const calleeRole = word(str(c.calleeRole ?? c.toRole ?? c.role)) || "owner";
  const options = arr(c.options).map((x, i) => { const o = obj(x); return { id: str(o.id) ?? `option-${i + 1}`, label: rn(str(o.label ?? o.text ?? o.name)) ?? str(o.id) ?? `Option ${i + 1}` }; });
  const refsRaw = obj(c.refs);
  const refs = Object.fromEntries(Object.entries(refsRaw).filter(([, v]) => typeof v === "string" && v)) as Record<string, string>;
  const transcript = arr(c.transcript ?? c.lines ?? c.turns).map((x, i) => normaliseLine(x, i, callerName, calleeRole)).sort((a, b) => a.seq - b.seq);
  const startedAt = isoOf(c.startedAt ?? c.started_at), endedAt = isoOf(c.endedAt ?? c.ended_at), queuedAt = isoOf(c.queuedAt ?? c.createdAt ?? c.enqueuedAt);
  return {
    id: str(c.id) ?? `call:${queuedAt ?? ""}`, purpose: word(str(c.purpose)) || "call", caller, callerName, calleeRole,
    calleeName: rn(str(c.calleeName)) ?? null, siteId: str(c.siteId ?? c.site), goal: scrub(rn(str(c.goal))) || null,
    facts: arr(c.facts).map(f => scrub(rn(str(f)) ?? "")).filter(Boolean), options, status: word(str(c.status)) || "queued",
    transcript, actionItems: arr(c.actionItems ?? c.post_call_action_items).map((x, i) => { const o = obj(x); return { seq: num(o.seq) ?? i + 1, action: scrub(rn(str(o.action)) ?? ""), details: scrub(rn(str(o.details))) || null }; }),
    outcome: normaliseOutcome(c.outcome), attempt: num(c.attempt), retryOf: str(c.retryOf), refs, outboxId: str(c.outboxId),
    queuedAt, startedAt, endedAt, durationSeconds: num(c.durationSeconds ?? c.duration_seconds), hangupReason: str(c.hangupReason),
    at: startedAt ?? queuedAt ?? endedAt ?? "",
  };
}
export const optionLabel = (c: PhoneCall, id: string | null | undefined) => (id ? c.options.find(o => o.id === id)?.label ?? null : null);

/* ---- section 2: the outbox ------------------------------------------------------------------------------- */
export interface OutboxItem {
  id: string; channel: "email" | "call" | "internal_email" | "sms" | string; purpose: string; sender: string | null; senderName: string;
  toRole: string | null; toAgent: string | null; cc: string[]; subject: string | null; preview: string | null; siteId: string | null;
  status: string; reason: string | null; enqueuedAt: string | null; notBefore: string | null; earliestAt: string | null; sentAt: string | null;
  attachments: { filename: string; contentType: string | null; size: number | null }[]; phoneCallId: string | null; refs: Record<string, string>; at: string;
}
export interface OutboxStatus {
  state: string | null; reason: string | null; nextEmailAt: string | null; nextCallAt: string | null; bootGraceUntil: string | null;
  emailsToday: number | null; callsToday: number | null; emailsPerDay: number | null; callsPerDay: number | null;
  queuedEmails: number | null; queuedCalls: number | null; emailGapSeconds: number | null; callGapSeconds: number | null;
  activeCallId: string | null; internalThisHour: number | null; internalPerHour: number | null;
}
const OUT_CHANNEL: Record<string, string> = { email: "email", mail: "email", call: "call", phone: "call", internal_email: "internal_email", internal: "internal_email", agent_email: "internal_email", sms: "sms", text: "sms" };
export function normaliseOutboxItem(raw: unknown): OutboxItem {
  const o = obj(raw);
  const sender = str(o.sender ?? o.from ?? o.agentId);
  const refsRaw = obj(o.refs);
  const channel = OUT_CHANNEL[word(str(o.channel))] ?? (word(str(o.channel)) || "email");
  const enqueuedAt = isoOf(o.enqueuedAt ?? o.createdAt ?? o.queuedAt), sentAt = isoOf(o.sentAt);
  return {
    id: str(o.id) ?? `outbox:${enqueuedAt ?? ""}`, channel, purpose: word(str(o.purpose)) || "", sender: sender ? canonicalId(sender) : null,
    senderName: rn(str(o.senderName)) ?? (sender ? agentName(canonicalId(sender)) : "Steward"),
    toRole: word(str(o.toRole ?? o.role)) || null,
    toAgent: str(o.toAgent ?? o.toAgentId) ? canonicalId(str(o.toAgent ?? o.toAgentId)!) : channel === "internal_email" ? agentOfAddress(str(o.to)) : null,
    cc: arr(o.cc).map(recipientWord), subject: scrub(rn(str(o.subject ?? o.title))) || null, preview: scrub(rn(str(o.preview ?? o.text ?? o.goal))) || null,
    siteId: str(o.siteId ?? o.site), status: word(str(o.status)) || "queued", reason: rn(str(o.reason)) ?? null,
    enqueuedAt, notBefore: isoOf(o.notBefore), earliestAt: isoOf(o.earliestAt ?? o.goesOutAt ?? o.nextAt), sentAt,
    attachments: arr(o.attachments).map(a => { const x = obj(a); return { filename: str(x.filename ?? x.name) ?? "attachment", contentType: str(x.contentType ?? x.content_type), size: num(x.size) }; }),
    phoneCallId: str(o.phoneCallId ?? o.callId), refs: Object.fromEntries(Object.entries(refsRaw).filter(([, v]) => typeof v === "string" && v)) as Record<string, string>,
    at: sentAt ?? enqueuedAt ?? "",
  };
}
/* The status may name its figures a few ways; the counts may sit under sentToday / caps / today. */
export function normaliseOutboxStatus(raw: unknown): OutboxStatus {
  const o = obj(raw); const today = obj(o.sentToday ?? o.today ?? o.counts); const caps = obj(o.caps ?? o.limits); const queued = obj(o.queued);
  const gaps = obj(o.gaps ?? o.pacing);
  const pick = (...vs: unknown[]) => { for (const v of vs) { const n = num(v); if (n !== null) return n; } return null; };
  return {
    state: str(o.state), reason: rn(str(o.reason)) ?? null,
    nextEmailAt: isoOf(o.nextEmailAt ?? obj(o.next).email ?? o.emailNextAt), nextCallAt: isoOf(o.nextCallAt ?? obj(o.next).call ?? o.callNextAt),
    bootGraceUntil: isoOf(o.bootGraceUntil ?? o.graceUntil),
    emailsToday: pick(today.emails, today.email, o.emailsToday, o.emailsSentToday), callsToday: pick(today.calls, today.call, o.callsToday, o.callsSentToday),
    emailsPerDay: pick(caps.emailsPerDay, caps.emails, caps.email, o.emailsPerDay), callsPerDay: pick(caps.callsPerDay, caps.calls, caps.call, o.callsPerDay),
    queuedEmails: pick(queued.emails, queued.email, o.queuedEmails), queuedCalls: pick(queued.calls, queued.call, o.queuedCalls),
    emailGapSeconds: pick(gaps.emailGapSeconds, gaps.email, o.emailGapSeconds), callGapSeconds: pick(gaps.callGapSeconds, gaps.call, o.callGapSeconds),
    activeCallId: str(o.activeCallId ?? obj(o.activeCall).id ?? (typeof o.activeCall === "string" ? o.activeCall : null)),
    internalThisHour: pick(obj(o.internal).thisHour, o.internalThisHour, o.internalEmailsThisHour), internalPerHour: pick(caps.internalPerHour, caps.internal, obj(o.internal).perHour, o.internalPerHour),
  };
}
const OUT_STATUS_WORD: Record<string, string> = {
  queued: "Waiting to go out", sending: "Going out now", sent: "Sent", dry_run: "Not sent: live messaging is off", capped: "Held: today's limit reached",
  failed: "Failed", canceled: "Canceled",
};
export const outboxStatusWord = (s: string) => OUT_STATUS_WORD[s] ?? s.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const OUT_CHANNEL_WORD: Record<string, string> = { email: "Email", call: "Call", internal_email: "Email between agents", sms: "Text" };
export const outboxChannelWord = (c: string) => OUT_CHANNEL_WORD[c] ?? c.replace(/_/g, " ");
const OUT_PURPOSE_WORD: Record<string, string> = {
  digest: "Compliance snapshot", owner_digest: "Compliance snapshot", agent_report: "Report", inspection: "Inspection", owner_email: "Inspection",
  counsel_to_contractor: "Legal requirements", contractor_confirmation: "Booking confirmation", booking: "Booking confirmation", attendance_recap: "Call recap",
  recap: "Call recap", evidence_to_manager: "Evidence", owner_compliance: "Compliance", contractor_schedule: "Booking the work", employee_attendance: "Attendance",
  counsel_followup: "Legal follow-up", callback: "Call back", email_file: "The file you asked for",
};
export const outboxPurposeWord = (p: string) => OUT_PURPOSE_WORD[p] ?? p.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
/* When it goes out: the outbox's own estimate, else its not-before time. */
export const goesOutAt = (i: OutboxItem) => i.earliestAt ?? i.notBefore;
/* "to you (owner), copying Compliance Counsel". */
export function outboxTo(i: OutboxItem): string {
  const to = i.toAgent ? agentName(i.toAgent) : i.channel === "internal_email" && !i.toRole ? "another agent" : roleWord(i.toRole);
  return `to ${to}${i.cc.length ? `, copying ${i.cc.join(", ")}` : ""}`;
}

/* ---- section 5: the badge log and the People Officer's cases --------------------------------------------- */
export type DayStatus = "on_time" | "late" | "absent" | "rest_day" | string;
export interface AttendanceEntry { date: string; shiftStart: string | null; shiftEnd: string | null; checkIn: string | null; checkOut: string | null; lateMinutes: number | null; status: DayStatus }
export interface AttendanceEmployee { crewId: string; name: string; role: string | null; shift: string | null; entries: AttendanceEntry[] }
export interface AttendanceCase {
  id: string; siteId: string | null; crewId: string | null; name: string; role: string | null; days: { date: string; checkIn: string | null; lateMinutes: number | null }[];
  status: string; conversationIds: string[]; callId: string | null; outcome: { result: string | null; decision: string | null; summary: string | null } | null;
  openedAt: string | null; resolvedAt: string | null;
}
export interface AttendanceLog { siteId: string; timezone: string | null; employees: AttendanceEmployee[]; cases: AttendanceCase[]; dates: string[] }
const dateOf = (v: unknown): string | null => { const s = str(v); if (!s) return null; const m = /^(\d{4}-\d{2}-\d{2})/.exec(s); return m ? m[1] : null; };
function normaliseEntry(raw: unknown): AttendanceEntry | null {
  const o = obj(raw); const date = dateOf(o.date ?? o.day ?? o.localDate);
  if (!date) return null;
  const late = num(o.lateMinutes ?? o.minutesLate ?? o.late);
  let status = word(str(o.status));
  if (!status) status = late && late > 0 ? "late" : o.checkIn ? "on_time" : "absent";
  if (status === "ontime" || status === "present") status = "on_time";
  if (status === "rest" || status === "off" || status === "day_off") status = "rest_day";
  return { date, shiftStart: str(o.shiftStart), shiftEnd: str(o.shiftEnd), checkIn: str(o.checkIn), checkOut: str(o.checkOut), lateMinutes: late, status };
}
export function normaliseCase(raw: unknown): AttendanceCase {
  const o = obj(raw); const out = o.outcome;
  const oo = obj(out);
  return {
    id: str(o.id) ?? `case:${str(o.crewId) ?? ""}:${str(o.openedAt) ?? ""}`, siteId: str(o.siteId ?? o.site), crewId: str(o.crewId ?? o.employeeId),
    name: rn(str(o.name)) ?? "An employee", role: rn(str(o.role)) ?? null,
    days: arr(o.days).map(d => { const x = obj(d); return { date: dateOf(x.date) ?? str(x.date) ?? "", checkIn: str(x.checkIn), lateMinutes: num(x.lateMinutes ?? x.minutesLate) }; }).filter(d => d.date),
    status: word(str(o.status)) || "open", conversationIds: arr(o.conversationIds).map(x => str(x) ?? "").filter(Boolean),
    callId: str(o.callId ?? o.phoneCallId),
    outcome: !out ? null : typeof out === "string" ? { result: null, decision: null, summary: scrub(rn(out)) } : { result: word(str(oo.result)) || null, decision: scrub(rn(str(oo.decision))) || null, summary: scrub(rn(str(oo.summary ?? oo.text))) || null },
    openedAt: isoOf(o.openedAt ?? o.createdAt), resolvedAt: isoOf(o.resolvedAt),
  };
}
/* The log nests entries per employee, or lists them flat with the employee's id; both read the same here. */
export function normaliseAttendance(raw: unknown, siteId: string): AttendanceLog {
  const o = obj(raw);
  const flat = arr(o.entries ?? o.log);
  const employees: AttendanceEmployee[] = arr(o.employees ?? o.roster ?? o.crew).map(e => {
    const x = obj(e); const crewId = str(x.crewId ?? x.id) ?? str(x.name) ?? "";
    const own = arr(x.entries ?? x.days ?? x.log).length ? arr(x.entries ?? x.days ?? x.log) : flat.filter(f => str(obj(f).crewId) === crewId);
    const shift = typeof x.shift === "string" ? x.shift : str(obj(x.shift).label) ?? ([str(obj(x.shift).start), str(obj(x.shift).end)].filter(Boolean).join(" to ") || null);
    return { crewId, name: rn(str(x.name)) ?? crewId, role: rn(str(x.role)) ?? null, shift: shift ? rn(shift) : null, entries: own.map(normaliseEntry).filter((y): y is AttendanceEntry => Boolean(y)) };
  });
  if (!employees.length && flat.length) {
    const by = new Map<string, AttendanceEmployee>();
    for (const f of flat) {
      const x = obj(f); const crewId = str(x.crewId) ?? str(x.name) ?? "?"; const e = normaliseEntry(f); if (!e) continue;
      const cur = by.get(crewId) ?? { crewId, name: rn(str(x.name)) ?? crewId, role: rn(str(x.role)) ?? null, shift: null, entries: [] };
      cur.entries.push(e); by.set(crewId, cur);
    }
    employees.push(...by.values());
  }
  const dates = [...new Set(employees.flatMap(e => e.entries.map(x => x.date)))].sort();
  return { siteId: str(o.siteId) ?? siteId, timezone: str(o.timezone ?? o.tz), employees, cases: arr(o.cases).map(normaliseCase), dates };
}
const CASE_WORD: Record<string, string> = { open: "Open", calling: "Calling now", resolved: "Resolved", unreachable: "Could not reach them", closed: "Resolved" };
export const caseStatusWord = (s: string) => CASE_WORD[s] ?? s.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());

/* ---- section 6: inspections ------------------------------------------------------------------------------ */
export interface InspectionFinding { assetTag: string | null; title: string; reasons: string[]; severity: string | null; obligationId: string | null; issueId: string | null }
export interface InspectionStepRefs { conversationId: string | null; outboxId: string | null; callId: string | null; windowId: string | null; issueId: string | null }
export interface InspectionStep { name: string; at: string | null; summary: string | null; status: string | null; refs: InspectionStepRefs }
export interface Inspection {
  id: string; siteId: string | null; inspectorId: string; state: string; stops: { assetTag: string; at: string | null }[];
  findings: InspectionFinding[]; primary: InspectionFinding | null; steps: InspectionStep[];
  conversationIds: string[]; outboxIds: string[]; callId: string | null; windowId: string | null; startedAt: string | null; finishedAt: string | null;
}
function normaliseFinding(raw: unknown): InspectionFinding {
  const o = obj(raw);
  return {
    assetTag: str(o.assetTag ?? o.tag), title: rn(str(o.title ?? o.summary ?? o.what)) ?? (str(o.assetTag) ? `${str(o.assetTag)}` : "Finding"),
    reasons: arr(o.reasons).map(r => rn(str(r)) ?? "").filter(Boolean), severity: str(o.severity), obligationId: str(o.obligationId), issueId: str(o.issueId),
  };
}
export function normaliseInspection(raw: unknown): Inspection {
  const o = obj(raw);
  const findings = arr(o.findings).map(normaliseFinding);
  const primaryRaw = o.primary;
  const primary = typeof primaryRaw === "string" ? findings.find(f => f.assetTag === primaryRaw || f.obligationId === primaryRaw || f.issueId === primaryRaw) ?? null
    : primaryRaw && typeof primaryRaw === "object" ? normaliseFinding(primaryRaw) : findings[0] ?? null;
  return {
    id: str(o.id) ?? `inspection:${str(o.startedAt) ?? ""}`, siteId: str(o.siteId ?? o.site), inspectorId: canonicalId(str(o.inspectorId ?? o.agentId) ?? "site-inspector"),
    state: word(str(o.state ?? o.status)) || "running",
    stops: arr(o.stops).map(s => { const x = obj(s); return { assetTag: str(x.assetTag ?? x.tag) ?? "", at: isoOf(x.at) }; }).filter(s => s.assetTag),
    findings, primary,
    steps: arr(o.steps).map(s => { const x = obj(s); const r = obj(x.refs); return {
      name: word(str(x.name ?? x.step)) || "step", at: isoOf(x.at), summary: rn(str(x.summary)) ?? null, status: word(str(x.status)) || null,
      refs: { conversationId: str(r.conversationId ?? x.conversationId), outboxId: str(r.outboxId ?? x.outboxId), callId: str(r.callId ?? r.phoneCallId ?? x.callId), windowId: str(r.windowId ?? x.windowId), issueId: str(r.issueId ?? x.issueId) },
    }; }),
    conversationIds: arr(o.conversationIds).map(x => str(x) ?? "").filter(Boolean), outboxIds: arr(o.outboxIds).map(x => str(x) ?? "").filter(Boolean),
    callId: str(o.callId ?? o.phoneCallId), windowId: str(o.windowId), startedAt: isoOf(o.startedAt ?? o.at), finishedAt: isoOf(o.finishedAt ?? o.endedAt),
  };
}
/* The chain, in order (section 6): which record each step points at comes from the step's refs, else the inspection's
   own lists in step order. */
export const CHAIN: { key: string; label: string; re: RegExp; kind: "chat" | "outbox" | "call" | "window" }[] = [
  { key: "report", label: "Report chat with the Compliance Officer", re: /report/, kind: "chat" },
  { key: "evidence_to_manager", label: "Evidence to the manager", re: /evidence|manager/, kind: "chat" },
  { key: "owner_email", label: "Email to you (owner), Compliance Counsel copied", re: /owner/, kind: "outbox" },
  { key: "counsel_to_contractor", label: "Compliance Counsel's email to you (contractor)", re: /counsel/, kind: "outbox" },
  { key: "contractor_call", label: "Call with you (contractor)", re: /call/, kind: "call" },
  { key: "booking", label: "Maintenance booked", re: /book|window|maintenance/, kind: "window" },
];
export interface ChainRow { key: string; label: string; kind: "chat" | "outbox" | "call" | "window"; step: InspectionStep | null; ref: string | null; extraRef: string | null }
export function chainOf(i: Inspection): ChainRow[] {
  const used = new Set<number>();
  return CHAIN.map((c, k) => {
    const idx = i.steps.findIndex((s, j) => !used.has(j) && (s.name === c.key || c.re.test(s.name)));
    if (idx >= 0) used.add(idx);
    const step = idx >= 0 ? i.steps[idx] : null;
    const r = step?.refs;
    let ref: string | null = null; let extraRef: string | null = null;
    /* Without step refs, the inspection's lists are read in chain order: chats [report, evidence], outbox items
       [evidence mail, owner email, counsel email, booking confirmation]. */
    if (c.kind === "chat") { ref = r?.conversationId ?? i.conversationIds[k] ?? null; if (c.key === "evidence_to_manager") extraRef = r?.outboxId ?? i.outboxIds[0] ?? null; }
    if (c.kind === "outbox") ref = r?.outboxId ?? i.outboxIds[c.key === "owner_email" ? 1 : 2] ?? null;
    if (c.kind === "call") ref = r?.callId ?? i.callId;
    if (c.kind === "window") { ref = r?.windowId ?? i.windowId; extraRef = r?.outboxId ?? i.outboxIds[3] ?? null; }
    return { key: c.key, label: c.label, kind: c.kind, step, ref, extraRef };
  });
}

/* ---- loaders ---------------------------------------------------------------------------------------------- */
export interface PhoneCallFilters { siteId?: string; active?: boolean; purpose?: string; limit?: number }
export interface OutboxFilters { status?: string; channel?: string; siteId?: string; limit?: number }
export const phoneCallsPath = (f: PhoneCallFilters = {}) => `/api/phone-calls${qs({ siteId: f.siteId, active: f.active === undefined ? undefined : String(f.active), purpose: f.purpose, limit: f.limit })}`;
export const outboxPath = (f: OutboxFilters = {}) => `/api/outbox${qs({ status: f.status, channel: f.channel, siteId: f.siteId, limit: f.limit })}`;
export const attendancePath = (siteId: string, days = 14) => `/api/attendance${qs({ siteId, days })}`;
export const casesPath = (siteId?: string, limit?: number) => `/api/attendance/cases${qs({ siteId, limit })}`;
export const inspectionsPath = (siteId?: string, limit?: number) => `/api/inspections${qs({ siteId, limit })}`;

export const api10 = {
  /* Newest first; an array or { calls | items: [...] }. */
  phoneCalls: async (f: PhoneCallFilters = {}) => list<unknown>(await request<unknown>(phoneCallsPath(f)), "calls", "phoneCalls", "items").map(normalisePhoneCall).sort(newest(c => c.at)),
  phoneCall: async (id: string) => { const r = obj(await request<unknown>(`/api/phone-calls/${enc(id)}`)); return normalisePhoneCall(r.call ?? r.phoneCall ?? r); },
  outbox: async (f: OutboxFilters = {}) => list<unknown>(await request<unknown>(outboxPath(f)), "items", "outbox").map(normaliseOutboxItem).sort(newest(i => i.at)),
  outboxStatus: async () => normaliseOutboxStatus(await request<unknown>("/api/outbox/status")),
  attendance: async (siteId: string, days = 14) => normaliseAttendance(await request<unknown>(attendancePath(siteId, days)), siteId),
  cases: async (siteId?: string, limit = 50) => list<unknown>(await request<unknown>(casesPath(siteId, limit)), "cases", "items").map(normaliseCase).sort(newest(c => c.openedAt)),
  inspections: async (siteId?: string, limit = 5) => list<unknown>(await request<unknown>(inspectionsPath(siteId, limit)), "inspections", "items").map(normaliseInspection).sort(newest(i => i.startedAt)),
};

/* ---- text for agents (agent mode): the same records as plain lines --------------------------------------- */
const line = (...parts: (string | null | undefined | false)[]) => parts.filter(Boolean).join(" ");
export function outboxText(items: OutboxItem[], s: OutboxStatus | null): string {
  const out = ["# Outbox"];
  if (s) {
    out.push(line("- next email from:", s.nextEmailAt ?? "now"), line("- next call from:", s.nextCallAt ?? "now"));
    if (s.emailsPerDay !== null || s.emailsToday !== null) out.push(`- emails today: ${s.emailsToday ?? 0} of ${s.emailsPerDay ?? "?"}`);
    if (s.callsPerDay !== null || s.callsToday !== null) out.push(`- calls today: ${s.callsToday ?? 0} of ${s.callsPerDay ?? "?"}`);
    if (s.bootGraceUntil) out.push(`- nothing goes out before: ${s.bootGraceUntil}`);
  }
  for (const i of items) {
    out.push(`- [${i.status}] ${outboxChannelWord(i.channel)} ${outboxTo(i)} from ${i.senderName}: ${i.subject ?? i.preview ?? outboxPurposeWord(i.purpose)}`
      + (i.status === "queued" && goesOutAt(i) ? ` (goes out at ${goesOutAt(i)})` : "") + (i.sentAt ? ` (sent ${i.sentAt})` : "") + (i.reason && i.status !== "sent" ? ` (${i.reason})` : "") + ` id=${i.id}`);
  }
  if (!items.length) out.push("- empty");
  return out.join("\n");
}
export function attendanceText(log: AttendanceLog, cases: AttendanceCase[]): string {
  const out = [`# Badge log · ${log.siteId}${log.timezone ? ` (${log.timezone})` : ""}`, `- days: ${log.dates[0] ?? "?"} to ${log.dates.at(-1) ?? "?"}`];
  for (const e of log.employees) {
    const lates = e.entries.filter(x => x.status === "late"); const absent = e.entries.filter(x => x.status === "absent");
    out.push(`## ${e.name}${e.role ? `, ${e.role}` : ""}${e.shift ? ` (${e.shift})` : ""}`);
    out.push(`- late: ${lates.length ? lates.map(x => `${x.date} +${x.lateMinutes ?? "?"} min`).join(", ") : "never"}`);
    if (absent.length) out.push(`- absent: ${absent.map(x => x.date).join(", ")}`);
  }
  out.push("# Cases");
  for (const c of cases) out.push(`- [${c.status}] ${c.name}${c.role ? `, ${c.role}` : ""}: late ${c.days.map(d => `${d.date} +${d.lateMinutes ?? "?"} min`).join(", ") || "—"}${c.outcome?.decision || c.outcome?.summary ? `; outcome: ${c.outcome.decision ?? c.outcome.summary}` : ""}${c.callId ? `; call ${c.callId}` : ""} id=${c.id}`);
  if (!cases.length) out.push("- none");
  return out.join("\n");
}
export function inspectionText(i: Inspection): string {
  const out = [`# Inspection ${i.id} · ${i.siteId ?? "?"}`, `- by: ${agentName(i.inspectorId)}`, `- state: ${i.state}`, `- started: ${i.startedAt ?? "?"}${i.finishedAt ? `, finished ${i.finishedAt}` : ""}`];
  if (i.stops.length) out.push(`- stops: ${i.stops.map(s => s.assetTag).join(", ")}`);
  if (i.primary) out.push(`- finding: ${i.primary.assetTag ? `${i.primary.assetTag}: ` : ""}${i.primary.title}${i.primary.reasons.length ? ` (${i.primary.reasons.join("; ")})` : ""}`);
  const also = i.findings.filter(f => f !== i.primary && !(i.primary && f.assetTag === i.primary.assetTag && f.title === i.primary.title));
  if (also.length) out.push(`- also noted: ${also.map(f => `${f.assetTag ? `${f.assetTag} ` : ""}${f.title}`).join("; ")}`);
  out.push("## Chain");
  for (const r of chainOf(i)) out.push(`- [${r.step ? "done" : "waiting"}] ${r.label}${r.step?.at ? ` at ${r.step.at}` : ""}${r.ref ? ` ref=${r.ref}` : ""}${r.step?.summary ? ` — ${r.step.summary}` : ""}`);
  return out.join("\n");
}
