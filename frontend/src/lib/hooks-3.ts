"use client";

/* Hooks for the phase-3 dashboard. Each returns a Remote (data, readiness, error, reload) from useRemote, so every
   panel can show "Not available yet" with Retry when the backend answers 404/405/501. Polling backs off to 20 s while
   an endpoint is not there yet, so a missing route is not hammered every second. */
import { useEffect, useRef, useState } from "react";
import { useRemote, type Remote } from "./reality";
import { api3 } from "./api-3";
import { api } from "./api";
import type { ViewerCommand } from "./types-3";

export function usePoll<T>(loader: () => Promise<T>, deps: unknown[], intervalMs: number): Remote<T> {
  const [slow, setSlow] = useState(false);
  const remote = useRemote<T>(loader, deps, slow ? Math.max(intervalMs, 20_000) : intervalMs);
  const r = remote.readiness;
  useEffect(() => { setSlow(r === "not_ready" || r === "error"); }, [r]);
  return remote;
}

export const useOverview = () => usePoll(() => api3.overview(), [], 3_000);
export const useAgents3 = () => usePoll(() => api3.agents(), [], 5_000);
export const useBoardMeetings = (siteId?: string) => usePoll(() => api3.boardMeetings(siteId ? { siteId } : {}), [siteId], 6_000);
export const useScene = (siteId: string) => usePoll(() => api3.scene(siteId), [siteId], 15_000);
export const useIssues3 = (siteId: string) => usePoll(() => api3.issues(siteId), [siteId], 5_000);
export const useVision = (siteId: string) => usePoll(() => api3.vision(siteId), [siteId], 20_000);
export const useCrew = (siteId: string) => usePoll(() => api3.crew(siteId), [siteId], 30_000);
export const useObligations = (siteId: string) => usePoll(() => api3.obligations(siteId), [siteId], 15_000);
export const useDocuments3 = (siteId: string) => usePoll(() => api3.documents(siteId), [siteId], 30_000);
export const useNotices = (siteId: string) => usePoll(() => api3.notices(siteId), [siteId], 10_000);
export const useDocumentEmails = (siteId?: string) => usePoll(() => api3.documentEmails(siteId), [siteId], 10_000);
export const useResponsible = (siteId: string, issueKind: string | null) => usePoll(() => issueKind ? api3.responsible(siteId, issueKind) : Promise.resolve(null), [siteId, issueKind], 30_000);
export const useAgentActivity = (agentId: string) => usePoll(() => api3.agentActivity(agentId), [agentId], 5_000);
export const useAgentMemory = (agentId: string, query?: string) => usePoll(() => api3.agentMemory(agentId, query), [agentId, query], 20_000);
export const useAgentConfig = (agentId: string) => usePoll(() => api3.agentConfig(agentId), [agentId], 20_000);
export const useTranscript3 = (agentId: string) => usePoll(() => api3.transcript(agentId), [agentId], 4_000);
export const useEvals3 = (fast: boolean) => usePoll(() => api3.evals(), [], fast ? 3_000 : 20_000);
export const useEvalFindings = () => usePoll(() => api3.evalFindings(), [], 10_000);
/* Contract 4 */
export const useMetricsSummary = () => usePoll(() => api3.metricsSummary(), [], 10_000);
/* The live readings, every 5 s (the backend's own grid); all sites, or one with siteId. */
export const useMetricsLive = (siteId?: string) => usePoll(() => api3.metricsLive(siteId), [siteId], 5_000);
export const useMetrics = (siteId: string, hours: number, step?: string | number, intervalMs?: number) => usePoll(() => {
  const to = new Date(); const from = new Date(to.getTime() - hours * 3_600_000);
  return api3.metrics(siteId, { from: from.toISOString(), to: to.toISOString(), step });
}, [siteId, hours, step], intervalMs ?? (hours <= 24 ? 10_000 : 60_000));
export const useEvalMetrics = () => usePoll(() => api3.evalMetrics(), [], 20_000);
export const useConversations = (filters: { siteId?: string; agentId?: string } = {}) => usePoll(() => api3.conversations(filters), [filters.siteId, filters.agentId], 6_000);
export const useRegulations = (siteId?: string) => usePoll(() => api3.regulations(siteId), [siteId], 60_000);
export const useRegulationsWithComparison = (siteId: string) => usePoll(() => api3.regulationsWithComparison(siteId), [siteId], 60_000);
export const useMaintenance = (siteId?: string) => usePoll(() => api3.maintenance(siteId), [siteId], 20_000);
export const useNotifications = (siteId?: string) => usePoll(() => api3.notifications(siteId), [siteId], 8_000);
export const useFixWorkflows = (siteId?: string) => usePoll(() => api3.fixWorkflows(siteId), [siteId], 8_000);
export const useA2ATasks = () => usePoll(() => api3.a2aTasks(), [], 6_000);
export const useEyeFeed = (siteId: string, intervalMs = 3_000) => usePoll(() => api3.eyeFeed(siteId), [siteId], intervalMs);
export const useIssue = (issueId: string | null, fast: boolean) => usePoll(() => issueId ? api3.issue(issueId) : Promise.resolve(null), [issueId], fast ? 2_000 : 15_000);

export const useFacts3 = (siteId: string, assetTag: string | null) => usePoll(() => assetTag ? api.facts(siteId, { assetTag }) : Promise.resolve([]), [siteId, assetTag], 15_000);

/* The viewer command stream (section 2): poll GET /viewer?since= every second. The first answer only sets the cursor,
   so commands issued before the page opened are not replayed. New commands go to onCommand in order. */
export function useViewerCommands(siteId: string, onCommand: (c: ViewerCommand) => void): { readiness: Remote<unknown>["readiness"]; error: string; retry: () => void } {
  const [readiness, setReadiness] = useState<Remote<unknown>["readiness"]>("loading");
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const handler = useRef(onCommand); handler.current = onCommand;
  useEffect(() => {
    let alive = true; let timer = 0; let cursor: number | string | null = null; let primed = false; const seen = new Set<string>();
    const keyOf = (c: ViewerCommand, i: number) => c.id ?? `${c.seq ?? i}:${c.at ?? ""}`;
    const next = (ms: number) => { if (alive) timer = window.setTimeout(run, ms); };
    async function run() {
      try {
        const feed = await api3.viewer(siteId, primed ? cursor : undefined);
        if (!alive) return;
        setReadiness("ready"); setError("");
        const fresh = feed.commands.filter((c, i) => !seen.has(keyOf(c, i)));
        feed.commands.forEach((c, i) => seen.add(keyOf(c, i)));
        const seqs = feed.commands.map(c => c.seq).filter((s): s is number => typeof s === "number");
        cursor = feed.cursor ?? (seqs.length ? Math.max(...seqs) : feed.commands.at(-1)?.at ?? cursor);
        if (primed) for (const c of fresh) handler.current(c);
        primed = true;
        next(1_000);
      } catch (e) {
        if (!alive) return;
        const notReady = (e as { notReady?: boolean }).notReady;
        setReadiness(notReady ? "not_ready" : "error"); setError(e instanceof Error ? e.message : "Request failed");
        next(notReady ? 20_000 : 5_000);
      }
    }
    run();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [siteId, tick]);
  return { readiness, error, retry: () => setTick(t => t + 1) };
}
/* Contract 6: forged tools. */
export const useTools = (siteId?: string) => usePoll(() => api3.tools(siteId ? { siteId } : {}), [siteId], 6_000);
export const useTool = (id: string | null, fast: boolean) => usePoll(() => id ? api3.tool(id) : Promise.resolve(null), [id], fast ? 2_000 : 10_000);
