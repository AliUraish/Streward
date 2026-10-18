"use client";

/* /app/[site]/team: the site's agent team (plant manager, site engineer, compliance officer, field technician) with
   each agent's detail, then the human crew: shifts, certifications, the issue kinds they own, who is contacted for what. */
import { useMemo, useState } from "react";
import type { Remote } from "@/lib/reality";
import { useCrew, useResponsible } from "@/lib/hooks-3";
import { agentName, teamOf } from "@/lib/sites-3";
import type { CrewMember, SiteId3 } from "@/lib/types-3";
import { AgentDetail } from "./agent-detail";
import { useNowRows } from "./portfolio";
import { useShared } from "./shell";
import { NotYet, PageHead, Reveal, State, SynthTag, ago, day, words } from "./ui3";

const DAY = 86_400_000;
function certState(expiresAt: string | null, now: number, status?: string): "ok" | "warn" | "bad" | "off" {
  if (status === "expired") return "bad"; if (status === "expiring" || status === "expiring_soon") return "warn";
  if (!expiresAt) return "off";
  const t = new Date(expiresAt).getTime(); if (Number.isNaN(t)) return "off";
  return t < now ? "bad" : t - now < 30 * DAY ? "warn" : "ok";
}
const shiftText = (s: CrewMember["shift"]) => typeof s === "string" ? s : s.label ?? [s.start, s.end].filter(Boolean).join(" to ");
/* The backend masks the user’s phone and email; a value with no mask characters is masked here too. */
const masked = (v: string) => /[*•]/.test(v) ? v : v.length > 4 ? `ending ${v.slice(-4)}` : v;

export default function TeamPage({ siteId }: { siteId: SiteId3 }) {
  const crew = useCrew(siteId);
  const now = Date.now();
  const { overview, agents } = useShared();
  const rows = useNowRows(overview, agents);
  const team = teamOf(siteId);
  const [selected, setSelected] = useState(team[0].id);
  const me = team.find(a => a.id === selected) ?? team[0];
  return <div className="page3">
    <PageHead id="team" title="Team" />
    <Reveal as="section" className="p3" aria-labelledby="agents-h">
      <div className="p-head"><h2 id="agents-h">Agents</h2>{!rows.some(r => r.known) ? <NotYet remote={overview.readiness === "ready" ? agents as Remote<unknown> : overview as Remote<unknown>} what="agent status" /> : null}</div>
      <div className="team-cards">{team.map(a => { const r = rows.find(x => x.id === a.id); const st = r?.status ?? (r?.known ? "idle" : "unknown");
        return <button key={a.id} type="button" className={`ag-btn card ${a.id === me.id ? "on" : ""}`} aria-pressed={a.id === me.id} onClick={() => setSelected(a.id)}>
          <span className="r1"><span className={`sig ${st === "working" ? "ok" : st === "waiting" ? "warn" : "off"}`} aria-hidden="true" /><strong>{a.name}</strong><span className="st">{st}</span></span>
          <span className="r2">{r?.task ?? (r?.known ? "No task" : "Status not available yet")}</span>
          {r?.waitingOn ? <span className="r3">Waiting on {r.waitingOn}</span> : r?.since ? <span className="r3">{ago(r.since)}</span> : null}
        </button>; })}</div>
    </Reveal>
    <AgentDetail key={me.id} me={me} info={agents.data?.find(x => x.id === me.id)} />
    <div className="ppl3">
      <Reveal className="p3 crew3">
        <div className="p-head"><h2>Crew</h2><span className="meta">{crew.data ? `${crew.data.length} people, ${crew.data.filter(c => c.onShift).length} on shift` : ""}</span></div>
        <State remote={crew} what="the crew" isEmpty={c => c.length === 0} empty="No crew recorded for this site.">
          {list => <div className="tbl3 crew-tbl" role="table" aria-label="Crew">
            <div className="tr head" role="row"><span role="columnheader">Name</span><span role="columnheader">Role and shift</span><span role="columnheader">Certifications</span><span role="columnheader">Owns</span></div>
            {list.map(c => <div className="tr" role="row" key={c.id}>
              <span role="cell" className="c-name"><strong>{c.name}</strong><SynthTag rec={c} />
                <small>{c.contactable || c.phone || c.email ? `Contact: ${[c.phone ? `phone ${masked(c.phone)}` : "", c.email ? `email ${masked(c.email)}` : ""].filter(Boolean).join(", ") || "through the Steward Dispatch Line"}` : "No contact details on file"}</small></span>
              <span role="cell" className="c-role">{c.role}<small><span className={`sig ${c.onShift ? "ok" : "off"}`} aria-hidden="true" />{c.onShift ? "on shift" : "off shift"}, {shiftText(c.shift)}</small></span>
              <span role="cell" className="c-certs">{c.certifications.length ? <ul>{c.certifications.map(x => { const st = certState(x.expiresAt, now, x.status); return <li key={x.name} className={st === "bad" ? "bad" : ""}><span className={`sig ${st}`} aria-hidden="true" />{x.name}<small>{x.expiresAt ? `${st === "bad" ? "expired" : "expires"} ${day(x.expiresAt)}` : "no expiry"}</small></li>; })}</ul> : <small>None recorded</small>}</span>
              <span role="cell" className="c-owns">{c.owns.length ? c.owns.map(k => <span className="tg" key={k}>{words(k)}</span>) : <small>Nothing</small>}</span>
            </div>)}
          </div>}
        </State>
      </Reveal>
      <Reveal className="p3 contact3" i={1}>
        <div className="p-head"><h2>Who is contacted for what</h2></div>
        <State remote={crew} what="the crew" isEmpty={c => c.length === 0} empty="No crew, so no contacts.">
          {list => <ContactMap siteId={siteId} crew={list} />}
        </State>
      </Reveal>
    </div>
  </div>;
}

function ContactMap({ siteId, crew }: { siteId: SiteId3; crew: CrewMember[] }) {
  const kinds = useMemo(() => [...new Set(crew.flatMap(c => c.owns))].sort(), [crew]);
  const [kind, setKind] = useState<string | null>(null);
  const responsible = useResponsible(siteId, kind);
  return <div className="cmap">
    <ul className="rows3 plain">{kinds.map(k => {
      const owners = crew.filter(c => c.owns.includes(k));
      return <li key={k} className={kind === k ? "sel" : ""}>
        <button type="button" className="row-btn" onClick={() => setKind(kind === k ? null : k)} aria-expanded={kind === k}>
          <span className="r1"><strong>{words(k)}</strong></span>
          <span className="r2">{owners.map(o => `${o.name}, ${o.role}`).join("; ")}</span>
        </button>
        {kind === k ? <div className="resp">
          <State remote={responsible} what="who is responsible">
            {r => r?.crewMember ? <p>Responsible: <strong>{r.crewMember.name}</strong> ({r.crewMember.role}){r.fallback ? ", as the fallback owner" : ""}{r.via ? `, reached through ${agentName(r.via)}` : ""}{r.channel ? ` by ${r.channel}` : ""}.{r.reason ? ` ${r.reason}` : ""}</p> : <p>Nobody is named for {words(k)}{r?.reason ? `: ${r.reason}` : "."}</p>}
          </State>
        </div> : null}
      </li>;
    })}</ul>
  </div>;
}
