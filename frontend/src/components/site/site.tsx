"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import ModeSwitch, { type Mode } from "./mode-switch";
import Human from "./human";
import AgentDoc from "./agent-doc";
import "./site.css";

const MCP_URL = "http://127.0.0.1:8002/mcp";
const KEY = "steward.mode";
type Phase = "human" | "to-agent" | "agent" | "to-human";

function readStoredMode(): Mode | null {
  try { const url = new URL(window.location.href); const q = url.searchParams.get("mode"); if (q === "agent" || q === "human") return q; } catch { /* no URL */ }
  try { const v = window.localStorage.getItem(KEY); if (v === "agent" || v === "human") return v; } catch { /* storage blocked */ }
  return null;
}
function remember(mode: Mode) {
  try { window.localStorage.setItem(KEY, mode); } catch { /* storage blocked */ }
  try { const url = new URL(window.location.href); if (mode === "agent") url.searchParams.set("mode", "agent"); else url.searchParams.delete("mode"); window.history.replaceState(null, "", url.toString()); } catch { /* no history */ }
}

export default function Site() {
  const [mode, setMode] = useState<Mode>("human");
  const [phase, setPhase] = useState<Phase>("human");
  const timer = useRef<number>(0);
  const rootRef = useRef<HTMLDivElement>(null);

  /* Deep link and memory, read after hydration. */
  useEffect(() => { const m = readStoredMode(); if (m === "agent") { setMode("agent"); setPhase("agent"); } }, []);

  /* Scatter offsets for the dissolve, set once per element, deterministic. */
  useEffect(() => {
    const root = rootRef.current; if (!root) return;
    const els = root.querySelectorAll<HTMLElement>("[data-dissolve]");
    els.forEach((el, i) => {
      const a = (i * 137.508) % 360; const r = 18 + ((i * 53) % 30);
      el.style.setProperty("--dx", `${Math.cos(a * Math.PI / 180) * r}px`);
      el.style.setProperty("--dy", `${Math.sin(a * Math.PI / 180) * r + 12}px`);
      el.style.setProperty("--i", String(i % 21));
    });
  }, [phase]);

  const switchMode = useCallback((next: Mode) => {
    if (next === mode) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    setMode(next); remember(next);
    window.clearTimeout(timer.current);
    window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
    if (reduced) { setPhase(next); return; }
    if (next === "agent") { setPhase("to-agent"); timer.current = window.setTimeout(() => setPhase("agent"), 720); }
    else { setPhase("to-human"); timer.current = window.setTimeout(() => setPhase("human"), 320); }
  }, [mode]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const agentShown = phase === "agent" || phase === "to-human";
  return <div className={`site mode-${mode}`} data-phase={phase} ref={rootRef}>
    <header className="bar">
      {mode === "agent" ? <span className="wordmark">Steward</span> : <Link href="/" className="wordmark">Steward</Link>}
      <ModeSwitch mode={mode} onChange={switchMode} />
      {mode === "human" && <nav className="links" aria-label="Sections"><a href="#work">Work item</a><a href="#eyes">Three eyes</a><a href="#record">Record</a><a href="#connect">Connect</a></nav>}
    </header>
    <main>
      {phase !== "agent" && <div className="human-wrap" inert={phase !== "human" ? true : undefined} aria-hidden={phase !== "human"}><Human mcpUrl={MCP_URL} still={phase !== "human"} /></div>}
      {agentShown && <div className="agent-wrap" inert={phase !== "agent" ? true : undefined} aria-hidden={phase !== "agent"}><AgentDoc mcpUrl={MCP_URL} /></div>}
    </main>
  </div>;
}
