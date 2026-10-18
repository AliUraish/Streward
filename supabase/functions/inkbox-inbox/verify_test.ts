// Node 22 check of verify.ts against a signature computed by the caller (backend/tests/test_supabase_inbox.py signs
// with the Inkbox SDK's algorithm). Usage: node verify_test.ts <json-case>; exits 0 when every expectation holds.
import { envelopeOf, importKeys, signatureHeaders, signingSecrets, timestampFresh, verifySignature } from "./verify.ts";

const input = JSON.parse(process.argv[2] ?? "{}") as {
  body: string; secrets: Record<string, string>; headers: Record<string, string>; expect: boolean; envelope: string; tolerance?: number; nowMs?: number;
};
const headers = signatureHeaders(name => input.headers[name] ?? null);
const keys = await importKeys(signingSecrets(input.secrets));
const raw = new TextEncoder().encode(input.body);
const verified = headers ? await verifySignature(raw, headers, keys) : false;
const envelope = envelopeOf(raw, headers?.requestId ?? "");
const fresh = headers ? timestampFresh(headers.timestamp, input.tolerance ?? 0, input.nowMs ?? Date.now()) : false;
const ok = verified === input.expect && (!input.expect || envelope?.envelopeId === input.envelope) && (input.tolerance ? fresh === input.expect : true);
console.log(JSON.stringify({ verified, envelope, fresh, ok }));
process.exit(ok ? 0 : 1);
