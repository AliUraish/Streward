// Inkbox webhook signature verification (WebCrypto only, so it runs in Deno and in Node 22 for tests).
// Same algorithm as the Inkbox SDK (inkbox.signing_keys.verify_webhook) and backend/src/providers.py:
//   X-Inkbox-Signature: sha256=<hex(HMAC-SHA256(key, `${X-Inkbox-Request-Id}.${X-Inkbox-Timestamp}.` + raw body))>
// where key is the identity's signing key without its optional `whsec_` prefix. Every configured key is tried
// (INKBOX_WEBHOOK_SIGNING_KEY and INKBOX_WEBHOOK_SIGNING_KEY_*: one per Inkbox identity).

const encoder = new TextEncoder();

export interface SignatureHeaders {
  signature: string;
  requestId: string;
  timestamp: string;
}

export function signatureHeaders(get: (name: string) => string | null): SignatureHeaders | null {
  const signature = (get("x-inkbox-signature") ?? "").trim();
  const requestId = (get("x-inkbox-request-id") ?? "").trim();
  const timestamp = (get("x-inkbox-timestamp") ?? "").trim();
  if (!signature.startsWith("sha256=") || !requestId || !timestamp || requestId.length > 200 || timestamp.length > 64) return null;
  return { signature, requestId, timestamp };
}

export function signingSecrets(env: Record<string, string | undefined>): string[] {
  const keys = new Set<string>();
  for (const [name, value] of Object.entries(env)) {
    if (name !== "INKBOX_WEBHOOK_SIGNING_KEY" && !name.startsWith("INKBOX_WEBHOOK_SIGNING_KEY_")) continue;
    const key = (value ?? "").trim().replace(/^whsec_/, "");
    if (key && !key.startsWith("#")) keys.add(key);
  }
  return [...keys];
}

export function importKeys(secrets: string[]): Promise<CryptoKey[]> {
  return Promise.all(secrets.map(secret => crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"])));
}

function toHex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function verifySignature(raw: Uint8Array, headers: SignatureHeaders, keys: CryptoKey[]): Promise<boolean> {
  const prefix = encoder.encode(`${headers.requestId}.${headers.timestamp}.`);
  const message = new Uint8Array(prefix.byteLength + raw.byteLength);
  message.set(prefix, 0);
  message.set(raw, prefix.byteLength);
  const expected = headers.signature.slice("sha256=".length).toLowerCase();
  let matched = false;
  for (const key of keys) {
    const mac = toHex(await crypto.subtle.sign("HMAC", key, message));
    if (constantTimeEqual(mac, expected)) matched = true; // no early exit: every key costs the same
  }
  return matched;
}

/** Seconds-or-milliseconds Unix timestamps outside the tolerance are refused when a tolerance is set (0 = off). */
export function timestampFresh(timestamp: string, toleranceSeconds: number, nowMs: number = Date.now()): boolean {
  if (!toleranceSeconds) return true;
  const value = Number(timestamp);
  if (!Number.isFinite(value)) {
    const parsed = Date.parse(timestamp);
    return Number.isFinite(parsed) ? Math.abs(nowMs - parsed) <= toleranceSeconds * 1000 : false;
  }
  const ms = value > 1e12 ? value : value * 1000;
  return Math.abs(nowMs - ms) <= toleranceSeconds * 1000;
}

export function toBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  return btoa(binary);
}

/** The envelope id Inkbox retries with (`id`), else the request id; the event type for logs. */
export function envelopeOf(raw: Uint8Array, requestId: string): { envelopeId: string; eventType: string } | null {
  try {
    const payload = JSON.parse(new TextDecoder().decode(raw)) as { id?: unknown; event_type?: unknown };
    if (!payload || typeof payload !== "object") return null;
    const id = typeof payload.id === "string" || typeof payload.id === "number" ? String(payload.id) : requestId;
    return { envelopeId: id.slice(0, 200), eventType: typeof payload.event_type === "string" ? payload.event_type.slice(0, 60) : "unknown" };
  } catch {
    return null;
  }
}
