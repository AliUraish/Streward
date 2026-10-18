/* Live HUD over Supabase Realtime (Broadcast + Presence on the private channel `site:<siteId>:hud`).

   import { isRealtimeEnabled, useHudChannel, useSitePresence } from "@/lib/realtime";

   const hud = useHudChannel("myer-plant");          // { events, status, reason, lastAt }
   const who = useSitePresence("myer-plant", "viewer"); // { members, viewers, renderers, status }

   - Needs NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY (the publishable key; public by design). Without
     them, or when the backend's budget guard says no (POST /api/supabase/viewers), hooks stay `off` with no events and
     no connection: keep the existing polling as the source of truth and treat events as a faster nudge.
   - At most one message per second per site arrives (the backend coalesces), each carrying several events.
   - Eye frames arrive as signed Storage URLs (15 minutes) or local frame URLs, never image bytes.
   - The tab hidden disconnects; visible again reconnects after a heartbeat. */
export { isRealtimeEnabled, realtimeDisabledReason, subscribeHud, subscribePresence } from "./client";
export { useHudChannel, useSitePresence } from "./hooks";
export type { HudChannel, SitePresence } from "./hooks";
export type {
  AgentActionEvent, ConversationLineEvent, EyeFrameEvent, HudEvent, HudEventType, HudMessage, HudVisiblePin, IssueChangeEvent,
  PresenceMember, PresenceRole, RealtimeStatus,
} from "./types";
