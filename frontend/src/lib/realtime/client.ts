"use client";

/* The Supabase Realtime connection behind useHudChannel and useSitePresence. One channel per site, shared by every
   hook on the page (reference counted), private (Realtime Authorization: the publishable key may only receive on
   `site:<siteId>:hud` and track presence there; only the backend can send).

   Budget rules, enforced here and in the backend (backend/src/supa_realtime.py):
   - Before joining, the module asks POST /api/supabase/viewers {siteId, viewerId}. If the answer is not
     `realtime: true` (Supabase not configured, viewer cap, or the day's message budget spent), nothing connects and the
     dashboard keeps polling. The heartbeat repeats while connected; a later "no" disconnects.
   - The tab hidden means disconnected: the channel is removed and the backend is told the viewer left, so a background
     tab costs nothing. Visible again means heartbeat first, then reconnect.
   - The only network the module makes without that heartbeat's "yes" is the heartbeat itself. */

import { createClient, type RealtimeChannel, type SupabaseClient } from "@supabase/supabase-js";
import type { HudEvent, HudMessage, PresenceMember, PresenceRole, RealtimeStatus } from "./types";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
const VIEWERS_ENDPOINT = "/api/supabase/viewers";
const DEFAULT_HEARTBEAT_MS = 10_000;

type HudListener = (events: HudEvent[]) => void;
type PresenceListener = (members: PresenceMember[]) => void;
type StatusListener = (status: RealtimeStatus, reason: string | null) => void;

interface Entry {
  siteId: string;
  refs: number;
  channel: RealtimeChannel | null;
  status: RealtimeStatus;
  reason: string | null;
  members: PresenceMember[];
  hud: Set<HudListener>;
  presence: Set<PresenceListener>;
  statusListeners: Set<StatusListener>;
  roles: Map<symbol, PresenceRole>;
  tracked: PresenceRole | null;
  timer: ReturnType<typeof setTimeout> | null;
  generation: number;
}

let client: SupabaseClient | null = null;
let budgetReason: string | null = null;
let visibilityBound = false;
const entries = new Map<string, Entry>();
const viewerId = `v-${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;

function envReady(): boolean {
  return Boolean(SUPABASE_URL && SUPABASE_KEY) && typeof window !== "undefined";
}

/** True when the env has the public Supabase URL and publishable key and the backend has not said "off" (budget). */
export function isRealtimeEnabled(): boolean {
  return envReady() && budgetReason === null;
}

/** Why Realtime is off, when it is (missing env, viewer cap, or the day's budget spent). */
export function realtimeDisabledReason(): string | null {
  if (!envReady()) return "NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY is not set";
  return budgetReason;
}

function getClient(): SupabaseClient {
  if (!client) {
    client = createClient(SUPABASE_URL, SUPABASE_KEY, {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      realtime: { params: { eventsPerSecond: 5 } },
    });
  }
  return client;
}

function setStatus(entry: Entry, status: RealtimeStatus, reason: string | null = null) {
  entry.status = status;
  entry.reason = reason;
  entry.statusListeners.forEach(listener => listener(status, reason));
}

function wantedRole(entry: Entry): PresenceRole | null {
  const roles = [...entry.roles.values()];
  if (!roles.length) return null;
  return roles.includes("renderer") ? "renderer" : "viewer";
}

async function heartbeat(entry: Entry): Promise<{ ok: boolean; everyMs: number; reason: string | null }> {
  try {
    const response = await fetch(VIEWERS_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ siteId: entry.siteId, viewerId, role: wantedRole(entry) ?? "viewer" }),
      cache: "no-store",
    });
    if (!response.ok) return { ok: false, everyMs: 30_000, reason: `viewer heartbeat answered ${response.status}` };
    const body = (await response.json()) as { realtime?: boolean; reason?: string | null; heartbeatSeconds?: number };
    const everyMs = Math.max(5_000, Math.min(60_000, (body.heartbeatSeconds ?? DEFAULT_HEARTBEAT_MS / 1000) * 1000));
    if (!body.realtime) return { ok: false, everyMs, reason: body.reason ?? "Realtime is off" };
    return { ok: true, everyMs, reason: null };
  } catch {
    return { ok: false, everyMs: 30_000, reason: "viewer heartbeat failed" };
  }
}

function leave(siteId: string) {
  try {
    const payload = JSON.stringify({ siteId, viewerId, leave: true });
    if (typeof navigator !== "undefined" && navigator.sendBeacon) {
      navigator.sendBeacon(VIEWERS_ENDPOINT, new Blob([payload], { type: "application/json" }));
    } else {
      void fetch(VIEWERS_ENDPOINT, { method: "POST", headers: { "Content-Type": "application/json" }, body: payload, keepalive: true });
    }
  } catch {
    /* leaving is best effort; the backend drops a viewer 30 s after its last heartbeat anyway */
  }
}

function membersOf(channel: RealtimeChannel): PresenceMember[] {
  const state = channel.presenceState() as Record<string, Array<{ role?: string; since?: string }>>;
  return Object.entries(state).flatMap(([key, metas]) =>
    metas.slice(0, 1).map(meta => ({ key, role: meta.role === "renderer" ? "renderer" : "viewer", since: meta.since ?? null } as PresenceMember)));
}

async function syncTrack(entry: Entry) {
  const channel = entry.channel;
  if (!channel || entry.status !== "live") return;
  const role = wantedRole(entry);
  if (role === entry.tracked) return;
  entry.tracked = role;
  try {
    if (role) await channel.track({ role, since: new Date().toISOString() });
    else await channel.untrack();
  } catch {
    /* presence is a nicety; the HUD works without it */
  }
}

function disconnect(entry: Entry, status: RealtimeStatus, reason: string | null) {
  entry.generation += 1;
  if (entry.timer) clearTimeout(entry.timer);
  entry.timer = null;
  const channel = entry.channel;
  entry.channel = null;
  entry.tracked = null;
  entry.members = [];
  entry.presence.forEach(listener => listener([]));
  if (channel) {
    void getClient().removeChannel(channel);
    leave(entry.siteId);
  }
  setStatus(entry, status, reason);
}

async function connect(entry: Entry) {
  const generation = ++entry.generation;
  setStatus(entry, "connecting");
  const beat = await heartbeat(entry);
  if (generation !== entry.generation) return;
  if (!beat.ok) {
    budgetReason = beat.reason;
    disconnect(entry, "off", beat.reason);
    retryLater(entry, beat.everyMs);
    return;
  }
  budgetReason = null;
  if (!entry.channel) {
    const supabase = getClient();
    await supabase.realtime.setAuth(); // the publishable key: anon, which the HUD policies let receive and track presence
    if (generation !== entry.generation) return;
    const channel = supabase.channel(`site:${entry.siteId}:hud`, {
      config: { private: true, broadcast: { self: false, ack: false }, presence: { key: viewerId } },
    });
    channel.on("broadcast", { event: "hud" }, message => {
      const payload = (message as { payload?: HudMessage }).payload;
      if (!payload || !Array.isArray(payload.events) || payload.siteId !== entry.siteId) return;
      entry.hud.forEach(listener => listener(payload.events));
    });
    channel.on("presence", { event: "sync" }, () => {
      entry.members = membersOf(channel);
      entry.presence.forEach(listener => listener(entry.members));
    });
    channel.subscribe(status => {
      if (generation !== entry.generation) return;
      if (status === "SUBSCRIBED") {
        setStatus(entry, "live");
        void syncTrack(entry);
      } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
        setStatus(entry, "error", status === "TIMED_OUT" ? "Realtime join timed out" : "Realtime refused the channel");
      } else if (status === "CLOSED" && entry.status !== "paused" && entry.status !== "off") {
        setStatus(entry, "off", "channel closed");
      }
    });
    entry.channel = channel;
  }
  const schedule = (everyMs: number) => {
    entry.timer = setTimeout(async () => {
      if (generation !== entry.generation) return;
      const next = await heartbeat(entry);
      if (generation !== entry.generation) return;
      if (!next.ok) {
        budgetReason = next.reason;
        disconnect(entry, "off", next.reason);
        retryLater(entry, next.everyMs);
        return;
      }
      schedule(next.everyMs);
    }, everyMs);
  };
  schedule(beat.everyMs);
}

/** While a hook is mounted and the backend says "off", ask again once a minute (one small request, no connection). */
function retryLater(entry: Entry, everyMs: number) {
  if (entry.refs <= 0) return;
  const generation = entry.generation;
  entry.timer = setTimeout(() => {
    if (generation === entry.generation && entry.refs > 0 && !entry.channel && document.visibilityState !== "hidden") void connect(entry);
  }, Math.max(everyMs, 60_000));
}

function bindVisibility() {
  if (visibilityBound || typeof document === "undefined") return;
  visibilityBound = true;
  document.addEventListener("visibilitychange", () => {
    entries.forEach(entry => {
      if (document.visibilityState === "hidden") {
        if (entry.status !== "off" || entry.channel) disconnect(entry, "paused", "tab hidden");
      } else if (entry.refs > 0 && !entry.channel) {
        void connect(entry);
      }
    });
  });
  window.addEventListener("pagehide", () => entries.forEach(entry => { if (entry.channel) leave(entry.siteId); }));
}

function acquire(siteId: string): Entry {
  let entry = entries.get(siteId);
  if (!entry) {
    entry = { siteId, refs: 0, channel: null, status: "off", reason: null, members: [], hud: new Set(), presence: new Set(), statusListeners: new Set(),
              roles: new Map(), tracked: null, timer: null, generation: 0 };
    entries.set(siteId, entry);
  }
  entry.refs += 1;
  if (!envReady()) {
    setStatus(entry, "off", realtimeDisabledReason());
  } else if (entry.refs === 1) {
    bindVisibility();
    if (document.visibilityState !== "hidden") void connect(entry); // the heartbeat inside decides (budget, viewer cap)
    else setStatus(entry, "paused", "tab hidden");
  }
  return entry;
}

function release(entry: Entry) {
  entry.refs = Math.max(0, entry.refs - 1);
  if (entry.refs === 0) {
    disconnect(entry, "off", null);
    entries.delete(entry.siteId);
  }
}

/** Subscribe to a site's HUD events; returns an unsubscribe function. A no-op when Realtime is off. */
export function subscribeHud(siteId: string, onEvents: HudListener, onStatus?: StatusListener): () => void {
  const entry = acquire(siteId);
  entry.hud.add(onEvents);
  if (onStatus) {
    entry.statusListeners.add(onStatus);
    onStatus(entry.status, entry.reason ?? (isRealtimeEnabled() ? null : realtimeDisabledReason()));
  }
  return () => {
    entry.hud.delete(onEvents);
    if (onStatus) entry.statusListeners.delete(onStatus);
    release(entry);
  };
}

/** Join a site's presence as a viewer or a renderer; returns an unsubscribe function. */
export function subscribePresence(siteId: string, role: PresenceRole, onMembers: PresenceListener, onStatus?: StatusListener): () => void {
  const entry = acquire(siteId);
  const token = Symbol(role);
  entry.roles.set(token, role);
  entry.presence.add(onMembers);
  onMembers(entry.members);
  if (onStatus) {
    entry.statusListeners.add(onStatus);
    onStatus(entry.status, entry.reason ?? (isRealtimeEnabled() ? null : realtimeDisabledReason()));
  }
  void syncTrack(entry);
  return () => {
    entry.roles.delete(token);
    entry.presence.delete(onMembers);
    if (onStatus) entry.statusListeners.delete(onStatus);
    void syncTrack(entry);
    release(entry);
  };
}
