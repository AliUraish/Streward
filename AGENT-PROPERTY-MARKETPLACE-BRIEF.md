# Steward — archived marketplace proposal

Rejected direction, October 17, 2026: the user explicitly does not want a marketplace. Retained only as design history; do not implement this proposal. The next direction should narrow the private property-agent workflow. The current Steward implementation follows the private property-agent workflow instead.

## The customer and product

The customer is a booking or mission agent. It needs a dependable way to discover, inspect, reserve, access and manage physical space as part of a larger task. Each property has a host agent that knows its current condition, equipment, availability and permitted booking terms.

The operating workflow is agent-to-agent after initial account, policy and funding setup. People may own or ultimately use the space; they do not need to operate the search, negotiation, reservation or recovery flow in the demonstration.

Interpret “Airbnb for agents” as physical spaces transacted through an agent interface. Agents renting cloud computers would be a different product: an agent-workspace marketplace. This proposal preserves the physical property and functional 3D world.

Pitch: “Agents can book space they can verify, receive scoped access, and recover automatically when conditions change.”

The previous broker dashboard becomes an observer and operational audit view. The core product is the property contract and complete machine-to-machine booking lifecycle.

## Why an agent would want it

An agent needs explicit capabilities, fresh condition data, complete prices, stable identifiers, reliable inventory, scoped access and a way to recover from failure.

| Agent need | Product behavior |
| --- | --- |
| Find a space that meets a mission's constraints | Search typed capabilities and availability |
| Check whether a listing's claims are current | Retrieve dated, source-linked condition evidence |
| Resolve spatial uncertainty | Query the scene graph, geometry and selected camera views |
| Reserve without racing another customer | Atomic inventory hold with expiry and a fixed offer |
| Complete a delegated transaction | Validate an agent mandate and payment authority |
| Use the booked space | Issue a time-scoped access lease |
| Handle a condition change | Notify the buyer agent and execute the agreed recovery policy |
| Continue across sessions | Persist work state and recall relevant history |

Stripe already documents agent-facing booking APIs and MCP operations. The proposed differentiation is inspectable property condition and automated continuity after booking. [Agent service-booking documentation](https://docs.stripe.com/agentic-commerce/sellers/use-cases/booking).

## Participants

1. **Guest agent:** an external travel, operations or field-task agent. It has a mission, deadline, budget and delegated capabilities.
2. **Host agent:** one property-scoped instance per listing. It can answer questions, provide evidence, offer permitted terms, notify customers and arrange policy-compliant alternatives.
3. **Marketplace services:** deterministic inventory, authorization, payment references, access leases and event delivery.

One host-agent implementation can serve all three properties using isolated sessions. The guest agent is a separate actor with its own private requirements and memory. Agents do not need to expose their internal reasoning or private maximum budget to one another.

The reference buyer is only a demonstration client. An existing external MCP-compatible agent must be able to use the same marketplace.

## The bookable property contract

A listing exposes:

- Property, room and component IDs, plus scene version.
- Bookable time windows and atomic reservation rules.
- Capabilities such as working power, network availability, quiet zones and equipment.
- Geometry-derived facts such as room dimensions, object positions and a route's available clearance.
- Current condition, unresolved issues, evidence references and observation times.
- An itemized price, quote expiry and permitted booking terms.
- Access scope and validity period.
- Modification, cancellation and condition-failure recovery rules.

Unobserved or stale facts return an explicit unknown or evidence request. A host agent cannot manufacture a fresh inspection or promise unverified capabilities.

Real applicability and safety claims require appropriate physical evidence. Geometry in the hackathon demo describes a synthetic scene, not a certified real property.

## The 3D world has an operational role

Create three fictional bookable spaces with a shared modular room system. Each has a host agent and a distinct current condition.

The scene graph is shared with the agent's tools. Equipment IDs, object positions, obstruction state and condition records drive both the rendered view and query results.

Demonstrate one genuine spatial query: test a requested route through the modeled room and report which object obstructs it. Highlight that same object in the viewer. Camera images are optional evidence; compact semantic results are the default.

A mechanical or service area can explain a property's operational condition. For example, a power or equipment issue can make a work zone temporarily unsuitable.

The visual app shows the 3D properties, buyer and host actions, offers, reservation holds, payment results and access leases. It can animate a rejected route, an accepted room and a later relocation.

## Reference mission and inventory

Use an illustrative mission:

“Reserve a workspace for the field team's task from 10 AM to 2 PM. It needs three work points, working power and a clear entry route. Total price must be within the delegated budget. If a required capability fails, obtain an equivalent permitted replacement.”

These are task constraints, not invented legal standards.

| Property | Scene and condition | Expected decision |
| --- | --- | --- |
| Cedar | Lowest price, but a modeled obstruction blocks the required route | Reject with the object ID and visible spatial evidence |
| Harbor | Meets the mission and has current supporting evidence | Quote, hold and book |
| Juniper | Meets the mission and is eligible as a replacement | Offer under the agreed recovery policy if Harbor becomes unsuitable |

For the first build, all three properties belong to one fictional operator and one Stripe merchant account. Distinct host agents do not require implementing real multi-merchant payouts.

Use the same accepted price for Harbor and Juniper in the recovery demo. A relocation within the same operator can transfer the booking's payment allocation without silently creating a second charge. Any price change outside the delegated terms is a separate authorization case.

## Complete operating lifecycle

1. A mission event activates the buyer agent with a bounded mandate and test payment authority.
2. The buyer searches spaces through MCP and gets compact candidates.
3. It asks host agents for current condition and spatial evidence.
4. It rejects Cedar after the route check and requests an offer for Harbor.
5. Harbor's host agent returns an itemized, expiring offer inside its permitted terms.
6. The buyer creates an atomic hold. The platform validates the mandate, offer version and availability.
7. The payment adapter completes a Stripe sandbox payment. Verified payment and booking state produce confirmation.
8. The platform issues an access lease to the buyer. Door access is explicitly simulated for this demo.
9. A labeled simulated condition event changes Harbor's power availability.
10. Harbor's host agent sends a machine-readable incident notification and an Inkbox notification to the buyer agent.
11. The buyer checks the agreed recovery policy and verifies Juniper against the same mission constraints.
12. The agents confirm the permitted replacement. The platform updates inventory and payment allocation, revokes the old access lease and issues a new one.
13. Both agents save the outcome, source events and useful scoped history. The UI shows the reason for relocation and the resulting reservation.

No person clicks the booking, accepts the alternative or updates a component during this sequence. Initial setup and the policy under which the agents act remain explicit.

## Agent-facing tools

| Tool family | Purpose |
| --- | --- |
| discover_spaces | Search availability, task constraints and complete prices |
| inspect_space | Read current capabilities, condition and evidence freshness |
| query_spatial_requirements | Evaluate selected geometric constraints and return witnesses |
| request_offer | Obtain permitted terms and an expiring quote |
| hold_reservation | Atomically reserve an offer for a limited time |
| commit_booking | Validate payment authority and confirm the booking |
| get_access_lease | Retrieve appropriately scoped access for a confirmed reservation |
| get_changes | Read condition and booking events after a cursor |
| resolve_booking_issue | Request a permitted modification, replacement or cancellation |
| complete_booking | Close the reservation and return its records and receipt |

Use typed errors such as stale condition evidence, expired offer, unavailable slot, unsupported requirement and additional payment authorization required. Return the next valid action.

Condition queries are not an authority to change the physical world. Repairs need actual services and evidence; a model cannot mark physical work done by changing a status field.

## The selected stack

| Service | Function in this product |
| --- | --- |
| InsForge | Property and scene records, inventory holds, access leases, events, auth, worker hosting, model gateway and live UI updates |
| Manufact | Hosted property marketplace MCP, tool inspection, session traces and external-agent testing |
| Inkbox | Stable host and guest identities, asynchronous notifications, replies and attachments |
| Supermemory | Scoped history for hosts and the buyer; relevant preferences and earlier incident outcomes |
| Stripe | Sandbox booking payments and receipts; later permitted refunds and marketplace payment capabilities |

Keep critical authorization, current availability and booking state in transactional records. Recalled memory cannot override them.

The browser and “own PC” idea becomes optional for operating external legacy services. Our marketplace's complete primary workflow is headless through MCP. InsForge Custom Compute hosts the agents, with external persistence for checkpoints because its containers currently lack persistent volumes. [Compute documentation](https://docs.insforge.dev/core-concepts/compute/overview).

## Payments and the no-human operating loop

For the demo, initialize a delegated test budget and payment source before the run. The server enforces permitted transactions, amounts and duplicate prevention. Stripe charges are test transactions.

The earlier Link Agent Wallet path requires customer approval for spend requests, so it should not be described as an unattended payment flow. A production design needs an appropriate previously authorized payment arrangement and must handle any issuer authentication request. Saved off-session payment methods require the customer's specific consent; they do not guarantee that every payment can finish without interaction. [Link spending flow](https://docs.stripe.com/agentic-commerce/agents/link-agent-wallet/use-link-wallet-pay-online), [saved-payment consent](https://docs.stripe.com/payments/save-and-reuse).

Do not use a fictional agent persona as an alternative to legitimate payment authority. The hackathon claim is an autonomous operating workflow within a preconfigured mandate, demonstrated with sandbox money.

## Scope for the hackathon

Build:

- Three synthetic spaces and three property-scoped host agents.
- One external reference buyer agent.
- One spatial constraint with real computation against the synthetic scene.
- Discovery, offer, atomic hold, test payment, confirmation and simulated access.
- One asynchronous condition incident and one automatic replacement.
- Visible source-linked memory recall and event traces.
- One observer UI with the live 3D world and transaction timeline.

Real email or agent notifications and real Stripe sandbox API calls should be distinguished from synthetic property inventory, condition feeds and door access.

Later capabilities include live smart-lock/sensor integration, additional jurisdictions and rule packs, multi-owner payouts, real-world repair procurement and richer negotiation.

## Build order

1. Verify infrastructure access, agent execution persistence, an external MCP call and one sandbox payment.
2. Build the shared property/scene manifest and three distinct fixtures.
3. Implement discovery, inspection, one spatial check, offer and hold.
4. Complete booking, test payment and simulated access.
5. Add host/buyer identity, asynchronous incident handling and replacement.
6. Add scoped memory and the 3D observer view.
7. Verify stale facts, conflicting holds, duplicate events, expired offers, budget bounds and lease revocation.
8. Rehearse and record the run with the dashboard closed, then open the observer view to show the result.

Acceptance test: an external agent can discover, verify, book and recover from a property failure through our MCP interface while no person operates the application.
