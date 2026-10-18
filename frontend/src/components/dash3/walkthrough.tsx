"use client";

/* Walkthroughs (REALITY-CONTRACT-7.md section 1). The site's Engineer walks the scan with the agent eye, stop by stop,
   and labels each asset it looks at: green "Looks good", blue "Looks bad: <first reason>". This module draws the
   walkthrough line ("Site Engineer · Bristol is walking the pump house: stop 4 of 9, PV-301") with the operator's
   "Walk the site now" and the follow-the-camera switch, the label details in a pin's hover card, the label as the
   viewer's pin chip, and the overview's tally over the scan picture. */
import { useState, type ReactNode } from "react";
import type { Remote } from "@/lib/reality";
import { api7, type Patrol, type WalkLabel } from "@/lib/api-7";
import { useLabels, usePatrols } from "@/lib/hooks-7";
import { REGULATIONS_PACK } from "@/lib/regulations-3";
import { roleOf } from "@/lib/sites-3";
import type { EyeFrame, SiteId3 } from "@/lib/types-3";
import type { SplatViewerProps, ViewerPin } from "./viewer-slot";
import { Btn, JaText, ago, errorText, useToast } from "./ui3";
import "./dash7.css";

export const PLACE_NOUN: Record<SiteId3, string> = { "myer-plant": "the plant room", "bristol-pumps": "the pump house", "tomioka-mill": "the mill" };
export const isRunning = (p: Patrol | null | undefined): p is Patrol => p?.state === "running";
const engineerOf = (siteId: SiteId3) => roleOf(siteId, "engineer").name;

/* Stop n of N and the asset being looked at; stopIndex counts from 0 along the route. */
export function stopOf(p: Patrol): { n: number; of: number; tag: string | null } {
  const of = Math.max(p.route.length, p.stops.length);
  const i = Math.max(0, Math.min(Math.max(of - 1, 0), p.stopIndex));
  return { n: of ? i + 1 : 0, of, tag: p.route[i] ?? p.stops[i]?.assetTag ?? null };
}
export function tally(labels: WalkLabel[]) {
  const good = labels.filter(l => l.verdict === "good").length;
  return { good, bad: labels.length - good, at: labels.reduce((m, l) => (l.at > m ? l.at : m), "") };
}

/* "Pressure Systems Safety Regulations 2000, reg. 8" for eng-pssr-2000-reg-8; the id itself when the pack lacks it. */
export function regulationName(id: string): string {
  const r = REGULATIONS_PACK.find(x => x.id === id);
  if (!r) return id;
  return `${(r.instrument ?? "").replace(/\s*\(.*$/, "")}${r.provision ? `, ${r.provision.replace(/\s*\(.*$/, "")}` : ""}` || r.title || id;
}
export const labelText = (l: WalkLabel) => (l.verdict === "bad" && l.reasons[0] ? `${l.title}: ${l.reasons[0]}` : l.title);
/* The label as the viewer draws it: the chip's words, and the sentence the dot's accessible name reads. */
export function assessmentOf(l: WalkLabel): NonNullable<ViewerPin["assessment"]> {
  const more = l.reasons.slice(l.verdict === "bad" ? 1 : 0);
  const regs = l.regulationIds.length ? `${l.regulationIds.length > 1 ? "Regulations" : "Regulation"} ${l.regulationIds.map(regulationName).join("; ")}` : "";
  const parts = [labelText(l), ...more, regs, `Labelled by ${l.agentName}${l.at ? `, ${ago(l.at)}` : ""}`].filter(Boolean);
  return { verdict: l.verdict, text: labelText(l), description: parts.map(p => p.replace(/[.\s]+$/, "")).join(". ") };
}

/* The camera pose of the walking agent's newest frame, for the viewer to follow while the walkthrough runs. */
export function followPose(frames: EyeFrame[], p: Patrol | null | undefined): NonNullable<SplatViewerProps["follow"]> | null {
  if (!isRunning(p)) return null;
  const ok = (v: unknown): v is [number, number, number] => Array.isArray(v) && v.length === 3 && v.every(n => typeof n === "number" && Number.isFinite(n));
  const f = frames.find(fr => (!p.startedAt || fr.at >= p.startedAt) && (!p.agentId || !fr.actor || fr.actor === p.agentId) && ok(fr.camera?.position) && ok(fr.camera?.target));
  if (!f || !f.camera) return null;
  return { position: f.camera.position as [number, number, number], target: f.camera.target as [number, number, number], fov: typeof f.camera.fov === "number" ? f.camera.fov : null, nonce: f.id };
}

function lastWords(p: Patrol, siteId: SiteId3): string {
  const when = ago(p.finishedAt ?? p.startedAt);
  const good = p.stops.filter(s => s.verdict === "good").length; const bad = p.stops.filter(s => s.verdict === "bad").length;
  const counts = `${p.stops.length} checked, ${good} look${good === 1 ? "s" : ""} good, ${bad} look${bad === 1 ? "s" : ""} bad`;
  if (p.state === "canceled") return `The last walkthrough of ${PLACE_NOUN[siteId]} was stopped ${when}, after ${p.stops.length} of ${Math.max(p.route.length, p.stops.length)} stops.`;
  if (p.state === "failed") return `The last walkthrough of ${PLACE_NOUN[siteId]} failed ${when}${p.summary ? `: ${p.summary}` : "."}`;
  return `Last walkthrough ${when}, by ${p.agentName ?? engineerOf(siteId)}: ${p.summary ?? counts}`;
}

export function WalkthroughBar({ siteId, patrols, labels, follow, onFollow, hud }: {
  siteId: SiteId3; patrols: Remote<Patrol[]>; labels?: Remote<WalkLabel[]>; follow: boolean; onFollow: (on: boolean) => void; hud?: boolean;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const latest = patrols.data?.[0] ?? null;
  const running = isRunning(latest);
  const noun = PLACE_NOUN[siteId];
  async function walk() {
    setBusy(true); setError("");
    try {
      const p = await api7.startPatrol(siteId);
      patrols.reload();
      toast(`${p.agentName ?? engineerOf(siteId)} is walking ${noun}`);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  let line: ReactNode;
  if (!patrols.data) line = patrols.readiness === "loading" ? <>Connecting to the walkthroughs</>
    : <>{patrols.readiness === "not_ready" ? "Walkthroughs are not available yet." : "Could not load the walkthroughs."} <button type="button" className="retry" onClick={patrols.reload}>Retry</button></>;
  else if (running) {
    const s = stopOf(latest);
    line = <><strong>{latest.agentName ?? engineerOf(siteId)}</strong>&nbsp;is walking {noun}{s.of ? <>: stop {s.n} of {s.of}{s.tag ? <>, <code>{s.tag}</code></> : null}</> : null}</>;
  } else if (latest) line = <JaText text={lastWords(latest, siteId)} />;
  else line = <>No walkthrough yet. {engineerOf(siteId)} walks {noun} on its own and labels what it sees.</>;
  const t = tally(labels?.data ?? []);
  const s = running ? stopOf(latest) : null;
  return <div className={`walk7 ${hud ? "hud" : ""}`}>
    <p className="walk-line" aria-live="polite"><span className={`sig ${running ? "ok" : "off"}`} aria-hidden="true" />{line}</p>
    {running && s && s.of ? <ol className="walk-stops" aria-hidden="true">{Array.from({ length: s.of }, (_, k) => {
      const done = latest.stops[k];
      const state = done?.verdict ?? (k < latest.stops.length ? "next" : k === s.n - 1 ? "now" : "next");
      const tag = latest.route[k] ?? done?.assetTag ?? "";
      return <li key={k} data-state={state} title={`${tag}${done?.verdict ? `: looks ${done.verdict}` : k === s.n - 1 ? ": now" : ""}`} />;
    })}</ol> : null}
    {!hud && labels?.data?.length ? <span className="walk-tally" aria-label={`Latest labels: ${t.good} look good, ${t.bad} look bad`}>
      <span><span className="sw7 good" aria-hidden="true" />{t.good} look{t.good === 1 ? "s" : ""} good</span>
      <span><span className="sw7 bad" aria-hidden="true" />{t.bad} look{t.bad === 1 ? "s" : ""} bad</span>
    </span> : null}
    <span className="walk-actions">
      {running ? <button type="button" className="follow7" aria-pressed={follow} onClick={() => onFollow(!follow)}>{follow ? "Following the camera" : "Follow the camera"}</button> : null}
      <Btn small arrow disabled={busy || running || !patrols.data} onClick={walk} title={running ? "A walkthrough is running" : undefined}>{busy ? "Starting" : "Walk the site now"}</Btn>
    </span>
    {error ? <p className="err3" role="alert">{error}</p> : null}
  </div>;
}

/* A label in a pin's hover card: the verdict, the reasons, the regulation, the agent and the time, the evidence frame. */
export function LabelDetail({ label }: { label: WalkLabel }) {
  return <div className="lbl7">
    <span className="lbl-chip" data-verdict={label.verdict}>{label.title}</span>
    {label.reasons.length ? <ul className="lbl-reasons">{label.reasons.map((r, i) => <li key={i}><JaText text={r} /></li>)}</ul> : null}
    {label.regulationIds.length ? <p className="lbl-regs">{label.regulationIds.length > 1 ? "Regulations" : "Regulation"} <strong><JaText text={label.regulationIds.map(regulationName).join("; ")} /></strong></p> : null}
    <p className="lbl-by">{label.agentName}{label.at ? `, ${ago(label.at)}` : ""}</p>
    {label.frameUrl ? <img className="lbl-frame" src={label.frameUrl} alt={`What ${label.agentName} saw at ${label.assetTag}`} loading="lazy" /> : null}
  </div>;
}

/* Over the overview's scan picture: the walkthrough under way, or the latest labels. Nothing until there is either. */
export function SceneTally({ siteId }: { siteId: SiteId3 }) {
  const labels = useLabels(siteId, 10_000);
  const patrols = usePatrols(siteId, 6_000);
  const latest = patrols.data?.[0] ?? null;
  const list = labels.data ?? [];
  if (!isRunning(latest) && !list.length) return null;
  const t = tally(list);
  const s = isRunning(latest) ? stopOf(latest) : null;
  return <div className="fo-tally">
    {isRunning(latest) && s ? <span className="ft-row"><span><span className="sig ok" aria-hidden="true" /><strong>{latest.agentName ?? engineerOf(siteId)}</strong>&nbsp;is walking {PLACE_NOUN[siteId]}{s.of ? `: stop ${s.n} of ${s.of}` : ""}</span></span>
      : <span>Latest walkthrough labels{t.at ? `, ${ago(t.at)}` : ""}</span>}
    {list.length ? <span className="ft-row"><span><span className="sw7 good" aria-hidden="true" />{t.good} look{t.good === 1 ? "s" : ""} good</span><span><span className="sw7 bad" aria-hidden="true" />{t.bad} look{t.bad === 1 ? "s" : ""} bad</span></span> : null}
  </div>;
}
