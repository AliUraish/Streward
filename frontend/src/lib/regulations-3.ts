/* The regulations rule pack (backend/seed/regulations/regulations.json, real records with our own summaries), read at
   build time so the compliance pages can cite them before GET /api/regulations answers. Display rules for licensing,
   the same for every jurisdiction: servePdf true may be embedded from GET /api/regulations/{id}/file with the record's
   attribution (England: the OGL line); servePdf false (Victorian legislation, the VBA practice note, and any Japanese
   record whose terms do not allow serving a copy) is never embedded, only linked, with the licence note. */
import pack from "../../../backend/seed/regulations/regulations.json";
import type { Regulation } from "./types-3";

export const REGULATIONS_PACK = pack as unknown as Regulation[];
export const OGL_ATTRIBUTION = "Contains public sector information licensed under the Open Government Licence v3.0.";
export const isJapan = (j: string | null | undefined) => j === "JP" || Boolean(j?.startsWith("JP-"));
export const jurisdictionName = (j: string | null | undefined) => j === "ENG-UK" ? "England (ENG-UK)" : j === "VIC-AU" ? "Victoria, Australia (VIC-AU)" : isJapan(j) ? "Japan (JP)" : isCalifornia(j) ? "California, United States (US-CA)" : j ?? "";
export function isCalifornia(j: string | null | undefined) { return j === "US-CA" || Boolean(j?.startsWith("US-CA")); }
/* A comparison record: California's rule shown beside the binding one, never as the law of the site. */
export const isComparison = (r: Regulation) => r.comparison === true || r.binding === false || isCalifornia(r.jurisdiction);
export const COMPARISON_NOTE = "comparison, not binding here";
/* Each site's law, explicitly: Myer cites Victoria, Bristol England, Tomioka Japan. */
const SITE_JURISDICTION: Record<string, string> = { "myer-plant": "VIC-AU", "bristol-pumps": "ENG-UK", "tomioka-mill": "JP" };
export const siteJurisdiction = (siteId: string) => SITE_JURISDICTION[siteId] ?? "";
/* The law that binds the site; comparison records never count. */
export const regsForSite = (siteId: string, list: Regulation[] = REGULATIONS_PACK) => list.filter(r => !isComparison(r) && (r.siteIds?.length ? r.siteIds.includes(siteId) : siteJurisdiction(siteId) === "JP" ? isJapan(r.jurisdiction) : r.jurisdiction === siteJurisdiction(siteId)));
/* California's records for the "If this site were in California" comparison: every site, unless a record names its sites. */
export const comparisonRegsForSite = (siteId: string, list: Regulation[] = REGULATIONS_PACK) => list.filter(r => isComparison(r) && (r.comparisonFor?.length ? r.comparisonFor.includes(siteId) : r.siteIds?.length ? r.siteIds.includes(siteId) : true));
/* The comparison records for an issue: its own comparisonRegulationIds, else those that apply to its kind or scenario. */
export function comparisonForIssue(issue: { kind: string; scenarioId?: string | null; comparisonRegulationIds?: string[] | null }, comparisons: Regulation[]): Regulation[] {
  if (issue.comparisonRegulationIds?.length) return issue.comparisonRegulationIds.map(id => comparisons.find(r => r.id === id)).filter((r): r is Regulation => Boolean(r));
  const keys = [issue.kind, issue.scenarioId].filter(Boolean) as string[];
  return comparisons.filter(r => (Array.isArray(r.appliesTo) ? r.appliesTo : [r.appliesTo ?? ""]).some(a => keys.includes(a)));
}
export function hostOf(url: string | null | undefined) { try { return url ? new URL(url).host.replace(/^www\./, "") : ""; } catch { return ""; } }
/* The licence note under a record that is linked, not embedded. A Japanese record carries its site's terms verbatim in
   `licence`; that text is the note. */
export function linkedNote(r: Regulation): string {
  const host = hostOf(sourceUrl(r));
  if (host.endsWith("legislation.vic.gov.au")) return "Victorian legislation, personal use only; opened from legislation.vic.gov.au";
  if (isJapan(r.jurisdiction) && r.licence) return `${r.licence.trim().replace(/[.。\s]+$/, "")}. Opened from ${host || "the official site"}`;
  if (r.sourceType === "guidance") return `Regulator guidance, not law, and not to be copied without consent; opened from ${host || "the publisher's site"}`;
  return `Not ours to redistribute; opened from ${host || "the official site"}`;
}
/* The attribution under an embedded copy: the OGL line for England; for any other record its own attribution, the part
   of its licence text after "Attribution:" (Japan: the 出典 line e-Gov's terms and PDL1.0 ask for, the source in
   English and the note that the summaries are ours), else the whole licence text. Never the OGL line for Japan. */
export function embedAttribution(r: Regulation): string {
  if (r.jurisdiction === "ENG-UK") return OGL_ATTRIBUTION;
  const text = r.licence?.trim() ?? "";
  const m = text.match(/Attribution:\s*([\s\S]+)$/);
  if (m) return m[1].trim();
  if (/open government licence/i.test(text)) return OGL_ATTRIBUTION;
  return text || `Served under the terms of ${hostOf(r.officialUrl) || "the official site"}.`;
}
/* Where "Open the official source" goes: the official PDF when there is one, else the official page. */
export const sourceUrl = (r: Regulation) => r.pdfUrl ?? r.officialUrl ?? null;
export const isPdfUrl = (url: string | null | undefined) => Boolean(url && /\.pdf($|[?#])|\/data\.pdf/i.test(url));
/* The English translation of a Japanese record, when it names one. */
export const translationOf = (r: Regulation) => r.translationUrl ?? r.englishUrl ?? null;
export const atPage = (url: string, page: number | null | undefined) => page ? `${url.split("#")[0]}#page=${page}` : url;
/* Regulations that explain an issue: its own ids, else the pack's records that apply to its kind or scenario. */
export function regsForIssue(issue: { kind: string; scenarioId?: string | null; regulationIds?: string[] | null; regulationId?: string | null }, siteRegs: Regulation[]): Regulation[] {
  const ids = [...(issue.regulationIds ?? []), ...(issue.regulationId ? [issue.regulationId] : [])];
  if (ids.length) return ids.map(id => siteRegs.find(r => r.id === id)).filter((r): r is Regulation => Boolean(r));
  const keys = [issue.kind, issue.scenarioId].filter(Boolean) as string[];
  return siteRegs.filter(r => (Array.isArray(r.appliesTo) ? r.appliesTo : [r.appliesTo ?? ""]).some(a => keys.includes(a)));
}
