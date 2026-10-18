# Contract addendum 4: two factory teams, agent eyes, metrics, regulations, multi-page dashboard

Written Oct 17 2026, 21:10 PDT. Extends REALITY-CONTRACT-3.md; where they differ, this file wins. Still no paid calls during the build and no git commands that change state. Everything below is simulated unless it says live, and every simulated record carries `synthetic: true`.

## 1. Agents: two teams plus a director

| level | id | display name | scope | Inkbox handle | env suffix |
| --- | --- | --- | --- | --- | --- |
| 1 | `operator` | Owner's agent | the customer's own agent over MCP, all sites | none | none |
| 2 | `director` | Operations Director | both factories | steward-ops-director | DIRECTOR |
| 3 | `myer-manager` | Plant Manager · Myer | myer-plant | steward-myer-manager | MYER_MANAGER |
| 4 | `myer-engineer` | Site Engineer · Myer | myer-plant | steward-myer-engineer | MYER_ENGINEER |
| 4 | `myer-compliance` | Compliance Officer · Myer | myer-plant | steward-myer-compliance | MYER_COMPLIANCE |
| 5 | `myer-technician` | Field Technician · Myer | myer-plant | steward-myer-technician | MYER_TECHNICIAN |
| 3 | `bristol-manager` | Plant Manager · Bristol | bristol-pumps | steward-bristol-manager | BRISTOL_MANAGER |
| 4 | `bristol-engineer` | Site Engineer · Bristol | bristol-pumps | steward-bristol-engineer | BRISTOL_ENGINEER |
| 4 | `bristol-compliance` | Compliance Officer · Bristol | bristol-pumps | steward-bristol-compliance | BRISTOL_COMPLIANCE |
| 5 | `bristol-technician` | Field Technician · Bristol | bristol-pumps | steward-bristol-technician | BRISTOL_TECHNICIAN |

All nine identities exist on Inkbox now, with A2A enabled, role skills on their Agent Cards and identity-scoped keys. Env: `INKBOX_IDENTITY_<SUFFIX>` and `INKBOX_AGENT_KEY_<SUFFIX>` in the root `.env`. The single phone number belongs to `steward-runner`, now displayed as "Steward Dispatch Line"; env `INKBOX_IDENTITY_DISPATCH` and `STEWARD_DISPATCH_PHONE_NUMBER`. Both field technicians reach people by SMS or call through the dispatch line; every agent emails from its own identity.

Old ids map as follows and must be migrated in stored records idempotently: `atlas` → `director`; `warden:myer-plant` → `myer-engineer`; `warden:bristol-pumps` → `bristol-engineer`; `counsel` → `myer-compliance` or `bristol-compliance` by the record's site (cross-site records go to `bristol-compliance`); `runner` → `myer-technician` or `bristol-technician` by site. The identities steward-atlas, steward-warden-myer, steward-warden-bristol, steward-counsel and steward-warden-harbor are retired; route nothing to them.

Authority, enforced in code:
- operator: read everything, start scenarios and fix workflows, decide, set budgets.
- director: both sites; delegate to managers; read eval metrics and telemetry; `reconfigure_agent`; approve cross-site maintenance; escalate to the owner.
- manager: own site; convene calls; assign crew; approve work orders within budget; schedule maintenance; talk to the other site's manager.
- engineer: own site; drive the agent eye; run valve inspections; resolve, attest, verify; open issues.
- compliance: own site; obligations, regulations, documents, notices; email documents to any agent; talk to the other site's compliance officer.
- technician: own site; contact people through the dispatch line and email; collect evidence; cannot attest or write facts.
Cross-site messages are allowed only manager to manager, compliance to compliance, and anyone to or from the director.

## 2. The agent eye: the 3D scan is an interface for agents

Humans watch it; agents operate it. A renderer (any open viewer page in eye mode, or a headless Chrome worker the backend starts) executes camera commands and returns frames.

Backend:
- `POST /api/eye/{siteId}/renderers {rendererId}` registers or heartbeats a renderer (every 5 s; stale after 15 s).
- `GET /api/eye/{siteId}/commands?rendererId=&since=` long-polls (≤ 25 s) for the next command.
- `POST /api/eye/{siteId}/frames {commandId, jpegBase64, camera: {position, target, fov}, visiblePins: [{assetTag, x, y, distance, occluded}]}` stores the frame (backend data dir, `GET /api/eye/frames/{frameId}.jpg`) and completes the command.
- `POST /api/eye/{siteId}/act {action, params}` with `X-Steward-Actor`, authority engineer, manager, director or operator. Actions: `look` (render the current pose), `move {direction: forward|back|left|right|up|down, meters (0.1 to 5)}`, `turn {yawDeg, pitchDeg}`, `go_to {assetTag}`, `orbit {assetTag, frames (4 to 16)}`, `mark {x, y, note}` (screen point in 0..1 to a world point, creates an annotation and optionally an issue candidate). Waits up to 20 s for the frame and returns `{frameId, frameUrl, camera, visiblePins, actor, at}`; `orbit` returns a list. If no renderer is registered, the backend starts one headless Chrome worker on `http://127.0.0.1:3000/eye?site=<id>&renderer=headless` (GPU flags first, SwiftShader as fallback), tracks its PID, and stops it after 5 idle minutes. Every act is a Change of type `eye` and a telemetry row.
- `GET /api/eye/{siteId}/feed?since=` returns recent frames with actor and action, for the dashboard's agent mode.

Viewer (frontend): `/eye?site=&renderer=` mounts SplatViewer in eye mode: registers, long-polls commands, eases the camera, waits two frames after the move settles, captures the canvas to a 640×400 JPEG, projects pins, posts the frame. The dashboard's Environment page runs the same eye mode when it is open, so humans watch the camera move as agents drive it, with an overlay naming the agent and its last action.

MCP: `eye_look`, `eye_move`, `eye_turn`, `eye_go_to`, `eye_orbit`, `eye_mark` return MCP image content (the JPEG) plus a short text with the pose and the visible asset tags, so a vision model literally sees the plant.

## 3. Metrics

Series per site, synthetic and labelled: `pressure_bar` (per pump circuit), `flow_m3h`, `temperature_c`, `level_pct` (Myer expansion tank, Bristol sump), `vibration_mms`, `power_kw`. Deterministic generator (seeded random walk plus a daily cycle) for the last 7 days at 5-minute resolution, scenario overlays (overpressure ramp, sump rise), and a live point every 5 s while simulation is on.
- `GET /api/properties/{id}/metrics?series=&from=&to=&step=` returns `{series: [{key, unit, assetTag?, points: [[isoTime, value]], spec?: {min, max}}]}`.
- `GET /api/metrics/summary` returns per site and the two-site average: avg pressure, avg flow, uptime percent, open issues, compliance percent, crew on shift, agent actions today.

Eval metrics: `GET /api/evals/metrics` returns pass rate per suite over runs, tokens per agent per mission, tool calls per mission, wait time held by `wait_for` (tokens avoided), latency p50 and p95, A2A messages per day, estimated cost. Source label: "Steward telemetry, also delivered to Armature".

## 4. Agent calls and meetings

Every agent-to-agent exchange is a `conversation`: `{id, kind: 'call'|'meeting'|'message', participants, siteIds, transport: 'inkbox'|'local', providerTaskIds, transcript: [{speaker, text, at}], summary: {headline, points, decisions, actions: [{owner, task, due}]}, summaryBy: 'claude-opus-5-5'|'hand-seed', startedAt, endedAt, synthetic}`. A "call" is an Inkbox A2A conversation presented as a call; voice comes from the browser's text-to-speech and the UI says so. There are no phone calls between agents on the current plan.
- `GET /api/conversations?siteId=&agentId=`, `GET /api/conversations/{id}`.
- Summaries: `scripts/synth/summarise.py` (Claude, dry-run default) and hand-seeded summaries for every scripted conversation now.

## 5. Regulations and compliance

Real government sources, cached locally with attribution, explained in our own words:
- Bristol (England): Pressure Systems Safety Regulations 2000 (SI 2000/128); Workplace (Health, Safety and Welfare) Regulations 1992 (SI 1992/3004); Health and Safety at Work etc. Act 1974. Official PDFs from legislation.gov.uk (Open Government Licence v3.0).
- Myer (Victoria, Australia; the Kenneth Myer Building is in Melbourne): Occupational Health and Safety Regulations 2017 (Vic), plant and pressure equipment; Building Regulations 2018 (Vic), maintenance of essential safety measures including portable fire extinguishers. Official PDFs from legislation.vic.gov.au, with the licence stated on that site recorded verbatim.
A `regulation` record: `{id, jurisdiction: 'ENG-UK'|'VIC-AU', instrument, provision, title, officialUrl, pdfPath, licence, retrievedAt, summary, appliesTo}`; `summary` is our wording, never a long quotation. Obligations and compliance issues cite regulation ids. `GET /api/regulations?siteId=`, `GET /api/regulations/{id}/file` (the cached PDF with an attribution header).

A compliance issue page shows what is wrong, why it is a problem (the regulation, provision and our summary, with a link to the official PDF), who is responsible, and a demo control "Ask the agents to fix it" that starts the fix workflow. This is a demo rule pack, not legal advice.

## 6. The fix workflow (simulated)

`POST /api/issues/{id}/fix` (operator) plays, with compressed timing and every step a Change:
1. Evidence: the engineer drives the eye to the asset (`go_to`, `orbit`) and the frame is attached to the issue; synthetic defects stay labelled.
2. Call: engineer calls the manager (a conversation); the manager decides, picks the responsible person from the crew table, and the compliance officer adds the regulation reason.
3. Contact: the technician contacts the person through the dispatch line (simulated for synthetic crew; live SMS only to the duty engineer, the user, when live mode is on).
4. Fix: the person's reply arrives (simulated after a delay with a synthetic photo or reading, or the user's real reply in live mode).
5. Verify: the engineer verifies (vision and attest), the compliance officer closes the obligation.
6. Inform: the manager posts the resolution; a `notification` goes to every person on the site roster and to the other agents; the dashboard updates. Notifications to synthetic crew are records only.
`GET /api/notifications?siteId=`.

## 7. The factories talk to each other

Scenario `x-maintenance`: Bristol's compliance officer, blocked by the expired pressure-vessel certificate, asks Myer's compliance officer when Myer's pressure-equipment examiner is scheduled and whether they hold a written scheme template; the two managers agree a shared examiner visit; the director approves. Result: a `maintenance_window` `{id, siteIds, date, scope, examiner, status: 'proposed'|'approved'|'done', conversationId}`. `GET /api/maintenance?siteId=`. Every scenario's conversations show on both factories' pages when both took part.

## 8. Dashboard: separate pages

Sidebar: factory switch at the top (Myer · Bristol), the selected factory's pages, then the portfolio pages, then the Human · Agent switch. Routes:
- `/app` Portfolio: both factories side by side, two-site averages, what is happening in each right now.
- `/app/[site]` Factory overview: KPIs, key metric sparklines, open issues, team status, crew on shift.
- `/app/[site]/metrics` Pressure, flow, temperature, level, vibration and power charts with spec bands.
- `/app/[site]/environment` The agent eye: the scan in eye mode, the operating agent and its last action, frame strip, valve inspections, pins.
- `/app/[site]/team` The site's agent team and human crew.
- `/app/[site]/compliance` Obligations, regulations with their PDFs, compliance issues with why and the fix control.
- `/app/[site]/maintenance` Schedule, including cross-factory windows.
- `/app/agents` The full agent map: director, both teams, the dispatch line and the owner's agent, edges that light up as conversations happen, each node showing its current task.
- `/app/conversations` Every call and meeting: summary first, then transcript, then Listen.
- `/app/evals` Eval metrics charts, suites, the self-optimisation loop, Armature link.
Agent mode: the Human · Agent switch dissolves the current page and brings up `/app/agent-view`: what the agents see and say, live. The latest eye frames per factory with a HUD of visible pins, the stream of tool calls and A2A messages typing in, the agent map pulsing, token meters. Switching back re-forms the page. Same black and white language, same dissolve as the home page.
