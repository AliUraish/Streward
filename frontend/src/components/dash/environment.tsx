"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Workspace } from "../../../../shared/types";
import { api } from "@/lib/api";
import { useChanges, useFacts, useIssues, useRemote } from "@/lib/reality";
import type { Environment, Issue, IssueKind } from "@/lib/types-2";
import { Loading, errorMessage } from "../ui";
import { AttestationDrawer, AttestationsPanel, ContractorReply, FactsPanel, NotReady, OwnerDecision, Panel, WorkItemsPanel } from "./rail";
import { Timeline } from "./timeline";
import { useSite } from "./shell";

const PlantRoom = dynamic(() => import("../scene").then(m => m.PlantRoom), { ssr: false, loading: () => <Loading label="Preparing the twin" /> });

/* Caption for the frame strip. Frames are rendered from the hosted SuperSplat capture by headless Chrome; see DESIGN-DECISION.md. */
const FRAME_CAPTION = "frames rendered from the hosted capture";
const kindWord: Record<IssueKind, string> = { out_of_range: "out of range", rejected_evidence: "rejected evidence", overdue: "overdue", unknown_identity: "unknown identity", escalated: "escalated" };

export default function EnvironmentView() {
  const { siteId, requestId, sites, notify } = useSite();
  const site = sites.find(s => s.id === siteId)!;
  const env = site.environment;
  const workspace = useRemote<Workspace>(() => api.workspace(requestId), [requestId], 0);
  const changes = useChanges(requestId);
  const facts = useFacts(requestId);
  const issues = useIssues(requestId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<string | null>(null);
  const [cameraTarget, setCameraTarget] = useState<string | null>(null);
  const [attestationId, setAttestationId] = useState<string | null>(null);
  const [patrolBusy, setPatrolBusy] = useState(false);
  useEffect(() => { setSelectedId(null); setSelectedIssue(null); setCameraTarget(null); }, [siteId]);

  const reloadReality = useCallback(() => { changes.reload(); facts.reload(); issues.reload(); workspace.reload(); }, [changes.reload, facts.reload, issues.reload, workspace.reload]); // eslint-disable-line react-hooks/exhaustive-deps
  const lastVersion = useRef(0);
  useEffect(() => { const v = changes.data?.version ?? 0; if (v !== lastVersion.current) { lastVersion.current = v; facts.reload(); issues.reload(); workspace.reload(); } }, [changes.data?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const focus = useCallback((componentId: string) => {
    setSelectedId(componentId);
    setCameraTarget(prev => { if (prev === componentId) { requestAnimationFrame(() => setCameraTarget(componentId)); return null; } return componentId; });
  }, []);
  const tagToId = useMemo(() => new Map((workspace.data?.components ?? []).map(c => [c.tag, c.id])), [workspace.data?.components]);
  const pickIssue = useCallback((issue: Issue) => { setSelectedIssue(issue.id); if (issue.componentId) focus(issue.componentId); }, [focus]);
  async function patrol() {
    setPatrolBusy(true);
    try { await api.patrol(requestId); reloadReality(); } catch (e) { notify(errorMessage(e)); } finally { setPatrolBusy(false); }
  }
  const waiting = changes.data?.waiting ?? [];
  const issueList = issues.data ?? [];

  return <div className="env">
    <div className="env-viewer">
      {env.kind === "fixture"
        ? (workspace.readiness === "ready" && workspace.data ? <>
            <div className="twin-mount"><PlantRoom components={workspace.data.components} selectedId={selectedId} onSelect={setSelectedId} showMarkers showGuides={false} viewMode="orbit" cameraTarget={cameraTarget} showControls={false} /></div>
            <TwinFocus workspace={workspace.data} selectedId={selectedId} facts={facts.data ?? []} waiting={waiting} />
            <div className="twin-tools"><button onClick={() => setCameraTarget(`reset-${Date.now()}`)}>Reset view</button><button onClick={patrol} disabled={patrolBusy}>{patrolBusy ? "Patrolling" : "Run patrol"}</button></div>
          </> : <div className="viewer-loading">{workspace.readiness === "loading" ? "Preparing the twin" : <span>{workspace.error || "Twin unavailable"} <button className="btn btn-small" style={{ pointerEvents: "auto", marginLeft: 8 }} onClick={workspace.reload}>Retry</button></span>}</div>)
        : <SplatViewer env={env} key={env.embedUrl} />}
      <PinLayer issues={issueList} selected={selectedIssue} onPick={pickIssue} />
    </div>
    <EnvCaption env={env} site={site.name} />
    {env.kind === "splat" ? <FrameStrip siteId={siteId} env={env} /> : null}
    <div className="env-panels">
      <WorkItemsPanel items={waiting} readiness={changes.readiness} error={changes.error} reload={changes.reload} onFocus={focus} selectedId={selectedId} onChanged={reloadReality} />
      <FactsPanel facts={facts.data ?? []} readiness={facts.readiness} error={facts.error} reload={facts.reload} onFocus={focus} selectedId={selectedId} onOpenAttestation={setAttestationId} />
      <AttestationsPanel facts={facts.data ?? []} items={waiting} changes={changes.data?.changes ?? []} onOpen={setAttestationId} />
    </div>
    <div className="env-timeline">
      <Timeline changes={changes.data?.changes ?? []} version={changes.data?.version ?? 0} readiness={changes.readiness} error={changes.error} reload={changes.reload} transport={changes.transport} onTag={tag => { const id = tagToId.get(tag); if (id) focus(id); }} />
    </div>
    <aside className="env-side">
      <IssuesPanel issues={issueList} readiness={issues.readiness} error={issues.error} reload={issues.reload} selected={selectedIssue} onPick={pickIssue} onOpenAttestation={setAttestationId} />
      <ContractorReply items={waiting} onChanged={reloadReality} />
      <OwnerDecision propertyId={requestId} items={waiting} onChanged={reloadReality} />
    </aside>
    {attestationId ? <AttestationDrawer id={attestationId} onClose={() => setAttestationId(null)} /> : null}
  </div>;
}

/* SuperSplat embed: a third-party capture hosted on superspl.at, shown as the site environment. Never ours. */
function SplatViewer({ env }: { env: Environment }) {
  const [loaded, setLoaded] = useState(false);
  if (!env.embedUrl) return <div className="viewer-loading">No environment embed for this site.</div>;
  return <>
    <iframe src={env.embedUrl} title="Site environment, hosted capture on SuperSplat" allow="fullscreen; xr-spatial-tracking" allowFullScreen loading="eager" onLoad={() => setLoaded(true)} />
    <div className={`viewer-loading ${loaded ? "done" : ""}`} aria-hidden={loaded}>Loading the hosted capture from SuperSplat</div>
  </>;
}
function EnvCaption({ env, site }: { env: Environment; site: string }) {
  return <div className="env-caption">
    <span className="kind">{env.kind === "splat" ? `Gaussian splat · ${site}` : `Fixture twin · ${site}`}</span>
    <span>{env.credit}</span>
    <span>{env.captureNote}</span>
    {env.embedUrl ? <a className="link" href={env.embedUrl} target="_blank" rel="noreferrer">Open on SuperSplat</a> : null}
  </div>;
}

/* Thumbnail first, then the four frames rendered by headless Chrome from the hosted viewer (frontend/public/env/<siteId>/). */
function FrameStrip({ siteId, env }: { siteId: string; env: Environment }) {
  const [missing, setMissing] = useState<Set<number>>(new Set());
  const hide = (i: number) => setMissing(prev => { const n = new Set(prev); n.add(i); return n; });
  return <figure className="env-frames panel">
    <div className="panel-head"><h2>Capture frames<span className="count"> {1 + 4 - missing.size}</span></h2></div>
    <div className="strip">
      {env.thumbnailUrl && !missing.has(0) ? <div className="frame"><img src={env.thumbnailUrl} alt="Thumbnail of the hosted capture" onError={() => hide(0)} /><span>thumbnail</span></div> : null}
      {[1, 2, 3, 4].filter(i => !missing.has(i)).map(i => <div className="frame" key={i}><img src={`/env/${siteId}/frame-${i}.jpg`} alt={`Frame ${i} rendered from the hosted capture`} onError={() => hide(i)} /><span>angle {i}</span></div>)}
    </div>
    <figcaption>{FRAME_CAPTION}</figcaption>
  </figure>;
}

/* 2-D pins from each issue's normalised pin; positions are seeded as approximate and labelled so. */
function PinLayer({ issues, selected, onPick }: { issues: Issue[]; selected: string | null; onPick: (i: Issue) => void }) {
  const pinned = issues.filter(i => i.pin && Number.isFinite(i.pin.x) && Number.isFinite(i.pin.y));
  if (!pinned.length) return null;
  return <div className="pins">
    {pinned.map(i => <button key={i.id} className={`pin ${i.severity} ${selected === i.id ? "selected" : ""}`} style={{ left: `${Math.min(100, Math.max(0, i.pin!.x * 100))}%`, top: `${Math.min(100, Math.max(0, i.pin!.y * 100))}%` }} onClick={() => onPick(i)} aria-label={`${i.assetTag}: ${i.summary}`} title={i.summary}><span className="pin-label">{i.assetTag} · {kindWord[i.kind] ?? i.kind}</span></button>)}
    <span className="pins-note">pins approximate</span>
  </div>;
}

export function IssuesPanel({ issues, readiness, error, reload, selected, onPick, onOpenAttestation }: { issues: Issue[]; readiness: "loading" | "ready" | "not_ready" | "error"; error: string; reload: () => void; selected: string | null; onPick: (i: Issue) => void; onOpenAttestation: (id: string) => void }) {
  const rows = useRef(new Map<string, HTMLDivElement>());
  useEffect(() => { if (selected) rows.current.get(selected)?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [selected]);
  const order = { high: 0, medium: 1, low: 2 };
  const sorted = [...issues].sort((a, b) => order[a.severity] - order[b.severity] || b.at.localeCompare(a.at));
  return <Panel title="Issues" count={issues.length || undefined}>
    <div className="panel-body">
      {sorted.length === 0 ? <NotReady readiness={readiness} error={error} reload={reload} empty="Nothing open. Issues come from out-of-range readings, rejected evidence, overdue or escalated work and assets with no identity on record." /> : null}
      {sorted.map(i => <div key={i.id} ref={el => { if (el) rows.current.set(i.id, el); else rows.current.delete(i.id); }} className={`row issue-row ${selected === i.id ? "selected" : ""}`}>
        <button className="top" style={{ width: "100%", textAlign: "left" }} onClick={() => onPick(i)}><span className="tag">{i.assetTag}<span className="kind-tag">{kindWord[i.kind] ?? i.kind}</span>{i.simulated ? <span className="sim-tag">simulated</span> : null}</span><span className={`sev ${i.severity}`}>{i.severity}</span></button>
        <div className="summary">{i.summary}</div>
        <div className="sub"><span>{new Date(i.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>{i.refId ? (i.kind === "rejected_evidence" ? <button className="link mono" onClick={() => onOpenAttestation(i.refId)}>{i.refId.slice(0, 16)}</button> : <a className="link mono" href={`/api/work-items/${encodeURIComponent(i.refId)}`} target="_blank" rel="noreferrer">{i.refId.slice(0, 16)}</a>) : null}</div>
      </div>)}
    </div>
  </Panel>;
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
