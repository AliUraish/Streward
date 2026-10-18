"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Fact, FactStatus, WorkItem } from "../../../shared/types";
import type { AgentInfo, Change, EvalRun, Issue, Mission, SimulationStatus, SiteProperty, TranscriptEntry } from "./types-2";
import { api, ApiError, type FactRow } from "./api";
export interface ChangesResult { version: number; changes: Change[]; waiting: WorkItem[] }

/* Degraded-state model shared by every reality panel: the backend stream may not have shipped an endpoint yet. */
export type Readiness = "loading" | "ready" | "not_ready" | "error";
export interface Remote<T> { data: T | null; readiness: Readiness; error: string; reload: () => void; at: number }

export function readinessOf(error: unknown): { readiness: Readiness; message: string } {
  if (error instanceof ApiError && error.notReady) return { readiness: "not_ready", message: `${error.message}. The backend has not shipped this endpoint yet.` };
  if (error instanceof Error) return { readiness: "error", message: error.message };
  return { readiness: "error", message: "Request failed" };
}

export function useRemote<T>(loader: () => Promise<T>, deps: unknown[], intervalMs = 0): Remote<T> {
  const [data, setData] = useState<T | null>(null);
  const [readiness, setReadiness] = useState<Readiness>("loading");
  const [error, setError] = useState("");
  const [at, setAt] = useState(0);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader); loaderRef.current = loader;
  const reload = useCallback(() => setTick(t => t + 1), []);
  useEffect(() => {
    let alive = true; let busy = false;
    const run = async () => {
      if (busy) return; busy = true;
      try { const next = await loaderRef.current(); if (!alive) return; setData(next); setReadiness("ready"); setError(""); setAt(Date.now()); }
      catch (e) { if (!alive) return; const r = readinessOf(e); setReadiness(r.readiness); setError(r.message); }
      finally { busy = false; }
    };
    run();
    const timer = intervalMs > 0 ? setInterval(run, intervalMs) : null;
    return () => { alive = false; if (timer) clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, intervalMs]);
  return { data, readiness, error, reload, at };
}

/* Changes feed: Supabase Realtime when NEXT_PUBLIC_SUPABASE_URL and anon key exist, otherwise polling.
   Poll cadence: 2 s while any work item is open, 10 s otherwise (REALITY-CONTRACT.md, Frontend). */
const OPEN_STATES = new Set<WorkItem["state"]>(["open", "dispatched", "waiting", "needs_clarification", "escalated"]);
export const isOpen = (w: WorkItem) => OPEN_STATES.has(w.state);

export function useChanges(propertyId: string): Remote<ChangesResult> & { transport: "realtime" | "polling" } {
  const [transport, setTransport] = useState<"realtime" | "polling">("polling");
  const [anyOpen, setAnyOpen] = useState(false);
  const interval = transport === "realtime" ? 30_000 : anyOpen ? 2_000 : 10_000;
  const remote = useRemote(() => api.changes(propertyId, 0, 200) as Promise<ChangesResult>, [propertyId], interval);
  useEffect(() => { setAnyOpen(Boolean(remote.data?.waiting.some(isOpen))); }, [remote.data]);
  const reload = remote.reload;
  useEffect(() => {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL; const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!url || !key) return;
    let cleanup = () => {};
    let cancelled = false;
    import("@supabase/supabase-js").then(({ createClient }) => {
      if (cancelled) return;
      const client = createClient(url, key, { realtime: { params: { eventsPerSecond: 5 } } });
      const channel = client.channel(`changes:${propertyId}`)
        .on("postgres_changes", { event: "*", schema: "public", table: "changes" }, payload => {
          const row = (payload.new ?? payload.old ?? {}) as Record<string, unknown>;
          const pid = row.propertyId ?? row.property_id;
          if (row.type === "a2a") announceA2A(row);  /* addendum 2: one change per agent-to-agent message; the mission panel listens */
          if (!pid || pid === propertyId) reload();
        })
        .subscribe(status => { if (status === "SUBSCRIBED") setTransport("realtime"); if (status === "CHANNEL_ERROR" || status === "TIMED_OUT" || status === "CLOSED") setTransport("polling"); });
      cleanup = () => { client.removeChannel(channel); };
    }).catch(() => setTransport("polling"));
    return () => { cancelled = true; cleanup(); setTransport("polling"); };
  }, [propertyId, reload]);
  return { ...remote, transport };
}

/* A2A changes fan out through one DOM event so mission and transcript views refresh at once, whatever the transport. */
export const A2A_EVENT = "steward:a2a";
export function announceA2A(row: Record<string, unknown>) { if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(A2A_EVENT, { detail: row })); }
export function useA2ASignal(onSignal: () => void) {
  const ref = useRef(onSignal); ref.current = onSignal;
  useEffect(() => { const h = () => ref.current(); window.addEventListener(A2A_EVENT, h); return () => window.removeEventListener(A2A_EVENT, h); }, []);
}
/* Polling path: when the change feed grows a new a2a entry, announce it the same way realtime does. */
export function useA2AFromChanges(changes: Change[] | undefined) {
  const last = useRef(0);
  useEffect(() => { if (!changes) return; const top = changes.filter(c => c.type === "a2a").reduce((m, c) => Math.max(m, c.version), 0); if (top > last.current) { const first = last.current === 0; last.current = top; if (!first) announceA2A({ version: top }); } }, [changes]);
}

/* Addendum 2 hooks. Each degrades to not_ready on 404 so a panel can say so and offer Retry. */
export function useSites() { return useRemote<SiteProperty[]>(() => api.sites(), [], 30_000); }
export function useSimulation() { return useRemote<SimulationStatus>(() => api.simulation(), [], 15_000); }
export function useIssues(siteId: string, intervalMs = 10_000) { return useRemote<Issue[]>(() => api.issues(siteId), [siteId], intervalMs); }
export function useAgents(intervalMs = 5_000) { return useRemote<AgentInfo[]>(() => api.agentList(), [], intervalMs); }
/* Transcript: 3 s while a mission runs, 10 s otherwise (REALITY-CONTRACT-2.md, Dashboard). */
export function useTranscript(agentId: string | null, missionRunning: boolean) {
  const remote = useRemote<TranscriptEntry[]>(() => agentId ? api.transcript(agentId) : Promise.resolve([]), [agentId], missionRunning ? 3_000 : 10_000);
  useA2ASignal(remote.reload);
  return remote;
}
export const missionActive = (m: Mission | null | undefined) => m?.state === "running" || m?.state === "input_required";
export function useMissions(siteId: string) {
  const [active, setActive] = useState(false);
  const remote = useRemote<Mission[]>(() => api.missions(siteId), [siteId], active ? 3_000 : 15_000);
  useEffect(() => { setActive(Boolean(remote.data?.some(missionActive))); }, [remote.data]);
  useA2ASignal(remote.reload);
  return remote;
}
export function useMission(id: string | null) {
  const [active, setActive] = useState(true);
  const remote = useRemote<Mission | null>(() => id ? api.mission(id) : Promise.resolve(null), [id], active ? 3_000 : 0);
  useEffect(() => { setActive(missionActive(remote.data)); }, [remote.data]);
  useA2ASignal(remote.reload);
  return remote;
}
export function useEvals(running: boolean) { return useRemote<EvalRun[]>(() => api.evals(), [], running ? 3_000 : 20_000); }

export function useFacts(propertyId: string, intervalMs = 10_000) {
  return useRemote(() => api.facts(propertyId), [propertyId], intervalMs);
}

/* Freshness: 1 at observation, 0 at expiry. Identity facts (ttl null) never expire. */
export function freshness(fact: Pick<Fact, "observedAt" | "ttlSeconds">, now = Date.now()): { ratio: number; ageSeconds: number; status: FactStatus } {
  const observed = new Date(fact.observedAt).getTime();
  const ageSeconds = Math.max(0, Math.round((now - observed) / 1000));
  if (fact.ttlSeconds === null || fact.ttlSeconds === undefined) return { ratio: 1, ageSeconds, status: "known" };
  const ratio = Math.max(0, Math.min(1, 1 - ageSeconds / fact.ttlSeconds));
  return { ratio, ageSeconds, status: ratio > 0 ? "known" : "stale" };
}

export function latestPerAttribute(rows: FactRow[]): FactRow[] {
  const map = new Map<string, FactRow>();
  for (const row of rows) { const key = `${row.assetTag}:${row.attribute}`; const prev = map.get(key); if (!prev || new Date(row.observedAt) > new Date(prev.observedAt)) map.set(key, row); }
  return [...map.values()].sort((a, b) => a.assetTag.localeCompare(b.assetTag) || a.attribute.localeCompare(b.attribute));
}

export function age(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export function untilDeadline(iso: string | null, now = Date.now()): string {
  if (!iso) return "no deadline";
  const s = Math.round((new Date(iso).getTime() - now) / 1000);
  if (s <= 0) return "overdue";
  if (s < 3600) return `${Math.ceil(s / 60)} min left`;
  return `${Math.round(s / 3600)} h left`;
}
export const attributeLabel = (attribute: string) => attribute.replace(/_/g, " ");
export const formatValue = (value: string | number | boolean | undefined, unit?: string | null) => value === undefined ? "" : `${typeof value === "boolean" ? (value ? "yes" : "no") : value}${unit ? ` ${unit}` : ""}`;
export const stateLabel: Record<WorkItem["state"], string> = { open: "open", dispatched: "dispatched", waiting: "waiting for a reply", needs_clarification: "needs clarification", escalated: "escalated", resolved: "resolved", rejected: "rejected", expired: "expired" };
export type { Change, WorkItem, FactRow };
