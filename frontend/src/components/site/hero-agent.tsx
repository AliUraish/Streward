import type { Ref } from "react";

const TOPICS = [
  {
    title: "P-101 · Pump inspection", goal: "Can P-101 restart?",
    engineer: ["Reading the equipment record.", "Pressure evidence is missing.", "Technician, read P-101’s gauge.", "Checking identity and evidence.", "2.4 bar. Signed proof ready."],
    technician: ["Ready for an inspection.", "Preparing a fresh gauge check.", "Finding the P-101 tag plate.", "Gauge photo: 2.4 bar.", "Evidence delivered to Engineer."],
  },
  {
    title: "TS-801 · Sensor reading", goal: "Investigate the sensor alert.",
    engineer: ["Reading the sensor history.", "This reading needs a fresh check.", "Technician, inspect TS-801.", "Cross-checking the new reading.", "Fresh evidence linked to the record."],
    technician: ["Ready to check the sensor.", "Locating the sensor tag.", "Checking TS-801 in the plant.", "Fresh reading and photo attached.", "Sensor evidence delivered."],
  },
  {
    title: "V-504 · Valve maintenance", goal: "Check V-504’s seal.",
    engineer: ["Reviewing the valve history.", "Seal inspection is due.", "Technician, inspect V-504.", "Checking the inspection evidence.", "Seal report returned to Director."],
    technician: ["Ready for the maintenance task.", "Finding the V-504 label.", "Inspecting the valve housing.", "Valve photos and notes attached.", "Maintenance evidence delivered."],
  },
] as const;

const STAGES = [
  { from: "Director", to: "Engineer", tool: "resolve", path: "M200 80 V98 H94 V116" },
  { from: "Engineer", to: "Director", tool: "context.min", path: "M94 116 V98 H200 V80" },
  { from: "Engineer", to: "Technician", tool: "A2A task", path: "M94 196 V210 H306 V196" },
  { from: "Technician", to: "Engineer", tool: "A2A evidence", path: "M306 196 V210 H94 V196" },
  { from: "Engineer", to: "Director", tool: "attest · check", path: "M94 116 V98 H200 V80" },
] as const;

function AgentGlyph({ kind }: { kind: "coordinator" | "site" | "field" }) {
  return <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden="true">
    {kind === "coordinator" ? <><rect x="8" y="2" width="8" height="6" /><rect x="2" y="16" width="7" height="6" /><rect x="15" y="16" width="7" height="6" /><path d="M12 8v5M5.5 16v-3h13v3" /></>
      : kind === "site" ? <><rect x="5" y="5" width="14" height="14" /><rect x="9" y="9" width="6" height="6" /><path d="M8 1v4m8-4v4M8 19v4m8-4v4M1 8h4m-4 8h4M19 8h4m-4 8h4" /></>
        : <><path d="M3 8h5l2-3h5l2 3h4v13H3z" /><rect x="8" y="11" width="8" height="6" /><path d="M5 11h1m12 0h1" /></>}
  </svg>;
}

function AgentNode({ name, role, message, kind, speaking, top }: { name: string; role: string; message: string; kind: "coordinator" | "site" | "field"; speaking: boolean; top?: boolean }) {
  return <div className={`hero-agent-node${speaking ? " is-speaking" : ""}${top ? " is-coordinator" : ""}`}>
    <div className="hero-agent-head"><AgentGlyph kind={kind} /><div className="hero-agent-identity"><strong>{name}</strong><span>{role}</span></div></div>
    <p className="hero-agent-message">{message}</p>
  </div>;
}

export default function HeroAgent({ beat = 4, topic = 0, attestationId, anchorRef }: { beat?: number; topic?: number; attestationId: string; anchorRef?: Ref<HTMLDivElement> }) {
  const index = Math.min(4, Math.max(0, beat));
  const conversation = TOPICS[topic % TOPICS.length];
  const stage = STAGES[index];
  return <div className="hero-agent-console" ref={anchorRef} data-ui="" data-topic={topic % TOPICS.length} data-beat={index} aria-label={`Illustrated agent conversation about ${conversation.title}. ${stage.from} messages ${stage.to}.`}>
    <div className="hero-agent-topic"><span>{conversation.title}</span><span>Illustrated cycle</span></div>
    <div className="hero-agent-graph">
      <svg className="hero-agent-network" viewBox="0 0 400 220" preserveAspectRatio="none" fill="none" aria-hidden="true">
        <defs><marker id="steward-agent-arrow" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto"><path d="m0 0 4 2.5L0 5" fill="none" stroke="#ededed" /></marker></defs>
        <path className="hero-agent-link" d="M200 80 V98 H94 V116 M94 196 V210 H306 V196" />
        <path className="hero-agent-link is-active" d={stage.path} markerEnd="url(#steward-agent-arrow)" />
      </svg>
      <AgentNode name="Director" role="All sites" kind="coordinator" message={conversation.goal} speaking={stage.from === "Director"} top />
      <AgentNode name="Engineer" role="Own site" kind="site" message={conversation.engineer[index]} speaking={stage.from === "Engineer"} />
      <AgentNode name="Technician" role="Field" kind="field" message={conversation.technician[index]} speaking={stage.from === "Technician"} />
    </div>
    <div className="hero-agent-exchange" title={index === 4 ? attestationId : undefined}><span>{stage.from} → {stage.to}</span><code>{stage.tool}</code></div>
  </div>;
}
