# Technical ideas — things a human does, an agent can't, and after this weekend can
(Companion to IDEAS.md. Same event facts and tracks apply. Hardware notes at the bottom.)

## The pattern that unlocks all of these
Coding agents got good because they have a loop: write code → run tests → read structured failure → fix. Robotics, hardware, and debugging have no such loop for agents. Every existing "robot MCP" or "simulator MCP" hands the LLM a GUI-shaped toolset (65 MuJoCo tools, step-the-sim, look at a screenshot) and makes the LLM the control loop at 1 Hz. That is a human interface translated to JSON, not an agent interface. YC's own thesis line is "AX, not UX". The technical opportunity is: **give agents the test-driven loop for the physical and runtime world, and keep the LLM out of the fast path.**

Evidence the fast/slow split is the right cut: VLA control runs 1–10 Hz, stable manipulation needs >50 Hz (UniFS, arXiv 2606.22794); LLM inference dominates end-to-end latency at ~250 ms (DaDu-Corki, arXiv 2407.04292); ICML-2026 TIC-VLA explicitly separates reasoning from control. Practitioner consensus: slow tier 1–10 Hz, fast tier 100–1000 Hz, the slow tier should hand off intent, never close the loop.

---

## ★ 1. REFLEX — test-driven control: controllers as code, the simulator as the test runner
**Human does / agent can't:** A human has reflexes and deliberation. They catch the falling cup without thinking, then decide what to do next. An agent thinks at 1 Hz and therefore cannot safely control anything that moves. Today a human writes the controller, tunes PID by feel, and watches the plot.

**What exists:** MuJoCo/Isaac/Genesis MCP servers that expose sim internals as dozens of tools and have the LLM step the physics (glama.ai mujoco-mcp-server, omni-mcp/isaac-sim-mcp). Code-as-Policies (Google, 2022) had the LLM write robot code once, with no verification loop. Nothing exposes "compile a fast policy, run it against a physics harness, get a structured failure report, deploy with a safety envelope" as a tool.

**Build (one MCP server, four tools):**
- `propose_controller(code, lang=py|c|rust, task_id)` → compiles and runs the controller at 1 kHz inside MuJoCo in a **Blaxel sandbox** (headless, batch jobs for N seeds in parallel). The LLM never sees frames. It gets back a **failure report built like a test failure**: time-to-violation, which constraint tripped (joint limit, torque sat, tip-over angle, contact force), min stability margin, a 20-line downsampled phase trace, and an auto-generated PNG plot only if it asks (`fidelity="plot"`). Tokens per iteration: ~300 instead of ~30k for video.
- `sysid(experiment)` → runs step/chirp inputs in sim or on hardware, returns identified mass/friction/latency so the agent can calibrate sim to real. (Humans tune by feel; agents can't.)
- `deploy(controller_id, target=sim|esp32|realtime_proc, envelope={max_torque, max_vel, kill_angle})` → flashes the same C controller to a microcontroller or runs it as a realtime process. The **envelope is enforced by a watchdog the agent cannot edit**, so the agent proposes, the harness guarantees.
- `supervise(controller_id)` → the slow loop. The agent subscribes to events (violation, task done, stuck) rather than polling, and may hot-swap controllers between episodes.

**Demo (no hardware needed):** Task: "balance the Unitree Go2 on a tilting plate" or "swing up and balance a cart-pole" in MuJoCo (menagerie models). Claude writes a controller, gets a failure report ("tipped at t=1.42s, pitch 31°, torque saturated on FR_hip"), iterates 4 times live, passes 50 randomized seeds in parallel on Blaxel, and the rendered video plays only at the end as proof. **With hardware:** deploy the same controller to a $25 reaction-wheel pendulum or a self-balancing bot on an ESP32 and let a judge poke it.

**Tracks:** Manufact (an MCP server where the agent is the customer, end-to-end novel task) + Blaxel (sandboxes running physics at 1 kHz, batch seeds; and "a 1 kHz numeric trace is something a human would never want") + Armature (AX: the whole design is token-first).
**Why it wins:** It is the event thesis applied to the one domain where UX-shaped tools fail hardest. Judges have not seen a controller test-runner. It produces an asset (passing controllers + sysid'd models) and the Browser-Brawl-style loop (randomized seeds as adversary).
**Risks:** MuJoCo build in sandbox (pip wheel exists, fine). Hot-reloading C at 1 kHz — use Python+numba or compile to a shared object. Scope the task to one robot model.

---

## ★ 2. WORLDVIEW — a queryable world model instead of pixels
**Human does / agent can't:** A human glances at a table and knows where things are, what moved, and what is reachable. Agents get a JPEG, burn thousands of tokens, and are bad at metric 3D (VLM spatial reasoning is still poor; every robot MCP sends images and warns about image token cost).

**What exists:** Research only. ConceptGraphs (open-vocab 3D scene graphs → JSON per object with 3D bbox), Hi-Dyna Graph, MoMa-LLM. **No shipped MCP/tool exposes scene-graph queries** (search returned none).

**Build:** A perception daemon (webcam or iPhone LiDAR / RealSense; monocular fallback with Depth Anything) running open-vocab detection + segmentation + depth → a live scene graph. MCP tools:
- `query_scene("red cup")` → {pose_xyz, bbox, on: "table", left_of: "laptop", reachable: true, confidence}
- `diff_scene(since=t)` → what moved, appeared, disappeared (humans notice change for free)
- `await_change(predicate="cup is empty" | "door opens", timeout)` → event-driven wake (no polling, no frames)
- `snapshot(fidelity=graph|crop|full)` → agent chooses how many tokens to spend. Default is the graph.

**Demo:** Point a webcam at the judging table. Agent is asked "tell me when someone picks up the Stripe sticker and where it goes." Zero frames in context; it answers from `await_change` + `query_scene` and shows the token meter next to a baseline that streams screenshots.
**Tracks:** Manufact + Armature. Add Blaxel if inference runs in sandbox.
**Stacks with REFLEX:** perceive (WORLDVIEW) → plan (LLM) → act (REFLEX fast policy). Together it is a full agent-native robot stack, built in 24h, with the LLM nowhere in the fast path.
**Risks:** Depth quality from a webcam; use relative poses and the graph (relations), not absolute mm. Pre-pick 10 objects.

---

## ★ 3. REWIND — time-travel debugging as a single tool call (software only)
**Human does / agent can't:** A senior engineer records a failing run once, then asks "when did `balance` go negative?" and reverse-steps to the exact line. Agents add print statements, re-run, and burn 30 turns; flaky bugs defeat them entirely because they cannot reproduce.

**What exists:** Many live-debugger MCPs over DAP (gdb-mcp, mcp-debugger, aidb, DotnetDebugger.Mcp). **None do record/replay or reverse execution** (search: "none mention rr, reverse execution, record-and-replay").

**Build:** MCP server on top of **rr** (Linux, runs in a Blaxel sandbox) and Python's equivalent (`sys.settrace`/`PyTrace` or `revdb`):
- `record(cmd)` → deterministic trace; flaky bug captured once.
- `when_did(expr, condition)` → binary-searches the recording with hardware watchpoints + reverse-continue, returns the exact instruction, stack, and locals at the mutation. One call replaces a 30-turn print-debug session.
- `timeline(var)` → compressed table of every value change with stack hashes (deduped), ~200 tokens.
- `replay_to(event_id)` then standard DAP inspection, all reversible.
- `diff_runs(trace_a, trace_b)` → first divergence between a passing and failing recording (humans do this by eye in Pernosco).

**Demo:** A seeded race-condition bug in a Rust or C++ service that fails 1 in 20 runs. Baseline Claude Code flails for 5 minutes. With REWIND: `record` in a loop until failure (sandbox batch), `diff_runs`, `when_did` → root cause in 3 calls, and a token counter showing the difference.
**Tracks:** Manufact (MCP, novel end-to-end task) + Blaxel (rr needs Linux perf counters; sandboxes with snapshot are a natural fit) + Armature (AX, token-first). Could meter per `record` with Stripe MPP (pay-per-evaluation was a Berlin x402 placer).
**Risks:** rr needs ptrace + perf counters in the sandbox; verify Blaxel microVM support early, fallback is a Docker container on a bare VM. Python path via `pytrace`/own tracer if rr is blocked.

---

## 4. BENCH — the agent gets hands on a dev board (incremental, but very demoable)
**Gap:** Agents write firmware but a human flashes, resets, watches LEDs, and reads the scope. Probe MCPs (probe-rs/OpenOCD/J-Link) exist and cover flash + memory + registers. **Missing:** measurement and physical observation as tools: `measure(pin, "frequency")` via a $10 sigrok logic analyzer, `power_cycle()` via USB relay, `await_serial(pattern)` event-wake, `camera_check("LED blinking?")` as fallback. Closes the loop so the agent can bring up a board end-to-end.
**Demo:** ESP32 + logic analyzer. "Make GPIO4 output a 2 kHz 30% duty PWM and report over serial." Agent flashes, measures 1.998 kHz / 29.8%, done. Then you cut the sensor wire; it notices via serial and recovers.
**Tracks:** Manufact + Armature. Hardware: ESP32 ($8), logic analyzer ($12), USB relay ($10). All available same-day in SF.
**Why lower:** several probe MCPs exist; novelty is the measurement + wake layer only.

## 5. FORGE — test-driven mechanical design → fabrication
**Gap:** Agents can write CadQuery, but a human runs FEA, checks tolerances, slices, prints, and inspects. Text-to-CAD exists; the verify-and-fabricate loop does not.
**Build:** `design(code)` → CadQuery → `check(load_case)` runs CalculiX FEA and returns the structured failure (max stress location, deflection, interference with mating part) → iterate → `fabricate(service=local_printer|JLC3DP)` with Stripe test-mode payment and intent receipt → `inspect(camera)` compares print to model.
**Demo:** Physical object on the judging table printed overnight, with the four failed iterations shown as stress maps. Berlin x402's three physical projects all placed.
**Tracks:** Stripe (agent provisions/pays for a service, user controls budget) + Manufact. Needs a printer or a print service with fast turnaround; otherwise show the order.

## 6. ORACLE — verification agents can buy before they trust another agent (software)
**Gap:** "Agents can't check their own work"; 93% of merchants want someone to verify agent output. Humans run property tests and symbolic exec; agents rarely do.
**Build:** `verify(spec, impl)` → Hypothesis/CrossHair for Python, Kani/Miri for Rust, in a Blaxel sandbox → counterexample or proof bound, metered per call via Stripe MPP. One agent pays another agent's work only after `verify` passes.
**Tracks:** Stripe + Manufact. Lower on the list because pieces exist; the pay-gated acceptance test is the twist.

---

## Recommendation
**REFLEX, with WORLDVIEW as the second half if you are two or more people.** It is the most "cracked" (it inverts how every existing robot/sim MCP works), it needs zero hardware for a strong demo and gets dramatically better with $30 of parts, and it maps cleanly onto Manufact + Blaxel with Armature as a third. One-sentence pitch: *"Coding agents got good because they have a test loop. We gave them one for the physical world: controllers are code, the simulator is the test runner, and the LLM is never in the fast path."*

If you want purely software and the sharpest contrast demo: **REWIND.** One tool call replacing a 30-turn debugging session is the cleanest token-economics story in the room.

## 24-hour plan (REFLEX)
- Sat 10:30–13:00: MuJoCo headless in a Blaxel sandbox, one menagerie model (cart-pole first, Go2 if time), controller interface `u = f(state, t)` in Python (numba) with a 1 kHz stepper and the constraint checker.
- 13:00–16:00: failure-report generator (test-failure format, downsampled trace, optional plot). Batch seeds via Blaxel jobs.
- 16:00–19:00: MCP server (mcp-use SDK, deploy on Manufact Cloud so judges see it in their dashboard). Tools: propose_controller, sysid, supervise.
- 19:00–22:00: `deploy` to a real-time process; if hardware arrived, C codegen to ESP32 + watchdog envelope.
- 22:00–01:00: run Claude against it end to end, record token counts vs a screenshot baseline. Sleep.
- Sun 08:00–09:45: dashboard (iterations, failure reports, seeds passing, tokens), rehearse. 10:00 demo.

## Hardware notes
- No hardware: REFLEX, WORLDVIEW (webcam), REWIND, ORACLE all demo fully.
- $30 and a Saturday-morning trip: ESP32 + logic analyzer + USB relay (BENCH), or reaction-wheel pendulum kit (REFLEX deploy).
- If you own an SO-101 / LeRobot arm: REFLEX `deploy` target + WORLDVIEW gives a complete pick-and-place with the LLM out of the loop. The existing SO-ARM100 MCP (IliaLarchenko) is image-in, joint-angles-out at LLM speed; your demo is the counterexample.

## Sources
UniFS arXiv 2606.22794 · DaDu-Corki arXiv 2407.04292 · TIC-VLA ICML 2026 slides 65809 · FASTER arXiv 2603.19199 · ConceptGraphs arXiv 2309.16650 · existing MCPs: glama.ai (mujoco-mcp-server, isaac-sim-mcp, gdb-mcp, mcp-debugger, embedded-debugger-mcp, dbgprobe, mcjtag), mcpservers.org IliaLarchenko/robot_MCP · token-reduction caveat arXiv 2607.12161 (compressing tool output does not reliably cut billed cost because of prompt caching; measure tokens AND turns).
