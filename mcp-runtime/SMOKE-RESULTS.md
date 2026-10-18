# Steward MCP verification

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
