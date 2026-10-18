"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { WorkItem } from "../../../../shared/types";
import type { Change } from "@/lib/types-2";
import { api, type FactRow, type InboundResult, type SignedAttestation } from "@/lib/api";
import { age, attributeLabel, formatValue, freshness, isOpen, latestPerAttribute, stateLabel, untilDeadline, type Readiness } from "@/lib/reality";
import { errorMessage, useModal } from "../ui";

export function Panel({ title, count, demo, action, children }: { title: string; count?: ReactNode; demo?: boolean; action?: ReactNode; children: ReactNode }) {
  return <section className="panel" aria-label={title}>
    <div className="panel-head"><h2>{title}{count !== undefined ? <span className="count"> {count}</span> : null}</h2>{demo ? <span className="demo">demo control</span> : null}{action}</div>
    {children}
  </section>;
}

export function NotReady({ readiness, error, reload, empty }: { readiness: Readiness; error: string; reload: () => void; empty: string }) {
  if (readiness === "loading") return <div className="empty">Loading</div>;
  const text = readiness === "not_ready" ? "Not available yet: the backend has not shipped this endpoint." : readiness === "error" ? error : empty;
  return <div className="empty"><span>{text}</span>{readiness !== "ready" ? <button className="btn btn-small" onClick={reload}>Retry</button> : null}</div>;
}

/* Work items: waiting list from GET /changes, each with escalate. */
export function WorkItemsPanel({ items, readiness, error, reload, onFocus, selectedId, onChanged }: { items: WorkItem[]; readiness: Readiness; error: string; reload: () => void; onFocus: (componentId: string) => void; selectedId: string | null; onChanged: () => void }) {
  const open = items.filter(isOpen);
  const closed = items.filter(w => !isOpen(w));
  return <Panel title="Work items" count={open.length ? `${open.length} open` : undefined}>
    <div className="panel-body">
      {open.length === 0 ? <NotReady readiness={readiness} error={error} reload={reload} empty="Nothing waiting. A resolve call with a budget opens one." /> : null}
      {[...open, ...closed.slice(0, 3)].map(w => <WorkItemRow key={w.id} item={w} selected={selectedId === w.componentId} onFocus={() => onFocus(w.componentId)} onChanged={onChanged} />)}
    </div>
  </Panel>;
}

function WorkItemRow({ item, selected, onFocus, onChanged }: { item: WorkItem; selected: boolean; onFocus: () => void; onChanged: () => void }) {
  const [level, setLevel] = useState<1 | 2 | 3 | 4>(() => (Math.min(4, item.dispatches.length + 1) as 1 | 2 | 3 | 4));
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  async function escalate() {
    setBusy(true); setResult("");
    try { const next = await api.escalate(item.id, level); setResult(`Escalated to level ${level}; state ${stateLabel[next.state]}, ${next.dispatches.length} dispatches.`); onChanged(); }
    catch (e) { setResult(errorMessage(e)); }
    finally { setBusy(false); }
  }
  return <div className={`row ${selected ? "selected" : ""}`}>
    <button className="top" onClick={onFocus} style={{ width: "100%", textAlign: "left" }}><span className="tag">{item.assetTag}</span><span className={`state ${item.state}`}>{stateLabel[item.state]}</span></button>
    <div className="attr"><b>{attributeLabel(item.attribute)}</b> for {item.requester}</div>
    <div className="ref">{item.reference}</div>
    <div className="sub"><span>{untilDeadline(item.deadlineAt)}</span><span>{item.dispatches.length} {item.dispatches.length === 1 ? "dispatch" : "dispatches"}</span>{item.dispatches.at(-1) ? <span>last by {item.dispatches.at(-1)!.channel}</span> : null}{item.verdicts.length ? <span>{item.verdicts.length} {item.verdicts.length === 1 ? "verdict" : "verdicts"}, last {item.verdicts.at(-1)!.verdict.replace("_", " ")}</span> : null}</div>
    {isOpen(item) ? <div className="row-actions">
      <select aria-label="Escalation level" value={level} onChange={e => setLevel(Number(e.target.value) as 1 | 2 | 3 | 4)}><option value={1}>1 · re-send</option><option value={2}>2 · email</option><option value={3}>3 · call</option><option value={4}>4 · ask the owner</option></select>
      <button className="btn btn-small" onClick={escalate} disabled={busy}>{busy ? "Escalating" : "Escalate"}</button>
      {result ? <span className="result">{result}</span> : null}
    </div> : null}
  </div>;
}

/* Facts: latest per asset/attribute, freshness bar from observedAt and ttlSeconds. */
export function FactsPanel({ facts, readiness, error, reload, onFocus, selectedId, onOpenAttestation }: { facts: FactRow[]; readiness: Readiness; error: string; reload: () => void; onFocus: (componentId: string) => void; selectedId: string | null; onOpenAttestation: (id: string) => void }) {
  const latest = useMemo(() => latestPerAttribute(facts), [facts]);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(t); }, []);
  return <Panel title="Facts" count={latest.length || undefined}>
    <div className="panel-body">
      {latest.length === 0 ? <NotReady readiness={readiness} error={error} reload={reload} empty="No facts recorded for this site yet." /> : null}
      {latest.map(f => { const fr = freshness(f, now); const status = f.status ?? fr.status; return <button key={f.id} className={`row ${selectedId === f.componentId ? "selected" : ""}`} onClick={() => onFocus(f.componentId)}>
        <div className="top"><span className="tag">{f.assetTag}</span><span className={`state ${status}`}>{status}</span></div>
        <div className="attr">{attributeLabel(f.attribute)}</div>
        <div className="value">{formatValue(f.value, f.unit)}</div>
        <div className="fresh" role="img" aria-label={`freshness ${Math.round(fr.ratio * 100)} percent`}><span style={{ width: `${Math.round(fr.ratio * 100)}%` }} /></div>
        <div className="sub"><span>{age(f.observedAt, now)}</span><span>{f.ttlSeconds === null ? "never expires" : f.expiresAt ? `expires ${age(f.expiresAt, now).replace(" ago", "")}` : ""}</span><span>{f.source.kind} · <span className="mono">{f.source.ref}</span></span>{f.attestationId ? <span className="mono" role="link" tabIndex={0} onClick={e => { e.stopPropagation(); onOpenAttestation(f.attestationId); }} onKeyDown={e => { if (e.key === "Enter") { e.stopPropagation(); onOpenAttestation(f.attestationId); } }}>{f.attestationId.slice(0, 14)}</span> : null}</div>
      </button>; })}
    </div>
  </Panel>;
}

/* Attestations: badges collected from facts, work item verdicts and the change feed. */
export function AttestationsPanel({ facts, items, changes, onOpen }: { facts: FactRow[]; items: WorkItem[]; changes: Change[]; onOpen: (id: string) => void }) {
  const badges = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of changes) if (c.type === "attestation") map.set(c.refId, c.assetTag ?? "");
    for (const w of items) for (const v of w.verdicts) map.set(v.attestationId, w.assetTag);
    for (const f of facts) if (f.attestationId) map.set(f.attestationId, f.assetTag);
    return [...map.entries()].reverse();
  }, [facts, items, changes]);
  return <Panel title="Attestations" count={badges.length || undefined}>
    {badges.length ? <div className="badges">{badges.map(([id, tag]) => <button key={id} className="badge" onClick={() => onOpen(id)} title={id}><span className="dot" aria-hidden="true" />{tag ? `${tag} · ` : ""}{id.length > 18 ? `${id.slice(0, 18)}…` : id}</button>)}</div>
      : <div className="panel-body"><div className="empty">No signed attestations yet. One appears when a submission passes all six checks.</div></div>}
  </Panel>;
}

export function AttestationDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [data, setData] = useState<SignedAttestation | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useModal(true, onClose);
  useEffect(() => { let alive = true; setData(null); setError(""); api.attestation(id).then(a => { if (alive) setData(a); }).catch(e => { if (alive) setError(errorMessage(e)); }); return () => { alive = false; }; }, [id, attempt]);
  return <div className="drawer-backdrop" onClick={onClose}>
    <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="att-title" onClick={e => e.stopPropagation()}>
      <button className="btn btn-quiet btn-small close" onClick={onClose}>Close</button>
      <h2 id="att-title">{data ? `${data.assetTag} · ${attributeLabel(data.attribute)}` : "Attestation"}</h2>
      <div className="id">{id}</div>
      {error ? <div className="empty"><span>{error}</span><button className="btn btn-small" onClick={() => setAttempt(a => a + 1)}>Retry</button></div> : !data ? <div className="empty">Fetching the signed record</div> : <>
        <div className={`valid ${data.valid ? "ok" : ""}`}>{data.valid ? "Signature valid" : "Signature did not verify"} · {data.verdict.replace("_", " ")}</div>
        <dl>
          <dt>Value</dt><dd>{formatValue(data.value, data.unit)}</dd>
          <dt>Observed</dt><dd>{new Date(data.observedAt).toLocaleString()} ({age(data.observedAt)})</dd>
          <dt>Signed</dt><dd>{new Date(data.signedAt).toLocaleString()}</dd>
          <dt>Source</dt><dd>{data.source.kind} · <span className="mono">{data.source.ref}</span></dd>
          <dt>Verifier</dt><dd className="mono">{data.verifierVersion}</dd>
          <dt>Evidence</dt><dd className="mono">{data.evidenceHashes.length ? data.evidenceHashes.map(h => <div key={h}>{h}</div>) : "none"}</dd>
          <dt>Public key</dt><dd className="mono">{data.publicKey}</dd>
        </dl>
        <table className="checks"><thead><tr><th>Check</th><th>Result</th><th>Reason</th></tr></thead><tbody>{data.checks.map(c => <tr key={c.name}><td className="name">{c.name}</td><td className={`pass ${c.passed ? "ok" : ""}`}>{c.passed ? "passed" : "failed"}</td><td className="rule">{c.reason}</td></tr>)}</tbody></table>
        <div className="sig">{data.signature}</div>
      </>}
    </aside>
  </div>;
}

/* Demo controls. Clearly labelled: these stand in for the technician's phone and the owner's reply. */
export function ContractorReply({ items, onChanged }: { items: WorkItem[]; onChanged: () => void }) {
  const open = items.filter(isOpen);
  const [reference, setReference] = useState(open[0]?.reference ?? "");
  const [statedTag, setStatedTag] = useState(open[0]?.assetTag ?? "");
  const [value, setValue] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<InboundResult | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { if (!reference && open[0]) { setReference(open[0].reference); setStatedTag(open[0].assetTag); } }, [open, reference]);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(""); setResult(null);
    try { setResult(await api.inboundLocal({ reference, statedTag: statedTag || undefined, value: value || undefined, body: `${statedTag || ""} ${value ? `reads ${value}` : ""} ref ${reference}`.trim(), file })); onChanged(); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <Panel title="Reply as contractor" demo>
    <form className="form" onSubmit={submit}>
      <label className="field">Reference{open.length ? <select value={reference} onChange={e => { setReference(e.target.value); const w = open.find(x => x.reference === e.target.value); if (w) setStatedTag(w.assetTag); }}>{open.map(w => <option key={w.id} value={w.reference}>{w.reference}</option>)}<option value="">other</option></select> : null}{!open.length || reference === "" ? <input className="mono" value={reference} onChange={e => setReference(e.target.value)} placeholder="HW-P101-PRESSURE_BAR-0042" required /> : null}</label>
      <div className="two">
        <label className="field">Tag plate reads<input className="mono" value={statedTag} onChange={e => setStatedTag(e.target.value.toUpperCase())} placeholder="P-101" /></label>
        <label className="field">Reading<input value={value} onChange={e => setValue(e.target.value)} placeholder="2.4" /></label>
      </div>
      <label className="file">Photo (optional) <input type="file" accept="image/*,.pdf" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
      <div className="actions"><button className="btn btn-primary btn-small" type="submit" disabled={busy || !reference}>{busy ? "Sending" : "Send reply"}</button>{error ? <span className="muted" style={{ fontSize: 13 }}>{error}</span> : null}</div>
      {result ? <div className="result"><b className={result.verdict === "accepted" ? "" : "rejected"}>{result.routed ? (result.verdict ? result.verdict.replace("_", " ") : "routed") : "not routed"}</b>{result.reasons?.map(r => <span key={r}>{r}</span>)}{result.checks?.filter(c => !c.passed).map(c => <span key={c.name}>{c.name}: {c.reason}</span>)}{result.attestationId ? <span className="mono">{result.attestationId}</span> : null}</div> : null}
    </form>
  </Panel>;
}

export function OwnerDecision({ propertyId, items, onChanged }: { propertyId: string; items: WorkItem[]; onChanged: () => void }) {
  const open = items.filter(isOpen);
  const [workItemId, setWorkItemId] = useState(open[0]?.id ?? "");
  const [decision, setDecision] = useState("approve");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  useEffect(() => { if (!workItemId && open[0]) setWorkItemId(open[0].id); }, [open, workItemId]);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setResult("");
    try { const w = await api.ownerDecision(propertyId, { workItemId, decision, note: note || undefined }); setResult(`Recorded. ${w.reference} is now ${stateLabel[w.state]}.`); onChanged(); }
    catch (err) { setResult(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <Panel title="Owner decision" demo>
    <form className="form" onSubmit={submit}>
      <label className="field">Work item{open.length ? <select value={workItemId} onChange={e => setWorkItemId(e.target.value)}>{open.map(w => <option key={w.id} value={w.id}>{w.reference}</option>)}</select> : <input className="mono" value={workItemId} onChange={e => setWorkItemId(e.target.value)} placeholder="work item id" required />}</label>
      <div className="two">
        <label className="field">Decision<select value={decision} onChange={e => setDecision(e.target.value)}><option value="approve">approve</option><option value="reject">reject</option><option value="defer">defer</option></select></label>
        <label className="field">Note<input value={note} onChange={e => setNote(e.target.value)} placeholder="optional" /></label>
      </div>
      <div className="actions"><button className="btn btn-small" type="submit" disabled={busy || !workItemId}>{busy ? "Recording" : "Record decision"}</button>{result ? <span className="muted" style={{ fontSize: 13 }}>{result}</span> : null}</div>
    </form>
  </Panel>;
}
