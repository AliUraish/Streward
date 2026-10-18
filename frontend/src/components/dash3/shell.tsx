"use client";

/* The dashboard shell (owner, Oct 18: "no sidebar"): one top bar on every page with Steward, the path as a breadcrumb
   (Overview, then Overview / <environment>), the one Human · Agent switch for the whole dashboard (mode-11.ts) and the
   notifications bell at the top right; under it the page, then a footer line to the pages that are not on the path.
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
import NotificationsBell from "./bell";
import { ToastHost } from "./ui3";
import "./dash3.css";
import "./dash7.css";
import "./dash11.css";

const SITE_KEY = "steward.factory";
const PAGES: Record<string, string> = { conversations: "Conversations", notifications: "Notifications", memory: "Memory", tools: "Tools", evals: "Evals" };
const FOOTER = [{ href: "/app/conversations", label: "Conversations" }, { href: "/app/notifications", label: "Notifications" }, { href: "/app/memory", label: "Memory" }, { href: "/app/tools", label: "Tools" }, { href: "/app/evals", label: "Evals" }];
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
  const page = !pathSite && seg[1] ? PAGES[seg[1]] ?? null : null;

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
      <main className="main3 main11" id="main" key={mode}>{children}</main>
      <footer className="foot11"><nav aria-label="More pages">{FOOTER.map(p => <Link key={p.href} href={p.href} aria-current={pathname.startsWith(p.href) ? "page" : undefined}>{p.label}</Link>)}</nav></footer>
      {siteKnown ? <HudBridge siteId={site} role={scanSite === site ? "renderer" : "viewer"} /> : null}
      <LiveNotifier />
    </div>
  </ToastHost></SharedCtx.Provider>;
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
    <button type="button" aria-current="page" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(o => !o)}>{s.name}<span className="chev" aria-hidden="true">▾</span></button>
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
