"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useSimulation, useSites, type Remote } from "@/lib/reality";
import { backendIsOld, DEMO_SITE, requestId, siteList, toSiteId } from "@/lib/site";
import type { SimulationStatus, SiteId, SiteProperty, Environment } from "@/lib/types-2";
import { errorMessage } from "../ui";

export interface SiteContextValue {
  siteId: SiteId;                 /* the ID the UI speaks */
  requestId: string;              /* the ID the backend answers to (legacy alias while the backend is old) */
  setSiteId: (id: SiteId) => void;
  sites: (SiteProperty & { id: SiteId; environment: Environment })[];
  listed: SiteProperty[];
  backendOld: boolean;
  simulation: Remote<SimulationStatus>;
  notify: (message: string) => void;
}
const SiteContext = createContext<SiteContextValue | null>(null);
export function useSite() { const v = useContext(SiteContext); if (!v) throw new Error("useSite outside DashShell"); return v; }

const STORAGE = "steward.site";
const NAV = [{ href: "/app/environment", label: "Environment" }, { href: "/app/agents", label: "Agents" }, { href: "/app/evals", label: "Evals" }];
const MORE = [{ view: "inspection", label: "Inspection wall" }, { view: "library", label: "Library" }, { view: "agents", label: "Agent chat" }];

export default function DashShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [siteId, setSite] = useState<SiteId>(DEMO_SITE);
  const [notice, setNotice] = useState("");
  const sitesRemote = useSites();
  const simulation = useSimulation();
  const listed = useMemo(() => sitesRemote.data ?? [], [sitesRemote.data]);
  const sites = useMemo(() => siteList(listed), [listed]);
  const backendOld = backendIsOld(listed);

  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("site");
    let stored: string | null = null; try { stored = localStorage.getItem(STORAGE); } catch {}
    setSite(toSiteId(fromUrl ?? stored));
  }, []);
  const setSiteId = useCallback((id: SiteId) => {
    setSite(id);
    try { localStorage.setItem(STORAGE, id); } catch {}
    const url = new URL(window.location.href); url.searchParams.set("site", id); window.history.replaceState(null, "", url.toString());
  }, []);
  const value = useMemo<SiteContextValue>(() => ({ siteId, requestId: requestId(siteId, listed), setSiteId, sites, listed, backendOld, simulation, notify: setNotice }), [siteId, listed, setSiteId, sites, backendOld, simulation]);
  const site = sites.find(s => s.id === siteId);

  return <SiteContext.Provider value={value}>
    <div className="dash dash-2">
      <header className="dash-bar">
        <Link href="/" className="wordmark">Steward <small>{site?.name ?? ""}</small></Link>
        <div className="right">
          <SimulationBadge remote={simulation} onError={setNotice} />
          <select aria-label="Select site" value={siteId} onChange={e => setSiteId(toSiteId(e.target.value))}>{sites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        </div>
      </header>
      <nav className="side" aria-label="Sections">
        {NAV.map(n => <Link key={n.href} href={`${n.href}?site=${siteId}`} className={pathname?.startsWith(n.href) ? "active" : ""}>{n.label}</Link>)}
        <div className="more muted" style={{ fontSize: 13, padding: "6px 10px" }}>More</div>
        <div className="more-links">{MORE.map(m => <Link key={m.view} href={`/app?view=${m.view}&site=${siteId}`}>{m.label}</Link>)}</div>
        <div className="foot">{backendOld ? "Backend still on the old seed; new panels report not available until it restarts." : sitesRemote.readiness === "ready" ? `${listed.length} sites listed` : sitesRemote.readiness === "loading" ? "Listing sites" : "Site list unavailable; showing the three known sites"}</div>
      </nav>
      {notice ? <div className="dash-notice" role="alert" style={{ gridColumn: "1 / -1" }}><span>{notice}</span><button className="btn btn-quiet btn-small" onClick={() => setNotice("")}>Dismiss</button></div> : null}
      <main className="dash-main">{children}</main>
    </div>
  </SiteContext.Provider>;
}

/* "simulation on" with a toggle: a demo control, posts as the operator. Says so when the endpoint is not there yet. */
function SimulationBadge({ remote, onError }: { remote: Remote<SimulationStatus>; onError: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  async function toggle() {
    if (!remote.data) return;
    setBusy(true);
    try { await api.setSimulation(!remote.data.enabled); remote.reload(); } catch (e) { onError(errorMessage(e)); } finally { setBusy(false); }
  }
  if (remote.readiness === "loading") return <span className="sim"><span className="dot" />simulation</span>;
  if (remote.readiness !== "ready" || !remote.data) return <span className="sim" title={remote.error}><span className="dot" />simulation: not available yet<button onClick={remote.reload}>Retry</button></span>;
  const total = Object.values(remote.data.counts ?? {}).reduce((a, b) => a + b, 0);
  return <span className={`sim ${remote.data.enabled ? "on" : ""}`}><span className="dot" />simulation {remote.data.enabled ? "on" : "off"}{total ? ` · ${total} records` : ""}<span className="demo">demo control</span><button onClick={toggle} disabled={busy}>{remote.data.enabled ? "Turn off" : "Turn on"}</button></span>;
}
