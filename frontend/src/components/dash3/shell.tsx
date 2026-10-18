"use client";

/* The dashboard shell (REALITY-CONTRACT-4.md section 8): a sidebar with the factory switch at the top, the selected
   factory's pages, the portfolio pages, then the Human · Agent switch. Switching to Agent dissolves the page (the
   home page's technique: deterministic scatter offsets, opacity and transform only) and brings up /app/agent-view;
   switching back fades the agent view and re-forms the page. Reduced motion makes both instant. */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { Remote } from "@/lib/reality";
import { useAgents3, useOverview } from "@/lib/hooks-3";
import type { AgentInfo } from "@/lib/types-2";
import type { Overview } from "@/lib/types-3";
import { SITES3, isSite3, site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { ToastHost } from "./ui3";
import "./dash3.css";

const SITE_KEY = "steward.factory";
const RETURN_KEY = "steward.return";
type Phase = "idle" | "to-agent" | "to-human" | "reform-start" | "reform";
const FACTORY_PAGES = [
  { slug: "", label: "Overview" }, { slug: "metrics", label: "Metrics" }, { slug: "environment", label: "Environment" },
  { slug: "team", label: "Team" }, { slug: "compliance", label: "Compliance" }, { slug: "maintenance", label: "Maintenance" },
];
const PORTFOLIO_PAGES = [
  { href: "/app", label: "Portfolio" }, { href: "/app/agents", label: "Agents map" },
  { href: "/app/conversations", label: "Conversations" }, { href: "/app/evals", label: "Evals" },
];
/* The overview and the agent list are polled once by the shell and shared with every page. */
interface Shared { overview: Remote<Overview>; agents: Remote<AgentInfo[]> }
const SharedCtx = createContext<Shared | null>(null);
export function useShared(): Shared { const v = useContext(SharedCtx); if (!v) throw new Error("useShared outside the dashboard shell"); return v; }

const reducedMotion = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

export default function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/app";
  const router = useRouter();
  const seg = pathname.split("/").filter(Boolean);
  const pathSite = isSite3(seg[1]) ? seg[1] : null;
  const agentMode = pathname.startsWith("/app/agent-view");
  const [site, setSite] = useState<SiteId3>("myer-plant");
  const [phase, setPhase] = useState<Phase>("idle");
  const [menu, setMenu] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const reformPending = useRef(false);
  const timer = useRef(0);
  const overview = useOverview();
  const agents = useAgents3();
  const shared = useMemo(() => ({ overview, agents }), [overview, agents]);

  useEffect(() => { try { const v = window.localStorage.getItem(SITE_KEY); if (isSite3(v)) setSite(v); } catch { /* storage blocked */ } }, []);
  useEffect(() => { if (pathSite) { setSite(pathSite); try { window.localStorage.setItem(SITE_KEY, pathSite); } catch { /* storage blocked */ } } }, [pathSite]);
  useEffect(() => { setMenu(false); }, [pathname]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  /* Deterministic scatter offsets for every block that dissolves, set when the page's blocks are on screen. */
  const scatter = useCallback(() => {
    const root = rootRef.current; if (!root) return;
    root.querySelectorAll<HTMLElement>(".main3 [data-dissolve]").forEach((el, i) => {
      const a = (i * 137.508) % 360; const r = 18 + ((i * 53) % 30);
      el.style.setProperty("--dx", `${(Math.cos(a * Math.PI / 180) * r).toFixed(1)}px`);
      el.style.setProperty("--dy", `${(Math.sin(a * Math.PI / 180) * r + 12).toFixed(1)}px`);
      el.style.setProperty("--di", String(i % 21));
    });
  }, []);

  /* After a navigation: arriving in agent mode ends the dissolve; arriving back re-forms the page. */
  useEffect(() => {
    if (agentMode) { setPhase("idle"); return; }
    if (!reformPending.current) { setPhase("idle"); return; }
    reformPending.current = false;
    let raf = 0;
    const start = () => { scatter(); setPhase("reform-start"); raf = requestAnimationFrame(() => { raf = requestAnimationFrame(() => setPhase("reform")); }); };
    raf = requestAnimationFrame(start);
    timer.current = window.setTimeout(() => setPhase("idle"), 1100);
    return () => cancelAnimationFrame(raf);
  }, [pathname, agentMode, scatter]);

  const toAgent = useCallback(() => {
    try { window.sessionStorage.setItem(RETURN_KEY, pathname); } catch { /* storage blocked */ }
    if (reducedMotion()) { router.push("/app/agent-view"); return; }
    scatter(); setPhase("to-agent");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => router.push("/app/agent-view"), 640);
  }, [pathname, router, scatter]);
  const toHuman = useCallback(() => {
    let back = "/app"; try { back = window.sessionStorage.getItem(RETURN_KEY) || "/app"; } catch { /* storage blocked */ }
    if (back.startsWith("/app/agent-view")) back = "/app";
    if (reducedMotion()) { router.push(back); return; }
    setPhase("to-human"); reformPending.current = true;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => router.push(back), 300);
  }, [router]);

  const pickSite = (id: SiteId3) => {
    setSite(id); try { window.localStorage.setItem(SITE_KEY, id); } catch { /* storage blocked */ }
    if (pathSite) router.push(pathname.replace(`/app/${pathSite}`, `/app/${id}`));
    else router.push(`/app/${id}`);
  };
  const live = overview.readiness === "ready";
  const s = site3(site);
  const factoryHref = (slug: string) => `/app/${site}${slug ? `/${slug}` : ""}`;
  const isActive = (href: string) => href === "/app" || href === `/app/${site}` ? pathname === href : pathname.startsWith(href);

  return <SharedCtx.Provider value={shared}><ToastHost>
    <div className={`d3 shell3 ${agentMode ? "agent-mode" : ""} ${menu ? "menu-open" : ""}`} data-phase={phase} ref={rootRef}>
      <aside className="side3" aria-label="Dashboard">
        <Link href="/" className="wordmark">Steward</Link>
        {!agentMode ? <>
          <FactorySwitch value={site} onChange={pickSite} />
          <button type="button" className="menu3" aria-expanded={menu} aria-controls="nav3" onClick={() => setMenu(m => !m)}>{menu ? "Close" : "Menu"}</button>
          <nav className="nav3" id="nav3" aria-label="Pages">
            <div className="group">
              <span className="gname">{s.name}</span>
              {FACTORY_PAGES.map(p => { const href = factoryHref(p.slug); return <Link key={p.label} href={href} className={isActive(href) ? "on" : ""} aria-current={isActive(href) ? "page" : undefined}>{p.label}</Link>; })}
            </div>
            <div className="group">
              <span className="gname">Both factories</span>
              {PORTFOLIO_PAGES.map(p => <Link key={p.href} href={p.href} className={isActive(p.href) ? "on" : ""} aria-current={isActive(p.href) ? "page" : undefined}>{p.label}</Link>)}
            </div>
            <ModeSwitch agent={false} onChange={a => a ? toAgent() : undefined} />
            <span className={`live3 ${live ? "on" : ""}`} title={live ? "GET /api/overview answers" : overview.error}><span className={`sig ${live ? "ok" : "off"}`} aria-hidden="true" />{live ? "Live" : overview.readiness === "loading" ? "Connecting" : "Overview not available yet"}</span>
          </nav>
        </> : <div className="agent-side"><ModeSwitch agent onChange={a => a ? undefined : toHuman()} /></div>}
      </aside>
      <main className="main3" id="main">{children}</main>
    </div>
  </ToastHost></SharedCtx.Provider>;
}

/* Myer · Bristol: a track with a white knob that glides, as the home page's mode switch does. */
function FactorySwitch({ value, onChange }: { value: SiteId3; onChange: (id: SiteId3) => void }) {
  const idx = SITES3.findIndex(s => s.id === value);
  const key = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); onChange(SITES3[(idx + 1) % 2].id); }
  };
  return <div className={`fswitch ${idx === 1 ? "second" : ""}`} role="radiogroup" aria-label="Factory" onKeyDown={key}>
    <span className="knob" aria-hidden="true" />
    {SITES3.map(s => <button key={s.id} type="button" role="radio" aria-checked={s.id === value} tabIndex={s.id === value ? 0 : -1} className={s.id === value ? "on" : ""} onClick={() => onChange(s.id)}>{s.short}</button>)}
  </div>;
}

/* Human · Agent: role switch, arrow keys, Space and Enter, as on the home page. */
function ModeSwitch({ agent, onChange }: { agent: boolean; onChange: (agent: boolean) => void }) {
  const key = (e: KeyboardEvent) => {
    if (["ArrowRight", "End"].includes(e.key)) { e.preventDefault(); if (!agent) onChange(true); }
    if (["ArrowLeft", "Home"].includes(e.key)) { e.preventDefault(); if (agent) onChange(false); }
  };
  return <button type="button" role="switch" aria-checked={agent} aria-label="Agent mode" className={`mode3 ${agent ? "is-agent" : ""}`} onClick={() => onChange(!agent)} onKeyDown={key}>
    <span className="knob" aria-hidden="true" />
    <span className="word human">Human</span><span className="word agent">Agent</span>
  </button>;
}
