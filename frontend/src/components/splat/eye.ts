/**
 * Agent eye protocol (REALITY-CONTRACT-4.md section 2), renderer side.
 *
 * - `POST {api}/api/eye/{site}/renderers {rendererId}` every 5 s (skipped while the tab is hidden, so a
 *   background tab goes stale and the backend picks another renderer);
 * - `GET {api}/api/eye/{site}/commands?rendererId=&since=` long-polls for the next command;
 * - `POST {api}/api/eye/{site}/frames {...}` returns each frame. An orbit posts one frame per stop with
 *   `index`, `count` and `final`.
 *
 * Any 404 or network failure flips the status to offline; both loops retry every 5 s.
 */
import type { CameraInfo, VisiblePin } from './engine';
import type { SplatSiteId, Vec3Tuple } from './types';

export interface SplatEyeConfig {
  siteId: SplatSiteId;
  rendererId: string;
  /** Origin of the backend API; defaults to the page origin (Next proxies /api to FastAPI). */
  apiBase?: string;
  /** Draw the HUD: acting agent, action, crosshair and visible tags. */
  showOverlay?: boolean;
  /** Jump instead of easing (headless renderers, where a frame can take seconds). */
  instant?: boolean;
  /** Frame size posted to the backend. Defaults to 640×400. */
  frameWidth?: number;
  frameHeight?: number;
}

export type EyeAction = 'look' | 'move' | 'turn' | 'go_to' | 'orbit' | 'mark';
export const EYE_ACTIONS: EyeAction[] = ['look', 'move', 'turn', 'go_to', 'orbit', 'mark'];

export interface EyeCommand {
  id: string;
  action: EyeAction;
  params: Record<string, unknown>;
  actor: string | null;
  actorName: string | null;
  seq: number | null;
  at: string | null;
  /** Pin the backend attached to the command, if any. */
  pin: Vec3Tuple | null;
}

export interface EyeFramePost {
  commandId: string;
  rendererId: string;
  action: EyeAction;
  actor: string | null;
  index: number;
  count: number;
  final: boolean;
  jpegBase64: string;
  width: number;
  height: number;
  camera: CameraInfo;
  visiblePins: VisiblePin[];
  assetTag?: string | null;
  mark?: { x: number; y: number; world: Vec3Tuple; hit: boolean; note: string | null };
  error?: string;
  renderMs: number;
  at: string;
}

export type EyeStatus = 'connecting' | 'online' | 'offline';

type Json = unknown;
const isObj = (v: Json): v is Record<string, Json> => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: Json) => (typeof v === 'string' && v ? v : null);

export function toVec3(v: Json): Vec3Tuple | null {
  if (isObj(v) && [v.x, v.y, v.z].every((n) => typeof n === 'number' && Number.isFinite(n))) return [v.x as number, v.y as number, v.z as number];
  if (Array.isArray(v) && v.length === 3 && v.every((n) => typeof n === 'number' && Number.isFinite(n))) return v as Vec3Tuple;
  return null;
}

function parseOne(c: Json): EyeCommand | null {
  if (!isObj(c)) return null;
  const id = str(c.id) ?? str(c.commandId) ?? (typeof c.id === 'number' ? String(c.id) : null);
  const action = str(c.action) as EyeAction | null;
  if (!id || !action) return null;
  const params: Record<string, unknown> = isObj(c.params) ? { ...c.params } : {};
  // tolerate flat commands: { action, assetTag, meters, ... }
  for (const k of ['direction', 'meters', 'yawDeg', 'pitchDeg', 'assetTag', 'frames', 'x', 'y', 'note', 'distance']) {
    if (params[k] === undefined && c[k] !== undefined) params[k] = c[k];
  }
  const actorObj = isObj(c.actor) ? c.actor : null;
  const actor = actorObj ? str(actorObj.id) : str(c.actor) ?? str(c.actorId) ?? str(c.issuedBy);
  const actorName = (actorObj ? str(actorObj.name) : null) ?? str(c.actorName) ?? str(c.issuedByName) ?? str(c.agentName) ?? actor;
  return {
    id,
    action,
    params,
    actor,
    actorName,
    seq: typeof c.seq === 'number' ? c.seq : null,
    at: str(c.at) ?? str(c.createdAt),
    pin: toVec3(c.pin) ?? toVec3(params.pin),
  };
}

export function parseCommands(json: Json): EyeCommand[] {
  if (!json) return [];
  let list: Json[] = [];
  if (Array.isArray(json)) list = json;
  else if (isObj(json)) {
    if ('command' in json) list = json.command ? [json.command] : [];
    else if (Array.isArray(json.commands)) list = json.commands;
    else if ('action' in json) list = [json];
  }
  return list.map(parseOne).filter((c): c is EyeCommand => !!c);
}

const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve) => {
  const t = window.setTimeout(resolve, ms);
  signal?.addEventListener('abort', () => { window.clearTimeout(t); resolve(); }, { once: true });
});

export interface EyeHandlers {
  onStatus(status: EyeStatus, detail: string | null): void;
  execute(command: EyeCommand): Promise<void>;
}

export class EyeClient {
  status: EyeStatus = 'connecting';
  executed = 0;
  private abort = new AbortController();
  private since: string | number = 0;
  private seen = new Set<string>();
  private base: string;

  constructor(private cfg: SplatEyeConfig, private handlers: EyeHandlers) {
    this.base = `${(cfg.apiBase ?? '').replace(/\/+$/, '')}/api/eye/${encodeURIComponent(cfg.siteId)}`;
  }

  start() {
    void this.heartbeatLoop();
    void this.pollLoop();
  }

  stop() { this.abort.abort(); }

  private setStatus(status: EyeStatus, detail: string | null = null) {
    if (this.status === status && status !== 'offline') return;
    this.status = status;
    this.handlers.onStatus(status, detail);
  }

  private get stopped() { return this.abort.signal.aborted; }

  private async heartbeatLoop() {
    while (!this.stopped) {
      if (typeof document !== 'undefined' && document.hidden) { await sleep(1000, this.abort.signal); continue; }
      try {
        const res = await fetch(`${this.base}/renderers`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ rendererId: this.cfg.rendererId, siteId: this.cfg.siteId, kind: this.cfg.rendererId.startsWith('headless') ? 'headless' : 'browser' }),
          signal: this.abort.signal,
        });
        if (res.ok) this.setStatus('online');
        else this.setStatus('offline', `renderers ${res.status}`);
      } catch (e) {
        if (this.stopped) return;
        this.setStatus('offline', e instanceof Error ? e.message : String(e));
      }
      await sleep(5000, this.abort.signal);
    }
  }

  private async pollLoop() {
    while (!this.stopped) {
      if (this.status !== 'online' || (typeof document !== 'undefined' && document.hidden)) { await sleep(this.status === 'offline' ? 5000 : 500, this.abort.signal); continue; }
      const ctl = new AbortController();
      const onAbort = () => ctl.abort();
      this.abort.signal.addEventListener('abort', onAbort, { once: true });
      const timer = window.setTimeout(() => ctl.abort(), 30000);
      let commands: EyeCommand[] = [];
      try {
        const q = new URLSearchParams({ rendererId: this.cfg.rendererId, since: String(this.since) });
        const res = await fetch(`${this.base}/commands?${q}`, { signal: ctl.signal, cache: 'no-store' });
        if (res.status === 404 || res.status >= 500) { this.setStatus('offline', `commands ${res.status}`); await sleep(5000, this.abort.signal); continue; }
        if (res.ok && res.status !== 204) {
          const text = await res.text();
          commands = text ? parseCommands(JSON.parse(text)) : [];
        }
      } catch (e) {
        if (this.stopped) return;
        // a long-poll that simply timed out is not an outage
        if (!(e instanceof DOMException && e.name === 'AbortError')) { this.setStatus('offline', e instanceof Error ? e.message : String(e)); await sleep(5000, this.abort.signal); }
        continue;
      } finally {
        window.clearTimeout(timer);
        this.abort.signal.removeEventListener('abort', onAbort);
      }
      for (const cmd of commands) {
        if (this.stopped) return;
        this.since = cmd.seq ?? cmd.id;
        if (this.seen.has(cmd.id)) continue;
        this.seen.add(cmd.id);
        if (this.seen.size > 500) this.seen = new Set([...this.seen].slice(-200));
        // the backend waits at most 20 s for a frame; anything much older has been answered already
        if (cmd.at && Date.now() - Date.parse(cmd.at) > 90_000) continue;
        try { await this.handlers.execute(cmd); this.executed++; } catch { /* the executor posts its own error frame */ }
      }
    }
  }

  async postFrame(frame: EyeFramePost): Promise<boolean> {
    for (let attempt = 0; attempt < 3 && !this.stopped; attempt++) {
      try {
        const res = await fetch(`${this.base}/frames`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(frame),
          signal: this.abort.signal,
        });
        if (res.ok) return true;
        if (res.status === 404 || res.status === 409 || res.status === 422) return false;
      } catch {
        if (this.stopped) return false;
      }
      await sleep(600 * (attempt + 1), this.abort.signal);
    }
    return false;
  }
}

export function describeCommand(cmd: EyeCommand): string {
  const p = cmd.params;
  const n = (v: unknown, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : d);
  switch (cmd.action) {
    case 'look': return 'look';
    case 'move': return `move ${String(p.direction ?? 'forward')} ${n(p.meters, 1).toFixed(1)} m`;
    case 'turn': return `turn yaw ${n(p.yawDeg).toFixed(0)}° pitch ${n(p.pitchDeg).toFixed(0)}°`;
    case 'go_to': return `go to ${String(p.assetTag ?? '')}`;
    case 'orbit': return `orbit ${String(p.assetTag ?? '')} · ${Math.round(n(p.frames, 8))} frames`;
    case 'mark': return `mark ${n(p.x).toFixed(2)}, ${n(p.y).toFixed(2)}${p.note ? ` · ${String(p.note)}` : ''}`;
    default: return String(cmd.action);
  }
}
