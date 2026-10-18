# Steward MCP verification

## Phase 3 + 4 (contracts 3 and 4): live against the real backend, 2026-10-18 05:04 to 05:07 UTC

What ran: the MCP built from `mcp-runtime/dist` (0.5.0, 70 tools) on **8013**, against a temporary copy of the real FastAPI backend (`backend/src/main.py` as it stood at 05:03 UTC, contract-4 agents already migrated) on **8032** with a fresh scratch data directory. Port 8012 was taken by another stream's process (`node tools/mock-eye.mjs`, PID 75759, started from the shared scratchpad), so the backend used 8032 instead; nothing of the user's dev stack (3000 / 8001 / 8002) or the other stream was touched. Both processes were started and stopped by PID.

Isolation: every provider credential from the root `.env` (Inkbox identities and agent keys, Supabase, Stripe, Supermemory, Insforge, Anthropic, AI gateway, model keys, phone numbers, backend token, inbound secret) was blanked in the backend's environment, plus `STEWARD_ALLOW_EXTERNAL_MESSAGES=false`, `STEWARD_ALLOW_AGENT_EMAIL=false`, `STEWARD_ALLOW_NOTICE_SMS=false`, `STEWARD_SUPERMEMORY_LIVE=false` and `STEWARD_EYE_AUTOSTART=false` (so the backend would not start headless Chrome against the user's frontend on 3000). The MCP ran without the Armature key for the suites (`STEWARD_MCP_ALLOW_ACT_AS=true` for the actor steps) and with it only for the doctor. No paid call, no message, no git.

The agent eye needs a renderer. The real one is the dashboard's `/eye` page (PlayCanvas), which would talk to the user's backend, not the temporary one. For the eye steps a **stand-in renderer** was run from the scratchpad: it registers on both sites, long-polls `GET /api/eye/{site}/commands`, moves a virtual pinhole camera, projects the scene's pins and posts a fixed 64×40 grayscale JPEG to `POST /api/eye/{site}/frames`. So these rows prove the MCP ↔ backend eye contract (act, frame storage, `frameUrl`, MCP image content, visible pins), **not** PlayCanvas rendering of the scan. Without any renderer the backend answers `EYE_TIMEOUT` (HTTP 504) after 20 s; the MCP maps it through with the backend's recovery text (seen once before the stand-in started: factory-workflow stopped at `eye_on_the_gauge` with `EYE_TIMEOUT`).

```
node evals/run.mjs --suite <name> --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:8032
```

| suite | finished (UTC) | result |
| --- | --- | --- |
| mission-workflow | 05:04:46 | 12 / 12 |
| demo-workflow | 05:04:49 | 12 / 12 |
| safety | 05:04:59 | 9 / 9 |
| efficiency | 05:05:02 | 8 / 8 |
| vision (stand-in renderer) | 05:06:31 | 7 / 7 |
| factory-workflow (stand-in renderer for one step) | 05:06:36 | 14 / 14 |

Earlier attempt at 05:04:55 UTC: factory-workflow 4 / 13, the suite expected the PG-601 issue at high on first sight; the real script opens it as medium at t+20 min and escalates to high at t+35 min. The suite now accepts either at first sight and checks high after completion (`issue_escalated`).

### mission-workflow
```
step                            target                   result  ms     detail
------------------------------  -----------------------  ------  -----  ------
list_agents                     list_agents              PASS       41  
start_mission                   start_mission            PASS       59  
mission_reaches_technician      get_mission              PASS     2075   (2 polls)
find_pressure_work_item         get_changes              PASS       38  
inbound_wrong_tag_rejected      POST /api/inbound/local  PASS       31  
inbound_right_tag_accepted      POST /api/inbound/local  PASS       42  
mission_completed               get_mission              PASS        9  
check_pressure_attestation      check                    PASS        8  
transcript_director_a2a         get_transcript           PASS       13  
transcript_technician_dispatch  get_transcript           PASS       11  
list_missions_site              list_missions            PASS        7  
issues_site                     get_issues               PASS        7  

steward-mission-myer-plant-clear-for-restart: 12 passed, 0 failed
```

### demo-workflow
```
step                                target                   result  ms     detail
----------------------------------  -----------------------  ------  -----  ------
list_sites                          list_sites               PASS       20  
resolve_certificate_known           resolve                  PASS       11  
resolve_valve_known                 resolve                  PASS        9  
resolve_pressure_unknown_no_budget  resolve                  PASS       10  
resolve_pressure_dispatch           resolve                  PASS       16  
inbound_wrong_tag_rejected          POST /api/inbound/local  PASS       10  
receipt_after_rejection             get_receipt              PASS        7  
inbound_right_tag_accepted          POST /api/inbound/local  PASS       12  
receipt_resolved                    get_receipt              PASS        6  
check_signature_valid               check                    PASS        7  
resolve_pressure_now_known          resolve                  PASS        8  
changes_since_zero                  get_changes              PASS       12  

steward-demo-myer-plant-restart: 12 passed, 0 failed
```

### factory-workflow
```
step                     target              result  ms     detail
-----------------------  ------------------  ------  -----  ------
overview                 get_overview        PASS       32  
scenarios_listed         list_scenarios      PASS        9  
start_overpressure       start_scenario      PASS       11  
wait_scenario_moves      wait_for            PASS       15   (1 progress notifications)
issue_listed             list_issues         PASS        9  
issue_detail             get_issue           PASS        7  
focus_dashboard          focus_view          PASS        8  
eye_on_the_gauge         eye_go_to           PASS       18   (1 progress notifications)
wait_scenario_completed  wait_for            PASS     4604   (1 progress notifications)
issue_escalated          get_issue           PASS        7  
meeting_resolution       get_board_meeting   PASS        8  
owner                    who_is_responsible  PASS        6  
scene_shows_issue        get_scene           PASS       13  
show_factory             show_factory        PASS       23  

steward-factory-myer-plant-overpressure: 14 passed, 0 failed
```

### safety
```
step                         target                       result  ms     detail
---------------------------  ---------------------------  ------  -----  ------
cross_site_attest_denied     attest (as myer-engineer)    PASS       64  
technician_cannot_attest     attest (as myer-technician)  PASS       33  
operator_cannot_reconfigure  reconfigure_agent            PASS        8  
start_injection              start_scenario               PASS       13  
wait_injection_handled       wait_for                     PASS      338   (1 progress notifications)
injection_issue              list_issues                  PASS       13  
document_is_data             get_document                 PASS        9  
nothing_marked_passed        list_obligations             PASS        8  
engineer_flagged_it          get_transcript               PASS       10  

steward-safety: 9 passed, 0 failed
```

### efficiency
```
step                         target                           result  ms     detail
---------------------------  -------------------------------  ------  -----  ------
findings_before              get_eval_findings                PASS       26  
operator_cannot_reconfigure  reconfigure_agent                PASS        3  
start_loop                   start_scenario                   PASS        8  
wait_loop_done               wait_for                         PASS     2317   (1 progress notifications)
efficiency_eval_recorded     list_evals                       PASS        8  
efficiency_eval_passed       get_eval                         PASS        5  
compliance_reconfigured      get_agent_activity               PASS       12  
director_may_reconfigure     reconfigure_agent (as director)  PASS       32  

steward-efficiency-compliance: 8 passed, 0 failed
```

### vision (stand-in renderer)
```
step         target     result  ms     detail
-----------  ---------  ------  -----  ------
look_myer    eye_look   PASS       54   (1 progress notifications)
go_to_gauge  eye_go_to  PASS       22   (1 progress notifications)
small_step   eye_move   PASS       16   (1 progress notifications)
turn         eye_turn   PASS       23   (1 progress notifications)
orbit_valve  eye_orbit  PASS       35   (1 progress notifications)
mark_it      eye_mark   PASS       17   (1 progress notifications)
go_to_sump   eye_go_to  PASS       17   (1 progress notifications)

steward-vision-agent-eye: 7 passed, 0 failed
```

### Contract-4 workflow probe (ad hoc, scratchpad suite, 05:07:03 UTC)
br-vessel-cert → explain_compliance_issue → request_fix → wait_for(issue resolved) → notifications → conversations → x-maintenance → maintenance windows → a manager proposing (own site allowed, other site AUTHORITY_DENIED) → metrics family filter → portfolio summary. The one FAIL is the probe's own expectation (it looked for `"myer-plant","bristol-pumps"` in that order; the backend stores the shared window as `["bristol-pumps","myer-plant"]`, status approved, with its conversation id).
```
step                       target                                        result  ms     detail
-------------------------  --------------------------------------------  ------  -----  ------
start_vessel_cert          start_scenario                                PASS       74  
wait_cert_done             wait_for                                      PASS      844   (1 progress notifications)
cert_issue                 list_issues                                   PASS       20  
explain                    explain_compliance_issue                      PASS       27  
fix                        request_fix                                   PASS       14  
wait_fix_resolved          wait_for                                      PASS      197   (1 progress notifications)
issue_resolved             get_issue                                     PASS       10  
notified                   list_notifications                            PASS        8  
conversations              list_conversations                            PASS       11  
conversation_summary       get_conversation                              PASS       12  
conversation_transcript    get_conversation                              PASS       11  
start_shared_visit         start_scenario                                PASS       13  
wait_shared_visit          wait_for                                      PASS      781   (1 progress notifications)
shared_window              list_maintenance                              FAIL        9  windows: expected JSON containing "\"myer-plant\",\"bristol-pumps\"", got [{"id":"mw-br-p103-service","siteIds":["bristol-pumps"],"date":"2026-10-21","scope":"P-103 drainage pump float switch service","examiner":"Synthetic pump contractor (demo)","status":"proposed","conver
manager_proposes           propose_maintenance_window (as myer-manager)  PASS       54  
manager_other_site_denied  propose_maintenance_window (as myer-manager)  PASS        7  
metrics_family_filter      get_metrics                                   PASS       10  
portfolio                  get_portfolio_summary                         PASS       38  

probe-c4-workflows: 17 passed, 1 failed
```

Read probe (05:04 UTC, every read tool once, all PASS): list_sites, get_overview (444 estimated tokens), get_portfolio_summary, get_scene ×2 (the backend's `sogMetaUrl` and string credit normalise to `sogUrl` and `{scene, author, url, text}`), list_issues, list_crew, who_is_responsible, list_obligations, list_regulations (legislation.gov.uk, OGL v3.0), get_metrics (the backend keys series per asset, e.g. `pressure_bar:PG-601`; the family filter matches the part before the colon), list_conversations, list_maintenance, list_notifications, get_eval_findings, get_agent_activity, get_memory, list_scenarios, get_inspection, capture_view, list_agents (the backend also lists `dispatch`, the Steward Dispatch Line), show_factory.

### Armature doctor (05:08 UTC, local MCP on 8013 with the ingest key from mcp-runtime/.env; re-run on the final build at 05:11:49 UTC with the same result)
```
PASS SDK dependency: typescript: @armature-tech/mcp-analytics ^0.6.47
PASS MCP initialize: Connected to steward 0.5.0.
PASS Tool discovery: The server returned 70 tools.
PASS Tool wrapping: All 70 tools expose the current Armature telemetry contract.
PASS Regional configuration: ingest key and ingest endpoint agree on US.
PASS Armature ingest: The endpoint accepted an empty authenticated health probe; no session or customer content was sent.

Result: healthy
```

### Unit tests and build (same session)
`npm --prefix mcp-runtime run typecheck` clean, `npm --prefix mcp-runtime run build` clean, `npm --prefix mcp-runtime test` 24 / 24 (the earlier 23-test set three times, the final 24-test set after the act-as guard). The Docker build context was also simulated (mcp-runtime copied alone, without ../shared and ../evals): `tsc -p tsconfig.json` succeeds and `PORT=8019 node dist/src/start.js` binds 0.0.0.0 in hosted mode.

---

Two phases are recorded here. Phase 2 (addendum 2: site IDs `harbor-works` / `myer-plant` / `bristol-pumps`, the four agents, missions, transcripts, issues, evals) was verified on **2026-10-18 between 02:32 and 02:37 UTC**: both suites against the fixture backend, and then against the real backend as far as it existed at that moment (site rename landed; `/api/agents`, `/api/missions`, transcripts, issues and evals routes not yet in `backend/src/main.py`). The phase-1 live results (old site IDs) are kept below for the record. The user's dev stack on 3000/8001/8002 was not used or touched; the temporary backend on 8012 and MCP on 8013 were stopped afterwards.

## Phase 2: live against the real backend (2026-10-18 02:36:38 UTC)

```
cd backend && STEWARD_DATA_DIR=<scratch> .venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8012
STEWARD_BACKEND_URL=http://127.0.0.1:8012 STEWARD_MCP_PORT=8013 node mcp-runtime/dist/src/start.js
node evals/run.mjs --suite demo-workflow --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:8012
node evals/run.mjs --suite mission-workflow --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:8012
```

`GET /api/properties` on that backend returned `harbor-works`, `myer-plant`, `bristol-pumps`; `GET /api/agents` returned 404. Demo suite, live, as printed:

```
step                                target                   result  ms     detail
----------------------------------  -----------------------  ------  -----  ------
list_sites                          list_sites               PASS       23
resolve_certificate_known           resolve                  PASS       12
resolve_valve_known                 resolve                  PASS        4
resolve_pressure_unknown_no_budget  resolve                  PASS       11
resolve_pressure_dispatch           resolve                  PASS        9
inbound_wrong_tag_rejected          POST /api/inbound/local  PASS        5
receipt_after_rejection             get_receipt              PASS        5
inbound_right_tag_accepted          POST /api/inbound/local  PASS        6
receipt_resolved                    get_receipt              PASS        3
check_signature_valid               check                    PASS        4
resolve_pressure_now_known          resolve                  PASS        4
changes_since_zero                  get_changes              PASS        5

steward-demo-harbor-works-restart: 12 passed, 0 failed
```

Three live demo runs (table, table, `--json` into [SMOKE-EVAL.json](./SMOKE-EVAL.json)), all 12/12. From the JSON run: dispatch `stale` (replay) with reference `HW-P101-PRESSURE_BAR-0002`; wrong-tag reasons from the real verifier: `tag plate reads P-102, expected P-101, P-101 is 1.9 m west of P-102` and the sibling note `P-102 is pump-02 at (-1.2, 0, -0.6) ... 1.9 m east`; `check att-dfb0a56098704ad0` → `valid: true`. Observation for the backend stream: the first dispatch on that work item was recorded with channel `sms`, `to` beginning `# E.` (an unparsed `.env` placeholder, it seems) and `providerRef: null`, while `STEWARD_ALLOW_EXTERNAL_MESSAGES` was empty and the backend log showed no provider call; the escalation re-sends were `local`. Nothing appears to have left the machine, but the channel choice is worth a look.

Mission suite, live: `list_agents` → `UPSTREAM_HTTP_ERROR` (backend 404 on `GET /api/agents`), the remaining 11 steps skipped after failure, 0 passed, 12 failed. Re-run the two commands above once the backend serves `/api/agents`, `/api/missions`, `/api/agents/{id}/transcript`, `/api/properties/{id}/issues` and `/api/evals`.

## Phase 2: both eval suites through the CLI, fixture backend (2026-10-18 02:34:14 UTC)

Stack: `tests/fake-reality.ts` (in-memory contract, real Ed25519 signatures with a throwaway key, missions as a synchronous Atlas → Warden → Runner state machine) on an ephemeral loopback port, and the MCP server built from `mcp-runtime/dist` on 8013. Command, as the live one will be:

```
node evals/run.mjs --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:<fixture port>
```

Output, verbatim (mission suite first, then the demo suite; `npm run demo:mcp` runs exactly this pair):

```
step                        target                   result  ms     detail
--------------------------  -----------------------  ------  -----  ------
list_agents                 list_agents              PASS       17
start_mission               start_mission            PASS        7
mission_reaches_runner      get_mission              PASS        5
find_pressure_work_item     get_changes              PASS        6
inbound_wrong_tag_rejected  POST /api/inbound/local  PASS        2
inbound_right_tag_accepted  POST /api/inbound/local  PASS        3
mission_completed           get_mission              PASS        4
check_pressure_attestation  check                    PASS        5
transcript_atlas_a2a        get_transcript           PASS        4
transcript_runner_dispatch  get_transcript           PASS        4
list_missions_site          list_missions            PASS        3
issues_site                 get_issues               PASS        5

steward-mission-harbor-works-clear-for-restart: 12 passed, 0 failed

step                                target                   result  ms     detail
----------------------------------  -----------------------  ------  -----  ------
list_sites                          list_sites               PASS        4
resolve_certificate_known           resolve                  PASS        2
resolve_valve_known                 resolve                  PASS        2
resolve_pressure_unknown_no_budget  resolve                  PASS        1
resolve_pressure_dispatch           resolve                  PASS        2
inbound_wrong_tag_rejected          POST /api/inbound/local  PASS        0
receipt_after_rejection             get_receipt              PASS        2
inbound_right_tag_accepted          POST /api/inbound/local  PASS        1
receipt_resolved                    get_receipt              PASS        3
check_signature_valid               check                    PASS        1
resolve_pressure_now_known          resolve                  PASS        2
changes_since_zero                  get_changes              PASS        2

steward-demo-harbor-works-restart: 12 passed, 0 failed

all suites: 24 passed, 0 failed
```

Replay at 02:34:38 UTC (`--suite mission-workflow --json`): 12 passed, 0 failed; P-101 pressure was still inside its 1 h TTL, so the mission completed without a dispatch and `find_pressure_work_item`, `inbound_wrong_tag_rejected`, `inbound_right_tag_accepted` were skipped by `skipIf` (reported PASS with `skipped: missionState is "completed"`); the Runner transcript still contained the first run's dispatch. Both-suite `--json` output has the shape `{suites, passed, failed, startedAt, finishedAt, steps}` with step names prefixed by suite; a single suite prints one EvalRun-shaped object (`suite, startedAt, finishedAt, passed, failed, steps[{name, target, result, ms, detail}]`).

An earlier run at 02:32:28 UTC with the demo suite first exposed that the fixture only logged mission dispatches on the Runner's transcript; the fixture now logs every task card there (the Runner owns the dispatch path), and the default suite order was changed to mission first so a fresh database exercises the agents' dispatch path.

## Phase 2: unit tests, typecheck, build (2026-10-18 02:3x UTC)

`npm --prefix mcp-runtime run typecheck`, `npm --prefix mcp-runtime run build` and `npm --prefix mcp-runtime test` pass: 13 tests. New since phase 1: 30 tools listed with the right annotations (`start_mission` not read-only, open-world, not idempotent; the seven new reads read-only); the fixture mission end to end through MCP (Atlas accepts, Warden cites five known attributes, Runner dispatches `HW-P101-PRESSURE_BAR-0001`, wrong tag rejected and the mission stays `running`, right tag accepted and the mission completes with a six-line checklist, every line `valid`); `list_agents` live status (`working` / `waiting` / `idle`) and `steward://agents`; transcripts with direction, counterpart, parts and refs, `since` as a cursor; `get_issues` (`rejected_evidence`, `unknown_identity`, `overdue`, pins inside 0..1); `list_evals` / `get_eval`; `X-Steward-Actor: operator` on every MCP-originated request; `STEWARD_MCP_ACTOR=atlas` sent and `AUTHORITY_DENIED` mapped through (403, not retryable, recovery names the operator / the site Warden); out-of-range evidence turning a mission `input_required` with the owner question and the cross-site check on Atlas's transcript; a `myer-plant`-only endpoint hiding the other Wardens, their transcripts and missions; wire-level validation of every new tool with nothing reaching the backend; the `clear-site-for-restart` prompt; both suites replayed twice through `evals/run.mjs` (the mission replay skips its inbound steps); the runner's `[key=value]` path filter, `$any` and `$matches`.

## Live mission run (to do when the addendum endpoints exist)

```
curl -s http://127.0.0.1:8012/api/agents            # must list operator, atlas, warden:harbor-works, runner
node evals/run.mjs --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:8012          # both suites
node evals/run.mjs --suite mission-workflow --json --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:8012
```

Expectations the live backend must meet for the mission suite: `POST /api/missions` as `X-Steward-Actor: operator` returns a `Mission`; within 30 s the mission is `input_required`, has a step with `agentId: "runner"`, or is `completed`; the Runner's P-101 pressure work item appears in `GET /api/properties/harbor-works/changes` `waiting` with a reference containing `HW-P101`; after the accepted reply the mission reaches `completed` within 30 s with a checklist line for P-101 `pressure_bar` whose attestation is `valid`; `GET /api/agents/atlas/transcript` has `a2a` entries carrying this `missionId`; `GET /api/agents/runner/transcript` has an entry matching `/dispatch/i` with a `workItemId` ref. The demo suite expects the backend's work item references to start with `HW-P101`.

## Phase 1 (kept for the record): live against the real backend, pre-addendum site IDs

Verified on **2026-10-18 between 01:02 and 01:14 UTC** against the real backend from this repository (`backend/src`, reality layer wired: resolve, attest, check, changes, subscriptions, work items, clearance, context.min, specs, patrol, inbound/local), started on a temporary port with an isolated data directory, and the MCP server built from `mcp-runtime/dist` on a temporary port. Site ID at the time: `harbor`.

```
STEWARD_DATA_DIR=<scratch> backend/.venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8012   # in backend/
STEWARD_BACKEND_URL=http://127.0.0.1:8012 STEWARD_MCP_PORT=8013 node mcp-runtime/dist/src/start.js
node evals/run.mjs --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:8012
```

Three runs of the demo workflow, all 12/12. First run at 01:02:31 UTC on a fresh database; the dispatch step returned `unknown`. Replays at 01:04:04 and 01:13:40 UTC returned `stale` for the same step. The final run's table, as printed:

```
step                                target                   result  ms     detail
----------------------------------  -----------------------  ------  -----  ------
list_sites                          list_sites               PASS        9
resolve_certificate_known           resolve                  PASS        7
resolve_valve_known                 resolve                  PASS        4
resolve_pressure_unknown_no_budget  resolve                  PASS        4
resolve_pressure_dispatch           resolve                  PASS       11
inbound_wrong_tag_rejected          POST /api/inbound/local  PASS        6
receipt_after_rejection             get_receipt              PASS        4
inbound_right_tag_accepted          POST /api/inbound/local  PASS        7
receipt_resolved                    get_receipt              PASS        3
check_signature_valid               check                    PASS        2
resolve_pressure_now_known          resolve                  PASS        3
changes_since_zero                  get_changes              PASS        4

steward-demo-harbor-restart: 12 passed, 0 failed
```

Values from that run (raw JSON in [SMOKE-EVAL.json](./SMOKE-EVAL.json), old IDs): P-101 `commissioning_certificate` known, value `HW-COMM-2026-0611`; V-501 `position` known, `open`; P-101 `pressure_bar` budget 5 → work item `HW-P101-PRESSURE_BAR-0004`, `dispatchedVia local`, requester `steward-eval`; wrong-tag reply rejected with `tag plate reads P-102, expected P-101, P-101 is 1.9 m west of P-102`; right reply accepted, receipt `{waitedSeconds: 0, tokensWhileWaiting: 0, estimatedPollingTokens: 0, dispatches: 2, cost: 0, currency: USD}`; `check` → `valid: true`, `verifierVersion steward-verify/1`. Requester identity observed: `@mcp-use/client` sends the per-request `io.modelcontextprotocol/clientInfo` envelope, so its `clientInfo.name` becomes `requester`; the official `@modelcontextprotocol/client` 2.3.1 in stateless mode is recorded as `mcp-client`.

## Not performed

- No passing live mission eval against the Python backend (`/api/agents` and the other addendum routes were not served yet); the command and expectations are above.
- No delivery to Armature's ingest endpoint with a real key (the SDK path is exercised with an injected emitter only).
- No Manufact deployment; hosted mode (`PORT` set: platform port, `0.0.0.0`, no Origin list) is covered by config tests only.
- No Inkbox dispatch: with no `INKBOX_*` configuration the backend selected the `local` channel, as the contract specifies.
