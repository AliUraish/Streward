# Steward: a reality layer for industrial agents

Written Oct 17 2026, 17:30. Submissions Oct 18 10:00. Replaces the earlier framing in STEWARD-BUILD-BRIEF.md. The engine stays; the domain is a plant and the customer is an agent.

## 1. What it is

Agents that run factories, plants and sites are blind and handless. Most equipment has no sensor. Nobody can ask a pump what its pressure is. An agent planning a restart, a procurement, or a shutdown has to guess, and when it guesses wrong, it has no receipt.

Steward is the reality layer those agents plug into. An agent asks for a fact about a physical asset. If the plant's record knows it and it is fresh, the agent gets the value with a signed proof. If not, Steward turns a human into a sensor: it dispatches a technician to that exact spot, verifies what comes back against the asset's record, geometry and specification, pays the technician from the agent's budget, and calls the agent back with a fact it can cite. Any agent can contribute what it learned, and any agent can check another agent's proof without redoing the work.

One line: **"Agents ask the plant. The plant answers with proof, or sends someone to get it."**

## 2. Why an agent wants it

| The agent's want | What Steward gives it |
| --- | --- |
| Not to guess | `resolve` returns known, stale, unknown or conflicting, never a made-up value |
| Not to be blamed | Every fact carries an attestation: signed, hash-chained to the evidence, the verdict and the verifier version |
| Not to redo another agent's work | `attest` writes verified observations into a shared record; `check` lets any agent trust them |
| To act without a body | Unknown facts trigger a human dispatch, paid from the agent's own budget, with zero tokens spent waiting |
| To stay inside its mandate | Budget, scope, allowlist and freshness rules are enforced in code, outside any prompt |

## 3. The plant

Reuse the existing scene as **Harbor Works**, one plant room with 24 tagged assets across mechanical, hydronic distribution and electrical subsystems. Each asset has a stable tag (P-101, V-204, G-117), world coordinates, a specification sheet (operating range, required certificates), requirements, evidence, and now facts.

A fact has an attribute, a value, a source, `observedAt`, a TTL and provenance. TTLs are per attribute class:

| Attribute class | Example | TTL |
| --- | --- | --- |
| Reading | gauge pressure, temperature, valve position | 1 hour |
| Condition | leak, corrosion, guard fitted | 24 hours |
| Document | commissioning certificate, test report | 365 days |
| Identity | serial, nameplate | never expires |

Cedar and Juniper remain as two more sites to show the layer is multi-site. The demo touches Harbor only.

## 4. The three calls

| Call | Input | Output |
| --- | --- | --- |
| `resolve` | `siteId, assetTag, attribute, maxAge?, budget?` | `{status: known\|stale\|unknown\|conflict, value?, unit?, observedAt?, attestationId?, workItemId?, cost?}` |
| `attest` | `siteId, assetTag, attribute, value, evidence (file or reference), observedAt` | `{verdict: accepted\|rejected\|needs_clarification, reasons[], attestationId?}` |
| `check` | `attestationId` | `{valid, siteId, assetTag, attribute, value, observedAt, evidenceHashes[], verifier, signature}` |

Resolver policy, in order: known and inside `maxAge`, return it. Stale, re-dispatch if `budget` allows, else return stale with the old attestation. Unknown, dispatch if `budget` allows, else return unknown. Two accepted facts disagree inside the window, return `conflict` with both attestations and open a clarification.

Supporting calls: `get_changes(siteId, sinceVersion)` diff; `subscribe(siteId, callbackUrl)` A2A callback on resolution; `get_receipt(workItemId)`; `escalate(workItemId, level)`; `query_clearance(siteId, from, to, widthM)`; and the existing reads (`list_sites`, `get_site_context`, `list_assets`, `inspect_asset`, `search_requirements`, `search_documents`, `recall_memory`, `export_report`).

Resources: `steward://guide`, `steward://schema`, `steward://sites/{id}/context.min` under 400 tokens. Prompt: `prove-before-signing(siteId, task)`. Every error returns `{code, recovery}`.

## 5. Dispatch: turning a human into a sensor

When `resolve` cannot answer, the orchestrator opens a work item and sends a task card through Inkbox to an allowlisted technician:

```
Harbor Works, plant room, north wall.
Asset P-101, primary circulation pump, tag plate on the motor housing.
Need: pressure gauge reading. Photograph the gauge with the tag plate visible.
Expected range 1.5 to 3.5 bar. Reply to this thread. Pays $0.50 on verified proof.
Reference HW-P101-PRESSURE-0042
```

Location and neighbours come from the scene graph. Expected range comes from the spec sheet. The reference is the work item ID, and routing is by thread, then by reference, then by sender. One Inkbox identity serves every site.

Escalation: re-send at half the deadline, then email; overdue or safety-relevant, place a voice call from the Inkbox number and log the commitment; outside the mandate, one-tap question to the plant owner.

## 6. Verification engine

Evidence passes only if every check passes. Each check writes a reason that ends up in the attestation.

| Check | Rule |
| --- | --- |
| Scope | Same `siteId` and `assetTag` as the work item. Wrong site is a hard reject. |
| Identity | Tag plate or serial in the photo or document matches the asset record. OCR on photos, text extraction on PDFs. |
| Geometry | The task card named a position; the returned tag must be the asset at that position, not a sibling two metres away. |
| Plausibility | Reading falls inside the spec range, or outside it with a confirmed re-read. 9.8 bar on a 3.5 bar pump is `needs_clarification`, not `accepted`. |
| Time | Captured inside the work item window, by EXIF when present, else provider receipt time. |
| Integrity | SHA-256 stored; a file reused across work items is flagged. |
| Verdict | `accepted` writes the fact, signs the attestation, updates the twin and releases payment. Anything else does not. |

Attestation: `{id, siteId, assetTag, attribute, value, observedAt, evidenceHashes, checks[], verifierVersion, signature}` signed with a server Ed25519 key. `check` verifies the signature and returns the record. Another agent can trust it offline.

## 7. Money and mandate

Each requester agent gets a budget per site, set by the owner. `resolve` with a budget may spend it on dispatch. Payment is held against the work item in Stripe test mode and released only on `accepted`, with the work item ID as the idempotency key, so a duplicate webhook cannot pay twice. The receipt carries the Stripe reference, the wait time, and tokens spent versus what polling would have cost.

## 8. The demo, three minutes

Left screen: Claude Code with the Steward MCP connected. Right screen: a teammate's phone. In the room, two labeled props with tag plates P-101 and P-102 and a dial.

**0:00** One instruction to the agent: "Clear Harbor Works for restart after the shutdown. Sign off nothing you cannot prove. Budget $5."

**0:15** The agent, on its own, calls `resolve` for each restart item. Commissioning certificate for P-101: `known`, attested, 4 months old, inside TTL. Isolation valve V-204 position: `known`, 40 minutes old. Pressure on P-101: `unknown`, no reading ever recorded. The agent asks for it with budget.

**0:40** Steward dispatches. The teammate's phone gets the task card. The agent says "waiting for a reading on P-101" and stops. No tokens burn.

**1:05** The teammate photographs P-102 by mistake. Webhook. Scope passes, identity fails. `rejected`, reason "tag plate reads P-102, work item is P-101, P-101 is two metres west with the blue valve." Steward replies on the thread. The agent sees it through `get_changes` and keeps waiting.

**1:30** Right photo. Tag matches, position matches, 2.4 bar inside 1.5 to 3.5, timestamp inside the window. `accepted`. Fact written, attestation signed, $0.50 test payment released, receipt attached. Callback fires. The agent finishes the restart checklist, each line carrying an attestation ID.

**2:05** A second agent, or the same one in a new session, calls `check` on the pressure attestation and gets the signed record back. It did not redo the work.

**2:25** Open the twin. Camera flies to P-101, the photo is pinned to the gauge, the timeline shows dispatch, rejection, acceptance, payment, signature.

**2:45** Close: "Nobody told the agent to use Steward. It was told not to lie, and reality was one tool call away."

Backup: record 0:40 to 1:30 tonight. If no Inkbox key by 19:30, inbound replays saved messages through the same webhook, labeled as replay.

## 9. Tracks

| Track | What they see |
| --- | --- |
| Primitive | An identity that asks humans, receives attachments, rejects and re-asks, and coordinates asynchronously with zero polling |
| Inkbox | One persistent identity with iMessage, SMS, email and a scripted voice call, acting for agents |
| Manufact | An MCP whose customer is an agent: three verbs, diff reads, callbacks, signed attestations, typed recovery, hosted on Manufact |
| Stripe | An agent pays for the resource it needs, inside an owner-set budget, released only on verified proof |
| Armature | Pure AX |
| Blaxel | `context.min` and a signed attestation are things no human wants to read |

## 10. Build order, 17:30 Sat to 10:00 Sun

| When | Build | Done when |
| --- | --- | --- |
| 17:30–19:30 | `facts`, `work_items`, `attestations` tables; TTL classes; spec ranges on the 24 assets; `resolve` and `attest` over the existing evidence validation; Ed25519 signing; `check` | `resolve` returns known for a seeded fact, unknown for pressure; `attest` with a wrong tag is rejected with reason |
| 19:30–21:30 | `CommsAdapter` on Inkbox: task card builder from scene graph and spec, send, inbound webhook with attachment, thread routing; dispatch from `resolve` | A real message leaves and a photo reply lands on the work item |
| 21:30–23:00 | Verification engine: tag OCR, geometry, plausibility, time, hash; `get_changes`; `get_receipt`; `subscribe` | Wrong-tag photo rejected, right photo accepted, attestation signed, callback delivered |
| 23:00–00:00 | Stripe test hold and release with idempotency; budget enforcement; `escalate` with voice call if hosted voice works | Payment released once on `accepted`, duplicate webhook pays nothing |
| 00:00–01:00 | Twin: photo pinned to asset, timeline, attestation badge; `context.min`; schema; prompt; deploy gateway to Manufact | Dashboard-closed run from Claude Code end to end; judges' dashboard shows the server |
| 01:00–08:00 | Sleep | |
| 08:00–09:30 | Git init, public repo, README to this pitch, rehearse twice, record backup | |

## 11. What stays honest

Fictional plant, labeled props instead of real pumps, rule-based verification unless a vision model is configured, one real message thread, one real photo, one real test payment, one real signature. Say all of it on stage. Steward does not certify equipment, replace an engineer's sign-off, or state any statutory requirement.
