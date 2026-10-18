# Backend deviations from REALITY-CONTRACT.md

Each entry says what the contract asks for, what was implemented, and why.

1. **`cryptography` pin.** The brief asked for `cryptography==45.0.5`. The venv already carried `cryptography==50.0.2` as a
   dependency of the pinned `inkbox==0.7.19` (which requires `>=43.0`). `requirements.txt` pins `50.0.2` so the install stays
   consistent instead of downgrading a working SDK dependency. `pillow==13.0.0` (already present via reportlab) is pinned
   explicitly because `verify.py` reads EXIF with it.

2. **Every attest is signed, not only accepted ones.** The contract text says only `accepted` "signs an Attestation", but the
   `Attestation` type carries `verdict: Verdict` with all three values and `WorkItem.verdicts[].attestationId` must point at
   something. The backend therefore stores and signs an attestation for every submission (verdict inside the signed payload) and
   writes a Fact, updates the component, resolves the work item and emits the `fact` Change only for `accepted`. A signed
   rejection is still a useful receipt and lets integrity reuse detection cover rejected photos.

3. **Component `status` on an accepted fact.** The contract says accepted facts update the component "status + lastFactAt".
   `status` is also the requirement roll-up recomputed by inspections. The backend sets `lastFactAt`, `factStatus: "known"` and
   `status: "verified"` unless the component is in `issue`; a later inspection recompute may reset `status` from requirements.

4. **Owner decision fact attribute.** The contract writes "a condition fact with `source.kind='owner'`". Writing the decision
   into the work item's own attribute (e.g. `pressure_bar = "hold"`) would corrupt later resolves, so the fact is written under
   attribute `owner_decision` (class `condition`, TTL 86400 s, value = the decision text). `owner_decision` is not in the spec
   table and bypasses spec validation for this one source kind.

5. **Change type for unrouted inbound.** The `Change.type` enum has no message type; unrouted inbound messages emit a Change of
   type `dispatch` whose `refId` is the `inbound_unrouted` record id and whose summary starts with "Unrouted inbound".

6. **Footprint radii.** The contract lists tank 1.0, exchanger 0.9, panel 0.5, pump 0.6, duct 0.8, default 0.6. Two extra
   entries were added: `door` and `light` get radius 0 (an opening and a ceiling luminaire do not block a floor corridor);
   everything else, including sensors and gauges on the wall, uses the table or the 0.6 m default exactly as written.

7. **Inbound secret header (per docs/INKBOX.md).** `/api/inbound/inkbox` requires `X-Steward-Inbound-Secret == STEWARD_INBOUND_SECRET` as specified;
   because Inkbox cannot set custom headers but can send `Authorization: Bearer <auth_token>` on a subscription, the same
   secret is also accepted as a bearer token. If `INKBOX_WEBHOOK_SIGNING_KEY` is set the `X-Inkbox-Signature` HMAC is verified
   as well. The `/api/inbound/inkbox` path is exempt from the optional `STEWARD_API_TOKEN` middleware because it carries its
   own secret.

8. **Provider-unavailable dispatches.** The contract specifies `providerRef: null` plus a reason only for level 3 calls. The
   backend applies the same honest pattern to every channel that cannot be sent (no Inkbox, gate closed, recipient not
   allowlisted, provider error): the dispatch is recorded with `providerRef: null` and a body that starts with
   `[not sent: <reason>]`. The initial dispatch additionally falls back to the `local` channel so the local replay path works.

9. **Scheduler ladder thresholds.** The contract defines the ladder but not when the scheduler climbs it. Auto-escalation
   fires at 50 %, 70 %, 85 % and 95 % of the work item's deadline window (`STEWARD_WORK_DEADLINE_SECONDS`, default 7200) for
   levels 1–4; expiry at 100 %. Manual `escalate` can jump to any level at any time.

10. **Time-check lower bound without a work item.** The contract defines the window relative to `workItem.createdAt`. For an
    ad-hoc `attest` with no work item the lower bound is `now - TTL(class)` (none for identity) so a four-month-old document can
    be attested but a stale reading cannot.

## Addendum 2 (REALITY-CONTRACT-2.md)

11. **Operator keeps the direct reality verbs.** The addendum says the Operator "cannot write facts, dispatch, or decide",
    but the MCP's existing `resolve` / `attest` / `escalate` tools, the dashboard's owner-decision control and the demo eval
    all call those endpoints as the operator (the default actor when `X-Steward-Actor` is absent). The authority table
    therefore enforces the level restrictions on Atlas, the Wardens, Runner and the owner, while the Operator's direct verbs
    remain the single-agent path and missions are the four-agent path (README "Four agents and authority").

12. **Default restart set is one representative asset per kind.** The addendum lists the restart set per kind; the live demo
    and `evals/mission-workflow.json` start a mission with only `{siteId, goal, budget}` and expect one unknown
    (`P-101.pressure_bar`). The default therefore covers P-101, V-501, DB-401, FE-1001 and D-1101 (six attributes);
    `assetTags` narrows it and `["all"]` covers every asset of those kinds.

13. **Extra demo seeds and seed refresh.** To make that one-unknown mission reproducible the demo site is also seeded with
    `DB-401.status = normal`, `FE-1001.pressure_ok = yes` and `D-1101.closed = yes` (patrol, `seed:patrol-initial`), and on
    startup a seeded demo observation past its TTL is re-seeded as `seed:patrol-refresh` only while every fact for that
    attribute is itself a seed. Real facts are never overwritten.

14. **Evidence is verified on the inbound path, not by the Warden handler.** Step 3 reads "field agent hands it to the site
    agent → site agent runs verification → attest". Phase 1's `/api/inbound/*` already runs the six checks and signs the
    attestation (contract behaviour that had to stay); the Runner's reply therefore carries the attestation ID and verdict,
    and the Warden records the verdict as its step. The verifier and signing key are the site's.

15. **Change types `a2a` and `eval`.** `a2a` is the addendum's extension; `eval` was added for eval runs because the
    addendum asks for a Change without naming a type. Changes also omit `assetTag` instead of sending `null`, which the
    MCP's schema rejects.

16. **Attestations re-signed by the site-ID migration.** Renaming `propertyId` inside a signed attestation invalidates its
    signature, so migrated attestations are re-signed with the local key and keep `_resignedFrom` (private). The backend is
    the signer; nothing external relied on the old bytes.

17. **Inkbox transport delivers in-process too.** Both ends of every task are this process, so a task sent through Inkbox
    (real `SendMessage`, real `a2a_reply`) is also handed to the handler immediately; webhook echoes are deduplicated by
    provider task/message id. Without the sending identity's agent-scoped key the task is stored as `transport: local` with a
    `providerError`; it is never reported as sent.

18. **SuperSplat credits.** The viewer and its `meta.json` expose no author field, so the seed credit names the scene id and
    "its SuperSplat author (handle as shown on superspl.at)" rather than a handle we could not retrieve; the capture note is
    verbatim from the addendum.

19. **Environment hygiene.** The repository root `.env` is a template whose values are inline comments; the backend now
    strips inline comments and treats empty values as unset for `STEWARD_*`, `INKBOX_*`, `SUPABASE_*`, `STRIPE_*`,
    `INSFORGE_*`, `SUPERMEMORY_*`, `ARMATURE_*` before any adapter (including the Inkbox SDK, which reads `INKBOX_BASE_URL`
    and `INKBOX_VAULT_KEY` itself) sees them. Dispatch channels are `local` unless key, identity, the external-messages
    gate and a validated, allowlisted recipient all exist.

20. **Backend-only fields are not mirrored.** `simulated`, `ownerDecision` and dispatch `note` have no column in
    `supabase/migrations/0001_reality.sql`; the mirror drops them so PostgREST upserts keep succeeding.
