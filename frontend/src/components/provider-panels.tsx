"use client";

import { useState } from "react";
import { ArrowClockwise, ArrowSquareOut, Brain, CheckCircle, CloudArrowUp, Database, EnvelopeSimple, Info, PaperPlaneRight, PlugsConnected, Receipt, SpinnerGap, WarningCircle } from "@phosphor-icons/react";
import { request } from "@/lib/api";
import type { Integration, Purchase } from "../../../shared/types";
import { EmptyState, errorMessage, formatDate, formatTime } from "./ui";

export type ProviderIntegration = Integration & { capabilities?: Record<string, boolean> };
type IdentityResult = { provider: string; status: string; handle: string; identity?: string; email?: string; detail?: string };
type InboxMessage = { id: string; mailbox_id?: string; thread_id?: string; message_id?: string; from_address: string; to_addresses: string[]; subject: string | null; snippet: string | null; direction: string; status: string; created_at: string; has_attachments: boolean };
const base = (id: string) => `/api/properties/${encodeURIComponent(id)}`;
const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export function InboxPanel({ propertyId, propertyName, identity: localIdentity, integration, onChanged }: { propertyId: string; propertyName: string; identity: string; integration?: ProviderIntegration; onChanged: () => Promise<void> }) {
  const [identity, setIdentity] = useState<IdentityResult | null>(null);
  const [messages, setMessages] = useState<InboxMessage[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [compose, setCompose] = useState(false);
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const capabilities = integration?.capabilities ?? {};
  const selected = messages?.find(message => message.id === selectedId);

  async function checkIdentity() {
    setBusy("identity"); setError(""); setNote("");
    try { const result = await request<IdentityResult>(`${base(propertyId)}/identity`); setIdentity(result); setNote(result.detail ?? `Identity verified: ${result.email || result.handle}`); await onChanged(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(""); }
  }
  async function readInbox() {
    setBusy("inbox"); setError(""); setNote("");
    try { const result = await request<InboxMessage[]>(`${base(propertyId)}/inbox`); setMessages(result); setSelectedId(result[0]?.id ?? null); setNote(`Read ${result.length} messages from the configured property inbox.`); await onChanged(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(""); }
  }
  async function send(e: React.FormEvent) {
    e.preventDefault(); if (!capabilities.sendEmail || busy) return;
    const recipients = to.split(/[,;\n]/).map(address => address.trim()).filter(Boolean);
    if (!recipients.length) return;
    setBusy("send"); setError(""); setNote("");
    try { const result = await post<{ id?: string; status?: string }>(`${base(propertyId)}/messages`, { to: recipients, subject, bodyText: body }); setNote(`Email submitted to Inkbox${result.id ? ` (${result.id})` : ""}. Provider submission is not a delivery receipt.`); setCompose(false); setTo(""); setSubject(""); setBody(""); await onChanged(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(""); }
  }

  return <div className="agent-content-scroll inbox-content"><div className="content-section-intro"><EnvelopeSimple size={23} /><div><h2>A persistent property identity</h2><p>Read and communicate from {propertyName}’s configured Inkbox identity. External actions run only when you choose them.</p></div></div><div className="provider-identity-card"><span className="provider-card-icon"><EnvelopeSimple size={21} /></span><div><span className="eyebrow">{identity?.provider === "inkbox" ? "Inkbox identity" : "Local property identity"}</span><strong>{identity?.email || identity?.identity || localIdentity}</strong><p>{identity?.handle ? `Handle: ${identity.handle}` : "An external mailbox has not been verified in this workspace."}</p></div><button className="button dark-ghost" disabled={Boolean(busy) || !capabilities.identity} title={capabilities.identity ? "Look up the configured identity" : "Configure an Inkbox API key and property identity handle"} onClick={checkIdentity}>{busy === "identity" ? <SpinnerGap className="spin" size={13} /> : <PlugsConnected size={13} />}Check identity</button></div><div className="provider-action-bar"><div><button className="button dark-ghost" disabled={Boolean(busy) || !capabilities.inbox} onClick={readInbox} title={!capabilities.inbox ? "Configure Inkbox and this property’s identity handle to read messages" : "Read the configured external inbox"}>{busy === "inbox" ? <SpinnerGap className="spin" size={13} /> : <ArrowClockwise size={13} />}Read inbox</button><button className="button dark-ghost" disabled={Boolean(busy) || !capabilities.sendEmail} onClick={() => setCompose(!compose)} title={!capabilities.sendEmail ? "External sending must be enabled with an explicit recipient allowlist" : "Compose an email to an allowlisted recipient"}><PaperPlaneRight size={13} />Compose</button></div><span>Sending: {capabilities.sendEmail ? "Allowlisted recipients" : "Disabled"}</span></div>{!capabilities.inbox ? <div className="provider-setup-note"><Info size={15} /><div><strong>Connect an existing Inkbox identity</strong><p>Add the Inkbox API key and this property’s identity handle in the backend environment. Sending also requires explicit enablement and an allowed recipient list.</p></div></div> : null}{error ? <div className="provider-error" role="alert"><WarningCircle size={14} />{error}</div> : null}{note ? <div className="provider-result" role="status"><CheckCircle size={14} />{note}</div> : null}{compose ? <form className="provider-compose" onSubmit={send}><div className="eyebrow">New email / Inkbox</div><label className="field-label">To<input value={to} onChange={e => setTo(e.target.value)} required placeholder="Allowed recipient email address" maxLength={1500} /></label><label className="field-label">Subject<input value={subject} onChange={e => setSubject(e.target.value)} required maxLength={300} /></label><label className="field-label">Message<textarea value={body} onChange={e => setBody(e.target.value)} required rows={6} maxLength={20000} /></label><div className="provider-compose-footer"><span>This sends an external email to the listed recipients.</span><button className="button dark-ghost" type="button" disabled={Boolean(busy)} onClick={() => setCompose(false)}>Cancel</button><button className="button provider-primary" type="submit" disabled={Boolean(busy) || !capabilities.sendEmail}>{busy === "send" ? <SpinnerGap className="spin" size={13} /> : <PaperPlaneRight size={13} />}Send email</button></div></form> : null}{messages === null ? <EmptyState icon={<EnvelopeSimple size={29} />} title={capabilities.inbox ? "Your inbox is ready to read" : "No external inbox connected"}>{capabilities.inbox ? "Choose Read inbox to retrieve the latest messages. Messages are not fetched automatically." : "Local property identities and jobs continue to work. No external messages have been fetched or sent."}</EmptyState> : messages.length ? <div className="inbox-layout"><div className="inbox-message-list">{messages.map(message => <button className={selectedId === message.id ? "active" : ""} key={message.id} onClick={() => setSelectedId(message.id)}><div><strong>{message.from_address}</strong><time>{formatTime(message.created_at)}</time></div><span>{message.subject || "(No subject)"}</span><p>{message.snippet || "No message preview provided."}</p><small>{message.direction} · {message.status}{message.has_attachments ? " · Attachments" : ""}</small></button>)}</div><div className="inbox-message-preview">{selected ? <><div className="eyebrow">Message preview</div><h3>{selected.subject || "(No subject)"}</h3><dl><dt>From</dt><dd>{selected.from_address}</dd><dt>To</dt><dd>{selected.to_addresses.join(", ")}</dd><dt>Received</dt><dd>{formatDate(selected.created_at)} · {formatTime(selected.created_at)}</dd></dl><p>{selected.snippet || "No preview text provided by Inkbox."}</p><div className="provider-list-note">The inbox endpoint returns metadata and a preview. Full message bodies and attachments are not fetched here.</div></> : null}</div></div> : <EmptyState icon={<EnvelopeSimple size={29} />} title="The inbox is empty">No messages were returned by the configured identity.</EmptyState>}</div>;
}

export function MemoryProviderTools({ propertyId, integration, onChanged }: { propertyId: string; integration?: ProviderIntegration; onChanged: () => Promise<void> }) {
  const [query, setQuery] = useState(""); const [busy, setBusy] = useState(""); const [error, setError] = useState(""); const [note, setNote] = useState(""); const [result, setResult] = useState<unknown>(null);
  const capabilities = integration?.capabilities ?? {};
  async function sync() {
    setBusy("sync"); setError(""); setNote("");
    try { const response = await post<{ submitted: { id: string; status: string }[]; detail: string }>(`${base(propertyId)}/memory/sync`); setNote(`${response.submitted.length} memories submitted. ${response.detail}`); await onChanged(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(""); }
  }
  async function recall(e: React.FormEvent) {
    e.preventDefault(); if (!query.trim()) return;
    setBusy("recall"); setError(""); setNote("");
    try { const response = await post<{ namespace: string; search: unknown; profile: unknown }>(`${base(propertyId)}/memory/recall`, { query: query.trim() }); setResult(response); setNote(`Profile and search retrieved from ${response.namespace}. Verify recalled claims against their sources.`); await onChanged(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(""); }
  }
  return <section className="memory-provider-tools"><div className="provider-tools-heading"><div><Brain size={17} /><h3>Supermemory</h3><span>{capabilities.sync ? "Available" : "Not configured"}</span></div><button className="button dark-ghost" onClick={sync} disabled={Boolean(busy) || !capabilities.sync} title={capabilities.sync ? "Submit the latest ten local property memories to Supermemory" : "Configure SUPERMEMORY_API_KEY in the backend environment"}>{busy === "sync" ? <SpinnerGap className="spin" size={13} /> : <CloudArrowUp size={13} />}Sync latest 10</button></div><p>Sync submits this property’s latest ten memories to its own external namespace. Indexing is asynchronous. Local memory remains available below.</p><form className="external-recall-form" onSubmit={recall}><input aria-label="Search Supermemory" value={query} onChange={e => setQuery(e.target.value)} maxLength={2000} placeholder="Search external property memory" disabled={!capabilities.recall} /><button className="button dark-ghost" disabled={Boolean(busy) || !capabilities.recall || !query.trim()}>{busy === "recall" ? <SpinnerGap className="spin" size={13} /> : <Brain size={13} />}Recall</button></form>{!capabilities.sync ? <div className="provider-list-note">Configure a Supermemory API key in the backend environment to enable sync and recall.</div> : null}{error ? <div className="provider-error" role="alert"><WarningCircle size={14} />{error}</div> : null}{note ? <div className="provider-result" role="status"><CheckCircle size={14} />{note}</div> : null}{result ? <details className="provider-response-details" open><summary>Namespace profile and search results</summary><pre>{JSON.stringify(result, null, 2)}</pre></details> : null}</section>;
}

export function SandboxCheckoutAction({ propertyId, purchase, integration, onChanged }: { propertyId: string; purchase: Purchase; integration?: ProviderIntegration; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [checkout, setCheckout] = useState<{ sessionId: string; url: string; mode: string; detail: string } | null>(null);
  const available = integration?.capabilities?.testCheckout === true;
  async function create() {
    setBusy(true); setError("");
    try { const result = await post<{ sessionId: string; url: string; mode: string; detail: string }>(`${base(propertyId)}/purchases/${encodeURIComponent(purchase.id)}/checkout`); if (result.mode !== "test" || !result.url.startsWith("https://checkout.stripe.com/")) throw new Error("The server did not return a valid Stripe test Checkout session."); setCheckout(result); await onChanged(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  if (purchase.status === "test_payment_received") return <span className="checkout-receipt"><CheckCircle size={12} />Test receipt recorded</span>;
  return <div className="checkout-action">{available ? <button className="button dark-ghost" onClick={create} disabled={busy}>{busy ? <SpinnerGap className="spin" size={12} /> : <Receipt size={12} />}{checkout ? "Refresh test Checkout" : "Create test Checkout"}</button> : <span className="provider-action-disabled">Connect a Stripe test key to enable sandbox Checkout.</span>}{checkout ? <><a className="button dark-ghost" href={checkout.url} target="_blank" rel="noreferrer">Open sandbox Checkout <ArrowSquareOut size={11} /></a><span className="provider-list-note">{checkout.detail} Payment is recorded only after a verified test webhook.</span></> : null}{error ? <span className="provider-error" role="alert">{error}</span> : null}</div>;
}

export function IntegrationCheckAction({ integration, onChanged }: { integration: ProviderIntegration; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false); const [result, setResult] = useState(""); const [error, setError] = useState("");
  if (integration.id !== "insforge") return null;
  async function check() { setBusy(true); setError(""); try { const response = await post<{ status: string; detail: string }>("/api/integrations/insforge/check"); setResult(response.detail); await onChanged(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  return <div className="connection-check"><button className="button" onClick={check} disabled={busy || !integration.capabilities?.check}>{busy ? <SpinnerGap className="spin" size={13} /> : <Database size={13} />}Check existing project</button><p className="provider-list-note">Read-only connection check. Your local database stays active.</p>{!integration.capabilities?.check ? <p className="provider-list-note">Configure the existing project URL and anonymous key in the backend environment.</p> : null}{result ? <p className="provider-result" role="status">{result}</p> : null}{error ? <p className="inline-error" role="alert">{error}</p> : null}</div>;
}
