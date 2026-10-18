"use client";

/* Hooks for contract 7. Each is a Remote from usePoll (hooks-3.ts), so a panel says "not available yet" with Retry
   while the backend has no route, and polling backs off to 20 s until it does. */
import { usePoll } from "./hooks-3";
import { api7 } from "./api-7";

/* The latest label per asset, every 5 s (the 3-D markers). */
export const useLabels = (siteId: string, intervalMs = 5_000) => usePoll(() => api7.labels(siteId), [siteId], intervalMs);
/* The site's latest walkthrough, every 3 s (the walkthrough line). */
export const usePatrols = (siteId: string, intervalMs = 3_000) => usePoll(() => api7.patrols(siteId, 1), [siteId], intervalMs);
/* Owner alerts arrive a step at a time, about 4 s apart, so the feed polls every 5 s. */
export const useOwnerAlerts = (siteId?: string, limit = 6) => usePoll(() => api7.ownerAlerts(siteId, limit), [siteId, limit], 5_000);
/* The latest calls across every site, every 3 s (the dashboard-wide call notifier). */
export const useCalls = () => usePoll(() => api7.calls(12), [], 3_000);
