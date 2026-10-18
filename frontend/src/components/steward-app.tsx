"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CaretRight, Cube, Play, SpinnerGap, X } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import type { Job, Property, Workspace } from "../../../shared/types";
import { ErrorState, JobBanner, Loading, errorMessage } from "./ui";
import LibraryPanel from "./library-panel";
import AgentPanel from "./agent-panel";
import { useChanges, useFacts } from "@/lib/reality";
import { requestId, siteList, toSiteId } from "@/lib/site";
import "../app/dash.css";
import { AttestationDrawer, AttestationsPanel, ContractorReply, FactsPanel, OwnerDecision, WorkItemsPanel } from "./dash/rail";
import { Timeline } from "./dash/timeline";
import "./dash/dash.css";

const PlantRoom = dynamic(() => import("./scene").then(m => m.PlantRoom), { ssr: false, loading: () => <Loading label="Preparing the twin" /> });
const CameraWall = dynamic(() => import("./scene").then(m => m.CameraWall), { ssr: false, loading: () => <Loading label="Opening inspection cameras" /> });
type View = "twin" | "inspection" | "library" | "agents";

export default function StewardApp() {
  const [view, setView] = useState<View>("twin");
  const [properties, setProperties] = useState<Property[]>([]);
  const [propertyId, setPropertyId] = useState("harbor-works");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>("pump-01");
  const [cameraTarget, setCameraTarget] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [sourceId, setSourceId] = useState<string | undefined>();
  const [sourcePage, setSourcePage] = useState(1);
  const [attestationId, setAttestationId] = useState<string | null>(null);
  const propertyRef = useRef(propertyId);
  propertyRef.current = propertyId;

  const refresh = useCallback(async (id: string = propertyId) => {
    const next = await api.workspace(id);
    if (propertyRef.current !== id) return;
    setWorkspace(next);
  }, [propertyId]);

  /* Legacy views under the new shell: /app?view=inspection|library|agents&site=<id>. The site ID in the URL is the new one; requests use whichever the backend lists. */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const v = params.get("view"); if (v === "twin" || v === "inspection" || v === "library" || v === "agents") setView(v);
    const wanted = toSiteId(params.get("site"));
    api.properties().then(list => { setProperties(list); setPropertyId(requestId(wanted, list)); }).catch(e => { setNotice(errorMessage(e)); setPropertyId(wanted); });
  }, []);
  const sites = useMemo(() => siteList(properties), [properties]);
  useEffect(() => {
    let alive = true;
    setLoading(true); setLoadError(""); setWorkspace(null); setActiveJob(null);
    api.workspace(propertyId).then(next => { if (alive) { setWorkspace(next); setActiveJob(next.activeJob); } }).catch(e => { if (alive) setLoadError(errorMessage(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [propertyId]);

  const jobRunning = activeJob?.status === "running" || activeJob?.status === "queued";
  useEffect(() => {
    if (!activeJob || !jobRunning) return;
    let alive = true; let polling = false;
    const poll = async () => {
      if (polling) return; polling = true;
      try { const next = await api.job(activeJob.id); if (!alive) return; setActiveJob(next); await refresh(); }
      catch (e) { if (alive) setNotice(errorMessage(e)); }
      finally { polling = false; }
    };
    const timer = setInterval(poll, 1300);
    return () => { alive = false; clearInterval(timer); };
  }, [activeJob?.id, jobRunning, refresh]);

  const changes = useChanges(propertyId);
  const facts = useFacts(propertyId);
  const reloadReality = useCallback(() => { changes.reload(); facts.reload(); refresh().catch(() => {}); }, [changes.reload, facts.reload, refresh]); // eslint-disable-line react-hooks/exhaustive-deps
  const lastVersion = useRef(0);
  useEffect(() => { const v = changes.data?.version ?? 0; if (v !== lastVersion.current) { lastVersion.current = v; facts.reload(); refresh().catch(() => {}); } }, [changes.data?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  async function inspect() {
    if (jobRunning || actionBusy) return;
    setActionBusy(true);
    try { setActiveJob(await api.inspect(propertyId)); await refresh(); }
    catch (e) { setNotice(errorMessage(e)); }
    finally { setActionBusy(false); }
  }

  const focus = useCallback((id: string) => {
    setSelectedId(id); setView("twin");
    setCameraTarget(prev => { if (prev === id) { requestAnimationFrame(() => setCameraTarget(id)); return null; } return id; });
  }, []);
  const tagToId = useMemo(() => new Map((workspace?.components ?? []).map(c => [c.tag, c.id])), [workspace?.components]);
  function openSource(id: string, page = 1) { setSourceId(id); setSourcePage(page); setView("library"); }
  const property = workspace?.property ?? properties.find(p => p.id === propertyId);
  const running = Boolean(jobRunning);

  return <div className={`dash app-shell view-${view}`}>
    <header className="dash-bar">
      <Link href="/app/environment" className="wordmark">Steward <small>{sites.find(s => s.id === toSiteId(propertyId))?.name ?? property?.name ?? ""}</small></Link>
      <nav className="dash-nav" aria-label="Views">
        <Link href={`/app/environment?site=${toSiteId(propertyId)}`} className="btn btn-quiet btn-small" style={{ color: "var(--muted)" }}>Dashboard</Link>
        {([{ id: "twin", label: "Twin" }, { id: "inspection", label: "Inspection wall" }, { id: "library", label: "Library" }, { id: "agents", label: "Agent chat" }] as const).map(item => <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}>{item.label}{item.id === "agents" && running ? " ·" : ""}</button>)}
      </nav>
      <div className="right">
        <span className={`transport ${changes.transport}`}>{changes.transport === "realtime" ? "Supabase realtime" : changes.readiness === "ready" ? "polling" : ""}</span>
        <select aria-label="Select site" value={toSiteId(propertyId)} onChange={e => { setPropertyId(requestId(toSiteId(e.target.value), properties)); setSourceId(undefined); setSourcePage(1); setCameraTarget(null); setSelectedId(null); }}>{sites.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      </div>
    </header>

    {notice ? <div className="dash-notice" role="alert"><span>{notice}</span><button className="btn btn-quiet btn-small" aria-label="Dismiss message" onClick={() => setNotice("")}><X size={14} /></button></div> : null}
    <main className="dash-main">
      {loading ? <Loading /> : loadError ? <ErrorState message={loadError} retry={() => { setLoading(true); setLoadError(""); refresh().catch(e => setLoadError(errorMessage(e))).finally(() => setLoading(false)); }} /> : workspace ? <>
        {view === "twin" ? <div className="twin-view">
          <div className="twin-stage">
            <PlantRoom components={workspace.components} selectedId={selectedId} onSelect={setSelectedId} showMarkers showGuides={false} viewMode="orbit" cameraTarget={cameraTarget} showControls={false} />
            <TwinFocus workspace={workspace} selectedId={selectedId} facts={facts.data ?? []} waiting={changes.data?.waiting ?? []} />
            <div className="twin-tools"><button onClick={() => setCameraTarget(`reset-${Date.now()}`)}>Reset view</button><button onClick={inspect} disabled={actionBusy || running}>{running ? "Patrolling" : "Run patrol"}</button></div>
          </div>
          <Timeline changes={changes.data?.changes ?? []} version={changes.data?.version ?? 0} readiness={changes.readiness} error={changes.error} reload={changes.reload} transport={changes.transport} onTag={tag => { const id = tagToId.get(tag); if (id) focus(id); }} />
          <aside className="rail">
            <WorkItemsPanel items={changes.data?.waiting ?? []} readiness={changes.readiness} error={changes.error} reload={changes.reload} onFocus={focus} selectedId={selectedId} onChanged={reloadReality} />
            <FactsPanel facts={facts.data ?? []} readiness={facts.readiness} error={facts.error} reload={facts.reload} onFocus={focus} selectedId={selectedId} onOpenAttestation={setAttestationId} />
            <AttestationsPanel facts={facts.data ?? []} items={changes.data?.waiting ?? []} changes={changes.data?.changes ?? []} onOpen={setAttestationId} />
            <ContractorReply items={changes.data?.waiting ?? []} onChanged={reloadReality} />
            <OwnerDecision propertyId={propertyId} items={changes.data?.waiting ?? []} onChanged={reloadReality} />
          </aside>
        </div> : null}
        {view === "inspection" ? <section className="inspection-page legacy-view"><div className="dark-page-header"><div>{/* taste-skill-ignore: legacy secondary view, restyled to sentence case in legacy.css */}<div className="eyebrow"><button onClick={() => setView("twin")}>Steward</button><CaretRight size={11} />Spatial inspection</div><h1>Plant room inspection wall <span>{sites.find(s => s.id === toSiteId(propertyId))?.name ?? property?.name}</span></h1></div><div className="header-actions"><span className="technical-tag">12 survey viewpoints · {workspace.components.length} components</span><button className="button dark-ghost" onClick={() => setView("twin")}><Cube size={14} />Twin</button><button className="button button-light" onClick={inspect} disabled={actionBusy || running}>{running ? <SpinnerGap className="spin" size={14} /> : <Play size={13} weight="fill" />}{running ? "Inspecting" : "Run inspection"}</button></div></div><JobBanner job={activeJob} /><div className="inspection-content"><div className="camera-wall"><CameraWall components={workspace.components} onSelect={focus} running={running} /></div></div></section> : null}
        {view === "library" ? <div className="legacy-view"><LibraryPanel propertyId={propertyId} workspace={workspace} sourceId={sourceId} sourcePage={sourcePage} onExplore={() => setView("twin")} onComponent={focus} onUpdated={() => refresh()} onError={setNotice} /></div> : null}
        {view === "agents" ? <div className="legacy-view"><AgentPanel propertyId={propertyId} workspace={workspace} job={activeJob} onJob={setActiveJob} onRefresh={() => refresh()} onComponent={focus} onSource={openSource} onError={setNotice} /></div> : null}
      </> : null}
    </main>
    {attestationId ? <AttestationDrawer id={attestationId} onClose={() => setAttestationId(null)} /> : null}
  </div>;
}

function TwinFocus({ workspace, selectedId, facts, waiting }: { workspace: Workspace; selectedId: string | null; facts: { componentId: string; attribute: string; value: string | number | boolean; unit?: string | null; status?: string }[]; waiting: { componentId: string; state: string; reference: string }[] }) {
  const component = workspace.components.find(c => c.id === selectedId);
  if (!component) return null;
  const own = facts.filter(f => f.componentId === component.id);
  const items = waiting.filter(w => w.componentId === component.id && !["resolved", "rejected", "expired"].includes(w.state));
  return <div className="twin-focus">
    <span className="tag">{component.tag}</span>
    <span className="name">{component.name}</span>
    <span className="line">{component.system} / {component.subsystem}</span>
    <span className="line">{own.length ? own.map(f => <span key={f.attribute}><b>{f.attribute.replace(/_/g, " ")}</b> {String(f.value)}{f.unit ? ` ${f.unit}` : ""}{f.status ? ` (${f.status})` : ""}  </span>) : "no facts on record"}</span>
    {items.length ? <span className="line">{items.length} open work {items.length === 1 ? "item" : "items"}: <span className="mono">{items.map(w => w.reference).join(", ")}</span></span> : null}
  </div>;
}
