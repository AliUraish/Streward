"use client";

/* Walks (REALITY-CONTRACT-7.md section 1). Each site's Engineer walks the scan with the agent eye on its own, stop
   after stop, and marks what it sees: green "Looks good", blue "Looks bad: <first reason>", with its observation. This
   module draws the walk line ("Site Engineer · Myer at PG-601: needle steady in the green band, no weep at the
   flange") with the follow-the-camera switch, the label details in a pin's hover card, the label as the viewer's pin
   chip, and the overview's tally over the scan picture. Nothing here starts or stops a walk. */
import type { ReactNode } from "react";
import type { Remote } from "@/lib/reality";
import type { Patrol, WalkLabel, WalkNow } from "@/lib/api-7";
import { useLabels, useWalk } from "@/lib/hooks-7";
import { REGULATIONS_PACK } from "@/lib/regulations-3";
import type { EyeFrame, SiteId3 } from "@/lib/types-3";
import type { SplatViewerProps, ViewerPin } from "./viewer-slot";
import { JaText, ago } from "./ui3";
import "./dash7.css";

export const PLACE_NOUN: Record<SiteId3, string> = { "myer-plant": "the plant room", "bristol-pumps": "the pump house", "tomioka-mill": "the mill" };
export const isRunning = (p: Patrol | null | undefined): p is Patrol => p?.state === "running";

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

/* "Pressure Systems Safety Regulations 2000, reg. 8" for eng-pssr-2000-reg-8: the instrument without its trailing
   citation in brackets ("(SI 2000/128)"), and the provision's first part without its notes in brackets ("(第43条…)",
   "(guidance, not law)"; "(1)" and "(17)" stay); the id itself when the pack lacks it. */
const instrumentName = (s: string) => s.replace(/\s+\([^()]*\)\s*$/, "").replace(/\s+\([^()]*\)\s*$/, "").trim();
const provisionName = (s: string) => s.split(";")[0].replace(/\s*\((?=[^()]*[\s　-鿿＀-￯])[^()]*\)/g, "").replace(/[\s,;:]+$/, "").trim();
export function regulationName(id: string): string {
  const r = REGULATIONS_PACK.find(x => x.id === id);
  if (!r) return id;
  const provision = r.provision ? provisionName(r.provision) : "";
  return `${instrumentName(r.instrument ?? "")}${provision ? `, ${provision}` : ""}` || r.title || id;
}
export const labelText = (l: WalkLabel) => (l.verdict === "bad" && l.reasons[0] ? `${l.title}: ${l.reasons[0]}` : l.title);
/* The label as the viewer draws it: the chip's words, and the sentence the dot's accessible name reads. */
export function assessmentOf(l: WalkLabel): NonNullable<ViewerPin["assessment"]> {
  const more = l.reasons.slice(l.verdict === "bad" ? 1 : 0);
  const regs = l.regulationIds.length ? `${l.regulationIds.length > 1 ? "Regulations" : "Regulation"} ${l.regulationIds.map(regulationName).join("; ")}` : "";
  const parts = [labelText(l), l.observation ?? "", ...more, regs, `Labelled by ${l.agentName}${l.at ? `, ${ago(l.at)}` : ""}`].filter(Boolean);
  return { verdict: l.verdict, text: labelText(l), description: parts.map(p => p.replace(/[.\s]+$/, "")).join(". ") };
}

/* The camera pose of the walking engineer's newest frame, for the viewer to follow while it walks. */
export function followPose(frames: EyeFrame[], w: Pick<WalkNow, "walking" | "startedAt" | "agentId"> | null | undefined): NonNullable<SplatViewerProps["follow"]> | null {
  if (!w?.walking) return null;
  const ok = (v: unknown): v is [number, number, number] => Array.isArray(v) && v.length === 3 && v.every(n => typeof n === "number" && Number.isFinite(n));
  const f = frames.find(fr => (!w.startedAt || fr.at >= w.startedAt) && (!w.agentId || !fr.actor || fr.actor === w.agentId) && ok(fr.camera?.position) && ok(fr.camera?.target));
  if (!f || !f.camera) return null;
  return { position: f.camera.position as [number, number, number], target: f.camera.target as [number, number, number], fov: typeof f.camera.fov === "number" ? f.camera.fov : null, nonce: f.id };
}

/* What the walk line says about the stop: the walk's own observation, else the label this walk left on the asset. */
export function stopWords(w: WalkNow, labels: WalkLabel[]): { text: string | null; at: string | null } {
  if (w.observation) return { text: w.observation, at: w.at };
  const l = w.assetTag ? labels.find(x => x.assetTag === w.assetTag && (!w.patrolId || !x.patrolId || x.patrolId === w.patrolId)) : undefined;
  if (!l) return { text: null, at: w.at };
  return { text: l.observation ?? (l.reasons[0] ? `${l.title}, ${l.reasons[0]}` : l.title), at: l.at || w.at };
}

/* The walk line: who, at which asset, what it saw there, and the stop. The walk runs on its own; the one control is
   whether this view follows the walking engineer's camera. */
export function WalkthroughBar({ siteId, walk, labels, follow, onFollow, hud }: {
  siteId: SiteId3; walk: Remote<WalkNow>; labels?: Remote<WalkLabel[]>; follow: boolean; onFollow: (on: boolean) => void; hud?: boolean;
}) {
  const w = walk.data;
  const list = labels?.data ?? [];
  let line: ReactNode; let when: string | null = null;
  if (!w) line = walk.readiness === "loading" ? <>Connecting to the walk</>
    : <>{walk.readiness === "not_ready" ? "The walk is not available yet." : "Could not load the walk."} <button type="button" className="retry" onClick={walk.reload}>Retry</button></>;
  else {
    const said = stopWords(w, list); when = said.at;
    line = <><strong>{w.agentName}</strong>{w.assetTag ? <>&nbsp;at <code>{w.assetTag}</code>{said.text ? <>: <JaText text={said.text} /></> : null}</>
      : <>&nbsp;{w.walking ? "is walking" : "is about to walk"} {PLACE_NOUN[siteId]}</>}{w.stop && w.of ? <span className="walk-stop">, stop {w.stop} of {w.of}</span> : null}</>;
  }
  const t = tally(list);
  const n = w?.stop ?? 0, of = w?.of ?? 0;
  return <div className={`walk7 ${hud ? "hud" : ""}`}>
    <p className="walk-line" aria-live="polite"><span className={`sig ${w?.walking ? "ok" : "off"}`} aria-hidden="true" />{line}</p>
    {w && when ? <span className="walk-when">{ago(when)}</span> : null}
    {w?.walking && of ? <ol className="walk-stops" aria-hidden="true">{Array.from({ length: Math.min(of, 24) }, (_, k) => {
      const done = w.stops[k];
      const state = done?.verdict ?? (k < n - 1 ? "done" : k === n - 1 ? "now" : "next");
      const tag = w.route[k] ?? done?.assetTag ?? "";
      return <li key={k} data-state={state} title={tag ? `${tag}${done?.verdict ? `: looks ${done.verdict}` : k === n - 1 ? ": now" : ""}` : undefined} />;
    })}</ol> : null}
    {!hud && list.length ? <span className="walk-tally" aria-label={`Latest labels: ${t.good} look good, ${t.bad} look bad`}>
      <span><span className="sw7 good" aria-hidden="true" />{t.good} look{t.good === 1 ? "s" : ""} good</span>
      <span><span className="sw7 bad" aria-hidden="true" />{t.bad} look{t.bad === 1 ? "s" : ""} bad</span>
    </span> : null}
    {w?.walking ? <span className="walk-actions">
      <button type="button" className="follow7" aria-pressed={follow} onClick={() => onFollow(!follow)}>{follow ? "Following the camera" : "Follow the camera"}</button>
    </span> : null}
  </div>;
}

/* A label in a pin's hover card: the verdict, what the engineer saw, the reasons, the regulation, the agent and the
   time, the evidence frame. */
export function LabelDetail({ label }: { label: WalkLabel }) {
  const note = label.mark?.note && label.mark.note !== label.observation ? label.mark.note : null;
  return <div className="lbl7">
    <span className="lbl-chip" data-verdict={label.verdict}>{label.title}</span>
    {label.observation ? <p className="lbl-obs"><JaText text={label.observation} /></p> : null}
    {note ? <p className="lbl-note">Marked: <JaText text={note} /></p> : null}
    {label.reasons.length ? <ul className="lbl-reasons">{label.reasons.map((r, i) => <li key={i}><JaText text={r} /></li>)}</ul> : null}
    {label.regulationIds.length ? <p className="lbl-regs">{label.regulationIds.length > 1 ? "Regulations" : "Regulation"} <strong><JaText text={label.regulationIds.map(regulationName).join("; ")} /></strong></p> : null}
    <p className="lbl-by">{label.agentName}{label.at ? `, ${ago(label.at)}` : ""}{label.confidence !== null ? `, confidence ${Math.round(label.confidence * 100)}%` : ""}</p>
    {label.frameUrl ? <img className="lbl-frame" src={label.frameUrl} alt={`What ${label.agentName} saw at ${label.assetTag}`} loading="lazy" /> : null}
  </div>;
}

/* Over the overview's scan picture: the walk under way, or the latest labels. Nothing until there is either. */
export function SceneTally({ siteId }: { siteId: SiteId3 }) {
  const labels = useLabels(siteId, 10_000);
  const walk = useWalk(siteId, 6_000);
  const w = walk.data;
  const list = labels.data ?? [];
  if (!w?.walking && !list.length) return null;
  const t = tally(list);
  return <div className="fo-tally">
    {w?.walking ? <span className="ft-row"><span><span className="sig ok" aria-hidden="true" /><strong>{w.agentName}</strong>&nbsp;{w.assetTag ? `at ${w.assetTag}` : `is walking ${PLACE_NOUN[siteId]}`}{w.stop && w.of ? `, stop ${w.stop} of ${w.of}` : ""}</span></span>
      : <span>Latest walkthrough labels{t.at ? `, ${ago(t.at)}` : ""}</span>}
    {list.length ? <span className="ft-row"><span><span className="sw7 good" aria-hidden="true" />{t.good} look{t.good === 1 ? "s" : ""} good</span><span><span className="sw7 bad" aria-hidden="true" />{t.bad} look{t.bad === 1 ? "s" : ""} bad</span></span> : null}
  </div>;
}
