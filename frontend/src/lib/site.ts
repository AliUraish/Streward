/* Site identity: the three sites of REALITY-CONTRACT-2.md, with the legacy IDs an older backend may still report.
   The UI always speaks the new IDs; requests are routed to whichever ID the backend actually lists. */
import type { Environment, SiteId, SiteProperty } from "./types-2";

export const DEMO_SITE: SiteId = "harbor-works";
export const SITES: { id: SiteId; name: string; prefix: string; legacyId: string; environment: Environment }[] = [
  { id: "harbor-works", name: "Harbor Works", prefix: "HW", legacyId: "harbor", environment: { kind: "fixture", credit: "Steward fixture twin from shared/scene.json", captureNote: "Three.js twin built from the site register; not a capture." } },
  { id: "myer-plant", name: "Myer Plant Room", prefix: "MY", legacyId: "cedar", environment: { kind: "splat", splatId: "66b655d3", embedUrl: "https://superspl.at/s?id=66b655d3", thumbnailUrl: "https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/66b655d3/v1/xl.webp", credit: "Capture hosted on SuperSplat (superspl.at/s?id=66b655d3), credited to its author there", captureNote: "Scene rendered from a third-party capture hosted on SuperSplat; shown here as the site environment." } },
  { id: "bristol-pumps", name: "Bristol Dock Machine Room", prefix: "BR", legacyId: "juniper", environment: { kind: "splat", splatId: "8a8ce192", embedUrl: "https://superspl.at/s?id=8a8ce192", thumbnailUrl: "https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/8a8ce192/v1/xl.webp", credit: "Capture hosted on SuperSplat (superspl.at/s?id=8a8ce192), credited to its author there", captureNote: "Scene rendered from a third-party capture hosted on SuperSplat; shown here as the site environment." } },
];
export const SITE_IDS = SITES.map(s => s.id);
const byLegacy = new Map(SITES.map(s => [s.legacyId, s]));
const byId = new Map(SITES.map(s => [s.id, s]));

export const isSiteId = (v: string | null | undefined): v is SiteId => Boolean(v && byId.has(v as SiteId));
/* Normalise anything the backend or the URL hands us to a new site ID. */
export function toSiteId(v: string | null | undefined): SiteId { if (!v) return DEMO_SITE; if (byId.has(v as SiteId)) return v as SiteId; return byLegacy.get(v)?.id ?? DEMO_SITE; }
export function siteName(id: string) { return byId.get(toSiteId(id))?.name ?? id; }
export function sitePrefix(id: string) { return byId.get(toSiteId(id))?.prefix ?? id.slice(0, 2).toUpperCase(); }

/* The ID to put in request paths: the new ID when the backend lists it, else the legacy one it still answers to. */
export function requestId(id: SiteId, listed: { id: string }[]): string {
  if (!listed.length || listed.some(p => p.id === id)) return id;
  const legacy = byId.get(id)?.legacyId;
  return legacy && listed.some(p => p.id === legacy) ? legacy : id;
}
/* True when the backend still answers with the old residential seed (no environment field, legacy IDs). */
export function backendIsOld(listed: SiteProperty[]) { return listed.length > 0 && !listed.some(p => p.environment && isSiteId(p.id)); }

/* Merge what the backend says with the hardcoded three, so the switcher and the environment always resolve. */
export function siteList(listed: SiteProperty[]): (SiteProperty & { id: SiteId; environment: Environment })[] {
  return SITES.map(s => {
    const fromApi = listed.find(p => p.id === s.id) ?? listed.find(p => p.id === s.legacyId);
    const env = (fromApi?.environment && isSiteId(fromApi.id)) ? fromApi.environment : s.environment;
    return { ...(fromApi ?? { address: "", jurisdiction: "", phase: "", readiness: 0, componentCount: 0, openIssues: 0, updatedAt: "" }), id: s.id, name: isSiteId(fromApi?.id) && fromApi?.name ? fromApi.name : s.name, environment: env };
  });
}
export function environmentOf(id: string, listed: SiteProperty[]): Environment { return siteList(listed).find(s => s.id === toSiteId(id))!.environment; }
