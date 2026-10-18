/** Shared tool-registration types and annotation presets (server.ts owns the helper; factory.ts registers addendum-3 tools with it). */
import type { z } from 'zod';

export const READ_ONLY = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } as const;
export const LOCAL_WRITE = { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false } as const;
/** resolve with budget > 0 may dispatch a human through a messaging provider: not read-only, and it leaves the local system. */
export const DISPATCH_WRITE = { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true } as const;
/** start_mission / start_scenario: every call starts something new (not idempotent) and its agents may contact humans (open world). */
export const MISSION_WRITE = { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true } as const;
/** assign_issue: a local record that is safe to repeat (the same assignment twice is the same state). */
export const IDEMPOTENT_WRITE = { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false } as const;
export interface Annotations { readonly readOnlyHint: boolean; readonly destructiveHint: boolean; readonly idempotentHint: boolean; readonly openWorldHint: boolean }

/** The slice of mcp-use's RequestContext the Steward tools use. */
export interface RequestContextLike {
  signal?: AbortSignal;
  client?: { can?(capability: string): boolean; supportsViews?(): boolean; info?(): { name?: string; version?: string }; capabilities?(): Record<string, unknown> };
  inputResponses?: Record<string, unknown>;
  reportProgress?(progress: number, total?: number, message?: string): Promise<boolean>;
  sendLog?(level: 'debug' | 'info' | 'notice' | 'warning' | 'error', data: unknown, logger?: string): Promise<void>;
  request?: { header(name: string): string | undefined; raw?: { headers: Headers } };
}

export interface CallContext { requester: string; actor: string; ctx: RequestContextLike }

/** Return this from a tool callback to ask the client for input (2026-07-28 multi-round-trip `input_required`). */
export class InputRequired {
  constructor(readonly result: { resultType: 'input_required'; inputRequests?: Record<string, unknown>; requestState?: string }) {}
}
/** Return this to choose the text content block yourself (the structured payload still goes in structuredContent). */
export class WithText<T> {
  constructor(readonly data: T, readonly text: string) {}
}
export type ContentBlock = { type: 'text'; text: string } | { type: 'image'; data: string; mimeType: string };
/** Return this for image results (the agent eye): content blocks in order (images, then text); structuredContent stays the metadata. */
export class WithContent<T> {
  constructor(readonly data: T, readonly content: ContentBlock[]) {}
}
/** Approximate vision tokens for one 640×400 frame (width × height / 750). */
export const IMAGE_TOKENS = 341;

export interface ToolExtras { title?: string; view?: { name: string; description?: string; csp?: Record<string, string[]>; prefersBorder?: boolean } }

export type ToolFn = <I extends z.ZodType<Record<string, unknown>>, O extends z.ZodType<Record<string, unknown>>>(
  name: string, description: string, inputSchema: I, outputSchema: O,
  callback: (input: z.output<I>, call: CallContext) => Promise<z.output<O> | InputRequired | WithText<z.output<O>> | WithContent<z.output<O>>>,
  mutates?: boolean | Annotations, extras?: ToolExtras,
) => void;
