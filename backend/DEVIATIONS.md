# Backend deviations from REALITY-CONTRACT.md

Each entry says what the contract asks for, what was implemented, and why.

1. **`cryptography` pin.** The brief asked for `cryptography==45.0.5`. The venv already carried `cryptography==50.0.2` as a
   dependency of the pinned `inkbox==0.7.19` (which requires `>=43.0`). `requirements.txt` pins `50.0.2` so the install stays
   consistent instead of downgrading a working SDK dependency. `pillow==13.0.0` (already present via reportlab) is pinned
   explicitly because `verify.py` reads EXIF with it.

2. **Every attest is signed, not only accepted ones.** The contract text says only `accepted` "signs an Attestation", but the
   `Attestation` type carries `verdict: Verdict` with all three values and `WorkItem.verdicts[].attestationId` must point at
   something. The backend therefore stores and signs an attestation for every submission (verdict inside the signed payload) and
   writes a Fact, updates the component, resolves the work item and emits the `fact` Change only for `accepted`. A signed
   rejection is still a useful receipt and lets integrity reuse detection cover rejected photos.

3. **Component `status` on an accepted fact.** The contract says accepted facts update the component "status + lastFactAt".
   `status` is also the requirement roll-up recomputed by inspections. The backend sets `lastFactAt`, `factStatus: "known"` and
   `status: "verified"` unless the component is in `issue`; a later inspection recompute may reset `status` from requirements.

4. **Owner decision fact attribute.** The contract writes "a condition fact with `source.kind='owner'`". Writing the decision
   into the work item's own attribute (e.g. `pressure_bar = "hold"`) would corrupt later resolves, so the fact is written under
   attribute `owner_decision` (class `condition`, TTL 86400 s, value = the decision text). `owner_decision` is not in the spec
   table and bypasses spec validation for this one source kind.

5. **Change type for unrouted inbound.** The `Change.type` enum has no message type; unrouted inbound messages emit a Change of
   type `dispatch` whose `refId` is the `inbound_unrouted` record id and whose summary starts with "Unrouted inbound".

6. **Footprint radii.** The contract lists tank 1.0, exchanger 0.9, panel 0.5, pump 0.6, duct 0.8, default 0.6. Two extra
   entries were added: `door` and `light` get radius 0 (an opening and a ceiling luminaire do not block a floor corridor);
   everything else, including sensors and gauges on the wall, uses the table or the 0.6 m default exactly as written.

7. **Inbound secret header (per docs/INKBOX.md).** `/api/inbound/inkbox` requires `X-Steward-Inbound-Secret == STEWARD_INBOUND_SECRET` as specified;
   because Inkbox cannot set custom headers but can send `Authorization: Bearer <auth_token>` on a subscription, the same
   secret is also accepted as a bearer token. If `INKBOX_WEBHOOK_SIGNING_KEY` is set the `X-Inkbox-Signature` HMAC is verified
   as well. The `/api/inbound/inkbox` path is exempt from the optional `STEWARD_API_TOKEN` middleware because it carries its
   own secret.

8. **Provider-unavailable dispatches.** The contract specifies `providerRef: null` plus a reason only for level 3 calls. The
   backend applies the same honest pattern to every channel that cannot be sent (no Inkbox, gate closed, recipient not
   allowlisted, provider error): the dispatch is recorded with `providerRef: null` and a body that starts with
   `[not sent: <reason>]`. The initial dispatch additionally falls back to the `local` channel so the local replay path works.

9. **Scheduler ladder thresholds.** The contract defines the ladder but not when the scheduler climbs it. Auto-escalation
   fires at 50 %, 70 %, 85 % and 95 % of the work item's deadline window (`STEWARD_WORK_DEADLINE_SECONDS`, default 7200) for
   levels 1–4; expiry at 100 %. Manual `escalate` can jump to any level at any time.

10. **Time-check lower bound without a work item.** The contract defines the window relative to `workItem.createdAt`. For an
    ad-hoc `attest` with no work item the lower bound is `now - TTL(class)` (none for identity) so a four-month-old document can
    be attested but a stale reading cannot.

## Addendum 2 (REALITY-CONTRACT-2.md)

11. **Operator (contract 4: the Owner's agent) keeps the direct reality verbs.** The addendum says the Operator "cannot write facts, dispatch, or decide",
    but the MCP's existing `resolve` / `attest` / `escalate` tools, the dashboard's owner-decision control and the demo eval
    all call those endpoints as the operator (the default actor when `X-Steward-Actor` is absent). The authority table
    therefore enforces the level restrictions on Atlas, the Wardens, Runner and the owner, while the Operator's direct verbs
    remain the single-agent path and missions are the four-agent path (README "Four agents and authority").

12. **Default restart set is one representative asset per kind.** The addendum lists the restart set per kind; the live demo
    and `evals/mission-workflow.json` start a mission with only `{siteId, goal, budget}` and expect one unknown
    (`P-101.pressure_bar`). The default therefore covers P-101, V-501, DB-401, FE-1001 and D-1101 (six attributes);
    `assetTags` narrows it and `["all"]` covers every asset of those kinds.

13. **Extra demo seeds and seed refresh.** To make that one-unknown mission reproducible the demo site is also seeded with
    `DB-401.status = normal`, `FE-1001.pressure_ok = yes` and `D-1101.closed = yes` (patrol, `seed:patrol-initial`), and on
    startup a seeded demo observation past its TTL is re-seeded as `seed:patrol-refresh` only while every fact for that
    attribute is itself a seed. Real facts are never overwritten.

14. **Evidence is verified on the inbound path, not by the Warden handler.** Step 3 reads "field agent hands it to the site
    agent → site agent runs verification → attest". Phase 1's `/api/inbound/*` already runs the six checks and signs the
    attestation (contract behaviour that had to stay); the Runner's reply therefore carries the attestation ID and verdict,
    and the Warden records the verdict as its step. The verifier and signing key are the site's.

15. **Change types `a2a` and `eval`.** `a2a` is the addendum's extension; `eval` was added for eval runs because the
    addendum asks for a Change without naming a type. Changes also omit `assetTag` instead of sending `null`, which the
    MCP's schema rejects.

16. **Attestations re-signed by the site-ID migration.** Renaming `propertyId` inside a signed attestation invalidates its
    signature, so migrated attestations are re-signed with the local key and keep `_resignedFrom` (private). The backend is
    the signer; nothing external relied on the old bytes.

17. **Inkbox transport delivers in-process too.** Both ends of every task are this process, so a task sent through Inkbox
    (real `SendMessage`, real `a2a_reply`) is also handed to the handler immediately; webhook echoes are deduplicated by
    provider task/message id. Without the sending identity's agent-scoped key the task is stored as `transport: local` with a
    `providerError`; it is never reported as sent.

18. **SuperSplat credits.** The viewer and its `meta.json` expose no author field, so the seed credit names the scene id and
    "its SuperSplat author (handle as shown on superspl.at)" rather than a handle we could not retrieve; the capture note is
    verbatim from the addendum.

19. **Environment hygiene.** The repository root `.env` is a template whose values are inline comments; the backend now
    strips inline comments and treats empty values as unset for `STEWARD_*`, `INKBOX_*`, `SUPABASE_*`, `STRIPE_*`,
    `INSFORGE_*`, `SUPERMEMORY_*`, `ARMATURE_*` before any adapter (including the Inkbox SDK, which reads `INKBOX_BASE_URL`
    and `INKBOX_VAULT_KEY` itself) sees them. Dispatch channels are `local` unless key, identity, the external-messages
    gate and a validated, allowlisted recipient all exist.

20. **Backend-only fields are not mirrored.** `simulated`, `ownerDecision` and dispatch `note` have no column in
    `supabase/migrations/0001_reality.sql`; the mirror drops them so PostgREST upserts keep succeeding.

## Addenda 3 and 4 (REALITY-CONTRACT-3.md, REALITY-CONTRACT-4.md)

21. **harbor-works is archived, not deleted.** Its records move to kind `archived:<kind>` under property `archived:harbor-works`
    (bodies and signatures unchanged), after a SQLite backup, so the retirement is reversible and nothing in the app reads them.
22. **Two coordinate systems per asset.** `position` stays the register layout in metres because the verifier's geometry and
    direction messages, task cards and the clearance query depend on it; `pin {x, y, z}` is the separate scan-world point. Myer's
    register keeps the earlier shared register's tags and layout (it already described a modern plant room), so references and
    replays keep working; Bristol got a new pump-house register and new kinds `sump`, `vessel`, `walkway`.
23. **Estimated pins** are a scaled copy of the register layout within a few metres of the scan origin, not measured; the vision
    stream found they do not sit on the valves, so every view carries `pinSource` and vision findings on estimated pins say
    `located: false` and "Location unconfirmed" in the issue text.
24. **Crew contact is masked.** The contract's `phone?`/`email?` are shown and mirrored masked (`••• ••• 4321`); the real values are
    read from `INKBOX_CONTRACTOR_*` only at send time, so they never land in SQLite, Supabase or an API response.
25. **Board meetings are conversations.** Contract 4 makes every exchange a `conversation`; a board meeting is one with `kind:
    meeting`, and `/api/board-meetings` stays as a view. The Supabase `board_meetings` table from the contract-3 draft is replaced by
    `conversations`. Each participant's statement is an A2A reply to a short "your view" task from the convener; that protocol
    message is not repeated in the transcript.
26. **Derived conversations.** A2A exchanges that are not a scripted call or meeting (missions, document deliveries, notifications)
    are listed as `kind: message` conversations grouped by A2A context, with `summary: null` until `summarise.py` or
    `POST /api/conversations/{id}/summary` provides one. Their ids are `conv-ctx-<contextId>`.
27. **The mission chain gains the plant manager.** "Director: delegate to managers" → the director asks the site's plant manager,
    who approves the work order (capped at `STEWARD_WORK_ORDER_LIMIT_USD`, default 500) and hands the restart set to the site
    engineer; the manager relays the engineer's replies up. Engineers no longer dispatch people (resolve with a budget):
    technicians do, per "technician: contact people through the dispatch line".
28. **Document email reaches any agent; A2A obeys the cross-site rule.** Compliance may "email documents to any agent", but the
    accompanying A2A note is skipped (`a2aSkipped` says why) when the cross-site rule forbids that pair. A compliance officer may
    send only its own site's documents. Header-less `request-document` calls act as the site's compliance officer.
29. **`ops-counsel-tokens` keeps its id** (MCP and eval suites reference it) but its subject is now `bristol-compliance` (the
    contract-3 "Counsel" maps to the Bristol officer for cross-site records). The scenario's efficiency eval is computed locally
    from telemetry and stored as an `eval_run` with suite `efficiency` and `runner: local-telemetry`; the MCP-owned
    `evals/efficiency.json` runs through `POST /api/evals/run` when that file exists.
30. **Findings use a 5x bar.** An agent is flagged when its tokens per mission are at least five times its peers' median (or it has
    failed calls). Armature reads need a workspace read key; the ingest key is never used to read.
31. **Agent eye protocol details.** Commands are broadcast to every open renderer (humans watch the camera move) and the first
    renderer to post a frame produces it; orbits get a longer, bounded wait; an act with no frame returns 504 `EYE_TIMEOUT`. The
    headless worker runs only when workers run (`STEWARD_EYE_AUTOSTART`), in its own process group, stopped by that PID.
32. **Metrics are generated at query time.** The 7-day 5-minute series are a deterministic function of (site, series, time); the
    "live point every 5 s" is computed for the last minutes while the simulation is on instead of being appended by a ticker, and
    facts for the same asset (scenario ramps, verified fixes, the sensor feed) are merged as overlays with their offset carried
    forward. Seeded daily pump outages make uptime meaningful.
33. **Fix workflow evidence and live mode.** Without a renderer (and with autostart off) the evidence step records why there is
    no frame instead of failing. Live mode is exactly "the contact notice was sent by SMS"; otherwise the reply is simulated through
    the normal inbound verifier with a labelled synthetic photo.
34. **Cross-site maintenance proposals.** A manager may propose a window that includes its own site and the other one (agreed on
    the managers' call); only the director approves cross-site windows.
35. **Agent Card skills are not re-set at startup** unless `STEWARD_A2A_SET_SKILLS=true`: the orchestrator already set role skills on
    all nine cards, and overwriting them on every restart would be a needless live call.
36. **Overdue issues are deduplicated.** Expired work items yield one `overdue` issue per asset attribute (the latest, last 24 h,
    not superseded by a later fact or resolved item); the simulation expires a fresh card every few minutes.
37. **Regulation citations are ids.** Obligations carry `regulationIds` from the REGULATIONS stream's mapping (the Victorian
    wording no longer says "written scheme": TK-201 is inspection and maintenance with records, OHS regs 105-106, Part 3.5);
    ids the rule pack does not contain are reported as `unresolvedRegulationIds`. The file endpoint streams only `servePdf`
    records and redirects the rest.
38. **Test backend port.** Port 8012 was held by another stream's mock eye server (`node tools/mock-eye.mjs`); my test backend ran
    on 8022 against a copy of the real database and was stopped by its PID. Nothing was killed by pattern.
39. **Telemetry from the MCP is explicit.** The MCP posts one row per tool call to `POST /api/telemetry` (`detail: {in, out}` is
    stored compactly; missing `tokens` are taken as `in + out`). Owner's-agent endpoint calls are kept as `operator_call` records for
    transcripts but no longer add telemetry rows, so an MCP call is never counted twice.
40. **`decide` goes to the manager first.** The fallback records a one-question `message` conversation to the site's Plant Manager
    (left open until answered) and notifications; the owner SMS is sent only in live mode. A cross-site asker is routed through
    the director to respect the cross-site rule.

## Contract 5 (Tomioka Silk Mill), the eye fixes, comparison regulations and contract 6 (Tool Forge)

41. **The mill has 25 assets.** Contract 5 §3 heads its table "24" but lists 25 tags (RM-101..106, TR-201..204, BW-251, HS-301..303,
    VS-401, FE-501..503, FH-601, D-701/702, W-801, EP-901, CC-1001, DH-1101). Every listed tag is registered (`REGISTER_SIZES`), so the
    mill has 25 assets and 100 project checks; the plants keep 24 and 96.
42. **Sensor sub-kinds.** The contract gives the mill's sensors kind `sensor` but their own ranges (humidity 40-65 %, temperature
    5-30 °C; seismic 0-80 gal) while "existing kinds keep their specs" (`sensor` temperature 5-40 °C). The register keeps
    `kind: "sensor"` and adds `specKind` (`sensor:humidity`, `sensor:seismic`); every spec lookup goes through `spec_kind()`. New
    kinds also carry an identity `serial` where the asset has a nameplate (machine, sensors, camera, dehumidifier).
43. **Estimated pins in the viewer frame.** Pins for the mill are a scaled copy of the register layout centred about 2.5 m beyond the
    initial camera target along the view, inside dense leaves of the capture's LOD octree (the data rotated 180 degrees about Z, as
    the viewer shows it); the floor is taken near y -2.6. They stay `estimated` until the PINS stream places them.
44. **`jurisdiction` is back on property records**, as the registry's code (`VIC-AU`, `ENG-UK`, `JP`), with `prefix` and `siteKind`
    (the contract's "kind"); the first generation's free-text jurisdiction is still removed (`steward_site_shape_version=5`).
45. **tm-humidity ends with the fix workflow.** Contract 5 describes the whole arc (dehumidifier started, humidity back under 65 %,
    the engineer verifies and signs), so the script's last step (`fix`) runs the contract-4 fix workflow for its issue; the other
    scenarios leave their issue open for "Ask the agents to fix it", as before.
46. **Responsible person versus who is sent.** §4 makes the conservation architect own `humidity_high`; §5 has the technician send
    the conservator to start DH-1101. The crew table follows §4 (the architect is responsible and assigned by the fix call); the
    scenario's contact step names the conservator (`crewMemberId`). Both are synthetic, so both are recorded, never contacted.
47. **Cross-site checks only where the asset kind exists.** A mission's out-of-range cross-check now goes only to sites that register
    the same asset kind (the mill has no pumps or valves). The simulator's expiring work item uses the first asset with a state
    attribute where a site has no valve (RM-101.status at the mill).
48. **Overview budget.** With three sites and 14 agents the overview trims task and change text step by step to stay under 2,350
    characters (about 600 tokens).
49. **Comparison regulations.** Records with `binding: false` (the regulations stream's US-CA set, `comparisonFor`) are never cited
    as a reason: issues and obligations list them as `comparisonRegulationIds`, `GET /api/regulations` shows them only with
    `include=comparison`, and `why()` skips them. A comparison record relates to a problem through `appliesTo` (issue kind or
    scenario) or a link field (`comparesTo`, `equivalentOf`, `comparableTo`, `comparisonOf`) naming a binding id.
50. **Served PDFs carry their own attribution.** The JP records end their licence text with an `Attribution: 出典…` sentence; the
    header `X-Steward-Attribution` carries its ASCII "Source: …" part and `X-Steward-Attribution-Encoded` the full text
    (percent-encoded), because HTTP headers are Latin-1.
51. **Eye fixes.** A mark's picked point is read from `mark` or `annotation` and returned as `world` (`{x, y, z}`, the same shape as pins)
    with `hit`; `viewPose` is stored per asset through the pin route (a pose-only PUT keeps the pin; resetting to the estimate clears
    it) and sent with go_to and orbit (`viewPoseSource: asset | request`); `params.purpose == "survey"` tags frames and annotations
    (`survey: true`, `GET /feed?excludeSurvey=true`). Viewer commands and issue assignment are now authorised for the site they touch
    (a team role could previously post them at another site).
52. **Tool Forge additions.** Besides the contract's transforms there is `concat` (to put issue and obligation rows in one list) and
    the read `metrics.samples` (one row per point). An `act` step (eye moves, dispatch, raising an issue, moving the dashboard
    camera, `resolve` with a budget) makes a tool not read-only; such steps are previewed, not executed, during the test. The
    Owner's agent does not approve tools; a site manager approves read-only tools (the Director may too) and only the Director
    approves a tool with an act. A request whose task matches a hand-seeded draft (site, builder and keywords) uses it in build mode;
    anything else is recorded as `awaiting_draft` until `scripts/synth/forge.py --live` posts a Claude draft. Calls are allowed to the
    site's team, the Director and the Owner's agent; the steps always run as the builder. Each lifecycle step is a stored Change of
    type `tool` with `toolId`, `status`, `step` and `version`, and a line on the request's A2A conversation.
53. **Test backend port.** The contract-5/6 checks ran on 8062 against a SQLite-backup copy of the live database (the migration
    added the mill once, with a `pre-third-site-*` backup in the copy); it was stopped by its PID. The live database was only read.
