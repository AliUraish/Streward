"use client";

/* The dashboard shell: one top bar on every page with Steward, the path as a breadcrumb (Overview, then Overview /
   <environment>, then the page), the one Human · Agent switch for the whole dashboard (mode-11.ts) and the notifications
   bell at the top right; in human mode a left sidebar (owner, Oct 18) with four pages, Conversations, Notifications, Memory
   and Tools, for all three sites on the overview and for the open environment only on an environment, each option
   pixelating on hover; then the page.
   The dashboard-wide notices (calls-live.tsx: a phone call to you while it is on the line, and the agents' chats) are
   mounted once here. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { Remote } from "@/lib/reality";
import { useAgents3, useOverview } from "@/lib/hooks-3";
import type { AgentInfo } from "@/lib/types-2";
import type { Overview } from "@/lib/types-3";
import { HudBridge } from "@/lib/live-3";
import { SITES3, isSite3, site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { useMode, useScanSite } from "@/lib/mode-11";
import LiveNotifier from "./calls-live";
import AgentGuide from "./agent-guide";
import NotificationsBell from "./bell";
import { ToastHost } from "./ui3";
import "./dash3.css";
import "./dash7.css";
import "./dash11.css";

const SITE_KEY = "steward.factory";
const PAGES: Record<string, string> = { conversations: "Conversations", notifications: "Notifications", memory: "Memory", tools: "Tools", evals: "Evals",
  metrics: "Metrics", compliance: "Compliance", maintenance: "Maintenance", employees: "Employees", team: "Team and chats", calls: "Phone calls" };
/* The sidebar's four pages: /app/<page> for all three sites, /app/<site>/<page> for one environment. */
const SIDE_PAGES = [{ key: "conversations", label: "Conversations" }, { key: "notifications", label: "Notifications" }, { key: "memory", label: "Memory" }, { key: "tools", label: "Tools" }];
/* Evals is one page for the whole of Steward (model usage, tool calls, eval suites), at the end of every sidebar. */
const EVALS = { href: "/app/evals", label: "Evals" };
/* An environment's own pages, above the four (owner, Oct 18: each option has its page; Today is the environment itself). */
const SECTIONS = [{ key: "", label: "Today" }, { key: "metrics", label: "Metrics" }, { key: "compliance", label: "Compliance" }, { key: "maintenance", label: "Maintenance" },
  { key: "employees", label: "Employees" }, { key: "team", label: "Team and chats" }, { key: "calls", label: "Phone calls" }];
/* The hover pixels (owner, Oct 18: "it should pixelate and be white"): 20 x 4 squares per option that turn white one by
   one in a fixed shuffled order when the pointer arrives, and go back the same way when it leaves (each square's own
   transition delay, both directions). */
const PX = Array.from({ length: 80 }, (_, k) => { const x = Math.sin((k + 1) * 78.233) * 43758.5453; return Math.round((x - Math.floor(x)) * 240); });
function Px() { return <span className="px11" aria-hidden="true">{PX.map((d, k) => <i key={k} style={{ transitionDelay: `${d}ms` }} />)}</span>; }
const NAV_KEY = "steward.sidebar";
/* The overview and the agent list are polled once by the shell and shared with every page. */
interface Shared { overview: Remote<Overview>; agents: Remote<AgentInfo[]> }
const SharedCtx = createContext<Shared | null>(null);
export function useShared(): Shared { const v = useContext(SharedCtx); if (!v) throw new Error("useShared outside the dashboard shell"); return v; }

export default function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/app";
  const seg = pathname.split("/").filter(Boolean);
  const pathSite = isSite3(seg[1]) ? seg[1] : null;
  const [mode, setMode] = useMode();
  const agent = mode === "agent";
  const [site, setSite] = useState<SiteId3>(() => pathSite ?? "myer-plant");
  /* The realtime bridge joins once the current site is known (the path, else the stored choice), so a page load does not
     open a channel for one site and move it to another. */
  const [siteKnown, setSiteKnown] = useState(Boolean(pathSite));
  const scanSite = useScanSite();
  const overview = useOverview();
  const agents = useAgents3();
  const shared = useMemo(() => ({ overview, agents }), [overview, agents]);
  useEffect(() => { try { const v = window.localStorage.getItem(SITE_KEY); if (isSite3(v) && !pathSite) setSite(v); } catch { /* storage blocked */ } setSiteKnown(true); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (pathSite) { setSite(pathSite); try { window.localStorage.setItem(SITE_KEY, pathSite); } catch { /* storage blocked */ } } }, [pathSite]);
  const live = overview.readiness === "ready";
  const page = (pathSite ? PAGES[seg[2] ?? ""] : seg[1] ? PAGES[seg[1]] : null) ?? null;
  /* The sidebar opens and closes with the Options button at the bottom left; the choice is remembered on this device. */
  const [navOpen, setNavOpen] = useState(true);
  useEffect(() => { try { if (window.localStorage.getItem(NAV_KEY) === "closed") setNavOpen(false); } catch { /* storage blocked */ } }, []);
  const toggleNav = () => setNavOpen(open => { const next = !open; try { window.localStorage.setItem(NAV_KEY, next ? "open" : "closed"); } catch { /* storage blocked */ } return next; });

  return <SharedCtx.Provider value={shared}><ToastHost>
    <div className={`d3 shell11 ${agent ? "agent-mode" : ""}`} data-mode={mode}>
      <header className="top11">
        <Link href="/app" className="wordmark">Steward</Link>
        <nav className="crumbs11" aria-label="Path">
          <ol>
            <li>{pathSite || page ? <Link href="/app">Overview</Link> : <span aria-current="page">Overview</span>}</li>
            {pathSite ? <li><SiteCrumb site={pathSite} /></li> : null}
            {page ? <li><span aria-current="page">{page}</span></li> : null}
          </ol>
        </nav>
        <div className="top11-right">
          <span className={`live3 ${live ? "on" : ""}`}><span className={`sig ${live ? "ok" : "off"}`} aria-hidden="true" />{live ? "Live" : overview.readiness === "loading" ? "Connecting" : "Not connected"}</span>
          <ModeSwitch agent={agent} onChange={a => setMode(a ? "agent" : "human")} />
          <NotificationsBell />
        </div>
      </header>
      {/* Human mode keeps the sidebar mounted so it can slide in and out; the grid column animates with it. */}
      <div className={`frame11 ${agent ? "agent" : navOpen ? "" : "closed"}`}>
        {agent ? null : <SideNav pathname={pathname} pathSite={pathSite} open={navOpen} />}
        {/* Agent mode is the same minimal guide on every page: the endpoints for the page and the tools (agent-guide.tsx). */}
        <main className="main3 main11" id="main" key={mode}>{agent ? <AgentGuide pathname={pathname} pathSite={pathSite} /> : children}</main>
      </div>
      {agent ? null : <button type="button" className={`opt11 ${navOpen ? "open" : ""}`} onClick={toggleNav} aria-expanded={navOpen} aria-controls="sidebar11"
        aria-label={navOpen ? "Hide the sidebar" : "Show the sidebar"} title={navOpen ? "Hide the sidebar" : "Show the sidebar"}>
        <Px /><span className="burger" aria-hidden="true"><i /><i /><i /></span><span className="lbl" aria-hidden="true">Options</span>
      </button>}
      {siteKnown ? <HudBridge siteId={site} role={scanSite === site ? "renderer" : "viewer"} /> : null}
      <LiveNotifier />
    </div>
  </ToastHost></SharedCtx.Provider>;
}

/* The left sidebar (human mode): on an environment its own pages, then the four pages for the open environment only, or for
   all three sites on the overview. */
function SideNav({ pathname, pathSite, open }: { pathname: string; pathSite: SiteId3 | null; open: boolean }) {
  return <aside className="nav11" id="sidebar11" aria-label="Sidebar" inert={!open} aria-hidden={!open || undefined}>
    <h4>{pathSite ? site3(pathSite).name : "All three sites"}</h4>
    {pathSite ? <ul className="sections11">{SECTIONS.map(x => { const href = `/app/${pathSite}${x.key ? `/${x.key}` : ""}`; return <li key={x.key || "today"}>
      <Link href={href} aria-current={pathname === href ? "page" : undefined}><Px /><span className="lbl">{x.label}</span></Link>
    </li>; })}</ul> : null}
    {pathSite ? <h4>Across the site</h4> : null}
    <ul>{SIDE_PAGES.map(p => {
      const href = pathSite ? `/app/${pathSite}/${p.key}` : `/app/${p.key}`;
      return <li key={p.key}><Link href={href} aria-current={pathname === href ? "page" : undefined}><Px /><span className="lbl">{p.label}</span></Link></li>;
    })}
      <li><Link href={EVALS.href} aria-current={pathname === EVALS.href ? "page" : undefined}><Px /><span className="lbl">{EVALS.label}</span></Link></li>
    </ul>
  </aside>;
}

/* The environment in the path; it opens a short list of the three environments to move between them. */
function SiteCrumb({ site }: { site: SiteId3 }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const s = site3(site);
  return <div className="sitecrumb11" ref={ref}>
    <button type="button" aria-current="page" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(o => !o)}>{s.name}<svg className="chev" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg></button>
    {open ? <ul className="menu11" role="list">{SITES3.map(x => <li key={x.id}><Link href={`/app/${x.id}`} aria-current={x.id === site ? "page" : undefined}><strong>{x.name}</strong><span>{x.place}</span></Link></li>)}</ul> : null}
  </div>;
}

/* Human · Agent: the one switch; arrow keys, Home and End, Space and Enter. */
function ModeSwitch({ agent, onChange }: { agent: boolean; onChange: (agent: boolean) => void }) {
  const key = (e: KeyboardEvent) => {
    if (["ArrowRight", "End"].includes(e.key)) { e.preventDefault(); if (!agent) onChange(true); }
    if (["ArrowLeft", "Home"].includes(e.key)) { e.preventDefault(); if (agent) onChange(false); }
  };
  return <button type="button" role="switch" aria-checked={agent} aria-label="Agent mode" className={`mode3 mode11 ${agent ? "is-agent" : ""}`} onClick={() => onChange(!agent)} onKeyDown={key}>
    <span className="knob" aria-hidden="true" />
    <span className="word human">Human</span><span className="word agent">Agent</span>
  </button>;
}
