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

### Factory pipework detail, Oct 18 2026

The user approved the gas and asked for a more detailed factory appearance. The existing monochrome direction
is retained, with no direction redraw. Harbor Works' mechanical hardware becomes the subject of the elevation:
bolted flanges and gasket plates, weld seams and outer pipe walls, reinforced tees, cast valve bodies with
bonnets and threaded yokes, five-spoke handwheels, graduated gauges with isolation fittings, finned motors with
terminal boxes, casing studs, anchored pump skids, vessel bands, sight-glass graduations and braced vessel legs.
A quiet secondary layer adds steel pipe-rack columns, threaded hangers, clamps, electrical raceway and cable tray.

The gas shader, density texture, flow parameters and shared gas interior dimensions are unchanged. Verified shader
SHA-256 before and after: `0169baa78690a190a58582c7486675ae1ccff6d44d410bd2ee30fe2e01cd2b9f`.
No extra equipment readings or operating claims are introduced. The additional surfaces are line geometry.
Three merged line batches provide 974 equipment segments, 494 detail segments and 164 rack/support segments.
The two additional batches are memoized and disposed with the scene; the background rack hides below 640px and
fine detail becomes lighter on phones. The SVG shares every mechanical shape and follows the same responsive rule.
The tablet gauge label now stays inside the left edge.

Validation: TypeScript and the final Next production build pass, retaining the pre-existing `/llms.txt`
filesystem-tracing warning. Scoped taste lint: **0 FAIL, 0 WARN**. All generated line coordinates are finite.
The React checklist covers stable geometry allocation, cleanup and the absence of new per-frame mesh creation.
CUA screenshots at 1280, 1440, 768 and 390 pixels show the fittings, preserved gas and no horizontal page overflow;
the SVG fallback was separately rendered and visually checked. The skill's external browser driver was not used.

Scoped visual critique: design 8.5, usability 8, creativity 8, content 8 (**8.2/10**, subjective). The denser
mechanical silhouettes now read as factory equipment; the darker rack gives depth while the gas remains the
brightest moving element. At phone width hardware details naturally compress; removing the rack at that width
keeps the main equipment and gas legible. The original page copy, navigation, buttons and photographs remain.
Proof: `frontend/qa/factory-pipes-before.png`, `factory-pipes-final.png`, `factory-pipes-1440.png`,
`factory-pipes-tablet.png`, `factory-pipes-mobile.png`, `factory-pipes-reduced-motion.png`, `factory-pipes-console.json`.

---

# Dashboard, Oct 17 2026 (late night): two factory worlds, the agent eye, mission view, agent mode

Dashboard stream for REALITY-CONTRACT-3.md and REALITY-CONTRACT-4.md (contract 4 wins). It replaces the phase-2 route
group and the one-page phase-3 draft. The home page (`components/site/**`, `app/page.tsx`) is untouched; the splat
viewer (`components/splat/**`) and `/capture`, `/eye` belong to the VIEWER stream and are only mounted. The old
Inspection wall, Library, Agent chat and the hand-built Three.js twin stay on disk (`components/steward-app.tsx`,
`components/dash/**`, `components/scene/**`) and are mounted nowhere.

## Decisions

- **Ground, ink, one signal.** Black ground, `#ededed` ink, tone steps `#0a0a0a` → `#333`. White marks what is
  verified, ok or active (selected nav item, the active tab, the acting agent, a passing step). One warm red,
  `--issue #ff6a5c`, is the only hue and is reserved for what is wrong: high severity, overdue, blocked, failed,
  not fixed, out of spec. Medium severity and "due soon" are a mid grey square. Marks are 8 px filled squares.
- **Type.** Geist Sans; five working sizes, 44 figures, 30 page titles, 20 panel heads, 16 text, 13 small (17 for the
  wordmark as on the home page; 12 inside the mission-view HUD and chart ticks). Geist Mono appears in two places only:
  the agent-view stream, which is literally tool-call and A2A traffic, and asset tags and record ids in the mission
  HUD (`<code>`), each marked `taste-skill-ignore`.
- **Controls are the home page's.** The white button with the `#333` fill sliding in from the left, difference-blended
  words, press scale and arrow nudge; the factory switch (Myer · Bristol) and the Human · Agent switch reuse the home
  page's gliding white knob. Tabs mark the selected item with a white fill.
- **Structure (contract 4 §8).** A 236 px sidebar: factory switch, the selected factory's pages (Overview, Metrics,
  Environment, Team, Compliance, Maintenance), the portfolio pages (Portfolio, Agents map, Conversations, Evals), the
  Human · Agent switch and a live mark. Below 1024 px it becomes a bar with the factory switch and a Menu. Routes:
  `/app`, `/app/[site]` (+ `metrics`, `environment`, `team`, `compliance`, `maintenance`; `dynamicParams = false`,
  only the two sites), `/app/agents`, `/app/conversations`, `/app/evals`, `/app/agent-view`; `/app/environment` redirects
  to `/app/myer-plant/environment`.
- **Agent names everywhere are contract 4 §1's.** Retired ids (atlas, warden:*, counsel, runner) map to the new
  names in `lib/sites-3.ts`; record text written before the migration is shown with the new names (`rn()`), and
  1:1 retired ids (atlas → director, warden:<site> → <site>-engineer) are read as a fallback while a store migrates.
- **Charts** (`components/dash3/charts.tsx`, inline SVG, measured to the container so text is never scaled): one
  axis, no grid lines, the spec band as a tone step behind the line, out-of-spec segments in the issue signal,
  series told apart by tone and dash with a legend and direct end labels pushed apart so they never collide, a hover
  readout that also works with the arrow keys, an `aria-label` summary and the numbers in a screen-reader table.
  Bars for tokens and tool calls per agent and suite pass rates; columns for A2A messages per day; sparklines on the
  factory overview. Black and white; source line "Steward telemetry, also delivered to Armature".
- **Agent mode** dissolves the page with the home page's technique (deterministic scatter offsets, 460 to 520 ms,
  staggered, transform and opacity only), routes to `/app/agent-view`, and coming back the page mounts scattered and
  glides home; reduced motion makes both instant. The agent view is a HUD, not a document: the latest eye frame per
  factory with the visible tags placed where the renderer projected them, a stream of tool calls, eye moves and A2A
  messages typing in, a pulsing agent map and token meters.
- **Mission view** (Environment, "Mission view", `?mission=1`, Esc or Exit to leave). The viewer's container becomes a
  fixed full-window host (Fullscreen API when allowed) and the same viewer instance keeps running with `fill` and a
  `safeArea` matching the panels, so the 3-D dots stay visible and the camera keeps following eye commands. Panels at
  90 percent tone, no blur, no shadow, each collapsible, and Hide HUD (key `h`): Agent cameras (3 × 2 latest eye frames,
  "Site Engineer · V-501", "2 assets · 1 issue", the issue tile outlined in the signal; capture renders labelled as
  such until the eye looks), Evals per version (v1 before the director's first reconfigure, v2 after, derived from
  eval runs and telemetry split at that moment until `/api/evals/metrics` sends per-version rows; best value per row in
  white, regressions marked), Changes to the next version (the director's reconfigures with measured token effect and
  accepted or rejected), Alerts (open issues and notices with severity, site time, who raised them and the regulation
  cited; a click turns the camera), the Inkbox team graph (the pair talking now in white, the acting node filled) and
  one live line. It leads with what is ours: the last signed proof (attestation id, Ed25519), the regulation cited,
  the Inkbox team; it copies nothing from the reference image.
- **Regulations, licensing.** England (Open Government Licence, `servePdf: true`) is embedded from
  `/api/regulations/{id}/file` at its page with "Contains public sector information licensed under the Open Government
  Licence v3.0." under it. Victoria (`servePdf: false`) is never embedded: provision, our summary, version and "Open the
  official PDF" at `#page=<pageHint>`, with "Victorian legislation, personal use only; opened from
  legislation.vic.gov.au". The VBA practice note is also linked only, with a note naming its own host
  (bpc.vic.gov.au), because "opened from legislation.vic.gov.au" would be untrue for it. Bristol's pages say England
  (ENG-UK), Myer's say Victoria, Australia (VIC-AU), and "Demo rule pack, not legal advice." stays on the page. Until
  `/api/regulations` answers, the records come from `backend/seed/regulations/regulations.json` (real sources, our
  summaries), labelled as the repository's rule pack.
- **Honesty labels.** Every synthetic record carries a "synthetic" tag; every control that starts something carries
  "demo control" ("operator tool" for pin placement); Listen says "voiced by your browser's text-to-speech"; calls are
  described as Inkbox A2A conversations, never phone calls.
- **Degraded states.** Every panel shows "Not available yet" with Retry on 404/405/501 and polls slower (20 s) while an
  endpoint is missing. Polling is the baseline; `lib/live-3.ts` is the seam for the SUPABASE stream's
  `lib/realtime` (one channel per site per tab via a single bridge in the shell, closed when the tab hides). Until it
  lands the bridge is a no-op and views poll (eye feed 2 to 3 s, overview 3 s).

## API used (lib/api-3.ts, normalised to lib/types-3.ts)

overview, agents (+ activity, memory, config, transcript, send-document), scenarios (+ start, scenario-runs),
board-meetings, properties/{id}/scene, assets/{tag}/pin (PUT), viewer (GET since, POST), issues (+ issue, assign, fix),
fix-workflows, inspections/vision (+ frames), crew, responsible, obligations (+ request-document), documents
(+ file), notices, document-emails, notifications, maintenance, regulations (+ file), metrics, metrics/summary,
evals (+ run, findings, metrics), conversations, eye/{site}/feed, eye/frames/{id}.jpg, waits, a2a/tasks.

## QA (Oct 17 2026, against 127.0.0.1:3000 with the new backend on 8001)

- `tsc --noEmit` clean; `npm run build` from the repo root green (24 routes; the only warning is the existing
  `/llms.txt` filesystem trace).
- Taste lint over `components/dash3`, `lib`, `app/app`: **0 FAIL, 0 WARN**.
- Inspector, 1440 and 390: portfolio and factory overview **2 FAIL** (few-pictures, focal-point), agent view **2 FAIL**
  (same two, `--allow mono`), metrics **2 FAIL** (same two). Defended: both are landing-page rules and the brief
  exempts app screens from the photography and headline rules. WARNs card-rows (dense rows of records are the content
  of an app screen), no-footage (no honest clip of these plants exists), blend-text (difference-blended words only over
  white, `#333` or black). Fixed in the loop: small captions read as eyebrows above KPI figures and sparkline values
  (captions moved under the figures), a wrapped issue row at 390, screen-reader tables widening the phone viewport,
  long agent names truncated on the map, 13 px running text (raised to 16), chart legends scaled by a global SVG rule.
- No horizontal scroll at 390 on any page (measured `scrollWidth` 390).
- Screenshots in `frontend/qa/`: `dash4-<page>-1440.jpg` for every page against the live backend,
  `dash4-portfolio-390.jpg`, `dash4-agent-view-390.jpg`, `mission-myer-1440.jpg`, `mission-bristol-1440.jpg`,
  `dash4-mode-dissolve-1440.jpg` (mid-dissolve), and `dash4-seeded-*.jpg`, `mission-*-seeded-1440.jpg` taken with the
  page on :3000 but `/api/*` answered by an isolated copy of the current backend (temp data dir, every provider
  variable cleared, workers off, port 8031 because 8012 and 8022 were in use by other streams) after playing every
  scenario, one fix workflow and two eye frames, so the data states can be seen without touching the live stack.
  The older names `dash3-{overview,factories,people,compliance,agents,evals}-1440.jpg` and `dash3-390.jpg` are copies
  mapped to Portfolio, Environment, Team, Compliance, Agents map and Evals.

---

# Dashboard, Oct 18 2026: the third site, the Tool Forge, the California comparison, realtime

Streams DASH-5 and DASH-6 (REALITY-CONTRACT-5.md, REALITY-CONTRACT-6.md and the coordinator's additions). Same language
as the late-night section above: black ground, tone steps, one issue signal, Geist, mono only for identifiers.

- **Tomioka Silk Mill (`tomioka-mill`) is a first-class site.** `lib/sites-3.ts` carries it (with `jaName`, a site
  line, `credit`, `scanNote`, `tz`, its KPI set and metric series, and `valves: false`), the Tomioka team with the
  contract's names (Site Manager, Conservation Engineer, Compliance Officer, Field Technician · Tomioka) and the
  tm-humidity, tm-alteration-permit and x-heritage scenarios. The factory switch has three stops (the knob is a
  third of the track, `--k` of `--n`, focus follows arrows, Home and End); on phones it fits beside Menu. Portfolio:
  three tiles, three-site averages (the note says pressure, flow and uptime come from the two pumped sites, and names
  any site the summary does not cover yet), three team columns. The agents map has three clusters (manager on top,
  engineer and technician, compliance at the foot) so manager-to-manager and compliance-to-compliance lines run
  straight between clusters; 15 seats. Agent view: three eyes across the top. Mission view: Tokyo time, Bristol as
  the mill's peer. Maintenance: windows say whom they are shared with (x-heritage: Tomioka and Bristol).
- **Japanese text.** Geist has no Japanese glyphs, so only Japanese runs (`JaText`, `SiteTitle`: 富岡製糸場 beside the
  English name, law titles, article numbers such as 第43条, the 出典 line) carry `lang="ja"` and `.ja`: Geist, then
  Hiragino Sans, Hiragino Kaku Gothic ProN, Yu Gothic, Meiryo, Noto Sans JP.
- **Mill figures.** KPIs average humidity (signal outside 40 to 65 %), visitors over 24 h (the integral of the
  per-hour rate) and the widest crack (signal above 0.3 mm), taken from the summary when it carries them, else from
  the site's own series. Metrics shows the site's series with spec bands, then any further series the backend sends.
- **Regulations.** Jurisdictions are explicit (myer-plant VIC-AU, bristol-pumps ENG-UK, tomioka-mill JP, "Japan (JP)").
  One licence rule: servePdf true embeds the cached PDF with the record's own attribution under it (England: the OGL
  line; Japan: the part of `licence` after "Attribution:", the e-Gov 出典 line with PDL1.0, the English source and the
  note that the summaries are ours, with working links), never the OGL line for Japan; servePdf false links "Open the
  official PDF" or "Open the official source" with the licence note.
- **California (US-CA) comparison.** Binding law first, always. A separate panel, "If this site were in California",
  lists the US-CA records (`comparisonRegulationIds`, `GET /api/regulations?siteId=&include=comparison`, else the
  rule pack), each tagged "comparison, not binding here", same embed-or-link rule; each compliance issue has its own
  separated block. Comparison records never count as a site's law (mission alerts, citations). "Demo rule pack, not
  legal advice." stays on the page and on the panel. No US-CA records exist yet, so the panel shows its empty state.
- **Tools (contract 6).** `/app/[site]/tools` and `/app/tools`: the list beside one tool; the tool shows who built it
  and when, who asked, why (task, gap, tools considered and why not), the lifecycle as a step row, inputs and output,
  the recipe as numbered steps (readable op names, template references set apart), the test (sample input and output),
  approval or refusal, usage (calls, tokens saved, calls per day) and history. "Ask the team for a new tool" (demo
  control: pick the agent, type the task, or use the contract's demo task) follows the lifecycle live: request, draft,
  validate, test, approve, publish, one endpoint at a time; approval is sent as the approver the contract names (the
  site's manager for read-only tools); a tool that writes stops for the Operations Director with Approve and Refuse.
  Forged tools also show on each agent's page. Mono here is limited to tool names, op names and template references.
  Until `GET /api/tools` answers, the contract's two demo tools appear as labelled contract drafts, with only the
  contract's words (task, gap, inputs, output shape) and no recipe, test, approval or usage.
- **Realtime.** `HudBridge` (`lib/live-3.ts`) subscribes once, for the shell's current site, to
  `useHudChannel` and `useSitePresence` (viewer, or renderer on that site's environment page); new events go out on
  the bus once; presence feeds the mission top bar ("N watching · eye renderer online · realtime", else the eye feed's
  renderer list and "polling"). Polling stays the baseline. Signed eye-frame URLs are kept per frame id for 10 minutes
  so polls stop restarting image loads; a frame that no longer loads falls back to the capture thumbnail.

QA (dev server on :3000, backend on 8001, which does not serve the mill or `/api/tools` yet, so those panels show their
"Not available yet" states): `tsc --noEmit` clean; `npm run build` green (every site page, including Tools, for the
three sites; the only warning is the existing `/llms.txt` trace); taste lint over `components/dash3`, `lib`, `app/app`
0 FAIL, 0 WARN; no horizontal scroll at 390 or 1100 (portfolio, tools, agents map, mill compliance, agent view).
Screenshots: `qa/dash5-portfolio-1440.jpg`, `dash5-tomioka-1440.jpg`, `dash5-tomioka-environment-1440.jpg` (the mill's
streamed scan in the viewer), `dash5-agents-1440.jpg`, `dash6-tools-myer-1440.jpg`, `dash6-tools-bristol-1440.jpg`,
`dash6-tool-detail-1440.jpg`; `dash6-tool-detail-fixture-1440.jpg` is the detail rendered with `/api/tools` answered by a
contract-shaped fixture through CDP request interception (QA only, labelled FIXTURE in its text), to exercise the recipe,
test, approval, usage and published controls before the backend ships them.
