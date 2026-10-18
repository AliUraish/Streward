"use client";

import { useEffect, useState } from "react";
import { subscribeHud, subscribePresence } from "./client";
import type { HudEvent, PresenceMember, PresenceRole, RealtimeStatus } from "./types";

export interface HudChannel {
  /** Newest last, at most `limit` (default 60). Empty while Realtime is off: keep polling then. */
  events: HudEvent[];
  status: RealtimeStatus;
  /** Why the channel is off or paused (missing env, budget spent, tab hidden), if it is. */
  reason: string | null;
  lastAt: string | null;
}

/** Live HUD events for one site (eye_frame, agent_action, conversation_line, issue_change) over Supabase Realtime.
 *  Falls back to nothing when env or the backend's budget says off; disconnects while the tab is hidden. */
export function useHudChannel(siteId: string | null | undefined, options: { limit?: number } = {}): HudChannel {
  const limit = Math.max(1, Math.min(500, options.limit ?? 60));
  const [state, setState] = useState<HudChannel>({ events: [], status: "off", reason: null, lastAt: null });
  useEffect(() => {
    if (!siteId) return;
    setState({ events: [], status: "off", reason: null, lastAt: null });
    return subscribeHud(
      siteId,
      events => setState(previous => ({ ...previous, events: [...previous.events, ...events].slice(-limit), lastAt: new Date().toISOString() })),
      (status, reason) => setState(previous => ({ ...previous, status, reason })),
    );
  }, [siteId, limit]);
  return state;
}

export interface SitePresence {
  members: PresenceMember[];
  viewers: number;
  renderers: number;
  status: RealtimeStatus;
  reason: string | null;
}

/** Presence on the same channel: track this tab as a viewer or a renderer and see who else is watching. */
export function useSitePresence(siteId: string | null | undefined, role: PresenceRole = "viewer"): SitePresence {
  const [members, setMembers] = useState<PresenceMember[]>([]);
  const [status, setStatus] = useState<{ status: RealtimeStatus; reason: string | null }>({ status: "off", reason: null });
  useEffect(() => {
    if (!siteId) return;
    return subscribePresence(siteId, role, setMembers, (next, reason) => setStatus({ status: next, reason }));
  }, [siteId, role]);
  return {
    members,
    viewers: members.filter(member => member.role === "viewer").length,
    renderers: members.filter(member => member.role === "renderer").length,
    status: status.status,
    reason: status.reason,
  };
}
