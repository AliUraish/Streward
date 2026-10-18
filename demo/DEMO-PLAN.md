# Steward demo video: plan

Working doc for the hackathon demo video (submission Oct 18 2026, 10:00). Ali explains on camera / voice-over; Claude writes the board. Board segments are rendered with the khan-explainer skill (`~/.claude/skills/khan-explainer`, blackboard or whiteboard, pen draws while the voice speaks). Remotion skills are installed in `.claude/skills/remotion-*` for any motion-graphic insert that a hand-drawn board cannot do well (animated call flow, counters, UI zoom).

## How the video gets made

1. Ali records the raw demo (screen + voice, one take is fine, pauses are fine).
2. `bash demo/ingest.sh recording.mov` writes `demo/work/<name>/transcript.txt` (timed sentences), `words.txt` (timed words) and `frames/` + `sheet-N.jpg` (one frame every 5 s with the timestamp burned in).
3. Claude reads the transcript and the frames, then proposes a cut list: for every spoken passage, either keep the screen recording, or overlay/insert a board segment, with the exact second it starts and ends.
4. Ali approves or edits the cut list.
5. Board segments are built in **real-audio mode**: Ali's own voice is the clock (`audio: 'clip.wav'`, beats take `at:` from `words.txt`), so the pen follows what he actually said. Nothing is re-voiced.
6. ffmpeg assembles: screen recording segments and board segments concatenated (or board picture-in-picture over the screen where the UI must stay visible), one MP4 out.

Board style decision: blackboard (dark) matches the dashboard's dark UI; the same scene renders as a whiteboard with `KHAN_THEME=light` if the final look needs it.

## Proposed structure (adjust after the recording)

| # | Section | Visual | Board or screen |
| --- | --- | --- | --- |
| 1 | Hook: the problem. An agent asks "is P-101 commissioned?" and today gets a made-up answer. | Board | Board: a box "agent", an arrow to "plant", a "?" and the word "guess" crossed out. |
| 2 | What Steward is: a reality layer. Three verbs: resolve, attest, check. Four answer states: known, stale, unknown, conflict. | Board | Board: three verbs as three ovals, the four states listed under resolve. |
| 3 | Who the agents are: Operator, Atlas, Warden, Runner. Authority is enforced in code. | Board | Board: a four-level ladder, one line per level of what it may and may not do. |
| 4 | Live demo: `start_mission clear_for_restart` from Claude Code through the Manufact-hosted MCP. | Screen | Screen, with a small caption strip per step. |
| 5 | Inkbox: Runner texts the technician the task card, wrong photo rejected, right photo accepted, escalation call. | Screen + board | Draw-over-UI: ring the SMS thread and the rejection reason "tag plate reads P-102, expected P-101". |
| 6 | Verification: six checks (scope, identity, geometry, plausibility, time, integrity), Ed25519 signature, `check` returns `valid: true`. | Board | Board: six checkboxes ticked one by one, then a signature line. |
| 7 | Supabase: `select verify_ledger();` returns ok over 6,000+ signed rows; an UPDATE on `attestations` is refused by the append-only trigger; Storage shows the walkthrough frames. | Screen | Draw-over-UI: ring `ok: true`, the red refusal, and the `signature` / `prev_hash` / `row_hash` columns. |
| 8 | Manufact: Sessions replay of `initialize` / `tools/list` / `tools/call`, publish score. | Screen | Draw-over-UI: ring the session and the tool call. |
| 9 | Armature: scored session, eval suite "Steward demo workflow" with judge marks. | Screen | Draw-over-UI: ring the score. |
| 10 | Close: honesty line (fictional plant, rule-based verification, no certification) and the one-line pitch. | Board | Board: the pitch written big. |

Per-sponsor "how we used it" boards (one each, 15 to 25 s), to insert where Ali mentions the product:

- **Inkbox**: one identity, three channels (SMS, email, call), signed webhook back, tunnel as the public URL. Draw: identity in the middle, channels fanning out to a phone, webhook arrow back, tunnel arrow to the laptop.
- **Manufact**: laptop backend, tunnel, hosted MCP on Manufact, Claude Code client. Draw: four boxes left to right with the gateway in the middle labelled "Sessions, Analytics, Publish checks".
- **Supabase**: an append-only, hash-chained ledger whose Ed25519 signatures Postgres verifies itself (pgsodium); every agent a Supabase Auth user under row-level security; Inkbox replies through an Edge Function into a pgmq queue; eye frames in private Storage behind signed URLs; private Realtime channels for the live HUD. Draw: signed reading into a chain of blocks with a padlock; three boxes underneath (Auth + RLS, Edge Function + queue, Storage); a browser labelled Realtime HUD.
- **Armature**: SDK wraps the MCP, sessions scored, eval suite runs a tester agent. Draw: the MCP box wrapped by a ring labelled "analytics", a tester agent arrow in, a 0 to 5 score out.

## Length target

Hackathon demo videos: 2 to 3 minutes. Boards total under 60 s so the product stays on screen most of the time.

## Render commands

```sh
# a board segment
node ~/.claude/skills/khan-explainer/scripts/render.js demo/scenes/<name>.js demo/out/<name>.mp4
KHAN_THEME=light node ~/.claude/skills/khan-explainer/scripts/render.js demo/scenes/<name>.js demo/out/<name>-light.mp4
```
