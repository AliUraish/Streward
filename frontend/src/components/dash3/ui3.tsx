"use client";

/* Small pieces shared by every section of the phase-3 dashboard: the animated button, tags, the degraded states,
   the staggered reveal and the site tabs. The button is the home page's: white fill, a dark fill sliding in from the
   left on hover, words inverting through difference, press scale, arrow nudge. */
import { createContext, useContext, useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { Remote } from "@/lib/reality";
import { SITES3, type Site3 } from "@/lib/sites-3";
import type { SiteId3, SyntheticMark } from "@/lib/types-3";

/* Japanese text. Geist has no Japanese glyphs, so these spans (and only these) carry a system Japanese face after Geist
   in their font stack (.ja in dash3.css) and lang="ja" so the right glyph forms are chosen and read. JaText wraps the
   Japanese runs of a mixed string ("Act on Protection of Cultural Properties (文化財保護法), 第43条"). */
const JA_RUN = /([\u3000-\u303f\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]+)/;
export function JaText({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  if (!JA_RUN.test(text)) return <>{text}</>;
  return <>{text.split(JA_RUN).map((part, i) => i % 2 ? <span key={i} lang="ja" className="ja">{part}</span> : part)}</>;
}
/* Text with links: URLs become links (ending before a full-width bracket), the rest goes through JaText. */
export function LinkedText({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  const parts = text.split(/(https?:\/\/[^\s）)」、]+)/);
  return <>{parts.map((part, i) => i % 2 ? <a key={i} className="lnk" href={part} target="_blank" rel="noreferrer">{part.replace(/^https?:\/\//, "")}</a> : <JaText key={i} text={part} />)}</>;
}
/* "Tomioka Silk Mill 富岡製糸場": the English name with the site's own name beside it, where the site is introduced. */
export function SiteTitle({ site }: { site: Site3 }) {
  return <>{site.name}{site.jaName ? <> <span lang="ja" className="ja ja-name">{site.jaName}</span></> : null}</>;
}

export function Btn({ children, arrow, quiet, small, className = "", ...rest }: { children: ReactNode; arrow?: boolean; quiet?: boolean; small?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" className={`b3 ${quiet ? "quiet" : ""} ${small ? "small" : ""} ${className}`} {...rest}>
    <span>{children}</span>{arrow ? <span className="arrow" aria-hidden="true">→</span> : null}
  </button>;
}
export function LinkBtn({ href, children, quiet, small, external }: { href: string; children: ReactNode; quiet?: boolean; small?: boolean; external?: boolean }) {
  return <a className={`b3 ${quiet ? "quiet" : ""} ${small ? "small" : ""}`} href={href} {...(external ? { target: "_blank", rel: "noreferrer" } : {})}>
    <span>{children}</span><span className="arrow" aria-hidden="true">→</span>
  </a>;
}

/* Records keep their provenance flags (synthetic, simulated, generator) for the audit trail; the dashboard shows the
   record itself, untagged. The tags stay as components so every call site is unchanged; they render nothing. */
export const isSynthetic = (r: SyntheticMark | null | undefined) => Boolean(r && (r.synthetic || r.simulated));
export function SynthTag(_props: { rec?: SyntheticMark | null; always?: boolean }) { return null; }
export const DemoTag = () => null;
export const OperatorTag = () => null;

/* Live readings: an arrow for the direction since the previous reading (none when it held) and a High or Low mark when
   the reading is outside its normal band. Both are words to a screen reader, so neither rests on its glyph or colour. A
   new reading (at) replays the arrow's entrance. */
export type TrendWord = "up" | "down" | "flat";
export type BandWord = "high" | "low" | "normal";
export function TrendMark({ trend, at }: { trend?: TrendWord | string | null; at?: string | number | null }) {
  if (trend !== "up" && trend !== "down") return null;
  return <span key={at ?? undefined} className={`trend3 ${trend}`}><span aria-hidden="true">{trend === "up" ? "▲" : "▼"}</span><span className="sr-only">{trend}</span></span>;
}
export function BandMark({ state }: { state?: BandWord | string | null }) {
  if (state !== "high" && state !== "low") return null;
  return <span className="tg bad band3">{state === "high" ? "High" : "Low"}<span className="sr-only">, {state === "high" ? "above" : "below"} normal range</span></span>;
}

/* Loading, not ready (404/405/501) with Retry, or a plain error with Retry. Renders children only when ready. */
export function State<T>({ remote, what, children, empty, isEmpty }: { remote: Remote<T>; what: string; children: (data: T) => ReactNode; empty?: string; isEmpty?: (data: T) => boolean }) {
  if (remote.readiness === "loading" && remote.data === null) return <div className="st3 loading" aria-live="polite"><span className="pulse" aria-hidden="true" />Loading {what}</div>;
  if (remote.data === null || remote.readiness === "not_ready") {
    const notReady = remote.readiness === "not_ready";
    return <div className="st3 not-ready" role="status">
      <strong>{notReady ? "Not available yet" : "Could not load"}</strong>
      {notReady ? null : <span>{remote.error || `Loading ${what} failed.`}</span>}
      <Btn quiet small onClick={remote.reload}>Retry</Btn>
    </div>;
  }
  if (isEmpty?.(remote.data)) return <div className="st3 empty">{empty ?? `No ${what} yet.`}</div>;
  return <>{children(remote.data)}</>;
}
/* Inline variant for a single figure inside a tile. */
export function NotYet({ remote, what }: { remote: Remote<unknown>; what: string }) {
  if (remote.readiness === "ready") return null;
  if (remote.readiness === "loading" && remote.data === null) return <span className="st3-inline">Loading {what}</span>;
  return <span className="st3-inline">{remote.readiness === "not_ready" ? "Not available yet" : "Could not load"} <button type="button" className="retry" onClick={remote.reload}>Retry</button></span>;
}

/* Entrance: rise, staggered by --i, once, as the element enters. Content stays visible without script. */
export function Reveal({ as: Tag = "div", i = 0, className, children, id, ...rest }: { as?: "div" | "section" | "li" | "header" | "article" | "nav" | "figure"; i?: number; className?: string; children?: ReactNode; id?: string } & Record<string, unknown>) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (typeof IntersectionObserver === "undefined") { el.classList.add("is-in"); return; }
    const io = new IntersectionObserver(entries => { for (const e of entries) if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } }, { rootMargin: "0px 0px -6% 0px", threshold: 0.02 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const C = Tag as "div";
  return <C ref={ref as never} id={id} data-reveal="" data-dissolve="" style={{ ["--i" as string]: i }} className={className} {...rest}>{children}</C>;
}

export function SiteTabs({ value, onChange, label }: { value: SiteId3; onChange: (id: SiteId3) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function key(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault(); const n = (i + (e.key === "ArrowRight" ? 1 : -1) + SITES3.length) % SITES3.length;
    onChange(SITES3[n].id); refs.current[n]?.focus();
  }
  return <div className="tabs3" role="tablist" aria-label={label}>
    {SITES3.map((s, i) => <button key={s.id} ref={el => { refs.current[i] = el; }} role="tab" type="button" aria-selected={value === s.id} tabIndex={value === s.id ? 0 : -1} className={value === s.id ? "on" : ""} onClick={() => onChange(s.id)} onKeyDown={e => key(e, i)}>
      <span className="long">{s.name}</span><span className="short">{s.short}</span>
    </button>)}
  </div>;
}

export function SectionHead({ id, title, sub, children, page }: { id: string; title: ReactNode; sub?: ReactNode; children?: ReactNode; page?: boolean }) {
  const H = page ? "h1" : "h2";
  return <Reveal as="header" className={`sh3 ${page ? "page" : ""}`}>
    <div className="say"><H id={`${id}-h`}>{title}</H>{sub ? <p>{sub}</p> : null}</div>
    {children ? <div className="tools">{children}</div> : null}
  </Reveal>;
}
export const PageHead = (props: { id: string; title: ReactNode; sub?: ReactNode; children?: ReactNode }) => <SectionHead {...props} page />;

/* Toasts: one live region for the page ("moved by Site Engineer · Myer"). */
interface Toast { id: number; text: string }
const ToastCtx = createContext<(text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastHost({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const push = useRef((text: string) => {
    const id = ++seq.current;
    setToasts(t => [...t.slice(-2), { id, text }]);
    window.setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3600);
  });
  return <ToastCtx.Provider value={push.current}>
    {children}
    <div className="toasts3" aria-live="polite" role="status">{toasts.map(t => <div className="toast3" key={t.id}>{t.text}</div>)}</div>
  </ToastCtx.Provider>;
}

/* Formatting */
export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso); if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
export function day(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso); if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (Number.isNaN(s)) return "";
  const a = Math.abs(s); const fut = s < 0;
  const v = a < 60 ? `${a} s` : a < 3600 ? `${Math.round(a / 60)} min` : a < 86400 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} d`;
  return fut ? `in ${v}` : `${v} ago`;
}
export const words = (s: string | null | undefined) => (s ?? "").replace(/_/g, " ");
export const fx = (v: number | null | undefined, d = 3) => v === null || v === undefined ? "–" : v.toFixed(d);
export const n = (v: number | null | undefined) => v === null || v === undefined ? "–" : new Intl.NumberFormat().format(v);
export function errorText(e: unknown) {
  const err = e as { notReady?: boolean; message?: string };
  if (err?.notReady) return "Not available yet.";
  return err?.message ?? "Request failed";
}
