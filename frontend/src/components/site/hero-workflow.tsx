import HeroAgent from "./hero-agent";

const WORKFLOWS = [
  { asset: "P-101", title: "Pump inspection", attribute: "pressure_bar", value: "2.4 bar", requirement: "1.5–3.5 bar", result: "Pressure verified", proof: "att_sample_p101_pressure" },
  { asset: "TS-801", title: "Sensor reading", attribute: "temperature_c", value: "21.4 °C", requirement: "Fresh reading + asset identity", result: "Reading verified", proof: "att_sample_ts801_temperature" },
  { asset: "V-504", title: "Valve maintenance", attribute: "condition", value: "Seal inspected", requirement: "Tagged photos + inspection notes", result: "Evidence verified", proof: "att_sample_v504_condition" },
] as const;

function DocumentGlyph() {
  return <svg viewBox="0 0 32 38" width="28" height="34" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><path d="M3 2h17l9 9v25H3zM20 2v10h9M9 19h14M9 25h14M9 31h8" /></svg>;
}

function CheckGlyph({ complete = true }: { complete?: boolean }) {
  return <svg className="agent-check" viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d={complete ? "m3 10 4 4L17 4" : "M4 16 16 4M5 4h11v11"} /></svg>;
}

export default function HeroWorkflow({ beat, topic = 0, attestationId, visible = true }: { beat: number; topic?: number; attestationId: string; visible?: boolean }) {
  const step = Math.min(4, Math.max(1, beat));
  const work = WORKFLOWS[topic % WORKFLOWS.length];
  const proof = topic % WORKFLOWS.length === 0 ? attestationId : work.proof;
  const calls = [
    { tool: "resolve", args: `assetTag: "${work.asset}"`, result: "Fresh evidence requested", ready: 1 },
    { tool: "eye_go_to", args: `assetTag: "${work.asset}"`, result: "Asset framed in the 3D world", ready: 2 },
    { tool: "attest", args: `attribute: "${work.attribute}"`, result: "Scope, identity and evidence checked", ready: 3 },
    { tool: "check", args: "attestationId: proof.id", result: "Signed result returned", ready: 4 },
  ];
  return <div className={`agent-world${visible ? " is-visible" : ""}`} data-step={step} data-topic={topic % WORKFLOWS.length} data-ui="" aria-hidden={!visible} inert={!visible ? true : undefined}>
    <div className="agent-world-heading"><p>Agents at work.</p></div>
    <div className="agent-world-workspace">
      <div className="agent-contract">
        <div className="agent-contract-heading"><DocumentGlyph /><div><strong>Task contract</strong><span>Director → Engineer</span></div></div>
        <p className="agent-contract-goal">{work.title}, with proof.</p>
        <dl><div><dt>Scope</dt><dd>Harbor Works · {work.asset}</dd></div><div><dt>Authority</dt><dd>Read · inspect · attest</dd></div><div><dt>Budget</dt><dd>$5.00 ceiling</dd></div><div><dt>Completion</dt><dd>{work.requirement}</dd></div></dl>
        <div className="agent-contract-signature"><CheckGlyph /><span>Identity attached. Scope enforced.</span></div>
      </div>
      <div className="agent-world-team"><HeroAgent beat={step} topic={topic} attestationId={proof} /><div className="agent-world-identity"><CheckGlyph /> Persistent identities · scoped permissions</div></div>
      <div className="agent-call-stream">
        <div className="agent-call-heading"><strong>MCP calls</strong><span>{step < 4 ? "Working" : "Complete"}</span></div>
        <ol>{calls.map((call, index) => <li key={call.tool} className={step >= call.ready ? "is-arrived" : ""} style={{ ["--call-delay" as string]: `${index * 80}ms` }}>
          <div className="agent-call-name"><code title={call.args}>{call.tool}</code><span aria-hidden="true">{step >= call.ready ? "↗" : "·"}</span></div><code className="agent-call-args">{call.args}</code><span className="agent-call-result">{step >= call.ready ? call.result : "Waiting for the previous call"}</span>
        </li>)}</ol>
      </div>
    </div>
    <div className={`agent-world-result${step === 4 ? " is-complete" : ""}`}>
      <div><CheckGlyph complete={step === 4} /><strong>{step === 4 ? `${work.result} · ${work.value}` : step === 1 ? "A clear mandate. An agent that can act." : step === 2 ? "The team shares context and delegates work." : "Tools run. Evidence returns to the agent."}</strong></div>
      <span>{step === 4 ? "Proof → Director" : "Context → action → evidence"}</span>
    </div>
  </div>;
}
