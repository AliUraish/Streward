// inkbox-inbox: the inbox that never sleeps. Inkbox webhooks land here even while the backend (or its tunnel) is down.
//   1. Anything without X-Inkbox-Signature / -Request-Id / -Timestamp is refused before the body is read (401).
//   2. The HMAC-SHA256 signature is checked against every configured signing key (function secrets
//      INKBOX_WEBHOOK_SIGNING_KEY and INKBOX_WEBHOOK_SIGNING_KEY_*, set with `supabase secrets set`, never committed).
//   3. public.inkbox_enqueue() counts the call against the daily cap, deduplicates on the envelope id and sends the
//      exact request (raw body bytes as base64 plus the signature headers) to the pgmq queue `inkbox_inbound`.
// The backend drains the queue every 5 s and replays each message through POST /api/inbound/inkbox, which verifies
// the signature again. Deployed with verify_jwt = false: Inkbox sends no Supabase JWT; the HMAC is the authentication.
import { envelopeOf, importKeys, signatureHeaders, signingSecrets, timestampFresh, toBase64, verifySignature } from "./verify.ts";

const MAX_BODY_BYTES = 1_048_576;
const SUPABASE_URL = (Deno.env.get("SUPABASE_URL") ?? "").replace(/\/+$/, "");
const TOLERANCE_SECONDS = Number(Deno.env.get("INKBOX_WEBHOOK_TOLERANCE_SECONDS") ?? "0") || 0;

function serviceKey(): string {
  const raw = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (raw) {
    try {
      const keys = JSON.parse(raw) as Record<string, string>;
      const key = keys["default"] ?? Object.values(keys)[0];
      if (key) return key;
    } catch {
      /* fall through to the legacy key */
    }
  }
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
}

const SERVICE_KEY = serviceKey();
const keysPromise = importKeys(signingSecrets(Deno.env.toObject()));

Deno.serve(async (request: Request): Promise<Response> => {
  const started = performance.now();
  // X-Steward-Elapsed-Ms: time spent inside the function, so a refusal's cost is visible from outside.
  const reply = (status: number, body: Record<string, unknown>): Response => new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Steward-Elapsed-Ms": (performance.now() - started).toFixed(2) },
  });
  if (request.method !== "POST") return reply(405, { error: "POST only" });
  const headers = signatureHeaders(name => request.headers.get(name));
  if (!headers) return reply(401, { error: "unsigned: X-Inkbox-Signature, X-Inkbox-Request-Id and X-Inkbox-Timestamp are required" });
  if (!timestampFresh(headers.timestamp, TOLERANCE_SECONDS)) return reply(401, { error: "timestamp outside the permitted window" });
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY_BYTES) return reply(413, { error: "payload too large" });
  const keys = await keysPromise;
  if (!keys.length || !SUPABASE_URL || !SERVICE_KEY) return reply(503, { error: "inbox not configured" });
  const raw = new Uint8Array(await request.arrayBuffer());
  if (raw.byteLength > MAX_BODY_BYTES) return reply(413, { error: "payload too large" });
  if (!(await verifySignature(raw, headers, keys))) return reply(401, { error: "signature did not verify" });
  const envelope = envelopeOf(raw, headers.requestId);
  if (!envelope) return reply(400, { error: "body is not a JSON object" });
  const message = {
    rawB64: toBase64(raw),
    headers: {
      "x-inkbox-signature": headers.signature,
      "x-inkbox-request-id": headers.requestId,
      "x-inkbox-timestamp": headers.timestamp,
      "content-type": request.headers.get("content-type") ?? "application/json",
    },
    envelopeId: envelope.envelopeId,
    eventType: envelope.eventType,
    receivedAt: new Date().toISOString(),
    size: raw.byteLength,
  };
  const auth: Record<string, string> = SERVICE_KEY.startsWith("sb_") ? { apikey: SERVICE_KEY } : { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` };
  let result: { accepted?: boolean; duplicate?: boolean; reason?: string } = {};
  try {
    const response = await fetch(`${SUPABASE_URL}/rest/v1/rpc/inkbox_enqueue`, {
      method: "POST",
      headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify({ p_envelope_id: envelope.envelopeId, p_request_id: headers.requestId, p_event_type: envelope.eventType, p_message: message }),
    });
    if (!response.ok) return reply(503, { error: "queue unavailable; retry" });
    result = await response.json();
  } catch {
    return reply(503, { error: "queue unavailable; retry" });
  }
  if (!result.accepted) return reply(429, { error: result.reason ?? "refused" });
  return reply(200, { queued: !result.duplicate, duplicate: Boolean(result.duplicate), eventType: envelope.eventType });
});
