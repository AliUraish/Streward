"use client";

import type { KeyboardEvent } from "react";

export type Mode = "human" | "agent";

/* The Human / Agent switch: a track with a sliding knob under two words. The words sit over the knob
   and invert where it covers them (mix-blend-mode: difference), so only the knob moves. */
export default function ModeSwitch({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const agent = mode === "agent";
  function onKey(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key === "ArrowLeft" || e.key === "Home") { e.preventDefault(); onChange("human"); }
    if (e.key === "ArrowRight" || e.key === "End") { e.preventDefault(); onChange("agent"); }
  }
  return <button type="button" role="switch" aria-checked={agent} aria-label="Read this page as an agent" className={`mode ${agent ? "is-agent" : ""}`} onClick={() => onChange(agent ? "human" : "agent")} onKeyDown={onKey} data-mode-switch="">
    <span className="knob" aria-hidden="true" />
    <span className="word human">Human</span>
    <span className="word agent">Agent</span>
  </button>;
}
