"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowClockwise, ArrowDown, ArrowSquareOut, BookOpenText, Buildings, CaretDown, CaretRight, Check, CheckCircle, Crosshair, Cube, Eye, FileText, GridFour, Info, Keyboard, MagnifyingGlass, MapPin, Play, Plus, Robot, SpinnerGap, UploadSimple, WarningCircle, X } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import type { Component, ComponentDetail, Job, Property, Workspace } from "../../../shared/types";
import { EmptyState, ErrorState, JobBanner, Loading, ProgressBar, StatusDot, errorMessage, formatDate, useModal } from "./ui";
import LibraryPanel from "./library-panel";
import AgentPanel from "./agent-panel";

const PlantRoom = dynamic(() => import("./scene").then(m => m.PlantRoom), { ssr: false, loading: () => <Loading label="Preparing spatial workspace" /> });
const CameraWall = dynamic(() => import("./scene").then(m => m.CameraWall), { ssr: false, loading: () => <Loading label="Opening inspection cameras" /> });
type View = "workspace" | "inspection" | "library" | "agents";

export default function StewardApp() {
  const [view, setView] = useState<View>("workspace");
  const [properties, setProperties] = useState<Property[]>([]);
  const [propertyId, setPropertyId] = useState("cedar");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>("pump-01");
  const [requestedFocusId, setRequestedFocusId] = useState<string | null>(null);
  const consumeFocusRequest = useCallback(() => setRequestedFocusId(null), []);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [sourceId, setSourceId] = useState<string | undefined>();
  const [sourcePage, setSourcePage] = useState(1);
  const propertyRef = useRef(propertyId);
  propertyRef.current = propertyId;

  const refresh = useCallback(async (id: string = propertyId) => {
    const next = await api.workspace(id);
    if (propertyRef.current !== id) return;
    setWorkspace(next);
  }, [propertyId]);

  useEffect(() => { api.properties().then(setProperties).catch(e => setNotice(errorMessage(e))); }, []);
  useEffect(() => {
    let alive = true;
    setLoading(true); setLoadError(""); setWorkspace(null); setActiveJob(null);
    api.workspace(propertyId).then(next => { if (alive) { setWorkspace(next); setActiveJob(next.activeJob); } }).catch(e => { if (alive) setLoadError(errorMessage(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [propertyId]);

  const jobRunning = activeJob?.status === "running" || activeJob?.status === "queued";
  useEffect(() => {
    if (!activeJob || !jobRunning) return;
    let alive = true;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await api.job(activeJob.id);
        if (!alive) return;
        setActiveJob(next);
        await refresh();
      } catch (e) { if (alive) setNotice(errorMessage(e)); }
      finally { polling = false; }
    };
    const timer = setInterval(poll, 1300);
    return () => { alive = false; clearInterval(timer); };
  }, [activeJob?.id, jobRunning, refresh]);

  async function inspect() {
    if (jobRunning || actionBusy) return;
    setActionBusy(true);
    try { setActiveJob(await api.inspect(propertyId)); await refresh(); }
    catch (e) { setNotice(errorMessage(e)); }
    finally { setActionBusy(false); }
  }

  function openSource(id: string, page = 1) { setSourceId(id); setSourcePage(page); setView("library"); }
  function selectComponent(id: string) { setSelectedId(id); setRequestedFocusId(id); setView("workspace"); }
  const property = workspace?.property ?? properties.find(p => p.id === propertyId);
  const running = Boolean(jobRunning);

  return <div className={`app-shell view-${view}`}>
    <header className="app-header">
      <button className="brand" onClick={() => setView("workspace")} aria-label="Steward home"><span>Steward</span></button>
      <nav className="main-nav" aria-label="Main navigation">
        {([{ id: "workspace", label: "Workspace", icon: Cube }, { id: "inspection", label: "Inspection wall", icon: GridFour }, { id: "library", label: "Codes & standards", icon: BookOpenText }, { id: "agents", label: "Agents", icon: Robot }] as const).map(item => <button key={item.id} aria-label={item.label} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}><item.icon size={16} /><span>{item.label}</span>{item.id === "agents" && running ? <span className="nav-running" /> : null}</button>)}
      </nav>
      <div className="header-right"><span className="local-indicator"><span />Local workspace</span><label className="property-switch"><Buildings size={15} /><select aria-label="Select property" value={propertyId} onChange={e => { setPropertyId(e.target.value); setSourceId(undefined); setSourcePage(1); setRequestedFocusId(null); }}>{properties.length ? properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>) : <option value="cedar">Cedar House</option>}</select><CaretDown size={12} /></label><div className="user-avatar" title="Local property portfolio">AM</div></div>
    </header>

    {notice ? <div className="notice-banner" role="alert"><WarningCircle size={16} /><span>{notice}</span><button aria-label="Dismiss message" onClick={() => setNotice("")}><X size={15} /></button></div> : null}
    <main className="app-main">
      {loading ? <Loading /> : loadError ? <ErrorState message={loadError} retry={() => { setLoading(true); setLoadError(""); refresh().catch(e => setLoadError(errorMessage(e))).finally(() => setLoading(false)); }} /> : workspace ? <>
        {view === "workspace" ? <SpatialWorkspace workspace={workspace} selectedId={selectedId} requestedFocusId={requestedFocusId} onFocusConsumed={consumeFocusRequest} onSelect={setSelectedId} onLibrary={() => { setSourceId(undefined); setSourcePage(1); setView("library"); }} onSource={openSource} onInspection={() => setView("inspection")} onRefresh={() => refresh()} job={activeJob} onError={setNotice} /> : null}
        {view === "inspection" ? <section className="inspection-page"><div className="dark-page-header"><div><div className="eyebrow"><button onClick={() => setView("workspace")}>Steward</button><CaretRight size={11} />Spatial inspection</div><h1>Plant room inspection wall <span>{property?.name}</span></h1></div><div className="header-actions"><span className="technical-tag">12 survey viewpoints · {workspace.components.length} components</span><button className="button dark-ghost" onClick={() => setView("workspace")}><Cube size={14} />Explore room</button><button className="button button-light" onClick={inspect} disabled={actionBusy || running}>{running ? <SpinnerGap className="spin" size={14} /> : <Play size={13} weight="fill" />}{running ? "Inspecting" : "Run inspection"}</button></div></div><JobBanner job={activeJob} /><div className="inspection-content"><div className="camera-wall"><CameraWall components={workspace.components} onSelect={selectComponent} running={running} /></div></div></section> : null}
        {view === "library" ? <LibraryPanel propertyId={propertyId} workspace={workspace} sourceId={sourceId} sourcePage={sourcePage} onExplore={() => setView("workspace")} onComponent={selectComponent} onUpdated={() => refresh()} onError={setNotice} /> : null}
        {view === "agents" ? <AgentPanel propertyId={propertyId} workspace={workspace} job={activeJob} onJob={setActiveJob} onRefresh={() => refresh()} onComponent={selectComponent} onSource={openSource} onError={setNotice} /> : null}
      </> : null}
    </main>
  </div>;
}

function SpatialWorkspace({ workspace, selectedId, requestedFocusId, onFocusConsumed, onSelect, onLibrary, onSource, onInspection, onRefresh, job, onError }: { workspace: Workspace; selectedId: string | null; requestedFocusId: string | null; onFocusConsumed: () => void; onSelect: (id: string | null) => void; onLibrary: () => void; onSource: (id: string, page?: number) => void; onInspection: () => void; onRefresh: () => Promise<void>; job: Job | null; onError: (s: string) => void }) {
  const [search, setSearch] = useState("");
  const [system, setSystem] = useState("All");
  const [status, setStatus] = useState("all");
  const [showMarkers, setShowMarkers] = useState(true);
  const [showGuides, setShowGuides] = useState(false);
  const [viewMode, setViewMode] = useState<"orbit" | "walk">("orbit");
  const [resetCount, setResetCount] = useState(0);
  const [sidebar, setSidebar] = useState(true);
  const [detail, setDetail] = useState<ComponentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [detailTab, setDetailTab] = useState<"requirements" | "evidence">("requirements");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [purchaseOpen, setPurchaseOpen] = useState(false);
  const [focusTarget, setFocusTarget] = useState<string | null>(requestedFocusId);
  useEffect(() => {
    if (!requestedFocusId) return;
    setFocusTarget(requestedFocusId);
    onFocusConsumed();
  }, [requestedFocusId, onFocusConsumed]);
  const [helpOpen, setHelpOpen] = useState(false);
  useModal(helpOpen, () => setHelpOpen(false));
  const systems = useMemo(() => ["All", ...new Set(workspace.components.map(c => c.system))], [workspace.components]);
  const filtered = useMemo(() => workspace.components.filter(c => (system === "All" || c.system === system) && (status === "all" || c.status === status) && `${c.name} ${c.tag} ${c.kind} ${c.subsystem}`.toLowerCase().includes(search.toLowerCase())), [workspace.components, system, status, search]);
  const verified = workspace.stats.total ? Math.round(workspace.stats.verified / workspace.stats.total * 100) : 0;
  const loadDetail = useCallback(async () => {
    if (!selectedId) { setDetail(null); return; }
    setDetailLoading(true); setDetailError("");
    try { setDetail(await api.component(workspace.property.id, selectedId)); }
    catch (e) { setDetailError(errorMessage(e)); }
    finally { setDetailLoading(false); }
  }, [selectedId, workspace.property.id]);
  useEffect(() => { let alive = true; if (!selectedId) { setDetail(null); return; } setDetailLoading(true); setDetailError(""); api.component(workspace.property.id, selectedId).then(d => { if (alive) setDetail(d); }).catch(e => { if (alive) setDetailError(errorMessage(e)); }).finally(() => { if (alive) setDetailLoading(false); }); return () => { alive = false; }; }, [selectedId, workspace.property.id, workspace.stats.verified, workspace.stats.pending, workspace.stats.issue]);
  function select(id: string) { onSelect(id); setFocusTarget(id); }

  return <section className="spatial-page">
    <div className="scene-container"><PlantRoom components={workspace.components} selectedId={selectedId} onSelect={select} showMarkers={showMarkers} showGuides={showGuides} viewMode={viewMode} cameraTarget={focusTarget ?? `reset-${resetCount}`} showControls={false} /></div>
    <div className="scene-shade" />
    <div className="workspace-top"><div><div className="scene-breadcrumb"><MapPin size={12} />{workspace.property.name}<CaretRight size={10} />Plant room</div><h1>Visual workspace <span>Spatial inspection</span></h1></div><div className="workspace-toolbar"><button className={`scene-button ${sidebar ? "selected" : ""}`} onClick={() => setSidebar(!sidebar)}><Cube size={13} />Components <span>{workspace.components.length}</span></button><button className={`scene-button ${showMarkers ? "selected" : ""}`} onClick={() => setShowMarkers(!showMarkers)}><Eye size={13} />Markers</button><button className={`scene-button ${showGuides ? "selected" : ""}`} onClick={() => setShowGuides(!showGuides)}><Crosshair size={13} />Clearance</button><button className="scene-button light" onClick={onLibrary}><BookOpenText size={13} />Codes & standards <span>{workspace.requirements.length}</span><ArrowSquareOut size={11} /></button></div></div>
    {sidebar ? <aside className="component-panel glass-panel"><div className="panel-heading"><div className="eyebrow">Plant room survey</div><div className="panel-title-row"><h2>Components <span>{workspace.components.length}</span></h2><button className="icon-button" title="Hide component list" aria-label="Hide component list" onClick={() => setSidebar(false)}><ArrowDown size={14} /></button></div><p>{workspace.components.length} mapped in the scene</p></div><div className="readiness-box"><div><span>Evidence verified</span><strong>{verified}<small>%</small></strong></div><ProgressBar value={verified} /><div className="readiness-labels"><span>{workspace.stats.verified} verified</span><span>{workspace.stats.pending + workspace.stats.issue + workspace.stats.unknown} remaining</span></div></div><div className="component-controls"><label className="search-input dark-search"><MagnifyingGlass size={14} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Find name, code or object #" aria-label="Search components" />{search ? <button onClick={() => setSearch("")} aria-label="Clear component search"><X size={12} /></button> : null}</label><div className="filter-pills">{systems.map(s => <button key={s} onClick={() => setSystem(s)} className={system === s ? "active" : ""}>{s}</button>)}</div><div className="list-options"><span><Eye size={12} />{filtered.length} matches</span><select aria-label="Filter component status" value={status} onChange={e => setStatus(e.target.value)}><option value="all">All statuses</option><option value="verified">Verified</option><option value="pending">Pending</option><option value="issue">Needs attention</option><option value="unknown">Not assessed</option></select></div></div><div className="component-list">{filtered.map(c => <button className={`component-row ${selectedId === c.id ? "active" : ""}`} key={c.id} onClick={() => select(c.id)}><span className={`component-tag status-${c.status}`}>{c.tag}</span><div className="component-row-text"><strong>{c.kind.charAt(0).toUpperCase() + c.kind.slice(1)}</strong><span>{c.system} / {c.subsystem}</span></div><div className="component-row-status"><StatusDot status={c.status} /><span>{Math.round(c.confidence * 100)}% match</span></div></button>)}{filtered.length === 0 ? <EmptyState title="No matching components">Try another name or filter.</EmptyState> : null}</div><button className="panel-footer-button" onClick={onInspection}><GridFour size={14} />Open inspection wall <ArrowSquareOut size={12} /></button></aside> : null}

    {selectedId ? <aside className="detail-panel glass-panel"><div className="panel-heading"><div className="detail-topline"><span className="eyebrow">Component / {detail?.tag ?? selectedId}</span><button className="icon-button" onClick={() => onSelect(null)} aria-label="Close component details"><X size={16} /></button></div><h2>{detail?.name ?? "Component"}</h2><p>{detail?.system} / {detail?.subsystem}</p></div>{detailLoading ? <Loading label="Loading component" /> : detailError ? <ErrorState message={detailError} retry={loadDetail} /> : detail ? <><div className={`detail-status-box status-${detail.status}`}><div><strong>{detail.status === "verified" ? "Evidence verified" : detail.status === "issue" ? "Requires attention" : "Evidence pending"}</strong><span>{detail.verifiedCount} of {detail.requirements.length} related requirements verified</span></div><StatusDot status={detail.status} /></div><div className="detail-metadata"><div><span>Component code</span><strong className="mono">{detail.tag}</strong></div><div><span>Identification</span><strong>Mapped · {Math.round(detail.confidence * 100)}%</strong></div><div><span>Observations</span><strong>{detail.evidence.length}</strong></div><div><span>Location</span><strong className="mono">{detail.position.map(v => v.toFixed(1)).join(", ")}</strong></div></div><div className="detail-tabs"><button className={detailTab === "requirements" ? "active" : ""} onClick={() => setDetailTab("requirements")}>Requirements <span>{detail.requirements.length}</span></button><button className={detailTab === "evidence" ? "active" : ""} onClick={() => setDetailTab("evidence")}>Evidence <span>{detail.evidence.length}</span></button></div><div className="detail-scroll">{detailTab === "requirements" ? <div className="related-requirements">{detail.requirements.map(r => <button className="related-requirement" key={r.id} onClick={() => onSource(r.sourceId, r.sourcePage)}><div><span className="mono">{r.code}</span><StatusDot status={r.status} label /></div><strong>{r.title}</strong><span className="requirement-source">{r.sourceTitle} · p. {r.sourcePage}</span></button>)}</div> : <div className="evidence-list">{detail.evidence.length ? detail.evidence.map(e => <a href={e.url} target="_blank" rel="noreferrer" className="evidence-item" key={e.id}><FileText size={17} /><div><strong>{e.filename}</strong><span>{e.note || "Attached source evidence"}</span><small>{formatDate(e.createdAt)}</small></div><StatusDot status={e.status} /></a>) : <EmptyState icon={<FileText size={23} />} title="No attached evidence">Attach an observation or document to a specific requirement.</EmptyState>}<button className="button dark-ghost wide" onClick={() => setUploadOpen(true)}><UploadSimple size={14} />Add evidence</button></div>}<div className="component-description"><span className="eyebrow">About this component</span><p>{detail.description}</p></div></div><div className="detail-footer"><button className="button button-light wide" onClick={onLibrary}>Explore codes & standards <ArrowSquareOut size={12} /></button><div className="detail-footer-links"><button onClick={() => { setDetailTab("evidence"); setUploadOpen(true); }}><Plus size={12} />Evidence</button><button onClick={() => setPurchaseOpen(true)}>Purchase proposal <ArrowSquareOut size={11} /></button></div></div></> : null}</aside> : null}

    <div className="workspace-bottom"><div className="keyboard-help"><Keyboard size={16} /><div><strong>{viewMode === "walk" ? "Explore with your keyboard" : "Explore the spatial record"}</strong><span>{viewMode === "walk" ? "W A S D to move · Mouse to look · Shift for faster" : "Drag to orbit · Scroll to zoom · Select a marker to inspect"}</span></div><button className="text-button" onClick={() => setHelpOpen(true)}>Help</button></div><div className="bottom-controls"><div className="segmented-control"><button className={viewMode === "orbit" ? "active" : ""} onClick={() => setViewMode("orbit")}><Cube size={13} />Orbit</button><button className={viewMode === "walk" ? "active" : ""} onClick={() => setViewMode("walk")}><MapPin size={13} />Walk</button></div><button className="scene-button" onClick={() => { setFocusTarget(null); setResetCount(v => v + 1); }}><ArrowClockwise size={13} />Reset view</button></div></div>
    {job ? <div className="workspace-job"><JobBanner job={job} /></div> : null}
    <div className="scene-disclosure"><span className="status-dot" />Original scene · Local evidence</div>
    {uploadOpen && detail ? <EvidenceDialog propertyId={workspace.property.id} component={detail} onClose={() => setUploadOpen(false)} onSaved={async () => { setUploadOpen(false); await onRefresh(); await loadDetail(); }} onError={onError} /> : null}
    {purchaseOpen && detail ? <PurchaseDialog propertyId={workspace.property.id} component={detail} onClose={() => setPurchaseOpen(false)} onError={onError} /> : null}
    {helpOpen ? <div className="modal-backdrop" onClick={() => setHelpOpen(false)}><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="help-title" onClick={e => e.stopPropagation()}><div className="dialog-heading"><h2 id="help-title">Explore the workspace</h2><button className="icon-button" onClick={() => setHelpOpen(false)} aria-label="Close help"><X size={18} /></button></div><p>The mechanical room is an original 3D model with mapped equipment. Select an object or marker to inspect its requirements and attached evidence.</p><div className="help-controls"><div><kbd>Drag</kbd><span>Orbit around the room</span></div><div><kbd>Scroll</kbd><span>Zoom in or out</span></div><div><kbd>W A S D</kbd><span>Move in Walk mode</span></div><div><kbd>Shift</kbd><span>Move faster in Walk mode</span></div></div><div className="dialog-note"><Info size={15} />Local example requirements demonstrate evidence workflows. They are not statutory certification.</div><button className="button button-primary wide" onClick={() => setHelpOpen(false)}>Continue exploring</button></section></div> : null}
  </section>;
}

function EvidenceDialog({ propertyId, component, onClose, onSaved }: { propertyId: string; component: ComponentDetail; onClose: () => void; onSaved: () => Promise<void>; onError: (s: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [requirementId, setRequirementId] = useState(component.requirements[0]?.id ?? "");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useModal(true, onClose);
  async function submit(e: React.FormEvent) { e.preventDefault(); if (!file || !requirementId) return; if (!file.size || file.size > 10 * 1024 * 1024) { setError("Choose a non-empty evidence file up to 10 MB."); return; } setSaving(true); setError(""); try { await api.uploadEvidence(propertyId, file, component.id, requirementId, note); await onSaved(); } catch (e) { setError(errorMessage(e)); } finally { setSaving(false); } }
  return <div className="modal-backdrop" onClick={() => !saving && onClose()}><form className="dialog" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="evidence-title" onClick={e => e.stopPropagation()}><div className="dialog-heading"><div><div className="eyebrow">{component.tag} / Evidence</div><h2 id="evidence-title">Attach source evidence</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close upload"><X size={18} /></button></div><p>Link an observation to the equipment and requirement it supports. The local pipeline checks and records the attachment.</p><label className="field-label">Requirement<select value={requirementId} onChange={e => setRequirementId(e.target.value)} required>{component.requirements.map(r => <option value={r.id} key={r.id}>{r.code} — {r.title}</option>)}</select></label><label className={`upload-drop ${file ? "has-file" : ""}`}><UploadSimple size={26} /><strong>{file?.name ?? "Choose an evidence file"}</strong><span>PDF, image, text, JSON, or CSV · Up to 10 MB</span><input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.json,.csv" onChange={e => setFile(e.target.files?.[0] ?? null)} required /></label><label className="field-label">Observation note<textarea rows={3} placeholder="What does this file demonstrate?" value={note} onChange={e => setNote(e.target.value)} /></label>{error ? <div className="inline-error" role="alert"><WarningCircle size={15} />{error}</div> : null}<div className="dialog-actions"><button className="button" type="button" onClick={onClose}>Cancel</button><button className="button button-primary" type="submit" disabled={saving || !file || !requirementId}>{saving ? <SpinnerGap className="spin" size={15} /> : <UploadSimple size={15} />}{saving ? "Attaching" : "Attach evidence"}</button></div></form></div>;
}

function PurchaseDialog({ propertyId, component, onClose }: { propertyId: string; component: Component; onClose: () => void; onError: (s: string) => void }) {
  const [description, setDescription] = useState(""); const [amount, setAmount] = useState(""); const [busy, setBusy] = useState(false); const [saved, setSaved] = useState(false); const [error, setError] = useState("");
  useModal(true, onClose);
  async function submit(e: React.FormEvent) { e.preventDefault(); setBusy(true); setError(""); try { await api.createPurchase(propertyId, { componentId: component.id, description, amount: Number(amount), currency: "USD" }); setSaved(true); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  return <div className="modal-backdrop" onClick={() => !busy && onClose()}><form className="dialog" role="dialog" aria-modal="true" aria-labelledby="purchase-title" onSubmit={submit} onClick={e => e.stopPropagation()}><div className="dialog-heading"><div><div className="eyebrow">{component.tag} / Procurement</div><h2 id="purchase-title">Purchase proposal</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close proposal"><X size={18} /></button></div>{saved ? <div className="success-state"><CheckCircle size={40} /><h3>Proposal recorded</h3><p>The request is saved in this property’s procurement record. No payment or external order has been made.</p><button className="button button-primary" onClick={onClose} type="button">Done</button></div> : <><p>Create a traceable request linked to this component. Local proposals do not charge a card or place an order.</p><label className="field-label">Item or service<textarea value={description} onChange={e => setDescription(e.target.value)} rows={3} required placeholder="Describe the part or service needed" /></label><label className="field-label">Estimated amount (USD)<input type="number" min="0.01" step="0.01" required value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" /></label>{error ? <div className="inline-error" role="alert">{error}</div> : null}<div className="dialog-actions"><button className="button" type="button" onClick={onClose}>Cancel</button><button className="button button-primary" type="submit" disabled={busy}>{busy ? <SpinnerGap className="spin" size={14} /> : <Check size={14} />}Save proposal</button></div></>}</form></div>;
}
