# Pin placement on the two splat scans (PINS stream, 2026-10-17)

Every placed pin below was found by driving the site engineer's agent eye (`POST /api/eye/{site}/act`, actor
`myer-engineer` / `bristol-engineer`), written with `PUT /api/properties/{site}/assets/{tag}/pin {x, y, z, source: "placed"}`
(actor `operator`, the only role allowed `place_pin`), and verified with `go_to` (plus `orbit` for several) after the headless
renderer reloaded pins (it refreshes `/scene` every 20 s). Coordinates are the viewer world frame (metres).

## How the world points were obtained (read this first)

- **`mark` does not return a world point.** The renderer posts the depth-picked point as `mark: {x, y, world, hit, note}` in the
  frame body (`frontend/src/components/splat/viewer.tsx`), but the backend `FrameRequest` only accepts `annotation`
  (`backend/src/main.py`), so `mark` is dropped and every eye annotation has `world: null`. Two survey marks on Myer
  (`eya-be9d2605e97446c6`, `eya-d7f1c51abf004c19`, no issue) confirmed this. Fix: send `annotation: {world, hit, x, y}` from the
  renderer, or accept `mark` in the backend. No code was changed.
- Instead each point was **triangulated from 2 to 4 eye frames** using the `camera` returned with each frame (vertical fov 75°,
  640×400, rig yaw/pitch conventions from `camera-rig.ts`). The projection model reproduces the renderer's own `visiblePins`
  to 0.02 px mean (0.03 px max over 48 pins), so the geometry is exact; picks were made by eye on zoomed frames, or by
  patch-NCC sweeps along the ray for stereo pairs (0.3 to 0.8 m baselines). "ray miss" is the residual between the rays.
- Floors: Myer y ≈ −1.55, Bristol y ≈ 0.03 (checked by stereo on the floor).
- `go_to` and `orbit` frame the pin from the camera's *current* side at 1.8 m, so every verification and baseline depends on
  the pose before the call. Start poses are recorded below.

Verification frames are in the backend (`http://127.0.0.1:8001/api/eye/frames/<frameId>.jpg`, pin at frame centre) and, with the
pin dots drawn from `visiblePins`, in the scratchpad: `<scratch>/myer/frames/<name>_ov.jpg`, `<scratch>/bristol/frames/<name>_ov.jpg`,
one-sheet montages `<scratch>/myer/verify_all.jpg` and `<scratch>/bristol/verify_all.jpg`
(`<scratch>` = `/private/tmp/claude-501/-Users-aliuraishmirani-YC-Hackstripe/bd5a4097-1616-4efe-92a2-5c2361139e1c/scratchpad`).

## Myer Plant Room (`myer-plant`): 20 placed, 4 estimated

| tag | kind | object chosen | world point (x, y, z) | how found | verify frame | confidence |
| --- | --- | --- | --- | --- | --- | --- |
| P-101 | pump | pump set under the riser labelled **P1** (first set beside the expansion vessels), pump casing | (−4.75, −0.95, −6.43) | 3-view stereo, side views | `eyf-e3a0163683fc4d3e` (215_v_P-101), orbit 216_o_P-101_00..03 | high |
| P-102 | pump | pump set under riser **P2**, casing | (−4.90, −0.92, −5.45) | 3-view stereo | `eyf-599caeff304c48c5` (220_v_P-102), orbit 221_o | high |
| P-103 | pump | pump set under riser **P3**, casing | (−4.77, −0.91, −4.48) | 3-view stereo | `eyf-b1676378bb2647c7` (225_v_P-103), orbit 226_o | high |
| TK-201 | tank | left of the two white vertical expansion vessels at the −z end | (−6.07, −0.55, −8.62) | top lug 2-view (0.3 cm) + front face | `eyf-e67c011f3d7f4b7e` (464_v_TK-201) | high |
| TK-202 | tank | large horizontal insulated white tank behind the pump row (buffer vessel) | (−2.43, −0.50, −5.50) | surface point checked in 4 views | `eyf-87fd3fad97ac4af2` (468_v_TK-202), orbit 516_o | medium-high |
| HX-301 | exchanger | small black upright plate-pack unit on the pipework beside the expansion vessels | (−4.652, −0.826, −8.117) | 2-view (1.4 cm) | `eyf-8049aa508ab74e08` (472_v_HX-301) | medium |
| HX-302 | exchanger | bank of wall-hung continuous-flow water heaters (covers off) on the −z wall | (−2.78, 0.13, −8.06) | 3-view stereo | `eyf-b5b151a9541a42b0` (477_v_HX-302) | medium |
| DB-401 | panel | tall grey two-door electrical cabinet near the +z door | (−6.40, −0.25, 6.40) | cabinet face plane x = −6.40 from 2 views | `eyf-158c2e00dd324983` (509_v2_DB-401) | high |
| CP-402 | panel | orange control panel with lamps and HMI (mid room) | (−5.488, −0.103, 1.636) | HMI 3-view (≤ 0.7 cm) | `eyf-36b88fabd3424dac` (488_v_CP-402; panel seen edge-on) | medium-high |
| V-501 | valve | header valve row by the stair, **large handwheel** at the +x end | (−9.077, −0.242, 6.028) | 3-view (≤ 0.7 cm) | `eyf-42accf5d6fd64821` (384_v3_V-501), orbit 294_o | high |
| V-502 | valve | same row, 3rd handwheel (2nd small wheel at x −9.375 left free) | (−9.682, −0.239, 6.122) | 2-view (0.1 cm) | `eyf-d80191a380c2478f` (388_v3_V-502) | high |
| V-503 | valve | same row, 4th handwheel | (−9.941, −0.234, 6.126) | 2-view (0.1 cm) | `eyf-af0a0206b17d4924` (392_v3_V-503), orbit 302_o | high |
| V-504 | valve | same row, 5th handwheel | (−10.306, −0.231, 6.189) | 2-view (0.2 cm) | `eyf-480b555faa434b56` (396_v3_V-504) | high |
| V-505 | valve | same row, 6th handwheel (−x end) | (−10.497, −0.229, 6.173) | 2-view (0.5 cm) | `eyf-18c38a05c4ff4a71` (400_v3_V-505), orbit 310_o | high |
| PG-601 | gauge | lower pressure gauge on the P1 riser (aisle side) | (−5.59, −0.64, −6.13) | 4-view (≤ 0.9 cm) | `eyf-937b5493e87b47f0` (535_v3_PG-601) | medium-high |
| PG-602 | gauge | lower pressure gauge on the P2 riser | (−5.512, −0.607, −5.233) | 3-view (≤ 1.7 cm) | `eyf-44e3f59dc9394f14` (525_v3_PG-602) | medium-high |
| PG-603 | gauge | lower pressure gauge on the P3 riser | (−5.374, −0.634, −4.220) | 4-view (≤ 4.1 cm) | `eyf-a28111ec15e64409` (530_v3_PG-603) | medium-high |
| L-901 | light | illuminated green EXIT luminaire above the −z double door | (−8.780, 1.319, −9.366) | 2-view (0.3 cm) | `eyf-69831c58c19c46b1` (493_v_L-901) | high |
| FE-1001 | fire | red extinguisher on its wall bracket beside the +z door | (−7.999, −0.953, 8.846) | 3-view (≤ 0.3 cm) | `eyf-9cb66ca179564c32` (500_v_FE-1001) | high |
| D-1101 | door | grey double door at the +z end (door plane z ≈ 9.03) | (−6.62, −0.35, 9.00) | floor/vertical geometry | `eyf-ec50e70c3a9b43e3` (505_v_D-1101) | high |

Left **estimated** (no reuse): AHU-701 supply air duct and AHU-702 extract air duct (one foil-insulated rectangular duct is visible
at ceiling height above the vessel aisle but was not triangulated; only one duct object seen), TS-801 and TS-802 temperature
sensors (none identifiable at the scan's resolution). Other objects seen and not used: grey second panel beside the orange
panel, boilers with red burners and the Forbes-Bryan unit on the −x side, a blue vertical pressure vessel by the manifold, more
pump sets with red flanges toward +z, the −z double door (exit sign used for L-901).

## Bristol Dock Pump House (`bristol-pumps`): 12 placed, 12 estimated

Placed in the coordinator's priority order (sump, vessel, walkway, egress door, steam pumps, valves), then the obvious extras on
the third pump set; the rest were left estimated on instruction rather than searched for.

| tag | kind | object chosen | world point (x, y, z) | how found | verify frame | confidence |
| --- | --- | --- | --- | --- | --- | --- |
| SU-201 | sump | recessed slotted cast-iron grating (sump pit cover) in the floor beside No. 2 engine's bed | (2.46, 0.00, −2.70) | 3 downward views (8 to 18 cm, low texture), projection-checked in 4 | `eyf-8fb2527b34484aad` (174_v_SU-201) | medium (the pit itself is under the cover) |
| PV-301 | vessel | green vertical vessel painted **"2"** on No. 2 engine | (0.163, 1.408, −2.927) | stereo NCC 0.96 | `eyf-c5df4395ea624263` (179_v_PV-301) | medium-high |
| W-1201 | walkway | raised chequer-plate visitor walkway with handrails, through the FIRE EXIT door (+z) | (2.80, 0.08, 2.80) | stereo + floor rays | `eyf-a32fc807b7294fe1` (184_v_W-1201) | high |
| D-1101 | door | open arched outside door leaf (green diagonal boarding) on the −x wall, to the yard/dock | (−1.80, 1.30, −2.13) | stereo NCC 0.93 | `eyf-be5bcd6a29574b49` (190_v_D-1101) | medium-high (the FIRE EXIT door to the walkway is the alternative) |
| SP-101 | pump | No. 1 engine (vessel painted "1"): its flywheel half-guard | (0.78, 1.65, −6.80) | stereo NCC 0.97; engine axes parallel to No. 2 | `eyf-e271819db5a34a67` (195_v_SP-101) | medium-high |
| SP-102 | pump | No. 2 engine: its flywheel half-guard | (2.28, 1.75, −4.45) | stereo NCC 0.99 | `eyf-360104b4aeb44a7a` (200_v_SP-102) | medium-high |
| V-502 | valve | blue spring-loaded valve on top of No. 1 engine | (−1.88, 2.235, −5.53) | 2-view + stereo | `eyf-8d77167b5b354057` (205_v_V-502) | medium (real valve on engine 1; "delivery" not visible) |
| V-505 | valve | blue spring safety valve on No. 2 engine, beside vessel "2" (PV-301) | (−0.23, 2.25, −3.17) | 2-view + stereo | `eyf-37c97cfa6dfd40f4` (210_v_V-505) | medium-high |
| V-503 | valve | blue spring valve on the **third pump set** (by the walkway door) | (1.428, 2.388, −0.715) | stereo, projection-checked in 4 views | `eyf-d0f15a584c7e4d01` (225_v_V-503) | low-medium: real valve, but the register's "No. 2 engine" link does not hold |
| V-504 | valve | blue handwheel valve at the base of the third pump set (suction side) | (1.442, 0.885, −0.382) | stereo, projection-checked | `eyf-244c3fdb95c842c6` (215_v_V-504) | medium |
| PG-602 | gauge | large white-dial pressure gauge on the third pump set | (1.19, 2.252, −1.039) | stereo, projection-checked | `eyf-fa68d675c5d44bf1` (219_v_PG-602) | medium |
| P-103 | pump | third pump set body (green column under the gauge) | (1.40, 1.55, −0.70) | projection-checked in 4 views | `eyf-b0a13a74650f45e1` (222_v_P-103) | low-medium (cannot confirm it is the electric duty pump) |

Left **estimated**: V-501 main steam stop valve (no stop valve identified), PG-601 receiver gauge (other gauges exist, e.g. on
No. 1 engine and a large dial hung high, not placed), TK-202 feedwater tank and HX-302 feedwater heater (not identified),
DB-401 and CP-402 (grey electrical cabinets line the back wall; not placed), AHU-701 (orange-framed mesh louvres high on the back
wall; not placed), TS-801 and TS-802 (not identified), L-901 walkway emergency luminaire (not identified), FE-1001 (red
extinguishers stand by both doors; not placed), P-104 standby drainage pump (electric motors with red-guarded pulleys at the
far end; not placed).

## Clean valve baselines (`vision/reference/<site>/fixed`)

Captured with `vision/.venv/bin/python vision/capture.py <site> --source eye --out-root vision/reference/<site>/fixed`
(capture.py has no label flag; clean orbits carry no label because labels are only burned in for `--defect` runs).

- **Myer**: V-501 to V-505, 16 frames each at 640×400, `source: eye`, actor myer-engineer, `pinSource: placed`, `defect: none`,
  12.2 to 16.5 s per valve. Camera set to (−10.8, 0.0, 4.3) yaw 180 pitch 0 just before the run (frame `eyf-711010250c7a45ab`).
  This replaced the earlier capture-route 256 px baselines taken at estimated pins.
- **Bristol**: V-502 to V-505 (`--only V-502,V-503,V-504,V-505`), 16 frames each at 640×400, `source: eye`, actor
  bristol-engineer, 6.8 to 7.0 s per valve. Start pose (0.3, 2.4, −1.5) yaw 0 pitch −10 (frame `eyf-666c12a8dbcf402a`).
  V-501 is still estimated and has no baseline, so `jepa.py` baseline mode (which needs a baseline for every valve clip) will fall
  back to peer mode at Bristol unless V-501 is placed and captured, or the inspection run uses `--only` the same four.
- Caveats: V-502's orbit passes through the brick wall at f08 (blank frame); V-504 sits low inside the pump cage, so parts of
  its orbit are occluded. Inspection runs must also use `--source eye` (jepa refuses mixed sources or sizes) and should start
  from the same pose, because the orbit starts from the camera's current side.
