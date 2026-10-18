"use client";

/* The asset drawer: facts, issues, obligations and the valve inspection result (frames and explanation) for one asset.
   It floats over the page, so it is the one place a scrim is used. Esc closes; focus is trapped while open. */
import type { Remote } from "@/lib/reality";
import { api3 } from "@/lib/api-3";
import { useFacts3 } from "@/lib/hooks-3";
import { latestPerAttribute, formatValue } from "@/lib/reality";
import type { Asset3, Issue3, Obligation, SiteId3, ValveResult } from "@/lib/types-3";
import { useModal } from "../ui";
import { Btn, State, SynthTag, ago, day, fx, words } from "./ui3";
import { isOpenIssue, pinOf, valveWord } from "./environment";
import { regulationName } from "./walkthrough";

const obligationWord: Record<Obligation["status"], string> = { ok: "ok", due_soon: "due soon", overdue: "overdue", blocked: "blocked" };

export default function AssetDrawer({ siteId, tag, asset, issues, obligations, valve, onClose, onFocus }: { siteId: SiteId3; tag: string; asset?: Asset3; issues: Issue3[]; obligations: Remote<Obligation[]>; valve: ValveResult | null; onClose: () => void; onFocus: (action: "focus" | "orbit" | "highlight") => void }) {
  useModal(true, onClose);
  const facts = useFacts3(siteId, tag);
  const pin = asset ? pinOf(asset) : null;
  const mine = (obligations.data ?? []).filter(o => o.assetTag === tag);
  return <div className="drawer3-wrap">
    <button type="button" className="scrim3" aria-label="Close the asset drawer" onClick={onClose} tabIndex={-1} />
    <aside className="drawer3" role="dialog" aria-modal="true" aria-labelledby="drawer3-title">
      <header>
        <div><h3 id="drawer3-title">{tag}</h3><p>{asset ? `${asset.name}${asset.kind ? `, ${words(asset.kind)}` : ""}` : "This asset is not in the register the backend returned."}<SynthTag rec={asset} /></p></div>
        <Btn quiet small onClick={onClose}>Close</Btn>
      </header>
      <div className="d-actions"><Btn small arrow onClick={() => onFocus("focus")}>Focus</Btn><Btn small quiet onClick={() => onFocus("orbit")}>Orbit</Btn></div>

      <section>
        <h4>Facts</h4>
        <dl className="kv3">
          <dt>Pin</dt><dd>{pin ? `${pin.map(v => v.toFixed(2)).join(", ")} (${asset?.pinSource === "placed" ? "placed" : "estimated"})` : "No pin yet"}</dd>
          {asset?.location ? <><dt>Location</dt><dd>{asset.location}</dd></> : null}
          {asset?.spec ? Object.entries(asset.spec).slice(0, 8).map(([k, v]) => <div key={k} className="kv-pair"><dt>{words(k)}</dt><dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></div>) : null}
        </dl>
        <State remote={facts} what="facts" isEmpty={f => f.length === 0} empty="No recorded facts for this asset yet.">
          {f => <ul className="facts3">{latestPerAttribute(f).map(x => <li key={x.id}><span className="k">{words(x.attribute)}</span><span className="v">{formatValue(x.value, x.unit)}</span><span className="a">{x.status}, {ago(x.observedAt)}</span></li>)}</ul>}
        </State>
      </section>

      <section>
        <h4>Issues</h4>
        {issues.length ? <ul className="rows3 plain">{issues.map(i => <li key={i.id}><span className="r1"><span className={`sig ${!isOpenIssue(i) ? "ok" : i.severity === "high" ? "bad" : "warn"}`} aria-hidden="true" /><strong>{i.severity}</strong><span className="sev">{words(i.kind)}{i.status ? `, ${words(i.status)}` : ""}</span><SynthTag rec={i} /></span><span className="r2">{i.summary}</span><span className="r3">{ago(i.at)}{i.assignedTo ? `, assigned to ${i.assignedTo}` : ""}</span></li>)}</ul> : <p className="st3 empty">No issues on this asset.</p>}
      </section>

      <section>
        <h4>Obligations</h4>
        <State remote={obligations} what="obligations" isEmpty={() => mine.length === 0} empty="No obligations attached to this asset.">
          {() => <ul className="rows3 plain">{mine.map(o => <li key={o.id}><span className="r1"><span className={`sig ${o.status === "ok" ? "ok" : o.status === "due_soon" ? "warn" : "bad"}`} aria-hidden="true" /><strong>{o.title}</strong><SynthTag rec={o} /></span><span className="r2">{obligationWord[o.status]}, due {day(o.dueAt)}; {o.frequency}{o.regulationIds?.[0] ? `; ${regulationName(o.regulationIds[0])}` : ""}</span>{o.documentId ? <a className="lnk r3" href={api3.documentFileUrl(o.documentId)} target="_blank" rel="noreferrer">Open the document</a> : null}</li>)}</ul>}
        </State>
      </section>

      {valve || asset?.kind === "valve" ? <section>
        <h4>Valve inspection</h4>
        {valve ? <>
          <p className={`v-res ${valve.status === "not_fixed" ? "bad" : ""}`}><span className={`sig ${valve.status === "fixed" ? "ok" : valve.status === "not_fixed" ? "bad" : "warn"}`} aria-hidden="true" />{valveWord[valve.status]}, score {fx(valve.score)} against a threshold of {fx(valve.threshold)}{valve.model ? `, ${valve.model}` : ""}</p>
          {valve.frames?.length ? <div className="v-frames">{valve.frames.slice(0, 16).map((f, i, all) => <img key={f} src={api3.frameUrl(siteId, tag, f)} alt={`Agent eye view of ${tag}, ${i + 1} of ${Math.min(all.length, 16)}`} loading="lazy" />)}</div> : <p className="st3 empty">No frames for this valve.</p>}
          {valve.explanation ? <dl className="kv3">
            <dt>Finding</dt><dd>{valve.explanation.finding}</dd>
            <dt>Evidence</dt><dd>{valve.explanation.evidence}</dd>
            <dt>Confidence</dt><dd>{String(valve.explanation.confidence)}</dd>
            <dt>Action</dt><dd>{valve.explanation.recommendedAction}</dd>
          </dl> : <p className="st3 empty">{valve.status === "fixed" ? "No explanation needed: the valve sits with its peers." : "No explanation yet."}</p>}
          <p className="note3">An embedding anomaly score, not a trained defect classifier.</p>
        </> : <p className="st3 empty">This valve has not been inspected yet.</p>}
      </section> : null}
    </aside>
  </div>;
}
