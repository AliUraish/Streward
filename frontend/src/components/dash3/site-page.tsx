"use client";

/* An environment (owner, Oct 18: "give each option its page; Today has the 3-D scan and the agent's view as the page opens,
   with the latest metrics"). /app/[site] is Today: the agent's view and the 3-D scan side by side, the walk and what the
   agent marked, the latest metrics and what happened last. /app/[site]/<section> are the environment's other pages
   (metrics, compliance, maintenance, employees, team and chats, phone calls), chosen in the sidebar. Agent mode on any of
   them: how the agent sees the site, the text and JSON an MCP client reads, and the Site Inspector's tours. */
import { useEffect, useMemo, useState } from "react";
import { useEyeFeed } from "@/lib/hooks-3";
import { useLabels, useWalk } from "@/lib/hooks-7";
import { useInspections } from "@/lib/hooks-10";
import { setScanSite, useMode } from "@/lib/mode-11";
import { rn, site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { AgentEye, ConnectPanel, SiteAgentEnvironment, SiteTours } from "./agent-env";
import { EyePanel } from "./agent-view";
import CompliancePage from "./compliance-page";
import EmployeesPage from "./employees";
import EnvironmentPage from "./environment";
import FactoryOverview from "./factory-overview";
import MaintenancePage from "./maintenance";
import MetricsPage from "./metrics";
import { LatestChats, LiveLog } from "./overview";
import { PhoneCallView, PhoneCallsPanel } from "./phone-calls";
import TeamPage from "./team";
import { PageHead, Reveal, SiteTitle, ago } from "./ui3";

export type SiteSection = "today" | "metrics" | "compliance" | "maintenance" | "employees" | "team" | "calls";

export default function SitePage({ siteId, section = "today" }: { siteId: SiteId3; section?: SiteSection }) {
  const [mode] = useMode();
  if (mode === "agent") return <SiteAgent siteId={siteId} />;
  return section === "today" ? <SiteToday siteId={siteId} /> : <SiteSectionPage siteId={siteId} section={section} />;
}

function LocalTime({ tz }: { tz: string }) {
  const [time, setTime] = useState("");
  useEffect(() => {
    const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false });
    const tick = () => setTime(fmt.format(new Date())); tick();
    const id = window.setInterval(tick, 30_000); return () => window.clearInterval(id);
  }, [tz]);
  return time ? <>{` · ${time} local time`}</> : null;
}

/* Today: what the agent sees and the scan, then the latest figures, then what happened last. */
function SiteToday({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  return <div className="page3">
    <PageHead id="site" title={<SiteTitle site={site} />} sub={<>{site.place}<LocalTime tz={site.tz} /></>} />
    <TodayWindows siteId={siteId} />
    <FactoryOverview siteId={siteId} metricsOnly />
    <LiveLog siteId={siteId} i={4} lines={10} />
  </div>;
}

/* The agent's view and the 3-D scan, side by side as the page opens; the walk and what the agent marked underneath. */
function TodayWindows({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const walk = useWalk(siteId, 2_500);
  const labels = useLabels(siteId);
  const w = walk.data;
  const eye = useEyeFeed(siteId, w?.walking ? 1_500 : 3_000);
  const inspection = useInspections(siteId, 1).data?.[0] ?? null;
  /* The scan is on screen, so this dashboard renders it for the realtime view of the site. */
  useEffect(() => { setScanSite(siteId); return () => setScanSite(null); }, [siteId]);
  const latest = useMemo(() => [...(eye.data?.frames ?? [])].sort((a, b) => b.at.localeCompare(a.at))[0] ?? null, [eye.data]);
  const list = useMemo(() => [...(labels.data ?? [])].sort((a, b) => b.at.localeCompare(a.at)), [labels.data]);
  const marks = list.filter(l => latest && l.frameId === latest.id && l.mark && typeof l.mark.x === "number" && typeof l.mark.y === "number");
  const inspecting = Boolean(inspection && /running|walking|in_progress/.test(inspection.state ?? ""));
  const line = inspecting ? <><strong>Site Inspector</strong>&nbsp;is inspecting {site.short}{inspection?.primary?.assetTag ? <>: <code>{inspection.primary.assetTag}</code></> : null}</>
    : w?.walking ? <><strong>{w.agentName}</strong>&nbsp;is walking{w.stop && w.of ? `, stop ${w.stop} of ${w.of}` : ""}{w.assetTag ? <>: <code>{w.assetTag}</code></> : null}{w.observation ? <span className="r3">&nbsp;{rn(w.observation)}</span> : null}</>
      : w ? <><strong>{w.agentName}</strong>&nbsp;{w.at ? `finished the last walk ${ago(w.at)}; the next one starts on its own` : "starts the next walk on its own"}</>
        : <>{walk.readiness === "loading" ? "Connecting to the agent eye" : "The walk is not available yet."}</>;
  const n = w?.stop ?? 0, of = w?.of ?? 0;
  return <Reveal as="section" className="p3" i={1} aria-labelledby="win-h">
    <div className="winbar11">
      <h2 id="win-h" className="sr-only">What the agent sees</h2>
      <p className="now" aria-live="polite"><span className={`sig ${w?.walking || inspecting ? "ok" : "off"}`} aria-hidden="true" />{line}</p>
    </div>
    <div className="duo12">
      <figure className="pane12">
        <figcaption>Agent&apos;s view</figcaption>
        <div className="eyebox">
          <EyePanel siteId={siteId} frames={eye.data?.frames ?? []} readiness={eye.readiness} renderers={eye.data?.renderers ? eye.data.renderers.filter(r => !r.stale).length : null} />
          {marks.length ? <div className="marks11" aria-hidden="true">{marks.map(l => <span key={l.id} className={`mk ${l.verdict}`} style={{ left: `${(l.mark!.x as number) * 100}%`, top: `${(l.mark!.y as number) * 100}%` }}><i /><span>{l.assetTag}: {l.title}</span></span>)}</div> : null}
        </div>
      </figure>
      <figure className="pane12">
        <figcaption>3-D scan</figcaption>
        <div className="scanwrap11 scan12"><EnvironmentPage siteId={siteId} compact /></div>
      </figure>
    </div>
    <div className="below12">
      {w?.walking && of ? <div className="p3"><h3 style={{ marginBottom: 8 }}>The walk</h3>
        <ol className="walk-stops" aria-label={`Stop ${n} of ${of}`}>{Array.from({ length: Math.min(of, 24) }, (_, k) => { const done = w.stops[k]; const state = done?.verdict ?? (k < n - 1 ? "done" : k === n - 1 ? "now" : "next"); const tag = w.route[k] ?? done?.assetTag ?? ""; return <li key={k} data-state={state} title={tag ? `${tag}${done?.verdict ? `: looks ${done.verdict}` : k === n - 1 ? ": now" : ""}` : undefined} />; })}</ol>
      </div> : null}
      <div className="p3"><h3 style={{ marginBottom: 8 }}>What it marked</h3>
        {list.length ? <ul className="lbl11">{list.slice(0, 9).map(l => <li key={l.id}><span className={`sw ${l.verdict}`} aria-hidden="true" /><span>
          <span className="t" style={{ display: "block" }}>{l.assetTag}{l.assetName ? ` ${l.assetName}` : ""}: {l.title}</span>
          {l.reasons[0] ? <span className="why" style={{ display: "block" }}>{rn(l.reasons[0])}</span> : null}
          <span className="m" style={{ display: "block" }}>{l.agentName}, {ago(l.at)}</span>
        </span></li>)}</ul> : <p className="r3">{labels.readiness === "ready" ? "Nothing marked yet; the agent marks each asset it looks at." : "Not available yet."}</p>}
      </div>
    </div>
  </Reveal>;
}

/* One of the environment's pages. Metrics, Compliance, Maintenance and Team carry their own titles. */
function SiteSectionPage({ siteId, section }: { siteId: SiteId3; section: Exclude<SiteSection, "today"> }) {
  switch (section) {
    case "metrics": return <MetricsPage siteId={siteId} />;
    case "compliance": return <CompliancePage siteId={siteId} />;
    case "maintenance": return <MaintenancePage siteId={siteId} />;
    case "employees": return <div className="page3"><PageHead id="employees" title="Employees" /><EmployeesPage siteId={siteId} /></div>;
    case "team": return <div className="page3"><TeamPage siteId={siteId} /><LatestChats siteId={siteId} /></div>;
    default: return <CallsPage siteId={siteId} />;
  }
}

function CallsPage({ siteId }: { siteId: SiteId3 }) {
  const [open, setOpen] = useState<string | null>(null);
  return <div className="page3">
    <PageHead id="calls" title="Phone calls" />
    <PhoneCallsPanel siteId={siteId} openId={open} onOpen={setOpen} />
    {open ? <PhoneCallView id={open} initial={null} /> : null}
  </div>;
}

function SiteAgent({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  return <div className="page3 agent11">
    <PageHead id="site-agent" title={<>How the agent sees <SiteTitle site={site} /></>} sub="The eye's frames with what the agent marked, the text and JSON an MCP client reads, and the Site Inspector's tours." />
    <AgentEye siteId={siteId} i={0} />
    <SiteAgentEnvironment siteId={siteId} i={1} title="What an MCP client reads" />
    <SiteTours siteId={siteId} i={2} />
    <ConnectPanel i={3} />
  </div>;
}
