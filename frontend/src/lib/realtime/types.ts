/* Shapes of the live HUD events the backend broadcasts on the private channel `site:<siteId>:hud` (event "hud").
   Source of truth: backend/src/supa_realtime.py. Image bytes never travel over Realtime: eye frames carry a signed
   Storage URL (15 minutes) or, when Storage is off or over budget, the backend's local frame URL. */

export type HudEventType = "eye_frame" | "agent_action" | "conversation_line" | "issue_change";

export interface HudVisiblePin {
  assetTag: string;
  x: number | null;
  y: number | null;
  distance: number | null;
  occluded: boolean | null;
}

export interface EyeFrameEvent {
  type: "eye_frame";
  siteId: string;
  frameId: string;
  seq: number | null;
  actor: string | null;
  actorName: string | null;
  action: string | null;
  at: string | null;
  /** Signed Supabase Storage URL when `signed`, else the backend's local `/api/eye/frames/<id>.jpg`. */
  url: string | null;
  thumbUrl: string | null;
  signed: boolean;
  camera: { position?: number[]; target?: number[]; fov?: number } | null;
  visiblePins: HudVisiblePin[];
}

export interface AgentActionEvent {
  type: "agent_action";
  agentId: string | null;
  kind: string | null;
  tool: string | null;
  text: string | null;
  tokens: number | null;
  ok: boolean | null;
  at: string | null;
}

export interface ConversationLineEvent {
  type: "conversation_line";
  conversationId: string;
  kind: string | null;
  topic: string | null;
  speaker: string | null;
  text: string | null;
  at: string | null;
  siteIds: string[] | null;
}

export interface IssueChangeEvent {
  type: "issue_change";
  issueId: string;
  siteId: string | null;
  kind: string | null;
  severity: string | null;
  status: string | null;
  summary: string | null;
  assetTag: string | null;
  at: string | null;
}

export type HudEvent = EyeFrameEvent | AgentActionEvent | ConversationLineEvent | IssueChangeEvent;

/** One broadcast message: the backend coalesces a site's events to at most one message per second. */
export interface HudMessage {
  siteId: string;
  at: string;
  events: HudEvent[];
}

/** off: env or budget says no Realtime (keep polling). paused: tab hidden. */
export type RealtimeStatus = "off" | "connecting" | "live" | "paused" | "error";

export type PresenceRole = "viewer" | "renderer";

export interface PresenceMember {
  key: string;
  role: PresenceRole;
  since: string | null;
}
