# Steward — every property gets an agent

Local implementation brief, October 17, 2026. The user explicitly authorized coding and parallel subagents and requested a working local application. Cloud deployment is excluded from the current task.

Current product direction, restored by the user on October 17, 2026: agents managing several properties, with a 3D view, memory, identity, communication and the ability to act. First reconstruct the reference video's visible frontend and working backend behavior, then integrate the property agents and selected services, then extend the agent-facing workflow. Marketplace, building-simulator and property-design pivots are not the product direction.

Implementation authorization: the user said "code" and authorized frontend/backend implementation, subagents, all four reference views and local operation. Build and test locally. Do not deploy to Vercel or another cloud. Optional external services require their configured credentials and action gates; no external messages or payments have been executed during implementation.

Reconstruction boundary: the original source code and original 3D scan have not been recovered. Match visible screens, interactions and observable outcomes against the saved video; implement the backend ourselves. An identical scan requires the original reusable asset. Otherwise use the original mechanical-room scene discussed earlier and state that difference clearly.

Selected optional services: Inkbox, Supermemory, InsForge, Stripe and Manufact. The working local application uses FastAPI + SQLite/private local files and exposes optional adapters; no cloud backend has been provisioned or deployed. See [README.md](README.md) for current launch instructions and the precise boundary between working local capabilities and credential-dependent services.

## Implemented local application

The app runs at http://127.0.0.1:3000 with the API on http://127.0.0.1:8001. `npm run dev` launches the frontend, backend and local MCP service. It includes the 3D Workspace, twelve-view Inspection wall, Codes & standards library/requirements/PDF reader, and Agents workspace. Twenty-four stable scene components, ninety-six source-linked project checks per property, original PDF project specifications and synthetic baseline observations are persisted separately for Cedar, Harbor and Juniper.

Local jobs extract actual source text, check project identifiers and model locations, assess machine-readable evidence, persist component/requirement changes, emit tool events, save memory and export reports. A portfolio job coordinates the three scoped property workers. SQLite records, uploaded files and interrupted-job checkpoints survive restart in `backend/data/`. Missing model access is shown as unconfigured; local analysis does not pretend to run vision inference or certify a real building.

The optional eve runtime defines one coordinator plus three property specialists with typed tools. It runs locally on port 2000 when started and connected to a supported model. Property-specific mutation mandates are enforced outside prompts. The backend's read-only model questions cannot issue inspection writes. Optional Supermemory namespace sync/recall, Inkbox identity/inbox/allowlisted email, Stripe test Checkout/verified receipt handling, and an InsForge read-only connectivity check are implemented and capability-gated. No keys have been supplied and no successful external integration is claimed.

Installed project-local runtime/tooling: Python 3.12.13, Node 24.22.0, InsForge CLI 0.2.8, Manufact CLI (`mcp-use`) 4.4.1, eve 0.80.1 and Inkbox Python SDK 0.7.19. Offline version wrappers are documented in the root README. Existing global tools were reused without changing the user's global Node or Python selection.

The sections below retain the wider product design and future cloud architecture. They are planning context, not a claim that every proposed hosted service, browser automation or procurement feature has been implemented.

## Current build order and setup

1. Recreate the video reference: inspection camera wall; codes-and-standards source library with PDF viewer; requirements and system/subsystem/component hierarchy; navigable 3D inspection workspace with selectable objects, world markers, evidence and source-linked requirement panels; connected project chat and the reference MCP workflow. Use real backend records, uploads, analysis jobs and persisted state.
2. Run one portfolio coordinator and three persistent property-agent contexts locally, using shared inspection, requirement and evidence tools. Connect optional InsForge, Supermemory, Inkbox, Manufact and Stripe test capabilities when credentials are supplied. Each property retains its own identity, scoped memory and work history. Agents need not run on separate servers.
3. Extend the external-agent workflow and controls after the reference application works. The user wants the original product implemented before another theme-driven redesign.

Implemented local stack: Next.js/TypeScript frontend, FastAPI application backend, Three.js/React Three Fiber renderer, SQLite/private local files, durable local job workers, and an optional eve model runtime. InsForge cloud persistence remains a future integration beyond the current read-only connection adapter. The original backend internals are not known from the video.

Optional access to prepare: a funded model connection; Supermemory API access; Inkbox account/API access and chosen identity handles; Stripe sandbox access; and an existing InsForge project if testing its connection. Manufact tooling and the MCP server run locally. Hosting access is unnecessary for this task. Store credentials in local ignored environment files, and only connect externally when configuring the selected service.

Optional input: the original reusable 3D scan, if exact scene identity is essential. Existing video captures and locally created demo documents are sufficient to begin reconstruction without it. Custom domains and real-money transactions are not prerequisites.

The user's global Node 22 and system Python remain untouched. The application has project-managed Node 24 and Python 3.12 plus local InsForge/Manufact/eve tooling and the Inkbox SDK. Existing GitHub, Docker, Stripe and Claude CLIs remain available, but their presence does not establish authentication or a running Docker engine. No cloud deployment CLI has been invoked to deploy this application.

## Product and hackathon fit

Steward gives agents a persistent, structured representation of a property: its equipment, requirements, evidence, blockers, contacts, deadlines and permitted actions. An external agent can operate it through MCP. A 3D property view lets a person inspect the same state and understand each action.

The reference customer is Steward, an AI property coordinator acting for the broker. Steward has an Inkbox communication identity with email and, when enabled, phone/text channels. It works across three property contexts, asks people for missing evidence and resumes when they reply. Supermemory provides long-term recall across sessions; InsForge remains the authoritative store for current property records and approvals. Stripe supports service-fee collection and a narrowly scoped, owner-approved purchasing workflow.

The YC theme emphasizes agents as users, dedicated agent interfaces and efficient context. The event lists hacking from October 17 at 10:30 AM until submissions on October 18 at 10:00 AM: approximately 23.5 hours, despite spanning two dates. [Event and sponsor tracks](https://events.ycombinator.com/MakeSomethingAgentsWant).

Pitch: “We give buildings an agent identity. A property agent knows what is unfinished, asks the right person for proof, and keeps its property record current until it is ready for human review.”

## Broker backstory

“I am a real estate broker coordinating the launch of three small developments for a developer. Every property has a different contractor, permit folder, punch list and handover date. Before I promise a viewing or a launch date, I need to know what is genuinely ready, what evidence is missing and who is following up. Today, those answers are scattered across PDFs, photos and email threads.”

Position the broker as coordinating readiness and handover. Official inspection and approval remain with the responsible professionals and authorities. SF's published process distinguishes inspections from final approval and permit closure. [SF permit lifecycle](https://www.sf.gov/permit-application-timelines-expiration-and-extensions).

## Demonstration portfolio

Use three clearly fictional properties in one supported jurisdiction for the first build:

| Property | Situation | Agent action |
| --- | --- | --- |
| Cedar | Pump installed; commissioning report required by the demo project specification is missing | Request the report from the assigned contractor |
| Harbor | A submitted report names a different property or equipment serial | Reject the evidence match and ask a focused question |
| Juniper | Evidence checklist complete; authorized signoff still pending | Prepare a review packet and show the remaining approval |

The commissioning requirement is a labeled demo project requirement, not an invented statutory requirement.

Build one detailed mechanical-room template with approximately 20–40 meaningful objects. Vary layout, equipment IDs and construction state across the properties. Use simple exterior building forms for the portfolio view. This preserves the original visual ambition without requiring three complete architectural models.

The room is an original designed scene, not a recovered reference scan or a measured representation of a real building. Three.js and React Three Fiber render it. Every equipment assembly has a stable component ID used by the scene, database, evidence and tools. [React Three Fiber model loading](https://r3f.docs.pmnd.rs/tutorials/loading-models).

Original geometry can be supplemented with the CC0 [Poly Haven industrial pipe kit](https://polyhaven.com/a/modular_industrial_pipes_01). [Asset license](https://polyhaven.com/license).

## Agent identity

Steward's identity consists of:

- A stable agent ID, display name, role, owner and disclosure that it is an AI coordinator.
- An Inkbox identity with its own email inbox and configured phone, SMS/MMS or iMessage channels. Route conversations to the appropriate property context.
- Persistent property-scoped memory: open work, contacts, requirements, evidence links, last actions and pending replies.
- An explicit mandate: prepare named properties for a named milestone.
- A contact allowlist, property scope, follow-up limit, tool-call budget, purchasing limits and escalation policy.
- An attributable action history: trigger, tool, input references, outcome and next step.

Implement one reusable agent definition with separate persistent sessions for the three properties. The portfolio coordinator reads their structured summaries. Multiple property contexts do not require separate servers or a large swarm.

For the demo, humans or teammates play the contractor and reviewer. Real outbound communication is restricted to explicitly designated demo recipients.

## Complete workflow

1. **Onboard.** Enter property ID, jurisdiction, construction phase, target milestone, contacts and permitted actions. Choose the room template and upload the project specification and evidence.
2. **Ingest.** Extract document text and metadata; interpret photos when needed; retain the original file, source page, sender and equipment identifiers.
3. **Ground.** Associate observations and evidence with property IDs, component IDs and requirements. An uncertain match creates a question rather than silently attaching to an object.
4. **Plan.** Retrieve relevant property history and owner preferences from Supermemory, reconcile them against current records and cited sources, determine blockers for the target milestone, rank dependencies and choose a permitted next action.
5. **Act.** Request a missing document or clarification through Inkbox, including the exact equipment and requirement reference. For an approved procurement task, obtain a supplier quote and prepare a purchase proposal with an itemized total.
6. **Wait.** Save the pending thread and next action, then stop model execution. An authenticated inbound event or scheduled deadline starts new work.
7. **Verify.** Check a reply's property, equipment serial, document type and applicable requirement. A reply alone does not resolve a blocker.
8. **Update.** Save the evidence assessment and event. Recompute readiness and update the corresponding 3D equipment state. Queue a source-linked interaction or outcome summary for Supermemory so later sessions can recall the history.
9. **Escalate.** Prepare the review packet when authoritative signoff is required. Track evidence completeness separately from official approval.
10. **Reassess the portfolio.** Query related equipment across properties when a finding may apply elsewhere. Do not transfer evidence or conclusions without checking scope.

Procurement extends the same loop: quote, owner approval, payment, vendor confirmation, delivery, installation evidence and review. A successful payment records an order; it does not establish that equipment has been delivered, installed or approved.

The agent chooses tools and asks follow-up questions. Deterministic application rules enforce identities, permissions, evidence state transitions and duplicate prevention.

## Sponsor selection

Use four core sponsors, each for a distinct job, plus Supermemory for long-term recall.

| Sponsor | Features to use | Product evidence in the demo |
| --- | --- | --- |
| Inkbox | Persistent agent identity; email and attachments; configured phone/text or iMessage channels; inbound event routing; contacts | Steward requests evidence, receives a PDF and sends the owner a purchase-approval link through the same identity |
| Manufact | Typed MCP tools and resources; hosted endpoint; Inspector; call/session traces; a client test scenario | An external MCP client operates a property without needing the dashboard |
| InsForge | Postgres; private Storage; authentication and property-scoped policies; Realtime; Custom Compute; functions and schedules | Durable property records, a running agent worker, private evidence, follow-ups and immediate 3D updates |
| Stripe | Hosted Checkout for service fees; Link Agent Wallet spend requests and one-time payment credentials; payment webhooks; idempotency and receipt references | A test service payment and a separately approved test purchase are linked to the correct property and equipment |

Inkbox is the selected communication provider. Its products cover email, phone, iMessage and agent-to-agent communication. Dedicated numbers and channel allowances depend on the plan and configuration; verify the available hackathon account and recipient setup early. [Introduction](https://inkbox.ai/docs/get-started/introduction), [pricing and channel limits](https://inkbox.ai/pricing).

Manufact provides deployment, inspection, testing and MCP-specific observability. Some testing/distribution features depend on the available plan or hackathon credits; deployment plus Inspector and traces are the first priority. [Manufact documentation](https://docs.manufact.com/dashboard).

InsForge documents its [backend services](https://docs.insforge.dev/introduction), [Custom Compute](https://docs.insforge.dev/core-concepts/compute/overview), [model gateway](https://docs.insforge.dev/core-concepts/ai/overview), [scheduled functions](https://docs.insforge.dev/core-concepts/functions/schedules) and [Stripe integration](https://docs.insforge.dev/core-concepts/payments/stripe). Keep a small application-owned Postgres work queue/outbox. Scheduled functions enqueue due follow-ups; the worker performs the reasoning. Configure retries in the application rather than assuming scheduled calls retry themselves.

Stripe documents [Checkout](https://docs.stripe.com/payments/checkout), [Link Agent Wallet](https://docs.stripe.com/agentic-commerce/agents/link-agent-wallet), [agent spending and test mode](https://docs.stripe.com/agentic-commerce/agents/link-agent-wallet/use-link-wallet-pay-online) and [agent service bookings](https://docs.stripe.com/agentic-commerce/sellers/use-cases/booking).

The most direct prize-track fits are Inkbox's persistent agent identity, Manufact's MCP server for agents, InsForge's agent-native cloud and Stripe's useful agent spending with clear owner control. The same design addresses Armature's published agent-experience theme without making another integration a critical dependency. Eligibility and any additional rules should be checked with organizers.

Supermemory is the fifth technical integration, with the specific responsibility of long-term contextual recall. It is additional to the four selected sponsors; the event's published sponsor list does not name Supermemory.

## Runtime and state

Recommended application stack:

- Next.js, TypeScript, React Three Fiber and Three.js for the human view.
- An eve agent worker with a custom Inkbox inbound adapter and typed property tools, hosted in InsForge Custom Compute. Keep the exact eve version pinned during the event.
- A thin MCP server on Manufact exposing the property operations.
- InsForge for domain records, files, access policies, event delivery, model access and live UI updates.
- Supermemory for scoped long-term recall, profiles and relevant prior conversations or outcomes.
- Stripe Checkout for incoming service payments; a Link SDK adapter for owner-approved procurement, starting in test mode.
- One tool-using, vision-capable model through InsForge's Model Gateway, selected from the available models after verifying tool calls and image inputs. Vision is invoked only for evidence that needs it.

eve documents durable sessions, checkpointed turns and parked work. Current setup requires Node.js 24+. Configure and verify a persistent workflow backend for the InsForge deployment; do not rely on eve's default local checkpoint directory. [Getting started](https://eve.dev/docs/getting-started), [execution and durability](https://eve.dev/docs/concepts/execution-model-and-durability).

InsForge holds the domain truth. Supermemory provides historical context. The worker runtime holds its execution checkpoints. Do not build competing workflow schedulers. A small queue/outbox protects inbound events and outbound sends; the worker performs the reasoning.

Core records: properties, components, requirements, evidence, evidence assessments, issues, contacts, agent identities, work items, message threads, purchase proposals, approvals, vendor orders, payment references and append-only action events.

Maintain two independent status dimensions:

- Evidence: missing, requested, received, needs clarification, accepted.
- Authority: not required, review pending, approved, rejected.

A green “evidence complete” object must not imply that a government inspection passed.

## Steward's cloud computer and browser

The agent needs a runtime. Orders through supplier APIs do not require a browser. Ordinary web checkouts require a browser and an adapter capable of operating that checkout.

InsForge Custom Compute supports long-running Docker images. Package the worker and a Chromium/Playwright browser service as appropriate containers. Keep browser sessions isolated by owner. Expose only application tools for product search, quotes, cart preparation, approved checkout, screenshots and order-status checks.

This browser setup is a proposed architecture based on documented container support. A working browser, interactive screen stream and deployment recovery have not yet been verified on InsForge. The opening integration check must load our controlled demo shop, capture a screenshot and verify protected session save/restore before browser shopping becomes a demo dependency.

Custom Compute currently has no persistent volumes; a redeploy or configuration change can discard local writable state. Keep domain records and execution checkpoints in an external persistent backend, and store encrypted browser-session state and files in protected storage. Never put payment credentials in Supermemory or a visible browser trace. [Compute documentation](https://docs.insforge.dev/core-concepts/compute/overview).

Show browser actions or screenshots in the work timeline when useful. A full remote desktop UI is not required. If browser hosting cannot be verified early, use the supplier API for the first ordering flow and accurately describe the demonstration.

InsForge Sites can deploy the frontend through Vercel while tracking URLs and releases. This is separate from Custom Compute for long-running workers. [Sites](https://docs.insforge.dev/core-concepts/sites/overview).

## Supermemory integration

Supermemory's current documentation describes document ingestion, memory search, related-memory retrieval and static/dynamic profiles, organized by namespace. [Quickstart](https://supermemory.ai/docs/quickstart). It also offers a managed [memory MCP server](https://supermemory.ai/mcp/).

Use its SDK/API inside the worker for the application build. An explicit recall-and-save adapter gives us control over property scope, context size and which source-linked interactions are stored. The managed MCP is an alternative for an initial exploratory demo, not a second required integration.

| Context | Example content | Scope |
| --- | --- | --- |
| Owner profile | Communication preferences and recurring review routines, when supplied by the owner | Owner within the organization |
| Property history | Report requests, rejected evidence matches, resolved questions and decision explanations | One property within the organization |
| Shared lessons | Curated verification practices supported by earlier work | Explicitly shared within the organization |

The server derives the namespace from the authenticated organization and authorized property. It does not let a model select an arbitrary tenant. Shared lessons are deliberately promoted into the shared scope; property-specific evidence and approval conclusions do not automatically become portfolio-wide facts.

For every recalled item, retain or resolve its source event/document ID, property/component scope, observation date and source version. A remembered claim does not independently establish a current permission, deadline, legal requirement or approval.

Execution pattern:

1. A new event identifies the authorized owner and property.
2. Retrieve a small profile and query-relevant memories; load current work state from InsForge alongside them.
3. Resolve relevant source links and reconcile time-sensitive claims with current records.
4. Run the agent's tools and enforce state transitions in the application.
5. Commit the source event, evidence assessment and action outcome to InsForge.
6. Send a bounded interaction/outcome record to Supermemory through the outbox, using stable IDs for related conversations.
7. Later sessions retrieve relevant history and can update or forget outdated memories through controlled operations.

This adds contextual recall without making a semantic memory service responsible for task scheduling or transactional approvals.

Demo extension: in a fresh agent session, Steward recalls that a prior Cedar submission named Harbor's equipment. It checks the current Cedar requirement and includes the exact property and serial number in its next request. The UI shows the retrieved memory, date and source event. A portfolio lesson may suggest checking serials elsewhere, but each property's requirement and evidence are evaluated independently.

Memory ingestion is asynchronous. Seed a few explicitly labeled historical demo interactions before presentation and verify that memory/profile processing has completed. New inbound attachments continue through the main workflow even while memory indexing is pending. The current quickstart documents immediate processing as an optional mode with an extra operation charge; do not assume writes are instantly searchable. [Processing and readiness](https://supermemory.ai/docs/quickstart).

Keep the hackathon memory feature to profiles, scoped recall and source-linked writes. Broad Drive/Gmail synchronization and automatic nationwide rule ingestion are outside this build.

## Stripe: collecting payments and purchasing

There are two separate money flows:

| Flow | First implementation | Purpose |
| --- | --- | --- |
| Customer pays Steward | Stripe-hosted Checkout, initially in sandbox/test mode | Collect a property readiness-review or coordination fee |
| Steward buys for an owner | Link Agent Wallet spend request, owner approval and a one-time payment credential | Buy an approved replacement part or book an independent service |

Incoming service revenue is merchant revenue. It does not automatically become a customer wallet or an escrow balance that the agent can spend. The purchase flow uses the owner's separately authorized payment source.

The current Link Agent Wallet guide makes customer approval part of each spend request and lists agent-payment availability for US and Canadian customers. After approval, the wallet supplies a credential compatible with the seller: a Link Pay Token, a Shared Payment Token, or a one-time card credential. Do not present an application budget cap as a way to bypass Link approval. [Wallet guide](https://docs.stripe.com/agentic-commerce/agents/link-agent-wallet), [spend flow](https://docs.stripe.com/agentic-commerce/agents/link-agent-wallet/use-link-wallet-pay-online).

Link uses its own OAuth and SDK/API rather than the normal Stripe secret key. Keep financial credentials in the payment adapter; exclude them from model transcripts, Supermemory and ordinary action logs.

Stripe supplies the payment layer. The supplier's catalog, stock, checkout/API, shipping and order confirmation need a separate integration. Start with one explicitly labeled demo supplier or bookable service. Do not claim arbitrary hardware-store ordering on day one.

Concrete procurement demonstration:

1. Seed a fictional issue requiring replacement of a gauge in Cedar.
2. Steward checks the demo project specification and retrieves a compatible demo SKU from the supplier catalog.
3. Obtain a quote with the exact seller, quantity, item, tax, shipping, total and delivery estimate.
4. Create a proposal linked to the issue and component. The server checks the owner's configured property budget and permitted supplier.
5. Steward sends a Link approval URL through Inkbox. The owner approves the specific transaction in Link.
6. Retrieve the approved one-time credential and complete the supplier checkout or payment API.
7. Confirm the payment through verified Stripe events and confirm the order with the supplier. Preserve both references.
8. Update the 3D component to “replacement ordered” and attach the order/receipt.
9. Continue waiting for delivery and installation evidence. Reassess readiness only after the relevant evidence and review arrive.

For the hackathon, use Link test spend requests and a Stripe sandbox supplier payment. The published Link guide documents a test flag that returns test credentials without charging the underlying payment method. If Shared Payment Token access is unavailable, test the documented card-credential route against a sandbox checkout; if wallet access is blocked, keep a clearly labeled human-completed sandbox Checkout as the fallback. Do not represent the fallback as an autonomous wallet purchase.

The incoming-fee demonstration can use a separate Checkout Session for one review package. Mark the fee paid only after a verified successful payment event; a browser redirect alone is insufficient. Payment and vendor-order retries use stable idempotency keys.

Minimal procurement tools: search approved catalog, get quote, propose purchase, create spend request, check approval, place approved order and get order status. The server binds approval to the property, component, seller, SKU, quantity, currency and total. A changed price or item requires a refreshed proposal and appropriate renewed approval.

Start with collections and one test purchase. Marketplace payouts through Connect, real-money procurement, card-issuing programs and managed customer balances are later capabilities rather than prerequisites.

## MCP interface and agent experience

| Tool | Result |
| --- | --- |
| list_properties | Compact property summaries and available milestones |
| get_property_context | Scoped component graph, blockers and changes since a version |
| inspect_component | Equipment facts, evidence and spatial reference; optional camera image |
| evaluate_readiness | Required checks, unmet dependencies, source references and next actions |
| request_evidence | A permitted request, thread ID and waiting work-item ID |
| assess_evidence | A structured match or rejection with source-page references |
| propose_resolution | A validated state transition or a clear review requirement |
| get_work_status | Current work state and events after a cursor |
| recall_property_history | Authorized, bounded prior context with source references |

Expose the procurement tools only after the core property tools and authorization checks work. A payment success updates the order state, while evidence and official approval states remain independent.

Use resources for source documents and property manifests. Return a short summary plus resource links; load long documents and images only when requested. Include state versions, pagination and recoverable error codes.

For the first demo, camera evidence may be explicitly labeled, pre-rendered images from the synthetic scene. General live headless rendering is a stretch feature. The semantic component graph remains usable when the human 3D dashboard is closed.

Waits return a work-item ID and a waiting state. They do not leave an MCP request open for hours or repeatedly call the LLM. Inbound email resumes the stored work.

## Laws and source handling

Start with one jurisdiction and a small reviewed rule pack. Each rule records jurisdiction, document title, section/page, source URL, edition/effective date, applicability and the last review date. Project requirements remain distinct from statutory requirements.

A source citation alone does not establish applicability. Permit date, approved plans, occupancy/use and project scope can affect which requirements apply. Unknown or conflicting applicability becomes a review item.

The first demo uses a few official process references and labeled project requirements. It does not claim nationwide code coverage or automatic construction certification.

## Human experience

Keep four main surfaces:

1. Portfolio: three buildings, target dates and the few blockers that matter.
2. Property world: walk/orbit the room; select components; follow markers to evidence.
3. Work timeline: actions, conversations, waiting replies, purchase proposals, orders, pending review and browser screenshots when available.
4. Evidence and sources: originals, page citations, assessments, purchase receipts and approval records.

The strongest visual moment is a reply becoming a spatial change: the email appears in the timeline, the camera focuses on the related pump, the document is linked, and its evidence status updates. Use a clean professional shell, realistic industrial materials, smooth camera transitions and labeled component states. Show counts derived from actual checklist items instead of an unexplained AI readiness score.

Adding a property repeats onboarding, document ingestion, template instantiation and session creation. Uploading a PDF does not automatically reconstruct an accurate building; importing real BIM/CAD/scans is a later capability.

## Three-minute demonstration

1. Open the portfolio and ask an external MCP client: “Which property can be prepared for handover first? Resolve the missing evidence within my mandate.”
2. Steward identifies Cedar's missing report and highlights its pump.
3. Show the actual outbound email and waiting state.
4. A teammate replies with a PDF for Harbor. Steward identifies the mismatch and asks for the correct property/equipment report.
5. Reply with Cedar's correct PDF. The workflow resumes without a second “run” click, links the cited evidence and updates the component.
6. Show the review packet and the still-pending authoritative approval.
7. Ask for other properties using the same equipment; show a scoped follow-up work item rather than copying the first property's conclusion.

Clearly label fictional property data, synthetic scene images and any replayed events. Keep a recorded backup of the live email sequence.

For the Stripe track, add a short purchasing branch: the agent proposes a replacement gauge, sends an approval link via Inkbox, completes a test purchase and pins its receipt to the equipment. Show “ordered” as a distinct state from “installed” and “approved.”

## Build order and completion criteria

| Build block | Deliverable |
| --- | --- |
| Opening integration check | Verify InsForge records, model tool/vision calls, worker persistence and browser feasibility; send/receive one Inkbox email, check the phone channel, call one deployed MCP tool and confirm Stripe sandbox/Link test access |
| Hours 1–4 | Three property manifests, component IDs, evidence storage and state model; verify a scoped Supermemory write and recall |
| Hours 4–8 | Agent tools and one working property readiness path through an external client |
| Hours 8–12 | Threaded email, attachment ingestion, waiting and resumption |
| Hours 12–16 | One polished room template, portfolio view and live state updates |
| Hours 16–19 | Wrong-document branch, fresh-session memory recall, one test purchase, review packet and targeted verification; portfolio related-equipment query is a stretch if time remains |
| Remaining time | Styling, demo rehearsal, recovery checks and recording |

Run the sequence in this order even if the available clock time is shorter. One fully working property loop is the first completion milestone.

Necessary verification:

- Correct evidence updates the intended component and preserves its citation.
- A report for the wrong property or serial does not resolve the blocker.
- A duplicate webhook does not repeat the action or send another email.
- Waiting work resumes after a worker restart using the same pinned runtime version.
- Property-scoped credentials cannot access another property's private files.
- The MCP flow works with the dashboard closed.
- Evidence completeness and official approval remain separate.
- A fresh session recalls the seeded property history and resolves its source event.
- Memory scope prevents another organization's history from being retrieved.
- An outdated or corrected memory cannot override a newer authoritative property record.
- Delayed or failed memory indexing does not prevent the live evidence workflow from completing.
- A service Checkout payment and a procurement purchase are recorded as separate flows.
- Expired, denied or changed purchase approvals cannot authorize payment.
- Duplicate payment events or retries do not create a second charge or vendor order.
- A paid order does not mark equipment delivered, installed or approved.
- Test purchases never use live payment credentials, and payment secrets never enter memory or ordinary logs.
- The deployed worker recovers waiting work after a redeploy using external checkpoint persistence.
- If browser shopping is shown, its demo session restores after redeploy and checkout produces a verifiable supplier order.

The hackathon build is complete when a real MCP-driven request produces a real email, a real reply with an attachment resumes the work, and the 3D view shows the resulting evidence state with an audit trail.

The commerce branch is complete when a sandbox service fee is confirmed separately from an owner-approved test purchase, and the vendor order, payment reference and equipment receipt remain linked without marking the physical work complete.

