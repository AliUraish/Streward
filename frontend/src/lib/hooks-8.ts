"use client";

/* Hooks for the owner's notifications. Each feed is a Remote from usePoll (hooks-3.ts), so the page says "not available
   yet" with Retry while the backend has no route, and polling backs off to 20 s until it does. The last visit is kept
   on this device (localStorage, inside try/catch) so the sidebar can count what arrived since. */
import { useEffect, useState, useSyncExternalStore } from "react";
import { api3 } from "./api-3";
import { api8, type NotificationFilters, type OwnerNotification } from "./api-8";
import { usePoll } from "./hooks-3";

export const NOTIFICATIONS_POLL_MS = 10_000;
export const feedKey = (f: NotificationFilters) => JSON.stringify([f.limit ?? null, f.since ?? null, f.siteId ?? null, f.kind ?? null]);

/* The feed, tagged with the filters it answers, so a page can tell a fresh answer from the previous filter's. */
export function useOwnerNotifications(f: NotificationFilters, intervalMs = NOTIFICATIONS_POLL_MS) {
  const key = feedKey(f);
  return usePoll<{ key: string; items: OwnerNotification[] }>(async () => ({ key, items: await api8.notifications(f) }), [key], intervalMs);
}
/* The same feed as Markdown (?format=md), for agent mode. */
export function useOwnerNotificationsMarkdown(f: NotificationFilters, intervalMs = NOTIFICATIONS_POLL_MS) {
  const key = feedKey(f);
  return usePoll<{ key: string; text: string }>(async () => ({ key, text: await api8.markdown(f) }), [key], intervalMs);
}

/* ---- the last visit: the newest item the owner has seen ---------------------------------------------------- */
const SEEN_KEY = "steward.notifications.seen";
const seenListeners = new Set<() => void>();
let seenValue: string | null | undefined;
export function readNotificationsSeen(): string | null {
  if (typeof window === "undefined") return null;
  if (seenValue === undefined) { try { seenValue = window.localStorage.getItem(SEEN_KEY); } catch { seenValue = null; } }
  return seenValue ?? null;
}
/* Moves forward only: an older time never undoes a later visit. */
export function markNotificationsSeen(iso: string | null | undefined) {
  if (!iso) return;
  const t = Date.parse(iso); if (Number.isNaN(t)) return;
  const cur = readNotificationsSeen(); const c = cur ? Date.parse(cur) : NaN;
  if (!Number.isNaN(c) && c >= t) return;
  seenValue = iso;
  try { window.localStorage.setItem(SEEN_KEY, iso); } catch { /* storage blocked */ }
  seenListeners.forEach(f => f());
}
function subscribeSeen(f: () => void) {
  seenListeners.add(f);
  const onStorage = (e: StorageEvent) => { if (e.key === SEEN_KEY) { seenValue = e.newValue; f(); } };
  window.addEventListener("storage", onStorage);
  return () => { seenListeners.delete(f); window.removeEventListener("storage", onStorage); };
}
export const useNotificationsSeen = () => useSyncExternalStore(subscribeSeen, readNotificationsSeen, () => null);

/* What arrived since the last visit, for the sidebar. A device that has never visited starts counting from now. */
export function useUnreadNotifications(intervalMs = 15_000): number {
  const seen = useNotificationsSeen();
  useEffect(() => { if (readNotificationsSeen() === null) markNotificationsSeen(new Date().toISOString()); }, []);
  const remote = usePoll(() => api8.notifications({ limit: 50 }), [], intervalMs);
  const since = seen ? Date.parse(seen) : NaN;
  if (Number.isNaN(since) || !remote.data) return 0;
  return remote.data.filter(n => Date.parse(n.at) > since).length;
}

/* ---- where an issue lives (its site and asset), read once per issue while the dashboard is open ---------------- */
export interface IssueAt { siteId: string | null; assetTag: string | null }
const issueAt = new Map<string, IssueAt | null>();
const issueAsked = new Set<string>();
const issueListeners = new Set<() => void>();
export function useIssueTargets(ids: string[]): ReadonlyMap<string, IssueAt | null> {
  const [, setTick] = useState(0);
  useEffect(() => { const f = () => setTick(t => t + 1); issueListeners.add(f); return () => { issueListeners.delete(f); }; }, []);
  const key = [...new Set(ids)].sort().join("\n");
  useEffect(() => {
    const todo = key ? key.split("\n").filter(id => !issueAt.has(id) && !issueAsked.has(id)) : [];
    if (!todo.length) return;
    todo.forEach(id => issueAsked.add(id));
    void Promise.allSettled(todo.map(id => api3.issue(id))).then(got => {
      got.forEach((r, i) => {
        issueAsked.delete(todo[i]);
        if (r.status === "fulfilled") issueAt.set(todo[i], { siteId: r.value.siteId ?? null, assetTag: r.value.assetTag || null });
        else if ((r.reason as { notReady?: boolean } | undefined)?.notReady) issueAt.set(todo[i], null);
      });
      issueListeners.forEach(f => f());
    });
  }, [key]);
  return issueAt;
}
