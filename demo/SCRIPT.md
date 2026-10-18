# Steward demo: lines to record for the boards

Rules for recording: say each line as written, one short pause (about half a second) at every full stop, and a two-second silence before each new board so I can cut cleanly. Numbers are written the way you should say them. Speak at a tutor's pace, not a pitch pace. Record the boards as separate clips or as one take; either is fine.

Who speaks: **YOU** = your voice, recorded. **CLAUDE** = I voice it with the local Kokoro voice. Default is YOU for everything; change any board to CLAUDE and I will do it.

Each line is one "beat": one clause, one drawing. Board total is about 95 seconds of speech.

---

## Board 1 · Hook (YOU, ~15 s)

1. "Say an agent is running a plant."
2. "It asks: is pump P-101 commissioned?"
3. "Today, it gets a guess, from a document, from last year."
4. "No one checked. Nothing is signed."
5. "That's the problem Steward fixes."

Drawing: an "agent" box, an arrow to a "plant" box, a question mark, the word "guess" crossed out.

## Board 2 · What Steward is (YOU, ~22 s)

1. "Steward is a reality layer for agents."
2. "It has three verbs."
3. "Resolve: ask for a fact about a physical asset."
4. "Attest: submit evidence for it."
5. "Check: verify someone else's signed proof."
6. "Every answer is one of four things: known, stale, unknown, or conflict."
7. "Never a made-up value."

Drawing: three ovals for the verbs, the four states under resolve, "never a made-up value" underlined.

## Board 3 · The four agents (YOU, ~20 s)

1. "Four agents share one record."
2. "Operator holds the mandate. It starts missions and sets a budget."
3. "Atlas coordinates the portfolio. It delegates and declares readiness."
4. "Warden owns one site. Only Warden can sign a fact."
5. "Runner reaches humans: text, email, call."
6. "Authority is enforced in code, not in a prompt."

Drawing: a four-level ladder, each level with what it may and may not do, "in code" circled.

## Board 4 · Verification (YOU, ~20 s)

Place this after the demo shows a photo being rejected and then accepted.

1. "A reply is not a fact yet."
2. "Six checks have to pass."
3. "Scope. Identity. Geometry. Plausibility. Time. Integrity."
4. "The wrong tag plate fails identity, so it's rejected, with the reason."
5. "When all six pass, Warden signs it with an Ed25519 key."
6. "Any agent can call check, and get valid: true."

Drawing: six boxes ticked one by one, a cross on the wrong one, then a signature line.

---

# Sponsor boards: how we used each product

Say each one right where that product appears on screen. One board per sponsor, about 15 to 20 seconds.

## Inkbox (YOU, ~18 s)

1. "Inkbox gives Steward one persistent identity."
2. "Runner uses it to text the technician the task card."
3. "The photo comes back through a signed webhook."
4. "If nobody answers, the same identity places a voice call."
5. "And its tunnel is the public URL that lets the hosted server reach my laptop."

Drawing: identity in the middle, SMS, email and call fanning out to a phone, a webhook arrow back, a tunnel arrow to a laptop.

## Manufact (YOU, ~18 s)

1. "The MCP server is hosted on Manufact."
2. "Claude Code connects to it with one URL."
3. "Every session is captured: initialize, tools list, tool call."
4. "Manufact's gateway shows latency and issues per tool."
5. "And the publish checklist scores the server for protocol compliance."

Drawing: laptop, tunnel, Manufact box in the middle labelled "Sessions, Analytics, Publish", Claude Code on the right.

## Supabase (YOU, ~16 s)

1. "SQLite on the laptop stays the source of truth."
2. "Every fact, attestation and work item is mirrored into Supabase."
3. "Realtime pushes each change to the dashboard timeline."
4. "So a judge can open the attestations table and see the signed rows land."

Drawing: SQLite box, arrow "upsert" to Postgres, arrow "realtime" to a browser, a row with a signature.

## Armature (YOU, ~16 s)

1. "Armature watches the agent sessions."
2. "Each session is scored: did the agent get what it asked for?"
3. "We wrote a five-case eval suite for the demo workflow."
4. "Armature's tester agent runs it against the hosted server, and a judge scores every run."

Drawing: the MCP box wrapped by a ring labelled "analytics", a tester agent arrow in, a 0 to 5 score out.

---

## Close (YOU, ~12 s)

1. "This is a fictional plant, and the checks are rule-based."
2. "Steward doesn't certify equipment."
3. "It makes sure an agent never signs what it can't prove."

Drawing: the last line written big.
