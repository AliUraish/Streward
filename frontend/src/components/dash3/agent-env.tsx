"use client";

/* The agent views (owner, Oct 18: "make these agent environments for MCPs, so MCP servers can see them, and add how the
   agent is seeing the environment"): how to connect an MCP client, the tools it uses, each site's agent environment as
   the text and JSON an MCP client reads (GET /api/agent-environment/{siteId}), the agent eye's frame with what the agent
   marked, and the Site Inspector's site tours with the pictures of what is wrong. */
import { useMemo, useState } from "react";
import { environmentPath, toursPath, type EnvFrame, type EnvLabel, type SiteTour } from "@/lib/api-11";
import { useAgentEnvironment, useAgentEnvironmentText, useSiteTours } from "@/lib/hooks-11";
import { useEyeFeed } from "@/lib/hooks-3";
import { site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { AgentText, CopyBtn } from "./mode10";
import { EyePanel } from "./agent-view";
import { Reveal, State, ago } from "./ui3";

export const MCP_URL = "http://127.0.0.1:8002/mcp";
export const AGENT_TOOLS: { name: string; purpose: string }[] = [
  { name: "get_environment", purpose: "What the agent sees of a site: the walk, the eye's latest frames with their labels and marks, readings, obligations, issues, the latest inspection and the log." },
  { name: "request_site_tour", purpose: "Ask the Site Inspector for a tour of a site; it walks the site with the agent eye and sends back pictures of what is wrong." },
  { name: "get_site_tour", purpose: "Read a tour by id: every stop, the pictures of the bad ones and the inspector's summary." },
  { name: "eye_look, eye_go_to, eye_mark", purpose: "Drive the agent eye yourself: look, go to an asset, mark what you see." },
  { name: "wait_for", purpose: "Wait for a change without polling: a walk stop, an issue, a booking, a call ending." },
  { name: "resolve, attest", purpose: "Ask the site for a fact with its evidence; sign what was checked." },
  { name: "get_changes, get_issues, list_obligations", purpose: "What changed, what is open, what is due." },
  { name: "get_owner_notifications, get_compliance_snapshot", purpose: "What the owner was last sent; the compliance snapshot." },
];

export function ConnectPanel({ i = 0 }: { i?: number }) {
  const config = useMemo(() => JSON.stringify({ mcpServers: { steward: { url: MCP_URL } } }, null, 2), []);
  return <div className="connect11">
    <Reveal as="section" className="p3" i={i} aria-labelledby="mcp-h">
      <div className="p-head"><h2 id="mcp-h">Connect an agent</h2></div>
      <p className="r2">Any MCP client reads the sites through the Steward MCP server, as the Owner&apos;s agent. Every view below is what it gets.</p>
      <p style={{ margin: "12px 0 6px" }}><code>{MCP_URL}</code> <CopyBtn text={MCP_URL} what="the MCP address" /></p>
      <pre className="pre10" tabIndex={0} aria-label="MCP client settings">{config}</pre>
    </Reveal>
    <Reveal as="section" className="p3" i={i + 1} aria-labelledby="tools-h">
      <div className="p-head"><h2 id="tools-h">Tools an agent uses</h2></div>
      <ul className="tools11">{AGENT_TOOLS.map(t => <li key={t.name}><code>{t.name}</code><span>{t.purpose}</span></li>)}</ul>
    </Reveal>
  </div>;
}

/* One site as an agent reads it: the latest eye frame beside the text an MCP client gets, with the JSON behind it. */
export function SiteAgentEnvironment({ siteId, i = 0, heading = true, title }: { siteId: SiteId3; i?: number; heading?: boolean; title?: string }) {
  const s = site3(siteId);
  const env = useAgentEnvironment(siteId);
  const text = useAgentEnvironmentText(siteId);
  const eye = useEyeFeed(siteId, 4_000);
  const latest = useMemo(() => [...(eye.data?.frames ?? [])].sort((a, b) => b.at.localeCompare(a.at))[0] ?? null, [eye.data]);
  const frame: { url: string; at: string | null; who: string | null } | null = env.data?.frames[0] ? { url: env.data.frames[0].url, at: env.data.frames[0].at, who: env.data.frames[0].actorName }
    : latest ? { url: latest.frameUrl, at: latest.at, who: null } : null;
  return <Reveal as="section" className="p3" i={i} aria-labelledby={`env-${siteId}-h`}>
    {heading ? <div className="p-head"><h2 id={`env-${siteId}-h`}>{title ?? s.name}</h2><span className="meta">{env.data?.at ? `as of ${ago(env.data.at)}` : ""}</span></div> : null}
    <div className="envtext11">
      <figure style={{ margin: 0 }}>
        <img src={frame?.url ?? s.thumbnailUrl} alt={frame ? `${s.name}: the agent eye's latest frame` : `${s.name}: the capture's thumbnail`} />
        <figcaption className="cap">{frame ? `Agent eye${frame.who ? `, ${frame.who}` : ""}${frame.at ? `, ${ago(frame.at)}` : ""}` : "The eye has not looked yet."}</figcaption>
      </figure>
      <State remote={text} what={`what an agent sees of ${s.short}`} isEmpty={t => !t.trim()} empty="Nothing to read yet.">
        {t => <AgentText what={`${s.short} as an agent sees it`} endpoints={[environmentPath(siteId, true), environmentPath(siteId)]} text={t} json={env.data?.raw} />}
      </State>
    </div>
  </Reveal>;
}

/* The eye frame with the marks the agent left on it: green "looks good", blue "looks bad", where it pointed. */
function marksOf(frame: EnvFrame | null, labels: EnvLabel[]): EnvLabel[] {
  const own = (frame?.labels ?? []).filter(l => l.mark);
  if (own.length) return own;
  return labels.filter(l => l.mark && frame?.assetTag && l.assetTag === frame.assetTag);
}
export function AgentEye({ siteId, i = 0 }: { siteId: SiteId3; i?: number }) {
  const s = site3(siteId);
  const eye = useEyeFeed(siteId, 2_000);
  const env = useAgentEnvironment(siteId, 4_000);
  const first = env.data?.frames[0] ?? null;
  const marks = marksOf(first, env.data?.labels ?? []);
  const labels = env.data?.labels ?? [];
  return <Reveal as="section" className="p3" i={i} aria-labelledby={`sees-${siteId}-h`}>
    <div className="p-head"><h2 id={`sees-${siteId}-h`}>The agent&apos;s eye at {s.short}</h2>{env.data?.walk ? <span className="chip11 on">{env.data.walk.agentName ?? "Agent"} · {env.data.walk.moving ? "moving" : "still"}{env.data.walk.stopIndex && env.data.walk.stops ? ` · stop ${env.data.walk.stopIndex} of ${env.data.walk.stops}` : ""}{env.data.walk.assetTag ? ` · ${env.data.walk.assetTag}` : ""}</span> : null}</div>
    <div className="win11">
      <div className="eyebox">
        <EyePanel siteId={siteId} frames={eye.data?.frames ?? []} readiness={eye.readiness} renderers={eye.data?.renderers ? eye.data.renderers.filter(r => !r.stale).length : null} />
        {marks.length ? <div className="marks11" aria-hidden="true">{marks.map(l => <span key={l.assetTag} className={`mk ${l.verdict === "bad" ? "bad" : "good"}`} style={{ left: `${(l.mark!.x) * 100}%`, top: `${(l.mark!.y) * 100}%` }}><i /><span>{l.assetTag}: {l.title}</span></span>)}</div> : null}
      </div>
      <div className="side">
        <div className="p3"><h3 style={{ marginBottom: 8 }}>What it marked</h3>
          {labels.length ? <ul className="lbl11">{labels.slice(0, 12).map(l => <li key={l.assetTag}><span className={`sw ${l.verdict === "bad" ? "bad" : "good"}`} aria-hidden="true" /><span><span className="t">{l.assetTag}{l.assetName ? ` ${l.assetName}` : ""}: {l.title}</span>{l.reasons[0] ? <span className="why" style={{ display: "block" }}>{l.reasons[0]}</span> : null}<span className="m" style={{ display: "block" }}>{l.mark ? `mark at ${Math.round(l.mark.x * 100)}%, ${Math.round(l.mark.y * 100)}%${l.mark.note ? `: ${l.mark.note}` : ""}` : "no mark"}{l.at ? ` · ${ago(l.at)}` : ""}</span></span></li>)}</ul>
            : <p className="r3">{env.readiness === "ready" ? "Nothing marked yet." : "Not available yet."}</p>}
        </div>
      </div>
    </div>
  </Reveal>;
}

/* The Site Inspector's tours for agents: each stop, the pictures of the bad ones, the summary. */
export function SiteTours({ siteId, i = 0, limit = 5 }: { siteId?: SiteId3; i?: number; limit?: number }) {
  const tours = useSiteTours(siteId, limit);
  return <Reveal as="section" className="p3" i={i} aria-labelledby={`tours-${siteId ?? "all"}-h`}>
    <div className="p-head"><h2 id={`tours-${siteId ?? "all"}-h`}>Site tours</h2><span className="meta"><code>request_site_tour</code></span></div>
    <State remote={tours} what="site tours" isEmpty={t => t.length === 0} empty="No tours yet. An agent asks for one with request_site_tour; the Site Inspector walks the site and sends back pictures of what is wrong.">
      {t => <ol className="tours11">{t.map(x => <Tour key={x.id} t={x} />)}</ol>}
    </State>
    <p className="r3" style={{ marginTop: 10 }}><a className="lnk" href={toursPath(siteId, limit)} target="_blank" rel="noreferrer">{toursPath(siteId, limit)}</a></p>
  </Reveal>;
}
function Tour({ t }: { t: SiteTour }) {
  const [all, setAll] = useState(false);
  const shown = all ? t.stops : t.findings;
  return <li className="tour11">
    <div className="r1"><strong>{t.guideName} toured {t.siteName ?? site3(t.siteId as SiteId3)?.name ?? t.siteId}</strong><span className="r3">{t.requesterName ? `for ${t.requesterName}, ` : ""}{t.state === "running" ? "walking now" : t.state === "failed" ? "stopped" : `${t.stops.length} stops, ${t.findings.length} look bad`}{t.startedAt ? `, ${ago(t.startedAt)}` : ""}</span></div>
    {t.summary ? <p className="r2">{t.summary}</p> : null}
    {shown.length ? <div className="pics">{shown.map(s => <figure key={`${s.n}-${s.assetTag}`}>
      {s.frameUrl ? <img src={s.frameUrl} alt={`${s.assetTag}: ${s.title}`} loading="lazy" /> : null}
      <figcaption><span><span className={`sw7 ${s.verdict === "bad" ? "bad" : "good"}`} aria-hidden="true" />{s.assetTag}{s.assetName ? ` ${s.assetName}` : ""}: {s.title}</span>{s.reasons[0] ? <span className="why">{s.reasons[0]}</span> : null}</figcaption>
    </figure>)}</div> : <p className="r3">{t.state === "running" ? "The inspector is still walking." : "Nothing looked bad."}</p>}
    {t.stops.length > t.findings.length ? <button type="button" className="lnk" onClick={() => setAll(a => !a)}>{all ? "Only what is wrong" : `All ${t.stops.length} stops`}</button> : null}
  </li>;
}
