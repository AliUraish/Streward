"use client";

/* Polls for the agent views (api-11.ts): what an agent sees of a site, as JSON and as the Markdown an MCP client reads,
   and the Site Inspector's site tours. */
import { api11 } from "./api-11";
import { usePoll } from "./hooks-3";

export const useAgentEnvironment = (siteId: string, intervalMs = 6_000) => usePoll(() => api11.environment(siteId), [siteId], intervalMs);
export const useAgentEnvironmentText = (siteId: string, intervalMs = 10_000) => usePoll(() => api11.environmentText(siteId), [siteId], intervalMs);
export const useSiteTours = (siteId?: string, limit = 5, intervalMs = 8_000) => usePoll(() => api11.tours(siteId, limit), [siteId, limit], intervalMs);
