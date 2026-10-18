"use client";

/* Human · Agent: the dashboard has one switch now, in the top bar (mode-11.ts; owner, Oct 18: "it should be one on top
   switch for agents"). These helpers keep their old names so every page and panel follows that one switch: useViewMode
   returns the global mode and ViewSwitch draws nothing. Agent views show the same records as an agent reads them: the
   endpoints, the records as plain text and as JSON. */
import { useEffect, useState } from "react";
import { useMode } from "@/lib/mode-11";
import { Btn } from "./ui3";
import "./dash10.css";

export type View = "human" | "agent";
export function useViewMode(_key: string): [View | null, (v: View) => void] {
  const [mode, setMode] = useMode();
  return [mode, setMode];
}
export function ViewSwitch(_props: { agent: boolean; onChange: (agent: boolean) => void; label: string; small?: boolean }) { return null; }

function copyText(text: string): Promise<boolean> {
  const fallback = () => {
    try {
      const ta = document.createElement("textarea"); ta.value = text; ta.setAttribute("readonly", "");
      ta.style.position = "fixed"; ta.style.top = "0"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select(); const ok = document.execCommand("copy"); ta.remove(); return ok;
    } catch { return false; }
  };
  try { if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text).then(() => true, fallback); } catch { /* no clipboard */ }
  return Promise.resolve(fallback());
}
export function CopyBtn({ text, what }: { text: string; what: string }) {
  const [done, setDone] = useState<"" | "ok" | "fail">("");
  useEffect(() => { if (!done) return; const t = window.setTimeout(() => setDone(""), 1800); return () => window.clearTimeout(t); }, [done]);
  return <>
    <Btn quiet small disabled={!text} onClick={() => { void copyText(text).then(ok => setDone(ok ? "ok" : "fail")); }}>{done === "ok" ? "Copied" : done === "fail" ? "Copy failed" : "Copy"}<span className="sr-only"> {what}</span></Btn>
    <span className="sr-only" role="status">{done === "ok" ? `Copied ${what}` : done === "fail" ? `Could not copy ${what}; select the text instead` : ""}</span>
  </>;
}

/* What an agent reads: the endpoints, then the text and the JSON, each with Copy. */
export function AgentText({ endpoints, text, json, what }: { endpoints: string[]; text: string; json?: unknown; what: string }) {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const jsonText = json === undefined ? "" : JSON.stringify(json, null, 2);
  return <div className="at10">
    <ul className="at-urls" aria-label="Endpoints">{endpoints.map(e => <li key={e}><a className="lnk" href={e} target="_blank" rel="noreferrer">{origin}{e}</a></li>)}</ul>
    <div className="at-block">
      <div className="at-head"><span className="meta">As text</span><CopyBtn text={text} what={`${what} as text`} /></div>
      <pre className="pre10" tabIndex={0} aria-label={`${what} as text`}>{text}</pre>
    </div>
    {jsonText ? <details className="at-block">
      <summary>As JSON</summary>
      <div className="at-head"><CopyBtn text={jsonText} what={`${what} as JSON`} /></div>
      <pre className="pre10" tabIndex={0} aria-label={`${what} as JSON`}>{jsonText}</pre>
    </details> : null}
  </div>;
}
