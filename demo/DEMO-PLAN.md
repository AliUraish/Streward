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

## Proposed structure (rewritten Oct 18 against the live dashboard)

| # | Section | Screen | Board |
| --- | --- | --- | --- |
| 1 | Hook: an agent asks "is the sump about to overflow?" and gets a guess. | Home page hero. | Board 1. |
| 2 | What Steward is: three scanned factories, three verbs, four states. | Overview page, three site cards. | Board 2. |
| 3 | The agent eye: walkthrough, green and blue labels. | Bristol Environment page, "Agent's view" and "3-D scan". | Board 3. |
| 4 | The team: 17 agents, authority in code and Postgres. | Agents map. | Board 4. |
| 5 | Live: Claude Code on the hosted MCP, `get_overview`, `eye_go_to bristol-pumps SU-201`, start the Bristol sump scenario. | Terminal plus dashboard. | Captions only. |
| 6 | The meeting and the dispatch SMS; wrong photo rejected, right photo accepted. | Conversations page, phone. | Board 5 after the acceptance. |
| 7 | Compliance page: the regulation, the PDF, "Ask the agents to fix it". | Bristol Compliance tab. | Draw-over: ring the regulation and the button. |
| 8 | Inspection chain: owner email with the lawyer in CC, contractor call transcript, booking. | Notifications and Phone calls. | Board 6. |
| 9 | wait_for and tokens avoided. | Evals page. | Board 7. |
| 10 | Tool Forge (optional). | Tools page. | Board 8. |
| 11 | Self-optimisation (optional). | Evals before/after. | Board 9. |
| 12 | Sponsors: Inkbox console, Manufact sessions, Supabase tables, Armature sessions and evals. | Each dashboard. | One board each. |
| 13 | Close. | Home page footer. | Close board. |

Facts the boards rely on (checked Oct 18 on the running app): sites myer-plant, bristol-pumps, tomioka-mill; 17 agents plus the Dispatch Line; 76 MCP tools; hosted MCP at dark-wave-okfom.run.mcp-use.com; tunnel steward-atlas.inkboxwire.com; six checks scope, identity, geometry, plausibility, time, integrity; Evals page shows 362.8 min held by wait_for and 268,450 tokens avoided; efficiency eval 7.7x fewer tokens; published forged tool forge_pump_spec_breaches.

## Length target

Hackathon demo videos: 2 to 3 minutes. Boards total under 60 s so the product stays on screen most of the time.

## Render commands

```sh
# a board segment
node ~/.claude/skills/khan-explainer/scripts/render.js demo/scenes/<name>.js demo/out/<name>.mp4
KHAN_THEME=light node ~/.claude/skills/khan-explainer/scripts/render.js demo/scenes/<name>.js demo/out/<name>-light.mp4
```
