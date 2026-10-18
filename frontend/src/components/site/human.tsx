"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Attestation } from "../../../../shared/types";
import { api, type SignedAttestation } from "@/lib/api";
import { age, formatValue, freshness, latestPerAttribute, useFacts, useRemote } from "@/lib/reality";
import { BEATS, CHECKS, METRES_WEST } from "./story";
import HeroStatic from "./hero-static";
import type { HeroControl } from "./hero-scene";

const HeroScene = dynamic(() => import("./hero-scene"), { ssr: false, loading: () => null });

const SITE = "harbor-works";
const SAMPLE_ATTESTATION_ID = "att_p101_pressure";

/* Entrance for the parts of a section: rise, slide or settle, once, staggered by --i. Content stays visible without script. */
export function Reveal({ as: Tag = "div", i = 0, manner = "rise", className, children, ...rest }: { as?: "div" | "section" | "li" | "h2" | "h3" | "p" | "figure" | "span"; i?: number; manner?: "rise" | "slide" | "settle"; className?: string; children?: ReactNode } & Record<string, unknown>) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (typeof IntersectionObserver === "undefined") { el.classList.add("is-in"); return; }
    const io = new IntersectionObserver(entries => { for (const e of entries) if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const Component = Tag as "div";
  return <Component ref={ref as never} data-reveal={manner} style={{ ["--i" as string]: i }} className={className} {...rest}>{children}</Component>;
}

function useLatestAttestation() {
  return useRemote<SignedAttestation | null>(async () => {
    const changes = await api.changes(SITE, 0, 200);
    const ids: string[] = [];
    for (const w of changes.waiting) for (const v of w.verdicts) ids.push(v.attestationId);
    for (const c of [...changes.changes].reverse()) if (c.type === "attestation") ids.push(c.refId);
    for (const id of [...new Set(ids)].reverse()) { try { const a = await api.attestation(id); if (a.verdict === "accepted") return a; } catch { /* try the next */ } }
    return null;
  }, []);
}

function useWebGL() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    try { const c = document.createElement("canvas"); setOk(Boolean(c.getContext("webgl2") || c.getContext("webgl"))); } catch { setOk(false); }
  }, []);
  return ok;
}
function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)"); if (!mq) return;
    const on = () => setReduced(mq.matches); on(); mq.addEventListener?.("change", on); return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

export default function Human({ mcpUrl, still }: { mcpUrl: string; still: boolean }) {
  const latest = useLatestAttestation();
  const att = latest.data;
  return <div className="human">
    <Story att={att} attLoading={latest.readiness === "loading"} still={still} />
    <Strip att={att} />
    <Eyes />
    <Record />
    <Close mcpUrl={mcpUrl} />
    <Tiles mcpUrl={mcpUrl} />
  </div>;
}

/* The hero is the drawing, full width. The headline sits just below it; the five beats follow in one column. */
function Story({ att, attLoading, still }: { att: SignedAttestation | null; attLoading: boolean; still: boolean }) {
  const control = useRef<HeroControl>({ nudge: null, visible: true });
  const beatsRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [beat, setBeat] = useState(0);
  const webgl = useWebGL();
  const reduced = useReducedMotion();
  const live = Boolean(att);
  const attestationId = att?.id ?? SAMPLE_ATTESTATION_ID;

  /* The loop reports its progress so the six ticks in beat four follow it; it pauses rendering when off screen. */
  const onProgress = useCallback((p: number) => {
    const el = beatsRef.current; if (el) el.style.setProperty("--p", String(p));
    const b = Math.min(4, Math.floor(p)); setBeat(prev => (prev === b ? prev : b));
  }, []);
  useEffect(() => {
    const stage = stageRef.current; if (!stage) return;
    if (typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(entries => { for (const e of entries) control.current.visible = e.isIntersecting; }, { threshold: 0 });
    io.observe(stage);
    return () => io.disconnect();
  }, []);

  const useCanvas = webgl === true && !reduced;
  return <section className="story" id="plant">
    <div className="stage" ref={stageRef} aria-label="Agent team illustration: the Director delegates factory questions to the Engineer, the Technician supplies evidence, and verified results return over MCP. Gas flows through the factory pipework.">
      {webgl === null ? null : useCanvas ? <HeroScene control={control} attestationId={attestationId} still={still} onProgress={onProgress} /> : <HeroStatic attestationId={attestationId} />}
    </div>
    <div className="hero" data-dissolve="">
      <div className="hero-title">
        <h1 className="lines"><span className="line"><span data-line style={{ ["--i" as string]: 0 }}>Give your agent a world.</span></span></h1>
        <p className="lines lead"><span className="line"><span data-line style={{ ["--i" as string]: 1 }}>Vision. Telemetry. Identity.</span></span></p>
      </div>
      <div className="hero-side" data-rise style={{ ["--i" as string]: 3 }}>
        <p className="quiet">Steward gives agents a shared 3D world, equipment telemetry, and a persistent identity with scoped permissions. They can inspect the plant, remember what happened, communicate with other agents, and act through MCP tools. Every observation and handoff carries its context forward, so each agent knows its responsibilities, what has changed, and what needs to happen next.</p>
        <div className="actions"><a href="#connect" className="btn"><span>Connect your agent</span><span className="arrow" aria-hidden="true">→</span></a><Link href="/app" className="btn"><span>Open the dashboard</span></Link></div>
      </div>
    </div>
    <div className="beats" ref={beatsRef}>
      {BEATS.map((b, i) => <div className={`beat ${beat === i ? "is-on" : ""}`} key={b.title} data-dissolve="">
        <div className="say"><Reveal as="h2" manner="rise">{b.title}</Reveal><Reveal as="p" i={1}>{b.text}</Reveal></div>
        <Reveal i={2} manner="settle" className="frag" data-ui="">
          {i === 0 && <pre>{`resolve({ siteId: "harbor-works", assetTag: "P-101",\n          attribute: "commissioning_certificate" })`}</pre>}
          {i === 1 && <pre>{`{ status: "known", value: "CC-2026-0611-P101",\n  observedAt: "2026-06-11T09:30:00Z", ageSeconds: 11059200,\n  attestationId: "att_cc_p101_2026_0611" }`}</pre>}
          {i === 2 && <div className="card"><span className="ref">HW-P101-PRESSURE_BAR-0042</span><p>Harbor Works, plant room, north wall. Asset P-101, primary circulation pump, tag plate on the motor housing. Need: pressure gauge reading. Photograph the gauge with the tag plate visible. Expected 1.5 to 3.5 bar. Pays $0.50 on verified proof.</p></div>}
          {i === 3 && <ol className="ticks">{CHECKS.map((c, n) => <li key={c} style={{ ["--n" as string]: n }}><span className="box" aria-hidden="true" /><span className="name">{c}</span><span className="why">{c === "identity" ? `first try: plate reads P-102, P-101 is ${METRES_WEST} m west` : c === "plausibility" ? "2.4 bar inside 1.5 to 3.5" : c === "time" ? "inside the work-item window" : c === "integrity" ? "SHA-256 stored, not reused" : c === "geometry" ? "right position, not a sibling" : "harbor-works, P-101"}</span></li>)}</ol>}
          {i === 4 && <AttestationFrag att={att} loading={attLoading} live={live} />}
        </Reveal>
      </div>)}
    </div>
  </section>;
}

function AttestationFrag({ att, loading, live }: { att: Attestation | null; loading: boolean; live: boolean }) {
  const a = att ?? { id: SAMPLE_ATTESTATION_ID, assetTag: "P-101", attribute: "pressure_bar", value: 2.4, unit: "bar", observedAt: "2026-10-18T00:12:00Z", verifierVersion: "steward-verify/1", signature: "ed25519:…", evidenceHashes: ["sha256:…"] };
  return <div className="attestation">
    <span className="ref">{a.id}</span>
    <dl>
      <dt>asset</dt><dd>{a.assetTag} · {a.attribute}</dd>
      <dt>value</dt><dd>{formatValue(a.value, a.unit)}</dd>
      <dt>observed</dt><dd>{a.observedAt}</dd>
      <dt>verifier</dt><dd>{a.verifierVersion}</dd>
      <dt>signature</dt><dd className="sig">{a.signature}</dd>
    </dl>
    <span className={`state ${live ? "live" : ""}`}>{loading ? "Looking for a signed attestation on Harbor Works" : live ? "A real attestation from GET /api/attestations, Ed25519, valid" : "Every accepted fact is signed in this shape."}</span>
  </div>;
}

/* One work item, four states: four colour fields, the same card further along each time. */
function Strip({ att }: { att: Attestation | null }) {
  const states = [
    { word: "First the agent opens it.", state: "open", rows: [["requester", "Atlas"], ["budget", "$5.00"], ["attribute", "pressure_bar"], ["asked", "just now"]] },
    { word: "Then a technician is sent.", state: "dispatched", rows: [["channel", "Runner, iMessage via Inkbox"], ["deadline", "30 min"], ["expected", "1.5 to 3.5 bar"], ["pays", "$0.50 on proof"]] },
    { word: "Then the wrong plate is refused.", state: "rejected", rows: [["stated tag", "P-102"], ["identity", "failed"], ["reply", `P-101 is ${METRES_WEST} m west`], ["payment", "held"]] },
    { word: "Then it closes, signed and paid.", state: "resolved", rows: [["value", att ? formatValue(att.value, att.unit) : "2.4 bar"], ["checks", "6 of 6 passed"], ["attestation", att?.id ?? SAMPLE_ATTESTATION_ID], ["paid", "$0.50"]] },
  ];
  return <section className="strip" id="work" aria-label="One work item, four states">
    {states.map((s, i) => <div className="field" key={s.state} data-dissolve="">
      {i === 0 && <Reveal as="h2">One work item, four states.</Reveal>}
      <Reveal className="ticket-wrap" manner="settle" i={1}>
        <div className="ticket" data-ui="">
          <span className="ref">HW-P101-PRESSURE_BAR-0042</span>
          <span className="asset">P-101 · Primary circulation pump</span>
          <span className={`state ${s.state}`}>{s.state}</span>
          <dl>{s.rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        </div>
      </Reveal>
      <Reveal as="p" className="clause" i={2}>{s.word}</Reveal>
    </div>)}
  </section>;
}

/* Three eyes: three rows on a 5/7 split, statement left, the fragment right, each a different size. */
function Eyes() {
  const facts = useFacts(SITE, 15_000);
  const sensors = useMemo(() => latestPerAttribute(facts.data ?? []).filter(f => ["TS-801", "TS-802"].includes(f.assetTag)), [facts.data]);
  const now = Date.now();
  const sample = [{ tag: "TS-801", value: "21.4", when: "typical" }, { tag: "TS-802", value: "22.1", when: "typical" }];
  return <section className="eyes" id="eyes">
    <div data-dissolve=""><Reveal as="h2" className="lead">Three eyes, one record.</Reveal></div>
    <div className="row" data-dissolve="">
      <div className="say"><Reveal as="h3">The scan.</Reveal><Reveal as="p" i={1}>The twin comes from a 3D scan: 24 tagged assets with world positions, so a task card can say north wall, two metres west of P-102, and a wrong tag plate can be refused by geometry.</Reveal></div>
      <Reveal as="figure" className="pic big" manner="settle" i={2}><img src="/site/twin.jpg" alt="The Harbor Works plant room twin in the Steward dashboard, P-101 selected" loading="lazy" width={1008} height={616} /></Reveal>
    </div>
    <div className="row" data-dissolve="">
      <div className="say"><Reveal as="h3">The camera.</Reveal><Reveal as="p" i={1}>Twelve survey viewpoints and a technician's phone. A photo is evidence only after its tag, position, value, time and hash pass. Until then it is a claim.</Reveal></div>
      <div className="pair">
        <Reveal as="figure" className="pic wide" manner="settle" i={2}><img src="/site/wall.jpg" alt="The inspection wall: twelve survey viewpoints of the plant room" loading="lazy" width={1432} height={790} /></Reveal>
        <Reveal as="figure" className="pic tall" manner="settle" i={3}><img src="/site/phone.jpg" alt="The dashboard at phone width: the twin above the work items" loading="lazy" width={390} height={700} /></Reveal>
      </div>
    </div>
    <div className="row" data-dissolve="">
      <div className="say"><Reveal as="h3">The sensor.</Reveal><Reveal as="p" i={1}>Two temperature sensors report on their own and their readings expire after an hour. Nothing else in the room has a sensor, which is why the other two eyes exist.</Reveal></div>
      <div className="pair">
        <Reveal className="readings" manner="settle" i={2} data-ui="">
          {(sensors.length ? sensors.map(f => { const fr = freshness(f, now); return { tag: f.assetTag, value: formatValue(f.value), when: `${fr.status}, ${age(f.observedAt, now)}` }; }) : sample).map(r => <div className="reading" key={r.tag}><span className="tag">{r.tag}</span><span className="when">{r.when}</span><span className="value">{r.value}<small>°C</small></span></div>)}
          <span className="src">{sensors.length ? "Live from /facts, refreshed every 15 s" : facts.readiness === "loading" ? "Reading TS-801 and TS-802" : "Typical values until the sensors report."}</span>
        </Reveal>
        <Reveal as="figure" className="pic rail" manner="settle" i={3}><img src="/site/rail.jpg" alt="The dashboard rail: work items, facts with freshness bars and attestations" loading="lazy" width={420} height={840} /></Reveal>
      </div>
    </div>
  </section>;
}

/* What the record holds: two-ended rows in one narrow column, in groups. */
function Record() {
  const groups: { name: string; rows: [string, string][] }[] = [
    { name: "Verbs", rows: [["resolve", "known, stale, unknown or conflict"], ["attest", "accepted, rejected or needs clarification"], ["check", "valid, with the signed record"]] },
    { name: "Freshness", rows: [["reading", "1 hour"], ["condition", "24 hours"], ["document", "365 days"], ["identity", "never expires"]] },
    { name: "Checks", rows: [["scope", "same site, same asset"], ["identity", "tag plate matches"], ["geometry", "right position, not a sibling"], ["plausibility", "inside the spec range"], ["time", "inside the work-item window"], ["integrity", "SHA-256, never reused"]] },
    { name: "Runs on", rows: [["Inkbox", "messages, email and calls"], ["Manufact", "hosts the MCP"], ["Supabase", "facts, attestations, change feed"], ["Armature", "analytics on the MCP"]] },
  ];
  return <section className="record" id="record">
    <div className="col" data-dissolve="">
      <Reveal as="h2">What the record holds.</Reveal>
      {groups.map((g, gi) => <div className="group" key={g.name}>
        <Reveal as="span" className="gname" i={gi}>{g.name}</Reveal>
        <ul>{g.rows.map(([k, v], i) => <Reveal as="li" key={k} manner="slide" i={i}><span className="dot" aria-hidden="true" /><span className="k">{k}</span><span className="v">{v}</span></Reveal>)}</ul>
      </div>)}
    </div>
  </section>;
}

/* The close: a sentence with a blank, and the blank is the MCP URL. */
function Close({ mcpUrl }: { mcpUrl: string }) {
  const [url, setUrl] = useState(mcpUrl);
  const [copied, setCopied] = useState(false);
  const cmd = `claude mcp add --transport http steward ${url.trim() || mcpUrl}`;
  async function copy() { try { await navigator.clipboard.writeText(cmd); setCopied(true); setTimeout(() => setCopied(false), 1600); } catch { setCopied(false); } }
  return <section className="close" id="connect">
    <form className="sentence" data-dissolve="" onSubmit={e => { e.preventDefault(); copy(); }}>
      <label className="blank-wrap">
        <span className="t">Point Claude Code at</span>
        <input className="blank" value={url} onChange={e => setUrl(e.target.value)} aria-label="MCP URL" spellCheck={false} autoComplete="off" />
        <span className="t">and</span>
        <button type="submit" className="btn big"><span>{copied ? "copied" : "copy the command"}</span></button>
      </label>
    </form>
    <p className="after" data-dissolve="">Copies <code>{cmd}</code>. Then ask the agent to clear Harbor Works for restart and sign off nothing it cannot prove.</p>
  </section>;
}

/* The footer is a board of tiles. */
function Tiles({ mcpUrl }: { mcpUrl: string }) {
  const [time, setTime] = useState("");
  useEffect(() => {
    const tick = () => setTime(new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit" }).format(new Date()));
    tick(); const t = setInterval(tick, 15_000); return () => clearInterval(t);
  }, []);
  return <footer className="tiles" data-dissolve="">
    <div className="tile statement"><p>Rule-based verification, one real signature.</p><small>Steward does not certify equipment or replace an engineer's sign-off.</small></div>
    <nav className="tile nav" aria-label="Sections"><a href="#plant">The plant</a><a href="#work">The work item</a><a href="#eyes">Three eyes</a><a href="#record">The record</a><a href="#connect">Connect</a><a href="/llms.txt">/llms.txt</a></nav>
    <div className="tile place"><span>Harbor Works</span><span>68 Harbor Way, Oakland</span><span>{time ? `${time} local` : ""}</span></div>
    <div className="tile address"><a href={mcpUrl}>{mcpUrl}</a></div>
    <div className="tile mark" aria-hidden="true"><span>Steward</span></div>
    <Link href="/app" className="tile go"><span>Open the dashboard</span><svg viewBox="0 0 48 48" width="48" height="48" aria-hidden="true"><path d="M8 24h30M26 12l12 12-12 12" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="square" /></svg></Link>
  </footer>;
}
