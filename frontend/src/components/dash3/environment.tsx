"use client";

/* /app/[site]/environment, the agent eye: the PlayCanvas scan in eye mode (the camera moves when agents drive it),
   the operating agent and its last action, the eye's frame strip, pins with hover cards and the asset drawer, the
   operator's pin placement, the viewer following focus_view commands, the capture strip and the valve inspections. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api3 } from "@/lib/api-3";
import { useEyeFeed, useIssues3, useObligations, useScene, useViewerCommands, useVision } from "@/lib/hooks-3";
import { agentName, site3 } from "@/lib/sites-3";
import type { Asset3, EyeFrame, Issue3, PinSeverity, SiteId3, ValveResult, ViewerCommand } from "@/lib/types-3";
import AssetDrawer from "./asset-drawer";
import ViewerSlot, { type ViewerFocus, type ViewerPin } from "./viewer-slot";
import { Btn, OperatorTag, PageHead, Reveal, State, SynthTag, ago, errorText, fx, useToast, words } from "./ui3";

export const tagOf = (a: Asset3) => a.tag ?? a.assetTag ?? "";
export const pinOf = (a: Asset3): [number, number, number] | null => !a.pin ? null : Array.isArray(a.pin) ? a.pin : [a.pin.x, a.pin.y, a.pin.z];
const RANK: Record<PinSeverity, number> = { none: 0, low: 1, medium: 2, high: 3 };
export const isOpenIssue = (i: Issue3) => !i.status || !["resolved", "closed"].includes(i.status);
export const valveWord: Record<ValveResult["status"], string> = { fixed: "fixed", not_fixed: "not fixed", uncertain: "uncertain" };

export default function EnvironmentPage({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const eye = useEyeFeed(siteId);
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

  const assets = useMemo(() => scene.data?.assets ?? [], [scene.data]);
  const openIssues = useMemo(() => (issues.data ?? []).filter(isOpenIssue), [issues.data]);
  const pins: ViewerPin[] = useMemo(() => assets.flatMap(a => {
    const p = pinOf(a); if (!p) return [];
    const tag = tagOf(a);
    const mine = openIssues.filter(i => i.assetTag === tag);
    const severity = mine.reduce<PinSeverity>((m, i) => RANK[i.severity] > RANK[m] ? i.severity : m, "none");
    return [{ assetTag: tag, position: p, severity, label: `${tag} ${a.name}`, estimated: a.pinSource !== "placed", issueIds: mine.map(i => i.id) }];
  }), [assets, openIssues]);
  const unpinned = assets.length - pins.length;
  const estimated = pins.filter(p => p.estimated).length;

  const focusOn = useCallback((assetTag: string | undefined, action: ViewerFocus["action"] = "focus") => setFocus({ assetTag, action, nonce: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}` }), []);
  const openAsset = useCallback((tag: string) => { focusOn(tag); setDrawer(tag); }, [focusOn]);
  /* ?asset=<tag> (from the factory overview's issue list) opens that asset. */
  useEffect(() => { const tag = new URLSearchParams(window.location.search).get("asset"); if (tag) openAsset(tag); }, [openAsset]);
  const frames = useMemo(() => [...(eye.data?.frames ?? [])].sort((a, b) => b.at.localeCompare(a.at)), [eye.data]);
  const lastFrame = frames[0] ?? null;

  /* The viewer follows backend viewer commands (MCP focus_view, agents). */
  const onCommand = useCallback((c: ViewerCommand) => {
    const tag = c.assetTag ?? (c.issueId ? (issues.data ?? []).find(i => i.id === c.issueId)?.assetTag : undefined) ?? undefined;
    setFocus({ assetTag: tag, action: c.action, nonce: c.id ?? `${c.seq}` });
    const who = c.issuedByName ?? agentName(c.issuedBy ?? c.actor ?? c.agentId ?? c.by ?? null);
    toast(`moved by ${who}`);
    setLastMove(`${words(c.action)}${tag ? ` ${tag}` : ""}, moved by ${who}`);
  }, [issues.data, toast]);
  const viewerFeed = useViewerCommands(siteId, onCommand);

  const renderCard = useCallback((tag: string) => <AssetCard asset={assets.find(a => tagOf(a) === tag)} tag={tag} issues={openIssues.filter(i => i.assetTag === tag)} valve={vision.data?.results.find(v => v.assetTag === tag)} />, [assets, openIssues, vision.data]);

  const drawerAsset = drawer ? assets.find(a => tagOf(a) === drawer) : undefined;
  return <div className="page3">
    <PageHead id="environment" title="Environment" sub={`${site.name}: the scan is the agents' eye. Humans watch it; the Site Engineer, the Plant Manager and the Operations Director drive it, and each move returns a frame.`} />
    <Reveal className="eye-now"><OperatingAgent frame={lastFrame} readiness={eye.readiness} retry={eye.reload} /></Reveal>

    <div className="fac3">
      <Reveal className="viewer3">
        <div className={`vw-box ${editMode ? "editing" : ""}`}>
          <ViewerSlot key={siteId} siteId={siteId} pins={pins} focus={focus} editMode={editMode} eye={{ siteId, rendererId: `dashboard-${siteId}`, showOverlay: true }}
            onPinClick={openAsset} onPlacePin={p => setPending(p)} renderCard={renderCard} className="fill" />
        </div>
        <div className="viewer-meta">
          <span>{scene.readiness === "ready" ? `${pins.length} pins${estimated ? `, ${estimated} estimated (hollow)` : ""}${unpinned > 0 ? `, ${unpinned} assets without a pin` : ""}` : scene.readiness === "loading" ? "Loading pins" : <>Pins not available yet <button type="button" className="retry" onClick={scene.reload}>Retry</button></>}</span>
          <span>{viewerFeed.readiness === "ready" ? (lastMove || "Following viewer commands") : viewerFeed.readiness === "loading" ? "Connecting to viewer commands" : <>Viewer commands not available yet <button type="button" className="retry" onClick={viewerFeed.retry}>Retry</button></>}</span>
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

    <p className="credit3 wide">{site.name}: “{site.sceneTitle}”, captured by {site.author}, hosted on SuperSplat. <a className="lnk" href={site.sceneUrl} target="_blank" rel="noreferrer">superspl.at/scene/{site.splatId}</a></p>

    <EyeStrip frames={frames} readiness={eye.readiness} retry={eye.reload} />
    <CaptureStrip siteId={siteId} results={vision.data?.results ?? []} />

    <Reveal className="p3 valves3">
      <div className="p-head"><h3>Valve inspection</h3><span className="meta">{vision.data?.model ?? (vision.data?.results[0]?.model ?? "V-JEPA 2")}{vision.data?.ranAt ? `, ${new Date(vision.data.ranAt).toLocaleString()}` : ""}</span></div>
      <p className="note3">An embedding anomaly score: distance from the site&apos;s other valves, not a trained defect classifier. Explanations come from Claude only for valves that are not fixed or uncertain.</p>
      <State remote={vision} what="the valve inspection" isEmpty={v => v.results.length === 0} empty="No valve inspection results for this site yet.">
        {v => <ValveTable results={v.results} onOpen={openAsset} />}
      </State>
    </Reveal>

    {drawer ? <AssetDrawer siteId={siteId} tag={drawer} asset={drawerAsset} issues={(issues.data ?? []).filter(i => i.assetTag === drawer)} obligations={obligations} valve={vision.data?.results.find(v => v.assetTag === drawer) ?? null} onClose={() => setDrawer(null)} onFocus={a => focusOn(drawer, a)} /> : null}
  </div>;
}

/* Who is driving the eye and what it last did, from GET /api/eye/{siteId}/feed. */
function OperatingAgent({ frame, readiness, retry }: { frame: EyeFrame | null; readiness: string; retry: () => void }) {
  if (readiness !== "ready") return <p className="eye-line"><span className="sig off" aria-hidden="true" />{readiness === "loading" ? "Connecting to the agent eye" : <>The eye feed is not available yet. <button type="button" className="retry" onClick={retry}>Retry</button></>}</p>;
  if (!frame) return <p className="eye-line"><span className="sig off" aria-hidden="true" />No agent has driven the eye yet. When one does, the camera below moves and its frames appear in the strip.</p>;
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
    case "mark": return `marked a point${p.note ? `: ${String(p.note)}` : ""}`;
    case "look": return "looked";
    default: return f.action ? words(f.action) : "rendered a frame";
  }
}

/* The frames the agent eye returned, newest first. */
function EyeStrip({ frames, readiness, retry }: { frames: EyeFrame[]; readiness: string; retry: () => void }) {
  return <Reveal as="section" className="p3 eyestrip3" aria-labelledby="eye-h">
    <div className="p-head"><h2 id="eye-h">What the agent eye saw</h2><span className="meta">{frames.length ? `${frames.length} frames` : ""}</span></div>
    {readiness !== "ready" ? <p className="st3 empty">{readiness === "loading" ? "Loading the eye feed." : <>The eye feed is not available yet. <button type="button" className="retry" onClick={retry}>Retry</button></>}</p>
      : !frames.length ? <p className="st3 empty">No frames yet.</p>
      : <ol className="eye-frames">{frames.slice(0, 8).map(f => <li key={f.id}>
        <img src={f.frameUrl} alt={`${agentName(f.actor)} ${actionText(f)}: frame rendered from the hosted capture`} loading="lazy" />
        <span className="cap"><strong>{agentName(f.actor)}</strong> {actionText(f)}<small>{ago(f.at)}{f.visiblePins.length ? `, ${f.visiblePins.filter(p => !p.occluded).length} tags in view` : ""}</small></span>
      </li>)}</ol>}
  </Reveal>;
}

function AssetCard({ asset, tag, issues, valve }: { asset?: Asset3; tag: string; issues: Issue3[]; valve?: ValveResult }) {
  return <div className="card3">
    <span className="c-tag">{tag}</span>
    <span className="c-name">{asset?.name ?? "Unknown asset"}{asset?.kind ? `, ${words(asset.kind)}` : ""}</span>
    {issues.length ? <span className="c-issue"><span className={`sig ${issues.some(i => i.severity === "high") ? "bad" : "warn"}`} aria-hidden="true" />{issues[0].summary}{issues.length > 1 ? ` (+${issues.length - 1})` : ""}</span> : <span className="c-ok"><span className="sig ok" aria-hidden="true" />No open issues</span>}
    {valve ? <span className="c-valve">Valve inspection: {valveWord[valve.status]}</span> : null}
    <span className="c-pin">{asset?.pinSource === "placed" ? "Pin placed" : "Pin estimated, not yet placed"}</span>
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

/* Capture pictures: the scan thumbnail, then frames rendered from the hosted capture (vision/frames when the backend
   serves them, else the four committed renders under public/env/<site>/). */
function CaptureStrip({ siteId, results }: { siteId: SiteId3; results: ValveResult[] }) {
  const site = site3(siteId);
  const [broken, setBroken] = useState<Set<string>>(new Set());
  const fromVision = results.flatMap(r => (r.frames ?? []).slice(0, 1).map(f => ({ src: api3.frameUrl(siteId, r.assetTag, f), label: r.assetTag })));
  const usable = fromVision.filter(f => !broken.has(f.src));
  const frames = usable.length ? usable.slice(0, 7) : site.frames.map((src, i) => ({ src, label: `view ${i + 1}` }));
  return <Reveal as="div" className="cap3">
    <figure>
      <div className="cap-strip">
        <div className="frame thumb"><img src={site.thumbnailUrl} alt={`${site.name}, capture thumbnail`} loading="lazy" /><span>thumbnail</span></div>
        {frames.map(f => <div className="frame" key={f.src}><img src={f.src} alt={`${site.name}, ${f.label}, rendered from the hosted capture`} loading="lazy" onError={() => setBroken(b => new Set(b).add(f.src))} /><span>{f.label}</span></div>)}
      </div>
      <figcaption>frames rendered from the hosted capture</figcaption>
    </figure>
  </Reveal>;
}

function ValveTable({ results, onOpen }: { results: ValveResult[]; onOpen: (tag: string) => void }) {
  const order = { not_fixed: 0, uncertain: 1, fixed: 2 } as const;
  return <div className="tbl3" role="table" aria-label="Valve inspection results">
    <div className="tr head" role="row"><span role="columnheader">Valve</span><span role="columnheader">Result</span><span role="columnheader">Score</span><span role="columnheader">Explanation</span></div>
    {[...results].sort((a, b) => order[a.status] - order[b.status]).map(r => <div className="tr" role="row" key={r.assetTag}>
      <span role="cell" className="c-tag"><button type="button" className="lnk" onClick={() => onOpen(r.assetTag)}>{r.assetTag}</button>{r.defect && r.defect !== "none" ? <span className="tg synth">synthetic defect: {words(r.defect)}</span> : <SynthTag rec={r} />}</span>
      <span role="cell" className={`c-res ${r.status === "not_fixed" ? "bad" : ""}`}><span className={`sig ${r.status === "fixed" ? "ok" : r.status === "not_fixed" ? "bad" : "warn"}`} aria-hidden="true" />{valveWord[r.status]}</span>
      <span role="cell" className="c-score">{fx(r.score)} <small>threshold {fx(r.threshold)}</small></span>
      <span role="cell" className="c-exp">{r.explanation ? <><strong>{r.explanation.finding}</strong> {r.explanation.recommendedAction}</> : r.status === "fixed" ? "Within the site's normal range." : r.explainDryRun ? "Dry run: the request to Claude was written, not sent." : "No explanation yet."}</span>
    </div>)}
  </div>;
}
