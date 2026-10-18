# Inkbox for Steward

Inkbox is the persistent identity Steward uses to turn a human into a sensor: the task card goes out by SMS, iMessage or email from one agent identity, the technician's reply (with photo) comes back to the backend through a signed webhook, and the escalation ladder can place a voice call from the same number. The same identity's **tunnel** is the public URL that lets Manufact (hosted MCP) and Inkbox webhooks reach the laptop.

Everything below was read from https://inkbox.ai/docs (llms index https://inkbox.ai/docs/llms.txt) and from the installed SDK `inkbox==0.7.19` in `backend/.venv/lib/python3.12/site-packages/inkbox/` on 2026-10-17. Items marked **unverified** could not be confirmed from those sources.

## 1. Plan needed

From https://inkbox.ai/pricing:

| Plan | Price | Identities | Phone | What Steward can do on it |
| --- | --- | --- | --- | --- |
| Free | $0 | 3 | none listed | Email send/receive, tunnel, iMessage via the **shared router** only (recipient must text `connect @<handle>` to Inkbox's router number first; "up to 2,000 iMessages/month, 3 unique recipients at a time"). No SMS, no voice. Outgoing mail carries a "Sent via Inkbox" footer. |
| Developer | $30/mo | 10 | 1 dedicated VoIP number | SMS/MMS (300/mo) and 30 call minutes per number, U.S./Canada. **This is the minimum plan for the SMS + voice demo.** |
| Startup | $200/mo | 100 | 9 VoIP + 1 dedicated iMessage number | Dedicated iMessage line (recipients need not initiate). |

Overage: "$0.03 per SMS/MMS … $0.03 per call minute (U.S. and Canada)". Call-minute packs (250 min / $7) exist on paid plans only.

SMS gotchas that affect the demo (https://inkbox.ai/docs/capabilities/phone.md and https://inkbox.ai/docs/api/phone/texts.md):

- "US and US territory recipients must text `START` to one of your numbers before you can message them." A send to a number that has not opted in returns `403 recipient_not_opted_in`. **Have the teammate text START to the Steward number before the demo.** Writing opt-ins via API requires your own 10DLC campaign (`409 customer_campaign_required` otherwise).
- A newly provisioned number returns `409 sender_sms_pending` "until its 10DLC registration propagates (about 10-15 minutes)". Wait for the number's `sms_status` to be `ready`.
- Default campaign cap: 100 recipient sends per number per rolling 24 h.
- Inbound MMS media arrive as presigned URLs that expire after 1 hour; the backend must download the photo immediately (it hashes the bytes for the integrity check anyway).

## 2. Identity, API key, phone number

1. Console https://inkbox.ai/console → create an organisation → **API keys** → create an **admin-scoped** key (admin keys "can't be created through the API. Use the Inkbox Console"). Contact rules and webhook signing-key rotation need the admin key; the backend can run entirely on it for the hackathon.
2. Create one identity for all three sites (the contract says "One Inkbox identity serves every site"). Python, using the backend's venv so no extra install is needed:

```sh
cd backend && .venv/bin/python - <<'PY'
import os
from inkbox import Inkbox
inkbox = Inkbox()                       # reads INKBOX_API_KEY
identity = inkbox.create_identity("steward-harbor",
    display_name="Steward",
    description="Reality layer for industrial agents. Sends task cards to technicians and verifies replies.",
    phone_number={"type": "local"})     # Developer plan or above; omit on Free
print("handle:", identity.agent_handle)
print("email:", identity.email_address)
print("phone:", identity.phone_number and identity.phone_number.phone_number)
print("tunnel:", identity.tunnel and identity.tunnel.tunnel_name, "-> https://%s.inkboxwire.com" % identity.agent_handle)
PY
```

   `create_identity(agent_handle, *, display_name, description, imessage_enabled, …, tunnel, phone_number, …)` "Atomically provisions the linked mailbox and tunnel as part of the same request." Handle rules: 3–63 chars, lowercase letters, digits, hyphens; it cannot be changed later and is also the tunnel name. The mailbox is `<handle>@inkboxmail.com`, the tunnel `https://<handle>.inkboxwire.com`.
   If you created the identity without a phone, add one later: `identity.provision_phone_number(type="local", state="CA")`.
   The identity's `phone_number` object field name shown above (`.phone_number`) is **unverified**; print `identity.phone_number` and read it.

3. (Optional, Free plan only) enable iMessage on the identity (`imessage_enabled=True`) and have the recipient text `connect @steward-harbor` to the router number shown in the console. Pre-reply iMessages are limited to three, ≤159 chars, "no phone numbers, links, or media", so the task card must be short and the photo arrives only after the contractor replies first.

## 3. Env vars (`backend/.env`)

```dotenv
INKBOX_API_KEY=                       # admin-scoped key from the console; SDK reads this name itself (inkbox/_config.py)
INKBOX_IDENTITY=steward-harbor        # the handle; also accepted per site as INKBOX_IDENTITY_HARBOR etc.
INKBOX_OWNER_PHONE=+1415…             # E.164; level-4 escalation sends the owner a question here
INKBOX_CONTRACTOR_PHONE=+1415…        # E.164; task cards go here by SMS (needs START opt-in, see above)
INKBOX_CONTRACTOR_EMAIL=tech@example.com   # email fallback / level-2 escalation
INKBOX_ALLOWED_RECIPIENTS=+1415…,+1415…,tech@example.com   # exact list; every send is checked against it in providers.py
STEWARD_ALLOW_EXTERNAL_MESSAGES=true  # default false; nothing leaves the laptop until this is true
STEWARD_INBOUND_SECRET=<long random>  # compared to header X-Steward-Inbound-Secret on POST /api/inbound/inkbox
STEWARD_PUBLIC_BASE_URL=https://steward-harbor.inkboxwire.com   # the tunnel URL; used to build callback/webhook URLs
INKBOX_WEBHOOK_SIGNING_KEY=whsec_…    # returned ONCE by the first webhook subscription; verify_webhook() needs it
```

`STEWARD_INBOUND_SECRET`: generate with `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`. It is Steward's own gate, separate from Inkbox's signature; pass it to Inkbox as the subscription's `auth_token` (delivered as `Authorization: Bearer <token>`) **or** append it as a query string, whichever the backend stream implemented. The contract specifies the header `X-Steward-Inbound-Secret`; Inkbox cannot set custom headers, only `Authorization: Bearer`, so the backend must accept the bearer form or the signature check must stand alone. Flagging this for the backend stream.

## 4. The tunnel (public URL for Manufact and webhooks)

Inkbox has no `tunnel connect` CLI command (checked https://inkbox.ai/docs/skills/cli.md: only `tunnel list|get|update|sign-csr`). The data plane is opened from Python or TypeScript. Steward runs it from the backend venv in its own terminal, forwarding to FastAPI on 8001:

```sh
cd backend && INKBOX_API_KEY=… .venv/bin/python - <<'PY'
from inkbox import Inkbox
inkbox = Inkbox()
listener = inkbox.tunnels.connect(name="steward-harbor", forward_to="http://127.0.0.1:8001")
print(listener.public_url)   # https://steward-harbor.inkboxwire.com
listener.wait()              # blocks until Ctrl+C
PY
```

Docs: "The data-plane `connect()` helper opens the persistent agent connection and forwards inbound traffic to wherever you point it. … Authentication uses the same `INKBOX_API_KEY` the rest of the SDK uses — there is no per-tunnel secret on disk." TLS terminates at Inkbox's edge by default (`tls_mode: edge`). One identity = one tunnel = one forward target, so **everything public points at the backend**: Manufact's hosted MCP calls `https://steward-harbor.inkboxwire.com/api/...`, Inkbox webhooks post to `https://steward-harbor.inkboxwire.com/api/inbound/inkbox`, subscription callbacks from Steward to other agents go outbound and need no tunnel.

The backend's `local_origin_guard` (backend/src/main.py) only rejects non-GET requests that carry a browser `Origin` header outside the localhost list; server-to-server calls from Manufact and Inkbox carry no `Origin`, so they pass. Browser traffic from the Manufact dashboard goes to the MCP server, not to this tunnel.

Put the printed URL in `backend/.env` as `STEWARD_PUBLIC_BASE_URL` and in Manufact as `STEWARD_BACKEND_URL` (see manufact/README.md). Restart the backend after editing `.env`.

## 5. Inbound delivery: webhooks (not polling, not an SDK stream)

Inbound SMS, iMessage and email are delivered by **webhook subscriptions** (https://inkbox.ai/docs/webhooks.md). The SDK also offers `iter_unread_emails()` for mail, but texts and iMessages have no streaming API in `inkbox 0.7.19`; `list_texts()` exists for a polling fallback.

Create one subscription per identity, pointing at the tunnel:

```sh
cd backend && .venv/bin/python - <<'PY'
from inkbox import Inkbox
inkbox = Inkbox()
identity = inkbox.get_identity("steward-harbor")
sub = inkbox.webhooks.subscriptions.create(
    agent_identity_id=identity.id,
    url="https://steward-harbor.inkboxwire.com/api/inbound/inkbox",
    event_types=["text.received", "imessage.received", "message.received", "call.ended",
                 "text.delivered", "text.delivery_failed"],
    auth_token=__import__("os").environ["STEWARD_INBOUND_SECRET"])
print("subscription:", sub.id)
print("SIGNING KEY (shown once):", sub.signing_key)
PY
```

Docs: the create response's `signing_key` "is returned only on the first subscription created for an identity that had no key yet … Store it now; it cannot be retrieved again." Put it in `INKBOX_WEBHOOK_SIGNING_KEY`. Rotate with `POST /identities/{agent_handle}/signing-key` if lost.

Verification, from the installed SDK (`inkbox/signing_keys.py`): headers `X-Inkbox-Signature` (`sha256=<hex>`), `X-Inkbox-Request-Id`, `X-Inkbox-Timestamp`; HMAC-SHA256 over `f"{request_id}.{timestamp}." + raw_body` with the key (the `whsec_` prefix is stripped). Call:

```python
from inkbox.signing_keys import verify_webhook
ok = verify_webhook(payload=raw_body_bytes, headers=dict(request.headers), secret=os.environ["INKBOX_WEBHOOK_SIGNING_KEY"])
```

Payload: envelope `{id, event_type, data}`; "The event `id` is stable across retries and replays, so use it to deduplicate." Received-message events carry `data.contacts` and `data.agent_identities`; text events carry the message object (`conversation_id`, `remote_phone_number`, `text`, `media[]` with `url`). "Delivery is at least once." Route by `conversation_id` (thread), then the reference regex, then sender, exactly as the contract says. Replay a missed delivery with `inkbox.webhooks.deliveries.replay(...)`.

## 6. Sending (what the backend adapter calls)

All on the `AgentIdentity` object returned by `inkbox.get_identity(handle)`:

| Channel | SDK call (inkbox 0.7.19) | Notes |
| --- | --- | --- |
| SMS/MMS | `identity.send_text(to="+1…", text=card, media_urls=None, idempotency_key=work_item_id)` | Returns the queued `TextMessage`; delivery status arrives by webhook. Reply into the same thread with `conversation_id=` instead of `to=`. |
| Email | `identity.send_email(to=[addr], subject=f"[{reference}] …", body_text=card, in_reply_to_message_id=None, idempotency_key=…)` | Thread replies by passing the RFC 5322 Message-ID. |
| iMessage | `identity.send_imessage(to=["+1…"], …)` | Shared router on Free; pre-reply limits above. |
| Voice | `identity.place_call(to_number="+1…", mode="hosted_agent", reason=script, on_voicemail="leave_message")` | See §7. |

`providerRef` for the `Dispatch` record = the returned message/call `id`.

## 7. Voice: hosted agent runs a real conversation

Verified from https://inkbox.ai/docs/capabilities/phone/hosted-call-agent.md: "Inkbox runs a realtime voice agent on its own platform, so you don't need a WebSocket server." It "answers (or places) the call, knows who it's talking to" and hands back a structured package when the call ends. So **hosted voice runs the conversation; it does not merely stream audio.** Audio-only is the separate `client_websocket` mode (`client_websocket_url`, media stream).

- Standing behaviour: `identity.set_hosted_agent_config(voice="ara", instructions="…≤8000 chars…")`. 19 voices; the model is chosen by Inkbox and not configurable (`model` is deprecated).
- Per call: `reason` (≤2000 chars) is the task brief and overrides standing instructions on conflict; `on_voicemail` ∈ `leave_message | hang_up | ignore`; `voicemail_message` ≤1000 chars.
- `authority_mode`: `contact_scoped` (safer: current recipient only) or `yolo` (identity-wide; default for unconfigured identities). Set `contact_scoped` for the demo.
- Capacity: `503 hosted_agent_at_capacity` is possible; the contract's fallback (record a `call` dispatch with `providerRef: null` and the reason) covers it.
- Transcript: live via `identity.list_transcripts(call_id)`; final transcript, `outcome` and `post_call_action_items` arrive in the `call.ended` webhook (`data.transcript_url` is authoritative).
- Custom tools are not supported in the hosted agent; the "commitment" the contract wants logged comes from the transcript/outcome, not from a tool call.

## 8. Allowlist setup (two layers)

**Steward's own gate (code, always on):** `INKBOX_ALLOWED_RECIPIENTS` must list every phone/email exactly, and `STEWARD_ALLOW_EXTERNAL_MESSAGES=true` must be set, or `providers.py` raises before any send.

**Inkbox contact rules (server side, admin key):** switch the identity to whitelist and allow only the demo numbers/addresses, so even a bug cannot message a stranger. From https://inkbox.ai/docs/api/phone/contact-rules.md (direction defaults to `both`):

```python
inkbox.phone_identity_contact_rules.create("steward-harbor", action="allow", match_target="+14155550100")   # contractor
inkbox.phone_identity_contact_rules.create("steward-harbor", action="allow", match_target="+14155550101")   # owner
```

```sh
curl -X PATCH "https://inkbox.ai/api/v1/identities/steward-harbor" -H "X-API-Key: $INKBOX_API_KEY" \
  -H "Content-Type: application/json" -d '{"phone_filter_mode":"whitelist","mail_filter_mode":"whitelist"}'
inkbox identity mail-rules create steward-harbor --action allow --match-target tech@example.com --direction both   # CLI form; flag names from skills/cli.md, create flags unverified
```

Phone rules cover SMS, calls and iMessage together ("SMS/MMS, voice calls, and iMessage share the same phone rules"). "Agents cannot change their own contact rules" — use the admin key.

## 9. Contacts, Policies, Vault (what they are, what Steward uses)

- **Contacts**: shared org address book; create the contractor and owner with names + E.164 phone so inbound events are enriched with `data.contacts` (needs the identity to have Profile access to the contact group). Optional for the demo; routing uses the thread and the reference.
- **Communication policy / contact rules**: the per-identity whitelist/blacklist above. "Permission to receive does not automatically include permission to reply." We allow both directions.
- **Vault**: client-side-encrypted secret store (`INKBOX_VAULT_KEY`, never sent to the server). Not used by Steward; the signing key and secrets live in `backend/.env`.

## 10. Fallback when no key exists

`CommsAdapter` selects `local`: the task card is stored on the work item, the state becomes `waiting`, and the reply is posted to `POST /api/inbound/local` by the dashboard's "reply as contractor" control (or replayed from saved messages). Nothing external is attempted, and the dashboard labels the run as local. The MCP surface is unchanged.

## Unverified / could not confirm

- Exact field names on `identity.phone_number` / `identity.tunnel` objects (print them once).
- Whether Inkbox retries webhook deliveries on non-2xx, and the retry schedule (docs: "The page doesn't document a retry schedule"); at-least-once is documented, replay is manual.
- Whether a Free-plan identity can be upgraded in place to carry a phone number (plans page implies yes via `provision_phone_number`, not tested).
- `inkbox identity mail-rules create` flag names (CLI page lists the subcommand, not its create flags). Use the Python call or the console instead.
