"use client";

/* /app/[site], an environment (owner, Oct 18): first the window the agent is seeing (its eye's latest frame, refreshing
   as it walks or inspects, with what it marked green "looks good" or blue "looks bad"; the 3-D scan one switch away),
   then what happened last at the site, then the environment's details in tabs. Agent mode on the same route: how the
   agent sees the site, the text and JSON an MCP client reads, and the Site Inspector's tours. */
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

export default function SitePage({ siteId }: { siteId: SiteId3 }) {
  const [mode] = useMode();
  return mode === "agent" ? <SiteAgent siteId={siteId} /> : <SiteHuman siteId={siteId} />;
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

function SiteHuman({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  return <div className="page3">
    <PageHead id="site" title={<SiteTitle site={site} />} sub={<>{site.place}<LocalTime tz={site.tz} /></>} />
    <AgentWindow siteId={siteId} />
    <LiveLog siteId={siteId} i={2} lines={10} />
    <Details siteId={siteId} />
  </div>;
}

/* The window the agent is seeing. */
function AgentWindow({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const [view, setView] = useState<"eye" | "scan">("eye");
  const walk = useWalk(siteId, 2_500);
  const labels = useLabels(siteId);
  const w = walk.data;
  const eye = useEyeFeed(siteId, w?.walking ? 1_500 : 3_000);
  const inspection = useInspections(siteId, 1).data?.[0] ?? null;
  useEffect(() => { setScanSite(view === "scan" ? siteId : null); return () => setScanSite(null); }, [view, siteId]);
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
      <div className="tabs11" role="tablist" aria-label="View">
        <button type="button" role="tab" aria-selected={view === "eye"} onClick={() => setView("eye")}>Agent&apos;s view</button>
        <button type="button" role="tab" aria-selected={view === "scan"} onClick={() => setView("scan")}>3-D scan</button>
      </div>
    </div>
    {view === "eye" ? <div className="win11">
      <div className="eyebox">
        <EyePanel siteId={siteId} frames={eye.data?.frames ?? []} readiness={eye.readiness} renderers={eye.data?.renderers ? eye.data.renderers.filter(r => !r.stale).length : null} />
        {marks.length ? <div className="marks11" aria-hidden="true">{marks.map(l => <span key={l.id} className={`mk ${l.verdict}`} style={{ left: `${(l.mark!.x as number) * 100}%`, top: `${(l.mark!.y as number) * 100}%` }}><i /><span>{l.assetTag}: {l.title}</span></span>)}</div> : null}
      </div>
      <div className="side">
        {w?.walking && of ? <div className="p3"><h3 style={{ marginBottom: 8 }}>The walk</h3>
          <ol className="walk-stops" aria-label={`Stop ${n} of ${of}`}>{Array.from({ length: Math.min(of, 24) }, (_, k) => { const done = w.stops[k]; const state = done?.verdict ?? (k < n - 1 ? "done" : k === n - 1 ? "now" : "next"); const tag = w.route[k] ?? done?.assetTag ?? ""; return <li key={k} data-state={state} title={tag ? `${tag}${done?.verdict ? `: looks ${done.verdict}` : k === n - 1 ? ": now" : ""}` : undefined} />; })}</ol>
        </div> : null}
        <div className="p3"><h3 style={{ marginBottom: 8 }}>What it marked</h3>
          {list.length ? <ul className="lbl11">{list.slice(0, 10).map(l => <li key={l.id}><span className={`sw ${l.verdict}`} aria-hidden="true" /><span>
            <span className="t" style={{ display: "block" }}>{l.assetTag}{l.assetName ? ` ${l.assetName}` : ""}: {l.title}</span>
            {l.reasons[0] ? <span className="why" style={{ display: "block" }}>{rn(l.reasons[0])}</span> : null}
            <span className="m" style={{ display: "block" }}>{l.agentName}, {ago(l.at)}</span>
          </span></li>)}</ul> : <p className="r3">{labels.readiness === "ready" ? "Nothing marked yet; the agent marks each asset it looks at." : "Not available yet."}</p>}
        </div>
      </div>
    </div> : <div className="scanwrap11"><EnvironmentPage siteId={siteId} /></div>}
  </Reveal>;
}

const TABS = [
  { key: "today", label: "Today" }, { key: "metrics", label: "Metrics" }, { key: "compliance", label: "Compliance" },
  { key: "maintenance", label: "Maintenance" }, { key: "employees", label: "Employees" }, { key: "team", label: "Team and chats" }, { key: "calls", label: "Phone calls" },
] as const;
type Tab = typeof TABS[number]["key"];
const isTab = (v: string): v is Tab => TABS.some(t => t.key === v);

/* The environment's details; the tab follows the URL's #hash, so an old link (…/compliance) lands on its tab. */
function Details({ siteId }: { siteId: SiteId3 }) {
  const [tab, setTab] = useState<Tab>("today");
  useEffect(() => {
    const read = () => { const h = window.location.hash.replace(/^#/, ""); if (isTab(h)) setTab(h); };
    read(); window.addEventListener("hashchange", read); return () => window.removeEventListener("hashchange", read);
  }, []);
  const pick = (t: Tab) => { setTab(t); try { window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}#${t}`); } catch { /* no history */ } };
  return <Reveal as="section" className="page3" i={3} aria-label="Details" id="details">
    <div className="tabs11" role="tablist" aria-label="Details">{TABS.map(t => <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => pick(t.key)}>{t.label}</button>)}</div>
    <div className="embed11" role="tabpanel">
      {tab === "today" ? <FactoryOverview siteId={siteId} embedded />
        : tab === "metrics" ? <MetricsPage siteId={siteId} />
          : tab === "compliance" ? <CompliancePage siteId={siteId} />
            : tab === "maintenance" ? <MaintenancePage siteId={siteId} />
              : tab === "employees" ? <EmployeesPage siteId={siteId} />
                : tab === "team" ? <div className="page3"><TeamPage siteId={siteId} /><LatestChats siteId={siteId} /></div>
                  : <CallsTab siteId={siteId} />}
    </div>
  </Reveal>;
}

function CallsTab({ siteId }: { siteId: SiteId3 }) {
  const [open, setOpen] = useState<string | null>(null);
  return <div className="page3">
    <PhoneCallsPanel siteId={siteId} openId={open} onOpen={setOpen} />
    {open ? <PhoneCallView id={open} initial={null} /> : null}
  </div>;
}

function SiteAgent({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  return <div className="page3 agent11">
    <PageHead id="site-agent" title={<>How the agent sees <SiteTitle site={site} /></>} sub="The eye's frames with what the agent marked, the text and JSON an MCP client reads, and the Site Inspector's tours." />
    <AgentEye siteId={siteId} i={0} />
    <SiteAgentEnvironment siteId={siteId} i={1} />
    <SiteTours siteId={siteId} i={2} />
    <ConnectPanel i={3} />
  </div>;
}
