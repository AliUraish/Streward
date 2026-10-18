# Frontend design decision

Written Oct 17 2026 for the Steward reality layer (`/` website, `/app` dashboard). This record is the
pre-flight the taste skill asks for (`.agents/skills/design-taste-frontend/SKILL.md`, steps 1–5) plus
the tokens adopted from the taste-library references, so anyone picking up `frontend/` can see what was
decided and why.

## Pre-flight (taste-skill step 1, 2 and 4)

- **Subject.** Steward: a reality layer industrial agents call. `resolve` returns a fact with a signed
  attestation, or dispatches a human to get one. The plant is Harbor Works (24 tagged assets, one plant room).
- **Audience.** Hackathon judges and engineers who run agents (Claude Code with an MCP attached). They
  read JSON for a living and distrust marketing claims; the page has to show real output.
- **The one action.** Connect Claude Code to the MCP at `http://127.0.0.1:8002/mcp` (the close section
  holds the snippet) and open `/app` to watch the plant answer.
- **The idea sentence.** On this page, **the resolve call's own JSON response** becomes **the hero
  picture: typed out live from a real backend call, with the signed attestation as the proof artefact.**
  The competitor test: another twin product would show a render of a plant; Steward shows the answer an
  agent gets, and whether it was proven. The live thing: the hero makes a real `POST
  /api/properties/harbor/resolve` on load and types the real response; when the backend is not up it
  types a clearly labelled sample.
- **Inventory used.** Tag plates (P-101, P-102, TS-801, TS-802), the reference format
  `HW-P101-PRESSURE_BAR-0042`, the six check names (scope, identity, geometry, plausibility, time,
  integrity), the Ed25519 public key, TTLs per attribute class, the "P-101 is 2 m west of P-102"
  rejection reason, the 1.5–3.5 bar spec range, the 400-token `context.min`.
- **The argument (one claim per section, each with proof).**
  1. Hero: "Agents ask the plant. The plant answers with proof, or sends someone to get it." Proof: the
     live resolve call, typed.
  2. Three eyes: the plant is seen by scan, camera and sensor. Proof: live TS-801/TS-802 readings from
     `/facts` with their age.
  3. Proof is rejected before it is accepted. Proof: the check table from a real attestation, else the
     six rules verbatim from the contract.
  4. Every fact is signed and anyone can `check` it. Proof: the real public key from
     `/api/attestations/public-key` and the shape of the record.
  5. Runs on: Inkbox, Manufact, Supabase, Armature, one line each on what runs there (text only; no
     sponsor logos because we do not have their brand assets).
  6. Close: the Claude Code connection snippet and the link to `/app`.
  No testimonials, no pricing, no feature grid: none of those have proof.

## References from the taste-library (`scripts/query.py show …`)

Cloned to the session scratchpad and queried with `python3 -I scripts/query.py show <id> --section <s>`.

| Reference | Section | What was taken |
| --- | --- | --- |
| `vercel` | `typography` | Geist Sans for everything; display headings at weight 450 and line-height 1.0 (Heading 72/64/56 are set solid). Copy sizes 18–24 px with generous leading. |
| `vercel` | `colors` | "Ink Black" `#171717` as the darkest tone step; the discipline of one neutral palette with one reserved accent ("Accent Blue … reserved strictly" → here the green is reserved for verified and the primary action). |
| `vercel` | `surfaces` | Surfaces as a ladder of flat greys (background-100/200, gray 100/200/1000). Adopted as tone steps on black. Its soft shadows and linear gradients were not adopted (house rule). |
| `vercel` | `navigation` | 64 px plain bar, no visible border (`0px solid`), sticky. Adopted as is. |
| `linear` | `surfaces` | Primary `#08090A`, panel `#0F1011`, nested `#141516`: depth on dark through a lighter surface step rather than lines. Adopted as the step sizes between `--s0` … `--s3`. |
| `linear` | `colors` | Text ladder: high contrast `#F7F8F8`, reading `#D0D6E0`, muted `#8A8F98`. Adopted as `--ink`, `--ink-2`, `--muted` (neutralised; no blue tint, because the ground is pure black per the user's decision). |
| `linear` | `navigation` | Nav links muted at rest, brightening to white on hover/active. Adopted; the glass background and 1 px bottom border were not (house rules: no glass, no hairlines). |
| `linear` | `typography` | Medium weight (500) for titles, 16/24 body. Adopted for the dashboard's working size. |
| `supabase` | `colors` | "Signal Green" as the single energetic accent on a monochrome base; the insight that the palette "commits to a disciplined monochromatic base punctuated by a single green accent". Our accent is `#3ddc84` (user's choice), used only for verified and the primary action. |
| `supabase` | `navigation` | Tabs that change text and border tone, not background colour, for the dashboard's secondary nav. |

## Tokens adopted (`src/app/globals.css`)

```
--g0 #000000   ground (Vercel OG black)
--s1 #0a0a0a   first tone step: rail, panels
--s2 #121212   second step: rows, fields
--s3 #1b1b1b   third step: hover, pressed, selected
--s4 #262626   fourth step: chips, tracks
--ink #ededed  primary text (soft light, not #fff)
--ink-2 #c9c9c9 reading text in dense views
--muted #8f8f8f secondary text, 7.2:1 on black
--accent #3ddc84 verified + primary action only; --accent-ink #000
--radius 0     decided once; square corners everywhere, including buttons
--font-sans Geist Sans (geist package); --font-mono Geist Mono, used only for tags, references, hashes, attestation IDs and real JSON
--ease-out cubic-bezier(.22,1,.36,1); --t-press 140ms; --t-hover 180ms; --t-ui 240ms; --t-reveal 800ms
```

Type: two working sizes per view. Website: display `clamp(44px, 8vw, 112px)` at line-height 0.95 and
tracking −0.03em; text 18 px. Dashboard: title 28 px and working 14 px, with mono 13 px for tags.

House rules applied: no hairlines (surfaces separate by tone step), no eyebrows, no tracked uppercase
labels, no gradients, no shadows at rest (the attestation drawer, which floats, is the one exception the
skill allows), no glass, no icon-topped card grids, no index numbering, no styled accent word.

## Rejected directions

- A light "paper" theme (the previous Steward build): the user chose black ground; dark only.
- Rendering the Three.js twin on the website as the hero picture: heavy for a landing page and would
  compete with the real resolve output, which is the idea.
- Sponsor logos in the "runs on" strip: no brand assets in the repo, so names set in text.

## QA results (Oct 17 2026, dev server on :3000, backend reality endpoints still 404)

Tools: `scripts/lint.mjs` and `scripts/inspect.mjs` from the installed taste skill (Chrome headless, widths
1440 / 768 / 390). Screenshots: `frontend/qa/site-{1440,768,390}.jpg`, `frontend/qa/app-{1440,768,390}.jpg`,
full sheets under `frontend/qa/inspect-site/` and `frontend/qa/inspect-app/` with `report.json` each.

**Lint** (`src/components/site`, `src/components/dash`, `src/app`, `src/lib`, `steward-app.tsx`): 0 FAIL, 0 WARN.
Lines that set monospace carry `taste-skill-ignore` because the user chose mono for tags, references,
hashes and attestation IDs; one legacy `.eyebrow` in the inspection-wall header is restyled to sentence
case in `legacy.css` and marked the same way.

**Inspector, `/` (website), run with `--allow mono` for the same reason:** 0 FAIL, 2 WARN.
- Measured: hero "Agents ask the plant." 2 lines at 1440 (100 px, Geist 450, tracking −0.03em, leading 0.95),
  1 line at 768, 2 lines at 390. Body 18 px / 1.5. Page #000000, sections #0a0a0a, button #3ddc84.
  4 images (the product's own interface: twin, inspection wall, rail, phone), 8.5 screens, 786 words.
- WARN size-count: 11 sizes measured. Defended: the working pair is 100/18 (display/text) with 14 for
  mono and 60 for section titles; the rest are the statement (34→22 fluid), buttons (15/16) and the
  footer wordmark (317). WARN no-footage: no honest clip exists of a fictional plant; not faked.
- Fixed during the loop: headlines that wrapped to 3–4 lines (hero column widened to 1/2, titles cut to
  "Three eyes, one record.", "Rejected, then accepted.", "Signed, so anyone can check."), the footer
  wordmark at 1.2:1 contrast (now `--muted`), muted ink raised from #8f8f8f to #a1a1a1 (8:1 on black),
  figure captions that read as eyebrows above the next heading (removed), zero pictures (four real
  dashboard captures added under `public/site/`).

**Inspector, `/app` (dashboard), `--allow mono`:** 3 FAIL, 4 WARN, all defended because the skill is
written for landing pages ("Not for dashboards or app screens"):
- shadow: `scene.module.css` marker label (Three.js twin internals, out of scope by instruction).
- body-size 13 px: the dashboard working size is 14 px in the new chrome; the 13 px measured is the
  legacy secondary views and dense row metadata. hero-words / few-pictures / measure: not applicable to
  an app screen whose first screen is the twin canvas (48% of the viewport).
- Verified by eye at 390: bar wraps to two rows, twin at 48vh, rail stacks below, timeline last.

**Build:** `npm run build` green (routes `/`, `/app`, `/llms.txt`); `tsc --noEmit` clean.

---

# Website redesign, Oct 17 2026 (evening): Human / Agent modes, the hero drawing, black and white only

Second pass on `/` only. The dashboard at `/app` is untouched and keeps its green. Taste skill
(`.claude/skills/design-taste-frontend`) run in full: pre-flight, three dealt directions, one chosen, one redraw,
lint and inspector at 1440 / 768 / 390, look-and-fix rounds. The previous section above stays as the record of the
first build; this section supersedes it for the website.

## Pre-flight (steps 1, 2, 4)

- **Subject.** Steward, a reality layer industrial agents call: `resolve` returns a signed fact or dispatches a
  technician; `attest` and `check` close the loop. The plant is Harbor Works (site id `harbor-works`, 24 tagged assets).
- **Audience.** Judges and engineers who run agents; and the agents themselves (Agent mode serves `/llms.txt`).
- **The one action.** Point Claude Code at the MCP URL (the close section's sentence has the URL as its blank).
- **Inventory used.** The name Steward; Harbor Works, 68 Harbor Way, Oakland; the 13 × 12 m plant room; P-101 at
  x −3.1 and P-102 at x −1.2 (1.9 m apart, the "two metres west" rejection); V-501 above P-101, V-504, TK-201 and
  PG-601 from `shared/scene.json`; door D-1101; 1.5–3.5 bar and the 2.4 bar reading; the six checks; reference
  `HW-P101-PRESSURE_BAR-0042`; $0.50 on proof and the $5 budget; TTL classes; Ed25519; the task card text.
- **The argument.** (1) Agents ask the plant; the plant answers with proof or sends someone → the hero drawing
  performing the loop. (2) The same call, beat by beat, with the real fragments (call, response, task card, six
  checks, attestation). (3) One work item through four states → the ticket card in four fields. (4) Three eyes:
  scan, camera, sensor → three 5/7 rows with the product's own captures. (5) What the record holds (verbs,
  freshness, checks, runs-on) → one narrow column of two-ended rows. (6) Connect → a sentence with a blank.
  (7) A footer of tiles. No testimonials, pricing or feature grid: none have proof.
- **Idea sentence.** On this page, **the plant's own pipe run (P-101, P-102, their valves, the gauge and the tank
  from the twin's scene graph)** becomes **the stage on which one `resolve` call is performed, in a loop, as a line
  drawing**. Competitor test: another twin vendor would render a plant; only Steward's page shows the ask, the
  refusal at the wrong plate, the six checks and the signed packet leaving.
- **The live things.** The drawing's loop (it runs on its own; scrolling to a beat re-phases it), and the close
  sentence whose blank is the MCP URL the reader can edit before copying the exact `claude mcp add` command.

## Direction dealt (step 3)

`node scripts/draw.mjs --sector dev-tool --sections how-it-works,features,list,cta,footer --tone technical
--have product-ui --keep palette,type --options 3` dealt `one-motif`, `product-performs`, `quiet-instrument`.
Chosen: **The product performs** (seed 2045055831), because the brief's five beats are literally the product
doing its job in front of the visitor, and Agent mode shows the real agent-facing document.

Redraws, with reasons:
- `--redraw hero` once: the dealt "Controls on the sentence" (chips that alter the headline) contradicted the
  user's stated constraint that the first screen is the Three.js narrative. The redraw dealt "Control that reads the
  page" (two tone halves, headline bottom-left, the working fragment on the right), which was built first; the user
  then asked for the scene full width with the headline just below it, so the final hero is that: the drawing is the
  hero, edge to edge, and the headline block sits under it. Recorded as a user instruction overriding the blueprint.
- Sections taken from the sheet: how-it-works "One card, four fields" (the ticket through open, dispatched,
  rejected, resolved), features as the 5/7 rows of the direction's composition (three eyes), list "Two-ended rows,
  narrow column" (the record), cta "A sentence with a blank" (the MCP URL is the blank, the last words are the
  button), footer "A footer of tiles" (the accent tile became a grey tile; no accent on this page). The features
  blueprint "Fixed output, live controls" was used for the first full-width-less build and dropped when the hero
  went full width; the beats are now a plain two-column list under the hero.

## What was built

- **Modes.** A `role="switch"` in the bar: a track, a white knob that glides (320 ms, ease-in-out), two words that
  invert where the knob covers them (`mix-blend-mode: difference` over white/grey only). Arrow keys, Home/End,
  Space/Enter. `?mode=agent` in the URL via `history.replaceState`, remembered in `localStorage` (try/catch), instant
  swap under reduced motion. Switching to Agent scatters every `[data-dissolve]` block (deterministic offsets,
  460–520 ms, stagger up to 200 ms, transform and opacity only), then mounts the document; switching back mounts the
  human page scattered and re-forms it. In Agent mode the bar keeps only the wordmark (not a link) and the switch:
  no buttons, no links, no copy control, per the user's instruction. The document is `/llms.txt` fetched at runtime
  and rendered by a 60-line Markdown renderer (`markdown.tsx`: headings, paragraphs, lists, blockquote, fences,
  inline code, bold, links), plus the Claude Code snippet as code blocks. Monospace is used for this document only.
- **The hero drawing** (`hero-sketch.ts`, `hero-scene.tsx`, `hero-static.tsx`). One 2D segment list draws the pipe
  run, two pumps (motor, fins, shaft, volute, pedestal, riser, flanges), two gate valves with handwheels, a gauge with
  a scaled dial and needle, a domed tank with legs and a level glass. React Three Fiber renders it orthographically
  as one merged `LineSegments` (one draw call for the still part) plus a dozen small animated parts; the same list
  draws the SVG still frame used under reduced motion or without WebGL. The loop is about 16 s: the ask travels in
  along the pipe (2.8 s), the needle settles on 2.4 bar and P-101 cites `CC-2026-0611-P101` (2.8 s), a dot goes out
  to P-102 (3.0 s), a cross appears, the dot slides 1.9 m west to P-101 and six ticks appear (3.8 s), a packet
  travels back along the pipe (2.8 s), then a rest (1.6 s). Easing is cubic in-out; the only persistent motion is
  the handwheels turning at 0.12 rad/s, the tank level breathing over ~70 s, and a camera drift of 0.18 units.
  Captions are one line of at most six words, in one place at the top of the stage, cross-fading. Labels are DOM
  elements placed by projecting world positions; on phones only agent, P-101 and P-102 show. The drawing is
  captioned honestly in the hero copy as a sketch of the fixture plant. The attestation ID in the last beat is the
  latest accepted attestation from `GET /api/attestations/{id}` (found through `/changes`) when the backend has one;
  otherwise `att_sample_p101_pressure` labelled as a sample. Rendering pauses when the stage leaves the viewport.
- **Buttons.** One shape: white fill, black words, square, 44 px. Hover: a `#333` layer scales in from the left
  (240 ms) and the words invert through `difference`; press scales to .97; arrows nudge 4 px. Reduced motion makes
  every move instant through the global rule in `globals.css`.
- **Colour.** On `/` the root tokens are overridden: `--accent: #fff`, so focus rings and selection are white; the
  page uses #000, #0a0a0a, #121212, #1b1b1b, #262626, #333 and the ink ladder only. The four strip fields step
  #0a0a0a → #161616 → #232323 → #303030. The footer wordmark tile is white.
- **Type.** Geist Sans; five steps: `--t5` 96–150 px (footer wordmark), `--t4` 30–48 px (h1, section leads),
  `--t3` 26–34 px (headings, beat titles, clauses), `--t2` 17 px (text), `--t1` 14 px (small), with 13 px inside
  `data-ui` fragments as interface text, which the sheet allows.
- **Copy.** Site ids use `harbor-works`; agent names where mentioned are Atlas (requester) and Runner (the field
  agent on the dispatch channel); no residential words.

## Lint and inspector results (final run, dev server on :3000, Chrome headless with SwiftShader WebGL)

- `scripts/lint.mjs` over `src/components/site`, `src/app/{page,layout}.tsx`, `globals.css`: **0 FAIL, 0 WARN**.
  Lines that set monospace carry `taste-skill-ignore` with the reason (real code, the agent document).
- `scripts/inspect.mjs http://127.0.0.1:3000/` at 1440 / 768 / 390: **0 FAIL, 2 WARN.** Measured: hero headline
  "Agents ask the plant." 4 words, 1 line at every width (48 / 30 / 30 px); sizes 13 / 14 / 16 / 17 / 22 / 32 / 36 /
  48 / 130; page #000000, sections #0a0a0a #121212, button #ffffff; 8.4 screens, 799 words, 4 pictures (the
  product's own captures under `public/site/`), hero media 62% canvas.
  - WARN `no-footage`: defended. The plant is fictional; no honest clip exists and none was faked. The hero's loop is
    the page's moving picture.
  - WARN `blend-text`: defended. The eight blended elements (button labels, the switch words) sit only over white,
    #333 or the black ground, which is the one case the rule allows; the page has no hue.
- The inspector could capture WebGL (SwiftShader), so no separate capture path was needed for it. The deliverable
  screenshots were taken with the skill's own CDP helper (`scripts/lib/cdp.mjs`) from a scratch script, which also
  exercised the switch, the deep link and storage and dumped the console: no errors, no warnings in the final run.
- Earlier rounds fixed: a three-line CTA sentence (now a 36 px statement), monospace references outside code (set in
  the text face), two near-empty desktop screens (the record and the close now sit on tone fields), eleven sizes
  (cut to the five steps plus 13 px fragments), a hydration warning (whitespace in `layout.tsx`'s `<html>` and the
  `js` class added before hydration, now `suppressHydrationWarning`), drei `Html` labels that threw on unmount
  (replaced by projected DOM labels), the scene caption reading as an eyebrow above the h1 at 390 (moved to the top
  of the stage), and 11 px phone labels (13 px, secondary ones hidden).
- `npm run build` from the repo root: green (`/`, `/app`, `/llms.txt`); `tsc --noEmit`: clean. The build's only
  note is Next's pre-existing warning about `fs.readFile` in the `/llms.txt` route.

Screenshots: `frontend/qa/site2-1440.jpg`, `site2-768.jpg`, `site2-390.jpg`, `site2-agent-1440.jpg`,
`site2-agent-390.jpg`, `site2-1440-beat.jpg`; inspector sheets under `frontend/qa/inspect-site2/`.

## Rejected during the session

- A 3D wireframe of all 24 assets (first as abstract primitives, then as a merged line sketch with a walking
  figure): rejected by the user as hard to read. Replaced by the flat elevation of six pieces of equipment and a dot.
- A scroll-pinned story column beside the scene: dropped when the hero went full width; the loop runs on its own
  and scrolling to a beat only re-phases it.
- Any accent colour on `/`; copy and raw-link buttons in Agent mode; the technician as a stick figure.

## Still open

- On 768 the drawing fits the width and leaves black above and below inside the 46svh stage; a shorter stage at
  that width is a one-line change once the user has approved the hero.
- The backend reality endpoints answered 404 during this session, so every live slot (sensor readings, the
  attestation, the check table) rendered its labelled sample; the code paths for live data are in place.

---

# Dashboard sections, Oct 17 2026 (night): Environment, Agents, Evals under `/app`

Dashboard stream for REALITY-CONTRACT-2.md. The website at `/` is untouched; everything here is scoped under
`.dash` in the new `src/app/dash.css` (the shell and the three sections) next to the existing
`src/components/dash/dash.css` (panels, rows, timeline, drawer). Same tokens, same rules: tone steps, no hairlines,
no eyebrows, no gradients, no shadows, Geist, green only for verified and the primary action, mono only for tags,
references, hashes, handles and tool targets. The taste skill is written for landing pages, so its picture and
headline rules are not applied to these app screens; its lint is.

## What was built

- **Shell** (`components/dash/shell.tsx`, route group `app/app/(dash)/`): `/app` redirects to `/app/environment`
  (server redirect; `/app?view=inspection|library|agents` still renders the older views, now labelled "More" in the
  left nav). 172 px left nav with Environment / Agents / Evals, header with the wordmark, a site switcher and a
  simulation badge (`GET /api/simulation`, toggle posts as `X-Steward-Actor: operator`, labelled demo control).
  The site ID lives in `?site=` and `localStorage`; the UI always speaks the new IDs (`harbor-works`, `myer-plant`,
  `bristol-pumps`) and `lib/site.ts` routes requests to whichever ID the backend actually lists, so the twin keeps
  rendering while the backend is still on the old seed, and the nav foot says so. Every new panel degrades to
  "Not available yet: the backend has not shipped this endpoint." with Retry (404/405/501 → `not_ready`).
- **Environment**: fixture sites mount the Three.js twin exactly as before (focus strip, Reset view, Run patrol);
  splat sites mount the SuperSplat iframe from `environment.embedUrl` (`allow="fullscreen; xr-spatial-tracking"`,
  loading state fades when the frame loads, credit and `captureNote` under it, "Open on SuperSplat"). A 2-D pin layer
  sits over either viewer, positioned by each issue's normalised `pin`, labelled "pins approximate"; pins pulse once
  on hover (`animation-iteration-count: 1`), click selects the issue in the list beside the viewer and scrolls it
  into view. Under the viewer: the capture-frames strip (thumbnail, then `public/env/<siteId>/frame-1..4.jpg`,
  captioned exactly "frames rendered from the hosted capture"), then Work items / Facts / Attestations as three
  columns, then the Timeline; Reply as contractor and Owner decision (demo controls) stay in the side column.
  Records with `simulated: true` carry a small "simulated" tag (issues, transcript entries, timeline rows).
- **Agents**: four cards in level order (Operator, Atlas, Warden for the selected site, Runner) from
  `GET /api/agents`, placeholders from the addendum's names and role lines while the endpoint is missing. The
  transcript polls every 3 s while a mission is running, else 10 s, rendered as a chat log (direction by alignment,
  counterpart, kind tag, text, refs as links, `<audio>` when `audioUrl` exists). "Listen to entry" / "Listen to all" /
  "Stop" use `speechSynthesis` with a deterministic voice per agent (`lib/speech.ts`), and say so when the browser has
  none. Mission panel: "Start mission: clear site for restart" (demo control, `POST /api/missions` as operator, budget
  input), live state and steps, the restart checklist when complete, and the A2A chain Atlas → Warden → Runner as a
  vertical list with each task's state and last message derived from mission steps and `a2a` changes.
- **Evals**: runs list with passed / failed counts, run detail table (step, target, result, ms, detail), "Run demo
  workflow" and "Run mission workflow" (demo controls, `POST /api/evals/run`), polling every 3 s while a run is in
  flight; "Open in Armature" when `NEXT_PUBLIC_ARMATURE_URL` is set, else a muted line saying so.
- **Library**: `lib/types-2.ts` mirrors the addendum types; `lib/api.ts` gains every new endpoint and the
  `actorHeaders()` helper; `lib/reality.ts` gains the polling hooks and fans `a2a` changes (realtime or polled) out
  through one DOM event so mission and transcript views refresh together.
- **Copy**: no residential words remain in the dashboard or the older views ("property" → "site" in the agent chat,
  library and provider panels; the site switcher never shows the old residential seed names).

## Capture frames (honesty)

The two splat scenes are third-party captures hosted on SuperSplat, credited as the backend provides (hardcoded
credit lines point at the SuperSplat page until the backend ships `environment`). The four frames per site under
`public/env/<siteId>/` were rendered by headless Chrome (SwiftShader WebGL 2, driven over CDP with the taste skill's
`lib/cdp.mjs`) from `https://superspl.at/s?id=<id>`: wait for the viewer to load, Esc to stop the camera animation,
hide the viewer's own DOM overlays, then orbit by mouse drag and wheel between frames. Frames 1 and 2 of each site
came out that way; the third camera move stalls Chrome's input pipeline under SwiftShader every time (CDP timeout on
`Input.dispatchMouseEvent`, three attempts), so frames 3 and 4 are from the earlier pass that still showed the
viewer's control strip, centre-cropped from 800 to 690 px to remove it. They are renders of the hosted capture, never
our photographs, and the strip says so. `capture.json` next to the frames records the method per frame.

## Lint and QA

`lint.mjs` over `src/app/dash.css`, `src/components/dash`, `src/lib`, `steward-app.tsx`, the legacy panels and
`src/app/app`: 0 FAIL, 1 WARN. The legacy agent-chat and library views' `.eyebrow` lines carry `taste-skill-ignore`
(already restyled to sentence case in `legacy.css`, unchanged here). The one WARN is the legacy library's
`padStart(2, "0")` index numbering on system cards, pre-existing in a secondary view this pass only re-worded;
left as is. Mono lines carry the same comment as before.
Screenshots against the dev server on :3000 with the backend still on the old seed, so the new panels show their
not-ready states by design: `qa/dash-environment-1440.jpg` (fixture twin), `qa/dash-environment-splat-1440.jpg`
(Myer Plant Room iframe and frame strip), `qa/dash-agents-1440.jpg`, `qa/dash-evals-1440.jpg`,
`qa/dash-environment-390.jpg`. At 390 the nav becomes a row, the viewer is 48 vh, Issues follow the viewer, and the
page has no horizontal scroll (measured `scrollWidth` 390 on all three sections).

**Build:** `npm run build` green (routes `/`, `/app`, `/app/environment`, `/app/agents`, `/app/evals`,
`/llms.txt`); `tsc --noEmit` clean.

### Addendum, same evening: two approved hero changes

The user approved the site and asked for two hero changes only. (1) The beat captions over the drawing are removed
(`.caps` no longer rendered; the static SVG lost its caption line too), so the only text over the drawing is the
equipment labels. (2) A gas flow inside the pipe run: one `Points` object of 72 particles between the flanges,
sliding at one even speed (0.42 units/s), white at 0.32 opacity; and one leak at the V-504 stem: nine particles
rising 0.9 units over 3.2 s with a slight sway, fading through vertex colour toward the black ground. Two extra draw
calls, time-driven, hidden when the scene is `still`; the static frame under reduced motion is unchanged. On
phones the P-101 citation label is left-anchored at the base plate so it no longer runs off the left edge.
Re-run: `tsc --noEmit` clean, `npm run build` green, inspector at 1440 / 390 **0 FAIL, 2 WARN** (the same two,
defended above), console clean. Screenshots: `frontend/qa/site3-1440.jpg`, `frontend/qa/site3-390.jpg`; sheets in
`frontend/qa/inspect-site3/`.

### Hero gas revision, Oct 17 2026

The user asked for gas throughout the pipe network and removal of the travelling ball. The existing black and
white direction is retained; this is an animation change, with no new direction draw or page rewrite.
On this page, Harbor Works' complete pipe run becomes a transparent section through moving gas.

`hero-gas.tsx` replaces both point clouds with one volume shader: a seamless 64³ density texture, advected and
warped into wisps, sampled ten times through each equipment cross section with absorption and scattering.
The fill covers both pipe ends, all branches and suction stubs, the gauge connection, valve bonnets, both pump
chambers and the tank. Pump density swirls, the vessel mixes more slowly, and the V-504 leak expands and disperses
as a soft plume. This is an artistic gas visualization rather than a CFD model or a reading of live equipment.
The ball, halo, proof ring, travelling trail and envelope are removed. Gauge, labels and verification ticks
retain the workflow. No new dependencies, images, services or deployment are needed.

The shader changes only a time uniform per frame. Device pixel ratio is capped at 1.5, rendering still pauses
offscreen, and geometry, materials and the density texture are disposed on unmount. The SVG fallback uses the
same shared pipe bounds, filled with a stationary turbulence field, without loading the Three.js scene eagerly.

Validation: TypeScript and the production Next build pass; the build retains the existing filesystem-tracing
warning for `/llms.txt`. Scoped taste lint: **0 FAIL, 0 WARN**. The React best-practices checklist was applied to
resource cleanup, memoized texture creation, transient animation state and the dynamic scene boundary.
Browser checks used the Codex browser at 1280, 1440, 768 and 390 pixels, rather than the skill's separate browser
driver. Gas stays inside its geometry and no horizontal page overflow occurs. Switching Human → Agent → Human
unmounts and recreates the gas successfully. The SVG fallback was rendered separately and visually checked.

Scoped visual critique: design 8, usability 8, creativity 8, content 8 (**8.0/10**, subjective).
The gas is now a continuous, changing mass with depth rather than evenly spaced squares; outlines remain legible
on black. At phone width the thin pipe naturally compresses to a few pixels and the vessel carries most of the
visible texture. Existing text, controls, photographs and page composition are preserved.
Proof: `frontend/qa/gas-flow-final.png`, `gas-flow-1440.png`, `gas-flow-tablet.png`, `gas-flow-mobile.png`,
`gas-flow-reduced-motion.png` and `gas-flow-console.json`.
