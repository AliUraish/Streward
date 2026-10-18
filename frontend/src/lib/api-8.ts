/* The owner's notifications: what Steward last sent the owner (email, call, text) and what last happened at the sites,
   newest first (GET /api/owner/notifications); the same feed as Markdown for agents (?format=md); the compliance
   snapshot PDF (GET /api/compliance/snapshot.pdf); and the digest the operator prepares now (POST /api/owner/digest),
   which lands in the feed with its PDF attached. Field names follow the brief; obvious alternatives are accepted so a
   partial backend still renders. Every loader throws the ApiError of api.ts, so a 404 reads as "not available yet"
   through useRemote's readiness. */
import { ApiError, actorHeaders, request } from "./api";
import { list } from "./api-3";
import { rn } from "./sites-3";

export type NotificationChannel = "email" | "call" | "sms" | "dashboard";
export type NotificationMode = "sent" | "queued" | "dry_run" | "capped" | "failed" | "event";
/* Contract 8 adds the phone call, the outbox item, the inspection and the attendance case an item comes from. */
export interface NotificationLinks {
  issueId: string | null; conversationId: string | null; alertId: string | null; windowId: string | null; patrolId: string | null;
  phoneCallId: string | null; outboxId: string | null; inspectionId: string | null; caseId: string | null;
}
export interface NotificationAttachment { filename: string; contentType: string | null; size: number | null; url: string | null }
export interface OwnerNotification {
  id: string; at: string; kind: string;
  channel: NotificationChannel | string; mode: NotificationMode | string;
  title: string; summary: string | null; reason: string | null; siteId: string | null;
  /* The asset an issue sits on, when the record names it (it is not one of the links). */
  assetTag: string | null;
  links: NotificationLinks; attachments: NotificationAttachment[];
  /* A queued item's time to go out (contract 8 outbox), when the feed gives one. */
  goesOutAt: string | null;
}
export interface NotificationFilters { limit?: number; since?: string; siteId?: string; kind?: string }
export interface SnapshotFile { blob: Blob; filename: string }

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const obj = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? v as Raw : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => typeof v === "string" && v.trim() ? v.trim() : typeof v === "number" && Number.isFinite(v) ? String(v) : null;
const num = (v: unknown): number | null => typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)) ? Number(v) : null;
/* An ISO time, or epoch seconds or milliseconds turned into one. */
const isoOf = (v: unknown): string | null => typeof v === "number" && Number.isFinite(v) ? new Date(v < 1e12 ? v * 1000 : v).toISOString() : str(v);
const word = (v: string | null) => (v ?? "").toLowerCase().replace(/[\s-]+/g, "_");
const qs = (values: Record<string, string | number | undefined | null>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  return q.size ? `?${q}` : "";
};

const CHANNEL: Record<string, NotificationChannel> = {
  email: "email", mail: "email", e_mail: "email", call: "call", phone: "call", voice: "call",
  sms: "sms", text: "sms", texts: "sms", dashboard: "dashboard", web: "dashboard", app: "dashboard", feed: "dashboard",
};
const MODE: Record<string, NotificationMode> = {
  sent: "sent", delivered: "sent", queued: "queued", sending: "queued", waiting: "queued", dry_run: "dry_run", dryrun: "dry_run", dry: "dry_run", capped: "capped", held: "capped",
  rate_limited: "capped", failed: "failed", failure: "failed", error: "failed", event: "event", info: "event", none: "event",
};

/* Files the backend links on its own host go through the dashboard's /api proxy instead. */
function localUrl(u: string | null): string | null {
  if (!u) return null;
  const m = /^https?:\/\/(?:127\.0\.0\.1|localhost|0\.0\.0\.0)(?::\d+)?(\/api\/.*)$/i.exec(u);
  return m ? m[1] : u;
}
function normaliseAttachment(raw: unknown): NotificationAttachment {
  const a = obj(raw);
  return {
    filename: str(a.filename ?? a.name) ?? "attachment", contentType: str(a.contentType ?? a.content_type ?? a.mimeType),
    size: num(a.size ?? a.bytes), url: localUrl(str(a.url ?? a.href ?? a.downloadUrl ?? a.fileUrl)),
  };
}
export const isPdf = (a: NotificationAttachment) => /pdf/i.test(a.contentType ?? "") || /\.pdf$/i.test(a.filename) || /\.pdf(?:[?#]|$)/i.test(a.url ?? "");

/* The kind as a word ("owner_alert" reads "Alert"); records keep provenance words for the audit trail, the page does not. */
const KIND_WORD: Record<string, string> = {
  digest: "Digest", owner_digest: "Digest", snapshot: "Snapshot", compliance_snapshot: "Snapshot",
  owner_alert: "Alert", alert: "Alert", compliance_alert: "Alert", call: "Call", owner_call: "Call", phone_call: "Call", sms: "Text", text: "Text", email: "Email",
  inspection: "Inspection", attendance: "Attendance", attendance_case: "Attendance", agent_report: "Report", report: "Report",
  issue: "Issue", issue_opened: "Issue", issue_resolved: "Issue resolved", maintenance: "Maintenance", maintenance_window: "Maintenance",
  window: "Maintenance", patrol: "Walkthrough", walkthrough: "Walkthrough", label: "Label", conversation: "Conversation",
  meeting: "Meeting", message: "Message", fix: "Fix", fix_workflow: "Fix", event: "Event",
};
const RECORD_WORDS = /\b(?:synthetic|simulated|simulation|seeded|seed|generated|demo|scenario|sample)\b/gi;
export function kindWord(kind: string): string {
  const k = word(kind);
  const w = KIND_WORD[k] ?? k.replace(/_/g, " ").replace(RECORD_WORDS, "").replace(/\s{2,}/g, " ").trim();
  return w ? w.charAt(0).toUpperCase() + w.slice(1) : "Event";
}

export function normaliseNotification(raw: unknown, fallbackKind = "event"): OwnerNotification {
  const o = obj(raw); const l = obj(o.links); const e = obj(o.email); const d = obj(o.delivery);
  const kind = word(str(o.kind ?? o.type)) || fallbackKind;
  const ch = word(str(o.channel ?? o.via ?? d.channel)) || (o.email ? "email" : o.call ? "call" : o.sms ? "sms" : "dashboard");
  const md = word(str(o.mode ?? d.mode ?? e.mode ?? o.status ?? d.status));
  const at = isoOf(o.at ?? o.createdAt ?? o.sentAt ?? o.time) ?? "";
  const title = rn(str(o.title ?? o.subject ?? e.subject)) ?? kindWord(kind);
  const files = arr(o.attachments).length ? arr(o.attachments) : arr(e.attachments).length ? arr(e.attachments) : arr(o.files);
  return {
    id: str(o.id ?? o.notificationId) ?? `${kind}:${at}:${title}`, at, kind,
    channel: CHANNEL[ch] ?? ch, mode: MODE[md] ?? (md || "event"), title,
    summary: rn(str(o.summary ?? o.text ?? o.body ?? o.message)),
    reason: rn(str(o.reason ?? o.error ?? d.reason ?? e.reason ?? o.failure)),
    siteId: str(o.siteId ?? o.site_id ?? o.site), assetTag: str(l.assetTag ?? o.assetTag),
    links: {
      issueId: str(l.issueId ?? o.issueId), conversationId: str(l.conversationId ?? o.conversationId),
      alertId: str(l.alertId ?? o.alertId), windowId: str(l.windowId ?? l.maintenanceId ?? o.windowId),
      patrolId: str(l.patrolId ?? l.walkthroughId ?? o.patrolId),
      phoneCallId: str(l.phoneCallId ?? l.callId ?? o.phoneCallId ?? o.callId), outboxId: str(l.outboxId ?? o.outboxId),
      inspectionId: str(l.inspectionId ?? o.inspectionId), caseId: str(l.caseId ?? l.attendanceCaseId ?? o.caseId),
    },
    attachments: files.map(normaliseAttachment),
    goesOutAt: isoOf(o.earliestAt ?? o.goesOutAt ?? o.notBefore ?? d.earliestAt),
  };
}
const time = (iso: string) => { const t = Date.parse(iso); return Number.isNaN(t) ? 0 : t; };
export const newestFirst = (a: OwnerNotification, b: OwnerNotification) => time(b.at) - time(a.at);

/* One compact JSON object per item: the feed's fields, empty ones left out. */
export function jsonLine(n: OwnerNotification): string {
  const out: Record<string, unknown> = { id: n.id, at: n.at, kind: n.kind, channel: n.channel, mode: n.mode, title: n.title };
  if (n.summary) out.summary = n.summary;
  if (n.reason) out.reason = n.reason;
  if (n.siteId) out.siteId = n.siteId;
  const links = Object.fromEntries(Object.entries(n.links).filter(([, v]) => v));
  if (Object.keys(links).length) out.links = links;
  if (n.attachments.length) out.attachments = n.attachments.map(a => Object.fromEntries(Object.entries(a).filter(([, v]) => v !== null && v !== "")));
  return JSON.stringify(out);
}
/* The Markdown as the agent reads it, each line's words cleaned as everywhere else (rn); indentation, link targets,
   code spans and URLs are kept exactly. */
export function cleanMarkdown(md: string): string {
  return md.replace(/\r\n?/g, "\n").split("\n").map(line => {
    const m = /^(\s*)(.*)$/.exec(line); if (!m || !m[2]) return line;
    const keep: string[] = [];
    const masked = m[2].replace(/\]\([^)\s]*\)|`[^`]*`|https?:\/\/\S+/g, x => { keep.push(x); return `\u0000${keep.length - 1}\u0000`; });
    return m[1] + (rn(masked) ?? "").replace(/\u0000(\d+)\u0000/g, (_x, i) => keep[Number(i)] ?? "");
  }).join("\n");
}

async function errorOf(response: Response): Promise<ApiError> {
  let detail = `Request failed (${response.status})`; let code: string | undefined; let recovery: string | undefined;
  try { const body = await response.json(); detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body); code = body.code; recovery = body.recovery; } catch { /* not JSON */ }
  return new ApiError(detail, response.status, code, recovery);
}
function filenameOf(disposition: string | null): string | null {
  if (!disposition) return null;
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(disposition);
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition);
  const raw = (star?.[1] ?? plain?.[1] ?? "").trim().replace(/^"|"$/g, "");
  if (!raw) return null;
  try { return decodeURIComponent(raw); } catch { return raw; }
}

export const feedPath = (f: NotificationFilters = {}, format?: "md") => `/api/owner/notifications${qs({ format, limit: f.limit, since: f.since, siteId: f.siteId, kind: f.kind })}`;
export const snapshotPath = (siteId?: string) => `/api/compliance/snapshot.pdf${qs({ siteId })}`;
export const NOTIFICATION_TOOLS = ["get_owner_notifications", "get_compliance_snapshot"] as const;

export const api8 = {
  /* Newest first; an array or { items | notifications: [...] }. */
  notifications: async (f: NotificationFilters = {}) => list<unknown>(await request<unknown>(feedPath(f)), "notifications", "items")
    .map(x => normaliseNotification(x)).sort(newestFirst),
  /* The same feed as Markdown, as text (a JSON wrapper with a markdown field is read too). */
  markdown: async (f: NotificationFilters = {}): Promise<string> => {
    const response = await fetch(feedPath(f, "md"), { cache: "no-store", headers: { Accept: "text/markdown, text/plain;q=0.9, */*;q=0.5" } });
    if (!response.ok) throw await errorOf(response);
    if (/json/i.test(response.headers.get("content-type") ?? "")) {
      const body = obj(await response.json());
      const text = [body.markdown, body.md, body.text, body.content].find(v => typeof v === "string");
      return typeof text === "string" ? text : "";
    }
    return response.text();
  },
  /* The compliance snapshot PDF, all sites unless one is named. */
  snapshot: async (siteId?: string): Promise<SnapshotFile> => {
    const response = await fetch(snapshotPath(siteId), { cache: "no-store", headers: { Accept: "application/pdf" } });
    if (!response.ok) throw await errorOf(response);
    const blob = await response.blob();
    if (/json|html/i.test(blob.type)) throw new Error("No PDF came back");
    const day = new Date().toISOString().slice(0, 10);
    return { blob, filename: filenameOf(response.headers.get("content-disposition")) ?? `compliance-snapshot-${siteId || "all-sites"}-${day}.pdf` };
  },
  /* The operator's "send me a snapshot now": the digest comes back as the feed item it becomes. */
  digest: async (siteId?: string): Promise<OwnerNotification> => {
    const res = await request<unknown>("/api/owner/digest", { method: "POST", body: JSON.stringify(siteId ? { siteId } : {}), headers: actorHeaders("operator") });
    const o = obj(res);
    const raw = [o.notification, o.item, o.digest, arr(o.items)[0], arr(o.notifications)[0]].find(v => v && typeof v === "object" && !Array.isArray(v)) ?? res;
    const n = normaliseNotification(raw, "digest");
    const at = n.at || new Date().toISOString();
    return { ...n, at, id: str(obj(raw).id ?? obj(raw).notificationId) ? n.id : `digest:${at}` };
  },
};
