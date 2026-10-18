"use client";

import { useEffect, useMemo, useRef } from "react";
import type { Change } from "@/lib/types-2";
import type { Readiness } from "@/lib/reality";
import { NotReady, Panel } from "./rail";

const typeWord: Record<Change["type"], string> = { fact: "fact", work_item: "work item", attestation: "attestation", dispatch: "dispatch", escalation: "escalation", owner_decision: "owner decision", a2a: "agent task", eval: "eval" } as Record<Change["type"], string>;

export function Timeline({ changes, version, readiness, error, reload, transport, onTag }: { changes: Change[]; version: number; readiness: Readiness; error: string; reload: () => void; transport: "realtime" | "polling"; onTag: (tag: string) => void }) {
  const rows = useMemo(() => [...changes].sort((a, b) => b.version - a.version), [changes]);
  const seen = useRef(new Set<number>());
  const fresh = useRef(new Set<number>());
  useEffect(() => { fresh.current = new Set(rows.filter(r => !seen.current.has(r.version)).map(r => r.version)); rows.forEach(r => seen.current.add(r.version)); }, [rows]);
  return <section className="timeline" aria-label="Timeline">
    <Panel title="Timeline" count={rows.length ? `version ${version} · ${transport === "realtime" ? "realtime" : "polling"}` : undefined}>
      {rows.length === 0 ? <div className="panel-body"><NotReady readiness={readiness} error={error} reload={reload} empty="No changes yet. Every fact, dispatch, verdict and decision lands here." /></div>
        : rows.map(c => <button key={c.version} className={`tl-row ${fresh.current.has(c.version) ? "fresh-row" : ""}`} onClick={() => c.assetTag && onTag(c.assetTag)} disabled={!c.assetTag}>
          <span className="at">{new Date(c.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
          <span className={`type ${c.type}`}>{typeWord[c.type] ?? c.type}</span>
          <span className="summary">{c.summary}{c.simulated ? <span className="sim-tag">simulated</span> : null}</span>
          <span className="tag">{c.assetTag ?? ""}</span>
        </button>)}
    </Panel>
  </section>;
}
