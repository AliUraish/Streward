/**
 * The owner's notifications page in agent mode (owner, Oct 18 2026: "that page should have agent mode too, so an agent can
 * see what last things I got"): what the owner was last sent or prepared (owner alerts by email and call, the Operations
 * Director's compliance digest with its PDF, each agent's play report from its own mailbox, decision texts and duty-engineer
 * notices) and the main things that happened, plus the compliance snapshot behind the digest. Upstream bodies are parsed
 * leniently and normalised here; the owner's own address and phone are never passed on.
 */
import { z } from 'zod';
import type { PropertyId, RuntimeConfig } from './config.js';
import type { Backend } from './upstream.js';
import { WithText, type ToolFn } from './tooling.js';
import { list } from './factory.js';

type Json = Record<string, unknown>;
const ANY = z.unknown();
const obj = (value: unknown): Json => value && typeof value === 'object' && !Array.isArray(value) ? value as Json : {};
const str = (value: unknown): string | null => typeof value === 'string' && value.length ? value : typeof value === 'number' ? String(value) : null;
const num = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const LinksSchema = z.object({
  issueId: z.string().nullable(), conversationId: z.string().nullable(), alertId: z.string().nullable(), windowId: z.string().nullable(), patrolId: z.string().nullable(),
  digestId: z.string().nullable(), reportId: z.string().nullable(), obligationId: z.string().nullable(), decisionRequestId: z.string().nullable(),
});
const AttachmentSchema = z.object({ filename: z.string(), contentType: z.string().nullable(), size: z.number().nullable(), url: z.string().nullable() });
const NotificationSchema = z.object({
  id: z.string(), at: z.string().nullable(), kind: z.string(), channel: z.string(), mode: z.string(), title: z.string(), summary: z.string(),
  siteId: z.string().nullable(), siteName: z.string().nullable(), from: z.string().nullable(), fromAddress: z.string().nullable(), severity: z.string().nullable(),
  links: LinksSchema, attachments: z.array(AttachmentSchema),
});
const ScheduleSchema = z.object({
  live: z.boolean().nullable(), digestEveryHours: z.number().nullable(), digestsPerDay: z.number().nullable(), lastDigestAt: z.string().nullable(),
  nextDigestAt: z.string().nullable(), reportsPerDay: z.number().nullable(), reportsPerAgentPerDay: z.number().nullable(),
});
const FeedSchema = z.object({ notifications: z.array(NotificationSchema), total: z.number(), latestAt: z.string().nullable(), schedule: ScheduleSchema, nextStep: z.string() });

const RegulationRefSchema = z.object({ id: z.string(), cite: z.string().nullable(), title: z.string().nullable(), url: z.string().nullable(), linkOnly: z.boolean() });
const ObligationSchema = z.object({
  obligationId: z.string(), title: z.string(), assetTag: z.string().nullable(), status: z.string(), dueDate: z.string().nullable(), daysOverdue: z.number().nullable(),
  dueInDays: z.number().nullable(), blockedReason: z.string().nullable(), blockedBy: z.string().nullable(), owner: z.string().nullable(), regulations: z.array(RegulationRefSchema),
});
const SnapshotSiteSchema = z.object({
  siteId: z.string(), siteName: z.string().nullable(), compliancePct: z.number().nullable(),
  counts: z.object({ total: z.number().nullable(), compliant: z.number().nullable(), overdue: z.number().nullable(), blocked: z.number().nullable(), dueSoon: z.number().nullable(), openComplianceIssues: z.number().nullable() }),
  overdue: z.array(ObligationSchema), blocked: z.array(ObligationSchema), dueSoon: z.array(ObligationSchema),
  openComplianceIssues: z.array(z.object({ issueId: z.string(), kind: z.string().nullable(), severity: z.string().nullable(), assetTag: z.string().nullable(), summary: z.string().nullable() })),
  maintenance: z.array(z.object({ windowId: z.string(), when: z.string().nullable(), scope: z.string().nullable(), examiner: z.string().nullable(), status: z.string().nullable(), coordinatedWith: z.string().nullable() })),
  walkthrough: z.object({ patrolId: z.string(), finishedAt: z.string().nullable(), agentName: z.string().nullable(), checked: z.number().nullable(), bad: z.array(z.object({ assetTag: z.string().nullable(), reasons: z.array(z.string()), frameUrl: z.string().nullable() })) }).nullable(),
  agents: z.array(z.object({ agentId: z.string(), name: z.string().nullable(), status: z.string().nullable(), currentTask: z.string().nullable(), why: z.string().nullable(), waitingOn: z.string().nullable() })),
  conversations: z.array(z.object({ id: z.string().nullable(), kind: z.string().nullable(), headline: z.string(), participants: z.array(z.string()), at: z.string().nullable() })),
  changes: z.array(z.object({ at: z.string().nullable(), type: z.string().nullable(), summary: z.string() })),
});
const SnapshotSchema = z.object({
  at: z.string().nullable(), complianceLine: z.string().nullable(), sites: z.array(SnapshotSiteSchema), decisions: z.array(z.string()), changes: z.array(z.string()),
  changesSince: z.string().nullable(), attributions: z.array(z.string()), disclaimer: z.string().nullable(), pdfUrl: z.string(), nextStep: z.string(),
});

export interface OwnerDeps { tool: ToolFn; backend: Backend; config: RuntimeConfig; siteId: z.ZodType<PropertyId>; inScope(site: string): boolean }

const MODE_LABEL: Record<string, string> = { sent: 'sent', dry_run: 'prepared, not sent', capped: 'held by the daily limit', failed: 'failed', event: 'event' };

export function registerOwnerTools({ tool, backend, config, siteId, inScope }: OwnerDeps) {
  const absolute = (url: string | null) => !url ? null : /^https?:\/\//.test(url) ? url : url.startsWith('/') ? `${config.backendUrl}${url}` : url;
  const qs = (values: Record<string, string | undefined>) => { const query = new URLSearchParams(Object.entries(values).filter((entry): entry is [string, string] => Boolean(entry[1]))); return query.size ? `?${query}` : ''; };
  /** Every site this endpoint serves, as the backend's comma-separated siteId (empty when that is every site). */
  const scopeParam = () => config.allowedProperties.length < 3 ? config.allowedProperties.join(',') : undefined;

  const normaliseItem = (row: Json): z.infer<typeof NotificationSchema> => {
    const links = obj(row.links);
    return {
      id: str(row.id) ?? 'notification', at: str(row.at), kind: str(row.kind) ?? 'event', channel: str(row.channel) ?? 'dashboard', mode: str(row.mode) ?? 'event',
      title: str(row.title) ?? '', summary: str(row.summary) ?? '', siteId: str(row.siteId), siteName: str(row.siteName), from: str(row.from), fromAddress: str(row.fromAddress),
      severity: str(row.severity),
      links: { issueId: str(links.issueId), conversationId: str(links.conversationId), alertId: str(links.alertId), windowId: str(links.windowId), patrolId: str(links.patrolId),
               digestId: str(links.digestId), reportId: str(links.reportId), obligationId: str(links.obligationId), decisionRequestId: str(links.decisionRequestId) },
      attachments: list(row, 'attachments').map(file => ({ filename: str(file.filename) ?? 'file', contentType: str(file.contentType), size: num(file.size), url: absolute(str(file.url)) })),
    };
  };

  tool('get_owner_notifications', 'What the owner was last sent or prepared and what last happened, newest first: owner alerts (the compliance officer\'s email with the file and the evidence, and the dispatch line\'s call), the Operations Director\'s compliance digest with its PDF, each agent\'s play report from its own mailbox (sender name and address), decision texts and the duty engineer\'s notices, plus the main events (high-severity issues opened or resolved, compliance gaps raised or closed, maintenance booked or lined up with another site, walkthroughs that found something bad). Each item has when, kind, channel (email, call, sms, dashboard), mode (sent; dry_run = prepared but not sent; capped = held by the daily limit; failed; event), title, summary, site, links (issue, conversation, alert, window, walkthrough, digest, report) and attachment URLs. The owner\'s address and phone are never returned. Free, read-only, one request, ~150 tokens an item. NEXT: get_compliance_snapshot for the compliance picture behind the digest; get_issue or get_conversation to follow a link.',
    z.strictObject({
      limit: z.number().int().min(1).max(100).default(20).describe('How many of the newest items to return.'),
      siteId: siteId.optional().describe('Only one site\'s items (the cross-site digest is included for every site).'),
    }), FeedSchema, async ({ limit, siteId: site }) => {
      const raw = obj(await backend.json(`/api/owner/notifications${qs({ limit: String(Math.min(200, limit * 3)), siteId: site })}`, ANY));
      const rows = list(raw, 'items', 'notifications').map(normaliseItem).filter(row => !row.siteId || inScope(row.siteId)).slice(0, limit);
      const schedule = obj(raw.schedule); const digest = obj(schedule.digest); const reports = obj(schedule.reports);
      const data = {
        notifications: rows, total: num(raw.total) ?? rows.length, latestAt: rows[0]?.at ?? null,
        schedule: { live: typeof schedule.live === 'boolean' ? schedule.live : null, digestEveryHours: num(digest.everyHours), digestsPerDay: num(digest.perDay), lastDigestAt: str(digest.lastAt),
                    nextDigestAt: str(digest.nextScheduledAt), reportsPerDay: num(reports.perDay), reportsPerAgentPerDay: num(reports.perAgentPerDay) },
        nextStep: rows.length ? 'get_compliance_snapshot() for the full compliance picture; follow a link with get_issue(issueId) or get_conversation(conversationId).'
          : 'Nothing has been sent or prepared for the owner yet; get_compliance_snapshot() shows the current state.',
      };
      const lines = rows.map(row => `${row.at ?? '?'} · ${row.kind} · ${row.channel} · ${MODE_LABEL[row.mode] ?? row.mode} · ${row.siteName ?? 'all sites'}: ${row.title}${row.from ? ` (from ${row.from})` : ''}\n  ${row.summary}`);
      const live = data.schedule.live === null ? '' : data.schedule.live ? 'Owner email is live.' : 'Owner email is prepared only (not sent).';
      return new WithText(data, `${rows.length} of ${data.total} owner notifications, newest first. ${live}\n${lines.join('\n')}\nNEXT: ${data.nextStep}`);
    });

  const normaliseObligation = (row: Json): z.infer<typeof ObligationSchema> => ({
    obligationId: str(row.obligationId) ?? str(row.id) ?? 'obligation', title: str(row.title) ?? '', assetTag: str(row.assetTag), status: str(row.status) ?? 'unknown',
    dueDate: str(row.dueDate) ?? str(row.dueAt), daysOverdue: num(row.daysOverdue), dueInDays: num(row.dueInDays), blockedReason: str(row.blockedReason),
    blockedBy: str(row.blockedByTitle) ?? str(row.blockedBy), owner: str(obj(row.owner).label) ?? str(obj(row.owner).name),
    regulations: list(row, 'regulations').map(reg => ({ id: str(reg.id) ?? 'regulation', cite: str(reg.cite), title: str(reg.title), url: str(reg.url), linkOnly: reg.linkOnly === true })),
  });

  tool('get_compliance_snapshot', 'The compliance snapshot behind the owner\'s digest, as data, with the URL of its PDF (a black-and-white report of a few pages): per site the compliance percent; overdue, blocked (and what blocks it) and due-within-14-days obligations with due dates, owners and regulation citations (title and official link; Victorian legislation by title and link only); open compliance issues; upcoming maintenance and cross-site coordination; agent activity (each agent\'s task and why, the latest calls and messages, the latest changes, the latest walkthrough\'s findings); what needs the owner\'s decision and what changed since the last snapshot. Omit siteId for every site. Free, read-only, one request, ~2-4k tokens for three sites. NEXT: give the owner pdfUrl, explain_compliance_issue(issueId) for one gap, get_owner_notifications for what the owner was last sent.',
    z.strictObject({ siteId: siteId.optional().describe('One site; omit for every site this endpoint serves.') }), SnapshotSchema, async ({ siteId: site }) => {
      const raw = obj(await backend.json(`/api/compliance/snapshot${qs({ siteId: site ?? scopeParam() })}`, ANY));
      const sites = list(raw, 'sites').filter(row => inScope(str(row.siteId) ?? '')).map(row => {
        const counts = obj(row.counts); const walk = row.walkthrough && typeof row.walkthrough === 'object' ? obj(row.walkthrough) : null;
        return {
          siteId: str(row.siteId) ?? 'site', siteName: str(row.siteName), compliancePct: num(row.compliancePct),
          counts: { total: num(counts.total), compliant: num(counts.compliant), overdue: num(counts.overdue), blocked: num(counts.blocked), dueSoon: num(counts.dueSoon), openComplianceIssues: num(counts.openComplianceIssues) },
          overdue: list(row, 'overdue').map(normaliseObligation), blocked: list(row, 'blocked').map(normaliseObligation), dueSoon: list(row, 'dueSoon').map(normaliseObligation),
          openComplianceIssues: list(row, 'openComplianceIssues').map(issue => ({ issueId: str(issue.issueId) ?? str(issue.id) ?? 'issue', kind: str(issue.kind), severity: str(issue.severity), assetTag: str(issue.assetTag), summary: str(issue.summary) })),
          maintenance: list(row, 'maintenance').map(window => {
            const coordination = obj(window.coordination);
            return { windowId: str(window.windowId) ?? str(window.id) ?? 'window', when: str(window.localStart) ?? str(window.date), scope: str(window.scope), examiner: str(window.examiner), status: str(window.status),
                     coordinatedWith: str(coordination.siteName) ?? str(coordination.siteId) ?? (strings(window.sharedWith)[0] ?? null) };
          }),
          walkthrough: walk ? { patrolId: str(walk.patrolId) ?? 'walk', finishedAt: str(walk.finishedAt), agentName: str(walk.agentName), checked: num(walk.checked),
                                bad: list(walk, 'bad').map(label => ({ assetTag: str(label.assetTag), reasons: strings(label.reasons), frameUrl: absolute(str(label.frameUrl)) })) } : null,
          agents: list(row, 'agents').map(agent => ({ agentId: str(agent.agentId) ?? 'agent', name: str(agent.name), status: str(agent.status), currentTask: str(agent.currentTask), why: str(agent.why), waitingOn: str(agent.waitingOn) })),
          conversations: list(row, 'conversations').map(item => ({ id: str(item.id), kind: str(item.kind), headline: str(item.headline) ?? '', participants: strings(item.participants), at: str(item.at) })),
          changes: list(row, 'changes').map(change => ({ at: str(change.at), type: str(change.type), summary: str(change.summary) ?? '' })),
        };
      });
      const changes = obj(raw.changes);
      const pdfUrl = absolute(str(raw.pdfUrl) ?? `/api/compliance/snapshot.pdf${qs({ siteId: site ?? scopeParam() })}`) ?? '';
      const gaps = sites.reduce((sum, row) => sum + row.overdue.length + row.blocked.length, 0);
      return {
        at: str(raw.at), complianceLine: str(raw.complianceLine), sites, decisions: list(raw, 'decisions').map(item => str(item.text) ?? '').filter(Boolean),
        changes: strings(changes.lines), changesSince: str(changes.since), attributions: strings(raw.attributions), disclaimer: str(raw.disclaimer), pdfUrl,
        nextStep: gaps ? `${gaps} overdue or blocked obligation${gaps === 1 ? '' : 's'}: explain_compliance_issue(issueId) for one of openComplianceIssues; the owner's PDF is at pdfUrl.` : 'Every obligation is current; the owner\'s PDF is at pdfUrl.',
      };
    });
}
