# Steward demo: lines to record for the boards

Rewritten Oct 18 after reading the live dashboard (three scanned factories, 17 agents, 76 MCP tools, the agent eye, walkthroughs, the inspection chain, Tool Forge). Supersedes the Oct 17 version.

Recording rules: say each line as written; a short pause at every full stop; two seconds of silence before each new board so I can cut. Say numbers the way they are written. Tutor's pace. Boards default to **your voice**; mark any board "Claude" and I voice it with the local Kokoro voice.

Each line is one beat: one clause, one drawing. Core boards are about 2 minutes of speech in total; the optional ones add about 50 seconds. Say the sponsor boards right where that product is on screen.

---

## Board 1 · Hook (~14 s)

1. "Say your agent is running a factory."
2. "It asks: is the sump about to overflow?"
3. "Today it gets a guess, from a document, from last year."
4. "Nobody looked. Nothing is signed."
5. "Steward fixes that."

Drawing: an "agent" box, an arrow to a factory, a "?" and the word "guess" crossed out.

## Board 2 · What Steward is (~22 s)

1. "Steward is a reality layer for industrial agents."
2. "Three real factories, scanned in 3D: a plant room in Melbourne, a 1907 pump house in Bristol, and a silk mill in Japan."
3. "Three verbs."
4. "Resolve: ask for a fact about an asset."
5. "Attest: submit evidence for it."
6. "Check: verify someone else's signed proof."
7. "Every answer is known, stale, unknown, or conflict. Never a made-up value."

Drawing: three small factory icons, then three ovals for the verbs, the four states under resolve, "never a made-up value" underlined.

## Board 3 · The agent eye (~16 s)

Say this where the Environment page shows the camera moving.

1. "The scan is not just for humans. It's an interface for agents."
2. "An agent calls eye go to, and gets back a picture with the asset tags in view."
3. "The Site Engineer walks the plant, ten stops at a time."
4. "Green means looks good. Blue means looks bad, with the regulation it breaks."

Drawing: an eye icon, an arrow into a frame with tag labels, a route of ten dots, a green dot and a blue dot.

## Board 4 · The team (~24 s)

Say this where the Agents map is on screen.

1. "Each factory has a team of four agents."
2. "A Plant Manager who decides."
3. "A Site Engineer who looks, verifies and signs."
4. "A Compliance Officer who knows the law."
5. "And a Field Technician who reaches humans."
6. "Above them, an Operations Director. Beside them, an Inspector, a People Officer and a lawyer."
7. "Every one is a real Inkbox identity."
8. "And authority is enforced in code, and again in Postgres."

Drawing: a ladder with the Director on top, three columns of four under it, three side boxes, and "in code" plus "in Postgres" circled.

## Board 5 · Verification (~18 s)

Say this after the demo shows a wrong photo rejected and a right one accepted.

1. "A reply is not a fact yet."
2. "Six checks have to pass."
3. "Scope. Identity. Geometry. Plausibility. Time. Integrity."
4. "The wrong tag plate fails identity, so it's rejected, with the reason."
5. "When all six pass, the engineer signs it with an Ed25519 key."
6. "Any agent can call check, and get valid: true."

Drawing: six boxes ticked one by one, a cross on identity, then a signature line.

## Board 6 · The inspection chain (~22 s)

Say this where the owner email, the contractor email or the phone call is on screen.

1. "When the Inspector finds a compliance gap, a chain starts."
2. "Inspector to Compliance Officer: here's the evidence."
3. "Compliance Officer to Plant Manager: here's what the law requires."
4. "Manager emails the owner, with the lawyer in CC."
5. "The lawyer emails the contractor what must be certified."
6. "Then the manager calls the contractor, and they agree a date."
7. "One email and one call per two minutes. Never a flood."

Drawing: five boxes in a row joined by arrows, "CC lawyer" on the owner arrow, a phone on the last arrow, "1 per 2 min" boxed.

## Board 7 · Waiting costs nothing (~12 s)

Say this where the Evals page shows "time held by wait for".

1. "When an agent starts work it needs an answer to, it calls wait for."
2. "The call is held open. The model generates nothing."
3. "Six hours held so far. A quarter of a million tokens never spent."

Drawing: a clock, a flat line labelled "0 tokens", then "268,450 saved".

## Board 8 · Tool Forge (~16 s, optional)

Say this on the Tools page.

1. "If no tool fits a task, the agent builds one."
2. "It records the gap, drafts the tool, Steward validates and tests it."
3. "The Plant Manager approves it."
4. "And it's published as a real MCP tool. Every connected client sees it at once."

Drawing: gap, draft, validate, test, approve, publish as six steps, the last one fanning out to three client boxes.

## Board 9 · Agents optimise themselves (~14 s, optional)

Say this where the before and after chart is on screen.

1. "The Compliance Officer in Bristol was burning four times the tokens of its peers."
2. "The Director saw it in the telemetry, called it, and reconfigured it: cache, and subscribe instead of poll."
3. "Seven times fewer tokens. The eval proves it."

Drawing: a tall bar next to a short bar, "7.7x" between them.

---

# Sponsor boards: how we used each product

## Inkbox (~22 s)

1. "Inkbox gives every agent a persistent identity. Seventeen of them."
2. "Agents talk to each other over Inkbox A2A, and email each other PDFs."
3. "One phone number, the Steward Dispatch Line, texts and calls real people."
4. "Calls are real conversations with Inkbox Voice AI, and they end in a decision."
5. "Replies come back through signed webhooks."
6. "And the Inkbox tunnel is the public URL that lets the cloud reach my laptop."

Drawing: 17 small circles, A2A arrows between them, one phone icon, a webhook arrow back, a tunnel arrow to a laptop.

## Manufact (~18 s)

1. "The MCP server is hosted on Manufact."
2. "Seventy-six tools, one URL."
3. "Claude Code connects with one command."
4. "Every session is captured: initialize, tools list, tool call."
5. "The gateway shows latency and issues per tool, and the publish checklist scores compliance."

Drawing: laptop, tunnel, Manufact box labelled "76 tools, Sessions, Analytics", Claude Code on the right.

## Supabase (~20 s)

1. "SQLite on the laptop stays the source of truth."
2. "Every fact, proof, work item and call is mirrored into Supabase."
3. "Row-level security enforces who may write what. A technician trying to write a proof is refused by Postgres itself."
4. "The proof ledger is append-only and hash-chained."
5. "Realtime drives the live dashboard. An Edge Function is the inbox for Inkbox webhooks."

Drawing: SQLite box, arrow "upsert" to Postgres, a lock labelled "RLS", a chain of three linked blocks, arrows "realtime" to a browser and "webhook" from a phone into an "Edge Function" box.

## Armature (~16 s)

1. "Armature watches every agent session."
2. "Each session is scored: did the agent get what it asked for?"
3. "We wrote eval suites for the demo workflow, safety, efficiency and Tool Forge."
4. "Armature's tester agent runs them against the hosted server, and a judge scores every run."

Drawing: the MCP box wrapped by a ring labelled "analytics", a tester agent arrow in, a 0 to 5 score out.

## Claude and vision (~14 s, optional)

1. "Claude Opus 5.5 writes the agents' conversations and reads the call transcripts into decisions."
2. "V-JEPA 2 compares each valve's orbit with its clean baseline."
3. "A valve that changed comes back not fixed, and Claude explains why from four frames."

Drawing: a valve with an orbit ring, "baseline" next to "now", an arrow to "not fixed, because".

---

## Close (~12 s)

1. "The factories are real scans. The checks are rule-based."
2. "Steward doesn't certify equipment."
3. "It makes sure an agent never signs what it can't prove."

Drawing: the last line written big.
