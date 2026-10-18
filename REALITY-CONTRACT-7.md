# Contract addendum 7: walkthroughs, green and blue labels, live calls, owner alerts

Written Oct 18 2026, 02:00 PDT, from the owner's instructions:

> The agent should walk through the 3D world on its own, do a walkthrough and then label things with green and blue,
> like "this looks good" and "this looks bad" (the compliance issue things). Not visitors: employees checked in. Show
> agent-to-agent conversations. Notify "this agent started a call", with their real voice in the dashboard. Agents talk
> to their teammates and to agents at other sites. Make a sensible workflow so things look working, and they give me a
> call if there are compliance issues and also email me the file and evidence.
> The simulation runs continuously and is never shown. No labels such as "synthetic" on the frontend. Metrics change
> continuously with arrows for highs and lows. Compliance is never 100 %: there are issues.

Same rules as before: no git, no paid model calls (deterministic templates only), never kill by pattern, never restart
3000/8001/8002 (the owner's session does), never print secrets. Backend data keeps `synthetic: true` internally; the
frontend never shows it.

## 1. Walkthrough (patrol)

The site's Engineer (Site Engineer · Myer, Site Engineer · Bristol, Conservation Engineer · Tomioka; they hold eye
authority) walks the scan with the agent eye, stop by stop, and labels every asset it looks at.

- `POST /api/patrols {siteId, agentId?, route?: [assetTag], paceSeconds?}` → 202, the patrol record. Authority: operator,
  director, the site's manager or engineer. Default route: up to 10 assets of the site that have placed pins (stored
  `viewPose` or `pinSource: placed`) first, then the most important others (tags with obligations or open issues);
  default pace 8 s per stop (humans watch the camera move on the Environment page). A patrol already running for the
  site is returned instead of a second one.
- `GET /api/patrols?siteId=&limit=`, `GET /api/patrols/{id}`, `POST /api/patrols/{id}/cancel`.
- Patrol record: `{id, siteId, agentId, agentName, state: running|completed|canceled|failed, origin: manual|autoplay,
  route: [assetTag], stopIndex, stops: [{assetTag, labelId, verdict, frameId, at}], startedAt, finishedAt, summary,
  alertIds: [], synthetic: true}`.
- Each stop: `eye.act_sync(site, "go_to", {assetTag}, engineer)` (cold-start aware), then an assessment, then a label.
  If the eye cannot answer, the label is still written with `frameId: null` and the reason in `reasons`.
- Assessment (deterministic). **bad** when any of: an obligation on the asset is `overdue` or `blocked`
  (`compliance: true`, reason like "Pressure vessel examination overdue by 6 days (PSSR 2000 reg. 8)"); an open stored
  issue on the asset (reason "Open issue: …"); a live reading of the asset outside its spec band (reason
  "PG-601 4.1 bar, above the 3.5 bar limit"). **good** otherwise, with the evidence in words ("2.61 bar, inside
  1.5 to 3.5 bar", "Certificate current, next due in 207 days", "No open issues").
- Labels: `GET /api/properties/{siteId}/labels` returns the latest label per asset:
  `{id, patrolId, siteId, assetTag, assetName, verdict: "good"|"bad", color: "green"|"blue", title: "Looks good"|"Looks
  bad", reasons: [string], compliance: bool, regulationIds: [string], obligationId, issueId, frameId, frameUrl,
  world: {x, y, z} | null, agentId, agentName, at}`. Green means looks good, blue means looks bad.
- Changes: type `patrol` on the site with extras `{patrolId, status: started|stop|completed|canceled|failed, assetTag,
  verdict, labelId, stop, stops}` (wait with `event: "any", filter: {type: "patrol", patrolId}`).
- When the patrol ends, the engineer posts a short message to the Site Manager ("Walked the pump house: 9 checked,
  7 look good, 2 look bad: …") as an A2A message conversation, and every bad compliance label starts §2 (once per
  obligation per 24 h; later patrols reuse the open alert).

## 2. Compliance alert workflow (one per bad compliance finding)

Paced steps (about 4 s apart, so the dashboard shows them arriving), each a Change of type `compliance_alert` with
extras `{alertId, step, status}`; the record is `owner_alert`-backed (below).

1. **Issue**: raise or reuse a stored issue, kind `compliance_overdue` or `compliance_blocked`, with `obligationId`,
   `regulationIds`, `evidenceFrameIds` (the label's frame), severity high when overdue by more than 7 days, else medium.
2. **Teammate call** (A2A call, `ConversationService.call`): engineer → the site's Compliance Officer, 4 to 6 turns:
   what the engineer saw at the asset, the regulation and section (from the obligation's `regulationIds` and the
   regulation records' titles), who owns it (the crew owner), the evidence attached, and the plan.
3. **Cross-site call**: the site's Compliance Officer → another site's Compliance Officer about the same kind of
   obligation, 3 to 4 turns, ending with something useful (share the examiner's visit, the method statement, the
   contractor). Pairs: Myer ↔ Bristol for pressure equipment and fire equipment, Bristol ↔ Tomioka for heritage and
   visitor-route work, Myer ↔ Tomioka for fire equipment; pick by the obligation's keywords, else the next site.
4. **Manager decision**: Compliance Officer → Site Manager call, 2 to 3 turns: the manager approves telling the owner,
   assigns the crew owner, and names the next step.
5. **Owner email with the file and the evidence**, from the site Compliance Officer's Inkbox identity to the owner's
   email (`INKBOX_OWNER_EMAIL`): subject `[<site name>] Compliance: <obligation title> (<overdue by N days | blocked>)`;
   HTML body (what, why with the regulation citation and its official link, who owns it, the decision asked) with the
   evidence frames inline (`content_id`) and attached as JPEG; attachments also carry the file: the official regulation
   PDF when its licence allows redistribution (England OGL, Japan PDL1.0 with the 出典 attribution line in the body;
   never the Victorian PDFs, which are link-only: link them instead) and an `evidence-<alertId>.txt` summary (asset,
   label, reasons, frame times, attestation ids, obligation, due date). Inkbox's `send_email` accepts
   `attachments=[{filename, content_type, content_base64, content_id?}]` and `body_html`; extend
   `InkboxAdapter.send_email` accordingly, keeping its `_gate`.
6. **Owner call**: the Steward Dispatch Line calls the owner's phone (`INKBOX_OWNER_PHONE`) through
   `InkboxAdapter.place_call` (hosted voice agent) with a brief under 2000 characters: who is calling, which site, what
   is wrong in plain words, the regulation, that the file and evidence were emailed, and the decision asked
   ("Shall I book the examiner for Tuesday morning?"); voicemail leaves the same message.
7. **Record**: `owner_alert` `{id, siteId, obligationId, issueId, labelId, patrolId, title, severity, steps: [{name, at,
   summary}], conversationIds, email: {mode: sent|dry_run|capped|failed, to, subject, attachments: [{filename,
   contentType, size}], providerRef, reason, at}, call: {mode, to, brief, providerRef, reason, at}, at}`;
   `GET /api/owner-alerts?siteId=&limit=`, `GET /api/owner-alerts/{id}`.

Gates (all must hold for a real send, else `dry_run` with the full content stored so the dashboard can show exactly
what would go out): Inkbox configured, `STEWARD_ALLOW_EXTERNAL_MESSAGES=true`, the new `STEWARD_ALLOW_OWNER_ALERTS=true`,
and the recipient in `INKBOX_ALLOWED_RECIPIENTS`. Caps: at most `STEWARD_OWNER_ALERTS_PER_DAY` (default 3) real
alerts a day (each is one email and one call), one per obligation per 24 h; beyond that `capped`. Autoplayed patrols
never send for real unless `STEWARD_SCENARIO_AUTOPLAY_LIVE=true` (autoplay pauses while live switches are on).

## 3. Autoplay

The autoplayer (`backend/src/autoplay.py`) interleaves walkthroughs with scenarios: playlist entries `patrol:<siteId>`
after every two scenarios, rotating the three sites, started with `origin: "autoplay"`; a patrol counts as busy until it
and its alert workflows finish. Default pace for continuous running: scenarios at 10x, a 30 s pause between items.

## 4. Employees checked in (replaces visitors)

The mill's `visitor_count` series is replaced by `checked_in:<site>` on every site (badge check-ins of the site's
employees, following its shift pattern: day shift up, night shift down). Summary key `employeesCheckedIn` replaces
`visitorsToday`; the live endpoint's `kpis.checkedIn` replaces `kpis.visitors`.

## 5. Live metrics

`GET /api/metrics/live[?siteId=]`: `{at, intervalSeconds: 5, sites: [{siteId, kpis: {pressure, flow, humidity,
checkedIn, crackWidth, temperature, vibration, power, level}, readings: [{key, label, assetTag, unit, value, previous,
delta, trend: up|down|flat, state: high|low|normal, spec}]}], average: {...}}`; each KPI is `{value, previous, delta,
trend, state, unit}` (state high/low when any reading of that kind is out of band). Scenario overlays apply.

## 6. Compliance is never 100 %

Each site carries real gaps: at least one overdue and, at two sites, one blocked obligation (seeded with real
regulation ids; blocked ones name what blocks them), each with an open compliance issue. If agents close every gap at
a site, the simulator lets the next obligation fall due later in the day, so compliance dips again.

## 7. Dashboard (frontend)

- Environment page and the fullscreen mission view: labels as markers at the asset pins, green "Looks good" or blue
  "Looks bad: <first reason>", with details on hover or focus (reasons, regulation, agent, time, evidence frame), and
  the walkthrough line ("Site Engineer · Bristol is walking the pump house: stop 4 of 9, PV-301"). An operator action
  "Walk the site now" posts `/api/patrols`.
- Calls: a dashboard-wide notification when a call starts ("Compliance Officer · Bristol started a call with
  Compliance Officer · Myer"), a live call panel that reveals the transcript line by line as it is spoken, and voices
  per agent from the browser's best voices (distinct voice per agent, locale by site: Myer en-AU, Bristol en-GB,
  Tomioka en-US or ja-JP for Japanese lines, the Director en-US). Browsers need one click to allow audio: a
  "Play calls aloud" toggle, remembered locally. Neural voices need a TTS provider key, which is not configured.
- Owner alerts: a feed of alerts with their steps, the email (subject, attachments) and the call, showing sent,
  waiting for live messaging, or held by the daily cap.
- No synthetic, demo or scenario labels anywhere; no scenario controls.
