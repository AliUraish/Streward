"use client";

/* /app, the portfolio: both factories side by side, the two-site averages, what is happening at each right now,
   and the scenario demo control. */
import Link from "next/link";
import { useMemo, useState } from "react";
import type { Remote } from "@/lib/reality";
import { api3 } from "@/lib/api-3";
import { useConversations, useMetricsSummary, usePoll, useScenarios } from "@/lib/hooks-3";
import { AGENTS3, SCENARIOS3, SITES3, agentName, rn, scenarioTitle, site3, type Site3 } from "@/lib/sites-3";
import type { AgentInfo } from "@/lib/types-2";
import type { Conversation, Overview, Scenario, ScenarioRun, SiteOverview, SiteSummary } from "@/lib/types-3";
import { Kpis } from "./kpis";
import { useShared } from "./shell";
import { Btn, DemoTag, NotYet, PageHead, Reveal, SynthTag, ago, errorText, n, useToast } from "./ui3";

export default function PortfolioPage() {
  const { overview, agents } = useShared();
  const summary = useMetricsSummary();
  const conversations = useConversations();
  const active = overview.data?.activeScenario ?? null;
  const average = summary.data?.average ?? averageOf(summary.data?.sites ?? []);
  return <div className="page3">
    <PageHead id="portfolio" title="Portfolio" sub="The Myer Plant Room in Melbourne and the Bristol Dock Pump House in England: two teams, one Operations Director, one record." />
    <Reveal as="section" className="p3 avg3" aria-labelledby="avg-h">
      <div className="p-head"><h2 id="avg-h">Both factories</h2><span className="meta">two-site averages{summary.data?.synthetic ? ", synthetic metrics" : ""}</span></div>
      <Kpis s={average} remote={summary as Remote<unknown>} />
    </Reveal>
    <div className="tiles3">
      {SITES3.map((s, i) => <FactoryTile key={s.id} site={s} i={i} sum={summary.data?.sites.find(x => x.siteId === s.id) ?? null} summary={summary as Remote<unknown>} ov={overview.data?.sites.find(x => x.siteId === s.id) ?? null} overview={overview} active={active && active.siteId === s.id ? active : null} />)}
    </div>
    <NowBoard overview={overview} agents={agents} conversations={conversations.data ?? []} />
    <Scenarios active={active} onStarted={overview.reload} />
  </div>;
}

function averageOf(sites: SiteSummary[]): SiteSummary | null {
  if (sites.length < 2) return null;
  const avg = (k: keyof SiteSummary) => { const v = sites.map(s => s[k]).filter((x): x is number => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const sum = (k: keyof SiteSummary) => { const v = sites.map(s => s[k]).filter((x): x is number => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) : null; };
  return { siteId: "average", avgPressure: avg("avgPressure"), avgFlow: avg("avgFlow"), uptimePct: avg("uptimePct"), openIssues: sum("openIssues"), compliancePct: avg("compliancePct"), crewOnShift: sum("crewOnShift"), agentActionsToday: sum("agentActionsToday") };
}

function FactoryTile({ site, sum, summary, ov, overview, active, i }: { site: Site3; sum: SiteSummary | null; summary: Remote<unknown>; ov: SiteOverview | null; overview: Remote<Overview>; active: ScenarioRun | null; i: number }) {
  /* Until the overview answers, the severity counts come straight from the site's issues. */
  const fromIssues = usePoll(() => ov ? Promise.resolve(null) : api3.issues(site.id), [site.id, Boolean(ov)], 10_000);
  const counts = ov?.issues ?? (fromIssues.data ? fromIssues.data.filter(x => !x.status || !["resolved", "closed"].includes(x.status)).reduce((m, x) => ({ ...m, [x.severity]: (m[x.severity] ?? 0) + 1 }), { high: 0, medium: 0, low: 0 } as Record<string, number>) : null);
  const c = ov?.compliance;
  return <Reveal as="article" className="tile3" i={i}>
    <Link href={`/app/${site.id}`} className="thumb" aria-label={`Open ${site.name}`}>
      <img src={site.thumbnailUrl} alt={`${site.name}, thumbnail of the SuperSplat capture`} width={960} height={540} loading="lazy" />
    </Link>
    <div className="tile-body">
      <div className="tile-head">
        <div><h2>{site.name}</h2><p className="place">{site.place}</p></div>
        <Link className="b3 small quiet" href={`/app/${site.id}`}><span>Open factory</span><span className="arrow" aria-hidden="true">→</span></Link>
      </div>
      {active ? <p className="active-run"><span className="sig bad" aria-hidden="true" />Scenario running: {scenarioTitle(active.scenarioId)}{active.steps ? `, step ${active.step ?? 0} of ${active.steps}` : ""}<SynthTag rec={active} /></p> : null}
      <Kpis s={sum} remote={summary} compact only={["avgPressure", "avgFlow", "uptimePct", "compliancePct", "agentActionsToday"]} />
      <dl className="stats3">
        <div className="stat">
          <dt>Open issues</dt>
          <dd>{counts ? <span className="sev-row">
            <span className={`fig ${counts.high ? "bad" : ""}`}>{counts.high}<small>high</small></span>
            <span className="fig">{counts.medium}<small>medium</small></span>
            <span className="fig dim">{counts.low}<small>low</small></span>
          </span> : <NotYet remote={ov ? overview : fromIssues} what="issue counts" />}</dd>
        </div>
        <div className="stat">
          <dt>Obligations</dt>
          <dd>{c ? <span className="comp-row">
            <span><span className="sig ok" aria-hidden="true" />{c.ok} ok</span>
            <span><span className="sig warn" aria-hidden="true" />{c.due_soon} due soon</span>
            <span className={c.overdue ? "bad" : ""}><span className={`sig ${c.overdue ? "bad" : "off"}`} aria-hidden="true" />{c.overdue} overdue</span>
            <span className={c.blocked ? "bad" : ""}><span className={`sig ${c.blocked ? "bad" : "off"}`} aria-hidden="true" />{c.blocked} blocked</span>
          </span> : <NotYet remote={overview} what="compliance" />}</dd>
        </div>
        <div className="stat">
          <dt>Crew on shift</dt>
          <dd>{ov ? <span className="fig">{typeof ov.crewOnShift === "number" ? ov.crewOnShift : ov.crewOnShift.count}</span> : sum?.crewOnShift != null ? <span className="fig">{sum.crewOnShift}</span> : <NotYet remote={overview} what="crew" />}</dd>
        </div>
      </dl>
      <p className="credit3">{site.sceneTitle}, captured by {site.author} on SuperSplat. <a className="lnk" href={site.sceneUrl} target="_blank" rel="noreferrer">superspl.at/scene/{site.splatId}</a></p>
    </div>
  </Reveal>;
}

/* What is happening right now: the director and the owner's agent, then each factory's team, changes and calls. */
function NowBoard({ overview, agents, conversations }: { overview: Remote<Overview>; agents: Remote<AgentInfo[]>; conversations: Conversation[] }) {
  const rows = useNowRows(overview, agents);
  const changes = overview.data?.changes ?? [];
  const known = rows.some(r => r.known);
  return <Reveal as="section" className="now3" i={1} aria-labelledby="now-h">
    <div className="now-head"><h2 id="now-h">Right now</h2>{known ? <span className="meta">live, every 3 s</span> : <NotYet remote={overview.readiness === "ready" ? agents as Remote<unknown> : overview as Remote<unknown>} what="agent status" />}</div>
    <ol className="now-top">{rows.filter(r => !r.siteId).map(r => <NowCell key={r.id} r={r} />)}</ol>
    <div className="now-sites">
      {SITES3.map(s => {
        const mine = changes.filter(c => (c.siteId ?? "").startsWith(s.id.slice(0, 2)) || (c as { site?: string }).site === s.id.slice(0, 2)).slice(0, 4);
        const call = conversations.find(c => c.siteIds.includes(s.id));
        return <div className="now-site" key={s.id}>
          <h3><Link href={`/app/${s.id}`} className="lnk-plain">{s.name}</Link></h3>
          <ol className="now-strip">{rows.filter(r => r.siteId === s.id).map(r => <NowCell key={r.id} r={r} />)}</ol>
          <div className="now-feed">
            {call ? <p className="call"><strong>{call.kind === "meeting" ? "Meeting" : call.kind === "call" ? "Call" : "Message"}:</strong> {call.summary?.headline ?? call.title ?? "conversation"} <span className="r3">{ago(call.startedAt)}</span> <Link className="lnk" href={`/app/conversations?id=${encodeURIComponent(call.id)}`}>Read</Link></p> : null}
            {mine.length ? <ul className="rows3 plain changes">{mine.map((c, i) => <li key={`${c.at}-${i}`}><span className="r2">{rn(c.summary ?? "")}</span><span className="r3">{c.type ? c.type.replace(/_/g, " ") : ""}{c.at ? `, ${c.at.length <= 8 ? c.at : ago(c.at)}` : ""}</span></li>)}</ul> : <p className="st3 empty">{overview.readiness === "ready" ? "No changes in the last few minutes." : "Changes appear here once the overview answers."}</p>}
          </div>
        </div>;
      })}
    </div>
  </Reveal>;
}
export interface NowRow { id: string; name: string; level: number; siteId?: string; status: string | null; task: string | null; why: string | null; waitingOn: string | null; since: string | null; known: boolean }
export function useNowRows(overview: Remote<Overview>, agents: Remote<AgentInfo[]>): NowRow[] {
  return useMemo(() => {
    const fromOverview = overview.data?.agents ?? [];
    const fromList = agents.data ?? [];
    return AGENTS3.map(a => {
      const o = fromOverview.find(x => x.agentId === a.id);
      const l = fromList.find(x => x.id === a.id);
      return { id: a.id, name: a.name, level: a.level, siteId: a.siteId, status: o?.status ?? l?.status ?? null, task: o?.currentTask ?? l?.currentTask ?? null, why: o?.why ?? l?.why ?? null, waitingOn: o?.waitingOn ?? l?.waitingOn ?? null, since: o?.since ?? l?.lastActivityAt ?? null, known: Boolean(o || l) };
    });
  }, [overview.data, agents.data]);
}
export function NowCell({ r }: { r: NowRow }) {
  const [prev, setPrev] = useState(r.task);
  const [flash, setFlash] = useState(0);
  if (prev !== r.task) { setPrev(r.task); setFlash(f => f + 1); }
  const status = r.status ?? (r.known ? "idle" : "unknown");
  return <li className="now-cell" data-status={status}>
    {flash ? <span className="flash" key={flash} aria-hidden="true" /> : null}
    <span className="who"><span className={`sig ${status === "working" ? "ok" : status === "waiting" ? "warn" : "off"}`} aria-hidden="true" />{r.name}</span>
    <span className="task" key={r.task ?? "none"}>{r.task ?? (r.known ? "No task" : "Status not available yet")}</span>
    {r.why ? <span className="why">Why: {r.why}</span> : null}
    {r.waitingOn ? <span className="wait">Waiting on {r.waitingOn}</span> : null}
    <span className="since">{status}{r.since ? `, ${ago(r.since)}` : ""}</span>
  </li>;
}

function Scenarios({ active, onStarted }: { active: ScenarioRun | null; onStarted: () => void }) {
  const remote = useScenarios();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const list: Scenario[] = remote.data?.length ? remote.data : SCENARIOS3;
  async function start(s: Scenario) {
    setBusy(s.id); setError("");
    try { await api3.startScenario(s.id); toast(`Scenario started: ${rn(s.title)}`); onStarted(); remote.reload(); }
    catch (e) { setError(`${rn(s.title)}: ${errorText(e)}`); }
    finally { setBusy(null); }
  }
  return <Reveal as="section" className="scen3" i={2} aria-labelledby="scen-h">
    <div className="scen-head">
      <div><h2 id="scen-h">Start scenario</h2><p>Nothing fires until a scenario is started here or with start_scenario over MCP. Every scenario is a synthetic script.</p></div>
      <DemoTag />
    </div>
    {remote.readiness !== "ready" ? <p className="note3">{remote.readiness === "loading" ? "Listing scenarios." : <>The scenario list endpoint is not available yet; showing the scenarios agreed in the contracts. <button type="button" className="retry" onClick={remote.reload}>Retry</button></>}</p> : null}
    {error ? <p className="err3" role="alert">{error}</p> : null}
    <ul className="scen-list">{list.map(s => {
      const running = active?.scenarioId === s.id && active.state === "running";
      return <li key={s.id} className={running ? "running" : ""}>
        <div className="what"><span className="title">{rn(s.title)}{s.headline ? <span className="tg">headline</span> : null}<SynthTag rec={s} always /></span><span className="sum">{rn(s.summary)}</span></div>
        <span className="where">{s.siteId ? site3(s.siteId).short : "Both"}</span>
        <span className="owners">{s.owners.map(o => agentName(o)).join(", ")}</span>
        <Btn small arrow={!running} disabled={Boolean(busy) || running} onClick={() => start(s)}>{running ? "Running" : busy === s.id ? "Starting" : "Start"}</Btn>
      </li>;
    })}</ul>
    {active ? <p className="note3">Active: {scenarioTitle(active.scenarioId)}, {active.state}{active.startedAt ? `, started ${ago(active.startedAt)}` : ""}{active.steps ? `, step ${n(active.step ?? 0)} of ${n(active.steps)}` : ""}.</p> : null}
  </Reveal>;
}
