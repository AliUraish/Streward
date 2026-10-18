# vision/ — valve inspection pipeline

Standalone Python package (own venv, never imported by the backend) that gets a 16-frame orbit
around every pinned valve of a site, embeds each clip with **V-JEPA 2**, flags valves that changed
since their accepted-good baseline (or, without baselines, look unlike their peers), optionally asks
Claude why, and posts the results to the backend. The site
engineer agent runs inspections (REALITY-CONTRACT-4 §1): `myer-engineer` at `myer-plant`,
`bristol-engineer` at `bristol-pumps`. Results carry `inspectedBy`, and the engineer is the
`X-Steward-Actor` for the agent eye and for the results POST.

```
capture.py ──► frames/<site>/<tag>/f00..f15.jpg + meta.json + manifest.json
               (frames from the /capture route, or --source eye: the engineer's agent eye)
jepa.py    ──► results/<site>.json  (+ <site>.embeddings.npz)
explain.py ──► results/_requests/<site>__<tag>.json   (dry run, default)
               or merges {finding, evidence, confidence, recommendedAction} into results (--live)
post.py    ──► POST /api/properties/<site>/inspections/vision
run.sh     ──  all four in order
```

## Honesty note

The status is an **embedding anomaly score, not a trained defect classifier**. Each valve's clip is
compared with its own accepted-good baseline capture when every valve has one (baseline mode), or
else with the leave-one-out median of the *other valves at the same site* plus an optional labelled
reference set (peer mode). `not_fixed` means "changed since its baseline / differs from its peers
by more than the site's robust spread"; `fixed` means only "unchanged / looks like its peers", not
that the valve is sound. While pins are `estimated` the orbit may not even show the valve
(`pinWarning` in the results says so). It certifies nothing and replaces no engineer's sign-off. Frames are rendered from a third-party Gaussian-splat
capture; any defect injected with `--defect` is synthetic and recorded as `synthetic: true` in
`meta.json`, the manifest and the results file. The same wording ships in every results file
(`honesty`).

## Setup

```bash
.runtime/python/cpython-3.12.13-macos-aarch64-none/bin/python3.12 -m venv vision/.venv
vision/.venv/bin/pip install -r vision/requirements.txt     # every package pinned
```

The model weights (1.3 GB, MIT licence) download from Hugging Face on first use into
`~/.cache/huggingface/hub` (free; no token needed).

## Model

- **Id:** `facebook/vjepa2-vitl-fpc64-256` (V-JEPA 2 ViT-L/16, 300 M params, 256 px), pinned to
  Hugging Face revision `b3c1679b7c34d3255ef3547f27c7b226aefab26f`. This is the current official
  V-JEPA 2 release in `transformers` (the V-JEPA 2.1 checkpoints on the Hub are community ports).
- **Loading (model-card usage):** `AutoVideoProcessor.from_pretrained(id)` +
  `AutoModel.from_pretrained(id)` (→ `VJEPA2Model`), then
  `model.get_vision_features(processor(video, return_tensors="pt")["pixel_values_videos"])`, which
  returns the encoder's `last_hidden_state`. 16 frames × 256² → **(1, 2048, 1024)** tokens =
  8 time steps (tubelet 2) × 16 × 16 patches.
- **Device:** MPS on Apple silicon when available, else CPU (`--device`). MPS and CPU give the same
  embeddings (cosine distance 0.0 on the test clips).
- transformers 5.20.1, torch 2.14.1 (see `requirements.txt`).

## Score and threshold (`scoring.py`)

The capture route orbits the camera around the pin, so patch (t, y, x) of one clip and patch
(t, y, x) of another look at the same place relative to their pins. Every score uses that:

- **Embedding:** the (8, 16, 16, 1024) token map, each token L2-normalised; distances are per-token
  cosine distances averaged with a centred Gaussian weight (σ = 6 patches) so the area around the
  pin counts most (`--region full` weighs every patch equally).

Two modes (`--mode auto` picks baseline when it can):

- **Peer mode** (the brief's formula): score = distance to the element-wise median token map of
  the *other* valves at the site (leave-one-out) + mean distance to the k = 3 nearest clips of a
  normal label (`fixed`, `ok`, `normal`, `good`, `healthy`) in the optional reference set. Any
  reference label also votes (kNN); a valve that scores `fixed` but whose nearest reference clips
  carry a defect label becomes `uncertain`. It answers "does this valve look unlike its peers?",
  which is only meaningful when the valves' views look alike.
- **Baseline mode:** when `vision/reference/<site>/fixed/<tag>/` holds an accepted-good capture of
  **every** valve (same frame source and size), score = distance from each valve's clip to its own
  baseline: "has this valve changed since it was last known good?". Capture the baselines with
  `capture.py <site> --out-root vision/reference/<site>/fixed` (no `--defect`). The peer distance is
  still reported (`components.looPatchDistance`).

References live in `vision/reference/<site>/<label>/<clip>/` (used when the folder exists) or in a
shared `vision/reference/<label>/<clip>/`.

**Threshold** over the site's scores (both modes):

- `MAD_eff = max(1.4826 × MAD, 0.005)`; 1.4826 × MAD is the consistent σ estimate, the 0.005
  absolute floor (≈ 1 % of the real-scan peer distance) stops a collapsed MAD (three of five
  scores equal) from flagging noise.
- `threshold = max(median + 3 × MAD_eff, 1.05 × median)`: the statistical bar (Hampel identifier,
  **k = 3**, robust "three sigma") and a practical bar (at least 5 % above the median).
- `uncertainAbove = min(median + 2 × MAD_eff, threshold)` (**k = 2**).
- status: score > threshold → `not_fixed`; score > uncertainAbove → `uncertain`; else `fixed`.
  `--k` / `--k-uncertain` override k. With fewer than 3 clips (peer mode, no references) every
  valve is `uncertain`.
- The rule was revised once, after the first real-scan run: the earlier MAD floor of 10 % of the
  median (0.044 there) was ten times the real spread (MAD 0.003), and a floor scaled by the score's
  level rather than its spread is the wrong noise model. Treat the thresholds as uncalibrated until
  there is a labelled reference set.

Each valve also gets `anomalyGrid` (16 × 16 time-averaged patch distance; row 0 = top of the
256 px centre crop the processor takes) and `anomalyPeak` (where it differs most), plus the
mean-pooled embedding distance as a diagnostic (`components.pooledLooDistance`, not used for
status: on flat synthetic scenes it moved with sub-visible colour shifts, while the
position-aligned token score tracked the actual defect).

**Label strip.** The capture route stamps `synthetic defect: <kind>` in a 19 px box at the bottom
of defected frames. Left in, the model would score the label and Claude would read the answer, so
`jepa.py` and `explain.py` black out the bottom 20 px of **every** frame of **every** clip
(`common.LABEL_STRIP_PX`). The frames on disk keep the label for people. Claude is also not told
which defect was injected.

## Results file (`results/<site>.json`)

```jsonc
{
  "siteId": "myer-plant", "kind": "valve-inspection", "generatedAt": "...",
  "inspectedBy": "myer-engineer", "frameSource": "capture-route 256x256", "mode": "baseline",
  "model": {"id": "facebook/vjepa2-vitl-fpc64-256", "revision": "b3c1679b...", "device": "mps", ...},
  "threshold": {"method": "max(median + k * MAD, (1 + minEffect) * median)", "k": 3, "kUncertain": 2,
                "median": ..., "mad": ..., "madEffective": ..., "minEffect": 0.05, "statisticalBar": ...,
                "practicalBar": ..., "value": ..., "uncertainAbove": ..., "region": "...", "mode": "baseline"},
  "honesty": "Status comes from an embedding anomaly score ... not a trained defect classifier ...",
  "synthetic": true, "counts": {"fixed": 4, "not_fixed": 1, "uncertain": 0}, "pinWarning": "...",
  "timings": {"device": "mps", "modelLoadSeconds": 2.1, "perClip": [...], "meanWarmClipSeconds": 0.8},
  "valves": [{
    "assetTag": "V-503", "status": "not_fixed", "score": 0.0676, "threshold": 0.015,
    "uncertainAbove": 0.01, "model": "facebook/vjepa2-vitl-fpc64-256",
    "baseline": "vision/reference/myer-plant/fixed/V-503",
    "frames": ["vision/frames/myer-plant/V-503/f00.jpg", "..."],
    "components": {"looPatchDistance": ..., "referenceDistance": 0, "pooledLooDistance": ...},
    "anomalyPeak": {"row": 8, "col": 7, "where": "middle-centre", "value": ...},
    "anomalyGrid": [[...16 x 16...]], "reference": null, "reason": "score ... > threshold ...",
    "defect": "leak", "synthetic": true, "pin": {"x": ..., "y": ..., "z": ...},
    "frameSource": "capture-route", "inspectedBy": "myer-engineer", "pinSource": "estimated",
    "explanation": null, "explanationStatus": "dry_run",
    "explanationRequest": "vision/results/_requests/myer-plant__V-503.json"
  }]
}
```

After `explain.py --live`, `explanation` is
`{finding, evidence[], confidence: low|medium|high, recommendedAction, model, stopReason, usage, generatedAt}`.

## Claude explanation (`explain.py`)

Dry run by default: writes the exact Messages API body to `results/_requests/` and sends nothing.
The request: model `claude-opus-5-5`, 4 of the 16 frames (f00, f05, f10, f15, spread over the
arc) as base64 JPEG, the asset's register entry (from capture's `meta.json`, enriched from
`GET /api/properties/<site>/components/<id>` when the backend is reachable), the score and the
anomaly peak; `output_config.format` is a JSON schema for
`{finding, evidence, confidence, recommendedAction}`, `effort: high`. It is sent through
`client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", ...)`
so a policy decline is retried server-side on Anthropic's default fallback model; a final
`stop_reason: "refusal"` is recorded as `explanationStatus: "refused"`. `--live` reads
`ANTHROPIC_API_KEY` from the environment or the repo-root `.env` and fails before sending anything
if neither has it (the root `.env` had no `ANTHROPIC_API_KEY` on 2026-10-17).

## Commands

```bash
# one-off: accepted-good baselines for every valve (enables baseline mode for later runs)
vision/.venv/bin/python vision/capture.py myer-plant --out-root vision/reference/myer-plant/fixed

# full pipeline (frontend on 3000 serving /capture, backend on 8001 with 3-D pins)
vision/run.sh myer-plant --defect V-503=leak                  # explain stays a dry run
vision/run.sh myer-plant --defect V-503=leak --source eye     # frames from myer-engineer's agent eye
vision/run.sh myer-plant --defect V-503=leak --live-explain   # paid: sends flagged valves to Claude

# steps
vision/.venv/bin/python vision/capture.py myer-plant --defect V-503=leak [--source capture|eye] [--renderer auto|gpu|swiftshader] [--base http://127.0.0.1:3000] [--backend http://127.0.0.1:8001]
vision/.venv/bin/python vision/jepa.py myer-plant [--mode auto|peer|baseline] [--k 3 --k-uncertain 2 --device auto --region centre] [--inspected-by myer-engineer]
vision/.venv/bin/python vision/explain.py myer-plant [--live]
vision/.venv/bin/python vision/post.py myer-plant

# capture with pins from a file instead of the backend (offline override), e.g. the backend's own
# estimated pins while the running backend still serves 2-D pins:
(cd backend/src && python3 -I -c "import importlib.util as u, json; s=u.spec_from_file_location('r', 'registers.py'); \
  m=u.module_from_spec(s); s.loader.exec_module(m); json.dump({'assets': m.register_for('myer-plant')}, open('../../vision/myer-pins.json', 'w'))")
vision/run.sh myer-plant --source eye --defect V-503=leak --assets-file vision/myer-pins.json

# tests (no browser/backend/API needed; Chrome test runs if Chrome is installed)
vision/.venv/bin/python -m unittest discover -s vision/tests -v
VISION_TEST_MODEL=1 vision/.venv/bin/python -m unittest discover -s vision/tests -v   # + real V-JEPA 2

# fixture with the real model
vision/.venv/bin/python vision/fixtures/make_fixture.py
vision/.venv/bin/python vision/jepa.py fixture --frames-root vision/fixtures/clips --out vision/results/fixture.json
```

### Frame sources (`capture.py --source`)

`capture.py` reads `GET /api/properties/<site>/scene` (contract 3) and falls back to
`/components`; it keeps assets of kind `valve` with a 3-D `pin {x, y, z}` (or `[x, y, z]`) and
exits with a clear message when only 2-D pins exist (`--assets-file` takes the asset list from a
JSON file instead, for offline runs). One source per run, so the valves stay comparable:

- **`capture` (default)**: the frontend's `/capture?site=&asset=&frames=16&defect=&pos=x,y,z`
  route in our own headless Chrome (`--headless=new`, temporary profile). `--renderer auto`
  (default) starts it with ANGLE Metal (`--use-angle=metal`) and falls back to SwiftShader
  (`--use-angle=swiftshader --enable-unsafe-swiftshader`) when that gives no WebGL context;
  `--renderer swiftshader` forces SwiftShader (see the timings below for why it is not the default),
  driven over CDP by a small `websockets` client (`cdp.py`): wait for `window.__done`, read
  `window.__frames` (256 × 256 JPEG data URLs) and `window.__capture` (pin used, arc, radius,
  probe, timings), stop the Chrome we started by PID. The pin always goes along as `pos` (the
  route prefers its own backend lookup and falls back to `pos`). A `window.__error` from the route
  is reported verbatim.
- **`eye`**: the site engineer's own agent eye (REALITY-CONTRACT-4 §2):
  `POST <backend>/api/eye/<site>/act {action: "orbit", params: {assetTag, frames: 16}}` with
  `X-Steward-Actor: myer-engineer` (or `bristol-engineer`; `--actor` overrides), then each returned
  frame is downloaded from its `frameUrl` (or `/api/eye/frames/<frameId>.jpg`, or inline
  `jpegBase64`). `--defect` is passed as `params.defect`. If the eye answers **404 on the first
  valve**, the whole run falls back to the `/capture` route; a 404 after earlier valves succeeded
  is an error rather than a mixed-source site.

Every clip's `meta.json` records `source` (`capture-route` | `eye`), `requestedBy`, the frame
size, `synthetic`, and `defectConfirmed` (whether the source echoed the synthetic edit back;
`synthetic: true` is recorded whenever a defect was requested, confirmed or not). `jepa.py`
refuses to score a site whose clips mix sources or frame sizes (`--allow-mixed` overrides).
`post.py` sends `X-Steward-Actor: <inspectedBy>` and exits 3 when the backend ingest route does not
exist yet.

## Tests and timings (Apple M4, 24 GB, 2026-10-17)

**Model (V-JEPA 2 ViT-L, 16 frames per clip):**

| | load | first clip | warm clip |
| --- | --- | --- | --- |
| MPS (default) | 2.0–2.2 s | 1.6–2.2 s | **0.79–0.87 s** |
| CPU (`--device cpu`) | — | 2.8 s | 1.6–1.7 s |

First download of the weights: 80 s (1.30 GB). MPS and CPU embeddings are identical (cosine
distance 0.0), and repeated runs are deterministic.

**Fixture (`fixtures/make_fixture.py`, 6 numpy clips: five solid-colour peers, one full-noise
outlier FX-06), peer mode:** with V-JEPA 2 on MPS, FX-06 scores 0.455 against threshold 0.303
(median 0.281 + 3 × MAD_eff 0.0073) → `not_fixed`; FX-01..05 score 0.274–0.291 → `fixed`. With
the model-free pixel baseline the same split holds (0.033 vs threshold 0.016). Results:
`results/fixture.json`, `results/fixture.pixel.json`. Warm clip time is 0.8 s on an idle GPU and
1.1–1.4 s while Chrome shares it.

**Plumbing tests (`tests/`, 24 tests, ~25 s; ~45 s with `VISION_TEST_MODEL=1`):** scoring and
threshold rules (including the real-scan numbers below); baseline mode; fixture → jepa → explain (dry run writes the request, nothing sent) → explain
`--live` against a local mock of the Messages API (`ANTHROPIC_BASE_URL`, fake key, no network) →
POST with `X-Steward-Actor`; 2-D pins fail clearly; mixed frame sources are refused; real headless
Chrome over CDP against a mock `/capture` page (5 valves × 16 frames, one synthetic leak);
`--source eye` against a mock agent eye (actor header, orbit body, 640 × 400 downloads, defect
echo); eye 404 → fallback to `/capture`. With the model on, V-JEPA 2 flags the synthetic leak,
corrosion and missing handwheel on the mock renders (MV-503 0.17–0.24 vs threshold ~0.10).

**Renderer on the real scan (Myer, 14.16 M gaussians, 256 px orbit around an estimated pin):**

| Chrome WebGL | scan download → first frame | 12-direction line-of-sight probe | 16 frames | total per valve |
| --- | --- | --- | --- | --- |
| ANGLE Metal (`--renderer gpu`, the `auto` default) | 3.3 s → 3.9 s | 9.2 s | 7.2 s (sort ≈ 250 ms) | **≈ 21 s** |
| SwiftShader (`--renderer swiftshader`) | ≈ 6 min to first frame | not finished after 5 min more | — | **> 11.5 min, stopped** |

SwiftShader works for small scenes (the mock page renders in ≈ 1 s per valve) but not for this
scan, so `--renderer auto` (default) uses the GPU and keeps SwiftShader as the fallback when the
GPU gives no WebGL context, matching REALITY-CONTRACT-4 §2.

**End-to-end on the real Myer scan (2026-10-17, 21:40 PDT).** Command:

```bash
vision/run.sh myer-plant --source eye --defect V-503=leak --assets-file <estimated pins>
```

- *capture* (151 s for the whole pipeline): the eye endpoint on 8001 answered 404, so the run
  fell back to `/capture`; Chrome 155 headless, WebGL `ANGLE Metal Renderer: Apple M4`; V-501
  26.1 s, V-502 22.4 s, V-503 (synthetic leak, echoed by the route) 32.1 s, V-504 23.8 s, V-505
  32.9 s. The running backend on 8001 still serves 2-D pins, so the pins came from
  `--assets-file`: the backend's own estimated pins (`registers.register_for`), which the current
  backend code's `/scene` returns verbatim (checked in-process against a scratch data dir).
- *peer mode:* V-503 scores highest (0.479; others 0.427–0.441). With the first threshold rule it
  stayed `fixed` (threshold 0.569); with the revised rule it is `not_fixed` (threshold 0.460). **A
  control re-capture of V-503 without the leak scores 0.477 and is flagged too**: on estimated pins
  the peer flag comes from V-503's location looking different, not from the leak (the leak moves V-503
  only 0.068 from its own clean render, the location spread is ~0.44).
- *baseline mode* (clean baselines of all five valves in `reference/myer-plant/fixed/`, 26–39 s
  each): re-renders are bit-identical (score 0.0000 for the four untouched valves); V-503 with the
  leak scores **0.0676 → `not_fixed`** (threshold 0.015, peak middle-centre where the edit is); the
  clean control V-503 scores 0.0000 → `fixed`. This is the result in `results/myer-plant.json`
  (`mode: baseline`, `inspectedBy: myer-engineer`, `synthetic: true`, `pinWarning` set).
- *explain:* dry run; `results/_requests/myer-plant__V-503.json` (4 masked frames, 88 KB body).
  Nothing was sent.
- *post:* 8001 answered 404 (the running backend predates the ingest route; exit 3, results kept).
  The current backend code, run in-process with a scratch data dir, accepted the same file:
  201, 5 findings, 1 issue `iss-vision-my-v-503`, only V-503 marked synthetic.
