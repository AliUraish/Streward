# Make Something Agents Want — idea brief
YC HQ, SF · Oct 17 (9am) → Oct 18 (submissions + live demos 10:00, judging done 11:00, winners 12:15)
Source of truth: events.ycombinator.com/MakeSomethingAgentsWant (page is JS-rendered; full text saved in scratchpad `yc/hackathon_brief.md`)

## 1. The event, decoded

**Theme sentence from YC:** "Agent experience (AX) rather than user experience (UX). Headless MCPs rather than UIs and APIs. Optimizing token spend rather than minimizing user time. Documentation made for agents."

**Sponsors (confirmed on page):** Armature, Blaxel, Inkbox, Insforge, Manufact, Primitive, Stripe, Supabase.

**There is NO overall prize and NO published rubric.** Every prize is a sponsor track. "Competing for 2" means: pick two sponsor tracks whose judges are the people who built the product you're building on.

| Track | What they want | Cash (1st/2nd/3rd) | Judges |
|---|---|---|---|
| Primitive — Best Agent Communication Setup | "Give your agent an identity. Let it ask questions, receive replies, handle attachments & coordinate asynchronously." | **$3k / $2k / $1k** | Ethan Byrd, Ashley Ha, Ben Poile |
| Stripe | "Agent that can safely participate in the economy: buy, provision services, manage spending, pay for resources… clear user control over what agents can do and spend." | $3k / $2k / $1k credits + Atlas fee waived | not listed |
| Manufact — Best MCP Server for Agents | "Best MCP server built for agents as the primary customer." | $2k+$6k cr / $700+$3k / $300+$300 | Luigi Pederzani, Enrico Toniato, Andrew Khadder |
| Insforge — Agent-Native Cloud | agent provisions/operates its own backend | $1k+$1k / $500+$500 / $300+$300 | Tony Chang, Hang Huang |
| Armature — Best AX | "Agents use your product through a dedicated agent-facing interface (MCP, CLI). Build the best experience for them." | $1k+$1k / $500+$500 / $300+$300 | Theodore Otzenberger, Louis Scremin |
| Inkbox | "persistent identity with email, phone, iMessage, A2A so agents communicate with humans and each other" | $1k+$1k / $500+$500 / $200+$200 | not listed |
| Blaxel — "Something a Human Would Never Want" | no description | $1k | not listed |

**Precedent that matters (from past YC-office agent hackathons):**
- Dedalus Aug-2025 rules: ≤4 per team, >2/3 built at event, repo public, in-person demo. Qualifying example given verbatim: "an MCP server enabling an agent to complete a novel task." Disqualifying: "adding AI across an existing product."
- Only published rubric at a YC-office agent hackathon (Browser Use, Feb 2026): **Impact 40% · Creativity 20% · Technical 20% · Demo 20%.**
- Winners that stuck: Browser Brawl (adversarial agents producing training data; called "a research rabbit hole", won 1st + YC interview), Lamina (LinkedIn for healthcare agents → YC interview), World of Geneva / Moltbet (won two tracks each by stacking), Juicebag Mail / Print402 / Volt402 (physical side effects all placed).
- Pattern: ambitious + working + visible side effect + produces an asset (data, money, receipts) beats safe.

## 2. What to NOT build (saturated — judges have seen 20+ of each)
- Spend caps / allowlists / "Brex for agents" dashboards (Tempo MPP hackathon alone had 5)
- Escrow where an LLM judges the work
- x402/MPP routers, "turn any API into pay-per-call", cheapest-provider routers
- On-chain agent reputation / credit score (one track had 403 entries)
- Thin MCP wrapper around an existing SaaS (300 people did this at Manufact's Feb event)
- Generic browser/scraper agents; "websites → API" (Skeleton Key just won Agent Arena)
- Better-Devin / parallel-coding-agent orchestrators
- MCP trace viewers; memory-as-a-service

## 3. The chokepoints, ranked by evidence (humans do it, agents can't)

| # | Chokepoint | Hardest evidence |
|---|---|---|
| 1 | Waiting. Agents can't sleep for hours/days and resume with state; they time out or burn tokens polling. | Microsoft DELEGATE-52: models lose ~25% of document content over 20 delegated turns. Agentverse gap list: "no job queue for deferred tasks", "no standard path for agent to request human input". Claude Code's two most-commented issues (1,499 and 877 comments) are agents stalled on usage caps. |
| 2 | OTP / phone verification / CAPTCHA | Anthropic Sept-2026 threat report: a 1,022-page agent transcript was mostly the model fighting CAPTCHAs and a phone-verification wall. Claude Code issue #34229 "Phone verification", 742 comments. Garry Tan on phone numbers for agents: "Sounds like a request for startup." |
| 3 | Approvals are rubber stamps | Humans approve 93–97% of permission prompts (why Claude Code shipped auto mode). HumanLayer's approvals SDK deprecated. Loopjacking paper: HITL approval is hijackable. Nobody has one cross-agent approval inbox with blast-radius summaries. |
| 4 | Phone calls, IVR, hold queues | Only consumer apps (Martin, Instinct, Assindo) are starting outbound calls. No "call as a tool" for coding/personal agents. |
| 5 | After-payment: receipts, refunds, disputes, "agent error" | 93% of merchants say agent providers should eat losses from wrong purchases (PYMNTS Sept 2026). Visa/Mastercard have no reason code separating agent error from fraud. Every payments hackathon builds the spend side; nobody builds the after side. Stripe even ran a Brussels event on agentic e-invoicing. |
| 6 | Verified ≠ allowed | Since Jul-2026 Cloudflare admits verified bots only if the site enabled their category; since Sep-15 blocks agents by default on ad pages. No broker where an agent asks a site for access and the owner approves once. |
| 7 | Hiring humans with proof of completion | RentAHuman: a $40 USPS package pickup got 30 applicants and zero completions in 2 days. Tax/1099 status for agent-hired humans "unresolved". |
| 8 | Negotiation leaks | NeurIPS'25: agents disclose budgets, accept above-retail prices; stronger model wins ~9.5%. |
| 9 | Logs aren't evidence | Amazon v. Perplexity: both sides had logs, neither could prove who authorized what. |
| 10 | Agents pick tools by doc-SEO | Claude Code chose deprecated Whisper over Groq (200x faster) because the docs indexed better (Gary's List). Login.gov RFI is literally asking how to admit "approved agents". |

## 4. Ideas (ranked). Each one: a thing a human does today that an agent can't, made agent-doable.

### ★ 1. HIBERNATE — "wake me when the world replies"
**Human does / agent can't:** A human sends an email asking for a quote, closes the laptop, and picks the thread up three days later. An agent either dies at the timeout or burns tokens polling.
**Build:** An MCP server with one verb: `await_event(kind, filter, resume_token)`. The agent sends mail via Primitive, calls `await_event`, and the harness **snapshots the Blaxel sandbox** (Blaxel's microVMs auto-suspend and resume in ~25 ms with memory intact — this is the product's headline feature). Inbound Primitive webhook (reply arrived) / Stripe webhook (payment cleared) / Inkbox SMS / cron → resume the exact sandbox with the reply injected as the tool result. Zero tokens while waiting. Return a `wait_receipt` (what it waited for, how long, token spend saved).
**Tracks:** Primitive (async comms, attachments = the quotes) + Blaxel (suspend/resume is the whole trick; and "a human would never want to be frozen mid-thought and thawed 3 days later") + Manufact (it is an MCP server). Add Stripe if the task ends in a purchase.
**Demo (10:00 Sunday):** Saturday night the agent emails 3 real sticker/print vendors for quotes and hibernates. Sunday 10:00 you show the frozen sandbox at $0.00/hour, a judge replies to one email from their phone, the agent wakes in <1s, compares, asks the human one question via Primitive, pays with a Stripe test-mode shared payment token, posts the receipt. The event-page thesis "optimize token spend, not user time" is literally your dashboard.
**Why not me-too:** Temporal/Inngest do durable waits inside their own orchestrator. Nobody exposes "wait for an external-world event" as an MCP tool to any agent, with sandbox-level suspend.
**Risk:** Blaxel snapshot API wiring; have a fallback where the agent process is re-spawned with a serialized state blob.

### ★ 2. HANDOFF — one escalation inbox for every wall an agent hits
**Human does / agent can't:** Read the OTP off their phone, click "I'm not a robot", answer "which card?", approve "spend $412". Agents hit these 5–20 times per real task; today each one is a dead end or an unsafe workaround (SIM farms, disabling 2FA).
**Build:** An MCP server `escalate(kind: otp|captcha|approval|question|signature, context, blast_radius)` that routes to wherever the human is right now: iMessage/SMS via Inkbox, email via Primitive, with a one-tap signed reply. Every request carries a machine-generated blast-radius card (what it will do, cost, reversibility, expiry) because the research says approval fatigue is a *summary* problem, not a button problem. OTPs: the human keeps their number; the forward is scoped to one site, one code, 5 minutes, and generates a receipt. Multiple agents (Claude Code, OpenClaw, browser agent) share one inbox.
**Tracks:** Primitive (ask question → receive reply → attachments) + Inkbox (identity across email/phone/iMessage). Manufact as a third.
**Demo:** Agent signs up for a real SaaS live → hits phone verification → judge's phone buzzes with "Agent X needs the code just sent to you, for acme.com, expires in 4:59" → tap → agent finishes, pays via Stripe test SPT, sends receipt.
**Why not me-too:** HumanLayer died; GroupFactor/AgentCall are grey SIMs. The consented, human-held, scoped relay with receipts doesn't exist (Anthropic's own browser extension just "pauses and asks you to handle it manually").
**Risk:** Inkbox/Primitive judges may see overlap with their own roadmaps; position it as the *human-side* consent layer on top of their identity, not a competitor.

### 3. DIALTONE — the phone as a tool
**Human does / agent can't:** Call the pharmacy, sit on hold 22 minutes, navigate "press 3 for billing", cancel the subscription, get a confirmation number.
**Build:** MCP tool `call(number, goal, constraints, budget)` → the agent gets a structured result (outcome, confirmation #, transcript, recording URL) and the call is placed from an Inkbox phone identity. Hold detection parks the call and (with Hibernate) suspends the agent. If payment is needed, Stripe SPT with a per-call cap. Mandatory AI-disclosure on connect.
**Tracks:** Inkbox (phone identity) + Manufact (MCP) + Stripe (pay on the call).
**Demo:** Live call to a real restaurant to book a table, or to your own cell with an IVR you set up; return the structured result in the agent's context. Judges hear it.
**Why not me-too:** Twilio/Vapi/Retell are inbound business bots. YC hosted "Call My Agent" in May 2026, so the space is known but *outbound call-as-MCP-tool for coding agents* with hold-parking is still fresh.
**Risk:** Audio latency in a demo room; pre-record a backup.

### 4. INTENT RECEIPTS — the after-payment half nobody builds
**Human does / agent can't:** Dispute a charge, request a refund, prove to the merchant "I authorized $50 for blue, not $500 for red", file the expense.
**Build:** Wrap every agent purchase in a signed **intent receipt**: the human's authorization (scope, cap, item class), the agent's reasoning hash, the SPT used, merchant ack. MCP tools: `refund_request`, `dispute(reason="agent_error")`, `reconcile` → spend report to the human, invoice PDF via Primitive attachment. Expose a merchant-side endpoint that *verifies the receipt before accepting an agent order* (answers the 80%-of-merchants "verify agent authority" ask).
**Tracks:** Stripe (this is exactly "clear user control" extended past checkout) + Manufact.
**Demo:** Agent buys the wrong thing on purpose; one tool call opens a dispute carrying the intent receipt; merchant dashboard shows "agent error, scope exceeded, auto-refund".
**Why not me-too:** Zero after-payment projects in any 2026 payments hackathon; 93%-of-merchants stat makes the pitch.
**Risk:** Less visual; pair with a physical purchase for the demo.

### 5. GATEKEEPER — verified ≠ allowed, so let agents *ask*
**Human does / agent can't:** Email a site owner "can I have API access?" and get a yes. Agents are blocked by Cloudflare defaults even when their identity is verified.
**Build:** A broker where an agent (signed with Web Bot Auth / RFC 9421) requests access to a site, attaches who it acts for and what it will do, optionally offers to pay via MPP/x402. The owner gets one Primitive email, approves once, and the agent receives a scoped token. A Cloudflare Worker snippet that honors the token.
**Tracks:** Primitive + Stripe (MPP), or Armature (this *is* AX).
**Risk:** Needs a site owner in the loop; demo on your own domain. More "standards pitch" than product; best as a YC-interview story, weaker for cash.

### 6. PROOF-OF-HANDS — agent hires a human and actually gets the thing done
**Human does / agent can't:** Pick up a package, photograph a storefront, sign at a notary.
**Build:** Agent posts a task with Stripe escrow; the human accepts over Inkbox SMS; completion requires geotagged photo + liveness + the agent's own verification step before funds release. Employer-of-record style 1099 handling stubbed.
**Tracks:** Stripe + Inkbox.
**Risk:** RentAHuman exists (YC) and their reliability is the gap; you're building the verification layer, not the marketplace. Demo requires a human physically doing something during judging — doable: send a judge to the YC kitchen.

### Cheap add-on for Blaxel's $1k ("Something a human would never want")
Whatever you build, ship a second interface no human could stand: a token-metered mode where every response is a compressed binary/JSON-diff stream priced per byte via MPP, docs served as a single 40-token grammar instead of prose, and the agent can `buy_more_context()` mid-call. It's a 2-hour addition, it dramatizes the event's "optimize token spend" thesis, and it answers Blaxel's track literally.

## 5. Recommendation
Build **Hibernate (1) with Handoff (2) folded in as the "ask the human" event type.** One MCP server, three verbs: `await_event`, `escalate`, `receipt`. It targets Primitive (richest cash track, very specific description most teams will skip) + Blaxel (their core feature, their vague track) + Manufact (it is an MCP server) and the demo ends in a Stripe test-mode payment. The one-sentence pitch: *"Agents can finally do what every human does a hundred times a day: send a message, go to sleep, and pick it up when the reply comes."*

If you want pure cash EV with less infra risk: **Handoff (2) + Dialtone (3)** share the Inkbox phone identity and both demo loudly in a room.

## 6. 24-hour plan for the recommended build
- **Sat 10:30–13:00** Primitive inbox + webhook → event bus (Supabase or Insforge Postgres + Realtime). Stripe test-mode SPT purchase path.
- **13:00–17:00** Blaxel sandbox: run a Claude agent inside, snapshot on `await_event`, resume on webhook. Fallback: serialize agent state to Postgres and respawn.
- **17:00–21:00** MCP server (mcp-use SDK, deploy on Manufact Cloud so their judges see it in their own dashboard). Tools: `await_event`, `escalate`, `receipt`.
- **21:00–23:00** Send the real quote emails. Hibernate. Go to sleep yourself.
- **Sun 08:00–09:45** Dashboard: frozen sandboxes, $/hour = 0, tokens saved counter, receipts list. Rehearse the live reply with a teammate's phone.
- **10:00** Demo.

## 7. Source notes
Chokepoints: Anthropic threat report Sept 2026 (techcrunch.com/2026/09/10/anthropic-reveals-rogue-ai-agents-hate-captchas-just-like-you), Claude Code issues #34229/#16157/#38335, HN 47226958 / 46838946 / 47089014 / 47736831 / 49468363, PYMNTS Sept 2026 via finance.yahoo.com, Cloudflare blog web-bot-auth + agent-registry, arxiv 2606.20570 (Agentverse gaps), Microsoft DELEGATE-52 via theregister.com/ai-ml/2026/05/11, openclaw.report/ecosystem/yc-lightcone-make-something-agents-want.
Past hackathons: luma.com/pz27h0xy, events.ycombinator.com/manufact-hackathon26, hackhq.io/customers/browser-use-hackathon, stack.convex.dev/the-real-reason-y-combinator-is-using-convex, medplum.com/blog/yc-medplum-hackathon-2026-recap, tempo-hackathon-projects.vercel.app, dorahacks.io/hackathon/x402/winner, algorand.co/blog/agentic-commerce-x402-hackathon-berlin-recap, browser-use.com/posts/how-to-win-hackathons.
Sponsor docs: docs.stripe.com/agentic-commerce, docs.primitive.dev, docs.manufact.com, blaxel.ai, inkbox.ai, insforge.dev, armature.tech.
Not verified: Reddit and X could not be read directly (blocked); sentiment is via HN, GitHub issues, and press quoting them.
