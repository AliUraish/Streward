"use client";

/* Live updates for the mission view, agent mode and the agents map. Polling is the baseline and stays the fallback.
   The SUPABASE stream's frontend/src/lib/realtime/ (useHudChannel, useSitePresence) feeds this bus through HudBridge,
   mounted once in the shell for the current site: one channel per tab, never more (the module reference-counts a
   site's channel, and the bridge is its only caller), closed while the tab is hidden, off when env or the backend's
   budget says no. Pages never open channels themselves; they subscribe to the bus with useHudEvents and reload the
   record an event touches, so an event is only ever a faster nudge to the poll. */
import { useEffect, useRef, useSyncExternalStore } from "react";
import { useHudChannel, useSitePresence, type PresenceRole } from "./realtime";

export type HudEventType = "eye_frame" | "agent_action" | "conversation_line" | "issue_change";
export interface HudEvent { type: HudEventType; siteId: string; at?: string; payload?: unknown }
export interface Presence { watchers: { role: string; name?: string | null }[]; rendererOnline: boolean | null }

type Listener = (e: HudEvent) => void;
const listeners = new Set<Listener>();
let realtime = false;
const presence = new Map<string, Presence>();
const subs = new Set<() => void>();
const notify = () => subs.forEach(f => f());

/* Called by the bridge for every event a site channel delivers. */
export function emitHud(e: HudEvent) { listeners.forEach(l => { try { l(e); } catch { /* a listener's error stays its own */ } }); }
export function setRealtime(on: boolean) { if (realtime !== on) { realtime = on; notify(); } }
export function setPresence(siteId: string, p: Presence | null) { if (p) presence.set(siteId, p); else presence.delete(siteId); notify(); }

/* Subscribe to events for one site (or every site); handlers may change between renders. */
export function useHudEvents(siteId: string | "all", handlers: Partial<Record<HudEventType, (e: HudEvent) => void>>) {
  const ref = useRef(handlers); ref.current = handlers;
  useEffect(() => {
    const l: Listener = e => { if (siteId === "all" || e.siteId === siteId) ref.current[e.type]?.(e); };
    listeners.add(l); return () => { listeners.delete(l); };
  }, [siteId]);
}

/* Whether a realtime channel is feeding the bus, and the latest presence for a site (null without realtime). */
export function useLive(siteId?: string): { realtime: boolean; presence: Presence | null } {
  const on = useSyncExternalStore(f => { subs.add(f); return () => { subs.delete(f); }; }, () => realtime, () => false);
  const p = useSyncExternalStore(f => { subs.add(f); return () => { subs.delete(f); }; }, () => (siteId ? presence.get(siteId) ?? null : null), () => null);
  return { realtime: on, presence: p };
}

/* The bridge to lib/realtime, for the shell's current site. Each new event goes out on the bus once (events keep their
   identity across the hook's renders, so a WeakSet tells new from seen). Presence tracks this tab as a viewer, or as a
   renderer while it runs the agent eye (the environment page), and publishes how many tabs are watching and whether
   any renderer is online; without a live channel presence is cleared and pages fall back to the eye feed's renderer list. */
export function HudBridge({ siteId, role = "viewer" }: { siteId: string; role?: PresenceRole }) {
  const hud = useHudChannel(siteId);
  const who = useSitePresence(siteId, role);
  const seen = useRef(new WeakSet<object>());
  useEffect(() => {
    for (const e of hud.events) {
      if (seen.current.has(e)) continue;
      seen.current.add(e);
      emitHud({ type: e.type, siteId, at: e.at ?? undefined, payload: e });
    }
  }, [hud.events, siteId]);
  useEffect(() => { setRealtime(hud.status === "live"); }, [hud.status]);
  useEffect(() => () => setRealtime(false), []);
  useEffect(() => {
    if (who.status !== "live") { setPresence(siteId, null); return; }
    /* Every tab on the channel is someone watching the site (a renderer tab is a dashboard running the eye). */
    setPresence(siteId, { watchers: who.members.map(m => ({ role: m.role })), rendererOnline: who.renderers > 0 });
  }, [siteId, who.status, who.members, who.renderers]);
  useEffect(() => () => setPresence(siteId, null), [siteId]);
  return null;
}
