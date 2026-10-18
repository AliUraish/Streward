# Steward reference and functional QA

## Scope and visual truth

- Source video: `/Users/aliuraishmirani/Downloads/project_rec_cmv4h3aam00rio222eu8rp1ds-2026-10-11T235222.mp4`.
- Source frames: `/private/tmp/yc-video-review/frames/frame-0055.jpg` (inspection wall), `frame-0100.jpg` (source/PDF library), `frame-0107.jpg` (hierarchy), `frame-0125.jpg` (requirements), `frame-0160.jpg` (3D inspector), and `frame-0245.jpg` (external agent client).
- Implementation: `http://127.0.0.1:3000/`, captured in the Codex in-app browser. Steward is the requested project identity.
- Main comparison viewport: 960 × 640 CSS pixels, browser screenshots 960 × 640 pixels at 1× density. Source frames are 1280 × 720; the app region is cropped at `(26,61,970,661)`, yielding 944 × 600 pixels. The implementation's persistent 55px navigation is removed only in comparison boards, yielding 960 × 585. Both regions are contained at equal width inside 960 × 640 panels without stretching; surrounding broadcast chrome is excluded.
- Narrow-screen checks: 390 × 844 CSS pixels. Temporary viewport overrides are reset before handoff.

The reference scene and source repository were unavailable. The user explicitly accepted creating an original 3D room. Geometry, 24 mapped assets, original project PDFs, fictional portfolio data and Steward branding are intentional substitutions. The external reference agent client is consolidated into Steward's agent workspace; the TypeScript MCP endpoint also works with independent protocol clients. These comparisons assess the reconstructed workflow and visual language, not recovered source or an identical scan.

## Comparison history

### Initial visual comparison — blocked

Source and implementation were opened together in the combined comparison boards, including enlarged component-panel crops.

- **[P2] Workspace density.** `qa/comparison-workspace-before.png` and `qa/comparison-workspace-detail-before.png`: the initial component panel exposed about two equipment rows where the reference exposed several. Introductory controls consumed too much height; the inspector was wider than the reference. Fix: compact the 581–1080px panel frame, headings, progress area, filters and rows; reduce inspector width to 238px while preserving mobile layout.
- **[P2] Chat text contrast.** `qa/comparison-agents-before.png`: primary response text was more muted and greener than the reference's neutral light body text. Fix: use warm off-white primary text and preserve green accents.
- **[P2] Library vertical rhythm.** `qa/comparison-source-library-before.png`, `qa/comparison-requirements-before.png` and `qa/comparison-systems-before.png`: larger page headings, tabs and detail spacing reduced visible evidence/citation content. Fix: compact tablet/desktop library headers and requirement detail spacing at the reference viewport.

### Revised comparison — passed

The revised implementation was recaptured at the same 960 × 640 viewport and opened alongside the same source frames in these combined boards:

- `qa/comparison-workspace.png` and enlarged `qa/comparison-workspace-detail.png`: about five equipment rows now remain visible, the inspector is 238px wide, and the full room retains useful space between panels. The earlier density issue is resolved.
- `qa/comparison-agents.png`: primary response text is neutral off-white (`rgb(208,214,204)`) while the sidebar and accents remain green. The earlier contrast drift is resolved.
- `qa/comparison-source-library.png`, `qa/comparison-requirements.png`, and `qa/comparison-systems.png`: compact headers/tabs restore content area, and conditions, mapped component, evidence and cited source are visible together. The earlier vertical-rhythm issue is resolved.
- `qa/comparison-inspection-wall.png`: all twelve distinct rendered views and the top-down map remain visible. The source frame is an active analysis state; the final capture is idle, and `qa/inspection-complete.jpg` separately records a real completed portfolio job.

No actionable P0/P1/P2 differences remain within the agreed reconstruction scope. This is not an exact reproduction of the unavailable photographic scan, source dataset or external chat client's application chrome. The permanent navigation, property selector, original scene, record counts, project specification content and integrated agent console are expected product differences.

Focused typography evidence uses doubled crops of the same actual source/implementation panels, not replacement artwork. Browser computed style confirmed Inter was loaded, with the intended 10px chat body text at this viewport. Main layout checks found no horizontal overflow. Small reference labels and original font-face uncertainty remain minor P3 fidelity limits rather than blocked functionality.

## Required fidelity surfaces

- **Fonts and typography:** Inter is bundled locally in 400/500/600/700 weights; a compact neutral sans is a visual approximation because the reference's original CSS/font files were unavailable. Hierarchy, monospace identifiers, wrapping and small labels are compared in the enlarged crop and full-view boards. Primary chat contrast was corrected and checked in the final combined board.
- **Spacing and layout:** the olive floating inspector/list, white document library, two-column requirements/hierarchy and 4×3 inspection grid follow the reference. The density findings were fixed and recaptured; all required detail sections are now visible together at the comparison viewport.
- **Colors and tokens:** off-white library surfaces, olive/charcoal spatial panels, green verified states and pink pending markers preserve the reference palette. Steward's issue state has a distinct warm red tone. Primary text and selected rows are checked in the screenshots.
- **Image quality and assets:** the viewer is real interactive geometry, and all twelve camera cards are actual rendered views of that geometry. No room screenshot is used as a 3D substitute. The original photographic scan is an explicit scope difference. PDF pages are rendered locally from real source bytes.
- **Copy and content:** Steward branding appears in the app, accessibility labels, agent identities, PDFs, reports and MCP metadata. Counts and progress come from backend records. Source text, fixture disclosures and provider status describe the actual data/capability state.

## Functional evidence

Browser verification completed so far:

- All four views, equipment search/filtering, geometry selection, markers, clearance and navigation controls.
- Twelve different camera images, expanded image view and Escape dismissal.
- Actual inspections, portfolio coordination across three property contexts, correct completed portfolio banner, source-linked chat and persistent memory.
- Matching JSON evidence upload updated P-101 from two to three verified checks and Cedar from 76 to 77 verified records. The evidence and proposal survived the Steward migration/restart.
- A $49.99 local proposal was persisted and shown as awaiting authorization; no payment or supplier order occurred.
- PDF page navigation and zoom, requirement citations opening the cited page, and uploaded text-source ingestion/preview with correct file-format labeling.
- Property switching showed isolated conversations, counts and memory.
- Unconfigured inbox, memory and payment actions remain visibly unavailable; MCP connection information is available.
- Mobile workspace and chat remain within the 390px viewport; screenshots: `qa/mobile-workspace.png`, `qa/mobile-agents.png`.
- Fresh browser warning/error logs were empty after the Steward reload, including a reply with four citations to one document on different pages. Final logs after the clean restart and all revised navigation/citation flows contain zero warnings or errors; saved in `qa/browser-console.json`.

The MCP protocol tests and two-client demo are recorded separately in `mcp-runtime/SMOKE-RESULTS.md`. Live model/provider actions are not verified because credentials were not supplied.

## Implementation checklist

- [x] Preserve and migrate existing local records to Steward.
- [x] Verify source/PDF/evidence/inspection/agent flows.
- [x] Implement and exercise TypeScript MCP with two independent clients.
- [x] Capture and compare the revised workspace, chat and library density.
- [x] Complete final clean tests/builds and browser-console check.
- [x] Reset viewport and leave the local app open (`qa/steward-final.png`).

## Final verification and limits

- `npm test`: **24 backend tests + 1 agent mutation-scope test + 3 MCP protocol/auth tests passed**. Frontend TypeScript, production frontend build and TypeScript MCP build passed. One third-party Starlette/AnyIO deprecation warning is unrelated to application behavior.
- `npm run build:agents`: succeeded with all four explicitly local virtual-filesystem templates; no VM/cloud provider was required. No live model turn is claimed.
- Both MCP libraries passed against the restarted direct endpoint (`qa/mcp-final.json`) and the frontend `/mcp` proxy (`qa/mcp-proxy.json`). The real cross-client inspection/report demo is preserved in `mcp-runtime/SMOKE-RESULTS.md`.
- Existing evidence, records, identifiers and proposal survived migration to Steward. New source ingestion and the final source page were checked in the browser. External component links focus the correct 3D asset (`qa/component-focus.jpg`).
- Remaining limits: provider credentials and account access were not supplied; live model, external inbox/memory, payment and cloud-store operations therefore remain unverified. No external messages, live payments, supplier orders, public tunnel or cloud deployment occurred. Accessibility checks covered labels, keyboard dismissal/focus, responsive containment and reduced-motion rules; this was not an exhaustive assistive-technology audit.

final result: passed
