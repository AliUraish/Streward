"""Regulations (contract 4 §5): real government sources cached locally with attribution, explained in our own words.

The REGULATIONS stream owns `backend/seed/regulations/` (`regulations.json`, `obligations-suggested.json`, README) and
the cached PDFs in `backend/data/regulations/`; this module only reads them. A record is `{id, jurisdiction:
ENG-UK | VIC-AU | JP, instrument, provision, title, officialUrl, pdfPath (relative to backend/data), licence, retrievedAt,
summary, appliesTo (scenario ids and issue kinds)}` plus `siteIds`, `sourceType`, `pdfUrl`, `version`, `licenceUrl`,
`servePdf`, `pageHint` (1-based physical page, usable as `#page=N`) and `synthetic: false`.

Serving rule: `GET /api/regulations/{id}/file` streams the cached PDF only when `servePdf` is true (the three UK
Open Government Licence files), with the attribution "Contains public sector information licensed under the Open
Government Licence v3.0."; when `servePdf` is false (Victorian legislation, the VBA practice note: personal use or
no copying) it answers 302 to the record's `pdfUrl` and never streams the local copy.

Obligations carry `regulationIds`; compliance issues cite their obligation's regulations, or the records whose
`appliesTo` names the issue's kind (or scenario) at the issue's site. Ids that are not (yet) in the file are tolerated:
the obligation view lists them as `unresolvedRegulationIds` with `regulationPending: true` (contract 5: the Japanese
records for Tomioka arrive from the regulations stream). A served PDF carries its record's own attribution (`attribution`,
the OGL line for the UK files, else the `Attribution: ...` sentence of the record's licence text, which is how the JP
records end: the e-Gov 出典 line plus "Source: e-Gov Law Search (Digital Agency, Japan), PDL1.0."); header values are
kept ASCII and the full text is also sent percent-encoded.

Binding and comparison records: a record with `binding: false` (the regulations stream's US-CA records) is a
comparison, never law for any of our sites; `comparisonFor` (mirrored in `siteIds`) names the sites it is compared
with. A record without `binding` is binding. `GET /api/regulations?siteId=` lists binding records; `include=comparison`
adds the comparison records. Issues and obligations cite only binding records in `regulationIds` (the reason something
is a breach) and expose `comparisonRegulationIds` for the comparison records about the same problem (matching
`appliesTo`, or a comparison record's `comparesTo` / `equivalentOf` / `comparableTo` ids).

Demo rule pack, not legal advice.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .env import env
from .errors import RealityError
from .sites import SITE_JURISDICTION

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_FILE = BACKEND / "seed" / "regulations" / "regulations.json"
SUGGESTED_FILE = BACKEND / "seed" / "regulations" / "obligations-suggested.json"
PDF_ROOT = BACKEND / "data"
OGL_ATTRIBUTION = "Contains public sector information licensed under the Open Government Licence v3.0."
DISCLAIMER = "Demo rule pack: our own plain-language summaries with links to the official text. Not legal advice."
COMPARISON_NOTE = "Comparison only: not binding at this site and never the reason an issue is a breach."
LINK_FIELDS = ("comparesTo", "equivalentOf", "comparableTo", "comparisonOf")
_ATTRIBUTION_RE = re.compile(r"Attribution:\s*(.+?)(?:\s+The summaries\b.*)?$", re.S)


def is_binding(record: dict) -> bool:
    """A record is binding unless it says `binding: false` (comparison records such as the US-CA set)."""
    return record.get("binding") is not False


class RegulationService:
    def __init__(self, service):
        self.service = service
        self._cache: dict[str, tuple[float, object]] = {}

    @property
    def path(self) -> Path:
        return Path(env("STEWARD_REGULATIONS_FILE", "") or DEFAULT_FILE)

    @property
    def suggested_path(self) -> Path:
        return Path(env("STEWARD_REGULATIONS_SUGGESTED_FILE", "") or (self.path.parent / SUGGESTED_FILE.name))

    def _read(self, path: Path):
        if not path.is_file():
            return None
        mtime = path.stat().st_mtime
        cached = self._cache.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            payload = json.loads(path.read_text())
        except (ValueError, OSError):
            return None
        self._cache[str(path)] = (mtime, payload)
        return payload

    def records(self) -> list[dict]:
        payload = self._read(self.path)
        items = payload.get("records") if isinstance(payload, dict) else payload
        return [r for r in (items or []) if isinstance(r, dict) and r.get("id") and r.get("jurisdiction")]

    def by_id(self) -> dict[str, dict]:
        return {r["id"]: r for r in self.records()}

    def suggested(self) -> list[dict]:
        payload = self._read(self.suggested_path)
        items = payload.get("records") if isinstance(payload, dict) else payload
        return [r for r in (items or []) if isinstance(r, dict)]

    def suggestion_for(self, obligation_id: str) -> dict | None:
        """The REGULATIONS stream's suggested obligation that covers one of our seed obligations (why, closing evidence)."""
        return next((s for s in self.suggested() if obligation_id in (s.get("relatedSeedObligationIds") or [])), None)

    @staticmethod
    def sites_of(record: dict) -> set[str]:
        """Sites where a record is binding law (empty for comparison records)."""
        if not is_binding(record):
            return set()
        sites = set(record.get("siteIds") or [])
        if not sites:
            sites = {site for site, jurisdiction in SITE_JURISDICTION.items() if jurisdiction == record.get("jurisdiction")}
        return sites

    @staticmethod
    def comparison_sites_of(record: dict) -> set[str]:
        """Sites a comparison record is compared with (`comparisonFor`, mirrored in `siteIds`)."""
        if is_binding(record):
            return set()
        return set(record.get("comparisonFor") or record.get("siteIds") or [])

    def pdf_file(self, record: dict) -> Path | None:
        raw = str(record.get("pdfPath") or "")
        if not raw:
            return None
        candidate = Path(raw)
        options = [candidate] if candidate.is_absolute() else [PDF_ROOT / candidate, self.path.parent / candidate, PDF_ROOT / "regulations" / candidate.name]
        allowed = [(PDF_ROOT / "regulations").resolve(), self.path.parent.resolve()]
        for option in options:
            try:
                resolved = option.resolve()
            except OSError:
                continue
            if resolved.is_file() and resolved.suffix.lower() == ".pdf" and any(str(resolved).startswith(str(root)) for root in allowed):
                return resolved
        return None

    def file_target(self, record: dict) -> tuple[str, Path | str]:
        """('stream', path) when servePdf is true and the cached PDF exists; ('redirect', pdfUrl) otherwise."""
        if record.get("servePdf") is True:
            path = self.pdf_file(record)
            if path:
                return "stream", path
        url = record.get("pdfUrl") or record.get("officialUrl")
        if url:
            return "redirect", url
        raise RealityError("No PDF for this regulation.", "NOT_FOUND", "Open the official source page instead.", 404)

    @staticmethod
    def attribution(record: dict) -> str:
        """The attribution to show with a served copy: the record's own `attribution`; the OGL line for the UK files;
        else the `Attribution: ...` sentence the record's licence text ends with (the JP records' e-Gov 出典 line and
        PDL1.0 source line); else a generic source line."""
        own = str(record.get("attribution") or "").strip()
        if own:
            return own
        licence = str(record.get("licence") or "")
        if record.get("jurisdiction") == "ENG-UK" or ("Open Government Licence" in licence and "Attribution:" not in licence):
            return OGL_ATTRIBUTION
        match = _ATTRIBUTION_RE.search(licence)
        if match:
            return " ".join(match.group(1).split())[:600]
        return f"Source: {record.get('instrument') or record.get('id')}; {licence.strip()[:300] or 'see the official site for terms'}"

    @staticmethod
    def attribution_ascii(text: str) -> str:
        """An HTTP-header-safe attribution: the English `Source: ...` sentence when there is one, else the ASCII part."""
        if "Source:" in text:
            text = text[text.index("Source:"):]
        return " ".join(text.encode("ascii", "ignore").decode().split())[:500] or "See the official source for terms."

    def view(self, record: dict) -> dict:
        page = record.get("pageHint")
        serve = record.get("servePdf") is True
        file_url = f"/api/regulations/{record['id']}/file"
        read_url = (file_url if serve else (record.get("pdfUrl") or record.get("officialUrl"))) or None
        return dict(id=record["id"], jurisdiction=record["jurisdiction"], siteIds=sorted(self.sites_of(record)), sourceType=record.get("sourceType", "legislation"),
                    instrument=record.get("instrument"), provision=record.get("provision"), title=record.get("title"), officialUrl=record.get("officialUrl"),
                    pdfUrl=record.get("pdfUrl"), pageHint=page, readUrl=f"{read_url}#page={page}" if read_url and page else read_url,
                    licence=record.get("licence"), licenceUrl=record.get("licenceUrl"), version=record.get("version"), retrievedAt=record.get("retrievedAt"),
                    summary=record.get("summary"), appliesTo=record.get("appliesTo"), servePdf=serve, fileUrl=file_url,
                    attribution=self.attribution(record) if serve else "Official copy at the source; the licence does not allow redistribution.",
                    cached=self.pdf_file(record) is not None, synthetic=bool(record.get("synthetic", False)), disclaimer=DISCLAIMER,
                    binding=is_binding(record), comparisonFor=sorted(self.comparison_sites_of(record)) or None,
                    **({} if is_binding(record) else dict(comparisonNote=COMPARISON_NOTE)))

    def list(self, site_id: str | None = None, include: str | None = None) -> list[dict]:
        """Binding records (for one site when `site_id` is given); `include="comparison"` adds the comparison records."""
        records = self.records()
        with_comparison = "comparison" in {part.strip() for part in (include or "").split(",")}
        if site_id:
            self.service.require_property(site_id)
            records = [r for r in records if site_id in self.sites_of(r) or (with_comparison and site_id in self.comparison_sites_of(r))]
        else:
            records = [r for r in records if is_binding(r) or with_comparison]
        return [self.view(r) for r in records]

    def get(self, regulation_id: str) -> dict:
        record = self.by_id().get(regulation_id)
        if not record:
            raise RealityError("Regulation not found.", "NOT_FOUND", "List regulations with GET /api/regulations?siteId=.", 404)
        return record

    # ---- citations -------------------------------------------------------------------------------------

    def for_obligation(self, obligation: dict) -> list[str]:
        """The obligation's cited ids that exist and are binding (a comparison id is never a reason)."""
        known = self.by_id()
        return [rid for rid in (obligation.get("regulationIds") or []) if rid in known and is_binding(known[rid])]

    def for_issue(self, issue: dict) -> list[str]:
        site = issue.get("siteId")
        if issue.get("obligationId"):
            obligation = self.service.store.get("obligation", issue["obligationId"], site)
            ids = self.for_obligation(obligation) if obligation else []
            if ids:
                return ids
        keys = {issue.get("kind"), issue.get("scenarioId")} - {None}
        return [r["id"] for r in self.records() if site in self.sites_of(r) and keys & set(r.get("appliesTo") or [])]

    def comparisons(self, site: str | None, keys: set, binding_ids: list[str]) -> list[str]:
        """Comparison records about the same problem at `site`: their `appliesTo` names the issue kind or scenario, or
        they link to one of the binding ids. Shown beside the reason, never as it."""
        cited = set(binding_ids)
        out = []
        for record in self.records():
            if is_binding(record) or (site and site not in self.comparison_sites_of(record)):
                continue
            linked = {str(v) for field in LINK_FIELDS for v in (record.get(field) or [])}
            if keys & set(record.get("appliesTo") or []) or linked & cited:
                out.append(record["id"])
        return out

    def comparison_for_issue(self, issue: dict, binding_ids: list[str] | None = None) -> list[str]:
        keys = {issue.get("kind"), issue.get("scenarioId")} - {None}
        return self.comparisons(issue.get("siteId"), keys, binding_ids if binding_ids is not None else self.for_issue(issue))

    def comparison_for_obligation(self, obligation: dict) -> list[str]:
        known = self.by_id()
        listed = [rid for rid in (obligation.get("regulationIds") or []) if rid in known and not is_binding(known[rid])]
        suggestion = self.suggestion_for(obligation["id"]) or {}
        keys = set(suggestion.get("issueKinds") or []) | ({suggestion["scenarioId"]} if suggestion.get("scenarioId") else set()) | (
            {obligation["scenarioId"]} if obligation.get("scenarioId") else set())
        found = self.comparisons(obligation.get("siteId"), keys, self.for_obligation(obligation))
        return list(dict.fromkeys(listed + found))

    def why(self, regulation_ids: list[str]) -> list[dict]:
        """Why an issue is a problem: binding records only (a comparison id passed in is skipped)."""
        known = self.by_id()
        out = []
        for rid in regulation_ids:
            record = known.get(rid)
            if record and is_binding(record):
                view = self.view(record)
                out.append(dict(regulationId=rid, instrument=view["instrument"], provision=view["provision"], title=view["title"], summary=view["summary"],
                                officialUrl=view["officialUrl"], readUrl=view["readUrl"], fileUrl=view["fileUrl"], servePdf=view["servePdf"],
                                licence=view["licence"], pageHint=view["pageHint"]))
        return out

    def reason_text(self, regulation_ids: list[str], fallback: str) -> str:
        why = self.why(regulation_ids)
        if not why:
            return fallback
        first = why[0]
        return f"{first.get('instrument')}, {first.get('provision')}: {(first.get('summary') or '').strip()[:260]}".strip()
