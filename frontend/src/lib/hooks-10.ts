"use client";

/* Hooks for contract 8. Each is a Remote from usePoll (hooks-3.ts), so a panel says "not available yet" with Retry while
   the backend has no route, and polling backs off to 20 s until it does. Phone calls poll every 2 s while one is on the
   line and every 10 s otherwise. */
import { useEffect, useState } from "react";
import { api3 } from "./api-3";
import { api10, isLiveCall, isQueuedCall, type OutboxFilters, type PhoneCallFilters } from "./api-10";
import { usePoll } from "./hooks-3";

/* The calls on the line now (GET /api/phone-calls?active=true): 2 s while there is one, 10 s otherwise. */
export function useActivePhoneCalls() {
  const [fast, setFast] = useState(false);
  const remote = usePoll(() => api10.phoneCalls({ active: true, limit: 5 }), [], fast ? 2_000 : 10_000);
  const any = Boolean(remote.data?.some(c => isLiveCall(c) || isQueuedCall(c)));
  useEffect(() => { setFast(any); }, [any]);
  return remote;
}
/* The latest calls (the conversations page): 2 s while one of them is live, 10 s otherwise. */
export function usePhoneCalls(f: PhoneCallFilters = {}) {
  const [fast, setFast] = useState(false);
  const remote = usePoll(() => api10.phoneCalls(f), [f.siteId, f.active, f.purpose, f.limit], fast ? 2_000 : 10_000);
  const any = Boolean(remote.data?.some(isLiveCall));
  useEffect(() => { setFast(any); }, [any]);
  return remote;
}
/* One call: every 2 s while `fast` (on the line, or ended with its outcome still being read), else every 15 s. */
export const usePhoneCall = (id: string | null, fast: boolean) =>
  usePoll(() => (id ? api10.phoneCall(id) : Promise.resolve(null)), [id], fast ? 2_000 : 15_000);

export const useOutbox = (f: OutboxFilters = {}, intervalMs = 10_000) => usePoll(() => api10.outbox(f), [f.status, f.channel, f.siteId, f.limit], intervalMs);
export const useOutboxStatus = (intervalMs = 10_000) => usePoll(() => api10.outboxStatus(), [], intervalMs);

export const useAttendance = (siteId: string, days = 14) => usePoll(() => api10.attendance(siteId, days), [siteId, days], 30_000);
export const useAttendanceCases = (siteId?: string, limit = 30) => usePoll(() => api10.cases(siteId, limit), [siteId, limit], 10_000);

/* The chain moves a step at a time, so the site's inspections poll every 8 s. */
export const useInspections = (siteId?: string, limit = 5) => usePoll(() => api10.inspections(siteId, limit), [siteId, limit], 8_000);

/* One conversation by id (a case's or an inspection's chat), for its summary. */
export const useConversation = (id: string | null, intervalMs = 15_000) => usePoll(() => (id ? api3.conversation(id) : Promise.resolve(null)), [id], intervalMs);
