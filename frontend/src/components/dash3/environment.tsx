"use client";

/* /app/[site]/environment, the agent eye: the PlayCanvas scan in eye mode (the camera moves when agents drive it),
   the operating agent and its last action, the eye's frame strip, pins with hover cards and the asset drawer, the
   operator's pin placement, the viewer following focus_view commands, the capture strip and the valve inspections. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api3 } from "@/lib/api-3";
import { useEyeFeed, useIssues3, useObligations, useScene, useViewerCommands, useVision } from "@/lib/hooks-3";
import { SITES3, agentName, rn, site3 } from "@/lib/sites-3";
import type { Asset3, EyeFrame, Issue3, PinSeverity, SiteId3, ValveResult, ViewerCommand } from "@/lib/types-3";
import AssetDrawer from "./asset-drawer";
import MissionHud from "./mission";
import { useHudEvents } from "@/lib/live-3";
import ViewerSlot, { type ViewerFocus, type ViewerPin } from "./viewer-slot";
import { Btn, OperatorTag, PageHead, Reveal, State, SynthTag, ago, errorText, fx, useToast, words } from "./ui3";
import { markPoint, type WalkLabel } from "@/lib/api-7";
import { useLabels, useWalk } from "@/lib/hooks-7";
import { LabelDetail, WalkthroughBar, assessmentOf, followPose } from "./walkthrough";

export const tagOf = (a: Asset3) => a.tag ?? a.assetTag ?? "";
export const pinOf = (a: Asset3): [number, number, number] | null => !a.pin ? null : Array.isArray(a.pin) ? a.pin : [a.pin.x, a.pin.y, a.pin.z];
const RANK: Record<PinSeverity, number> = { none: 0, low: 1, medium: 2, high: 3 };
export const isOpenIssue = (i: Issue3) => !i.status || !["resolved", "closed"].includes(i.status);
export const valveWord: Record<ValveResult["status"], string> = { fixed: "fixed", not_fixed: "not fixed", uncertain: "uncertain" };

export default function EnvironmentPage({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  /* Contract 7: the walk now (every 3 s) and the label it left on each asset (every 5 s). While the engineer walks,
     the eye feed is read faster and the view follows its camera unless that is turned off. */
  const walk = useWalk(siteId);
  const labels = useLabels(siteId);
  const walking = Boolean(walk.data?.walking);
  const [followWalk, setFollowWalk] = useState(true);
  const eye = useEyeFeed(siteId, walking ? 1_500 : 3_000);
  const scene = useScene(siteId);
  const issues = useIssues3(siteId);
  const vision = useVision(siteId);
  const obligations = useObligations(siteId);
  const toast = useToast();
  const [focus, setFocus] = useState<ViewerFocus | null>(null);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [pending, setPending] = useState<[number, number, number] | null>(null);
  const [lastMove, setLastMove] = useState<string>("");
  /* Mission view: the scan fills the screen, the team's work floats over it as HUD panels. ?mission=1 opens it. */
  const [mission, setMission] = useState(false);
  const [hudHidden, setHudHidden] = useState(false);
  const [tick, setTick] = useState(() => Date.now());
  const hostRef = useRef<HTMLDivElement>(null);
  const closeMission = useCallback(() => { setMission(false); if (typeof document !== "undefined" && document.fullscreenElement) document.exitFullscreen().catch(() => {}); }, []);
  const openMission = () => { setMission(true); setHudHidden(false); hostRef.current?.requestFullscreen?.().catch(() => { /* a fixed full-window view is the fallback */ }); };
  useEffect(() => { if (new URLSearchParams(window.location.search).get("mission")) setMission(true); }, []);
  useEffect(() => {
    if (!mission) return;
    const id = window.setInterval(() => setTick(Date.now()), 1000);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") closeMission(); if (e.key === "h" && !(e.target instanceof HTMLInputElement)) setHudHidden(v => !v); };
    const fs = () => { if (!document.fullscreenElement) setMission(false); };
    const prev = document.documentElement.style.overflow; document.documentElement.style.overflow = "hidden";
    window.addEventListener("keydown", key); document.addEventListener("fullscreenchange", fs);
    return () => { window.clearInterval(id); window.removeEventListener("keydown", key); document.removeEventListener("fullscreenchange", fs); document.documentElement.style.overflow = prev; };
  }, [mission, closeMission]);

  const assets = useMemo(() => scene.data?.assets ?? [], [scene.data]);
  const openIssues = useMemo(() => (issues.data ?? []).filter(isOpenIssue), [issues.data]);
  const labelOf = useMemo(() => new Map<string, WalkLabel>((labels.data ?? []).map(l => [l.assetTag, l])), [labels.data]);
  const pins: ViewerPin[] = useMemo(() => assets.flatMap(a => {
    const p = pinOf(a); if (!p) return [];
    const tag = tagOf(a);
    const mine = openIssues.filter(i => i.assetTag === tag);
    const severity = mine.reduce<PinSeverity>((m, i) => RANK[i.severity] > RANK[m] ? i.severity : m, "none");
    const l = labelOf.get(tag);
    /* A labelled asset's marker sits where the engineer marked it (else at the label's own point); that point is seen,
       not estimated. */
    const at = l ? markPoint(l) : null;
    return [{ assetTag: tag, position: p, severity, label: `${tag} ${a.name}`, estimated: a.pinSource !== "placed" && !l?.mark?.world, issueIds: mine.map(i => i.id), ...(l ? { assessment: assessmentOf(l) } : {}), ...(at ? { mark: at } : {}) }];
  }), [assets, openIssues, labelOf]);
  /* A label on an asset the register has no pin for is drawn where the engineer marked it (else its world point). */
  const shownPins: ViewerPin[] = useMemo(() => {
    const have = new Set(pins.map(p => p.assetTag));
    const extra = (labels.data ?? []).filter(l => markPoint(l) && !have.has(l.assetTag)).map(l => ({ assetTag: l.assetTag, position: markPoint(l)!, severity: "none" as PinSeverity, label: `${l.assetTag}${l.assetName ? ` ${l.assetName}` : ""}`, estimated: !l.mark?.world, issueIds: [], assessment: assessmentOf(l) }));
    return extra.length ? [...pins, ...extra] : pins;
  }, [pins, labels.data]);
  const unpinned = assets.length - pins.length;
  const estimated = pins.filter(p => p.estimated).length;

  const focusOn = useCallback((assetTag: string | undefined, action: ViewerFocus["action"] = "focus") => setFocus({ assetTag, action, nonce: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}` }), []);
  const openAsset = useCallback((tag: string) => { focusOn(tag); setDrawer(tag); }, [focusOn]);
  /* ?asset=<tag> (from the factory overview's issue list) opens that asset. */
  useEffect(() => { const tag = new URLSearchParams(window.location.search).get("asset"); if (tag) openAsset(tag); }, [openAsset]);
  const frames = useMemo(() => [...(eye.data?.frames ?? [])].sort((a, b) => b.at.localeCompare(a.at)), [eye.data]);
  /* Realtime, when the bridge has a channel: reload what an event touches instead of waiting for the next poll. */
  useHudEvents(siteId, { eye_frame: () => eye.reload(), issue_change: () => issues.reload() });
  const lastFrame = frames[0] ?? null;
  const follow = useMemo(() => (followWalk ? followPose(frames, walk.data) : null), [followWalk, frames, walk.data]);

  /* The viewer follows backend viewer commands (MCP focus_view, agents). */
  const onCommand = useCallback((c: ViewerCommand) => {
    const tag = c.assetTag ?? (c.issueId ? (issues.data ?? []).find(i => i.id === c.issueId)?.assetTag : undefined) ?? undefined;
    setFocus({ assetTag: tag, action: c.action, nonce: c.id ?? `${c.seq}` });
    const who = c.issuedByName ?? agentName(c.issuedBy ?? c.actor ?? c.agentId ?? c.by ?? null);
    toast(`moved by ${who}`);
    setLastMove(`${words(c.action)}${tag ? ` ${tag}` : ""}, moved by ${who}`);
  }, [issues.data, toast]);
  const viewerFeed = useViewerCommands(siteId, onCommand);

  const renderCard = useCallback((tag: string) => <AssetCard asset={assets.find(a => tagOf(a) === tag)} tag={tag} issues={openIssues.filter(i => i.assetTag === tag)} valve={vision.data?.results.find(v => v.assetTag === tag)} label={labelOf.get(tag)} />, [assets, openIssues, vision.data, labelOf]);

  const drawerAsset = drawer ? assets.find(a => tagOf(a) === drawer) : undefined;
  return <div className="page3">
    <PageHead id="environment" title="Environment" />
    <Reveal className="eye-now"><OperatingAgent frame={lastFrame} readiness={eye.readiness} retry={eye.reload} /><WalkthroughBar siteId={siteId} walk={walk} labels={labels} follow={followWalk} onFollow={setFollowWalk} /></Reveal>

    <div className="fac3">
      <Reveal className={`viewer3 ${mission ? "mission-on" : ""}`}>
        <div className={`mission-host ${mission ? "on" : ""}`} ref={hostRef} role={mission ? "dialog" : undefined} aria-modal={mission ? true : undefined} aria-label={mission ? `Mission view, ${site.name}` : undefined}>
          <div className={`vw-box ${editMode ? "editing" : ""}`}>
            <ViewerSlot key={siteId} siteId={siteId} pins={shownPins} focus={focus} follow={follow} credit={false} editMode={mission ? false : editMode} eye={{ siteId, rendererId: `dashboard-${siteId}`, showOverlay: true }}
              fill={mission} safeArea={mission ? (hudHidden ? { top: 48 } : { top: 136, left: 392, right: 344, bottom: 56 }) : undefined} onFrame={() => eye.reload()}
              onPinClick={mission ? tag => focusOn(tag) : openAsset} onPlacePin={p => setPending(p)} renderCard={renderCard} className="fill" />
          </div>
          {mission ? <MissionHud siteId={siteId} frames={frames} issues={issues.data ?? []} hidden={hudHidden} now={tick} renderers={eye.data?.renderers ? eye.data.renderers.filter(r => !r.stale).length : undefined} onFocus={tag => focusOn(tag)} onHide={() => setHudHidden(v => !v)} onExit={closeMission} /> : null}
          {mission && !hudHidden ? <WalkthroughBar hud siteId={siteId} walk={walk} labels={labels} follow={followWalk} onFollow={setFollowWalk} /> : null}
        </div>
        <div className="viewer-meta">
          <span>{scene.readiness === "ready" ? `${pins.length} pins${estimated ? `, ${estimated} estimated (hollow)` : ""}${unpinned > 0 ? `, ${unpinned} assets without a pin` : ""}` : scene.readiness === "loading" ? "Loading pins" : <>Pins not available yet <button type="button" className="retry" onClick={scene.reload}>Retry</button></>}</span>
          <span>{viewerFeed.readiness === "ready" ? (lastMove || "Following viewer commands") : viewerFeed.readiness === "loading" ? "Connecting to viewer commands" : <>Viewer commands not available yet <button type="button" className="retry" onClick={viewerFeed.retry}>Retry</button></>}</span>
          <Btn small arrow onClick={openMission}>Mission view</Btn>
        </div>
      </Reveal>

      <div className="fac-side">
        <Reveal className="p3 place3" i={1}>
          <div className="p-head"><h3>Place pins</h3><OperatorTag /></div>
          <PlacePins siteId={siteId} assets={assets} editMode={editMode} setEditMode={m => { setEditMode(m); if (!m) setPending(null); }} pending={pending} clear={() => setPending(null)} onSaved={tag => { scene.reload(); toast(`Pin saved for ${tag}`); focusOn(tag, "highlight"); }} sceneReady={scene.readiness === "ready"} />
        </Reveal>
        <Reveal className="p3 issues3" i={2}>
          <div className="p-head"><h3>Open issues</h3><span className="meta">{issues.data ? openIssues.length : ""}</span></div>
          <State remote={issues} what="issues" isEmpty={() => openIssues.length === 0} empty="No open issues on this site.">
            {() => <ul className="rows3">{[...openIssues].sort((a, b) => RANK[b.severity] - RANK[a.severity]).map(i => <li key={i.id}>
              <button type="button" className="row-btn" onClick={() => openAsset(i.assetTag)}>
                <span className="r1"><span className={`sig ${i.severity === "high" ? "bad" : i.severity === "medium" ? "warn" : "off"}`} aria-hidden="true" /><strong>{i.assetTag}</strong><span className="sev">{i.severity}</span><SynthTag rec={i} /></span>
                <span className="r2">{i.summary}</span>
              </button>
            </li>)}</ul>}
          </State>
        </Reveal>
      </div>
    </div>

    <EyeStrip frames={frames} readiness={eye.readiness} retry={eye.reload} />
    <CaptureStrip siteId={siteId} results={vision.data?.results ?? []} />

    {site.valves || (vision.data?.results.length ?? 0) > 0 ? <Reveal className="p3 valves3">
      <div className="p-head"><h3>Valve inspection</h3><span className="meta">{vision.data?.ranAt ? new Date(vision.data.ranAt).toLocaleString() : ""}</span></div>
      <State remote={vision} what="the valve inspection" isEmpty={v => v.results.length === 0} empty="No valve inspection results for this site yet.">
        {v => <ValveTable results={v.results} onOpen={openAsset} />}
      </State>
    </Reveal> : null}

    <p className="credit3 wide">3-D captures: {SITES3.map(s => s.author).join(", ")} (SuperSplat)</p>

    {drawer ? <AssetDrawer siteId={siteId} tag={drawer} asset={drawerAsset} issues={(issues.data ?? []).filter(i => i.assetTag === drawer)} obligations={obligations} valve={vision.data?.results.find(v => v.assetTag === drawer) ?? null} onClose={() => setDrawer(null)} onFocus={a => focusOn(drawer, a)} /> : null}
  </div>;
}

/* Who is driving the eye and what it last did, from GET /api/eye/{siteId}/feed. */
function OperatingAgent({ frame, readiness, retry }: { frame: EyeFrame | null; readiness: string; retry: () => void }) {
  if (readiness !== "ready") return <p className="eye-line"><span className="sig off" aria-hidden="true" />{readiness === "loading" ? "Connecting to the agent eye" : <>The eye feed is not available yet. <button type="button" className="retry" onClick={retry}>Retry</button></>}</p>;
  if (!frame) return <p className="eye-line"><span className="sig off" aria-hidden="true" />No agent has driven the eye yet.</p>;
  const pins = frame.visiblePins.filter(p => !p.occluded).map(p => p.assetTag);
  return <p className="eye-line on"><span className="sig ok" aria-hidden="true" /><strong>{agentName(frame.actor)}</strong>&nbsp;{actionText(frame)}<span className="r3">, {ago(frame.at)}{pins.length ? `; sees ${pins.slice(0, 6).join(", ")}${pins.length > 6 ? ` and ${pins.length - 6} more` : ""}` : ""}</span></p>;
}
export function actionText(f: EyeFrame): string {
  const p = (f.params ?? {}) as Record<string, unknown>;
  switch (f.action) {
    case "move": return `moved ${p.direction ?? ""} ${p.meters ?? ""} m`.replace(/\s+/g, " ").trim();
    case "turn": return `turned ${p.yawDeg ?? 0}° yaw, ${p.pitchDeg ?? 0}° pitch`;
    case "go_to": return `went to ${p.assetTag ?? "an asset"}`;
    case "orbit": return `orbited ${p.assetTag ?? "an asset"}`;
    case "mark": { const note = p.note ? rn(String(p.note)).replace(/\s*\(evals?\)/gi, "").trim() : ""; return `marked a point${note ? `: ${note}` : ""}`; }
    case "look": return "looked";
    default: return f.action ? words(f.action) : "rendered a frame";
  }
}

/* "Agent eye view of PG-601": what a frame shows, by the asset it was taken for (else the agent and its move). */
const eyeViewAlt = (f: EyeFrame) => { const tag = (f.params as { assetTag?: unknown } | null)?.assetTag; return typeof tag === "string" && tag ? `Agent eye view of ${tag}` : `Agent eye view: ${agentName(f.actor)} ${actionText(f)}`; };

/* The frames the agent eye returned, newest first. */
function EyeStrip({ frames, readiness, retry }: { frames: EyeFrame[]; readiness: string; retry: () => void }) {
  return <Reveal as="section" className="p3 eyestrip3" aria-labelledby="eye-h">
    <div className="p-head"><h2 id="eye-h">What the agent eye saw</h2><span className="meta">{frames.length ? `${frames.length} frame${frames.length === 1 ? "" : "s"}` : ""}</span></div>
    {readiness !== "ready" ? <p className="st3 empty">{readiness === "loading" ? "Loading the eye feed." : <>The eye feed is not available yet. <button type="button" className="retry" onClick={retry}>Retry</button></>}</p>
      : !frames.length ? <p className="st3 empty">No frames yet.</p>
      : <ol className="eye-frames">{frames.slice(0, 8).map(f => <li key={f.id}>
        <img src={f.frameUrl} alt={eyeViewAlt(f)} loading="lazy" />
        <span className="cap"><strong>{agentName(f.actor)}</strong> {actionText(f)}<SynthTag rec={f as unknown as { synthetic?: boolean }} /><small>{ago(f.at)}{f.visiblePins.length ? `, ${f.visiblePins.filter(p => !p.occluded).length} tags in view` : ""}</small></span>
      </li>)}</ol>}
  </Reveal>;
}

function AssetCard({ asset, tag, issues, valve, label }: { asset?: Asset3; tag: string; issues: Issue3[]; valve?: ValveResult; label?: WalkLabel }) {
  return <div className="card3">
    <span className="c-tag">{tag}</span>
    <span className="c-name">{asset?.name ?? "Unknown asset"}{asset?.kind ? `, ${words(asset.kind)}` : ""}</span>
    {issues.length ? <span className="c-issue"><span className={`sig ${issues.some(i => i.severity === "high") ? "bad" : "warn"}`} aria-hidden="true" />{issues[0].summary}{issues.length > 1 ? ` (+${issues.length - 1})` : ""}</span> : <span className="c-ok"><span className="sig ok" aria-hidden="true" />No open issues</span>}
    {valve ? <span className="c-valve">Valve inspection: {valveWord[valve.status]}</span> : null}
    <span className="c-pin">{asset?.pinSource === "placed" ? "Pin placed" : "Pin estimated, not yet placed"}</span>
    {label ? <LabelDetail label={label} /> : null}
  </div>;
}

function PlacePins({ siteId, assets, editMode, setEditMode, pending, clear, onSaved, sceneReady }: { siteId: SiteId3; assets: Asset3[]; editMode: boolean; setEditMode: (m: boolean) => void; pending: [number, number, number] | null; clear: () => void; onSaved: (tag: string) => void; sceneReady: boolean }) {
  const sorted = useMemo(() => [...assets].sort((a, b) => (a.pinSource === "placed" ? 1 : 0) - (b.pinSource === "placed" ? 1 : 0) || tagOf(a).localeCompare(tagOf(b))), [assets]);
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const chosen = tag || (sorted[0] ? tagOf(sorted[0]) : "");
  async function save() {
    if (!pending || !chosen) return;
    setBusy(true); setError("");
    try { await api3.placePin(siteId, chosen, { x: pending[0], y: pending[1], z: pending[2], source: "placed" }); onSaved(chosen); clear(); setTag(""); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  return <div className="place-body">
    <p>Click a point on the scan, choose the asset it belongs to, save. Estimated pins stay hollow until placed.</p>
    <div className="row-actions">
      <Btn small quiet={editMode} onClick={() => setEditMode(!editMode)} aria-pressed={editMode}>{editMode ? "Stop placing" : "Place pins"}</Btn>
    </div>
    {editMode && !pending ? <p className="hint">Placing: click on the scan.</p> : null}
    {pending ? <div className="pending">
      <span className="xyz">x {pending[0].toFixed(3)}, y {pending[1].toFixed(3)}, z {pending[2].toFixed(3)}</span>
      {sceneReady && sorted.length ? <label className="fld">Asset
        <select value={chosen} onChange={e => setTag(e.target.value)}>{sorted.map(a => <option key={tagOf(a)} value={tagOf(a)}>{tagOf(a)} · {a.name}{a.pinSource === "placed" ? " (placed)" : ""}</option>)}</select>
      </label> : <p className="hint">The asset register is not available yet, so there is nothing to pin.</p>}
      <div className="row-actions"><Btn small disabled={busy || !chosen || !sceneReady} onClick={save}>{busy ? "Saving" : "Save pin"}</Btn><Btn small quiet onClick={clear}>Cancel</Btn></div>
      {error ? <p className="err3" role="alert">{error}</p> : null}
    </div> : null}
  </div>;
}

/* Views of the site: the overview, then the valve inspection's views of each valve (when the backend serves them), else
   the four views under public/env/<site>/. */
function CaptureStrip({ siteId, results }: { siteId: SiteId3; results: ValveResult[] }) {
  const site = site3(siteId);
  const [broken, setBroken] = useState<Set<string>>(new Set());
  const fromVision = results.flatMap(r => (r.frames ?? []).slice(0, 1).map(f => ({ src: api3.frameUrl(siteId, r.assetTag, f), label: r.assetTag, alt: `Agent eye view of ${r.assetTag}` })));
  const usable = fromVision.filter(f => !broken.has(f.src));
  const frames = usable.length ? usable.slice(0, 7) : site.frames.map((src, i) => ({ src, label: `view ${i + 1}`, alt: `${site.name}, view ${i + 1}` }));
  return <Reveal as="div" className="cap3">
    <figure>
      <div className={`cap-strip ${frames.length ? "" : "only-thumb"}`}>
        <div className="frame thumb"><img src={site.thumbnailUrl} alt={`${site.name}, overview`} loading="lazy" /><span>overview</span></div>
        {frames.map(f => <div className="frame" key={f.src}><img src={f.src} alt={f.alt} loading="lazy" onError={() => setBroken(b => new Set(b).add(f.src))} /><span>{f.label}</span></div>)}
      </div>
    </figure>
  </Reveal>;
}

function ValveTable({ results, onOpen }: { results: ValveResult[]; onOpen: (tag: string) => void }) {
  const order = { not_fixed: 0, uncertain: 1, fixed: 2 } as const;
  return <div className="tbl3" role="table" aria-label="Valve inspection results">
    <div className="tr head" role="row"><span role="columnheader">Valve</span><span role="columnheader">Result</span><span role="columnheader">Score</span><span role="columnheader">Explanation</span></div>
    {[...results].sort((a, b) => order[a.status] - order[b.status]).map(r => <div className="tr" role="row" key={r.assetTag}>
      <span role="cell" className="c-tag"><button type="button" className="lnk" onClick={() => onOpen(r.assetTag)}>{r.assetTag}</button></span>
      <span role="cell" className={`c-res ${r.status === "not_fixed" ? "bad" : ""}`}><span className={`sig ${r.status === "fixed" ? "ok" : r.status === "not_fixed" ? "bad" : "warn"}`} aria-hidden="true" />{valveWord[r.status]}</span>
      <span role="cell" className="c-score">{fx(r.score)} <small>threshold {fx(r.threshold)}</small></span>
      <span role="cell" className="c-exp">{r.explanation ? <><strong>{r.explanation.finding}</strong> {r.explanation.recommendedAction}</> : r.status === "fixed" ? "Within the site's normal range." : "No explanation yet."}</span>
    </div>)}
  </div>;
}
