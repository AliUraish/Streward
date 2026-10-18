"use client";

/* One Human · Agent switch for the whole dashboard (the owner, Oct 18: "it should be one on top switch for agents"). The
   choice is kept on this device (localStorage `steward.mode`); `?mode=agent` or `?mode=human` in the URL wins once, on the
   page that carries it. Every page reads it with useMode() and draws its agent view in place of the human one. The
   store is module-level (useSyncExternalStore), so any component can read it without a provider. */
import { useSyncExternalStore } from "react";

export type Mode = "human" | "agent";
const KEY = "steward.mode";
const listeners = new Set<() => void>();
let mode: Mode | null = null;

function initial(): Mode {
  if (typeof window === "undefined") return "human";
  try { const q = new URLSearchParams(window.location.search).get("mode"); if (q === "agent" || q === "human") { window.localStorage.setItem(KEY, q); return q; } } catch { /* no URL */ }
  try { const s = window.localStorage.getItem(KEY); if (s === "agent" || s === "human") return s; } catch { /* storage blocked */ }
  return "human";
}
export function readMode(): Mode { if (mode === null) mode = initial(); return mode; }
export function setMode(next: Mode) {
  if (readMode() === next) return;
  mode = next;
  try { window.localStorage.setItem(KEY, next); } catch { /* storage blocked */ }
  /* A shared link says which view it shows: the URL's ?mode follows the switch without a navigation. */
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.has("mode") || next === "agent") { if (next === "agent") url.searchParams.set("mode", "agent"); else url.searchParams.delete("mode"); window.history.replaceState(window.history.state, "", url); }
  } catch { /* no history */ }
  listeners.forEach(f => f());
}
function subscribe(f: () => void) {
  listeners.add(f);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY && (e.newValue === "agent" || e.newValue === "human")) { mode = e.newValue; f(); } };
  window.addEventListener("storage", onStorage);
  return () => { listeners.delete(f); window.removeEventListener("storage", onStorage); };
}
/* The server render and the first client render agree on "human"; the stored choice follows right after hydration. */
export function useMode(): [Mode, (m: Mode) => void] {
  const m = useSyncExternalStore(subscribe, readMode, () => "human" as Mode);
  return [m, setMode];
}

/* Which site's 3-D scan is mounted on its environment page (the scan joins the realtime channel as a renderer). */
const scanListeners = new Set<() => void>();
let scanSite: string | null = null;
export function setScanSite(site: string | null) { if (scanSite !== site) { scanSite = site; scanListeners.forEach(f => f()); } }
export const useScanSite = () => useSyncExternalStore(f => { scanListeners.add(f); return () => { scanListeners.delete(f); }; }, () => scanSite, () => null);
